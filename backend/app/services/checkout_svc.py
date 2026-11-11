"""Shared logic between the two checkout paths (wallet, synchronous; and
ShurjoPay gateway, completed later from the payment callback) so
provisioning behavior can't drift between them.
"""
import asyncio
import re
import uuid
import json
import secrets
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus, ESIMProfile, ESIMStatus
from app.models.catalog import Product
from app.models.commission_tier import CommissionTier
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.services.ledger_svc import LedgerService
from app.services import agent_svc, referral_svc
from app.services.vivape_adapter import VivaPeAdapter
from app.services.esimaccess_adapter import ESIMAccessAdapter, ESIMAccessError, decimal_to_scaled
from app.services.audit_svc import AuditService
from app.core.logging import get_logger

logger = get_logger(__name__)

# How long to keep asking the supplier for an eSIM inside the purchase's own
# background task before handing the order to recover_stuck_orders. The
# customer is never waiting on this: checkout already returned, and the
# browser is polling the order, so a short wait here just means the QR is
# ready on the first poll for the common case.
_ESIM_READY_POLL_DELAYS = (0, 2, 3, 5, 5, 5)


class EsimNotReadyYet(Exception):
    """The supplier took the money and has not produced the eSIM yet.

    Explicitly NOT a failure: WorldMove provisions asynchronously and
    reports "Transaction Pending" with a null iccid for the first seconds
    or minutes. Treating that as a failure refunded the customer and
    abandoned an eSIM we had already paid for (production, 28 Oct 2026:
    7 eSIMs bought and thrown away, one customer retrying five times and
    buying five of them)."""

RESELLER_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT}


def new_share_token() -> str:
    """The token in a customer's public tracking link. 32 hex characters =
    128 bits, so the links cannot be guessed or walked the way VivaPe's
    sequential status ids can."""
    return secrets.token_hex(16)


def _password_from_phone(phone: str | None) -> tuple[str, bool]:
    """The customer's phone number as their first password, so the merchant
    standing in front of them can say how to sign in. Returns the password
    and whether it came from the phone.

    Falls back to a random one when there is no usable phone: a 3-digit
    "password" would be worse than making them read an email.
    """
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 6:
        return digits, True
    # Unambiguous alphabet - these get read aloud and copied by hand, and
    # a password nobody can transcribe is a support call.
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8)), False


async def resolve_beneficiary(
    db: AsyncSession,
    current_user: User,
    is_buy_for_user: bool,
    auto_create_user: bool,
    beneficiary_username: str | None,
    beneficiary_email: str | None,
    beneficiary_phone: str | None = None,
) -> tuple[str, dict | None]:
    """Who the eSIM belongs to, and the credentials if an account was made.

    An email given here is used as the customer's real address. The old
    version discarded it whenever auto_create_user was set and invented
    user_<random>@customer.esim.local instead, so the delivery email went
    to a domain that does not exist, the order showed a meaningless name,
    and the customer could never sign in to see what they had paid for.

    Returns (beneficiary_id, new_account) where new_account is None unless
    an account was created, in which case the caller emails the customer
    their credentials.
    """
    if not is_buy_for_user:
        return current_user.id, None

    email = (beneficiary_email or "").strip().lower() or None
    username = (beneficiary_username or "").strip() or None

    if email or username:
        # Look for an existing account BEFORE creating anything: a repeat
        # customer must get the eSIM on the account they already have,
        # rather than a second account they do not know about.
        matches = []
        if email:
            matches.append(func.lower(User.email) == email)
        if username:
            matches.append(User.username == username)
        target = (await db.execute(select(User).where(or_(*matches)))).scalars().first()
        if target:
            return target.id, None

        if not auto_create_user:
            raise ValueError("Beneficiary user account not found")
        if not email:
            raise ValueError("An email address is required to create a customer account")

        password, from_phone = _password_from_phone(beneficiary_phone)
        from app.api.v1.auth import _unique_username

        new_user = User(
            email=email,
            username=await _unique_username(db, email),
            hashed_password=get_password_hash(password),
            phone=(beneficiary_phone or "").strip() or None,
            role=UserRole.USER,
            # The phone is a way in, not a password they chose.
            must_change_password=True,
        )
        db.add(new_user)
        await db.flush()
        await LedgerService.ensure_wallets_for_user(db, new_user.id, new_user.role)
        return new_user.id, {
            "email": email,
            "username": new_user.username,
            "password": password,
            "password_is_phone": from_phone,
        }

    if auto_create_user:
        # No identity given at all - the Partner API sells to end customers
        # it never names, and their own reference ties the order back. A
        # placeholder is right here and wrong anywhere an email was typed.
        auto_username = f"user_{uuid.uuid4().hex[:8]}"
        new_user = User(
            email=f"{auto_username}@customer.esim.local",
            username=auto_username,
            hashed_password=get_password_hash(uuid.uuid4().hex),
            role=UserRole.USER,
        )
        db.add(new_user)
        await db.flush()
        await LedgerService.ensure_wallets_for_user(db, new_user.id, new_user.role)
        return new_user.id, None

    return current_user.id, None


def _parse_lpa_string(lpa: str) -> tuple[str | None, str | None]:
    """A standard activation code is LPA:1$<smdp>$<matching_id>. Real
    values live inside it; this is the one place that decomposes it,
    shared by every supplier branch that receives a ready-made LPA string
    rather than separate smdp/matching_id fields, so the two can't quietly
    drift apart."""
    parts = lpa.split("$")
    if len(parts) == 3 and parts[0].upper().startswith("LPA:"):
        return parts[1] or None, parts[2] or None
    return None, None


def _extract_esimaccess_details(entry: dict) -> dict | None:
    """One entry from eSIM Access's esim/query obj.esimList[]. `ac` is the
    full LPA string - confirmed live (2026-11-10, a real $0.30 test
    purchase, refunded via esim/cancel) in exactly the LPA:1$<smdp>$<id>
    shape _parse_lpa_string already handles, so no new parsing logic was
    needed, only a new field name to read it from. Returns None for an
    entry with no iccid/ac yet - esim/order is confirmed asynchronous
    (it returns only orderNo/transactionId, never profile details), so an
    empty/partial esimList is a normal "not ready yet" state, not an
    error."""
    if not isinstance(entry, dict) or not entry.get("iccid") or not entry.get("ac"):
        return None
    lpa = entry["ac"]
    smdp, matching_id = _parse_lpa_string(lpa)
    return {
        "iccid": entry["iccid"],
        "lpa": lpa,
        "smdp": smdp,
        "matching_id": matching_id,
    }


def _extract_esim_details(esim_data: dict) -> dict | None:
    """VivaPe proxies multiple underlying eSIM suppliers through the same
    get-esim-by-trx endpoint, and each returns a differently-shaped
    response depending on the product's supplier type - there is no single
    schema. Tries each known shape in turn; returns None if none match.
    Confirmed against real (not mocked) VivaPe responses for all three
    shapes, Telna's confirmed by an actual live purchase (trx 60401, ICCID
    8910300000064674263) on 2026-10-23 - which this parser originally
    failed to recognise, refunding a real customer for a real eSIM that
    VivaPe had already issued and charged us for. That gap is exactly why
    every shape here is checked against a response VivaPe actually sent,
    not against documentation or a guess at the pattern."""
    if not isinstance(esim_data, dict):
        return None

    esim_order = esim_data.get("esim_order")

    # "worldmove"-type products: iccid + the actual LPA activation string
    # under qrcodeContent/qrcode - NOT "lpa"/"qr_code", which don't exist
    # in VivaPe's real response at all (an earlier version of this parser
    # silently fell back to a self-generated fake LPA for every one of
    # these purchases while still marking them is_mock_fallback=False).
    # These fields appear nested under esim_order on real responses, and
    # sometimes also mirrored at the top level - check both, since a
    # top-level-only parser refunded real, successfully-issued eSIMs.
    for candidate in (esim_order, esim_data):
        if isinstance(candidate, dict) and candidate.get("iccid") and candidate.get("qrcodeContent"):
            lpa = candidate["qrcodeContent"]
            smdp, matching_id = _parse_lpa_string(lpa)
            return {
                "iccid": candidate["iccid"],
                "lpa": lpa,
                "smdp": smdp,
                "matching_id": matching_id,
            }

    # "esimgo"-type products: esim details are nested inside a JSON string
    # (not a nested object) under esim_order.order, e.g.
    # '[{"esims":[{"iccid":"...","matchingId":"...","smdpAddress":"..."}]}]'
    if isinstance(esim_order, dict):
        order_raw = esim_order.get("order")
        if isinstance(order_raw, str):
            try:
                order_items = json.loads(order_raw)
                esims = order_items[0].get("esims") if order_items else None
                if esims:
                    e = esims[0]
                    if e.get("iccid") and e.get("smdpAddress") and e.get("matchingId"):
                        return {
                            "iccid": e["iccid"],
                            "lpa": f"LPA:1${e['smdpAddress']}${e['matchingId']}",
                            "smdp": e["smdpAddress"],
                            "matching_id": e["matchingId"],
                        }
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass

    # "telna"-type products: iccid, smdpAddress and matchingId sit directly
    # on esim_order as their own keys - no qrcodeContent (worldmove's shape)
    # and no JSON-string-wrapped order/esims array (esimgo's shape). Telna
    # also sends its own "activation_code", already a full LPA string, but
    # it is not trusted over building one from the same iccid/smdp/matching
    # fields every other branch returns, so downstream code never has to
    # know which supplier it came from.
    if isinstance(esim_order, dict) and esim_order.get("iccid") and esim_order.get("smdpAddress") and esim_order.get("matchingId"):
        return {
            "iccid": esim_order["iccid"],
            "lpa": f"LPA:1${esim_order['smdpAddress']}${esim_order['matchingId']}",
            "smdp": esim_order["smdpAddress"],
            "matching_id": esim_order["matchingId"],
        }

    return None


def _attach_profile(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, trx_id, details: dict) -> ESIMProfile:
    """Builds the delivered eSIM from parsed supplier details and marks the
    order COMPLETED. Shared by first-time provisioning and crash recovery
    so the two can't produce differently-shaped profiles."""
    profile = ESIMProfile(
        order_id=order.id,
        beneficiary_id=beneficiary_id,
        iccid=details["iccid"],
        lpa_string=details["lpa"],
        qr_code_data=details["lpa"],
        smdp_address=details["smdp"] or "rsp.truphone.com",
        matching_id=details["matching_id"] or uuid.uuid4().hex[:12].upper(),
        # Shown as "Purchase ID" on the delivery email and the printable
        # eSIM, and what support quotes to VivaPe.
        supplier_reference=str(trx_id),
        status=ESIMStatus.RELEASED,
        is_mock_fallback=False,
        share_token=new_share_token(),
        # activated_at/expires_at are deliberately left unset: the plan's
        # validity starts when the customer installs the profile, not now.
        # esim_telemetry_svc fills both in from the supplier once that happens.
        # Setting them here dated a 3-day eSIM from the purchase, so anyone
        # who bought before their trip saw it as expired on arrival.
    )
    db.add(profile)
    order.status = OrderStatus.COMPLETED
    return profile


async def _complete_esimaccess_from_order_no(db: AsyncSession, order: Order, product: Product) -> ESIMProfile | None:
    """eSIM Access's half of complete_from_supplier_trx - recovery for an
    order whose esim/order call already went through (external_trx_id holds
    the orderNo) but whose delivery never finished. Queries by orderNo and
    never calls create_order again, so a recovered order cannot be charged
    twice.

    Same reasoning as the polling loop in _provision_via_esimaccess: a
    transient business error from query_esim (errorCode 200010 - "still
    being allocated" - confirmed live, see that function's comment) is
    "not ready yet", not a failure, and must raise EsimNotReadyYet like any
    other inconclusive answer - never let it escape as a raw, unhandled
    ESIMAccessError, which recover_stuck_orders has no reason to expect
    from this path."""
    try:
        result = await ESIMAccessAdapter.query_esim(db, order_no=order.external_trx_id)
    except ESIMAccessError as e:
        raise EsimNotReadyYet(
            f"order {order.order_no}: eSIM Access query not ready for orderNo {order.external_trx_id} ({e})"
        ) from e
    esim_list = (result or {}).get("esimList") or []
    details = _extract_esimaccess_details(esim_list[0]) if esim_list else None
    if details:
        return _attach_profile(db, order, product, order.beneficiary_id, order.external_trx_id, details)
    raise EsimNotReadyYet(
        f"order {order.order_no}: no usable eSIM for eSIM Access orderNo {order.external_trx_id} yet"
    )


async def complete_from_supplier_trx(db: AsyncSession, order: Order, product: Product, actor_id: str, actor_role: str) -> ESIMProfile | None:
    """Recovery for an order whose supplier purchase already went through
    (external_trx_id is set) but whose delivery never finished - typically
    a deploy that killed the background task mid-provisioning.

    Fetches the existing eSIM by that id and never calls create-transaction,
    so a recovered order cannot be charged twice at the supplier. Refunds
    only on a definitive answer (VivaPe responded but there's no usable
    eSIM); a network error propagates so the caller can retry later rather
    than refunding an eSIM that may well exist."""
    if product.supplier_reference == "esimaccess":
        return await _complete_esimaccess_from_order_no(db, order, product)

    esim_data = await VivaPeAdapter.get_esim_by_trx(db, order.external_trx_id)
    details = _extract_esim_details(esim_data)
    if details:
        return _attach_profile(db, order, product, order.beneficiary_id, order.external_trx_id, details)
    # Not usable YET is not the same as never. WorldMove issues eSIMs
    # asynchronously and answers "Transaction Pending" with a null iccid for
    # the first seconds or minutes, so a single look is never a definitive
    # answer. Raising hands the decision to the caller, whose GIVE_UP_AFTER
    # window keeps retrying and only refunds once enough time has passed -
    # time is the arbiter here, not the wording of one supplier response.
    raise EsimNotReadyYet(
        f"order {order.order_no}: no usable eSIM for trx {order.external_trx_id} yet"
    )


async def _provision_via_esimaccess(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, actor_id: str, actor_role: str) -> ESIMProfile | None:
    """eSIM Access's half of provision_esim(). Structurally mirrors the
    VivaPe branch (commit the supplier reference before polling, poll over
    _ESIM_READY_POLL_DELAYS, never refund once the supplier has been asked
    to charge us) but the specifics differ in ways confirmed live
    (2026-11-10, a real $0.30 test purchase against packageCode PFRQ8FIBC,
    refunded via esim/cancel afterwards) rather than assumed from docs:

    - transaction_id is order.id itself, not a freshly generated string.
      Unlike VivaPe (no idempotency key at all - see the big comment on the
      VivaPe branch below about why that's dangerous), eSIM Access's
      transactionId is designed to be reused on a retry of the same
      request. Using order.id means every retry of THIS order (including
      recover_stuck_orders re-entering this path) sends the identical
      transactionId, which is what makes that protection actually apply
      here instead of generating a fresh id and losing it.
    - esim/order's response is confirmed to carry ONLY orderNo/
      transactionId - never iccid/LPA - so there is no "found it
      immediately" fast path to check before polling, unlike VivaPe's
      occasional same-call answer. Every eSIM Access purchase polls
      esim/query at least once.
    - amount_scaled is derived from product.cost_price (kept in lockstep
      with the live catalog by the sync job), not round-tripped from a
      separate supplier-specific field the way VivaPe's
      supplier_receiver_amount is - eSIM Access's own request shape takes
      a real price, not an opaque supplier-defined quantity.
    """
    transaction_id = order.id
    amount_scaled = decimal_to_scaled(Decimal(str(product.cost_price)))
    try:
        order_obj = await ESIMAccessAdapter.create_order(
            db, transaction_id=transaction_id, package_code=product.supplier_package_code,
            amount_scaled=amount_scaled, period_num=product.supplier_period_num,
        )
        order_no = (order_obj or {}).get("orderNo")
        if not order_no:
            logger.warning(
                "esimaccess_provisioning_failed_refunding_order",
                order_id=order.id, esimaccess_response=order_obj,
            )
            await _refund_failed_order(db, order, actor_id, actor_role)
            return None

        # Durable BEFORE polling - esim/order has already charged us at this
        # point (confirmed live: balance dropped immediately on order, and
        # only came back on a later, separate esim/cancel call - the refund
        # itself was not instant either). If the process dies now, recovery
        # must re-query this orderNo, never call create_order a second time.
        order.external_trx_id = str(order_no)
        await db.commit()

        for delay in _ESIM_READY_POLL_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            # Real, live bug (2026-11-10, a genuine customer purchase on
            # beta, Bangladesh 1-day package): eSIM Access answers a query
            # made before provisioning finishes with errorCode 200010 -
            # "the batchOrder has been getting resource... success:[0]" -
            # which call_api() correctly raises as ESIMAccessError (any
            # non-success response is an error, not a value to guess at).
            # But that is "not ready yet", not a failure - exactly the
            # WorldMove/VivaPe "Transaction Pending" case this same file
            # already has a hard rule for (see the big comment at the top
            # of provision_esim's VivaPe branch: the supplier has already
            # been asked to charge us, so an inconclusive answer must never
            # trigger a refund). An earlier version let this exception
            # propagate straight past the loop to the outer except below,
            # refunding a real customer on the very first "still
            # allocating" poll. Any error during polling - 200010 or
            # anything else - is now treated the same as an empty esimList:
            # not ready THIS attempt, keep polling, never a reason to
            # refund an order the supplier has already been paid for.
            try:
                result = await ESIMAccessAdapter.query_esim(db, order_no=order_no)
            except ESIMAccessError as e:
                logger.info("esimaccess_query_not_ready_yet", order_id=order.id, order_no=order_no, error=str(e))
                continue
            esim_list = (result or {}).get("esimList") or []
            details = _extract_esimaccess_details(esim_list[0]) if esim_list else None
            if details:
                return _attach_profile(db, order, product, beneficiary_id, order_no, details)

        # Still nothing - but eSIM Access has already charged us, so this
        # order must NOT be refunded here. Leaving it PROCESSING hands it to
        # recover_stuck_orders, which re-queries this same orderNo (never
        # buying again) - same reasoning as the VivaPe branch below, and the
        # same real-money mistake it already cost this project once on a
        # different supplier.
        logger.info("esimaccess_esim_not_ready_leaving_for_recovery", order_id=order.id, order_no=order_no)
        return None
    except ESIMAccessError as e:
        logger.warning("esimaccess_provisioning_failed_refunding_order", order_id=order.id, error=str(e))
        await _refund_failed_order(db, order, actor_id, actor_role)
        return None


async def provision_esim(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, actor_id: str, actor_role: str) -> ESIMProfile | None:
    """Creates the ESIMProfile for `order` from a real VivaPe purchase and
    marks the order COMPLETED.

    Two different "no eSIM" outcomes, deliberately handled differently:

    - VivaPe never took the money (no transaction id, no supplier mapping,
      or the call failed outright): the order is marked FAILED and the buyer
      refunded in full, since a customer must never be charged for an eSIM
      that doesn't work.
    - VivaPe DID take the money but the eSIM isn't ready yet: the order is
      left PROCESSING and returned as None WITHOUT a refund, so
      recover_stuck_orders can re-fetch that same transaction. Refunding
      here is what bought and abandoned real eSIMs.

    Returns None in both cases. Caller commits either way.

    eSIM Access products (product.supplier_reference == "esimaccess") take
    a structurally similar but differently-detailed path - see
    _provision_via_esimaccess for what's actually different and why."""
    if product.supplier_reference == "esimaccess":
        return await _provision_via_esimaccess(db, order, product, beneficiary_id, actor_id, actor_role)

    if product.supplier_product_id and product.supplier_receiver_amount is not None:
        try:
            # receiver_amount is NOT the price — confirmed against VivaPe's
            # live catalog it's a supplier-defined quantity whose meaning
            # varies by product type. Must be the exact catalog value,
            # never derived from cost_price.
            trx = await VivaPeAdapter.create_transaction(
                db, product.supplier_product_id, Decimal(str(product.supplier_receiver_amount))
            )
            purchase_trx = trx.get("purchase_trx") if isinstance(trx, dict) else None
            trx_id = purchase_trx.get("id") if isinstance(purchase_trx, dict) else None
            if trx_id:
                # Pin VivaPe's transaction id to the order as soon as we have
                # it - before fetching the eSIM details, which may fail. It's
                # the only handle that ties an order back to a specific
                # supplier transaction; without it, tracing a customer's eSIM
                # (or a failed charge) means scanning supplier logs by
                # timestamp.
                order.external_trx_id = str(trx_id)
                # Durable BEFORE the next supplier call. VivaPe has already
                # charged us at this point; if the process dies now (a deploy
                # mid-purchase), recovery can fetch this already-paid eSIM by
                # id instead of buying a second one.
                await db.commit()
                # Ask a few times over ~20s rather than once immediately.
                # The old single call happened ~300ms after the purchase,
                # which is far sooner than an async supplier can answer.
                for delay in _ESIM_READY_POLL_DELAYS:
                    if delay:
                        await asyncio.sleep(delay)
                    esim_data = await VivaPeAdapter.get_esim_by_trx(db, trx_id)
                    details = _extract_esim_details(esim_data)
                    if details:
                        return _attach_profile(db, order, product, beneficiary_id, trx_id, details)
                # Still nothing - but VivaPe has already charged us, so this
                # order must NOT be refunded here. Leaving it PROCESSING
                # hands it to recover_stuck_orders, which re-fetches this
                # same transaction (never buying again) for up to an hour
                # before giving up. Refunding at this point is what threw
                # away eSIMs we had paid for.
                logger.info(
                    "vivape_esim_not_ready_leaving_for_recovery",
                    order_id=order.id, trx_id=trx_id,
                )
                return None
            else:
                logger.warning(
                    "vivape_provisioning_failed_refunding_order",
                    order_id=order.id,
                    vivape_error=trx.get("error") if isinstance(trx, dict) else str(trx)
                )
        except Exception as e:
            logger.warning("vivape_provisioning_failed_refunding_order", order_id=order.id, error=str(e))
    else:
        logger.warning("vivape_provisioning_skipped_no_supplier_mapping_refunding_order", order_id=order.id, product_id=product.id)

    await _refund_failed_order(db, order, actor_id, actor_role)
    return None


async def _refund_failed_order(db: AsyncSession, order: Order, actor_id: str, actor_role: str) -> None:
    """Marks `order` FAILED and refunds the full order amount — the same
    compensation regardless of whether the order was originally paid from the
    wallet (reverses the debit) or via ShurjoPay gateway (no prior debit to
    reverse, so this is the customer's only compensation since no
    payment-gateway refund integration exists).

    The refund is split the way the payment was: whatever came out of promo
    credit goes back to promo credit. Returning it all to the main wallet
    would quietly convert non-withdrawable reward credit into cash the
    customer could withdraw."""
    order.status = OrderStatus.FAILED

    total = Decimal(str(order.total_amount))
    reward_part = min(Decimal(str(order.reward_amount_used or 0)), total)
    cash_part = total - reward_part

    if reward_part > 0:
        reward_wallet = await LedgerService.ensure_reward_wallet(db, order.buyer_id)
        await LedgerService.credit(
            db, reward_wallet.id, reward_part,
            LedgerRefType.REFUND,
            ref_id=order.id,
            description=f"Refund to reward credit: order {order.order_no} failed",
            idempotency_key=f"order-refund-{order.id}-reward"
        )

    if cash_part > 0:
        w_res = await db.execute(
            select(Wallet).where(Wallet.user_id == order.buyer_id, Wallet.wallet_type == WalletType.DEFAULT)
        )
        wallet = w_res.scalar_one_or_none()
        if wallet:
            await LedgerService.credit(
                db, wallet.id, cash_part,
                LedgerRefType.REFUND,
                ref_id=order.id,
                description=f"Refund: eSIM provisioning failed for order {order.order_no}",
                idempotency_key=f"order-refund-{order.id}"
            )

    # The single refund funnel, so a first-purchase referral reward tied to
    # this order is clawed back here rather than at each call site.
    await referral_svc.reverse_for_order(db, order.id, f"order {order.order_no} refunded")

    await AuditService.log_action(
        db, actor_id=actor_id, actor_role=actor_role,
        action="ORDER_PROVISIONING_FAILED_REFUNDED",
        after_state={
            "order_id": order.id, "product_id": order.product_id,
            "refund_amount": str(order.total_amount), "refunded_to_reward_credit": str(reward_part),
        }
    )


async def get_effective_commission_rate(db: AsyncSession, merchant_user_id: str, flat_rate_pct: Decimal) -> Decimal:
    """Volume-based tiered commission, falling back to the merchant's own
    flat MerchantProfile.commission_rate_pct - both because that's the
    plan's "default flat %" requirement, and so tiers are fully optional:
    a deployment with none configured behaves exactly as before this
    feature existed."""
    tiers_res = await db.execute(select(CommissionTier).order_by(CommissionTier.min_volume_usd.desc()))
    tiers = tiers_res.scalars().all()
    if not tiers:
        return flat_rate_pct

    volume_res = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            Order.buyer_id == merchant_user_id,
            Order.is_reseller_order == True,
            Order.status == OrderStatus.COMPLETED,
        )
    )
    cumulative_volume = Decimal(str(volume_res.scalar_one()))

    for tier in tiers:  # sorted highest-threshold-first
        if cumulative_volume >= Decimal(str(tier.min_volume_usd)):
            return Decimal(str(tier.rate_pct))

    # Below every configured tier's threshold - the flat rate is the floor.
    return flat_rate_pct


async def distribute_commission(db: AsyncSession, order: Order, total_cost: Decimal, buyer: User) -> None:
    """Credits `buyer`'s COMMISSION wallet for a reseller order, at the
    tiered/flat rate from get_effective_commission_rate, and then the agent
    behind that merchant, if any. Shared between the wallet-checkout path
    (orders.py) and the Partner API order path (partner.py) so the two can't
    drift apart. No-op for non-merchant or non-reseller orders.

    Called only for a delivered order (see order_fulfilment._finish), which is
    what keeps a refunded sale from paying either party. Caller commits."""
    if buyer.role != UserRole.MERCHANT or not order.is_reseller_order:
        return

    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == buyer.id))
    merchant_profile = m_res.scalar_one_or_none()
    flat_rate_pct = Decimal(str(merchant_profile.commission_rate_pct)) if merchant_profile else Decimal("5.0")
    gross_rate_pct = await get_effective_commission_rate(db, buyer.id, flat_rate_pct)

    # Resolve the agent FIRST, because the deduction is only legitimate if
    # somebody is actually receiving it. Deducting for a suspended agent would
    # take the slice off the merchant and pay it to nobody - the money would
    # simply vanish - so both sides hang off the same approved-agent check.
    agent_user_id, agent_pct = (
        await agent_svc.commission_rate_for_merchant(db, merchant_profile)
        if merchant_profile else (None, Decimal("0"))
    )
    # Capped at the merchant's own rate, so a generous bonus can zero a
    # merchant out but can never make their commission negative.
    bonus_pct = agent_svc.bonus_pct_for(merchant_profile, gross_rate_pct) if agent_user_id else Decimal("0")
    rate_pct = gross_rate_pct - bonus_pct
    commission_amount = (total_cost * (rate_pct / Decimal("100"))).quantize(Decimal("0.0001"))

    cw_res = await db.execute(
        select(Wallet).where(Wallet.user_id == buyer.id, Wallet.wallet_type == WalletType.COMMISSION)
    )
    comm_wallet = cw_res.scalar_one_or_none()
    if comm_wallet and commission_amount > Decimal("0"):
        await LedgerService.credit(
            db, comm_wallet.id, commission_amount,
            LedgerRefType.COMMISSION_EARNED,
            ref_id=order.id,
            # The NET rate: this line shows up in the merchant's own ledger,
            # and naming the pre-deduction rate here would give the bonus away.
            description=f"Commission for order {order.order_no} ({rate_pct}%)",
            idempotency_key=f"order-commission-{order.id}"
        )
        order.reseller_commission_amount = commission_amount

    if agent_user_id:
        await _pay_agent_commission(db, order, total_cost, agent_user_id, agent_pct, bonus_pct)


async def _pay_agent_commission(
    db: AsyncSession, order: Order, total_cost: Decimal, agent_user_id: str, agent_pct: Decimal, bonus_pct: Decimal
) -> None:
    """The agent earns two separate things on a sale by one of their merchants:

    1. their own percentage of the sale price, which comes out of our margin;
    2. the bonus slice they take from the merchant's commission, which costs
       us nothing because the merchant's share shrinks by the same amount.

    Both are credited to the agent's commission wallet but recorded separately
    on the order, because only the first one affects profit. The agent id is
    snapshotted here so re-pointing the merchant to another agent later can
    never rewrite who was paid for this sale.
    """
    own = (total_cost * (agent_pct / Decimal("100"))).quantize(Decimal("0.0001")) if agent_pct > 0 else Decimal("0")
    bonus = (total_cost * (bonus_pct / Decimal("100"))).quantize(Decimal("0.0001")) if bonus_pct > 0 else Decimal("0")
    if own <= 0 and bonus <= 0:
        return

    wallet = await LedgerService.ensure_commission_wallet(db, agent_user_id)
    if own > 0:
        await LedgerService.credit(
            db, wallet.id, own,
            LedgerRefType.AGENT_COMMISSION_EARNED,
            ref_id=order.id,
            description=f"Agent commission for order {order.order_no} ({agent_pct}%)",
            idempotency_key=f"order-agent-commission-{order.id}",
        )
    if bonus > 0:
        await LedgerService.credit(
            db, wallet.id, bonus,
            LedgerRefType.AGENT_COMMISSION_EARNED,
            ref_id=order.id,
            description=f"Partner bonus for order {order.order_no} ({bonus_pct}%)",
            idempotency_key=f"order-agent-bonus-{order.id}",
        )

    order.agent_id = agent_user_id
    order.agent_commission_amount = own
    order.agent_bonus_amount = bonus

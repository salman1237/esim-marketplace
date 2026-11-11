import time
import httpx
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import SupplierTransactionLog
from app.core.config import settings

# See backend/docs/esimaccess_integration_reference.md for the full
# investigation behind every decision in this file - auth, the response
# envelope, the Day Pass pricing formula, the exit-IP gotcha, all confirmed
# there, most of it against the real account on 2026-11-10.

USD_SCALE = Decimal(10000)  # every price/amount field is USD x10,000; 70000 == $7.00

# dataType -> plan model, confirmed live (reference doc §6).
DATA_TYPE_FIXED = 1
DATA_TYPE_DAILY_SPEED_CAPPED = 2
DATA_TYPE_DAILY_CUTOFF = 3
DATA_TYPE_DAILY_UNLIMITED = 4
DAY_PASS_DATA_TYPES = frozenset({DATA_TYPE_DAILY_SPEED_CAPPED, DATA_TYPE_DAILY_CUTOFF, DATA_TYPE_DAILY_UNLIMITED})

# Day Pass tiered discount off the daily rate, confirmed against a real live
# pull (reference doc §6) - NOT price x days. Keyed by the inclusive upper
# bound of each periodNum band; _day_pass_rate_share() picks the first band
# periodNum fits into.
_DAY_PASS_BANDS = (
    (4, Decimal("0.96")),
    (9, Decimal("0.92")),
    (19, Decimal("0.89")),
    (29, Decimal("0.85")),
    (365, Decimal("0.82")),
)


def _day_pass_rate_share(period_num: int) -> Decimal:
    for upper_bound, share in _DAY_PASS_BANDS:
        if period_num <= upper_bound:
            return share
    # Longer than any documented band - reference doc only confirms up to
    # 365 days, which is also eSIM Access's own apparent ceiling (same
    # upper bound every band table it's derived from uses), so there is no
    # evidence-backed share beyond it. Fail loudly rather than silently
    # applying a guessed discount to an order that size.
    raise ValueError(f"No confirmed Day Pass discount band for periodNum={period_num} (max confirmed: 365)")


def day_pass_total_price(daily_rate_scaled: int, period_num: int) -> int:
    """daily_rate_scaled is the package's per-day price in the x10,000
    encoding (e.g. 6500 == $0.65/day). Returns the real total price for
    buying period_num days, in the same encoding - NOT daily_rate_scaled *
    period_num. See the China worked example in the reference doc: $0.65/day
    for 7 days is $4.19 total (91% share... actually 92% per the 5-9 band),
    not $4.55."""
    share = _day_pass_rate_share(period_num)
    return int(Decimal(daily_rate_scaled) * period_num * share)


def scaled_to_decimal(scaled) -> Decimal:
    """USD x10,000 integer -> a real Decimal amount. Every price/amount
    field on every endpoint uses this encoding (confirmed: package prices,
    balance/query's balance, esim/order's amount) - never assume cents."""
    return (Decimal(scaled) / USD_SCALE).quantize(Decimal("0.0001"))


def decimal_to_scaled(amount: Decimal) -> int:
    """The inverse of scaled_to_decimal, for building a request body."""
    return int((amount * USD_SCALE).to_integral_value())


class ESIMAccessAdapter:
    """No session/token model - unlike VivaPe, RT-AccessCode is a static
    credential sent on every call (confirmed live, reference doc §2). This
    is why there is no get_token()/_token_lock/force_fresh_token here: there
    is nothing to cache or refresh. If a future account ever does require
    HMAC signing (the one unresolved, conflicting claim in the reference
    doc), that becomes a second header computed in call_api() from
    settings.ESIMACCESS_SECRET_KEY - not a rewrite of this class's shape.

    Every endpoint is POST (confirmed - there do not appear to be GET
    endpoints at all, including reads like balance/query), and every
    response is HTTP 200 even on a business failure (same trap as VivaPe -
    see call_api()'s success check). http2=True is set defensively, the same
    way VivaPe's adapter does, even though nothing today suggests eSIM
    Access needs it - cheap insurance against repeating that exact incident
    for a different supplier.
    """

    @classmethod
    async def call_api(cls, db: AsyncSession, endpoint: str, data: dict | None = None) -> dict:
        """Returns resp_data on success. Raises ESIMAccessError if the HTTP
        call itself failed, the body wasn't JSON, or `success` is not True -
        a 200 status is never, by itself, treated as success. See the
        reference doc §3: this is the same "always-200, business-error-in-
        body" model VivaPe uses, and vivape_adapter.py's create_transaction()
        comment documents what trusting HTTP status alone has already cost
        this project once, on a different supplier."""
        url = f"{settings.ESIMACCESS_BASE_URL}/{endpoint.lstrip('/')}"
        headers = {
            "RT-AccessCode": settings.ESIMACCESS_ACCESS_CODE,
            "Content-Type": "application/json",
        }

        start_time = time.time()
        status_code = 0
        resp_data = None
        error_msg = None

        try:
            async with httpx.AsyncClient(verify=True, timeout=30.0, http2=True) as client:
                resp = await client.post(url, headers=headers, json=data or {})
                status_code = resp.status_code
                try:
                    resp_data = resp.json()
                except Exception:
                    resp_data = {"raw": resp.text}

                if status_code != 200:
                    raise ESIMAccessError(f"eSIM Access HTTP {status_code} on {endpoint}: {resp.text[:500]}")
                if not isinstance(resp_data, dict) or resp_data.get("success") is not True:
                    error_code = resp_data.get("errorCode") if isinstance(resp_data, dict) else None
                    error_text = resp_data.get("errorMsg") if isinstance(resp_data, dict) else None
                    raise ESIMAccessError(
                        f"eSIM Access business error on {endpoint}: errorCode={error_code!r} errorMsg={error_text!r}"
                    )
                return resp_data
        except ESIMAccessError:
            raise
        except Exception as e:
            error_msg = str(e)
            raise ESIMAccessError(f"eSIM Access call to {endpoint} failed: {error_msg}") from e
        finally:
            latency = int((time.time() - start_time) * 1000)
            log = SupplierTransactionLog(
                supplier_name="ESIMACCESS",
                endpoint=endpoint,
                method="POST",
                request_payload=data or {},
                response_payload=resp_data or {"error": error_msg},
                status_code=status_code,
                latency_ms=latency,
            )
            db.add(log)
            await db.commit()

    @classmethod
    async def get_balance(cls, db: AsyncSession) -> Decimal:
        """Account balance in real USD. No request body (confirmed live)."""
        result = await cls.call_api(db, "balance/query")
        return scaled_to_decimal(result["obj"]["balance"])

    @classmethod
    async def list_packages(cls, db: AsyncSession, location_code: str = "", package_type: str = "") -> list:
        """location_code="" returns the full catalogue (confirmed this is
        how the 3,259-package live pull was taken - see reference doc §4.1).
        Never assume a doc example's smaller sample is the whole catalogue;
        this project has already drawn wrong conclusions from that mistake
        once. package_type is "" for the base product list or "TOPUP" to
        list top-up options (only meaningful together with packageCode/
        iccid, not implemented here - add when top-up is actually built)."""
        result = await cls.call_api(db, "package/list", data={
            "locationCode": location_code,
            "type": package_type,
            "packageCode": "",
            "iccid": "",
        })
        obj = result.get("obj") or {}
        return obj.get("packageList", []) if isinstance(obj, dict) else []

    @classmethod
    async def list_topup_packages(cls, db: AsyncSession, package_code: str = "", iccid: str = "") -> list:
        """type="TOPUP" scoped to a specific base package and/or a
        specific eSIM (reference doc §4.1) - this is the ONLY reliable way
        to know what's actually top-up-eligible right now. supportTopUpType
        on a base package is NOT a reliable gate (empirically disproven: a
        package with supportTopUpType=1 still returned real options here) -
        never pre-filter on it, always query live."""
        result = await cls.call_api(db, "package/list", data={
            "locationCode": "",
            "type": "TOPUP",
            "packageCode": package_code,
            "iccid": iccid,
        })
        obj = result.get("obj") or {}
        return obj.get("packageList", []) if isinstance(obj, dict) else []

    @classmethod
    async def topup_esim(cls, db: AsyncSession, iccid: str, package_code: str,
                          amount_scaled: int, transaction_id: str) -> dict:
        """Adds data to an ALREADY-DELIVERED eSIM (reference doc §4.5) - no
        VivaPe equivalent exists. Unlike create_order, the docs describe no
        asynchronous provisioning step for this - no orderNo to poll - so a
        caller treats a successful call_api return as done, not as "now
        poll esim/query". Only valid while the target eSIM hasn't expired
        and the specific TOPUP_* packageCode is still offered for it (see
        list_topup_packages) - a stale packageCode is a business error here,
        same as any other, not a special case."""
        if len(transaction_id) > 50:
            raise ValueError(f"transactionId must be <=50 chars, got {len(transaction_id)}")
        result = await cls.call_api(db, "esim/topup", data={
            "iccid": iccid,
            "packageCode": package_code,
            "transactionId": transaction_id,
            "amount": amount_scaled,
        })
        return result.get("obj")

    @classmethod
    async def create_order(cls, db: AsyncSession, transaction_id: str, package_code: str,
                            amount_scaled: int, count: int = 1, period_num: int | None = None) -> dict:
        """transaction_id is the idempotency key (max 50 chars, confirmed
        sent in the body, not a header - see reference doc §4.2). Caller is
        responsible for generating a transaction_id that is actually unique
        per attempt (mirroring how checkout_svc.py already has to generate
        one for other suppliers) and for computing amount_scaled correctly
        for a Day Pass via day_pass_total_price() rather than passing a
        package's bare daily rate.

        period_num is the Day Pass duration in days (periodNum, reference
        doc §4.2) - required for a Day Pass packageCode, omitted entirely
        for fixed-data (the key is left out of the request rather than
        sent as null, since that's unconfirmed and the fixed-data path has
        already been proven live without it)."""
        if len(transaction_id) > 50:
            raise ValueError(f"transactionId must be <=50 chars, got {len(transaction_id)}")
        package_info = {"packageCode": package_code, "count": count}
        if period_num is not None:
            package_info["periodNum"] = period_num
        result = await cls.call_api(db, "esim/order", data={
            "transactionId": transaction_id,
            "amount": amount_scaled,
            "packageInfoList": [package_info],
        })
        return result.get("obj")

    @classmethod
    async def query_esim(cls, db: AsyncSession, order_no: str | None = None, iccid: str | None = None,
                          page_num: int = 1, page_size: int = 20) -> dict:
        """Query by orderNo or iccid - at least one should be given, though
        the API itself isn't confirmed to require it (reference doc §4.3).
        Used both for polling right after create_order (no webhook
        configured yet, or as a startup-safety fallback once one is) and for
        status/usage lookups from the eSIM detail screen, mirroring how
        vivape_adapter.py's get_esim_usage/get_esim_device_info are used."""
        result = await cls.call_api(db, "esim/query", data={
            "orderNo": order_no,
            "iccid": iccid,
            "pager": {"pageNum": page_num, "pageSize": page_size, "total": None},
            "startTime": None,
            "endTime": None,
        })
        return result.get("obj")

    @classmethod
    async def cancel_esim(cls, db: AsyncSession, iccid: str) -> dict:
        """Unused/inactive profile only - refunds to account balance. This
        is a capability VivaPe has no equivalent of at all (vivape_adapter.py
        has no cancel/refund method), which is what caused the real EUR28.61
        lost-to-abandoned-eSIMs incident this project already paid for on
        VivaPe (see vivape-vs-esimaccess.tex). Do not confuse with
        revoke_esim() below - cancel is the recovery/refund path; revoke is
        not refundable."""
        result = await cls.call_api(db, "esim/cancel", data={"iccid": iccid})
        return result.get("obj")

    @classmethod
    async def revoke_esim(cls, db: AsyncSession, iccid: str) -> dict:
        """Closes an ACTIVE profile. Explicitly NOT refundable (reference
        doc §4.4) - never use this to clean up a test order; use
        cancel_esim() for that."""
        result = await cls.call_api(db, "esim/revoke", data={"iccid": iccid})
        return result.get("obj")

    @classmethod
    async def suspend_esim(cls, db: AsyncSession, iccid: str) -> dict:
        result = await cls.call_api(db, "esim/suspend", data={"iccid": iccid})
        return result.get("obj")

    @classmethod
    async def unsuspend_esim(cls, db: AsyncSession, iccid: str) -> dict:
        result = await cls.call_api(db, "esim/unsuspend", data={"iccid": iccid})
        return result.get("obj")

    @classmethod
    async def set_webhook_url(cls, db: AsyncSession, webhook_url: str) -> dict:
        result = await cls.call_api(db, "webhook/save", data={"webhook": webhook_url})
        return result.get("obj")

    @classmethod
    async def get_webhook_url(cls, db: AsyncSession) -> dict:
        result = await cls.call_api(db, "webhook/query")
        return result.get("obj")


class ESIMAccessError(Exception):
    """Raised for both transport failures and business-logic failures
    (success is not True in an otherwise-200 response) - callers that need
    to tell the two apart should inspect the message, which always states
    which case it was (see call_api()'s two raise sites)."""
    pass

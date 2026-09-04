"""Shared logic between the two checkout paths (wallet, synchronous; and
ShurjoPay gateway, completed later from the payment callback) so
provisioning behavior can't drift between them.
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.order import Order, OrderStatus, ESIMProfile, ESIMStatus
from app.models.catalog import Product
from app.services.ledger_svc import LedgerService
from app.services.vivape_adapter import VivaPeAdapter
from app.services.audit_svc import AuditService
from app.core.logging import get_logger

logger = get_logger(__name__)

RESELLER_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT}


async def resolve_beneficiary(db: AsyncSession, current_user: User, is_buy_for_user: bool, auto_create_user: bool, beneficiary_username: str | None, beneficiary_email: str | None) -> str:
    if not is_buy_for_user:
        return current_user.id

    if auto_create_user:
        auto_username = f"user_{uuid.uuid4().hex[:8]}"
        auto_email = f"{auto_username}@customer.esim.local"
        new_user = User(
            email=auto_email,
            username=auto_username,
            hashed_password=get_password_hash(uuid.uuid4().hex),
            role=UserRole.USER
        )
        db.add(new_user)
        await db.flush()
        await LedgerService.ensure_wallets_for_user(db, new_user.id, new_user.role)
        return new_user.id

    if beneficiary_username or beneficiary_email:
        u_query = select(User).where(
            (User.username == beneficiary_username) | (User.email == beneficiary_email)
        )
        b_res = await db.execute(u_query)
        target = b_res.scalar_one_or_none()
        if not target:
            raise ValueError("Beneficiary user account not found")
        return target.id

    return current_user.id


async def provision_esim(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, actor_id: str, actor_role: str) -> ESIMProfile:
    """Creates the ESIMProfile for `order` (real VivaPe data if possible,
    an obviously-fake mock flagged via is_mock_fallback otherwise so a
    supplier failure never silently looks like a working eSIM), marks the
    order COMPLETED, and adds/returns the profile. Caller commits."""
    iccid = f"89882{uuid.uuid4().hex[:14].upper()}"
    matching_id = uuid.uuid4().hex[:12].upper()
    smdp = "rsp.truphone.com"
    lpa = f"LPA:1${smdp}${matching_id}"
    qr_data = lpa
    is_mock_fallback = True

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
                esim_data = await VivaPeAdapter.get_esim_by_trx(db, trx_id)
                if esim_data.get("iccid"):
                    iccid = esim_data["iccid"]
                    lpa = esim_data.get("lpa") or lpa
                    qr_data = esim_data.get("qr_code") or lpa
                    is_mock_fallback = False
            else:
                logger.warning(
                    "vivape_provisioning_failed_using_mock_fallback",
                    order_id=order.id,
                    vivape_error=trx.get("error") if isinstance(trx, dict) else str(trx)
                )
        except Exception as e:
            logger.warning("vivape_provisioning_failed_using_mock_fallback", order_id=order.id, error=str(e))

    if is_mock_fallback:
        await AuditService.log_action(
            db, actor_id=actor_id, actor_role=actor_role,
            action="MOCK_ESIM_FALLBACK",
            after_state={"order_id": order.id, "product_id": product.id, "reason": "VivaPe provisioning unavailable or failed"}
        )

    profile = ESIMProfile(
        order_id=order.id,
        beneficiary_id=beneficiary_id,
        iccid=iccid,
        lpa_string=lpa,
        qr_code_data=qr_data,
        smdp_address=smdp,
        matching_id=matching_id,
        status=ESIMStatus.RELEASED,
        is_mock_fallback=is_mock_fallback,
        expires_at=datetime.now(timezone.utc) + timedelta(days=product.validity_days)
    )
    db.add(profile)
    order.status = OrderStatus.COMPLETED
    return profile

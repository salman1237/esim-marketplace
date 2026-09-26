"""Everything the admin Overview tab shows, in one call.

Built from the same records as the finance and sales reports - orders
(with their cost snapshot), the wallet ledger, users and the review queues -
so the Overview never disagrees with those reports."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Country, Product
from app.models.kyc import KYCStatus, KYCSubmission
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import Order, OrderStatus
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.models.user import User, UserRole
from app.models.wallet import LedgerRefType, LedgerTxType, WalletLedgerEntry
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from app.services.finance_svc import cents, ledger_integrity, wallet_liabilities

STUCK_AFTER = timedelta(minutes=30)
TOP_DESTINATIONS = 8
RECENT_ORDERS = 8
_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _channel_of(order_no: str) -> str:
    if order_no.startswith("PTR-"):
        return "api"
    if order_no.startswith("ADM-"):
        return "admin"
    return "web"


async def _order_totals(db: AsyncSession, start: datetime, end: datetime) -> dict:
    completed = Order.status == OrderStatus.COMPLETED
    row = (await db.execute(
        select(
            func.count(Order.id).filter(completed),
            func.coalesce(func.sum(Order.total_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.total_amount).filter(and_(completed, Order.cost_amount.isnot(None))), 0),
            func.coalesce(func.sum(Order.cost_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount).filter(completed), 0),
            func.count(Order.id).filter(Order.status == OrderStatus.FAILED),
        ).where(Order.created_at >= start, Order.created_at < end)
    )).one()
    orders, sales, sales_with_cost, cost, commission, failed = row
    return {
        "orders": orders,
        "sales": _dec(sales),
        "net_profit": _dec(sales_with_cost) - _dec(cost) - _dec(commission),
        "failed": failed,
    }


async def _new_customers(db: AsyncSession, start: datetime, end: datetime) -> int:
    # users.created_at is naive UTC (unlike orders), so compare naive.
    return (await db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.USER,
            User.created_at >= start.replace(tzinfo=None),
            User.created_at < end.replace(tzinfo=None),
        )
    )).scalar_one()


def _topup_filter():
    return and_(
        WalletLedgerEntry.tx_type == LedgerTxType.CREDIT,
        WalletLedgerEntry.reference_type.in_([LedgerRefType.DEPOSIT_GATEWAY, LedgerRefType.DEPOSIT_MANUAL]),
    )


async def _topups(db: AsyncSession, start: datetime, end: datetime) -> Decimal:
    return _dec((await db.execute(
        select(func.coalesce(func.sum(WalletLedgerEntry.amount), 0)).where(
            _topup_filter(), WalletLedgerEntry.created_at >= start, WalletLedgerEntry.created_at < end,
        )
    )).scalar_one())


async def build_overview(db: AsyncSession, days: int) -> dict:
    now = datetime.now(timezone.utc)
    start_day = now.date() - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end = now + timedelta(seconds=1)
    prev_start = start - timedelta(days=days)
    day_list = [start_day + timedelta(days=i) for i in range(days)]
    daily = {d: {"sales": _ZERO, "cost": _ZERO, "net_profit": _ZERO, "orders": 0, "failed": 0, "new_customers": 0, "topups": _ZERO} for d in day_list}

    # ---- orders per day ----
    completed = Order.status == OrderStatus.COMPLETED
    order_day = func.date(func.timezone("UTC", Order.created_at))
    for day, orders, sales, sales_with_cost, cost, commission, failed in (await db.execute(
        select(
            order_day,
            func.count(Order.id).filter(completed),
            func.coalesce(func.sum(Order.total_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.total_amount).filter(and_(completed, Order.cost_amount.isnot(None))), 0),
            func.coalesce(func.sum(Order.cost_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount).filter(completed), 0),
            func.count(Order.id).filter(Order.status == OrderStatus.FAILED),
        ).where(Order.created_at >= start).group_by(order_day)
    )).all():
        if day in daily:
            daily[day].update(
                orders=orders, sales=_dec(sales), cost=_dec(cost), failed=failed,
                net_profit=_dec(sales_with_cost) - _dec(cost) - _dec(commission),
            )

    # ---- new customers per day (naive UTC column) ----
    user_day = func.date(User.created_at)
    for day, count in (await db.execute(
        select(user_day, func.count(User.id))
        .where(User.role == UserRole.USER, User.created_at >= start.replace(tzinfo=None))
        .group_by(user_day)
    )).all():
        if day in daily:
            daily[day]["new_customers"] = count

    # ---- money received per day ----
    ledger_day = func.date(func.timezone("UTC", WalletLedgerEntry.created_at))
    for day, amount in (await db.execute(
        select(ledger_day, func.coalesce(func.sum(WalletLedgerEntry.amount), 0))
        .where(_topup_filter(), WalletLedgerEntry.created_at >= start)
        .group_by(ledger_day)
    )).all():
        if day in daily:
            daily[day]["topups"] = _dec(amount)

    current = {
        "orders": sum(d["orders"] for d in daily.values()),
        "sales": sum((d["sales"] for d in daily.values()), _ZERO),
        "net_profit": sum((d["net_profit"] for d in daily.values()), _ZERO),
        "failed": sum(d["failed"] for d in daily.values()),
        "new_customers": sum(d["new_customers"] for d in daily.values()),
        "topups": sum((d["topups"] for d in daily.values()), _ZERO),
    }
    previous = await _order_totals(db, prev_start, start)
    previous["new_customers"] = await _new_customers(db, prev_start, start)
    previous["topups"] = await _topups(db, prev_start, start)

    # ---- where sales come from ----
    channel_totals = {c: {"sales": _ZERO, "orders": 0} for c in ("web", "api", "admin")}
    for order_no, amount in (await db.execute(
        select(Order.order_no, Order.total_amount).where(completed, Order.created_at >= start)
    )).all():
        bucket = channel_totals[_channel_of(order_no)]
        bucket["sales"] += _dec(amount)
        bucket["orders"] += 1

    payment_rows = (await db.execute(
        select(Order.payment_method, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .where(completed, Order.created_at >= start)
        .group_by(Order.payment_method)
    )).all()

    top = (await db.execute(
        select(Country.iso2, Country.name_en, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .select_from(Order)
        .join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .where(completed, Order.created_at >= start)
        .group_by(Country.iso2, Country.name_en)
        .order_by(func.sum(Order.total_amount).desc())
        .limit(TOP_DESTINATIONS)
    )).all()

    # ---- what needs a human ----
    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar_one()

    settled = current["orders"] + current["failed"]
    integrity = await ledger_integrity(db)
    attention = {
        "pending_merchants": await count(select(func.count(MerchantProfile.id)).where(MerchantProfile.status == MerchantStatus.PENDING)),
        "pending_deposits": await count(select(func.count(ManualPaymentRequest.id)).where(ManualPaymentRequest.status == ManualPaymentStatus.PENDING)),
        "pending_kyc": await count(select(func.count(KYCSubmission.id)).where(KYCSubmission.status == KYCStatus.PENDING)),
        "pending_withdrawals": await count(select(func.count(WithdrawalRequest.id)).where(WithdrawalRequest.status == WithdrawalStatus.PENDING)),
        "stuck_orders": await count(select(func.count(Order.id)).where(
            Order.status.in_([OrderStatus.PAID, OrderStatus.PROCESSING]), Order.updated_at < now - STUCK_AFTER,
        )),
        "failed_orders": current["failed"],
        "failure_rate_pct": round(current["failed"] / settled * 100, 1) if settled else 0.0,
        "ledger_ok": integrity["ok"],
        "ledger_mismatches": integrity["wallet_balance_mismatches"],
    }

    approved_merchants = await count(select(func.count(MerchantProfile.id)).where(MerchantProfile.status == MerchantStatus.APPROVED))
    active_merchants = await count(select(func.count(func.distinct(Order.buyer_id))).where(
        completed, Order.is_reseller_order == True, Order.created_at >= start,
    ))

    recent = (await db.execute(
        select(Order, Product.title_en, Product.is_unlimited, Product.data_amount_gb, Product.validity_days, Country.iso2, User.username, User.email)
        .join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .join(User, Order.buyer_id == User.id)
        .order_by(Order.created_at.desc())
        .limit(RECENT_ORDERS)
    )).all()

    liability = await wallet_liabilities(db)

    def pair(key, money=True):
        cur, prev = current[key], previous[key]
        return {"current": cents(cur) if money else cur, "previous": cents(prev) if money else prev}

    return {
        "period": {"days": days, "start": start_day.isoformat(), "end": now.date().isoformat()},
        "currency": "EUR",
        "kpis": {
            "sales": pair("sales"),
            "net_profit": pair("net_profit"),
            "orders": pair("orders", money=False),
            "new_customers": pair("new_customers", money=False),
            "topups": pair("topups"),
            "wallet_liability": {"current": liability["total"]},
        },
        "daily": [
            {
                "day": d.isoformat(),
                "sales": cents(v["sales"]), "cost": cents(v["cost"]), "net_profit": cents(v["net_profit"]),
                "orders": v["orders"], "failed": v["failed"], "new_customers": v["new_customers"], "topups": cents(v["topups"]),
            }
            for d, v in daily.items()
        ],
        "channels": [{"channel": c, "sales": cents(v["sales"]), "orders": v["orders"]} for c, v in channel_totals.items()],
        "payment_methods": [
            {"method": method.value, "orders": n, "sales": cents(total)} for method, n, total in payment_rows
        ],
        "top_destinations": [
            {"iso2": iso2, "country": name, "orders": n, "sales": cents(total)} for iso2, name, n, total in top
        ],
        "merchants": {"approved": approved_merchants, "active": active_merchants},
        "attention": attention,
        "recent_orders": [
            {
                "order_no": o.order_no,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "status": o.status.value,
                "amount": cents(o.total_amount),
                "product": f"{'Unlimited' if unlimited else f'{Decimal(str(gb)).normalize():f} GB'} · {vdays} days",
                "title": title,
                "country_iso2": iso2,
                "buyer": email or username,
                "channel": _channel_of(o.order_no),
            }
            for o, title, unlimited, gb, vdays, iso2, username, email in recent
        ],
    }

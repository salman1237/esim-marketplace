"""Who is holding money, and how much.

The three wallets are reported side by side rather than summed into one
number, because they are not interchangeable: DEFAULT is cash the customer
topped up, REWARD is promotional credit that can be spent but never
withdrawn, and COMMISSION is what a merchant or agent has earned. A single
"balance" column would quietly imply the business owes cash it does not.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import fmt_bd
from app.models.user import User
from app.models.wallet import Wallet, WalletLedgerEntry, WalletType

SORTABLE = ("total", "default", "reward", "commission", "name", "email", "created", "last_activity")


async def build_wallet_report(
    db: AsyncSession,
    *,
    search: Optional[str] = None,
    sort: str = "total",
    descending: bool = True,
    min_balance: Optional[Decimal] = None,
    limit: int = 500,
) -> dict:
    """One row per user holding a wallet, with each balance and the date
    they last moved money."""
    limit = max(1, min(limit, 2000))

    last_activity = (
        select(
            Wallet.user_id.label("user_id"),
            func.max(WalletLedgerEntry.created_at).label("last_activity"),
        )
        .join(WalletLedgerEntry, WalletLedgerEntry.wallet_id == Wallet.id)
        .group_by(Wallet.user_id)
        .subquery()
    )

    default_sum = func.coalesce(func.sum(Wallet.balance).filter(Wallet.wallet_type == WalletType.DEFAULT), 0)
    reward_sum = func.coalesce(func.sum(Wallet.balance).filter(Wallet.wallet_type == WalletType.REWARD), 0)
    commission_sum = func.coalesce(func.sum(Wallet.balance).filter(Wallet.wallet_type == WalletType.COMMISSION), 0)
    total_sum = func.coalesce(func.sum(Wallet.balance), 0)

    stmt = (
        select(
            User,
            default_sum.label("default_balance"),
            reward_sum.label("reward_balance"),
            commission_sum.label("commission_balance"),
            total_sum.label("total_balance"),
            last_activity.c.last_activity,
        )
        .join(Wallet, Wallet.user_id == User.id)
        .outerjoin(last_activity, last_activity.c.user_id == User.id)
        .group_by(User.id, last_activity.c.last_activity)
    )

    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(User.email.ilike(term), User.username.ilike(term),
                User.full_name.ilike(term), User.phone.ilike(term))
        )
    if min_balance is not None:
        stmt = stmt.having(total_sum >= min_balance)

    # Ordering has to happen in SQL, BEFORE the limit. Sorting in Python
    # afterwards silently reorders only whichever rows the database
    # happened to return, so "the ten largest balances" would be the ten
    # largest of an arbitrary slice - wrong in exactly the case the sort
    # exists for, and invisible until there are more holders than `limit`.
    order_exprs = {
        "total": total_sum,
        "default": default_sum,
        "reward": reward_sum,
        "commission": commission_sum,
        "name": func.coalesce(User.full_name, User.username),
        "email": User.email,
        "created": User.created_at,
        "last_activity": last_activity.c.last_activity,
    }
    order_by = order_exprs.get(sort, total_sum)
    stmt = stmt.order_by(order_by.desc() if descending else order_by.asc(), User.id.asc())

    rows = (await db.execute(stmt.limit(limit))).all()

    items = []
    for user, default_b, reward_b, commission_b, total_b, last_act in rows:
        items.append({
            "user_id": user.id,
            "customer_name": user.full_name or user.username,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.value,
            "status": user.status.value,
            "default_balance": str(Decimal(str(default_b)).quantize(Decimal("0.01"))),
            "reward_balance": str(Decimal(str(reward_b)).quantize(Decimal("0.01"))),
            "commission_balance": str(Decimal(str(commission_b)).quantize(Decimal("0.01"))),
            "total_balance": str(Decimal(str(total_b)).quantize(Decimal("0.01"))),
            "last_activity": fmt_bd(last_act) if last_act else None,
            "last_activity_iso": last_act.isoformat() if last_act else "",
            "created_at": fmt_bd(user.created_at) if user.created_at else None,
            "created_at_iso": user.created_at.isoformat() if user.created_at else "",
        })

    def _sum(field: str) -> str:
        return str(sum((Decimal(i[field]) for i in items), Decimal("0")).quantize(Decimal("0.01")))

    return {
        "items": items,
        "summary": {
            "wallet_holders": len(items),
            # Reported apart on purpose - only the cash column is money the
            # business could actually be asked to hand back.
            "total_default_eur": _sum("default_balance"),
            "total_reward_eur": _sum("reward_balance"),
            "total_commission_eur": _sum("commission_balance"),
            "total_all_eur": _sum("total_balance"),
            "sorted_by": sort if sort in SORTABLE else "total",
            "descending": descending,
        },
    }

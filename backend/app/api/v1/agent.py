"""The agent's own portal: their merchants, what those merchants sold, and
what the agent earned on it.

Access is gated on an APPROVED AgentProfile rather than on User.role, because
an agent can also be a merchant and a single role column can't say both.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.agent import AgentProfile, AgentStatus, DEFAULT_AGENT_COMMISSION_PCT
from app.models.catalog import Country, Product
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.models.wallet import LedgerRefType, Wallet, WalletLedgerEntry, WalletType
from app.services import agent_svc, finance_svc
from app.services.audit_svc import AuditService
from app.services.ledger_svc import LedgerService

router = APIRouter(prefix="/agent", tags=["Agent Portal"])

MONEY = Decimal("0.0001")


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(MONEY))


@dataclass
class AgentContext:
    user: User
    agent: AgentProfile


async def get_current_agent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentContext:
    profile = await agent_svc.approved_profile_for(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=403, detail="An approved agent account is required")
    return AgentContext(user=current_user, agent=profile)


class AgentApplicationRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    contact_phone: str = Field(..., min_length=5, max_length=50)


class AddMerchantRequest(BaseModel):
    # Email or username of an existing partner who has no agent yet.
    merchant: str = Field(..., min_length=3, max_length=255)


@router.get("/status")
async def my_agent_status(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Whether this account is an agent, and if not whether it could apply.
    Drives the agent entry point in the UI without a 403 round-trip."""
    profile = (await db.execute(
        select(AgentProfile).where(AgentProfile.user_id == current_user.id)
    )).scalar_one_or_none()
    return {
        "is_agent": bool(profile and profile.status == AgentStatus.APPROVED),
        "status": profile.status.value if profile else None,
        "rejection_reason": profile.rejection_reason if profile else None,
        "agent_code": profile.agent_code if profile and profile.status == AgentStatus.APPROVED else None,
        "commission_rate_pct": str(profile.commission_rate_pct) if profile else DEFAULT_AGENT_COMMISSION_PCT,
        "can_apply": profile is None and current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN),
    }


@router.post("/apply")
async def apply_as_agent(
    req: AgentApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_svc.can_become_agent(db, current_user)
        code = await agent_svc.new_agent_code(db)
    except agent_svc.AgentError as e:
        raise HTTPException(status_code=400, detail=str(e))

    profile = AgentProfile(
        user_id=current_user.id,
        company_name=req.company_name.strip(),
        contact_phone=req.contact_phone.strip(),
        agent_code=code,
        commission_rate_pct=Decimal(DEFAULT_AGENT_COMMISSION_PCT),
        status=AgentStatus.PENDING,
    )
    db.add(profile)
    await db.commit()
    return {"status": "success", "message": "Application submitted for review", "agent_status": "PENDING"}


@router.get("/overview")
async def agent_overview(ctx: AgentContext = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    merchant_ids = (await db.execute(
        select(MerchantProfile.user_id).where(MerchantProfile.agent_id == ctx.user.id)
    )).scalars().all()

    completed = Order.status == OrderStatus.COMPLETED
    # Earnings are read from the orders, not from the wallet: the wallet also
    # holds this user's own merchant commission if they are a merchant too.
    totals = (await db.execute(
        select(
            func.count(Order.id).filter(completed),
            func.coalesce(func.sum(Order.total_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.agent_commission_amount).filter(completed), 0),
        ).where(Order.agent_id == ctx.user.id)
    )).one()

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = (await db.execute(
        select(
            func.count(Order.id).filter(completed),
            func.coalesce(func.sum(Order.agent_commission_amount).filter(completed), 0),
        ).where(Order.agent_id == ctx.user.id, Order.created_at >= month_start)
    )).one()

    commission_wallet = await LedgerService.get_wallet(db, ctx.user.id, WalletType.COMMISSION)
    default_wallet = await LedgerService.get_wallet(db, ctx.user.id, WalletType.DEFAULT)

    return {
        "agent": {
            "company_name": ctx.agent.company_name,
            "agent_code": ctx.agent.agent_code,
            "commission_rate_pct": str(ctx.agent.commission_rate_pct),
            "status": ctx.agent.status.value,
        },
        "merchants": len(merchant_ids),
        "sales": {
            "orders": totals[0],
            "volume": _money(totals[1]),
            "commission": _money(totals[2]),
        },
        "this_month": {"orders": this_month[0], "commission": _money(this_month[1])},
        "wallets": {
            "commission_balance": _money(commission_wallet.balance if commission_wallet else 0),
            "wallet_balance": _money(default_wallet.balance if default_wallet else 0),
        },
        "currency": settings.BASE_CURRENCY,
    }


@router.get("/merchants")
async def my_merchants(ctx: AgentContext = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    completed = Order.status == OrderStatus.COMPLETED
    rows = (await db.execute(
        select(MerchantProfile, User).join(User, MerchantProfile.user_id == User.id)
        .where(MerchantProfile.agent_id == ctx.user.id)
        .order_by(MerchantProfile.created_at.desc())
    )).all()

    out = []
    for profile, user in rows:
        stats = (await db.execute(
            select(
                func.count(Order.id).filter(completed),
                func.coalesce(func.sum(Order.total_amount).filter(completed), 0),
                func.coalesce(func.sum(Order.agent_commission_amount).filter(completed), 0),
            ).where(Order.buyer_id == user.id, Order.is_reseller_order == True)  # noqa: E712
        )).one()
        out.append({
            "merchant_id": profile.id,
            "business_name": profile.business_name,
            "username": user.username,
            "email": user.email,
            "status": profile.status.value,
            "joined_at": profile.created_at,
            "orders": stats[0],
            "volume": _money(stats[1]),
            "my_commission": _money(stats[2]),
        })
    return out


@router.post("/merchants")
async def add_merchant(
    req: AddMerchantRequest,
    request: Request,
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Claims a partner who has no agent yet. A partner already mapped to
    another agent is never taken over here - only an admin can move one - and
    every claim is audit-logged with who made it."""
    needle = req.merchant.strip().lower()
    target = (await db.execute(
        select(MerchantProfile, User).join(User, MerchantProfile.user_id == User.id).where(
            or_(func.lower(User.email) == needle, func.lower(User.username) == needle)
        )
    )).first()
    if not target:
        raise HTTPException(status_code=404, detail="No partner found with that email or username.")

    profile, user = target
    if profile.user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You can't add your own partner account.")
    if profile.agent_id == ctx.user.id:
        raise HTTPException(status_code=400, detail=f"{profile.business_name} is already one of yours.")
    if profile.agent_id:
        raise HTTPException(
            status_code=400,
            detail="That partner already has an agent. Ask an admin if it should be moved.",
        )

    profile.agent_id = ctx.user.id
    await AuditService.log_action(
        db, actor_id=ctx.user.id, actor_role=ctx.user.role.value,
        action="AGENT_CLAIMED_MERCHANT",
        after_state={
            "agent_user_id": ctx.user.id, "agent_code": ctx.agent.agent_code,
            "merchant_id": profile.id, "merchant_user_id": profile.user_id,
            "business_name": profile.business_name,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {
        "status": "success",
        "message": f"{profile.business_name} is now mapped to you. Commission applies to their future sales.",
    }


@router.get("/orders")
async def my_commission_orders(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Every sale this agent earned on. Reads Order.agent_id, which was
    snapshotted at delivery - so a later mapping change never rewrites it."""
    total = (await db.execute(
        select(func.count(Order.id)).where(Order.agent_id == ctx.user.id)
    )).scalar() or 0

    rows = (await db.execute(
        select(Order, Product.title_en, Country.iso2, User.username)
        .join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .join(User, Order.buyer_id == User.id)
        .where(Order.agent_id == ctx.user.id)
        .order_by(Order.created_at.desc())
        .limit(limit).offset(offset)
    )).all()

    return {
        "total": total,
        "currency": settings.BASE_CURRENCY,
        "rows": [
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "merchant": merchant_username,
                "product": title,
                "country_iso2": iso2,
                "amount": _money(order.total_amount),
                "merchant_commission": _money(order.reseller_commission_amount),
                "my_commission": _money(order.agent_commission_amount),
                "status": order.status.value,
                "created_at": order.created_at,
            }
            for order, title, iso2, merchant_username in rows
        ],
    }


@router.get("/commission-ledger")
async def my_commission_ledger(
    limit: int = Query(100, ge=1, le=500),
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    wallet = await LedgerService.get_wallet(db, ctx.user.id, WalletType.COMMISSION)
    if not wallet:
        return {"balance": "0.0000", "entries": []}
    entries = (await db.execute(
        select(WalletLedgerEntry)
        .where(WalletLedgerEntry.wallet_id == wallet.id)
        .order_by(WalletLedgerEntry.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return {
        "balance": _money(wallet.balance),
        "entries": [
            {
                "id": e.id,
                "tx_type": e.tx_type.value,
                "amount": _money(e.amount),
                "balance_after": _money(e.balance_after),
                "reference_type": e.reference_type.value,
                "description": e.description,
                "created_at": e.created_at,
            }
            for e in entries
        ],
    }


def _statement_month(month: Optional[str]):
    try:
        return finance_svc.month_bounds(month) if month else finance_svc.month_bounds(
            datetime.now(timezone.utc).strftime("%Y-%m")
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/statement")
async def my_monthly_statement(
    month: Optional[str] = None,
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Same shape as the merchant statement, so the frontend reuses one view."""
    start, end = _statement_month(month)
    statement = await finance_svc.merchant_statement(db, ctx.user.id, start, end)
    if not statement:
        raise HTTPException(status_code=404, detail="No statement available")
    return statement


@router.get("/statement.csv")
async def my_monthly_statement_csv(
    month: Optional[str] = None,
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    start, end = _statement_month(month)
    statement = await finance_svc.merchant_statement(db, ctx.user.id, start, end)
    if not statement:
        raise HTTPException(status_code=404, detail="No statement available")
    filename = f"agent-statement-{statement['period']['month']}.csv"
    return Response(
        content=finance_svc.statement_csv(statement),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/commission/transfer")
async def transfer_commission(
    request: Request,
    ctx: AgentContext = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Moves the whole commission balance into the main wallet, where it can
    be spent or withdrawn. Same two-leg ledger move the merchant portal uses,
    so an agent's cash-out goes through the Phase 1 withdrawal flow."""
    source = (await db.execute(
        select(Wallet).where(
            Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.COMMISSION
        ).with_for_update()
    )).scalar_one_or_none()
    amount = Decimal(str(source.balance)) if source else Decimal("0")
    if not source or amount <= 0:
        raise HTTPException(status_code=400, detail="There's no commission to move.")

    destination = await LedgerService.get_wallet(db, ctx.user.id, WalletType.DEFAULT)
    if not destination:
        raise HTTPException(status_code=400, detail="No main wallet found for this account.")

    marker = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    await LedgerService.debit(
        db, source.id, amount, LedgerRefType.COMMISSION_TRANSFER, ref_id=ctx.user.id,
        description="Agent commission moved to main wallet",
        idempotency_key=f"agent-commission-out-{ctx.user.id}-{marker}",
    )
    await LedgerService.credit(
        db, destination.id, amount, LedgerRefType.COMMISSION_TRANSFER, ref_id=ctx.user.id,
        description="Agent commission moved from commission balance",
        idempotency_key=f"agent-commission-in-{ctx.user.id}-{marker}",
    )
    await AuditService.log_action(
        db, actor_id=ctx.user.id, actor_role=ctx.user.role.value,
        action="AGENT_COMMISSION_TRANSFER", after_state={"amount": str(amount)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"status": "success", "transferred": _money(amount)}

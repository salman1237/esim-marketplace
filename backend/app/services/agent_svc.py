"""Agents: codes, the merchant mapping, and the margin arithmetic.

Agent commission is a percentage of the product PRICE, which is what the
client chose, and it is paid on top of the merchant's own commission. Both
therefore come out of the same margin, so margin_check() exists to make that
visible before an admin sets a rate that gives away more than the sale earns.
"""
import secrets
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentProfile, AgentStatus
from app.models.merchant import MerchantProfile
from app.models.user import User, UserRole
from app.services.pricing_svc import get_selling_profit_pct

CODE_LENGTH = 6
# No 0/O/1/I/L: agent codes are read aloud and typed by hand onto an
# application form.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_AGENT_COMMISSION_PCT = Decimal("50.00")


class AgentError(Exception):
    """A rule the caller broke, surfaced as a 400 with this message."""


async def new_agent_code(db: AsyncSession) -> str:
    for _ in range(8):
        candidate = "AG" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        clash = (await db.execute(select(AgentProfile.id).where(AgentProfile.agent_code == candidate))).scalar_one_or_none()
        if not clash:
            return candidate
    raise AgentError("Could not allocate an agent code. Please try again.")


async def find_by_code(db: AsyncSession, raw_code: Optional[str]) -> Optional[AgentProfile]:
    code = (raw_code or "").strip().upper()
    if not code:
        return None
    res = await db.execute(select(AgentProfile).where(func.upper(AgentProfile.agent_code) == code))
    return res.scalar_one_or_none()


async def approved_profile_for(db: AsyncSession, user_id: str) -> Optional[AgentProfile]:
    """What gates the agent portal. Deliberately not a role check: an agent can
    also be a merchant, so the profile is the source of truth."""
    res = await db.execute(
        select(AgentProfile).where(
            AgentProfile.user_id == user_id, AgentProfile.status == AgentStatus.APPROVED
        )
    )
    return res.scalar_one_or_none()


async def commission_rate_for_merchant(db: AsyncSession, merchant: MerchantProfile) -> tuple[Optional[str], Decimal]:
    """(agent user id, rate %) for the merchant's agent, or (None, 0) when
    there isn't one, the mapping points at a non-agent, or the agent is no
    longer approved - a suspended agent stops earning immediately."""
    if not merchant.agent_id:
        return None, Decimal("0")
    profile = await approved_profile_for(db, merchant.agent_id)
    if not profile:
        return None, Decimal("0")
    return merchant.agent_id, Decimal(str(profile.commission_rate_pct))


async def margin_check(db: AsyncSession, merchant_pct: Decimal, agent_pct: Decimal) -> dict:
    """How much of a sale is left after both commissions.

    Prices are cost plus the selling profit %, so on a sale the margin is
    profit_pct / (100 + profit_pct) of the selling price. Both commissions are
    percentages of that same selling price, which is what makes them
    comparable here - and what makes it possible to configure a pair of rates
    that costs more than the sale earns.
    """
    profit_pct = Decimal(str(await get_selling_profit_pct(db)))
    margin_pct = (profit_pct / (Decimal("100") + profit_pct) * Decimal("100")).quantize(Decimal("0.01"))
    combined = (Decimal(str(merchant_pct)) + Decimal(str(agent_pct))).quantize(Decimal("0.01"))
    remaining = (margin_pct - combined).quantize(Decimal("0.01"))
    return {
        "selling_profit_pct": str(profit_pct),
        "margin_pct_of_price": str(margin_pct),
        "merchant_pct": str(Decimal(str(merchant_pct)).quantize(Decimal("0.01"))),
        "agent_pct": str(Decimal(str(agent_pct)).quantize(Decimal("0.01"))),
        "combined_pct": str(combined),
        "remaining_pct": str(remaining),
        "exceeds_margin": remaining < 0,
        "warning": (
            f"Merchant {combined}% of the sale price is more than the {margin_pct}% margin a sale earns — "
            f"each of these sales would lose money."
            if remaining < 0 else None
        ),
    }


def serialize(profile: AgentProfile, user: User, *, merchants: int = 0, stats: dict | None = None) -> dict:
    data = {
        "id": profile.id,
        "user_id": profile.user_id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "company_name": profile.company_name,
        "contact_phone": profile.contact_phone,
        "agent_code": profile.agent_code,
        "commission_rate_pct": str(profile.commission_rate_pct),
        "status": profile.status.value,
        "rejection_reason": profile.rejection_reason,
        "merchants": merchants,
        "created_at": profile.created_at,
        "reviewed_at": profile.reviewed_at,
    }
    if stats:
        data.update(stats)
    return data


async def merchant_count(db: AsyncSession, agent_user_id: str) -> int:
    res = await db.execute(
        select(func.count(MerchantProfile.id)).where(MerchantProfile.agent_id == agent_user_id)
    )
    return res.scalar() or 0


async def can_become_agent(db: AsyncSession, user: User) -> None:
    """Staff accounts are excluded: an admin earning agent commission on the
    platform's own merchants is a conflict, not a feature."""
    if user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise AgentError("Staff accounts can't be agents.")
    existing = (await db.execute(select(AgentProfile).where(AgentProfile.user_id == user.id))).scalar_one_or_none()
    if existing:
        raise AgentError("You've already applied to be an agent.")

"""Referral codes and reward granting.

Rewards are paid as promo credit into the REWARD wallet, never into the main
wallet. That is what makes the client's rule structural rather than a policy
note: withdrawal_svc only ever debits the DEFAULT wallet, so reward credit
cannot leave the platform as cash, while LedgerService.spend lets it pay for
an eSIM.

Each (referred user, event) pair can pay only once - the unique constraint on
referral_rewards enforces it, and the granting code treats a clash as "already
paid" rather than an error, so a retried registration or a re-fulfilled order
is harmless.
"""
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.referral import ReferralEvent, ReferralReward, ReferralRewardStatus
from app.models.user import User
from app.models.wallet import LedgerRefType, WalletType
from app.services.ledger_svc import LedgerService
from app.services.referral_settings_svc import event_amounts, get_referral_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CODE_LENGTH = 8
# No 0/O/1/I/L: these codes get read off a screen and typed by hand.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _random_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


async def ensure_referral_code(db: AsyncSession, user: User) -> str:
    """Gives `user` a code if they don't have one yet. Caller commits."""
    if user.referral_code:
        return user.referral_code
    for _ in range(6):
        candidate = _random_code()
        clash = (await db.execute(select(User.id).where(User.referral_code == candidate))).scalar_one_or_none()
        if not clash:
            user.referral_code = candidate
            return candidate
    # 31^8 possibilities; six clashes means something is very wrong, and a
    # missing code must not stop a registration.
    logger.warning("referral_code_generation_exhausted", user_id=user.id)
    return ""


async def find_referrer(db: AsyncSession, raw_code: Optional[str]) -> Optional[User]:
    code = (raw_code or "").strip().upper()
    if not code:
        return None
    res = await db.execute(select(User).where(func.upper(User.referral_code) == code))
    return res.scalar_one_or_none()


async def rewarded_referral_count(db: AsyncSession, referrer_id: str) -> int:
    """Distinct people this referrer has been paid for, ignoring reversals."""
    res = await db.execute(
        select(func.count(func.distinct(ReferralReward.referred_id))).where(
            ReferralReward.referrer_id == referrer_id,
            ReferralReward.status == ReferralRewardStatus.GRANTED,
        )
    )
    return res.scalar() or 0


async def grant(
    db: AsyncSession,
    referred: User,
    event: ReferralEvent,
    order_id: Optional[str] = None,
) -> Optional[ReferralReward]:
    """Pays this event's rewards, if the programme is on, the event is on, and
    it hasn't been paid for this person before. Returns the reward row, or None
    when nothing was due. Never raises for an ordinary "no reward" case - it is
    called from registration, fulfilment and merchant approval, none of which
    may fail because of a referral. Caller commits."""
    if not referred.referred_by_id or referred.referred_by_id == referred.id:
        return None

    cfg = await get_referral_settings(db)
    referrer_amount, referred_amount = event_amounts(cfg, event)
    if referrer_amount <= 0 and referred_amount <= 0:
        return None

    existing = (await db.execute(
        select(ReferralReward).where(
            ReferralReward.referred_id == referred.id, ReferralReward.event == event
        )
    )).scalar_one_or_none()
    if existing:
        return None

    referrer = (await db.execute(select(User).where(User.id == referred.referred_by_id))).scalar_one_or_none()
    if not referrer:
        return None

    cap = cfg["max_rewarded_referrals"]
    if cap is not None and referrer_amount > 0:
        # The cap limits what one referrer can be paid, not whether the person
        # they brought in gets their own welcome credit.
        if await rewarded_referral_count(db, referrer.id) >= cap:
            logger.info("referral_referrer_cap_reached", referrer_id=referrer.id, cap=cap)
            referrer_amount = Decimal("0")
            if referred_amount <= 0:
                return None

    reward = ReferralReward(
        referrer_id=referrer.id,
        referred_id=referred.id,
        event=event,
        referrer_amount=referrer_amount,
        referred_amount=referred_amount,
        order_id=order_id,
        status=ReferralRewardStatus.GRANTED,
    )
    db.add(reward)
    try:
        await db.flush()
    except IntegrityError:
        # Two triggers for the same event raced; the other one paid it.
        await db.rollback()
        return None

    label = event.value.replace("_", " ").lower()
    if referrer_amount > 0:
        wallet = await LedgerService.ensure_reward_wallet(db, referrer.id)
        await LedgerService.credit(
            db, wallet.id, referrer_amount, LedgerRefType.REWARD_EARNED, ref_id=reward.id,
            description=f"Referral reward — {referred.username} ({label})",
            idempotency_key=f"referral-referrer-{reward.id}",
        )
    if referred_amount > 0:
        wallet = await LedgerService.ensure_reward_wallet(db, referred.id)
        await LedgerService.credit(
            db, wallet.id, referred_amount, LedgerRefType.REWARD_EARNED, ref_id=reward.id,
            description=f"Welcome reward — referred by {referrer.username} ({label})",
            idempotency_key=f"referral-referred-{reward.id}",
        )

    return reward


async def reverse_for_order(db: AsyncSession, order_id: str, reason: str) -> Optional[ReferralReward]:
    """Claws back a first-purchase reward when that order is refunded.

    The credit may already be partly spent, so the debit is capped at whatever
    is left rather than forcing the wallet negative: recovering what we can is
    right, and a negative promo balance would silently block future spending
    for reasons the customer can't see. Caller commits."""
    reward = (await db.execute(
        select(ReferralReward).where(
            ReferralReward.order_id == order_id,
            ReferralReward.status == ReferralRewardStatus.GRANTED,
        )
    )).scalar_one_or_none()
    if not reward:
        return None

    reward.status = ReferralRewardStatus.REVERSED
    reward.reversal_reason = reason
    reward.reversed_at = datetime.now(timezone.utc)

    for user_id, amount, who in (
        (reward.referrer_id, Decimal(str(reward.referrer_amount)), "referrer"),
        (reward.referred_id, Decimal(str(reward.referred_amount)), "referred"),
    ):
        if amount <= 0:
            continue
        wallet = await LedgerService.ensure_reward_wallet(db, user_id)
        recoverable = min(amount, Decimal(str(wallet.balance)))
        if recoverable <= 0:
            logger.info("referral_reward_already_spent", reward_id=reward.id, side=who)
            continue
        await LedgerService.debit(
            db, wallet.id, recoverable, LedgerRefType.REWARD_REVERSED, ref_id=reward.id,
            description=f"Referral reward reversed — {reason}",
            idempotency_key=f"referral-reversed-{reward.id}-{who}",
        )

    return reward


async def my_summary(db: AsyncSession, user: User) -> dict:
    """Everything the "Refer & earn" page shows."""
    cfg = await get_referral_settings(db)
    reward_wallet = await LedgerService.get_wallet(db, user.id, WalletType.REWARD)

    joined = (await db.execute(
        select(User.id, User.username, User.created_at, User.role)
        .where(User.referred_by_id == user.id)
        .order_by(User.created_at.desc())
        .limit(100)
    )).all()

    rewards = (await db.execute(
        select(ReferralReward, User.username)
        .join(User, ReferralReward.referred_id == User.id)
        .where(ReferralReward.referrer_id == user.id)
        .order_by(ReferralReward.created_at.desc())
        .limit(100)
    )).all()

    earned = sum(
        (Decimal(str(r.referrer_amount)) for r, _ in rewards if r.status == ReferralRewardStatus.GRANTED),
        Decimal("0"),
    )

    return {
        "code": user.referral_code,
        "is_enabled": cfg["is_enabled"],
        "events": {
            event: {"referrer": str(a["referrer"]), "referred": str(a["referred"]), "enabled": a["enabled"]}
            for event, a in cfg["events"].items()
        },
        "promo_balance": str(Decimal(str(reward_wallet.balance)) if reward_wallet else Decimal("0")),
        "total_earned": str(earned),
        "referred_count": len(joined),
        "referred": [
            {"username": username, "joined_at": created_at, "role": role.value}
            for _, username, created_at, role in joined
        ],
        "rewards": [
            {
                "event": r.event.value,
                "referred_username": username,
                "amount": str(r.referrer_amount),
                "status": r.status.value,
                "created_at": r.created_at,
            }
            for r, username in rewards
        ],
    }

"""Automatic notification emails, and the copy that goes to the platform.

One branded template driven by a small registry, rather than a bespoke file
per event: there are ten events here and more coming, and a template each
would mean ten places to update when the layout changes. The bespoke emails
that genuinely differ - the welcome, the eSIM delivery with its QR code, the
withdrawal receipts - keep their own designs.

Every notice can carry a copy to the platform's system address (default
system@triptel.co), which is what the client asked for: all monetary activity
visible in one mailbox without anyone having to remember to CC it.

Context passed in here is always plain values, never ORM objects: these are
sent from background tasks with their own DB session, and a detached instance
would explode at render time rather than at the call site.
"""
import asyncio
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.settings import PlatformSetting

logger = get_logger(__name__)

SYSTEM_EMAIL_KEY = "system_notice_email"
DEFAULT_SYSTEM_EMAIL = "system@triptel.co"


async def get_system_email(db: AsyncSession) -> str:
    """Where the platform's own copy goes. Stored non-public: it is an
    internal mailbox and has no business in /settings/public."""
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == SYSTEM_EMAIL_KEY))
    row = res.scalar_one_or_none()
    value = (row.value if row else None) or DEFAULT_SYSTEM_EMAIL
    return str(value).strip() or DEFAULT_SYSTEM_EMAIL


async def set_system_email(db: AsyncSession, email: str, admin_id: str) -> dict:
    """Caller commits."""
    email = (email or "").strip()
    if "@" not in email or len(email) < 5:
        raise ValueError("Enter a valid email address")
    before = await get_system_email(db)
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == SYSTEM_EMAIL_KEY))
    row = res.scalar_one_or_none()
    if row:
        row.value = email
        row.is_public = False
        row.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=SYSTEM_EMAIL_KEY, value=email, is_public=False, updated_by_id=admin_id))
    return {"before": before, "after": email}


async def send_notice(
    db: AsyncSession,
    *,
    to: Optional[str],
    subject: str,
    title: str,
    intro: str,
    rows: Optional[Iterable[tuple]] = None,
    highlight: Optional[str] = None,
    highlight_label: Optional[str] = None,
    cta_label: Optional[str] = None,
    cta_path: Optional[str] = None,
    footnote: Optional[str] = None,
    copy_system: bool = True,
    system_intro: Optional[str] = None,
) -> None:
    """Sends one notice, plus the platform's copy when copy_system is set.

    Never raises: a notification must not be able to fail the thing it is
    reporting on. A missing SMTP config is already handled one level down.
    """
    from app.services.email_svc import EmailService  # local: email_svc imports settings-heavy deps

    rows = list(rows or [])
    cta_url = f"{settings.FRONTEND_BASE_URL}{cta_path}" if cta_path else None

    if to:
        try:
            await EmailService.send_notice(
                db, to, subject=subject, title=title, intro=intro, rows=rows,
                highlight=highlight, highlight_label=highlight_label,
                cta_label=cta_label, cta_url=cta_url, footnote=footnote,
            )
        except Exception as e:
            logger.warning("notice_send_failed", to=to, subject=subject, error=str(e))

    if not copy_system:
        return

    try:
        system_email = await get_system_email(db)
        # Don't send the same mail twice when the recipient IS the system box.
        if to and system_email.lower() == to.lower():
            return
        await EmailService.send_notice(
            db, system_email,
            subject=f"[Triptel] {subject}",
            title=title,
            intro=system_intro or intro,
            rows=rows, highlight=highlight, highlight_label=highlight_label,
            cta_label=None, cta_url=None,
            footnote="Automatic copy for the platform's records.",
        )
    except Exception as e:
        logger.warning("system_notice_send_failed", subject=subject, error=str(e))


def notify_background(**kwargs) -> None:
    """Fire-and-forget from a request handler. Opens its own session, because
    the request's closes as soon as the response is returned."""
    async def _run():
        async with AsyncSessionLocal() as db:
            await send_notice(db, **kwargs)

    task = asyncio.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# The event loop only holds weak references to tasks, so without this a notice
# can be garbage-collected before it is sent.
_tasks: set = set()


def _when(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%d %b %Y, %H:%M UTC")


# --- The events themselves -------------------------------------------------
# Each one is a thin wrapper so call sites read as what happened, not as email
# plumbing, and so the wording lives in one place.

def account_created(*, username: str, email: str, referred_by: Optional[str] = None) -> None:
    notify_background(
        to=None,  # the customer already gets the welcome email
        subject=f"New account — {username}",
        title="A new account was created",
        intro=f"{username} signed up.",
        rows=[("Username", username), ("Email", email), ("Referred by", referred_by or "—"), ("When", _when())],
    )


def merchant_applied(*, to: str, business_name: str, username: str, agent: Optional[str] = None) -> None:
    notify_background(
        to=to,
        subject=f"Partner application received — {business_name}",
        title="We've got your partner application",
        intro=(
            f"Thanks for applying to the B2B Partner Program as {business_name}. "
            "We'll review it and email you as soon as it's approved."
        ),
        rows=[("Business", business_name), ("Submitted", _when())],
        cta_label="Open the partner portal", cta_path="/reseller",
        system_intro=f"{username} applied as {business_name}" + (f", introduced by agent {agent}." if agent else "."),
    )


def agent_applied(*, to: str, company_name: str, username: str) -> None:
    notify_background(
        to=to,
        subject=f"Agent application received — {company_name}",
        title="We've got your agent application",
        intro=(
            f"Thanks for applying as an agent for {company_name}. Once approved you'll get your agent code "
            "and can start recruiting travel agencies."
        ),
        rows=[("Company", company_name), ("Submitted", _when())],
        cta_label="Open the agent portal", cta_path="/agent",
        system_intro=f"{username} applied to become an agent for {company_name}.",
    )


def agent_approved(*, to: str, company_name: str, agent_code: str, rate_pct: str, username: str) -> None:
    notify_background(
        to=to,
        subject=f"You're approved as an agent — {agent_code}",
        title="Your agent account is live",
        intro=(
            "You can now recruit travel agencies. Share your invite link and every eSIM they sell earns you "
            "commission."
        ),
        rows=[("Company", company_name), ("Agent code", agent_code), ("Commission", f"{rate_pct}% of each sale")],
        highlight=agent_code, highlight_label="Your agent code",
        cta_label="Open the agent portal", cta_path="/agent",
        system_intro=f"{username} was approved as an agent ({company_name}, code {agent_code}, {rate_pct}%).",
    )


def merchant_approved(*, to: str, business_name: str, rate_pct: str, username: str) -> None:
    notify_background(
        to=to,
        subject=f"You're approved as a partner — {business_name}",
        title="Your partner account is live",
        intro="You can now issue eSIMs to your customers from the partner dashboard or through our API.",
        rows=[("Business", business_name), ("Your commission", f"{rate_pct}% of each sale")],
        cta_label="Open the partner portal", cta_path="/reseller",
        system_intro=f"{username} was approved as a partner ({business_name}, {rate_pct}%).",
    )


def referral_used(*, to: str, referrer: str, joined: str, reward: Optional[str], currency: str) -> None:
    earned = f"{reward} {currency}" if reward and reward != "0" else None
    notify_background(
        to=to,
        subject=f"{joined} joined with your referral code",
        title="Someone used your referral code",
        intro=f"{joined} signed up with your code." + (" Your reward credit has been added." if earned else ""),
        rows=[("Who joined", joined), ("Your reward", earned or "—"), ("When", _when())],
        highlight=earned, highlight_label="Reward credit" if earned else None,
        cta_label="See your referrals", cta_path="/refer",
        system_intro=f"{joined} signed up using {referrer}'s referral code.",
    )


def agent_code_used(*, to: str, agent: str, business_name: str, applicant: str) -> None:
    notify_background(
        to=to,
        subject=f"{business_name} applied with your agent code",
        title="A travel agency used your agent code",
        intro=(
            f"{business_name} submitted a partner application with your code. Once an admin approves them, "
            "you'll earn on everything they sell."
        ),
        rows=[("Business", business_name), ("Applied", _when())],
        cta_label="Open the agent portal", cta_path="/agent",
        system_intro=f"{applicant} applied as {business_name} using agent {agent}'s code.",
    )


def referred_became_merchant(*, to: str, referrer: str, business_name: str, reward: Optional[str], currency: str) -> None:
    earned = f"{reward} {currency}" if reward and reward != "0" else None
    notify_background(
        to=to,
        subject=f"{business_name} became a partner",
        title="Someone you referred became a partner",
        intro=f"{business_name}, who joined with your referral code, has been approved as a partner."
              + (" Your reward credit has been added." if earned else ""),
        rows=[("Business", business_name), ("Your reward", earned or "—")],
        highlight=earned, highlight_label="Reward credit" if earned else None,
        cta_label="See your referrals", cta_path="/refer",
        system_intro=f"{business_name} (referred by {referrer}) was approved as a partner.",
    )


def transaction(*, order_no: str, buyer: str, product: str, amount: str, currency: str, method: str) -> None:
    """The platform's transaction alert. The customer already gets the eSIM
    delivery email with their QR code, so this copy is for the records."""
    notify_background(
        to=None,
        subject=f"Sale {order_no} — {amount} {currency}",
        title="An eSIM was sold",
        intro=f"{buyer} bought {product}.",
        rows=[
            ("Order", order_no), ("Customer", buyer), ("Product", product),
            ("Amount", f"{amount} {currency}"), ("Paid by", method), ("When", _when()),
        ],
        highlight=f"{amount} {currency}", highlight_label="Sale value",
    )

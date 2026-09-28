"""Transactional email (welcome, password reset, order confirmation).

Sending is deliberately best-effort: an unconfigured or failing SMTP
server logs a warning and returns rather than raising, so registration,
password-reset requests, and checkout never fail because email isn't
set up or is temporarily down.
"""
import io
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import aiosmtplib
import qrcode
from qrcode.image.pil import PilImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formatdate, make_msgid
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.timeutil import fmt_bd
from app.core.logging import get_logger
from app.models.settings import PlatformSetting
from app.services.esim_links import esim_install_links

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))


CURRENCY_SYMBOLS = {"EUR": "€", "BDT": "৳", "USD": "$", "GBP": "£"}


def money(amount, currency: str) -> str:
    """"€12.50" / "৳1,773.24" / "12.50 SAR" - readable in an email body,
    where a bare number next to a code reads as a template that failed."""
    value = Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{value:,.2f}"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper())
    return f"{symbol}{formatted}" if symbol else f"{formatted} {(currency or '').upper()}".strip()


class EmailService:
    @staticmethod
    async def _get_platform_name(db: AsyncSession) -> str:
        res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "platform_name"))
        row = res.scalar_one_or_none()
        return row.value if row and row.value else "eSIM Global"

    @staticmethod
    async def finance_notice_address(db: AsyncSession) -> str:
        """Where the platform's copy of a payout receipt goes: the same system
        mailbox every other monetary notice is copied to, so withdrawals are
        not the one thing sitting in a different inbox."""
        from app.services.notify_svc import get_system_email

        return await get_system_email(db)

    @staticmethod
    async def _logo_png(db: AsyncSession) -> bytes | None:
        """The uploaded brand logo, read off disk to be attached inline.
        The setting stores the public URL (/api/v1/uploads/branding/x.png)
        whose file lives under UPLOADS_DIR - a remote <img> would just be
        blocked by the mail client. Returns None (header falls back to the
        platform name as text) if no logo is set or the file is missing."""
        res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "logo_light"))
        row = res.scalar_one_or_none()
        if not row or not row.value:
            return None
        try:
            path = Path(settings.UPLOADS_DIR) / "branding" / Path(row.value).name
            return path.read_bytes() if path.is_file() else None
        except Exception as e:
            logger.warning("email_logo_read_failed", error=str(e))
            return None

    @staticmethod
    def _qr_png(payload: str) -> bytes | None:
        """QR image for an eSIM activation string. Returns None rather than
        raising: a missing QR must never stop the delivery email, which
        also carries the activation code as copyable text."""
        try:
            # Pin the PIL factory explicitly: without Pillow, qrcode falls
            # back to a pure-python PNG writer whose save() takes no format
            # kwarg. Pillow is a hard dependency here, so this is always
            # available and removes the guesswork.
            img = qrcode.make(payload, image_factory=PilImage)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning("qr_generation_failed", error=str(e))
            return None

    @staticmethod
    async def _send(
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
        inline_images: dict[str, bytes] | None = None,
    ) -> bool:
        if not settings.smtp_configured:
            logger.warning("email_skipped_smtp_not_configured", to=to_email, subject=subject)
            return False

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(text_body or "This email requires an HTML-capable client.", "plain", "utf-8"))
        alternative.attach(MIMEText(html_body, "html", "utf-8"))

        # Inline (cid:) images rather than remote <img src="https://...">,
        # which most clients block by default and which scores worse for
        # spam. The nesting matters: multipart/related must WRAP the
        # alternative, not sit inside it - Gmail (the mobile app
        # especially) leaves cid: images as broken placeholders when
        # related is nested within alternative, even though the part is
        # present and correctly marked inline. EmailMessage can't express
        # that nesting (make_related() refuses to convert an existing
        # alternative), hence the explicit tree here.
        if inline_images:
            message = MIMEMultipart("related")
            message.attach(alternative)
            for cid, data in inline_images.items():
                image = MIMEImage(data, _subtype="png")
                image.add_header("Content-ID", f"<{cid}>")
                image.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
                message.attach(image)
        else:
            message = alternative

        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = subject
        # Absent Date/Message-ID headers are a spam signal on their own, and
        # nothing downstream is guaranteed to add them for us.
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=settings.SMTP_FROM_EMAIL.split("@")[-1] or None)

        # Port 465 is implicit TLS (SMTPS): the connection is encrypted from
        # the first byte and there is no STARTTLS command to issue. Port 587
        # is the opposite - it opens in the clear and upgrades via STARTTLS.
        # Passing start_tls=True on 465 makes the handshake hang until the
        # timeout, so the two are selected here rather than conflated under
        # one "use TLS" flag.
        implicit_tls = settings.SMTP_PORT == 465
        try:
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=implicit_tls,
                start_tls=False if implicit_tls else settings.SMTP_USE_TLS,
                timeout=20,
            )
            logger.info("email_sent", to=to_email, subject=subject)
            return True
        except Exception as e:
            logger.warning("email_send_failed", to=to_email, subject=subject, error=str(e))
            return False

    @classmethod
    async def send_welcome(cls, db: AsyncSession, to_email: str, username: str):
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        html = _env.get_template("welcome.html").render(
            has_logo=logo_png is not None,
            platform_name=platform_name, username=username,
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        await cls._send(to_email, f"Welcome to {platform_name}", html,
                        inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_password_reset(cls, db: AsyncSession, to_email: str, reset_token: str):
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        reset_url = f"{settings.FRONTEND_BASE_URL}/auth/reset-password?token={reset_token}"
        html = _env.get_template("password_reset.html").render(
            platform_name=platform_name, reset_url=reset_url, has_logo=logo_png is not None,
            year=datetime.now(timezone.utc).year,
        )
        await cls._send(to_email, f"Reset your {platform_name} password", html,
                        inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_notice(
        cls, db: AsyncSession, to_email: str, *, subject: str, title: str, intro: str,
        rows=None, highlight=None, highlight_label=None, cta_label=None, cta_url=None, footnote=None,
    ):
        """The generic branded notice used by notify_svc. Everything that is
        not a welcome, an eSIM delivery or a withdrawal receipt goes through
        this, so the layout lives in one template."""
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        rows = list(rows or [])
        html = _env.get_template("notice.html").render(
            platform_name=platform_name, has_logo=logo_png is not None,
            title=title, intro=intro, rows=rows,
            highlight=highlight, highlight_label=highlight_label,
            cta_label=cta_label, cta_url=cta_url, footnote=footnote,
            year=datetime.now(timezone.utc).year,
        )
        text_rows = "\n".join(f"{label}: {value}" for label, value in rows)
        text = f"{title}\n\n{intro}\n\n{text_rows}\n" + (f"\n{cta_url}\n" if cta_url else "")
        await cls._send(to_email, subject, html, text_body=text,
                        inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_withdrawal_requested(cls, db: AsyncSession, to_email: str, withdrawal: dict, processing_time: str):
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        details = [
            ("Reference", withdrawal["reference_no"]),
            ("Requested", money(withdrawal["amount"], withdrawal["base_currency"])),
        ]
        if Decimal(str(withdrawal["fee_amount"])) > 0:
            details.append(("Processing fee", f"- {money(withdrawal['fee_amount'], withdrawal['base_currency'])}"))
        details.extend([
            ("You will receive", money(withdrawal["net_amount"], withdrawal["base_currency"])),
            ("Paid to", withdrawal["account_line"]),
            ("Requested on", withdrawal["created_display"]),
        ])
        html = _env.get_template("withdrawal_requested.html").render(
            platform_name=platform_name, has_logo=logo_png is not None, details=details,
            processing_time=processing_time, payout_currency=withdrawal["payout_currency"],
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        text = (
            f"Withdrawal request {withdrawal['reference_no']} received.\n"
            f"Requested: {money(withdrawal['amount'], withdrawal['base_currency'])}\n"
            f"You will receive: {money(withdrawal['net_amount'], withdrawal['base_currency'])}\n"
            f"Paid to: {withdrawal['account_line']}\n"
            f"Expected processing time: {processing_time}\n"
        )
        await cls._send(to_email, f"Withdrawal request received — {withdrawal['reference_no']}", html,
                        text_body=text, inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_withdrawal_paid(
        cls, db: AsyncSession, to_email: str, withdrawal: dict, processing_time: str, for_admin: bool = False
    ):
        """The receipt. Sent to the user and, with for_admin=True, to the
        platform's finance address - the client asked for both copies to
        carry the conversion rate and amounts."""
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        base = withdrawal["base_currency"]
        payout_display = money(withdrawal["payout_amount"], withdrawal["payout_currency"])
        details = [
            ("Reference", withdrawal["reference_no"]),
            ("Withdrawn from wallet", money(withdrawal["amount"], base)),
        ]
        if Decimal(str(withdrawal["fee_amount"])) > 0:
            details.append(("Processing fee", f"- {money(withdrawal['fee_amount'], base)}"))
        details.extend([
            ("Net amount", money(withdrawal["net_amount"], base)),
            ("Conversion rate", f"1 {base} = {withdrawal['conversion_rate']} {withdrawal['payout_currency']}"),
            ("Amount sent", payout_display),
            ("Sent to", withdrawal["account_line"]),
            ("Payment reference", withdrawal["payment_reference"] or "—"),
            ("Requested on", withdrawal["created_display"]),
            ("Paid on", withdrawal["paid_display"]),
        ])
        html = _env.get_template("withdrawal_paid.html").render(
            platform_name=platform_name, has_logo=logo_png is not None, details=details,
            payout_display=payout_display, reference_no=withdrawal["reference_no"],
            withdrawal_id=withdrawal["id"], processing_time=processing_time, for_admin=for_admin,
            username=withdrawal.get("username"), user_email=withdrawal.get("user_email"),
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        text = "\n".join(f"{label}: {value}" for label, value in details)
        subject = (
            f"Withdrawal paid to {withdrawal.get('username')} — {withdrawal['reference_no']}" if for_admin
            else f"Your withdrawal has been paid — {withdrawal['reference_no']}"
        )
        await cls._send(to_email, subject, html, text_body=text,
                        inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_withdrawal_rejected(cls, db: AsyncSession, to_email: str, withdrawal: dict, reason: str | None):
        platform_name = await cls._get_platform_name(db)
        logo_png = await cls._logo_png(db)
        details = [
            ("Reference", withdrawal["reference_no"]),
            ("Amount returned", money(withdrawal["amount"], withdrawal["base_currency"])),
            ("Requested on", withdrawal["created_display"]),
        ]
        html = _env.get_template("withdrawal_rejected.html").render(
            platform_name=platform_name, has_logo=logo_png is not None, details=details,
            reference_no=withdrawal["reference_no"], reason=reason,
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        text = (
            f"Withdrawal {withdrawal['reference_no']} was not approved.\n"
            f"{money(withdrawal['amount'], withdrawal['base_currency'])} has been returned to your wallet.\n"
            + (f"Reason: {reason}\n" if reason else "")
        )
        await cls._send(to_email, f"Withdrawal not approved — {withdrawal['reference_no']}", html,
                        text_body=text, inline_images={"brand_logo": logo_png} if logo_png else None)

    @classmethod
    async def send_order_confirmation(
        cls,
        db: AsyncSession,
        to_email: str,
        order_no: str,
        product_title: str,
        iccid: str,
        lpa_string: str,
        validity_days: int | None = None,
        data_label: str | None = None,
        purchase_reference: str | None = None,
        purchased_at: datetime | None = None,
        status_url: str | None = None,
    ):
        platform_name = await cls._get_platform_name(db)
        qr_png = cls._qr_png(lpa_string) if lpa_string else None
        logo_png = await cls._logo_png(db)
        install = esim_install_links(lpa_string)

        # Only rows we actually have a value for - a table with blank cells
        # reads as a bug to the customer.
        details = [("Order ID", order_no), ("Product", product_title), ("ICCID", iccid)]
        if data_label:
            details.append(("Data", data_label))
        if validity_days:
            details.append(("Plan Validity", f"{validity_days} Days"))
        if purchase_reference:
            details.append(("Purchase ID", purchase_reference))
        if purchased_at:
            details.append(("Purchase Date", fmt_bd(purchased_at)))

        html = _env.get_template("order_confirmation.html").render(
            platform_name=platform_name, order_no=order_no, product_title=product_title,
            iccid=iccid, lpa_string=lpa_string, has_qr=qr_png is not None, details=details,
            has_logo=logo_png is not None, status_url=status_url, validity_days=validity_days,
            ios_install_url=install["ios"], android_install_url=install["android"],
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        detail_lines = "\n".join(f"{label}: {value}" for label, value in details)
        text = (
            f"Your eSIM for order {order_no} is ready.\n\n"
            f"{detail_lines}\n"
            f"Activation code (LPA): {lpa_string}\n\n"
            f"Install it by scanning the QR code in this email, or enter the activation "
            f"code manually in your phone's cellular settings.\n"
            + (f"\nTrack your data usage and expiry any time: {status_url}\n" if status_url else "")
            + f"{settings.FRONTEND_BASE_URL}/my-esims\n"
        )
        images = {}
        if qr_png:
            images["esim_qr"] = qr_png
        if logo_png:
            images["brand_logo"] = logo_png
        await cls._send(
            to_email,
            f"Your eSIM is ready — {order_no}",
            html,
            text_body=text,
            inline_images=images or None,
        )

"""Transactional email (welcome, password reset, order confirmation).

Sending is deliberately best-effort: an unconfigured or failing SMTP
server logs a warning and returns rather than raising, so registration,
password-reset requests, and checkout never fail because email isn't
set up or is temporarily down.
"""
import io
from datetime import datetime, timezone
from pathlib import Path
import aiosmtplib
import qrcode
from qrcode.image.pil import PilImage
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.logging import get_logger
from app.models.settings import PlatformSetting

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))


class EmailService:
    @staticmethod
    async def _get_platform_name(db: AsyncSession) -> str:
        res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "platform_name"))
        row = res.scalar_one_or_none()
        return row.value if row and row.value else "eSIM Global"

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

        message = EmailMessage()
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = subject
        # Absent Date/Message-ID headers are a spam signal on their own, and
        # nothing downstream is guaranteed to add them for us.
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=settings.SMTP_FROM_EMAIL.split("@")[-1] or None)
        message.set_content(text_body or "This email requires an HTML-capable client.")
        message.add_alternative(html_body, subtype="html")

        # Inline (cid:) images ride along inside the HTML part as
        # multipart/related. Remote <img src="https://..."> would be blocked
        # by default in most mail clients and scores worse for spam.
        if inline_images:
            html_part = message.get_payload()[-1]
            for cid, data in inline_images.items():
                html_part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>")

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
        html = _env.get_template("welcome.html").render(
            platform_name=platform_name, username=username,
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        await cls._send(to_email, f"Welcome to {platform_name}", html)

    @classmethod
    async def send_password_reset(cls, db: AsyncSession, to_email: str, reset_token: str):
        platform_name = await cls._get_platform_name(db)
        reset_url = f"{settings.FRONTEND_BASE_URL}/auth/reset-password?token={reset_token}"
        html = _env.get_template("password_reset.html").render(
            platform_name=platform_name, reset_url=reset_url, year=datetime.now(timezone.utc).year,
        )
        await cls._send(to_email, f"Reset your {platform_name} password", html)

    @classmethod
    async def send_order_confirmation(cls, db: AsyncSession, to_email: str, order_no: str, product_title: str, iccid: str, lpa_string: str):
        platform_name = await cls._get_platform_name(db)
        qr_png = cls._qr_png(lpa_string) if lpa_string else None

        html = _env.get_template("order_confirmation.html").render(
            platform_name=platform_name, order_no=order_no, product_title=product_title,
            iccid=iccid, lpa_string=lpa_string, has_qr=qr_png is not None,
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        text = (
            f"Your eSIM for order {order_no} is ready.\n\n"
            f"Plan: {product_title}\n"
            f"ICCID: {iccid}\n"
            f"Activation code (LPA): {lpa_string}\n\n"
            f"Install it by scanning the QR code in this email, or enter the activation "
            f"code manually in your phone's cellular settings.\n"
            f"{settings.FRONTEND_BASE_URL}/my-esims\n"
        )
        await cls._send(
            to_email,
            f"Your eSIM is ready — {order_no}",
            html,
            text_body=text,
            inline_images={"esim_qr": qr_png} if qr_png else None,
        )

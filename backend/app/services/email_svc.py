"""Transactional email (welcome, password reset, order confirmation).

Sending is deliberately best-effort: an unconfigured or failing SMTP
server logs a warning and returns rather than raising, so registration,
password-reset requests, and checkout never fail because email isn't
set up or is temporarily down.
"""
from datetime import datetime, timezone
from pathlib import Path
import aiosmtplib
from email.message import EmailMessage
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
    async def _send(to_email: str, subject: str, html_body: str) -> bool:
        if not settings.smtp_configured:
            logger.warning("email_skipped_smtp_not_configured", to=to_email, subject=subject)
            return False

        message = EmailMessage()
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content("This email requires an HTML-capable client.")
        message.add_alternative(html_body, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                start_tls=settings.SMTP_USE_TLS,
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
        html = _env.get_template("order_confirmation.html").render(
            platform_name=platform_name, order_no=order_no, product_title=product_title,
            iccid=iccid, lpa_string=lpa_string,
            frontend_base_url=settings.FRONTEND_BASE_URL, year=datetime.now(timezone.utc).year,
        )
        await cls._send(to_email, f"Your eSIM is ready — {order_no}", html)

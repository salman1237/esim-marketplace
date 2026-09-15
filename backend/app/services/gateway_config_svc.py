"""ShurjoPay credentials editable from the admin console.

A Super Admin-saved configuration (one private PlatformSetting, password
encrypted with secret_box) takes precedence; with none saved, the server's
SHURJOPAY_* environment settings are used exactly as before. The base URL
is never free text - only ShurjoPay's own live or sandbox host - so an
edited setting can't send the credentials anywhere else."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_box import decrypt_secret, encrypt_secret
from app.models.settings import PlatformSetting

SHURJOPAY_KEY = "shurjopay_config"
SHURJOPAY_HOSTS = {
    "live": "https://engine.shurjopayment.com",
    "sandbox": "https://sandbox.shurjopayment.com",
}
PREFIX_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")


@dataclass
class ShurjoPayConfig:
    base_url: str
    username: str
    password: str
    prefix: str
    source: str  # "admin" or "environment"

    @property
    def mode(self) -> str:
        return next((m for m, url in SHURJOPAY_HOSTS.items() if url == self.base_url.rstrip("/")), "custom")


def environment_config() -> ShurjoPayConfig:
    return ShurjoPayConfig(
        base_url=settings.SHURJOPAY_BASE_URL.rstrip("/"),
        username=settings.SHURJOPAY_USERNAME,
        password=settings.SHURJOPAY_PASSWORD,
        prefix=settings.SHURJOPAY_PREFIX,
        source="environment",
    )


async def _row(db: AsyncSession) -> Optional[PlatformSetting]:
    return (await db.execute(select(PlatformSetting).where(PlatformSetting.key == SHURJOPAY_KEY))).scalar_one_or_none()


def _saved_config(value) -> Optional[ShurjoPayConfig]:
    if not isinstance(value, dict) or value.get("mode") not in SHURJOPAY_HOSTS:
        return None
    password = decrypt_secret(value.get("password_encrypted"))
    if not (value.get("username") and password and value.get("prefix")):
        return None
    return ShurjoPayConfig(SHURJOPAY_HOSTS[value["mode"]], value["username"], password, value["prefix"], "admin")


async def get_shurjopay_config(db: AsyncSession) -> ShurjoPayConfig:
    row = await _row(db)
    return (_saved_config(row.value) if row else None) or environment_config()


async def describe_shurjopay_config(db: AsyncSession) -> dict:
    """What the admin console shows - never the password itself."""
    row = await _row(db)
    value = row.value if row and isinstance(row.value, dict) else None
    active = (_saved_config(value) if value else None) or environment_config()
    env = environment_config()
    return {
        "source": active.source,
        "mode": active.mode,
        "base_url": active.base_url,
        "username": active.username,
        "prefix": active.prefix,
        "password_set": bool(active.password),
        # Saved by an admin but no longer decryptable (SECRET_KEY changed) -
        # the server settings are in use until the password is re-entered.
        "saved_password_unreadable": bool(value and value.get("password_encrypted") and not decrypt_secret(value["password_encrypted"])),
        "updated_at": value.get("updated_at") if value else None,
        "environment": {"mode": env.mode, "username": env.username, "prefix": env.prefix},
        "urls": {
            "return_url": settings.SHURJOPAY_RETURN_URL,
            "cancel_url": settings.SHURJOPAY_CANCEL_URL,
            "ipn_url": settings.SHURJOPAY_RETURN_URL.rsplit("/callback", 1)[0] + "/ipn",
        },
    }


def validate_fields(mode: str, username: str, prefix: str) -> None:
    if mode not in SHURJOPAY_HOSTS:
        raise ValueError("mode must be 'live' or 'sandbox'")
    if not username.strip() or len(username.strip()) > 100:
        raise ValueError("Username is required")
    if not PREFIX_RE.match(prefix.strip()):
        raise ValueError("Store code must be 2-10 letters or digits")


async def candidate_config(db: AsyncSession, mode: str, username: str, password: Optional[str], prefix: str) -> ShurjoPayConfig:
    """Config built from form values; a blank password means 'keep the saved one'."""
    validate_fields(mode, username, prefix)
    if not password:
        row = await _row(db)
        saved = _saved_config(row.value) if row else None
        password = saved.password if saved else None
    if not password:
        raise ValueError("Password is required")
    return ShurjoPayConfig(SHURJOPAY_HOSTS[mode], username.strip(), password, prefix.strip().upper(), "admin")


async def save_shurjopay_config(db: AsyncSession, config: ShurjoPayConfig, admin_id: str) -> dict:
    """Returns the audit-safe before/after (no password). Caller commits."""
    row = await _row(db)
    before = {k: v for k, v in (row.value or {}).items() if k != "password_encrypted"} if row and isinstance(row.value, dict) else None
    previous_password = _saved_config(row.value).password if row and _saved_config(row.value) else None
    value = {
        "mode": config.mode,
        "username": config.username,
        "prefix": config.prefix,
        "password_encrypted": encrypt_secret(config.password),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if row:
        row.value = value
        row.is_public = False
        row.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=SHURJOPAY_KEY, value=value, is_public=False, updated_by_id=admin_id))
    after = {k: v for k, v in value.items() if k != "password_encrypted"}
    after["password_changed"] = previous_password != config.password
    return {"before": before, "after": after}


async def clear_shurjopay_config(db: AsyncSession) -> bool:
    row = await _row(db)
    if row:
        await db.delete(row)
    return row is not None

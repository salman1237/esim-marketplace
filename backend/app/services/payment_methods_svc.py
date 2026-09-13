"""Manual-deposit payment methods (bKash/Nagad/bank/Bangla QR accounts).

Stored as one public JSON PlatformSetting so the Super Admin can change an
account number without a redeploy, and the wallet page reads it straight
from /settings/public. No migration: same key-value table as branding."""
import re
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSetting
from app.schemas.settings import PaymentMethodConfig

PAYMENT_METHODS_KEY = "payment_methods"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "method"


def parse_payment_methods(raw) -> List[PaymentMethodConfig]:
    """Tolerant read - a malformed row is skipped rather than taking the
    public settings endpoint (and so every page) down with it."""
    methods = []
    for item in raw if isinstance(raw, list) else []:
        try:
            methods.append(PaymentMethodConfig.model_validate(item))
        except Exception:
            continue
    return methods


async def get_payment_methods(db: AsyncSession, active_only: bool = False) -> List[PaymentMethodConfig]:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == PAYMENT_METHODS_KEY))
    setting = res.scalar_one_or_none()
    methods = parse_payment_methods(setting.value if setting else None)
    return [m for m in methods if m.is_active] if active_only else methods


def normalize_payment_methods(methods: List[PaymentMethodConfig]) -> List[PaymentMethodConfig]:
    """Trims fields, assigns stable unique ids, and rejects duplicate names
    (the name is what a deposit request records, so it must be unambiguous)."""
    seen_names, seen_ids, out = set(), set(), []
    for m in methods:
        name = m.name.strip()
        if not name:
            raise ValueError("Every payment method needs a name")
        if name.lower() in seen_names:
            raise ValueError(f"Duplicate payment method name: {name}")
        seen_names.add(name.lower())

        base = _slug(m.id or name)
        mid, n = base, 2
        while mid in seen_ids:
            mid, n = f"{base}-{n}", n + 1
        seen_ids.add(mid)

        out.append(m.model_copy(update={
            "id": mid,
            "name": name,
            "account_name": (m.account_name or "").strip() or None,
            "account_number": (m.account_number or "").strip() or None,
            "branch": (m.branch or "").strip() or None,
            "instructions": (m.instructions or "").strip() or None,
        }))
    return out


async def set_payment_methods(db: AsyncSession, methods: List[PaymentMethodConfig], admin_id: str):
    """Returns (before, after) as plain lists for the audit log. Caller commits."""
    after = [m.model_dump() for m in normalize_payment_methods(methods)]
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == PAYMENT_METHODS_KEY))
    setting = res.scalar_one_or_none()
    before = setting.value if setting else []
    if setting:
        setting.value = after
        setting.is_public = True
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=PAYMENT_METHODS_KEY, value=after, is_public=True, updated_by_id=admin_id))
    return before, after

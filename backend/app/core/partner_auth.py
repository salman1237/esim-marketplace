import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.partner_api import ApiKey
from app.models.merchant import MerchantProfile
from app.models.user import User


@dataclass
class PartnerContext:
    api_key: ApiKey
    merchant: MerchantProfile
    user: User


async def get_current_partner(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> PartnerContext:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    res = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = res.scalar_one_or_none()
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == api_key.merchant_id))
    merchant = m_res.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    u_res = await db.execute(select(User).where(User.id == merchant.user_id))
    user = u_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return PartnerContext(api_key=api_key, merchant=merchant, user=user)

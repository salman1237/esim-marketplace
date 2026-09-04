import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.partner_api import ApiKey
from app.models.merchant import MerchantProfile
from app.models.user import User

# Distinguishes a partner access token from a regular user session JWT -
# both are signed with the same SECRET_KEY, so this claim is what stops
# either one from being replayed against the other's endpoints. Never a
# real UserRole value.
PARTNER_TOKEN_ROLE = "PARTNER_API"

# Points Swagger/OpenAPI at the token-exchange endpoint rather than the
# user login route get_current_user's oauth2_scheme uses.
partner_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/partner/auth/token", auto_error=False)


@dataclass
class PartnerContext:
    api_key: ApiKey
    merchant: MerchantProfile
    user: User


async def authenticate_partner_api_key(raw_key: str, db: AsyncSession) -> ApiKey:
    """Validates a raw API key (the partner's long-lived credential) and
    returns the active ApiKey row. Used only by the token-exchange
    endpoint - the raw key itself is never accepted on any other route."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    res = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = res.scalar_one_or_none()
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
    return api_key


async def get_current_partner(
    token: str = Depends(partner_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> PartnerContext:
    """Resolves a partner's short-lived access token (obtained from POST
    /partner/auth/token) into their merchant/user context. The raw API
    key is never sent on these calls - only this token, which expires on
    its own and carries no more privilege than reading the ApiKey it was
    minted from."""
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired partner access token")
    if not token:
        raise unauthorized

    payload = decode_access_token(token)
    if not payload or payload.get("role") != PARTNER_TOKEN_ROLE:
        raise unauthorized

    api_key_id = payload.get("sub")
    if not api_key_id:
        raise unauthorized

    res = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = res.scalar_one_or_none()
    # Re-checked against the DB (not just trusting the JWT signature) so a
    # key revoked mid-flight stops working before the token's own expiry.
    if not api_key or not api_key.is_active:
        raise unauthorized

    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == api_key.merchant_id))
    merchant = m_res.scalar_one_or_none()
    if not merchant:
        raise unauthorized

    u_res = await db.execute(select(User).where(User.id == merchant.user_id))
    user = u_res.scalar_one_or_none()
    if not user:
        raise unauthorized

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return PartnerContext(api_key=api_key, merchant=merchant, user=user)

from typing import List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole, UserStatus

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception
    # A partner API access token (see app/core/partner_auth.py) is signed
    # with the same SECRET_KEY but must never authenticate as a regular
    # user - its "sub" is an ApiKey id, not a User id, and scoping it out
    # explicitly here means that isolation doesn't rely only on the two
    # id spaces happening not to collide.
    if payload.get("role") == "PARTNER_API":
        raise credentials_exception
    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception
    
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise credentials_exception
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return user

def require_roles(allowed_roles: List[UserRole]):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {[r.value for r in allowed_roles]}"
            )
        return current_user
    return role_checker


async def require_password_changed(current_user: User = Depends(get_current_user)) -> User:
    """Blocks the money paths for an account whose password is still the
    one a merchant was given to hand over.

    Forcing the change in the browser alone would be theatre: the phone
    number is often public, and anyone who guessed it could simply call
    the API directly. So the credential signs them in and lets them look
    at what was bought for them, and nothing that moves money works until
    they have chosen their own password.
    """
    if getattr(current_user, "must_change_password", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please set your own password before buying or moving money.",
        )
    return current_user

require_super_admin = require_roles([UserRole.SUPER_ADMIN])
require_admin = require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN])
require_merchant = require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT])
require_any_user = require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT, UserRole.USER])

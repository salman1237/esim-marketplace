"""Checking a discount code before paying.

The checkout popup calls this so the customer sees the new total before
committing. It is deliberately authenticated: several of the rules are
per-user (first purchase only, uses per user), so an anonymous check could
promise a discount that the actual checkout then refuses.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.catalog import Product
from app.services.supplier_settings_svc import get_enabled_suppliers, supplier_visible_filter
from app.models.user import User
from app.services import discount_svc

router = APIRouter(prefix="/discounts", tags=["Discount Codes"])


class DiscountCheckRequest(BaseModel):
    code: str


@router.post("/check")
async def check_discount_code(req: DiscountCheckRequest, db: AsyncSession = Depends(get_db)):
    """Unauthenticated, best-effort validity check so a visitor browsing
    without an account can see a code is real before being asked to sign in.
    Deliberately weaker than /preview: it can't see per-user rules (first
    purchase only, uses per user) or whether the code applies to a specific
    package, so checkout and /preview remain the authoritative answer."""
    return await discount_svc.check_generic(db, req.code)


class DiscountPreviewRequest(BaseModel):
    code: str
    product_id: str


@router.post("/preview")
async def preview_discount(
    req: DiscountPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = (await db.execute(
        select(Product).where(
            Product.id == req.product_id, Product.is_active == True,  # noqa: E712
            supplier_visible_filter(Product.supplier_reference, await get_enabled_suppliers(db)),
        )
    )).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    list_price = Decimal(str(product.retail_price))
    try:
        # No row lock here: this is a look, not a claim. The lock is taken at
        # checkout, which re-runs every rule - so a code that runs out in
        # between is refused there rather than being quietly honoured.
        code, amount = await discount_svc.validate(db, req.code, current_user, product, list_price)
    except discount_svc.DiscountError as e:
        # 200 with valid=false: a mistyped code is an expected answer for
        # this endpoint, not a client error the UI has to parse out of a body.
        return {"valid": False, "reason": str(e)}

    return {
        "valid": True,
        "code": code.code,
        "description": code.description,
        "discount_type": code.discount_type.value,
        "value": str(code.value),
        "discount_amount": str(amount),
        "list_price": str(list_price),
        "total": str(list_price - amount),
        "currency": settings.BASE_CURRENCY,
    }

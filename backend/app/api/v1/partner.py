from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.partner_auth import get_current_partner, PartnerContext
from app.models.catalog import Country, Product
from app.models.wallet import Wallet, WalletType
from app.schemas.catalog import CountryResponse, ProductResponse
from app.services.checkout_svc import get_effective_commission_rate

router = APIRouter(prefix="/partner", tags=["Partner API"])


@router.get("/countries", response_model=List[CountryResponse])
async def list_countries(
    search: Optional[str] = None,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    query = select(Country).where(Country.is_active == True)
    if search:
        query = query.where(Country.name_en.ilike(f"%{search}%") | Country.iso2.ilike(f"%{search}%"))
    query = query.order_by(Country.name_en.asc())
    res = await db.execute(query)
    return res.scalars().all()


@router.get("/countries/{iso2}/products", response_model=List[ProductResponse])
async def list_country_products(
    iso2: str,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    c_res = await db.execute(select(Country).where(Country.iso2 == iso2.upper()))
    country = c_res.scalar_one_or_none()
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")

    p_res = await db.execute(
        select(Product).where(Product.country_id == country.id, Product.is_active == True).order_by(Product.data_amount_gb.asc())
    )
    return p_res.scalars().all()


@router.get("/me")
async def get_partner_profile(
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    rate = await get_effective_commission_rate(db, ctx.user.id, ctx.merchant.commission_rate_pct)

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()

    return {
        "business_name": ctx.merchant.business_name,
        "commission_rate_pct": rate,
        "wallet_balance": wallet.balance if wallet else 0,
        "wallet_currency": wallet.currency if wallet else "USD",
        "webhook_configured": bool(ctx.merchant.webhook_url),
    }

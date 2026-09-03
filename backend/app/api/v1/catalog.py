from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.catalog import Country, Product
from app.schemas.catalog import CountryResponse, ProductResponse

router = APIRouter(prefix="/catalog", tags=["Catalog"])

@router.get("/countries", response_model=List[CountryResponse])
async def list_countries(
    search: Optional[str] = None,
    popular_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    query = select(Country).where(Country.is_active == True)
    if popular_only:
        query = query.where(Country.is_popular == True)
    if search:
        query = query.where(Country.name_en.ilike(f"%{search}%") | Country.iso2.ilike(f"%{search}%"))
    
    query = query.order_by(Country.name_en.asc())
    res = await db.execute(query)
    return res.scalars().all()

@router.get("/countries/{iso2}/products", response_model=List[ProductResponse])
async def list_country_products(iso2: str, db: AsyncSession = Depends(get_db)):
    c_res = await db.execute(select(Country).where(Country.iso2 == iso2.upper()))
    country = c_res.scalar_one_or_none()
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")

    p_res = await db.execute(
        select(Product).where(Product.country_id == country.id, Product.is_active == True).order_by(Product.data_amount_gb.asc())
    )
    return p_res.scalars().all()

@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

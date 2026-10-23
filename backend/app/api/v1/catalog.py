import re
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.catalog import Country, Product
from app.schemas.catalog import CountryResponse, DestinationResponse, ProductResponse
from app.services.supplier_settings_svc import get_enabled_suppliers, supplier_visible_filter

router = APIRouter(prefix="/catalog", tags=["Catalog"])


def country_slug(name: str) -> str:
    """"Bangladesh" -> "bangladesh", "United Arab Emirates" -> "united-arab-emirates"."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")

@router.get("/countries", response_model=List[CountryResponse])
async def list_countries(
    search: Optional[str] = None,
    popular_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    # Only destinations that actually have something to sell. VivaPe lists
    # ~250 countries but most have no eSIM inventory, and surfacing those
    # gave visitors a country tile that opened to an empty package list.
    enabled = await get_enabled_suppliers(db)
    has_products = (
        select(Product.id)
        .where(
            Product.country_id == Country.id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled),
        )
        .exists()
    )
    query = select(Country).where(Country.is_active == True, has_products)
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

    enabled = await get_enabled_suppliers(db)
    p_res = await db.execute(
        select(Product).where(
            Product.country_id == country.id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled),
        )
        # Cheapest first - what a traveler compares on; data amount breaks ties.
        .order_by(Product.retail_price.asc(), Product.data_amount_gb.asc())
    )
    return p_res.scalars().all()

@router.get("/destinations/{slug}", response_model=DestinationResponse)
async def get_destination(slug: str, db: AsyncSession = Depends(get_db)):
    """One shareable destination page in a single call - triptel.co/explore/bangladesh
    (or /explore/bd). Accepts the country name slug or its ISO2 code."""
    needle = (slug or "").strip().lower()
    if not needle:
        raise HTTPException(status_code=404, detail="Country not found")

    country = None
    # Exact code match first (iso2 is unique), then the name slug.
    if len(needle) <= 10:
        res = await db.execute(select(Country).where(Country.iso2 == needle.upper(), Country.is_active == True))
        country = res.scalar_one_or_none()
    if country is None:
        # Slug match. The catalog is a few hundred rows, so matching in
        # Python beats keeping a slug column in step with renames.
        res = await db.execute(select(Country).where(Country.is_active == True))
        country = next((c for c in res.scalars().all() if country_slug(c.name_en) == needle), None)
    if country is None:
        raise HTTPException(status_code=404, detail="Country not found")

    enabled = await get_enabled_suppliers(db)
    p_res = await db.execute(
        select(Product).where(
            Product.country_id == country.id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled),
        )
        .order_by(Product.retail_price.asc(), Product.data_amount_gb.asc())
    )
    return DestinationResponse(country=country, products=p_res.scalars().all())


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    enabled = await get_enabled_suppliers(db)
    res = await db.execute(
        select(Product).where(
            Product.id == product_id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled),
        )
    )
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

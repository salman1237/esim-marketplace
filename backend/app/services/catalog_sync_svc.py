"""Syncs the local catalog (countries + products) from VivaPe.

Extracted out of the /admin/catalog/sync endpoint so the same logic can
be called from a scheduled background job, not just an admin click.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.catalog import Country, Product
from app.services.vivape_adapter import VivaPeAdapter
from app.services.catalog_parsing import parse_vivape_product
from app.core.logging import get_logger

logger = get_logger(__name__)

# Products are only synced for these destinations - VivaPe's catalog is
# huge (248 countries) but most have no eSIM-classified products at all
# (confirmed live: the US currently has zero), and syncing product
# details for all 248 on every run would be far more VivaPe API calls
# than needed. Expand this list as more destinations get real inventory.
POPULAR_ISO = ["US", "TH", "JP", "SA", "AE", "GB", "TR", "SG", "MY", "BD"]


async def sync_vivape_catalog(db: AsyncSession) -> dict:
    raw_countries = await VivaPeAdapter.get_countries(db)
    synced_c = 0
    updated_p = 0
    created_p = 0

    existing_res = await db.execute(select(Country.iso2))
    seen_iso = set(existing_res.scalars().all())

    for item in raw_countries:
        c_id = item.get("id")
        raw_iso = item.get("iso_alpha2") or item.get("iso2") or item.get("country_code", "")
        iso2 = raw_iso.strip().upper()
        name = item.get("country_name") or item.get("name", "")
        if not iso2 or iso2 in seen_iso:
            continue

        seen_iso.add(iso2)
        db.add(Country(
            id=c_id,
            iso2=iso2,
            name_en=name,
            flag_url=f"https://flagcdn.com/w80/{iso2.lower()}.png",
            is_popular=iso2 in POPULAR_ISO,
            is_active=True
        ))
        synced_c += 1

    await db.commit()

    # Sync products for popular destination countries. Upserts by
    # supplier_product_id (VivaPe's own id, unique across their whole
    # catalog) instead of blindly inserting - the previous version
    # re-inserted every product on every run with no existence check,
    # which meant re-running the sync (exactly what a scheduled job does)
    # duplicated the entire catalog every time.
    top_c = await db.execute(select(Country).where(Country.is_popular == True))
    for c in top_c.scalars().all():
        existing_res = await db.execute(
            select(Product).where(Product.country_id == c.id, Product.supplier_product_id.isnot(None))
        )
        existing_by_supplier_id = {p.supplier_product_id: p for p in existing_res.scalars().all()}

        raw_products = await VivaPeAdapter.get_products(db, c.id)
        for p in raw_products:
            parsed = parse_vivape_product(p)
            if parsed is None:
                continue

            existing = existing_by_supplier_id.get(parsed["supplier_product_id"])
            if existing:
                existing.title_en = parsed["title"] or existing.title_en
                existing.data_amount_gb = parsed["data_amount_gb"]
                existing.validity_days = parsed["validity_days"]
                existing.cost_price = parsed["cost_price"]
                existing.retail_price = parsed["retail_price"]
                existing.is_unlimited = parsed["is_unlimited"]
                existing.supplier_reference = parsed["supplier_reference"]
                existing.supplier_receiver_amount = parsed["supplier_receiver_amount"]
                updated_p += 1
            else:
                db.add(Product(
                    supplier_product_id=parsed["supplier_product_id"],
                    country_id=c.id,
                    title_en=parsed["title"] or f"{c.name_en} eSIM",
                    data_amount_gb=parsed["data_amount_gb"],
                    validity_days=parsed["validity_days"],
                    cost_price=parsed["cost_price"],
                    retail_price=parsed["retail_price"],
                    currency="USD",
                    is_unlimited=parsed["is_unlimited"],
                    supplier_reference=parsed["supplier_reference"],
                    supplier_receiver_amount=parsed["supplier_receiver_amount"]
                ))
                created_p += 1

    await db.commit()
    logger.info("vivape_catalog_synced", synced_countries=synced_c, created_products=created_p, updated_products=updated_p)
    return {
        "status": "success",
        "synced_countries": synced_c,
        "synced_products": created_p,
        "updated_products": updated_p,
    }

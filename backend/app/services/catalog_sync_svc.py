"""Syncs the local catalog (countries + products) from VivaPe.

Extracted out of the /admin/catalog/sync endpoint so the same logic can
be called from a scheduled background job, not just an admin click.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.catalog import Country, Product
from app.services.vivape_adapter import VivaPeAdapter
from app.services.esimaccess_adapter import ESIMAccessAdapter
from app.services.catalog_parsing import parse_vivape_product, parse_esimaccess_package
from app.services.pricing_svc import get_selling_profit_pct
from app.core.logging import get_logger

logger = get_logger(__name__)

# A product that stops appearing in VivaPe's /products response for a
# country is never explicitly told to us - it just silently isn't in the
# list any more. So "when did the feed last list this product" is recorded
# explicitly, in Product.last_seen_in_feed_at, by a direct UPDATE of every
# id the feed returned.
#
# It must NOT be inferred from updated_at. That was the original design and
# it emptied the production storefront: SQLAlchemy compares values at flush
# time, so re-assigning a product the same price/data it already had
# produces no UPDATE and no onupdate. updated_at froze on every unchanged
# product, went stale after the grace period, and the sweep below
# deactivated ~1430 of 1473 products at the end of the very run that had
# just seen all of them in the feed - then the next run revived them by
# flipping is_active, giving a ~16h cycle of the catalog emptying itself
# (23-28 Oct 2026).
#
# The grace period is deliberately several sync cycles, not one: a single
# missed country (a timeout, a transient 5xx) must not make a perfectly
# good product vanish from the storefront. Only a product that has been
# absent across multiple consecutive runs gets deactivated - exactly the
# gap that let a retired China product sit purchasable for weeks, failing
# at checkout with "Product not found" every time a customer reached it,
# which is what this is written to prevent from happening at catalog scale
# when a supplier discontinues an entire product line at once.
_SYNC_INTERVAL = timedelta(hours=4)
_STALE_GRACE_CYCLES = 3
STALE_GRACE = _SYNC_INTERVAL * _STALE_GRACE_CYCLES

# No supplier retires most of its catalogue in one go, so a sweep that
# would is far likelier to be a bug in us than a real mass retirement -
# which is exactly what happened. Past this share of the active
# supplier-sourced catalogue the sweep refuses to run, leaves every product
# purchasable, and reports itself so the admin console can raise it: an
# alert is recoverable, a silently emptied storefront during an ad campaign
# is not.
MAX_DEACTIVATION_SHARE = 0.2
# Below this many rows, share is meaningless (2 of 3 products is 67%), so
# small sweeps are always allowed through.
MIN_DEACTIVATION_FLOOR = 25

# Which destinations get highlighted on the storefront's "popular" grid.
# This is purely a merchandising choice - products are synced for EVERY
# country now, not just these (an earlier version synced products only
# for this list, which is why e.g. China showed zero packages despite
# VivaPe listing 20 eSIM products for it). Countries that end up with no
# eSIM products are hidden from the storefront by the catalog API, so a
# barren entry here (the US currently has no eSIM inventory at all) is
# self-correcting rather than a visible empty destination.
POPULAR_ISO = ["US", "TH", "JP", "SA", "AE", "GB", "TR", "SG", "MY", "BD"]

# VivaPe rate-limits to 60 requests/minute (x-ratelimit-limit header), and
# a full sync is one products call per country (~250). Pace them so a
# scheduled sync can never trip the limit and start failing mid-run.
_PER_COUNTRY_DELAY_SECONDS = 1.1


async def sync_vivape_catalog(db: AsyncSession) -> dict:
    sync_started_at = datetime.now(timezone.utc)
    profit_pct = await get_selling_profit_pct(db)
    raw_countries = await VivaPeAdapter.get_countries(db)
    synced_c = 0
    seen_p = 0
    changed_p = 0
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
    all_c = await db.execute(select(Country).where(Country.is_active == True).order_by(Country.iso2.asc()))
    for c in all_c.scalars().all():
        existing_res = await db.execute(
            select(Product).where(Product.country_id == c.id, Product.supplier_product_id.isnot(None))
        )
        existing_by_supplier_id = {p.supplier_product_id: p for p in existing_res.scalars().all()}

        raw_products = await VivaPeAdapter.get_products(db, c.id)
        seen_ids: list[str] = []
        for p in raw_products:
            parsed = parse_vivape_product(p, profit_pct)
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
                # Reappeared after being deactivated below (the supplier
                # brought it back, or it was only ever absent for a few
                # cycles) - being seen in the feed again is exactly what
                # "active" means here.
                existing.is_active = True
                seen_p += 1
                seen_ids.append(existing.id)
                # Counts rows the database will really change, not rows we
                # assigned to. The old counter reported "updated 1430"
                # every run while writing nothing, which is why the feed
                # was trusted and the sweep's damage stayed invisible in
                # these very logs.
                if db.is_modified(existing):
                    changed_p += 1
            else:
                db.add(Product(
                    supplier_product_id=parsed["supplier_product_id"],
                    country_id=c.id,
                    title_en=parsed["title"] or f"{c.name_en} eSIM",
                    data_amount_gb=parsed["data_amount_gb"],
                    validity_days=parsed["validity_days"],
                    cost_price=parsed["cost_price"],
                    retail_price=parsed["retail_price"],
                    currency="EUR",  # VivaPe prices in euro
                    is_unlimited=parsed["is_unlimited"],
                    supplier_reference=parsed["supplier_reference"],
                    supplier_receiver_amount=parsed["supplier_receiver_amount"],
                    last_seen_in_feed_at=sync_started_at,
                ))
                created_p += 1

        # Record every id the feed just listed, as a direct UPDATE rather
        # than ORM assignment - this is the one write that must happen even
        # when nothing about the product changed, so it cannot be left to
        # change detection. updated_at is explicitly set to itself to keep
        # the column's onupdate from firing: it still means "when this
        # product's data last changed", not "when we last looked".
        if seen_ids:
            await db.execute(
                update(Product)
                .where(Product.id.in_(seen_ids))
                .values(last_seen_in_feed_at=sync_started_at, updated_at=Product.updated_at)
            )

        # Commit per country so a long full-catalog run doesn't hold one
        # giant transaction open, and a failure partway through keeps the
        # countries already synced.
        await db.commit()
        await asyncio.sleep(_PER_COUNTRY_DELAY_SECONDS)

    await db.commit()

    # Anything still marked active that this run did not touch, and has not
    # been touched for multiple sync cycles, is no longer in the supplier's
    # feed. Deactivating it (not deleting - order history still references
    # it) is what stops it from being purchasable and failing at checkout
    # against a supplier that no longer recognises it.
    stale_cutoff = sync_started_at - STALE_GRACE
    # Only supplier-sourced products: a hand-created product is never in
    # any feed, so last_seen_in_feed_at stays NULL forever and nothing
    # would ever revive it once deactivated.
    stale_clause = (
        Product.is_active.is_(True),
        Product.supplier_product_id.isnot(None),
        Product.last_seen_in_feed_at.isnot(None),
        Product.last_seen_in_feed_at < stale_cutoff,
    )
    stale_count = (await db.execute(
        select(func.count()).select_from(Product).where(*stale_clause)
    )).scalar_one()
    active_count = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_active.is_(True), Product.supplier_product_id.isnot(None)
        )
    )).scalar_one()

    deactivated_p = 0
    deactivation_skipped = False
    if stale_count >= MIN_DEACTIVATION_FLOOR and stale_count > active_count * MAX_DEACTIVATION_SHARE:
        deactivation_skipped = True
        logger.error(
            "vivape_catalog_mass_deactivation_refused",
            stale_products=stale_count,
            active_products=active_count,
            share=round(stale_count / active_count, 3) if active_count else None,
            message="Refused to deactivate an implausible share of the catalog - left everything purchasable",
        )
    elif stale_count:
        deactivate_res = await db.execute(update(Product).where(*stale_clause).values(is_active=False))
        deactivated_p = deactivate_res.rowcount or 0
        await db.commit()

    logger.info(
        "vivape_catalog_synced",
        synced_countries=synced_c,
        created_products=created_p,
        products_in_feed=seen_p,
        changed_products=changed_p,
        deactivated_products=deactivated_p,
        deactivation_skipped=deactivation_skipped,
    )
    return {
        "status": "success",
        "synced_countries": synced_c,
        "synced_products": created_p,
        "products_in_feed": seen_p,
        # Kept under its original key so the admin console's existing sync
        # alert keeps working, but it now counts real changes.
        "updated_products": changed_p,
        "deactivated_products": deactivated_p,
        "deactivation_skipped": deactivation_skipped,
        "deactivation_candidates": stale_count,
    }


async def sync_esimaccess_catalog(db: AsyncSession) -> dict:
    """Syncs the local catalog from eSIM Access's package/list.

    Deliberately narrower in scope than sync_vivape_catalog, by design, not
    oversight - see parse_esimaccess_package's docstring: only fixed-data
    (dataType 1), single-country packages are synced. Day Passes and
    multi-country/regional bundles are real eSIM Access products this
    function does not create Product rows for, because Product has no
    column for "pick your own duration at purchase" or "one package, many
    countries" - adding either is its own design decision, not something to
    improvise here.

    Structurally simpler than VivaPe's sync in one respect: package/list
    with an empty locationCode returns the ENTIRE catalogue in one call
    (confirmed live, 2026-11-10: a single unfiltered call returned all
    3,283 packages, with no pager field anywhere in the response) - there is
    no per-country loop, no pagination, and therefore no per-call rate-limit
    pacing needed the way VivaPe's _PER_COUNTRY_DELAY_SECONDS is.

    Shares the same circuit breaker (MAX_DEACTIVATION_SHARE,
    MIN_DEACTIVATION_FLOOR, STALE_GRACE) as VivaPe's sync - a supplier
    emptying its catalog is exactly as implausible and exactly as dangerous
    regardless of which supplier it is - but scoped to eSIM Access's own
    rows (Product.supplier_reference == "esimaccess") throughout, so a
    VivaPe-side hiccup and an eSIM Access-side hiccup can never share the
    same active/stale denominator and mask or trigger each other.
    """
    sync_started_at = datetime.now(timezone.utc)
    profit_pct = await get_selling_profit_pct(db)

    existing_country_res = await db.execute(select(Country.iso2, Country.id))
    country_id_by_location = {iso2: cid for iso2, cid in existing_country_res.all()}

    # Country.id has no reliable auto-increment to fall back on: VivaPe's own
    # sync has always supplied an explicit id (its own numeric country id -
    # see sync_vivape_catalog above), so the column's underlying Postgres
    # sequence has never actually been advanced by an app-level insert and
    # sits far behind the ids already in use. Letting SQLAlchemy omit id and
    # rely on that stale sequence default (what an earlier version of this
    # function did) collided with an existing row on the very first country
    # eSIM Access needed to create (Aland Islands, live on beta - a genuine
    # UniqueViolationError, not a hypothetical one). Computed once per run
    # and incremented in Python for each new country, rather than re-querying
    # MAX(id) per row.
    next_country_id = ((await db.execute(select(func.max(Country.id)))).scalar_one() or 0) + 1

    existing_product_res = await db.execute(
        select(Product).where(
            Product.supplier_reference == "esimaccess",
            Product.supplier_package_code.isnot(None),
        )
    )
    # Keyed on (packageCode, periodNum), not packageCode alone: a Day Pass
    # package is synced as several Product rows sharing one
    # supplier_package_code (see parse_esimaccess_package and
    # DAY_PASS_VARIANT_DAYS), distinguished only by supplier_period_num.
    # Keying on packageCode alone would make this dict collapse every
    # variant down to whichever one happened to be seen last, so a re-sync
    # would treat all but one variant as brand new every single run -
    # migration b2d5f93a8e61's own partial unique index enforces this same
    # pairing can't collide at the database level either.
    existing_by_code_period = {
        (p.supplier_package_code, p.supplier_period_num): p
        for p in existing_product_res.scalars().all()
    }

    raw_packages = await ESIMAccessAdapter.list_packages(db)

    created_countries = 0
    created_p = 0
    seen_p = 0
    changed_p = 0
    skipped_out_of_scope = 0
    seen_ids: list[str] = []

    for raw in raw_packages:
        variants = parse_esimaccess_package(raw, profit_pct)
        if not variants:
            skipped_out_of_scope += 1
            continue

        for parsed in variants:
            location_key = parsed["location_key"]
            country_id = country_id_by_location.get(location_key)
            if country_id is None:
                # A location eSIM Access covers that isn't in Triptel's
                # Country table yet - a real country (eSIM Access's 202 vs.
                # VivaPe's ~132 means this is expected, not an error) or a
                # multi-country/regional/global pseudo-country keyed on
                # eSIM Access's own stable locationCode (confirmed live:
                # every package sharing one locationCode shares the exact
                # same country set - see parse_esimaccess_package). Mirrors
                # sync_vivape_catalog's own country auto-creation for the
                # real-country case; a regional pseudo-country gets no
                # flag_url (nullable - there is no single flag for "Europe,
                # 41 countries") and its name from region_name instead of
                # locationNetworkList.
                if parsed["is_regional"]:
                    name = parsed["region_name"]
                    flag_url = None
                else:
                    networks = raw.get("locationNetworkList") or []
                    name = networks[0].get("locationName") if networks else location_key
                    flag_url = f"https://flagcdn.com/w80/{location_key.lower()}.png"
                new_country = Country(
                    id=next_country_id,
                    iso2=location_key,
                    name_en=name or location_key,
                    flag_url=flag_url,
                    region="Regional" if parsed["is_regional"] else None,
                    is_popular=False,
                    is_active=True,
                )
                db.add(new_country)
                await db.flush()
                country_id = new_country.id
                country_id_by_location[location_key] = country_id
                created_countries += 1
                next_country_id += 1

            key = (parsed["supplier_package_code"], parsed["supplier_period_num"])
            existing = existing_by_code_period.get(key)
            if existing:
                existing.title_en = parsed["title"] or existing.title_en
                existing.data_amount_gb = parsed["data_amount_gb"]
                existing.validity_days = parsed["validity_days"]
                existing.cost_price = parsed["cost_price"]
                existing.retail_price = parsed["retail_price"]
                existing.currency = parsed["currency"]
                existing.is_unlimited = parsed["is_unlimited"]
                existing.coverage_networks = parsed["coverage_networks"]
                existing.country_id = country_id
                # Reappeared after being deactivated below, or was only
                # ever absent for a few cycles - being seen in the feed
                # again is exactly what "active" means here (same
                # reasoning as VivaPe's sync, see its own comment on this
                # exact line).
                existing.is_active = True
                seen_p += 1
                seen_ids.append(existing.id)
                if db.is_modified(existing):
                    changed_p += 1
            else:
                new_product = Product(
                    country_id=country_id,
                    title_en=parsed["title"],
                    data_amount_gb=parsed["data_amount_gb"],
                    validity_days=parsed["validity_days"],
                    cost_price=parsed["cost_price"],
                    retail_price=parsed["retail_price"],
                    currency=parsed["currency"],
                    is_unlimited=parsed["is_unlimited"],
                    supplier_reference=parsed["supplier_reference"],
                    supplier_package_code=parsed["supplier_package_code"],
                    supplier_period_num=parsed["supplier_period_num"],
                    coverage_networks=parsed["coverage_networks"],
                    last_seen_in_feed_at=sync_started_at,
                )
                db.add(new_product)
                await db.flush()
                created_p += 1
                seen_ids.append(new_product.id)

    await db.commit()

    # Same direct-UPDATE pattern as VivaPe's sync, and for the identical
    # reason: this must happen even for a row whose data didn't change, so
    # it cannot be left to SQLAlchemy's change detection (see the long
    # comment on sync_vivape_catalog's own identical UPDATE for the
    # production incident that taught this project why).
    if seen_ids:
        await db.execute(
            update(Product)
            .where(Product.id.in_(seen_ids))
            .values(last_seen_in_feed_at=sync_started_at, updated_at=Product.updated_at)
        )
        await db.commit()

    stale_cutoff = sync_started_at - STALE_GRACE
    stale_clause = (
        Product.is_active.is_(True),
        Product.supplier_reference == "esimaccess",
        Product.last_seen_in_feed_at.isnot(None),
        Product.last_seen_in_feed_at < stale_cutoff,
    )
    stale_count = (await db.execute(
        select(func.count()).select_from(Product).where(*stale_clause)
    )).scalar_one()
    active_count = (await db.execute(
        select(func.count()).select_from(Product).where(
            Product.is_active.is_(True), Product.supplier_reference == "esimaccess"
        )
    )).scalar_one()

    deactivated_p = 0
    deactivation_skipped = False
    if stale_count >= MIN_DEACTIVATION_FLOOR and stale_count > active_count * MAX_DEACTIVATION_SHARE:
        deactivation_skipped = True
        logger.error(
            "esimaccess_catalog_mass_deactivation_refused",
            stale_products=stale_count,
            active_products=active_count,
            share=round(stale_count / active_count, 3) if active_count else None,
            message="Refused to deactivate an implausible share of the eSIM Access catalog - left everything purchasable",
        )
    elif stale_count:
        deactivate_res = await db.execute(update(Product).where(*stale_clause).values(is_active=False))
        deactivated_p = deactivate_res.rowcount or 0
        await db.commit()

    logger.info(
        "esimaccess_catalog_synced",
        created_countries=created_countries,
        created_products=created_p,
        products_in_feed=seen_p,
        changed_products=changed_p,
        skipped_out_of_scope=skipped_out_of_scope,
        deactivated_products=deactivated_p,
        deactivation_skipped=deactivation_skipped,
    )
    return {
        "status": "success",
        # Named synced_countries, not created_countries, to match
        # sync_vivape_catalog's response shape exactly - the admin console
        # reuses the same result-summary rendering for both suppliers'
        # sync buttons.
        "synced_countries": created_countries,
        "synced_products": created_p,
        "products_in_feed": seen_p,
        "updated_products": changed_p,
        "skipped_out_of_scope": skipped_out_of_scope,
        "deactivated_products": deactivated_p,
        "deactivation_skipped": deactivation_skipped,
        "deactivation_candidates": stale_count,
    }

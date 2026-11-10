"""sync_esimaccess_catalog - deliberately narrow scope (fixed-data,
single-country only; see parse_esimaccess_package's docstring for why Day
Passes and multi-country bundles are excluded), the country auto-creation
path, the upsert-by-supplier_package_code path, and the circuit breaker
reused from VivaPe's sync but scoped to supplier_reference == "esimaccess"
only.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.models.catalog import Country, Product
from app.services.catalog_sync_svc import sync_esimaccess_catalog, MIN_DEACTIVATION_FLOOR

pytestmark = pytest.mark.asyncio


def _raw_package(iso2, code, name, price_scaled, volume_gb, duration, data_type=1, duration_unit="DAY", location=None):
    return {
        "packageCode": code,
        "name": name,
        "price": price_scaled,
        "volume": int(volume_gb * 1024 ** 3),
        "dataType": data_type,
        "duration": duration,
        "durationUnit": duration_unit,
        "location": location if location is not None else iso2,
        "ipExport": iso2,
        "locationNetworkList": [{"locationName": f"{iso2}land"}],
    }


async def _patched_list_packages(packages):
    return patch(
        "app.services.catalog_sync_svc.ESIMAccessAdapter.list_packages",
        new=AsyncMock(return_value=packages),
    )


async def test_syncs_a_new_fixed_data_single_country_package_creating_the_country(db_session):
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"Z{suffix[:1]}"  # unlikely to collide with a real/existing test country
    pkg = _raw_package(iso2, f"PKG{suffix}", f"{iso2}land 1GB 7Days", 7000, 1, 7)

    with await _patched_list_packages([pkg]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_products"] == 1
    assert result["synced_countries"] == 1

    country = (await db_session.execute(select(Country).where(Country.iso2 == iso2))).scalar_one()
    assert country.name_en == f"{iso2}land"

    product = (await db_session.execute(
        select(Product).where(Product.supplier_package_code == f"PKG{suffix}")
    )).scalar_one()
    assert product.country_id == country.id
    assert product.supplier_reference == "esimaccess"
    assert product.data_amount_gb == Decimal("1.00")
    assert product.validity_days == 7
    assert product.cost_price == Decimal("0.7000")
    assert product.currency == "USD"
    assert product.coverage_networks == iso2


async def test_auto_created_country_id_is_always_past_the_current_max_not_a_stale_sequence(db_session):
    """Reproduces the real bug, live on beta on first use (2026-11-10):
    Country.id has no reliable auto-increment to fall back on - VivaPe's
    sync has always supplied an explicit id (see sync_vivape_catalog), so
    the column's underlying Postgres sequence was never actually advanced
    by an app-level insert and sits far behind the ids already in use.
    Omitting id and trusting that stale sequence default collided with an
    existing row (a real UniqueViolationError on "countries_pkey",
    inserting Aland Islands) the very first time this sync ran for real.

    Doesn't hardcode a specific colliding id (this test DB is shared
    across the whole suite with no per-test rollback - a fixed low id
    like 1 may well already be taken by something else entirely) -
    instead proves the general property the fix actually relies on: a
    freshly auto-created country's id is always strictly greater than
    whatever the real current max was at sync time, computed in Python,
    never left to the database's own (demonstrably unreliable) default."""
    current_max = (await db_session.execute(select(func.max(Country.id)))).scalar_one() or 0

    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"Y{suffix[:1]}"
    pkg = _raw_package(iso2, f"COL{suffix}", f"{iso2}land 1GB 7Days", 7000, 1, 7)

    with await _patched_list_packages([pkg]):
        result = await sync_esimaccess_catalog(db_session)  # must not raise IntegrityError

    assert result["synced_countries"] == 1
    new_country = (await db_session.execute(select(Country).where(Country.iso2 == iso2))).scalar_one()
    assert new_country.id > current_max


async def test_two_new_countries_in_one_sync_get_distinct_ids(db_session):
    """The fix increments its own counter per new country within a single
    run rather than re-querying MAX(id) per row - if it didn't, two new
    countries created in the same sync would both compute the same "next"
    id from the same stale MAX() snapshot and collide with each other."""
    suffix = uuid.uuid4().hex[:4].upper()
    iso2_a, iso2_b = f"A{suffix[:1]}", f"B{suffix[:1]}"
    pkg_a = _raw_package(iso2_a, f"TWOA{suffix}", f"{iso2_a}land 1GB 7Days", 7000, 1, 7)
    pkg_b = _raw_package(iso2_b, f"TWOB{suffix}", f"{iso2_b}land 1GB 7Days", 7000, 1, 7)

    with await _patched_list_packages([pkg_a, pkg_b]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_countries"] == 2
    rows = (await db_session.execute(
        select(Country).where(Country.iso2.in_([iso2_a, iso2_b]))
    )).scalars().all()
    ids = {c.id for c in rows}
    assert len(ids) == 2  # distinct, not collided


async def test_day_pass_and_multi_country_packages_are_not_synced(db_session):
    """The deliberate scope decision, verified: a Day Pass and a regional
    bundle in the raw feed must produce zero Product rows, not a
    mis-modeled one."""
    suffix = uuid.uuid4().hex[:4].upper()
    day_pass = _raw_package(f"Y{suffix[:1]}", f"DP{suffix}", "Day Pass", 9000, 1, 1, data_type=2)
    bundle = _raw_package("XX", f"BND{suffix}", "Regional Bundle", 50000, 5, 30,
                          location="QA,EG,IL,MA,AE,JO,BH,TN,KW,SA,TR,OM")

    with await _patched_list_packages([day_pass, bundle]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_products"] == 0
    assert result["skipped_out_of_scope"] == 2
    assert (await db_session.execute(
        select(Product).where(Product.supplier_package_code.in_([f"DP{suffix}", f"BND{suffix}"]))
    )).scalar_one_or_none() is None


async def test_re_syncing_an_existing_package_updates_it_not_duplicates_it(db_session):
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"W{suffix[:1]}"
    code = f"UPD{suffix}"
    pkg_v1 = _raw_package(iso2, code, f"{iso2}land 1GB 7Days", 7000, 1, 7)

    with await _patched_list_packages([pkg_v1]):
        await sync_esimaccess_catalog(db_session)

    pkg_v2 = _raw_package(iso2, code, f"{iso2}land 1GB 7Days", 8500, 1, 7)  # price changed
    with await _patched_list_packages([pkg_v2]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_products"] == 0  # not created again
    assert result["updated_products"] == 1

    rows = (await db_session.execute(
        select(Product).where(Product.supplier_package_code == code)
    )).scalars().all()
    assert len(rows) == 1  # never duplicated
    assert rows[0].cost_price == Decimal("0.8500")


async def test_a_package_that_stops_appearing_in_the_feed_is_eventually_deactivated(db_session):
    """Mirrors sync_vivape_catalog's own stale-product sweep, scoped to
    eSIM Access's rows only - last_seen_in_feed_at must age out, not
    updated_at (same production incident that already broke this once for
    VivaPe, replayed here for the second supplier's own sync path)."""
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"V{suffix[:1]}"
    code = f"STALE{suffix}"

    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=iso2, name_en=f"{iso2}land", is_active=True)
    db_session.add(country)
    await db_session.flush()

    stale_product = Product(
        id=str(uuid.uuid4()), country_id=country.id, title_en="Stale package",
        data_amount_gb=Decimal("1.00"), validity_days=7, cost_price=Decimal("0.70"),
        retail_price=Decimal("0.90"), currency="USD", is_active=True,
        supplier_reference="esimaccess", supplier_package_code=code,
        last_seen_in_feed_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    db_session.add(stale_product)
    # Pad active_count comfortably past MIN_DEACTIVATION_FLOOR so the
    # circuit breaker's share-based refusal never fires in this test - a
    # single stale row out of one row is 100%, which the breaker correctly
    # refuses (see the next test), so this one needs real headroom.
    for i in range(MIN_DEACTIVATION_FLOOR + 10):
        db_session.add(Product(
            id=str(uuid.uuid4()), country_id=country.id, title_en=f"Healthy {i}",
            data_amount_gb=Decimal("1.00"), validity_days=7, cost_price=Decimal("0.70"),
            retail_price=Decimal("0.90"), currency="USD", is_active=True,
            supplier_reference="esimaccess", supplier_package_code=f"HEALTHY{suffix}{i}",
            last_seen_in_feed_at=datetime.now(timezone.utc) - timedelta(days=30),
        ))
    await db_session.commit()

    with await _patched_list_packages([]):  # feed no longer lists any of them... but see below
        # Re-touch the healthy ones so they're NOT stale this cycle - only
        # the target product is genuinely absent from the feed.
        healthy_pkgs = [_raw_package(iso2, f"HEALTHY{suffix}{i}", f"Healthy {i}", 7000, 1, 7)
                        for i in range(MIN_DEACTIVATION_FLOOR + 10)]
        with patch("app.services.catalog_sync_svc.ESIMAccessAdapter.list_packages", new=AsyncMock(return_value=healthy_pkgs)):
            result = await sync_esimaccess_catalog(db_session)

    assert result["deactivation_skipped"] is False
    await db_session.refresh(stale_product)
    assert stale_product.is_active is False


async def test_mass_deactivation_is_refused_and_everything_stays_purchasable(db_session):
    """The exact production incident sync_vivape_catalog's own circuit
    breaker was built to prevent, reproduced here for eSIM Access's own
    sync path with an empty feed response (e.g. a transient API outage) -
    must refuse to deactivate an implausible share rather than empty the
    storefront."""
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"U{suffix[:1]}"
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=iso2, name_en=f"{iso2}land", is_active=True)
    db_session.add(country)
    await db_session.flush()

    for i in range(MIN_DEACTIVATION_FLOOR + 5):
        db_session.add(Product(
            id=str(uuid.uuid4()), country_id=country.id, title_en=f"Product {i}",
            data_amount_gb=Decimal("1.00"), validity_days=7, cost_price=Decimal("0.70"),
            retail_price=Decimal("0.90"), currency="USD", is_active=True,
            supplier_reference="esimaccess", supplier_package_code=f"MASS{suffix}{i}",
            last_seen_in_feed_at=datetime.now(timezone.utc) - timedelta(days=30),
        ))
    await db_session.commit()

    with await _patched_list_packages([]):  # "the whole feed is empty" - implausible, must be refused
        result = await sync_esimaccess_catalog(db_session)

    assert result["deactivation_skipped"] is True
    assert result["deactivated_products"] == 0
    # Scoped to this test's own rows by package-code prefix, not a bare
    # count of every esimaccess product - this test DB has no per-test
    # rollback, so other tests' active rows are already present here too
    # (the same lesson test_supplier_settings.py's own tests already
    # learned the hard way). The breaker's own decision above (global,
    # correctly) already proves it refused; this just confirms MY rows
    # specifically were never touched.
    still_active = (await db_session.execute(
        select(Product).where(
            Product.supplier_reference == "esimaccess",
            Product.is_active.is_(True),
            Product.supplier_package_code.like(f"MASS{suffix}%"),
        )
    )).scalars().all()
    assert len(still_active) == MIN_DEACTIVATION_FLOOR + 5  # every one of mine still purchasable

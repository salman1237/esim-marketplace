"""sync_esimaccess_catalog - fixed-data AND Day Pass, single-country AND
multi-country/regional/global, the country/pseudo-country auto-creation
path, the upsert-by-(packageCode,periodNum) path, and the circuit breaker
reused from VivaPe's sync but scoped to supplier_reference == "esimaccess"
only. Day Pass and regional support were added in the same pass as each
other (see parse_esimaccess_package's docstring) because eSIM Access's
real catalog mixes the two freely.
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


def _raw_package(iso2, code, name, price_scaled, volume_gb, duration, data_type=1, duration_unit="DAY",
                  location=None, location_code=None):
    loc = location if location is not None else iso2
    return {
        "packageCode": code,
        "name": name,
        "price": price_scaled,
        "volume": int(volume_gb * 1024 ** 3),
        "dataType": data_type,
        "duration": duration,
        "durationUnit": duration_unit,
        "location": loc,
        "locationCode": location_code if location_code is not None else loc,
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


async def test_day_pass_package_syncs_as_two_priced_duration_variants(db_session):
    """A Day Pass has no single "the" product - DAY_PASS_VARIANT_DAYS (7,
    15) is synced as two separate, correctly fixed-looking Product rows
    sharing one supplier_package_code, each priced through the real
    tiered-discount formula (not price_scaled * days)."""
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"Y{suffix[:1]}"
    code = f"DP{suffix}"
    day_pass = _raw_package(iso2, code, f"{iso2}land 1GB/Day", 9000, 1, 1, data_type=2)

    with await _patched_list_packages([day_pass]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_products"] == 2
    assert result["skipped_out_of_scope"] == 0

    rows = (await db_session.execute(
        select(Product).where(Product.supplier_package_code == code).order_by(Product.validity_days)
    )).scalars().all()
    assert len(rows) == 2
    assert [r.supplier_period_num for r in rows] == [7, 15]
    assert [r.validity_days for r in rows] == [7, 15]
    # Tiered discount, not linear: 7 days at the 5-9 day band (92%) of a
    # $0.90/day rate, not flat 7 x $0.90 = $6.30.
    assert rows[0].cost_price == Decimal("5.7960")
    assert rows[0].data_amount_gb == Decimal("7.00")  # 1GB/day x 7 days


async def test_regional_package_creates_a_pseudo_country_keyed_on_location_code(db_session):
    """A multi-country/regional package has no single ISO2 - gets its own
    Country row keyed on eSIM Access's own stable locationCode, named from
    the package's own name (stripped of the data/duration suffix), with no
    flag_url (there is no single flag for a 41-country bundle)."""
    suffix = uuid.uuid4().hex[:4].upper()
    code = f"RG{suffix}"
    loc_code = f"EUTEST{suffix}"
    regional = _raw_package("XX", code, "Europe Test 3GB 30Days", 50000, 3, 30,
                            location="NO,RS,DE", location_code=loc_code)

    with await _patched_list_packages([regional]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_countries"] == 1
    assert result["synced_products"] == 1

    country = (await db_session.execute(select(Country).where(Country.iso2 == loc_code))).scalar_one()
    assert country.name_en == "Europe Test"
    assert country.flag_url is None
    assert country.region == "Regional"

    product = (await db_session.execute(
        select(Product).where(Product.supplier_package_code == code)
    )).scalar_one()
    assert product.country_id == country.id
    assert product.supplier_period_num is None  # fixed-data, not a Day Pass variant


async def test_a_regional_day_pass_shares_the_pseudo_country_with_a_regional_fixed_package(db_session):
    """Confirmed live: eSIM Access's real catalog mixes Day Pass and
    regional freely (e.g. a Day Pass and a fixed-data package under the
    same "EU-42" locationCode) - both must resolve to the SAME
    pseudo-country, not create a duplicate."""
    suffix = uuid.uuid4().hex[:4].upper()
    loc_code = f"EUMIX{suffix}"
    fixed = _raw_package("XX", f"FX{suffix}", "Mix Region 3GB 30Days", 50000, 3, 30,
                         location="NO,RS,DE", location_code=loc_code)
    day_pass = _raw_package("XX", f"DPX{suffix}", "Mix Region 500MB/Day", 14400, 0.5, 1,
                            data_type=2, location="NO,RS,DE", location_code=loc_code)

    with await _patched_list_packages([fixed, day_pass]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_countries"] == 1  # one pseudo-country, not two
    assert result["synced_products"] == 3  # 1 fixed + 2 Day Pass variants

    countries = (await db_session.execute(select(Country).where(Country.iso2 == loc_code))).scalars().all()
    assert len(countries) == 1


async def test_re_syncing_a_day_pass_updates_both_variants_not_duplicates_them(db_session):
    """The composite (packageCode, periodNum) upsert key, verified: both
    variants of the SAME Day Pass package must each update in place on a
    re-sync, not be treated as new because they share a packageCode."""
    suffix = uuid.uuid4().hex[:4].upper()
    iso2 = f"Z{suffix[:1]}"
    code = f"RDP{suffix}"
    v1 = _raw_package(iso2, code, f"{iso2}land 1GB/Day", 9000, 1, 1, data_type=2)

    with await _patched_list_packages([v1]):
        await sync_esimaccess_catalog(db_session)

    v2 = _raw_package(iso2, code, f"{iso2}land 1GB/Day", 10000, 1, 1, data_type=2)  # price changed
    with await _patched_list_packages([v2]):
        result = await sync_esimaccess_catalog(db_session)

    assert result["synced_products"] == 0  # not created again
    assert result["updated_products"] == 2  # both variants updated

    rows = (await db_session.execute(
        select(Product).where(Product.supplier_package_code == code)
    )).scalars().all()
    assert len(rows) == 2  # never duplicated despite sharing one packageCode


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

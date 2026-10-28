from datetime import datetime, timedelta, timezone

import pytest
import httpx
from sqlalchemy import select, update
from app.services.catalog_sync_svc import STALE_GRACE, sync_vivape_catalog
from app.services.vivape_adapter import VivaPeAdapter
from app.models.catalog import Product

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_vivape_token_cache():
    # VivaPeAdapter caches its login token on the class itself, so a token
    # from an earlier test would otherwise skip the mocked login here.
    VivaPeAdapter._token = None
    VivaPeAdapter._token_expiry = 0


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


async def _mock_post(self, url, *args, **kwargs):
    # Only the VivaPe login call goes through POST here.
    return _FakeResponse({"access_token": "fake-token"})


def _mock_get_factory(countries: list, products_by_country_id: dict):
    async def _mock_get(self, url, *args, **kwargs):
        if "countries" in str(url):
            return _FakeResponse(countries)
        if "products" in str(url):
            country_id = kwargs.get("params", {}).get("country_id")
            return _FakeResponse(products_by_country_id.get(country_id, []))
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _mock_get


THAILAND = {"id": 212, "iso_alpha2": "th", "country_name": "Thailand"}
THAILAND_1GB_7D = {
    "id": 9991, "price": 3.129411764705978, "reference": "esimgo_bundle",
    "title": "eSIM, 1GB, 7 Days, Thailand, V2",
    "receiver_amount_min": "1000", "receiver_amount_max": "1000",
}

# Price chosen to round-trip exactly through Numeric(18,4) so that a
# re-sync of this product is genuinely a no-op at the database level -
# which is what almost the whole real catalog looks like, and the only
# condition under which the staleness bug appears.
THAILAND_STABLE_PRICE = {
    "id": 9992, "price": 4.0, "reference": "esimgo_bundle",
    "title": "eSIM, 2GB, 7 Days, Thailand, V2",
    "receiver_amount_min": "2000", "receiver_amount_max": "2000",
}


async def test_sync_is_idempotent_does_not_duplicate_products(db_session, monkeypatch):
    """Regression test: the original sync unconditionally INSERTed every
    product on every call with no existence check, so running it twice
    (exactly what happens every time an admin re-clicks "Sync Catalog", and
    exactly what a scheduled job does automatically) silently duplicated
    the entire catalog — confirmed live in production, where every product
    existed in exactly 2 copies after two manual syncs."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )

    first = await sync_vivape_catalog(db_session)
    assert first["synced_countries"] == 1
    assert first["synced_products"] == 1
    assert first["updated_products"] == 0

    second = await sync_vivape_catalog(db_session)
    assert second["synced_countries"] == 0  # country already exists
    assert second["synced_products"] == 0   # must NOT create a duplicate
    assert second["updated_products"] == 1  # existing row refreshed instead

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    rows = res.scalars().all()
    assert len(rows) == 1, f"expected exactly one product row, found {len(rows)} (duplication bug)"


async def test_sync_updates_existing_product_fields(db_session, monkeypatch):
    """A re-sync must pick up real changes (price movement, data amount) on
    an existing product rather than leaving it stale forever."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)

    changed_product = dict(THAILAND_1GB_7D, price=5.0, title="eSIM, 2GB, 7 Days, Thailand, V2")
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [changed_product]})
    )
    await sync_vivape_catalog(db_session)

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    product = res.scalar_one()
    assert product.cost_price == pytest.approx(5.0)
    assert product.title_en == "eSIM, 2GB, 7 Days, Thailand, V2"


async def test_a_product_missing_from_one_sync_is_not_deactivated(db_session, monkeypatch):
    """A single missed sync - a timeout, a transient 5xx from VivaPe - must
    not make a perfectly good product vanish from the storefront. Only
    sustained absence (STALE_GRACE) means the supplier actually retired it."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)

    # This run's response for Thailand no longer includes it, but it was
    # only just updated - nowhere near stale yet.
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: []})
    )
    result = await sync_vivape_catalog(db_session)
    assert result["deactivated_products"] == 0

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    assert res.scalar_one().is_active is True


async def test_a_product_absent_past_the_grace_period_is_deactivated(db_session, monkeypatch):
    """The actual scenario this exists for: a supplier discontinues a
    product line and it simply stops appearing. Confirmed against a real
    retired product in production, which stayed purchasable - and failed at
    checkout with "Product not found" - for weeks because nothing ever
    noticed it was gone from the feed."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    product = res.scalar_one()
    # Backdate as if several sync cycles have passed with this product
    # genuinely gone from the feed, rather than waiting out real time.
    product.last_seen_in_feed_at = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
    await db_session.commit()

    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: []})
    )
    result = await sync_vivape_catalog(db_session)
    assert result["deactivated_products"] == 1

    await db_session.refresh(product)
    assert product.is_active is False


async def test_a_deactivated_product_reactivates_if_the_supplier_brings_it_back(db_session, monkeypatch):
    """Deactivation must not be a one-way door - a product the supplier
    reinstates (or that was only absent due to a longer outage, not a real
    discontinuation) has to become purchasable again on its own, not stay
    hidden forever because of one past gap."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    product = res.scalar_one()
    product.is_active = False
    product.last_seen_in_feed_at = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
    await db_session.commit()

    # Back in the feed on this run.
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)

    await db_session.refresh(product)
    assert product.is_active is True


async def test_an_active_product_in_a_country_with_zero_other_changes_stays_active(db_session, monkeypatch):
    """Guards against an over-broad deactivation query: a product that IS
    still being seen and updated every run must never be swept up by the
    staleness check just because it exists."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    await sync_vivape_catalog(db_session)
    result = await sync_vivape_catalog(db_session)
    assert result["deactivated_products"] == 0

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9991))
    assert res.scalar_one().is_active is True


async def test_an_unchanged_product_still_in_the_feed_survives_the_grace_period(db_session, monkeypatch):
    """The outage this is written for (production, 23-28 Oct 2026).

    Staleness used to be read off Product.updated_at, on the assumption
    that re-syncing a product always advances it. It does not: SQLAlchemy
    compares values at flush time, so a product whose price and data are
    identical to last run produces no UPDATE and no onupdate at all. Every
    unchanged product's updated_at froze, went stale after STALE_GRACE, and
    the sweep deactivated it at the end of the very run that had just seen
    it in the feed - ~1430 of 1473 products, on a ~16h cycle, emptying the
    storefront while ads were running.

    The existing "stays active" test missed it by running two syncs
    milliseconds apart, so nothing was ever old enough to go stale. The
    grace period has to be crossed for the bug to appear."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_STABLE_PRICE]})
    )
    await sync_vivape_catalog(db_session)

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9992))
    product = res.scalar_one()
    stale = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
    # As if the product had been sitting unchanged in the feed for several
    # cycles - which is the normal case for almost the whole catalog.
    product.last_seen_in_feed_at = stale
    product.updated_at = stale
    await db_session.commit()

    # Still in the feed, with byte-identical data: no ORM-visible change.
    result = await sync_vivape_catalog(db_session)

    # Guards the guard: if this product ever stops being a true no-op, the
    # test stops reproducing the bug and must fail loudly rather than pass
    # for the wrong reason.
    assert result["updated_products"] == 0, "fixture no longer reproduces an unchanged product"
    assert result["deactivated_products"] == 0, "deactivated a product that is still in the supplier feed"
    await db_session.refresh(product)
    assert product.is_active is True
    assert product.last_seen_in_feed_at > stale, "last_seen_in_feed_at was not refreshed by the sync"


async def test_seeing_an_unchanged_product_does_not_rewrite_updated_at(db_session, monkeypatch):
    """last_seen_in_feed_at answers "when did the feed last list this",
    updated_at answers "when did this product's data last change". Keeping
    them separate is the point of the fix, so the sync must not quietly
    bump updated_at for every product on every run."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_STABLE_PRICE]})
    )
    await sync_vivape_catalog(db_session)

    res = await db_session.execute(select(Product).where(Product.supplier_product_id == 9992))
    product = res.scalar_one()
    updated_at_before = product.updated_at

    result = await sync_vivape_catalog(db_session)

    await db_session.refresh(product)
    assert product.updated_at == updated_at_before
    assert result["products_in_feed"] == 1
    assert result["updated_products"] == 0, "reported a change for a product nothing changed about"


async def test_a_mass_deactivation_is_refused_rather_than_emptying_the_catalog(db_session, monkeypatch):
    """The circuit breaker. No supplier retires its whole catalogue at
    once, so a sweep that large is far likelier to be a bug in us - as it
    was. Refusing it leaves every product purchasable and reports itself,
    because an alert is recoverable and an empty storefront is not."""
    many = [
        {
            "id": 90000 + i, "price": 3.0 + i, "reference": "esimgo_bundle",
            "title": f"eSIM, {i + 1}GB, 7 Days, Thailand, V2",
            "receiver_amount_min": "1000", "receiver_amount_max": "1000",
        }
        for i in range(30)
    ]
    # The breaker trips on a SHARE of the active catalog, so the test has to
    # say what the catalog is. Products left behind by other modules (the
    # session is not rolled back between tests) would otherwise dilute the
    # denominator until 30 retirements look routine - which is exactly how
    # this passed alone and failed in the full suite.
    await db_session.execute(
        update(Product).where(Product.supplier_product_id.isnot(None)).values(is_active=False)
    )
    await db_session.commit()

    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_factory([THAILAND], {212: many}))
    await sync_vivape_catalog(db_session)

    mine = (await db_session.execute(
        select(Product).where(Product.supplier_product_id.between(90000, 90029))
    )).scalars().all()
    assert len(mine) == 30
    stale = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
    for p in mine:
        p.last_seen_in_feed_at = stale
    await db_session.commit()

    # The whole feed comes back empty - a supplier outage, a bad token, a
    # parsing regression. Whatever the cause, it is not 30 retirements.
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_factory([THAILAND], {212: []}))
    result = await sync_vivape_catalog(db_session)

    assert result["deactivation_skipped"] is True
    assert result["deactivated_products"] == 0
    assert result["deactivation_candidates"] >= 30
    still_active = (await db_session.execute(
        select(Product).where(
            Product.supplier_product_id.between(90000, 90029), Product.is_active == True  # noqa: E712
        )
    )).scalars().all()
    assert len(still_active) == 30, "catalog was emptied despite the circuit breaker"


async def test_a_hand_created_product_is_never_deactivated_by_the_sweep(db_session, monkeypatch):
    """A product with no supplier_product_id is in nobody's feed, so
    last_seen_in_feed_at stays NULL forever and no sync could ever revive
    it. Deactivating it would be a one-way door the admin never opened."""
    from conftest import create_test_product

    manual = await create_test_product(db_session, supplier_product_id=None)
    manual.last_seen_in_feed_at = None
    manual.updated_at = datetime.now(timezone.utc) - STALE_GRACE - timedelta(days=7)
    await db_session.commit()

    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        _mock_get_factory([THAILAND], {212: [THAILAND_1GB_7D]})
    )
    result = await sync_vivape_catalog(db_session)

    assert result["deactivated_products"] == 0
    await db_session.refresh(manual)
    assert manual.is_active is True

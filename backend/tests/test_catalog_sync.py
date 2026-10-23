from datetime import datetime, timedelta, timezone

import pytest
import httpx
from sqlalchemy import select
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
    product.updated_at = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
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
    product.updated_at = datetime.now(timezone.utc) - STALE_GRACE - timedelta(hours=1)
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

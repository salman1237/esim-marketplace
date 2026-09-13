import pytest
from sqlalchemy import select

from conftest import register_and_login
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.catalog import Product
from app.services.catalog_parsing import parse_vivape_product

pytestmark = pytest.mark.asyncio


async def test_base_currency_is_euro():
    """VivaPe prices in euro and catalog costs are stored as VivaPe reports
    them - every amount in the system is EUR."""
    assert settings.BASE_CURRENCY == "EUR"
    assert settings.DEFAULT_CURRENCY == "EUR"


async def test_new_accounts_get_euro_wallets(client, promote_role):
    user = await register_and_login(client, "eurowallets")
    await promote_role(user["user_id"], "MERCHANT")  # DEFAULT, REWARD and COMMISSION wallets

    wallets = (await client.get("/api/v1/wallets/my-wallets", headers=user["headers"])).json()
    assert wallets
    assert {w["currency"] for w in wallets} == {"EUR"}


async def test_public_settings_default_to_euro(client):
    body = (await client.get("/api/v1/settings/public")).json()
    assert body["default_currency"] in ("EUR",)


async def test_products_default_to_euro():
    assert Product.__table__.c.currency.default.arg == "EUR"
    parsed = parse_vivape_product({"id": 1, "price": 3.5, "reference": "esimgo_bundle", "title": "eSIM, 1GB, 7 Days, Thailand, V2"})
    # The VivaPe price is stored unconverted, as the euro cost.
    assert str(parsed["cost_price"]) == "3.5"

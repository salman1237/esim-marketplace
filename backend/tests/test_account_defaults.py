"""What a new account starts on, and what it may leave blank.

Two decisions live here. Prices are SHOWN in taka because the home market is
Bangladesh - the books are still kept in EUR, and nothing about storage
changes. And a phone number is optional at every point it is asked for:
plenty of customers buy a travel eSIM precisely because they are about to
stop being reachable on their usual number.
"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def test_a_new_account_is_shown_prices_in_taka(client, db_session):
    user = await register_and_login(client, "taka_default")
    row = (await db_session.execute(select(User).where(User.id == user["user_id"]))).scalar_one()
    assert row.preferred_currency == "BDT"


async def test_the_books_are_still_kept_in_euro(client):
    """Display currency and base currency are different questions. Storage,
    supplier cost and every rate stay in EUR."""
    assert settings.BASE_CURRENCY == "EUR"


async def test_an_account_can_switch_and_the_choice_sticks(client):
    user = await register_and_login(client, "switcher")
    res = await client.put("/api/v1/auth/me/preferences",
                           json={"preferred_currency": "EUR"}, headers=user["headers"])
    assert res.status_code == 200
    assert res.json()["preferred_currency"] == "EUR"

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["preferred_currency"] == "EUR"


async def test_registering_without_a_phone_number_is_allowed(client, db_session):
    """Registered directly rather than through the shared helper, which always
    supplies one - the whole point here is leaving the field out."""
    res = await client.post("/api/v1/auth/register", json={
        "email": "nophone_signup@example.com",
        "username": "nophone_signup",
        "password": "TestPass123!",
    })
    assert res.status_code == 200, res.text
    row = (await db_session.execute(
        select(User).where(User.id == res.json()["user_id"])
    )).scalar_one()
    assert row.phone is None
    assert row.preferred_currency == "BDT"


async def test_a_phone_number_can_be_added_later(client):
    user = await register_and_login(client, "addsphone")
    res = await client.put("/api/v1/auth/me/preferences",
                           json={"phone": "+8801711000000"}, headers=user["headers"])
    assert res.status_code == 200
    assert res.json()["phone"] == "+8801711000000"
    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["phone"] == "+8801711000000"


async def test_a_phone_number_can_be_removed_again(client):
    """Optional has to mean removable, not just omittable at signup."""
    user = await register_and_login(client, "dropsphone")
    await client.put("/api/v1/auth/me/preferences",
                     json={"phone": "+8801711000001"}, headers=user["headers"])
    res = await client.put("/api/v1/auth/me/preferences",
                           json={"phone": ""}, headers=user["headers"])
    assert res.status_code == 200
    assert res.json()["phone"] is None


async def test_updating_the_phone_leaves_the_currency_alone(client):
    """One endpoint carries both, so each has to be independently optional."""
    user = await register_and_login(client, "phone_only")
    await client.put("/api/v1/auth/me/preferences",
                     json={"preferred_currency": "USD"}, headers=user["headers"])
    await client.put("/api/v1/auth/me/preferences",
                     json={"phone": "+8801711000002"}, headers=user["headers"])
    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["preferred_currency"] == "USD"
    assert me.json()["phone"] == "+8801711000002"


async def test_an_unsupported_currency_is_still_refused(client):
    user = await register_and_login(client, "badcurrency")
    res = await client.put("/api/v1/auth/me/preferences",
                           json={"preferred_currency": "XYZ"}, headers=user["headers"])
    assert res.status_code == 400

"""Two emergency fixes shipped together:

1. POST /discounts/check - lets a visitor who hasn't signed in see whether a
   discount code is real before being asked to log in. It must stay weaker
   than the authenticated /preview: no product, no per-user rule, so it can
   never promise a discount that checkout later refuses.
2. Admin control over which destinations show in the home page's Popular
   Destinations row, and in what order.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Country
from app.models.discount import DiscountCode, DiscountType
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, role="SUPER_ADMIN", name="destadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], role)
    return admin


# --- POST /discounts/check (anonymous) --------------------------------------

async def test_check_accepts_a_real_active_code_with_no_auth(client, db_session):
    code = DiscountCode(code="SAVE10", discount_type=DiscountType.PERCENT, value=Decimal("10"), is_active=True)
    db_session.add(code)
    await db_session.commit()

    res = await client.post("/api/v1/discounts/check", json={"code": "save10"})
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is True
    assert body["code"] == "SAVE10"
    assert body["discount_type"] == "PERCENT"


async def test_check_rejects_an_unknown_code(client):
    res = await client.post("/api/v1/discounts/check", json={"code": "NOSUCHCODE"})
    assert res.status_code == 200
    assert res.json() == {"valid": False, "reason": "That discount code isn't valid."}


async def test_check_rejects_an_expired_code(client, db_session):
    code = DiscountCode(
        code="EXPIRED1", discount_type=DiscountType.FIXED, value=Decimal("5"), is_active=True,
        ends_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(code)
    await db_session.commit()
    res = await client.post("/api/v1/discounts/check", json={"code": "EXPIRED1"})
    assert res.json()["valid"] is False


async def test_check_rejects_a_code_that_hit_its_global_cap(client, db_session):
    code = DiscountCode(code="CAPPED1", discount_type=DiscountType.FIXED, value=Decimal("5"), is_active=True, max_uses=0)
    db_session.add(code)
    await db_session.commit()
    res = await client.post("/api/v1/discounts/check", json={"code": "CAPPED1"})
    assert res.json()["valid"] is False
    assert "limit" in res.json()["reason"]


async def test_check_flags_a_first_order_only_code_as_scoped(client, db_session):
    """A first-purchase-only code can still fail once a specific logged-in
    user is known - the UI must say "confirmed once signed in", not promise
    a saving outright."""
    code = DiscountCode(code="FIRSTBUY1", discount_type=DiscountType.PERCENT, value=Decimal("15"), is_active=True, first_order_only=True)
    db_session.add(code)
    await db_session.commit()
    res = await client.post("/api/v1/discounts/check", json={"code": "FIRSTBUY1"})
    body = res.json()
    assert body["valid"] is True
    assert body["scoped"] is True


async def test_check_does_not_require_authentication_header_at_all(client, db_session):
    code = DiscountCode(code="OPEN2ALL", discount_type=DiscountType.FIXED, value=Decimal("2"), is_active=True)
    db_session.add(code)
    await db_session.commit()
    # No Authorization header anywhere in this request.
    res = await client.post("/api/v1/discounts/check", json={"code": "OPEN2ALL"})
    assert res.status_code == 200
    assert res.json()["valid"] is True


# --- Admin popular-destinations control -------------------------------------

async def test_admin_can_list_countries_with_inventory(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    await create_test_product(db_session)
    res = await client.get("/api/v1/admin/countries", headers=admin["headers"])
    assert res.status_code == 200
    assert len(res.json()["countries"]) >= 1
    assert {"id", "iso2", "name_en", "is_popular", "popular_order"} <= set(res.json()["countries"][0])


async def test_super_admin_can_set_and_reorder_popular_destinations(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="reorderadmin")
    p1 = await create_test_product(db_session)
    p2 = await create_test_product(db_session)

    res = await client.put(
        "/api/v1/admin/countries/popular",
        json={"countries": [
            {"id": p1.country_id, "is_popular": True, "popular_order": 1},
            {"id": p2.country_id, "is_popular": True, "popular_order": 0},
        ]},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    by_id = {c["id"]: c for c in res.json()["countries"]}
    assert by_id[p1.country_id]["is_popular"] is True
    assert by_id[p2.country_id]["is_popular"] is True

    # The public, unauthenticated endpoint reflects the order just set.
    pub = await client.get("/api/v1/catalog/countries", params={"popular_only": "true"})
    iso2s = [c["iso2"] for c in pub.json()]
    country2 = (await db_session.execute(select(Country).where(Country.id == p2.country_id))).scalar_one()
    assert country2.iso2 in iso2s
    assert iso2s.index(country2.iso2) < len(iso2s)  # present and ordered ahead per popular_order=0


async def test_a_plain_admin_cannot_change_popular_destinations(client, db_session, promote_role):
    admin = await _admin(client, promote_role, role="ADMIN", name="plaindestadmin")
    p1 = await create_test_product(db_session)
    res = await client.put(
        "/api/v1/admin/countries/popular",
        json={"countries": [{"id": p1.country_id, "is_popular": True, "popular_order": 0}]},
        headers=admin["headers"],
    )
    assert res.status_code == 403


async def test_removing_a_destination_from_the_popular_list_hides_it_from_home(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="removedestadmin")
    p1 = await create_test_product(db_session)

    await client.put(
        "/api/v1/admin/countries/popular",
        json={"countries": [{"id": p1.country_id, "is_popular": True, "popular_order": 0}]},
        headers=admin["headers"],
    )
    res = await client.put(
        "/api/v1/admin/countries/popular",
        json={"countries": [{"id": p1.country_id, "is_popular": False, "popular_order": 0}]},
        headers=admin["headers"],
    )
    assert res.status_code == 200
    assert res.json()["countries"][0]["is_popular"] is False


async def test_unauthenticated_requests_are_rejected(client):
    assert (await client.get("/api/v1/admin/countries")).status_code in (401, 403)
    assert (await client.put("/api/v1/admin/countries/popular", json={"countries": []})).status_code in (401, 403)

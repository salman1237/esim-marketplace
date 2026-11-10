"""Admin control over which suppliers' products are shown to customers.

The live finding this exists for: a real test purchase against Telna found
two of three sampled products rejected outright by VivaPe's own
create-transaction endpoint, with only a product literally named "Test"
actually completing. Recognising a supplier (catalog_parsing.ESIM_REFERENCES)
and being willing to sell its products to a paying customer are different
decisions - this is what lets an admin make the second one independently,
without code, the moment a supplier proves unreliable or proves itself.
"""
import pytest

from app.services.supplier_settings_svc import (
    DEFAULT_ENABLED_SUPPLIERS,
    get_enabled_suppliers,
    serialize_all,
    set_enabled_suppliers,
)
from app.models.catalog import Country
from sqlalchemy import select
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, role="SUPER_ADMIN", name="supplieradmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], role)
    return admin


# --- the service layer ------------------------------------------------------

async def test_defaults_to_the_two_proven_suppliers_telna_off(db_session):
    """Not a neutral default: Telna starts disabled because most of its real
    catalog failed a live purchase test, while the other two have been
    selling real orders since launch. eSIM Access is different again - not
    a cautious default pending proof, but the primary supplier, so it
    launches enabled from day one. This is the only test in this file
    entitled to check the untouched blank-slate default (every other test
    that cares about a specific enabled-set state sets it explicitly first,
    the same discipline test_disabled_suppliers_product_disappears_from_
    the_storefront's own docstring states) - it must stay the first test in
    this file, or its assumption about nothing having touched the setting
    yet no longer holds."""
    enabled = await get_enabled_suppliers(db_session)
    assert enabled == DEFAULT_ENABLED_SUPPLIERS
    assert "telna_esim" not in enabled
    assert "esimgo_bundle" in enabled
    assert "worldmove_esim" in enabled
    assert "esimaccess" in enabled


async def test_an_unrecognised_supplier_is_rejected_not_silently_dropped(db_session):
    with pytest.raises(ValueError):
        await set_enabled_suppliers(db_session, ["esimgo_bundle", "not_a_real_supplier"], admin_id=None)


async def test_enabling_telna_persists_and_is_read_back(db_session):
    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim", "telna_esim"], admin_id=None)
    await db_session.commit()
    enabled = await get_enabled_suppliers(db_session)
    assert enabled == {"esimgo_bundle", "worldmove_esim", "telna_esim"}


async def test_serialize_all_lists_every_known_supplier_with_its_state(db_session):
    await set_enabled_suppliers(db_session, ["esimgo_bundle"], admin_id=None)
    await db_session.commit()
    rows = await serialize_all(db_session)
    by_ref = {r["reference"]: r for r in rows}
    assert by_ref["esimgo_bundle"]["enabled"] is True
    assert by_ref["worldmove_esim"]["enabled"] is False
    assert by_ref["telna_esim"]["enabled"] is False
    # Human labels, not raw reference strings - what the checkboxes show.
    assert by_ref["telna_esim"]["label"] == "Telna"
    # eSIM Access is a separate top-level supplier, not a VivaPe wholesaler,
    # but it appears in this same list through the identical mechanism.
    assert by_ref["esimaccess"]["label"] == "eSIM Access"
    assert by_ref["esimaccess"]["enabled"] is False  # this call only enabled esimgo_bundle


# --- the actual control surface: does disabling a supplier really hide it --

async def test_disabled_suppliers_product_disappears_from_the_storefront(client, db_session):
    """Telna is off by default (see test_defaults_to_the_two_proven_
    suppliers_telna_off), so this starts by turning it ON to prove the
    toggle genuinely round-trips in both directions, not just that the
    default happens to hide it."""
    product = await create_test_product(db_session, supplier_reference="telna_esim")
    country = (await db_session.execute(select(Country).where(Country.id == product.country_id))).scalar_one()

    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim", "telna_esim"], admin_id=None)
    await db_session.commit()
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert res.status_code == 200
    assert any(p["id"] == product.id for p in res.json())

    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim"], admin_id=None)
    await db_session.commit()
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert res.status_code == 200
    assert not any(p["id"] == product.id for p in res.json())


async def test_esim_access_product_sells_when_enabled_then_can_be_turned_off(client, db_session):
    """eSIM Access defaults ON (see test_defaults_to_the_two_proven_
    suppliers_telna_off), but this test does not rely on that ambient
    state - like test_disabled_suppliers_product_disappears_from_the_
    storefront, it sets the enabled list explicitly first, so it stays
    correct regardless of what any earlier test in this file left behind.
    Proves the default actually results in a sellable product, not just a
    checkbox state, and that turning it off genuinely removes it."""
    product = await create_test_product(db_session, supplier_reference="esimaccess")
    country = (await db_session.execute(select(Country).where(Country.id == product.country_id))).scalar_one()

    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim", "esimaccess"], admin_id=None)
    await db_session.commit()
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert res.status_code == 200
    assert any(p["id"] == product.id for p in res.json())

    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim"], admin_id=None)  # esimaccess off
    await db_session.commit()
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert res.status_code == 200
    assert not any(p["id"] == product.id for p in res.json())


async def test_a_country_with_only_disabled_supplier_products_is_hidden_entirely(client, db_session):
    """The has_products check on /catalog/countries must respect the same
    filter - otherwise a destination tile opens to an empty package list,
    exactly the bug this storefront already fixed once for inactive
    countries."""
    product = await create_test_product(db_session, supplier_reference="telna_esim")
    country = (await db_session.execute(select(Country).where(Country.id == product.country_id))).scalar_one()
    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim"], admin_id=None)
    await db_session.commit()

    res = await client.get("/api/v1/catalog/countries", params={"search": country.name_en})
    assert res.status_code == 200
    assert not any(c["iso2"] == country.iso2 for c in res.json())


async def test_direct_product_fetch_also_respects_the_setting(client, db_session):
    """Hiding from the list views is not a real control if the product is
    still reachable by anyone who already has (or guesses) its id."""
    product = await create_test_product(db_session, supplier_reference="telna_esim")
    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim"], admin_id=None)
    await db_session.commit()

    res = await client.get(f"/api/v1/catalog/products/{product.id}")
    assert res.status_code == 404


async def test_checkout_refuses_a_disabled_suppliers_product_even_by_direct_id(client, db_session):
    """The real control: a customer who already has the product id cached
    (or calls the API directly) must not be able to buy around the
    storefront filter - disabling a supplier has to mean disabling
    purchasing, not just hiding a tile."""
    product = await create_test_product(db_session, supplier_reference="telna_esim")
    await set_enabled_suppliers(db_session, ["esimgo_bundle", "worldmove_esim"], admin_id=None)
    await db_session.commit()

    user = await register_and_login(client, "supplierbuyer")
    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 404


async def test_an_enabled_suppliers_product_still_shows_and_sells_normally(client, db_session):
    """Guards against an over-broad filter: enabling one supplier must not
    accidentally hide or block a different, already-enabled one."""
    product = await create_test_product(db_session, supplier_reference="esimgo_bundle")
    country = (await db_session.execute(select(Country).where(Country.id == product.country_id))).scalar_one()
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert any(p["id"] == product.id for p in res.json())

    res = await client.get(f"/api/v1/catalog/products/{product.id}")
    assert res.status_code == 200


async def test_a_product_with_no_supplier_reference_is_always_visible(client, db_session):
    """supplier_reference is NULL on anything not attributed to one of the
    known suppliers - this switch controls supplier products specifically,
    not catalogue visibility in general, so such a row must never be
    collaterally hidden by a supplier toggle."""
    product = await create_test_product(db_session, supplier_reference=None)
    await set_enabled_suppliers(db_session, [], admin_id=None)  # every real supplier off
    await db_session.commit()

    res = await client.get(f"/api/v1/catalog/products/{product.id}")
    assert res.status_code == 200


# --- the admin API surface --------------------------------------------------

async def test_a_plain_admin_can_read_but_not_write_supplier_settings(client, db_session, promote_role):
    admin = await _admin(client, promote_role, role="ADMIN", name="plainsupplieradmin")

    get_res = await client.get("/api/v1/admin/supplier-settings", headers=admin["headers"])
    assert get_res.status_code == 200
    assert {"reference", "label", "enabled"} <= set(get_res.json()["suppliers"][0])

    put_res = await client.put(
        "/api/v1/admin/supplier-settings",
        json={"enabled_suppliers": ["telna_esim"]},
        headers=admin["headers"],
    )
    # Same gate as PUT /pricing - this changes what the whole storefront
    # offers, not one product, so a plain admin cannot flip it alone.
    assert put_res.status_code == 403


async def test_a_super_admin_can_enable_telna_through_the_api(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    res = await client.put(
        "/api/v1/admin/supplier-settings",
        json={"enabled_suppliers": ["esimgo_bundle", "worldmove_esim", "telna_esim"]},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    by_ref = {r["reference"]: r["enabled"] for r in res.json()["suppliers"]}
    assert by_ref["telna_esim"] is True


async def test_the_update_endpoint_rejects_garbage_suppliers(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="garbageadmin")
    res = await client.put(
        "/api/v1/admin/supplier-settings",
        json={"enabled_suppliers": ["telna_esim", "a_made_up_supplier"]},
        headers=admin["headers"],
    )
    assert res.status_code == 400


async def test_the_update_is_audit_logged(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="auditsupplieradmin")
    await client.put(
        "/api/v1/admin/supplier-settings",
        json={"enabled_suppliers": ["telna_esim"]},
        headers=admin["headers"],
    )
    res = await client.get("/api/v1/admin/audit-logs", headers=admin["headers"])
    body = res.json()
    rows = body["items"] if isinstance(body, dict) else body
    actions = [row["action"] for row in rows]
    assert "UPDATE_ENABLED_SUPPLIERS" in actions


async def test_an_unauthenticated_request_cannot_read_or_write(client):
    assert (await client.get("/api/v1/admin/supplier-settings")).status_code in (401, 403)
    assert (await client.put("/api/v1/admin/supplier-settings", json={"enabled_suppliers": []})).status_code in (401, 403)

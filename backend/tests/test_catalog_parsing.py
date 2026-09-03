from decimal import Decimal
from app.services.catalog_parsing import parse_vivape_product

# Captured directly from the live VivaPe catalog (GET /api/products) — see
# the VivaPe Postman collection at
# documenter.getpostman.com/view/12835212/2sAYQdjALq for the endpoint list.
# Kept verbatim (not simplified) so these tests catch the same class of bug
# the ShurjoPay investigation found: assumptions about a supplier's real
# response shape that were never actually checked against it.

THAILAND_1GB_7D = {
    "id": 9991, "vivape_id": "VPPRESMGesim_1GB_7D_TH_V2", "price": 3.129411764705978,
    "reference": "esimgo_bundle", "title": "eSIM, 1GB, 7 Days, Thailand, V2",
    "country_id": 212, "receiver_type": "0",
    "receiver_amount_min": "1000", "receiver_amount_max": "1000", "receiver_amount_currency": "TH",
}

THAILAND_UNLIMITED_3D = {
    "id": 10761, "vivape_id": "VPPRESMGesim_UL_3D_TH_V2", "price": 10.94,
    "reference": "esimgo_bundle", "title": "eSIM, Unlimited, 3 Days, Thailand, V2",
    "country_id": 212, "receiver_type": "1",
    "receiver_amount_min": "-1", "receiver_amount_max": "-1", "receiver_amount_currency": "TH",
}

JAPAN_WORLDMOVE_10GB = {
    "id": 16434, "price": 14.38,
    "reference": "worldmove_esim", "title": "Japan, 15 Days, 10GB, 128kbps",
    "country_id": 107, "receiver_type": 0,
    # NOT the GB*1000 pattern esimgo_bundle uses — a different, cost-like
    # unit specific to this supplier reference (~3.7x the USD price here).
    "receiver_amount_min": 3.888, "receiver_amount_max": 3.888,
}

BANGLADESH_MOBILE_TOPUP = {
    "id": 15598, "price": 9.503267973856497,
    "reference": "ranged_price", "title": "20 TK TOP UP",
    "country_id": 18, "receiver_type": "topup",
    "receiver_amount_min": "20", "receiver_amount_max": "1000",
}


def test_esimgo_bundle_fixed_data_plan():
    parsed = parse_vivape_product(THAILAND_1GB_7D)
    assert parsed is not None
    assert parsed["data_amount_gb"] == Decimal("1")
    assert parsed["validity_days"] == 7
    assert parsed["is_unlimited"] is False
    # This is the field that was previously never captured, and the bug
    # this whole module exists to prevent: create-transaction's
    # receiver_amount must be VivaPe's own 1000 (MB), never derived from
    # cost_price (~3.13, which would provision ~3MB instead of 1GB).
    assert parsed["supplier_receiver_amount"] == Decimal("1000")
    assert parsed["cost_price"] == Decimal(str(THAILAND_1GB_7D["price"]))


def test_unlimited_plan_is_flagged_not_mislabeled_as_3gb():
    """Regression test: 'Unlimited' plans have no GB figure in the title,
    so the GB regex always missed and silently fell back to a hardcoded
    3.0 GB — mislabeling e.g. an Unlimited/3-Days plan as a small fixed
    3GB one, with is_unlimited never set at all."""
    parsed = parse_vivape_product(THAILAND_UNLIMITED_3D)
    assert parsed is not None
    assert parsed["is_unlimited"] is True
    assert parsed["data_amount_gb"] == Decimal("0")
    assert parsed["validity_days"] == 3
    # VivaPe's own sentinel for "no fixed data amount" must round-trip
    # unchanged, not get coerced into some other number.
    assert parsed["supplier_receiver_amount"] == Decimal("-1")


def test_worldmove_esim_receiver_amount_is_not_gb_times_1000():
    """worldmove_esim's receiver_amount uses a different unit than
    esimgo_bundle's (confirmed live: Japan's 10GB plan reports 3.888, not
    10000) — parse_vivape_product must not assume one universal formula
    and must just pass through whatever the catalog reports."""
    parsed = parse_vivape_product(JAPAN_WORLDMOVE_10GB)
    assert parsed is not None
    assert parsed["data_amount_gb"] == Decimal("10")
    assert parsed["validity_days"] == 15
    assert parsed["supplier_receiver_amount"] == Decimal("3.888")


def test_non_esim_product_is_filtered_out():
    """Bangladesh's domestic mobile top-up catalog (reference='ranged_price')
    must never be classified as an eSIM product."""
    assert parse_vivape_product(BANGLADESH_MOBILE_TOPUP) is None

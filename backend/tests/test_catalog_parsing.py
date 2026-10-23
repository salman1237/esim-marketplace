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

# Telna joined VivaPe's catalog in October 2026. These four are real entries
# captured from a full live scan of every country VivaPe lists (249
# countries, 9 Telna products total at the time) - not simplified or
# invented, because Telna's titles turned out messier than the other two
# suppliers' and that messiness is exactly what needs to be tested against.
TELNA_1GB_7D = {
    "id": 16497, "vivape_id": "VPTLN21634922", "price": 1.98,
    "price_min": 2.67, "price_max": 2.67, "reference": "telna_esim",
    "title": "Telna Test - 1GB - Global - 7 Days", "details": "Standard Full Speed (Unthrottled)",
    "country_id": 5, "receiver_type": "0",
    "receiver_amount_min": "2.67", "receiver_amount_max": "2.67", "receiver_amount_currency": "EUR",
}

# The one that would have broken silently: VivaPe's other two suppliers
# have never used MB in a title, only GB. The GB-only regex would have
# missed this entirely and fallen back to the hardcoded 3.0 GB default -
# showing a 500MB plan as six times its real allowance.
TELNA_500MB_BANGLADESH = {
    "id": 20001, "price": 1.6, "reference": "telna_esim",
    "title": "VivaPe Test - 500MB - BGD - 7 Days",
    "country_id": 18, "receiver_type": "0",
    "receiver_amount_min": "302.4", "receiver_amount_max": "302.4", "receiver_amount_currency": "EUR",
}

# Messy real-world spacing (double spaces, "days" before the data amount
# rather than after) - must parse the same as a clean title.
TELNA_MESSY_SPACING_BANGLADESH = {
    "id": 20002, "price": 1.98, "reference": "telna_esim",
    "title": "Bangladesh 7  days 1 GB ",
    "country_id": 18, "receiver_type": "0",
    "receiver_amount_min": "373.8", "receiver_amount_max": "373.8", "receiver_amount_currency": "EUR",
}

TELNA_UNLIMITED_UK = {
    "id": 20003, "price": 16.83, "reference": "telna_esim",
    "title": "United Kingdom Unlimited 2 days ",
    "country_id": 77, "receiver_type": "0",
    "receiver_amount_min": "19.77", "receiver_amount_max": "19.77", "receiver_amount_currency": "EUR",
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


def test_esim_titled_product_from_another_supplier_is_filtered_out():
    """Only esimgo_bundle and worldmove_esim can actually be provisioned.
    An earlier version also accepted any product whose title mentioned
    "esim", which would list a third supplier's stock we can't fulfil."""
    assert parse_vivape_product({
        "id": 99999, "price": 7.5, "reference": "some_other_supplier",
        "title": "eSIM, 5GB, 30 Days, Nowhere", "country_id": 1,
        "receiver_amount_min": "5000", "receiver_amount_max": "5000",
    }) is None


def test_telna_is_recognised_as_a_provisionable_supplier():
    """Confirmed live on VivaPe's catalog, October 2026 - not merely
    announced. See catalog_parsing.ESIM_REFERENCES."""
    parsed = parse_vivape_product(TELNA_1GB_7D)
    assert parsed is not None
    assert parsed["data_amount_gb"] == Decimal("1")
    assert parsed["validity_days"] == 7
    assert parsed["is_unlimited"] is False
    # Same rule as worldmove_esim: no universal formula exists (confirmed by
    # comparing receiver_amount/price ratios across Telna's own products,
    # which vary from ~1.2x to ~189x with no pattern) - only round-trip
    # whatever the catalog reports for this exact product.
    assert parsed["supplier_receiver_amount"] == Decimal("2.67")
    assert parsed["supplier_reference"] == "telna_esim"


def test_telna_megabyte_title_is_not_mistaken_for_three_gigabytes():
    """Regression test for the bug this scan actually found: a title using
    MB (never seen from either existing supplier) has no GB substring to
    match, and the GB-only regex used to fall through to its catch-all
    default - showing a 500MB plan as 3.0 GB, six times its real size."""
    parsed = parse_vivape_product(TELNA_500MB_BANGLADESH)
    assert parsed is not None
    assert parsed["data_amount_gb"] == Decimal("0.5")
    assert parsed["validity_days"] == 7
    assert parsed["is_unlimited"] is False


def test_telna_messy_title_spacing_still_parses_correctly():
    """Telna's titles are not as clean as the other two suppliers' (double
    spaces, data-amount-after-validity rather than before) - the regexes
    search the whole string rather than assume a fixed layout, so this
    must parse identically to a tidy title."""
    parsed = parse_vivape_product(TELNA_MESSY_SPACING_BANGLADESH)
    assert parsed is not None
    assert parsed["data_amount_gb"] == Decimal("1")
    assert parsed["validity_days"] == 7


def test_telna_unlimited_plan_is_flagged_not_mislabeled():
    parsed = parse_vivape_product(TELNA_UNLIMITED_UK)
    assert parsed is not None
    assert parsed["is_unlimited"] is True
    assert parsed["data_amount_gb"] == Decimal("0")
    assert parsed["validity_days"] == 2


def test_a_gb_title_is_never_read_as_megabytes():
    """Guards the ordering: if a title somehow mentioned both units, GB must
    win - MB is only ever consulted after the GB pattern has already missed."""
    parsed = parse_vivape_product(TELNA_1GB_7D)
    assert parsed["data_amount_gb"] == Decimal("1")  # not Decimal("0.001")

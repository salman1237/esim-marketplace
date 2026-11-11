"""Parses a raw VivaPe /api/products entry into eSIM catalog fields.

Extracted into its own module so it can be unit tested directly against
real captured VivaPe responses (see tests/test_catalog_parsing.py) without
needing network access or a live merchant account — this is exactly the
kind of parsing logic where an untested assumption about the supplier's
response shape turned out wrong before (see the ShurjoPay fixes earlier in
this project's history) and is cheap to lock down with a real fixture.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services.pricing_svc import DEFAULT_SELLING_PROFIT_PCT, retail_price_for
from app.services.esimaccess_adapter import day_pass_total_price, scaled_to_decimal

# Telna joined VivaPe's catalog in October 2026 (VivaPe's own notice: their
# existing suppliers "will discontinue... very soon"). Confirmed live against
# their real feed before adding it here, not assumed from the announcement.
ESIM_REFERENCES = ("esimgo_bundle", "worldmove_esim", "telna_esim")

_GB_RE = re.compile(r"(\d+(\.\d+)?)\s*GB", re.IGNORECASE)
# Telna is the first supplier whose titles use MB for small plans (e.g.
# "VivaPe Test - 500MB - BGD - 7 Days", confirmed live). Checked only when
# the GB pattern didn't match, so a title mentioning both (there are none
# today, but "GB" would otherwise also satisfy a careless MB-only regex)
# can never be read as the wrong unit.
_MB_RE = re.compile(r"(\d+(\.\d+)?)\s*MB", re.IGNORECASE)
_DAYS_RE = re.compile(r"(\d+)\s*Days?", re.IGNORECASE)


def parse_vivape_product(p: dict, profit_pct: Decimal = DEFAULT_SELLING_PROFIT_PCT) -> Optional[dict]:
    """Returns None unless `p`'s `reference` is one of the two eSIM
    supplier types we can provision, else a dict of fields ready to build
    a Product row.
    """
    # Strictly the two eSIM suppliers we resell. An earlier version also
    # accepted anything with "esim" in its title, which let other
    # suppliers' products (and VivaPe's own non-eSIM listings that merely
    # mention the word) into the catalog - we can only actually provision
    # esimgo_bundle and worldmove_esim.
    ref = str(p.get("reference") or "")
    title = str(p.get("title") or p.get("name") or "")
    if ref.lower() not in ESIM_REFERENCES:
        return None

    cost = Decimal(str(p.get("price") or p.get("amount") or 5.0))
    # Selling price follows the admin's global selling profit % (pricing_svc).
    retail = retail_price_for(cost, profit_pct)

    # "Unlimited" plans have no GB figure in the title at all (confirmed
    # against the live catalog: e.g. "eSIM, Unlimited, 3 Days, Thailand,
    # V2") — matching the GB regex against them always misses and used to
    # silently fall back to a hardcoded "3.0 GB", mislabeling an unlimited
    # plan as a small fixed-data one. is_unlimited is the real signal now;
    # data_amount_gb is meaningless for these and left at 0.
    is_unlimited = "unlimited" in title.lower()
    gb_match = None if is_unlimited else _GB_RE.search(title)
    # Only looked for once GB has already missed - GB must always win over
    # MB if a title somehow mentioned both, and in practice every title
    # observed so far uses exactly one of the two.
    mb_match = None if (is_unlimited or gb_match) else _MB_RE.search(title)
    days_match = _DAYS_RE.search(title)

    if is_unlimited:
        data_amount = Decimal("0")
    elif gb_match:
        data_amount = Decimal(gb_match.group(1))
    elif mb_match:
        # 500MB must read as 0.5 GB, not fall through to the 3.0 GB
        # fallback below - that fallback is for a title with NEITHER unit,
        # not a cue to silently show six times the real allowance.
        data_amount = (Decimal(mb_match.group(1)) / Decimal(1000)).quantize(Decimal("0.001"))
    else:
        data_amount = Decimal("3.0")
    validity = int(days_match.group(1)) if days_match else 15

    # VivaPe's own receiver_amount_min/max for this exact product — the
    # value create-transaction's receiver_amount must be. Confirmed against
    # the live catalog this is NOT a price and its meaning differs by
    # supplier_reference (MB quantity for esimgo_bundle: 1000 for a 1GB
    # plan, -1 for unlimited; an unrelated cost-like figure for
    # worldmove_esim, roughly 3.7x the USD price). There is no way to
    # derive it from cost_price or the title — only round-trip whatever
    # value the catalog itself reports for this specific product.
    receiver_amount_raw = p.get("receiver_amount_min")
    if receiver_amount_raw is None:
        receiver_amount_raw = p.get("receiver_amount_max")
    try:
        supplier_receiver_amount = Decimal(str(receiver_amount_raw)) if receiver_amount_raw is not None else None
    except (InvalidOperation, ValueError):
        supplier_receiver_amount = None

    return {
        "supplier_product_id": p.get("id"),
        "title": title,
        "data_amount_gb": data_amount,
        "validity_days": validity,
        "cost_price": cost,
        "retail_price": retail,
        "is_unlimited": is_unlimited,
        "supplier_reference": ref,
        "supplier_receiver_amount": supplier_receiver_amount,
    }


# eSIM Access dataType values, per backend/docs/esimaccess_integration_
# reference.md section 6:
#   1 = fixed data, a stable-price fixed-validity SKU - the same shape
#       every existing Product already is.
#   2/3/4 = Day Pass: a *daily* rate, bought for a *customer-chosen*
#       number of days (periodNum) at a tiered discount - confirmed live,
#       see esimaccess_adapter.py's day_pass_total_price(). Product has no
#       "pick a duration at purchase" concept, so a Day Pass is synced as
#       several fixed-looking variants instead - one per entry in
#       DAY_PASS_VARIANT_DAYS below - each a real, correctly-priced SKU
#       for that specific duration, not a guess at "the" Day Pass product.
ESIMACCESS_FIXED_DATA_TYPE = 1
ESIMACCESS_DAY_PASS_DATA_TYPES = (2, 3, 4)

# Durations offered for every synced Day Pass. Matches this project's own
# existing convention for which duration tiers actually get sold (see the
# admin "2 featured products per country, 7 days & 15 days" decision) -
# not an eSIM Access concept, a Triptel merchandising choice, kept small
# deliberately: each entry multiplies every Day Pass package into one more
# Product row (1,316 real Day Pass packages x 2 durations here = ~2,632
# rows), and every additional duration added multiplies that further.
DAY_PASS_VARIANT_DAYS = (7, 15)

_REGION_NAME_SUFFIX_RE = re.compile(r"\s+[\d.]+\s*(GB|MB)(/Day)?(\s+\d+\s*[Dd]ays)?\s*$", re.IGNORECASE)


def _esimaccess_location(p: dict) -> tuple[Optional[str], bool]:
    """Returns (location_key, is_regional).

    location_key is a bare ISO2 for a single-country package ("ES"), or
    eSIM Access's own stable region identifier (`locationCode` - confirmed
    live: 42 distinct values across the whole catalog, every package
    sharing one locationCode shares the exact same country set, e.g.
    "EU-42" for 41 European countries, up to 14 characters) for a
    multi-country/regional/global package. `location` itself (the
    comma-separated country list, "QA,EG,IL,MA,...") is NOT used as the
    key - it can be far longer than any reasonable column width and
    carries no stable short identifier of its own; locationCode already
    is that identifier, confirmed consistent for every package that
    shares it. Returns (None, False) if neither a clean ISO2 nor a
    locationCode is present - genuinely unparseable, not silently
    defaulted to anything.
    """
    location = (p.get("location") or "").strip().upper()
    if location and "," not in location and len(location) == 2:
        return location, False
    location_code = (p.get("locationCode") or "").strip().upper()
    if location_code:
        return location_code, True
    return None, False


def _esimaccess_region_name(p: dict) -> str:
    """eSIM Access sends no region name separate from the package's own
    name ("Europe 3GB 30Days", "Asia (7 areas) 1GB 7Days", "AUKUS(3
    countries) 1GB 30days") - strips the trailing data/duration suffix to
    recover just "Europe" / "Asia (7 areas)" / "AUKUS(3 countries)".
    Verified live against all 42 distinct region shapes seen in a real,
    unfiltered pull, including every "(N areas)"/"(N countries)" and
    "X & Y & Z" multi-word form actually observed - not assumed to
    generalize from one example."""
    name = p.get("name") or p.get("locationCode") or "Region"
    stripped = _REGION_NAME_SUFFIX_RE.sub("", name).strip()
    return stripped or name


def parse_esimaccess_package(p: dict, profit_pct: Decimal = DEFAULT_SELLING_PROFIT_PCT) -> list[dict]:
    """Returns a list of Product-row dicts ready to sync - empty for
    anything genuinely unparseable, one entry for a fixed-data package,
    len(DAY_PASS_VARIANT_DAYS) entries for a Day Pass package (it has no
    single "the" product - see DAY_PASS_VARIANT_DAYS above).

    Each dict's "location_key"/"is_regional"/"region_name" tell the sync
    loop how to resolve (or create) the right Country row - a real ISO2
    country, or a pseudo-Country keyed on eSIM Access's own locationCode
    for a multi-country/regional/global package. Single-country and
    regional packages share this one function because eSIM Access's real
    catalog mixes Day Pass and regional freely (confirmed live: e.g.
    "Europe 500MB/Day" is a Day Pass under the same "EU-42" regional code
    as the fixed-data "Europe 3GB 30Days") - handling them as two
    independent dimensions (location shape x data-plan shape) avoids a
    combinatorial explosion of near-duplicate parsing paths.

    Field names and encoding confirmed live, not assumed from docs - see
    backend/docs/esimaccess_integration_reference.md and the real $0.30
    test purchase (packageCode PFRQ8FIBC) the fixed-data path was
    originally built against.
    """
    if p.get("durationUnit") != "DAY":
        # Confirmed "DAY" on every one of 3,283 packages in a live,
        # unfiltered pull - guard against ever silently misreading
        # validity_days if that ever isn't true, rather than assume it
        # always will be.
        return []

    package_code = p.get("packageCode")
    if not package_code:
        return []

    location_key, is_regional = _esimaccess_location(p)
    if location_key is None:
        return []

    data_type = p.get("dataType")
    # USD x10,000 encoding, confirmed live (balance/query: 500000 ==
    # $50.00; the real $0.30 test purchase: 3000 == $0.30 actually
    # charged). Never 2-decimal cents.
    price_scaled = p.get("price") or 0
    volume_bytes = p.get("volume") or 0
    daily_gb = Decimal(volume_bytes) / Decimal(1024 ** 3)

    # The raw `location` field is the actual comma-separated ISO2 list for
    # a regional package (e.g. "NO,RS,DE") - locationCode/location_key
    # above is just eSIM Access's stable short identifier for the group,
    # not the countries themselves. Normalized (uppercased, no stray
    # whitespace) so the storefront can split on "," and resolve each
    # code to a Country name without re-cleaning it there.
    coverage_country_isos = (
        ",".join(code.strip().upper() for code in (p.get("location") or "").split(",") if code.strip())
        if is_regional else None
    ) or None

    common = {
        "location_key": location_key,
        "is_regional": is_regional,
        "region_name": _esimaccess_region_name(p) if is_regional else None,
        "coverage_country_isos": coverage_country_isos,
        "supplier_package_code": package_code,
        "currency": "USD",  # eSIM Access bills in USD, unlike VivaPe's EUR
        "supplier_reference": "esimaccess",
        "is_unlimited": False,
        # ipExport (the exit-IP distinction - e.g. HK vs SG for China,
        # confirmed to carry a real 15-44% price difference between
        # otherwise-identical packages) lives in the package `name` itself
        # already (e.g. "China 10GB 30Days (nonhkip)"), which becomes
        # title_en verbatim below - so the distinction is preserved
        # without inventing a new column for it, matching the reference
        # doc's warning not to fold it away as a name-string oddity.
        "coverage_networks": p.get("ipExport") or None,
    }

    if data_type == ESIMACCESS_FIXED_DATA_TYPE:
        cost = Decimal(str(price_scaled)) / Decimal(10000)
        return [{
            **common,
            "title": str(p.get("name") or f"{location_key} eSIM"),
            "data_amount_gb": daily_gb.quantize(Decimal("0.01")),
            "validity_days": int(p.get("duration") or 0),
            "cost_price": cost,
            "retail_price": retail_price_for(cost, profit_pct),
            "supplier_period_num": None,
        }]

    if data_type in ESIMACCESS_DAY_PASS_DATA_TYPES:
        # A friendly label for the synthesized title - region_name for a
        # regional package ("Europe"), or the matching entry's own
        # locationName for a single country (locationNetworkList[0] is
        # "Singapore" for a Singapore package, confirmed live - falls back
        # to the bare ISO2 only if that's ever missing, which has not been
        # observed).
        if is_regional:
            label = common["region_name"]
        else:
            networks = p.get("locationNetworkList") or []
            label = (networks[0].get("locationName") if networks else None) or location_key
        variants = []
        for days in DAY_PASS_VARIANT_DAYS:
            # Tiered discount formula, not price_scaled * days - see
            # day_pass_total_price's own docstring for the real worked
            # example (flat multiplication overcharges by a wide margin).
            total_scaled = day_pass_total_price(price_scaled, days)
            cost = scaled_to_decimal(total_scaled)
            total_gb = (daily_gb * days).quantize(Decimal("0.01"))
            # .normalize() strips trailing zeros (3.00 -> 3, 3.50 -> 3.5)
            # so the title reads the way eSIM Access's own fixed-data
            # names already do ("Spain 3GB 30Days", not "Spain
            # 3.00GB 30Days") - Decimal's own :g format spec does NOT do
            # this (verified: f"{Decimal('7.00'):g}" prints "7.00", not
            # "7"), unlike float's.
            gb_display = total_gb.normalize()
            variants.append({
                **common,
                "title": f"{label} {gb_display}GB {days}Days",
                "data_amount_gb": total_gb,
                "validity_days": days,
                "cost_price": cost,
                "retail_price": retail_price_for(cost, profit_pct),
                "supplier_period_num": days,
            })
        return variants

    return []

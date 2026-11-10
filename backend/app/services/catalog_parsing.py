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


# eSIM Access dataType values a single Product row can represent today - see
# backend/docs/esimaccess_integration_reference.md section 6. Only fixed
# data (1) is a stable-price, fixed-validity SKU the way every existing
# Product already is. Day Passes (2/3/4) sell a *daily* rate for a
# *customer-chosen* number of days at a tiered discount - a genuinely
# different product shape Product has no column for (no "pick a duration at
# purchase" concept anywhere in checkout today) and are deliberately not
# synced by this function. Confirmed live (2026-11-10): of 3,283 real
# packages, 1,817 are dataType 1, and of those, 1,583 are single-country
# (the rest are multi-country/regional bundles - see
# _esimaccess_single_country below for why those are excluded too).
ESIMACCESS_SYNCABLE_DATA_TYPE = 1


def _esimaccess_single_country(location: str) -> Optional[str]:
    """Returns the ISO2 if `location` names exactly one country, else None.
    eSIM Access's `location` field is a bare ISO2 for a single-country
    package ("ES") or a comma-separated list for a multi-country/regional
    bundle ("QA,EG,IL,MA,AE,JO,BH,TN,KW,SA,TR,OM", confirmed live). Product
    has one country_id FK - no multi-country representation exists - so a
    bundle has nowhere correct to go yet and is skipped, not forced onto
    one arbitrarily-chosen member country."""
    loc = (location or "").strip().upper()
    if loc and "," not in loc and len(loc) == 2:
        return loc
    return None


def parse_esimaccess_package(p: dict, profit_pct: Decimal = DEFAULT_SELLING_PROFIT_PCT) -> Optional[dict]:
    """Returns None for anything outside today's deliberately narrow sync
    scope (see ESIMACCESS_SYNCABLE_DATA_TYPE's comment: fixed-data,
    single-country only), else a dict of fields ready to build a Product
    row. Field names and encoding confirmed live, not assumed from docs -
    see backend/docs/esimaccess_integration_reference.md and the real
    $0.30 test purchase (packageCode PFRQ8FIBC) this sync path was built
    against."""
    if p.get("dataType") != ESIMACCESS_SYNCABLE_DATA_TYPE:
        return None
    iso2 = _esimaccess_single_country(p.get("location"))
    if iso2 is None:
        return None
    # durationUnit is "DAY" on every single package observed in a live,
    # unfiltered pull (3,283/3,283) - guard against ever silently
    # misreading validity_days if that ever isn't true, rather than assume
    # it always will be.
    if p.get("durationUnit") != "DAY":
        return None

    package_code = p.get("packageCode")
    if not package_code:
        return None

    # USD x10,000 encoding, confirmed live (balance/query: 500000 == $50.00;
    # this real test purchase: 3000 == $0.30 actually charged). Never 2-decimal
    # cents.
    cost = Decimal(str(p.get("price") or 0)) / Decimal(10000)
    retail = retail_price_for(cost, profit_pct)

    volume_bytes = p.get("volume") or 0
    data_amount_gb = (Decimal(volume_bytes) / Decimal(1024 ** 3)).quantize(Decimal("0.01"))
    validity_days = int(p.get("duration") or 0)

    title = str(p.get("name") or f"{iso2} eSIM")

    return {
        "iso2": iso2,
        "supplier_package_code": package_code,
        "title": title,
        "data_amount_gb": data_amount_gb,
        "validity_days": validity_days,
        "cost_price": cost,
        "retail_price": retail,
        "currency": "USD",  # eSIM Access bills in USD, unlike VivaPe's EUR
        "is_unlimited": False,  # dataType 1 is always a fixed total, never unlimited
        "supplier_reference": "esimaccess",
        # ipExport (the exit-IP distinction - e.g. HK vs SG for China,
        # confirmed to carry a real 15-44% price difference between
        # otherwise-identical packages) lives in the package `name` itself
        # already (e.g. "China 10GB 30Days (nonhkip)"), which becomes
        # title_en verbatim above - so the distinction is preserved without
        # inventing a new column for it, matching the reference doc's
        # warning not to fold it away as a name-string oddity.
        "coverage_networks": p.get("ipExport") or None,
    }

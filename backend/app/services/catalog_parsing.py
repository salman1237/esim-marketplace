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

ESIM_REFERENCES = ("esimgo_bundle", "worldmove_esim")

_GB_RE = re.compile(r"(\d+(\.\d+)?)\s*GB", re.IGNORECASE)
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
    days_match = _DAYS_RE.search(title)

    data_amount = Decimal("0") if is_unlimited else (Decimal(gb_match.group(1)) if gb_match else Decimal("3.0"))
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

"""Which upstream suppliers' products are shown to customers.

VivaPe proxies more than one underlying wholesaler through the same catalog
and provisioning API - esimgo_bundle, worldmove_esim, and (as of October
2026) telna_esim. All three can be *parsed* the moment catalog_parsing
recognises them, which is not the same as being fit to sell: a live test
purchase against Telna's real catalog found that two of three sampled
products were rejected outright by VivaPe's own create-transaction endpoint,
with only a product explicitly named "Test" actually completing. Recognising
a supplier's products and offering them to a paying customer are different
decisions, and this is what lets an admin make the second one independently
of the first - turn a supplier on once it is proven to work, or off the
moment it stops being reliable, without touching code.

This is a visibility switch, not a data switch: disabling a supplier never
deletes or deactivates its products (an admin reviewing the catalog, or
investigating a specific product, still sees everything). It only removes
that supplier's products from what a customer or partner can browse or buy.
"""
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSetting
from app.services.catalog_parsing import ESIM_REFERENCES

SUPPLIER_SETTINGS_KEY = "enabled_suppliers"

# Human-readable names for the admin console. Kept here rather than in the
# frontend so a new entry in ESIM_REFERENCES (catalog_parsing.py) fails
# loudly - KeyError, not a silently unlabelled checkbox - until someone
# names it.
SUPPLIER_LABELS = {
    "esimgo_bundle": "eSIM Go",
    "worldmove_esim": "WorldMove",
    "telna_esim": "Telna",
}

# Telna starts OFF, not on. This is not a neutral default: a live test
# purchase on 2026-10-23 found most of its real-looking catalog entries
# fail at VivaPe's own endpoint, and only a product literally named "Test"
# actually provisions. The other two have been selling real orders in
# production since launch. An admin turns Telna on deliberately, once
# VivaPe confirms which of its products are genuinely fulfillable.
DEFAULT_ENABLED_SUPPLIERS = frozenset({"esimgo_bundle", "worldmove_esim"})


def _normalize(raw) -> frozenset[str]:
    """Keeps only values catalog_parsing would actually recognise - a typo,
    a stale supplier removed from ESIM_REFERENCES, or hand-edited JSON in
    the settings table can never silently enable (or permanently hide)
    something the parser doesn't know about either way."""
    if not isinstance(raw, list):
        return DEFAULT_ENABLED_SUPPLIERS
    return frozenset(s for s in raw if s in ESIM_REFERENCES)


async def get_enabled_suppliers(db: AsyncSession) -> frozenset[str]:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == SUPPLIER_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    if setting is None:
        return DEFAULT_ENABLED_SUPPLIERS
    return _normalize(setting.value)


def supplier_visible_filter(column, enabled: Iterable[str]):
    """The SQLAlchemy predicate every customer/partner-facing catalog query
    filters by, in addition to Product.is_active. A NULL supplier_reference
    (not something catalog_sync ever produces, but not impossible on a
    hand-created row) is always visible - this switch controls supplier
    *products*, not anything that isn't attributed to one of them."""
    enabled = tuple(enabled)
    return column.is_(None) | column.in_(enabled)


async def set_enabled_suppliers(db: AsyncSession, suppliers: list[str], admin_id: str) -> dict:
    """Returns the audit-friendly before/after. Caller commits.

    Unknown entries are rejected outright (400 at the API layer) rather than
    silently dropped - if the admin console sent something catalog_parsing
    doesn't recognise, that is a bug worth surfacing immediately, not a
    setting worth half-saving.
    """
    unknown = [s for s in suppliers if s not in ESIM_REFERENCES]
    if unknown:
        raise ValueError(f"Unrecognised supplier(s): {', '.join(unknown)}")

    before = sorted(await get_enabled_suppliers(db))
    after = sorted(set(suppliers))

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == SUPPLIER_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    if setting:
        setting.value = after
        setting.is_public = False
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=SUPPLIER_SETTINGS_KEY, value=after, is_public=False, updated_by_id=admin_id))

    return {"before": before, "after": after}


async def serialize_all(db: AsyncSession) -> list[dict]:
    """Every known supplier with its label and current on/off state, in a
    stable order - what the admin console actually renders as checkboxes."""
    enabled = await get_enabled_suppliers(db)
    return [
        {"reference": ref, "label": SUPPLIER_LABELS.get(ref, ref), "enabled": ref in enabled}
        for ref in ESIM_REFERENCES
    ]

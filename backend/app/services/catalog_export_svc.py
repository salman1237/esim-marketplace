"""Excel export of the product catalog for the admin console.

Two sheets: a Summary (totals, current selling profit %, per-country
overview) and Products (one row per package with cost, price, profit,
supplier mapping and completed-sales figures), formatted to be usable
straight away - frozen header, filters, euro and percent formats."""
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Country, Product
from app.models.order import Order, OrderStatus
from app.services.pricing_svc import get_selling_profit_pct

EUR = '"€"#,##0.00'
PCT = "0.0%"
HEADER_FILL = PatternFill("solid", fgColor="1E293B")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=16, color="0F172A")
LABEL_FONT = Font(bold=True, color="475569")
ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
INACTIVE_FONT = Font(color="94A3B8", italic=True)
THIN = Side(style="thin", color="E2E8F0")

PRODUCT_COLUMNS = [
    # (header, width, number format)
    ("Country", 22, None),
    ("ISO", 7, None),
    ("Region", 14, None),
    ("Product", 42, None),
    ("Bundle type", 13, None),
    ("Data (GB)", 11, "0.##"),
    ("Validity (days)", 14, "0"),
    ("VivaPe cost", 13, EUR),
    ("Selling price", 13, EUR),
    ("Profit", 11, EUR),
    ("Profit %", 10, PCT),
    ("Status", 10, None),
    ("Supplier type", 17, None),
    ("VivaPe product ID", 17, "0"),
    ("Completed orders", 16, "#,##0"),
    ("Revenue (completed)", 19, EUR),
    ("Coverage networks", 40, None),
    ("Last updated (UTC)", 19, "yyyy-mm-dd hh:mm"),
    ("Product ID", 38, None),
]


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _style_header(ws, row: int, columns: int) -> None:
    for col in range(1, columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30


def catalog_filters(q: Optional[str], is_active: Optional[bool], country_iso: Optional[str] = None) -> list:
    filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(Product.title_en.ilike(term) | Country.name_en.ilike(term))
    if country_iso and country_iso.strip():
        filters.append(Country.iso2 == country_iso.strip().upper())
    if is_active is not None:
        filters.append(Product.is_active == is_active)
    return filters


async def build_catalog_workbook(
    db: AsyncSession, q: Optional[str] = None, is_active: Optional[bool] = None, country_iso: Optional[str] = None,
) -> bytes:
    sales = (
        select(
            Order.product_id.label("product_id"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(Order.status == OrderStatus.COMPLETED)
        .group_by(Order.product_id)
        .subquery()
    )
    stmt = (
        select(Product, Country, sales.c.orders, sales.c.revenue)
        .join(Country, Product.country_id == Country.id)
        .outerjoin(sales, sales.c.product_id == Product.id)
        .order_by(Country.name_en.asc(), Product.retail_price.asc(), Product.data_amount_gb.asc())
    )
    filters = catalog_filters(q, is_active, country_iso)
    if filters:
        stmt = stmt.where(*filters)
    rows = (await db.execute(stmt)).all()
    profit_pct = await get_selling_profit_pct(db)
    generated = datetime.now(timezone.utc)

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    products = wb.create_sheet("Products")

    # ---- Products sheet ----
    for col, (header, width, _fmt) in enumerate(PRODUCT_COLUMNS, start=1):
        products.cell(row=1, column=col, value=header)
        products.column_dimensions[get_column_letter(col)].width = width
    _style_header(products, 1, len(PRODUCT_COLUMNS))

    per_country: dict = {}
    active_count = unlimited_count = 0
    prices = []
    for index, (p, c, orders, revenue) in enumerate(rows, start=2):
        cost = Decimal(str(p.cost_price))
        price = Decimal(str(p.retail_price))
        profit = price - cost
        values = [
            c.name_en,
            c.iso2,
            c.region or "",
            p.title_en,
            "Unlimited" if p.is_unlimited else "Fixed data",
            None if p.is_unlimited else float(p.data_amount_gb),
            p.validity_days,
            float(cost),
            float(price),
            float(profit),
            float(profit / cost) if cost else None,
            "Active" if p.is_active else "Inactive",
            p.supplier_reference or "",
            p.supplier_product_id,
            int(orders or 0),
            float(revenue or 0),
            (p.coverage_networks or "")[:32000],
            _naive_utc(p.updated_at),
            p.id,
        ]
        for col, value in enumerate(values, start=1):
            cell = products.cell(row=index, column=col, value=value)
            fmt = PRODUCT_COLUMNS[col - 1][2]
            if fmt:
                cell.number_format = fmt
            cell.border = Border(bottom=THIN)
            if index % 2 == 0:
                cell.fill = ZEBRA_FILL
            if not p.is_active:
                cell.font = INACTIVE_FONT
        if p.is_unlimited:
            products.cell(row=index, column=6, value="Unlimited")

        active_count += 1 if p.is_active else 0
        unlimited_count += 1 if p.is_unlimited else 0
        prices.append(price)
        entry = per_country.setdefault(c.iso2, {"name": c.name_en, "total": 0, "active": 0, "min": None, "max": None, "orders": 0, "revenue": Decimal("0")})
        entry["total"] += 1
        entry["active"] += 1 if p.is_active else 0
        entry["min"] = price if entry["min"] is None else min(entry["min"], price)
        entry["max"] = price if entry["max"] is None else max(entry["max"], price)
        entry["orders"] += int(orders or 0)
        entry["revenue"] += Decimal(str(revenue or 0))

    products.freeze_panes = "E2"
    if rows:
        products.auto_filter.ref = f"A1:{get_column_letter(len(PRODUCT_COLUMNS))}{len(rows) + 1}"

    # ---- Summary sheet ----
    summary.column_dimensions["A"].width = 28
    for letter, width in zip("BCDEFG", (14, 12, 12, 16, 18, 18)):
        summary.column_dimensions[letter].width = width
    summary["A1"] = "Triptel product catalog"
    summary["A1"].font = TITLE_FONT
    filter_text = ", ".join(part for part in (
        f'search "{q.strip()}"' if q and q.strip() else "",
        ("active only" if is_active else "inactive only") if is_active is not None else "",
        f"country {country_iso.upper()}" if country_iso else "",
    ) if part) or "none - full catalog"

    facts = [
        ("Generated (UTC)", _naive_utc(generated), "yyyy-mm-dd hh:mm"),
        ("Filters", filter_text, None),
        ("Selling profit on VivaPe cost", float(profit_pct) / 100, PCT),
        ("Products", len(rows), "#,##0"),
        ("Active", active_count, "#,##0"),
        ("Inactive", len(rows) - active_count, "#,##0"),
        ("Unlimited bundles", unlimited_count, "#,##0"),
        ("Countries", len(per_country), "#,##0"),
        ("Cheapest selling price", float(min(prices)) if prices else None, EUR),
        ("Highest selling price", float(max(prices)) if prices else None, EUR),
        ("Prices in", "EUR", None),
    ]
    for offset, (label, value, fmt) in enumerate(facts, start=3):
        summary.cell(row=offset, column=1, value=label).font = LABEL_FONT
        cell = summary.cell(row=offset, column=2, value=value)
        cell.alignment = Alignment(horizontal="left")
        if fmt:
            cell.number_format = fmt

    table_row = 3 + len(facts) + 2
    summary.cell(row=table_row - 1, column=1, value="By country").font = Font(bold=True, size=12)
    headers = ["Country", "ISO", "Products", "Active", "Cheapest", "Most expensive", "Completed orders"]
    for col, header in enumerate(headers, start=1):
        summary.cell(row=table_row, column=col, value=header)
    _style_header(summary, table_row, len(headers))
    for i, (iso, e) in enumerate(sorted(per_country.items(), key=lambda kv: kv[1]["name"]), start=table_row + 1):
        for col, (value, fmt) in enumerate([
            (e["name"], None), (iso, None), (e["total"], "#,##0"), (e["active"], "#,##0"),
            (float(e["min"]), EUR), (float(e["max"]), EUR), (e["orders"], "#,##0"),
        ], start=1):
            cell = summary.cell(row=i, column=col, value=value)
            if fmt:
                cell.number_format = fmt
            if (i - table_row) % 2 == 0:
                cell.fill = ZEBRA_FILL
    summary.freeze_panes = f"A{table_row + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

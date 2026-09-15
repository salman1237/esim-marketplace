import io
import uuid
import pytest
from decimal import Decimal
from openpyxl import load_workbook

from conftest import register_and_login
from app.models.catalog import Country, Product
from app.models.order import Order, OrderStatus, PaymentMethod

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/catalog/export.xlsx"


async def _seed(db_session, buyer_id):
    tag = uuid.uuid4().hex[:8]
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"X{tag[:5].upper()}", name_en=f"Exportland {tag}", region="Asia", is_active=True)
    db_session.add(country)
    await db_session.flush()
    data = Product(country_id=country.id, title_en=f"Export 5GB {tag}", data_amount_gb=Decimal("5"), validity_days=30,
                   cost_price=Decimal("4.0000"), retail_price=Decimal("5.0000"), currency="EUR", is_active=True,
                   supplier_reference="esimgo_bundle", supplier_product_id=777001)
    unlimited = Product(country_id=country.id, title_en=f"Export Unlimited {tag}", data_amount_gb=Decimal("0"), validity_days=7,
                        cost_price=Decimal("8.0000"), retail_price=Decimal("10.0000"), currency="EUR", is_unlimited=True, is_active=False)
    db_session.add_all([data, unlimited])
    await db_session.flush()
    for _ in range(2):
        db_session.add(Order(order_no=f"ORD-XP-{uuid.uuid4().hex[:10]}", buyer_id=buyer_id, beneficiary_id=buyer_id, product_id=data.id,
                             total_amount=Decimal("5.0000"), cost_amount=Decimal("4.0000"), currency="EUR",
                             payment_method=PaymentMethod.WALLET, status=OrderStatus.COMPLETED))
    await db_session.commit()
    return tag


def _rows(ws):
    header = [c.value for c in ws[1]]
    return header, [dict(zip(header, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]


async def test_catalog_export_is_a_formatted_workbook_with_details(client, db_session, promote_role):
    admin = await register_and_login(client, "catexport")
    await promote_role(admin["user_id"], "ADMIN")
    tag = await _seed(db_session, admin["user_id"])

    res = await client.get(URL, params={"q": tag}, headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert ".xlsx" in res.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["Summary", "Products"]

    ws = wb["Products"]
    header, rows = _rows(ws)
    for column in ("Country", "Product", "Bundle type", "Validity (days)", "VivaPe cost", "Selling price", "Profit", "Profit %", "Status", "Completed orders"):
        assert column in header
    assert len(rows) == 2
    assert ws.freeze_panes == "E2" and ws.auto_filter.ref

    data = next(r for r in rows if r["Bundle type"] == "Fixed data")
    assert data["Selling price"] == 5.0 and data["VivaPe cost"] == 4.0 and data["Profit"] == 1.0
    assert data["Profit %"] == pytest.approx(0.25)
    assert data["Completed orders"] == 2 and data["Revenue (completed)"] == 10.0
    assert data["Status"] == "Active" and data["VivaPe product ID"] == 777001 and data["Region"] == "Asia"
    price_cell = ws.cell(row=rows.index(data) + 2, column=header.index("Selling price") + 1)
    assert "€" in price_cell.number_format

    unlimited = next(r for r in rows if r["Bundle type"] == "Unlimited")
    assert unlimited["Data (GB)"] == "Unlimited" and unlimited["Status"] == "Inactive"

    summary = {row[0].value: row[1].value for row in wb["Summary"].iter_rows(min_row=3, max_row=13)}
    assert summary["Products"] == 2 and summary["Active"] == 1 and summary["Inactive"] == 1
    assert tag in summary["Filters"]


async def test_catalog_export_respects_status_filter_and_requires_admin(client, db_session, promote_role):
    admin = await register_and_login(client, "catexport2")
    await promote_role(admin["user_id"], "ADMIN")
    tag = await _seed(db_session, admin["user_id"])

    active = await client.get(URL, params={"q": tag, "is_active": "true"}, headers=admin["headers"])
    _, rows = _rows(load_workbook(io.BytesIO(active.content))["Products"])
    assert [r["Status"] for r in rows] == ["Active"]

    user = await register_and_login(client, "catexportuser")
    assert (await client.get(URL, headers=user["headers"])).status_code == 403

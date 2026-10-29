"""The three export formats every admin report must produce.

Kept apart from the report tests because these are pure renderers with no
database or event loop involved - under the report module-level asyncio
mark they would each warn about being a sync test.
"""
import io

from openpyxl import load_workbook

from app.services import report_export_svc

# --- the three mandatory export formats ---

COLUMNS = [
    report_export_svc.Column("iccid", "ICCID", 24),
    report_export_svc.Column("customer_email", "Email", 28),
    report_export_svc.Column("supplier_cost_eur", "Cost (EUR)", 12, number_format='"EUR"#,##0.00'),
]
ROWS = [
    {"iccid": "89862103954300006454", "customer_email": "a@example.com", "supplier_cost_eur": "2.52"},
    {"iccid": None, "customer_email": "b@example.com", "supplier_cost_eur": "3.40"},
]


def test_csv_export_is_excel_safe_utf8():
    out = report_export_svc.to_csv(COLUMNS, ROWS)
    assert out.startswith(b"\xef\xbb\xbf"), "no BOM - Excel mangles UTF-8 on double-click"
    text = out.decode("utf-8-sig")
    assert "ICCID" in text and "89862103954300006454" in text


def test_xlsx_export_opens_as_a_real_workbook():
    out = report_export_svc.to_xlsx(COLUMNS, ROWS, title="Unused eSIMs", summary=[("Total:", 2)])
    wb = load_workbook(io.BytesIO(out))
    assert wb.active.max_row >= 3
    assert any("89862103954300006454" in str(c.value) for row in wb.active.iter_rows() for c in row)


def test_pdf_export_is_a_real_pdf():
    out = report_export_svc.to_pdf(COLUMNS, ROWS, title="Unused eSIMs", summary=[("Total:", 2)])
    assert out.startswith(b"%PDF-"), "not a PDF"
    assert len(out) > 800


def test_exports_handle_an_empty_report():
    """A clean month must not produce a corrupt file."""
    assert report_export_svc.to_csv(COLUMNS, []).decode("utf-8-sig").strip() == "ICCID,Email,Cost (EUR)"
    assert report_export_svc.to_xlsx(COLUMNS, [], title="Empty")[:2] == b"PK"
    assert report_export_svc.to_pdf(COLUMNS, [], title="Empty").startswith(b"%PDF-")

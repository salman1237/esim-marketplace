"""CSV, Excel and PDF renderers for admin reports.

One module for all three so a report defines its columns once and gets
every format, instead of three drifting copies of the same table. The
Excel sheet is the one people actually work in (frozen header, filters,
euro formats); the PDF is the one that gets emailed to a supplier, so it
carries the totals and the generated-at stamp on the page itself.
"""
import csv
import io
from typing import Callable, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADER_FILL = PatternFill("solid", fgColor="1E293B")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="0F172A")
ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")


class Column:
    """One column, rendered the same way into every format."""

    def __init__(self, key: str, label: str, width: int = 18, number_format: Optional[str] = None,
                 getter: Optional[Callable[[dict], object]] = None):
        self.key = key
        self.label = label
        self.width = width
        self.number_format = number_format
        self.getter = getter or (lambda row: row.get(key))

    def value(self, row: dict):
        v = self.getter(row)
        return "" if v is None else v


def to_csv(columns: Sequence[Column], rows: Sequence[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.label for c in columns])
    for row in rows:
        writer.writerow([c.value(row) for c in columns])
    # BOM so Excel opens UTF-8 (Bangla names, the euro sign) without
    # mangling it into mojibake on a double-click.
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(columns: Sequence[Column], rows: Sequence[dict], *, title: str,
            summary: Optional[Sequence[tuple[str, object]]] = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Report"

    cursor = 1
    ws.cell(row=cursor, column=1, value=title).font = TITLE_FONT
    cursor += 2
    for label, value in summary or []:
        ws.cell(row=cursor, column=1, value=label).font = Font(bold=True, color="475569")
        ws.cell(row=cursor, column=2, value=value)
        cursor += 1
    if summary:
        cursor += 1

    header_row = cursor
    for i, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=i, value=col.label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = col.width

    for r, row in enumerate(rows, start=header_row + 1):
        for i, col in enumerate(columns, start=1):
            value = col.value(row)
            if col.number_format and value not in ("", None):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass
            cell = ws.cell(row=r, column=i, value=value)
            if col.number_format:
                cell.number_format = col.number_format
            if r % 2 == 0:
                cell.fill = ZEBRA_FILL

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(len(columns))}{header_row + len(rows)}"
    )

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(columns: Sequence[Column], rows: Sequence[dict], *, title: str,
           summary: Optional[Sequence[tuple[str, object]]] = None) -> bytes:
    out = io.BytesIO()
    # Landscape A4: these tables are wide (ICCID plus a transaction id plus
    # contact details), and a portrait page squeezes the ICCID into an
    # unreadable column - which is the one value the supplier reconciles on.
    doc = SimpleDocTemplate(
        out, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("cell")
    cell_style.fontSize = 7
    cell_style.leading = 9
    head_style = cell_style.clone("head")
    head_style.textColor = colors.white
    head_style.fontName = "Helvetica-Bold"

    story = [Paragraph(title, styles["Heading2"])]
    for label, value in summary or []:
        story.append(Paragraph(f"<b>{label}</b> {value}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    if not rows:
        story.append(Paragraph("No records match this report.", styles["Normal"]))
    else:
        data = [[Paragraph(c.label, head_style) for c in columns]]
        for row in rows:
            data.append([Paragraph(str(c.value(row)), cell_style) for c in columns])
        table = Table(data, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(table)

    doc.build(story)
    return out.getvalue()

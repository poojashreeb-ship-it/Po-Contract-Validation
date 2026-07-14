"""Renders a ValidationReportBundle to a human-readable PDF.

This is a presentation-only concern on top of the same data the JSON
response already carries — no new fields, no new judgment calls, just a
table layout for each report's field-by-field ledger so the same result
can be read outside of curl/Postman.
"""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .schemas import ValidationReportBundle

_STATUS_HEX = {
    "PASS": "#2e7d32",
    "PASS_WITH_WARNINGS": "#ef6c00",
    "FAIL": "#c62828",
}
_SEVERITY_HEX = {
    "match": "#2e7d32",
    "minor": "#ef6c00",
    "major": "#c62828",
}

# A4 usable width with 1.5cm margins on both sides: 21cm - 3cm = 18cm.
_MARGIN = 1.5 * cm
_COL_WIDTHS = [2.8 * cm, 3.4 * cm, 3.4 * cm, 1.8 * cm, 6.2 * cm]


def _cell(text: str, style: ParagraphStyle, color_hex: str | None = None) -> Paragraph:
    safe = escape(text)
    if color_hex:
        safe = f'<font color="{color_hex}">{safe}</font>'
    return Paragraph(safe, style)


def write_report_pdf(bundle: ValidationReportBundle, output_path: Path) -> None:
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("cellHeader", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)

    story = [
        Paragraph("HZL PO/Contract Validation Report", styles["Title"]),
        Paragraph(f"Generated at: {escape(bundle.generated_at)}", styles["Normal"]),
        Spacer(1, 12),
    ]

    for report in bundle.reports:
        status_hex = _STATUS_HEX.get(report.overall_status, "#000000")
        story.append(Paragraph(escape(report.validation_type.replace("_", " ")), styles["Heading2"]))
        story.append(
            Paragraph(
                f'Overall status: <font color="{status_hex}"><b>{escape(report.overall_status)}</b></font>',
                styles["Normal"],
            )
        )
        story.append(Paragraph(escape(report.summary), styles["Normal"]))
        story.append(Spacer(1, 6))

        rows = [
            [
                _cell("Field", header_style),
                _cell("Source A", header_style),
                _cell("Source B", header_style),
                _cell("Severity", header_style),
                _cell("Note", header_style),
            ]
        ]
        for d in report.discrepancies:
            severity_hex = _SEVERITY_HEX.get(d.severity, "#000000")
            rows.append(
                [
                    _cell(d.field, cell_style),
                    _cell(d.source_a or "-", cell_style),
                    _cell(d.source_b or "-", cell_style),
                    _cell(d.severity, cell_style, color_hex=severity_hex),
                    _cell(d.note, cell_style),
                ]
            )
        table = Table(rows, colWidths=_COL_WIDTHS, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 16))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
    ).build(story)

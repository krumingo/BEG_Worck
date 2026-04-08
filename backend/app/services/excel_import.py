"""
Service - Excel Import/Export for KSS (Количествено-стойностна сметка).
"""
import io
import uuid
from datetime import datetime, timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill, numbers


def parse_float(val) -> float:
    if val is None:
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


async def import_kss_from_excel(file_bytes: bytes, org_id: str, project_id: str, created_by: str, project_name: str = "") -> dict:
    """Parse Excel file and return KSS lines."""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    lines = []
    warnings = []
    skipped = 0
    line_order = 0

    # Detect header row (look for "описание" or row 1)
    start_row = 2  # default: skip header
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=False):
        for cell in row:
            val = str(cell.value or "").lower()
            if any(k in val for k in ["описание", "смр", "дейност", "наименование", "description"]):
                start_row = cell.row + 1
                break

    for row in ws.iter_rows(min_row=start_row, values_only=True):
        # Skip empty rows
        if not row or all(v is None for v in row):
            skipped += 1
            continue

        # Extract fields by position
        num = row[0] if len(row) > 0 else None
        smr_type = str(row[1]).strip() if len(row) > 1 and row[1] else None
        unit = str(row[2]).strip() if len(row) > 2 and row[2] else "m2"
        qty = parse_float(row[3]) if len(row) > 3 else 0
        mat_price = parse_float(row[4]) if len(row) > 4 else 0
        labor_price = parse_float(row[5]) if len(row) > 5 else 0
        total_price = parse_float(row[6]) if len(row) > 6 else 0

        if not smr_type:
            skipped += 1
            continue

        # Infer prices if total is given but components aren't
        if total_price > 0 and mat_price == 0 and labor_price == 0 and qty > 0:
            per_unit = total_price / qty
            mat_price = round(per_unit * 0.4, 2)
            labor_price = round(per_unit * 0.6, 2)
            warnings.append(f"Ред {line_order + 1} ({smr_type}): цените са разпределени автоматично (40/60)")

        if qty <= 0:
            qty = 1
            warnings.append(f"Ред {line_order + 1} ({smr_type}): количество зададено на 1")

        line = {
            "line_id": str(uuid.uuid4()),
            "smr_type": smr_type,
            "smr_subtype": "",
            "unit": unit,
            "qty": qty,
            "materials": [],
            "material_cost_per_unit": mat_price,
            "labor_price_per_unit": labor_price,
            "logistics_pct": 0,
            "markup_pct": 0,
            "risk_pct": 0,
            "total_cost_per_unit": round(mat_price + labor_price, 2),
            "final_price_per_unit": round(mat_price + labor_price, 2),
            "final_total": round((mat_price + labor_price) * qty, 2),
            "is_active": True,
            "original_qty": qty,
            "original_price": round(mat_price + labor_price, 2),
            "line_order": line_order,
        }
        lines.append(line)
        line_order += 1

    return {
        "lines": lines,
        "lines_count": len(lines),
        "skipped_count": skipped,
        "warnings": warnings,
    }


def export_kss_to_excel(analysis: dict) -> bytes:
    """Generate Excel file from SMRAnalysis."""
    wb = Workbook()
    ws = wb.active
    ws.title = "КСС"

    # Styles
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_w = Font(bold=True, size=11, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    inactive_font = Font(color="999999", strikethrough=True)
    summary_font = Font(bold=True, size=11)
    num_fmt = '#,##0.00'

    # Title
    ws.merge_cells("A1:G1")
    ws["A1"] = analysis.get("name", "КСС")
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Проект: {analysis.get('project_name', '')} | Версия: {analysis.get('version', 1)}"
    ws["A2"].font = Font(size=10, color="666666")

    # Headers (row 4)
    headers = ["№", "Описание СМР", "Ед.", "Кол-во", "Материал/ед.", "Труд/ед.", "Общо"]
    col_widths = [6, 40, 8, 12, 14, 14, 16]
    for col_idx, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.font = header_font_w
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[chr(64 + col_idx)].width = w

    # Data rows
    row_num = 5
    for i, ln in enumerate(analysis.get("lines", [])):
        is_active = ln.get("is_active", True)
        font = inactive_font if not is_active else Font(size=10)

        ws.cell(row=row_num, column=1, value=i + 1).font = font
        ws.cell(row=row_num, column=2, value=ln.get("smr_type", "")).font = font
        ws.cell(row=row_num, column=3, value=ln.get("unit", "")).font = font

        for col, key in [(4, "qty"), (5, "material_cost_per_unit"), (6, "labor_price_per_unit"), (7, "final_total")]:
            cell = ws.cell(row=row_num, column=col, value=ln.get(key, 0))
            cell.font = font
            cell.number_format = num_fmt
            cell.border = thin_border

        for c in range(1, 8):
            ws.cell(row=row_num, column=c).border = thin_border

        row_num += 1

    # Summary row
    row_num += 1
    totals = analysis.get("totals", {})
    ws.cell(row=row_num, column=2, value="ОБЩО").font = summary_font
    ws.cell(row=row_num, column=7, value=totals.get("grand_total", 0)).font = summary_font
    ws.cell(row=row_num, column=7).number_format = num_fmt
    for c in range(1, 8):
        ws.cell(row=row_num, column=c).border = thin_border

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

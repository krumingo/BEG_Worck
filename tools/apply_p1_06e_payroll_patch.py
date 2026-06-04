#!/usr/bin/env python3
"""
P1-0.6E — BEG_Work payroll patch applier.

Applies the missing P1-0.6 payroll fix to backend/app/routes/pay_runs.py:
- Adds _money_float(), _validate_no_overpayment(), _build_report_lines().
- Guards paid_now_amount in create and update/reconfirm paths.
- Freezes report_lines[], selected_report_ids, and report_line_count on v3 payment_slips.
- Preserves day_cells and selected_report_ids in update/reconfirm rebuilt employee_rows.

The script is intentionally narrow and idempotent. It refuses to run if expected anchors
are not found, so it does not silently rewrite unknown code.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path.cwd()
PAY_RUNS = ROOT / "backend" / "app" / "routes" / "pay_runs.py"
TEST_FILE = ROOT / "backend" / "tests" / "test_pay_runs_p1_06e_helpers.py"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        fail(f"anchor not found for {label}")
    if count > 1:
        fail(f"anchor for {label} is not unique ({count} matches)")
    return text.replace(old, new, 1)


def insert_after_once(text: str, anchor: str, insertion: str, label: str) -> str:
    if insertion.strip() in text:
        print(f"SKIP: {label} already present")
        return text
    count = text.count(anchor)
    if count == 0:
        fail(f"anchor not found for {label}")
    if count > 1:
        fail(f"anchor for {label} is not unique ({count} matches)")
    return text.replace(anchor, anchor + insertion, 1)


HELPERS = r'''

# ── Payroll package / payment safety helpers ─────────────────────────

def _money_float(value, default: float = 0.0) -> float:
    """Return a safe money float for optional DB/request values."""
    if value is None:
        return default
    try:
        if isinstance(value, str) and value.strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _employee_name(row: dict) -> str:
    name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
    return name or row.get("employee_name") or row.get("name") or ""


def _validate_no_overpayment(row_or_rows):
    """
    Validate paid_now_amount against the remaining payable amount.

    Business rule:
    paid_now_amount <= earned_amount + bonuses_amount - deductions_amount - previously_paid + 0.01
    If old/stale data already makes remaining_before_payment negative, no positive payment is allowed.
    """
    if isinstance(row_or_rows, list):
        return [_validate_no_overpayment(row) for row in row_or_rows]

    row = row_or_rows or {}
    employee_id = row.get("employee_id", "")
    employee_name = _employee_name(row)

    earned = _money_float(row.get("earned_amount"))
    bonuses = _money_float(row.get("bonuses_amount"))
    deductions = _money_float(row.get("deductions_amount"))
    previously_paid = _money_float(row.get("previously_paid"))
    paid_now = round(_money_float(row.get("paid_now_amount")), 2)

    gross_payable = round(earned + bonuses - deductions, 2)
    remaining_before_payment = round(gross_payable - previously_paid, 2)

    def _raise(reason: str) -> None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Overpayment is not allowed. "
                f"employee_id={employee_id}; "
                f"employee_name={employee_name}; "
                f"paid_now_amount={paid_now:.2f}; "
                f"remaining_before_payment={remaining_before_payment:.2f}; "
                f"reason={reason}"
            ),
        )

    if paid_now < 0:
        _raise("paid_now_amount cannot be negative")

    if remaining_before_payment < -0.01 and paid_now > 0:
        _raise("remaining_before_payment is already negative from existing data")

    if paid_now - remaining_before_payment > 0.01:
        _raise("paid_now_amount exceeds remaining_before_payment")

    return {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "gross_payable": gross_payable,
        "remaining_before_payment": remaining_before_payment,
        "paid_now_amount": paid_now,
    }


def _build_report_lines(employee_row: dict) -> list:
    """Freeze concrete report atoms from employee_row.day_cells into slip.report_lines[]."""
    if not employee_row:
        return []

    lines = []
    seen = set()
    day_cells = employee_row.get("day_cells") or []
    if not isinstance(day_cells, list):
        return []

    for day_index, cell in enumerate(day_cells):
        if not isinstance(cell, dict):
            continue
        cell_date = cell.get("date") or cell.get("day") or ""

        reports = cell.get("reports") or []
        if isinstance(reports, list):
            for report in reports:
                if not isinstance(report, dict):
                    continue
                report_id = report.get("report_id") or report.get("id")
                if not report_id or report_id in seen:
                    continue
                seen.add(report_id)
                value = _money_float(report.get("value"), None)
                amount = _money_float(report.get("amount"), value if value is not None else 0.0)
                line = {
                    "report_id": report_id,
                    "date": report.get("date") or cell_date,
                    "project_id": report.get("project_id", ""),
                    "project_name": report.get("project_name", ""),
                    "hours": round(_money_float(report.get("hours")), 2),
                    "value": round(value if value is not None else amount, 2),
                    "amount": round(amount, 2),
                    "report_status": report.get("report_status") or report.get("status") or "",
                    "payroll_status": report.get("payroll_status") or "none",
                    "payroll_source": report.get("payroll_source") or "",
                    "payroll_batch_id": report.get("payroll_batch_id") or "",
                    "source": "day_cells.reports",
                    "day_cell_index": day_index,
                }
                lines.append(line)

        report_ids = cell.get("report_ids") or []
        if isinstance(report_ids, list):
            for report_id in report_ids:
                if not report_id or report_id in seen:
                    continue
                seen.add(report_id)
                lines.append({
                    "report_id": report_id,
                    "date": cell_date,
                    "project_id": "",
                    "project_name": "",
                    "hours": 0,
                    "value": 0,
                    "amount": 0,
                    "report_status": "",
                    "payroll_status": "",
                    "payroll_source": "",
                    "payroll_batch_id": "",
                    "source": "day_cells.report_ids",
                    "day_cell_index": day_index,
                })

    return lines
'''


TEST_CONTENT = r'''import pytest
from fastapi import HTTPException

from app.routes.pay_runs import _build_report_lines, _validate_no_overpayment


def _row(**overrides):
    base = {
        "employee_id": "emp-1",
        "first_name": "Ivan",
        "last_name": "Petrov",
        "earned_amount": 100.0,
        "bonuses_amount": 10.0,
        "deductions_amount": 5.0,
        "previously_paid": 20.0,
        "paid_now_amount": 85.0,
    }
    base.update(overrides)
    return base


def test_overpayment_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(_row(paid_now_amount=85.02))
    assert exc.value.status_code == 400
    assert "Overpayment is not allowed" in str(exc.value.detail)
    assert "employee_id=emp-1" in str(exc.value.detail)
    assert "remaining_before_payment=85.00" in str(exc.value.detail)


def test_exact_remaining_accepted():
    result = _validate_no_overpayment(_row(paid_now_amount=85.0))
    assert result["remaining_before_payment"] == 85.0
    assert result["paid_now_amount"] == 85.0


def test_zero_payment_accepted():
    result = _validate_no_overpayment(_row(paid_now_amount=0))
    assert result["paid_now_amount"] == 0


def test_negative_payment_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(_row(paid_now_amount=-0.01))
    assert exc.value.status_code == 400
    assert "cannot be negative" in str(exc.value.detail)


def test_stale_negative_remaining_blocks_positive_payment():
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(_row(earned_amount=100, bonuses_amount=0, deductions_amount=0, previously_paid=120, paid_now_amount=1))
    assert exc.value.status_code == 400
    assert "already negative" in str(exc.value.detail)


def test_rounding_tolerance_one_cent_accepted():
    result = _validate_no_overpayment(_row(paid_now_amount=85.01))
    assert result["paid_now_amount"] == 85.01
    with pytest.raises(HTTPException):
        _validate_no_overpayment(_row(paid_now_amount=85.02))


def test_build_report_lines_from_day_cells_reports_and_fallback_dedupes():
    employee_row = {
        "day_cells": [
            {
                "date": "2026-06-01",
                "report_ids": ["r1", "r2"],
                "reports": [
                    {
                        "report_id": "r1",
                        "project_id": "p1",
                        "project_name": "Site A",
                        "hours": 8,
                        "value": 80,
                        "report_status": "APPROVED",
                        "payroll_status": "none",
                        "payroll_source": "",
                        "payroll_batch_id": "",
                    }
                ],
            }
        ]
    }
    lines = _build_report_lines(employee_row)
    assert len(lines) == 2
    assert lines[0]["report_id"] == "r1"
    assert lines[0]["source"] == "day_cells.reports"
    assert lines[0]["project_id"] == "p1"
    assert lines[0]["hours"] == 8
    assert lines[0]["value"] == 80
    assert lines[1]["report_id"] == "r2"
    assert lines[1]["source"] == "day_cells.report_ids"


def test_build_report_lines_empty_fallback_does_not_crash():
    assert _build_report_lines({}) == []
    assert _build_report_lines({"day_cells": []}) == []
    assert _build_report_lines({"day_cells": [{"date": "2026-06-01"}]}) == []
'''


def apply() -> None:
    if not PAY_RUNS.exists():
        fail(f"missing {PAY_RUNS}")
    text = PAY_RUNS.read_text(encoding="utf-8")

    # Remove previous failed partial additions if any are not expected? We keep idempotency simple.
    text = insert_after_once(
        text,
        'router = APIRouter(tags=["Pay Runs"])\n',
        HELPERS,
        "helper insertion",
    )

    # CREATE path: paid_now + remaining block.
    old = '''        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        notes = ovr.notes if ovr else ""

        remaining = round(
            row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2
        )
'''
    new = '''        paid_now = round(_money_float(ovr.paid_now_amount if ovr else row["remaining_after_payment"]), 2)
        notes = ovr.notes if ovr else ""

        _validate_no_overpayment({
            "employee_id": eid,
            "first_name": row.get("first_name", ""),
            "last_name": row.get("last_name", ""),
            "earned_amount": row.get("earned_amount", 0),
            "bonuses_amount": total_bonuses,
            "deductions_amount": total_deductions,
            "previously_paid": row.get("previously_paid", 0),
            "paid_now_amount": paid_now,
        })

        remaining = round(
            row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2
        )
'''
    if old in text:
        text = replace_once(text, old, new, "create overpayment guard")
    elif '_validate_no_overpayment({\n            "employee_id": eid,' in text:
        print("SKIP: create overpayment guard already present")
    else:
        fail("create overpayment guard target not found")

    # CREATE slip report_lines fields.
    old = '''        # Generate payment slip
        slip_counter += 1
        slip = {
'''
    new = '''        # Generate payment slip
        report_lines = _build_report_lines(frozen_row)
        slip_counter += 1
        slip = {
'''
    if old in text:
        text = replace_once(text, old, new, "create slip report_lines variable")
    elif 'report_lines = _build_report_lines(frozen_row)\n        slip_counter += 1\n        slip = {' in text:
        print("SKIP: create slip report_lines variable already present")
    else:
        fail("create slip report_lines variable target not found")

    old = '''            "sites": row.get("sites", []),
            "status": "confirmed",
'''
    new = '''            "sites": row.get("sites", []),
            "selected_report_ids": frozen_row.get("selected_report_ids", []),
            "report_lines": report_lines,
            "report_line_count": len(report_lines),
            "status": "confirmed",
'''
    if old in text:
        text = replace_once(text, old, new, "create slip report_lines fields")
    elif '"report_lines": report_lines' in text:
        print("SKIP: create slip report_lines fields already present")
    else:
        fail("create slip report_lines fields target not found")

    # UPDATE path: add existing row map.
    old = '''    preview = await generate_pay_run(user, period_start=data.period_start, period_end=data.period_end)
    override_map = {r.employee_id: r for r in data.rows}

    employee_rows = []
'''
    new = '''    preview = await generate_pay_run(user, period_start=data.period_start, period_end=data.period_end)
    override_map = {r.employee_id: r for r in data.rows}
    existing_row_map = {er.get("employee_id"): er for er in run.get("employee_rows", [])}

    employee_rows = []
'''
    if old in text:
        text = replace_once(text, old, new, "update existing_row_map")
    elif 'existing_row_map = {er.get("employee_id"): er for er in run.get("employee_rows", [])}' in text:
        print("SKIP: update existing_row_map already present")
    else:
        fail("update existing_row_map target not found")

    # UPDATE loop block rewrite from paid_now through employee_rows.append({...}).
    old = '''        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        remaining = round(row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2)

        employee_rows.append({
            "employee_id": eid, "row_status": "included",
            "first_name": row["first_name"], "last_name": row["last_name"],
            "position": row.get("position", ""), "pay_type": row.get("pay_type", ""),
            "payment_schedule": row.get("payment_schedule", ""),
            "rate_type": row.get("rate_type", ""),
            "frozen_hourly_rate": row["hourly_rate"],
            "frozen_daily_rate": row.get("daily_rate", 0),
            "approved_days": row["approved_days"], "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0), "overtime_hours": row.get("overtime_hours", 0),
            "earned_amount": row["earned_amount"],
            "adjustments": adj_list,
            "bonuses_amount": round(total_bonuses, 2),
            "deductions_amount": round(total_deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []), "notes": ovr.notes if ovr else "",
        })
'''
    new = '''        paid_now = round(_money_float(ovr.paid_now_amount if ovr else row["remaining_after_payment"]), 2)
        remaining = round(row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2)
        existing_row = existing_row_map.get(eid, {}) or {}
        selected_report_ids = (
            list(ovr.selected_report_ids) if (ovr and ovr.selected_report_ids)
            else list(row.get("selected_report_ids") or existing_row.get("selected_report_ids") or [])
        )
        day_cells = row.get("day_cells") or existing_row.get("day_cells") or []

        frozen_row = {
            "employee_id": eid, "row_status": "included",
            "first_name": row["first_name"], "last_name": row["last_name"],
            "position": row.get("position", ""), "pay_type": row.get("pay_type", ""),
            "payment_schedule": row.get("payment_schedule", ""),
            "rate_type": row.get("rate_type", ""),
            "frozen_hourly_rate": row["hourly_rate"],
            "frozen_daily_rate": row.get("daily_rate", 0),
            "approved_days": row["approved_days"], "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0), "overtime_hours": row.get("overtime_hours", 0),
            "earned_amount": row["earned_amount"],
            "adjustments": adj_list,
            "bonuses_amount": round(total_bonuses, 2),
            "deductions_amount": round(total_deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []), "notes": ovr.notes if ovr else "",
            "day_cells": day_cells,
            "selected_report_ids": selected_report_ids,
        }
        _validate_no_overpayment(frozen_row)
        employee_rows.append(frozen_row)
'''
    if old in text:
        text = replace_once(text, old, new, "update row rebuild metadata and guard")
    elif 'selected_report_ids = (\n            list(ovr.selected_report_ids)' in text and '_validate_no_overpayment(frozen_row)' in text:
        print("SKIP: update row rebuild metadata and guard already present")
    else:
        fail("update row rebuild metadata and guard target not found")

    # UPDATE replacement slips: add report_lines variable.
    old = '''        for er in employee_rows:
            slip_counter += 1
            slips.append({
'''
    new = '''        for er in employee_rows:
            report_lines = _build_report_lines(er)
            slip_counter += 1
            slips.append({
'''
    if old in text:
        text = replace_once(text, old, new, "replacement slip report_lines variable")
    elif 'for er in employee_rows:\n            report_lines = _build_report_lines(er)' in text:
        print("SKIP: replacement slip report_lines variable already present")
    else:
        fail("replacement slip report_lines variable target not found")

    old = '''                "sites": er.get("sites", []),
                "status": "confirmed", "paid_at": None, "created_at": now,
'''
    new = '''                "sites": er.get("sites", []),
                "selected_report_ids": er.get("selected_report_ids", []),
                "report_lines": report_lines,
                "report_line_count": len(report_lines),
                "status": "confirmed", "paid_at": None, "created_at": now,
'''
    if old in text:
        text = replace_once(text, old, new, "replacement slip report_lines fields")
    elif '"selected_report_ids": er.get("selected_report_ids", [])' in text and '"report_line_count": len(report_lines)' in text:
        print("SKIP: replacement slip report_lines fields already present")
    else:
        fail("replacement slip report_lines fields target not found")

    PAY_RUNS.write_text(text, encoding="utf-8")
    TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEST_FILE.write_text(TEST_CONTENT, encoding="utf-8")
    print("OK: P1-0.6E payroll patch applied")
    print(f"UPDATED: {PAY_RUNS}")
    print(f"WROTE:   {TEST_FILE}")


if __name__ == "__main__":
    apply()

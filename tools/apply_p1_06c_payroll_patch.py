#!/usr/bin/env python3
"""
P1-0.6C payroll patch applicator for BEG_Work.

Run from the repository root:
    python tools/apply_p1_06c_payroll_patch.py

This script edits backend/app/routes/pay_runs.py only. It adds:
- _money_float()
- _validate_no_overpayment()
- _build_report_lines()
- overpayment guard in create/update/reconfirm pay-run paths
- report_lines[], selected_report_ids, report_line_count in new v3 payment_slips
- day_cells + selected_report_ids preservation in update/reconfirm rebuilt employee_rows

It is intentionally conservative and uses exact text anchors from krumingo/BEG_Worck main.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
PAY_RUNS = ROOT / "backend" / "app" / "routes" / "pay_runs.py"
TESTS_DIR = ROOT / "backend" / "tests"
TEST_FILE = TESTS_DIR / "test_pay_runs_p1_06c_helpers.py"


HELPERS = r'''
# ── P1-0.6C Payroll safety helpers ─────────────────────────────────

MONEY_TOLERANCE_EUR = 0.01


def _money_float(value, default: float = 0.0) -> float:
    """Convert money-like values safely and round to 2 decimals."""
    if value is None:
        return round(float(default), 2)
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
            if value == "":
                return round(float(default), 2)
        return round(float(value), 2)
    except (TypeError, ValueError):
        return round(float(default), 2)


def _validate_no_overpayment(values: dict) -> dict:
    """
    Guard against creating/freezing payroll rows and slips that overpay an employee.

    Rule:
      paid_now_amount >= 0
      paid_now_amount <= earned + bonuses - deductions - previously_paid + 0.01
      if remaining_before_payment is already negative from old/stale data, only 0 is allowed
    """
    employee_id = values.get("employee_id", "")
    employee_name = values.get("employee_name") or " ".join(
        str(values.get(k, "") or "").strip() for k in ("first_name", "last_name")
    ).strip()

    earned_amount = _money_float(values.get("earned_amount", 0))
    bonuses_amount = _money_float(values.get("bonuses_amount", 0))
    deductions_amount = _money_float(values.get("deductions_amount", 0))
    previously_paid = _money_float(values.get("previously_paid", 0))
    paid_now_amount = _money_float(values.get("paid_now_amount", 0))

    gross_payable = round(earned_amount + bonuses_amount - deductions_amount, 2)
    remaining_before_payment = round(gross_payable - previously_paid, 2)

    def _raise(reason: str) -> None:
        label = f"employee_id={employee_id}"
        if employee_name:
            label += f" employee_name={employee_name}"
        raise HTTPException(
            status_code=400,
            detail=(
                "Overpayment is not allowed: "
                f"{label}; paid_now_amount={paid_now_amount:.2f}; "
                f"remaining_before_payment={remaining_before_payment:.2f}; {reason}"
            ),
        )

    if paid_now_amount < 0:
        _raise("paid_now_amount must be >= 0")

    if remaining_before_payment < 0:
        if paid_now_amount > 0:
            _raise("remaining_before_payment is already negative, so no positive payment is allowed")
    elif paid_now_amount > round(remaining_before_payment + MONEY_TOLERANCE_EUR, 2):
        _raise("paid_now_amount exceeds remaining_before_payment")

    return {
        "gross_payable": gross_payable,
        "remaining_before_payment": remaining_before_payment,
        "paid_now_amount": paid_now_amount,
    }


def _build_report_lines(employee_row: dict) -> list:
    """
    Freeze concrete report atoms from employee_row.day_cells into a slip-local package.

    Source priority:
    - day_cells[].reports[] full detail
    - day_cells[].report_ids fallback when full reports[] is absent
    """
    report_lines = []
    seen_report_ids = set()

    for day_index, cell in enumerate(employee_row.get("day_cells") or []):
        if not isinstance(cell, dict):
            continue
        cell_date = cell.get("date")

        for report_index, report in enumerate(cell.get("reports") or []):
            if not isinstance(report, dict):
                continue
            report_id = report.get("report_id") or report.get("id") or ""
            if report_id:
                if report_id in seen_report_ids:
                    continue
                seen_report_ids.add(report_id)
            else:
                # No report_id means we still preserve the row, but cannot report-id de-dupe it.
                report_id = ""

            value = _money_float(report.get("value", report.get("amount", 0)))
            amount = _money_float(report.get("amount", report.get("value", value)))
            report_lines.append({
                "report_id": report_id,
                "date": report.get("date") or cell_date,
                "project_id": report.get("project_id", ""),
                "project_name": report.get("project_name", ""),
                "hours": _money_float(report.get("hours", 0)),
                "value": value,
                "amount": amount,
                "report_status": report.get("report_status") or report.get("status") or "",
                "payroll_status": report.get("payroll_status") or cell.get("payroll_status") or "none",
                "payroll_source": report.get("payroll_source") or employee_row.get("payroll_source") or "",
                "payroll_batch_id": report.get("payroll_batch_id") or "",
                "source": "day_cells.reports",
                "day_index": day_index,
                "report_index": report_index,
                "cell_date": cell_date,
            })

        for report_id in cell.get("report_ids") or []:
            if not report_id or report_id in seen_report_ids:
                continue
            seen_report_ids.add(report_id)
            report_lines.append({
                "report_id": report_id,
                "date": cell_date,
                "project_id": "",
                "project_name": "",
                "hours": 0,
                "value": 0,
                "amount": 0,
                "report_status": cell.get("report_status", ""),
                "payroll_status": cell.get("payroll_status") or "none",
                "payroll_source": employee_row.get("payroll_source") or "",
                "payroll_batch_id": "",
                "source": "day_cells.report_ids",
                "day_index": day_index,
                "cell_date": cell_date,
            })

    return report_lines
'''


TESTS = r'''import pytest
from fastapi import HTTPException

from app.routes.pay_runs import _build_report_lines, _validate_no_overpayment


def _row(**overrides):
    base = {
        "employee_id": "emp-1",
        "employee_name": "Test Employee",
        "earned_amount": 100.0,
        "bonuses_amount": 10.0,
        "deductions_amount": 5.0,
        "previously_paid": 20.0,
        "paid_now_amount": 0.0,
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


def test_zero_payment_accepted():
    result = _validate_no_overpayment(_row(paid_now_amount=0))
    assert result["paid_now_amount"] == 0


def test_negative_payment_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(_row(paid_now_amount=-0.01))
    assert exc.value.status_code == 400
    assert "must be >= 0" in str(exc.value.detail)


def test_stale_negative_remaining_blocks_positive_payment():
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(_row(earned_amount=50, bonuses_amount=0, deductions_amount=0, previously_paid=60, paid_now_amount=1))
    assert exc.value.status_code == 400
    assert "already negative" in str(exc.value.detail)


def test_rounding_tolerance_accepts_one_cent_only():
    _validate_no_overpayment(_row(paid_now_amount=85.01))
    with pytest.raises(HTTPException):
        _validate_no_overpayment(_row(paid_now_amount=85.02))


def test_build_report_lines_from_day_cells_reports_and_report_ids_fallback():
    employee_row = {
        "day_cells": [
            {
                "date": "2026-06-01",
                "report_ids": ["r1", "r2"],
                "reports": [
                    {
                        "report_id": "r1",
                        "project_id": "p1",
                        "project_name": "Project 1",
                        "hours": 7.5,
                        "value": 113.64,
                        "report_status": "APPROVED",
                        "payroll_status": "none",
                        "payroll_batch_id": None,
                    }
                ],
            }
        ]
    }
    lines = _build_report_lines(employee_row)
    assert len(lines) == 2
    assert lines[0]["report_id"] == "r1"
    assert lines[0]["project_id"] == "p1"
    assert lines[0]["value"] == 113.64
    assert lines[0]["source"] == "day_cells.reports"
    assert lines[1]["report_id"] == "r2"
    assert lines[1]["source"] == "day_cells.report_ids"


def test_build_report_lines_empty_fallback_does_not_crash():
    assert _build_report_lines({}) == []
    assert _build_report_lines({"day_cells": []}) == []
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match for {label}, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if not PAY_RUNS.exists():
        print(f"ERROR: {PAY_RUNS} not found. Run this script from BEG_Worck repo root.", file=sys.stderr)
        return 2

    original = PAY_RUNS.read_text(encoding="utf-8")
    text = original

    if "def _validate_no_overpayment" not in text:
        text = replace_once(
            text,
            'router = APIRouter(tags=["Pay Runs"])\n\n',
            'router = APIRouter(tags=["Pay Runs"])\n\n' + HELPERS + '\n',
            "helper insertion anchor",
        )

    # CREATE path: add selected_report_ids variable + guard.
    create_old = '''        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        notes = ovr.notes if ovr else ""

        remaining = round(
            row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2
        )
'''
    create_new = '''        paid_now = _money_float(ovr.paid_now_amount if ovr else row["remaining_after_payment"])
        notes = ovr.notes if ovr else ""
        selected_report_ids = list(ovr.selected_report_ids) if (ovr and ovr.selected_report_ids) else []

        _validate_no_overpayment({
            "employee_id": eid,
            "employee_name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            "earned_amount": row["earned_amount"],
            "bonuses_amount": total_bonuses,
            "deductions_amount": total_deductions,
            "previously_paid": row["previously_paid"],
            "paid_now_amount": paid_now,
        })

        remaining = round(
            row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2
        )
'''
    if create_old in text:
        text = text.replace(create_old, create_new, 1)

    create_selected_old = '''            # P0-2A.2: explicit per-report selection. Empty means "use day-level fallback" (old behavior).
            "selected_report_ids": list(ovr.selected_report_ids) if (ovr and ovr.selected_report_ids) else [],
'''
    create_selected_new = '''            # P0-2A.2: explicit per-report selection. Empty means "use day-level fallback" (old behavior).
            "selected_report_ids": selected_report_ids,
'''
    if create_selected_old in text:
        text = text.replace(create_selected_old, create_selected_new, 1)

    create_slip_anchor = '''        # Generate payment slip
        slip_counter += 1
        slip = {
'''
    create_slip_new = '''        # Generate payment slip
        slip_counter += 1
        report_lines = _build_report_lines(frozen_row)
        slip = {
'''
    if create_slip_anchor in text:
        text = text.replace(create_slip_anchor, create_slip_new, 1)

    create_slip_fields_old = '''            "sites": row.get("sites", []),
            "status": "confirmed",
'''
    create_slip_fields_new = '''            "sites": row.get("sites", []),
            "selected_report_ids": selected_report_ids,
            "report_lines": report_lines,
            "report_line_count": len(report_lines),
            "status": "confirmed",
'''
    # only first occurrence in create slip; replacement slips use er version below.
    if create_slip_fields_old in text:
        text = text.replace(create_slip_fields_old, create_slip_fields_new, 1)

    # UPDATE path: insert existing row lookup before loop.
    update_loop_old = '''    for row in preview["rows"]:
        eid = row["employee_id"]
        ovr = override_map.get(eid)
'''
    update_loop_new = '''    existing_employee_rows_by_id = {er.get("employee_id"): er for er in run.get("employee_rows", [])}

    for row in preview["rows"]:
        eid = row["employee_id"]
        ovr = override_map.get(eid)
        existing_row = existing_employee_rows_by_id.get(eid, {})
'''
    # replace only the second occurrence (update path), not create path. We do a manual occurrence split.
    idx = text.find(update_loop_old)
    if idx == -1:
        raise RuntimeError("Could not find update/create loop anchor")
    idx2 = text.find(update_loop_old, idx + len(update_loop_old))
    if idx2 == -1:
        raise RuntimeError("Could not find second loop anchor for update path")
    text = text[:idx2] + update_loop_new + text[idx2 + len(update_loop_old):]

    update_paid_old = '''        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        remaining = round(row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2)

        employee_rows.append({
'''
    update_paid_new = '''        paid_now = _money_float(ovr.paid_now_amount if ovr else row["remaining_after_payment"])
        selected_report_ids = (
            list(ovr.selected_report_ids) if (ovr and ovr.selected_report_ids)
            else list(existing_row.get("selected_report_ids") or row.get("selected_report_ids") or [])
        )
        day_cells = row.get("day_cells") or existing_row.get("day_cells", [])

        _validate_no_overpayment({
            "employee_id": eid,
            "employee_name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            "earned_amount": row["earned_amount"],
            "bonuses_amount": total_bonuses,
            "deductions_amount": total_deductions,
            "previously_paid": row["previously_paid"],
            "paid_now_amount": paid_now,
        })

        remaining = round(row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2)

        employee_rows.append({
'''
    if update_paid_old in text:
        text = text.replace(update_paid_old, update_paid_new, 1)

    update_row_tail_old = '''            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []), "notes": ovr.notes if ovr else "",
        })
'''
    update_row_tail_new = '''            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []),
            "day_cells": day_cells,
            "selected_report_ids": selected_report_ids,
            "notes": ovr.notes if ovr else "",
        })
'''
    if update_row_tail_old in text:
        text = text.replace(update_row_tail_old, update_row_tail_new, 1)

    # Replacement slips after update/reconfirm.
    replacement_slip_old = '''        for er in employee_rows:
            slip_counter += 1
            slips.append({
'''
    replacement_slip_new = '''        for er in employee_rows:
            slip_counter += 1
            report_lines = _build_report_lines(er)
            slips.append({
'''
    if replacement_slip_old in text:
        text = text.replace(replacement_slip_old, replacement_slip_new, 1)

    replacement_slip_fields_old = '''                "remaining_after_payment": er["remaining_after_payment"],
                "sites": er.get("sites", []),
                "status": "confirmed", "paid_at": None, "created_at": now,
'''
    replacement_slip_fields_new = '''                "remaining_after_payment": er["remaining_after_payment"],
                "sites": er.get("sites", []),
                "selected_report_ids": er.get("selected_report_ids", []),
                "report_lines": report_lines,
                "report_line_count": len(report_lines),
                "status": "confirmed", "paid_at": None, "created_at": now,
'''
    if replacement_slip_fields_old in text:
        text = text.replace(replacement_slip_fields_old, replacement_slip_fields_new, 1)

    if text == original:
        print("ERROR: No changes were made. The file may already be patched or has unexpected structure.", file=sys.stderr)
        return 3

    required_markers = [
        "def _build_report_lines",
        "def _validate_no_overpayment",
        '"report_lines": report_lines',
        '"selected_report_ids": selected_report_ids',
        "remaining_before_payment",
    ]
    missing = [m for m in required_markers if m not in text]
    if missing:
        print(f"ERROR: patched text is missing required markers: {missing}", file=sys.stderr)
        return 4

    backup = PAY_RUNS.with_suffix(PAY_RUNS.suffix + ".p1_06c_before")
    if not backup.exists():
        shutil.copy2(PAY_RUNS, backup)
    PAY_RUNS.write_text(text, encoding="utf-8")

    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_FILE.write_text(TESTS, encoding="utf-8")

    print("P1-0.6C patch applied.")
    print(f"Modified: {PAY_RUNS}")
    print(f"Backup:   {backup}")
    print(f"Test:     {TEST_FILE}")
    print("Next commands:")
    print("  python -m py_compile backend/app/routes/pay_runs.py")
    print("  PYTHONPATH=backend pytest backend/tests/test_pay_runs_p1_06c_helpers.py -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

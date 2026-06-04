import pytest
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

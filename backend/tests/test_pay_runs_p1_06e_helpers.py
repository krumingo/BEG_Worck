import pytest
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

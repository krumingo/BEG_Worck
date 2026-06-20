"""v3 payment_slips → legacy v1 "payslips" shape.

Lets the remaining admin-HR and cashflow readers consume v3 directly, so the
v1 `payslips` mirror can be retired. Field/status mapping mirrors exactly what
payroll_sync used to write into payslips:
    gross_pay/base_amount = earned_amount
    net_pay               = paid_now_amount
    net_period            = earned + bonuses - deductions  (expected net)
    status: confirmed→Generated, paid→Paid, reopened→Reversed
"""
from app.db import db

_STATUS_V3_TO_V1 = {"confirmed": "Generated", "paid": "Paid", "reopened": "Reversed"}
_STATUS_V1_TO_V3 = {
    "Generated": "confirmed", "Paid": "paid", "Reversed": "reopened",
    "Approved": "confirmed", "Draft": "confirmed",
}


def _to_v1(s: dict) -> dict:
    earned = round(float(s.get("earned_amount") or 0), 2)
    deductions = round(float(s.get("deductions_amount") or 0), 2)
    bonuses = round(float(s.get("bonuses_amount") or 0), 2)
    run_id = s.get("pay_run_id", "")
    return {
        "id": s.get("id"),
        "org_id": s.get("org_id"),
        "source_pay_run_id": run_id,
        "payroll_run_id": f"sync_{run_id}" if run_id else "",
        "user_id": s.get("employee_id"),
        "employee_id": s.get("employee_id"),
        "employee_name": f"{s.get('first_name', '')} {s.get('last_name', '')}".strip(),
        "period_start": s.get("period_start", ""),
        "period_end": s.get("period_end", ""),
        "gross_pay": earned,
        "base_amount": earned,
        "deductions": deductions,
        "bonuses": bonuses,
        "net_pay": round(float(s.get("paid_now_amount") or 0), 2),
        "net_period": round(earned + bonuses - deductions, 2),
        "status": _STATUS_V3_TO_V1.get(s.get("status", ""), s.get("status", "")),
        "week_number": s.get("week_number"),
        "created_at": s.get("created_at"),
        "paid_at": s.get("paid_at"),
        "slip_number": s.get("slip_number"),
        "pay_type": s.get("pay_type", ""),
        "approved_days": s.get("approved_days"),
        "approved_hours": s.get("approved_hours"),
        "overtime_hours": s.get("overtime_hours", 0),
        "frozen_hourly_rate": s.get("frozen_hourly_rate"),
    }


async def legacy_payslips(org_id, *, employee_id=None, pay_run_id=None,
                          v1_statuses=None, limit=500):
    """Return v3 payment_slips reshaped to the legacy v1 'payslips' shape."""
    q = {"org_id": org_id, "archived": {"$ne": True}}
    if employee_id:
        q["employee_id"] = employee_id
    if pay_run_id:
        pid = str(pay_run_id)
        q["pay_run_id"] = pid[5:] if pid.startswith("sync_") else pid
    if v1_statuses:
        v3 = list({_STATUS_V1_TO_V3.get(s, s) for s in v1_statuses})
        q["status"] = {"$in": v3}
    slips = await db.payment_slips.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return [_to_v1(s) for s in slips]


async def legacy_payslip_one(org_id, payslip_id):
    """Single v3 payment_slip reshaped to v1 shape (or None)."""
    s = await db.payment_slips.find_one({"id": payslip_id, "org_id": org_id}, {"_id": 0})
    return _to_v1(s) if s else None

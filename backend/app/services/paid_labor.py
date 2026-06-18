"""Paid labor from v3 payment_slips — replaces the legacy payroll_payments mirror.

Returns the exact shape the finance dashboard/reports already expect, so call
sites stay unchanged:
    {id, payment_date (YYYY-MM-DD), net_salary, employee_name}

Mapping mirrors what payroll_sync used to write into payroll_payments:
    net_salary   = paid_now_amount   (cash paid in that run)
    payment_date = paid_at[:10]      (date only)
Only paid slips with a non-zero amount are returned (same as the old sync).
"""
from app.db import db


async def paid_labor_v3(org_id: str, date_from: str, date_to: str) -> list[dict]:
    # paid_at is a full ISO timestamp; extend the upper bound so payments made
    # on date_to (which carry a time component) are not dropped.
    upper = date_to if "T" in (date_to or "") else (date_to or "") + "T23:59:59.999999"
    slips = await db.payment_slips.find(
        {
            "org_id": org_id,
            "status": "paid",
            "archived": {"$ne": True},
            "paid_at": {"$gte": date_from, "$lte": upper},
        },
        {"_id": 0, "id": 1, "paid_at": 1, "paid_now_amount": 1, "first_name": 1, "last_name": 1},
    ).to_list(10000)
    out = []
    for s in slips:
        amt = round(float(s.get("paid_now_amount") or 0), 2)
        if amt == 0:
            continue
        out.append({
            "id": s.get("id"),
            "payment_date": (s.get("paid_at") or "")[:10],
            "net_salary": amt,
            "employee_name": (f"{s.get('first_name', '')} {s.get('last_name', '')}").strip(),
        })
    return out

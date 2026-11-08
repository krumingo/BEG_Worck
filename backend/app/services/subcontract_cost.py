"""
SUB-ADV-01 addendum A (FLOW Guard FG-115) — subcontractor money: cash vs cost.

FLOW-006: "Каса + банка + печалба/резултат не се смесват". An advance to a subcontractor
(``subcontractor_payments`` row with ``kind = "advance"``) is a cash movement, NOT a cost:

  * cash reports keep it as an outflow (``subcontractor_cash_out``);
  * P&L / result recognise the subcontractor cost only when the advance is deducted on an
    act (the earned part): ordinary payments + advance deducted on acts
    (``subcontractor_cost_recognized``; the deducted amounts live on the packages,
    ``advance_deducted_total``, reserved atomically with the act).

Statuses as the callers used before: ``confirmed``, ``paid``, ``completed``.
"""
from typing import Any

PAID_STATUSES = ["confirmed", "paid", "completed"]
ADVANCE_KIND = "advance"


async def _sum(tenant: Any, coll: str, match: dict, field: str) -> float:
    rows = await getattr(tenant, coll).aggregate([
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$" + field}}},
    ]).to_list(1)
    return round(float(rows[0]["total"]) if rows else 0.0, 2)


async def subcontractor_cash_out(tenant: Any, org_id: str, project_id: str) -> float:
    """Every subcontractor payment that left the cash/bank, advances included."""
    return await _sum(tenant, "subcontractor_payments",
                      {"org_id": org_id, "project_id": project_id,
                       "status": {"$in": PAID_STATUSES}}, "amount")


async def subcontractor_cost_recognized(tenant: Any, org_id: str, project_id: str) -> float:
    """Subcontractor cost for P&L: ordinary payments + advance deducted on acts."""
    ordinary = await _sum(tenant, "subcontractor_payments",
                          {"org_id": org_id, "project_id": project_id,
                           "status": {"$in": PAID_STATUSES}, "kind": {"$ne": ADVANCE_KIND}},
                          "amount")
    deducted = await _sum(tenant, "subcontractor_packages",
                          {"org_id": org_id, "project_id": project_id},
                          "advance_deducted_total")
    return round(ordinary + deducted, 2)

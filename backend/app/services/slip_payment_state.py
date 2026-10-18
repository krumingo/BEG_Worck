"""R0-06-C02 — the one rule for "is this payment slip paid?".

A slip counts (and shows) as paid ONLY when its parent Pay Run, in the same tenant,
has status ``paid``. A slip the payment flow already wrote as ``paid`` whose run is
``paying`` / ``payment_failed`` (the payment broke after the slip update), or whose run
is missing or anything else, is NOT paid: its effective status is ``confirmed`` (still
owed / unresolved) and it carries ``payment_incomplete=True`` plus the recorded values.

Every reader of ``payment_slips`` as paid goes through here — never through the raw
slip status alone.
"""
from typing import Dict, Iterable, List, Optional, Set

from app.tenancy.data_access import TenantData

INCOMPLETE_RUN_STATUSES = ("paying", "payment_failed")


async def paid_run_ids(tenant: TenantData, run_ids: Optional[Iterable[str]] = None) -> Set[str]:
    """Ids of the tenant's Pay Runs whose payment COMPLETED (status ``paid``)."""
    flt = {"status": "paid"}
    if run_ids is not None:
        wanted = sorted({i for i in run_ids if i})
        if not wanted:
            return set()
        flt["id"] = {"$in": wanted}
    return set(await tenant.pay_runs.distinct("id", flt))


async def _run_statuses(tenant: TenantData, run_ids: Iterable[str]) -> Dict[str, str]:
    wanted = sorted({i for i in run_ids if i})
    if not wanted:
        return {}
    docs = await tenant.pay_runs.find({"id": {"$in": wanted}}, {"_id": 0, "id": 1, "status": 1}).to_list(None)
    return {d["id"]: d.get("status") or "" for d in docs}


def effective_slip(slip: dict, run_status: Optional[str]) -> dict:
    """The slip as readers must see it, given its parent run's status."""
    out = dict(slip)
    if run_status in INCOMPLETE_RUN_STATUSES:
        out["payment_incomplete"] = True
        out["pay_run_status"] = run_status
    if out.get("status") == "paid" and run_status != "paid":
        out["payment_incomplete"] = True
        out["pay_run_status"] = run_status
        out["recorded_status"] = "paid"
        out["recorded_paid_at"] = out.get("paid_at")
        out["status"] = "confirmed"
        out["paid_at"] = None
    return out


async def effective_slips(tenant: TenantData, slips: List[dict]) -> List[dict]:
    statuses = await _run_statuses(tenant, (s.get("pay_run_id") for s in slips))
    return [effective_slip(s, statuses.get(s.get("pay_run_id"))) for s in slips]


async def effective_slip_one(tenant: TenantData, slip: Optional[dict]) -> Optional[dict]:
    return (await effective_slips(tenant, [slip]))[0] if slip else None


async def slip_status_clause(tenant: TenantData, statuses: Iterable[str]) -> dict:
    """A query clause selecting the slips whose EFFECTIVE status is in ``statuses``."""
    wanted = set(statuses)
    paid_ids = sorted(await paid_run_ids(tenant))
    ors = []
    other = wanted - {"paid", "confirmed"}
    if other:
        ors.append({"status": {"$in": sorted(other)}})
    if "paid" in wanted:
        ors.append({"status": "paid", "pay_run_id": {"$in": paid_ids}})
    if "confirmed" in wanted:
        ors.append({"status": "confirmed"})
        ors.append({"status": "paid", "pay_run_id": {"$nin": paid_ids}})
    return {"$or": ors} if ors else {"status": {"$in": []}}

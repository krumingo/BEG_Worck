"""
Service — the ONE read of labor (LAB-R96 step 3, Р100 "едно четене, една формула").

Decisions: Р100 (P&L, ведомост, бюджет по дейност и „Приходи/разходи" четат едните одобрени
редове; една формула за ставка и извънреден труд), Р101 (старите записи от часовника остават,
дали се броят — след ОП-2), Р102 (отчетен / одобрен / платен), Р105 (разходът е платеното и
дължимото).

Design note
-----------
* Source: the labor lines in ``employee_daily_reports``, BOTH stored formats, through
  ``report_normalizer.fetch_normalized_report_lines`` (flat ``worker_id/date/hours`` and old
  ``employee_id/report_date/day_entries[]``, line id ``<report>_<entry>``). Nothing else is a
  labor source: ``work_sessions`` written by an approval (``source_method == APPROVED_REPORT``)
  are a derived record of that approval and are never added on top (no double count);
  ``labor_entries`` are not read (Р96); ``daily_work_logs`` / ``work_reports`` headers carry no
  hours since step 2.
* Old clock sessions (``work_sessions`` with any other ``source_method``, Р101): kept as today
  (their stored ``labor_cost`` / ``duration_hours``) but returned as a SEPARATE component
  ``clock`` labelled ``CLOCK_LABEL`` — callers that counted them keep counting them, visibly,
  never merged into the line totals. Whether they keep counting is decided after ОП-2.
* ONE formula = the pay run's ``calc_earned`` (moved here verbatim from ``routes/pay_runs.py``,
  which imports it back): it is what is actually paid (Р105). A line's cost is that formula
  applied per worker × day × payment batch, split over the day's lines by hours (cents to the
  last line). For Hourly / Daily / Monthly / Akord the pay run's formula is additive over days,
  so the per-line costs of the lines a pay run holds sum to its ``earned_amount``; a "batch" is
  one pay run (``payroll_source``) or "not yet paid" — exactly the groups the pay runs pay.
* Rates: a batched / paid line is costed with the rates frozen on its pay run's employee row
  (``frozen_hourly_rate`` / ``frozen_daily_rate`` / ``pay_type``) — what was paid; an unpaid or
  reported line with the employee profile of today — what the next pay run would pay.
* Normal / overtime: ``report_normalizer.enrich_hours_batch`` over the worker's whole day (all
  objects, frozen at approval when stored). Hours split only — the pay run applies no overtime
  coefficient to Hourly / Daily / Monthly pay (see ``calc_earned``); ``overtime_cost`` is the
  overtime hours' share of the line cost.
* States per line (Р102): ``reported`` (Submitted, not approved — a FORECAST, never in cost
  totals), ``approved_unpaid``, ``batched`` (in a confirmed pay run, not yet paid), ``paid``.
  A reported line's forecast is the increment it would add to its worker's unpaid day.
* Tenant: every read goes through ``TenantData.for_resolved_org`` (Tenant Guard).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

import app.db as _appdb   # read at call time: the database the app (or a test) points app.db.db at
from app.services.labor_report_service import norm_activity
from app.services.report_normalizer import enrich_hours_batch, fetch_normalized_report_lines
from app.tenancy.data_access import TenantData

STATE_REPORTED = "reported"
STATE_APPROVED = "approved_unpaid"
STATE_BATCHED = "batched"
STATE_PAID = "paid"
COST_STATES = (STATE_APPROVED, STATE_BATCHED, STATE_PAID)       # what is owed or paid (Р105)
ALL_STATES = (STATE_REPORTED,) + COST_STATES
CLOCK_LABEL = "часовник (стар)"
APPROVED_SESSION = "APPROVED_REPORT"


# ═══════════════════════════════════════════════════════════════════ the formula
def calc_earned(profile: dict, approved_hours: float, approved_days: int,
                period_days: int = 7, approved_value: float = 0) -> dict:
    """
    Multi pay-type earned engine (the pay run's formula — canonical, LAB-R96 step 3).
    Returns: {earned, rate, rate_type, daily_rate, hourly_rate, formula}
    """
    pay = (profile.get("pay_type") or "Monthly").strip()
    hr = float(profile.get("hourly_rate") or 0)
    dr = float(profile.get("daily_rate") or 0)
    ms = float(profile.get("monthly_salary") or 0)
    wd = int(profile.get("working_days_per_month") or 22)
    hd = int(profile.get("standard_hours_per_day") or 8)

    if pay == "Hourly":
        earned = round(approved_hours * hr, 2)
        return {"earned": earned, "rate": hr, "rate_type": "hourly",
                "daily_rate": round(hr * hd, 2), "hourly_rate": hr,
                "formula": f"{approved_hours}ч × {hr} EUR/ч"}

    elif pay == "Daily":
        earned = round(approved_days * dr, 2)
        effective_hr = round(dr / max(hd, 1), 2)
        return {"earned": earned, "rate": dr, "rate_type": "daily",
                "daily_rate": dr, "hourly_rate": effective_hr,
                "formula": f"{approved_days}д × {dr} EUR/д"}

    elif pay == "Monthly":
        # Pro-rated: (monthly / working_days) × approved_days
        daily = round(ms / max(wd, 1), 2)
        earned = round(daily * approved_days, 2)
        effective_hr = round(daily / max(hd, 1), 2)
        return {"earned": earned, "rate": ms, "rate_type": "monthly",
                "daily_rate": daily, "hourly_rate": effective_hr,
                "formula": f"{ms} EUR/мес ÷ {wd}д = {daily} EUR/д × {approved_days}д"}

    elif pay == "Akord":
        # Piecework: use approved_value if available, else hours × rate
        if approved_value > 0:
            earned = round(approved_value, 2)
            formula = f"Одобрена стойност: {approved_value} EUR"
        elif hr > 0:
            earned = round(approved_hours * hr, 2)
            formula = f"{approved_hours}ч × {hr} EUR/ч (акорд)"
        else:
            earned = 0
            formula = "Няма ставка / стойност"
        return {"earned": earned, "rate": hr, "rate_type": "piecework",
                "daily_rate": 0, "hourly_rate": hr, "formula": formula}

    else:  # mixed
        # Sum applicable: daily part + hourly overtime if any
        daily = round(ms / max(wd, 1), 2) if ms > 0 else dr
        base_earned = round(daily * approved_days, 2) if daily > 0 else 0
        effective_hr = round(daily / max(hd, 1), 2) if daily > 0 else hr
        overtime_h = max(0, approved_hours - approved_days * hd)
        ot_earned = round(overtime_h * effective_hr * 1.5, 2) if overtime_h > 0 else 0
        earned = round(base_earned + ot_earned, 2)
        formula = f"{approved_days}д × {daily} EUR/д"
        if ot_earned > 0:
            formula += f" + {overtime_h}ч OT × {effective_hr}×1.5"
        return {"earned": earned, "rate": daily, "rate_type": "mixed",
                "daily_rate": daily, "hourly_rate": effective_hr, "formula": formula}


def frozen_profile(row: dict, current: dict) -> dict:
    """The profile a pay run's employee row was paid with (its frozen rates)."""
    p = dict(current or {})
    pay = row.get("pay_type") or p.get("pay_type") or "Monthly"
    p["pay_type"] = pay
    if pay in ("Hourly", "Akord"):
        if row.get("frozen_hourly_rate") is not None:
            p["hourly_rate"] = row["frozen_hourly_rate"]
    elif pay == "Daily":
        if row.get("frozen_daily_rate") is not None:
            p["daily_rate"] = row["frozen_daily_rate"]
    elif row.get("frozen_daily_rate"):
        # Monthly / mixed: the frozen row holds the day rate (salary ÷ working days)
        p["monthly_salary"], p["working_days_per_month"] = row["frozen_daily_rate"], 1
    return p


def day_cost(profile: dict, hours: float) -> float:
    """One worker-day of one payment batch, through the pay run's formula."""
    return calc_earned(profile, round(hours, 2), 1, 1)["earned"]


def _split(total: float, lines: List[dict], field: str = "cost") -> None:
    """Split ``total`` over ``lines`` by hours; the last line takes the cents."""
    if not lines:
        return
    hours = sum(ln["hours"] for ln in lines)
    running = 0.0
    for i, ln in enumerate(lines):
        if i == len(lines) - 1:
            share = round(total - running, 2)
        elif hours > 0:
            share = round(total * ln["hours"] / hours, 2)
        else:
            share = round(total / len(lines), 2)
        running += share
        ln[field] = share


# ═══════════════════════════════════════════════════════════════════ states
def run_id_of(line: dict) -> Optional[str]:
    src = line.get("payroll_source") or ""
    return src[len("pay_run:"):] if src.startswith("pay_run:") else None


def state_of(line: dict) -> Optional[str]:
    st = (line.get("status") or "").upper()
    if st == "APPROVED":
        ps = line.get("payroll_status") or "none"
        return STATE_PAID if ps == "paid" else STATE_BATCHED if ps == "batched" else STATE_APPROVED
    if st == "SUBMITTED":
        return STATE_REPORTED
    return None


# ═══════════════════════════════════════════════════════════════════ the read
async def _profiles(tenant: TenantData, org_id: str, worker_ids: Iterable[str]) -> Dict[str, dict]:
    ids = [w for w in set(worker_ids) if w]
    if not ids:
        return {}
    rows = await tenant.employee_profiles.find({"org_id": org_id, "user_id": {"$in": ids}},
                                               {"_id": 0}).to_list(len(ids) + 50)
    return {p["user_id"]: p for p in rows}


async def _run_rows(tenant: TenantData, org_id: str, run_ids: Iterable[str]) -> Dict[tuple, dict]:
    ids = [r for r in set(run_ids) if r]
    if not ids:
        return {}
    runs = await tenant.pay_runs.find({"org_id": org_id, "id": {"$in": ids}},
                                      {"_id": 0, "id": 1, "number": 1, "status": 1,
                                       "employee_rows": 1}).to_list(len(ids) + 10)
    out = {}
    for run in runs:
        for row in run.get("employee_rows") or []:
            out[(run["id"], row.get("employee_id"))] = dict(row, _run_number=run.get("number"),
                                                            _run_status=run.get("status"))
    return out


def _view(ln: dict) -> dict:
    return {
        "line_id": ln.get("id"), "report_id": ln.get("report_id") or ln.get("id"),
        "format": "old" if ln.get("source_type") == "old" else "flat",
        "worker_id": ln.get("worker_id"), "worker_name": ln.get("worker_name") or "",
        "date": ln.get("date"), "project_id": ln.get("project_id") or "",
        "activity": ln.get("smr_type") or "", "activity_key": norm_activity(ln.get("smr_type")),
        "hours": round(float(ln.get("hours") or 0), 2),
        "status": (ln.get("status") or "").upper(),
        "payroll_status": ln.get("payroll_status") or "none",
        "payroll_source": ln.get("payroll_source"), "pay_run_id": run_id_of(ln),
        "payroll_batch_id": ln.get("payroll_batch_id"), "notes": ln.get("notes") or "",
        "created_at": ln.get("created_at") or "",
        "regular_hours": ln.get("regular_hours"), "overtime_hours": ln.get("overtime_hours"),
        "state": state_of(ln),
    }


async def labor_lines(org_id: str, *, project_id: Optional[str] = None,
                      worker_id: Optional[str] = None, activity: Optional[str] = None,
                      date_from: Optional[str] = None, date_to: Optional[str] = None,
                      include_reported: bool = True, fetch=None) -> List[dict]:
    """Every APPROVED labor line (both formats) matching the filters — plus the reported
    (Submitted) ones when ``include_reported`` — each with ``hours, normal_hours,
    overtime_hours, cost, overtime_cost, state, pay_run_id, cost_basis``."""
    tenant = TenantData.for_resolved_org(_appdb.db, org_id)
    fetch = fetch or fetch_normalized_report_lines   # the caller's (pay run) query function
    raw = await fetch(
        org_id=org_id, date_from=date_from if date_to else None, date_to=date_to if date_from else None,
        worker_id=worker_id, project_id=project_id)
    wanted = STATE_REPORTED if include_reported else None
    picked = [_view(ln) for ln in raw]
    picked = [v for v in picked if v["state"] in COST_STATES or (wanted and v["state"] == wanted)]
    if date_from and not date_to:
        picked = [v for v in picked if (v["date"] or "") >= date_from]
    if date_to and not date_from:
        picked = [v for v in picked if (v["date"] or "") <= date_to]
    if activity is not None:
        key = norm_activity(activity)
        picked = [v for v in picked if v["activity_key"] == key]
    if not picked:
        return []

    # The worker's whole day (every object) — a day rate is split over all its lines.
    ids = {v["line_id"] for v in picked}
    if project_id or activity is not None:
        days = {(v["worker_id"], v["date"]) for v in picked}
        workers = {w for w, _ in days}
        dates = sorted(d for _, d in days)
        more = await fetch(org_id=org_id, date_from=dates[0], date_to=dates[-1],
                                                   worker_id=worker_id if len(workers) == 1 else None)
        mates = [_view(ln) for ln in more if (ln.get("worker_id"), ln.get("date")) in days]
        mates = [v for v in mates if v["state"] in ALL_STATES and v["line_id"] not in ids]
        everything = picked + mates
    else:
        everything = picked

    profiles = await _profiles(tenant, org_id, (v["worker_id"] for v in everything))
    runs = await _run_rows(tenant, org_id, (v["pay_run_id"] for v in everything))
    _cost(everything, profiles, runs)
    return [v for v in everything if v["line_id"] in ids]


def _cost(lines: List[dict], profiles: Dict[str, dict], runs: Dict[tuple, dict]) -> None:
    # normal / overtime per worker-day over every line of the day (frozen at approval)
    split = [dict(ln, id=ln["line_id"]) for ln in lines]
    enrich_hours_batch(split)
    for ln, s in zip(lines, split):
        ln["normal_hours"], ln["overtime_hours"] = s["normal_hours"], s["overtime_hours"]

    groups = defaultdict(list)
    for ln in lines:
        if ln["state"] == STATE_REPORTED:
            continue
        batch = ln["pay_run_id"] if ln["state"] in (STATE_BATCHED, STATE_PAID) else None
        groups[(ln["worker_id"], ln["date"], batch)].append(ln)
    for (wid, _d, batch), group in groups.items():
        group.sort(key=lambda x: (x["created_at"], x["line_id"]))
        current = profiles.get(wid, {})
        row = runs.get((batch, wid)) if batch else None
        prof = frozen_profile(row, current) if row else current
        _split(day_cost(prof, sum(g["hours"] for g in group)), group)
        for g in group:
            g["cost_basis"] = "pay_run_frozen" if row else "profile"
            g["pay_run_number"] = (row or {}).get("_run_number")

    # Р102 forecast: what a reported line would ADD to its worker's unpaid day
    reported = defaultdict(list)
    for ln in lines:
        if ln["state"] == STATE_REPORTED:
            reported[(ln["worker_id"], ln["date"])].append(ln)
    for (wid, d), group in reported.items():
        prof = profiles.get(wid, {})
        unpaid = groups.get((wid, d, None))
        base = sum(g["hours"] for g in unpaid or [])
        base_cost = day_cost(prof, base) if unpaid else 0.0
        inc = day_cost(prof, base + sum(g["hours"] for g in group)) - base_cost
        _split(round(inc, 2), sorted(group, key=lambda x: (x["created_at"], x["line_id"])))
        for g in group:
            g["cost_basis"] = "forecast"
            g["pay_run_number"] = None

    for ln in lines:
        h = ln["hours"]
        ln["overtime_cost"] = round(ln["cost"] * ln["overtime_hours"] / h, 2) if h > 0 else 0.0


async def pay_run_lines(org_id: str, date_from: str, date_to: str, *, worker_id: Optional[str] = None,
                        include_locked: bool = False, fetch=None) -> List[dict]:
    """The approved lines a pay run reads — the SAME read and split as every report, in the
    shape the pay run code uses (``id, worker_id, date, project_id, hours, normal_hours,
    overtime_hours, status, payroll_status, payroll_batch_id, notes``) plus ``cost`` /
    ``pay_run_id``. Without ``include_locked`` only lines not batched / paid (the selection)."""
    lines = await labor_lines(org_id, worker_id=worker_id, date_from=date_from, date_to=date_to,
                              include_reported=False, fetch=fetch)
    if not include_locked:
        lines = [ln for ln in lines if ln["state"] == STATE_APPROVED]
    return [dict(ln, id=ln["line_id"], smr_type=ln["activity"]) for ln in lines]


async def clock_sessions(org_id: str, *, project_id: Optional[str] = None,
                         activity: Optional[str] = None, worker_id: Optional[str] = None,
                         started_from: Optional[str] = None, started_before: Optional[str] = None
                         ) -> List[dict]:
    """Old clock records (Р101) — ended ``work_sessions`` NOT written by an approval, with
    their stored cost (today's behaviour). Never merged into the line totals."""
    tenant = TenantData.for_resolved_org(_appdb.db, org_id)
    q: Dict[str, Any] = {"org_id": org_id, "ended_at": {"$ne": None},
                         "source_method": {"$ne": APPROVED_SESSION}}
    if project_id:
        q["site_id"] = project_id
    if worker_id:
        q["worker_id"] = worker_id
    if started_from or started_before:
        q["started_at"] = {}
        if started_from:
            q["started_at"]["$gte"] = started_from
        if started_before:
            q["started_at"]["$lt"] = started_before
    rows = await tenant.work_sessions.find(q, {"_id": 0}).to_list(5000)
    if activity is not None:
        key = norm_activity(activity)
        rows = [s for s in rows if norm_activity(s.get("smr_type_id")) == key]
    return [{"session_id": s.get("id"), "label": CLOCK_LABEL, "worker_id": s.get("worker_id"),
             "worker_name": s.get("worker_name") or "", "date": (s.get("started_at") or "")[:10],
             "project_id": s.get("site_id"), "activity": s.get("smr_type_id") or "",
             "activity_key": norm_activity(s.get("smr_type_id")),
             "source_method": s.get("source_method"), "is_flagged": bool(s.get("is_flagged")),
             "is_overtime": bool(s.get("is_overtime")),
             "hours": float(s.get("duration_hours") or 0), "cost": float(s.get("labor_cost") or 0),
             "hourly_rate_at_date": s.get("hourly_rate_at_date") or 0} for s in rows]


# ═══════════════════════════════════════════════════════════════════ totals
def _empty() -> dict:
    return {"hours": 0.0, "cost": 0.0, "lines": 0}


def summarize(lines: List[dict], clock: Optional[List[dict]] = None) -> dict:
    """Totals of a read. ``hours / cost / normal_hours / overtime_hours / overtime_cost`` are
    the APPROVED lines (approved_unpaid + batched + paid); ``by_state`` adds the reported
    forecast; ``clock`` is the old clock component, NOT inside the line totals."""
    by_state = {s: _empty() for s in ALL_STATES}
    tot = {"hours": 0.0, "cost": 0.0, "normal_hours": 0.0, "overtime_hours": 0.0, "overtime_cost": 0.0}
    for ln in lines:
        b = by_state[ln["state"]]
        b["hours"] += ln["hours"]
        b["cost"] += ln["cost"]
        b["lines"] += 1
        if ln["state"] in COST_STATES:
            tot["hours"] += ln["hours"]
            tot["cost"] += ln["cost"]
            tot["normal_hours"] += ln["normal_hours"]
            tot["overtime_hours"] += ln["overtime_hours"]
            tot["overtime_cost"] += ln["overtime_cost"]
    for b in by_state.values():
        b["hours"], b["cost"] = round(b["hours"], 2), round(b["cost"], 2)
    out = {k: round(v, 2) for k, v in tot.items()}
    out["by_state"] = by_state
    out["unpaid_cost"] = round(by_state[STATE_APPROVED]["cost"] + by_state[STATE_BATCHED]["cost"], 2)
    out["paid_cost"] = by_state[STATE_PAID]["cost"]
    out["forecast_cost"] = by_state[STATE_REPORTED]["cost"]
    c = clock or []
    out["clock"] = {"label": CLOCK_LABEL, "sessions": len(c),
                    "hours": round(sum(s["hours"] for s in c), 2),
                    "cost": round(sum(s["cost"] for s in c), 2),
                    "overtime_cost": round(sum(s["cost"] for s in c if s["is_overtime"]), 2)}
    return out


def group_by(lines: List[dict], key: str) -> Dict[Any, dict]:
    """Per project / activity_key / worker_id / date summaries of a read."""
    groups = defaultdict(list)
    for ln in lines:
        groups[ln.get(key)].append(ln)
    return {k: summarize(v) for k, v in groups.items()}


async def project_labor(org_id: str, project_id: str, *, include_clock: bool = True,
                        date_from: Optional[str] = None, date_to: Optional[str] = None) -> dict:
    """The read every project report uses: lines + clock component + totals."""
    lines = await labor_lines(org_id, project_id=project_id, date_from=date_from, date_to=date_to)
    clock = []
    if include_clock:
        clock = await clock_sessions(
            org_id, project_id=project_id,
            started_from=("%sT00:00:00" % date_from) if date_from else None,
            started_before=("%sT23:59:59.999" % date_to) if date_to else None)
    return {"project_id": project_id, "lines": lines, "clock": clock, "totals": summarize(lines, clock)}

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

FIX-PAY-03 (FLOW-028 "един отчетен ред не може да бъде платен два пъти", "Pay Run използва
само одобрени и неплатени source records", "заработка = одобрено измерено количество ×
договорена единична цена труд")
* A. The day rate (Daily; Monthly ÷ working days) is earned ONCE per worker × calendar day
  across all pay runs. A later pay run that holds more lines of a day already batched / paid
  adds only what the rule genuinely adds (``_increment``: nothing for Daily / Monthly; the
  extra over the day for mixed; Hourly is additive and unchanged). A pay run row written
  after this fix records the dates it paid the day rate for (``day_rate_dates``); the reader
  costs each batch exactly as its run paid it, so a row WITHOUT that field (written before)
  keeps its full day (what was paid — existing paid data is not changed).
* B. Akord: a line's earned = the approved quantity × the agreed unit labor price from a
  ``labor_quantity_approvals`` record (the LAB-02 data model: status "approved", bound to the
  line's report + entry + report_version, approver ≠ worker; price = the record's
  ``piece_rate`` snapshot, else the approver-named ``execution_packages.labor_piece_rate`` of
  the line's project). No such record / no price → amount 0 and ``akord_blocked`` (the reason);
  never hours × rate. A paid / batched akord line keeps what its run paid
  (``akord_line_amounts`` on the row; a row written before keeps hours × frozen rate).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
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
AKORD = "Akord"
DAY_RATE_TYPES = ("Daily", "Monthly")
AKORD_NO_QTY = "Акорд: няма одобрено количество"
AKORD_NO_PRICE = "Акорд: няма договорена единична цена труд"


# ═══════════════════════════════════════════════════════════════════ the formula
OT_DAY_HOURS = 8   # Р108: the day-rate premium hour = day rate ÷ 8
OT_RULE = "R108"   # marks a pay run row paid with the approved-coefficient premium


def _cents_half_up(value) -> float:
    """Р108 premium only: to the cent, half up (0.625 → 0.63). Base pay keeps ``round``."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def approved_coefficient(line: dict) -> Optional[float]:
    """Р108: the overtime coefficient the APPROVER put on the line — stored with the approval
    override (``overtime_coefficient`` with its ``overtime_reason``, approve_report_one). The
    default split of an approval without an override (coefficient 1.0, no reason) is not an
    approved coefficient: no premium."""
    coef = line.get("overtime_coefficient")
    if coef is None or not (line.get("overtime_reason") or "").strip():
        return None
    try:
        coef = float(coef)
    except (TypeError, ValueError):
        return None
    return coef if coef >= 1 and coef == coef and coef != float("inf") else None


def overtime_of(lines: Iterable[dict]) -> List[tuple]:
    """(overtime hours, approved coefficient) of the lines that carry an approved coefficient."""
    out = []
    for ln in lines:
        coef = approved_coefficient(ln)
        ot = float(ln.get("overtime_hours") or 0)
        if coef is not None and ot > 0:
            out.append((ot, coef))
    return out


def overtime_premium(pay: str, hourly: float, day_rate: float, overtime) -> tuple:
    """Р108 (Krum 16.11.2026): (premium, overtime hours, formula part). Only lines with an
    approved coefficient: Hourly — the hours over the norm are already paid × rate, the
    premium adds × (coefficient − 1), so they are paid × rate × coefficient; Daily / Monthly /
    mixed — hours over 8 in the day × (day rate ÷ 8) × coefficient. Akord: none."""
    if pay == AKORD or not overtime:
        return 0.0, 0.0, ""
    total, hours, parts = Decimal(0), 0.0, []
    for ot, coef in overtime:
        if pay == "Hourly":
            total += Decimal(str(ot)) * Decimal(str(hourly)) * (Decimal(str(coef)) - 1)
            parts.append(f"{ot}ч × {hourly} × {coef}")
        else:
            total += Decimal(str(ot)) * Decimal(str(day_rate)) / OT_DAY_HOURS * Decimal(str(coef))
            parts.append(f"{ot}ч × ({day_rate}/{OT_DAY_HOURS}) × {coef}")
        hours += ot
    premium = _cents_half_up(total)
    return premium, round(hours, 2), (" + извънреден " + " + ".join(parts) + f" = {premium} EUR"
                                      if premium else "")


def calc_earned(profile: dict, approved_hours: float, approved_days: int,
                period_days: int = 7, approved_value: float = 0, overtime=None) -> dict:
    """
    Multi pay-type earned engine (the pay run's formula — canonical, LAB-R96 step 3).
    ``overtime`` = [(overtime hours, approved coefficient)] of the lines (``overtime_of``) —
    Р108: a premium only where the approver put a coefficient.
    Returns: {earned, rate, rate_type, daily_rate, hourly_rate, formula, overtime_premium}
    """
    pay = (profile.get("pay_type") or "Monthly").strip()
    hr = float(profile.get("hourly_rate") or 0)
    dr = float(profile.get("daily_rate") or 0)
    ms = float(profile.get("monthly_salary") or 0)
    wd = int(profile.get("working_days_per_month") or 22)
    hd = int(profile.get("standard_hours_per_day") or 8)

    if pay == "Hourly":
        earned = round(approved_hours * hr, 2)
        out = {"earned": earned, "rate": hr, "rate_type": "hourly",
               "daily_rate": round(hr * hd, 2), "hourly_rate": hr,
               "formula": f"{approved_hours}ч × {hr} EUR/ч"}
        prem = overtime_premium(pay, hr, 0, overtime)

    elif pay == "Daily":
        earned = round(approved_days * dr, 2)
        effective_hr = round(dr / max(hd, 1), 2)
        out = {"earned": earned, "rate": dr, "rate_type": "daily",
               "daily_rate": dr, "hourly_rate": effective_hr,
               "formula": f"{approved_days}д × {dr} EUR/д"}
        prem = overtime_premium(pay, hr, dr, overtime)

    elif pay == "Monthly":
        # Pro-rated: (monthly / working_days) × approved_days
        daily = round(ms / max(wd, 1), 2)
        earned = round(daily * approved_days, 2)
        effective_hr = round(daily / max(hd, 1), 2)
        out = {"earned": earned, "rate": ms, "rate_type": "monthly",
               "daily_rate": daily, "hourly_rate": effective_hr,
               "formula": f"{ms} EUR/мес ÷ {wd}д = {daily} EUR/д × {approved_days}д"}
        prem = overtime_premium(pay, hr, daily, overtime)

    elif pay == "Akord":
        # FIX-PAY-03 (FLOW-028): akord = approved quantity × agreed unit labor price
        # (``approved_value``, see ``akord_terms``). Without it there is no payable amount —
        # hours × rate is never an akord earning.
        if approved_value > 0:
            earned = round(approved_value, 2)
            formula = f"Одобрено количество × ед. цена труд: {earned} EUR"
        else:
            earned = 0
            formula = "Няма одобрено количество / ед. цена труд — няма задължение"
        out = {"earned": earned, "rate": hr, "rate_type": "piecework",
               "daily_rate": 0, "hourly_rate": hr, "formula": formula}
        prem = (0.0, 0.0, "")

    else:  # mixed
        # Р108: the day part + the approved-coefficient premium per line (the former
        # automatic ×1.5 over the period's hours is gone)
        daily = round(ms / max(wd, 1), 2) if ms > 0 else dr
        base_earned = round(daily * approved_days, 2) if daily > 0 else 0
        effective_hr = round(daily / max(hd, 1), 2) if daily > 0 else hr
        out = {"earned": base_earned, "rate": daily, "rate_type": "mixed",
               "daily_rate": daily, "hourly_rate": effective_hr,
               "formula": f"{approved_days}д × {daily} EUR/д"}
        prem = overtime_premium(pay, hr, daily, overtime)

    premium, _ot_h, text = prem
    out["overtime_premium"] = premium
    if premium:
        out["earned"] = round(out["earned"] + premium, 2)
        out["formula"] += text
    return out


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


def day_cost(profile: dict, hours: float, overtime=None) -> float:
    """One worker-day of one payment batch, through the pay run's formula (Р108: with the
    approved-coefficient overtime of its lines)."""
    return calc_earned(profile, round(hours, 2), 1, 1, overtime=overtime)["earned"]


def pay_type_of(profile: dict) -> str:
    return ((profile or {}).get("pay_type") or "Monthly").strip()


def _increment(profile: dict, prior_hours: float, hours: float, overtime=None) -> float:
    """FIX-PAY-03 (A): what ``hours`` more add to a worker-day whose day rate was already
    earned with ``prior_hours`` (in another pay run). Hourly is additive (unchanged: its own
    hours); Daily / Monthly / mixed add no day rate — only (Р108) the approved-coefficient
    premium of these lines (``overtime``)."""
    if pay_type_of(profile) == "Hourly":
        return day_cost(profile, hours, overtime)
    return round(day_cost(profile, prior_hours + hours, overtime) - day_cost(profile, prior_hours), 2)


def run_earned(profile: dict, lines: List[dict], period_days: int = 7,
               locked_hours: Optional[Dict[str, float]] = None) -> dict:
    """FIX-PAY-03: the earned amount of ONE worker's ``lines`` in ONE pay run.

    ``locked_hours`` = {date: hours of that worker's lines already batched / paid by another
    pay run}. Those dates already earned the day rate: Daily / Monthly earn nothing more for
    them (Р108: only the approved-coefficient premium of the new lines); Hourly is unchanged. Akord lines carry their
    ``akord_amount`` (approved quantity × unit price; blocked lines are not passed in).
    Returns ``calc_earned``'s dict plus ``approved_days`` (the days this run pays the day rate
    for), ``day_rate_dates``, ``already_paid_dates`` and, for akord, ``akord_line_amounts``."""
    locked_hours = locked_hours or {}
    pay = pay_type_of(profile)
    total_hours = round(sum(ln["hours"] for ln in lines), 1)
    dates = sorted({ln["date"] for ln in lines})
    fresh = [d for d in dates if d not in locked_hours]
    topup = [d for d in dates if d in locked_hours]
    extra = {}
    if pay == AKORD:
        amounts = {ln["id"]: round(float(ln.get("akord_amount") or 0), 2) for ln in lines}
        e = calc_earned(profile, total_hours, len(dates), period_days,
                        approved_value=round(sum(amounts.values()), 2))
        e.update(approved_days=len(dates), day_rate_dates=dates)
        extra["akord_line_amounts"] = amounts
    elif pay == "Hourly":
        e = calc_earned(profile, total_hours, len(dates), period_days, overtime=overtime_of(lines))
        e.update(approved_days=len(dates), day_rate_dates=dates)
    else:
        # Daily / Monthly / mixed: the day rate for the fresh days only; Р108: the
        # approved-coefficient premium of every line of the run (a premium is per line, not
        # per day rate, so a line of an already-paid day still earns its own premium)
        e = calc_earned(profile, total_hours, len(fresh), period_days, overtime=overtime_of(lines))
        e.update(approved_days=len(fresh), day_rate_dates=fresh)
    if topup and pay not in ("Hourly", AKORD):
        e["formula"] += f" ({len(topup)}д вече платени — надницата се плаща веднъж)"
    e["already_paid_dates"] = topup
    e["overtime_rule"] = OT_RULE
    e.update(extra)
    return e


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
                                      {"_id": 0, "id": 1, "number": 1, "status": 1, "created_at": 1,
                                       "employee_rows": 1}).to_list(len(ids) + 10)
    out = {}
    for run in runs:
        for row in run.get("employee_rows") or []:
            out[(run["id"], row.get("employee_id"))] = dict(row, _run_number=run.get("number"),
                                                            _run_status=run.get("status"),
                                                            _run_created_at=run.get("created_at") or "")
    return out


def _num(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


async def akord_terms(tenant: TenantData, org_id: str, lines: List[dict]) -> Dict[str, dict]:
    """FIX-PAY-03 (B): per line id, the akord terms from records the worker cannot write —
    ``{approval_id, approved_quantity, unit, piece_rate, amount, blocked}``.

    Source: ``labor_quantity_approvals`` (LAB-02 data model, read only here): status
    "approved", same tenant, bound to the line's (report_id, entry_id, report_version), an
    ``approved_by`` who is not the line's worker; the earliest such record wins. Price: the
    record's ``piece_rate`` snapshot, else ``execution_packages.labor_piece_rate`` of the
    package the approver named, of the line's own project. amount = quantity × price
    (rounded to the cent); without either → amount 0 and ``blocked`` = the reason."""
    by_key = {}
    for ln in lines:
        by_key[(ln["report_id"], ln.get("entry_id") or "", int(ln.get("report_version") or 0))] = ln
    report_ids = sorted({k[0] for k in by_key if k[0]})
    chosen: Dict[str, dict] = {}
    if report_ids:
        recs = await tenant.labor_quantity_approvals.find(
            {"org_id": org_id, "report_id": {"$in": report_ids}, "status": "approved"},
            {"_id": 0}).to_list(len(by_key) * 4 + 10)
        recs.sort(key=lambda r: (str(r.get("approved_at") or ""), str(r.get("id") or "")))
        for r in recs:
            ln = by_key.get((r.get("report_id"), r.get("entry_id") or "", int(r.get("report_version") or 0)))
            if ln is None:
                continue
            by = r.get("approved_by")
            if not by or by == ln["worker_id"]:          # no self-approval
                continue
            if r.get("worker_id") and r["worker_id"] != ln["worker_id"]:
                continue
            chosen.setdefault(ln["line_id"], r)
    pkg_ids = sorted({r.get("execution_package_id") for r in chosen.values()
                      if r.get("execution_package_id") and not ((_num(r.get("piece_rate")) or 0) > 0)})
    packages = {}
    if pkg_ids:
        rows = await tenant.execution_packages.find(
            {"org_id": org_id, "id": {"$in": pkg_ids}},
            {"_id": 0, "id": 1, "project_id": 1, "labor_piece_rate": 1}).to_list(len(pkg_ids) + 5)
        packages = {p["id"]: p for p in rows}
    out = {}
    for ln in lines:
        r = chosen.get(ln["line_id"])
        qty = _num((r or {}).get("approved_quantity"))
        t = {"approval_id": (r or {}).get("id"), "approved_quantity": qty,
             "unit": (r or {}).get("unit") or "", "piece_rate": None, "amount": 0.0, "blocked": None}
        if r is None or qty is None or qty <= 0:
            t["blocked"] = AKORD_NO_QTY
            out[ln["line_id"]] = t
            continue
        rate = _num(r.get("piece_rate"))
        if not (rate and rate > 0):
            pkg = packages.get(r.get("execution_package_id") or "") or {}
            rate = _num(pkg.get("labor_piece_rate")) if pkg.get("project_id") == ln["project_id"] else None
        if not (rate and rate > 0):
            t["blocked"] = AKORD_NO_PRICE
            out[ln["line_id"]] = t
            continue
        t.update(piece_rate=rate, amount=round(qty * rate, 2))
        out[ln["line_id"]] = t
    return out


def _view(ln: dict) -> dict:
    return {
        "line_id": ln.get("id"), "report_id": ln.get("report_id") or ln.get("id"),
        "entry_id": ln.get("entry_id") or None, "report_version": int(ln.get("report_version") or 0),
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
        "overtime_coefficient": ln.get("overtime_coefficient"),
        "overtime_reason": ln.get("overtime_reason"),
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
    akord = await akord_terms(tenant, org_id, everything)
    _cost(everything, profiles, runs, akord)
    return [v for v in everything if v["line_id"] in ids]


def _akord_cost(group: List[dict], row: Optional[dict], prof: dict, akord: Dict[str, dict]) -> None:
    """FIX-PAY-03 (B): akord lines are costed per line — what their run paid when batched /
    paid (``akord_line_amounts``; a row written before this fix: hours × its frozen rate, as
    it was paid), else approved quantity × unit price, else 0 and blocked."""
    paid = (row or {}).get("akord_line_amounts")
    if row is not None and paid is None:
        _split(day_cost(prof, sum(g["hours"] for g in group)), group)   # legacy row: as paid
        return
    for g in group:
        t = akord.get(g["line_id"]) or {}
        g["approved_quantity"], g["piece_rate"], g["unit"] = (
            t.get("approved_quantity"), t.get("piece_rate"), t.get("unit") or "")
        if paid is not None and g["line_id"] in paid:
            g["cost"] = round(float(paid[g["line_id"]] or 0), 2)
        else:
            g["cost"] = round(float(t.get("amount") or 0), 2)
            g["akord_blocked"] = t.get("blocked")


def _cost(lines: List[dict], profiles: Dict[str, dict], runs: Dict[tuple, dict],
          akord: Optional[Dict[str, dict]] = None) -> None:
    akord = akord or {}
    # normal / overtime per worker-day over every line of the day (frozen at approval)
    split = [dict(ln, id=ln["line_id"]) for ln in lines]
    enrich_hours_batch(split)
    for ln, s in zip(lines, split):
        ln["normal_hours"], ln["overtime_hours"] = s["normal_hours"], s["overtime_hours"]
    for ln in lines:   # FIX-PAY-03 (B): the akord terms of every line, for the pay run
        t = akord.get(ln["line_id"]) or {}
        ln["akord_amount"], ln["akord_blocked"] = round(float(t.get("amount") or 0), 2), t.get("blocked")

    groups = defaultdict(list)
    for ln in lines:
        if ln["state"] == STATE_REPORTED:
            continue
        batch = ln["pay_run_id"] if ln["state"] in (STATE_BATCHED, STATE_PAID) else None
        groups[(ln["worker_id"], ln["date"], batch)].append(ln)

    # FIX-PAY-03 (A): the day rate once per worker × day — the batches of a day in the order
    # they were paid (the runs by creation, the unpaid lines last); each batch costs what its
    # run paid (``day_rate_dates`` on the row; a row without it, written before, paid its
    # own full day), the unpaid lines only what they add to the day.
    days = defaultdict(list)
    for (wid, d, batch) in groups:
        days[(wid, d)].append(batch)
    for (wid, d), batches in days.items():
        locked = sorted((b for b in batches if b),
                        key=lambda b: ((runs.get((b, wid)) or {}).get("_run_created_at") or "", b))
        prior_h, claimed = 0.0, False
        day_total, day_lines = 0.0, []    # the day amount of the day-rate types, re-split below
        for batch in locked + ([None] if None in batches else []):
            group = sorted(groups[(wid, d, batch)], key=lambda x: (x["created_at"], x["line_id"]))
            current = profiles.get(wid, {})
            row = runs.get((batch, wid)) if batch else None
            prof = frozen_profile(row, current) if row else current
            hours = sum(g["hours"] for g in group)
            if pay_type_of(prof) == AKORD:
                _akord_cost(group, row, prof, akord)
            else:
                # Р108: the approved-coefficient premium — for a paid / batched batch only when
                # its run paid by that rule (``overtime_rule``): what was paid stays what was paid
                ot = overtime_of(group) if (row is None or row.get("overtime_rule") == OT_RULE) else None
                if row is not None and "day_rate_dates" in row:
                    total = day_cost(prof, hours, ot) if d in (row.get("day_rate_dates") or []) \
                        else _increment(prof, prior_h, hours, ot)
                elif row is not None or not claimed:
                    total = day_cost(prof, hours, ot)
                else:
                    total = _increment(prof, prior_h, hours, ot)
                _split(total, group)
                if pay_type_of(prof) != "Hourly":
                    day_total += total
                    day_lines += group
            for g in group:
                g["cost_basis"] = "pay_run_frozen" if row else "profile"
                g["pay_run_number"] = (row or {}).get("_run_number")
            prior_h, claimed = prior_h + hours, True
        if len(locked) + (None in batches) > 1 and day_lines:
            # FIX-PAY-03 (A): ONE day amount (what the runs paid + what the unpaid lines add),
            # split over ALL the day's lines / projects by hours — project cost by hours.
            _split(round(day_total, 2), sorted(day_lines, key=lambda x: (x["created_at"], x["line_id"])))

    # Р102 forecast: what a reported line would ADD to its worker's day
    reported = defaultdict(list)
    for ln in lines:
        if ln["state"] == STATE_REPORTED:
            reported[(ln["worker_id"], ln["date"])].append(ln)
    for (wid, d), group in reported.items():
        prof = profiles.get(wid, {})
        group = sorted(group, key=lambda x: (x["created_at"], x["line_id"]))
        if pay_type_of(prof) == AKORD:
            _akord_cost(group, None, prof, akord)
        else:
            if pay_type_of(prof) == "Hourly":   # unchanged: over the unpaid lines of the day
                held = groups.get((wid, d, None)) or []
            else:                               # FIX-PAY-03: over every approved line of the day
                held = [g for b in days.get((wid, d), []) for g in groups[(wid, d, b)]]
            base = sum(g["hours"] for g in held)
            base_cost = day_cost(prof, base, overtime_of(held)) if held else 0.0
            inc = day_cost(prof, base + sum(g["hours"] for g in group),
                           overtime_of(held) + overtime_of(group)) - base_cost
            _split(round(inc, 2), group)
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

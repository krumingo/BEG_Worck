"""
Service — LAB-01: the ONE labor-cost calculation (FLOW-019 + FLOW-028, CLAUDE.md §7, R31).

Every consumer of "real labor cost" — the Pay Run earned amount, the labor sync,
"изхарчено" by SMR (expected-vs-actual), the project P&L labor line — goes through
``compute_person_labor`` (one person, one set of report lines) or
``project_labor_cost`` (one project, built from the same per-person calculation).

Canon applied
-------------
* FLOW-019 / FLOW-028: real labor comes ONLY from APPROVED daily-report lines.
  A line with any other status is excluded (listed in ``excluded``), never priced.
* FLOW-028 / CLAUDE §7: akord earned = APPROVED quantity × agreed piece rate.
  Hours never price an akord line. No approved quantity, or no piece rate →
  amount 0 + a Data Quality warning; the value is never invented.
* Salary (time) lines: approved hours/days × the person's rate (Hourly / Daily /
  Monthly pro-rata / mixed — the existing Pay Run formulas). A missing rate →
  amount 0 + DQ warning; there is NO default rate (no 25, no 200, no 18).
* FLOW-019 §Престой: a line with ``cost_type`` DOWNTIME / DOWNTIME_UNCLASSIFIED is
  its own cost type: it is paid as time and reported apart from the SMR labor;
  it never adds approved quantity.

Pay type priority (FLOW-028 "на ниво отчетен СМР ред/пакет, а не само в профила")
----------------------------------------------------------------------------------
1. the SMR / execution package terms: ``execution_packages.labor_pay_type`` of the
   package the APPROVER named in ``labor_quantity_approvals`` (LAB-01-C — never the
   line's own ``execution_package_id``, which the person filling the report can edit);
2. ``employee_profiles.pay_type`` (fallback; "Monthly" when the profile has none).

LAB-01-B (FG-64): NOTHING that prices a line is read from the report line itself —
the worker fills that line in. (LAB-01-C: ``PUT /daily-reports`` now also refuses
pricing/classification fields in day_entries.)
* ``line.pay_type`` / ``line.piece_rate`` / ``line.approved_quantity`` are IGNORED;
* the piece rate comes ONLY from the package/contract (``labor_piece_rate``);
  the profile ``hourly_rate`` is never a piece rate;
* the approved quantity comes ONLY from an approval record in
  ``labor_quantity_approvals`` (``report_id``, ``approved_quantity``, ``status``
  "approved", ``approved_by``, ``approved_at``) whose approver is not the worker.
  No writer for that collection exists yet — the approval flow is FG-65 (Krum).
DOWNTIME lines are paid as time: the time pay type of the package/profile,
or "Hourly" (profile ``hourly_rate``) when that is Akord.

Sum rule: the per-line amounts of one person add up exactly (to the cent) to
that person's total — so a Pay Run row and the sum over SMR rows of the same
person and period are one number.
"""
from collections import defaultdict

from app.db import db
from app.tenancy.data_access import TenantData

AKORD = "Akord"
TIME_PAY_TYPES = ("Hourly", "Daily", "Monthly")
DOWNTIME_TYPES = ("DOWNTIME", "DOWNTIME_UNCLASSIFIED")
LABOR = "LABOR"

# DQ codes
DQ_AKORD_NO_APPROVED_QTY = "AKORD_NO_APPROVED_QUANTITY"
DQ_AKORD_NO_PIECE_RATE = "AKORD_NO_PIECE_RATE"
DQ_MISSING_RATE = "MISSING_RATE"
DQ_DOWNTIME_UNCLASSIFIED = "DOWNTIME_UNCLASSIFIED"
DQ_DUPLICATE_ENTRY = "DUPLICATE_REPORT_ENTRY"


def approval_key(report_id, entry_id=None, report_version=0) -> str:
    """LAB-01-D (FG-72): a labor approval binds to (report id, report version, entry id)."""
    return f"{report_id or ''}|{entry_id or ''}|{int(report_version or 0)}"


def line_approval_key(line: dict) -> str:
    return approval_key(line.get("report_doc_id") or line.get("id"), line.get("entry_id"),
                        line.get("report_version"))


def record_approval_key(rec: dict) -> str:
    return approval_key(rec.get("report_id"), rec.get("entry_id"), rec.get("report_version"))


def _num(value):
    """A finite float, or None for missing/blank/invalid values."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _norm_pay_type(value):
    v = (value or "").strip() if isinstance(value, str) else ""
    if not v:
        return None
    low = v.lower()
    if low in ("akord", "акорд", "piecework"):
        return AKORD
    for t in TIME_PAY_TYPES:
        if low == t.lower():
            return t
    return v  # unknown → treated as "mixed" by the time formula (as before)


def _packages(terms):
    return (terms or {}).get("packages") or {}


def _quantities(terms):
    return (terms or {}).get("quantities") or {}


def _package(line: dict, terms: dict = None) -> dict:
    """The SMR package that prices ``line`` — ONLY the one named by the approver's record in
    ``labor_quantity_approvals`` (LAB-01-C, LAB01B-1). The line's own
    ``execution_package_id`` is a pointer the person filling the report can edit, so it
    never selects a price or pay type; with no approver-named package the line is priced
    by the profile. Only a package of the line's own project counts."""
    rec = _quantities(terms).get(line_approval_key(line)) or {}
    pkg_id = rec.get("execution_package_id") or ""
    pkg = _packages(terms).get(pkg_id) or {}
    if pkg and pkg.get("project_id") and pkg.get("project_id") != line.get("project_id"):
        return {}
    return pkg


def resolve_pay_type(line: dict, profile: dict, terms: dict = None):
    """(pay_type, source) by the documented priority SMR package → profile.
    The worker-editable ``line.pay_type`` is ignored (FG-64)."""
    terms = _package(line, terms)
    pt = _norm_pay_type(terms.get("labor_pay_type"))
    if pt:
        return pt, "smr"
    return (_norm_pay_type(profile.get("pay_type")) or "Monthly"), "profile"


def resolve_piece_rate(line: dict, terms: dict = None):
    """(piece_rate, source) — ONLY the SMR package/contract. Never the line, never the profile."""
    terms = _package(line, terms)
    r = _num(terms.get("labor_piece_rate"))
    if r is not None and r > 0:
        return r, "smr"
    return None, None


def _is_approved(line: dict) -> bool:
    return (line.get("status") or "").upper() == "APPROVED"


def _cost_type(line: dict) -> str:
    ct = (line.get("cost_type") or line.get("activity_type") or "").strip().upper()
    return ct if ct in DOWNTIME_TYPES else LABOR


def time_pay(profile: dict, pay_type: str, hours: float, days: int) -> dict:
    """The salary formulas of the Pay Run (unchanged), with NO default rate.

    Returns {earned, rate, rate_type, daily_rate, hourly_rate, formula, missing_rate,
    day_rate, ot_earned}. ``day_rate`` is the amount one approved day earns (day-based
    types), ``ot_earned`` the mixed overtime part — used to allocate per line.
    """
    hr = _num(profile.get("hourly_rate")) or 0.0
    dr = _num(profile.get("daily_rate")) or 0.0
    ms = _num(profile.get("monthly_salary")) or 0.0
    wd = int(_num(profile.get("working_days_per_month")) or 22)
    hd = int(_num(profile.get("standard_hours_per_day")) or 8)
    hours = round(float(hours or 0), 2)

    if pay_type == "Hourly":
        return {"earned": round(hours * hr, 2), "rate": hr, "rate_type": "hourly",
                "daily_rate": round(hr * hd, 2), "hourly_rate": hr, "day_rate": None,
                "ot_earned": 0.0, "missing_rate": hr <= 0,
                "formula": f"{hours}ч × {hr} EUR/ч"}
    if pay_type == "Daily":
        return {"earned": round(days * dr, 2), "rate": dr, "rate_type": "daily",
                "daily_rate": dr, "hourly_rate": round(dr / max(hd, 1), 2), "day_rate": dr,
                "ot_earned": 0.0, "missing_rate": dr <= 0,
                "formula": f"{days}д × {dr} EUR/д"}
    if pay_type == "Monthly":
        daily = round(ms / max(wd, 1), 2)
        return {"earned": round(daily * days, 2), "rate": ms, "rate_type": "monthly",
                "daily_rate": daily, "hourly_rate": round(daily / max(hd, 1), 2), "day_rate": daily,
                "ot_earned": 0.0, "missing_rate": ms <= 0,
                "formula": f"{ms} EUR/мес ÷ {wd}д = {daily} EUR/д × {days}д"}
    # mixed / unknown — as the Pay Run computed it before LAB-01
    daily = round(ms / max(wd, 1), 2) if ms > 0 else dr
    base = round(daily * days, 2) if daily > 0 else 0.0
    eff_hr = round(daily / max(hd, 1), 2) if daily > 0 else hr
    ot_h = max(0, hours - days * hd)
    ot = round(ot_h * eff_hr * 1.5, 2) if ot_h > 0 else 0.0
    formula = f"{days}д × {daily} EUR/д"
    if ot > 0:
        formula += f" + {ot_h}ч OT × {eff_hr}×1.5"
    return {"earned": round(base + ot, 2), "rate": daily, "rate_type": "mixed",
            "daily_rate": daily, "hourly_rate": eff_hr, "day_rate": daily if daily > 0 else None,
            "ot_earned": ot, "missing_rate": daily <= 0 and eff_hr <= 0, "formula": formula}


def _split(total: float, weights: list) -> list:
    """Split ``total`` by ``weights`` into cents that add up exactly to ``total``."""
    n = len(weights)
    if n == 0:
        return []
    wsum = sum(weights)
    if wsum <= 0:
        weights, wsum = [1.0] * n, float(n)
    cents = int(round(total * 100))
    parts = [int(cents * w // wsum) for w in weights]
    rest = cents - sum(parts)
    order = sorted(range(n), key=lambda i: (-(cents * weights[i] / wsum - parts[i]), i))
    for i in order[:rest]:
        parts[i] += 1
    return [p / 100 for p in parts]


def _line_base(line: dict) -> dict:
    return {
        "report_id": line.get("id", ""),
        "worker_id": line.get("worker_id", ""),
        "date": line.get("date", ""),
        "project_id": line.get("project_id", ""),
        "smr_type": line.get("smr_type", ""),
        "execution_package_id": line.get("execution_package_id") or None,
        "hours": round(float(line.get("hours") or 0), 2),
        "status": (line.get("status") or "").upper(),
    }


def resolve_approved_quantity(line: dict, terms: dict = None):
    """The approved quantity — ONLY from an approval record, never the line (FG-64), bound
    to this exact (report, version, entry) (FG-72)."""
    rec = _quantities(terms).get(line_approval_key(line))
    if not rec:
        return None
    return _num(rec.get("approved_quantity"))


def compute_person_labor(profile: dict, lines: list, smr_terms: dict = None) -> dict:
    """The labor cost of ONE person over ``lines`` (normalized report lines).

    Returns::

        {"lines": [per-line result], "excluded": [non-approved lines],
         "total", "labor_total", "downtime_total", "akord_total", "time_total",
         "time": {pay_type: time_pay(...)}, "primary_time": time_pay of the main type,
         "dq_warnings": [{code, report_id, message}], "approved_hours", "approved_days"}
    """
    profile = profile or {}
    out_lines, excluded, dq = [], [], []
    akord_lines, time_groups = [], defaultdict(list)
    seen_keys = set()  # FG-72: one approval / one entry is counted at most once

    for ln in lines or []:
        base = _line_base(ln)
        if not _is_approved(ln):
            excluded.append(dict(base, reason="not_approved"))
            continue
        key = line_approval_key(ln)
        duplicate = key in seen_keys
        seen_keys.add(key)
        cost_type = _cost_type(ln)
        pay_type, pt_src = resolve_pay_type(ln, profile, smr_terms)
        rec = dict(base, cost_type=cost_type, pay_type=pay_type, pay_type_source=pt_src,
                   quantity=_num(ln.get("quantity")),
                   approved_quantity=None if duplicate else resolve_approved_quantity(ln, smr_terms),
                   unit=ln.get("unit") or "", piece_rate=None, rate=None, amount=0.0, formula="", dq=[])
        if duplicate:
            rec["dq"].append(DQ_DUPLICATE_ENTRY)
        if cost_type == DQ_DOWNTIME_UNCLASSIFIED:
            rec["dq"].append(DQ_DOWNTIME_UNCLASSIFIED)
        if cost_type == LABOR and pay_type == AKORD:
            akord_lines.append((rec, ln))
        else:
            tpt = pay_type
            if tpt == AKORD:  # downtime of an akord line/person is paid as time
                prof_pt = _norm_pay_type(profile.get("pay_type"))
                tpt = prof_pt if prof_pt and prof_pt != AKORD else "Hourly"
            rec["pay_type"] = tpt
            time_groups[tpt].append(rec)
        out_lines.append(rec)

    # ── akord: approved quantity × piece rate (never hours) ──────────
    akord_total = 0.0
    for rec, ln in akord_lines:
        qty = rec["approved_quantity"]
        rate, r_src = resolve_piece_rate(ln, smr_terms)
        rec["piece_rate"], rec["rate"], rec["piece_rate_source"] = rate, rate, r_src
        if qty is None or qty <= 0:
            rec["dq"].append(DQ_AKORD_NO_APPROVED_QTY)
            rec["formula"] = "акорд: няма одобрено количество → 0"
        elif rate is None:
            rec["dq"].append(DQ_AKORD_NO_PIECE_RATE)
            rec["formula"] = f"акорд: {qty} {rec['unit']} без акордна цена → 0"
        else:
            rec["amount"] = round(qty * rate, 2)
            rec["formula"] = f"{qty} {rec['unit']} × {rate} EUR (акорд)".replace("  ", " ")
        akord_total += rec["amount"]

    # ── salary: the Pay Run time formulas, allocated per line ─────────
    time_results, time_total = {}, 0.0
    for tpt, recs in time_groups.items():
        hours = round(sum(r["hours"] for r in recs), 2)
        days = len({r["date"] for r in recs})
        res = time_pay(profile, tpt, hours, days)
        time_results[tpt] = res
        if res["missing_rate"]:
            for r in recs:
                r["dq"].append(DQ_MISSING_RATE)
                r["formula"] = "няма ставка → 0"
            continue
        total = res["earned"]
        if res["day_rate"] is not None:
            # each approved day earns day_rate, split between that day's lines by hours;
            # mixed overtime is split over all lines by hours
            base_total = round(total - res["ot_earned"], 2)
            by_day = defaultdict(list)
            for r in recs:
                by_day[r["date"]].append(r)
            day_list = sorted(by_day)
            day_amounts = _split(base_total, [1.0] * len(day_list))
            for d, amt in zip(day_list, day_amounts):
                for r, part in zip(by_day[d], _split(amt, [r["hours"] for r in by_day[d]])):
                    r["amount"] = part
            if res["ot_earned"]:
                for r, part in zip(recs, _split(res["ot_earned"], [r["hours"] for r in recs])):
                    r["amount"] = round(r["amount"] + part, 2)
        else:
            for r, part in zip(recs, _split(total, [r["hours"] for r in recs])):
                r["amount"] = part
        for r in recs:
            r["rate"] = res["hourly_rate"]
            r["formula"] = res["formula"]
        time_total += total

    for rec in out_lines:
        for code in rec["dq"]:
            dq.append({"code": code, "report_id": rec["report_id"], "message": _DQ_MESSAGES[code]})

    labor_total = round(sum(r["amount"] for r in out_lines if r["cost_type"] == LABOR), 2)
    downtime_total = round(sum(r["amount"] for r in out_lines if r["cost_type"] != LABOR), 2)
    approved = [r for r in out_lines]
    # the main time result (for rate display): the profile's type, else the largest group
    prof_pt = _norm_pay_type(profile.get("pay_type")) or "Monthly"
    primary = time_results.get(prof_pt) or (
        max(time_results.values(), key=lambda x: x["earned"]) if time_results else None)
    return {
        "lines": out_lines,
        "excluded": excluded,
        "total": round(labor_total + downtime_total, 2),
        "labor_total": labor_total,
        "downtime_total": downtime_total,
        "akord_total": round(akord_total, 2),
        "time_total": round(time_total, 2),
        "time": time_results,
        "primary_time": primary,
        "dq_warnings": dq,
        "approved_hours": round(sum(r["hours"] for r in approved), 1),
        "approved_days": len({r["date"] for r in approved}),
    }


_DQ_MESSAGES = {
    DQ_AKORD_NO_APPROVED_QTY: "Акорд без одобрено количество — не влиза в разхода (0).",
    DQ_AKORD_NO_PIECE_RATE: "Акорд без акордна цена по реда/СМР — не влиза в разхода (0).",
    DQ_MISSING_RATE: "Липсва ставка в профила — не влиза в разхода (0), без ставка по подразбиране.",
    DQ_DOWNTIME_UNCLASSIFIED: "Неуточнен престой — нужна е класификация (FLOW-019).",
    DQ_DUPLICATE_ENTRY: "Повторен ред (същият отчет/версия/ред) — одобреното количество се брои само веднъж.",
}


def person_summary_formula(result: dict) -> str:
    """One human formula line for a Pay Run row."""
    parts = []
    if result["primary_time"] and result["time_total"]:
        parts.append(result["primary_time"]["formula"])
    if result["akord_total"]:
        parts.append(f"акорд {result['akord_total']} EUR (одобр. к-во × цена)")
    if result["downtime_total"]:
        parts.append(f"в т.ч. престой {result['downtime_total']} EUR")
    if result["dq_warnings"]:
        parts.append(f"DQ: {len(result['dq_warnings'])}")
    return "; ".join(parts) or "0"


async def load_smr_terms(tenant: TenantData, org_id: str, lines) -> dict:
    """The pricing terms of ``lines`` from records the worker cannot edit (FG-64)::

        {"packages":   {execution_package_id: {labor_pay_type, labor_piece_rate}},
         "quantities": {approval_key(report, entry, version): approval record}}

    A quantity approval counts only with status "approved", an ``approved_by`` and an
    approver who is not the worker of the line (no self-approval).
    """
    lines = [ln for ln in (lines or []) if isinstance(ln, dict)]
    # FG-72: an approval counts only for the exact (report, version, entry) of a line
    worker_of = {line_approval_key(ln): ln.get("worker_id") for ln in lines
                 if ln.get("report_doc_id") or ln.get("id")}
    report_ids = sorted({ln.get("report_doc_id") or ln.get("id") for ln in lines
                         if ln.get("report_doc_id") or ln.get("id")})
    quantities = {}
    if report_ids:
        recs = await tenant.labor_quantity_approvals.find(
            {"org_id": org_id, "report_id": {"$in": report_ids}, "status": "approved"},
            {"_id": 0},
        ).to_list(len(worker_of) * 4 + 10)
        # deterministic: the earliest approval of a key wins, any second one is ignored
        recs.sort(key=lambda r: (str(r.get("approved_at") or ""), str(r.get("id") or "")))
        for r in recs:
            key, by = record_approval_key(r), r.get("approved_by")
            if key not in worker_of:            # another version / entry → void for this line
                continue
            if not by or by == worker_of[key]:  # no self-approval
                continue
            quantities.setdefault(key, r)
    # LAB-01-C: only approver-named packages are loaded — never the line's own pointer
    pkg_ids = sorted({r.get("execution_package_id") for r in quantities.values() if r.get("execution_package_id")})
    packages = {}
    if pkg_ids:
        pkgs = await tenant.execution_packages.find(
            {"org_id": org_id, "id": {"$in": pkg_ids}},
            {"_id": 0, "id": 1, "project_id": 1, "labor_pay_type": 1, "labor_piece_rate": 1},
        ).to_list(len(pkg_ids))
        packages = {p["id"]: p for p in pkgs}
    return {"packages": packages, "quantities": quantities}


async def void_labor_approvals(tenant: TenantData, org_id: str, report_id: str,
                               actor_id: str, reason: str,
                               collection: str = "employee_daily_reports", bump: bool = True,
                               session=None) -> int:
    """LAB-01-D (FG-72): any change or reset of a report bumps its ``report_version`` and
    voids every labor approval of it. The approval records stay (no delete), marked void."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if bump:  # LAB-01-M: a reset bumps the version inside its own compare-and-set
        await tenant.collection(collection).update_one(
            {"id": report_id, "org_id": org_id}, {"$inc": {"report_version": 1}}, session=session)
    res = await tenant.labor_quantity_approvals.update_many(
        {"org_id": org_id, "report_id": report_id, "status": "approved"},
        {"$set": {"status": "void", "voided_at": now, "voided_by": actor_id, "void_reason": reason}},
        session=session)
    return getattr(res, "modified_count", 0)


# R62 (Krum 09.11.2026, FG-340 / FG-58): a manual labor row counts only after the Owner
# approved it. The rows a sync derives from approved work reports are a PROJECTION of the
# report lines (already counted from the reports) and are never added a second time.
MANUAL_APPROVED = "approved"
MANUAL_PENDING = "pending"
SYNC_SOURCE = "work_report_sync"


async def approved_manual_rows(tenant: TenantData, org_id: str, project_id: str,
                               date_from: str = None, date_to: str = None) -> list:
    """R62: the Owner-approved manual labor rows of a project (not synced, not reversed)."""
    flt = {"org_id": org_id, "project_id": project_id, "source": {"$ne": SYNC_SOURCE},
           "approval_status": MANUAL_APPROVED, "entry_kind": {"$ne": "reversal"},
           "reversed_by_entry_id": None}
    if date_from or date_to:
        flt["date"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    return await tenant.labor_entries.find(flt, {"_id": 0}).to_list(5000)


async def project_labor_cost(org_id: str, project_id: str, date_from: str = None,
                             date_to: str = None) -> dict:
    """THE labor cost of one project ("изхарчено" труд, R31; R62: one number in every
    reader) — approved report lines priced by the one labor calculation (salary → approved
    hours × rate, akord → approved quantity × piece rate, DOWNTIME apart) PLUS the manual
    labor rows the Owner approved. Drafts / unapproved reports and unapproved manual rows
    never count.

    Each worker on the project is computed with ``compute_person_labor`` over ALL their
    approved lines on the same dates (other projects included), so a day-based salary is
    split between the projects of that day exactly as the Pay Run counts it; only the
    project's lines are kept. Returns ``{lines, by_smr, by_package, labor_total,
    downtime_total, total, approved_hours, downtime_hours, manual_total, manual_rows,
    dq_warnings}``. ``by_smr`` is keyed by smr_type and has labor/downtime/hours/
    akord_quantity per SMR; ``by_package`` is keyed by execution_package_id ("" = none).
    """
    from app.services.report_normalizer import fetch_normalized_report_lines

    tenant = TenantData.for_resolved_org(db, org_id)
    proj_lines = await fetch_normalized_report_lines(
        org_id=org_id, date_from=date_from, date_to=date_to, project_id=project_id,
        status_filter="APPROVED")
    proj_lines = [ln for ln in proj_lines if ln.get("project_id") == project_id]
    manual = await approved_manual_rows(tenant, org_id, project_id, date_from, date_to)

    kept, dq = [], []
    if proj_lines:
        workers = sorted({ln["worker_id"] for ln in proj_lines if ln.get("worker_id")})
        dates = sorted({ln["date"] for ln in proj_lines if ln.get("date")})
        d_from, d_to = (date_from or dates[0]), (date_to or dates[-1])

        profiles = await tenant.employee_profiles.find(
            {"org_id": org_id, "user_id": {"$in": workers}}, {"_id": 0}).to_list(len(workers) or 1)
        prof_map = {p["user_id"]: p for p in profiles}

        all_by_worker = {}
        for wid in workers:
            all_lines = await fetch_normalized_report_lines(
                org_id=org_id, date_from=d_from, date_to=d_to, worker_id=wid, status_filter="APPROVED")
            all_by_worker[wid] = all_lines
        smr_terms = await load_smr_terms(tenant, org_id, [ln for ls in all_by_worker.values() for ln in ls])

        for wid in workers:
            res = compute_person_labor(prof_map.get(wid, {}), all_by_worker[wid], smr_terms)
            for rec in res["lines"]:
                if rec["project_id"] == project_id:
                    kept.append(rec)
            dq.extend(w for w in res["dq_warnings"]
                      if any(r["report_id"] == w["report_id"] and r["project_id"] == project_id
                             for r in res["lines"]))

    # R62 / FG-58: the Owner-approved manual rows, each at its own stored cost
    for row in manual:
        cost = row.get("labor_cost")
        rec = {"report_id": "manual:" + str(row.get("id")), "worker_id": row.get("employee_id"),
               "date": row.get("date", ""), "project_id": project_id,
               "smr_type": row.get("activity_name") or "", "hours": float(row.get("hours") or 0),
               "cost_type": LABOR, "pay_type": "Manual", "pay_type_source": "manual_row",
               "rate": row.get("hourly_rate"), "approved_quantity": None, "piece_rate": None,
               "amount": round(float(cost), 2) if cost is not None else 0.0,
               "formula": "ръчен ред, одобрен от Собственика",
               "dq": [] if cost is not None else ["MANUAL_ROW_NO_COST"],
               "execution_package_id": row.get("execution_package_id") or None,
               "manual_entry_id": row.get("id")}
        kept.append(rec)
        if cost is None:
            dq.append({"code": "MANUAL_ROW_NO_COST", "report_id": rec["report_id"],
                       "message": "Ръчен ред за труд без стойност — не влиза в разхода (0)."})

    by_smr, by_package = {}, {}
    for rec in kept:
        key = rec["smr_type"] or "Общо"
        s = by_smr.setdefault(key, {"labor": 0.0, "downtime": 0.0, "hours": 0.0,
                                    "downtime_hours": 0.0, "akord_quantity": 0.0, "dq_count": 0})
        pk = by_package.setdefault(rec.get("execution_package_id") or "",
                                   {"labor": 0.0, "downtime": 0.0, "hours": 0.0, "downtime_hours": 0.0,
                                    "cost": 0.0})
        if rec["cost_type"] == LABOR:
            s["labor"] = round(s["labor"] + rec["amount"], 2)
            s["hours"] = round(s["hours"] + rec["hours"], 2)
            pk["labor"] = round(pk["labor"] + rec["amount"], 2)
            pk["hours"] = round(pk["hours"] + rec["hours"], 2)
            if rec["pay_type"] == AKORD and rec["approved_quantity"]:
                s["akord_quantity"] = round(s["akord_quantity"] + rec["approved_quantity"], 3)
        else:
            s["downtime"] = round(s["downtime"] + rec["amount"], 2)
            s["downtime_hours"] = round(s["downtime_hours"] + rec["hours"], 2)
            pk["downtime"] = round(pk["downtime"] + rec["amount"], 2)
            pk["downtime_hours"] = round(pk["downtime_hours"] + rec["hours"], 2)
        pk["cost"] = round(pk["labor"] + pk["downtime"], 2)
        s["dq_count"] += len(rec["dq"])

    labor_total = round(sum(r["amount"] for r in kept if r["cost_type"] == LABOR), 2)
    downtime_total = round(sum(r["amount"] for r in kept if r["cost_type"] != LABOR), 2)
    return {
        "lines": kept,
        "by_smr": by_smr,
        "by_package": by_package,
        "labor_total": labor_total,
        "downtime_total": downtime_total,
        "total": round(labor_total + downtime_total, 2),
        "approved_hours": round(sum(r["hours"] for r in kept if r["cost_type"] == LABOR), 2),
        "downtime_hours": round(sum(r["hours"] for r in kept if r["cost_type"] != LABOR), 2),
        "manual_total": round(sum(r["amount"] for r in kept if r.get("manual_entry_id")), 2),
        "manual_rows": len(manual),
        "dq_warnings": dq,
    }


async def package_labor_split(org_id: str, project_id: str) -> dict:
    """R62: ``{package_id: {cost, labor, downtime, hours, downtime_hours}}`` of the project
    from THE labor cost, at read time (no cached ``actual_labor_cost``)."""
    if not project_id:
        return {}
    return (await project_labor_cost(org_id, project_id))["by_package"]


async def package_labor_actual(org_id: str, pkg: dict) -> float:
    """R62: one package's labor cost (labor + downtime) from THE labor cost, at read time."""
    split = await package_labor_split(org_id, pkg.get("project_id"))
    return (split.get(pkg.get("id")) or {}).get("cost", 0.0)

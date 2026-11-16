"""
FIX-PERM-01 (Р98, Krum 16.11.2026) — who sees PEOPLE, and who sees their MONEY.

Р98: "The Technical Manager (SiteManager) sees people without money. On the screens
'Служители', 'Служител' and 'Календар на работниците' he sees the people, positions and
the calendar (where they are, leave, sick leave), but not rates, salaries and advances. The
server returns him only these fields; the screen and the server use one common rule."

This is the SEC-02-A (D9) rule of the employee file (``GET /employee-dossier/{id}``)
applied to the three people reads of ``app/routes/hr.py``; nothing new is invented:

  PEOPLE_READ_ROLES   Owner / Admin / Accountant / SiteManager may see people
                      (``FINANCE_WRITE_ROLES`` + SiteManager, the D9 list).
  PEOPLE_MONEY_ROLES  Owner / Admin / Accountant see their money too — the existing
                      ``hr.payroll_permission`` list, unchanged (R20, FLOW-010,
                      FLOW-037 §3.4).
  own record          a caller reading his OWN record keeps today's answer
                      (FLOW-037 §3.4 forbids other people's pay only).

Modes: off/shadow decide on the legacy role; in enforce the SiteManager's no-money view
needs the D9 company action ``finance.employee_dossier.read`` from the Permission
Service (the site_manager role holds it at company scope, catalog.py
``SEC02_SITE_MANAGER_COMPANY_ACTIONS``) — no new catalog action. The finance roles keep
the legacy check they have today in every mode. No denial audit here: the handler raises
the same 403 it raised before.

The no-money view is an ALLOW-LIST (``*_FIELDS`` below): a key that is not listed never
reaches the SiteManager, whatever is added to the stored documents later.

Frontend mirror: ``frontend/src/lib/financeAccess.js`` ``PEOPLE_VIEW_ROLES`` /
``canReadPeople`` (a test fails when the two lists drift).
"""
from typing import Any, Dict, Iterable, List, Optional

from app.permissions.finance_read import EMPLOYEE_FILE_ACTION
from app.permissions.money_write import FINANCE_WRITE_ROLES

PEOPLE_MONEY_ROLES = tuple(FINANCE_WRITE_ROLES)                   # Owner/Admin/Accountant
PEOPLE_READ_ROLES = PEOPLE_MONEY_ROLES + ("SiteManager",)
PEOPLE_READ_ACTION = EMPLOYEE_FILE_ACTION                         # D9 company action

VIEW_FULL = "full"
VIEW_NO_MONEY = "no_money"

# ── the allow-list of the no-money view ──────────────────────────────────────
USER_FIELDS = ("id", "first_name", "last_name", "name", "email", "role", "phone",
               "avatar_url", "is_active")
PROFILE_FIELDS = ("id", "user_id", "position", "active", "start_date")
ATTENDANCE_FIELDS = ("id", "date", "user_id", "project_id", "project_code", "project_name",
                     "status", "note", "marked_at", "source")
PROJECT_HISTORY_FIELDS = ("project_id", "project_code", "project_name", "project_status",
                          "role_in_project", "days_present", "total_hours",
                          "last_attendance", "active", "source")
HOURS_SUMMARY_FIELDS = ("current_month_days", "current_month_hours", "total_projects")
CAL_DAY_FIELDS = ("date", "attendance", "work_reports", "daily_report", "total_hours",
                  "reports", "normal_hours", "overtime_hours", "report_count")
CAL_ATTENDANCE_FIELDS = ("status", "project_code")
CAL_WORK_REPORT_FIELDS = ("project_code", "hours")
CAL_DAILY_REPORT_FIELDS = ("day_status", "approval_status", "hours", "project_codes")
# payroll_status (paid / batched) is pay information: not listed.
CAL_REPORT_FIELDS = ("report_id", "project_id", "project_code", "hours", "normal_hours",
                     "overtime_hours", "smr_type", "status")
CALENDAR_FIELDS = ("month", "days", "total_present", "total_hours")


async def people_view(request, user: Dict[str, Any], *,
                      subject_id: Optional[str] = None) -> Optional[str]:
    """``VIEW_FULL`` / ``VIEW_NO_MONEY`` / ``None`` (= 403) for this caller.

    ``subject_id``: the employee the route is about (None for the list)."""
    if subject_id is not None and subject_id == user.get("id"):
        return VIEW_FULL                                  # own record: unchanged
    role = user.get("role")
    if role in PEOPLE_MONEY_ROLES:
        return VIEW_FULL                                  # unchanged legacy rule
    if role not in PEOPLE_READ_ROLES:
        return None
    from app.permissions.deps import current_mode, MODE_ENFORCE
    if current_mode() != MODE_ENFORCE:
        return VIEW_NO_MONEY
    from app.tenancy.guard import get_tenant_context
    from app.permissions.service import evaluate_permission
    ctx = await get_tenant_context(request, user)
    decision = await evaluate_permission(ctx, PEOPLE_READ_ACTION, module=None,
                                         scope_type="company", scope_id=None)
    return VIEW_NO_MONEY if decision.allowed else None


def pick(doc: Optional[Dict[str, Any]], fields: Iterable[str]) -> Optional[Dict[str, Any]]:
    """Only the allow-listed keys of ``doc`` (None stays None)."""
    if not isinstance(doc, dict):
        return None if doc is None else doc
    return {k: doc[k] for k in fields if k in doc}


def _pick_all(rows, fields) -> List[Dict[str, Any]]:
    return [pick(r, fields) for r in (rows or []) if isinstance(r, dict)]


def employee_row_no_money(row: Dict[str, Any]) -> Dict[str, Any]:
    """One row of ``GET /employees`` without money."""
    out = pick(row, USER_FIELDS)
    out["profile"] = pick(row.get("profile"), PROFILE_FIELDS)
    out["has_profile"] = bool(row.get("has_profile"))
    out["money_hidden"] = True
    return out


def dashboard_no_money(body: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /employees/{id}/dashboard`` without money: no rates, no payslips."""
    return {
        "employee": pick(body.get("employee"), USER_FIELDS),
        "profile": pick(body.get("profile"), PROFILE_FIELDS),
        "attendance": _pick_all(body.get("attendance"), ATTENDANCE_FIELDS),
        "project_history": _pick_all(body.get("project_history"), PROJECT_HISTORY_FIELDS),
        "hours_summary": pick(body.get("hours_summary") or {}, HOURS_SUMMARY_FIELDS),
        "money_hidden": True,
    }


def _cal_day(day: Dict[str, Any]) -> Dict[str, Any]:
    out = pick(day, CAL_DAY_FIELDS)
    if isinstance(day.get("attendance"), dict):
        out["attendance"] = pick(day["attendance"], CAL_ATTENDANCE_FIELDS)
    if isinstance(day.get("daily_report"), dict):
        out["daily_report"] = pick(day["daily_report"], CAL_DAILY_REPORT_FIELDS)
    out["work_reports"] = _pick_all(day.get("work_reports"), CAL_WORK_REPORT_FIELDS)
    out["reports"] = _pick_all(day.get("reports"), CAL_REPORT_FIELDS)
    return out


def calendar_no_money(body: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /employees/{id}/calendar`` without pay information."""
    out = pick(body, CALENDAR_FIELDS)
    out["days"] = [_cal_day(d) for d in (body.get("days") or []) if isinstance(d, dict)]
    out["money_hidden"] = True
    return out

"""
SEC-02 (R20, Krum 06.11.2026) — who READS money. The registry of every guarded read.

Canon (locked; this is applying it, not a new business rule):

  * FLOW-002 "Обхват на правата": rights are role x scope (company / project / module /
    amount); "по-ограниченото право има предимство"; Viewer is not a canonical role.
  * ``app/permissions/catalog.py`` (the FLOW-002 catalog): Viewer reads only through
    project membership and grants nothing at company scope; Technician reaches a project
    only by membership; the Technical Manager is ``site_manager`` (FG-14).
  * FLOW-010: internal cost, margin, salaries and payments to subcontractors are for
    authorised internal roles only.
  * R20 (Krum, 06.11.2026, ``docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``):
    company finance only Owner/Admin/Accountant; the Technical Manager sees the budget of
    the project and of the SMR / SMR groups, the spent amount against it and the remainder
    — only on their own projects — and never profit, cost price, margin or client prices;
    Viewer, Technician, Driver, Warehousekeeper see no money (in the warehouse only
    quantities).

Rules (``rule`` column below):

  R20-1      company finance — Owner/Admin/Accountant only (403 for everyone else).
  R20-2      project money — Owner/Admin/Accountant only, on every project.
  R20-2B     project budget view (budget + spent + remaining) — Owner/Admin/Accountant
             everywhere; ``site_manager`` ONLY on a project they are a current member of
             (date-aware ``project_team.membership_filter``, SEC-R1); fields that carry
             client prices are removed for him (``EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS``).
  R20-5      shared screen: the response stays, the money values are removed for every
             caller without ``MONEY_VALUES_READ`` (FG-1 GET, FG-15 POST, all-reports,
             weekly matrix).

The decision in the three PERMISSION_SERVICE_MODEs is the W0-02 mechanism SEC-01 uses
(``app/permissions/money_write.py``): legacy role check in off/shadow, the Permission
Service with the catalog action in enforce.

FG-12 ("по-ограниченото право има предимство") — how SEC-02 applies it:

  1. off/shadow: the decision is the ONE legacy role of the session user
     (``users.role``); a user has no second role to combine.
  2. enforce: the Permission Service allows when ANY active assignment allows. SEC-02 makes
     sure a combination can never widen money reads: FINANCE_READ_ACTIONS and
     MONEY_VALUES_READ exist only on company-scope finance roles (Owner/Admin full set,
     Accountant); a project-scope assignment carries at most PROJECT_BUDGET_READ_ACTIONS,
     and only when the COMPANY role is ``site_manager``. So "site_manager + member of P"
     reads the budget of P and nothing else; "viewer + member of P" reads no money of P.
  3. Not done (needs Krum, FG-12 stays open for it): a NARROWER assignment cannot yet
     restrict a WIDER one (deny-overrides), e.g. a project-scope "read only" on P does not
     take money away from a company Accountant on P. The service has no deny assignment.

This module is pure data (no imports from the app) so the catalog can import it.
"""
from typing import Dict, FrozenSet, List, NamedTuple, Set

R20_1 = "R20-1"
R20_2 = "R20-2"
R20_2B = "R20-2B"
R20_5 = "R20-5"
R20_5M = "R20-5M"

RULE_TEXT: Dict[str, str] = {
    R20_1: "company finance: Owner/Admin/Accountant only",
    R20_2: "project money: Owner/Admin/Accountant only",
    R20_2B: "project budget view: Owner/Admin/Accountant; site_manager on own (member) "
            "projects, client prices removed",
    R20_5: "shared screen: money values removed without finance right",
    R20_5M: "mixed response (SEC-02-A, D1): money keys removed without finance right, "
            "quantities / statuses stay",
}

# Canon sources quoted in the HANDOFF table.
CANON_COMPANY = "R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010"
CANON_PAY = "R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay)"
CANON_PROJECT = "R20 (no profit / cost price / margin / client prices); FLOW-010"
CANON_BUDGET = "R20 (budget + spent + remaining on own projects); FLOW-002 membership"
CANON_SUBCONTRACT = "R20; FLOW-010 (payments to subcontractors)"
CANON_PRICING = "R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers)"
CANON_WAREHOUSE = "R20 (warehouse: quantities only); SEC-02 rule 4"
CANON_HIDE = "R20; SEC-02 rule 5 (hide the values on a shared screen); FG-1/FG-15"
CANON_D1 = "R20; FLOW-010; SEC-02 addendum A (D1: strip money, keep quantities/statuses)"
CANON_D1_ONLY = "R20; FLOW-010; SEC-02 addendum A (D1: the response is money only)"
CANON_D9 = "R20; FLOW-010; SEC-02 addendum A (D9: no-money file on own projects); rule 3"


class FinanceRead(NamedTuple):
    method: str
    path: str          # as served, with the /api prefix
    action: str        # catalog action (MONEY_VALUES_READ for R20-5)
    rule: str
    canon: str


MONEY_VALUES_READ = "finance.money_values.read"

_E = FinanceRead
FINANCE_READS: List[FinanceRead] = [
    # ── R20-1: company finance ───────────────────────────────────────────────
    _E("GET", "/api/billing/subscription", "finance.billing_subscription.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/billing/usage", "finance.billing_usage.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/cashflow/forecast", "finance.cashflow_forecast.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/cashflow/forecast/compact", "finance.cashflow_forecast_compact.read", R20_1, CANON_COMPANY),
    # SEC-02-A (D9): finance roles — the full file; SiteManager — the file WITHOUT money,
    # report lines / calendar of his current member projects only; others 403.
    _E("GET", "/api/employee-dossier/{worker_id}", "finance.employee_dossier.read", R20_2B, CANON_D9),
    _E("GET", "/api/employee-cost/{user_id}", "finance.employee_cost.read", R20_1, CANON_PAY),
    _E("GET", "/api/overhead-snapshots", "finance.overhead_snapshot.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/overhead-snapshots/aggregate", "finance.overhead_snapshot_aggregate.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/contract-payments", "finance.contract_payment.read", R20_1, CANON_PAY),
    _E("GET", "/api/invoice-lines", "finance.invoice_line.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/invoice-lines/unallocated", "finance.invoice_line_unallocated.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/invoice-lines/{line_id}", "finance.invoice_line_detail.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/invoice-lines/by-warehouse/{warehouse_id}", "finance.invoice_line_by_warehouse.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/invoice-lines/by-client/{client_id}", "finance.invoice_line_by_client.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/invoice-lines/by-purchaser/{user_id}", "finance.invoice_line_by_purchaser.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/fixed-expenses", "finance.fixed_expense.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/overhead/realtime", "finance.overhead_realtime.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/overhead/realtime/daily", "finance.overhead_realtime_daily.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/overhead/realtime/by-project", "finance.overhead_realtime_by_project.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/overhead/realtime/trend", "finance.overhead_realtime_trend.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/pay-runs", "finance.pay_run.read", R20_1, CANON_PAY),
    _E("GET", "/api/pay-runs/audit-check", "finance.pay_run_audit_check.read", R20_1, CANON_PAY),
    _E("GET", "/api/pay-runs/{run_id}", "finance.pay_run_detail.read", R20_1, CANON_PAY),
    _E("GET", "/api/pay-runs/{run_id}/history", "finance.pay_run_history.read", R20_1, CANON_PAY),
    _E("GET", "/api/pay-runs/{run_id}/allocations", "finance.pay_run_allocation.read", R20_1, CANON_PAY),
    _E("GET", "/api/payroll-weeks", "finance.payroll_week.read", R20_1, CANON_PAY),
    _E("GET", "/api/org/pnl-overview", "finance.org_pnl_overview.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/finance/cash-transactions", "finance.cash_transaction.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/finance/overhead-transactions", "finance.overhead_transaction.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/finance/bonus-payments", "finance.bonus_payment.read", R20_1, CANON_PAY),
    _E("GET", "/api/prices", "finance.purchase_price_history.read", R20_1, CANON_PRICING),
    _E("GET", "/api/reports/turnover-by-counterparty", "finance.turnover_by_counterparty.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/turnover-by-counterparty/{counterparty_id}/invoices", "finance.turnover_counterparty_invoices.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/turnover-by-client", "finance.turnover_by_client.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/company-finance-summary", "finance.company_finance_summary.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/company-finance-compare", "finance.company_finance_compare.read", R20_1, CANON_COMPANY),
    # export is a significant verb: a denial is audited in enforce.
    _E("GET", "/api/reports/company-finance-export", "finance.company_finance.export", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/company-finance-series", "finance.company_finance_series.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/finance-details/summary", "finance.finance_details_summary.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/finance-details/by-counterparty", "finance.finance_details_by_counterparty.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/finance-details/by-project", "finance.finance_details_by_project.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/finance-details/transactions", "finance.finance_details_transactions.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/reports/finance-details/top-counterparties", "finance.finance_details_top_counterparties.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/dashboard/pending-payments", "finance.pending_payment.read", R20_1, CANON_COMPANY),
    _E("GET", "/api/revenue-snapshots", "finance.revenue_snapshot.read", R20_1, CANON_PROJECT),
    _E("GET", "/api/revenue-snapshots/{snapshot_id}", "finance.revenue_snapshot_detail.read", R20_1, CANON_PROJECT),
    _E("GET", "/api/client-acts", "finance.client_act.read", R20_1, CANON_PROJECT),
    _E("GET", "/api/client-acts/{act_id}", "finance.client_act_detail.read", R20_1, CANON_PROJECT),
    _E("GET", "/api/execution-packages", "finance.execution_package.read", R20_1, CANON_PROJECT),
    _E("GET", "/api/subcontractor-payments", "finance.subcontractor_payment.read", R20_1, CANON_SUBCONTRACT),
    _E("GET", "/api/warehouse/value", "finance.warehouse_value.read", R20_1, CANON_WAREHOUSE),
    _E("GET", "/api/price-modifiers/org", "finance.org_price_modifier.read", R20_1, CANON_PRICING),
    _E("GET", "/api/pricing/material", "finance.material_price.read", R20_1, CANON_PRICING),
    _E("GET", "/api/pricing/history", "finance.material_price_history.read", R20_1, CANON_PRICING),
    _E("GET", "/api/pricing/catalog", "finance.material_price_catalog.read", R20_1, CANON_PRICING),
    # ── R20-2: project money, finance roles only ─────────────────────────────
    _E("GET", "/api/projects/{project_id}/centralized-reports", "finance.project_centralized_report.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/centralized-reports/finance", "finance.project_centralized_finance.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/centralized-reports/personnel", "finance.project_centralized_personnel.read", R20_2, CANON_PAY),
    _E("GET", "/api/projects/{project_id}/financial-results", "finance.project_financial_result.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/financial-results/breakdown", "finance.project_financial_result_breakdown.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/financial-alerts/{project_id}", "finance.project_financial_alert.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/project-net-profit/{project_id}", "finance.project_net_profit.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/project-risk/{project_id}", "finance.project_risk.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/pnl", "finance.project_pnl.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/pnl/summary", "finance.project_pnl_summary.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/pnl/breakdown", "finance.project_pnl_breakdown.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/pnl/trend", "finance.project_pnl_trend.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/projects/{project_id}/pnl/aggregated", "finance.project_pnl_aggregated.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/invoice-lines/by-project/{project_id}", "finance.invoice_line_by_project.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/labor-cost/by-project/{project_id}", "finance.project_labor_cost.read", R20_2, CANON_PAY),
    _E("GET", "/api/labor-cost/by-execution-package/{pkg_id}", "finance.package_labor_cost.read", R20_2, CANON_PAY),
    _E("GET", "/api/project-profit/{project_id}", "finance.project_profit.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/project-smr-view/{project_id}", "finance.project_smr_view.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/profit-by-period/{project_id}", "finance.project_profit_by_period.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/cash-vs-earned/{project_id}", "finance.project_cash_vs_earned.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/procurement-alerts/{project_id}", "finance.project_procurement_alert.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/execution-packages/financial-breakdown/{project_id}", "finance.package_financial_breakdown.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/execution-packages/{pkg_id}/net-financial", "finance.package_net_financial.read", R20_2, CANON_PROJECT),
    _E("GET", "/api/price-modifiers/project/{project_id}", "finance.project_price_modifier.read", R20_2, CANON_PRICING),
    _E("GET", "/api/price-modifiers/effective/{project_id}", "finance.effective_price_modifier.read", R20_2, CANON_PRICING),
    # ── R20-2B: the project budget view ─────────────────────────────────────
    _E("GET", "/api/projects/{project_id}/expected-actual", "finance.project_budget_vs_actual.read", R20_2B, CANON_BUDGET),
    _E("GET", "/api/projects/{project_id}/expected-actual/compact", "finance.project_budget_vs_actual_compact.read", R20_2B, CANON_BUDGET),
    _E("GET", "/api/projects/{project_id}/centralized-reports/activities", "finance.project_budget_burn.read", R20_2B, CANON_BUDGET),
    # ── R20-5: shared screens, values hidden ────────────────────────────────
    _E("GET", "/api/all-reports", MONEY_VALUES_READ, R20_5, CANON_HIDE),
    _E("GET", "/api/weekly-matrix", MONEY_VALUES_READ, R20_5, CANON_HIDE),
    _E("GET", "/api/labor-entries", MONEY_VALUES_READ, R20_5, CANON_HIDE + "; R16 (member projects)"),
    _E("POST", "/api/labor-entries", MONEY_VALUES_READ, R20_5, CANON_HIDE + "; R16"),
    # ── SEC-02 addendum A (D1): the remaining money GETs ─────────────────────
    # money only -> finance roles only
    _E("GET", "/api/ai-config/hourly-rates", "finance.worker_hourly_rate.read", R20_1, CANON_D1_ONLY),
    _E("GET", "/api/settings/sales-margins", "finance.sales_margin.read", R20_1, CANON_D1_ONLY),
    _E("GET", "/api/sales/history", "finance.sales_history.read", R20_1, CANON_D1_ONLY),
    _E("GET", "/api/clients/{client_id}/invoices", "finance.client_invoice.read", R20_1, CANON_D1_ONLY),
    _E("GET", "/api/subcontractor-acts", "finance.subcontractor_act.read", R20_1, CANON_D1_ONLY),
    _E("GET", "/api/projects/{project_id}/invoice-details", "finance.project_invoice_detail.read", R20_2, CANON_D1_ONLY),
    _E("GET", "/api/smr-analyses/{analysis_id}/export-excel", "finance.smr_analysis.export", R20_2, CANON_D1_ONLY + " (file)"),
    _E("GET", "/api/smr-analyses/{analysis_id}/lines/{line_id}/modifier-breakdown", "finance.smr_modifier_breakdown.read", R20_2, CANON_D1_ONLY),
    _E("GET", "/api/offers/{offer_id}/pdf", "finance.offer_document.export", R20_2, CANON_D1_ONLY + " (file)"),
    _E("GET", "/api/offers/{offer_id}/xlsx", "finance.offer_spreadsheet.export", R20_2, CANON_D1_ONLY + " (file)"),
    # mixed -> money keys removed for non-finance callers (strip_money_for_non_finance)
    _E("GET", "/api/subcontractor-packages", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/subcontractor-packages/{pkg_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/projects/{project_id}/dashboard", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/morning-briefing", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/morning-briefing/compact", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/budget-freezes/{project_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/budget-freezes/{project_id}/latest", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/progress-updates", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/progress-updates/{pkg_id}/latest", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/progress-updates/{pkg_id}/history", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/progress-comparison/{pkg_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/progress-warnings/{project_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/project-progress-summary/{project_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/material-entries", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/project-material-summary/{project_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/smr-analyses", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/smr-analyses/{analysis_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/smr-analyses/{analysis_id}/compare/{version}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/smr-analyses/{analysis_id}/diff/{version}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/offers", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/offers/{offer_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/offers/{offer_id}/versions", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/offers/{offer_id}/versions/{version_number}", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/offers/{offer_id}/events", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/extra-works", MONEY_VALUES_READ, R20_5M, CANON_D1),
    _E("GET", "/api/extra-works/{draft_id}", MONEY_VALUES_READ, R20_5M, CANON_D1),
]

# §5.2 endpoints that carry NO money and stay as they are (rule 3), with the reason.
NOT_MONEY: Dict[tuple, str] = {
    ("GET", "/api/dashboard/stats"): "project/user/attendance/report COUNTS only, no amount "
                                     "(app/routes/overhead.py get_dashboard_stats)",
    ("GET", "/api/worker-calendar"): "status / site / hours per worker-day, no amount "
                                     "(app/routes/overhead_realtime.py get_worker_calendar)",
    ("GET", "/api/billing/check-module/{module_code}"): "module entitlement yes/no, used by "
                                     "every screen; no amount",
}

FINANCE_READ_ACTIONS: Set[str] = {e.action for e in FINANCE_READS if e.rule in (R20_1, R20_2)}
# SEC-02-A (D9): the employee file is R20-2B-shaped (finance + SiteManager) but it is a
# COMPANY-scope read for the SiteManager (the worker, not a project, is the subject); its
# action is therefore a company action of finance + site_manager, see catalog.py.
EMPLOYEE_FILE_ACTION = "finance.employee_dossier.read"
PROJECT_BUDGET_READ_ACTIONS: Set[str] = {e.action for e in FINANCE_READS
                                         if e.rule == R20_2B and e.action != EMPLOYEE_FILE_ACTION}

# R20-2B: in expected-actual the SMR-GROUP and LOCATION "planned" amounts are summed from
# smr_analyses.lines[].final_total — the price TO THE CLIENT (markup + risk,
# app/routes/smr_analysis.py calc_line) — and the group "actual" is spread by that ratio.
# They are removed for a caller without MONEY_VALUES_READ. The per-SMR (activity) budget
# is activity_budgets.labor_budget — an internal budget — and stays.
EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS: FrozenSet[str] = frozenset(
    {"planned_cost", "actual_cost", "variance_cost", "status"})

# R20-5: the money keys removed from a shared response.
LABOR_MONEY_FIELDS: FrozenSet[str] = frozenset({"hourly_rate", "labor_cost"})
REPORT_LINE_MONEY_FIELDS: FrozenSet[str] = frozenset(
    {"hourly_rate", "labor_value", "earned_formula", "pay_type", "total_value"})
WEEKLY_MATRIX_MONEY_FIELDS: FrozenSet[str] = frozenset(
    {"pay_type", "hourly_rate", "labor_value", "net_pay", "value", "bonuses",
     "deductions"})


# ── SEC-02-A: which keys are money (R20-5M) ─────────────────────────────────
import re as _re

# A key is money when its name says price / cost / amount / value / margin / budget /
# pay / profit / revenue / VAT ...; quantities, hours, counts, ids, dates and statuses
# are not. Checked against the real responses in tests/test_sec_02_finance_read.py.
_MONEY_WORDS = _re.compile(
    r"(price|cost|amount|value|margin|markup|budget|profit|revenue|income|expense|"
    r"salary|wage|balance|subtotal|vat_|_vat|discount|earned|receivable|payable|payment|"
    r"paid|unpaid|_pay|pay_|^pay$|advance|bonus|deduction|overhead|(^|_)rates?($|_)|"
    r"logistics_pct|risk_pct|(^|_)eur($|_)|money|financ|total)")
_NOT_MONEY = _re.compile(
    r"(_qty$|^qty|_hours$|hours_|_count$|^count|_id$|_ids$|_at$|_date$|_status$|_number$|"
    r"_no$|^total_(hours|qty|count|pages|rows|lines|entries|workers|employees|packages|"
    r"items|days|planned_rows|returned_qty|issued_qty|certified_qty|qty_in_stock)$|"
    r"^(days_total|vat_number|is_vat_registered|payroll_status|has_consumption_data|"
    r"partial_cost_data|paid_hours|progress_rate|completion_rate|attendance_rate|"
    r"burn_rate_hours|pay_type_label|money_hidden|client_price_fields_hidden)$|"
    r"_pct_complete$|percent_complete)")
# A pagination "total" (sibling of items/page) is a count, not money.
_PAGINATION_KEYS = {"items", "page", "page_size", "total_pages"}


def is_money_key(key: str, siblings=(), keep=()) -> bool:
    if key in keep:
        return False
    k = key.lower()
    if k == "total" and _PAGINATION_KEYS & set(siblings):
        return False
    return bool(_MONEY_WORDS.search(k)) and not _NOT_MONEY.search(k)


def strip_money(value, keep=()):
    """A copy of a JSON-like value with every money key removed, at any depth.

    ``keep``: key names that are NOT money in this one response (e.g. a ``total`` that
    counts warnings), declared next to the route."""
    if isinstance(value, dict):
        keys = list(value)
        return {k: strip_money(v, keep) for k, v in value.items()
                if not (isinstance(k, str) and is_money_key(k, keys, keep))}
    if isinstance(value, list):
        return [strip_money(v, keep) for v in value]
    return value


def by_route() -> Dict[tuple, FinanceRead]:
    return {(e.method, e.path): e for e in FINANCE_READS}

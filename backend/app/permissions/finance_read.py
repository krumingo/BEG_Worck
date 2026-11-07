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
import re as _re
from typing import Dict, FrozenSet, List, NamedTuple, Set

R20_1 = "R20-1"
R20_2 = "R20-2"
R20_2B = "R20-2B"
R20_5 = "R20-5"
R20_5M = "R20-5M"
R20_5B = "R20-5B"

RULE_TEXT: Dict[str, str] = {
    R20_1: "company finance: Owner/Admin/Accountant only",
    R20_2: "project money: Owner/Admin/Accountant only",
    R20_2B: "project budget view: Owner/Admin/Accountant; site_manager on own (member) "
            "projects, client prices removed",
    R20_5: "shared screen: money values removed without finance right",
    R20_5M: "mixed response (SEC-02-A, D1): money keys removed without finance right, "
            "quantities / statuses stay",
    R20_5B: "project budget screen (SEC-02-B, FG-43): finance roles everything; SiteManager "
            "member budget + spent + remaining without client/subcontractor prices; other "
            "members no money",
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
CANON_B = "R20; FLOW-037 §3.4; FLOW-010; SEC-02 addendum B (SEC02-1 / FG-41 / FG-42)"
CANON_B43 = "R20 (budget + spent + remaining on own projects); SEC-02 addendum B (FG-43)"
CANON_PLAN = "R20; FLOW-050 (subscription price: Owner/Admin); SEC-02 addendum B"
SUBSCRIPTION_PRICE_READ = "finance.subscription_price.read"
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
    # ── SEC-02 addendum B (audit SEC02-1, FLOW Guard FG-41/42/43) ────────────────
    _E("GET", "/api/work-sessions", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/work-sessions/summary", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/work-sessions/overtime", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/work-sessions/{session_id}/detail", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/projects/{project_id}/site-workers", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/projects/{project_id}/smr-groups", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/projects/{project_id}/smr-groups/tree", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/pulse/today", MONEY_VALUES_READ, R20_5B, CANON_B43 + "; R31 (no per-worker money); B-D2"),
    _E("GET", "/api/pulse/summary", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/sites/{site_id}/pulse", MONEY_VALUES_READ, R20_5B, CANON_B43 + "; R31 (no per-worker money); B-D2"),
    _E("GET", "/api/sites/{site_id}/pulse/range", MONEY_VALUES_READ, R20_5B, CANON_B43 + "; R31 (no per-worker money); B-D2"),
    # SEC-02-E (audit SEC02D-1): the pulse generators
    _E("POST", "/api/sites/{site_id}/pulse/generate", "finance.site_pulse_generate.execute", R20_2B,
       CANON_BUDGET + "; R31; audit SEC02D-1 (response = the pulse view)"),
    _E("POST", "/api/pulse/generate-all", "finance.pulse_generate_all.execute", R20_1,
       CANON_COMPANY + "; audit SEC02D-1 (regenerates every site's stored pulse)"),
    # SEC-02-E: the POST/PUT sweep (tools/sec02_money_scan_post.py) — routes that answered a
    # non-finance role with money. Money computations / money documents -> finance only.
    _E("POST", "/api/price-modifiers/calculate", "finance.price_modifier_calculation.execute", R20_1, CANON_PRICING + "; SEC-02-E sweep"),
    _E("POST", "/api/resource-model/worker-cost-preview", "finance.worker_cost_preview.execute", R20_1, CANON_PAY + "; SEC-02-E sweep"),
    _E("POST", "/api/resource-model/subcontractor-burden-preview", "finance.subcontractor_burden_preview.execute", R20_1, CANON_SUBCONTRACT + "; SEC-02-E sweep"),
    _E("POST", "/api/smr-analyses/{analysis_id}/recalculate", "finance.smr_analysis_recalculation.execute", R20_2, CANON_PRICING + "; SEC-02-E sweep"),
    _E("POST", "/api/smr-analyses/{analysis_id}/recalculate-with-modifiers", "finance.smr_analysis_modifier_recalculation.execute", R20_2, CANON_PRICING + "; SEC-02-E sweep"),
    _E("POST", "/api/smr-analyses/from-offer/{offer_id}", "finance.smr_analysis_from_offer.execute", R20_2, CANON_PRICING + "; SEC-02-E sweep"),
    _E("POST", "/api/revenue-snapshots/from-offer/{offer_id}", "finance.revenue_snapshot_from_offer.execute", R20_2, CANON_PROJECT + "; SEC-02-E sweep"),
    _E("POST", "/api/client-acts/from-offer/{offer_id}", "finance.client_act_from_offer.execute", R20_2, CANON_PROJECT + "; SEC-02-E sweep; SEC-01-C02-D4"),
    _E("PUT", "/api/client-acts/{act_id}", "finance.client_act.update", R20_2, CANON_PROJECT + "; SEC-02-E sweep; SEC-01-C02-D4"),
    _E("PUT", "/api/execution-packages/{pkg_id}", "finance.execution_package.update", R20_2, CANON_PROJECT + "; SEC-02-E sweep; SEC-01-C02-D4"),
    # budget writes: finance + the Technical Manager on his project (budgets only in the answer)
    _E("POST", "/api/budget-freezes/{project_id}", "finance.budget_freeze.execute", R20_2B, CANON_BUDGET + "; SEC-02-E sweep"),
    # mixed answers -> money stripped, the route keeps its own rule
    _E("POST", "/api/extra-works/ai-proposal", MONEY_VALUES_READ, R20_5M, CANON_D1 + "; SEC-02-E sweep"),
    _E("POST", "/api/projects/{project_id}/activity-budgets/calculate-all-snapshots", MONEY_VALUES_READ, R20_5M, CANON_PAY + "; SEC-02-E sweep (avg daily wage)"),
    _E("POST", "/api/projects/{project_id}/activity-budgets/{budget_id}/calculate-snapshot", MONEY_VALUES_READ, R20_5M, CANON_PAY + "; SEC-02-E sweep"),
    _E("POST", "/api/offers/{offer_id}/send", MONEY_VALUES_READ, R20_5M, CANON_D1 + "; SEC-02-E sweep"),
    _E("PUT", "/api/offers/{offer_id}", MONEY_VALUES_READ, R20_5M, CANON_D1 + "; SEC-02-E sweep"),
    _E("POST", "/api/warehouse/batches", MONEY_VALUES_READ, R20_5M, CANON_WAREHOUSE + "; SEC-02-E sweep (echo of the entered unit cost)"),
    _E("GET", "/api/ocr-invoice", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/projects/{project_id}/activity-reports/{smr_type}", MONEY_VALUES_READ, R20_5M, CANON_B),
    _E("GET", "/api/labor-warnings/{project_id}", MONEY_VALUES_READ, R20_5M,
       CANON_B + "; non-finance: current member projects only"),
    _E("GET", "/api/material-warnings/{project_id}", MONEY_VALUES_READ, R20_5M,
       CANON_B + "; SEC-02-G (SEC71-03): money in the warning text"),
    # SEC-02-G (FLOW Guard FG-111): alarm events carry "бюджет 900.0% изхарчен" + metric_value
    _E("GET", "/api/alarms", MONEY_VALUES_READ, R20_5M, CANON_B + "; FG-111"),
    _E("GET", "/api/alarms/dashboard", MONEY_VALUES_READ, R20_5M, CANON_B + "; FG-111"),
    _E("GET", "/api/alarms/{event_id}", MONEY_VALUES_READ, R20_5M, CANON_B + "; FG-111"),
    _E("PUT", "/api/alarms/{event_id}/acknowledge", MONEY_VALUES_READ, R20_5M,
       CANON_B + "; FG-111 (answer is the event)"),
    _E("PUT", "/api/alarms/{event_id}/resolve", MONEY_VALUES_READ, R20_5M,
       CANON_B + "; FG-111 (answer is the event)"),
    _E("POST", "/api/alarms/evaluate", MONEY_VALUES_READ, R20_5M,
       CANON_B + "; FG-111 (answer lists the new events)"),
    _E("GET", "/api/projects/{project_id}/activities-overview", MONEY_VALUES_READ, R20_5B, CANON_B43),
    _E("GET", "/api/projects/{project_id}/activity-budget-summary", MONEY_VALUES_READ, R20_5B,
       CANON_B43 + "; Accountant on every project"),
    _E("GET", "/api/subscription", SUBSCRIPTION_PRICE_READ, R20_5, CANON_PLAN),
    # found by the re-run of the audit scanner (tools/sec02_money_scan.py)
    _E("GET", "/api/projects/{project_id}/activity-budgets", MONEY_VALUES_READ, R20_5B,
       CANON_B43 + "; closes SEC-02-D4 (Viewer/Technician/Driver members saw the budget)"),
    _E("GET", "/api/projects/{project_id}/budget-health", MONEY_VALUES_READ, R20_5B, CANON_B43),
    _E("GET", "/api/warehouse/batches", MONEY_VALUES_READ, R20_5M, CANON_WAREHOUSE + "; addendum B"),
    _E("GET", "/api/warehouse/batches/{batch_id}", MONEY_VALUES_READ, R20_5M, CANON_WAREHOUSE + "; addendum B"),
    _E("GET", "/api/warehouse/items/{item_id}/batches", MONEY_VALUES_READ, R20_5M, CANON_WAREHOUSE + "; addendum B"),
    _E("GET", "/api/warehouse/items/{item_id}/stock-summary", MONEY_VALUES_READ, R20_5M, CANON_WAREHOUSE + "; addendum B"),
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

# SEC-02-B: hits of the audit scanner judged NOT company money (kept, with the reason).
SCAN_JUDGED_NOT_MONEY: Dict[str, str] = {
    "/api/billing/plans": "the public BEG_Work plan price list (the signup page shows it); "
                          "not the tenant's money",
    "/api/organization": "vat_percent — the tax RATE of the company, no amount",
    "/api/projects/{project_id}/invoice-context": "default_vat_rate — a tax rate, no amount",
    "POST /api/supplier-invoices": "vat_percent — the tax RATE echoed from the caller's own "
                                   "input; no amount",
}
# SEC-02-B: a role reading ITS OWN record (FLOW-037 §3.4 forbids other people's pay only).
SCAN_OWN_RECORD_PATHS = {"/api/employees/{user_id}", "/api/employees/{user_id}/dashboard"}

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

# R20-5B (FG-43): what the Technical Manager does NOT see on his budget screens.
BUDGET_VIEW_HIDDEN_FIELDS: FrozenSet[str] = frozenset(
    {"subcontractor_price", "sale_total", "final_total", "unit_price", "total_price",
     "margin", "profit", "planned_margin", "total_sale"})
# SEC-02-G (Codex SEC71-01): the budget view never carries a client price, sale, margin,
# profit, revenue, markup or commission under ANY key name — the set above plus this
# pattern. Used to project the response and by the scanners / tests on every
# allowed_budget_view route.
BUDGET_VIEW_FORBIDDEN = _re.compile(
    r"(sale|price|margin|profit|revenue|markup|commission|final_total)", _re.I)


def budget_view_forbidden(key) -> bool:
    return isinstance(key, str) and (key in BUDGET_VIEW_HIDDEN_FIELDS
                                     or bool(BUDGET_VIEW_FORBIDDEN.search(key)))


def without_budget_view_forbidden(value):
    """A copy of ``value`` without any key the budget view must not carry, at any depth.
    SEC-02-G (SEC71-03): nor any amount / percent inside an alert text."""
    if isinstance(value, dict):
        return money_free_alert({k: without_budget_view_forbidden(v) for k, v in value.items()
                                 if not budget_view_forbidden(k)})
    if isinstance(value, list):
        return [without_budget_view_forbidden(v) for v in value]
    return value
# /api/subscription: the plan price — Owner/Admin only.
SUBSCRIPTION_PRICE_FIELDS: FrozenSet[str] = frozenset({"plan_price", "price"})

# R20-5: the money keys removed from a shared response.
LABOR_MONEY_FIELDS: FrozenSet[str] = frozenset({"hourly_rate", "labor_cost"})
REPORT_LINE_MONEY_FIELDS: FrozenSet[str] = frozenset(
    {"hourly_rate", "labor_value", "earned_formula", "pay_type", "total_value"})
WEEKLY_MATRIX_MONEY_FIELDS: FrozenSet[str] = frozenset(
    {"pay_type", "hourly_rate", "labor_value", "net_pay", "value", "bonuses",
     "deductions"})


# ── SEC-02-A: which keys are money (R20-5M) ─────────────────────────────────

# A key is money when its name says price / cost / amount / value / margin / budget /
# pay / profit / revenue / VAT ...; quantities, hours, counts, ids, dates and statuses
# are not. Checked against the real responses in tests/test_sec_02_finance_read.py.
_MONEY_WORDS = _re.compile(
    r"(price|cost|amount|value|margin|markup|budget|profit|revenue|income|expense|"
    r"salary|wage|balance|subtotal|vat_|_vat|discount|earned|receivable|payable|payment|"
    r"paid|unpaid|_pay|pay_|^pay$|advance|bonus|deduction|overhead|(^|_)rates?($|_)|"
    r"logistics_pct|risk_pct|(^|_)eur($|_)|money|financ|total|spent|(^|_)remaining$|"
    r"(^|_)salary)")
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
    counts warnings), declared next to the route.
    SEC-02-G (SEC71-03): alert / warning texts lose their amounts too (``money_free_alert``)."""
    if isinstance(value, dict):
        keys = list(value)
        return money_free_alert({k: strip_money(v, keep) for k, v in value.items()
                                 if not (isinstance(k, str) and is_money_key(k, keys, keep))})
    if isinstance(value, list):
        return [strip_money(v, keep) for v in value]
    return value


# ── SEC-02-G (Codex SEC71-03 [P1]; R20, R31 FLOW-037 §3.4): money inside TEXT ─────────────
# An alert such as "Надхвърлен бюджет! (900.0%)" next to a visible budget gives the spent
# amount — on a one-worker day, his pay. A caller without the finance right gets ONE
# generic budget alert instead of any money alert: no amount, no percent, and the same
# type / severity / text whichever threshold fired (>80 % or >100 %, over budget or not).
MONEY_ALERT_TYPES: FrozenSet[str] = frozenset({
    "budget_warning", "budget_overrun", "budget_burn_high",           # pulse, progress
    "over_labor_budget", "over_material_budget", "missing_material_budget",
    "labor_ahead_of_progress", "materials_ahead_of_progress", "progress_lag",
    "loan", "client_receivable"})
GENERIC_BUDGET_ALERT = {"type": "budget_attention", "severity": "warning",
                        "message": "Бюджетът изисква внимание — подробности при финансите"}
# the safety net for any other text: a number followed by a percent or a currency
MONEY_TEXT = _re.compile(r"\d\s*(%|eur\b|€|лв|bgn\b|usd\b|\$)", _re.I)
_TEXT_KEYS = ("message", "text", "title", "detail", "description", "label")


# SEC-02-G (FLOW Guard FG-111, addendum E): an alarm event (app.services.alarm_engine) —
# "<обект>: бюджет 900.0% изхарчен" + context.metric_value / threshold. Without the finance
# right: no metric_value / threshold / details for ANY alarm; a money alarm type gets the
# generic text, a generic rule name (an admin's name may hold the threshold) and one
# severity (two rules at 80 % / 100 % would tell the band).
MONEY_ALARM_TYPES: FrozenSet[str] = frozenset(
    {"budget", "overhead", "pricing", "procurement", "custom"})
GENERIC_ALARM_RULE_NAME = "Бюджетна аларма"
_ALARM_CONTEXT_HIDDEN = ("metric_value", "threshold", "details")


def _is_alarm_event(d: dict) -> bool:
    return "rule_id" in d and "triggered_at" in d


def money_free_alarm(d: dict) -> dict:
    out = dict(d)
    if isinstance(out.get("context"), dict):
        out["context"] = {k: v for k, v in out["context"].items()
                          if k not in _ALARM_CONTEXT_HIDDEN}
    if out.get("type") in MONEY_ALARM_TYPES:
        out.update({"message": GENERIC_BUDGET_ALERT["message"], "severity": "warning",
                    "rule_name": GENERIC_ALARM_RULE_NAME})
    elif isinstance(out.get("message"), str) and MONEY_TEXT.search(out["message"]):
        out["message"] = "Има предупреждение — подробности при финансите"
    return out


def money_free_alert(d: dict) -> dict:
    """``d`` itself when it is no alert with money; else the money-free alert."""
    if not isinstance(d, dict):
        return d
    if _is_alarm_event(d):
        return money_free_alarm(d)
    texts = [k for k in _TEXT_KEYS if isinstance(d.get(k), str)]
    if not texts:
        return d
    if d.get("type") in MONEY_ALERT_TYPES:
        out = {k: v for k, v in d.items()
               if k not in texts and k not in ("type", "severity")
               and not isinstance(v, (int, float))}
        out.update(GENERIC_BUDGET_ALERT)
        return out
    if any(MONEY_TEXT.search(d[k]) for k in texts):
        return {**d, **{k: "Има предупреждение — подробности при финансите"
                        for k in texts if MONEY_TEXT.search(d[k])}}
    return d


def without_money_text(value):
    """``money_free_alert`` at any depth (for views that keep budget keys)."""
    if isinstance(value, dict):
        return money_free_alert({k: without_money_text(v) for k, v in value.items()})
    if isinstance(value, list):
        return [without_money_text(v) for v in value]
    return value


# ── SEC-02-D (audit SEC02C-1; R31, FLOW-037 §3.4): no per-worker pay by derivation ──
# In a response that carries money for the Technical Manager:
#   * no per-worker identity / hours (``workers`` lists, ``workers_count``);
#   * a per-SMR "spent" (actual / spent / cost / variance / remaining / burn) is shown only
#     when EVERY SMR row of that list has 2+ workers — one single-worker row would give
#     that worker's pay directly, or as the project total minus the other rows;
#   * a project-level "spent" only when the project has 2+ workers.
# Budget / planned amounts stay (they are not anyone's pay).
_ACTUAL = _re.compile(r"(actual|spent|cost|variance|remaining|burn|labor_value|"
                      r"clean_labor|overrun|_pct$|percent)")
_PLANNED = _re.compile(r"(planned|budget|^name$|_name$|^type$|subtype|smr_type|category|"
                       r"activity|status|unit$|qty|hours|count$|is_extra|source|id$)")
_ROW_NAME_KEYS = ("smr_type", "smr_type_id", "type", "name", "activity_name", "category")
WORKER_DETAIL_KEYS = frozenset({"workers", "workers_count", "worker_ids", "personnel",
                                "by_worker"})


def _norm(v) -> str:
    return (str(v) if v is not None else "").lower().strip()


def _is_actual(key: str) -> bool:
    k = key.lower()
    return bool(_ACTUAL.search(k)) and not _PLANNED.search(k)


def _drop_actual(d: dict) -> dict:
    return {k: v for k, v in d.items() if not (isinstance(k, str) and _is_actual(k))}


def r31_view(value, workers_by_smr: Dict[str, set], project_workers: int):
    """SEC-02-D: the Technical Manager's budget view with nothing that gives one worker's
    pay. ``workers_by_smr``: normalized SMR name -> distinct worker ids of the project;
    ``project_workers``: distinct workers of the project."""
    # SEC-02-G: fewer than 2 COUNTED (paid) workers — 0 included: a source may list an SMR
    # whose only paid worker is not attributable to it (pulse, multi-SMR workers)
    single = {k for k, v in workers_by_smr.items() if len(v) <= 1}

    def walk(v):
        if isinstance(v, list):
            rows = [x for x in v if isinstance(x, dict)]
            names = {_norm(r.get(k)) for r in rows for k in _ROW_NAME_KEYS if r.get(k)}
            # one single-worker SMR row -> no row of the list keeps its "spent" (else
            # the project total minus the other rows would still give it)
            hide = bool(names & single) or any(
                isinstance(r.get("workers_count"), int) and r["workers_count"] <= 1
                for r in rows)                       # the row itself says: one worker
            out = []
            for x in v:
                y = walk(x)
                if hide and isinstance(y, dict):
                    y = _drop_actual(y)
                out.append(y)
            return out
        if isinstance(v, dict):
            d = {k: walk(x) for k, x in v.items() if k not in WORKER_DETAIL_KEYS}
            is_row = any(d.get(k) for k in _ROW_NAME_KEYS)
            if not is_row and project_workers <= 1:
                d = _drop_actual(d)                    # project-level total of ONE worker
            return d
        return v
    return walk(value)


def by_route() -> Dict[tuple, FinanceRead]:
    return {(e.method, e.path): e for e in FINANCE_READS}

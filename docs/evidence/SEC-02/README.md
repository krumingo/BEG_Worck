# SEC-02 — четене на пари според канона (FLOW-002, FLOW-010, Р20)

> Пакет: `docs/architecture/tasks/SEC-02_FINANCE_READ_PER_CANON.md` (клон `claude/happy-meitner-bmcnel` @ `731da89`), с добавката за Р20 и FLOW Guard FG-1 (GET), FG-12, FG-14, FG-15.
> Решение Р20 (Крум, 06.11.2026) — `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`.
> Канон: FLOW-002 (роля × обхват; „по-ограниченото право има предимство“), `backend/app/permissions/catalog.py` (Viewer чете само през членство, на ниво фирма — нищо; Технически ръководител = `site_manager`), FLOW-010 (себестойност, марж, заплати, плащания към подизпълнители — само за упълномощени вътрешни роли).
> Доказателство за дупката: PM-01 §5.2 (Viewer без членство чете финанси с 200).
> База: PR #69 @ `471eaaa` (SEC-01 … SEC-01-C02 + SEC-R1). Преизползвани са `require_money_write` и датираното `project_team.membership_filter` от #69 — нищо не е дублирано. Без миграция, без промяна на данни.

## Правилата (един регистър)

Всеки охранен read е ред в `backend/app/permissions/finance_read.py` (endpoint → действие → правило → източник). Каталогът (`catalog.py`) взима действията оттам.

| Правило | Кой | Как, в трите режима |
|---|---|---|
| **R20-1** финанси на фирмата | Owner/Admin/Accountant; всички други 403 | `require_finance_read` = `require_money_write` с read действие: в off/shadow — legacy ролята; в enforce — Permission Service, company scope |
| **R20-2** пари на обекта | Owner/Admin/Accountant на всеки обект; **SiteManager, Technician, Viewer, Driver — 403 и като членове** | същото |
| **R20-2B** бюджет на обекта (бюджет + изхарчено + остатък по СМР) | финансовите роли навсякъде; **SiteManager само на обект, където е член днес** (датирано членство, SEC-R1); Technician/Viewer/Driver — 403 | `require_project_budget_read` = R16 зависимостта на #69 с `member_roles=("SiteManager",)`; в enforce — действието е само в проектното назначение на `site_manager` |
| **R20-5** общ екран, стойностите се скриват | всеки, който стига до екрана, както досега; парите — само финансовите роли | `money_values_visible`: в off/shadow — legacy ролята; в enforce — `finance.money_values.read` от Permission Service |
| правило 3 (без пари) | без промяна | `GET /api/dashboard/stats` (само бройки), `GET /api/worker-calendar` (статус/часове), `GET /api/billing/check-module/{code}` (да/не за модул) |

Съседни правила в кода, на които стъпва R20-1/2: `routes/finance.py:36` (`finance_permission`), `routes/hr.py:30` (`payroll_permission`), `routes/project_pnl.py` `/org/pnl-attribution` (Admin/Owner/Accountant), `routes/overhead_realtime.py` `PUT /fixed-expenses` (Admin/Owner/Accountant). Съседен екран за R20-2B: `routes/activity_budgets.py` `GET /projects/{id}/activity-budgets` — бюджетите по СМР вече се четат от член на обекта.

### Таблица endpoint → правило → източник

| # | Endpoint | Rule | Action | Canon source | Code |
|---:|---|---|---|---|---|
| 1 | `GET /api/billing/subscription` | R20-1 | `finance.billing_subscription.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/billing.py:762` |
| 2 | `GET /api/billing/usage` | R20-1 | `finance.billing_usage.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/billing.py:950` |
| 3 | `GET /api/cashflow/forecast` | R20-1 | `finance.cashflow_forecast.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/cashflow_forecast.py:14` |
| 4 | `GET /api/cashflow/forecast/compact` | R20-1 | `finance.cashflow_forecast_compact.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/cashflow_forecast.py:22` |
| 5 | `GET /api/employee-dossier/{worker_id}` | R20-1 | `finance.employee_dossier.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/employee_dossier.py:36` |
| 6 | `GET /api/employee-cost/{user_id}` | R20-1 | `finance.employee_cost.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/full_cost.py:36` |
| 7 | `GET /api/overhead-snapshots` | R20-1 | `finance.overhead_snapshot.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/full_cost.py:139` |
| 8 | `GET /api/overhead-snapshots/aggregate` | R20-1 | `finance.overhead_snapshot_aggregate.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/full_cost.py:150` |
| 9 | `GET /api/contract-payments` | R20-1 | `finance.contract_payment.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/hr.py:857` |
| 10 | `GET /api/invoice-lines` | R20-1 | `finance.invoice_line.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:219` |
| 11 | `GET /api/invoice-lines/unallocated` | R20-1 | `finance.invoice_line_unallocated.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:271` |
| 12 | `GET /api/invoice-lines/{line_id}` | R20-1 | `finance.invoice_line_detail.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:469` |
| 13 | `GET /api/invoice-lines/by-warehouse/{warehouse_id}` | R20-1 | `finance.invoice_line_by_warehouse.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:731` |
| 14 | `GET /api/invoice-lines/by-client/{client_id}` | R20-1 | `finance.invoice_line_by_client.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:807` |
| 15 | `GET /api/invoice-lines/by-purchaser/{user_id}` | R20-1 | `finance.invoice_line_by_purchaser.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/invoice_lines.py:891` |
| 16 | `GET /api/fixed-expenses` | R20-1 | `finance.fixed_expense.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/overhead_realtime.py:218` |
| 17 | `GET /api/overhead/realtime` | R20-1 | `finance.overhead_realtime.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/overhead_realtime.py:253` |
| 18 | `GET /api/overhead/realtime/daily` | R20-1 | `finance.overhead_realtime_daily.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/overhead_realtime.py:261` |
| 19 | `GET /api/overhead/realtime/by-project` | R20-1 | `finance.overhead_realtime_by_project.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/overhead_realtime.py:270` |
| 20 | `GET /api/overhead/realtime/trend` | R20-1 | `finance.overhead_realtime_trend.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/overhead_realtime.py:279` |
| 21 | `GET /api/pay-runs` | R20-1 | `finance.pay_run.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1061` |
| 22 | `GET /api/pay-runs/audit-check` | R20-1 | `finance.pay_run_audit_check.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1087` |
| 23 | `GET /api/pay-runs/{run_id}` | R20-1 | `finance.pay_run_detail.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1164` |
| 24 | `GET /api/pay-runs/{run_id}/history` | R20-1 | `finance.pay_run_history.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1632` |
| 25 | `GET /api/pay-runs/{run_id}/allocations` | R20-1 | `finance.pay_run_allocation.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1652` |
| 26 | `GET /api/payroll-weeks` | R20-1 | `finance.payroll_week.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/pay_runs.py:1870` |
| 27 | `GET /api/org/pnl-overview` | R20-1 | `finance.org_pnl_overview.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/project_pnl.py:80` |
| 28 | `GET /api/finance/cash-transactions` | R20-1 | `finance.cash_transaction.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:921` |
| 29 | `GET /api/finance/overhead-transactions` | R20-1 | `finance.overhead_transaction.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:982` |
| 30 | `GET /api/finance/bonus-payments` | R20-1 | `finance.bonus_payment.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/reports.py:1039` |
| 31 | `GET /api/prices` | R20-1 | `finance.purchase_price_history.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/reports.py:28` |
| 32 | `GET /api/reports/turnover-by-counterparty` | R20-1 | `finance.turnover_by_counterparty.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:162` |
| 33 | `GET /api/reports/turnover-by-counterparty/{counterparty_id}/invoices` | R20-1 | `finance.turnover_counterparty_invoices.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:299` |
| 34 | `GET /api/reports/turnover-by-client` | R20-1 | `finance.turnover_by_client.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:353` |
| 35 | `GET /api/reports/company-finance-summary` | R20-1 | `finance.company_finance_summary.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:531` |
| 36 | `GET /api/reports/company-finance-compare` | R20-1 | `finance.company_finance_compare.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:817` |
| 37 | `GET /api/reports/company-finance-export` | R20-1 | `finance.company_finance.export` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/reports.py:1105` |
| 38 | `GET /api/reports/company-finance-series` | R20-1 | `finance.company_finance_series.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:302` |
| 39 | `GET /api/reports/finance-details/summary` | R20-1 | `finance.finance_details_summary.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:466` |
| 40 | `GET /api/reports/finance-details/by-counterparty` | R20-1 | `finance.finance_details_by_counterparty.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:590` |
| 41 | `GET /api/reports/finance-details/by-project` | R20-1 | `finance.finance_details_by_project.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:677` |
| 42 | `GET /api/reports/finance-details/transactions` | R20-1 | `finance.finance_details_transactions.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:767` |
| 43 | `GET /api/reports/finance-details/top-counterparties` | R20-1 | `finance.finance_details_top_counterparties.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:924` |
| 44 | `GET /api/dashboard/pending-payments` | R20-1 | `finance.pending_payment.read` | R20; FLOW-002 (catalog.py: Viewer grants nothing at company scope); FLOW-010 | `app/routes/dashboard.py:27` |
| 45 | `GET /api/revenue-snapshots` | R20-1 | `finance.revenue_snapshot.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_snapshot.py:88` |
| 46 | `GET /api/revenue-snapshots/{snapshot_id}` | R20-1 | `finance.revenue_snapshot_detail.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_snapshot.py:99` |
| 47 | `GET /api/client-acts` | R20-1 | `finance.client_act.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_expense.py:121` |
| 48 | `GET /api/client-acts/{act_id}` | R20-1 | `finance.client_act_detail.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_expense.py:134` |
| 49 | `GET /api/execution-packages` | R20-1 | `finance.execution_package.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_expense.py:406` |
| 50 | `GET /api/subcontractor-payments` | R20-1 | `finance.subcontractor_payment.read` | R20; FLOW-010 (payments to subcontractors) | `app/routes/subcontractors.py:602` |
| 51 | `GET /api/warehouse/value` | R20-1 | `finance.warehouse_value.read` | R20 (warehouse: quantities only); SEC-02 rule 4 | `app/routes/warehouse_batches.py:175` |
| 52 | `GET /api/price-modifiers/org` | R20-1 | `finance.org_price_modifier.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/price_modifiers.py:41` |
| 53 | `GET /api/pricing/material` | R20-1 | `finance.material_price.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/pricing.py:31` |
| 54 | `GET /api/pricing/history` | R20-1 | `finance.material_price_history.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/pricing.py:61` |
| 55 | `GET /api/pricing/catalog` | R20-1 | `finance.material_price_catalog.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/pricing.py:83` |
| 56 | `GET /api/projects/{project_id}/centralized-reports` | R20-2 | `finance.project_centralized_report.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/centralized_reports.py:14` |
| 57 | `GET /api/projects/{project_id}/centralized-reports/finance` | R20-2 | `finance.project_centralized_finance.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/centralized_reports.py:44` |
| 58 | `GET /api/projects/{project_id}/centralized-reports/personnel` | R20-2 | `finance.project_centralized_personnel.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/centralized_reports.py:34` |
| 59 | `GET /api/projects/{project_id}/financial-results` | R20-2 | `finance.project_financial_result.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/financial_results.py:14` |
| 60 | `GET /api/projects/{project_id}/financial-results/breakdown` | R20-2 | `finance.project_financial_result_breakdown.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/financial_results.py:24` |
| 61 | `GET /api/financial-alerts/{project_id}` | R20-2 | `finance.project_financial_alert.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/full_cost.py:423` |
| 62 | `GET /api/project-net-profit/{project_id}` | R20-2 | `finance.project_net_profit.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/full_cost.py:337` |
| 63 | `GET /api/project-risk/{project_id}` | R20-2 | `finance.project_risk.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/full_cost.py:481` |
| 64 | `GET /api/projects/{project_id}/pnl` | R20-2 | `finance.project_pnl.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/project_pnl.py:21` |
| 65 | `GET /api/projects/{project_id}/pnl/summary` | R20-2 | `finance.project_pnl_summary.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/project_pnl.py:32` |
| 66 | `GET /api/projects/{project_id}/pnl/breakdown` | R20-2 | `finance.project_pnl_breakdown.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/project_pnl.py:58` |
| 67 | `GET /api/projects/{project_id}/pnl/trend` | R20-2 | `finance.project_pnl_trend.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/project_pnl.py:70` |
| 68 | `GET /api/projects/{project_id}/pnl/aggregated` | R20-2 | `finance.project_pnl_aggregated.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/project_pnl.py:124` |
| 69 | `GET /api/invoice-lines/by-project/{project_id}` | R20-2 | `finance.invoice_line_by_project.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/invoice_lines.py:645` |
| 70 | `GET /api/labor-cost/by-project/{project_id}` | R20-2 | `finance.project_labor_cost.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/revenue_expense.py:263` |
| 71 | `GET /api/labor-cost/by-execution-package/{pkg_id}` | R20-2 | `finance.package_labor_cost.read` | R20; FLOW-010 (salaries); FLOW-037 §3.4 (no other people's pay) | `app/routes/labor_smr.py:360` |
| 72 | `GET /api/project-profit/{project_id}` | R20-2 | `finance.project_profit.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_expense.py:449` |
| 73 | `GET /api/project-smr-view/{project_id}` | R20-2 | `finance.project_smr_view.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_expense.py:639` |
| 74 | `GET /api/profit-by-period/{project_id}` | R20-2 | `finance.project_profit_by_period.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_snapshot.py:116` |
| 75 | `GET /api/cash-vs-earned/{project_id}` | R20-2 | `finance.project_cash_vs_earned.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_snapshot.py:229` |
| 76 | `GET /api/procurement-alerts/{project_id}` | R20-2 | `finance.project_procurement_alert.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/revenue_snapshot.py:293` |
| 77 | `GET /api/execution-packages/financial-breakdown/{project_id}` | R20-2 | `finance.package_financial_breakdown.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/material_smr.py:342` |
| 78 | `GET /api/execution-packages/{pkg_id}/net-financial` | R20-2 | `finance.package_net_financial.read` | R20 (no profit / cost price / margin / client prices); FLOW-010 | `app/routes/full_cost.py:280` |
| 79 | `GET /api/price-modifiers/project/{project_id}` | R20-2 | `finance.project_price_modifier.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/price_modifiers.py:93` |
| 80 | `GET /api/price-modifiers/effective/{project_id}` | R20-2 | `finance.effective_price_modifier.read` | R20 (no margin / client prices); SEC-02 rule 2 (pricing / price modifiers) | `app/routes/price_modifiers.py:163` |
| 81 | `GET /api/projects/{project_id}/expected-actual` | R20-2B | `finance.project_budget_vs_actual.read` | R20 (budget + spent + remaining on own projects); FLOW-002 membership | `app/routes/expected_actual.py:32` |
| 82 | `GET /api/projects/{project_id}/expected-actual/compact` | R20-2B | `finance.project_budget_vs_actual_compact.read` | R20 (budget + spent + remaining on own projects); FLOW-002 membership | `app/routes/expected_actual.py:46` |
| 83 | `GET /api/projects/{project_id}/centralized-reports/activities` | R20-2B | `finance.project_budget_burn.read` | R20 (budget + spent + remaining on own projects); FLOW-002 membership | `app/routes/centralized_reports.py:24` |
| 84 | `GET /api/all-reports` | R20-5 | `finance.money_values.read` | R20; SEC-02 rule 5 (hide the values on a shared screen); FG-1/FG-15 | `app/routes/all_reports.py:24` |
| 85 | `GET /api/weekly-matrix` | R20-5 | `finance.money_values.read` | R20; SEC-02 rule 5 (hide the values on a shared screen); FG-1/FG-15 | `app/routes/weekly_matrix.py:51` |
| 86 | `GET /api/labor-entries` | R20-5 | `finance.money_values.read` | R20; SEC-02 rule 5 (hide the values on a shared screen); FG-1/FG-15; R16 (member projects) | `app/routes/labor_smr.py:228` |
| 87 | `POST /api/labor-entries` | R20-5 | `finance.money_values.read` | R20; SEC-02 rule 5 (hide the values on a shared screen); FG-1/FG-15; R16 | `app/routes/labor_smr.py:51` |

| Endpoint (PM-01 §5.2) | Rule | Why unchanged |
|---|---|---|
| `GET /api/dashboard/stats` | rule 3 (no money) | project/user/attendance/report COUNTS only, no amount (app/routes/overhead.py get_dashboard_stats) |
| `GET /api/worker-calendar` | rule 3 (no money) | status / site / hours per worker-day, no amount (app/routes/overhead_realtime.py get_worker_calendar) |
| `GET /api/billing/check-module/{module_code}` | rule 3 (no money) | module entitlement yes/no, used by every screen; no amount |

Освен регистъра:
* `app/routes/overhead.py` `check_overhead_access` — четенето на режийни (`/overhead/categories`, `/costs`, `/assets`, `/snapshots`, `/snapshots/{id}`, `/allocations`) вече е само Owner/Admin/Accountant (R20-1). Досега SiteManager четеше.
* `/projects/{id}/pnl`, `/pnl/summary`, `/pnl/breakdown`, `/pnl/trend` — махната е проверката „член на обекта“ (`can_access_project`), която пускаше член с **всякаква** роля; Accountant вече чете P&L на всеки обект (Р20 „навсякъде“).

## FG-14 — Технически ръководител

Правилото е по canonical `role_id` `site_manager` (`catalog.PROJECT_BUDGET_MEMBER_ROLE_IDS`), не по `role_in_project`. Viewer, записан в обекта като „SiteManager“, не получава бюджета (тест `test_the_enforce_decisions_and_fg12_combinations`). Проектният мениджър (`project_manager`) няма legacy източник и не получава нищо ново.

**Какво вижда:** `expected-actual` (бюджет по СМР = `activity_budgets.labor_budget`, изхарчено = труд от работните сесии, разлика) и `centralized-reports/activities` (бюджет, отчетени часове, разход, % изгаряне). **Какво не вижда:** в `expected-actual` сумите по **група СМР** и по **локация** са суми от `smr_analyses.lines[].final_total` — това е цената към клиента (с надценка и риск, `routes/smr_analysis.py` `calc_line`). За него те се махат (`planned_cost`, `actual_cost`, `variance_cost`, `status`); остават часовете и броят липсващи СМР. Без печалба, себестойност на фирмата, марж, цени.

## FG-12 — „по-ограниченото право има предимство“

1. **off/shadow:** решава единствената legacy роля (`users.role`) — няма какво да се съчетае.
2. **enforce:** Permission Service пуска, ако **кое да е** активно назначение пуска. SEC-02 гарантира, че съчетанието **не може да разшири** четенето на пари: финансовите read действия и `finance.money_values.read` са само във фирмените роли Owner/Admin (пълен набор) и Accountant; проектното назначение носи най-много бюджета на обекта и само ако фирмената роля е `site_manager`. Тествано за всеки `role_id` × роля в обекта.
3. **Не е направено (остава за Крум):** по-тясно назначение не може да **отнеме** право от по-широко (deny-overrides), напр. проектно „само преглед“ на P не спира фирмен Accountant на P. В service-а няма назначение-забрана. FG-12 остава отворен за тази част.

## FG-1 (GET) и FG-15 — трудът

* `POST /api/labor-entries` (FG-15): записът в базата пази ставката и стойността; **отговорът** към роля без финансово право ги няма. Р16 остава: член SiteManager/Technician записва (201), без пари в отговора. `sync-from-work-reports` връща само бройки — няма пари.
* `GET /api/labor-entries` (FG-1): финансовите роли — всички редове със ставка и стойност (както досега). Всички други — **само редовете на обекти, където са членове днес** (датирано), без `hourly_rate`/`labor_cost`; филтър по обект, където не са членове → 403. Viewer/Driver членове виждат часовете на обекта (правило 3 — не-финансови данни по членство).

## Frontend

* `frontend/src/lib/financeAccess.js` — огледало (`FINANCE_ROLES`, `BUDGET_VIEW_ROLES`); backend тестът проверява, че съвпада с каталога.
* Менюто „Финанси“, „Ценообразуване“, „Цени“, „Оборот“ — само Owner/Admin/Accountant (`DashboardLayout.js`).
* `FinanceRoute` (`App.js`) за финансовите страници (21 route-а: финанси, фактури, плащания, заплати, аванси, режийни, анализи, цени, оборот, OCR фактури, финансов и оперативен изглед на обект); другите роли отиват на началната страница, вместо празен екран с 0.
* Начална страница: финансовите карти (Finance Pulse, печалба, cashflow, режийни, чакащи плащания, P&L по обекти, финансово обобщение) — само финансовите роли (вече и Accountant).
* Обект: финансовата карта, централизираният изглед, финансовите резултати, P&L и персоналът с пари — само финансовите роли; „Очаквано/реално“ и таблицата с бюджет по СМР — и SiteManager. Сумите, които backend-ът е махнал, се показват като „—“.
* Служител: досието (заплати, аванси) не се иска за не-финансови роли. Склад: картата „Стойност на наличността“ — само финансовите роли. Анализ на СМР: панелите с покупни цени — само финансовите роли. „Всички отчети“ и седмичната матрица: картата/колоната със стойност се показва, само ако backend-ът я е изпратил.

## Резултат (реална MongoDB 7.0 replica set, ST-01 фирми A и B + съществуващи записи)

`results.json` — **5958 извиквания**: 87 проби (83 охранени endpoint-а + 4 общи екрана) × 8 роли × 2 фирми × (P1 и P2 за проектните) × 3 режима + B → обекта на A. Екипът на P1 (през реалния API в enforce): SiteManager, Technician, Viewer, Driver. На P2: членството на Technician е изтекло вчера, на SiteManager започва утре (SEC-R1).

| | off | shadow | enforce |
|---|---|---|---|
| финансова роля | стига до функцията (200/201/404/422/400; нито едно 5xx) | същото | същото |
| друга роля, R20-1/R20-2 | **403, нищо записано** | 403 | 403 (+AuditEvent само за export) |
| SiteManager член P1, R20-2B | 200, без суми по група/локация, без цената 7777 от анализа | същото | същото |
| SiteManager P2 (бъдещо членство), Technician/Viewer/Driver | 403 | 403 | 403 |
| общи екрани, не-финансова роля | 200, **нито един** ключ за пари | същото | същото |
| B → обекта на A | нито един запис на A в отговора | същото | същото |

Проектните назначения на SiteManager (enforce) носят точно трите бюджетни действия и нито едно финансово (`site_manager_mirrors`).

**PM-01 матрицата (всички 752 route-а), ново пускане:** **1215 клетки** са променени (`pm01_cells_changed.csv`), в 89 route-а (83 от регистъра + 6 на режийните):
* 1198 → 403 без запис и 5 → 403 + само `audit_events` (export в enforce) — 5-те нефинансови роли;
* 12 → 200 — Accountant на 4-те `/projects/{id}/pnl*` (Р20: финансовите роли на всеки обект);
* `shadow` = `off` и `enforce` = `off` по статус остават вярни за всяка клетка.

## Решения за Крум

* **SiteManager губи** (досега имаше достъп през UI): режийни (четене), P&L/финансови резултати/печалба/риск на обекта, финансовите карти на началната страница, cashflow, всички страници под „Финанси“, цени/оборот/ценообразуване, досието на служителя, пълния централизиран изглед и персонала с пари на обекта, фактурните редове, ставките и стойностите в „Всички отчети“ и седмичната матрица. Запазва бюджета по СМР и изхарченото на своите обекти. Връщането на някое от тях е една зависимост в регистъра.
* **Accountant печели** P&L на всеки обект (досега — само където е член).
* Бюджет по **група СМР** за SiteManager няма как да се покаже: в модела групата има само цена към клиента, няма вътрешен бюджет (дълг SEC-02-D6).

## Дълг (записан, не поправен)

* **SEC-02-D1:** още GET-ове с пари, които Viewer/Technician стигат и не са в §5.2 или в пакета: `/api/subcontractor-acts`, `/api/subcontractor-packages(/{id})`, `/api/ai-config/hourly-rates`, `/api/settings/sales-margins`, `/api/sales/history`, `/api/clients/{id}/invoices`, `/api/projects/{id}/dashboard` и `/invoice-details` (баланс), `/api/morning-briefing`, `/api/budget-freezes/{id}`, `/api/progress-*`, `/api/project-progress-summary/{id}`, `/api/material-entries`, `/api/project-material-summary/{id}`, `/api/smr-analyses`, `/api/offers` (цени към клиента), `/api/extra-works`. Оркестраторът да реши пакета.
* **SEC-02-D2:** SiteManager създава/вижда оферти и анализи на СМР с цени към клиента; Р20 казва „без цени към клиента“. Изисква решение (UI на офертите е за SiteManager).
* **SEC-02-D3:** складовите стойности по ред (партиди, наличност, движения) — FG-23 → пакет 5C-C25. Тук е само `GET /api/warehouse/value` (общата стойност).
* **SEC-02-D4:** `activity_budgets` (`budget.read`) се дава на **всеки** член, вкл. Viewer (`PROJECT_MEMBER_ACTIONS`) — бюджетни суми за Viewer член срещу Р20. Не е пипано (W0-02 каталог, G6).
* **SEC-02-D5:** FG-12 deny-overrides (виж по-горе).
* **SEC-02-D6:** няма вътрешен бюджет по група СМР (виж по-горе).
* **SEC-02-D7:** вече съществуващите проектни назначения в enforce получават бюджетните действия при следващата синхронизация на членството или при ново пускане на W0-02 bootstrap-а (както SEC-01-C02-D6). Дотогава SiteManager в enforce получава 403 на бюджета — по-тясно, не по-широко.
* **SEC-02-D8:** `overhead.py` (M9) чете с legacy ролята и в enforce (не през Permission Service) — както беше; само правилото е стеснено.
* **SEC-02-D9:** досието на служителя за SiteManager — 403 целият екран; версия „без пари“ (часове, присъствие) иска решение.
* Остават: SEC-01-C02-D1…D6, FG-28.

## Допълнение A (SEC-02-A, 06.11.2026) — D1 и D9

Пакетът @ `3c9e57c`, Допълнение A: прилагане на Р20 и FLOW-010, без ново бизнес решение.

### D1 — останалите GET-ове с пари (36 реда в същия регистър)

**Само пари → само Owner/Admin/Accountant (R20-1/R20-2), 403 за всички други:** `/ai-config/hourly-rates`, `/settings/sales-margins`, `/sales/history`, `/clients/{id}/invoices`, `/subcontractor-acts`, `/projects/{id}/invoice-details`, `/smr-analyses/{id}/export-excel`, `/smr-analyses/{id}/lines/{line_id}/modifier-breakdown`, `/offers/{id}/pdf`, `/offers/{id}/xlsx` (трите файла са `.export` — отказът се одитира в enforce).

**Смесени → правило R20-5M:** отговорът остава, както и досегашното правило за достъп на route-а (членство и т.н.); за роля без финансово право **се махат само ключовете с пари**. Количества, часове, статуси и бройки остават. Засегнати са `/subcontractor-packages(/{id})`, `/projects/{id}/dashboard`, `/morning-briefing(/compact)`, `/budget-freezes/{id}(/latest)`, `/progress-updates`, `/progress-updates/{pkg}/latest|history`, `/progress-comparison/{pkg}`, `/progress-warnings/{id}`, `/project-progress-summary/{id}`, `/material-entries`, `/project-material-summary/{id}`, `/smr-analyses`, `/smr-analyses/{id}`, `/compare/{v}`, `/diff/{v}`, `/offers`, `/offers/{id}`, `/offers/{id}/versions(/{n})`, `/offers/{id}/events`, `/extra-works(/{id})`.
* Механизъм: декоратор `strip_money_for_non_finance` (`app/permissions/money_write.py`). Видимостта е `money_values_visible`: в off/shadow — legacy ролята, в enforce — Permission Service.
* Кое е пари: `finance_read.is_money_key` — по името на ключа (цена, себестойност, сума, стойност, марж, надценка, бюджет, заплата, плащане, ДДС, общо…). Количества, часове, бройки, id, дати и статуси не се махат; `total` до `items`/`page` е бройка. Изключение за един route се записва до него (`/progress-warnings`: `total`, `packages_total` са бройки). Тест `test_the_money_key_rule`.
* SiteManager тук не получава бюджетни суми. Бюджетът му е в R20-2B (`expected-actual`, `centralized-reports/activities`). Р20 е таван, не задължение.

### D9 — досието на служителя без пари

`GET /api/employee-dossier/{worker_id}`: финансовите роли — пълното досие. **SiteManager — версия без пари:** редовете с отчети и присъствията са само за обектите, където е член **днес** (датирано). Няма заплата, ставка, стойности, payroll, аванси, предупреждения за плащане и payroll статус (`money_hidden: true`). Всички други роли — 403. В enforce действието е фирмено за `accountant` и `site_manager`; Owner/Admin го имат чрез пълния набор.

### Frontend (SEC-02-A)

* Досието: SiteManager го отваря. Картите и колоните с пари и табовете „Заплати“, „Аванси и заеми“, „Фишове“ са само за финансовите роли.
* Обект: картите „Баланс“ и „Фактури“ — само финансовите роли.
* `formatCurrency(undefined)` показва „—“ вместо „0,00 €“, за всяка сума, която backend-ът не е изпратил.
* Оферта и анализ на СМР: за роля без финансово право — **само за четене**. Иначе запис без цените би ги затрил. SiteManager вече не редактира оферти и не пуска ценови операции по анализа; това следва от Р20.

### Резултат и PM-01

* `results.json` — **8127 извиквания**: 123 проби × 8 роли × 2 фирми × P1/P2 × 3 режима + B→A. Нито един ключ с пари, нито цената 7777 от seed-а в отговор към не-финансова роля. Еднакво в трите режима.
* PM-01 матрицата е регенерирана с harness-а. Спрямо SEC-02 @ `6080165` има **153 клетки**: 150 → 403 (10-те route-а „само пари“ × 5 роли × 3 режима; при трите `.export` в enforce — + `audit_events`) и 3 → 200 (SiteManager на досието). Спрямо базата #69 @ `471eaaa` — **1362 клетки** (`pm01_cells_changed.csv`).

### FG-12 / D5

Deny-overrides не се прави тук — остава дълг към W0-02 (Допълнение A).

### Дълг (SEC-02-A)

* D1 и D9 са закрити. D2 (SiteManager и оферти с цени към клиента) е закрит с „само четене“ в UI-а и без пари в GET-а. Backend записите в офертите и анализите за SiteManager обаче остават, както ги остави SEC-01 → **SEC-02-A-D1:** PUT/POST на оферти и анализи от роля, която не вижда цените, не е спрян в backend-а.
* **SEC-02-A-D2:** правилото „кое е пари“ е по имена на ключове. Нов ключ с друго име на пари в тези отговори няма да бъде махнат, докато не се добави. Тестът за seed-а го хваща само за проверените стойности.
* **SEC-02-A-D3:** `/offers/{id}` и `/offers/{id}/versions` пазят досегашното си правило за достъп (членство), затова Accountant без членство получава 403 (както и преди).

## Rollback

Revert на commit-а. Няма миграция и няма запис в данни. Проектните назначения, синхронизирани след SEC-02, носят три допълнителни read действия; при стария код те просто не се ползват.

## Как се повтаря

```bash
cd backend
PYTHONPATH=. pytest tests/test_sec_02_finance_read.py -v --noconftest
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
  PYTHONPATH=. pytest tests/test_sec_02_finance_read.py -v --noconftest
PYTHONPATH=. python tests/test_sec_02_finance_read.py --harness \
  --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
# PM-01 матрицата:
PYTHONPATH=. python tests/test_pm_01_permission_matrix.py --harness \
  --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
```

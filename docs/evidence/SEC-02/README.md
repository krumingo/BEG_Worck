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

## Допълнение B (SEC-02-B, 06.11.2026) — одит SEC02-1, FLOW Guard FG-15/41/42/43

Пакетът @ `9336d69`, Допълнение B: прилагане на Р20, FLOW-037 §3.4, FLOW-010 — без ново бизнес решение.

### Сливане с #69
#69 @ `07faab5` (SEC-01-C03: сумата трябва да е крайна и > 0; Idempotency-Key на паричните POST) е слят в клона с **merge commit** `3562913` (без rebase). Конфликтите са само в import-ите на `full_cost.py`, `reports.py`, `subcontractors.py`, `labor_smr.py`; запазени са и двете страни.

### FG-15 — повторение (replay) по Idempotency-Key
`POST /api/labor-entries`: и първият отговор, и **повторението** със същия `Idempotency-Key` (редът се чете наново от базата) са без `hourly_rate`/`labor_cost` за роля без финансово право. Записът в базата ги пази. Доказателство: `results.json` → `labor_replay` — Technician, SiteManager и Accountant × 3 режима; същото id; финансовата роля вижда парите и в двата отговора.

### SEC02-1 / FG-41 / FG-42 — нови редове в регистъра
* **R20-5M (махат се само парите):**
  * `/work-sessions`, `/work-sessions/summary`, `/work-sessions/overtime`, `/work-sessions/{id}/detail`;
  * `/projects/{id}/site-workers`, `/projects/{id}/smr-groups`, `/smr-groups/tree`;
  * `/pulse/today`, `/pulse/summary`, `/sites/{id}/pulse`, `/sites/{id}/pulse/range`;
  * `/ocr-invoice`, `/projects/{id}/activity-reports/{smr}`;
  * `/labor-warnings/{id}` — за роля без финансово право вече е нужно и **членство днес**, иначе 403;
  * складът (правило 4, само количества): `/warehouse/batches`, `/warehouse/batches/{id}`, `/warehouse/items/{id}/batches`, `/warehouse/items/{id}/stock-summary`.
* **`/subscription`:** `plan_price` само за Owner/Admin (`finance.subscription_price.read`).
* В pulse SiteManager не получава `total_budget` за никой обект. Това е по-тясно от позволеното от Р20 (там е позволено за свои обекти). Бюджетът му е в R20-2B/R20-5B.

### FG-43 — правило R20-5B (бюджетни екрани на обекта)
`/projects/{id}/activities-overview`, `/activity-budget-summary`, а след скенера и `/activity-budgets`, `/budget-health` (закрива SEC-02-D4):
* финансовите роли — всичко; Accountant чете двата FG-43 екрана **на всеки обект**;
* SiteManager, член днес — бюджет + изхарчено + остатък, без `subcontractor_price` и цени към клиента;
* Viewer/Technician/Driver членове — без пари (`actual_cost` и т.н. махнати).
Механизъм: декоратор `strip_for_budget_view` (`money_write.py`).

### Скенерът на одита — 0 пари
`tools/sec02_money_scan.py` е копие на `docs/audit/probes/sec02/probe_sec02_unregistered_money_gets.py` (claude/audit-log). Регулярният израз за пари и seed-овете са същите. Разлика: **не пропуска регистрираните route-ове** и минава **всички** роли без финансово право (SiteManager, Technician, Warehousekeeper, Driver, Viewer) × off/shadow/enforce.

Резултат `scan_sec02b.json`: **5640 извиквания, 0 попадения.** Отделно са изброени:
* `allowed_budget_view` — само SiteManager на своя обект, само по R20-2B/R20-5B;
* `judged_not_money` — с причина: публичният ценоразпис на плановете (`/billing/plans`) и ставката на ДДС (`/organization`, `/projects/{id}/invoice-context`);
* `own_record` — Technician чете **собствения си** профил (`/employees/{user_id}` = той; FLOW-037 §3.4 забранява само чуждите заплати). Другите роли не получават неговата ставка.

Тест: `test_the_audit_scan_finds_no_money_for_non_finance_roles`.

### Технически поправки
FastAPI подава само **един** `Request` на endpoint. Затова декораторите ползват собствения `request` на handler-а, ако го има. Иначе `/labor-warnings` даваше 500. Вземат потребителя от `user` или от W0-02 `ctx`, иначе `/activity-budgets` даваше 500. Скенерът и harness-ът не показват нито едно 500.

### Резултат и PM-01
* `results.json` — 9798 извиквания + `labor_replay` (9).
* PM-01 матрицата е регенерирана с harness-а. Спрямо SEC-02-A @ `73b72b5` — **75 клетки**:
  * 54 са от самия #69 (`201/404 → 422` при невалидна сума на паричните записи);
  * 15 → 403 — `/labor-warnings` без членство;
  * 6 → 200 — Accountant на двата FG-43 екрана.
* Спрямо #69 @ `07faab5` — **1383 клетки** (`pm01_cells_changed.csv`).

### Дълг (SEC-02-B)
* ~~SEC-02-B-D1~~, ~~SEC-02-B-D2~~ — закрити в SEC-02-C (виж Допълнение C).
* Остават: SEC-02-A-D1…D3, FG-12 deny-overrides (W0-02).

## Допълнение C (SEC-02-C, 06.11.2026) — Р31 и поправки B-D1, B-D2

Пакетът @ `370c9b0`, Допълнение C (Р31: FLOW-019, FLOW-037 §3.4). B-D1 и B-D2 са по съобщението на оркестратора (Р20).

### Р31 — „изхарчено“ за труд за техническия ръководител
**Скриването по човек е задължително и е направено.** SiteManager вижда парите за труд **само като сума по СМР/обект** срещу бюджета:
* `expected-actual`, `centralized-reports/activities`, `activities-overview`, `activity-budget-summary`, `activity-budgets`, `budget-health`, `pulse` (свои обекти) — само агрегати по СМР/обект;
* навсякъде другаде, където има хора — `activity-reports`, `site-workers`, `work-sessions*`, досието, `all-reports`, `weekly-matrix`, `labor-entries`, работниците в pulse — **без** ставка, `labor_cost` по човек или акордна цена (R20-5M / R20-5 / D9).

Доказателство:
* harness-ът проверява, че в бюджетните отговори към SiteManager няма `hourly_rate`, `labor_cost`, `rate`, `daily_rate`. В pulse seed-ът има работник с `labor_cost` 7777, и 7777 не стига до него;
* тестът на скенера проверява, че в `allowed_budget_view` няма път с `worker`, ставка, акорд или персонал.

**Дълг SEC-02-C-D1 (по Допълнение C — описан, не пренаписан): как кодът смята „изхарчено“ днес — не по FLOW-019/FLOW-028:**

| Екран | „Изхарчено“ в кода | Отклонение от Р31 |
|---|---|---|
| `expected-actual`, `activities-overview`, `budget-health`, `pulse.budget_snapshot` | сума на `work_sessions.labor_cost` | работни сесии, не **одобрени** отчети; без типа заплащане (акорд = количество × акордна цена) |
| `centralized-reports/activities` | `amount_clean_labor` (+ режийни) от отчетите, **чернови и одобрени** | брои и неодобрени отчети |
| `activity-budget-summary` | одобрени офертни редове + дневници × `default_hourly_rate` (25) | ставка по подразбиране, не реалната |
| навсякъде | — | престоят (DOWNTIME) не е отделен ред |

Бюджетът също е различен по екрани: `activity_budgets.labor_budget`, а не офертният трудов бюджет по FLOW-019. Поправката е изчисление, т.е. отделен пакет.

### B-D2 — бюджет в pulse за свои обекти (Р20)
`/pulse/today`, `/sites/{id}/pulse`, `/sites/{id}/pulse/range` → декоратор `strip_pulse_for_non_finance`, правило R20-5B:
* финансовите роли — всичко;
* SiteManager — за всеки обект, където е **член днес**: `budget_snapshot` (бюджет / изхарчено / остатък / %), `smr_summary` (по СМР) и общия труд на обекта; без парите по работник и без материалите. За другите обекти — без пари;
* другите роли — без пари.

`/pulse/summary` (сборове за цялата фирма) остава без пари за всички не-финансови роли. Доказателство: `results.json`, поле `sites_with_money` на `/pulse/today` — SiteManager само `P1`, финансовите роли `P1, P2`, другите роли — нищо.

### B-D1 — Accountant и бюджетът на всеки обект (Р20)
`accountant` държи `budget.read` на ниво фирма, само четене (`catalog.py`, с бележка до SCOPE RULE). Legacy проверките на `/activity-budgets` и `/budget-health` пускат финансовите роли на всеки обект.

### Резултат
* Скенерът на одита — отново **5640 извиквания, 0 попадения**; в `allowed_budget_view` вече са 10 route-а (+3 pulse).
* PM-01 матрицата е регенерирана с harness-а: спрямо SEC-02-B @ `ba29dac` — **6 клетки** (Accountant 403 → 200 на `activity-budgets` и `budget-health` × 3 режима); спрямо #69 @ `07faab5` — **1389**.
* Frontend: `SitePulseCard` показва „—“ вместо фалшива 0 и не показва „€“ по работник, когато сумата я няма.

## SEC-02-D (06.11.2026) — одит SEC02C-1: заплата по човек чрез извеждане

Находка на одита @ `f17f7e5` (MEDIUM-HIGH), по Р31 / FLOW-037 §3.4. В pulse SiteManager виждаше `workers[]` (id, часове, СМР) и `smr_summary` (`total_cost` + `workers_count`). При един работник на СМР заплатата му се извежда директно: 200 € за 8 ч = 25 €/ч.

### Правило (за всеки отговор, който носи пари за SiteManager)
`finance_read.r31_view`, извиквано в SiteManager клона на `strip_for_budget_view`, `strip_pulse_for_non_finance`, `expected-actual` и `centralized-reports/activities`:
* **никаква самоличност и часове по човек:** `workers`, `workers_count`, `worker_ids`, `personnel`, `by_worker` се махат. Часовете по човек остават само на екрани без пари;
* **„изхарчено“ по СМР** (actual / spent / cost / variance / remaining / burn) се показва само ако **всеки** ред от списъка е от ≥ 2 работници. Ако дори един СМР е от един работник, се махат всички редове, иначе „обект − другите редове“ би го дал;
* **„изхарчено“ на ниво обект** — само ако обектът има ≥ 2 работници;
* бюджетът и плановите суми остават — те не са ничия заплата.

Работниците по СМР се броят от работните сесии и дневните отчети на обекта (`project_labor_workers`). В pulse за деня се броят от самия pulse, а за натрупания `budget_snapshot` — от всички работници на обекта. Ред със собствено `workers_count ≤ 1` също се смята за еднолично СМР.

### Доказателство
* Пробата на одита `docs/audit/probes/sec02/probe_sec02_c_pulse_derive.py` е копирана **непроменена** като `backend/tools/audit_probe_sec02_c_pulse_derive.py` и пусната като тест `test_the_audit_pulse_derive_probe_finds_nothing` (off и enforce): `DERIVED {}`, `FAILS: none`.
* Контрапроба (`sec02c1_counter_check.txt`): при `f17f7e5` същата проба извежда 200 € / 25 €/ч и 210 € / 35 €/ч.
* Тест `test_r31_no_per_worker_pay_by_derivation`.
* Harness-ът: в seed-а P1 има **един** работник, затова SiteManager на P1 не получава нито един ключ „изхарчено“ и нито един `workers`/`workers_count` (по всички R20-2B/R20-5B route-ове, 3 режима).
* Скенерът: пак 0 попадения. В `allowed_budget_view` вече са само бюджетни ключове (`labor_budget`, `planned_cost`, `total_budget` …).

### Сливане с #69 @ `6d43284` (Р29)
Merge commit `0d30eae`, без rebase и без конфликт в кода. Паричен POST без `Idempotency-Key` → **428** (FG-52); проверено от C03 harness-а на #69 върху слетия клон. Пробата `labor_create` на SEC-02 вече праща нов ключ при всяко извикване.

### PM-01
Регенерирана с harness-а: спрямо SEC-02-C @ `f17f7e5` — **9 клетки**, всички `POST /projects/{id}/material-waste` × финансовите роли × 3 режима, `201 → 428` (Р29 от #69). Спрямо #69 @ `6d43284` — 1389 клетки.

### Frontend
`ExpectedActualPanel`: скрито „изхарчено“ не дава NaN в лентата. `SitePulseCard` вече пази `workers` и показва „—“.

### Дълг
* **SEC-02-D-D1:** правилото брои работниците по име на СМР. СМР с различно изписване в сесиите и в бюджета се брои като отделно (безопасно: показва по-малко).
* **SEC-02-D-D2:** статусът на реда (ok / over) и часовете по СМР остават. При един работник часовете по СМР са негови часове, но без пари (позволено — часове не са заплата).

## SEC-02-E (07.11.2026) — одит SEC02D-1: `POST /sites/{id}/pulse/generate` и всички парични POST/PUT

Находка на одита @ `e6ea838` (HIGH), Р20/Р31. `POST /api/sites/{id}/pulse/generate` имаше само `get_current_user` и не махаше нищо. Warehousekeeper без членство и Viewer получаваха `workers[].labor_cost`, `total_labor_cost` и `budget_snapshot.total_spent`, в off и enforce. Всеки можеше и да прегенерира запазените pulse-ове.

### Поправка
1. `POST /sites/{id}/pulse/generate` — пазач `require_project_budget_read(..., project_from="site")`, действие `finance.site_pulse_generate.execute` (R20-2B): финансовите роли + SiteManager, член днес на обекта; всички други → 403 (в enforce + AuditEvent). Отговорът минава през `strip_pulse_for_non_finance` (R31 изгледът).
2. `POST /pulse/generate-all` — само финансовите роли (`finance.pulse_generate_all.execute`).
3. Натрупаният `budget_snapshot.total_spent` в запазените дневни pulse-ове: два дни се различават с труда на един ден, т.е. със заплатата на един работник в ден с един човек (част (b) на пробата). За SiteManager в pulse остават **само `total_budget` и `status`**. „Изхарчено“ той вижда в бюджетните екрани (текущо, по правилата на Р31).
4. Същото извеждане чрез разлика е възможно и с `expected-actual?date_from=&date_to=` — за роля без финансово право филтърът по дати вече се пренебрегва (целият обект).

### Обхождане на всички POST/PUT (точка 3 от одита)
`backend/tools/sec02_money_scan_post.py`: същият регулярен израз и seed като GET скенера. Минава **всеки POST и PUT** (без auth/billing/platform/users/internal/dev), тялото е генерирано от OpenAPI като в PM-01, базата се връща след всяко извикване (oplog). Роли: SiteManager, Technician, Warehousekeeper, Driver, Viewer × off/shadow/enforce.

Първо пускане: **18 route-а** с пари към роля без финансово право. Всички са в регистъра:

| Route | Правило | Защо |
|---|---|---|
| `POST /price-modifiers/calculate`, `POST /resource-model/worker-cost-preview`, `…/subcontractor-burden-preview` | R20-1 (финансови роли) | ценово / разходно изчисление |
| `POST /smr-analyses/{id}/recalculate`, `…/recalculate-with-modifiers`, `POST /smr-analyses/from-offer/{id}`, `POST /revenue-snapshots/from-offer/{id}`, `POST /client-acts/from-offer/{id}`, `PUT /client-acts/{id}`, `PUT /execution-packages/{id}` | R20-2 | паричен документ; затваря част от SEC-01-C02-D4 |
| `POST /budget-freezes/{project_id}` | R20-2B | бюджет: финансови роли + SiteManager член (в отговора само бюджети) |
| `POST /extra-works/ai-proposal`, `POST /projects/{id}/activity-budgets/calculate-all-snapshots`, `…/{budget_id}/calculate-snapshot`, `POST /offers/{id}/send`, `PUT /offers/{id}`, `POST /warehouse/batches` | R20-5M (махат се парите, route-ът пази правилото си) | смесен отговор; `avg_daily_wage` е средна надница |
| `POST /api/supplier-invoices` | преценено: не е пари | ставката на ДДС, повторена от входа на самия викащ |

Второ пускане (`scan_sec02e_post.json`): **4575 извиквания, 0 попадения.** `allowed_budget_view` е само SiteManager на своя обект (`budget-freezes`, `pulse/generate` — само бюджет). Тестове `test_the_post_scan_finds_no_money_for_non_finance_roles`; GET скенерът — пак 5640 / 0.

### Доказателство за SEC02D-1
* Пробата на одита `docs/audit/probes/sec02/probe_sec02_d_pulse_generate.py` е копирана **непроменена** като `backend/tools/audit_probe_sec02_d_pulse_generate.py` и пусната като тест `test_the_audit_pulse_generate_probe_finds_nothing` (off и enforce): `pulse/generate → 403` за Warehousekeeper и Viewer, `FAILS: none`.
* Контрапроба (`sec02d1_counter_check.txt`): при `e6ea838` и двете роли получават 200 с `labor_cost` 200.0.

### PM-01
Регенерирана с harness-а: спрямо SEC-02-D @ `e6ea838` — **195 клетки**. 13 route-а × 5 роли без финансово право × 3 режима → 403; в enforce + `audit_events` (действия `.execute` / `.update`). Спрямо #69 @ `6d43284` — 1584 клетки.

### Дълг
* **SEC-02-E-D1:** `POST /warehouse/batches` иска от склададжията единична цена (формата), а Р20 казва „в склада само количества“. Отговорът вече е без цената; самото въвеждане е решение за 5C-C25 / FG-23.
* **SEC-02-E-D2:** POST скенерът генерира само задължителните полета на тялото. Route-ове, които отговарят 422 без пълно тяло, не са проверени с истински данни.

### FG-63 — работниците се броят в същия прозорец и източник като парите (HIGH)
Досега броят работници за правилото „2+“ (Р31, FLOW-037 §3.4) идваше от всички приключени сесии на обекта, за цялата история. А „изхарчено“ се сумира само за прозореца на екрана. Така прозорец с един работник показваше неговото заплащане.

Сега `project_labor_workers(user, project_id, source, date_from, date_to)` брои от **същия източник и със същите филтри** като парите на екрана:

| Източник (`source`) | Екрани | Какво се брои |
|---|---|---|
| `sessions` | expected-actual (+ compact), activities-overview, budget-health, burn на СМР | приключени `work_sessions` на обекта, в прозореца `started_at` |
| `centralized` | centralized-reports/activities | приключени и нефлагнати сесии + `employee_daily_reports` Draft/Submitted |
| `daily_logs` | activity-budget-summary | `daily_work_logs.entries.user_id`, СМР = activity type на вида работа |

Правилото „2+“ се прилага за всеки прозорец (`r31_budget_view(..., date_from, date_to)`). За не-финансови роли expected-actual не приема `date_from` / `date_to`, така че прозорецът е цялата история. Ред с един работник скрива „изхарчено“ на всички редове. Проектна сума с ≤1 работник също се скрива.

Доказателство:
* unit тест `test_fg63_workers_are_counted_from_the_money_source_and_window` — цялата история: 2 работника (незатворената сесия и черновата на отчет не се броят за `sessions`); прозорец от един ден: 1 работник → „изхарчено“ за деня е скрито; `centralized` брои и черновата (3);
* реален Mongo: seed-ът на SEC-02 вече има и дневен отчет на P1 с един работник (`daily_work_logs` + `work_types`). Така harness-ът проверява в off/shadow/enforce, че activity-budget-summary не дава „изхарчено“ на техническия ръководител. Без този запис парите на екрана идват само от офертните редове (това не е заплащане), затова harness-ът по-рано не хващаше този случай.

### Сливане с #69 @ `7300864` (SEC-01-C03 допълнение B: FG-15, FG-47, FG-29)
Merge commit `4c7a87a`. Конфликтите бяха само в import-ите на `labor_smr.py`, `price_modifiers.py` и `subcontractors.py`. За тялото на `POST /labor-entries` се ползва версията на #69 (`labor_money_visible` / `without_labor_money`). PM-01 матрицата е регенерирана с harness-а: **0 клетки** спрямо SEC-02-E @ `b37909f`. Спрямо #69 @ `7300864` — **1584 клетки в 117 route-а** (`pm01_cells_changed.csv`). Матрицата на #69 е една и съща при `6d43284` и `7300864`.

## SEC-02-F (07.11.2026) — FLOW Guard pass 6: FG-74, FG-75

### FG-74 (PROVEN) — броят се само работници със заплащане в прозореца
Правилото „2+“ броеше и работници с нулев разход: сесия без ставка (`labor_cost` 0), дневен отчет с 0 часа или вид работа със ставка 0. Такъв работник не добавя нищо към „изхарчено“, но вдигаше реда до „двама“. Така се виждаше заплащането на единствения платен работник.

Сега `project_labor_workers` сумира заплащането на всеки работник от същия източник, в същия прозорец и със същата формула като екрана. Брои го само ако сумата не е 0 (за СМР — сумата в това СМР):

| Източник | Заплащане |
|---|---|
| `sessions` | `labor_cost` на сесията (каквото сумират expected-actual, budget-health, activities-overview, burn) |
| `centralized` | `amount_clean_labor` на самите записи на `build_centralized_reports` (`with_entries=True`). Route-ът подава своите, затова формулата за ставка не е копирана |
| `daily_logs` | часове × `default_hourly_rate` на вида работа (25, ако липсва), както в activity-budget-summary |

Доказателство:
* `test_fg74_only_workers_with_pay_in_the_window_count`: работник с ставка 0, нетиране +100/−100, 0 часа, вид работа със ставка 0, запис с 0 заплащане — нито един не се брои. Ред с един платен работник губи „изхарчено“, а проектната сума на двама платени остава;
* контрапроба `sec02f_fg74_counter_check.txt`: при `71f9bbe` w1 (800) + w2 (0) дават „2 работника“ и техническият ръководител вижда 800, т.е. заплащането на w1. След поправката редът и сумата са скрити.

### FG-75 — `PUT /price-modifiers/*` пише canonical AuditEvent
Двата PUT-а (`/org` и `/project/{project_id}`) записват по **един** AuditEvent чрез `audit_money_write` (`app/permissions/money_write.py`), с envelope-а на FLOW-040 (`build_event` → `record_event`):
* action `pricing.org_modifier.updated` / `pricing.project_modifier.updated`, FLOW-023, R1, success, actor;
* scope company/project, before/after на `modifiers` и `auto_rules`, endpoint, `x-request-id`, Idempotency-Key, верига (sequence + integrity hash);
* в същата база като бизнес записа (`ctx.db()`). Tenant е legacy org в off/shadow и tenant-ът на контекста в enforce (PR-06). Грешка при одита не се поглъща.

`require_money_write` оставя своя TenantContext в `request.state`; отговорът и правата не се променят.

Доказателство (реален Mongo, harness-ът на SEC-02, `price_modifier_audit` в `results.json`): 3 режима × Admin / Accountant / Viewer × org / project.
* Разрешен PUT → 200 и точно 1 събитие с всички полета по-горе.
* Отказан PUT (Accountant на `/org`, Viewer и на двата) → 403 и 0 pricing събития.
* PM-01: **15 клетки** спрямо `71f9bbe`, само колоната `written`: + `op.audit_events` при 200 на двата PUT-а (project × 3 финансови роли × 3 режима = 9; org × Owner/Admin × 3 = 6). Нито един статус не е променен.
* SEC-01 (15 клетки) и SEC-01-C01 (48 клетки) са регенерирани с техните harness-и. Разликата е същата: само тези два PUT-а, + `op.audit_events`, статусите са същите.

### Извън обхвата
FG-76 (две различни „изхарчено“) отива към LAB-01, което ще пусне expected-actual през своята функция. #71 запазва правилата за видимост.

## SEC-02-G (07.11.2026) — Codex CHANGES_REQUESTED @ `dee0610`: SEC71-01, SEC71-02

### SEC71-01 [P1] — `POST /budget-freezes/{project_id}` даваше на техническия ръководител клиентската цена и марж
Route-ът е R20-2B (SiteManager член на проекта може да замразява бюджета). Отговорът обаче връщаше целия снимков запис: `sale_total` 12345, `planned_margin` 77 и `totals.total_sale`.
* Отговорът минава през `@strip_for_budget_view`. Финансовите роли получават всичко, техническият ръководител — R20 бюджетния изглед (бюджети, без продажна цена / марж), всеки друг — без пари. Записът в базата не се променя.
* Бюджетният изглед вече не зависи само от списък с имена. `finance_read.budget_view_forbidden` е списъкът + шаблон `sale|price|margin|profit|revenue|markup|commission|final_total` за **всяко** име на ключ; `without_budget_view_forbidden` го прилага при всеки R20-5B отговор и при pulse изгледа.
* Защо скенерите не го хванаха: (1) регексът за пари нямаше `sale`; (2) отговорите в „allowed_budget_view“ не се проверяваха за забранени ключове; (3) seed-ът нямаше пакет с продажна цена. И трите са поправени. Регексът има `sale|markup|commission`. Забранен ключ в allowed отговор се записва като **hit**, а пълният списък ключове на всеки allowed отговор се пази. Seed-ът има пакет на P1 със `sale_total` 12345 и `planned_margin` 77.

### SEC71-02 [P1] — pulse с един платен и един неплатен работник показваше 160
`GET /sites/{id}/pulse` (и `/pulse/range`, `/pulse/today`, `POST …/pulse/generate` — същият декоратор) броеше всички `worker_id` от pulse-а. При един платен (160) и един с 0 даваше `total_labor_cost` 160 и `total_cost` на СМР 160.
* `money_write.pulse_paid_workers(pulse)`: брои се само работник с `labor_cost` ≠ 0 за деня. Pulse-ът пази един разход на човек, не по СМР, затова работникът се брои за СМР само ако то е **единственото** му СМР за деня. Иначе заплащането му не може да се отнесе и би вдигнало чуждо СМР до „2+“.
* Всяко СМР от `smr_summary` е в списъка. СМР с < 2 преброени работници губи `total_cost`, ден с < 2 платени губи `total_labor_cost`. `r31_view` вече скрива при ≤ 1 (по-рано само при точно 1).

### Доказателство
* unit: `test_sec71_01_the_budget_freeze_answer_is_the_budget_view` (TM: нито един забранен ключ, бюджетите остават; финансови: целият отговор), `test_sec71_02_pulse_counts_only_paid_workers` (160 + 0 → скрито; 160 + 200 → видимо; платен работник с 2 СМР не се отнася към нито едно), `test_sec71_01_no_allowed_budget_view_route_carries_a_forbidden_field` (всички allowed route-ове в двата скана, със забранителния шаблон).
* реален Mongo, harness-ът на SEC-02 в off/shadow/enforce:
  * всеки R20-2B / R20-5B отговор 200/201 към не-финансова роля е без забранен ключ (`forbidden_keys`);
  * финансовите роли на POST freeze виждат `sale_total`, `planned_margin`, `total_sale`;
  * `pulse_one_paid_worker`: `GET /sites/{P1}/pulse?date=2026-11-03` (160 + 0) → TM без 160, без worker list, snapshot само budget/status; Accountant и Owner виждат 160.
* скенерите след поправката: GET 5640 извиквания / 0 hits, POST/PUT 4575 / 0 hits. POST freeze е в allowed само с бюджетни ключове.
* контрапроба `sec02g_counter_check.txt`: при `dee0610` TM получава `sale_total` 12345, `planned_margin` 77 и pulse 160; след поправката — нито едно от тях.
* PM-01: 0 клетки спрямо `dee0610` (статусите и записите са същите; промяната е само в съдържанието на отговора).

### SEC71-03 [P1] (Допълнение D) — текстът на алерта за бюджет издаваше заплатата
„Надхвърлен бюджет! (900.0%)“ до видим бюджет 10 дава 90. В еднодневен pulse с един платен работник това е цялото му заплащане. `strip_money` махаше ключове, но не текста в `alerts[].message`. Контрапробата при `c0247e8` показа, че текстът стигаше до **всяка** не-финансова роля, не само до техническия ръководител. Същото важеше за `labor-warnings` („90 EUR / 10 EUR budget“), `material-warnings` (EUR, без никаква защита) и `progress-warnings` (% разход спрямо бюджета).

Поправка (`finance_read.money_free_alert`, вградено в `strip_money` и в бюджетния изглед):
* за роля без финансово право всеки паричен алерт става **един и същ** генеричен алерт `budget_attention` / warning / „Бюджетът изисква внимание — подробности при финансите“, без сума, без процент и без числови полета. Важи за типовете budget_warning, budget_overrun, budget_burn_high, over_labor_budget, over_material_budget, missing_material_budget, labor/materials_ahead_of_progress, progress_lag, loan, client_receivable;
* „>80 %“ и „>100 %“ дават еднакъв отговор, така че прагът също не се издава;
* предпазна мрежа: всеки друг текст (message/text/title/detail/description/label) с число + % или валута се заменя с „Има предупреждение — подробности при финансите“;
* важи за запазени pulse-ове при четене и за генерирани (`POST …/pulse/generate` и при поискване). В базата записът остава пълен, финансовите роли виждат пълния текст;
* `GET /material-warnings/{project_id}` вече е в регистъра (R20-5M) и минава през `@strip_money_for_non_finance`;
* проверени и без проблем: `financial-alerts` и `procurement-alerts` (само финансови), досието (warnings = [] без финансово право), overtime / unmapped / sick (часове и бройки).

Доказателство:
* unit `test_sec71_03_budget_alert_text_gives_no_amount`: pulse изглед (TM и друга роля), двата прага → еднакъв генеричен алерт, без „900“ / „90.0“; финансови → пълен текст; labor / material / progress / receivable / непознат тип през `strip_money` и бюджетния изглед;
* реален Mongo, `pulse_budget_alerts`, 3 режима: запазен >80 % (11-02), запазен >100 % (11-03), генериран >100 % (11-04, 124 %) и при поискване (11-05) с един платен работник. TM получава един и същ генеричен алерт в четирите случая и никакъв текст с %/валута; Accountant вижда 85.0% / 900.0% / 124.0%;
* скенерите: текст с число + %/валута вече е **hit** (`=text`), включително в allowed бюджетния изглед. GET 5640 / 0 hits, POST/PUT 4575 / 0 hits;
* контрапроба `sec02g_sec71_03_counter_check.txt`.

### FG-111 (Допълнение E, ДОКАЗАНО) — `/alarms` показваше „бюджет 900.0% изхарчен“ и `metric_value`
Алармите (`alarm_engine`) пишат `message` „<обект>: бюджет 900.0% изхарчен“ и `context.metric_value` / `threshold`. Нито един reader не беше в FINANCE_READS, затова Technician, Viewer и SiteManager получаваха всичко. Класът е същият като при SEC71-03.

Поправка:
* регистрирани като R20-5M и минават през `@strip_money_for_non_finance`: `GET /alarms`, `GET /alarms/dashboard`, `GET /alarms/{event_id}`, `PUT /alarms/{event_id}/acknowledge`, `PUT /alarms/{event_id}/resolve` (отговорът е събитието) и `POST /alarms/evaluate` (отговорът изброява новите събития);
* `finance_read.money_free_alarm` (част от `money_free_alert`, т.е. от `strip_money`): за роля без финансово право **всяка** аларма губи `context.metric_value`, `threshold` и `details`;
* паричните типове аларми (budget, overhead, pricing, procurement, custom) получават генеричния текст, генерично име на правило („Бюджетна аларма“; името от администратора може да носи прага, напр. „Бюджет над 80%“) и severity warning. Така правило на 80 % и правило на 100 % изглеждат еднакво;
* останалите аларми (overtime, attendance, deadline) запазват текста си (часове / дни), но минават през предпазната мрежа за %/валута;
* финансовите роли виждат всичко; записът в базата не се променя;
* `/alarms/count` дава само бройки и не е променен.

Доказателство:
* unit `test_fg111_alarms_give_no_amount_metric_or_threshold`: регистър + декоратор на 6-те reader-а; правило 80 % и 100 % дават еднакъв отговор; overtime запазва часовете си без metric/threshold; evaluate и dashboard се проектират;
* реален Mongo, harness `alarms`, 3 режима × SiteManager / Technician / Viewer / Accountant × list / one / dashboard / evaluate. Seed: записана аларма „900.0%“ с `metric_value` и активно правило > 80 %; evaluate вдига нова аларма от 124 % при един платен работник. Не-финансовите роли получават генеричната аларма без metric/threshold/details и без „900“ / „124.0“ никъде в отговора. Accountant вижда пълния текст и metric_value;
* скенерите обхождат `/alarms*` (GET) и `POST /alarms/evaluate` / `PUT …` (POST/PUT) със seed-натата аларма; текст с %/валута е hit. GET 5640 / 0 hits, POST/PUT 4575 / 0 hits;
* контрапроба `sec02g_fg111_counter_check.txt`: при `5af530e` нито един reader не е в регистъра и отговорът е суров.

### SEC71-04 (Допълнение F, БЛОКИРАЩО, ДОКАЗАНО) = дълг D1 — бисекция на лентата
Лентата не беше груба. Техническият ръководител може да upsert-не бюджета на дейността и да генерира pulse. `budget_snapshot.status` (on_track / warning / over_budget) се смята спрямо **кумулативния** разход за труд на обекта. Пробата на одита `probe_sec71_d1_band_bisect.py` с бисекция по бюджета извежда **6196.90 при реални 6200.00 за 21 стъпки** в off/shadow/enforce (контрапроба при `02a1441`).

Поправка (Р31, същото правило като SEC71-02): за роля без финансово право, когато разходът за труд в обхвата идва от **< 2 платени работника** (`money_write.single_paid_sites`: приключени сесии на обекта, кумулативно, работник с ненулево заплащане — същото, което сравняват pulse статусът и бюджетната аларма), **няма лента**:
* pulse (`/sites/{id}/pulse`, `/pulse/range`, `/pulse/today`, `POST …/pulse/generate`): `budget_snapshot` остава само с `total_budget`, без `status`; бюджетните алерти (и генеричният) се махат. Отговорът е еднакъв при on_track, warning и over_budget;
* `/pulse/summary`: паричните алерти на такъв обект и броят им се махат;
* `/alarms`, `?severity=` филтърът, `/alarms/count`, `/alarms/dashboard` (by_severity, by_type, by_site, recent и тренд), `/alarms/{id}` (404), acknowledge / resolve (404), `POST /alarms/evaluate`: паричните аларми на такъв обект не съществуват за роля без финансово право (`money_alarm_exclusion` — `$nor` в самата заявка, така че и бройките са без тях). Отговорът е като при „няма данни“, еднакво за всички прагове;
* бюджетните екрани (R31 редове / проектна сума): лента, изчислена от скрит „изхарчено“, се маха заедно с него — `status`, `*_status`, severity, health, color, броячите `warning_/over_/red_/yellow_/green_count`, `biggest_overrun_*` (`finance_read._BAND` в `_drop_actual`);
* при **≥ 2 платени работника** лентата остава (сборът е разрешен по Р31): status, severity, бройки. Пак без сума, процент и metric. Затова severity на паричната аларма вече не се изравнява (FG-111 запазва генеричния текст и име);
* финансовите роли виждат всичко.

Доказателство:
* пробата на одита е копирана **непроменена** като `backend/tools/audit_probe_sec71_d1_band_bisect.py` и се пуска като тест `test_the_audit_band_bisection_probe_finds_nothing`: off/shadow/enforce → статус няма, „derived spent 0.02 vs actual 6200.00“, **FAILS: none**. Контрапроба при `02a1441` — FAILS в трите режима (`sec02g_sec71_04_counter_check.txt`);
* unit `test_sec71_04_no_band_with_fewer_than_two_paid_workers`: pulse изглед (TM и друга роля), on_track / warning / over_budget → еднакъв отговор без статус и алерт; 2 платени → статус и генеричен алерт; финансови → всичко; R31 изгледът маха `status` / `overall_status` / броячите / `biggest_overrun_activity` при 1 работник и ги пази при 2;
* реален Mongo, harness `band_paid_workers`, 3 режима × SiteManager / Technician / Viewer / Accountant:
  * 1 платен работник: count 0 / 0, `?severity=critical` празен, alarm по id → 404, dashboard by_severity нули, generate → snapshot само total_budget, без бюджетен алерт;
  * 2 платени (втора платена сесия, добавена за проверката): count critical ≥ 1, severity critical с генеричен текст, status в snapshot, генеричен алерт;
  * Accountant — пълно и в двата случая;
* `check_alarms` и `check_pulse_budget_alerts` са затегнати: при P1 (1 платен) не-финансовите роли нямат бюджетна аларма / алерт / статус.

### SEC71-05 (Допълнение H, БЛОКИРАЩО, ДОКАЗАНО) — `POST /alarms/evaluate` и `resolved_events`
При `e90aa5f` evaluate филтрираше `events` / `new_events`, но не `resolved_events`. С бюджетно правило с `auto_resolve: true` техническият ръководител прави цикъл: бюджет B → evaluate → бюджет 10⁹ → evaluate. `resolved_events > 0` точно когато B < кумулативния разход за труд, така че пробата на одита извежда **6196.90 при реални 6200.00 за 21 стъпки**.

Поправка:
* **`POST /alarms/evaluate` е само за финансови роли** (`require_finance_read("finance.alarm_evaluation.execute")`, R20-1 в регистъра). Evaluate оценява правилата на **всички** обекти и отговаря с броячи (нови / auto-resolved). Тези броячи не могат да се отнесат към обект, следователно не могат да се филтрират по обекти.
  * Кой го вика: само бутонът „Оцени“ на `AlarmsDashboardPage` (Admin/Owner/SiteManager/Accountant); няма cron или друг извикващ.
  * Бутонът вече се показва само при `canReadFinance` (Owner/Admin/Accountant).
  * В enforce отказът пише каноничния AuditEvent „permission denied“, т.е. кой е викал. В off/shadow решава legacy проверката (403).
* Допълнителна защита (недостижима за не-финансова роля): ако все пак стигне до handler-а, отговорът е само `new_events` / `events` без паричните аларми на single-paid обекти, без `resolved_events`, през `strip_money`.
* **Други отговори с броячи / списъци от аларми:**
  * `/alarms`, `?severity=`, `/alarms/count`, `/alarms/dashboard` (by_severity, by_type, by_site, recent, тренд), `/alarms/{id}`, acknowledge / resolve — `$nor` в заявката от SEC71-04. 404 за скрита аларма е еднакъв с 404 за несъществуваща (проба на одита, „404-oracle same=True“). Bulk ack/resolve няма;
  * **`GET /morning-briefing` и `/morning-briefing/compact` — намерено при проверката.** За всеки проект брифингът смяташе кумулативния разход за труд спрямо бюджета: причина „Бюджетът е надхвърлен“ / „Бюджет N% изхарчен“ + severity critical / warning, плюс броячите critical/warning, top аларми и „N критични аларми“ по обект. Това е същата бисекция като SEC71-04 (текстът „Бюджетът е надхвърлен“ няма число и минаваше покрай предпазната мрежа). Сега за роля без финансово право `build_morning_briefing(..., band_user=user)`: на single-paid обект няма причина / severity за бюджет, а паричните му аларми не се броят и не се изброяват (броячи, top_alarms, headline, „критични аларми“);
* при ≥ 2 платени работника лентата остава (Р31), финансовите роли виждат всичко.

Доказателство:
* пробата на одита (`ce2f93c`, разширена с /alarms + resolve, 404 oracle, auto_resolve oracle и known-pay вариант) е копирана **непроменена** в `backend/tools/audit_probe_sec71_d1_band_bisect.py`. Тестът `test_the_audit_band_bisection_probe_finds_nothing` изисква:
  * pulse и /alarms бисекция → нищо, в 3 режима (evaluate → 403, 0 стъпки);
  * 404 oracle еднакъв;
  * auto_resolve oracle → 0 стъпки, нищо;
  * остава **само** „known-pay variant“ — въпрос по канона, отнесен до Крум; по него нищо не е променено;
* контрапроба `sec02g_sec71_05_counter_check.txt`: при `e90aa5f` auto_resolve oracle извежда 6196.90; след поправката — 0 стъпки;
* harness: `alarms` — evaluate от SiteManager / Technician / Viewer → 403 в 3-те режима, Accountant → 200. `band_paid_workers` — morning-briefing (+ compact):
  * при 1 платен: P1 без бюджетна причина / „аларми“, броячи 0 / 0, top_alarms 0;
  * при 2 платени: „Бюджетът е надхвърлен“ и critical ≥ 1;
  * Accountant — пълно;
* PM-01: **15 клетки** спрямо `e90aa5f`. Всички са `POST /alarms/evaluate` × 5 не-финансови роли × 3 режима, 200 → 403; в enforce + `op.audit_events`.
* frontend: yarn test 102 passed, build compiled.

### Дълг / решение за Крум
* **SEC-02-G-D2 (Крум, канон):** known-pay вариантът — 2 платени работника, единият е самият технически ръководител (знае своето заплащане); лентата е разрешена по Р31 2+, а от нея се изважда заплащането на другия (6196.63 / 6200 в пробата на одита). Нищо не е променено до решение.
* **SEC-02-G-D1 — ЗАТВОРЕН от SEC71-04 (Допълнение F):** лентата (status / severity / count / филтър / наличие на аларма или алерт) не се показва на роля без финансово право при < 2 платени работника; при ≥ 2 остава, както позволява Р31.

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

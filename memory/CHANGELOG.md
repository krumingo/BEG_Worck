## Apr 12, 2026 — Step 3: Group Payment with Partial Pay + Carry Forward

### Step 3 UI:
- Columns: Checkbox | Служител (avatar+name) | Нетно | Реално платено (editable) | Остатък
- Header: Избрани X | Нетно X | Платено X | Остатък X
- Quick actions: "Платено = Нетно" | "Нулирай"

### Payment logic:
- paid_now_amount = editable per employee (can be < net, 0, or exact)
- remaining = net - paid_now_amount
- Unselected employees don't enter batch
- "Потвърди плащане (X EUR)" sends only selected rows with actual paid amounts

### Detail statuses per employee:
- Платен (green): paid > 0 && remaining <= 0
- Частичен (amber): paid > 0 && remaining > 0
- Неплатен (gray): paid = 0

### 3-step flow complete:
1. Дни (weekly grid, select days/employees)
2. Корекции (advance/loan/deduction/bonus per employee)
3. Плащане (actual paid amounts, partial/full, confirm)

### Files: frontend/src/pages/PayRunsPage.js — Step 3 table + payment state + detail statuses


## Apr 12, 2026 — Editable Day Cells + Step 2 Adjustments

### Day ordering: Sat→Fri (frontend sort by getDay)
### Day Edit Dialog (double-click):
- Shows: date, employee, site, original hours/value
- Editable: hours, value, reason
- Override layer: stored in dayOverrides[`${eid}_${date}`], source values preserved

### Step 2: Adjustments table
- Columns: Служител | Брутно | Аванс | Заем | Удръжки | Бонус | Други | Нетно
- Each cell clickable → opens type-specific dialog
- Formula: Нетно = Брутно + Бонуси - Удръжки - Аванс - Заем ± Ръчна корекция

### Adjustment dialog:
- Type selector: Аванс / Заем / Удръжка / Бонус / Ръчна корекция
- Fields: title, amount, note
- Shows existing adjustments for same type
- Can remove individual adjustments

### Flow: 1. Избор на дни → 2. Корекции → Чернова / Потвърди
- "Напред → Корекции" button
- "← Назад към дни" button
- State preserved between steps

### Files:
- frontend/src/pages/PayRunsPage.js — step state, dayOverrides, adjustments, dialogs
- backend/app/routes/pay_runs.py — dates in generate response (already done)


## Apr 12, 2026 — Weekly Selection Grid for "Ново разплащане"

### Selection Model:
- `selectedEmps`: Set<employee_id> — which people are in current batch
- `selectedDays`: { employee_id: Set<date> } — which days per person
- Both update live — header totals recalculate instantly

### Day Cell Content:
- Hours (bold), Value (EUR), Site name (compact, +N if multiple)
- Source: /api/pay-runs/generate returns `day_cells[]` per employee
- Each cell: { date, hours, value, sites[] }

### Save Draft / Reopen:
- "Запази чернова" → sends only selected employees + their selected day amounts
- "Потвърди (X EUR)" → sends selected + confirms + generates slips
- Selection state lives in React state, preserved across tab switches

### Bulk Actions:
- "Избери всички" — selects all employees + all their days
- "Изчисти" — deselects all
- Per-row: ✓ (select all days) / × (clear all days) mini button

### Backend: /api/pay-runs/generate enhanced
- Returns `dates[]` (full date range) + `day_cells[]` per employee row
- day_cells: { date, hours, value, sites[] }

### Files:
- backend/app/routes/pay_runs.py — day_cells + dates in generate response
- frontend/src/pages/PayRunsPage.js — weekly grid with selection model


## Apr 12, 2026 — Editable Workflow: Draft/Reopen/Version History

### Batch Status Model:
draft → confirmed → paid (normal flow)
draft → reopened → draft (edit cycle)
confirmed → reopened → confirmed (fix after confirm)

### Row-level Status: included | excluded | reopened | removed

### New Endpoints:
- POST /pay-runs (status: "draft" | "confirmed") — Save Draft or Confirm
- PATCH /pay-runs/{id} — Update draft/reopened, increment version, generate slips on confirm
- POST /pay-runs/{id}/reopen — Reopen whole batch or specific employee rows
- GET /pay-runs/{id}/history — Version history with action/reason/totals snapshots

### Version History (stored in pay_run.history[]):
{version, action, changed_by, changed_at, reason, totals_snapshot, reopened_employees}

### UI Actions:
- "Запази чернова" — saves as draft status
- "Потвърди" — confirms + generates slips
- "Отвори за редакция" — reopens batch/rows
- "История" — shows version timeline

### Backward Compatible: old pay_runs without version/history field default to v1

### Files:
- backend/app/routes/pay_runs.py — PATCH, reopen, history endpoints + row_status
- frontend/src/pages/PayRunsPage.js — draft/reopen/history UI + new status badges


## Apr 12, 2026 — Stage 6 Final: All Employee Tabs Unified at 100%

### Tabs fixed to use period-aware sources:
- **Обекти**: Rewritten — derives from dossier.reports.lines, groups by project, shows Дни/Часове/Стойност + ОБЩО row. Period-aware.
- **Присъствия**: Rewritten — derives from dossier.calendar, filters by periodFrom/periodTo. Summary: На работа/Болни/Отпуска/С отчет/Часове. Period-aware.
- **Заеми**: Enhanced — summary bar (Общо/Активни/Върнати/Дълг/Издадени) + status breakdown (Активен/Одобрен/Върнат). All-time correct.
- **Заплати + Фишове**: Already period-filtered (from previous stage)

### Reconciliation verified (Светлин, 04/01→04/12):
- Summary.часове = Отчети.часове = Обекти.ОБЩО = Присъствия.часове = 30ч ✅
- Summary.стойност = Отчети.стойност = Обекти.ОБЩО.стойност = 486 EUR ✅
- Summary.заеми = Заеми.издадени = 4100 EUR ✅

### All tabs now use same source chain:
employee-dossier/{id}?date_from&date_to → Summary + Отчети + Обекти + Присъствия + Заеми
payroll-weeks?employee_id + client filter → Заплати
payment-slips?employee_id + client filter → Фишове
employees/{id}/calendar?month (synced) → Календар

### Files: frontend/src/pages/EmployeeDetailPage.js (Обекти + Присъствия rewritten, Заеми enhanced)


## Apr 12, 2026 — Stage 6: Unified Employee Data / Period Controller

### Unified Period Controller
- Date picker: от/до + бързи бутони "Този месец" / "Миналият" / "3 месеца"
- Shared state: periodFrom + periodTo passed to all tabs
- Calendar syncs month with periodFrom
- Dossier fetches with date_from/date_to parameters
- PayrollWeeks and Slips filter by overlapping period

### Summary Bar — 6 unified cards
- Часове | Отчети | Изработено EUR | Платено EUR | Остатък EUR | Заеми EUR
- All from same dossier endpoint with same period

### Reconciliation:
- Summary ↔ Отчети: same source (employee-dossier), same period → match ✅
- Заплати: pay_runs with overlapping periods → correct behavior ✅
- Фишове: payment_slips with overlapping periods → correct ✅
- Calendar: syncs month from periodFrom → consistent ✅

### Source of Truth per tab:
| Tab | Endpoint | Period Source |
|-----|----------|-------------|
| Summary | /employee-dossier/{id} | periodFrom→periodTo |
| Calendar | /employees/{id}/calendar | month from periodFrom |
| Reports | /employee-dossier/{id} | periodFrom→periodTo |
| Payroll | /payroll-weeks?employee_id= | filter by overlap |
| Slips | /payment-slips?employee_id= | filter by overlap |
| Projects | /employees/{id}/dashboard | all time |
| Advances | /employee-dossier/{id} | all time |

### Files: frontend/src/pages/EmployeeDetailPage.js


## Apr 12, 2026 — Stage 5 Final: PDF Slip + Guardrails + Quick Filters

### PDF Payment Slip
- `GET /api/payment-slips/{id}/pdf` — generates printable A4 PDF
- Content: фирма, служител, период, седмица №, тип, дни, часове, ставка
- Calculation: изработено → корекции → удръжки → вече платено → платено сега → остатък
- Footer: формула + подписи (работодател / служител)
- Cyrillic: DejaVu font

### Guardrails
- Warning при remaining < 0 (надплащане) в slip detail + generate tab
- Formula explanation: "Остатък = Изработено + Бонуси - Удръжки - Вече платено - Платено сега"
- Color coding: зелено (=0), amber (>0 остатък), червено (<0 надплащане)

### Quick Filters (Седмици tab)
- Всички | Неплатени | Частично | Надплатени | С фиш | Без фиш

### Reconciliation
- Payroll Weeks, Slips, Employee Заплати, Employee Фишове all use same pay_runs source
- All frozen at confirm time — no drift from profile changes

### Files:
- backend/app/routes/pay_runs.py — PDF endpoint + lint fix
- frontend/src/pages/PayRunsPage.js — quick filters + PDF button + guardrails


## Apr 12, 2026 — Payroll Weeks View + Earned Engine Fix + Employee Integration

### Earned Engine Corrections:
- **monthly**: Pro-rated: (monthly_salary / working_days) × approved_days. Formula shown in UI.
- **daily**: approved_days × daily_rate (not hours × hourly equivalent)
- **akord/piecework**: Uses approved_value when available, falls back to hours × hourly_rate
- **mixed**: Base (daily × days) + overtime at 1.5× rate
- All types return `formula` string for UI display

### Payroll Weeks View (new tab "Седмици"):
- Global view: Сед.№ | Период | Човек | Обект | Дни | Часове | Изработено | Корекции | Платено | Остатък | Статус | Фиш
- Filter: "Само неплатени" checkbox
- Paid rows: green tint | Partial: amber остатък | Slip badge clickable

### Employee Integration (real data, not dossier fallback):
- Tab "Заплати": loads /api/payroll-weeks?employee_id={id} — shows real pay run rows per employee
- Tab "Фишове": loads /api/payment-slips?employee_id={id} — shows real slips with detail modal
- Summary bar: Изработено X EUR | Платено Y EUR | Записи N

### Backend: GET /api/payroll-weeks
- Flattens all pay_runs → per-employee rows
- Enriches with slip_id/slip_number/slip_status
- Filters: employee_id, month, status, only_unpaid

### Files:
- backend/app/routes/pay_runs.py — calc_earned fix + formula + /payroll-weeks endpoint
- frontend/src/pages/PayRunsPage.js — "Седмици" tab
- frontend/src/pages/EmployeeDetailPage.js — real EmployeePayrollWeeks + EmployeeSlips components


## Apr 12, 2026 — Pay Runs v2: Multi-type Earned Engine + Adjustments + Payment Slips

### Payment Profile (from employee_profiles):
- pay_type: Hourly / Daily / Monthly / Akord (piecework) / mixed
- payment_schedule: weekly / Monthly / manual (from pay_schedule field)

### Earned Calculation Engine (calc_earned):
- hourly: approved_hours × hourly_rate
- daily: approved_hours × (daily_rate / hours_per_day)
- monthly: approved_hours × (monthly_salary / working_days / hours_per_day)
- piecework (Akord): approved_hours × hourly_rate (if set)
- mixed: fallback to monthly formula

### Adjustment Types:
- bonus, advance, loan_repayment, deduction, manual_correction
- Each stored as {type, title, amount, note} in employee_rows

### Payment Slips (payment_slips collection):
- Generated automatically at Pay Run confirm
- slip_number: SL-00001, SL-00002...
- Contains: all frozen employee fields + adjustments + earned/paid/remaining
- Status syncs with Pay Run (confirmed → paid)
- Detail shows: КОРЕКЦИИ section + full calculation breakdown

### New: 3 tabs in /pay-runs page
- "Ново разплащане" (generate + adjustments + confirm)
- "История" (pay run list + detail)
- "Фишове" (slip list + detail modal)

### Files:
- backend/app/routes/pay_runs.py — rewritten with calc_earned engine + slips
- frontend/src/pages/PayRunsPage.js — rewritten with adj dialog + slips tab


## Apr 12, 2026 — Pay Runs (Разплащане) — Stage 5 Core

### New Data Model: pay_runs collection
Fields: id, org_id, number (PR-XXXX), run_type (weekly/advance/month_close), period_start, period_end, week_number, status (confirmed/paid), employee_rows[], totals, created_by, confirmed_at, paid_at

### Employee Row (frozen at confirm):
frozen_hourly_rate, approved_days, approved_hours, normal_hours, overtime_hours, earned_amount, bonuses_amount, deductions_amount, previously_paid, paid_now_amount, remaining_after_payment, sites[], notes

### Formula: remaining = earned + bonuses - deductions - previously_paid - paid_now

### Source of Truth:
- earned_amount from approved report lines × frozen_hourly_rate
- paid_now_amount set by admin at confirm time
- remaining_after_payment = math result
- All values frozen in snapshot at confirm

### Backend: /app/backend/app/routes/pay_runs.py
- GET /pay-runs/generate — preview from approved reports
- POST /pay-runs — create + confirm with frozen values
- GET /pay-runs — list history
- GET /pay-runs/{id} — detail
- POST /pay-runs/{id}/mark-paid

### Frontend: /app/frontend/src/pages/PayRunsPage.js
- Tab "Ново разплащане": period picker, editable table (бонуси/удръжки/плащане), confirm button
- Tab "История": list with detail modal, mark-paid button
- Sidebar: Персонал → Разплащане


## Apr 11, 2026 — Unified Report Model Cleanup

### Official Report Model: Flat normalized line
Fields: id, date, worker_id, worker_name, project_id, smr_type, hours, status, payroll_status, notes, source_type ("new"|"old"), submitted_by, approved_by, entered_by_admin, entry_mode, created_at

### New: /app/backend/app/services/report_normalizer.py
- `fetch_normalized_report_lines()` — reads both old+new style, returns unified flat list
- `enrich_hours()` — adds normal_hours/overtime_hours to any line
- `fetch_worker_day_map()` — groups by worker→date→entries (for matrix/payroll)
- Supports: date range, worker_id, project_id, smr filter, status filter, payroll filter

### Legacy: Old-style (employee_id + day_entries)
- Still readable via normalizer
- Each line tagged with `source_type: "old"`
- Not removed from DB, but no new creation

### Consumers refactored to unified path:
1. **All Reports** (all_reports.py) — `fetch_normalized_report_lines()` ✅
2. **Weekly Matrix** (weekly_matrix.py) — `fetch_worker_day_map()` ✅
3. **Payroll Batch** (payroll_batch.py eligible) — `fetch_worker_day_map()` ✅
4. **Payslip** (payroll_batch.py payslip) — reads from batch (already normalized at batch time) ✅
5. **Employee Dossier** (employee_dossier.py) — `fetch_normalized_report_lines()` ✅

### Files changed:
- NEW: backend/app/services/report_normalizer.py
- REFACTORED: backend/app/routes/all_reports.py (removed inline dual-query)
- REFACTORED: backend/app/routes/weekly_matrix.py (removed inline dual-query)
- REFACTORED: backend/app/routes/payroll_batch.py (eligible uses normalizer)
- REFACTORED: backend/app/routes/employee_dossier.py (removed inline dual-query)


## Apr 11, 2026 — Rate Freeze at Batch Creation

### Freeze Fields Added to employee_summaries:
- `frozen_hourly_rate` — rate at batch creation time
- `frozen_pay_type` — pay type at batch creation time
- `frozen_gross` — calculated gross at batch creation time
- `rate_frozen_at` — timestamp of freeze

### Allocation Uses Frozen Rate:
- Primary: `frozen_hourly_rate` from batch employee_summaries
- Fallback: `_calc_rate(profile)` only if no frozen field (legacy batches)
- Each allocation line tagged with `rate_source: "frozen"` or `"legacy_profile_rate"`

### Payslip Shows Rate Source:
- `rate_frozen: true` + "Ставка замразена при създаване" (green)
- `rate_frozen: false` + "Ставка от текущ профил (стар batch)" (amber)

### Legacy Backward Compatibility:
- Old batches without freeze fields → fallback to current profile rate
- Warning badge in payslip for legacy rate source

### Files: payroll_batch.py (batch creation + allocation + payslip), PayslipDialog.js, i18n


## Apr 11, 2026 — Official Payslip + Legacy Demotion

### New Payslip Endpoint: GET /api/payslip/{batch_id}/{worker_id}
- Returns: worker info, summary (days/hours/normal/OT/gross/bonuses/deductions/net)
- Breakdowns: by_day (entries), by_project (hours+value), by_smr (hours), allocations
- Traceability: batch_id → report_ids → worker → projects → paid_at

### Frontend: PayslipDialog.js
- Worker header + status badge + period
- 6-card summary: Дни | Часове | Норм. | Извънр. | Брутно | Нетно
- ПО ДНИ table: date, hours, normal, overtime, details (SMR@Project)
- ПО ОБЕКТИ: project name, hours, value
- Final calculation: Брутно → Бонуси → Удръжки → За плащане
- Paid indicator: ✓ Платено на YYYY-MM-DD

### Visible "Фиш" button:
- Payroll tab → ФИШОВЕ ЗА ЗАПЛАТИ section (for paid weeks)
- Employee dossier → Заплати tab → Фиш per week row

### Legacy demotion:
- Sidebar: /payroll renamed to "Фишове (стар)" via nav.payrollLegacy

### Test: 100% backend (16/16) + 100% frontend
- /app/test_reports/iteration_69.json


## Apr 11, 2026 — Final Dossier Wiring (All Reports + Weekly + Payroll)

### Worker Name/Avatar Links Added:
- **AllReportsPage**: click worker → `/employees/:id?tab=reports`
- **WeeklyMatrixSection**: click worker → `/employees/:id?tab=calendar`
- **PayrollBatchSection**: click worker → `/employees/:id?tab=payroll-weeks`

### All Entry Points Complete:
1. Персонал → Служители → click row → `/employees/:id`
2. Отчети → Досие tab → worker picker → `/employees/:id?tab=reports`
3. Dashboard → Персонал днес → click name → `/employees/:id`
4. Всички отчети → click worker → `/employees/:id?tab=reports` ✅ NEW
5. Седмица → click worker → `/employees/:id?tab=calendar` ✅ NEW
6. Заплати → click worker → `/employees/:id?tab=payroll-weeks` ✅ NEW

### Files: AllReportsPage.js, WeeklyMatrixSection.js, PayrollBatchSection.js (cursor + navigate)


## Apr 11, 2026 — Unified Employee Dossier (Route Unification)

### Single Route: /employees/:id?tab=
- 7 tabs: Календар | Отчети | Заплати | Обекти | Заеми | Присъствия | Фишове
- Deep links: ?tab=reports, ?tab=payroll-weeks, ?tab=advances, etc.
- Summary cards: Общо часове | Изработено EUR | Платено EUR | Отчети count
- Warnings: unpaid weeks, active loans, missing rate

### Entry Points (all navigate to same /employees/:id):
- Персонал → Служители list → click row
- Отчети → Досие tab → worker picker → navigate to /employees/:id?tab=reports
- Dashboard → Персонал днес → click worker name
- All Reports table → worker name click
- Weekly Matrix → worker click

### Changes:
- EmployeeDossierSection.js: rewritten to be worker picker → navigate (no duplicate dossier)
- EmployeeDetailPage.js: added 3 new tabs (Отчети, Заплати, Заеми), dossier summary cards, warnings, ?tab= deep link
- PersonnelTodayCard.js: worker name click → /employees/:id
- Fixed: calendar endpoint 500 error in hr.py

### Test: /app/test_reports/iteration_68.json — 100% frontend


## Apr 11, 2026 — Employee Dossier (Досие на служител)

### Backend: GET /api/employee-dossier/{worker_id}
- Aggregates: users + profiles + reports (old+new) + payroll_batches + advances + worker_calendar + rosters
- Returns: header, reports (flat lines), payroll (weekly), advances, calendar (daily), warnings

### Frontend: EmployeeDossierSection.js (4th tab in AllReportsPage)
- 4 tabs total: Всички отчети | Седмица | Заплати | Досие
- Worker picker: search + avatar cards → select worker
- Dossier header: photo, name, position, pay type, rate, active badge
- Summary: 4 cards (Общо часове | Изработено EUR | Платено EUR | Отчети)
- Inner tabs: Отчети (report lines) | Заплати (weekly payroll) | Календар (daily status) | Заеми (advances)
- Warnings: unpaid weeks, active loans, missing rate, no payroll status
- i18n: 47 BG + 47 EN keys

### Test: 100% backend (15/15) + 100% frontend
- /app/test_reports/iteration_67.json


## Apr 11, 2026 — Cash Result Fix: ONLY paid labor, no fallback

### Fix
- `effective_cash_labor = paid_labor_expense` (was: `paid if >0 else reported`)
- Cash out = paid labor only. If no paid allocations → labor cash out = 0
- New warning: "Има отчетен труд (X EUR), който още не е платен — не е включен в cash out"
- 1 file changed: project_financial_results.py (3 lines)


## Apr 11, 2026 — Paid Labor → Project Financial Results Integration

### Backend: compute_financial_results enriched
- New `labor` section: reported_labor_value, paid_labor_expense, paid_labor_hours, unpaid_approved_labor, labor_expense_basis, allocation_count
- Cash result now uses paid labor (from payroll_payment_allocations) when available
- Warnings: "Одобрен, но неплатен труд", "Има платен труд, но няма отчетен труд от work_sessions"
- Idempotency guard: double-pay blocked (400 "Already paid" + 409 "Allocations already exist")

### Frontend: FinancialResultsCard breakdown enriched
- New "ТРУД" section in breakdown: Отчетен труд (blue) | Платен труд (green highlight) | Неплатен одобрен (amber)
- Cash result card reflects paid labor in "Плащания"
- i18n: 4 new BG + 4 new EN keys (finResults.laborSection, reportedLabor, paidLabor, unpaidLabor)

### Test: 100% backend (18/18) + 100% frontend
- /app/test_reports/iteration_66.json


## Apr 11, 2026 — Payment Allocation (Paid → Project Expense)

### Core Logic
- On batch `Paid`: gross labor allocated back to projects from included report lines
- Allocation by value: each report line's gross = hours × hourly_rate → mapped to its project_id
- Deductions (loans, fines, rent) stay payroll-only — do NOT reduce project labor expense
- Project labor expense = sum of allocated_gross_labor from payroll_payment_allocations

### New Collection: payroll_payment_allocations
- Fields: id, org_id, payroll_batch_id, worker_id, worker_name, project_id, project_name
- allocated_hours, allocated_gross_labor, allocation_basis (value|hours)
- lines (array of {report_id, date, smr, hours, gross})
- week_start, week_end, paid_at, created_by, created_at

### New Endpoints
- `GET /api/payroll-batch/{id}/allocations` — allocations grouped by project with workers
- `GET /api/projects/{pid}/paid-labor` — total paid labor for a project (by_worker, by_week)

### UI: Allocation Summary in Payroll Tab
- Green card: "Разнесено по обекти" with project count badge + total EUR
- Per project: name, worker count, hours, gross EUR
- Disclaimer: "Брутната стойност на труда е разнесена обратно по обектите от включените отчети. Удръжките са само в заплатата."

### Traceability: batch → worker → report_lines → project (full chain)

### Test: 100% backend (15/15) + 100% frontend
- /app/test_reports/iteration_65.json


## Apr 11, 2026 — Payroll Batch (Заплати Съб→Пет)

### Backend: /api/payroll-batch/*
- `GET /eligible?week_of=` — approved+unpaid entries per worker per day
- `POST /` — create batch with included_days + adjustments
- `POST /{id}/pay` — mark batch paid, update report payroll_status
- `GET /list` — list all batches
- `GET /{id}` — single batch detail
- `POST /carry-forward?week_of=` — mark unbatched as carry_forward
- Model: payroll_batches collection (id, week_start/end, included_days, employee_summaries, totals, status)

### Frontend: PayrollBatchSection.js (third tab in AllReportsPage)
- 3 tabs: Всички отчети | Седмица | Заплати
- Week picker (Sat→Fri) with prev/next/today
- Day selection checkboxes (only days with data enabled)
- Summary cards: Общо часове | Брутно | Бонуси | Удръжки | Нетно
- Worker table: Дни, Часове, Норм., Извънр., Ставка, Брутно, Бонуси, Удръжки, Нетно
- Adjustments dialog: bonus, deduction, loan, rent, fine
- Worker detail modal with day breakdown
- Batch lifecycle: Създай пакет → Маркирай платен → Платен
- Value disclaimer: "Заплатата не е разход по обекта, докато не бъде платена и алокирана."
- i18n: 32 BG + 32 EN keys

### Test: 100% backend (23/23) + 100% frontend
- /app/test_reports/iteration_64.json


## Apr 11, 2026 — Weekly Matrix (Седмица Съб→Пет)

### Backend: GET /api/weekly-matrix
- `week_of` parameter finds containing Saturday→Friday payroll week
- Returns: rows (per worker), 7 day columns, totals
- Per day: hours, normal, overtime, entries array
- Per worker: total_hours, worked_days, hourly_rate, labor_value, bonuses, deductions, net_pay
- Grand totals: hours, normal, overtime, value, workers, workers_with_data

### Frontend: WeeklyMatrixSection.js (inside AllReportsPage tabs)
- Internal tabs: "Всички отчети" | "Седмица"
- Week picker: ← 11.04–17.04.2026 → | Днес
- Matrix: Служител | Съб | Нед | Пон | Вт | Ср | Чет | Пет | Общо ч. | Дни | Ставка | Труд | Бонуси | Удръжки | Нетно
- Day cells: hours + amber overtime badge (e.g. 50 + +42)
- Day detail modal: entries with СМР, обект, часове, статус
- ОБЩО ред + value disclaimer
- i18n: 21 BG + 21 EN keys

### Test: 100% backend (21/21) + 100% frontend
- /app/test_reports/iteration_63.json


## Apr 11, 2026 — New Main Tab: Всички отчети (All Reports)

### Backend: GET /api/all-reports
- Merges 2 report styles: new (technician portal flat) + old (structured day_entries)
- Enriches with user names/avatars, project names, hourly rates, labor values
- Filters: date_from, date_to, worker_id, project_id, smr, report_status, only_overtime
- Sorting: date, worker, hours, value, status (asc/desc)
- Pagination: page + page_size
- Summary: total_hours, normal_hours, overtime_hours, total_value, by_status breakdown

### Frontend: /all-reports (AllReportsPage.js)
- Summary cards: Общо часове | Нормални | Наднормени | Стойност по отчет (EUR)
- Status chips: Чернова (gray) | Подаден (blue) | Одобрен (green) | Отхвърлен (red)
- Table: 12 columns — Дата, Служител (avatar+name), Обект (link), СМР, Часове, Норм., Извънр., Ставка, Стойност, Статус, Заплата, Детайл
- Filters panel: дати, СМР, статус, само наднормено
- Detail modal: full breakdown + audit info + value disclaimer
- Sidebar: "Всички отчети" first item in "Дневник СМР" group

### Status Logic
- Report: Draft → Submitted → Approved / Rejected
- Payroll: none → eligible → batched → paid (future)
- Value disclaimer: "Стойност по отчет ≠ реален разход по проекта"

### Test: 100% backend (17/17) + 100% frontend
- /app/test_reports/iteration_62.json


## Apr 11, 2026 — Dashboard: Персонал днес

### New: Personnel Today Card
- **Backend**: `GET /api/dashboard/personnel-today` — aggregates 5 data sources (users, profiles, worker_calendar, site_daily_rosters, employee_daily_reports)
- **Counters**: Всички, На работа, С отчет, Без отчет, Болни, Отпуска, Самоотлъчка
- **Status rules**: working (roster/calendar), sick, leave, absent, unknown
- **Alerts**: Amber "на работа без отчет", Red "самоотлъчка", Gray "без статус"
- **Sorting**: Problems first (absent → unknown → working-no-report → working-with-report → sick → leave)
- **Per-person row**: avatar, name, position, status badge, site link, report indicator + hours
- **Amber highlight** on working-without-report rows
- **Click actions**: site name → project detail, "Виж всички" → employees page
- **Filtered**: test accounts excluded by email prefix
- **i18n**: 19 BG + 19 EN keys in new `personnel` namespace
- Test report: /app/test_reports/iteration_61.json (100% backend 12/12, 100% frontend)


## Apr 11, 2026 — Technician Wizard Review/Overtime Polish

### Enhanced Review Step (Step 3)
- **Day Summary card**: 4 quadrants — Хора, Общо часове, Нормални (green), Наднормени (amber)
- **Per-worker cards**: Avatar, name, activity count, total hours, normal/overtime breakdown
- **Overtime badge**: "Наднормено" amber badge when worker has >8h total
- **Warning card**: Amber AlertTriangle card showing count of workers with overtime
- **Activity lines**: SMR name + hours + notes shown under each worker card
- **Live recalculation**: Summary updates automatically when editing and returning to review
- **i18n**: Added 8 new BG + EN keys for overtime review (normalHours, overtimeHours, daySummary, etc.)
- Fixed i18n interpolation: `{count}` → `{{count}}` for i18next
- Test report: /app/test_reports/iteration_60.json (100% frontend 11/11)


## Apr 11, 2026 — Admin Field Mode Hardening & Verification

### Access Hardening
- **AdminRoute guard** in App.js: 60+ admin-only routes now protected with role check
- Non-admin roles (Technician, Worker, Driver, Viewer) redirected to `/tech` on direct URL access
- Protected routes: /employees, /finance, /payroll, /offers, /settings, /data/*, /reports/*, /overhead, etc.
- Allowed for all: /, /projects, /my-day, /attendance-history, /my-payslips, /tech, /notifications

### Audit Marker Propagation Fix
- `entered_by_admin`, `entry_mode`, `submitted_by` now propagated from `employee_daily_reports` to `work_sessions` on approval
- Previously only saved in draft, NOT in the source-of-truth `work_sessions` collection

### Verification (100% Pass)
- Backend: 8/8 pytest tests passed (/app/backend/tests/test_admin_field_mode.py)
- Frontend: 6/6 acceptance criteria verified via Playwright
- E2E: Admin → field portal → roster → report → approve → work_session with audit markers confirmed
- Route protection: /employees, /finance, /settings, /payroll all redirect to /tech for technician
- Test report: /app/test_reports/iteration_59.json


## Apr 10, 2026 — Phase 1 Core Closure (Фази 1.1-1.4)

### Phase 1.1: Roster (site_daily_rosters)
- 4 new endpoints: GET/POST roster, suggestions, copy-yesterday
- New collection: site_daily_rosters

### Phase 1.2: DRAFT Submit
- POST /technician/daily-report now creates DRAFTs in employee_daily_reports
- NO work_sessions created at submit time
- 2-step frontend: Roster → Report

### Phase 1.3: Approval = Posting Event
- POST /daily-reports/{id}/approve creates work_sessions + worker_calendar + slip_number
- POST /daily-reports/{id}/reject sets REJECTED, no sessions
- POST /daily-reports/{id}/reset voids sessions (flagged, not deleted)
- org_counters for per-org slip numbering

### Phase 1.4: Source of Truth Policy
- Created /app/memory/SOURCE_OF_TRUTH.md
- work_sessions = ONLY source of truth for labor cost
- employee_daily_reports = DRAFT input, NOT financial truth
- Code comments added at 3 key locations

### Also in this session:
- Technician activity dropdown: real data from 5 sources, priority-sorted, noise-filtered
- expected_actual: replaced hardcoded 25 with real avg_daily_wage


## Apr 9, 2026 — Integration Smoke Map
- Created /app/memory/INTEGRATION_MAP.md
- 5 integration chains mapped (field report→money, SMR→commercial, project/client/finance, materials/warehouse, location/group/SMR)
- Source-of-truth matrix (15 domains)
- 6 integration risk hotspots documented
- Safe extension points per domain
- Recommended order for next 9 improvements
- 0 code changes


# CHANGELOG

## Mar 11, 2026 (Session 26)
### HR FIX: Photo Crop + Position Field + Месечно/Акорд Pay Types
- **Photo crop**: ImageCropDialog with react-easy-crop — round crop, zoom slider, 300x300 JPEG output
- **File validation**: Only JPG/PNG/WebP accepted, max 10MB, clear error messages
- **Длъжност field**: New position field in create + edit forms, visible in detail header
- **Pay types**: Месечно + Акорд (пазарлък) — replaces old Daily/Hourly options
- **Акорд mode**: Shows akord_note field instead of monthly salary; no misleading formula
- **Месечно mode**: Full auto-calc (monthly / days = daily, daily / hours = hourly) with formula display
- **Backend**: position, akord_note added to EmployeeProfileCreate/Update; PAY_TYPES = ["Monthly", "Akord"]
- New: /app/frontend/src/components/ImageCropDialog.js
- Test report: /app/test_reports/iteration_40.json (100% backend 8/8, 100% frontend)

## Mar 11, 2026 (Session 25)
### HR FIX: New Employee Flow + Employee Photo/Avatar
- **"Нов служител" button**: In Employees list, opens create dialog
- **Create dialog**: Име, Фамилия, Имейл, Парола, Телефон, Роля + Заплащане (EUR) with auto-calc
- **After create**: Redirects to new employee detail page
- **Avatar**: Initials fallback (colored circle with 2 letters), supports uploaded photo
- **Photo upload**: Camera overlay on avatar in edit mode → uploads via /api/media/upload
- **Employees list columns**: Avatar | Име+email | Роля | Телефон | Тип | Ставка EUR | Статус
- **Backend**: avatar_url added to user queries, employees list returns phone/first_name/last_name
- Test report: /app/test_reports/iteration_39.json (100% backend 11/11, 100% frontend)

## Mar 10, 2026 (Session 24)
### HR FIX: Employee Editing + Phone + Salary + Auto Calculation
- **Edit mode**: "Редактиране" button on Employee Detail → full edit form with Save/Cancel
- **Basic fields**: Име, Фамилия, Телефон, Активен — via PUT /api/employees/{id}/basic
- **Pay fields**: Тип (Месечно/Дневно/Почасово), Месечна заплата EUR, Работни дни/мес, Часове/ден
- **Auto-calculation**: Monthly → Daily = monthly/22, Hourly = daily/8 (live in UI, green "(авто)")
- **Formula display**: "2200 EUR / 22 дни = 100 EUR/ден → 100 / 8ч = 12.5 EUR/ч"
- **View mode**: Pay info bar shows all rates in EUR + phone + type + active status
- **Backend**: working_days_per_month added to EmployeeProfileCreate/Update models
- **Backend**: PUT /api/employees/{id}/basic for name/phone/role updates
- Test report: /app/test_reports/iteration_38.json (100% backend 16/16, 100% frontend)

## Mar 10, 2026 (Session 23)
### P0 RECOVERY: Restore HR, Remove Hardcoded Rates, Switch to EUR, Keep Historical Base
- **HR restored**: Служители, Аванси, Заплати, Присъствие, Преглед отчети all verified working
- **Pricing settings**: New section in CompanySettingsPage — 8 worker categories with EUR rates
- **Org-specific rates**: GET/PUT /api/ai-config/hourly-rates loads from DB, not hardcoded
- **DEMO fallback**: Hardcoded rates renamed to DEMO_WORKER_RATES, clearly marked as "ДЕМО ставки"
- **EUR everywhere**: Default currency EUR in offers, imports, AI proposals; "лв" replaced with "EUR"
- **AI is_demo flag**: hourly_info includes is_demo=true/false so UI can show warning
- **Historical intact**: 331 rows, 22 categories, analytics page accessible
- Test report: /app/test_reports/iteration_37.json (100% backend 9/9)

## Mar 10, 2026 (Session 22)
### FOCUS PHASE 3: Pricing Rules + Materials Generation
- **AIPricingBreakdown component**: Reusable component showing type/subtype, worker rate badge, small qty badge, internal hint, explanation, collapsible materials list
- **Materials display**: Grouped by Основни/Спомагателни/Консумативи with estimated quantities and reasons
- **Pricing explanation**: Worker type + hourly rate + min-job indicator + small qty % + explanation text all visible
- **Materials saved**: batch-save now stores materials array from proposals (was empty before)
- **Both pages updated**: NovoSMRPage and OfferEditorPage AI dialog use AIPricingBreakdown
- New: /app/frontend/src/components/AIPricingBreakdown.js
- Test report: /app/test_reports/iteration_36.json (100% backend 12/12, 100% frontend)

## Mar 10, 2026 (Session 21)
### FINAL FIX: Source Link + Edit Mode + Clean Offer Detail (Polished)
- **Източник deep-link**: Clickable link navigates to Project page → scrolls to #extra-works-section showing source rows with unit prices
- **Scroll anchor**: `id="extra-works-section"` added to ExtraWorksDraftPanel for deep-link targeting
- **"Отвори в обекта →"**: Underlined primary-color helper text in source section
- **Clean import**: Removed unused ActivityBudgetsPanel import from OfferEditorPage
- **Hash scroll**: ProjectDetailPage auto-scrolls to anchor on load (e.g. #extra-works-section)
- All 9 requirements verified: source link, deep-link, values visible, edit button, full edit mode, budget removed, budget stays in project, no other modules touched

## Mar 10, 2026 (Session 20)
### FINAL FIX: Additional Offer Detail Screen Layout
- **Summary moved**: Right sidebar REMOVED for extra offers → horizontal summary strip above KSS table
- **Unified header**: offer_no + Допълнителна (amber) + status + version + project + source relation in one block
- **KSS columns rebuilt**: СМР | Тип | **Локация** (NEW) | Мярка | К-во | Мат/ед | Труд/ед | Материал | Труд | Общо
- **Full SMR text visible**: Wrapping enabled, no more "Шпакл..." fragments
- **Grouping default OFF** for extra offers (readability > compactness)
- **Source section**: "Източник: Допълнителни СМР" badge + count in horizontal strip
- **Location column**: Extracts Ет./Помещение/Зона from line notes for extra offers
- **Main offers unchanged**: Still use sidebar layout with grouping toggle
- Test report: /app/test_reports/iteration_34.json (100% frontend)

## Mar 10, 2026 (Session 19)
### FOCUS PHASE 2.1: Readability + Type Clarity for Additional Offers
- **Type badges everywhere**: "Основна" (blue) / "Допълнителна" (amber) in offers list, offer detail header, project page
- **Type filter**: Segmented buttons "Всички / Основни (60) / Допълнителни (4)" in offers list
- **Source relation**: Offer detail header shows "Създадена от N допълнителни СМР" for extra offers
- **KSS line notes**: Location/note text now visible under activity name in offer lines table
- **Column widths**: Reduced numeric column widths to give more space to activity descriptions
- **i18n fix**: NeedsRevision → "Корекция" translation added
- **Project page**: Extra offers block with amber border, amber offer_no, better layout
- Test report: /app/test_reports/iteration_33.json (100% frontend)

## Mar 10, 2026 (Session 18)
### FOCUS PHASE 2: Complete "Ново СМР" Flow
- **Dedicated page**: /projects/{id}/novo-smr — standalone for site walkthrough extra works
- **Multi-row input**: Description + unit + qty + location (floor/room/zone) per row, add/remove/duplicate
- **Single AI action**: "Анализирай с AI (N реда)" processes all rows with two-stage (fast+LLM)
- **Editable proposals**: Per-row checkboxes, inline editing of all fields, provider/confidence badges
- **Smart info**: Hourly rate badges, internal price hints, small qty adjustments, location display
- **Save options**: "Чернова" (draft) or "Запази като готово" (ready) — saves to extra_work_drafts with batch_id
- **Recalculate**: "Редактирай и пресметни" returns to input phase preserving edits
- **Enter key**: Adds new row when pressing Enter on last row
- Entry point: "Ново СМР" button in ProjectDetailPage header → navigates to dedicated page
- New: /app/frontend/src/pages/NovoSMRPage.js
- Test report: /app/test_reports/iteration_32.json (100% backend 16/16, 100% frontend)

## Mar 9, 2026 (Session 17)
### FOCUS PHASE 1: Complete AI Offer Module Core to Usable MVP
- **Multi-line AI input** in Offer Editor: add/remove lines with description + unit + qty
- **Two-stage analysis**: Fast rule-based (~0.2s) → LLM refinement (auto-merge in background)
- **Fully editable proposals**: description, unit, qty, material price, labor price — all inline editable
- **Provider badges**: Rule/LLM + confidence % + type/subtype
- **Historical hints**: Internal price range badge when historical data exists
- **Hourly rate badges**: worker type + rate + min applied indicator
- **Recalculate flow**: "Обратно към входа" → edit → re-analyze
- **Batch add**: "Добави N ред в офертата" adds all accepted lines to offer
- Replaced old single-line AI dialog with production-ready multi-line panel
- Test report: /app/test_reports/iteration_31.json (100% backend 11/11, 100% frontend)

## Mar 9, 2026 (Session 16)
### P1: BLOCK C — HR/Attendance/Payroll Improvements
- **Employee Detail Page**: /employees/{id} with 4 tabs: Calendar, Обекти, Присъствия, Заплащане
- **Personal Calendar**: Monthly grid view with attendance status (Present/Absent), project codes, hours per day
- **Hours Summary**: Current month days + hours in header
- **Project History**: Per-employee table with project code, role, days, hours, last attendance
- **Pay Info Bar**: Pay type (Daily/Hourly/Monthly), rate, hours/day, active status
- **Payroll Tab**: Recent payslips with gross/net/status
- **Clickable Employees**: EmployeesPage rows navigate to detail page
- New: /app/frontend/src/pages/EmployeeDetailPage.js
- Backend: GET /api/employees/{id}/dashboard + GET /api/employees/{id}/calendar
- Test report: /app/test_reports/iteration_30.json (100% backend 19/19, 100% frontend)

## Mar 9, 2026 (Session 15)
### P1: BLOCK B — Historical Offer Intelligence
- **Historical Import**: POST /api/historical/import-preview (parse XLSX + normalize) + POST /api/historical/import-confirm (save)
- **Normalization Layer**: NORMALIZATION_MAP (25+ keywords → type/subtype), SECTION_KEYWORDS filter, unit normalization
- **Analytics**: GET /api/historical/analytics — median/avg/min/max by category/city/unit with sample counts
- **Internal Price Base**: get_internal_price_hint() — lookups historical median for AI merge
- **AI Merge**: AI proposals now include internal_price_hint field (available, median, range, sample_count)
- **Frontend**: /historical-offers page with overview cards, comparative tables, import dialog
- New backend: /app/backend/app/routes/historical_offers.py
- New frontend: /app/frontend/src/pages/HistoricalOffersPage.js
- Test report: /app/test_reports/iteration_29.json (100% backend 15/15, 100% frontend)

## Mar 9, 2026 (Session 14)
### P0: BLOCK A — Offer Import / Export
- **PDF Export**: GET /api/offers/{id}/pdf — clean A4 PDF with company info, lines (material+labor), totals, DejaVu font
- **XLSX Export**: GET /api/offers/{id}/xlsx — structured spreadsheet with headers, line data, totals
- **Import Template**: GET /api/offer-import-template — template with example rows + instructions sheet
- **Import Preview**: POST /api/offers/import-preview — parses XLSX, auto-detects columns, returns warnings
- **Import Confirm**: POST /api/offers/import-confirm — creates offer from previewed lines
- **Frontend**: OfferEditorPage has PDF+Excel export buttons; OffersListPage has Шаблон+Импорт+Нова оферта
- **Import Dialog**: File upload → preview table → project select → confirm
- Works for both main and extra offers; handles Bulgarian units (м2, бр, часа)
- Test report: /app/test_reports/iteration_28.json (100% backend 16/16, 100% frontend)

## Mar 9, 2026 (Session 13)
### Roadmap Update + Three-Block Audit
- **Updated Master Roadmap** with 3 new priority blocks: A (Offer Import/Export), B (Historical Intelligence), C (HR/Attendance/Payroll)
- **Full audit** of all three blocks: what exists, what's missing, what's scattered
- **BLOCK A audit**: No offer export/import exists, but PDF+XLSX patterns ready (invoice PDF, finance XLSX)
- **BLOCK B audit**: AI infrastructure ready (hybrid LLM, calibration, knowledge base), but no historical ingest pipeline
- **BLOCK C audit**: 70-80% complete (43 endpoints, 10 pages, 3093 lines), missing calendar/employee detail/hours report
- **Recommendation**: BLOCK A first (P0, prerequisite for B, quick to build on existing patterns)

## Mar 9, 2026 (Session 12)
### P1/P2: Two-Stage AI for Extra Works and Offer AI Assist
- **Stage A (Fast)**: POST /api/extra-works/ai-fast — rule-based, ~0.15s, instant usable proposals
- **Stage B (Refine)**: POST /api/extra-works/ai-refine — LLM via GPT-4.1-mini, ~15-20s, richer results
- **Non-blocking UX**: Fast results appear immediately, user can edit while LLM refines in background
- **Smart merge**: User-edited fields protected from LLM overwrite (userEditedFields tracking)
- **Apply refinement**: "Приеми LLM подобрения" button (global) + per-line "Приеми LLM" links
- **Stage badges**: "Бърз анализ" → "LLM уточняване..." (pulsing) → "LLM уточнено" ✓ / "LLM недостъпен" ⚠
- **Fallback**: If LLM fails, fast proposal remains fully usable
- Test report: /app/test_reports/iteration_27.json (100% backend 10/10, 100% frontend)

## Mar 9, 2026 (Session 11)
### P0/P1: Editable AI Proposals + Multi-line Entry + Hourly Rate Logic
- **Multi-line entry**: Add/remove/duplicate lines in ExtraWorkModal, each with location fields
- **Batch AI**: POST /api/extra-works/ai-batch processes N lines, returns per-line proposals + combined materials
- **Editable proposals**: All pricing fields editable before accept (type, subtype, material/labor price, qty)
- **Related SMR selection**: Clickable chips to select which related works to include
- **Editable material checklist**: Add/remove/edit materials per line with category badges
- **Hourly rates**: 8 worker types (15-28 лв/ч) with min_hours and min_job_price
- **Small qty pricing**: min_job_price applied when estimated labor < minimum and qty <= 10
- **Batch save**: POST /api/extra-works/batch-save with batch_id grouping
- **Combined materials summary**: Deduplicated across all lines
- Test report: /app/test_reports/iteration_26.json (100% backend 15/15, 100% frontend)

## Mar 9, 2026 (Session 10)
### P1: Inventory Dashboard + Stock Alerts + Warehouse Visibility
- **Dashboard**: /inventory with 7 overview cards (materials, value, low stock, on projects, recent movements)
- **Stock table**: Search + low stock filter + threshold + status badges (OK/Ниско)
- **Low stock alerts**: Configurable threshold per material (default 5), PUT /api/inventory/threshold
- **Movement insights**: Top moved materials (intake/issue/return counts)
- **Project remainders**: Materials sitting on projects with remaining quantities
- **3 tabs**: Наличности | Движения | По обекти
- New frontend: /app/frontend/src/pages/InventoryDashboardPage.js
- Test report: /app/test_reports/iteration_25.json (100% backend 12/12, 100% frontend)

## Mar 9, 2026 (Session 9)
### P1: Main Warehouse → Project Allocation + Consumption + Remaining Stock Control
- **Warehouse Issue**: POST /api/warehouse-issue with stock validation (prevents over-issue)
- **Stock Balance**: GET /api/warehouse-stock computes: intake + returns - issues
- **Consumption**: POST /api/project-consumption with project-available validation
- **Return**: POST /api/warehouse-return with project-available validation
- **Material Ledger**: GET /api/project-material-ledger/{id} - requested/purchased/issued/consumed/returned/remaining
- **Warnings**: under_purchased, not_consumed, high_remaining
- **Frontend**: ProjectMaterialLedger component with 3 action buttons + warnings + comparison table
- Test report: /app/test_reports/iteration_24.json (100% backend 16/16, 100% frontend)

## Mar 9, 2026 (Session 8)
### P0/P1: Material Requests + Supplier Invoice Intake + Main Warehouse Posting
- **Material Requests**: CRUD with auto-numbering (MR-XXXX), from-offer generation (incl. AI checklist materials), project/stage linking
- **Supplier Invoices**: Create → Review/Correct (lines with discount) → Post to Warehouse
- **Warehouse Posting**: Auto-creates Main Warehouse, creates intake transaction with full line details + links
- **Procurement Page**: /procurement with tabs (Заявки + Входящи фактури), create/review/post dialogs
- **Linking**: warehouse_transaction → supplier_invoice → material_request → offer → project
- **OCR**: Manual-first review (AI-ready architecture for future M6)
- New backend: /app/backend/app/routes/procurement.py
- New frontend: /app/frontend/src/pages/ProcurementPage.js
- Test report: /app/test_reports/iteration_23.json (100% backend 20/20, 100% frontend)

## Mar 9, 2026 (Session 7)
### P0/P1: Extra Offers Send + Approval + Version Tracking
- **Send flow**: POST /api/offers/{id}/send generates review_token, creates auto version snapshot, records event
- **Public review page**: /offers/review/{token} - standalone, no auth, shows lines/totals/company/project
- **Client actions**: Approve (→Accepted), Reject (→Rejected), Request revision (→NeedsRevision)
- **Event history**: offer_events collection tracks sent/viewed/approved/rejected/revision events
- **Version snapshots**: Auto-created in offer_versions on send (is_auto_backup=True)
- **Project visibility**: Extra offers section in ProjectDetailPage with status badges
- **Copy link**: "Копирай линк" button in OfferEditorPage copies review URL
- New frontend page: OfferReviewPage.js (public route)
- Test report: /app/test_reports/iteration_22.json (100% backend 15/15, 100% frontend)

## Mar 9, 2026 (Session 6)
### In-App Admin Notifications for AI Calibration Readiness
- **Trigger**: When calibration category reaches >=10 samples, Admin gets in-app notification
- **Anti-duplicate**: Unique key prevents duplicate notifications per category/city/small_qty
- **Resolve on approve**: Notification auto-resolved (read=True, resolved=True) when admin approves calibration
- **New cycle**: After revoke + new data, new notification created
- **Frontend**: Violet Sparkles icon, "Отвори калибрация" deep link to /ai-calibration
- Test report: /app/test_reports/iteration_21.json (100% backend 6/6, 100% frontend)

## Mar 8, 2026 (Session 5)
### Learning Loop + Price Calibration Analytics
- **Data capture**: ai_calibration_events records AI vs user price deltas for every proposal
- **Analytics dashboard**: /ai-calibration with overview cards, category breakdown, filters
- **Controlled calibration**: observation→suggested→ready→approved with admin approval
- **Safety**: min 5/10 samples, outlier >200% skipped, trimmed median
- **Auto-apply**: Approved calibrations adjust AI prices transparently (base×factor=calibrated)
- Test report: /app/test_reports/iteration_20.json (100% backend 16/16, 100% frontend)

## Mar 8, 2026 (Session 4)
### Real LLM Integration for AI Offers (Hybrid Mode)
- **Hybrid Provider**: LLM (GPT-4.1-mini via emergentintegrations) primary → rule-based fallback on error
- **City-aware pricing**: CITY_PRICE_FACTORS (София=1.15, Пловдив=1.00, Варна=1.05, etc.)
- **Data capture**: ai_provider_used, ai_raw_response_summary, ai_confidence stored in drafts
- **Frontend**: Provider badge (LLM/Rule-based), explanation text, city factor display, fallback reason
- **NOT MOCKED**: Real LLM calls via EMERGENT_LLM_KEY
- Test report: /app/test_reports/iteration_19.json (100% backend 14/14, 100% frontend)

## Mar 8, 2026 (Session 3)
### P0/P1 MVP: AI Offers + Extra Works Draft Flow
- **New backend**: /app/backend/app/routes/extra_works.py with 7 API endpoints
- **AI Proposal**: Rule-based construction knowledge base (7 categories, materials checklist, related SMR, small qty pricing)
- **Fast Entry**: ExtraWorkModal with location fields (floor/room/zone) + AI proposal panel
- **Draft Bucket**: ExtraWorksDraftPanel with select/create-offer workflow
- **Create Extra Offer**: Groups selected drafts into new offer, transitions status to "converted"
- **Offer Editor AI**: "AI помощ" button adds lines with AI-suggested prices
- **MOCKED**: AI is rule-based (no external LLM calls) - ready for future integration
- Test report: /app/test_reports/iteration_18.json (100% backend 18/18, 100% frontend)

## Mar 8, 2026 (Session 2)
### P0: Complete Invoice Workflow Fix
- **Invoice → Project Link**: "Към обекта" button in header navigates to linked project
- **PDF Export**: GET /api/finance/invoices/{id}/pdf - reportlab with DejaVu Cyrillic font, clean A4 layout
- **Full Editing**: Sent/PartiallyPaid/Overdue editable. Paid/Cancelled blocked. Line edits recalculate remaining with existing payments
- **ROOT FIX - Payment→Project Sync**: Project dashboard used non-existent fields (total_ex_vat, client_id). Fixed to use paid_amount, remaining_amount, counterparty_name. Balance.income now aggregates from actual payments, not just Paid status
- **Project Invoice Table**: New columns (Статус badge, Общо, Платено, Остатък). Old broken columns (paid_ex_vat etc.) removed
- **UX Header**: Ordered buttons: Запази, Към обекта, PDF, Добави плащане, Анулирай, Изтрий
- Test report: /app/test_reports/iteration_17.json (100% backend, 100% frontend, 16 tests)

## Mar 8, 2026
### P0: Invoice Numbering Verification
- Verified auto-numbering system with 7 test scenarios
- Start number 1000, sequential INV-1000/1001/1002
- No duplicates, no re-numbering on re-open
- Settings UI at Company Settings → Invoice Numbering

### P0: Invoice Payments + Automatic Invoice Status Logic
- New API: POST /api/finance/invoices/{id}/payments (quick-pay: creates payment + allocation in one step)
- New API: GET /api/finance/invoices/{id}/payments (payment history)
- New API: DELETE /api/finance/invoices/{id}/payments/{alloc_id} (remove payment with status recalc)
- Automatic status transitions: Draft → Sent → PartiallyPaid → Paid / Overdue → Cancelled
- Status recalculation on payment add/remove (incl. Paid → PartiallyPaid → Sent/Overdue)
- Over-payment prevention
- Frontend: Inline payment dialog with quick-pay buttons (full, 50%)
- Frontend: Payment history panel with details
- Frontend: Progress bar and payment summary in sidebar
- Frontend: Bulgarian status labels
- Fix: update_invoice_status correctly handles reverting from PartiallyPaid when all payments removed
- Test report: /app/test_reports/iteration_16.json (100% backend, 100% frontend)


## Apr 9, 2026 — Contract Freeze & Guardrails
- Created /app/memory/CONTRACTS.md — protected modules, API contracts, safe extension points, risk list
- 0 code changes. Documentation-only guardrails step.

## Apr 7-9, 2026 — Session 2 (28 tasks)
### Backend Modules Built (20):
Missing SMR, Location Tree, SMR Analysis, Live Pricing Engine, WorkSession/SiteClock, Budget Labor Forecast, Weekly Payroll + Contract Payments, Extended Project Details, SMR Groups, Missing SMR Two Flows, Project P&L Dashboard, KSS Excel Import/Export, Price Modifiers, Realtime Overhead, Site Pulse, Centralized Alarms, Technician Mobile, Client Summary, Error Handler Middleware, Pagination Helper

### Frontend Tasks (8):
Sidebar Restructure, ProjectDetailPage Tabs, Dashboard Integration, Project Context, Client Detail Page, Technician Dashboard, Worker Calendar Page, Alarms Dashboard Page

### Stats: ~200 tests, ~300 i18n keys, 15 new test files, 12 new collections

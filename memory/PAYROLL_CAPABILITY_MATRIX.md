# BEG_Work Payroll Capability Matrix
## Generated: 2026-04-13

---

## EXECUTIVE SUMMARY

BEG_Work has **3 parallel payroll layers** that evolved incrementally:

| Layer | File | Collections | Status |
|-------|------|-------------|--------|
| **hr.py (legacy)** | payroll_runs, payslips | `payroll_runs`, `payslips`, `payroll_payments` | Legacy, sidebar demoted |
| **payroll_batch.py (v2)** | payroll_batches, payroll_payment_allocations | `payroll_batches`, `payroll_payment_allocations` | Active in "Отчети > Заплати" tab |
| **pay_runs.py (v3)** | pay_runs, payment_slips, pay_run_allocations | `pay_runs`, `payment_slips`, `pay_run_allocations` | **Primary**, sidebar "Разплащане" |

**v3 (pay_runs.py)** is the most complete and is the de-facto production system.
**v2 (payroll_batch.py)** still feeds `project_financial_results.py` via `payroll_payment_allocations`.
**v1 (hr.py legacy)** is demoted from sidebar but routes still exist at `/payroll`.

---

## CAPABILITY MATRIX

| # | Function / Capability | pay_runs.py (v3) | payroll_batch.py (v2) | hr.py (v1 legacy) | Frontend Entry | Mongo Collections | In Production UI? | Criticality | Missing if frozen? | Target Layer |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Generate payroll preview** | ✅ GET /pay-runs/generate (multi pay-type, day_cells, overlap warning) | ✅ GET /payroll-batch/eligible (Sat→Fri week, approved+unpaid) | ✅ POST /payroll-runs/{id}/generate (monthly, work_sessions based) | PayRunsPage "Ново разплащане" | employee_daily_reports, employee_profiles, users, projects, pay_runs | YES (v3) | CRITICAL | v3 has fullest engine | payroll_generation_service |
| 2 | **Eligible approved reports** | ✅ via report_normalizer (new+old style) | ✅ via report_normalizer + payroll_status filter | ✅ via work_sessions (different source!) | PayRunsPage grid / PayrollBatchSection | employee_daily_reports | YES | CRITICAL | v2/v3 share normalizer | payroll_generation_service |
| 3 | **Freeze rate at batch** | ✅ frozen_hourly_rate, frozen_daily_rate, rate_frozen_at | ✅ frozen_hourly_rate (added in v2.1) | ❌ Uses current profile rate | PayRunsPage | pay_runs.employee_rows / payroll_batches.employee_summaries | YES (v3) | CRITICAL | v1 has no freeze | payroll_generation_service |
| 4 | **Multi pay-type earned calc** | ✅ calc_earned(): hourly/daily/monthly/akord/mixed + formula | ❌ _calc_rate(): hourly fallback only | ❌ Fixed hourly from work_sessions | PayRunsPage | employee_profiles | YES (v3) | CRITICAL | v2/v1 can't do daily/monthly/akord | payroll_generation_service |
| 5 | **Gross/Net calculation** | ✅ earned + bonuses - deductions - previously_paid - paid_now | ✅ gross + bonuses - deductions | ✅ gross_pay - deductions = net_pay | PayRunsPage Step 2+3 | pay_runs / payroll_batches / payslips | YES (v3) | CRITICAL | All have it | payroll_payment_service |
| 6 | **Partial pay** | ✅ Step 3: editable paid_now_amount per employee | ❌ All-or-nothing batch | ❌ Per-payslip mark-paid | PayRunsPage Step 3 | pay_runs | YES (v3) | IMPORTANT | v2/v1 can't do partial | payroll_payment_service |
| 7 | **Reopen** | ✅ POST /pay-runs/{id}/reopen (batch + row level, version history) | ❌ No reopen | ❌ No reopen (delete only) | PayRunsPage detail modal | pay_runs | YES (v3) | IMPORTANT | v2/v1 can't reopen | payroll_payment_service |
| 8 | **Draft / multi-step** | ✅ draft → confirmed → paid (3-step: days → adjustments → payment) | ❌ Direct create as batched | ❌ Direct create + generate | PayRunsPage | pay_runs | YES (v3) | IMPORTANT | v2/v1 no drafts | payroll_payment_service |
| 9 | **Carry forward** | ✅ remaining_after_payment preserved per employee | ✅ POST /payroll-batch/carry-forward | ❌ No concept | PayRunsPage | pay_runs / payroll_batches | YES (v3) | IMPORTANT | v1 loses unpaid tracking | payroll_payment_service |
| 10 | **Day selection** | ✅ Weekly grid with per-day per-employee checkboxes | ❌ Day selection via included_days list | ❌ No day selection | PayRunsPage grid | pay_runs | YES (v3) | IMPORTANT | v2 has basic day list | payroll_payment_service |
| 11 | **Day edit / override** | ✅ Double-click day cell → edit hours/value/reason | ❌ No day edit | ❌ No day edit | PayRunsPage | pay_runs (dayOverrides in frontend) | YES (v3) | OPTIONAL | Only v3 | payroll_payment_service |
| 12 | **Adjustments (advance/loan/deduction/bonus)** | ✅ Step 2: typed adjustment rows per employee | ✅ Per-employee bonuses/deductions in batch | ✅ set-deductions per payslip | PayRunsPage Step 2 / PayrollBatchSection | pay_runs / payroll_batches / payslips | YES (v3) | IMPORTANT | All have some version | payroll_payment_service |
| 13 | **Project allocation** | ✅ pay_run_allocations: proportional per day/site with validation | ✅ payroll_payment_allocations: per batch (used by financial_results!) | ❌ No allocation | PayRunsPage detail | pay_run_allocations / payroll_payment_allocations | YES (both) | CRITICAL | **v2 feeds finance!** v3 allocations not yet in finance | payroll_allocation_service |
| 14 | **Paid labor for finance** | ❌ **NOT connected** to project_financial_results | ✅ **CONNECTED** via payroll_payment_allocations → project_financial_results.py | ❌ Not connected | FinancialResultsCard | payroll_payment_allocations | YES (v2) | **CRITICAL** | **If v2 frozen, finance loses paid labor!** | payroll_allocation_service |
| 15 | **Slip generation** | ✅ payment_slips created at confirm | ❌ No separate slips (data in batch) | ✅ payslips created at generate | PayRunsPage slips tab / MyPayslipsPage | payment_slips / payslips | YES (v3+v1) | IMPORTANT | Different collections! | payroll_document_service |
| 16 | **Slip PDF / Print** | ✅ GET /payment-slips/{id}/pdf + browser print (group/individual/selected) | ✅ PayslipDialog (batch-based view) | ❌ No PDF | PayRunsPage detail / PayslipDialog | payment_slips | YES (v3) | IMPORTANT | v2 has dialog only | payroll_document_service |
| 17 | **Employee payroll weeks** | ✅ GET /payroll-weeks (deduped per employee per week) | ❌ No weeks view | ❌ No weeks view | PayRunsPage "Седмици" / EmployeeDetailPage "Заплати" | pay_runs | YES (v3) | IMPORTANT | Only v3 | payroll_generation_service |
| 18 | **Employee dossier payroll tab** | ✅ EmployeeDetailPage "Заплати" reads /payroll-weeks | ✅ employee_dossier.py reads payroll_batches for weeks | ❌ EmployeeDetailPage "Фишове" reads legacy /payslips | EmployeeDetailPage | pay_runs + payroll_batches | YES (both) | IMPORTANT | Dossier reads both | payroll_generation_service |
| 19 | **Monthly calendar** | ✅ PayRunsPage "Месечен" tab (deduped, validated) | ❌ No monthly view | ❌ No monthly view | PayRunsPage | pay_runs | YES (v3) | IMPORTANT | Only v3 | payroll_generation_service |
| 20 | **Overlap warning** | ✅ warnings[] in generate response | ❌ Checks existing_batch but no warning | ❌ No overlap check | PayRunsPage | pay_runs | YES (v3) | OPTIONAL | Only v3 | payroll_generation_service |
| 21 | **Payroll status → reports** | ❌ Not yet (pay_runs don't update report payroll_status) | ✅ Updates employee_daily_reports payroll_status on batch/pay | ✅ No status sync | — | employee_daily_reports | YES (v2) | IMPORTANT | **v2 does this, v3 doesn't!** | payroll_payment_service |
| 22 | **Version history / audit** | ✅ history[] array with version, action, reason, totals_snapshot | ❌ No history | ❌ No history | PayRunsPage history dialog | pay_runs | YES (v3) | IMPORTANT | Only v3 | payroll_payment_service |
| 23 | **Allocation validation** | ✅ allocation_method, validation.match, rounding_adjustment | ❌ Basic allocation_basis field | ❌ None | PayRunsPage detail | pay_run_allocations | YES (v3) | OPTIONAL | Only v3 | payroll_allocation_service |
| 24 | **Payment method/reference/note** | ❌ Not yet | ❌ Not yet | ✅ payment_method, payment_reference, paid_by in payslips | — | payslips | NO | OPTIONAL | Missing everywhere except v1 | payroll_payment_service |
| 25 | **Payment journal record** | ❌ Not yet | ❌ Not yet | ❌ Not yet | — | — | NO | OPTIONAL | Missing in all | payroll_payment_service |
| 26 | **My Payslips (worker self-view)** | ❌ Not connected | ❌ Not connected | ✅ MyPayslipsPage reads /payslips | MyPayslipsPage | payslips | YES (v1) | IMPORTANT | **If v1 frozen, workers lose payslip view!** | payroll_document_service |
| 27 | **Old payroll runs CRUD** | ❌ N/A | ❌ N/A | ✅ Full CRUD: create/generate/finalize/delete | PayrollRunsPage, PayrollDetailPage | payroll_runs, payslips | Demoted (sidebar hidden) | LEGACY | Only historical data | legacy_read_only |

---

## RISKS

### R1: Finance depends on v2 allocations, NOT v3
`project_financial_results.py` reads `payroll_payment_allocations` (v2 collection).
`pay_run_allocations` (v3 collection) is NOT connected to finance.
**If v2 is frozen without migrating finance → paid labor disappears from project P&L.**

### R2: Report payroll_status updated only by v2
`payroll_batch.py` marks `employee_daily_reports.payroll_status = "batched"/"paid"`.
`pay_runs.py` does NOT update report statuses.
**If v2 is frozen → report lines never get marked as paid.**

### R3: Worker self-view (MyPayslipsPage) reads v1
Workers see their payslips via `/payslips` (v1 collection).
v3 writes to `payment_slips` (different collection).
**If v1 is frozen → workers lose their payslip access.**

### R4: Employee dossier reads both v2 and v3
`employee_dossier.py` reads `payroll_batches` (v2).
`EmployeeDetailPage` reads `/payroll-weeks` (v3) and `/payment-slips` (v3).
**Mixed data sources could show inconsistent numbers.**

### R5: Dedup assumes latest pay_run_number wins
Frontend dedup uses `pay_run_number` string comparison.
This works for PR-0001...PR-9999 but may break at PR-10000+.

---

## RECOMMENDATIONS

### A) Minimal safe direction for unification:
**Keep v3 as primary. Wire v3 outputs into v2's downstream consumers.**
- pay_run → after confirm → also write to `payroll_payment_allocations` (v2 format)
- pay_run → after confirm → also update `employee_daily_reports.payroll_status`
- payment_slips → also write to `payslips` (v1 format) for MyPayslipsPage
This preserves all 3 layers reading correctly without breaking anything.

### B) 5 functions that WILL be lost if 2 of 3 are hastily frozen:

| If frozen | Lost function |
|-----------|---------------|
| v2 (payroll_batch) | 1. **Project paid labor in finance** (P&L shows 0 paid labor) |
| v2 (payroll_batch) | 2. **Report payroll_status updates** (reports never marked "paid") |
| v1 (hr.py payroll) | 3. **Worker self-view payslips** (MyPayslipsPage breaks) |
| v1 (hr.py payroll) | 4. **Payment method/reference tracking** (no cash/bank/reference) |
| v3 (pay_runs) | 5. **Multi-step editable workflow** (draft/reopen/version history) |

### C) Target unified payroll model:

```
payroll_service/
├── generation/          ← calc_earned(), report normalizer, freeze, overlap check
├── payment/             ← draft/confirm/partial/reopen, adjustments, version history
├── allocation/          ← day/site proportional split → writes to BOTH pay_run_allocations AND payroll_payment_allocations
├── documents/           ← slips (writes to BOTH payment_slips AND payslips), PDF, print
└── sync/                ← updates employee_daily_reports.payroll_status, feeds project_financial_results
```

### D) Next smallest safe implementation prompt:

```
ЗАДАЧА: Wire v3 pay_runs into downstream v2 consumers without changing UI.

1. In pay_runs.py create_pay_run(), after generating pay_run_allocations:
   - Also create payroll_payment_allocations records (v2 format)
   - This makes project_financial_results.py see v3 payments

2. In pay_runs.py create_pay_run(), after confirm:
   - Update employee_daily_reports.payroll_status = "paid" for included report IDs

3. In pay_runs.py create_pay_run(), after generating payment_slips:
   - Also write to payslips collection (v1 format) for MyPayslipsPage

4. Test: verify project finance shows v3 paid labor
5. Test: verify reports show payroll_status = paid
6. Test: verify MyPayslipsPage shows v3 slips
```

---

## VERIFIED ROUTES

| Route | Status |
|-------|--------|
| /pay-runs | ✅ Active, primary |
| /pay-runs (Месечен tab) | ✅ Active |
| /pay-runs (Седмици tab) | ✅ Active |
| /pay-runs (История tab) | ✅ Active |
| /pay-runs (Фишове tab) | ✅ Active |
| /all-reports (Заплати tab) | ✅ Active (v2) |
| /payroll | ⚠ Demoted, still accessible |
| /my-payslips | ✅ Active (v1 data) |
| /employees/:id?tab=payroll-weeks | ✅ Active (v3 data) |

**WEB Preview**: https://client-registry-17.preview.emergentagent.com/pay-runs

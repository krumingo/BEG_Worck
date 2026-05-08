# BEG_Work Payroll Module — Production Readiness Checklist
## Generated: 2026-04-13

---

## A) EXECUTIVE SUMMARY

The payroll module has 3 layers (v1/v2/v3). v3 `pay_runs` is the primary production system with full lifecycle support. v2 `payroll_batch` feeds project finance via the sync adapter. v1 `hr.py` feeds worker self-view. After E2E verification and test data cleanup, the system is ready for controlled production use.

**Recommendation: Freeze v1/v2 WRITE paths, keep READ paths, make v3 the sole write authority.**

---

## B) CHECKLIST: All Payroll Routes

### v3 pay_runs.py — PRIMARY (13 routes)

| Route | Method | Purpose | Status | Freeze? |
|-------|--------|---------|--------|---------|
| `/pay-runs/generate` | GET | Preview payroll | **ACTIVE** | Keep |
| `/pay-runs` | POST | Create/confirm pay run | **ACTIVE** | Keep |
| `/pay-runs` | GET | List pay runs | **ACTIVE** | Keep |
| `/pay-runs/{id}` | GET | Get single run | **ACTIVE** | Keep |
| `/pay-runs/{id}/mark-paid` | POST | Mark paid + sync | **ACTIVE** | Keep |
| `/pay-runs/{id}` | PATCH | Update draft/reopened | **ACTIVE** | Keep |
| `/pay-runs/{id}/reopen` | POST | Reopen run | **ACTIVE** | Keep |
| `/pay-runs/{id}/history` | GET | Version history | **ACTIVE** | Keep |
| `/pay-runs/{id}/allocations` | GET | Allocation detail | **ACTIVE** | Keep |
| `/payment-slips` | GET | List v3 slips | **ACTIVE** | Keep |
| `/payment-slips/{id}` | GET | Get slip | **ACTIVE** | Keep |
| `/payment-slips/{id}/pdf` | GET | PDF export | **ACTIVE** | Keep |
| `/payroll-weeks` | GET | Weekly aggregation | **ACTIVE** | Keep |

### v2 payroll_batch.py — SYNC TARGET (9 routes)

| Route | Method | Purpose | Status | Freeze? |
|-------|--------|---------|--------|---------|
| `/payroll-batch/eligible` | GET | Eligible entries | **LEGACY** | **FREEZE** (replaced by /pay-runs/generate) |
| `/payroll-batch` | POST | Create batch | **LEGACY** | **FREEZE** (replaced by POST /pay-runs) |
| `/payroll-batch/list` | GET | List batches | READ-ONLY | Keep read |
| `/payroll-batch/{id}` | GET | Get batch | READ-ONLY | Keep read |
| `/payroll-batch/{id}/pay` | POST | Mark paid | **LEGACY** | **FREEZE** (v3 sync does this) |
| `/payroll-batch/carry-forward` | POST | Carry forward | **LEGACY** | **FREEZE** (v3 handles remaining) |
| `/payroll-batch/{id}/allocations` | GET | Get allocations | READ-ONLY | Keep read |
| `/projects/{id}/paid-labor` | GET | Project paid labor | READ-ONLY | Keep read |
| `/payslip/{batch_id}/{worker_id}` | GET | Old payslip view | READ-ONLY | Keep read |

### v1 hr.py payroll — LEGACY (13 routes)

| Route | Method | Purpose | Status | Freeze? |
|-------|--------|---------|--------|---------|
| `/payroll-runs` | GET | List legacy runs | READ-ONLY | Keep read |
| `/payroll-runs` | POST | Create legacy run | **LEGACY** | **FREEZE** |
| `/payroll-runs/{id}` | GET | Get legacy run | READ-ONLY | Keep read |
| `/payroll-runs/{id}/generate` | POST | Generate payslips | **LEGACY** | **FREEZE** |
| `/payroll-runs/{id}/finalize` | POST | Finalize run | **LEGACY** | **FREEZE** |
| `/payroll-runs/{id}` | DELETE | Delete run | **LEGACY** | **FREEZE** |
| `/payslips` | GET | List payslips (self-view!) | **ACTIVE** | Keep (worker self-view!) |
| `/payslips/{id}` | GET | Get payslip | **ACTIVE** | Keep |
| `/payslips/{id}/set-deductions` | POST | Set deductions | **LEGACY** | **FREEZE** |
| `/payslips/{id}/mark-paid` | POST | Mark paid | **LEGACY** | **FREEZE** |
| `/payroll-enums` | GET | Enum values | READ-ONLY | Keep |
| `/payroll/weekly-run` | POST | Weekly run create | **LEGACY** | **FREEZE** |
| `/payroll/{id}/generate-weekly` | POST | Weekly generate | **LEGACY** | **FREEZE** |

### Frontend Pages

| Page | Route | Reads from | Writes to | Status | Freeze? |
|------|-------|-----------|-----------|--------|---------|
| PayRunsPage | `/pay-runs` | v3 pay_runs, payment_slips, payroll-weeks | v3 pay_runs | **ACTIVE** | Keep |
| PayrollRunsPage | `/payroll` | v1 payroll_runs | v1 payroll_runs | **LEGACY** | **Hide from sidebar** |
| PayrollDetailPage | `/payroll/:id` | v1 payroll_runs, payslips | v1 payslips | **LEGACY** | **Hide from sidebar** |
| MyPayslipsPage | `/my-payslips` | v1 payslips | — | **ACTIVE** | Keep (worker self-view) |
| PayrollBatchSection | AllReportsPage tab | v2 payroll_batch | v2 payroll_batch | **LEGACY** | **Consider removing from tab** |
| EmployeeDetailPage payroll-weeks | `/employees/:id` | v3 payroll-weeks | — | **ACTIVE** | Keep |
| EmployeeDetailPage slips | `/employees/:id` | v3 payment-slips | — | **ACTIVE** | Keep |
| FinancialResultsCard | various | v2 allocations (via finance svc) | — | **ACTIVE** | Keep |

### Sidebar / Navigation

| Entry | Target | Visible to | Status | Action |
|-------|--------|-----------|--------|--------|
| Персонал > Разплащане | `/pay-runs` | Admin | **ACTIVE** | Keep |
| Моите фишове | `/my-payslips` | Workers | **ACTIVE** | Keep |
| ~~Персонал > Фишове (стар)~~ | `/payroll` | Admin | Already removed from sidebar | ✅ |

---

## C) SAFE-TO-FREEZE WRITE PATHS (12 total)

### Immediate freeze candidates:
1. `POST /payroll-batch` — replaced by `POST /pay-runs`
2. `POST /payroll-batch/{id}/pay` — replaced by v3 mark-paid + sync
3. `POST /payroll-batch/carry-forward` — v3 handles remaining
4. `POST /payroll-runs` — replaced by v3
5. `POST /payroll-runs/{id}/generate` — replaced by v3
6. `POST /payroll-runs/{id}/finalize` — replaced by v3
7. `DELETE /payroll-runs/{id}` — v3 uses archive, not delete
8. `POST /payslips/{id}/set-deductions` — v3 uses adjustments
9. `POST /payslips/{id}/mark-paid` — v3 sync marks payslips
10. `POST /payroll/weekly-run` — replaced by v3
11. `POST /payroll/{id}/generate-weekly` — replaced by v3
12. `GET /payroll-batch/eligible` — replaced by `/pay-runs/generate`

## D) READ-ONLY PATHS TO KEEP

| Route | Reason |
|-------|--------|
| `GET /payslips` | Worker self-view (MyPayslipsPage) |
| `GET /payslips/{id}` | Slip detail |
| `GET /payroll-runs` | Historical access |
| `GET /payroll-runs/{id}` | Historical access |
| `GET /payroll-batch/list` | Historical batches |
| `GET /payroll-batch/{id}` | Batch detail |
| `GET /payroll-batch/{id}/allocations` | Allocation history |
| `GET /projects/{id}/paid-labor` | Project finance read |
| `GET /payslip/{batch_id}/{worker_id}` | Old payslip read |
| `GET /payroll-enums` | Enum values |

## E) SIDEBAR CLEANUP CANDIDATES

| Current | Action | Risk |
|---------|--------|------|
| `/payroll` removed from admin nav | Already done ✅ | None |
| AllReportsPage "Заплати" tab (v2) | Consider hiding or marking "(стар)" | Low — v3 has full replacement |
| `/my-payslips` | Keep — synced v1 data visible | None |

## F) ROLLBACK PLAN

If freeze causes problems:
1. **Immediate**: Re-enable the frozen write endpoint by removing the guard (1 line per route)
2. **Data**: Archived records still exist — `db.pay_runs.updateMany({archived:true},{$unset:{archived:1}})` restores visibility
3. **Sync**: v3 sync adapter can be disabled by commenting out 3 calls in `pay_runs.py`
4. **Finance**: If v2 allocations are stale, legacy `payroll_batch.py` write paths can be re-enabled
5. **Self-view**: If v1 payslips missing, sync can be re-run for specific pay_runs

## G) EXACT FREEZE ORDER (step by step)

```
Step 1: Add HTTP 410 Gone guard to 12 legacy write endpoints
Step 2: Hide PayrollBatchSection from AllReportsPage tabs (or mark "стар")
Step 3: Verify self-view still works (sync creates v1 payslips)
Step 4: Verify finance still works (sync creates v2 allocations)
Step 5: Monitor for 1 week
Step 6: If stable, remove legacy pages from App.js routes (keep backend read-only)
```

---

## NEXT SMALLEST IMPLEMENTATION PROMPT

```
ЗАДАЧА: Freeze legacy write paths — добави HTTP 410 guard на 12 route-а.

1. В payroll_batch.py: POST /payroll-batch, POST /{id}/pay, POST /carry-forward
   → return HTTPException(410, "Deprecated: use /pay-runs instead")

2. В hr.py: POST /payroll-runs, POST /{id}/generate, POST /{id}/finalize,
   DELETE /payroll-runs/{id}, POST /payslips/{id}/set-deductions,
   POST /payslips/{id}/mark-paid, POST /payroll/weekly-run,
   POST /payroll/{id}/generate-weekly
   → return HTTPException(410, "Deprecated: use /pay-runs instead")

3. В AllReportsPage.js: скрий tab "Заплати" или добави "(стар)" label

4. Не пипай GET endpoints, sidebar, self-view, finance.
5. Verify /pay-runs, /my-payslips, finance all still work.
```

---

**WEB Preview verified**: https://client-registry-17.preview.emergentagent.com/pay-runs

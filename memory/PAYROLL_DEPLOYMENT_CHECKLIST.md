# BEG_Work Payroll Module — Final Production Deployment Checklist
## Generated: 2026-04-13

---

## A) EXECUTIVE SUMMARY

The payroll module (v3 pay_runs) is operationally complete with:
- 3-step payment flow (days → adjustments → payment)
- Sync adapter to downstream v2/v1 consumers
- Legacy write freeze (HTTP 410)
- Test data safely archived
- Worker self-view and project finance verified post-freeze

**Status: READY FOR PRODUCTION DEPLOYMENT**

No blocking issues found. 6 recommended indexes, 0 required crons.

---

## B) REQUIRED ENV / SETTINGS

| Variable | Location | Required | Current | Production Notes |
|----------|----------|----------|---------|-----------------|
| `MONGO_URL` | backend/.env | YES | localhost:27017 | Change to production MongoDB URI |
| `DB_NAME` | backend/.env | YES | test_database | Change to `begwork_production` |
| `JWT_SECRET` | backend/.env | YES | Set | **ROTATE for production** — current is dev secret |
| `CORS_ORIGINS` | backend/.env | YES | `*` | **RESTRICT** to production domain |
| `REACT_APP_BACKEND_URL` | frontend/.env | YES | preview URL | Change to production URL |
| `EMERGENT_LLM_KEY` | backend/.env | OPTIONAL | Set | Only if AI features used |
| `PLATFORM_BOOTSTRAP_TOKEN` | backend/.env | REMOVE | Set | **DELETE after admin promotion** |

**Payroll-specific settings: NONE required.** All payroll config is in-code (NORMAL_DAY=8, pay_type defaults, etc.)

---

## C) REQUIRED MONGO INDEXES

### Critical (must create before production):

```javascript
// 1. pay_runs — primary lookups
db.pay_runs.createIndex({ "org_id": 1, "archived": 1, "created_at": -1 })
db.pay_runs.createIndex({ "id": 1, "org_id": 1 }, { unique: true })

// 2. payment_slips — list + employee filter
db.payment_slips.createIndex({ "org_id": 1, "archived": 1, "created_at": -1 })
db.payment_slips.createIndex({ "pay_run_id": 1 })

// 3. payroll_payment_allocations — finance reads
db.payroll_payment_allocations.createIndex({ "org_id": 1, "project_id": 1, "status": 1 })
db.payroll_payment_allocations.createIndex({ "source_pay_run_id": 1 })

// 4. employee_daily_reports — payroll status queries
db.employee_daily_reports.createIndex({ "org_id": 1, "worker_id": 1, "date": 1, "status": 1 })

// 5. payslips (v1) — worker self-view
// Already has: org_id_1_user_id_1 ✅
// Already has: org_id_1_payroll_run_id_1 ✅
// Recommend: add archived filter
db.payslips.createIndex({ "org_id": 1, "user_id": 1, "archived": 1 })
```

### Already exists:
- `payslips.org_id_1_payroll_run_id_1` ✅
- `payslips.org_id_1_user_id_1` ✅
- `payroll_runs.org_id_1_status_1` ✅

---

## D) BACKGROUND JOBS / CRONS

| Job | Required? | Notes |
|-----|-----------|-------|
| Payroll auto-generate | **NO** | Payroll is manually triggered by admin |
| Payroll reminder | **NO** | No scheduled notifications |
| Allocation recalc | **NO** | Allocations created at confirm-time |
| Slip auto-cleanup | **NO** | Archived records stay for audit |
| Report status sync | **NO** | Sync happens at confirm/pay/reopen |

**ZERO crons/jobs needed for payroll.** All operations are admin-initiated via UI.

The only existing background task is a reminder scheduler (server.py line 1378) — this is unrelated to payroll.

---

## E) POST-DEPLOY SMOKE CHECKLIST

Execute in order, each step must pass:

```
□ 1. Login as admin
□ 2. Navigate to /pay-runs
□ 3. Tab "Ново разплащане" loads with period picker
□ 4. Set period with approved reports → grid shows employees
□ 5. Select days → "Напред" → Step 2 loads
□ 6. "Напред → Плащане" → Step 3 loads with payment amounts
□ 7. "Потвърди" → Pay run created, appears in History
□ 8. Open detail → "Маркирай платен" → payment dialog opens
□ 9. Fill method/reference → confirm → status = "Платен"
□ 10. Navigate to /my-payslips (as technician) → new slip visible
□ 11. Navigate to project → Финанси → paid labor increased
□ 12. Tab "Месечен" → monthly view shows data
□ 13. Tab "Седмици" → weekly view shows data  
□ 14. Tab "Фишове" → slips visible with detail
□ 15. Print: group list opens in new window
□ 16. Print: individual slip opens in new window
```

---

## F) ROLLBACK CHECKLIST

If deployment causes issues:

| Step | Action | Time |
|------|--------|------|
| 1 | Revert code to previous commit | 1 min |
| 2 | Restart backend service | 30 sec |
| 3 | Verify /pay-runs loads | 30 sec |
| 4 | Verify /my-payslips loads | 30 sec |

**Data rollback (if needed):**
- Archived records: `db.pay_runs.updateMany({archived:true}, {$unset:{archived:1}})`
- Legacy write unfreeze: Replace `raise HTTPException(410)` with original code (saved in git)
- Sync records: `db.payroll_payment_allocations.deleteMany({source_pay_run_id:{$exists:true}})`

---

## G) POST-DEPLOY WATCH ITEMS

| Item | Severity | What to watch | Action if triggered |
|------|----------|---------------|-------------------|
| "Има платен труд, но няма отчетен труд от work_sessions" | **INFO** | Normal warning for projects with paid labor from payroll but no direct work_sessions | Informational only — no action |
| Legacy payslips with gross=0 in self-view | **LOW** | Legacy test data showing with zero values | Safe to ignore — filter by status if needed |
| Duplicate pay runs for same week | **MEDIUM** | If admin creates multiple runs for same period | Frontend dedup handles display; warn admin |
| Archived records becoming visible | **LOW** | If `archived` filter is bypassed | Check query filters include `archived: {$ne: true}` |
| Finance showing stale v2 allocation data | **MEDIUM** | If old payroll_batch allocations are not reversed | Check `status` filter in project_financial_results.py |
| Self-view showing "Reversed" slips | **LOW** | After reopen, reversed slips may appear briefly | Status is correct — user sees accurate state |

---

## H) NEXT STEPS (post-deployment)

No immediate next prompt needed for payroll production readiness.

Future enhancements (non-blocking):
1. Add `payment_method` display in monthly calendar view
2. Add employee payroll summary PDF (monthly)  
3. Add bulk payment export (CSV/XLSX for bank transfers)
4. Consider removing AllReportsPage "Заплати (стар)" tab entirely after 30-day observation

---

**Reference WEB route**: https://client-registry-17.preview.emergentagent.com/pay-runs

# BEG_Work — Source of Truth Policy
# Generated: 2026-04-10
# Context: After Phase 1.1-1.3 (Roster → Draft → Approve → work_sessions)

---

## Operational Layers (New Flow — Phase 1)

### site_daily_rosters
**Purpose:** "Кой е на обекта днес"
- Operational field roster, filled by technician each morning
- NOT HR attendance — purely operational site presence
- One record per project+date
- Fields: workers[{worker_id, worker_name}]
- Consumers: TechnicianDashboard (Step 1), report pre-fill
- Does NOT feed into payroll or P&L directly

### employee_daily_reports
**Purpose:** "Какво е работено днес" (DRAFT input document)
- Entry document from the field
- Statuses: Draft → Submitted → APPROVED / REJECTED
- On approve → generates work_sessions (the real posting event)
- On reject → no work_sessions created
- On reset → work_sessions voided (flagged, not deleted)
- NOT the final financial truth — it's the input, not the ledger
- Fields: worker_id, smr_type, hours, status, slip_number (on approve)
- Consumers: Approval UI, ReportsModule

### work_sessions ⭐ SOURCE OF TRUTH FOR LABOR
**Purpose:** "Финално призната работа"
- THE ONLY source of truth for recognized labor hours and cost
- Created ONLY on approve (source_method=APPROVED_REPORT)
- Or from legacy direct flow (source_method=MANUAL, SELF_REPORT)
- On reset → becomes voided (is_flagged=true, flag_reason=voided_by_reset), NOT deleted
- Fields: worker_id, site_id, duration_hours, hourly_rate_at_date, labor_cost
- Consumers: payroll, P&L, budget burn, pulse, alarms, overhead, expected_actual

**Rules:**
- NEVER write financial data to employee_daily_reports
- NEVER read employee_daily_reports for P&L or payroll
- work_sessions is the ONLY place for labor_cost
- On conflict between old and new flow, work_sessions with newer timestamp wins

---

## HR Layers (Legacy Flow — Unchanged)

### attendance_entries
**Purpose:** HR presence tracking (Present/Absent/Late/Sick/Vacation)
- Separate from site_daily_rosters
- Could be auto-generated from rosters in the future (not done yet)
- Used by old HR attendance reports
- NOT modified by Phase 1 changes

### worker_calendar
**Purpose:** Calendar view of worker status per day
- Updated on approve (status=working, source=approved_report)
- Also updated by sync-from-sessions and manual entry
- Visual/reference layer for overhead calculation
- Source priority: manual > approved_report > auto_from_sessions

### work_reports
**Purpose:** Legacy HR report format
- Used by old payroll flow for Hourly workers
- Phase 1.2 writes here with status=Draft for compatibility
- NOT rewritten — new flow bypasses it for financial posting
- FUTURE: monthly payroll should also read from work_sessions

---

## Payroll Sources

| Payroll Type | Current Source | Correct Source | Status |
|-------------|---------------|----------------|--------|
| Weekly payroll | work_sessions | work_sessions | Correct |
| Monthly (Hourly) | work_reports | work_sessions | TODO: migrate |
| Monthly (Daily) | attendance_entries | work_sessions | TODO: migrate |
| Monthly (Fixed) | base_salary | base_salary | Correct |

---

## Data Flow Diagram

```
Technician (mobile)
  │
  ├─ Step 1: POST /technician/site/{id}/roster
  │           → site_daily_rosters (operational presence)
  │
  ├─ Step 2: POST /technician/daily-report
  │           → employee_daily_reports (DRAFT — no financial effect)
  │           → work_reports (summary, Draft status)
  │           → missing_smr (if unknown SMR type)
  │
  └─ Manager approves: POST /daily-reports/{id}/approve
              → employee_daily_reports (APPROVED + slip_number + payroll_ready)
              → work_sessions (CREATED — source of truth for labor)  ⭐
              → worker_calendar (updated — status=working)
              → org_counters (slip_number incremented)
              
              work_sessions then feeds:
              → payroll (weekly/monthly)
              → project P&L (labor_cost)
              → budget burn tracking
              → site pulse
              → alarms
              → overhead calculation
              → expected vs actual
```

---

## Anti-Patterns (DO NOT)

1. Do NOT read employee_daily_reports for financial calculations
2. Do NOT create work_sessions from anywhere except approve endpoint
3. Do NOT delete work_sessions on reset — only void (flag)
4. Do NOT write labor_cost to employee_daily_reports
5. Do NOT use site_daily_rosters as HR attendance source
6. Do NOT bypass approve to create work_sessions directly from technician flow

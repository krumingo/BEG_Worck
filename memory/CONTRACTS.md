# BEG_Work — Protected Modules & API Contracts
# Generated: 2026-04-09
# Purpose: Freeze guard — do NOT rewrite these modules without explicit task

## Protected Backend Modules (DO NOT REWRITE)

### 1. work_sessions.py (12 endpoints)
**Contract:**
- POST /work-sessions/start → 201, returns session with `auto_closed_session_id` if previous was open
- POST /work-sessions/end → 200, returns closed session with `duration_hours`, `labor_cost`
- GET /work-sessions → paginated `{items, total, page, page_size, total_pages, has_next, has_prev}`
- GET /work-sessions/active → `{items[], total}` with `elapsed_hours` computed
- GET /work-sessions/my-today → `{items[], total_hours, total_cost, has_open_session, is_overtime}`
- GET /work-sessions/summary → `{total_hours, total_cost, workers_count, overtime_hours}`
- POST /work-sessions/{id}/split → `{ok, new_sessions[]}`
- GET /work-sessions/overtime → `{workers[]}`
- PUT /work-sessions/{id} → recalculates duration/cost
- DELETE /work-sessions/{id} → only flagged

**Critical fields (never rename):**
`id, org_id, worker_id, site_id, started_at, ended_at, duration_hours, labor_cost, hourly_rate_at_date, is_overtime, overtime_coefficient, is_flagged, flag_reason`

**Consumers:** MyDayPage, SiteAttendancePage, TechnicianDashboard, project_pnl, budget_progress, pulse_generator, overhead_realtime

---

### 2. missing_smr.py (17 endpoints)
**Contract:**
- POST /missing-smr → 201
- GET /missing-smr → paginated
- GET /missing-smr/pending-approval → MUST be before /{item_id} (route ordering critical!)
- PUT /missing-smr/{id}/status → validates per urgency_type transitions
- PUT /missing-smr/{id}/execute → emergency only
- POST /missing-smr/{id}/request-approval → planned only
- PUT /missing-smr/{id}/client-approve, client-reject
- POST /missing-smr/{id}/ai-estimate → calls ai_proposal + pricing_engine
- POST /missing-smr/batch-to-offer
- POST /missing-smr/{id}/to-analysis → creates extra_work_draft
- POST /missing-smr/{id}/to-offer → creates offer

**Critical fields:**
`id, org_id, project_id, smr_type, status, urgency_type, client_approval, ai_estimated_price, source`

**Status values (FROZEN):** draft, reported, reviewed, executed, approved_by_client, rejected_by_client, analyzed, offered, closed

---

### 3. smr_analysis.py (20+ endpoints)
**Contract:**
- POST /smr-analyses → 201
- GET /smr-analyses → paginated
- POST /smr-analyses/{id}/lines → adds line, recalculates
- PUT /smr-analyses/{id}/lines/{lineId} → updates line, recalculates
- POST /smr-analyses/{id}/recalculate
- POST /smr-analyses/{id}/approve, /lock, /snapshot, /to-offer
- GET /smr-analyses/{id}/compare/{version}
- POST /smr-analyses/import-excel → multipart
- GET /smr-analyses/{id}/export-excel → binary xlsx
- PUT /smr-analyses/{id}/lines/{lineId}/toggle
- PUT /smr-analyses/{id}/bulk-update
- POST /smr-analyses/from-offer/{offerId}

**Critical:** `calc_line()` and `calc_totals()` are shared by pricing.py and price_modifiers.py — DO NOT change signatures

---

### 4. project_pnl.py + services/project_pnl.py
**Contract:**
- GET /projects/{id}/pnl → full P&L dict with `budget`, `revenue`, `expense`, `profit` sections
- GET /projects/{id}/pnl/summary
- GET /projects/{id}/pnl/trend?months=N
- GET /org/pnl-overview → `{projects[], totals}`

**Aggregates from:** invoices, work_sessions, warehouse_transactions, subcontractor_payments, contract_payments, project_overhead_allocations, missing_smr, offers

---

### 5. price_modifiers.py + services/price_modifiers.py
**Contract:**
- GET/PUT /price-modifiers/org
- GET/PUT/DELETE /price-modifiers/project/{id}
- GET /price-modifiers/effective/{id} → merged cascade
- POST /price-modifiers/calculate → breakdown steps
- POST /smr-analyses/{id}/recalculate-with-modifiers

**Cascade order (FROZEN):** org_default → project → line. Auto-rules: floor_auto, inhabited_auto.
**Modifier chain (FROZEN):** waste → floor → center → inhabited → overhead → risk → profit

---

### 6. overhead_realtime.py + services/overhead_realtime.py
**Contract:**
- GET/POST /worker-calendar, /worker-calendar/bulk, /worker-calendar/sync-from-sessions
- GET/PUT /fixed-expenses
- GET /overhead/realtime, /realtime/daily, /realtime/by-project, /realtime/trend

**Calendar statuses (FROZEN):** working, sick_paid, sick_unpaid, vacation_paid, vacation_unpaid, absent_unauthorized, day_off, holiday

---

### 7. pulse.py + services/pulse_generator.py
**Contract:**
- GET /sites/{id}/pulse → auto-generates on demand
- GET /pulse/today → all sites
- POST /pulse/generate-all
- GET /pulse/summary

---

### 8. alarms.py + services/alarm_engine.py
**Contract:**
- GET /alarms → paginated
- GET /alarms/count → `{critical, warning, info, total}`
- PUT /alarms/{id}/acknowledge, /resolve
- POST /alarms/evaluate
- CRUD /alarm-rules

---

### 9. technician.py
**Contract:**
- GET /technician/my-sites → `{sites[]}`
- POST /technician/daily-report → creates WorkSessions + MissingSMR for unknown types
- POST /technician/quick-smr → creates MissingSMR with source="mobile"
- POST /technician/material-request
- POST /technician/photo-invoice → creates pending_expense
- GET/PUT /pending-expenses

---

### 10. projects.py (32 endpoints)
**Critical fields (never rename):**
`id, org_id, code, name, status, owner_id, owner_type, structured_address, contacts, invoice_details, object_type, object_details`

---

### 11. clients.py
**Critical fields:**
`id, org_id, type, companyName, eik, fullName, phone, email`

**New endpoints (safe):** /clients/{id}/summary, /clients/{id}/projects, /clients/{id}/invoices

---

## Protected Frontend Modules

### DashboardLayout.js
- NAV_GROUPS structure — add items but never remove
- WORKER_NAV — first item is /tech
- Grouped sidebar with expand/collapse
- Active project banner from ProjectContext

### ProjectDetailPage.js
- 6 tabs: overview, smr, locations, finance, info, team
- URL hash sync (#smr, #finance)
- setActiveProject on load

### ProjectContext.js
- activeProject, setActiveProject, clearActiveProject
- Used by: MissingSMRPage, SiteAttendancePage, DailyLogsPage

### DashboardPage.js
- Sections: stats → alarms → overhead → pulse → projects → P&L → missing att/rep → finance → activity
- Fetches: /alarms/count, /pulse/today, /org/pnl-overview, /overhead/realtime

---

## Safe Extension Points

### Backend — safe to ADD:
- New route file in /app/backend/app/routes/ → register in server.py
- New service in /app/backend/app/services/
- New fields on existing models (additive only, with defaults)
- New query parameters on existing GET endpoints
- New collections in MongoDB

### Frontend — safe to ADD:
- New page in /app/frontend/src/pages/ → register in App.js
- New component in /app/frontend/src/components/
- New tab in ProjectDetailPage TabsContent
- New card in DashboardPage sections
- New group/item in NAV_GROUPS
- New i18n keys in bg.json/en.json

### UNSAFE (requires explicit task):
- Changing calc_line() or calc_totals() signatures
- Renaming MongoDB fields
- Changing status workflow values
- Removing endpoints
- Changing response shape of existing endpoints
- Modifying middleware order

---

## Risk List

### Data Overlap Risks:
1. **work_sessions vs attendance** — both track presence. work_sessions is source of truth for hours/cost. attendance is legacy check-in/out. DO NOT merge.
2. **project.invoice_details vs client record** — project copies from client via import-client-invoice. Client is SSOT. Project copy is snapshot.
3. **overhead_realtime vs full_cost.py overhead** — overhead_realtime is real-time from worker_calendar + fixed_expenses. full_cost.py has monthly snapshots. Both valid for different purposes.

### Regression Risks:
1. **missing_smr route ordering** — /pending-approval MUST be before /{item_id}. Moving it breaks the route.
2. **calc_totals skip inactive** — calc_totals skips is_active=false lines. Any caller that doesn't set is_active defaults to true (backward safe).
3. **paginate_query** — applied to 4 endpoints. Frontend expects `items[]` in response (still there). `total` is now accurate count vs array length.
4. **ProjectContext** — if cleared, pages fall back to manual selection (safe). But if activeProject.id points to deleted project, fetch will 404 (acceptable).

### DO NOT Refactor Now:
1. hr.py (951 lines) — massive but stable. Split only with explicit task.
2. attendance.py (500+ lines) — legacy but working. Technician flow bypasses it.
3. OfferEditorPage.js (1300+ lines) — Stage 6 will address this.
4. server.py route registration (50+ includes) — works, don't reorganize.

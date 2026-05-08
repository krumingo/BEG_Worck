# BEG_Work — Final Hardening Review
# Generated: 2026-04-10
# Scope: All additive improvements from Session 2 (A2 series)
# Purpose: Audit, stabilization, risk identification

---

## Section 1 — What Is Working Well

### Core operational chain is solid
- Technician → daily-report → work_sessions → payroll → P&L — this chain is fully connected and tested
- The data flows from field to finance without manual bridging
- work_sessions is a reliable single source of truth for labor hours/cost

### Dashboard is operationally useful
- Morning Briefing surfaces the right things: risks, payments, missing reports
- Cash Flow Forecast gives 30-day visibility with warning levels
- Pulse cards show per-site daily snapshots
- Alarm count in NotificationBell provides ambient awareness

### Project detail page is well organized
- 6-tab structure prevents overwhelming scroll
- Finance tab has good layering: P&L → Expected vs Actual → Material Waste → Subcontractor Performance
- Location tree + SMR groups provide structural navigation

### Excel import V2 is production-ready
- 3-step wizard (upload → preview → confirm) with smart column detection
- Template save/apply reduces repeated work
- Bridge pattern preserves old import engine as source of truth

### Backward compatibility is maintained throughout
- Old records without new fields continue to work
- Text fallback fields (floor/room/zone) coexist with location_id
- Old markup_pct/risk_pct coexist with new price modifiers chain

---

## Section 2 — Integration Gaps

| # | Gap | Severity | Affected | Recommended Fix |
|---|-----|----------|----------|-----------------|
| 1 | **OCR page not linked from pending_expenses or procurement** | MEDIUM | OCRInvoicePage, pending expenses flow | Add "Сканирай фактура" button in pending expenses list + procurement supplier invoice area |
| 2 | **ExcelImportV2Modal not linked from KSS detail page** | LOW | SMRAnalysisPage | Add "Импорт от Excel" button in the KSS detail page action bar (currently only on list page) |
| 3 | **Material Waste not linked from technician flow** | MEDIUM | TechnicianDashboard | Add quick "Регистрирай брак" button in technician site view |
| 4 | **Subcontractor Performance not auto-populated from subcontractor_payments** | LOW | subcontractor_performance service | Could auto-create performance records when subcontractor acts are confirmed |
| 5 | **Expected vs Actual has no time-range filter in UI** | LOW | ExpectedActualPanel | date_from/date_to params exist in API but no date pickers in the panel |
| 6 | **Cash Flow has no link FROM project finance tab** | LOW | ProjectDetailPage finance tab | Add compact cashflow widget or link in project finance tab |
| 7 | **Alarm rules have no UI for creation** | MEDIUM | AlarmRulesPage not created | Rules exist in API but there is no frontend page for managing them. Users can only create via API. |
| 8 | **Worker Calendar page not accessible from Employee Detail** | LOW | EmployeeDetailPage | Could add a "Календар" tab that filters worker_calendar for that employee |

---

## Section 3 — Data Overlap Risks

| # | Domain Pair | Risk | Level | Recommendation |
|---|-------------|------|-------|----------------|
| 1 | **OCR intake → pending_expense** | OCR approve creates a NEW pending_expense. If user also submitted via technician photo-invoice, there could be duplicates for the same physical invoice | MEDIUM | Add duplicate detection: check if pending_expense with same amount + similar date exists before creating |
| 2 | **work_sessions vs worker_calendar** | sync-from-sessions fills calendar, but manual calendar entries can contradict session data. No conflict resolution. | LOW | Calendar entries marked "manual" should take precedence. Add source priority logic. Currently safe because sync skips manual entries. |
| 3 | **location_id vs floor/room/zone** | LocationPicker sets both location_id AND text fields. But if user edits text fields after picking location, they drift. | LOW | Currently acceptable. LocationPicker auto-fills text. If user manually changes text, location_id stays (slightly inconsistent but non-breaking). |
| 4 | **project.invoice_details vs client record** | Snapshot copy. If client data is updated, project copy drifts. | LOW | "Import from client" button exists. Banner shows source. Acceptable for v1. |
| 5 | **pulse alerts vs centralized alarms** | Same condition can appear in both. Pulse alerts are ephemeral (regenerated). Alarms are persistent with ack/resolve. | NONE | Different purposes. Documented in INTEGRATION_MAP. No action needed. |
| 6 | **cashflow forecast vs finance summary widget** | Both show financial data on dashboard. Could confuse user about which is authoritative. | LOW | Cashflow is forward-looking (forecast). Finance summary is backward-looking (actuals). Labels are clear. |
| 7 | **material_waste_entries vs warehouse_transactions** | Waste entries are separate logging layer. Not linked to actual stock adjustments. | LOW | By design. Waste is analytics/tracking. Warehouse is transactional. No cross-update needed for v1. |

---

## Section 4 — UX Gaps

| # | Page/Flow | User Confusion | Level | Fix |
|---|-----------|---------------|-------|-----|
| 1 | **Where to upload an invoice?** | 3 places: Technician photo-invoice, OCR Invoices page, Procurement supplier invoice. User may not know which to use. | MEDIUM | Add a single "Качи фактура" entry point that routes to the right flow based on context |
| 2 | **Where to see material waste?** | Hidden inside Project → Finance tab, below P&L and Expected vs Actual. User must scroll. | LOW | Could add a badge in overview tab: "2 материала с overuse" |
| 3 | **Where to see subcontractor performance?** | Same as waste — deep in Finance tab | LOW | Performance badge in overview or separate sidebar link |
| 4 | **Alarm rules management** | No UI page. Only API access. | MEDIUM | Create AlarmRulesPage in /settings area |
| 5 | **Expected vs Actual "planned hours" estimation** | Uses budget / 25 (hardcoded hourly rate). If actual rates differ, planned hours look wrong. | LOW | Use project team's avg_daily_wage instead of hardcoded 25 |
| 6 | **ExcelImportV2 needs project selection** | The import button on SMRAnalysisListPage uses fProject filter or first project. If no project is filtered, it may pick wrong project. | LOW | Show project selector in the modal step 1 before upload |

---

## Section 5 — Quick Wins After Review (Top 10)

1. **Create AlarmRulesPage** — Simple CRUD table for alarm rules in /settings. API exists. Just needs UI.
2. **Add "Сканирай фактура" link** from pending_expenses list to /ocr-invoices
3. **Add project selector in ExcelImportV2Modal** step 1 (currently relies on page context)
4. **Add compact cashflow line** in ProjectDetailPage finance tab
5. **Add "Регистрирай брак" button** in TechnicianDashboard site view
6. **Add date range pickers** to ExpectedActualPanel (API supports it, UI doesn't)
7. **Add overuse badge** in ProjectDetailPage overview tab from material waste compact
8. **Seed default alarm rules** at org creation (budget>80%, overtime>20h, etc.)
9. **Add "Календар" tab** in EmployeeDetailPage linking to worker_calendar
10. **Add duplicate detection** in OCR approve (check existing pending_expense by amount+date)

---

## Section 6 — Recommended Next Phase

### Priority order based on hardening review:

**Tier 1 — Close the gaps (1-2 sessions):**
1. AlarmRulesPage (quick UI for existing API)
2. Seed default alarm rules at signup
3. ExcelImportV2 project selector fix
4. OCR → pending_expense duplicate guard
5. Material Waste badge in overview

**Tier 2 — Feature completion:**
6. Stage 6 — Execution Budget Tabs in Offer Editor (long-pending, high value)
7. PWA manifest + installability for mobile technicians
8. Real OCR engine (Tesseract or cloud) for image files

**Tier 3 — Polish and expand:**
9. Client/Project polish (B3) — client summary in project detail, client-level P&L
10. Supplier scorecard (auto-populate from payment history)
11. Worker Calendar tab in Employee Detail
12. Compact cashflow in project finance

### Reasoning:
- Stage 6 has been deferred longest and is most requested
- PWA is critical for technician adoption (real field usage)
- Gap closures (Tier 1) are small and prevent user confusion
- Real OCR engine transforms invoice intake from "text extraction" to "image recognition"

---

## Checklist Matrix

| Module | Implemented | Visible in UI | Used in Real Flow | Risk Level | Needs Polish? | Notes |
|--------|------------|---------------|-------------------|------------|---------------|-------|
| Morning Briefing | YES | YES (Dashboard) | YES (auto on load) | LOW | NO | Working well |
| Cash Flow Forecast | YES | YES (Dashboard) | YES (auto on load) | LOW | MINOR | Could add project-level link |
| Expected vs Actual | YES | YES (Project Finance tab) | YES | LOW | MINOR | Needs date range UI |
| Material Waste | YES | YES (Project Finance tab) | YES (manual entry) | LOW | MINOR | Not accessible from technician |
| Subcontractor Performance | YES | YES (Project Finance tab) | PARTIAL (manual only) | LOW | YES | Not auto-populated from payments |
| Smart Excel V2 | YES | YES (SMR Analysis list) | YES | LOW | MINOR | Needs project selector in modal |
| OCR Invoice Intake | YES | YES (/ocr-invoices + sidebar) | YES | MEDIUM | YES | Not linked from pending_expenses |
| LocationPicker | YES | YES (3 forms) | YES | LOW | NO | Working well after iterative fix |
| NotificationBell Alarms | YES | YES (sidebar bell) | YES (auto-refresh 60s) | LOW | NO | Working well |
| Project Tabs | YES | YES (6 tabs) | YES | LOW | NO | Clean organization |
| Project Context | YES | YES (sidebar banner) | YES (3 pages) | LOW | NO | Could expand to more pages |
| Client Detail | YES | YES (/clients/:id) | PARTIAL | LOW | MINOR | Not linked from projects list |
| Worker Calendar | YES | YES (/worker-calendar) | YES | LOW | MINOR | Not linked from employee detail |
| Sidebar Restructure | YES | YES | YES | LOW | NO | Clean grouped navigation |
| Dashboard Integration | YES | YES | YES | LOW | NO | Full operational view |
| Contract Payments | YES | YES (/contract-payments) | YES | LOW | NO | Stable |
| Price Modifiers | YES | API only | NO UI panel | MEDIUM | YES | No settings UI for modifiers |
| Realtime Overhead | YES | YES (Dashboard + /worker-calendar) | YES | LOW | NO | Working well |
| Site Pulse | YES | YES (Dashboard) | YES (auto-generate) | LOW | NO | Working well |
| Centralized Alarms | YES | YES (/alarms + bell) | PARTIAL | MEDIUM | YES | No rules management UI |

### Legend:
- **Implemented**: Backend + Frontend code exists
- **Visible in UI**: User can reach it from navigation
- **Used in Real Flow**: Integrated into actual workflow (not standalone)
- **Risk Level**: LOW = safe, MEDIUM = has gaps, HIGH = potential regression
- **Needs Polish?**: NO = production ready, MINOR = small improvement, YES = needs work

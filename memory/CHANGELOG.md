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

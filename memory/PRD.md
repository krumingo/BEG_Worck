# BEG_Work PRD (Product Requirements Document)

## Overview
BEG_Work is an ERP system for construction/field service businesses with comprehensive project management, HR, finance, inventory, and AI-assisted offer modules.

---

## Master Roadmap (Updated Apr 7, 2026)

### COMPLETED BLOCKS:
- Core Infrastructure (auth, billing, modules)
- Projects & Attendance
- Finance M5 (invoices, payments, accounts)
- Invoice Numbering & Payments
- Complete Invoice Workflow (PDF, edit, project sync)
- AI Offers + Extra Works Draft Flow MVP
- Real LLM Integration (Hybrid Mode)
- Learning Loop + Price Calibration Analytics
- In-App Admin Notifications
- Extra Offers Send + Approval + Version Tracking
- Material Requests + Supplier Invoice Intake + Warehouse Posting
- Warehouse → Project Allocation + Consumption + Stock Control
- Inventory Dashboard + Stock Alerts
- Editable AI Proposals + Multi-line + Hourly Rates
- Two-Stage AI (Fast + LLM Refinement)
- Data Module (Warehouses, Counterparties, Items, Prices, Turnover)
- Missing/Additional SMR Module (Липсващи/Допълнителни СМР) — Apr 7, 2026
- Location Tree Module (Обектова йерархия) — Apr 7, 2026
- SMR Analysis Module (Анализ на СМР) — Apr 7, 2026
- Live Pricing Engine (3 AI agents) — Apr 8, 2026

### UPCOMING PRIORITY BLOCKS:

#### BLOCK A: Offer Import / Export (P0)
- Export основни оферти в Excel (xlsx) и PDF
- Export допълнителни оферти в Excel и PDF
- Import на оферти от Excel в програмата
- Historical import на стари оферти (Excel + PDF) за AI ценова база
- Template format за import
- Validation + preview преди import

#### BLOCK B: Historical Offer Intelligence (P1)
- Ingest на архивни оферти от последните 15 години
- Нормализация на СМР (activity type/subtype mapping)
- Извличане на цени за труд и материали
- Сравнителни таблици (вътрешна цена vs пазарна)
- Вътрешна ценова база за AI предложения
- Хибридно AI предложение: интернет ориентир + вътрешна база + calibration

#### BLOCK C: Personnel / HR / Attendance / Payroll (P1 — AUDIT NEEDED)
- Въвеждане на персонал (вече частично)
- Данни за всеки човек (профил, квалификации, документи)
- Присъствия (вече частично)
- Личен календар
- По кои обекти е работил (вече частично чрез work reports)
- Часове / дни (вече частично)
- Заплати / ставки / справки (вече частично чрез payroll)

### FUTURE BLOCKS:
- P2: M6 — AI OCR разпознаване на фактури
- P2: M8 — Активи и QR код
- P2: M9 — Админ конзола / BI дашборд
- P2: Мобилни потоци за техници (Фаза 3-5)

---

## AUDIT: Three Priority Blocks (Mar 9, 2026)

### BLOCK A: Offer Import / Export — AUDIT

**Какво СЪЩЕСТВУВА:**
- PDF export за фактури (reportlab, DejaVu font, A4 layout) — `/api/finance/invoices/{id}/pdf`
- XLSX export за финанси (openpyxl) — `/api/reports/company-finance-export`
- Offer data model с lines (activity_name, unit, qty, material_unit_cost, labor_unit_cost)
- Extra offers с offer_type="extra" и source_batch_id
- Offer versioning (snapshots)
- Libraries installed: `reportlab 4.4.10`, `openpyxl 3.1.5`, `pandas 3.0.0`

**Какво ЛИПСВА напълно:**
- Export на оферта в PDF (само фактури имат PDF)
- Export на оферта в Excel
- Import на оферта от Excel
- Historical import pipeline за стари оферти
- Template format за import/export
- Validation/preview при import

**Какво трябва да се ДОВЪРШИ (не от нулата):**
- PDF offer export — може да се базира на invoice PDF pattern (reportlab + DejaVu)
- XLSX offer export — може да се базира на finance XLSX pattern (openpyxl)
- Import pipeline — нов, но Pydantic models за OfferLineInput вече съществуват

**Липсващи UI entry points:**
- Бутон "Експорт PDF/Excel" в OfferEditorPage header
- Бутон "Импорт оферта" в OffersListPage
- Секция "Исторически импорт" в Settings или отделна страница

**Relevant files:**
- `/app/backend/app/routes/offers.py` (offer CRUD, lines)
- `/app/backend/app/routes/finance.py` (PDF pattern, lines 1120-1250)
- `/app/backend/app/routes/reports.py` (XLSX pattern, lines 1234-1445)
- `/app/backend/app/models/offers.py` (OfferLineInput, OfferCreate)
- `/app/frontend/src/pages/OfferEditorPage.js`
- `/app/frontend/src/pages/OffersListPage.js`

---

### BLOCK B: Historical Offer Intelligence — AUDIT

**Какво СЪЩЕСТВУВА:**
- AI proposal service с rule-based + LLM hybrid (`/app/backend/app/services/ai_proposal.py`)
- ACTIVITY_KNOWLEDGE dict с 7 категории и ценови бази
- Learning Loop (ai_calibration_events: 138 записа, ai_calibrations: 7 одобрени)
- City-aware pricing (CITY_PRICE_FACTORS)
- Hourly rates по worker type (8 типа)
- Activity catalog collection (1 запис)
- Two-stage AI (fast rule-based + LLM refinement)
- 63 оферти в базата, 21 extra work drafts

**Какво ЛИПСВА напълно:**
- Ingest pipeline за архивни оферти (bulk import)
- Нормализация layer за СМР (activity_name → normalized type/subtype)
- Вътрешна ценова база от исторически данни (internal_price_db)
- Сравнителни таблици (вътрешна цена vs LLM vs пазарна)
- Merge на вътрешна база в AI proposal flow
- Dashboard/UI за historical price analytics

**Какво трябва да се ДОВЪРШИ:**
- activity_catalog вече съществува но е почти празен (1 запис) — трябва да се запълни
- ACTIVITY_KNOWLEDGE dict може да се надгради с исторически данни
- Calibration infrastructure е готова — трябва да се разшири за bulk ingest
- AI proposal service вече поддържа calibration factors — трябва internal_price_db source

**Зависимост:** BLOCK B зависи силно от BLOCK A (Import) — без import няма данни за ingest

**Relevant files:**
- `/app/backend/app/services/ai_proposal.py` (hybrid provider, knowledge base)
- `/app/backend/app/routes/ai_calibration.py` (calibration analytics)
- `/app/backend/app/routes/extra_works.py` (AI proposal endpoints)
- `/app/backend/app/routes/offers.py` (activity-catalog CRUD)

---

### BLOCK C: Personnel / HR / Attendance / Payroll — AUDIT

**Какво СЪЩЕСТВУВА (обширно):**

Backend (43 endpoints):
- `/api/employees` — CRUD с профили (pay_type, hourly/daily/monthly rates, start_date)
- `/api/advances` — аванси и заеми (create, apply deduction)
- `/api/payroll-runs` — създаване, генериране, финализиране, изтриване
- `/api/payslips` — генерирани фишове, удръжки, маркиране като платено
- `/api/attendance/mark` — маркиране присъствие (self + for-user)
- `/api/attendance/my-today`, `/my-range`, `/site-today`, `/missing-today`
- `/api/work-reports` — draft, submit, approve, reject, my-today, project-day
- `/api/reminders` — policy, missing-attendance, missing-work-reports, send, excuse
- `/api/notifications/my`, `/mark-read`
- `/api/daily-logs` — дневник на строителни работи
- `/api/change-orders` — промени по СМР

Frontend (3093 реда в 10 файла):
- `EmployeesPage.js` (297 реда) — списък служители, профили
- `PayrollRunsPage.js` (255 реда) — payroll run-ове
- `PayrollDetailPage.js` (470 реда) — детайл на payroll run
- `MyPayslipsPage.js` (224 реда) — лични фишове
- `AdvancesPage.js` (259 реда) — аванси
- `SiteAttendancePage.js` (264 реда) — присъствие по обект
- `AttendanceHistoryPage.js` (157 реда) — история присъствие
- `MyDayPage.js` (288 реда) — днешен ден (mark attendance + work report)
- `WorkReportFormPage.js` (369 реда) — работен отчет
- `DailyLogsPage.js` (510 реда) — дневник

Navigation:
- ✅ /employees
- ✅ /advances
- ✅ /payroll
- ✅ /site-attendance
- ✅ /review-reports
- ✅ /reminders
- ✅ /daily-logs
- ✅ /change-orders
- ✅ /my-day (за служители)
- ✅ /attendance-history

Models (hr.py):
- EmployeeProfile: pay_type (Hourly/Daily/Monthly), hourly_rate, daily_rate, monthly_salary
- AdvanceLoan: type, amount, currency
- PayrollRun: period_type, period_start/end
- Payslip: deductions, mark-paid

**Какво ЛИПСВА:**
- Личен календар (calendar view на присъствия/часове)
- Квалификации / сертификати / документи на служител
- Справка "по кои обекти е работил" (данните съществуват в work_reports, но няма dedicated report)
- Детайлни часови справки (total hours per project per employee)
- Детайлен employee profile view (сегашният е базов)

**Какво е РАЗПИЛЯНО и трябва да се подреди:**
- Work reports данните се записват, но няма обобщени справки (кой колко часа е работил къде)
- Attendance + work reports са в един routes файл (attendance.py) с 25 endpoint-а
- MyDayPage комбинира attendance + work report, но няма calendar view

**Липсващи UI entry points:**
- Employee detail page (сега само list + modal)
- Per-employee project history view
- Per-employee hours summary
- Calendar view за присъствие

**Relevant files:**
- `/app/backend/app/routes/hr.py` (18 endpoints)
- `/app/backend/app/routes/attendance.py` (25 endpoints)
- `/app/backend/app/routes/work_logs.py` (daily-logs, change-orders)
- `/app/backend/app/models/hr.py`
- `/app/backend/app/models/attendance.py`
- `/app/frontend/src/pages/EmployeesPage.js`
- `/app/frontend/src/pages/PayrollRunsPage.js`
- `/app/frontend/src/pages/PayrollDetailPage.js`
- `/app/frontend/src/pages/SiteAttendancePage.js`
- `/app/frontend/src/pages/MyDayPage.js`
- `/app/frontend/src/pages/WorkReportFormPage.js`
- `/app/frontend/src/pages/DailyLogsPage.js`

---

## RECOMMENDED NEXT PRIORITY

### Препоръка: BLOCK A (Offer Import/Export) → BLOCK B (Historical Intelligence)

**Защо BLOCK A е следващ:**
1. **Най-висока бизнес стойност** — Export на оферти е P0 функционалност за ежедневна работа
2. **Техническа готовност** — PDF + XLSX patterns вече съществуват (invoice PDF, finance XLSX)
3. **Бърз за изпълнение** — не изисква нова архитектура, а адаптация на съществуващи patterns
4. **Prerequisite за BLOCK B** — без Import няма данни за Historical Intelligence
5. **Immediate user value** — потребителят може веднага да изпраща оферти в професионален формат

**Защо НЕ BLOCK C:**
- HR/Attendance/Payroll вече е **70-80% завършен** (43 backend endpoints, 10 frontend pages, 3093 реда)
- Липсващите елементи (calendar, employee detail, hours report) са по-скоро **подобрения**, не foundation
- Може да се довърши паралелно или след A+B

**Логична последователност:**
1. **BLOCK A** (1-2 сесии): Export PDF/XLSX + Import Excel + Template
2. **BLOCK B** (2-3 сесии): Ingest pipeline + Нормализация + Вътрешна ценова база + AI merge
3. **BLOCK C improvements** (1 сесия): Calendar view + Employee detail + Hours report

---

## What's Been Implemented

### Phase: Core Infrastructure (DONE)
- Multi-tenant architecture with organizations
- JWT authentication with role-based access (Admin, Owner, SiteManager, Technician, etc.)
- Subscription billing with Stripe integration
- Feature flags per module (M0-M9)

### Phase: Projects & Attendance (DONE)
- Project CRUD with phases and team management
- Attendance tracking with clock in/out
- Work reports with activities and hours

### Phase: Finance M5 (DONE)
- Financial accounts (Cash, Bank)
- Invoice management (Issued/Received)
- Payment tracking with allocation to invoices
- Counterparties (suppliers/clients)

### Phase: Invoice Numbering & Payments (DONE) - Mar 8, 2026
**Automatic Sequential Invoice Numbering:**
- Settings API: GET/PUT /api/finance/invoice-settings (prefix, auto/manual, next number)
- Preview API: GET /api/finance/next-invoice-number
- Atomic increment with find_one_and_update to prevent race conditions
- Safe starting number validation (no conflicts with existing numbers)
- UI: CompanySettingsPage with toggle for auto/manual, prefix, next number

**Invoice Direct Payments & Automatic Status Logic (P0):**
- Direct payment API: POST /api/finance/invoices/{id}/payments (creates payment + allocation in one step)
- Payment history API: GET /api/finance/invoices/{id}/payments
- Payment removal API: DELETE /api/finance/invoices/{id}/payments/{alloc_id}
- Automatic status transitions: Draft → Sent → PartiallyPaid → Paid / Overdue → Cancelled
- Status recalculation on payment add/remove (including reverting from Paid → PartiallyPaid → Sent/Overdue)
- Over-payment prevention
- Frontend: Inline payment dialog from invoice page (no navigation away)
- Frontend: Payment history panel with date, amount, method, reference, account
- Frontend: Progress bar showing % paid
- Frontend: Quick-pay buttons (full amount, 50%)
- Frontend: Bulgarian status labels in badges

### Phase: Complete Invoice Workflow (DONE) - Mar 8, 2026
**1. Invoice → Project Link:**
- "Към обекта" button in invoice header navigates to linked project
- Hidden when no project_id

**2. Invoice PDF Export:**
- GET /api/finance/invoices/{id}/pdf - generates clean A4 PDF using reportlab
- DejaVu font for Cyrillic support
- Contains: invoice number, dates, counterparty, lines, totals, payment summary, notes
- Respects person vs company fields

**3. Full Invoice Editing:**
- Draft, Sent, PartiallyPaid, Overdue → fully editable
- Paid → blocked (must remove payments first)
- Cancelled → blocked (read-only)
- Line edits recalculate remaining_amount correctly with existing payments

**4. Payment → Project Financial Sync (ROOT FIX):**
- ROOT CAUSE: Project dashboard used non-existent fields (total_ex_vat, client_id)
- FIX: Now uses invoice.paid_amount, invoice.remaining_amount, invoice.counterparty_name
- Balance.income = sum of paid_amounts from project invoices (not just Paid status)
- Partial payments reflect immediately in project financials

**5. Project Invoice Table Fix:**
- Columns: №, Клиент, Дата, Падеж, Статус (with badge), Общо, Платено, Остатък
- Totals: Общо фактури, Платено, Неплатено

**6. UX Header Buttons:**
- Ordered: Запази, Към обекта, PDF, Добави плащане, Анулирай фактура, Изтрий


### Phase: AI Offers + Extra Works Draft Flow MVP (DONE) - Mar 8, 2026
**Data Model:**
- New `extra_work_drafts` collection with full schema (location, AI pricing, materials, status lifecycle)
- Status lifecycle: draft → converted → archived

**Fast Entry Flow:**
- "Допълнително СМР" button on Project Detail page
- Modal with: title, unit, qty, location (floor/room/zone), notes, AI button
- 20-40 second fast entry target achieved

**AI Proposal Service (Rule-Based MVP):**
- ACTIVITY_KNOWLEDGE dict with 7 construction categories (мазилка, боядисване, шпакловка, плочки, гипсокартон, електро, ВиК)
- Returns: recognition (type/subtype), pricing (material+labor per unit), small qty adjustment, related SMR, materials checklist
- Materials grouped: primary, secondary, consumables
- Clean AI-ready architecture for future LLM integration

**Draft Bucket:**
- ExtraWorksDraftPanel shows all drafts per project with select/delete/create-offer actions
- Shows: title, qty, AI price, date, location, status badges

**Create Extra Offer:**
- Select multiple draft rows → "Създай оферта" → new offer with lines from drafts
- Offer type=extra, auto-generated title, location info in line notes
- Draft status transitions to "converted" with link to created offer

**Offer Editor AI Assist:**
- "AI помощ" button in normal Offer Editor
- Dialog: description + unit + qty → AI proposal → "Добави като ред"
- Line added with AI-suggested material/labor prices

**API Endpoints:**
- POST /api/extra-works (create draft)
- GET /api/extra-works (list with project_id/status filters)
- PUT /api/extra-works/{id} (update)
- DELETE /api/extra-works/{id} (delete)
- POST /api/extra-works/ai-proposal (get AI pricing/materials)
- POST /api/extra-works/{id}/apply-ai (apply AI to draft)
- POST /api/extra-works/create-offer (create offer from selected drafts)


### Phase: Learning Loop + Price Calibration Analytics (DONE) - Mar 8, 2026
**Data Capture:**
- ai_calibration_events collection: records AI vs user price for every accepted/edited proposal
- Fields: ai_provider_used, ai_confidence, ai/final prices (material+labor+total), delta_percent, city, activity_type/subtype, small_qty_flag

**Analytics Dashboard (/ai-calibration):**
- Overview cards: total proposals, accepted/edited counts, accuracy rate, avg delta
- Category breakdown table: type/subtype, city, small_qty, samples, edits, avg prices, median delta, suggested factor, status
- Filters: search, city
- Top corrected categories badges

**Controlled Calibration (3 modes):**
- Observation: <5 samples (no action)
- Suggested: 5-9 samples (admin can review)
- Ready: >=10 samples (admin can approve)
- Approved: admin approved, auto-applies to AI proposals

**Safety Rules:**
- MIN_SAMPLES_FOR_SUGGESTION=5, MIN_SAMPLES_FOR_CALIBRATION=10
- OUTLIER_THRESHOLD_PERCENT=200 (edits >200% delta skipped)
- Trimmed median (remove top/bottom 10%) for factor calculation
- Admin-only approval required

**Calibration in AI Flow:**
- Approved calibrations auto-apply: base AI price × factor = calibrated price
- UI shows: base price → calibration adjustment → final recommended price
- Human still approves via "Приеми" / "Редактирай"

**API Endpoints:**
- POST /api/ai-calibration/record-edit
- GET /api/ai-calibration/overview
- GET /api/ai-calibration/categories
- POST /api/ai-calibration/approve
- DELETE /api/ai-calibration/{id}
- GET /api/ai-calibration/approved


### Phase: Real LLM Integration (Hybrid Mode) (DONE) - Mar 8, 2026
**Provider Architecture:**
- Hybrid: LLM (GPT-4.1-mini via emergentintegrations) → Rule-based fallback
- AIProvider in /app/backend/app/services/ai_proposal.py
- Automatic fallback on LLM error/timeout

**LLM Capabilities:**
- Free-text parsing of construction works (even uncommon types like PVC дограма, окачен таван Армстронг)
- Pricing suggestions (material + labor per unit)
- Material checklist with reasons for each item
- Related works suggestions (3-7 items)
- Explanation text for each proposal

**City-Aware Pricing:**
- CITY_PRICE_FACTORS: София=1.15, Пловдив=1.00, Варна=1.05, Бургас=1.02, etc.
- City field in ExtraWorkModal, passed to AI service
- Displayed in UI as "Град: София (коеф. 1.15)"

**Data Capture for Future Learning:**
- ai_provider_used, ai_raw_response_summary, ai_confidence
- ai_price_before_manual_edit, final_user_accepted_price (prepared)

**Frontend Enhancements:**
- Provider badge: "AI (LLM)" green / "Rule-based" gray
- Explanation text in italics
- City factor display
- Fallback reason display when LLM fails

### Phase: Invoice Lines Multi-Allocation (DONE) - Feb 21, 2026
- Invoice lines stored in separate collection
- Multi-allocation to projects/warehouses
- Backward compatibility with old format

### Phase: Data Module (DONE) - Feb 21, 2026
**Full implementation of "Данни" (Data) ERP module:**

#### Backend (P0 - DONE)
1. **Warehouses API** (`/api/warehouses`) - Full CRUD with server-side pagination
2. **Counterparties API** (`/api/counterparties`) - Full CRUD, EIK uniqueness check (application-level)
3. **Items/Materials API** (`/api/items`) - NEW, Full CRUD with SKU uniqueness
4. **Prices API** (`/api/prices`) - NEW, Aggregation from invoice_lines
5. **Turnover Report API** (`/api/reports/turnover-by-counterparty`) - NEW, Aggregated purchases/sales

**Filter Operators:** contains, equals, in, bool, min/max, from/to
**Response Format:** `{items, total, page, page_size, total_pages}`

#### Frontend (P0 - DONE)
1. **Sidebar "Данни" Section** - Collapsible navigation with 5 sub-pages
2. **Reusable DataTable Component** - Server-side pagination, sorting, filtering, URL state persistence, CSV export
3. **WarehousesPage** - DataTable + CRUD modals
4. **CounterpartiesPage** - DataTable + CRUD modals (EIK optional)
5. **ItemsPage** - DataTable + CRUD modals (SKU unique per org)
6. **PricesPage** - Read-only DataTable with price history from invoices
7. **TurnoverPage** - Report with grand totals cards + DataTable + drilldown drawer

**Tests:** 18 pytest tests in `/app/backend/tests/test_data_module.py`

### Phase: Finance Dashboard & Reports (DONE) - Feb 21, 2026
**Full implementation of Financial Reporting & Dashboard:**

#### Backend (P0 - DONE)
1. **Turnover by Client API** (`/api/reports/turnover-by-client`) - Aggregated sales by client (persons)
2. **Company Finance Summary API** (`/api/reports/company-finance-summary`) - Weekly income/expense breakdown
3. **Cash Transactions CRUD** (`/api/finance/cash-transactions`) - Income/expense cash flow
4. **Overhead Transactions CRUD** (`/api/finance/overhead-transactions`) - Monthly overhead costs  
5. **Bonus Payments CRUD** (`/api/finance/bonus-payments`) - Employee bonus tracking

**Response Format (Finance Summary):**
```json
{
  "year": 2026, "month": 1,
  "weeks": [{ "week": 1, "income": 0, "expenses": 0, ... }],
  "totals": { "income": 0, "expenses": 0, "net_balance": 0 },
  "income_breakdown": { "invoices": 0, "cash": 0 },
  "expense_breakdown": { "invoices": 0, "cash": 0, "overhead": 0, "payroll": 0, "bonus": 0 },
  "cumulative_balance": [{ "week": 1, "balance": 0 }]
}
```

#### Frontend (P0 - DONE)
1. **FinanceSummaryWidget** - Dashboard component with:
   - Year/Month selectors
   - Summary cards (Income, Expenses, Net Balance)
   - Bar chart: Income vs Expenses by week
   - Pie chart: Expense breakdown by type
   - Line chart: Cumulative balance
2. **Dashboard Integration** - Widget visible to managers
3. **CounterpartiesPage "Оборот" Button** - Drilldown to turnover with counterparty filter

**Tests:** 12 pytest tests in `/app/backend/tests/test_finance_reports.py`
**Seed Script:** `/app/backend/scripts/seed_finance_data.py` - Creates test data for 2024-2026

### Phase: Clients Module + Monthly Export (DONE) - Feb 21, 2026
**Full implementation of Clients (Private Persons) and Finance Export:**

#### Backend (P1 - DONE)
1. **Clients API** (`/api/clients`) - Full CRUD with phone uniqueness per org
   - `phone_normalized` field for unique index
   - Find-or-create endpoint
   - Get by phone endpoint
2. **Counterparty-Client Linking** (`/api/counterparties/{id}/link-client`) - Link counterparty to client
   - Auto-link endpoint creates/finds client from counterparty phone
3. **Finance Export API** (`/api/reports/company-finance-export`)
   - PDF export with totals, weekly table, expense breakdown
   - XLSX export with 3 sheets (Summary, Weekly, Breakdown)

**New DB Collections:**
- `clients`: `{org_id, first_name, last_name, phone, phone_normalized, email, address, notes, is_active}`

#### Frontend (P1 - DONE)
1. **ClientsPage** (`/data/clients`) - DataTable with CRUD modals
   - Columns: Name, Surname, Phone, Email, Linked counterparties, Invoice count, Active
   - Turnover drilldown button
2. **Sidebar Update** - Added "Клиенти" to Данни section
3. **CounterpartiesPage Update**
   - "Свързан клиент" column for person-type counterparties
   - Auto-link button (UserPlus icon) for unlinking counterparties with phone
4. **FinanceSummaryWidget Export Button**
   - Dropdown menu with PDF/Excel options
   - Downloads finance report for selected year/month

**Tests:** 12 pytest tests in `/app/backend/tests/test_clients_module.py`

### Phase: Finance Compare 3 Months (DONE) - Feb 21, 2026
**Added 3-month comparison feature to FinanceSummaryWidget:**

#### Backend (P1.1 - DONE)
1. **Compare API** (`/api/reports/company-finance-compare`)
   - `?year=YYYY&months=01,02,03` - specific months
   - `?mode=last3` - automatic last 3 completed months
   - Returns: monthly totals, breakdown, bar/line chart data, overall totals

#### Frontend (P1.1 - DONE)
1. **View Toggle** - "Месец | 3 месеца" tabs
2. **Preset Selector** - "Последни 3", Q1-Q4 quarters
3. **Compare Summary Cards** - 3 cards with totals for period
4. **Bar Chart** - Income vs Expenses by month (3 groups)
5. **Line Chart** - Net balance trend (3 points)
6. **Details Table** - Month | Income | Expenses | Net | Top expense type

**Performance:** useMemo/useCallback for chart data, no re-renders on toggle

**Tests:** 4 pytest tests for compare endpoint in `/app/backend/tests/test_finance_reports.py`

### Phase: Dashboard Improvements P2 (DONE) - Feb 21, 2026
**Enhanced Dashboard with Activity Log and Comprehensive Finance Details Page:**

#### Backend (P2 - DONE)
1. **Dashboard Activity API** (`/api/dashboard/activity`)
   - Server-side pagination (page, limit params)
   - Aggregates recent actions from audit_logs
   - Returns clickable links to entities (invoices, projects, counterparties)

2. **Finance Series API** (`/api/reports/company-finance-series?months=N`)
   - Rolling period support (1, 3, 6, 12 months)
   - Returns monthly totals with income/expense breakdown
   - Period totals aggregation

3. **Finance Details APIs** (`/api/reports/finance-details/*`)
   - `/summary` - Period totals, breakdown, KPIs (avg weekly, shares)
   - `/by-counterparty` - Grouped by counterparty with pagination
   - `/by-project` - Grouped by project allocation with pagination
   - `/transactions` - Full transaction list with type/direction filters
   - `/top-counterparties` - Top 10 by spend or income

**Response Format (Finance Details Summary):**
```json
{
  "period": { "date_from": "...", "date_to": "..." },
  "totals": { "income": 0, "expenses": 0, "net": 0 },
  "breakdown": { "income_invoices": 0, "expenses_invoices": 0, ... },
  "counts": { "income_invoice_count": 0, ... },
  "kpis": { "avg_weekly_income": 0, "invoice_share": 0, ... }
}
```

#### Frontend (P2 - DONE)
1. **Last Activity Widget** on Dashboard
   - Shows 3 rows by default
   - "Покажи всички" button expands to 20 rows
   - "Зареди още" (Load More) with server-side pagination
   - Clickable links to entity details

2. **FinanceSummaryWidget Enhanced**
   - Rolling period selector (1 / 3 / 6 / 12 months)
   - "Период" / "По седмици" toggle for view mode
   - Charts update based on selected period
   - "Подробно" button links to Finance Details page

3. **FinanceDetailsPage** (`/reports/finance-details`)
   - Period filter with presets (Този месец, Последни 3/6/12 месеца, Тази година)
   - Custom date range support
   - 4 KPI summary cards
   - 5 tabs:
     - **Обобщение**: KPIs + Top 10 counterparties
     - **Разбивка**: Pie chart + breakdown table by expense type
     - **По контрагент**: Server-side paginated table
     - **По проект**: Server-side paginated table
     - **Транзакции**: Filterable transaction list with pagination
   - CSV Export for filtered data

**Tests:** 11 backend tests + full UI verification in `/app/test_reports/iteration_15.json`

### Update: Monthly Breakdown Table (Feb 21, 2026)
**Added monthly rows table to Finance Details page:**

- **Period Selector (1/3/6/12 месеца)** - Rolling period selection
- **Monthly Table** with exactly N rows based on selected period
- **ОБЩО (Totals) row** at the bottom - sticky, always visible
- **Columns:** Месец, Приходи, Разходи, Нетно, Фактури (П), Каса (П), Фактури (Р), Режийни, Заплати
- **Chart:** Bar chart showing Income vs Expenses by month
- **Month Format:** "Януари 2026", "Февруари 2026", etc.

**Backend:** Uses `/api/reports/company-finance-series?months=N` endpoint which returns exactly N consecutive months with breakdown data.

---

## Backlog (P3/P4)

### COMPLETED: Activity Types + Budgets - Feb 26, 2026

**A) Data Model Changes:**
- Offer lines now have `activity_type` (default "Общо") and `activity_subtype` (optional)
- New collection `activity_budgets` with unique constraint on (org_id, project_id, type, subtype)

**B) API Endpoints:**
- `GET /api/activity-types` - Returns list of standard activity types
- `GET /api/projects/{id}/activity-budgets` - List all budgets for project
- `POST /api/projects/{id}/activity-budgets` - Upsert budget (create or update by type+subtype)
- `DELETE /api/projects/{id}/activity-budgets/{budgetId}` - Delete budget
- `GET /api/projects/{id}/activity-budget-summary` - Returns grouped summary with:
  - labor_budget, materials_budget
  - labor_spent, materials_spent (from offer lines + daily logs)
  - labor_remaining, materials_remaining
  - percent_labor_used, percent_materials_used

**C) Frontend UI:**
- Offer lines now have Type/Subtype popover selector
- ActivityBudgetsPanel component shows budget vs spent per type
- Visual warnings for negative remaining (red) and >100% used
- Inline editing of budgets via modal

**D) Grouping Feature (Feb 26, 2026):**
- Toggle "Групирай по Тип/Подтип" in Offer Editor header
- Groups lines by (activity_type, activity_subtype)
- Group headers show:
  - Type/Subtype title + line count badge
  - Subtotals (Material, Labor, Total)
  - Budget vs Spent vs Remaining from summary endpoint
  - Visual warnings for over-budget
- Collapsible groups with "Разгъни/Сгъни" actions
- User preference persisted in localStorage
- Changing line's type/subtype immediately re-groups

**Tests:**
- 7 backend tests in `/app/backend/tests/test_activity_budgets.py`

---

### COMPLETED: Work Logs Module (Дневник + Промени СМР) - Feb 26, 2026

**A) Data Models:**
- `work_types`: { id, org_id, name, default_hourly_rate, is_active }
- `daily_work_logs`: { id, org_id, site_id, date, work_type_id, entries[], notes, attachments, total_hours, created_by }
- `change_orders`: { id, org_id, site_id, created_by, requested_at, kind (new/modify/cancel), labor_delta, material_delta, total_delta, description, status, audit_trail[] }

**B) API Endpoints:**
- `GET/POST/PATCH /api/work-types` - Work types CRUD (admin only)
- `GET/POST/PATCH/DELETE /api/daily-logs` - Daily work logs CRUD
- `GET/POST/PATCH /api/change-orders` - Change orders CRUD
- `POST /api/change-orders/{id}/submit` - Submit draft for approval
- `POST /api/change-orders/{id}/approve` - Approve (admin/site manager)
- `POST /api/change-orders/{id}/reject` - Reject (admin/site manager)
- `GET /api/my-sites` - Get user's accessible sites
- `GET /api/my-team/{site_id}` - Get team members for site

**C) Access Rules:**
- Technician/Requester: CRUD only for sites with membership
- Admin: Full access + approve/reject
- SiteManager: Can approve/reject for their sites

**D) Mobile-First UI:**
- `/daily-logs` - Daily work log management (list + new form)
- `/change-orders` - Change orders management (list + new form + detail dialog)
- Workflow: Draft → Submit → Pending Approval → Approved/Rejected

**DB Indexes:**
- daily_work_logs: (org_id, site_id, date), (org_id, date)
- change_orders: (org_id, site_id, status), (org_id, status, requested_at)

---

### COMPLETED: Offer Versions (History + Restore) - Mar 8, 2026

**Feature: Full version control for offers with history, preview and restore capabilities.**

**A) Data Model:**
- `offer_versions`: { id, org_id, project_id, offer_id, version_number, snapshot_json, created_at, created_by, note, is_auto_backup }
- Unique constraint on (org_id, offer_id, version_number)
- `snapshot_json` stores complete offer state: header fields, all lines with totals, metadata

**B) API Endpoints:**
- `POST /api/offers/{offerId}/versions` - Create new version (snapshot of current state)
- `GET /api/offers/{offerId}/versions` - List all versions (latest first, excludes snapshot_json for performance)
- `GET /api/offers/{offerId}/versions/{versionNumber}` - Get single version with full snapshot_json
- `POST /api/offers/{offerId}/versions/{versionNumber}/restore` - Restore version with **automatic backup**
- `DELETE /api/offers/{offerId}/versions/{versionNumber}` - Delete version (admin only)

**C) Critical Restore Safety:**
- Before overwriting current offer, creates automatic backup version
- Backup note: "Автоматичен backup преди възстановяване на vN"
- `is_auto_backup: true` flag distinguishes auto-backups from manual saves
- Totals recomputed after restore to ensure accuracy

**D) Frontend UI (`OfferVersionsPanel`):**
- Displays in offer editor sidebar (only for existing offers)
- List shows: version number, timestamp, creator name, note, auto-backup badge
- "Запази версия" button opens dialog with optional note input
- "Преглед" button opens modal with:
  - Version metadata (timestamp, creator, note)
  - Offer header info (title, status, VAT)
  - Full lines table with computed totals
  - Totals summary
- "Възстанови" button opens AlertDialog confirmation:
  - Warning message about replacing current offer
  - Green checkmark confirming automatic backup creation
- After restore, UI state updates to reflect restored offer data

**E) Permissions:**
- Create/Restore versions: Admin, Owner, SiteManager
- Delete versions: Admin, Owner only
- View versions: Anyone with project access

**DB Indexes:**
- offer_versions: (org_id, offer_id, version_number) unique
- offer_versions: (org_id, project_id, offer_id)

---

### BUGFIX: Invoice Lines Standard Structure - Mar 8, 2026

**Root Cause:**
Invoice lines were using offer/КСС-like structure with `cost_category` field and "Материали" column dropdown, which is inappropriate for standard sales invoices.

**Issues Fixed:**

1. **Removed offer-specific fields:**
   - Removed `COST_CATEGORIES` constant
   - Removed `cost_category` from addLine()
   - Removed `project_id` from line structure
   - Removed `getCostCategoryKey` helper function

2. **Simplified line structure:**
   ```javascript
   {
     id: string,
     description: string,
     unit: string,        // "pcs", "m", "m2", etc.
     qty: number,
     unit_price: number,
     line_total: number   // computed: qty * unit_price
   }
   ```

3. **Updated table UI:**
   - Columns: ОПИСАНИЕ | МЯРКА | К-ВО | ЕД. ЦЕНА | ОБЩО | (delete)
   - Removed "Материали" column completely
   - Better input styling with font-mono for numbers

4. **Clean save payload:**
   - Lines sent without `cost_category` and `project_id`
   - Only standard invoice line fields

**Calculations:**
- lineTotal = qty × unitPrice
- subtotal = sum(lineTotals)
- vatAmount = subtotal × (vatPercent / 100)
- total = subtotal + vatAmount

**Files Changed:**
- `/app/frontend/src/pages/InvoiceEditorPage.js`

---

### BUGFIX: Invoice Editor Form Improvements - Mar 8, 2026

**Issues Fixed:**

**1. Date Logic (dueDate >= issueDate):**
- Added real-time validation: red border + error message when dueDate < issueDate
- Added `min={issueDate}` HTML attribute on dueDate input
- Save blocked with clear alert if validation fails
- Auto-update dueDate when issueDate changes (if not manually edited)
- New state: `dueDateManuallyEdited` to track user edits

**2. Client Type Logic (company vs person):**
- Added `clientType` state variable set during auto-fill
- Company fields (ЕИК, ДДС номер, МОЛ) conditionally rendered
- For person clients: company fields hidden completely
- For company clients: all fields shown and auto-filled
- For direct access (no project): all fields shown (default behavior)

**3. Placeholder/Demo Value Pollution:**
- Removed misleading placeholder text (123456789, BG123456789, email@example.com)
- New placeholders: "ЕИК на фирмата", "ДДС номер", "Материално отговорно лице", etc.
- Added `placeholder:text-muted-foreground/50` class for visual distinction
- Auto-fill only fills fields with actual non-empty data from client
- Empty strings explicitly cleared for person clients (no company fields)

**4. Auto-Fill Banner Accuracy:**
- Banner only lists fields that were actually filled with real data
- Added `.trim()` checks before counting field as filled
- Separate handling for company vs person field lists
- No banner shown when accessing form directly without project

**Root Causes:**
1. **Date issue:** Missing validation logic, no min attribute on input
2. **Company fields for person:** No conditional rendering, same form for all client types
3. **Demo values:** Placeholder text looked like real values due to same styling

**Files Changed:**
- `/app/frontend/src/pages/InvoiceEditorPage.js`

**Feature: Complete client management system with unified search and project linking.**

**A) Data Model:**
| Collection | Fields |
|------------|--------|
| **companies** | id, org_id, name, eik, vat_number, mol, address, email, phone, notes, is_active, created_at, updated_at |
| **persons** | id, org_id, first_name, last_name, egn, phone, phone_normalized, email, address, notes, is_active, created_at, updated_at |
| **projects** | owner_type ("company"/"person"), owner_id (references companies.id or persons.id) |

**B) New API Endpoints:**
- `GET /api/clients/search/unified?query=&type=&limit=` - Unified search across companies and persons
- `POST /api/clients/company` - Create company client (with EIK duplicate detection)
- `POST /api/clients/person` - Create person client (with EGN/phone duplicate detection)
- `GET /api/projects/{projectId}/client-info` - Get linked client details
- `PATCH /api/projects/{projectId}/client-link` - Link/unlink client to project

**C) Search Logic:**
- **Company:** name, eik, vat_number, mol, phone
- **Person:** full_name, egn (masked in results), phone
- Query works universally - searches all relevant fields
- Results include type, display_name, identifier (masked EGN), phone, email

**D) Validation & Duplicate Protection:**
- EIK: 9 or 13 digits required
- EGN: 10 digits required (displayed masked as XX****XX)
- Phone normalization for consistent comparison
- 409 Conflict returned if duplicate EIK or EGN found

**E) Frontend Components:**

1. **ClientPickerModal** (`/app/frontend/src/components/ClientPickerModal.js`):
   - Step 1: Type selection (Фирма / Частно лице)
   - Step 2: Search with results list + "Избери" buttons
   - Step 3: Create new client form (if no results)
   - Auto-prefill search query as name in create form
   - Success: Creates client + links to project + closes modal

2. **ProjectDetailPage Client Card:**
   - Shows full client details (name, EIK/masked EGN, VAT, MOL, phone, email)
   - "Избери клиент" button when no client
   - "Преглед" (eye) and "Смени клиент" buttons when client exists
   - Client details modal with all fields

**F) Test Scenarios Verified:**
1. ✅ Search company by EIK → select → link to project
2. ✅ Search person by phone → select → link to project
3. ✅ Search with no results → create new company → auto-link
4. ✅ Search with no results → create new person → auto-link
5. ✅ Change existing client on project
6. ✅ Invoice auto-fill continues to work with client data

---

### P3 - Phase 3: Mobile Technician Flows
- Clock in/out from mobile
- Work report submission
- Photo uploads

### P3 - Phase 4: Mobile Driver Deliveries
- Delivery tracking
- Status updates

### P3 - Phase 5: Machine Movements
- Machine assignment tracking
- Usage logging

### P3 - M6: AI Invoice Capture
- OCR scanning of invoices
- Auto-population of invoice fields

### P3 - M7: Inventory Module
- Stock movements
- Inventory counts
- Stock alerts

### P3 - M8: Assets & QR Management
- Asset checkout/checkin
- QR code generation
- Maintenance tracking

### P3 - M9: Admin Console/BI
- Dashboard statistics
- Custom reports
- Overhead cost allocation

---

## Technical Stack
- **Backend:** FastAPI, Motor (MongoDB async), Pydantic
- **Frontend:** React, Shadcn/UI, TailwindCSS
- **Database:** MongoDB
- **Auth:** JWT with role-based access
- **Payments:** Stripe (test mode)

---

## Test Credentials
- **Admin:** admin@begwork.com / AdminTest123!Secure

---

## Key URLs (Data Module)

| URL | Page | Features |
|-----|------|----------|
| /data/warehouses | Складове | CRUD, filtering, CSV export |
| /data/counterparties | Контрагенти | CRUD, filtering, CSV export |
| /data/items | Артикули | CRUD, filtering, CSV export |
| /data/prices | Цени | Read-only, price history |
| /data/turnover | Оборот | Grand totals, drilldown |
| /data/clients | Клиенти | CRUD, filtering |
| /reports/finance-details | Финансови детайли | 5 tabs, filters, export |

---

## API Endpoints Summary (Data Module)

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/items | GET | List items with pagination/filters |
| /api/items | POST | Create new item |
| /api/items/{id} | GET | Get item by ID |
| /api/items/{id} | PUT | Update item |
| /api/items/{id} | DELETE | Soft delete item |
| /api/items/enums/categories | GET | Get categories enum |
| /api/warehouses | GET | List warehouses |
| /api/warehouses | POST | Create warehouse |
| /api/warehouses/{id} | GET/PUT/DELETE | Warehouse CRUD |
| /api/counterparties | GET | List counterparties |
| /api/counterparties | POST | Create counterparty |
| /api/counterparties/{id} | GET/PUT/DELETE | Counterparty CRUD |
| /api/prices | GET | Price history from invoice lines |
| /api/reports/turnover-by-counterparty | GET | Turnover by counterparty |
| /api/reports/turnover-by-counterparty/{id}/invoices | GET | Drilldown invoices |
| /api/reports/turnover-by-client | GET | Turnover by client (persons) |
| /api/reports/company-finance-summary | GET | Company finance summary |
| /api/finance/cash-transactions | GET/POST | Cash transactions CRUD |
| /api/finance/overhead-transactions | GET/POST | Overhead transactions CRUD |
| /api/finance/bonus-payments | GET/POST | Bonus payments CRUD |
| /api/clients | GET/POST | Clients (persons) CRUD |
| /api/clients/{id} | GET/PUT/DELETE | Single client operations |
| /api/clients/find-or-create | POST | Find or create client by phone |
| /api/clients/by-phone/{phone} | GET | Get client by phone number |
| /api/counterparties/{id}/link-client | POST | Link counterparty to client |
| /api/counterparties/{id}/auto-link-client | POST | Auto-find/create and link client |
| /api/reports/company-finance-export | GET | Export PDF/XLSX finance report |
| /api/reports/company-finance-compare | GET | Compare 3 months finance data |
| /api/dashboard/activity | GET | Dashboard activity log with pagination |
| /api/reports/company-finance-series | GET | Rolling N months finance series |
| /api/reports/finance-details/summary | GET | Finance summary with KPIs |
| /api/reports/finance-details/by-counterparty | GET | Finance by counterparty |
| /api/reports/finance-details/by-project | GET | Finance by project |
| /api/reports/finance-details/transactions | GET | All transactions with filters |
| /api/reports/finance-details/top-counterparties | GET | Top 10 counterparties |
| /api/finance/invoice-settings | GET/PUT | Invoice numbering settings |
| /api/finance/next-invoice-number | GET | Preview next invoice number |
| /api/finance/invoices/{id}/payments | GET/POST | List/add direct payments to invoice |
| /api/finance/invoices/{id}/payments/{alloc_id} | DELETE | Remove payment from invoice |

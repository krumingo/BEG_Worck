# BEG_Work PRD (Product Requirements Document)

## Overview
BEG_Work is an ERP system for construction/field service businesses with comprehensive project management, HR, finance, and inventory modules.

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

### COMPLETED: Invoice Auto-Fill from Project Client - Mar 8, 2026

**Feature: When creating a new invoice from a project, automatically fill client data.**

**A) Flow:**
- Project Detail Page → "Нова фактура" button → Invoice Editor with `?project_id=...`
- Invoice Editor reads `project_id` from URL query params
- Fetches project dashboard data including client info
- Auto-fills `counterpartyName` field with client name

**B) Frontend Changes (`InvoiceEditorPage.js`):**
- New state variables: `clientAutoFilled`, `noClientWarning`, `autoFilledClientData`
- On load with `project_id`: calls `/api/projects/{id}/dashboard`
- If client exists (person or company): fills name, shows green success banner
- If no client: shows amber warning banner with instructions
- Fields remain editable after auto-fill

**C) UI Banners:**
- Success (green): "Клиентските данни са попълнени автоматично от проекта (Тел: ...)" or "(ЕИК: ...)"
- Warning (amber): "Към проекта няма избран клиент. Попълнете клиента ръчно или изберете клиент в проекта."

**D) Backward Compatibility:**
- Direct access to `/finance/invoices/new` works as before (no banner, no auto-fill)
- No backend changes required (uses existing `/projects/{id}/dashboard` endpoint)
- No breaking changes to existing invoice creation flow

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

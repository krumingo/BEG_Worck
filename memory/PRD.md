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

---

## Backlog (P2/P3)

### P2 - Phase 3: Mobile Technician Flows
- Clock in/out from mobile
- Work report submission
- Photo uploads

### P2 - Phase 4: Mobile Driver Deliveries
- Delivery tracking
- Status updates

### P2 - Phase 5: Machine Movements
- Machine assignment tracking
- Usage logging

### P2 - M6: AI Invoice Capture
- OCR scanning of invoices
- Auto-population of invoice fields

### P2 - M7: Inventory Module
- Stock movements
- Inventory counts
- Stock alerts

### P2 - M8: Assets & QR Management
- Asset checkout/checkin
- QR code generation
- Maintenance tracking

### P2 - M9: Admin Console/BI
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

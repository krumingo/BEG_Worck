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

---

## Backlog (P1/P2)

### P1 - Clients Page Clarification
- Determine if Clients should be filtered view of counterparties (type=person/client) or separate model

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

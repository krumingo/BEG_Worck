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

### Phase: Data Module Backend P0 (DONE) - Feb 21, 2026
**Backend APIs for "Данни" (Data) module with ERP-style features:**

1. **Warehouses API** (`/api/warehouses`)
   - Full CRUD with server-side pagination
   - Filters: type, project_id, active_only, search
   - Response format: `{items, total, page, page_size, total_pages}`

2. **Counterparties API** (`/api/counterparties`)  
   - Full CRUD with server-side pagination
   - Filters: type (supplier/client/both), search, active_only
   - Invoice count enrichment
   - Response format: `{items, total, page, page_size}`

3. **Items/Materials API** (`/api/items`) - NEW
   - Full CRUD for inventory items
   - Fields: sku (unique), name, unit, category, brand, description, default_price, min_stock
   - Categories: Materials, Tools, Equipment, Consumables, Services, Other
   - Filters: category, search, is_active
   - Response format: `{items, total, page, page_size, total_pages}`

4. **Prices API** (`/api/prices`) - NEW
   - Purchase price history from invoice_lines
   - Aggregation with invoice data (date, supplier)
   - Filters: item_id, supplier_id, project_id, warehouse_id, date_from/to
   - Enriched with supplier_name, purchaser_name, allocation_summary

5. **Turnover Report API** (`/api/reports/turnover-by-counterparty`) - NEW
   - Aggregated purchases/sales by counterparty
   - Fields: count_invoices, sum_subtotal, sum_vat, sum_total, sum_paid, sum_remaining
   - Grand totals for all counterparties
   - Drilldown endpoint: `/api/reports/turnover-by-counterparty/{id}/invoices`

**Filter Operators Supported:**
- `contains` - case-insensitive regex match
- `equals` - exact match
- `in` - multiple values (pipe-separated)
- `bool` - boolean filter
- `min/max` - numeric range
- `from/to` - date range

**Database Indexes Added:**
- items: (org_id, sku) unique, (org_id, name), (org_id, category), (org_id, is_active)

**Tests Created:**
- `/app/backend/tests/test_data_module.py` - 18 tests all passing

---

## In Progress

### Phase: Data Module Frontend P0 (NOT STARTED)
**To implement:**
1. Add "Данни" section to sidebar with sub-pages
2. Create reusable `DataTable` component with:
   - Server-side pagination/sorting/filtering
   - URL state persistence for filters
   - CSV export functionality
   - Column configuration
3. Build pages:
   - Warehouses page
   - Counterparties page
   - Items/Materials page
   - Prices page
   - Turnover Report page
4. CRUD modals for each entity

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

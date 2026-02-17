# BEG_Work - Construction Company Management SaaS

## Problem Statement
Modular sellable SaaS for construction company management with multi-tenant architecture, role-based access, feature-flagged modules (M0-M9), and mobile-first technician/driver flows.

## Architecture
- **Backend**: FastAPI + MongoDB (motor async driver)
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn)
- **Auth**: JWT (python-jose) + bcrypt password hashing
- **Database**: MongoDB with collections: organizations, users, feature_flags, subscriptions, audit_logs

## User Personas
- **Admin/Owner**: Full platform access, manage org, users, modules, view audit logs
- **SiteManager**: Project oversight, attendance review, report approval
- **Technician**: Mobile attendance, daily work reports
- **Accountant**: Finance, invoicing, payroll
- **Warehousekeeper**: Inventory management
- **Driver**: Deliveries, proof tracking
- **Viewer**: Read-only access

## Core Requirements (Static)
- Multi-tenant data isolation per organization
- 8 roles: Admin, Owner, SiteManager, Technician, Accountant, Warehousekeeper, Driver, Viewer
- 10 feature-flagged modules (M0-M9)
- SaaS subscription management skeleton
- Audit logging for all state changes

## Modules
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | IMPLEMENTED (Iteration 1) |
| M1 | Projects | Backlog |
| M2 | Estimates / BOQ | Backlog |
| M3 | Attendance & Reports | Backlog |
| M4 | HR / Payroll | Backlog |
| M5 | Finance | Backlog |
| M6 | AI Invoice Capture | Backlog |
| M7 | Inventory | Backlog |
| M8 | Assets & QR | Backlog |
| M9 | Admin Console / BI | Backlog |

## What's Been Implemented
### Iteration 1 - M0 Core (2026-02-17)
- Organization, User, FeatureFlag, AuditLog, Subscription data models
- JWT authentication (login, /me, token validation)
- CRUD: Users (create/read/update/delete), Organization settings, Feature flags toggle
- Role-based access control (Admin/Owner for write operations)
- Audit logging for all mutations + logins
- Seed admin: admin@begwork.com / admin123
- Dark professional theme with amber accents (Plus Jakarta Sans font)
- Web admin: Login, Dashboard (4 stat cards + recent activity), Users table + CRUD dialogs, Company Settings form, Module toggles (10 cards with switches, M0 locked), Audit Log table with pagination
- Testing: 100% backend, 95% frontend pass rate

## Prioritized Backlog
### P0 (Next)
- M1 Projects: CRUD projects, assign teams, status tracking
- M3 Attendance: Daily attendance marking, work report submission

### P1
- M2 Estimates/BOQ: Offer creation, activity-based costing
- M4 HR/Payroll: Employee pay types, advances, payslip generation
- M5 Finance: Invoice management, partial payments, cash/bank

### P2
- M6 AI Invoice Capture: Upload/OCR/parse invoices
- M7 Inventory: Items, stock movements, warehouse management
- M8 Assets & QR: Asset tracking, checkout/checkin, QR codes
- M9 Admin Console/BI: Statistics dashboard, overhead cost system, alerts

## Next Tasks
1. Implement M1 Projects module (CRUD, team assignment, status)
2. Implement M3 Attendance & Daily Reports (mobile-optimized)
3. Add user registration flow for new organizations
4. Implement subscription plan management UI
5. Add M9 overhead cost calculation system

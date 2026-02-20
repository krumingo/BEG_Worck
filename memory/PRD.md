# BEG_Work - Product Requirements Document

## Overview
Modular SaaS application for construction company management built with React + FastAPI + MongoDB.

## Original Problem Statement
Build a comprehensive construction management SaaS platform with modules for projects, HR/payroll, finance, offers/BOQ, attendance tracking, overhead cost allocation, billing/subscriptions, and mobile workforce management.

## Architecture
```
/app/backend/
├── app/
│   ├── core/config.py          # Configuration settings
│   ├── db/__init__.py          # Database connection
│   ├── deps/                   # Dependencies (auth, modules)
│   ├── models/                 # Pydantic models (8 files)
│   │   ├── core.py, projects.py, offers.py, hr.py
│   │   ├── finance.py, overhead.py, billing.py, mobile.py
│   ├── routes/                 # FastAPI routers (13 files - ALL MIGRATED)
│   │   ├── health.py (4), auth.py (13), projects.py (13)
│   │   ├── attendance.py (25), offers.py (15), hr.py (18)
│   │   ├── finance.py (19), overhead.py (19)
│   │   ├── billing.py (9), mobile.py (6), media.py (5)
│   │   ├── platform.py (2)
│   ├── services/audit.py
│   ├── shared.py              # Shared dependencies (db, auth guards)
│   └── main.py                # Entry point
├── server.py                  # THIN ENTRY POINT (1098 lines, 0 direct routes)
│                              # Contains: Pydantic models, helpers, router includes
└── tests/                     # Pytest suite (198+ tests)
```

## What's Implemented (as of Feb 2025)

### Core Platform
- [x] Multi-tenant organization system
- [x] Role-based access control (Admin, Owner, SiteManager, Accountant, Technician, Driver)
- [x] JWT authentication
- [x] Subscription billing with Stripe (MOCKED)
- [x] User self-service password change (POST /api/auth/change-password)
- [x] **Admin password reset for users** (POST /api/admin/set-password/{user_id}) - NEW Feb 2025

### Modules
- [x] M0: Core (Auth, Org, Users)
- [x] M1: Projects CRUD with assignments
- [x] M2: Offers/BOQ with versioning
- [x] M3: Attendance + Work Reports
- [x] M4: HR/Payroll (profiles, advances, payslips)
- [x] M5: Finance (accounts, invoices, payments)
- [x] M9: Overhead cost allocation
- [x] M10: Billing/Usage limits

### Backend Refactoring Status
- **Stage 1.2 COMPLETE**: 100% (148/148 routes migrated to modular files)
- **server.py**: Now a thin entry point with only wiring code
- **Next**: Stage 1.3 (Media ACL security), Stage 1.4 (Dismantle shared.py)

## Recent Changes (Dec 2025)

### Stage 1.2 Backend Refactor - COMPLETED
- Migrated ALL routes from server.py to modular files in app/routes/
- Route files: billing.py (9), mobile.py (6), media.py (5), platform.py (2)
- server.py reduced from 2151 to 1098 lines (0 direct routes)
- All billing endpoints now properly secured (Admin/Owner for checkout, Platform Admin for config)
- Tests: 42 passed in billing/platform suite

### Platform Admin Portal (P0) - NEW
- **Separate SuperAdmin login**: `/platform/login` - isolated from client `/login`
- **Platform Dashboard**: `/platform` with dedicated layout and navigation
- **Platform-only pages**:
  - `/platform/billing` - Stripe configuration
  - `/platform/modules` - Feature module toggles
  - `/platform/audit-log` - System audit trail
  - `/platform/mobile-settings` - Mobile app configuration
- **Bootstrap endpoint** (ONE-TIME USE):
  - `POST /api/platform/bootstrap-create-platform-admin`
  - Creates new user OR promotes existing to platform admin
  - Protected by `PLATFORM_BOOTSTRAP_TOKEN` env var
  - **REMOVE TOKEN AFTER USE**

### Platform Admin Access Control (P0)
- Added `is_platform_admin` user field (default: false)
- Added `require_platform_admin` dependency guard
- Protected endpoints:
  - `GET/POST /api/billing/config`, checkout, portal
  - `GET/PUT/DELETE /api/mobile/settings/*`
  - `PUT /api/feature-flags` (GET allowed for all)
  - `GET /api/audit-logs`
- Frontend: System tabs hidden for non-platform admins
- Frontend: NotAuthorizedPage for direct URL access
- Tests: 11 tests in `test_platform_bootstrap.py`, 10 in `test_platform_admin.py`

### Admin Set Password Feature
- Backend: `POST /api/admin/set-password/{user_id}`
- Frontend: `AdminResetPasswordModal.js` component
- Audit logging: `admin_password_reset` action

## Test Credentials
- Admin: admin@begwork.com / admin123
- Manager: manager@begwork.com / manager123
- Technician: tech@begwork.com / TechPass123!Secure

## API Contract
- Total endpoints: 149 (added admin/set-password)
- Baseline: /app/baseline_audit_endpoints.csv

## Backlog (P1)
1. Complete billing/mobile/media migration
2. Dismantle shared.py, implement proper DI
3. Mobile Phase 3-5 (Technician, Driver, Machine)

## Backlog (P2)
- M6: AI Invoice Capture
- M7: Inventory module
- M8: Assets & QR codes
- Performance: N+1 query optimization
- Phone + OTP authentication for low-privilege roles

## Tech Stack
- Frontend: React 18, TailwindCSS, Shadcn/UI
- Backend: FastAPI, Motor (async MongoDB)
- Database: MongoDB
- Payments: Stripe (mock mode)

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
│   ├── routes/                 # FastAPI routers (8 files migrated)
│   │   ├── health.py (4), auth.py (12), projects.py (13)
│   │   ├── attendance.py (25), offers.py (15), hr.py (18)
│   │   ├── finance.py (19), overhead.py (19)
│   ├── services/audit.py
│   ├── shared.py              # Temporary shared module
│   └── main.py                # Entry point
├── server.py                  # Legacy (2151 lines, 20 routes remaining)
└── tests/                     # Pytest suite (168+ tests)
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
- **Completed**: 86% (124/144 routes migrated)
- **Remaining**: billing (9), mobile (6), media (5)

## Recent Changes (Feb 2025)
- **Admin Set Password Feature**: Admin/Owner can reset passwords for any user via Users page dropdown menu
  - Backend: `POST /api/admin/set-password/{user_id}`
  - Frontend: `AdminResetPasswordModal.js` component
  - Audit logging: `admin_password_reset` action with target_email
  - Password validation: min 10 chars, uppercase, lowercase, digit, special char

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

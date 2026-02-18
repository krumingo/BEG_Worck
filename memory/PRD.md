# BEG_Work - Construction Company Management SaaS

## Original Problem Statement
Build a modular, sellable SaaS application named "BEG_Work" for construction company management. The development proceeds in 10 distinct iterations with multi-tenant architecture and role-based access control.

## Core Requirements
- Multi-tenant architecture with data isolation by company/organization
- Role-based access control (Admin, Owner, SiteManager, Technician, etc.)
- Feature-flagged modules

## User Personas
- **Admin/Owner**: Full access to all modules, company settings, user management
- **Site Manager**: Manage attendance, work reports, project teams
- **Technician**: Mark attendance, submit work reports

## Modules
- M0: Core/SaaS (tenancy, auth, roles, billing skeleton) ✅
- M1: Projects ✅
- M2: Estimates/BOQ ✅
- M3: Attendance & Daily Reports ✅
- M4: HR/Payroll-lite ✅
- M5: Finance ✅
- M6: AI Invoice Capture (UPCOMING)
- M7: Inventory (UPCOMING)
- M8: Assets & QR (UPCOMING)
- M9: Admin Console/BI - Alerts ✅ | Overhead Cost System ✅

## Technical Stack
- **Backend**: FastAPI, Motor (async MongoDB), JWT authentication
- **Frontend**: React, TailwindCSS, Shadcn/UI, react-i18next
- **Database**: MongoDB

## What's Been Implemented

### February 2026 - Iteration 9: M9 Overhead Cost System ✅
- ✅ Data Models: OverheadCategory, OverheadCost, OverheadAsset, OverheadSnapshot, ProjectOverheadAllocation
- ✅ Calculation Logic: Total overhead from costs + asset amortization, person-days from attendance, hours from work reports
- ✅ Snapshot Computation: €/person-day and €/hour rates
- ✅ Project Allocation: Distribute overhead based on PersonDays or Hours method
- ✅ API Endpoints: CRUD for categories, costs, assets; snapshot compute and allocation
- ✅ Permissions: Admin/Owner/Accountant full access, SiteManager read-only, Technician blocked
- ✅ Frontend Pages: OverheadPage (Dashboard, Costs, Assets, Snapshots tabs), OverheadSnapshotDetailPage
- ✅ i18n: Full Bulgarian translations for overhead section

### February 2026 - i18n Patch COMPLETE ✅
- ✅ Installed and configured react-i18next with Bulgarian (bg) as default language
- ✅ Created comprehensive translation files: `/app/frontend/src/i18n/en.json` and `bg.json`
- ✅ Translated core pages: Login, Dashboard, all M5 Finance pages
- ✅ Translated operational pages: MyDay, AttendanceHistory, WorkReportForm, SiteAttendance, WorkReportReview
- ✅ Translated management pages: Reminders, Notifications, Projects, ProjectDetail
- ✅ Translated commercial pages: OffersList, OfferEditor, ActivityCatalog
- ✅ Translated HR/Payroll pages: Employees, Advances, PayrollRuns, PayrollDetail, MyPayslips
- ✅ Translated admin pages: Users, CompanySettings, ModuleToggles, AuditLog
- ✅ Added formatDate, formatTime, formatDateTime utility functions for locale-aware formatting
- ✅ Translated all navigation menu items in DashboardLayout
- ✅ Language Switcher (BG/EN toggle) working with localStorage persistence
- ✅ **BG Mode Sweep PASSED: ZERO English UI strings visible in Bulgarian mode**

### Previous Sessions
- M0-M5 modules fully implemented
- M9 Alerts (Reminders system) implemented
- Test files created at `/app/backend/tests/test_finance.py`

## Prioritized Backlog

### P0 - Critical
- NONE - i18n patch completed

### P1 - Next Iteration
- M9: Overhead Cost System - Admin Console/BI statistics

### P2 - Future
- M6: AI Invoice Capture (upload/parse invoices)
- M7: Inventory (items + movements)
- M8: Assets & QR (checkout/checkin, maintenance)
- Backend refactoring: Break down monolithic `server.py` into `/routes`, `/models`

## Key API Endpoints
- `/api/auth/*` - Authentication
- `/api/projects/*` - Projects CRUD
- `/api/offers/*` - Offers/BOQ CRUD
- `/api/attendance/*` - Attendance tracking
- `/api/work-reports/*` - Work reports
- `/api/finance/*` - Accounts, Invoices, Payments
- `/api/employees/*` - Employee profiles
- `/api/payroll/*` - Payroll runs
- `/api/reminders/*` - Reminders system

## Credentials
- Admin: `admin@begwork.com` / `admin123`
- Manager: `manager@begwork.com` / `manager123`
- Technician: `tech@begwork.com` / `tech123`

## Known Issues
- `server.py` is monolithic and should be refactored (non-blocking)

## Files Structure
```
/app/
├── backend/
│   ├── server.py        # Main FastAPI app
│   ├── requirements.txt
│   └── tests/
│       └── test_finance.py
└── frontend/
    ├── src/
    │   ├── components/  # Reusable components
    │   ├── contexts/    # AuthContext
    │   ├── i18n/
    │   │   ├── bg.json  # Bulgarian translations
    │   │   ├── en.json  # English translations
    │   │   ├── i18n.js  # i18n configuration
    │   │   └── i18nUtils.js # Locale-aware formatting utilities
    │   ├── pages/       # Page components
    │   └── services/    # API service wrappers
    ├── package.json
    └── yarn.lock
```

# BEG_Work - Construction Company Management SaaS

## Original Problem Statement
Build a modular, sellable SaaS application named "BEG_Work" for construction company management. The development proceeds in 10 distinct iterations with multi-tenant architecture and role-based access control.

## Core Requirements
- Multi-tenant architecture with data isolation by company/organization
- Role-based access control (Admin, Owner, SiteManager, Technician, etc.)
- Feature-flagged modules
- **SaaS billing with self-onboarding (Iteration 10)** ✅

## User Personas
- **Admin/Owner**: Full access to all modules, company settings, user management, billing
- **Site Manager**: Manage attendance, work reports, project teams
- **Technician**: Mark attendance, submit work reports

## Subscription Plans
- **Free Trial**: 14 days, M0+M1+M3 (Core, Projects, Attendance)
- **Pro** (€49/month): All current modules (M0-M5, M9)
- **Enterprise** (€149/month): All modules + unlimited users

## Modules
- M0: Core/SaaS (tenancy, auth, roles, billing) ✅
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
- **Backend**: FastAPI, Motor (async MongoDB), JWT authentication, Stripe
- **Frontend**: React, TailwindCSS, Shadcn/UI, react-i18next
- **Database**: MongoDB

## What's Been Implemented

### February 2026 - Iteration 10: M10 SaaS Billing & Self-Onboarding ✅ (CURRENT)
- ✅ Public signup endpoint with org + user + subscription creation
- ✅ 14-day free trial with automatic status tracking
- ✅ 3 billing plans: Free, Pro (€49), Enterprise (€149)
- ✅ Stripe integration with MOCK MODE for development
- ✅ Mock checkout directly upgrades subscription without payment
- ✅ Module gating via `/api/billing/check-module/{code}`
- ✅ Trial expiration auto-updates status to `past_due`
- ✅ Frontend pages: SignupPage, PlanSelectionPage, BillingSettingsPage
- ✅ Success/Cancel pages for checkout flow
- ✅ Full i18n support (Bulgarian + English)
- ✅ Backend tests: 15/15 passed (`/app/backend/tests/test_m10_billing.py`)
- ✅ Required Stripe env vars documented: STRIPE_API_KEY, STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_ENTERPRISE, STRIPE_WEBHOOK_SECRET

### February 2026 - Usage Tracking & Limits Enforcement Patch ✅
- ✅ Usage tracking: GET `/api/billing/usage` returns users, projects, invoices (monthly), storage counts
- ✅ Plan limits enforced on create operations (users, projects, invoices)
- ✅ Limit error codes: `LIMIT_USERS_EXCEEDED`, `LIMIT_PROJECTS_EXCEEDED`, `LIMIT_INVOICES_EXCEEDED`
- ✅ Warning threshold at 80% usage
- ✅ Frontend usage section in BillingSettingsPage with progress bars and warnings
- ✅ i18n support for all usage strings (Bulgarian + English)
- ✅ Backend tests: 10/10 passed (`/app/backend/tests/test_usage_limits.py`)
- ✅ Updated plan limits:
  - Free: 3 users, 2 projects, 5 invoices/month, 100 MB storage
  - Pro: 20 users, 50 projects, 500 invoices/month, 2 GB storage
  - Enterprise: 100 users, 500 projects, 5000 invoices/month, 20 GB storage

### February 2026 - Mobile Integration Phase 1 + 2 ✅
**Phase 1 - Mobile Settings + Mobile Views:**
- ✅ Data models: `OrgMobileSettings`, `MobileViewConfig` in MongoDB
- ✅ Bootstrap endpoint: `GET /api/mobile/bootstrap` - single source of truth for mobile config
- ✅ Server-side enforcement: field filtering and action blocking helpers
- ✅ Admin endpoints: `/api/mobile/settings`, `/api/mobile/view-configs`
- ✅ Default configs per role: Technician, Driver, SiteManager
- ✅ Available modules: attendance, workReports, deliveries, machines, messages, media, profile
- ✅ Admin UI: MobileSettingsPage with Enabled Modules + View Configs tabs
- ✅ i18n support (Bulgarian + English)

**Phase 2 - Unified Media (Photos):**
- ✅ MediaFile model with context linking
- ✅ Endpoints: `POST /api/media/upload`, `POST /api/media/link`, `GET /api/media/{id}`, `GET /api/media/file/{filename}`
- ✅ File validation: allowed types (JPEG, PNG, WebP, HEIC), max 10MB
- ✅ Permission checking: owner/admin access
- ✅ Backend tests: 18/18 passed (`/app/backend/tests/test_mobile_integration.py`)

### February 2026 - Iteration 9: M9 Overhead Cost System ✅
- ✅ Data Models: OverheadCategory, OverheadCost, OverheadAsset, OverheadSnapshot, ProjectOverheadAllocation
- ✅ Calculation Logic: Total overhead from costs + asset amortization
- ✅ Snapshot Computation: €/person-day and €/hour rates
- ✅ Project Allocation: Distribute overhead based on PersonDays or Hours method
- ✅ Frontend Pages: OverheadPage, OverheadSnapshotDetailPage
- ✅ i18n: Full Bulgarian translations for overhead section

### Previous Sessions
- M0-M5 modules fully implemented
- M9 Alerts (Reminders system) implemented
- i18n patch completed with 100% Bulgarian translations

## Prioritized Backlog

### P0 - Critical
- NONE - Iteration 10 completed

### P1 - Future Iterations
- M6: AI Invoice Capture (upload/parse invoices)
- M7: Inventory (items + movements)
- M8: Assets & QR (checkout/checkin, maintenance)

### P2 - Enhancements
- Backend refactoring: Break down monolithic `server.py` into `/routes`, `/models`
- M9 Complete: Full Admin Console/BI statistics dashboard

## Key API Endpoints

### Billing (NEW)
- `GET /api/billing/plans` - List all plans (public)
- `GET /api/billing/config` - Stripe configuration status
- `POST /api/billing/signup` - Create new org with owner (public)
- `GET /api/billing/subscription` - Current subscription details
- `GET /api/billing/usage` - Current usage vs plan limits with percentages
- `POST /api/billing/create-checkout-session` - Stripe checkout (mock mode supported)
- `POST /api/billing/create-portal-session` - Stripe customer portal
- `POST /api/billing/webhook` - Stripe webhook handler
- `GET /api/billing/check-module/{code}` - Check module access

### Mobile Integration (NEW)
- `GET /api/mobile/bootstrap` - Single source of truth for mobile configuration
- `GET /api/mobile/settings` - Get organization mobile settings (admin)
- `PUT /api/mobile/settings` - Update enabled modules (admin)
- `GET /api/mobile/view-configs` - List all view configs (admin)
- `PUT /api/mobile/view-configs` - Update view config for role/module (admin)
- `DELETE /api/mobile/view-configs/{role}/{module}` - Reset config to defaults (admin)

### Media (NEW)
- `POST /api/media/upload` - Upload media file with optional context
- `POST /api/media/link` - Link existing media to context
- `GET /api/media/{id}` - Get media metadata
- `GET /api/media/file/{filename}` - Serve media file content
- `GET /api/media` - List media files (filtered by context)

### Existing
- `/api/auth/*` - Authentication
- `/api/projects/*` - Projects CRUD
- `/api/offers/*` - Offers/BOQ CRUD
- `/api/attendance/*` - Attendance tracking
- `/api/work-reports/*` - Work reports
- `/api/finance/*` - Accounts, Invoices, Payments
- `/api/employees/*` - Employee profiles
- `/api/payroll/*` - Payroll runs
- `/api/overhead/*` - Overhead costs system
- `/api/reminders/*` - Reminders system

## Credentials
- Admin: `admin@begwork.com` / `admin123`
- Manager: `manager@begwork.com` / `manager123`
- Technician: `tech@begwork.com` / `tech123`

## Environment Variables for Real Stripe
```
STRIPE_API_KEY=sk_live_xxx or sk_test_xxx
STRIPE_PRICE_ID_PRO=price_xxx
STRIPE_PRICE_ID_ENTERPRISE=price_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

## Known Issues
- `server.py` is monolithic and should be refactored (non-blocking)

## Audit Report (18 Feb 2026)
Full audit completed. See `/app/AUDIT_REPORT.md` for details:
- **144 API endpoints** documented and verified
- **30 MongoDB collections** identified
- **48 Pydantic models** cataloged
- **Top 10 risks** identified with mitigation plan
- **3-stage patch plan** created:
  - Stage 1: Stabilization (refactoring, security)
  - Stage 2: Functionality (Deliveries, Machines, Real Stripe)
  - Stage 3: Mobile App (React Native/Flutter)

## Files Structure
```
/app/
├── backend/
│   ├── server.py        # Main FastAPI app (4700+ lines)
│   ├── requirements.txt
│   └── tests/
│       ├── test_finance.py
│       ├── test_m9_overhead.py
│       └── test_m10_billing.py  # NEW
└── frontend/
    ├── src/
    │   ├── components/  # Reusable components
    │   ├── contexts/    # AuthContext
    │   ├── i18n/
    │   │   ├── bg.json  # Bulgarian translations (with billing)
    │   │   ├── en.json  # English translations (with billing)
    │   │   └── ...
    │   ├── pages/
    │   │   ├── SignupPage.js         # NEW
    │   │   ├── PlanSelectionPage.js  # NEW
    │   │   ├── BillingSettingsPage.js # NEW
    │   │   ├── BillingSuccessPage.js  # NEW
    │   │   ├── BillingCancelPage.js   # NEW
    │   │   └── ...
    │   └── services/
    ├── package.json
    └── yarn.lock
```

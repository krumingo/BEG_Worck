# BEG_Work - Construction Management SaaS

## Original Problem Statement
BEG_Work is a comprehensive construction management SaaS platform designed to streamline operations for construction companies. The platform provides project management, resource tracking, billing, and administrative capabilities.

## User Personas
1. **Company Admin** - Manages company projects, users, billing
2. **Platform Admin** - Super admin with cross-organization access
3. **Technician** - Field worker tracking work and materials
4. **Driver** - Handles deliveries and logistics

## Core Requirements
- Multi-tenant architecture with organization isolation
- Role-based access control (RBAC)
- Project and resource management
- Media file management with security ACLs
- Billing and invoicing
- Mobile-friendly interfaces for field workers

---

## What's Been Implemented

### Session: 2026-02-21

#### Backend Refactoring (Stages 1.2, 1.4, 1.5) ✅
- Migrated all routes from monolithic `server.py` to modular `app/routes/` structure
- Dismantled `app/shared.py` into clean dependency structure:
  - `app/deps/` - FastAPI dependencies for auth, modules, ACLs
  - `app/utils/` - Pure helper functions (audit, crypto)
  - `app/db/` - Database connection handling
  - `app/constants.py` - App-wide constants

#### Pytest Suite Stabilization ✅
- Fixed dozens of pre-existing test failures
- Achieved **212/212 tests passing** (100% pass rate)
- Created `/app/backend/tests/test_utils.py` for centralized test helpers

#### Media ACL Security (Stage 1.3) ✅
- Audited all media endpoints
- Added secure `DELETE /media/{id}` endpoint
- Created `/app/backend/tests/test_media_acl.py` with 13 security tests
- Blocked all cross-organization access (IDOR protection)

#### Login Flow Isolation ✅
- Created separate `PlatformAuthProvider` and `usePlatformAuth` for super-admin
- Isolated local storage: `bw_token` (company) vs `bw_platform_token` (platform)
- Implemented separate route guards for `/` and `/platform` sections

#### Calendar UI Bug Fix ✅ (Verified 2026-02-21)
- Created new `DatePicker.js` component using shadcn/ui Calendar + Popover
- Fixed invisible calendar in dark mode
- Fixed `.toLowerCase()` crash in `ProjectsListPage.js`

---

## Prioritized Backlog

### P1 - High Priority
- [x] Optimize N+1 query in `GET /media` endpoint (2026-02-21) - Batch prefetch for context data
- [x] Update `flow_map.md` documentation for `DELETE /api/media/{id}` (2026-02-21)

### P2 - Medium Priority
- [x] **Sites Module Phase 1** (2026-02-21) - Owner registry (persons/companies), address field, status filters
- [x] **Sites Photos** (2026-02-21) - Upload from mobile, gallery in web detail, lightbox, delete ACL
- [ ] Phase 3: Mobile Technician flows
- [ ] Phase 4: Mobile Driver deliveries
- [ ] Phase 5: Machine movements

### P3 - Future Modules
- [ ] M6: AI Invoice Capture
- [ ] M7: Inventory module
- [ ] M8: Assets & QR code management
- [ ] M9: Complete Admin Console/BI dashboard

---

## Technical Architecture

```
/app/
├── backend/
│   ├── app/
│   │   ├── constants.py       # App-wide constants (ROLES, etc.)
│   │   ├── db/                # DB connection handling
│   │   ├── deps/              # FastAPI dependencies
│   │   │   ├── auth.py
│   │   │   ├── media_acl.py
│   │   │   └── modules.py
│   │   ├── models/
│   │   ├── routes/            # All API routes
│   │   └── utils/             # Helper functions
│   ├── server.py              # Thin entry point
│   └── tests/                 # 212 tests, 100% passing
└── frontend/
    └── src/
        ├── App.js             # Dual Auth Providers
        ├── components/ui/     # Shadcn components + DatePicker
        ├── contexts/          # Company + Platform auth
        └── pages/
```

## Test Credentials
- **Company Admin:** admin@begwork.com / AdminTest123!Secure
- **Technician:** tech@begwork.com / TechTest123!Secure

## 3rd Party Integrations
- **Stripe:** Payment processing (test mode)

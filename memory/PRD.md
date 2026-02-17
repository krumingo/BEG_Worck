# BEG_Work - Construction Company Management SaaS

## Problem Statement
Modular sellable SaaS for construction company management with multi-tenant architecture, role-based access, feature-flagged modules (M0-M9), and mobile-first technician/driver flows.

## Architecture
- **Backend**: FastAPI + MongoDB (motor async driver)
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn)
- **Auth**: JWT (python-jose) + bcrypt password hashing
- **Database**: MongoDB with collections: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases

## User Personas
- **Admin/Owner**: Full platform access, manage org, users, modules, projects, view audit logs
- **SiteManager**: Project oversight, manage assigned projects/teams, attendance review
- **Technician**: Mobile attendance, daily work reports, view assigned projects
- **Accountant**: Finance, invoicing, payroll
- **Warehousekeeper**: Inventory management
- **Driver**: Deliveries, proof tracking
- **Viewer**: Read-only access to assigned projects

## Modules
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | IMPLEMENTED (Iter 1) |
| M1 | Projects | IMPLEMENTED (Iter 2) |
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
- Org/User/FeatureFlag/AuditLog/Subscription models + JWT auth
- CRUD: Users, Org settings, Feature flags, Audit log
- Seed admin: admin@begwork.com / admin123
- Dark professional theme, 6 admin screens

### Iteration 2 - M1 Projects (2026-02-17)
- Project model: code (unique/org), name, status, type, dates, budget, tags, notes
- ProjectTeamMember: user assignment with project-specific roles (SiteManager/Technician/Viewer)
- ProjectPhase: ordered phases with status and date tracking
- CRUD + team management + phase management endpoints
- Role-based permissions: Admin/Owner full, SiteManager assigned-only, Technician read-only assigned
- Projects list page with filters (status/type/search)
- Project detail page with overview, Team tab, Phases tab
- Dashboard KPIs: Active/Paused/Completed projects + Projects Overview section
- Audit logging for all project actions
- Testing: Backend 100% (41/41), Frontend 85%+ (fixed technician dashboard)

## Prioritized Backlog
### P0 (Next)
- M3 Attendance & Daily Reports: attendance marking, work report submission, reminders
- M2 Estimates/BOQ: offer creation, activity-based costing tied to projects

### P1
- M4 HR/Payroll: employee pay types, advances, payslip generation
- M5 Finance: invoice management, partial payments, cash/bank

### P2
- M6 AI Invoice Capture: upload/OCR/parse invoices
- M7 Inventory: items, stock movements
- M8 Assets & QR: asset tracking, QR codes
- M9 Admin Console/BI: statistics, overhead cost system

## Next Tasks
1. M3 Attendance & Daily Reports (mobile-optimized technician flows)
2. M2 Estimates/BOQ tied to projects
3. SiteManager-specific project dashboard
4. Mobile-responsive layouts for technician screens
5. M9 Overhead cost calculation system

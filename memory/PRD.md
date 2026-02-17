# BEG_Work - Construction Company Management SaaS

## Architecture
- **Backend**: FastAPI + MongoDB (motor async) — server.py ~2100 lines
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn) — 19 pages
- **Auth**: JWT + bcrypt
- **DB Collections**: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases, attendance_entries, work_reports, reminder_logs, notifications, offers, activity_catalog

## Modules Status
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | DONE (Iter 1) |
| M1 | Projects | DONE (Iter 2) |
| M3 | Attendance & Reports | DONE (Iter 3-4) |
| M9 | Reminders & Alerts | DONE (Iter 5) |
| M2 | Estimates / BOQ | DONE (Iter 6) |
| M4 | HR / Payroll | Backlog |
| M5 | Finance | Backlog |
| M6 | AI Invoice Capture | Backlog |
| M7 | Inventory | Backlog |
| M8 | Assets & QR | Backlog |
| M9 | Admin Console / BI (Full) | Backlog |

## Implementation Log

### Iteration 1 - M0 Core
- Org/User/FeatureFlag/AuditLog/Subscription + JWT auth + seed admin
- 6 admin screens

### Iteration 2 - M1 Projects
- Project CRUD, team management, phases, role-based permissions

### Iteration 3 - M3 Attendance
- AttendanceEntry with uniqueness, self/manager marking, auto-Late
- My Day, History, Site Attendance pages + configurable window

### Iteration 4 - M3 Daily Work Reports
- WorkReport model: Draft→Submitted→Approved/Rejected workflow
- Lines embedded (activity_name + hours + note), total_hours computed
- Uniqueness per (org, date, user, project), requires Present/Late attendance

### Iteration 5 - M9 Reminders & Alerts
- ReminderLog/Notification models, 7 API endpoints, 15-min scheduler
- NotificationBell, NotificationsPage, RemindersPage, Dashboard widgets

### Iteration 6 - M2 Estimates / BOQ (2026-02-17)
**Data Models:**
- Offer: id, orgId, projectId, offerNo (unique/org), title, status (Draft|Sent|Accepted|Rejected|Archived), version, parentOfferId, currency, vatPercent, subtotal, vatAmount, total, notes, timestamps
- OfferLine (embedded): id, activityCode, activityName, unit, qty, materialUnitCost, laborUnitCost, laborHoursPerUnit, lineMaterialCost, lineLaborCost, lineTotal, note, sortOrder
- ActivityCatalogItem: id, orgId, projectId, code, name, defaultUnit, defaultMaterialUnitCost, defaultLaborUnitCost, defaultLaborHoursPerUnit, active

**Rules:**
- OfferNo unique per org (format: OFF-0001)
- Versioning: "New Version" clones lines, increments version, sets parentOfferId
- Accepted offers locked (no edits), new version required

**API Endpoints:**
- POST /api/offers - Create draft offer
- GET /api/offers?projectId=&status= - List with filters
- GET /api/offers/{id} - Get single offer
- PUT /api/offers/{id} - Update draft
- PUT /api/offers/{id}/lines - Update BOQ lines
- POST /api/offers/{id}/send - Send offer
- POST /api/offers/{id}/accept - Accept (Admin/Owner)
- POST /api/offers/{id}/reject - Reject (Admin/Owner)
- POST /api/offers/{id}/new-version - Clone to new version
- DELETE /api/offers/{id} - Delete (not accepted)
- CRUD /api/activity-catalog - Activity catalog management
- GET /api/offer-enums - Status and unit enums

**Frontend:**
- OffersListPage: Table with filters (search, project, status)
- OfferEditorPage: BOQ table with live totals, actions (Save, Send, Accept, Reject, New Version)
- ActivityCatalogPage: CRUD table with dialog form
- WorkReportFormPage: Optional activity picker from catalog
- DashboardLayout: Offers and Activities navigation links

**Testing:** Backend 100% (25/25), Frontend 100%

## Credentials
- Admin: admin@begwork.com / admin123
- Tech1: tech1@begwork.com / tech123
- Tech2: tech2@begwork.com / tech123

## API Endpoints Summary
- `/api/auth/` - login, me
- `/api/organization` - org settings
- `/api/users` - CRUD
- `/api/feature-flags` - module toggles
- `/api/audit-logs` - activity logs
- `/api/projects` - CRUD with team/phases
- `/api/attendance` - mark, my-today, my-range, site-today, missing-today
- `/api/work-reports` - draft, edit, submit, approve, reject, list
- `/api/reminders` - policy, missing-attendance, missing-work-reports, logs, send, excuse
- `/api/notifications` - my, mark-read
- `/api/offers` - CRUD, send, accept, reject, new-version, lines
- `/api/activity-catalog` - CRUD
- `/api/dashboard/stats` - dashboard statistics

## Next Tasks (Priority Order)
1. **M4 HR/Payroll-lite** - pay types (hourly/daily/monthly), advances/loans, payslips
2. **M5 Finance** - invoices issued/received, payments
3. **M9 Overhead Cost System** - cost tracking and calculation
4. **M6 AI Invoice Capture** - upload, parse, approval queue
5. **M7 Inventory** - items, stock movements, warehouses
6. **M8 Assets & QR** - checkout/checkin, maintenance, warranty

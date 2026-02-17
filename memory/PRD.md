# BEG_Work - Construction Company Management SaaS

## Architecture
- **Backend**: FastAPI + MongoDB (motor async driver)
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn)
- **Auth**: JWT (python-jose) + bcrypt
- **DB Collections**: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases, attendance_entries

## Modules
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | DONE (Iter 1) |
| M1 | Projects | DONE (Iter 2) |
| M3 | Attendance & Reports | ATTENDANCE DONE (Iter 3), Reports next |
| M2 | Estimates / BOQ | Backlog |
| M4 | HR / Payroll | Backlog |
| M5 | Finance | Backlog |
| M6 | AI Invoice Capture | Backlog |
| M7 | Inventory | Backlog |
| M8 | Assets & QR | Backlog |
| M9 | Admin Console / BI | Backlog |

## Implementation Log

### Iteration 1 - M0 Core (2026-02-17)
- Org/User/FeatureFlag/AuditLog/Subscription models + JWT auth + seed admin
- 6 admin screens: Login, Dashboard, Users, Settings, Modules, Audit Log

### Iteration 2 - M1 Projects (2026-02-17)
- Project CRUD with code uniqueness, team management, phases
- Role-based permissions, project list with filters, project detail page

### Iteration 3 - M3 Attendance (2026-02-17)
- AttendanceEntry model with org+date+user uniqueness constraint
- Self-marking (POST /attendance/mark) with auto-Late detection past deadline
- Manager mark-for-user with project-level permission checks
- Endpoints: my-today, my-range, site-today, missing-today
- Mobile-first "My Day" page (big buttons, one-tap marking)
- Attendance History (14-day view with status badges)
- Site Attendance (manager view with project filter, user table, mark dialog)
- Configurable attendance window in Company Settings (start/end time)
- Role-based nav: Admin sees full sidebar, Technician sees My Day/History/Projects
- Dashboard updated with "Today Checked In" stat
- Audit events: attendance_marked, attendance_overridden
- Testing: Backend 96.5% (55/57), Frontend 95%

## Credentials
- Admin: admin@begwork.com / admin123
- Technician: tech1@begwork.com / tech123

## Next Tasks
1. M3 Daily Work Reports (end-of-day report submission tied to attendance)
2. M2 Estimates/BOQ tied to projects
3. M4 HR/Payroll: employee pay types, advances
4. M5 Finance: invoices, payments
5. M9 Overhead cost calculation system

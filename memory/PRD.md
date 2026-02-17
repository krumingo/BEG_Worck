# BEG_Work - Construction Company Management SaaS

## Architecture
- **Backend**: FastAPI + MongoDB (motor async) — server.py ~1200 lines
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn) — 14 pages
- **Auth**: JWT + bcrypt
- **DB Collections**: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases, attendance_entries, work_reports

## Modules Status
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | DONE (Iter 1) |
| M1 | Projects | DONE (Iter 2) |
| M3 | Attendance & Reports | DONE (Iter 3-4) |
| M2 | Estimates / BOQ | Backlog |
| M4 | HR / Payroll | Backlog |
| M5 | Finance | Backlog |
| M6 | AI Invoice Capture | Backlog |
| M7 | Inventory | Backlog |
| M8 | Assets & QR | Backlog |
| M9 | Admin Console / BI | Backlog |

## Implementation Log

### Iteration 1 - M0 Core
- Org/User/FeatureFlag/AuditLog/Subscription + JWT auth + seed admin
- 6 admin screens

### Iteration 2 - M1 Projects
- Project CRUD, team management, phases, role-based permissions

### Iteration 3 - M3 Attendance
- AttendanceEntry with uniqueness, self/manager marking, auto-Late
- My Day, History, Site Attendance pages + configurable window

### Iteration 4 - M3 Daily Work Reports (2026-02-17)
- WorkReport model: Draft→Submitted→Approved/Rejected workflow
- Lines embedded (activity_name + hours + note), total_hours computed
- Uniqueness per (org, date, user, project), requires Present/Late attendance
- Reject→reopen as Draft, Approve finalizes
- 9 API endpoints: draft, edit, submit, approve, reject, my-today, my-range, project-day, get
- Work Report Form (mobile-first): activity lines with hours stepper, save/submit
- Review Reports page (manager): project/date filter, approve/reject actions
- My Day updated with End-of-Day Reports CTA + report status per project
- Attendance History updated with report status badges
- Testing: Backend 91.8% (67/73), Frontend 95%

## Credentials
- Admin: admin@begwork.com / admin123
- Tech1: tech1@begwork.com / tech123
- Tech2: tech2@begwork.com / tech123

## Next Tasks
1. M2 Estimates/BOQ (offers + activities tied to projects)
2. M4 HR/Payroll-lite (pay types, advances, payslips)
3. M5 Finance (invoices issued/received, payments)
4. M9 Overhead cost calculation system
5. Missing report reminders / escalation

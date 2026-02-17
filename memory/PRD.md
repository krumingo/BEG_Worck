# BEG_Work - Construction Company Management SaaS

## Architecture
- **Backend**: FastAPI + MongoDB (motor async) — server.py ~1600 lines
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn) — 16 pages
- **Auth**: JWT + bcrypt
- **DB Collections**: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases, attendance_entries, work_reports, reminder_logs, notifications

## Modules Status
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | DONE (Iter 1) |
| M1 | Projects | DONE (Iter 2) |
| M3 | Attendance & Reports | DONE (Iter 3-4) |
| M9 | Reminders & Alerts | DONE (Iter 5) |
| M2 | Estimates / BOQ | Backlog |
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

### Iteration 5 - M9 Reminders & Alerts (2026-02-17)
**Backend:**
- ReminderLog model: type (MissingAttendance/MissingWorkReport), status (Open/Reminded/Resolved/Excused)
- Notification model: type, title, message, data, is_read
- API endpoints: /reminders/policy, /missing-attendance, /missing-work-reports, /logs, /send, /excuse
- API endpoints: /notifications/my, /notifications/mark-read
- Background scheduler (15-min interval) for automated reminder sending
- Auto-resolve hooks in attendance mark and work report submit endpoints
- MongoDB indexes for reminder_logs and notifications

**Frontend:**
- NotificationBell component in DashboardLayout header with unread badge
- NotificationsPage: list with CTA buttons (Mark Attendance / Fill Report)
- RemindersPage: tabs for Missing Attendance, Missing Reports, Reminder Log
- Dashboard widgets for managers: Missing Attendance, Missing Reports counts
- Navigation: Reminders link in sidebar for Admin/Owner/SiteManager roles

**Testing:** Backend 100% (15/15), Frontend 95%

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
- `/api/dashboard/stats` - dashboard statistics

## Next Tasks (Priority Order)
1. **M2 Estimates/BOQ** - offers + activities tied to projects
2. **M4 HR/Payroll-lite** - pay types, advances, payslips
3. **M5 Finance** - invoices issued/received, payments
4. **M9 Overhead Cost System** - cost tracking and calculation
5. **M6 AI Invoice Capture** - upload, parse, approval queue
6. **M7 Inventory** - items, stock movements, warehouses
7. **M8 Assets & QR** - checkout/checkin, maintenance, warranty

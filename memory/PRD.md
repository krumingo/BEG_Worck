# BEG_Work - Construction Company Management SaaS

## Architecture
- **Backend**: FastAPI + MongoDB (motor async) — server.py ~3600 lines
- **Frontend**: React 19 + Tailwind CSS + Radix UI (shadcn) — 29 pages
- **Auth**: JWT + bcrypt
- **DB Collections**: organizations, users, feature_flags, subscriptions, audit_logs, projects, project_team, project_phases, attendance_entries, work_reports, reminder_logs, notifications, offers, activity_catalog, employee_profiles, advances, payroll_runs, payslips, payroll_payments, financial_accounts, invoices, finance_payments, payment_allocations

## Modules Status
| Code | Name | Status |
|------|------|--------|
| M0 | Core / SaaS | DONE (Iter 1) |
| M1 | Projects | DONE (Iter 2) |
| M3 | Attendance & Reports | DONE (Iter 3-4) |
| M9 | Reminders & Alerts | DONE (Iter 5) |
| M2 | Estimates / BOQ | DONE (Iter 6) |
| M4 | HR / Payroll | DONE (Iter 7) |
| M5 | Finance | DONE (Iter 8) |
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

### Iteration 5 - M9 Reminders & Alerts
- ReminderLog/Notification models, 7 API endpoints, 15-min scheduler
- NotificationBell, NotificationsPage, RemindersPage, Dashboard widgets

### Iteration 6 - M2 Estimates / BOQ
- Offer model with versioning, BOQ lines with material+labor costing
- ActivityCatalogItem per project for reusable activities
- Workflow: Draft→Sent→Accepted/Rejected, New Version creates clone

### Iteration 7 - M4 HR / Payroll-lite (2026-02-17)
**Data Models:**
- EmployeeProfile: userId, payType (Hourly|Daily|Monthly), hourlyRate, dailyRate, monthlySalary, standardHoursPerDay, paySchedule, active, startDate
- AdvanceLoan: userId, type (Advance|Loan), amount, remainingAmount, status (Open|Closed), issuedDate, note
- PayrollRun: periodType, periodStart, periodEnd, status (Draft|Finalized|Paid)
- Payslip: payrollRunId, userId, baseAmount, deductionsAmount, advancesDeductedAmount, netPay, detailsJson, status
- PayrollPayment: payslipId, amount, method (Cash|BankTransfer), reference, paidAt

**Pay Calculation Logic:**
- Hourly: sum(hours from WorkReports in period) × hourlyRate
- Daily: count(Present/Late attendance in period) × dailyRate
- Monthly: fixed monthlySalary

**Payroll Workflow:**
1. Create payroll run (Draft)
2. Generate payslips (creates for all active employee profiles)
3. Set deductions per payslip (manual + advance selections)
4. Finalize (locks payroll, payslips → Finalized)
5. Mark individual payslips as paid (creates PayrollPayment, deducts from advances)

**API Endpoints:**
- CRUD /api/employees - employee profile management
- CRUD /api/advances - advances/loans with deduction tracking
- /api/payroll-runs - create, generate, finalize, delete
- /api/payslips - list, get, set-deductions, mark-paid
- /api/payroll-enums - enums for UI

**Frontend:**
- EmployeesPage: configure pay types and rates
- AdvancesPage: create advances/loans, track remaining balances
- PayrollRunsPage: create payroll runs, view status
- PayrollDetailPage: generate payslips, set deductions, finalize, mark paid
- MyPayslipsPage: technician view of own payslips

**Testing:** Backend 100% (20/20), Frontend 100%

### Iteration 8 - M5 Finance (2026-02-17)
**Data Models:**
- FinancialAccount: name, type (Cash|Bank), currency, openingBalance, active
- Invoice: direction (Issued|Received), invoiceNo, status (Draft|Sent|PartiallyPaid|Paid|Overdue|Cancelled), projectId, counterpartyName, issueDate, dueDate, currency, vatPercent, lines[], subtotal, vatAmount, total, paidAmount, remainingAmount
- InvoiceLine: description, unit, qty, unitPrice, lineTotal, costCategory, projectId
- FinancePayment: direction (Inflow|Outflow), amount, currency, date, method, accountId, counterpartyName, reference, note
- PaymentAllocation: paymentId, invoiceId, amountAllocated, allocatedAt

**Business Rules:**
- Default currency: EUR, default VAT: 20%
- Currency and VAT snapshotted per document (historic totals don't change)
- Invoice workflow: Draft → Send → PartiallyPaid/Paid or Overdue → Cancel
- Payment allocations: Inflow → Issued invoices, Outflow → Received bills
- Validation: allocation ≤ payment available, allocation ≤ invoice remaining
- Account balance = opening_balance + sum(inflows) - sum(outflows)

**API Endpoints:**
- GET/POST /api/finance/accounts - CRUD financial accounts
- PUT/DELETE /api/finance/accounts/{id} - update/delete account
- GET/POST /api/finance/invoices - list/create invoices with filters
- GET/PUT/DELETE /api/finance/invoices/{id} - invoice details/update/delete
- PUT /api/finance/invoices/{id}/lines - update invoice lines
- POST /api/finance/invoices/{id}/send - mark invoice as sent
- POST /api/finance/invoices/{id}/cancel - cancel invoice
- GET/POST /api/finance/payments - list/create payments
- GET/DELETE /api/finance/payments/{id} - payment details/delete
- POST /api/finance/payments/{id}/allocate - allocate payment to invoices
- GET /api/finance/stats - receivables, payables, cash/bank balances
- GET /api/finance/enums - finance-related enum values

**Frontend:**
- FinanceOverviewPage: stats cards (receivables, payables, cash, bank), quick links
- FinancialAccountsPage: account list with CRUD dialog
- InvoicesPage: invoice list with filters (direction/status/project/date), search
- InvoiceEditorPage: create/edit invoice, line items, totals, send/cancel actions
- PaymentsPage: payment list with filters, create dialog, allocate dialog

**Role Access:**
- Admin/Owner/Accountant: full finance access
- SiteManager: read-only for project-linked invoices
- Technician: blocked from all finance endpoints

**Testing:** Backend 100% (31/31 tests), Frontend 100%

## Credentials
- Admin: admin@begwork.com / admin123
- Tech1: tech1@begwork.com / tech123 (Daily @€120/day)
- Tech2: tech2@begwork.com / tech123 (Hourly @€18.5/hr)

## API Endpoints Summary
- `/api/auth/` - login, me
- `/api/organization` - org settings
- `/api/users` - CRUD
- `/api/feature-flags` - module toggles
- `/api/audit-logs` - activity logs
- `/api/projects` - CRUD with team/phases
- `/api/attendance` - mark, my-today, my-range, site-today
- `/api/work-reports` - draft, edit, submit, approve, reject
- `/api/reminders` - policy, missing-attendance, missing-work-reports
- `/api/notifications` - my, mark-read
- `/api/offers` - CRUD, send, accept, reject, new-version
- `/api/activity-catalog` - CRUD
- `/api/employees` - employee profiles
- `/api/advances` - advances/loans
- `/api/payroll-runs` - create, generate, finalize
- `/api/payslips` - list, set-deductions, mark-paid
- `/api/dashboard/stats` - statistics
- `/api/finance/accounts` - financial accounts CRUD
- `/api/finance/invoices` - invoices CRUD, send, cancel
- `/api/finance/payments` - payments CRUD, allocate
- `/api/finance/stats` - finance overview stats

## Next Tasks (Priority Order)
1. **i18n Hardening** - full translation pass for all UI strings
2. **M9 Overhead Cost System** - cost tracking, allocation, reporting
3. **M6 AI Invoice Capture** - upload, OCR/AI parsing, approval queue
4. **M7 Inventory** - items, stock movements, warehouses
5. **M8 Assets & QR** - checkout/checkin, maintenance, warranty

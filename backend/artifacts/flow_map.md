# BEG_Work Flow Map

## Authentication & Authorization
```
Login Flow:
  POST /api/auth/login → verify credentials → return JWT token
  GET /api/auth/me → validate token → return user profile (incl. is_platform_admin)

Platform Admin Flow:
  POST /api/platform/bootstrap-create-platform-admin → create first admin (token protected)
  /platform/login → check is_platform_admin → /platform dashboard
```

## Organization & User Management
```
Signup Flow:
  POST /api/billing/signup → create org + owner user → return token
  
User CRUD:
  GET /api/users → list org users
  POST /api/users → create user (Admin only)
  PUT /api/users/{id} → update user
  DELETE /api/users/{id} → delete user
  POST /api/admin/set-password/{id} → admin reset password
```

## Projects Lifecycle
```
Create → Assign → Track → Complete:
  POST /api/projects → create project
  PUT /api/projects/{id} → update project
  POST /api/projects/{id}/team → add team members
  GET /api/projects/{id}/attendance → view attendance
  PUT /api/projects/{id}/status → update status (draft→active→completed)
```

## Attendance & Work Reports
```
Daily Attendance:
  POST /api/attendance/check-in → worker check-in (GPS, photo)
  POST /api/attendance/check-out → worker check-out
  GET /api/attendance/today → current day attendance
  GET /api/attendance/site/{project_id} → site manager view

Work Reports:
  POST /api/work-reports → submit daily report
  PUT /api/work-reports/{id}/submit → submit for review
  PUT /api/work-reports/{id}/approve → manager approval
  GET /api/work-reports/pending → pending reports list
```

## Offers & BOQ (Bill of Quantities)
```
Offer Lifecycle:
  POST /api/offers → create offer (draft)
  PUT /api/offers/{id} → edit offer items
  POST /api/offers/{id}/versions → create version
  PUT /api/offers/{id}/status → send/accept/reject
  GET /api/offers/{id}/export → export to PDF
```

## HR & Payroll
```
Employee Management:
  GET /api/employees → list employees
  POST /api/employees → create employee profile
  PUT /api/employees/{id} → update profile

Payroll Processing:
  POST /api/payroll/runs → create payroll run
  GET /api/payroll/runs/{id} → get run details
  POST /api/payroll/runs/{id}/calculate → calculate salaries
  POST /api/payroll/runs/{id}/finalize → finalize run
  GET /api/payroll/payslips → employee payslips
```

## Finance
```
Accounts & Transactions:
  GET /api/financial-accounts → list accounts
  POST /api/financial-accounts → create account
  GET /api/invoices → list invoices
  POST /api/invoices → create invoice
  POST /api/payments → record payment
```

## Overhead Cost Allocation
```
Cost Distribution:
  GET /api/overhead/categories → cost categories
  POST /api/overhead/snapshots → create snapshot
  GET /api/overhead/snapshots/{id} → snapshot details
  POST /api/overhead/snapshots/{id}/allocate → allocate to projects
```

## Media Management
```
Upload & Access:
  POST /api/media/upload → upload file (chunked supported)
  POST /api/media/link → link to entity
  GET /api/media/{id} → get metadata
  GET /api/media/file/{filename} → download file
  DELETE /api/media/{id} → delete (ACL checked)
```

## Mobile App Configuration
```
Settings:
  GET /api/mobile/settings → get mobile config (platform admin)
  PUT /api/mobile/settings → update config
  GET /api/mobile/view-configs → role-based view configs
```

## Billing & Subscriptions
```
Subscription Flow:
  GET /api/billing/config → Stripe config status
  POST /api/billing/create-checkout-session → start checkout
  POST /api/billing/create-portal-session → customer portal
  POST /api/billing/webhook → Stripe webhook handler
  GET /api/usage → current usage vs limits
```

## Platform Administration (SuperAdmin Only)
```
System Management:
  GET /api/audit-logs → view audit trail
  PUT /api/feature-flags → toggle modules
  GET /api/billing/config → Stripe status
  GET /api/mobile/settings → mobile config
```

---

## Key Endpoints by Domain

| Domain | Create | Read | Update | Delete |
|--------|--------|------|--------|--------|
| Users | POST /users | GET /users | PUT /users/{id} | DELETE /users/{id} |
| Projects | POST /projects | GET /projects | PUT /projects/{id} | DELETE /projects/{id} |
| Offers | POST /offers | GET /offers | PUT /offers/{id} | DELETE /offers/{id} |
| Attendance | POST /attendance/check-in | GET /attendance | PUT /attendance/{id} | - |
| Work Reports | POST /work-reports | GET /work-reports | PUT /work-reports/{id} | DELETE /work-reports/{id} |
| Employees | POST /employees | GET /employees | PUT /employees/{id} | DELETE /employees/{id} |
| Invoices | POST /invoices | GET /invoices | PUT /invoices/{id} | DELETE /invoices/{id} |
| Media | POST /media/upload | GET /media | - | DELETE /media/{id} |

---

## Auth Dependencies Summary

| Dependency | Description | Used By |
|------------|-------------|---------|
| `get_current_user` | Any authenticated user | Most endpoints |
| `require_admin` | Admin/Owner role required | User management, settings |
| `require_platform_admin` | Platform admin flag required | Billing, modules, audit logs |

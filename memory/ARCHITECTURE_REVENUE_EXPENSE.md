# BEG_Work — Revenue & Expense Master Architecture
# Version: 1.0 | Date: 2026-03-11

---

## 1. COLLECTIONS / MODELS BY MODULE

### A. REVENUE SIDE

```
offers                     ← EXISTS (64 records)
  id, org_id, project_id, offer_no, title
  offer_type: "main" | "extra"
  status: Draft → Sent → Accepted → Rejected → NeedsRevision
  lines[]: { activity_name, unit, qty, material_unit_cost, labor_unit_cost, line_total }
  subtotal, vat_amount, total, currency: "EUR"
  review_token, sent_at, accepted_at

offer_versions             ← EXISTS (17 records)
  offer_id, version_number, snapshot_json, created_at

NEW: client_acts           ← TO BUILD
  id, org_id, project_id
  act_number, act_date, period_from, period_to
  source_offer_id
  lines[]: { offer_line_id, activity_name, unit, contracted_qty, executed_qty, executed_percent, unit_price, line_total }
  subtotal, vat_amount, total, currency
  status: Draft → Submitted → Accepted → Disputed → Paid
  accepted_at, accepted_by

invoices                   ← EXISTS (412 records) — client-side (Issued)
  id, org_id, project_id, direction: "Issued"
  invoice_no, counterparty_name, issue_date, due_date
  lines[], subtotal, vat_amount, total
  status: Draft → Sent → PartiallyPaid → Paid → Overdue → Cancelled
  paid_amount, remaining_amount

finance_payments           ← EXISTS (121 records)
  id, org_id, direction: "Inflow"
  amount, date, method, account_id

payment_allocations        ← EXISTS (121 records)
  payment_id → invoice_id, amount_allocated
```

### B. EXPENSE SIDE

```
material_requests          ← EXISTS (3 records)
  id, org_id, project_id, source_offer_id
  request_number, status: draft → submitted → fulfilled
  lines[]: { material_name, qty_requested, qty_fulfilled, unit }

supplier_invoices          ← EXISTS (3 records)
  id, org_id, supplier_id, project_id, linked_request_id
  invoice_number, invoice_date, purchased_by
  lines[]: { material_name, qty, unit, unit_price, discount_percent, final_unit_price, total_price }
  subtotal, vat_amount, total
  status: uploaded → reviewed → posted_to_warehouse
  posted_to_warehouse, warehouse_transaction_id

warehouse_transactions     ← EXISTS (7 records)
  id, org_id, warehouse_id, project_id
  type: "intake" | "issue" | "return"
  source_invoice_id, supplier_name, invoice_number
  lines[]: { material_name, qty_received/qty_issued/qty_returned, unit, unit_price, total_price }

project_material_ops       ← EXISTS (2 records)
  id, org_id, project_id, type: "consumption"
  lines[]: { material_name, qty_consumed, unit }

employee_profiles          ← EXISTS (16 records)
  user_id, pay_type: "Monthly" | "Akord"
  monthly_salary, daily_rate, hourly_rate
  working_days_per_month, standard_hours_per_day

payslips                   ← EXISTS (160 records)
  user_id, period_start, period_end
  gross_pay, net_pay, status

NEW: subcontractor_packages ← TO BUILD
  id, org_id, project_id
  subcontractor_id (→ counterparties)
  package_name, contract_number
  lines[]: { activity_name, unit, qty, unit_price, line_total }
  subtotal, vat_amount, total, currency
  status: Draft → Agreed → InProgress → Completed → Disputed

NEW: subcontractor_acts    ← TO BUILD
  id, org_id, project_id, package_id
  act_number, act_date, period_from, period_to
  lines[]: { package_line_id, activity_name, executed_qty, unit_price, line_total }
  subtotal, vat_amount, total
  status: Draft → Submitted → Accepted → Paid

overhead_transactions      ← EXISTS (82 records)
  id, org_id, category, amount, date

NEW: project_overhead_alloc ← TO BUILD
  id, org_id, project_id, period
  method: "revenue_share" | "direct" | "manual"
  allocated_amount, source_overhead_ids[]
```

### C. EXECUTION LAYER

```
NEW: execution_packages    ← TO BUILD
  id, org_id, project_id, source_offer_id
  package_name
  lines[]: {
    activity_name, unit, qty_planned,
    budget_material, budget_labor, budget_subcontract, budget_overhead, budget_total,
    actual_material, actual_labor, actual_subcontract, actual_overhead, actual_total,
    qty_executed, percent_complete
  }
  status: Planning → InProgress → Completed

work_reports               ← EXISTS (5 records)
  user_id, project_id, date
  lines[]: { activity_name, hours, note }
  → feeds actual_labor computation
```

---

## 2. MAIN RELATIONS

```
PROJECT
  ├── offers[] (main + extra)
  │     ├── offer_versions[]
  │     └── → client_acts[] (executed work certified)
  │           └── → invoices[] (Issued, billed to client)
  │                 └── → payment_allocations[] → finance_payments[]
  │
  ├── execution_packages[]
  │     ├── ← offers (planned budget source)
  │     ├── ← work_reports (actual labor hours)
  │     ├── ← warehouse_transactions.issue (actual materials)
  │     └── ← subcontractor_acts (actual subcontract)
  │
  ├── material_requests[]
  │     └── → supplier_invoices[]
  │           └── → warehouse_transactions.intake
  │                 └── → warehouse_transactions.issue → project
  │                       └── → project_material_ops.consumption
  │                             └── → warehouse_transactions.return
  │
  ├── subcontractor_packages[]
  │     └── → subcontractor_acts[]
  │           └── → invoices[] (Received, from subcontractor)
  │                 └── → payment_allocations[] (outgoing)
  │
  ├── employee labor
  │     ├── work_reports[] (hours per activity)
  │     ├── attendance_entries[] (presence)
  │     └── payslips[] (cost)
  │
  └── overhead_alloc[]
        └── ← overhead_transactions (company-wide)
```

---

## 3. STATUS FLOWS

### Revenue Flow:
```
Offer: Draft → Sent → Accepted
  ↓
Client Act: Draft → Submitted → Accepted
  ↓
Invoice (Issued): Draft → Sent → PartiallyPaid → Paid
  ↓
Payment: Allocated → Collected
```

### Expense Flow — Materials:
```
Material Request: draft → submitted → fulfilled
  ↓
Supplier Invoice: uploaded → reviewed → posted_to_warehouse
  ↓
Warehouse: intake → issue (to project) → consumption → return (if unused)
```

### Expense Flow — Subcontract:
```
Package: Draft → Agreed → InProgress → Completed
  ↓
Subcontractor Act: Draft → Submitted → Accepted → Paid
  ↓
Invoice (Received): Draft → Sent → Paid
```

### Expense Flow — Labor:
```
Attendance: marked daily
Work Report: submitted → approved
  → hours × hourly_rate = labor cost per activity
Payslip: generated → finalized → paid
```

---

## 4. FINANCIAL RECOGNITION RULES

### REVENUE RECOGNITION (5 stages):

| Stage | Event | Collection | Field | Revenue Status |
|-------|-------|-----------|-------|---------------|
| R1 | Offer accepted | offers | accepted_at | **Contracted** |
| R2 | Work certified | client_acts | status=Accepted | **Earned** |
| R3 | Invoice issued | invoices (Issued) | status=Sent | **Billed** |
| R4 | Partial payment | payment_allocations | amount | **Partially Collected** |
| R5 | Full payment | invoices | status=Paid | **Collected** |

**Primary revenue = R2 (Earned)** — recognized when client_act is Accepted.
**Cash revenue = R5 (Collected)** — actual money received.

### EXPENSE RECOGNITION (5 stages):

| Stage | Event | Collection | Field | Expense Status |
|-------|-------|-----------|-------|---------------|
| E1 | Material purchased | supplier_invoices | status=reviewed | **Committed** |
| E2 | Material issued to project | warehouse_transactions.issue | qty_issued | **Allocated** |
| E3 | Material consumed | project_material_ops | qty_consumed | **Consumed** |
| E4 | Labor performed | work_reports | hours × rate | **Incurred** |
| E5 | Subcontract certified | subcontractor_acts | status=Accepted | **Certified** |
| E6 | Payment made | finance_payments (Outflow) | amount | **Paid** |

**Primary expense = E3 (Consumed) + E4 (Incurred) + E5 (Certified)**
**Cash expense = E6 (Paid)**

---

## 5. PROFIT DASHBOARD NUMBERS

### Per SMR (Activity Line):
```
revenue_contracted  = SUM(accepted_offer_line.line_total)
revenue_earned      = SUM(client_act_line.line_total WHERE act.status=Accepted)
cost_material       = SUM(warehouse_issue_line.total_price WHERE project match)
cost_labor          = SUM(work_report_line.hours × employee.hourly_rate)
cost_subcontract    = SUM(subcontractor_act_line.line_total WHERE act.status=Accepted)
cost_overhead       = project_overhead_alloc.allocated_amount / num_activities (or proportional)

profit_planned      = revenue_contracted - budget_total
profit_actual       = revenue_earned - (cost_material + cost_labor + cost_subcontract + cost_overhead)
margin_percent      = profit_actual / revenue_earned × 100
```

### Per Project:
```
total_contracted    = SUM(accepted_offers.total)
total_earned        = SUM(accepted_client_acts.total)
total_billed        = SUM(issued_invoices.total)
total_collected     = SUM(invoice.paid_amount)

total_material_cost = SUM(warehouse_issues.total WHERE project)
total_labor_cost    = SUM(work_report_hours × rates) OR SUM(payslip.gross_pay prorated)
total_subcontract   = SUM(accepted_sub_acts.total)
total_overhead      = SUM(project_overhead_alloc.allocated_amount)
total_cost          = material + labor + subcontract + overhead

gross_profit        = total_earned - total_cost
gross_margin        = gross_profit / total_earned × 100

receivables         = total_billed - total_collected
payables            = total_committed_expenses - total_paid_expenses
cash_position       = total_collected - total_paid_expenses
```

---

## 6. PHASED IMPLEMENTATION ORDER

### Phase 1: Client Acts + Execution Tracking (P0)
- `client_acts` collection + CRUD + status flow
- Link: accepted_offer → client_act lines (qty executed)
- Revenue recognition: R1 (Contracted) + R2 (Earned)
- Basic project profit: earned vs actual costs (from existing data)
- **Depends on**: offers (EXISTS), invoices (EXISTS)
- **Estimated**: 1-2 sessions

### Phase 2: Labor Cost Aggregation (P0)
- Aggregate work_report hours × employee hourly_rate per project/activity
- Labor cost per project dashboard
- **Depends on**: work_reports (EXISTS), employee_profiles (EXISTS)
- **Estimated**: 1 session

### Phase 3: Subcontractor Module (P1)
- `subcontractor_packages` + `subcontractor_acts` collections
- Link to counterparties as subcontractors
- Subcontract cost per project
- **Estimated**: 1-2 sessions

### Phase 4: Overhead Allocation (P1)
- `project_overhead_alloc` with method selection
- Proportional or direct allocation
- **Depends on**: overhead_transactions (EXISTS)
- **Estimated**: 1 session

### Phase 5: Project Profit Dashboard (P0)
- Aggregation endpoints for all cost/revenue layers
- Per-project P&L summary
- Per-SMR margin analysis
- Receivables / payables
- **Depends on**: Phases 1-4
- **Estimated**: 1-2 sessions

### Phase 6: Cash Flow (P2)
- Cash collected vs cash paid timeline
- Forecast based on invoice due dates
- **Estimated**: 1 session

---

## EXISTING vs NEW SUMMARY

| Collection | Status | Records |
|-----------|--------|---------|
| offers | EXISTS | 64 |
| offer_versions | EXISTS | 17 |
| invoices | EXISTS | 412 |
| finance_payments | EXISTS | 121 |
| payment_allocations | EXISTS | 121 |
| material_requests | EXISTS | 3 |
| supplier_invoices | EXISTS | 3 |
| warehouse_transactions | EXISTS | 7 |
| project_material_ops | EXISTS | 2 |
| employee_profiles | EXISTS | 16 |
| payslips | EXISTS | 160 |
| work_reports | EXISTS | 5 |
| overhead_transactions | EXISTS | 82 |
| **client_acts** | **NEW** | — |
| **subcontractor_packages** | **NEW** | — |
| **subcontractor_acts** | **NEW** | — |
| **project_overhead_alloc** | **NEW** | — |
| **execution_packages** | **NEW** | — |

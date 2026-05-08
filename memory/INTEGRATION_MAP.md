# BEG_Work — Integration Smoke Map
# Generated: 2026-04-09
# Purpose: Dependency map between modules, source-of-truth matrix, risk hotspots

---

## Chain 1 — Field Report → Money

```
Technician (mobile)
  │  POST /technician/daily-report
  │  Inputs: project_id, entries[{worker_name, smr_type, hours}]
  ▼
work_sessions (collection)
  │  Creates: WorkSession per entry (duration_hours, hourly_rate_at_date, labor_cost)
  │  Side-effect: if smr_type unknown → creates MissingSMR (source="mobile")
  │  SoT: YES — canonical record of who worked where and how long
  ▼
worker_calendar (collection)                    activity_budgets burn
  │  sync-from-sessions fills                    │  GET /activity-budgets/{id}/burn
  │  status="working" per date                   │  Reads: work_sessions WHERE site_id
  │  SoT for attendance: YES                     │  Derived: actual_cost, burn_pct
  ▼                                              ▼
overhead_realtime                              budget_progress warnings
  │  Reads: worker_calendar + fixed_expenses     │  Reads: burn_pct + progress_pct
  │  Formula: fixed / days / avg_working         │  Generates: warnings[]
  │  Derived: overhead_per_person_day            ▼
  ▼                                            project_pnl
payroll                                          │  GET /projects/{id}/pnl
  │  POST /payroll/weekly-run                    │  Aggregates: work_sessions (labor)
  │  POST /payroll/{id}/generate-weekly          │              warehouse (materials)
  │  Reads: work_sessions for period             │              subcontractor_payments
  │  Reads: advances for deduction               │              contract_payments
  │  Creates: payslips with breakdown            │              overhead_allocations
  │  SoT for pay: YES                            │  Derived: gross_profit, margin_pct
  ▼                                              ▼
pending_expenses                               pulse_generator
  │  POST /technician/photo-invoice              │  Reads: work_sessions, worker_calendar,
  │  Creates: pending_expense                    │          activity_budgets, missing_smr,
  │  Needs: admin approve → expense              │          work_reports, warehouse_txns
  │  SoT for field expenses: YES                 │  Creates: site_pulses snapshot
  ▼                                              ▼
                                               alarm_engine
                                                 │  Evaluates: alarm_rules vs live data
                                                 │  Creates: alarm_events
                                                 │  Types: budget, overtime, attendance
```

**Key SoT in this chain:** work_sessions is the atomic unit. Everything else derives from it.

---

## Chain 2 — Additional SMR → Commercial Flow

```
MissingSMR creation
  │  Sources: web (MissingSMRPage), mobile (TechnicianDashboard), daily_report (auto)
  │  POST /missing-smr  OR  POST /technician/quick-smr
  │  Fields: project_id, smr_type, qty, urgency_type (emergency|planned)
  │  SoT: YES — canonical record of discovered work
  ▼
Status workflow (urgency-dependent)
  │  EMERGENCY: draft → reported → executed → analyzed → offered → closed
  │  PLANNED:   draft → reported → reviewed → approved_by_client → analyzed → offered → closed
  │  PLANNED:   draft → reported → reviewed → rejected_by_client → closed
  │  SoT for status: the record itself
  ▼
AI Estimate (optional)
  │  POST /missing-smr/{id}/ai-estimate
  │  Calls: ai_proposal.py (rule-based + LLM)
  │  Calls: pricing_engine.py (3 agents → median price)
  │  Writes: ai_estimated_price, ai_price_breakdown on the MissingSMR record
  │  Derived: price estimate, not binding
  ▼
Bridge to Analysis
  │  POST /missing-smr/{id}/to-analysis
  │  Creates: extra_work_draft in extra_work_drafts collection
  │  Sets: missing_smr.linked_extra_work_id
  │  Status: missing_smr → "analyzed"
  ▼
SMR Analysis (optional deeper analysis)
  │  POST /smr-analyses  (can create from missing_smr)
  │  Full cost breakdown: materials[], labor, logistics, markup, risk
  │  Versioned: snapshot/compare
  │  SoT for cost analysis: YES
  ▼
Bridge to Offer
  │  POST /missing-smr/{id}/to-offer  OR  POST /smr-analyses/{id}/to-offer
  │  OR  POST /missing-smr/batch-to-offer (multiple → one offer)
  │  Creates: offer in offers collection
  │  Sets: missing_smr.linked_offer_id
  │  Status: missing_smr → "offered"
  ▼
Offer → Invoice → Payment
  │  offer → send → client review → accept
  │  invoice from offer → payment tracking
  │  Feeds into: project_pnl revenue side
```

**Overlap risk:** MissingSMR can go to-analysis OR to-offer directly. Both paths create different records. The linked_*_id fields track provenance.

---

## Chain 3 — Project / Client / Finance

```
Client (SSOT for identity)
  │  Collection: clients
  │  Fields: type, companyName/fullName, eik, phone, email, address
  │  SoT: YES — single source for client identity and invoice data
  ▼
Project (links to client via owner_id)
  │  Collection: projects
  │  Fields: owner_id → client, invoice_details (SNAPSHOT copy from client)
  │  invoice_details is populated via POST /projects/{id}/import-client-invoice
  │  ⚠️ SNAPSHOT: may drift from client master if client data updated later
  ▼
Invoices
  │  Collection: invoices
  │  Links: project_id, counterparty fields (denormalized from client at creation time)
  │  SoT for billing: YES
  │  Has: total, paid_amount, status
  ▼
Client Summary (derived, read-only)
  │  GET /clients/{id}/summary
  │  Aggregates: all projects for client → all invoices → totals
  │  Derived: total_revenue, total_paid, total_outstanding
  ▼
Project P&L (derived)
  │  GET /projects/{id}/pnl
  │  Revenue side: reads invoices for project
  │  ⚠️ Does NOT read client summary — reads invoices directly
```

**Duplication risk:** project.invoice_details vs client record. Mitigation: "Import from client" button, display "Data from client: X" banner.

---

## Chain 4 — Materials / Warehouse / Cost

```
Material Request (from technician or procurement)
  │  POST /technician/material-request  OR  procurement UI
  │  Creates: material_request with lines
  │  Status: draft → submitted → approved → fulfilled
  ▼
Supplier Invoice / Delivery
  │  Procurement module: supplier_invoices, warehouse_transactions
  │  Type: "receipt" (into warehouse) or "issue" (to project)
  ▼
Warehouse Transactions
  │  Collection: warehouse_transactions
  │  Type: receipt | issue | return
  │  For issue: project_id links to project
  │  SoT for material movement: YES
  ▼
Project Material Ledger
  │  compute_project_ledger() in procurement.py
  │  Aggregates: warehouse_transactions WHERE project_id
  │  Derived: total material cost per project
  ▼
Project P&L (material_cost)
  │  Reads: warehouse_transactions OR invoice_lines allocated to project
  │  Takes MAX of two sources (invoice allocation vs warehouse issues)
  ▼
Pulse (materials_used)
  │  Reads: warehouse_transactions for the day
  │  Derived: daily material snapshot
```

**Safe extension:** Waste tracking can be added as a new field on warehouse_transactions (waste_qty, waste_reason) without touching existing flow.

---

## Chain 5 — Location / Group / SMR

```
Location Tree (structural hierarchy)
  │  Collection: location_nodes
  │  Hierarchy: building → floor → room → zone → element
  │  SoT for physical structure: YES
  ▼
SMR Groups (visual grouping)
  │  Collection: smr_groups
  │  Links: location_id (optional)
  │  Groups SMR lines from multiple sources
  │  SoT for grouping: YES (but lines exist independently)
  ▼
SMR Lines (from multiple sources)
  │  Sources: smr_analyses.lines[], missing_smr, extra_work_drafts
  │  Each may have: location_id (structured) OR floor/room/zone (text fallback)
  │  Each may have: group_id (if assigned to a group)
  │  ⚠️ DUAL KEY: location_id vs text fields
  ▼
Work Reporting
  │  work_sessions.smr_type_id — references activity type, NOT location
  │  worker_calendar.site_id — references project, NOT specific location
  │  ⚠️ Gap: work tracking is per-project, not per-location
  ▼
Budget Tracking
  │  activity_budgets — per activity type per project
  │  burn tracking reads work_sessions by project (not by location)
```

**Text vs ID risk:** Old records use floor/room/zone text. New records use location_id. The SMR-at-location endpoint handles both (queries by location_id AND falls back to text matching).

---

## Source of Truth Matrix

| Domain | Source of Truth | Derived Data | Consumers | Risk |
|--------|----------------|--------------|-----------|------|
| Clients | `clients` collection | client summary, project.invoice_details (copy) | projects, invoices, ClientDetailPage | LOW — clear SSOT |
| Projects | `projects` collection | dashboard stats, P&L | everywhere | LOW |
| Work Sessions | `work_sessions` collection | payroll, P&L labor, pulse, budget burn, overhead | 8+ modules | **HIGH** — central node |
| Worker Calendar | `worker_calendar` collection | overhead_realtime, pulse.calendar_summary | overhead, pulse | MED — can drift from sessions |
| Payroll | `payroll_runs` + `payslips` | none (final output) | MyPayslipsPage | LOW |
| Missing SMR | `missing_smr` collection | offers (via bridge), extra_work_drafts | MissingSMRPage, pulse, technician | MED — multiple status paths |
| SMR Analysis | `smr_analyses` collection | offers (via to-offer), KSS exports | SMRAnalysisPage | LOW |
| Offers | `offers` collection | P&L budget side, KSS (via from-offer) | OfferEditor, finance | LOW |
| Invoices | `invoices` collection | P&L revenue, client summary | finance, project detail | LOW |
| Warehouse Txns | `warehouse_transactions` | P&L material cost, pulse, project ledger | procurement, P&L, pulse | LOW |
| Alarms | `alarm_events` + `alarm_rules` | dashboard badge count | AlarmsDashboard, NotificationBell | LOW — isolated |
| Pulse | `site_pulses` | dashboard cards | DashboardPage, ProjectDetailPage | LOW — regenerated on demand |
| Price Modifiers | `price_modifiers_config` | effective modifiers (merged cascade) | smr_analysis recalculate | MED — cascade complexity |
| Location Nodes | `location_nodes` | tree structure, SMR linkage | LocationTreePanel, LocationPicker | LOW |

---

## Integration Risk Hotspots

### 1. client / owner / persons / companies overlap
- `clients` is unified. `persons` and `companies` are legacy.
- `projects.owner_id` can point to `clients` OR old `persons`/`companies`.
- import-client-invoice tries both collections.
- **Mitigation:** New data goes to `clients`. Old data works via fallback.

### 2. work_sessions / worker_calendar / daily_report overlap
- `work_sessions` = atomic time intervals (SoT for hours/cost).
- `worker_calendar` = daily status summary (SoT for attendance type).
- `employee_daily_reports` = structured daily log (SoT for SMR detail).
- `work_reports` = simplified report from technician.
- **Risk:** 4 overlapping data sources for "what happened today."
- **Mitigation:** work_sessions is SoT for cost. Calendar syncs from sessions. Reports are supplementary.

### 3. location_id vs floor/room/zone text fields
- Old MissingSMR records have text fields only.
- New records may have location_id.
- SMR-at-location endpoint handles both.
- **Risk:** Queries that only check location_id will miss old records.
- **Mitigation:** Always query both. Never drop text fields.

### 4. pulse alerts vs alarm events
- Pulse generates `alerts[]` per site per day (ephemeral, regenerated).
- Alarms are persistent events with ack/resolve workflow.
- **Risk:** Same condition (e.g., "no workers") appears in both.
- **Mitigation:** They serve different purposes. Pulse = snapshot. Alarms = actionable.

### 5. project.invoice_details vs client record
- Project copies client data at a point in time.
- Client may be updated later → project copy drifts.
- **Mitigation:** "Import from client" button. Banner showing source.

### 6. old markup_pct/risk_pct vs new price_modifiers
- SMR Analysis lines have `markup_pct` and `risk_pct` (simple).
- Price modifiers have 7-step chain (waste→floor→center→inhabited→overhead→risk→profit).
- `recalculate` uses old simple formula. `recalculate-with-modifiers` uses full chain.
- **Risk:** Both paths coexist. Results differ.
- **Mitigation:** Clear separation. "Recalculate" = simple. "Recalculate with modifiers" = full. UI shows which was used.

---

## Safe Extension Points by Domain

| Domain | Add Service | Add Summary Endpoint | Add UI Panel | Notes |
|--------|------------|---------------------|-------------|-------|
| Work Sessions | new analyzer | GET /work-sessions/analytics | tab in EmployeeDetail | don't touch start/end logic |
| Missing SMR | new bridge | GET /missing-smr/stats | widget in Dashboard | don't change status values |
| SMR Analysis | new calculator | GET /smr-analyses/{id}/what-if | panel in SMRAnalysisPage | don't change calc_line |
| P&L | new breakdown | GET /projects/{id}/pnl/monthly | chart component | read-only aggregation |
| Overhead | new forecaster | GET /overhead/forecast | card in Dashboard | don't change formula |
| Pulse | new enricher | GET /pulse/weekly | weekly pulse card | upsert pattern safe |
| Alarms | new rule type | extend evaluate_rule | rule config UI | add case to switch |
| Pricing | new agent | add to agents list | breakdown tooltip | extend, don't replace |
| Payroll | new report | GET /payroll/summary | payroll analytics tab | don't touch generate |
| KSS | new import format | POST /smr-analyses/import-csv | import wizard | follow same pattern |

---

## Recommended Order for Next Additive Improvements

### Tier 1 — Low risk, high value:
1. **Morning Briefing** — new service that aggregates pulse + alarms + calendar into email/notification. Read-only. No schema changes.
2. **Cash Flow Forecast** — new endpoint `GET /projects/{id}/cashflow` that projects future payments from invoices + payroll. Pure computation.
3. **Expected vs Actual** — new panel comparing activity_budgets planned vs work_sessions actual. Read-only aggregation.

### Tier 2 — Medium risk, high value:
4. **Waste Tracking** — add `waste_qty` field to warehouse_transactions. New UI in procurement. Feeds into P&L as separate line.
5. **Smart Excel v2** — preview endpoint already designed. Add column mapping UI + multi-sheet selector.
6. **LocationPicker Integration** — wire existing component into MissingSMR/NovoSMR create forms. Additive only.

### Tier 3 — Higher risk, requires care:
7. **Subcontractor Performance** — new collection `subcontractor_ratings`. Links to existing subcontractor_payments. New UI page.
8. **OCR Invoice Capture** — new service for image → text. Creates pending_expense. Isolated from existing flow.
9. **Stage 6 Execution Budget Tabs** — modifies OfferEditorPage (1300 lines). Needs careful approach.

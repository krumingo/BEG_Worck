# BEG_Work — Wave 2.1: FLOW-027 Schedule / Dependency / Readiness Foundation

> Status: DRAFT IMPLEMENTATION CONTRACT  
> Date: 2026-09-12  
> Tracking: Issue #10  
> Deploy: NO  
> Runtime change in this document: NONE

## 1. Purpose

Wave 2.1 introduces the missing operational backbone for Field Operations: a canonical schedule by СМР / execution package that connects planning with actual site progress, materials, deliveries, subcontractors, blockers, payments and alerts.

The goal is **not** to add another task list or another material/subcontractor register. Existing records remain authoritative and are linked through a schedule/readiness layer.

Core rule:

> Every planned СМР must know what is required for it to start. BEG_Work checks these prerequisites before the planned start, turns missing prerequisites into visible blockers/actions, and recalculates forecast dates from approved actual progress. Baseline is never changed silently.

## 2. Existing foundations in `main`

Wave 2.1 must build on the existing code instead of duplicating it.

### 2.1 Execution packages and progress

Existing:
- `execution_packages` are used by `backend/app/routes/budget_progress.py`;
- budget freeze snapshots already include qty, unit, budget and planned hours;
- `progress_updates` store actual progress;
- the execution package stores latest `progress_percent`, source and update timestamp;
- progress-vs-cost already compares labor/material/subcontract usage.

Gap:
- no canonical schedule dates/dependency graph;
- no baseline/current-plan/forecast separation;
- no readiness evaluation;
- no automatic downstream forecast impact.

### 2.2 Daily reports

Existing:
- `backend/app/routes/daily_reports.py` supports project + `smr_id` + hours;
- approval workflow exists;
- approved reports feed canonical labor/work-session logic.

Gap:
- no canonical quantity-progress payload per execution package for schedule forecasting;
- approved daily reports do not drive schedule forecast.

### 2.3 Procurement

Existing:
- `material_requests` with project, offer source, stage and `needed_date`;
- request lines with requested/fulfilled qty and offer-line relation;
- supplier invoice intake and warehouse posting foundations.

Gap:
- request not canonically linked to execution package/SMR readiness;
- no `required_on_site_date` derived from schedule;
- no latest-safe-order calculation;
- schedule does not verify physically available quantity at the project location.

### 2.4 Subcontractors

Existing:
- subcontractor packages and lines;
- `source_qty`, `assigned_qty`, `certified_qty`, `remaining_qty`;
- unit prices, contract/certified/paid totals;
- subcontractor performance dates and financial variance;
- progress-vs-cost can derive certified quantity / assigned quantity.

Gap:
- no `actual_executed_qty` and `accepted_qty` as distinct operational quantities;
- no required/confirmed crew date tied to scheduled СМР;
- no productivity-based forecast completion tied to FLOW-027.

### 2.5 Alerts and briefings

Existing:
- alarms route;
- morning briefing route;
- notifications/reminder logs.

Gap:
- no common readiness/blocker event contract feeding them from the schedule.

## 3. Canonical model

### 3.1 Schedule identity

The schedule operates on the existing execution package / WorkPackage identity.

No second `scheduled_tasks` business registry should be created for the same СМР.

Minimum schedule extension for an execution package:

```json
{
  "schedule": {
    "baseline_version": 1,
    "baseline_start": "2026-09-30",
    "baseline_end": "2026-10-03",
    "current_plan_start": "2026-09-30",
    "current_plan_end": "2026-10-03",
    "forecast_start": "2026-10-01",
    "forecast_end": "2026-10-04",
    "duration_workdays": 4,
    "calendar_id": "BG-WORKDAYS",
    "total_float_days": 1,
    "critical": false,
    "forecast_updated_at": "...",
    "forecast_source": "approved_daily_progress"
  }
}
```

The exact persistence shape may be embedded or normalized after schema review, but there must be one canonical schedule identity per execution package.

### 3.2 Dependency record

Proposed canonical relation:

```json
{
  "id": "...",
  "org_id": "...",
  "project_id": "...",
  "predecessor_package_id": "...",
  "successor_package_id": "...",
  "dependency_type": "FS",
  "lag_workdays": 0,
  "blocking": true,
  "created_at": "...",
  "created_by": "..."
}
```

Supported v1 dependency types:
- FS — Finish to Start;
- SS — Start to Start;
- FF — Finish to Finish.

SF is out of scope unless a real BEG use case requires it.

### 3.3 Baseline versions

Baseline is immutable history.

A baseline change creates a new version with reason/approval, never overwrites the previous version.

Forecast changes must **not** create new baseline versions.

## 4. Readiness model

Readiness is a calculated read model, not a second business truth.

Statuses:
- `READY`;
- `AT_RISK`;
- `BLOCKED`;
- `NOT_DUE`.

A readiness response must explain each prerequisite and its source.

Example:

```json
{
  "execution_package_id": "...",
  "status": "BLOCKED",
  "planned_start": "2026-09-30",
  "forecast_start": "2026-10-01",
  "readiness_percent": 72,
  "checks": [
    {"type": "predecessor", "status": "ready"},
    {"type": "material", "status": "blocked", "reason": "13 bags short on site"},
    {"type": "subcontractor", "status": "risk", "reason": "crew date not confirmed"},
    {"type": "decision", "status": "blocked", "reason": "drain detail unanswered"}
  ],
  "latest_safe_action_date": "2026-09-27"
}
```

Readiness must never hide an unknown prerequisite as green.

## 5. Material readiness

### 5.1 Required dates

Material requirements linked to an execution package must support:
- `required_qty`;
- `required_on_site_date`;
- `lead_time_days`;
- `delivery_days`;
- `buffer_days`;
- calculated `latest_safe_order_date`.

Formula v1:

```text
latest_safe_order_date
= required_on_site_date
- lead_time_days
- delivery_days
- buffer_days
```

Business calendars may replace raw calendar subtraction in the schedule service.

### 5.2 Status chain

The UI/readiness engine must distinguish:

```text
required
→ requested
→ ordered
→ advance/payment ready (when applicable)
→ supplier confirmed
→ dispatched
→ delivered
→ accepted
→ physically on site
→ available quantity for the СМР
→ consumed
```

`ordered` is never equivalent to `ready for work`.

### 5.3 Delivery evidence

A delivery receipt must support:
- ordered qty;
- delivered qty;
- accepted qty;
- damaged/rejected qty;
- project/location;
- receiving person;
- timestamp;
- photo/file evidence IDs through File Registry;
- note / discrepancy reason.

For configured material categories, photo evidence can be mandatory before final acceptance.

## 6. Subcontractor quantity control

Subcontractor operational progress must remain quantity-based and reconcile to the КСС / execution package.

Per line:

```text
source_qty          = quantity in source estimate / execution package
assigned_qty        = quantity awarded to this subcontractor
actual_executed_qty = field-reported quantity
accepted_qty        = technically accepted quantity
certified_qty       = quantity in subcontractor act/certificate
paid_qty/value      = quantity/value represented by official payments/allocations
remaining_qty       = assigned_qty - accepted/executed according to the chosen view
```

Required views:
- contract quantity vs actual executed;
- plan-to-date quantity vs actual quantity;
- accepted vs certified;
- certified vs paid;
- remaining quantity;
- daily/weekly productivity;
- forecast completion from recent productivity.

Example:

```text
КСС / assigned:     1,200 m²
plan-to-date:         360 m²
actual executed:      290 m²
accepted:             275 m²
certified:            250 m²
remaining:            910 m² (operational executed basis)
variance to plan:     -70 m²
```

Do not use a subjective `almost complete` status when a measurable unit exists.

## 7. Approved daily report → forecast

Only an approved field record may change official actual progress used by FLOW-027.

Wave 2.1 must support measured progress input per execution package:
- quantity completed today;
- cumulative actual quantity;
- workers/hours;
- downtime;
- rework;
- blocker reason;
- evidence references.

Forecast algorithm v1 must be deterministic and auditable.

Minimum logic:
1. determine remaining quantity;
2. calculate recent accepted productivity where enough evidence exists;
3. compare required productivity to meet current plan;
4. forecast package end;
5. propagate dependency impact downstream;
6. do not modify baseline;
7. expose reason/evidence for every forecast move.

AI may later suggest recovery scenarios, but deterministic schedule math is not delegated to an LLM.

## 8. Problems, questions and decisions

A blocker/question must link to one or more execution packages.

Minimum relation:

```json
{
  "blocker_id": "...",
  "execution_package_id": "...",
  "blocking_effect": "START_BLOCKED",
  "responsible_party_id": "...",
  "answer_due_at": "...",
  "status": "OPEN"
}
```

The answer due date should be derived from the latest safe decision date when possible, not manually guessed.

An informal comment is not an official decision. Formal approval/decision remains auditable under the canonical Approval/Decision flow.

If the due date passes:
- readiness changes;
- reminder/escalation is created;
- forecast impact is recalculated when the blocker affects the schedule.

## 9. Payments as prerequisites

Payment remains authoritative in Payment Core. Wave 2.1 stores only the relation that a payment/obligation blocks another prerequisite.

Examples:
- advance required before fabrication;
- balance required before dispatch;
- retention not blocking production.

The schedule/readiness engine may read payment status; it must not create a second payment ledger.

## 10. Alerts and reminders

Wave 2.1 emits normalized operational conditions for FLOW-026 / notifications.

Required conditions:
- work starts soon but readiness < 100%;
- material not ordered by latest safe order date;
- delivered material not physically on project location;
- required quantity short;
- delivery due soon but front/installer not ready;
- promised delivery late → supplier follow-up action;
- subcontractor crew not confirmed;
- blocking payment approaching / insufficient funding signal when finance source exists;
- blocker/question unanswered near/after due date;
- progress below plan / forecast slip;
- measurable work ready for act/certification.

Escalation must identify the actual blocking party, not blame a downstream worker who is waiting.

## 11. Proposed API surface

Names are provisional but ownership is not.

```text
GET  /projects/{project_id}/schedule
GET  /projects/{project_id}/schedule/readiness?days=14
GET  /execution-packages/{id}/schedule
PUT  /execution-packages/{id}/current-plan
POST /execution-packages/{id}/dependencies
DELETE /execution-packages/{id}/dependencies/{dependency_id}
GET  /execution-packages/{id}/readiness
POST /projects/{project_id}/schedule/recalculate
POST /projects/{project_id}/schedule/baselines
GET  /projects/{project_id}/schedule/baselines
```

Consequential plan/baseline writes require permission, idempotency, audit and explicit confirmation/approval according to the existing foundations.

## 12. Additive integration changes

### `material_requests`
Add/link, without creating a second request registry:
- `execution_package_id` / `smr_id` on request line where applicable;
- `required_on_site_date`;
- lead-time metadata or reference to supplier/material lead-time source.

### `subcontractor_package_lines`
Add operational fields/read model as needed:
- `actual_executed_qty`;
- `accepted_qty`;
- last progress/evidence timestamp;
- schedule package relation is already possible through `execution_package_id`.

### `daily_reports` / field progress
Extend approved measured data so actual quantities can update canonical package progress.

### delivery receipt
Use existing procurement/logistics/File Registry ownership; add evidence relation and accepted/damaged quantities instead of inventing a standalone photo table.

## 13. Migration strategy

W2.1-01 must be additive and feature-off.

Rules:
- existing execution packages remain valid with no schedule fields;
- migration/backfill must not invent historical baseline dates;
- records without schedule are `UNSCHEDULED`, not silently assigned dates;
- legacy `needed_date` remains readable during transition;
- new schedule-derived fields can be shadow-computed before enforcement;
- no destructive migration;
- rollback/revert only removes W2.1-owned additive data when safe;
- test on isolated non-production Mongo before any deploy decision.

## 14. Test contract

Minimum tests before runtime enablement:

### Schedule
- FS/SS/FF dependency math;
- lag calculation;
- critical path / float sanity;
- downstream shift from predecessor delay;
- overlapping delay does not double-count calendar impact;
- forecast move does not alter baseline.

### Progress
- unapproved field report cannot update official forecast;
- approved quantity updates remaining quantity and forecast;
- rework/downtime handling is explicit;
- measured quantity cannot exceed allowed bounds without review.

### Materials
- ordered but not delivered is not ready;
- delivered to warehouse but not project is not ready;
- insufficient on-site qty blocks readiness;
- latest-safe-order warning calculation;
- delivery receipt supports photo evidence IDs and discrepancies.

### Subcontractors
- source/assigned/executed/accepted/certified quantities reconcile;
- over-allocation remains blocked;
- productivity forecast detects delay;
- paid amount/quantity never becomes a second payment truth.

### Blockers
- unresolved question blocks the linked package;
- answer/decision clears blocker only through valid state transition;
- escalation identifies responsible party;
- downstream waiting party is not marked at fault.

### Security / foundations
- tenant isolation;
- permission checks;
- idempotency on critical writes;
- append-only audit evidence;
- no cross-project relation unless explicitly permitted.

## 15. Delivery plan

### W2.1-01 — contracts/schema/migration/tests
No UI. Feature off. Define relations and backfill-safe schema.

### W2.1-02 — schedule engine
Dependency graph, calendars, baseline/current/forecast and deterministic recalculation.

### W2.1-03 — readiness adapters
Materials, physical location, subcontractor, blocker/decision and payment-read adapters.

### W2.1-04 — daily progress integration
Approved measured progress → package actual → forecast.

### W2.1-05 — reminders/alarms
FLOW-026 + Action Inbox / morning briefing conditions.

### W2.1-06 — UI
Project schedule, 14-day readiness, blockers, who-is-waiting-for-whom and operational drill-down.

## 16. Non-goals for Wave 2.1 foundation

- automatic AI rescheduling without confirmation;
- replacing Primavera/MS Project as a full enterprise planning suite;
- free chat as a source of official decisions;
- a second procurement, payment, material, subcontractor or progress ledger;
- production deploy from a planning PR.

## 17. Gate to start coding

Before W2.1-01 implementation is merged:
- W0 tenancy/permission/audit/idempotency contracts used by the touched routes must be available in `main` or the PR must remain feature-off;
- schema owner for execution package schedule fields must be agreed;
- authoritative sources for material location, payment status and decision status must be named;
- migration and rollback plan reviewed;
- test evidence required in the PR;
- explicit Krum merge/deploy decisions remain separate.

# BEG_Work — Implementation Waves

> Цел: паралелно програмиране без нарушаване на FLOW зависимостите.  
> Корекция 20.07.2026: FLOW-008 е 100% Business Lock; FLOW-025 остава 80% с 2 решения.

# Wave 0 — Architecture Foundation Refactor

Тази вълна е задължителна преди масово feature development.

## W0-01 — Permission Service / FLOW-002

- `role_assignments` model.
- action/module/scope permissions.
- project/location scope.
- compatibility adapter за `users.role`.
- миграция и permission test matrix.

## W0-02 — Master Data / FLOW-032

- Master Person / Organization / Activity / Item / Asset Type / Location.
- alias and normalization tables.
- merge + redirect history.
- inventory на старите collections.
- read/write cutoff plan.

## W0-03 — Audit / Lifecycle / Idempotency

- Common `AuditEvent` envelope.
- `archived_at/deleted_at` policy.
- request/correlation/idempotency keys.
- before/after/reason/actor/source FLOW.
- critical write coverage test.

## W0-04 — Payment Core / FLOW-006

- one `finance_payments` write service.
- obligations and allocations.
- source uniqueness indexes.
- reverse/correction API.
- retire legacy payment writers/readers.

## W0-05 — File Registry / FLOW-016

- `files`, `file_versions`, `file_relations`, `storage_locations`.
- Local/Synology/S3/Google Drive adapters.
- checksum, immutable original, backup state.
- migration from `media_files` and `/uploads`.

## W0-06 — Data Quality + Approval / FLOW-033/034

- DQ issues with severity/blocking/owner/deadline.
- approval request with evidence/decision/execution.
- dual approval and escalation.
- links to original domain records.

## W0-07 — Test/Release Foundation / FLOW-042

- test-case schema: allowed/forbidden/correction/reversal.
- API contract tests.
- migration tests.
- source-of-truth reconciliation tests.
- CI and release version links.

## W0-08 — Disaster Recovery / FLOW-044

- version manifest.
- DB PITR/backups.
- file backup and immutable off-site copy.
- restore script and health checks.
- quarterly full restore drill.

---

# Wave 1 — Commercial Core

## Цел

Един надежден път:

`Object → Offer → Contract/Annex → Act → Invoice → Payment → Project result`

## FLOW scope

- FLOW-001 Projects/status/closing.
- FLOW-003 Offers/versions/Excel/provenance.
- FLOW-004 Acts.
- FLOW-005 Contracts/annexes/retentions/guarantees.
- FLOW-006 Finance/payment allocations.
- FLOW-007 Extra works/change orders.
- FLOW-008 Project financial view — бизнес логиката е заключена; изисква source map, read-only drill-down и reconciliation tests.
- FLOW-010 Master-linked counterparties — след останалите 3 решения.
- FLOW-025 document control — след двете финални checklist/blocking матрици.

## Exit criteria

- no hard delete of used project/commercial records;
- stable offer line identity;
- exact-version client/contract approval;
- fixed-price and remeasurement act tests;
- one payment ledger;
- contract/offer/act/invoice/payment reconciliation;
- Krum dashboard drill-down;
- document checklist/blocking rules са изрично заключени преди FLOW-025 release.

---

# Wave 2 — Field Operations and Cost Control

## FLOW scope

- FLOW-009 warehouse/FIFO/movements.
- FLOW-011 assets/QR/custody/repairs.
- FLOW-012 logistics — след 4 business decisions.
- FLOW-013 attendance.
- FLOW-014 daily reports/side work/change requests.
- FLOW-015 dashboards.
- FLOW-019 labor by SMR.
- FLOW-020 materials/request/delivery/invoice reconciliation.
- FLOW-021 subcontractor packages/acts/payments.
- FLOW-024 overhead.
- FLOW-026 alarms.
- FLOW-027 progress/timeline/delays.
- FLOW-028 payroll/Pay Run.
- FLOW-029 photo archive.
- FLOW-035 generic Work Package — след 2 business decisions.
- FLOW-037 offline field app — след 4 business decisions.
- FLOW-039 quality/defects/warranty — след 5 business decisions.
- FLOW-047 managed package/bonus fund.

## Exit criteria

- one canonical attendance/report schema;
- no report without presence/SMR/time;
- materials trace request→delivery→invoice→stock/object;
- one generic WorkPackage supports internal/subcontractor/mixed;
- offline writes are idempotent and conflict-aware;
- quality/defect cost affects package/project/rating;
- paid labor and subcontractor cash movements reconcile to finance ledger.

---

# Wave 3 — AI and Decision Intelligence

## FLOW scope

- FLOW-022 market labor prices.
- FLOW-023 automatic offer analysis.
- FLOW-030 BEG Brain.
- FLOW-031 agent hats.
- FLOW-036 Object Timeline — after 3 business decisions.
- FLOW-038 Procurement Agent — after 5 business decisions.
- FLOW-040 AI Audit Log — after 2 business decisions.
- FLOW-041 Scenario/What-if — after 4 business decisions.
- FLOW-045 AI Command Center — after final matrix.
- FLOW-048 Resource Recommendation — after 6 business decisions.

## Rules

- read-only tools first;
- write tools only through confirmation + permission + Approval;
- tool output states included/excluded/current timestamp;
- no direct MongoDB access from LLM;
- AI cannot invent Master IDs, locations, prices or approvals;
- every tool call/action is auditable.

---

# Wave 4 — External Portals and Marketplace

## FLOW scope

- FLOW-046 Client Portal — after 4 business decisions.
- FLOW-049 Marketplace — after 8 business decisions.

## Exit criteria

- tenant/client isolation;
- exact-version written approvals;
- magic link/identity verification;
- restricted financial view;
- WorkPackage publication redacts internal margin/budget;
- calendar reservations and conflict handling;
- verified profiles and evidence-based rating;
- disputes/cancellations/sanctions;
- no automatic contractor selection.

---

# Parallel work policy

## Може да върви едновременно

- W0 permission, Master Data, File Registry, AuditEvent, tests and DR can be separate workstreams with agreed schemas.
- UI mockups for W1/W2 can proceed against versioned API contracts.
- Data migration inventory can proceed in parallel with business FLOW completion.
- FLOW-008 technical refactor може да се проектира паралелно, защото Business Lock е възстановен.

## Не може да върви независимо

- AI write actions before Permission/DQ/Approval/Audit.
- Client portal approval before exact-version document/offer model.
- Marketplace before generic WorkPackage and Counterparty Master.
- payroll release before canonical daily reports and one payment service.
- file/photo expansion before File Registry abstraction.
- FLOW-025 final implementation before the two document/checklist matrices are approved.

---

# First programming backlog

1. ADR + schema for RoleAssignment.
2. Master Data inventory/migration map.
3. AuditEvent schema and critical-write helper.
4. Payment idempotency and source unique indexes.
5. File Registry schema and local adapter.
6. DQ/Approval minimal models.
7. Canonical project status migration.
8. Canonical daily report validation/migration.
9. Acceptance test harness.
10. Backup/version manifest and restore dry-run.

## Източници / сесии

- FLOW-001–049 business documents in PR #2.
- Cross-FLOW code audit, 20.07.2026.
- Correction pass, 20.07.2026.
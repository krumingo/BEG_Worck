# BEG_Work — Implementation Waves

> Цел: паралелно програмиране без нарушаване на FLOW зависимостите.  
> Business-close pass 21.07.2026: FLOW-025 е 100%; action-specific document requirements и blocking rules са заключени.

# Wave 0 — Architecture Foundation Refactor

Тази вълна е задължителна преди масово feature development.

## W0-01 — Permission Service / FLOW-002

- `role_assignments` model;
- `ExternalPrincipal` и `AccessGrant` за бъдещия Client Portal/Marketplace;
- action/module/scope/resource/version permissions;
- project/location scope;
- compatibility adapter за `users.role`;
- expiry/revoke/tenant-isolation rules;
- миграция и permission test matrix.

## W0-02 — Master Data / FLOW-032

- Master Person / Organization / Activity / Item / Asset Type / Location;
- alias and normalization tables;
- merge + redirect history;
- inventory на старите collections;
- read/write cutoff plan.

## W0-03 — Audit / Lifecycle / Idempotency

- Common `AuditEvent` envelope;
- `archived_at/deleted_at` policy;
- request/correlation/idempotency keys;
- before/after/reason/actor/source FLOW;
- critical write coverage test.

## W0-04 — Payment Core / FLOW-006

- one `finance_payments` write service;
- obligations and allocations;
- source uniqueness indexes;
- reverse/correction API;
- retire legacy payment writers/readers.

## W0-05 — File Registry / FLOW-016

- `files`, `file_versions`, `file_relations`, `storage_locations`;
- Local/Synology/S3/Google Drive adapters;
- checksum, immutable original, backup state;
- migration from `media_files` and `/uploads`.

## W0-06 — Data Quality + Approval / FLOW-033/034

- DQ issues with severity/blocking/owner/deadline;
- approval request with evidence/decision/execution;
- dual approval and escalation;
- links to original domain records.

## W0-07 — Test/Release Foundation / FLOW-042

- Bootstrap QA Gate v0 in GitHub from the first Wave 0 change;
- test-case schema: allowed/forbidden/correction/reversal;
- API contract tests;
- migration tests;
- source-of-truth reconciliation tests;
- CI and release version links.

## W0-08 — Disaster Recovery / FLOW-044

- version manifest;
- DB PITR/backups;
- file backup and immutable off-site copy;
- restore script and health checks;
- quarterly full restore drill.

---

# Wave 1 — Commercial Core

## Цел

Един надежден път:

`Object → Offer → Contract/Annex → Act → Invoice → Payment → Project result`

## FLOW scope

- FLOW-001 Projects/status/closing;
- FLOW-003 Offers/versions/Excel/provenance;
- FLOW-004 Acts;
- FLOW-005 Contracts/annexes/retentions/guarantees;
- FLOW-006 Finance/payment allocations;
- FLOW-007 Extra works/change orders;
- FLOW-008 Project financial view — бизнес логиката е заключена; изисква source map, read-only drill-down и reconciliation tests;
- FLOW-010 Master-linked counterparties — след останалите 3 решения;
- FLOW-025 Document Control — бизнес заключен; runtime след FLOW-016, FLOW-002 и FLOW-034.

## Written client approval преди FLOW-046

Пълният Client Portal не блокира Wave 1. Exact-version approval се реализира чрез един `ApprovalReceipt` модел и adapters за:

- подписан PDF/e-signature;
- verified email reply към exact version/ID;
- защитена еднократна approval page.

Receipt-ът използва File Registry, ExternalPrincipal/AccessGrant, Approval Center и AuditEvent. Portal-ът по-късно използва същия модел, без миграция към втори approval register.

## Document Control runtime / FLOW-025

Wave 1 изгражда:

- `DocumentType`, `DocumentFamily` и immutable `DocumentVersion`;
- one-Current constraint по version family;
- versioned `DocumentRequirementTemplate`;
- immutable `DocumentRequirementSnapshot` при акт, фактура, плащане и project transition;
- action-specific guards за client act, subcontractor act, advance invoice, progress/final invoice, supplier payable, payroll/bonus payment и retention release;
- exception requests през FLOW-034;
- правило: system-initiated payment се блокира при липсващи документи, но вече настъпил банков факт винаги се записва като `Unallocated / За проверка`.

Document Control не създава собствено плащане и не копира файлове извън FLOW-016.

## Exit criteria

- no hard delete of used project/commercial records;
- stable offer line identity;
- exact-version client/contract approval чрез валиден Approval Receipt;
- new-version invalidation на стар approval link;
- fixed-price and remeasurement act tests;
- one payment ledger;
- contract/offer/act/invoice/payment reconciliation;
- Krum dashboard drill-down;
- one-Current document version constraint;
- requirement template/snapshot traceability;
- allowed/forbidden tests за act, invoice и payment blockers;
- imported real payment без основание се пази в ledger, но остава unallocated и блокирано за closing.

---

# Wave 2 — Field Operations and Cost Control

## FLOW scope

- FLOW-009 warehouse/FIFO/movements;
- FLOW-011 assets/QR/custody/repairs;
- FLOW-012 logistics — след 4 business decisions;
- FLOW-013 attendance;
- FLOW-014 daily reports/side work/change requests/downtime;
- FLOW-015 dashboards;
- FLOW-019 labor by SMR + productive/total-efficiency KPI;
- FLOW-020 materials/request/delivery/invoice reconciliation;
- FLOW-021 subcontractor packages/acts/payments;
- FLOW-024 overhead + project-vs-firm downtime allocation;
- FLOW-026 alarms;
- FLOW-027 progress/timeline/delays;
- FLOW-028 payroll/Pay Run + management bonus obligations;
- FLOW-029 photo archive;
- FLOW-035 generic Work Package, PackageTemplate and canonical UI — business locked;
- FLOW-037 offline field app — след 4 business decisions;
- FLOW-039 quality/defects/warranty — след 5 business decisions;
- FLOW-047 managed package/bonus fund.

## Exit criteria

- one canonical attendance/report schema;
- no report without presence/SMR/time;
- side work and downtime have separate time/cause/cost treatment;
- productive productivity and total paid-labor efficiency are both visible;
- project downtime cannot be hidden in firm overhead;
- materials trace request→delivery→invoice→stock/object;
- one generic WorkPackage supports internal/subcontractor/mixed;
- PackageTemplate generation is idempotent and produces drafts/preview;
- offline writes are idempotent and conflict-aware;
- quality/defect cost affects package/project/rating;
- paid labor, management bonus and subcontractor cash movements reconcile to finance ledger;
- VAT-neutral bonus calculation and source-unique obligation tests pass.

---

# Wave 3 — AI and Decision Intelligence

## FLOW scope

- FLOW-022 market labor prices;
- FLOW-023 automatic offer analysis;
- FLOW-030 BEG Brain;
- FLOW-031 agent hats;
- FLOW-036 Object Timeline — after 3 business decisions;
- FLOW-038 Procurement Agent — after 5 business decisions;
- FLOW-040 AI Audit Log — after 2 business decisions;
- FLOW-041 Scenario/What-if — after 4 business decisions;
- FLOW-045 AI Command Center — business locked; runtime after Wave 0 foundations;
- FLOW-048 Resource Recommendation — after 6 business decisions.

## Rules

- FLOW-045 е интерфейсът/orchestrator на същия BEG Brain, не отделен AI;
- read-only tools first;
- write tools only through intent catalog, draft/preview, confirmation, permission and Approval;
- tool output states included/excluded/current timestamp;
- no direct MongoDB access from LLM;
- AI cannot invent Master IDs, locations, prices or approvals;
- every tool call/action is auditable;
- every retryable action has idempotency key.

---

# Wave 4 — External Portals and Marketplace

## FLOW scope

- FLOW-046 Client Portal — after remaining 3 business decisions;
- FLOW-049 Marketplace — after 8 business decisions.

## Exit criteria

- tenant/client isolation;
- ExternalPrincipal/AccessGrant enforcement;
- exact-version written approvals using the same ApprovalReceipt from Wave 1;
- magic link/identity verification and revoke/expiry;
- restricted financial view;
- WorkPackage publication redacts internal margin/budget;
- calendar reservations and conflict handling;
- verified profiles and evidence-based rating;
- disputes/cancellations/sanctions;
- no automatic contractor selection.

---

# Parallel work policy

## Може да върви едновременно

- W0 permission, Master Data, File Registry, AuditEvent, tests and DR can be separate workstreams with agreed schemas;
- UI mockups for W1/W2 can proceed against versioned API contracts;
- Data migration inventory can proceed in parallel with business FLOW completion;
- FLOW-008 technical refactor може да се проектира паралелно;
- FLOW-035 schema/UI contract може да се проектира след W0 IDs/permissions agreement;
- Interim Approval Receipt adapter може да се проектира преди пълния FLOW-046 portal;
- FLOW-025 requirement model може да се проектира паралелно след agreement за File Registry IDs, Approval и Permission contracts.

## Не може да върви независимо

- AI write actions before Permission/DQ/Approval/Audit;
- portal/magic link before ExternalPrincipal/AccessGrant security contract;
- Marketplace before generic WorkPackage and Counterparty Master;
- payroll release before canonical daily reports and one payment service;
- management bonus payment before FLOW-047 calculation + Approval + FLOW-028 obligation;
- file/photo/document expansion before File Registry abstraction;
- FLOW-025 action guards before FLOW-016 version relations and FLOW-034 exception/approval contracts.

---

# First programming backlog

1. ADR + schema for RoleAssignment and ExternalPrincipal/AccessGrant.
2. Master Data inventory/migration map.
3. AuditEvent schema and critical-write helper.
4. Payment idempotency and source unique indexes.
5. File Registry schema and local adapter.
6. DQ/Approval minimal models.
7. Bootstrap QA Gate repository structure.
8. Canonical project status migration.
9. Canonical daily report/downtime validation and migration.
10. ApprovalReceipt model + signed-PDF/email/secure-page adapters.
11. DocumentType/Family/Version + RequirementTemplate/Snapshot schema contract.
12. Generic WorkPackage + PackageTemplate schema contract.
13. Backup/version manifest and restore dry-run.

## Източници / сесии

- FLOW-001–049 business documents in PR #2.
- Cross-FLOW code audit, 20.07.2026.
- Claude Cross-FLOW logic audit and resolution pass, 20.07.2026.
- FLOW-025 business-close pass, 21.07.2026.

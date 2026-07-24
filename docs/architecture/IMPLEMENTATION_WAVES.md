# BEG_Work — Implementation Waves

> Цел: паралелно програмиране без нарушаване на FLOW зависимостите.  
> Business-close pass 24.07.2026: FLOW-010, FLOW-012, FLOW-025, FLOW-036, FLOW-040 и FLOW-046 са 100%; counterparty, logistics, document-control, Timeline, audit и Client Portal правилата са заключени.

# Wave 0 — Architecture Foundation Refactor

Тази вълна е задължителна преди масово feature development.

## W0-01 — Permission Service / FLOW-002

- `role_assignments` model;
- `ExternalPrincipal`, client organization membership и `AccessGrant`;
- action/module/scope/resource/version/amount permissions;
- project/location scope;
- compatibility adapter за `users.role`;
- OTP/MFA, expiry, revoke, session/device и tenant-isolation rules;
- миграция и permission test matrix.

## W0-02 — Master Data / FLOW-032

- Master Person / Organization / Activity / Item / Asset Type / Location;
- alias and normalization tables;
- merge + redirect history;
- inventory на старите collections;
- read/write cutoff plan.

## W0-03 — Audit / Lifecycle / Idempotency / FLOW-040

- canonical common `AuditEvent` envelope;
- append-only store и correction/reversal/annotation events вместо update/delete;
- request/correlation/idempotency keys;
- before/after references, reason, actor, effective role/scope и source FLOW;
- AI request→tools→draft→human confirmation→domain execution correlation;
- R1–R6 retention classes и retention anchors;
- hot storage, immutable archive, legal/incident hold и controlled disposition;
- hash chain или signed batch manifests и integrity verification;
- L0–L5 visibility, field masking и audit-of-audit;
- immutable/off-site backup и searchable-index rebuild;
- migration от текущите `audit_logs` и critical-write coverage test.

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
- file and AuditEvent backup with immutable off-site copy;
- restore script and health/integrity checks;
- quarterly full restore drill.

## Wave 0 exit criteria

- permission checks use canonical assignments, not ad hoc role strings;
- external access uses scoped and revocable AccessGrants;
- critical writes create one canonical AuditEvent;
- event sequence/hash integrity is verifiable;
- retention/hold/archive/disposition and visibility tests pass;
- payment writes are idempotent and source-unique;
- files use provider-neutral IDs and versions;
- DQ/Approval and Bootstrap QA foundations are available;
- database, files and audit archive have a proven restore path.

---

# Wave 1 — Commercial Core

## Цел

`Object → Offer → Contract/Annex → Act → Invoice → Payment → Project result`

## FLOW scope

- FLOW-001 Projects/status/closing;
- FLOW-003 Offers/versions/Excel/provenance;
- FLOW-004 Acts;
- FLOW-005 Contracts/annexes/retentions/guarantees;
- FLOW-006 Finance/payment allocations;
- FLOW-007 Extra works/change orders;
- FLOW-008 Project financial view;
- FLOW-010 Master-linked counterparties;
- FLOW-025 Document Control.

## Written client approval before full portal runtime

Exact-version approval uses one `ApprovalReceipt` model and adapters for:

- signed PDF/e-signature;
- verified email reply to exact version/ID;
- secure one-time approval page;
- exact-version approval card in a client thread.

The receipt uses File Registry, ExternalPrincipal/AccessGrant, Approval Center and AuditEvent. FLOW-046 later uses the same records without a second approval register.

## Counterparty / Communication / Bank Verification / FLOW-010

Wave 1 builds:

- Master Organization/Person with role/scope assignments;
- controlled deduplication/merge and redirects;
- separate internal and client project threads;
- context links to project, contract, offer, Change Request, act, invoice, document and task;
- versioned AI summary snapshots with source links and masking;
- ApprovalReceipt and invalidation at new version;
- VerifiedBankAccount registry and AI/OCR invoice comparison;
- first-payment/new-or-changed-IBAN block and two-source verification;
- financial view `counterparty → project → contract/package → role`;
- separate receivables/payables and no automatic netting.

IBAN verification and payment approval are separate actions. An outgoing BEG invoice may use only an active verified company IBAN.

## Document Control / FLOW-025

Wave 1 builds:

- `DocumentType`, `DocumentFamily`, immutable `DocumentVersion` and one-Current constraint;
- versioned `DocumentRequirementTemplate`;
- immutable `DocumentRequirementSnapshot`;
- action guards for acts, invoices, payables, payroll/bonus payments and retention release;
- exception requests through FLOW-034;
- rule: a system-initiated payment is blocked when requirements are missing, but an already occurred bank/cash fact is recorded as `Unallocated / За проверка`.

## Wave 1 exit criteria

- no hard delete of used project/commercial records;
- stable offer line identity and exact-version approval;
- fixed-price and remeasurement act tests;
- one payment ledger and reconciliation across contract/offer/act/invoice/payment;
- one Master organization/person identity and enforceable contact authority;
- internal/client communication isolation;
- AI summaries open their original sources;
- first payment to unverified IBAN is blocked;
- verified IBAN does not bypass payment Approval;
- financial view separates invoiced/received revenue, costs and overdue positions by project/contract;
- no automatic netting;
- one-Current document version and requirement snapshot traceability;
- allowed/forbidden tests for act, invoice and payment blockers;
- commercial critical actions have R1 AuditEvent and exact source-version references.

---

# Wave 2 — Field Operations and Cost Control

## FLOW scope

- FLOW-009 warehouse/FIFO/movements;
- FLOW-011 assets/QR/custody/repairs;
- FLOW-012 logistics / purchases / deliveries / courses — **100% Business Lock**;
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
- FLOW-035 generic Work Package + PackageTemplate;
- FLOW-037 offline field app — after 4 business decisions;
- FLOW-039 quality/defects/warranty — after 5 business decisions;
- FLOW-047 managed package/bonus fund.

## Logistics / FLOW-012

Wave 2 builds:

- `PurchaseDeliveryRequest` and line-level max price, VAT basis, allowed equivalents, object/SMR/deadline and blocking priority;
- `LogisticsTrip`, ordered stops, Loading List per stop, vehicle capacity and reverse loads;
- driver mobile flow: today → purchase → load → current stop → unload → handoff → reverse load → close;
- offline/idempotent queue through FLOW-037;
- residual priority queue: unfulfilled quantity remains on the original line and moves to the next possible course;
- official cancellation with reason and AuditEvent;
- AI/OCR invoice-line matching and `РАЗЛИЧНО ОТ ЗАЯВКАТА` explanation workflow;
- reusable-item intake: ID/QR, condition, location, one human responsible, return rule and warehouse reuse;
- person/project/vehicle/kit custody with one accountable human;
- QR physical-movement chain and explicit handover/acceptance before responsibility transfer;
- separate requested, approved, purchased, loaded, unloaded, accepted, damaged, refused, returned, remaining and cancelled quantities;
- missing-in-transport investigation without automatic blame;
- quarantine/return/claim/repair/write-off path for damaged items;
- acceptance roles and deadlines: immediate for assets, same workday for normal materials, up to 24h for large/technical checks;
- no automatic acceptance after SLA expiry; reminder, escalation and substitute task;
- controlled no-recipient delivery with photo, GPS, time, notice and temporary responsible;
- multi-stop wrong-destination prevention and approved AI reverse-route suggestions;
- monthly visibility for unassigned reusable purchases, missing returns and repeated purchases despite stock.

## Wave 2 exit criteria

- one canonical attendance/report schema;
- no report without presence/SMR/time;
- side work and downtime have separate time/cause/cost treatment;
- productive productivity and total paid-labor efficiency are both visible;
- project downtime cannot be hidden in firm overhead;
- materials trace request→purchase/warehouse→trip→delivery→acceptance→invoice→stock/object;
- max-price and VAT basis tests pass;
- unfulfilled residual lines survive trip closure and retain priority/history;
- unmatched invoice lines cannot close without explanation/classification;
- reusable items cannot close without location and one human responsible;
- QR scan alone cannot transfer responsibility;
- partial/missing/damaged/refused/returned state-machine tests pass;
- acceptance SLA never becomes silent auto-acceptance;
- wrong-stop, duplicate/retry and offline conflict tests pass;
- returned reusable items become available and are proposed before repurchase;
- one generic WorkPackage supports internal/subcontractor/mixed;
- PackageTemplate generation is idempotent and produces drafts/preview;
- quality/defect cost affects package/project/rating;
- paid labor, management bonus and subcontractor cash movements reconcile to the finance ledger;
- VAT-neutral bonus calculation and source-unique obligation tests pass;
- operational critical events inherit R1/R2 retention and are reconstructable.

---

# Wave 3 — AI and Decision Intelligence

## FLOW scope

- FLOW-022 market labor prices;
- FLOW-023 automatic offer analysis;
- FLOW-030 BEG Brain;
- FLOW-031 agent hats;
- FLOW-036 Object Timeline — business locked; runtime after stable source domains;
- FLOW-038 Procurement Agent — after 5 business decisions;
- FLOW-040 AI Audit View — business locked; runtime foundation starts in Wave 0;
- FLOW-041 Scenario/What-if — after 4 business decisions;
- FLOW-045 AI Command Center — business locked;
- FLOW-048 Resource Recommendation — after 6 business decisions.

## Object Timeline / FLOW-036

Wave 3 builds:

- canonical read-only `TimelineEvent` projection and source adapters;
- project/subproject `Временно спрян` versus WorkPackage/SMR `Блокирано`;
- `PauseImpactAssessment`, pause/resume and remobilization effect;
- operational, client and financial permission layers;
- delay overlap and causal-chain logic;
- daily, weekly, immediate and full-period versioned AI summaries;
- drill-down to original contract, report, delivery, act, invoice, payment, defect, Approval or AuditEvent.

Timeline does not write a second business fact.

## AI rules and exit criteria

- FLOW-045 is the interface/orchestrator of the same BEG Brain;
- read-only tools first;
- write tools only through draft, confirmation, permission and Approval;
- no direct MongoDB access from the LLM;
- AI cannot invent Master IDs, locations, prices or approvals;
- every tool call/action is auditable and retryable actions use idempotency keys;
- raw AI content follows R4, while official structured trails inherit R1/R2/R3;
- AI inherits the invoking user scope;
- request, tool calls, draft, human decision and execution form one correlation chain;
- secrets and PII are masked;
- Timeline summaries do not invent cause, amount, fault or approval;
- financial Timeline events point to FLOW-006 and never duplicate records.

---

# Wave 4 — External Portals and Marketplace

## FLOW scope

- FLOW-046 Client Portal — **100% Business Lock**, runtime after W0 and stable W1 approval/document/finance contracts;
- FLOW-049 Marketplace — after 8 business decisions.

## Client Portal runtime / FLOW-046

Wave 4 builds:

- one external identity model for secure links, persistent profiles and corporate client representatives;
- scoped `AccessGrant` by tenant, organization, project, resource/version, action, amount and expiry;
- OTP/MFA, session/device, expiry and revoke;
- explicit authority matrix: view, comment, technical choice, offer/act approval, contract/annex approval and financial view;
- Decision Inbox;
- allowlist client visibility and safe projection layer;
- separate internal/client threads;
- `Comment`, `Question`, `DecisionRequest` and `OfficialNotice` contracts;
- verified email/SMS ingress and exact context mapping;
- exact-version ApprovalReceipt and invalidation when a new version appears;
- client-safe AI summary and permission-filtered client Timeline;
- restricted finance view that reads FLOW-006;
- client-visible photos, progress, documents and guarantees;
- AuditEvent coverage for access, publish, read, reply, approve, reject and revoke.

## Wave 4 exit criteria

- tenant/client isolation;
- ExternalPrincipal/client-membership/AccessGrant enforcement;
- secure link and persistent-profile modes use the same permission service;
- contact does not become an approver automatically;
- exact-version written approval uses the same ApprovalReceipt from Wave 1;
- magic link expiry/revoke and new-version invalidation;
- client visibility is allowlist-based;
- no leak of margin, payroll, internal chat, subcontractor data or other tenants;
- portal communication is contextual and `read ≠ approve`;
- client finance is a restricted projection, not a second ledger;
- WorkPackage publication redacts internal margin/budget;
- marketplace calendar reservations, verified profiles, evidence-based rating and disputes are implemented later in FLOW-049;
- no automatic contractor selection;
- external access and approvals are tamper-evident and auditable.

---

# Parallel work policy

## Може да върви едновременно

- W0 permission, Master Data, File Registry, AuditEvent, tests and DR as coordinated workstreams;
- UI mockups for W1/W2/W4 against versioned API contracts;
- data migration inventory in parallel with business FLOW completion;
- FLOW-010, FLOW-012, FLOW-025, FLOW-035, FLOW-036 and FLOW-046 schema/UI contracts after agreement on shared IDs, permissions, Approval, File Registry and AuditEvent;
- FLOW-012 driver UI and purchase/delivery contracts before full offline runtime, using FLOW-037 interface contracts;
- client portal safe-view templates and UI prototypes before full runtime, without production external access;
- Interim ApprovalReceipt adapters before the full portal;
- AuditEvent schema, archive, visibility tests and critical-write inventory as coordinated W0 streams.

## Не може да върви независимо

- AI write actions before Permission/DQ/Approval/Audit;
- portal/magic link runtime before ExternalPrincipal/AccessGrant security contract;
- client publishing before allowlist visibility and forbidden-leak tests;
- free-text reply or `ОК` treated as exact-version approval;
- Marketplace before generic WorkPackage and Counterparty Master;
- FLOW-010 bank/payment guards before Payment Core and Approval;
- FLOW-012 official inventory/asset movements before canonical FLOW-009/011 IDs and custody contracts;
- FLOW-012 mobile/offline release before FLOW-037 sync/idempotency contracts;
- final Timeline projection before source schemas and permissions;
- payroll release before canonical daily reports and one payment service;
- management bonus payment before FLOW-047 calculation + Approval + FLOW-028 obligation;
- file/photo/document expansion before File Registry abstraction;
- critical feature release before AuditEvent coverage and retention rules;
- full audit export before L4 approval, masking and audit-of-audit.

---

# First programming backlog

1. ADR + schema for RoleAssignment, ExternalPrincipal, client membership and AccessGrant.
2. Master Data inventory/migration map.
3. Canonical AuditEvent + AuditEvidence and migration from `audit_logs`.
4. Append-only/hash-manifest store, R1–R6 retention, hold/disposition and L0–L5 visibility.
5. Payment idempotency and source unique indexes.
6. File Registry schema and local adapter.
7. DQ/Approval minimal models.
8. Bootstrap QA Gate repository structure.
9. Canonical project status migration.
10. Canonical daily report/downtime validation and migration.
11. ApprovalReceipt + signed-PDF/email/secure-page/chat-card adapters.
12. Counterparty/Contact Role + CommunicationThread/AISummarySnapshot + VerifiedBankAccount.
13. Counterparty financial read model and no-netting tests.
14. DocumentType/Family/Version + RequirementTemplate/Snapshot.
15. Generic WorkPackage + PackageTemplate.
16. FLOW-012 contracts: PurchaseDeliveryRequest/Line, Trip/Stop/LoadingList, DeliveryAcceptance, ResidualPriorityQueue, invoice matching and reusable-item custody.
17. FLOW-012 driver UI, QR handover, multi-stop and acceptance SLA tests; offline adapter contract with FLOW-037.
18. TimelineEvent projection + PauseImpactAssessment + source adapters.
19. Client Portal contracts: profile/membership, AccessGrant, visibility allowlist, threads/messages, Decision Inbox and client-safe projections.
20. Backup/version manifest, AuditEvent immutable copy and restore dry-run.

## Източници / сесии

- FLOW-001–049 business documents in PR #2.
- Cross-FLOW code audit, 20.07.2026.
- Claude Cross-FLOW logic audit and resolution pass, 20.07.2026.
- FLOW-010 business-close pass, 21.07.2026.
- FLOW-012 business-close pass, 24.07.2026.
- FLOW-025 business-close pass, 21.07.2026.
- FLOW-036 business-close pass, 22.07.2026.
- FLOW-040 business-close pass, 21.07.2026.
- FLOW-046 business-close pass, 23.07.2026.
# BEG_Work — Implementation Waves

> **Цел:** паралелно програмиране без нарушаване на FLOW зависимостите.  
> **Business status:** FLOW-001–050 са бизнес затворени; FLOW-018 е legacy и е погълнат от FLOW-039.  
> **Правило:** Business Lock не е Implementation Gate PASS.

# Wave 0 — Architecture Foundation

Wave 0 започва преди масово feature development.

## W0-01 — Tenancy / FLOW-050 + D-15

- Tenant Registry и database resolver;
- Tenant Guard за API, jobs, search, files, exports, AI и integrations;
- database-per-tenant;
- TenantMembership → RoleAssignment;
- per-tenant numbering, Master Data, integrations и AuditEvent;
- migration runner със `schema_version`, lock, retry, validation и rollback;
- Support/Partner Access Grants и break-glass;
- isolation test suite.

## W0-02 — Permission Service / FLOW-002

- canonical RoleAssignment;
- ExternalPrincipal и AccessGrant;
- action/module/project/location/resource/version/amount/validity scope;
- MFA/passkeys за чувствителни роли;
- migration от legacy role strings.

## W0-03 — Master Data / FLOW-032

- Master Person/Organization/Activity/Item/Asset Type/Location;
- aliases, normalization, merge и redirect history;
- per-tenant uniqueness и migration map.

## W0-04 — Audit / Lifecycle / Idempotency / FLOW-040

- canonical append-only AuditEvent;
- correction/reversal/annotation events вместо edit/delete;
- correlation/idempotency keys;
- R1–R6 retention, legal/incident hold и controlled disposition;
- hash/signed manifests, immutable archive и audit-of-audit.

## W0-05 — Payment Core / FLOW-006

- един `finance_payments` write service;
- obligations и allocations;
- source uniqueness indexes;
- reversal/correction API;
- retirement на legacy payment writers.

## W0-06 — File Registry / FLOW-016

- `files`, `file_versions`, `file_relations`, provider locations;
- mandatory customer-managed Primary Storage Provider onboarding;
- encrypted tenant credentials;
- Google Drive / Synology / S3 / on-prem adapters;
- read/write/checksum activation test;
- periodic availability/checksum scheduler;
- alarms с всички засегнати business records;
- immutable original, preview/OCR cache и no-cross-tenant links.

## W0-07 — Data Quality + Approval / FLOW-033/034

- DQ issue model със severity/blocking/owner/deadline;
- Approval request/evidence/decision/execution;
- dual approval, escalation и source links.

## W0-08 — Subscription / Billing / Entitlements / FLOW-050

- Feature Catalog, immutable Plan Version и Tenant Entitlement;
- AI Usage Ledger, budgets и add-on proration;
- client AI usage screen и 80%/100% rules;
- email/integration limits;
- Subscription/Billing state machine;
- Payment Provider Adapter и signed/idempotent webhooks;
- dunning 0/3/7;
- GRACE / RESTRICTED / SUSPENDED / SUSPENDED_CHARGEBACK;
- Trial/Demo/Partner states;
- invoice/credit-note links и no-deletion invariant.

## W0-09 — Test / Release / Environments / FLOW-042/050

- Bootstrap QA Gate v0;
- Development / Test / Staging / Production;
- common Release Manifest;
- no-private-fork enforcement;
- TAE exact-version Acceptance Receipt;
- migration/isolation/billing/environment/rollback tests.

## W0-10 — Disaster Recovery / FLOW-044

- DB PITR/backups;
- AuditEvent immutable off-site copy;
- restore scripts and integrity checks;
- per-tenant restore proof;
- quarterly full restore drill.

## W0-11 — Export / Retention / Controlled Deletion / FLOW-050

- tenant export in JSON, CSV/XLSX, PDF and manifests;
- File Registry/provider references and checksums;
- 90-day read-only retention after termination;
- legal/incident hold;
- explicit deletion Approval;
- deletion verification and signed disposition manifest;
- customer-managed originals remain outside standard deletion.

## Wave 0 exit criteria

- every request resolves one active tenant server-side;
- permissions use canonical assignments;
- customer Storage Provider onboarding and integrity checks pass;
- critical writes create one canonical AuditEvent;
- payment and billing writes are idempotent;
- files use provider-neutral IDs and tenant isolation;
- DQ/Approval foundations work;
- Release Manifest and environment gates work;
- backup/restore/export/retention/deletion are proven per tenant;
- no private fork or hidden client version exists.

---

# Wave 1 — Commercial Core

## Scope

FLOW-001, 003–008, 010 и 025:

```text
Object
→ Offer
→ Contract/Annex
→ Act
→ Invoice
→ Payment
→ Project result
```

## Key deliverables

- canonical project/subproject states;
- stable offer-line identity and versioning;
- exact-version ApprovalReceipt;
- contracts/annexes/retentions/guarantees;
- acts and remaining quantities;
- one Payment ledger;
- VerifiedBankAccount and first-payment/new-IBAN guards;
- counterparty financial read model without automatic netting;
- DocumentType/Family/Version and requirement snapshots;
- action-specific blockers and exception approvals.

## Exit criteria

- no hard delete of used commercial records;
- one payment ledger reconciles offer/contract/act/invoice/payment;
- exact-version approvals are provable;
- bank verification does not bypass payment Approval;
- client/internal communication and data visibility are isolated.

---

# Wave 2 — Field Operations and Cost Control

## Scope

FLOW-009, 011–015, 019–021, 024, 026–029, 035, 037, 039 и 047.

## Modern Field Experience — mandatory Wave 2 core

- PWA and offline-first;
- role-aware `Днес`;
- universal `СНИМАЙ / КАЖИ / СКАНИРАЙ` entry;
- voice-to-record with human confirmation;
- camera-first OCR and evidence;
- original audio/photo stored in File Registry before AI processing;
- context-only communication, comments and @mentions;
- Action Inbox;
- realtime operational push + Daily Digest;
- quick actions from notifications;
- QR-first inventory; NFC only for selected expensive assets;
- passkeys;
- basic context suggestions from object/location/supplier;
- idempotent offline sync and visible conflict handling.

## Operational deliverables

- canonical attendance and daily reports;
- side work/downtime classification;
- material requests, purchase limits and invoice matching;
- warehouse/FIFO and direct-delivery cost rules;
- logistics trips, stops, residual priority queue and acceptance SLA;
- assets/QR/custody/returns/repairs;
- subcontractor packages;
- generic WorkPackage and PackageTemplate;
- quality/defect/warranty lifecycle;
- payroll and management bonus obligations reconciled to finance.

## Exit criteria

- no report without presence/SMR/time;
- no duplicate offline writes;
- conflicts never resolve silently;
- QR scan alone does not transfer responsibility;
- unmatched invoice lines require explanation;
- reusable items always have location and one human responsible;
- original audio/photo remains available when AI extraction is disputed;
- Digital Twin Lite is not in scope.

---

# Wave 3 — AI and Decision Intelligence

## Scope

FLOW-022, 023, 030, 031, 036, 038, 040, 041, 045 и 048.

## Deliverables

- central BEG Brain tool registry;
- agent hats over the same Brain;
- AI Command Center;
- automatic offer analysis;
- Procurement Agent;
- Scenario/What-if;
- Resource Assignment recommendations;
- Object Timeline and versioned AI summaries;
- live logistics map after stable Wave 2 data;
- kiosk/shared tablet mode;
- auto-timeline summaries;
- role-based BEG Brain UI.

## Rules

- read-only tools first;
- write tools only through draft, confirmation, permission and Approval;
- no direct MongoDB access from the LLM;
- AI inherits tenant/user scope;
- all tool/action chains are auditable;
- AI never invents IDs, prices, approvals, fault or financial facts.

Live Activities and App Clips are not included; they require a later separate native decision if PWA reaches a proven limit.

---

# Wave 4 — External Portals and Marketplace

## Scope

- FLOW-046 Client Portal;
- FLOW-049 separate Marketplace product and API boundary.

## Deliverables

- secure links and persistent client profiles;
- corporate client representatives;
- scoped AccessGrant;
- allowlist client visibility;
- contextual threads and Decision Inbox;
- exact-version ApprovalReceipt;
- client-safe Timeline and restricted finance view;
- Marketplace verification, listings, matching, reservations, ratings, disputes and billing through its separate product boundary.

## Exit criteria

- no tenant/client data leakage;
- contact is not automatically an approver;
- read is not approval;
- marketplace never auto-selects a contractor;
- external actions are tamper-evident and auditable.

---

# Parallel work policy

## Can run in parallel

- Wave 0 tenancy, permissions, Master Data, AuditEvent, File Registry, Payment Core, DQ/Approval, billing, QA and DR as coordinated workstreams;
- UI prototypes against versioned contracts;
- data migration inventory;
- Wave 1/2 schema contracts after common IDs and permission rules are fixed.

## Cannot run independently

- AI write actions before Permission/DQ/Approval/Audit;
- portal runtime before ExternalPrincipal/AccessGrant;
- field release before offline/idempotency/conflict tests;
- official inventory movements before canonical item/asset/custody IDs;
- billing access changes before signed/idempotent provider events;
- deletion before export/hold/Approval/manifest;
- client-specific code branch or deployment version outside the common Release Manifest.

# First programming backlog

1. Tenant Registry + database resolver + Tenant Guard.
2. RoleAssignment / TenantMembership / ExternalPrincipal / AccessGrant.
3. Master Data inventory and migration map.
4. Canonical AuditEvent and immutable archive.
5. Payment write service and idempotency.
6. Customer-managed File Registry adapters and onboarding gate.
7. Data Quality and Approval foundations.
8. Subscription/Billing/Entitlements/AI Usage Ledger.
9. Dunning/access-state/chargeback workflow.
10. Bootstrap QA Gate and environment Release Manifest.
11. Backup/restore/export/retention/deletion proof.
12. Canonical project and daily-report migrations.
13. ApprovalReceipt and Document Control.
14. Counterparty/communication/bank verification.
15. Generic WorkPackage and PackageTemplate.
16. Modern Field Experience contracts and offline sync API.
17. Logistics/material/asset contracts.
18. Client Portal contracts.

## Sources

- FLOW-001–050 business documents in Draft PR #2.
- Cross-FLOW code and logic audits.
- FLOW-050 business-close decisions through 04.08.2026.
- Modern Field Experience, 04.08.2026.

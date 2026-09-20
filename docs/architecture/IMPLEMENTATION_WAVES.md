# BEG_Work — Implementation Waves

> **Цел:** паралелно програмиране без нарушаване на FLOW зависимостите.  
> **Business status:** FLOW-001–050 са бизнес затворени; FLOW-018 е legacy и е погълнат от FLOW-039.  
> **Правило:** Business Lock не е Implementation Gate PASS.
> **Implementation status:** синхронизиран на 13.09.2026 (WAVE-PLAN-SYNC); реалният статус по W0 items е в секция „Wave 0 — implementation status".

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

## Wave 0 — implementation status (20.09.2026)

Каноничната номерация е тази в този документ (W0-01…W0-11). Старата номерация в `06_WAVE_STATUS_DASHBOARD.md` от 05.08.2026 е отменена. Идентификаторите `W0-T01…T12` в `WAVE_0_TENANCY_FOUNDATIONS.md` са под-backlog, не отделни W0 items.

| ID | Статус | Доказателство | Оставащ дълг |
|---|---|---|---|
| W0-01 Tenancy | **CORE MERGED** | PR #3 — `app/tenancy` (registry, guard, resolver); ползва се от W0-02 пътищата | Tenant Guard не е вързан към всички legacy routes/jobs/files/search/export/AI; migration runner; support access; per-tenant numbering/integrations; пълен isolation suite |
| W0-02 Permission Service | **CORE DEPLOYED** | PR #9 → production `0b53bcd5` (12.09.2026); Synology real-Mongo/migration PASS; standard app regression без нови failures; automated + manual production smoke PASS; mode = off | W0-02 item не е затворен (решение на Крум 09.09.2026): 232 legacy проверки, 3 мигрирани, **229 остават** — миграция домейн по домейн; ExternalPrincipal/AccessGrant и MFA/passkeys не са започнати; shadow/enforce изискват отделно решение |
| W0-03 Master Data | **NOT STARTED** — next major build | — | целият обхват |
| W0-04 Audit / Lifecycle / Idempotency | **CORE MERGED** | PR #6 — `app/audit` (envelope, hash-chained store, correction/reversal/annotation, idempotency registry); ползва се от W0-02 | не покрива всички critical writes; retention enforcement, legal/incident hold, disposition, signed manifests, immutable archive, audit-of-audit → **W0-04B** |
| W0-05 Payment Core | **NOT STARTED** | legacy finance routes, без единен payment write service | целият обхват |
| W0-06 File Registry | **NOT STARTED** | legacy media uploads, без `file_id` registry | целият обхват |
| W0-07 DQ + Approval | **NOT STARTED** | — | целият обхват |
| W0-08 Subscription / Billing / Entitlements | **NOT STARTED** | legacy Stripe-mock billing, не е W0 canonical | целият обхват |
| W0-09 Test / Release / Environments | **PARTIAL — W0-09A MERGED, NOT DEPLOYED** | `ops/release` е в `main` чрез PR #14 → merge commit `fdf4d59e38fb17e9f566812d326258948a3459d7` (14.09.2026); independent re-review PASS на `e2d3d43d`, изолирана Synology валидация 172/172, committed tests 79/79 | **W0-09A не е adopt-нат в production** — на NAS-а няма `release-state/`, `DEPLOYED_COMMIT` е още `0b53bcd5` (12.09.2026); adoption/deploy изискват отделно разрешение от Крум. environments/TAE/no-fork/QA exit gate → **W0-09B** |
| W0-10 Disaster Recovery | **PARTIAL — W0-10A DONE (PASS)** | `ops/synology/atlas_backup.sh` + `atlas_restore.sh`; нощният backup работи — пропуснат е само 14.09.2026, когато NAS-ът е бил изключен | **restore е доказан на 20.09.2026**: реален нощен архив възстановен и проверен в изолирана среда — 2433 документа, 0 неуспешни, 93 колекции, 0 без `_id` индекс, tenant проверка PASS, почистване доказано, production непроменен ([отчет](../ops/W0-10A_RESTORE_PROOF_2026-09-20.md), инструмент `ops/dr/`, 22 теста). Остава **W0-10B**: PITR, off-site immutable copy, per-tenant restore, периодичен drill. Отделно и **все още отворен** стои хардуерният риск от [инцидента 13–16.09](../ops/INCIDENT_2026-09-13_NAS_THERMAL.md) — успешният restore на 780 KB не го закрива |
| W0-11 Export / Retention / Deletion | **NOT STARTED** | — | целият обхват |

„CORE MERGED/DEPLOYED" не означава, че W0 item-ът е затворен или че свързаният FLOW има Implementation Gate PASS.

## Roadmap split (без преномериране)

Каноничните W0 items запазват номерата си. За изпълнение се ползват следните под-етапи:

- **W0-09A** — Bootstrap Release / deploy / rollback foundation: общ Release Manifest, exact-version артефакт, записана deployed версия, rollback анкер, smoke gate.
- **W0-10A** — изолиран restore proof: реален backup се възстановява в non-production среда и се проверява. **Завършен на 20.09.2026 (PASS).**
- **W0-04B** — Audit lifecycle completion: retention/hold/disposition/archive/audit-of-audit и покритие на всички critical writes.
- **W0-10B** — пълен Disaster Recovery по FLOW-044/D-13.
- **W0-09B** — финален Wave 0 release/test/environment exit gate.

## Договорен ред на изпълнение след W0-02

```text
1)  WAVE-PLAN-SYNC
2)  W0-09A  Release Manifest / deploy / rollback core
3)  W0-10A  isolated restore proof
4)  W0-03   Master Data (A–E)
5)  W0-06   File Registry (A–E)
6)  W0-07   DQ + Approval
7)  W0-05   Payment Core
8)  W0-08   Billing / Entitlements
9)  W0-04B  Audit lifecycle completion
10) W0-10B  full DR
11) W0-11   Export / Retention / Deletion
12) W0-09B  full Wave 0 exit gate
```

**Статус на реда към 20.09.2026:** (1) WAVE-PLAN-SYNC — DONE; (2) W0-09A — **MERGED** (`fdf4d59e`, 14.09.2026), но **не е деплойван** в production; (3) W0-10A — **DONE, PASS** (20.09.2026): реален архив възстановен и проверен изолирано, production непроменен — [отчет](../ops/W0-10A_RESTORE_PROOF_2026-09-20.md). Следва **W0-03 Master Data**. Следващата implementation задача не започва преди това.

Една implementation задача наведнъж: код → тестове → exact SHA → Draft PR → HANDOFF → STOP. Паралелната политика по-долу важи за планиране и договори, не за едновременни implementation PR-и.

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
- delivery receipt with ordered/delivered/accepted/damaged/rejected quantities and photo evidence as File Registry `file_id` relations (FLOW-012/020/016);
- material readiness that distinguishes requested/ordered, delivered/unloaded, quantity-accepted, technically accepted and physically available at the project location for the СМР (FLOW-020/012/009);
- assets/QR/custody/returns/repairs with two-phase transfer: `PENDING_ACCEPTANCE` → `ACCEPTED` (FLOW-011);
- subcontractor packages with progress measured in КСС units: contracted/assigned vs executed vs approved-measured vs certified vs paid (FLOW-021/019, D-02);
- canonical project schedule and readiness by СМР/WorkPackage — baseline, current plan, forecast, dependencies, latest-safe action dates, proactive reminders (FLOW-027/026/045; Wave 2.1);
- generic WorkPackage and PackageTemplate;
- quality/defect/warranty lifecycle;
- payroll and management bonus obligations reconciled to finance.

## Exit criteria

- no report without presence/SMR/time;
- no duplicate offline writes;
- conflicts never resolve silently;
- QR scan alone does not transfer responsibility; custody changes only on `ACCEPTED`, a refused/problem transfer keeps history and the sender stays responsible (FLOW-011, 12.09.2026);
- ordered or delivered material is never shown as ready for work until it is accepted and physically available at the project location;
- delivery photo/GPS evidence proves the event but never replaces acceptance;
- subcontractor progress is never a subjective percentage when a measurable КСС unit exists; obligations use approved measured quantity (D-02);
- approved progress may move the schedule forecast, never the baseline; a forecast is never shown as the contractual date;
- unmatched invoice lines require explanation;
- reusable items always have location and one human responsible;
- original audio/photo remains available when AI extraction is disputed;
- Digital Twin Lite is not in scope.

## Wave 2.1 — FLOW-027 schedule / readiness foundation (planned)

Бизнес изискванията са в FLOW-027 (уточнение 12.09.2026), с вписани връзки във FLOW-011/012/020/021/026/045. Предложеният implementation договор е в **Draft PR #11** (issue #10) — не е merge-нат и не е канон до review и решение на Крум.

Правила за Wave 2.1:

- FLOW-027 е единственият source of truth за графика; готовността е изчислена проекция, не втори регистър за задачи, материали, подизпълнители или плащания;
- графикът се генерира/управлява от СМР дейностите (WorkPackage/execution package идентичност, FLOW-003/035) с потвърждение от човек;
- предстоящите СМР проверяват готовността и напомнят проактивно на отговорните хора (FLOW-026 условия, FLOW-045 целеви напомняния/ескалация, Action Inbox/Daily Digest);
- runtime кодът има predecessors: **W0-03** (материал/СМР идентичност), **W0-06** (`file_id` за снимкови доказателства), **W0-07** (блокиращи въпроси/решения/одобрения), read-only достъп до **W0-05** за плащания като предпоставка, плюс W0-01/W0-02/W0-04. Докато те липсват, всеки W2.1 PR остава feature-off и чете legacy източници само през изрично маркирани read-only адаптери.

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

> Исторически backlog от 04.08.2026. Редът на изпълнение след W0-02 е заменен от „Договорен ред на изпълнение след W0-02" в секция Wave 0 (13.09.2026); точки 1 и 2 имат merge-нато ядро (W0-01, W0-02).

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
- W0-02 production release `0b53bcd5` и smoke gate, 12.09.2026.
- Уточнения на Крум от 12.09.2026: двуфазно QR/custody приемане (FLOW-011) и управленски изисквания за график/готовност/материали/доставки/снимки/КСС (FLOW-027 и свързаните FLOW).
- WAVE-PLAN-SYNC (канонична W0 номерация, реален статус, roadmap split и договорен ред), 13.09.2026.
- W0-09A merge (PR #14 → `fdf4d59e`), 14.09.2026 — merge-нат, но не деплойван.
- INCIDENT 2026-09-13/16 — пет термични изключвания на Synology `bekr` от прегряващи M.2 NVMe кеш дискове; root cause установен, хардуерът **не е отстранен** (`docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md`), 20.09.2026.
- W0-10A restore proof — **PASS** (`docs/ops/W0-10A_RESTORE_PROOF_2026-09-20.md`), 20.09.2026.

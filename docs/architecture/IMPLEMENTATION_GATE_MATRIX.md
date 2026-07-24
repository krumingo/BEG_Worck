# BEG_Work — Implementation Gate Matrix

> **Дата:** 24.07.2026  
> **Правило:** `100% Business Lock` не означава `Implementation Gate PASS`.  
> **Последен business-close pass:** FLOW-012 е 100%; driver purchase limits, residual priority queue, QR custody, partial/damaged rules и acceptance SLA са заключени.

## Легенда

- **W0-BLOCKER** — cross-cutting foundation; започва първо.
- **REFACTOR** — има работещ код, но е в конфликт с каноничния FLOW.
- **READY-W1/W2/W3/W4** — може да се разработва в посочената вълна след predecessor-ите.
- **BUSINESS-OPEN** — остават бизнес решения; не се финализира кодът.
- **LEGACY** — не се развива самостоятелно; мигрира/поглъща се.
- **DOC/OPS** — документационен или инфраструктурен gate.

| FLOW | Business | Налична основа в кода | Implementation Gate | Критичен predecessor / действие |
|---|---:|---|---|---|
| 001 | 100% | projects CRUD, team, phases, status transitions | **REFACTOR** | FLOW-002; canonical statuses; project/subproject pause vs blocked SMR; Pause Impact; soft delete; closing guards |
| 002 | 100% | auth, JWT, single `user.role`, project-team checks | **W0-BLOCKER** | RoleAssignment + ExternalPrincipal/AccessGrant + Permission Service + migration |
| 003 | 100% | offers, lines, versions, Excel import, extra-work drafts | **REFACTOR / READY-W1** | stable Line_ID, provenance, DQ/Approval, Interim Approval Receipt, client/internal views |
| 004 | 100% | partial invoice/offer/payment foundations; subcontractor acts | **READY-W1** | FLOW-005 contract basis + canonical act domain + FLOW-006 |
| 005 | 100% | няма canonical contracts/annexes runtime | **READY-W1** | contract/annex domain, OCR intake, retention/guarantees |
| 006 | 100% | invoices, payment allocations, `finance_payments`, accounts | **W0/W1 REFACTOR** | one payment write service, obligations, idempotency, legacy retirement |
| 007 | 100% | extra-work drafts and offer creation foundation | **READY-W1** | FLOW-003 stable identity + FLOW-034 + exact-version client approval |
| 008 | 100% | P&L/full-cost/financial-result routes | **REFACTOR / READY-W1** | source map, locked card order, advance-coverage formula, read-only drill-down tests |
| 009 | 100% | warehouses, batches/FIFO, items, movements | **READY-W1** | FLOW-032 items/locations + transaction idempotency + cost recognition |
| 010 | 100% | clients, counterparties, persons/companies foundations | **REFACTOR / READY-W1 after W0/032** | Master Organization/Person migration; scoped contacts; internal/client threads; AI summary source links; ApprovalReceipt; VerifiedBankAccount; contract-scoped financial read model |
| 011 | 100% | asset items/units/custody/QR/repairs/intake | **READY-W1** | FLOW-032 asset type + FLOW-034 write-offs + File Registry |
| 012 | 100% | procurement/warehouse/mobile fragments | **READY-W2 after W0/009/011/020; mobile sync via 037** | Purchase/Delivery Request; max-price limits; residual priority queue; invoice matching; reusable-item custody; QR handover; partial/damaged state machine; acceptance SLA |
| 013 | 100% | attendance + old/new report schemas | **W0/W1 REFACTOR** | canonical presence/report schema and hard validation |
| 014 | 100% | work_reports, daily_reports, work_logs, media | **W0/W1 REFACTOR** | no report without presence/SMR/time; side-work/downtime/change flow; migration |
| 015 | 100% | dashboard, pulse, alarms, morning briefing | **READY-W2** | sources 001–014/026 stable; read-only projection tests |
| 016 | 100% | local media upload and ACL | **W0-BLOCKER** | provider-neutral File Registry, relations, versions, checksums |
| 017 | 100% | process/documentation concern | **DOC PASS** | keep CLAUDE/FLOW docs synchronized; no runtime feature gate |
| 018 | legacy | partial/old quality concept | **LEGACY** | migrate into FLOW-039; no separate implementation |
| 019 | 100% | labor-by-SMR and paid-labor services | **READY-W2** | canonical reports + downtime cost type + productive/total-efficiency KPI + FLOW-028 |
| 020 | 100% | material requests, supplier invoice intake, warehouse posting | **REFACTOR / READY-W2** | Master item, multi-allocation, request→receipt→invoice reconciliation |
| 021 | 100% | subcontractors, packages, acts, payments, performance | **REFACTOR / READY-W2** | Master counterparty, generic WorkPackage, Approval, payment idempotency |
| 022 | 100% | pricing/reporting foundations | **READY-W3** | validated historical data + marketplace signals + source timestamps |
| 023 | 100% | AI proposal, SMR analysis, pricing/calibration | **READY-W2/W3** | FLOW-032, DQ, tool framework, no demo rates in official results |
| 024 | 100% | overhead categories/costs/snapshots/allocations | **READY-W2** | canonical allocation; project-vs-firm downtime; gross cost + separate recovery |
| 025 | 100% | files exist, but no full document-control runtime | **READY-W1 after W0/016/034** | DocumentType/Family/Version; requirement templates/snapshots; action guards; exception approvals; migration |
| 026 | 100% | alarm engine/events/rules | **REFACTOR / READY-W2** | separate Alarm/DQ/Approval/Task; blocking semantics and audit |
| 027 | 100% | budget progress, expected/actual, weekly matrix | **READY-W2** | FLOW-005 timeline + FLOW-014 delay evidence + overlap logic |
| 028 | 100% | Pay Runs v3, slips, allocations, sync, audit checks | **REFACTOR / READY-W2** | canonical labor; akord quantity; management-bonus source adapters; payment idempotency |
| 029 | 100% | media upload/list/ACL | **READY-W2 after 016** | photo metadata, many relations, original/compressed/thumbnail, QR upload |
| 030 | 100% | scattered AI/OCR/proposal/briefing functions | **READY-W3** | central tool registry, permission scope, context, confirmation framework |
| 031 | 100% | business agent-шапки, no central runtime orchestration | **READY-W3** | FLOW-030 tool layer + FLOW-002 + AuditEvent |
| 032 | 100% | fragmented domain collections | **W0-BLOCKER** | Master entities, aliases, merge, migration and uniqueness |
| 033 | 100% | local checks/alarms, no central DQ router | **W0/W1 FOUNDATION** | DQ issue model, dedupe, severity/blocking, responsibility/SLA |
| 034 | 100% | няма central Approval runtime | **W0/W1 FOUNDATION** | request/evidence/decision/execution model + dual approval |
| 035 | 100% | subcontractor packages/budgets, no generic package | **READY-W2 after W0** | generic WorkPackage, versioned PackageTemplate, idempotent draft generation, canonical UI |
| 036 | 100% | scattered timestamps/events, no canonical read-only timeline service | **READY-W3 after W0/W1/W2 sources** | TimelineEvent projection; source adapters; pause/resume and blocked-work states; Pause Impact; permission layers; overlap/causal chains; versioned summaries |
| 037 | 50% | mobile bootstrap/config only | **BUSINESS-OPEN** | mobile UX, offline queue, sync, idempotency, edit rules |
| 038 | 45% | procurement foundation, no supplier RFQ agent | **BUSINESS-OPEN** | supplier registry/RFQ/parser/ranking/approval |
| 039 | 40% | assets repairs and scattered defect concepts | **BUSINESS-OPEN** | defect lifecycle, warranty calendar, responsibility, cost/rating |
| 040 | 100% | basic `audit_logs`; no canonical immutable event store | **W0-BLOCKER / FOUNDATION** | AuditEvent envelope; append-only/hash manifests; retention classes; hold/disposition; role/field visibility; audit-of-audit; migration |
| 041 | 35% | cashflow/expected-actual fragments | **BUSINESS-OPEN** | scenario catalog, assumptions, comparison UI, fact/forecast separation |
| 042 | 40% | legacy smoke script; no FLOW acceptance center | **BUSINESS-OPEN / W0** | Bootstrap QA Gate v0 now; full test schema, CI, migration tests and release linkage later |
| 043 | 100% | architecture documentation | **DOC PASS** | enforce D-01–D-14 through ADRs, lint/checklists and code review |
| 044 | 100% | no proven standby/PITR/restore implementation | **OPS-W0** | version manifest, backups, immutable copy, restore drill |
| 045 | 100% | no command-center runtime | **READY-W3 after W0** | same BEG Brain; versioned intent→data→draft→confirm→action catalog |
| 046 | 100% | no client portal runtime | **READY-W4 after W0/W1** | ExternalPrincipal/profile/membership; scoped AccessGrant; allowlist projections; context threads; message contracts; exact-version ApprovalReceipt; restricted finance/client Timeline |
| 047 | 100% | no generic managed package/bonus fund runtime | **READY-W2 after 035** | WorkPackage agreement/version + VAT-neutral bonus calculation + Approval + FLOW-028 obligation |
| 048 | 35% | resource cost model only, no assignment recommender | **BUSINESS-OPEN** | ranking/load/calendar/skill inputs/second manager/final authority |
| 049 | 40% | no marketplace runtime | **BUSINESS-OPEN** | verification, auctions, budgets, reservation, rating, disputes, billing |

---

# Gate summary

## Може да започне незабавно като Foundation Refactor

- FLOW-002 — RoleAssignment / ExternalPrincipal / Permission Service.
- FLOW-006 — Payment write service + idempotency + obligation allocation.
- FLOW-016 — File Registry / Storage Provider.
- FLOW-032 — Master Data migration foundation.
- FLOW-033/034 — DQ and Approval core.
- FLOW-040 — canonical immutable AuditEvent, retention and visibility runtime.
- FLOW-042 — Bootstrap QA Gate + acceptance/migration harness.
- FLOW-044 — backup/restore infrastructure.

## Може да се развива паралелно само зад feature flags и migration adapters

- FLOW-001, 003–012, 013–016, 019–021, 024–029, 035, 036 projection contracts, 045, 046 portal contracts/UI mockups и 047.

## Не трябва да се финализира преди оставащите бизнес решения

- FLOW-037–039, FLOW-041–042, FLOW-048 и FLOW-049.

## Release правило

Нито един FLOW получава `Implementation Gate PASS`, докато няма едновременно:

1. canonical permission enforcement;
2. source-of-truth и migration map;
3. API/tool contract;
4. positive + forbidden + correction/reversal tests;
5. AuditEvent coverage;
6. idempotency за retryable writes;
7. Data Quality / Approval връзки;
8. проверен UI за Крум;
9. rollback/restore план.

## Допълнителни условия за FLOW-010

- един Master Organization/Person модел и controlled deduplication/merge;
- role/scope/authority модел за контактите;
- отделни вътрешни и клиентски communication threads;
- versioned AI summary, source links, retention и permission masking;
- exact-version ApprovalReceipt от клиентския чат;
- VerifiedBankAccount registry и два независими verification sources;
- first-payment/new-IBAN block и invoice mismatch tests;
- разграничение между bank verification и payment approval;
- financial read model по counterparty→project→contract/package→role;
- отделни receivables/payables и тест срещу automatic netting;
- изходяща BEG фактура допуска само active verified company IBAN.

## Допълнителни условия за FLOW-012

- canonical Request, Order Line, Trip, Stop, Loading List, Delivery/Acceptance и Residual Queue модели;
- max-price basis и тестове с/без ДДС;
- mobile driver flow и offline/idempotent sync през FLOW-037;
- неизпълнен остатък остава към оригиналния ред и влиза в приоритетната опашка;
- официално cancellation/ отказване с причина и AuditEvent;
- invoice-line matching, unmatched badge и explanation/classification workflow;
- reusable-item classification, human responsible, location, return и inventory reuse;
- QR handover chain и забрана за responsibility transfer без acceptance;
- partial/missing/damaged/refused/returned state-machine tests;
- acceptance role matrix, same-day/24h SLA, escalation и no-auto-acceptance;
- multi-stop load-balance, wrong-stop prevention и approved reverse-route changes;
- integrations с FLOW-009, 011, 020, 026, 033, 034, 037 и 040.

## Допълнителни условия за FLOW-025

- one-Current constraint по document family;
- versioned requirement templates;
- immutable requirement snapshots;
- action-specific blocking tests;
- сценарий за вече настъпило, но unallocated плащане.

## Допълнителни условия за FLOW-036

- canonical read-only TimelineEvent projection и stable source links;
- project/subproject `Временно спрян` и WorkPackage/SMR `Блокирано` като различни състояния;
- Pause Impact Assessment snapshot/versioning и resume checks;
- source adapters за contract, offer, report, material, quality, finance, Approval и AuditEvent;
- financial/client/operational permission layers без data leakage;
- delay overlap и causal-chain tests;
- daily/weekly/immediate/period AI summaries със source links и version history;
- test срещу duplicate financial records и Timeline write-through;
- performance, pagination, timezone и correction propagation tests.

## Допълнителни условия за FLOW-040

- append-only store и correction events вместо edit/delete;
- hash chain или signed manifests и integrity verification;
- immutable archive + off-site backup/restore;
- R1–R6 retention class assignment и anchor tests;
- hot→archive→restore и legal/incident hold tests;
- controlled disposition със signed manifest;
- L0–L5 role/scope/field visibility и masking tests;
- audit-of-audit, export и two-person break-glass tests;
- AI request→tools→draft→human confirmation→domain execution correlation;
- rebuild на searchable index от immutable archive.

## Допълнителни условия за FLOW-046

- ExternalPrincipal, persistent client profile и corporate-representative membership model;
- scoped AccessGrant по tenant/project/resource/version/action/amount/expiry;
- OTP/MFA, link expiry/revoke, session/device и tenant-isolation tests;
- explicit contact-authority matrix и тест, че контакт ≠ automatic approver;
- allowlist client visibility и safe projection layer;
- forbidden data-leak tests за margin, payroll, internal chat, subcontractor data и други tenants;
- отделни internal/client threads и Comment/Question/DecisionRequest/OfficialNotice contracts;
- verified email/SMS ingress, exact context mapping и ambiguous-context confirmation;
- exact-version ApprovalReceipt, new-version invalidation и read≠approve tests;
- Decision Inbox, client-safe AI summary и permission-filtered client Timeline;
- restricted financial read model, който сочи към FLOW-006 и не дублира ledger;
- AuditEvent coverage за issue/use/read/reply/publish/approve/reject/revoke/denied;
- accessibility, responsive/mobile, performance, rollback/revoke и support/break-glass tests.

До пълния FLOW-042 Test Center доказателството се пази чрез Bootstrap QA Gate v0.

## Източници / сесии

- FLOW-001–049 business documents in this PR.
- Cross-FLOW code audit against `main`, 20.07.2026.
- Claude Cross-FLOW logic audit and resolution pass, 20.07.2026.
- FLOW-010 business-close pass, 21.07.2026.
- FLOW-012 business-close pass, 24.07.2026.
- FLOW-025 business-close pass, 21.07.2026.
- FLOW-036 business-close pass, 22.07.2026.
- FLOW-040 business-close pass, 21.07.2026.
- FLOW-046 business-close pass, 23.07.2026.
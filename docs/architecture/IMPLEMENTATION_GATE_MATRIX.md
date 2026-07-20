# BEG_Work — Implementation Gate Matrix

> **Дата:** 20.07.2026  
> **Правило:** `100% Business Lock` не означава `Implementation Gate PASS`.  
> **Logic-audit pass:** FLOW-035 и FLOW-045 са 100%; FLOW-046 е 80% с 3 решения; Interim Approval Receipt е допустим преди пълния портал.

## Легенда

- **W0-BLOCKER** — cross-cutting foundation; започва първо.
- **REFACTOR** — има работещ код, но е в конфликт с каноничния FLOW.
- **READY-W1/W2/W3** — може да се разработва в посочената вълна след predecessor-ите.
- **BUSINESS-OPEN** — остават бизнес решения; не се финализира кодът.
- **LEGACY** — не се развива самостоятелно; мигрира/поглъща се.
- **DOC/OPS** — документационен или инфраструктурен gate.

| FLOW | Business | Налична основа в кода | Implementation Gate | Критичен predecessor / действие |
|---|---:|---|---|---|
| 001 | 100% | projects CRUD, team, phases, status transitions | **REFACTOR** | FLOW-002; canonical statuses; soft delete; closing guards |
| 002 | 100% | auth, JWT, single `user.role`, project-team checks | **W0-BLOCKER** | RoleAssignment + ExternalPrincipal/AccessGrant + Permission Service + migration |
| 003 | 100% | offers, lines, versions, Excel import, extra-work drafts | **REFACTOR / READY-W1** | stable Line_ID, provenance, DQ/Approval, Interim Approval Receipt, client/internal views |
| 004 | 100% | partial invoice/offer/payment foundations; subcontractor acts | **READY-W1** | FLOW-005 contract basis + canonical act domain + FLOW-006 |
| 005 | 100% | няма canonical contracts/annexes runtime | **READY-W1** | contract/annex domain, OCR intake, retention/guarantees |
| 006 | 100% | invoices, payment allocations, `finance_payments`, accounts | **W0/W1 REFACTOR** | one payment write service, obligations, idempotency, legacy retirement |
| 007 | 100% | extra-work drafts and offer creation foundation | **READY-W1** | FLOW-003 stable identity + FLOW-034 + exact-version client approval |
| 008 | 100% | P&L/full-cost/financial-result routes | **REFACTOR / READY-W1** | source map, locked card order, advance-coverage formula, read-only drill-down tests |
| 009 | 100% | warehouses, batches/FIFO, items, movements | **READY-W1** | FLOW-032 items/locations + transaction idempotency + cost recognition |
| 010 | 70% | clients, counterparties, persons/companies foundations | **BUSINESS-OPEN** | FLOW-032 org/person consolidation + bank-change approval |
| 011 | 100% | asset items/units/custody/QR/repairs/intake | **READY-W1** | FLOW-032 asset type + FLOW-034 write-offs + File Registry |
| 012 | 70% | procurement/warehouse/mobile fragments | **BUSINESS-OPEN** | driver UX, QR custody chain, partial/damaged delivery, acceptance SLA |
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
| 025 | 80% | files exist, but no full document-control domain | **BUSINESS-OPEN** | close 2 document/checklist matrices; FLOW-016 first |
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
| 036 | 55% | scattered timestamps/events, no read-only timeline service | **BUSINESS-OPEN** | event catalog, filters, AI summaries, source links |
| 037 | 50% | mobile bootstrap/config only | **BUSINESS-OPEN** | mobile UX, offline queue, sync, idempotency, edit rules |
| 038 | 45% | procurement foundation, no supplier RFQ agent | **BUSINESS-OPEN** | supplier registry/RFQ/parser/ranking/approval |
| 039 | 40% | assets repairs and scattered defect concepts | **BUSINESS-OPEN** | defect lifecycle, warranty calendar, responsibility, cost/rating |
| 040 | 65% | basic `audit_logs` | **BUSINESS-OPEN / W0** | AuditEvent envelope, retention/visibility, mandatory coverage |
| 041 | 35% | cashflow/expected-actual fragments | **BUSINESS-OPEN** | scenario catalog, assumptions, comparison UI, fact/forecast separation |
| 042 | 40% | legacy smoke script; no FLOW acceptance center | **BUSINESS-OPEN / W0** | Bootstrap QA Gate v0 now; full test schema, CI, migration tests and release linkage later |
| 043 | 100% | architecture documentation | **DOC PASS** | enforce D-01–D-14 through ADRs, lint/checklists and code review |
| 044 | 100% | no proven standby/PITR/restore implementation | **OPS-W0** | version manifest, backups, immutable copy, restore drill |
| 045 | 100% | no command-center runtime | **READY-W3 after W0** | same BEG Brain; versioned intent→data→draft→confirm→action catalog |
| 046 | 80% | no client portal runtime | **BUSINESS-OPEN** | 3 decisions; ExternalPrincipal/AccessGrant; portal identity/visibility/communication. Interim Receipt allows Wave 1 approval |
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
- FLOW-040 — AuditEvent envelope.
- FLOW-042 — Bootstrap QA Gate + acceptance/migration harness.
- FLOW-044 — backup/restore infrastructure.

## Може да се развива паралелно само зад feature flags и migration adapters

- FLOW-001, 003–009, 011, 013–016, 019–021, 024, 026–029, 035, 045 и 047.

## Не трябва да се финализира преди оставащите бизнес решения

- FLOW-010, 012, 025, 036–042, 046, 048 и 049.

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

До пълния FLOW-042 Test Center доказателството се пази чрез Bootstrap QA Gate v0.

## Източници / сесии

- FLOW-001–049 business documents in this PR.
- Cross-FLOW code audit against `main`, 20.07.2026.
- Claude Cross-FLOW logic audit and resolution pass, 20.07.2026.

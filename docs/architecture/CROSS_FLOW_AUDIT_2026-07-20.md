# BEG_Work — Cross-FLOW Implementation Audit

> **Дата:** 20.07.2026  
> **Обхват:** FLOW-001–049 срещу текущия `main` код  
> **Цел:** да отдели Business Lock от реалната готовност за програмиране и release  
> **Статус:** работен архитектурен одит; не променя заключената бизнес логика

## Проверени кодови зони

- `backend/server.py` — регистрирани routers и MongoDB indexes.
- `backend/app/constants.py` — роли, модули и планове.
- `backend/app/deps/auth.py` и `backend/app/routes/auth.py` — auth, role и project access.
- `backend/app/routes/projects.py` — project model, status transitions и delete.
- `backend/app/routes/offers.py`, `offer_versions.py`, `extra_works.py` — offer/version/change foundation.
- `backend/app/routes/finance.py`, `pay_runs.py`, `subcontractors.py` и `services/payroll_sync.py` — cash/payment/payroll/subcontractor flows.
- `backend/app/routes/daily_reports.py` и attendance routes — присъствие и труд.
- `backend/app/routes/procurement.py`, warehouse routes и materials routes — материали и procurement.
- `backend/app/routes/media.py` — файлове/снимки и ACL.
- `backend/app/routes/mobile.py` — mobile configuration.
- `backend/app/routes/alarms.py` — аларми.
- `backend_test.py` — наличният общ API smoke test.

## Силни основи в кода

1. Backend-ът вече е модулен FastAPI проект с отделни route модули.
2. Има работещи ядра за projects, offers, finance, attendance, payroll, warehouse, assets, procurement, subcontractors, alarms и reporting.
3. `finance_payments` вече се използва като основен cash/bank регистър от payroll и subcontractor payments.
4. Има snapshots за offer versions, Pay Run versions и audit records.
5. Има проектен scope чрез `org_id`, `project_id` и project-team checks в много routes.
6. Има начални Data Quality проверки в отделни модули: payroll audit, duplicate guards, over-allocation и overpayment guards.

---

# Блокиращи и високорискови находки

## IG-01 — BLOCKING — Ролевият модел не съответства на FLOW-002

**Код:** `users.role` е едно поле; JWT и guards използват една роля. `ROLES` е фиксиран списък.  
**Бизнес правило:** един човек има много `RoleAssignment` записи с scope по tenant, обект и модул.

**Риск:** човек, който е Site Manager на един обект и Viewer/Снабдител на друг, не може да бъде моделиран коректно. Всички последващи права, Approval Center и AI tools стъпват върху непълен модел.

**Решение преди feature work:**
- `role_assignments` collection/model;
- central permission service;
- permission checks по action + module + scope;
- миграция от `users.role`;
- временно compatibility поле, но не source of truth.

## IG-02 — BLOCKING — Project status machine и hard delete са в конфликт с FLOW-001/043

**Код:** статусите са `Draft/Active/Paused/Stopped/Completed/Cancelled/Overhead/Archived/Finished`; hard delete премахва project/team/phases, ако няма child project.  
**Бизнес правило:** `Чернова/Офериране/Договорен/Активен/Временно спрян/Приключен технически/Приключен финансово/Гаранционен/Архивиран/Отказан`; използван обект не се изтрива.

**Риск:** грешни преходи, загубена история и orphan records.

**Решение:** canonical status enum + transition service + usage guard + archive/reopen + migration map.

## IG-03 — BLOCKING — Master Data е фрагментиран

**Код:** паралелни collections за `clients`, `counterparties`, `subcontractors`, `persons`, `companies`, `users`, `items`, activity catalog и asset types. EIK index е non-unique и дубликатите се проверяват ръчно.

**Бизнес правило:** един Master ID за човек, организация, СМР, материал, asset type и location.

**Риск:** двойни контрагенти, различни имена на един материал, разпилени финансови истории и невъзможен надежден BEG Brain.

**Решение:** Master records + aliases + role/capability flags + merge history + migration map.

## IG-04 — BLOCKING — FLOW-016 File Registry още не съществува като provider-neutral слой

**Код:** `media.py` записва в `/app/backend/uploads`, допуска само image types и пази един `context_type/context_id`; link операцията заменя текущата връзка.

**Бизнес правило:** един `file_id`, много relations, versions, immutable original, provider adapters (Synology/Google Drive/S3/on-prem), backup location и checksum.

**Риск:** загуба при redeploy, невъзможно multi-link използване, няма document family/versioning и миграция между providers.

**Решение:** `files`, `file_versions`, `file_relations`, `storage_locations` + `StorageProvider` interface; legacy media migration.

## IG-05 — BLOCKING — FLOW-033 и FLOW-034 нямат централен runtime модул

**Код:** има alarms, missing-SMR и локални audit checks, но няма регистрирани routers за общ Data Quality Center и Approval Center.

**Риск:** всеки модул решава грешки и approvals по различен начин; няма единна ескалация, evidence checklist или `Approved != Executed`.

**Решение:** общи domain services и collections преди нови AI write actions.

## IG-06 — BLOCKING — Daily Report invariants не са наложени

**Код:** `smr_id` е optional; допуска се entry с 0 часа и описание; attendance conflict е warning; няма create-time block за липсващо присъствие; паралелно съществуват old и new report schemas.

**Бизнес правило:** отчет без присъствие, СМР и време е забранен; само Admin може backdate; одобреният отчет създава официален труд.

**Риск:** неверен labor budget, payroll и P&L.

**Решение:** един canonical report schema + validation service + migration + block rules + explicit admin backdate workflow.

## IG-07 — HIGH — Payment ledger foundation е добра, но idempotency и obligation separation не са завършени

**Код:** Pay Run и subcontractor payment записват cash movement в `finance_payments`; invoices използват allocations. Има отделни domain payment records и частични legacy mirrors.

**Риск:** повторен `mark-paid`, retry или интеграционен timeout може да създаде второ cash movement; част от old collections още съществуват.

**Решение:**
- mandatory `idempotency_key`/source unique index;
- `obligation_id` + `payment_id` + allocations;
- one write service for `finance_payments`;
- migration/retirement list for legacy payment collections.

## IG-08 — HIGH — AuditEvent е прекалено слаб за заключената архитектура

**Код:** `audit_logs` пази action/entity/changes/timestamp, но не гарантира before/after, reason, actor type, correlation/request ID, source FLOW, approval, execution status или immutable policy. Някои write routes не логват.

**Риск:** невъзможно надеждно възстановяване кой и защо е променил критичен запис.

**Решение:** общ AuditEvent envelope и middleware/domain helper; coverage test за критичните writes.

## IG-09 — HIGH — Offer line identity и versions не са напълно canonical

**Код:** при update на lines се генерират нови UUID за всички редове; има snapshots при send, но няма стабилен `Line_ID` през versions и source-field provenance.

**Риск:** невъзможно надеждно сравнение added/changed/replaced/removed и безопасен Excel round-trip.

**Решение:** stable line identity, explicit version family, replacement graph, source provenance и publish gate.

## IG-10 — HIGH — Contract/Annex domain липсва

**Код:** няма регистриран contracts/annexes router в app assembly.

**Риск:** offer acceptance, fixed-price/re-measurement, retention, bank guarantee, contractual timeline и annex price changes не могат да бъдат source of truth.

**Решение:** contract basis domain преди FLOW-005-dependent automation.

## IG-11 — HIGH — Procurement flow е foundation, но не следва Master materials и multi-allocation правилата

**Код:** material request lines са текстови; `from-offer` използва activity name/qty като material line; supplier invoice съществува отделно; upload е локален; permissions са вързани към M2.

**Риск:** неправилни заявки, дублирани material identities, липса на разпределение към няколко обекта/складове и двойно признаване на разход.

**Решение:** Master item IDs, request-line/receipt/invoice-line allocation model, direct-vs-stock cost recognition и central approval.

## IG-12 — HIGH — Alarm semantics не покриват blocking/Data Quality модела

**Код:** severity = info/warning/critical; alarm може да бъде acknowledge/resolve; няма `Problem/Blocking`, responsibility, deadline/escalation и AuditEvent за всяко действие.

**Риск:** „видяно“ може да се обърка с „решено“ и опасна стъпка да продължи.

**Решение:** alarm vs DQ vs approval vs task separation.

## IG-13 — HIGH — Mobile е configuration API, не Offline Field App

**Код:** bootstrap/view-config/role fields/actions; няма local queue, idempotency key, sync state, conflict resolution или attachment retry.

**Риск:** FLOW-037 не може да гарантира работа без интернет.

**Решение:** offline command envelope + sync API + conflict rules + device/session metadata.

## IG-14 — HIGH — Няма общ Work Package model

**Код:** има subcontractor packages и resource cost model, но няма един общ package за internal manager / own crew / subcontractor / mixed execution.

**Риск:** FLOW-035/047/048/049 ще създадат паралелни модели.

**Решение:** generic WorkPackage + execution model + agreement/assignment layers.

## IG-15 — HIGH — Няма централен BEG Brain tool framework

**Код:** има AI proposal, OCR, calibration и morning briefing функции, но няма един tool registry с permission checks, confirmation-before-action, context, open questions и conversation orchestration.

**Риск:** AI функции ще имат различни правила и директни writes.

**Решение:** tool contracts, read/write classes, confirmation tokens, actor scope и AuditEvent.

## IG-16 — HIGH — Client Portal и verified approvals липсват

Няма runtime foundation за magic links, exact-version approval receipt, client decision inbox и restricted financial view.

## IG-17 — HIGH — Disaster Recovery е Business Lock, но не е доказан implementation

Няма code/repo evidence за standby, PITR, immutable off-site copy, restore scripts, version manifest и periodic restore tests.

## IG-18 — HIGH — Тестовата рамка не е FLOW acceptance framework

`backend_test.py` е стар smoke script с hard-coded preview URL и credentials; тества single-role CRUD и hard delete. Не покрива locked invariants, migrations, idempotency, DQ/Approval и forbidden scenarios.

## IG-19 — BLOCKING SECURITY — небезопасни production defaults

- JWT има fallback `dev-secret-key`.
- CORS default е `*` с credentials.
- част от destructive routes правят hard delete.
- права се проверяват ad hoc по role string.

Тези настройки блокират production readiness.

## IG-20 — HIGH — Parallel legacy schemas/collections

Кодът изрично поддържа old/new daily report schemas и payroll mirrors; има няколко client/counterparty models и old/new finance readers.

**Риск:** една и съща стойност може да бъде прочетена от различен source според екрана.

**Решение:** Source-of-Truth Migration Map с owner, read cutoff, write cutoff и removal release.

---

# Cross-FLOW dependency conclusions

## Foundation blockers, които трябва да се решат първо

1. FLOW-002 — RoleAssignment / Permission Service.
2. FLOW-032 — Master Data consolidation.
3. FLOW-040/043 — AuditEvent + soft-delete + idempotency envelope.
4. FLOW-016 — File Registry / Storage Provider abstraction.
5. FLOW-033/034 — Data Quality + Approval runtime foundation.
6. FLOW-006 — един payment write service и source-unique guards.
7. FLOW-042 — acceptance test framework и migration gates.

## След тези основи могат безопасно да се доизграждат

- Project / Offer / Contract / Acts / Finance.
- Attendance / Daily Reports / Payroll.
- Inventory / Materials / Logistics / Assets.
- Subcontractor and generic Work Packages.
- BEG Brain and external portals.

## Забранено преди foundation refactor

- AI write autonomy.
- Client verified approvals, които директно активират СМР.
- Marketplace assignment/payment automation.
- автоматично material posting от OCR.
- production release с current role/security/storage defaults.

---

# Одитен извод

Business документацията вече е значително по-зряла от runtime архитектурата. Това е полезно: не трябва да се изхвърля съществуващият код, а да се запази работещата domain логика и да се постави върху общите foundation services. Правилният следващ програмен етап е **Wave 0 — Architecture Foundation Refactor**, а не паралелно добавяне на още независими feature modules.

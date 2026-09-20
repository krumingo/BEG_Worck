# BEG_Work — Табло за изпълнение

> Актуално към: 20.09.2026 (NAS инцидент — W0-10A спрян)  
> Статус на документацията: FLOW-001–050 Business Lock; уточнения на Крум от 12.09.2026 са вписани във FLOW-011/012/020/021/026/027/045  
> Каноничната W0 номерация е в `docs/architecture/IMPLEMENTATION_WAVES.md`. Старата номерация на това табло от 05.08.2026 (12 точки с разменени Permission/Tenant и отделни QA/DR/Retention items) е **отменена**.  
> Production: `0b53bcd5b977ee27de8d4cee363fed41dd897482` (Merge PR #9), `PERMISSION_SERVICE_MODE` = off  
> Следващ етап: **БЛОКИРАН** — W0-09A е merge-нат (`fdf4d59e`, PR #14, 14.09.2026), но **не е деплойван**; W0-10A — инструментът е готов и тестван (`ops/dr/`), чака прогон на NAS-а; отделно остава отворен хардуерният риск от прегряващите M.2 кеш дискове (`docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md`)

## 1. Общ статус

| Показател | Стойност |
|---|---:|
| Общо FLOW-ове | 50 |
| Business Lock | 49 |
| Legacy | 1 — FLOW-018 → FLOW-039 |
| Активни незавършени FLOW-ове | 0 |
| Оставащи бизнес решения | 0 |
| Implementation Gate PASS (цял FLOW) | 0 |
| Wave 0 items с merge-нато ядро | 3 — W0-01, W0-02, W0-04 |
| Wave 0 items в production | W0-02 core (deploy 12.09.2026, manual smoke PASS); W0-01/W0-04 foundation код е част от същия build |

## 2. Wave 0 — реален статус по каноничната номерация

Легенда: **CORE MERGED** = foundation кодът е в `main`, но W0 item-ът не е затворен; **CORE DEPLOYED** = CORE MERGED + в production; **NOT STARTED** = няма W0 код в `main`; **PARTIAL** = има частични, нефундаментни артефакти.

| ID | Работен поток (FLOW) | Статус | Доказателство | Какво остава |
|---|---|---|---|---|
| W0-01 | Tenancy / D-15 / FLOW-050 | **CORE MERGED** | PR #3 (`app/tenancy`: registry, guard, resolver); ползва се от W0-02 пътищата (`deps/auth`, `permissions/*`, `routes/auth`, `activity_budgets`, `assets_intake_pending`) | Tenant Guard не е вързан към всички legacy routes/jobs/files/search/export/AI; migration runner, support access, per-tenant numbering/integrations, пълен isolation suite |
| W0-02 | Permission Service / FLOW-002 | **CORE DEPLOYED** | PR #9 → `0b53bcd5`; Synology real-Mongo 54 / mock 111 / migration PASS; standard app regression 0 нови failures; production deploy + automated smoke + manual login/dashboard smoke PASS (12.09.2026) | **W0-02 item НЕ е затворен** (решение на Крум 09.09.2026: не се затваря, докато има route, който заобикаля Permission Service). Инвентар в `main`: **232 legacy проверки, 3 мигрирани, 229 остават** (`backend/scripts/w0_02_permission_inventory.py`). Mode остава off; shadow/enforce изискват отделно решение. ExternalPrincipal/AccessGrant, MFA/passkeys — не са започнати |
| W0-03 | Master Data / FLOW-032 | **NOT STARTED — NEXT MAJOR BUILD** | няма `app/master_data` | целият обхват (A–E) |
| W0-04 | Audit / Lifecycle / Idempotency / FLOW-040 | **CORE MERGED** | PR #6 (`app/audit`: envelope, store с hash chain, correction/reversal/annotation, idempotency registry); ползва се от W0-02 permission audit/sync/workflow | Не покрива всички critical writes; R1–R6 retention enforcement, legal/incident hold, controlled disposition, signed manifests, immutable archive, audit-of-audit — **W0-04B** |
| W0-05 | Payment Core / FLOW-006 | **NOT STARTED** | няма единен payment write service (legacy `routes/finance.py` съществува) | целият обхват |
| W0-06 | File Registry / FLOW-016 | **NOT STARTED** | няма `file_id` registry (legacy `routes/media.py`, локален uploads път) | целият обхват (A–E), customer-managed provider onboarding |
| W0-07 | Data Quality + Approval / FLOW-033/034 | **NOT STARTED** | няма DQ/Approval runtime | целият обхват |
| W0-08 | Subscription / Billing / Entitlements / FLOW-050 | **NOT STARTED** | legacy `routes/billing.py` (Stripe mock), не е W0 canonical | целият обхват |
| W0-09 | Test / Release / Environments / FLOW-042/050 | **PARTIAL — W0-09A MERGED, NOT DEPLOYED** | `ops/release` (build от git обекти, adopt/deploy/rollback/retention) е в `main` чрез PR #14 → `fdf4d59e38fb17e9f566812d326258948a3459d7` (14.09.2026); independent re-review PASS на `e2d3d43d`, изолирана Synology валидация 172/172, committed tests 79/79 | **не е adopt-нат в production** — няма `release-state/` на NAS-а, `DEPLOYED_COMMIT` = `0b53bcd5`; adoption/deploy само с изрично разрешение на Крум. environments/TAE/no-fork/пълен QA gate — **W0-09B** |
| W0-10 | Disaster Recovery / FLOW-044 | **PARTIAL — W0-10A READY TO RUN** | `ops/synology/atlas_backup.sh` + `atlas_restore.sh` (PR #4/#5); нощен backup 03:10 работи, `gzip -t` OK, ротация 14 дни; **пропуснат backup за 14.09.2026** — NAS-ът е бил изключен | **Restore proof още липсва** — инструментът е разработен и тестван (`ops/dr/`, 21 теста), но прогонът на NAS-а не е изпълнен. Пуска се от Крум, с температурна граница заради отворения хардуерен риск (`docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md`); PITR, off-site immutable copy, per-tenant restore, тримесечен drill — **W0-10B** |
| W0-11 | Export / Retention / Controlled Deletion / FLOW-050 | **NOT STARTED** | — | целият обхват |

## 3. Roadmap split — без преномериране на каноничните W0 items

| Под-етап | Родител | Обхват | Кога |
|---|---|---|---|
| **W0-09A** | W0-09 | Bootstrap Release Manifest, exact-version deploy, rollback, deployed-version запис, smoke gate | **MERGED 14.09.2026** (`fdf4d59e`, PR #14) — не е деплойван |
| **W0-10A** | W0-10 | изолиран restore proof на реален backup в non-production среда | **ИНСТРУМЕНТЪТ Е ГОТОВ** (`ops/dr/`) — чака прогон на NAS-а |
| **W0-04B** | W0-04 | Audit lifecycle completion: retention/hold/disposition/archive/audit-of-audit, покритие на всички critical writes | по-късно |
| **W0-10B** | W0-10 | пълен DR: PITR, off-site immutable copy, per-tenant restore, drill | по-късно |
| **W0-09B** | W0-09 | финален Wave 0 release/test/environment exit gate | последен в Wave 0 |

## 4. Договорен ред на изпълнение след W0-02

```text
1)  WAVE-PLAN-SYNC                      (тази документационна задача)
2)  W0-09A  Release Manifest / deploy / rollback core
3)  W0-10A  изолиран restore proof
4)  W0-03   Master Data (A–E)
5)  W0-06   File Registry (A–E)
6)  W0-07   DQ + Approval
7)  W0-05   Payment Core
8)  W0-08   Billing / Entitlements
9)  W0-04B  Audit lifecycle completion
10) W0-10B  пълен DR
11) W0-11   Export / Retention / Deletion
12) W0-09B  пълен Wave 0 exit gate
```

Правило: една implementation задача наведнъж — код → тестове → exact SHA → Draft PR → HANDOFF → STOP.

Wave 2.1 (FLOW-027 график/готовност) е **планирана** — договорът е в Draft PR #11 и не е merge-нат; runtime кодът ѝ зависи от W0-03, W0-06, W0-07 и read-only достъп до W0-05 (виж `IMPLEMENTATION_WAVES.md`).

## 5. Wave 0 блокиращи критерии

Wave 0 не приключва, докато не са доказани:

- server-side active tenant resolution;
- cross-tenant read/write denial за API, files, search, export и AI;
- membership-scoped RoleAssignments и **нито един protected route извън Permission Service**;
- migration runner с per-tenant version/result;
- единен append-only AuditEvent за всички critical writes;
- idempotent critical writes;
- единен Payment ledger;
- customer-managed Storage Provider activation test;
- canonical DQ/Approval runtime;
- signed/idempotent billing webhooks;
- environment-specific Release Manifest;
- per-tenant backup/restore/export — с реално изпълнен restore;
- billing state никога да не стартира deletion;
- retention/hold/Approval/disposition manifest tests.

## 6. Рискове, които да не се допускат

| Риск | Контрол |
|---|---|
| Разработка на функции преди нужните foundations | Gate Matrix + predecessor gate във всеки PR |
| Втори payment/file/audit/schedule регистър | Source-of-truth review преди код |
| Shared operational records между фирми | Tenant isolation tests |
| Private Enterprise fork | Common code + Release Manifest + FLOW-043 exception rule |
| Secrets в frontend/Git | Server-side encrypted credentials и secret scanning |
| AI write без контрол | Draft → Confirm → Permission → Approval → Domain service |
| Offline дубликати | idempotency keys + conflict review |
| Автоматично изтриване при неплащане | Отделен termination/retention/deletion state machine |
| Deploy без записана версия | W0-09A: exact-version артефакт + deployed-version запис + rollback анкер |
| Backup без доказан restore | W0-10A преди W0-03 — инструментът е готов, чака прогон; restore остава недоказан дотогава |
| Отговорност, прехвърлена само със сканиране | FLOW-011: двуфазно предаване, custody се сменя само при `ACCEPTED` |

## 7. Производствени релийзи

| Дата | Версия | Съдържание | Доказателство |
|---|---|---|---|
| 12.09.2026 | `0b53bcd5b977ee27de8d4cee363fed41dd897482` | W0-02 core (Merge PR #9), mode off, без production migration | automated smoke PASS + manual login/dashboard smoke PASS; rollback анкер към `48e4a108` запазен |

> От 12.09.2026 насам **няма нов production релийз**. W0-09A (`fdf4d59e`, 14.09.2026) е merge-нат в `main`, но не е деплойван: production продължава да работи `0b53bcd5` с `PERMISSION_SERVICE_MODE` = off.

## 8. Канонични връзки

- `CLAUDE.md`
- `docs/flows/README.md`
- `docs/project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md`
- `docs/project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md`
- `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`
- `docs/architecture/IMPLEMENTATION_WAVES.md`
- `docs/architecture/WAVE_0_TENANCY_FOUNDATIONS.md`
- `docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md`

# BEG_Work — Project Canon Index

> Дата: 17.10.2026
> Статус: **ЧЕРНОВА — чака одобрение от Крум** (виж `RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`, решения Р1–Р8)
> Цел: една начална страница за Claude, Codex и ChatGPT, за да не се гадае кой от 117-те .md файла е важен.

## 1. Йерархия при конфликт

```text
1. Решения на Крум (записани в канона)
2. FLOW-001…050 + FLOW-043 / Decision Register (D-01…D-15)  ← бизнес правила
3. Master Recovery & FLOW Integration Plan                 ← само ред на изпълнение
4. Implementation Gate Matrix + Implementation Waves        ← зависимости и гейтове
5. CLAUDE.md (правила за агентите)
6. Архитектурни решения (TENANCY_MODEL, FLOW_050_*, MODERN_FIELD…)
7. Одити, recovery seeds, история, legacy
```

Правила:
- Документ от по-долно ниво **никога** не променя бизнес правило от ниво 2. При конфликт работата спира и се съгласува.
- Плановете (ниво 3) решават **кога**, FLOW (ниво 2) решава **какво**.
- Одитните находки са AUD-xxx и живеят само в `docs/audits/`. D-xx е само за архитектурни решения.
- Статусът се води **само** в `06_WAVE_STATUS_DASHBOARD.md`. Останалите документи сочат към него.

## 2. Задължителни за четене преди работа

| # | Документ | Тип | Приоритет | За какво | Кой чете | Актуален? | Замества |
|---|---|---|---|---|---|---|---|
| 1 | `CLAUDE.md` | правила за агенти | 5 | правила за разработка, coding protocol, DoD | всички агенти | **частично** — v15 (05.08); §13 и §18 са в конфликт с плана → v16 | — |
| 2 | `docs/architecture/MASTER_RECOVERY_AND_FLOW_INTEGRATION_PLAN_2026-10-17.md` | план | 3 | ред: оздравяване → интеграция → пилот | всички | **чака merge** (Draft PR #57); нужни са допълнения | — |
| 3 | `docs/flows/README.md` | индекс FLOW | 2 | индекс на FLOW-001…050 | всички | да (13.09) | — |
| 4 | `docs/project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md` | регистър | 2 | статус на FLOW-001…050 | всички | **частично** — „next step W0-09A“ е остаряло | — |
| 5 | `docs/project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md` | регистър | 2 | D-01…D-15 (огледало на FLOW-043) | всички | да | — |
| 6 | `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` | гейтове | 4 | какво може да се програмира и при какви зависимости | Claude, Codex | **не** — статус към 20.09 | — |
| 7 | `docs/architecture/IMPLEMENTATION_WAVES.md` | вълни | 4 | каноничната номерация W0-01…W0-11 | Claude, Codex | **частично** — статус към 21.09 | номерацията от 05.08 |
| 8 | `docs/project-recovery/2026-07-20/06_WAVE_STATUS_DASHBOARD.md` | статус | 4 | **единственият** източник на текущ статус | всички, Крум | **не** — 21.09; W0-03C/D/E и W0-06 са изостанали | — |
| 9 | `docs/architecture/README.md` | индекс | 4 | архитектурен индекс | всички | **частично** — W0-03 статусът е стар; липсват ops/ и W0-03* | — |
| 10 | `docs/architecture/PROJECT_CANON_INDEX.md` | индекс | 4 | този документ | всички | чернова | — |

## 3. Бизнес канон — FLOW-001…050 (ниво 2)

Всички са в `docs/flows/`. Статус: **100% Business Lock**, Implementation Gate: **не е PASS** за нито един.

| FLOW | Тема | Последна проверка | Бележка |
|---|---|---|---|
| 001 | Обекти / клиенти / структура | 22.07 | |
| 002 | Потребители / роли / права | 20.07 | AUD-025 |
| 003 | Оферта / СМР / Excel-КСС | 20.07 | |
| 004 | Оферта → Акт → Остатък → Прогноза | 20.07 | |
| 005 | Договори / анекси | 20.07 | |
| 006 | Фактури / аванси / плащания / ДДС | 20.07 | единственият Payment ledger; AUD-043 |
| 007 | Допълнителни СМР | 20.07 | |
| 008 | Приходи / разходи / печалба | 20.07 | |
| 009 | Склад / движения | 20.07 | |
| 010 | Клиенти / контрагенти | 21.07 | |
| 011 | Инструменти / машини / QR | **12.09** | двуфазно предаване |
| 012 | Логистика / доставки | **12.09** | close документът от 24.07 е изостанал |
| 013 | Работници / присъствие | 20.07 | |
| 014 | Дневни отчети / снимки | 20.07 | |
| 015 | Dashboard / справки / аларми | 20.07 | |
| 016 | File Registry | 03.08 | W0-BLOCKER |
| 017 | GitHub / агенти / контрол | 20.07 | процес; засегнат от Р1 |
| 018 | Quality (legacy) | 20.07 | **LEGACY → FLOW-039** |
| 019 | СМР / труд / производителност | 20.07 | |
| 020 | Материали / заявки / доставки | **12.09** | |
| 021 | Подизпълнители / бригади | **12.09** | |
| 022 | Цени труд | 20.07 | |
| 023 | Автоматично офериране | 20.07 | |
| 024 | Режийни | 20.07 | |
| 025 | Договорни документи / версии | 21.07 | |
| 026 | Аларми риск / загуба / кеш | **12.09** | |
| 027 | График / прогрес | **12.09** | гръбнак (план, срез 5.2) |
| 028 | Заплати / Pay Run | 20.07 | AUD-023, AUD-043 |
| 029 | Архив снимки / видео | 20.07 | |
| 030 | BEG Brain | 20.07 | |
| 031 | AI агент роли | 20.07 | |
| 032 | Master Data | 20.07 | W0-03 |
| 033 | Data Quality Center | 20.07 | W0-07 |
| 034 | Approval Center | 20.07 | W0-07 |
| 035 | Work Package Engine | 20.07 | |
| 036 | Object Timeline | 22.07 | |
| 037 | Mobile Field App | 25.07 | |
| 038 | Procurement Agent | 28.07 | |
| 039 | Quality / Defects / Warranty | 28.07 | наследник на 018 |
| 040 | AuditEvent / AI Audit Log | 21.07 | W0-04 |
| 041 | Scenario / What-if | 27.07 | |
| 042 | Release / QA / Test Center | 28.07 | AUD-039 |
| 043 | Architecture Decisions D-01…D-15 | 04.08 | **арбитър при конфликт** |
| 044 | Disaster Recovery | 20.07 | W0-10 |
| 045 | AI Command Center / ескалации | **12.09** | U3 |
| 046 | Client Portal | 23.07 | Wave 4 |
| 047 | Managed Work Package | 20.07 | |
| 048 | Resource Assignment | 28.07 | |
| 049 | Marketplace | 29.07 | отделен продукт |
| 050 | Tenant / абонаменти / entitlements | 04.08 | W0-BLOCKER; AUD-009, AUD-045 |

## 4. Архитектурни решения (ниво 6)

| Документ | Тема | Статус | Актуален? | Замества / заменен от |
|---|---|---|---|---|
| `docs/architecture/TENANCY_MODEL.md` | tenant изолация, database-per-tenant, membership | APPROVED (D-15) | да | — |
| `docs/architecture/WAVE_0_TENANCY_FOUNDATIONS.md` | W0-T01…T12 sub-backlog | REQUIRED | **не** — W0-03/06 „NOT STARTED“ | номерацията е в IMPLEMENTATION_WAVES |
| `docs/architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md` | PWA, глас/снимка/скан, field UX | APPROVED | да | — |
| `docs/architecture/FLOW_050_TENANCY_DECISION_2026-07-29.md` | tenancy + пакети + Launch Pricing v1 | APPROVED PARTIAL | **частично** | заменен в части от решенията от 03–04.08 |
| `docs/architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md` | customer-managed storage | APPROVED | да, но споменава „AI fair-use“ | променя D-11 |
| `docs/architecture/FLOW_050_PLAN_PLUS_AI_DECISION_2026-08-03.md` | План + AI бюджет | APPROVED | да | **заменя fair-use модела** |
| `docs/architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md` | billing, dunning | APPROVED | да | — |
| `docs/architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md` | trial, demo, partner | APPROVED | да | — |
| `docs/architecture/FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md` | среди, governance, retention | APPROVED | да | FLOW-050 → 100% |
| `docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md` | backfill на стари данни към tenant BEG | APPROVED | да | **заменя изискването за quarantine** (A3) |

## 5. W0 технически документи (ниво 4–6)

| Документ | Тип | Актуален? | Бележка |
|---|---|---|---|
| `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` | договор за задача | **частично** — „D/E NOT STARTED“ | текстът не се пренаписва; статусът е в dashboard |
| `docs/architecture/W0-03C_UNIQUENESS_READINESS.md` | бележка | **не** — „в ревю“, а е merged | |
| `docs/architecture/W0-03E_LEGACY_MIGRATION.md` | бележка | **не** — „Draft PR“, а е merged в #42 | |
| `docs/architecture/W0-03E-A1_INVENTORY.md` | генериран | исторически | заменен от A2C |
| `docs/architecture/W0-03E-A2_PROJECT_TEAM_INVENTORY.md` | генериран | исторически | |
| `docs/architecture/W0-03E-A2B_INVENTORY.md` | генериран | исторически | |
| `docs/architecture/W0-03E-A2C_INVENTORY.md` | генериран | да | **пълен backend**; пропуска `db.items` (AUD-026) |
| (липсва) W0-03D | — | — | **няма документ** за PR #30 |
| `docs/ops/W0-10A_RESTORE_PROOF_2026-09-20.md` | доказателство | да | PASS |
| `docs/ops/FOLLOWUP_ATLAS_STRAY_W0-04_TEST_DBS.md` | ops | **ОТВОРЕН** | 8 тестови бази в production Atlas; чака Крум |
| `docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md` | инцидент | **ОТВОРЕН** (хардуер) | |

## 6. История и контекст (ниво 7) — не са източник на правило

| Документ / група | Какво съдържа |
|---|---|
| `docs/architecture/FLOW_0xx_BUSINESS_CLOSE_*.md` (13 файла: 010, 012, 025, 036–042, 046, 048, 049) | протокол как FLOW е стигнал 100%; съдържанието е вече във FLOW файла |
| `docs/architecture/CROSS_FLOW_AUDIT_2026-07-20.md` | одит FLOW срещу код (20.07) |
| `docs/architecture/CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md` | одит FLOW срещу FLOW |
| `docs/architecture/CORRECTION_PASS_2026-07-20.md` | корекции след одита |
| `docs/project-recovery/2026-07-20/01_SOURCE_INDEX.md` | .docx източници от 12.07 |
| `docs/project-recovery/2026-07-20/02_RECOVERED_PROJECT_HISTORY.md` | история и „железни правила“ |
| `docs/project-recovery/2026-07-20/05_MASTER_KNOWLEDGE_BASE_SEED.md` | карта домейн → FLOW |
| (липсва) `docs/audits/2026-10-16_FULL_APP_AUDIT.md` | **трябва да се качи** (AUD-009…AUD-045) |

## 7. Legacy — не е канон

| Документ | Произход | Предложение |
|---|---|---|
| `README.md` (root) | шаблон от Emergent | замяна с кратко описание + линк тук |
| `AUDIT_REPORT.md` | одит 18.02.2026 | → `docs/archive/legacy-emergent/` |
| `PROMPT_TO_EMERGENT_P1_06C.md`, `README_P1_06C_BG.md` | неуспешен payroll patch | → архив |
| `PROMPT_TO_EMERGENT_P1_06E.md`, `README_P1_06E_BG.md` | корекция на 06C | → архив |
| `test_result.md` | протокол за тестове на Emergent | → архив |
| `memory/*.md` (12 файла, март–юни 2026) | knowledge base от Emergent ерата | бележка „LEGACY — не е канон“; особено `SOURCE_OF_TRUTH.md`, `CONTRACTS.md`, `PRD.md` |

## 8. Поддръжка на индекса

- Нов канонов документ → нов ред тук в същия PR.
- Документ, който замества друг → попълва се колоната „Замества“ и в двата документа.
- При всяка промяна на статус се пипа само `06_WAVE_STATUS_DASHBOARD.md`.

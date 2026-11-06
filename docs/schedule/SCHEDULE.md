# График за изпълнение — живо копие

> Поддържа: Claude Scheduler (клон `claude/schedule`). Решения: само Крум. Без merge/deploy без изрично „да“ от Крум.
> Обновено: 2026-11-06 21:30 UTC (периодичен преглед; main = `8e3b190`). Източници: PR списък и коментари, `02-release-gates.md`, `scope-matrix.md`, `08-c01-c16-review.md` (клон `codex/integrated-rc-2026-10-25` @ `3e0db8e`), BACKLOG_2026-10-17, seed SCHEDULE.

## Процес (решение на Крум R9, 06.11)

Claude програмира (до 3 паралелни сесии върху различни области/FLOW), Claude Audit ревюира, Claude Bot тества. **Codex само за пари/сигурност**. ChatGPT е извън процеса. Решения Р10–Р27 са в `RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md` (Р10 фира, Р11/Р18 всички трансфери „в път“, Р12 роли в ST-01, Р13 прехвърляне по дата, Р14 пари само Owner/Admin/Accountant, Р15 staging = shadow, Р16 труд/отпадък, Р17 разход при приемане, Р19 break-glass, Р20 финанси, Р21 частично приемане по партида, Р23 плащанията се сторнират, Р27 write-off от обект).
Активните пакети са в `docs/architecture/tasks/` на `claude/happy-meitner-bmcnel`.

## НА РЕД Е

**Codex (пари/сигурност)** — най-много чакащи: **#55 @ `64418eb`** (5C-C26c; последният видян Codex вердикт е CHANGES_REQUESTED на `53dbd28` — след него C24, C25, C26 и Р21/Р27 са добавени без нов Codex вердикт), **#56 @ `3234446`** (AUTH-02, Codex security review изрично поискан), **#69 @ `07faab5`** (SEC-01-C03), **#70 @ `8910939`** (PAY-01), **#71 @ `73b72b5`** (SEC-02).
**Крум** — решения, събрани от handoff-ите: (1) route gate `warehouse.write_command` спира Accountant и Technician преди проверката Р27 — да се даде ли право (чупи W0-02 инварианта и C19 F-6); (2) change-password: да вдига ли `auth_version` (UX: излиза от текущата сесия); (3) break-glass за platform admin, който не е Owner; (4) праг/Approval за значима разлика при write-off/ревизия (FG-22, чака W0-07); (5) ревизия на проектен баланс — цена при излишък; (6) линк от фактурен ред към партида освен чрез `invoice_line_id` (FG-17); (7) бележки по #54, решение за #53, #57.
**Сливане:** PM-01 (#68) е слят в main. Останалите — само по „да“ на Крум и след Codex PASS.

## Ред на интеграция (от audit merge-tree; файловете са моя проверка по diff срещу merge-base с main)

1. **#56** се слива първи — след Codex PASS и „да“ от Крум.
2. След това **#55** (вече е взел main `07da9ab` с merge commit, `1df77c3`) и **#54** вземат main с **merge commit, никога rebase**; #55 трябва отново да вземе main след сливане на #56.
3. **#53, #54 и #64** пресичат `DashboardLayout.js` и `App.js`; **#53 и #64 вървят след #55**.

Припокриващи се файлове (без docs/), по двойки:

| Двойка | Общи файлове |
|---|---|
| #56 ∩ #55 | `backend/app/tenancy/data_access.py`, `tenancy/ownership.py`, `backend/server.py`, `frontend/src/App.js` |
| #56 ∩ #54 | `backend/app/audit/store.py`, `tenancy/data_access.py`, `server.py`, `App.js`, `i18n/bg.json`, `i18n/en.json` |
| #55 ∩ #54 | `permissions/catalog.py`, `routes/procurement.py`, `tenancy/data_access.py`, `server.py`, `App.js`, `pages/ProcurementPage.js` |
| #54 ∩ #53 | `server.py`, `App.js`, `components/DashboardLayout.js`, `i18n/bg.json`, `i18n/en.json` |
| #53 ∩ #64 | `routes/live_ops.py`, `server.py`, `App.js`, `DashboardLayout.js`, i18n, `LiveOpsControlCenterPage.js` и неговия тест, `test_live_ops_a_read_only.py` |
| #54 ∩ #64 | `server.py`, `App.js`, `DashboardLayout.js`, i18n |
| #56 ∩ #64, #55 ∩ #64, #56 ∩ #53, #55 ∩ #53 | `server.py`, `App.js` (+ i18n за #56) |

`backend/server.py` и `frontend/src/App.js` са във всички пет PR — всяко сливане изисква ръчно разрешаване на регистрациите на routes. Решението за сливане е само на Крум.

## Задачи по ред

| # | Задача | PR | Отговорен | Статус | Head SHA | Блокира |
|---|---|---|---|---|---|---|
| 1 | AUTH-01 + AUTH-02 (Р19 break-glass; FG-7…11, 16) | #56 | Codex (security) | AUTH-02 качен, 122 passed на реална Mongo; чака Codex | `3234446` | — (първи за сливане) |
| 2 | Склад 5C до C26c (Р17 разход при приемане, Р18, Р21, Р27, FG-17 по D-04) | #55 | Claude (в работа) → Codex (пари) | C24→C26c качени; няма нов Codex вердикт след `53dbd28` | `64418eb` | решения на Крум (1,4,5,6); взема main след #56 |
| 3 | SEC-01 пари само за Owner/Admin/Accountant (Р14, C03: сума > 0, Idempotency-Key) | #69 | Claude → Codex | C03 качен | `07faab5` | — |
| 4 | ST-02 изолиран staging, shadow по Р15, манифест с режим (Р26) | #67 | Claude Audit → Крум | C03 качен (shadow репетиция с имена на deployer/approver) | `675faba` | — |
| 5 | PAY-01 плащанията се сторнират, не се трият (Р23, FG-34) | #70 | Claude → Codex (пари) | нов PR | `8910939` | — |
| 6 | SEC-02 четене на финансите по канона (Р20) | #71 | Claude → Codex | нов PR (стартира след SEC-01-C02) | `73b72b5` | #69 в main |
| 7 | PM-01 матрица роля × endpoint × режим | #68 | — | **СЛЯТ** (`8e3b190`) | `4e20084` | — |
| 8 | RC-01 (#65), ST-01 (#66) | — | — | **СЛЕТИ** | `07da9ab` | — |
| 9 | #53 Control Center ролеви тест | #53 | — | задържан (лимит от 3 сесии) | `e2a07ee` | — |
| 10 | #54 Заявки: mockup → права → телефон 390×844 | #54 | Крум (бележки) | чака Крум | `48306ba` | бележки на Крум |
| 11 | Интегриран RC + кумулативни тестове | #64 | Codex | подготовка; „NOT DEPLOY_READY“ | `3e0db8e` | 1–6 |
| 12 | 12-те сценария върху ST-01 + ST-02 (gate 7) | — | Bot / Codex | блокирано | — | #67, #56, #55 |
| 13 | Backup restore proof + rollback на точния image | — | Codex | блокирано: няма Docker socket / защитен backup | — | достъп до Synology (одобрение от Крум) |
| 14 | Решение на Крум за deploy | — | Крум | — | — | 1–13 |

Други отворени PR (извън RC пътя): #57 docs master recovery (`ba42cdf`, чака Крум); #51/#49/#46/#44 W0-06 File Registry (по ред #46→#49, после #44; #51 блокиран от C05); #47 md-usage-policy; #31/#28/#24/#23/#21 coordination (кандидати за затваряне, BACKLOG 0.7); #11 FLOW-027; #8 docs (BACKLOG 0.5).

## Следващите програмируеми задачи

В работа са повече от 3 програмни сесии (5C, SEC-01, ST-02, AUTH-02, PAY-01, SEC-02). **Нови сесии не се стартират** — потвърдено от оркестратора за SEC-02/W0-04 по-рано; PAY-01 и SEC-02 са вече стартирани, така че лимитът е надхвърлен и трябва да се потвърди.

| Ред | Задача | Codex | Състояние |
|---|---|---|---|
| 1 | **W0-04: загуба на AuditEvent при конкурентен запис** | да | задържана до сливане на #56 (`audit/store.py`) |
| 2 | **#53 ролеви тест** | не | задържан (лимит) |
| 3 | **Затваряне на малкия дълг:** `deps/auth.py` пада на `JWT_SECRET='dev-secret-key'` (AUTH-02 debt); P&L `input_vat` по старата селекция | да (сигурност) / не | идея за пакет — не е решена от Крум, да се одобри |

12-те сценария остават блокирани.

## Блокери и рискове

- Нито един интегриран RC не е минал (`NOT DEPLOY_READY`); #56 и #55 чакат exact-head вердикт.
- Standalone MongoDB отказва reset (503) — задължителна production проверка (replica set) в R0-08.
- Историческите данни (D-014/D-024/D-032/D-033) са отделен gate; код ги не поправя.
- Backup `begwork_atlas_2026-10-25_0310` е само проверка на архива, не restore proof.

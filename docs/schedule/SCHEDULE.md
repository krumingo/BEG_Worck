# График за изпълнение — живо копие

> Поддържа: Claude Scheduler (клон `claude/schedule`). Решения: само Крум. Без merge/deploy без изрично „да“ от Крум.
> Обновено: 2026-11-06 18:30 UTC (периодичен преглед; main = `07da9ab`). Източници: PR списък и коментари, `02-release-gates.md`, `scope-matrix.md`, `08-c01-c16-review.md` (клон `codex/integrated-rc-2026-10-25` @ `3e0db8e`), BACKLOG_2026-10-17, seed SCHEDULE.

## Процес (решение на Крум R9, 06.11)

Claude програмира (до 3 паралелни сесии върху различни области/FLOW), Claude Audit ревюира, Claude Bot тества. **Codex само за пари/сигурност** (плащания, заплати, складова оценка, auth/пароли, права, tenant изолация). ChatGPT е извън процеса.
Активни (по пакетите в `docs/architecture/tasks/` на `claude/happy-meitner-bmcnel`, проверени тук): **5C-C25** на #55 (FG-17 + Р17 разход при приемане + Р18 всички трансфери през „в път“), **ST-02-C02** на #67 (shadow по подразбиране, Р15), **SEC-01-C02** на #69 (FG-24/26/27/30/31), **AUTH-02** на #56 (Р19: break-glass оператор и причина). **SEC-02** чака SEC-01-C02. **Готови:** PM-01 (#68, audit PASS), RC-01, ST-01.

## НА РЕД Е

**Codex** — (пари/сигурност): (1) **#55 @ `dbda909`** — повторно ревю на 5C-C24; предишният вердикт на `53dbd28` е CHANGES_REQUESTED с F-55-C23-01 (FIFO слоеве/стойност 50 001 вместо 50 000) и F-55-C23-02 (unique индекс срещу реална legacy история); C24 ги поправя и включва пробите на Codex като тест (3 passed). (2) **#56 @ `dae097b`** — вердикт за RC-AUTH-03, няма нов.
**Claude (5C сесия)** — FG-17 е в **5C-C25** (в работа от 18:26 заедно с Р17 и Р18); блокер на #55 (FLOW GUARD, `project_pnl.py:92-94`): `max(invoice, warehouse)` в P&L — с фактурен ред 100 + консумация 30 + фира 20 P&L показва 100, а net-profit/project-profit 50; предложение: Път А и Път Б да се броят като отделни партиди и да се сумират през един helper. C24 не го адресира; C25 е в работа. Още FG-18…FG-23 в `docs/flow-guard/DIVERGENCES.md` (клон `claude/flow-guard`) — не са прегледани тук.
**ST-02** (`claude/st-02-staging-stack` @ `e987892`): стекът и репетицията X→X+1 с насилствен отказ и rollback на точния image са качени (`55ef71d`), `isolation_check` отказва production цели; сега **PR #67**; ST-02-C01 е готов, ST-02-C02 (shadow по Р15) е в работа.
**Решени от Крум на 06.11** (в `RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`, проверено): Р10 write-off от обект = разход на обекта („фира“); Р11 Rule B и за трансфери склад→склад; Р12 роли в ST-01 (заявител = SiteManager, одобряващ = Admin, без права = Viewer); Р13 legacy/канонични разходи се делят по дата на прехода.
**Крум — още чака:** (а) единствен останал въпрос за accept: дали приемането на трансфер склад→склад продължава да ползва действието и правото `accept_project_delivery` (така е сега) или получава отделно действие „accept transfer“ в permission каталога; (б) Rule B за `transfer_project_to_project` и `transfer_project_to_warehouse` — Р11 покрива само склад→склад, те още приемат директна дестинация; (в) бележки по #54; (г) решение за #53; (д) режимът на `PERMISSION_SERVICE_MODE`.

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

| # | Задача | PR / клон | Отговорен | Статус | Head SHA | Блокира |
|---|---|---|---|---|---|---|
| 1 | AUTH-01: RC-AUTH-01/02/03 | #56 | Codex (re-review) | Claude приложи C01 `10ed6b5` и C02 `dae097b` (стабилно подреждане); чака вердикт | `dae097b` | — |
| 2 | Склад 5C: C18→C24 (write-off = „фира“, Rule B за warehouse→warehouse) | #55 | Codex (пари) re-review; FG-17 отворен | C21–C24 качени (C22 затвори legacy справките; C23 фира по периоди; C24 FIFO слоеве + частичен индекс); чака Codex re-review на C24 | `dbda909` | решения на Крум (а–б по-горе); взема main отново след #56 |
| 3 | RC-01 Build identity (SHA в API + UI) | #65 | Claude Code | **СЛЯТ в main** (`1c01f67`) | `1c01f67` | — |
| 4 | #53 Control Center: съвместимост с main + тест на ролите | #53 | Codex | main-съвместимост 21 бекенд + 14 фронтенд PASS (по scope-matrix); интегриран в RC `8768c82`; чака ревю на роли/липсващи данни | `e2a07ee` | 1–2 за cumulative |
| 5 | #54 Заявки: mockup → права → телефон 390×844 | #54 | Крум (бележки), после Claude Code | чака бележки на Крум; C01 корекции F-01..F-04 са качени | `48306ba` | бележки на Крум |
| 6 | Staging артефакт → **ST-02 в работа** (`claude/st-02-staging-stack`) + решение `PERMISSION_SERVICE_MODE` (off срещу enforce) | — | Claude + Codex | не е започнато | — | 1–4; решение на Крум за режима |
| 7 | Интегриран RC + кумулативни тестове | `codex/integrated-rc-2026-10-25` (PR #64) | Codex | подготовка; „NOT DEPLOY_READY“ | `3e0db8e` | 1–5 |
| 8 | Изолиран staging + сценариите на Крум (12 сценария) | ST-01 #66 слят (`07da9ab`: синтетични фикстури + runner) | Codex / Bot | фикстури и runner са в main; самият staging не е стартиран | `07da9ab` | 6, 7, достъп до NAS |
| 9 | Backup restore proof + rollback на точния image | — | Codex | блокирано: няма Docker socket / защитен backup | — | root/Docker достъп на Synology (одобрение от Крум) |
| 10 | Решение на Крум за deploy | — | Крум | — | — | 1–9 |

Други отворени PR (извън RC пътя): #57 docs master recovery (`ba42cdf`, чака Крум); #51/#49/#46/#44 W0-06 File Registry (по ред #46→#49, после #44; #51 блокиран от C05); #47 md-usage-policy; #31/#28/#24/#23/#21 coordination (кандидати за затваряне, BACKLOG 0.7); #11 FLOW-027; #8 docs (BACKLOG 0.5).

## Следващите програмируеми задачи

Четири програмни сесии вече работят (5C-C25, SEC-01-C02, ST-02-C02, AUTH-02) — над планираните 3. **Нови сесии не се стартират.** Готово: PM-01 (#68). Решения Р14–Р20 са записани.

| Ред | Задача | Codex нужен | Състояние |
|---|---|---|---|
| 1 | **SEC-02** (финансови четения по канона, Р20) | да (пари/права) | следва в първия свободен слот, след SEC-01-C02 |
| 2 | **W0-04: загуба на AuditEvent при конкурентен запис** | да | задържана до сливането на AUTH-02 (#56): `audit/store.py` е споделен. Нов пакет не е нужен |
| — | #53 ролеви тест | не | задържан (над лимита от 3 сесии) |
| — | 12-те сценария (gate 7) | не | блокиран: #67, #56, #55 не са слети |

Няма свободна задача за стартиране в момента.

## Блокери и рискове

- Нито един интегриран RC не е минал (`NOT DEPLOY_READY`); #56 и #55 чакат exact-head вердикт.
- Standalone MongoDB отказва reset (503) — задължителна production проверка (replica set) в R0-08.
- Историческите данни (D-014/D-024/D-032/D-033) са отделен gate; код ги не поправя.
- Backup `begwork_atlas_2026-10-25_0310` е само проверка на архива, не restore proof.

# График за изпълнение — живо копие

> Поддържа: Claude Scheduler (клон `claude/schedule`). Решения: само Крум. Без merge/deploy без изрично „да“ от Крум.
> Обновено: 2026-11-06 15:30 UTC (периодичен преглед; main = `07da9ab`). Източници: PR списък и коментари, `02-release-gates.md`, `scope-matrix.md`, `08-c01-c16-review.md` (клон `codex/integrated-rc-2026-10-25` @ `3e0db8e`), BACKLOG_2026-10-17, seed SCHEDULE.

## Процес (решение на Крум R9, 06.11)

Claude програмира (до 3 паралелни сесии върху различни области/FLOW), Claude Audit ревюира, Claude Bot тества. **Codex само за пари/сигурност** (плащания, заплати, складова оценка, auth/пароли, права, tenant изолация). ChatGPT е извън процеса.
Активни имплементатори: **5C** (#55, сега C21) . **RC-01 (#65) и ST-01 (#66) са СЛЕТИ в main** (`1c01f67`, `07da9ab`).

## НА РЕД Е

**Codex** — (пари/сигурност) независимо ревю на **#56 @ `dae097b`** (RC-AUTH-03; няма нов вердикт след C02) и на **#55 @ `df48d68`** (склад/оценка/разходи = пари, т.е. Codex е нужен, след като Claude Audit и Bot минат C21).
**Claude Audit / Bot** — #55 @ `df48d68`: audit на C21 (write-off = „фира“, Rule B за warehouse→warehouse); от C20 audit остава **отворен**: три финансови справки четат само legacy редове (`project_financial_results.py`, `centralized_reports.py`, `revenue_snapshot.py`; още `material_waste.py`, `pulse_generator.py`, `materials_baseline.py` без проба). C21 не ги споменава — да се провери.
**Крум** — решения: (а) при project с канонични редове legacy разходите се отпадат изцяло (30 вместо 100+30) — дали да се раздели по време; (б) Rule B за останалите transfer-и (project→project, project→warehouse); (в) отделно действие за accept на transfer; бележки по #54; решение за #53; `PERMISSION_SERVICE_MODE`.

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
| 2 | Склад 5C: C18→C21 (write-off = „фира“, Rule B за warehouse→warehouse) | #55 | Claude Audit/Bot, после Codex (пари) | C21 качена; C20 audit за 3 legacy финансови справки не е потвърдено затворен; чака audit на C21 + Bot | `df48d68` | решения на Крум (а–в по-горе); взема main отново след #56 |
| 3 | RC-01 Build identity (SHA в API + UI) | #65 | Claude Code | **СЛЯТ в main** (`1c01f67`) | `1c01f67` | — |
| 4 | #53 Control Center: съвместимост с main + тест на ролите | #53 | Codex | main-съвместимост 21 бекенд + 14 фронтенд PASS (по scope-matrix); интегриран в RC `8768c82`; чака ревю на роли/липсващи данни | `e2a07ee` | 1–2 за cumulative |
| 5 | #54 Заявки: mockup → права → телефон 390×844 | #54 | Крум (бележки), после Claude Code | чака бележки на Крум; C01 корекции F-01..F-04 са качени | `48306ba` | бележки на Крум |
| 6 | Staging артефакт (инструментите W0-09A са в main) + решение `PERMISSION_SERVICE_MODE` (off срещу enforce) | — | Claude + Codex | не е започнато | — | 1–4; решение на Крум за режима |
| 7 | Интегриран RC + кумулативни тестове | `codex/integrated-rc-2026-10-25` (PR #64) | Codex | подготовка; „NOT DEPLOY_READY“ | `3e0db8e` | 1–5 |
| 8 | Изолиран staging + сценариите на Крум (12 сценария) | ST-01 #66 слят (`07da9ab`: синтетични фикстури + runner) | Codex / Bot | фикстури и runner са в main; самият staging не е стартиран | `07da9ab` | 6, 7, достъп до NAS |
| 9 | Backup restore proof + rollback на точния image | — | Codex | блокирано: няма Docker socket / защитен backup | — | root/Docker достъп на Synology (одобрение от Крум) |
| 10 | Решение на Крум за deploy | — | Крум | — | — | 1–9 |

Други отворени PR (извън RC пътя): #57 docs master recovery (`ba42cdf`, чака Крум); #51/#49/#46/#44 W0-06 File Registry (по ред #46→#49, после #44; #51 блокиран от C05); #47 md-usage-policy; #31/#28/#24/#23/#21 coordination (кандидати за затваряне, BACKLOG 0.7); #11 FLOW-027; #8 docs (BACKLOG 0.5).

## Следващите 3 програмируеми задачи, които НЕ са блокирани

Слети и затова махнати: R0-01…R0-07, RC-01 (#65), ST-01 (#66, включва runner-а на сценариите). #55 (5C) има активна сесия — не се предлага повторно.

| # | Задача | Codex нужен | Докосва (области) | Припокриване |
|---|---|---|---|---|
| 1 | **Staging артефакт с W0-09A инструментите** (gate 5): инструментите вече са в main (`w0-09a-release-foundation` е предшественик на main); остава да се построи артефактът — manifest, SHA256SUMS, image IDs, фиксиран build SHA от RC-01 | не | `ops/`, release tooling | независим от #55/#56; ползва build SHA от RC-01 |
| 2 | **`PERMISSION_SERVICE_MODE` off/enforce — тестове на роли** | **да** (права) | permission service, role тестове; режимът решава Крум | `permissions/catalog.py` е и в #54/#55 — да върви след тях или с merge main |
| 3 | **Пълно сценарийно изпълнение върху ST-01 фикстурите** (gate 7: 12-те сценария, доказателства) | не за изпълнението; Codex ревюира пари/сигурност сценариите | `tests/` runner, evidence | чака #56 и #55 в main, иначе тества несъщия код |

Алтернатива без пресичане: **#53 ролеви тест** (read-only Control Center; Codex: не). Затваряне на 3-те legacy финансови справки (C20 audit) е част от #55 — не е нова задача.

## Блокери и рискове

- Нито един интегриран RC не е минал (`NOT DEPLOY_READY`); #56 и #55 чакат exact-head вердикт.
- Standalone MongoDB отказва reset (503) — задължителна production проверка (replica set) в R0-08.
- Историческите данни (D-014/D-024/D-032/D-033) са отделен gate; код ги не поправя.
- Backup `begwork_atlas_2026-10-25_0310` е само проверка на архива, не restore proof.

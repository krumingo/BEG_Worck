# BL-13b — всички ботове върху TEST-ONLY интеграция v2 (16.11.2026)

Статус: **тестово доказателство върху синтетични данни, само за измерване**. Клонът
`claude/bots-lupa-integration-v2` е **еднократен тестов клон** — не е за merge в `main`, не е PR,
няма deploy, няма production, не е Implementation Gate PASS.

## 1. Код

| | |
|---|---|
| Основа | `claude/bots-lupa-integration` **9569591c** (= main de720f94 + fix-mat-02, fix-adv-02, fix-pay-02, fix-aud-01, fix-perm-01, lab-r96-step2; README в `../INTEGRATION_2026-11-16/`) |
| Влети (`--no-ff`) | fix-mat-03 **94cf7d12** → `ad2082f9` · lab-r96-step3 **aa2e2909** → `a9352ae7` |
| Конфликти | няма текстови. **Семантичен** (само в тестовете): LAB-R96 step 3 пуска P&L труда през `labor_cost_reader` → `report_normalizer`, който взема `app.db.db` при import. Тестовите хамути на PAY-01 и FIX-PAY-01 подменят фиксиран списък модули без него → при общо пускане fix-mat-01 (24), fix-pay-01 test_08 (6), fix-pay-02 test_01/03 (12) четат през Motor клиент на затворен event loop (41–42 грешки). Поправка `06404e4b`: `report_normalizer` добавен в двата списъка. Кодът на приложението не е пипан. |
| PM-01 / W0-03E-A1 | регенерирани след двете сливания (`--harness`, `w0_03e_a1_inventory.py`): **байт-идентични** (само `seconds` в run_meta — не е записано) |

### Тестове (Mongo: собствен docker `mongo:7` rs0 на 27191)

| Група | Резултат |
|---|---|
| `test_fix_*` + `test_lab_r96_*` (13 файла, заедно) | **576 passed, 1 skipped, 0 xfail** (skip: уникален индекс — само real Mongo, mongomock параметър) |
| PM-01 + `test_w0_03e_*static_guard*` | **128 passed** |
| всички `test_w0_03e_*` | 451 passed, **1 failed**: `test_w0_03e_legacy_routes.py::test_off_keeps_the_legacy_behaviour_and_touches_no_master_data[users]` — пада и на main de720f94, и на v1 (тестът очаква режим off да не пише одит, а изтриването на потребител вече пише AuditEvent); не е от интеграцията |

## 2. Процесен бот — същият хамут като v1

Нова фирма/база (`demoint2p_*`, Mongo 27191), backend на порт 8769, `process_bot.py --minutes 6.5 --pause 60` →
**7 чисти цикъла**. Заявките на бота са **непроменени спрямо v1** (разликата е само порт/база/папка през env, `harness.diff`).

| ID | Правило | main de720f94 (165 ц.) | v1 9569591c (5 ц.) | **v2 (7 ц.)** |
|---|---|---|---|---|
| F1-3 | вграден ред от финансовия UI към обект → material_cost +85 веднъж | нарушено Δ 0 | нарушено Δ 0 | **минава** Δ +85, `invoice_cost` 85 — 7/7 |
| F1-B4 | анулирана фактура: Δ 0, ДДС Δ 0 | нарушено +110/+22 | минава | **минава** 0/0 — 7/7 |
| F2-2 | транш paid + 1 Outflow 400 | нарушено 0 реда | минава | **минава** — 7/7 |
| F3-4 | втори отчет същ човек/ден/обект → отказ | нарушено 201 | минава 400 | **минава** 400 `LABOR_LINE_EXISTS` — 7/7 |
| F3-6 | одобрен отчет от втория път → 1 work_session | нарушено | минава (проба) | **минава** (проба `probe_f3_6.py` 3/3: 1 сесия; самоодобрение 403 `FOUR_EYES`) |
| F3-7 | generate: W0 8 ч × 12 = 96 | нарушено 192 | минава | **минава** 8 ч / 96 — 7/7 |
| F3-8 | P&L труд = ведомост | нарушено 306↔402 | минава | **минава** 24 ч / 306 = 24 ч / 306 — 7/7 |
| F3-12 | след mark-paid няма неплатени | нарушено | минава | **минава** — 7/7 |
| F4-2 | същият ключ ×3 → 1 аванс, 1 плащане | нарушено 3/3 | минава | **минава** 1/1 (`[409, 201, 201]`) — 7/7 |
| F5 | склад | непроверимо (422 `MASTER_IDENTITY_MISSING`) | непроверимо | непроверимо (същото) |
| F6 | Viewer/Driver/Worker → 403, 0 записа | минава | минава 135/135 | **минава 189/189** |

**Нарушени остават: 0 от 9.** Всички останали стъпки (повторно плащане, reversal, повторно одобрение, mark-paid 409 …) — минават.
Сървърът: 592 заявки, 0 × 5xx. „Непроверими“ стъпки (ok = None): F4 стъпка 1 (два различни ключа = две заявки, по дефиниция), F5.

## 3. UI ботове по роли (8) — 30 минути

Среда: собствен docker `mongo:7` rs0 на **27192**, база `demoint2ui_*`, нова фирма; build на интеграционния
frontend (`yarn install --frozen-lockfile`, `CI=false REACT_APP_BACKEND_URL="" yarn build`) и backend през
`serve.py` на порт **8768**; `run_ui.sh` прави всичко подред. Процесният бот **не** е пускан паралелно (в main беше —
от там идваха фалшивите „без одит“).

### Защо 6 от 8 бота спираха в main (доказано в пробата)

Пробно пускане (2 мин) на стария алгоритъм с таймаути: **0 таймаута**, а Driver/Viewer/Worker/Warehousekeeper пак
замръзват на `/assets/batch-intake` и `/tech/tools`. Причината: **задънени екрани** — там няма `<a href>`,
стъпката „посети“ няма какво да избере, „действай“ не намира бутон, цикълът се върти без нито едно действие до края.
Втората причина за малко покритие при PC ролите: групите в страничното меню (Обекти, Персонал, Финанси, Склад…)
са бутони — линковете им не са в DOM, докато групата не се отвори, затова Admin/Accountant/SiteManager виждаха 4–6 екрана.
Не е дефект на програмата.

### Промени в `bot.js` (само ботът; `harness.diff`)

| Промяна | Защо |
|---|---|
| твърд таймаут 15 s (`Promise.race`) за всяка стъпка/навигация; при таймаут → начален екран на ролята; ако и той виси → нова страница + вход | изискване; в 30-те минути не се задейства нито веднъж (0 възстановявания) |
| „празен ход“ 30 s без действие → възстановяване; 300 ms пауза на цикъл | задънен екран не може да държи бота |
| линкове: най-малко посещаваният от **всички видени досега** (и на задънен екран) | задънени екрани |
| отваряне на 1–2 групи от менюто преди избор на линк (`menu`, не се брои за действие) | PC покритие 4–6 → 33–45 екрана |
| етикетите на бутоните с **един** `evaluateAll` вместо по елемент (до 120 × 8 s); кратки таймаути за `fill/evaluate` | бърз екран, без минути чакане |
| PRNG **на роля** (mulberry32, seed = FNV-1a на името, в `data/bots_started.json`) | Codex: един общ seed за 8 паралелни бота → невъзпроизводимо; старият LCG губи точност над 2^53 |
| `x-correlation-id: <роля>:<n>:<вид>` на всяка `/api` заявка (route handler); `serviceWorkers: 'block'` | екран ↔ сървър по id, не по ±3 s |
| след пускането: `browser.on('disconnected')` → изход | прекъснат пробен процес без браузър писа 0.9 GB грешки в своята (преместена) папка; не е стигнал до сървъра на това пускане (последна мрежова заявка 19:01:31, сървърът е стартиран наново 19:02 с празна база) |

`serve.py`: логва `corr`; с `BOT_SERIALIZE_WRITES=1` всяка POST/PUT/PATCH/DELETE минава сама (asyncio lock) и
lock-ът се държи 0.4 s след отговора → всяка промяна от change stream принадлежи на **точно една** заявка (`t`..`t_end`).
`analyze.py`: съвпадение екран↔сървър по correlation id (39 437 / 39 437 съвпаднали по id), прозорци `t`..`t_end`,
групирани CSV-та, таблица на покритието.

### Покритие (`data/ui_coverage.csv`) — всички 8 роли работят

| Роля | Екрани | Посещения | Действия | Възстановявания | Заявки |
|---|---|---|---|---|---|
| Admin | 45 | 330 | 401 | 0 | 5 021 |
| Accountant | 44 | 323 | 342 | 0 | 5 160 |
| SiteManager | 33 | 333 | 357 | 0 | 4 048 |
| Warehousekeeper | 7 | 448 | 246 | 0 | 5 202 |
| Viewer | 6 | 435 | 265 | 0 | 5 273 |
| Technician | 7 | 389 | 205 | 0 | 5 064 |
| Driver | 5 | 377 | 212 | 0 | 4 627 |
| Worker | 7 | 374 | 205 | 0 | 5 042 |

Полевите роли имат 5–7 екрана, защото толкова им дава менюто (`WORKER_NAV`, `DashboardLayout.js:137-143`).

### Находки (`data/ui_*.csv`, `report.html`)

39 437 заявки от екраните, 39 468 в сървъра, 343 промени в базата.
**0 × 5xx, 0 JS срива, 0 hard delete, 0 insert без `org_id`, 0 „готово“ без запис, 0 заявки, неотишли до сървъра.**

| Находка | Брой | Роли | Сверено в кода |
|---|---|---|---|
| 403 `GET /assets/intake/locations` — менюто показва „Заскладяване“ на всеки неадминистратор, сървърът отказва (празен екран) | 343 | Driver 76, Viewer 74, Warehousekeeper 64, Technician 56, Worker 54, SiteManager 12, Accountant 7 | `frontend/src/components/DashboardLayout.js:140` (`WORKER_NAV`, без проверка) срещу `backend/app/routes/assets_intake_pending.py:221-227` (`_can_submit`); плочката в `TechnicianDashboard.js:459` е зад `canIntake` |
| 403 на екрани, достъпни за Accountant: `/projects/{id}/team` 23, `/pay-runs/generate` 22, ai-calibration, historical/analytics, work-reports/project-day … | 136 | Accountant | кандидати: екранът се отваря, сървърът отказва |
| 403 на екрани/бутони за SiteManager: ai-calibration, ai-config, finance/invoice-settings, sales/history, `POST /assets/units` 9, `/assets/qr/generate` 8, `/clients` 6, `/users` 6 … | 116 | SiteManager | кандидати (видим бутон, отказ) |
| **SiteManager `/employees`, `/worker-calendar`** | **0 × 403** (main ~1 200) | — | FIX-PERM-01 работи: 41 + 11 заявки, всички 200 |
| 422 `GET /items?page_size=500` (екран „Продажби“) | 17 | Admin 6, SiteManager 6, Accountant 5 | `frontend/src/components/sales/SalesWindow.js:61` срещу `backend/app/routes/items.py:121` (`le=100`) |
| 404 `GET /settings/payroll-week` „Organization not found“ | 4 | Admin 2, Accountant 2 | `backend/app/routes/settings.py:40-42`: проекция `{"_id":0,"payroll_week":1}` на фирма без това поле връща `{}` → 404, докато някой не запише настройката |
| Запис без AuditEvent | 43 | Admin, SiteManager, Accountant | `POST /activity-catalog` 12 (`offers.py:950`), `POST /contract-payments` 9 (`hr.py:982-1016` — само `insert_one`), `POST /smr-analyses` (+approve, +lines) 9 (`smr_analysis.py:150`), `POST /assets/units` 5, `POST /assets/items` 3 (`assets_items.py` — без одит), `PUT /settings/payroll-week` 4 (`settings.py:51`), `PUT /finance/invoice-settings` 1 |
| Промени без заявка за запис | 18 | — | `history.voided_read` AuditEvent при четене 7 (по дизайн), `reminder_logs` + `notifications` 10 (фонова задача), `invoice_settings` insert при първо четене 1 |

Записите без одит са с **сериализирани** записи (една заявка в прозореца) — не са артефакт на паралелност.
Main находките `POST /missing-smr` и `POST /assets/qr/generate` без одит **ги няма** (FIX-AUD-01: 11 `missing_smr.created`, 8 `asset_qr.generated`).
Правила върху крайната UI база (Q1–Q4, двойни отчети/номера/кодове/аванси): няма двойни; 9 pending транша, 13 Outflow.

## 4. Какво не е доказано

- Складът (F5) — Master Data изключен; в празна база ботът не може да създаде артикул.
- 30 минути, не 3 часа; полевите роли покриват само екраните от своето меню.
- 403-кандидатите за Accountant/SiteManager не са сверени един по един (кое е „правилно скрито“ и кое е грешка в екрана).
- Нищо за реалните данни; стари записи от стария формат на труда не са в тази база.

## 5. Файлове

- `harness/` — точните скриптове (+ `run_ui.sh`); `harness.diff` — спрямо `../INTEGRATION_2026-11-16/harness/` + `bot.js`/`watch.py` от happy-meitner.
- `report.html` — analyze.py върху UI пускането (+ процесните стъпки на v2).
- `data/int2_process.jsonl`, `data/int2_process_grouped.csv`, `data/probe_f3_6.jsonl` — процесен бот.
- `data/summary.json`, `data/ui_*.csv`, `data/bots_started.json` — UI ботове. Суровите UI логове (~22 MB) не са в Git.

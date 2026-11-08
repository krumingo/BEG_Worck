# PRJ-01 — обекти без изтриване, повторно отваряне, гаранция към оригинала, оценка на подизпълнител

Пакет: `docs/architecture/tasks/PRJ-01_PROJECT_NO_DELETE_REOPEN_WARRANTY.md` (клон `claude/happy-meitner-bmcnel` @ `0cb7161`). Решение Р54. FLOW Guard FG-236..FG-240 (`claude/flow-guard`).
Канон: CLAUDE.md §2 т.9, §4, §14, §15; FLOW-001 P-04, P-06, P-07, P-08, P-09, P-13, P-15; FLOW-018 → FLOW-039; FLOW-006.
Клон: `claude/prj-01-project-lifecycle` от main `0750d75`. Без merge, без deploy, без production.

## Първо червено, после поправка
* Commit `51c45fc` — само тестът `backend/tests/test_prj_01_project_lifecycle.py` (реален MongoDB 7.0 rs0, `W0_03_REAL_MONGO_URL`, два tenant-а ST-01, истински login/JWT, цялото приложение).
* На main: **9 failed** — `red_on_main.txt`, наблюденията: `red_on_main_results.json`. Например: DELETE на обект с оферта/плащане → 200 и обектът изчезва; снимката се трие заедно с файла; няма `/reopen`; PUT сменя типа Billable → Overhead при обект с отчет; Viewer записва оценка на подизпълнител; ръчно „платено“ 999 се показва.
* След поправката: **9 passed** (`results.json` — свежо пускане на harness-а).

## Какво е направено

| FG | Поправка |
|---|---|
| FG-239 | `DELETE /projects/{id}` (Owner/Admin, Idempotency-Key): обект, който **който и да е** запис на tenant-а сочи (`project_id`, `site_id`, `subproject_id`, `parent_project_id`, `warranty_of_project_id` във всяка `org_id` колекция на `ORG_KEYED`) → **409 `PROJECT_HAS_HISTORY`** със списък на връзките; не-чернова → **409 `PROJECT_NOT_DRAFT`**. Изтрива се само празна чернова (P-06), в транзакция с AuditEvent `project.delete`. Нови `POST /projects/{id}/archive` и `/cancel`: Owner/Admin, причина, ключ, транзакция + AuditEvent. Общият `PUT` вече не архивира/отказва (409 `USE_LIFECYCLE_ENDPOINT`). Тест за всяка от 13 вида връзка. |
| FG-237 | `POST /projects/{id}/reopen` — Completed → Active (P-08): Owner/Admin (P-07), вид (`warranty`, `defect`, `completion`, `additional_work`, `correction`) + причина, ключ; цикълът на отваряне се пази в `reopen_cycles`; `PUT status=Completed` го затваря. AuditEvent `project.reopen`. PUT Completed → Active остава забранен. Проверено и в enforce. |
| FG-238 | `DELETE /projects/photos/{id}` → **скриване**: `status=retired`, причина, кой/кога, AuditEvent `project.photo.retire`; редът и оригиналният файл остават; списъкът по подразбиране не я показва (`?include_retired=true` я показва). Правата — както преди (качилият, Admin, Owner). |
| FG-236 / Р54(1) | Нов обект тип Warranty → 409 `WARRANTY_IN_ORIGINAL_PROJECT` (път: reopen на оригинала). Смяна на типа след първия запис → 409 `PROJECT_TYPE_LOCKED`; към Warranty — никога. Миграция `backend/scripts/prj_01_warranty_link_migration.py`: dry-run (план + SHA-256) → `--apply --approved-by --plan-sha` (друг план → `PlanMismatch`, нищо не се записва) → по една транзакция на обект с AuditEvent `project.warranty_link`; ако оригиналът не може да се определи → `dq_issues` `PROJECT_WARRANTY_ORIGINAL_UNKNOWN` + AuditEvent `dq.issue.open`; втори пуск не пише нищо; нито един обект не се трие. |
| FG-240 / Р54(2) | `POST/PUT /subcontractor-performance`: само SiteManager на обекта, Owner, Admin (другите 403); ключ; версия (`version`, append-only `subcontractor_performance_versions`) + AuditEvent в транзакция; подизпълнителят и обектът трябва да са на tenant-а (422). `actual_paid_amount` в заявка → 422 `ACTUAL_PAID_IS_COMPUTED`; при четене се изчислява от `finance_payments` (Outflow, без сторнирани двойки) през `subcontractor_payments`; старата ръчна стойност остава в записа и се показва като `legacy_manual_paid_amount`, не се ползва. |

Общ модел (`app/services/project_lifecycle.py`): 428 без Idempotency-Key, W0-04 `begin_idempotent` (ключ на tenant + потребител + действие), `auth_tx.run_in_transaction`, `record_event(..., session=session)`.

UI: `ProjectsListPage` (изтриване с ключ и текст на грешката; Архивиран/Отказан през новите endpoint-и с причина; без „Гаранционен“ за нови), `ProjectReopenButton` на `ProjectDetailPage` (Owner/Admin, приключен обект), `SubcontractorPerformancePanel` (без поле „платено“, с ключ). Frontend тест `projectLifecycle.test.js`.

## Кръг 2 — FLOW Guard върху #86 (FG-252..FG-256, D3, D6)
Main `ec7ddd8` е слят в клона с merge commit (`5a80d22`, без конфликти). Разширеният тест върху предишния head `0bd77a1` дава **7 failed** (`red_round2_on_0bd77a1.txt`, наблюдения `red_round2_on_0bd77a1_results.json`); след поправката — 9 passed.

| | Поправка |
|---|---|
| FG-252 | `create-sub-project`, `wrap-in-group`, `add-subproject` върху Warranty обект → 409 `WARRANTY_IN_ORIGINAL_PROJECT` преди всеки запис (на 0bd77a1: 3 нови Warranty обекта). |
| FG-254 | Проверката за история намира препратка в **всяко** поле на най-горно ниво (`context_id`, `entity_id`, …) и в масив от id-та, плюс известните вложени пътища (`day_entries.project_id`, `transit_origin.project_id`, `context.entity_id`, `lines.project_id`). Файл от `/api/media/upload` и QR код блокират изтриването. |
| FG-253 | Reopen на Warranty / свързан обект → 409; гаранционната работа отива в оригинала. |
| FG-255 | GET `/subcontractor-performance`, `/compact`, `/log` махат парите за нефинансови роли (R20-5M, вписани в `FINANCE_READS`); `/log` — само Owner/Admin или SiteManager на посочения обект (Technician/Viewer → 403). |
| FG-256 | PUT само с неприети полета → 422, без празна версия и AuditEvent. Миграцията затваря отворения DQ при `--map` (AuditEvent `dq.issue.resolve`). |
| D3 | `PUT /projects/{id}` със смяна на статус изисква `status_reason` и Idempotency-Key; една транзакция с AuditEvent `project.status_change` (вкл. затварянето на цикъла на повторно отваряне). P-04A полетата (кой е поискал, отговорна страна, условие за възобновяване, Pause Impact Assessment) и P-10 проверките остават дълг (**D3-остатък**). |
| D6 | Файлът на скрита снимка се дава само на Owner/Admin; на останалите — 404. |

Бележка към D5: тъй като екранът генерира QR код при всеки нов обект, на практика почти всяка чернова вече има връзка и не се изтрива (409) — остава отказ (cancel).

## Кръг 3 — Р56 (Крум, 08.11) и „платено“ от всички плащания и аванси (Р39)
Разширеният тест върху head-а на кръг 2 `718bac7` дава **4 failed** (`red_round3_on_718bac7.txt`); след поправката — 9 passed.

| | Поправка |
|---|---|
| Р56(1) | Отваряне — само Owner/Admin (SiteManager → 403). Нов `POST /projects/{id}/reopen-request`: само SiteManager на обекта, вид + причина + ключ; искането се пази в `reopen_requests`, всеки активен Owner/Admin получава известие, AuditEvent `project.reopen_request`; отварянето от Owner/Admin маркира отворените искания `done`. UI: бутон „Поискай отваряне“ за SiteManager. |
| Р56(2) | Чернова с екип, етапи, оферта или клиент → 409 `PROJECT_HAS_HISTORY` (`team_members`, `project_phases`, `offers`, `client`), архив вместо изтриване. Изтрива се само наистина празна чернова (без триене на екип/етапи). |
| Р56(3) | `quality_score` — само цяло число 1–5 (0, 6, 4.5, „4“, −1 → 422). |
| Р56(4) | Неопределим оригинал → DQ към техническия ръководител (`owner_role=site_manager`, `assignee_user_id` = ръководителят на обекта), `due_at` = +7 дни; `escalate_overdue()` (`--escalate`) прехвърля просрочената задача към Собственика веднъж (известие + AuditEvent `dq.issue.escalate`). Връзката прави гаранционния проект **подобект** на оригинала (`parent_project_id` = оригинала; предишният родител се пази в `warranty_link`). Оригинал, който сам е подобект → DQ (две нива). |
| „Платено“ | Сбор от редовете в `finance_payments` (единният ledger, FLOW-006): `direction=Outflow`, без сторнирани двойки (`status ∉ {reversed, reversal}`), чийто `subcontractor_payment_id` е ред в `subcontractor_payments` със същия `subcontractor_id` + `project_id` (+ `package_id`, ако записът има). Така влизат **и плащанията, и авансите** (Р39 — SUB-ADV-01 #76 пише аванса като `subcontractor_payments` ред `kind="advance"` + ledger ред със `subcontractor_advance=True` и същия ключ). Тест: 150 плащане + 30 аванс − 50 сторно = 180. |

Колекции и ключове за „платено“ (за HANDOFF):
* `finance_payments` — `subcontractor_payment_id`, `direction`, `status`, `amount`;
* `subcontractor_payments` — `id`, `subcontractor_id`, `project_id`, `package_id` (плащания и аванси).
* Извън обхвата (няма каноничен ключ към подизпълнител): плащания по входящи фактури (`payment_allocations` → `invoices` с `supplier_counterparty_id` към `counterparties`, не към `subcontractors`) и „други разходи“ само с `counterparty_name` → **PRJ-01-D13**.

Нови дългове: **PRJ-01-D12** — ескалацията на DQ няма планировчик; `--escalate` трябва да се пуска ежедневно (или да влезе в W0-07). **PRJ-01-D13** — виж по-горе. D1, D5, D7, D9 са решени с Р56.


## Кръг 4 — FLOW Guard проход 28 (FG-272, FG-273 код, FG-274) + main 3699c3b
Main `3699c3b` (#74 OH-01 + документи) е слят с merge commit `0fe133d` (конфликт само в генерирания `PM-01/run_meta.json`, регенериран с harness-а). Аудитът за `quality_score` (Р56-3): проверката 1–5 (`StrictInt`, `ge=1`, `le=5`) е в `PerformanceCreate` и `PerformanceUpdate` от `0314e6e`; тестът вече покрива POST и PUT с 0, 6, 99, −3, 2.5, „x“, „4“, true → 422 и 1, 5 → OK (`6479cf1`). Разширеният тест върху `6479cf1` дава **2 failed** (`red_round4_on_6479cf1.txt`); след поправката — 9 passed.

| | Поправка |
|---|---|
| FG-272 | Проверката за история намира препратка **вътре в масиви и под-документи**. |
| FG-274 | `business_links`: **една** exists-заявка на колекция по именуваните пътища (`find_one` с `$or`; индекс по пътя обслужва клона си), после общото сканиране, **спира при първото попадение**. `DELETE` прави проверката **преди** транзакцията (първо евтините: клиент → екип → етапи → история), а транзакцията трие с **CAS** върху `status=Draft` + `updated_at` (иначе 409 `PROJECT_CHANGED`). Остатъчен риск: нов запис в друга колекция, създаден между проверката и CAS-а, не променя обекта → **PRJ-01-D14**. |
| FG-273 (код) | Автоматичното преименуване на кода на под-обект в `create-sub-project` (напр. свързан гаранционен проект под оригинала) е транзакция с CAS по стария код + каноничен AuditEvent `project.code_change` (преди/след). Първата половина (връзка към корена или второ ниво) чака Крум. |

Форми на препратка към обект, които проверката покрива (за HANDOFF):
* поле на най-горно ниво с произволно име — `project_id`, `site_id`, `subproject_id`, `parent_project_id`, `warranty_of_project_id`, `context_id` (`media_files`), `entity_id` (`asset_qr_codes`), `allocation_ref_id` (invoice lines) и всяко друго;
* масив от id-та на най-горно ниво;
* вложени масиви от препратки: `allocations[].ref_id` / `allocations[].refId` (`invoice_lines`, `POST /invoice-lines`), `lines[].project_id`, `lines[].allocation_ref_id`, `lines[].allocations[].ref_id` / `refId` (`invoices`), `day_entries[].project_id` (`worker_calendar`);
* вложени под-документи: `transit_origin.project_id` (склад), `context.entity_id` (файлове);
* **всяка друга форма** до 4 нива под документа (общо сканиране с `$objectToArray` / `$map`; id-тата са UUID, равна стойност = препратка). Тестът включва и непознат ключ: `material_requests.items[].target.site`.

Виж `test_summary.txt`.

## Дългове (Крум / оркестратор)
* **PRJ-01-D1** — FLOW-001 P-08 мълчи за Approval при повторно отваряне. Направено: Owner/Admin по P-07, без Approval (W0-07 runtime няма). Крум: нужен ли е Approval; може ли и PM/SiteManager.
* **PRJ-01-D2** — P-09: маркирането на всеки отчет/разход след гаранционно отваряне като „Гаранционен разход“ и разделението първоначална/гаранционна/крайна себестойност не са направени. Пазят се цикълът (вид, отворен/затворен кога), за да се построи проекцията.
* **PRJ-01-D3** — кръг 2: причина + ключ + каноничен AuditEvent са направени. Остават P-04A полетата и Pause Impact Assessment (FLOW-036) и P-10 проверките преди финансово приключване.
* **PRJ-01-D4** — `dq_issues` е временен регистър (същата форма като CP-01/#81, до W0-07); редът в `ownership.py` е същият като в CP-01. `owner_role="admin"` за тази DQ задача — предположение (проектите се управляват от Owner/Admin, P-07).
* **PRJ-01-D5** — изтриване на **празна чернова** е оставено (FG-239 решение, P-06). Ако Крум иска никакво изтриване — DELETE става винаги 409.
* **PRJ-01-D6** — снимките още са в локалната папка, не в File Registry / customer storage (W0-06). Кръг 2: скритата снимка вече не се дава на никого освен Owner/Admin.
* **PRJ-01-D7** — `quality_score` без граници: каноничната скала на рейтинга (FLOW-039) не е определена.
* **PRJ-01-D8** — FG-240: Крум да реши дали `subcontractor_performance` влиза в миграцията към FLOW-039 или се замразява read-only. GET-овете показват `promised_amount` на всички роли (извън пакета).
* **PRJ-01-D9** — миграцията определя оригинала само по `parent_project_id` на гаранционния обект или по `--map` (решение на човек). Крум потвърждава правилото при одобрението на dry-run плана.
* **PRJ-01-D10** — архивиране/отказ следват legacy графа на статусите (Completed/Cancelled/Overhead → Archived; Draft/Paused/Stopped → Cancelled); каноничният enum от P-04 (10 статуса) не е въведен.
* **PRJ-01-D11** — като `finance._once`: ключът се маркира completed след commit; срив точно между двете оставя ключа STARTED → повторът получава 409 IN_PROGRESS.
* Бележка: `W0-03E-A2C_INVENTORY.md` е остарял и на main; не е регенериран тук (само A2B, +2 реда за новите колекции).

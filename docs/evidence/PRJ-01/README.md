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

## Gates
Виж `test_summary.txt`.

## Дългове (Крум / оркестратор)
* **PRJ-01-D1** — FLOW-001 P-08 мълчи за Approval при повторно отваряне. Направено: Owner/Admin по P-07, без Approval (W0-07 runtime няма). Крум: нужен ли е Approval; може ли и PM/SiteManager.
* **PRJ-01-D2** — P-09: маркирането на всеки отчет/разход след гаранционно отваряне като „Гаранционен разход“ и разделението първоначална/гаранционна/крайна себестойност не са направени. Пазят се цикълът (вид, отворен/затворен кога), за да се построи проекцията.
* **PRJ-01-D3** — `PUT /projects/{id}` за пауза/възобновяване/приключване все още без причина и без каноничен AuditEvent (само legacy `log_audit`); P-04A/P-10 проверките не са направени. Затварянето на цикъл е в същия PUT.
* **PRJ-01-D4** — `dq_issues` е временен регистър (същата форма като CP-01/#81, до W0-07); редът в `ownership.py` е същият като в CP-01. `owner_role="admin"` за тази DQ задача — предположение (проектите се управляват от Owner/Admin, P-07).
* **PRJ-01-D5** — изтриване на **празна чернова** е оставено (FG-239 решение, P-06). Ако Крум иска никакво изтриване — DELETE става винаги 409.
* **PRJ-01-D6** — снимките още са в локалната папка, не в File Registry / customer storage (W0-06). Скритата снимка остава достъпна по файловия URL.
* **PRJ-01-D7** — `quality_score` без граници: каноничната скала на рейтинга (FLOW-039) не е определена.
* **PRJ-01-D8** — FG-240: Крум да реши дали `subcontractor_performance` влиза в миграцията към FLOW-039 или се замразява read-only. GET-овете показват `promised_amount` на всички роли (извън пакета).
* **PRJ-01-D9** — миграцията определя оригинала само по `parent_project_id` на гаранционния обект или по `--map` (решение на човек). Крум потвърждава правилото при одобрението на dry-run плана.
* **PRJ-01-D10** — архивиране/отказ следват legacy графа на статусите (Completed/Cancelled/Overhead → Archived; Draft/Paused/Stopped → Cancelled); каноничният enum от P-04 (10 статуса) не е въведен.
* **PRJ-01-D11** — като `finance._once`: ключът се маркира completed след commit; срив точно между двете оставя ключа STARTED → повторът получава 409 IN_PROGRESS.
* Бележка: `W0-03E-A2C_INVENTORY.md` е остарял и на main; не е регенериран тук (само A2B, +2 реда за новите колекции).

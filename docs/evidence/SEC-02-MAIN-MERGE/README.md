# SEC-02 — сливане на main `4bca18a` в #71

Клон `claude/sec-02-finance-read` (#71) @ `b1ab349` + `origin/main` @ `4bca18a` („Merge PR #69“; дървото е еднакво с `faa3da0` на #69). Сливането е с merge commit, без rebase и без force-push. Merge в main няма — той чака „да“ от Крум.

## Конфликти и как са решени

| Файл | Какво се сблъска | Решение |
|---|---|---|
| `backend/app/permissions/catalog.py` | `site_manager` и `accountant` в `CANONICAL_ROLES`. От main: складовите действия (TASK 5C, Р27 — фира по проект, Р35 — централен склад + история на цените). От #69: `MONEY_WRITE_ACTIONS` (Р14). От #71: финансовите четения по Р20 (`SEC02_SITE_MANAGER_COMPANY_ACTIONS`, `SEC02_ACCOUNTANT_READ_ACTIONS`, `budget.read` за Accountant — B-D1) | **И двете страни.** `site_manager` = складовите действия от main + `SEC02_SITE_MANAGER_COMPANY_ACTIONS` (досието без пари, D9). `accountant` = складовото от main + `MONEY_WRITE_ACTIONS` (#69) + `SEC02_ACCOUNTANT_READ_ACTIONS` + `budget.read` (#71). Нито едно действие не е махнато. |
| `backend/tests/test_pm_01_permission_matrix.py` | `ENFORCE_EXTRA_WRITES`. От main: `POST /api/warehouse/migration-readiness/execute` (LIVE-OPS-01 / TASK 5C, Р28). От #71: отказите на SEC-02 (export, SEC-02-E execute / update, `POST /api/alarms/evaluate` от SEC71-05) | **И двете страни** — обединение на двата списъка. |
| `frontend/src/components/DashboardLayout.js` | import-ите: `canReadFinance` (#71, R20 навигация) и `canOpenCanonicalWarehouse` (main, каноничен склад) | **И двата import-а.** Останалото се сля автоматично; навигацията ползва и двата. |
| `docs/architecture/W0-03E-A2B_INVENTORY.md` | генериран файл | **Регенериран само с инструмента** `backend/scripts/w0_03e_a2b_inventory.py` върху сливането. |
| `docs/evidence/PM-01/matrix.csv`, `run_meta.json` | генерирани файлове | **Регенерирани само с harness-а на PM-01** (`tests/test_pm_01_permission_matrix.py --harness`, реален Mongo replica set) върху сливането: 767 route-а, 18 408 клетки, 3 режима, 0 пропуснати. |

Без конфликт, но проверени:
* `docs/architecture/W0-03E-A1_INVENTORY.md` — регенериран с `backend/scripts/w0_03e_a1_inventory.py`. Заглавието е от main, таблицата е без разлика: 380 достъпа — FIXED 131, SAFE 249.
* `backend/app/services/centralized_reports.py`, `money_amount.py` (сумите с 2 знака след запетаята от #69) и route-овете на #69 се сляха автоматично. Паричните записи на #69 (права, Idempotency-Key, 2-знакови суми) са непроменени; правилата на #71 за четене (R20) са непроменени.

## PM-01 матрицата (регенерирана)

| Спрямо | Клетки | Route-ове | Какво |
|---|---|---|---|
| main `4bca18a` | **1614** | 120 | промените на #71 (`pm01_cells_vs_main_4bca18a.csv`). Това са 1599 клетки / 118 route-а от `docs/evidence/SEC-02/pm01_cells_changed.csv` (статус / wrote спрямо #69) + 15 клетки само в колоната `written`: `+ op.audit_events` на 200-те на `PUT /api/price-modifiers/org` и `/project/{id}` (FG-75) |
| #71 `b1ab349` | 627 | 33 | промените от main: 360 нови клетки (15 нови route-а × 24, предимно складът на TASK 5C) и промените на main в съществуващи route-ове (склад, `auth/reset-password`) |

## Скенерите на SEC-02 върху сливането
* GET: 5790 извиквания, **0 hits** (включва новите route-ове от main).
* POST/PUT: 4620 извиквания, **0 hits**.

## SEC71-M1 (одит, БЛОКИРАЩО) — складовият пакет беше червен върху сливането
При `eff56bf`: 1084 passed / 37 failed (main: 1121). Тестовете за отчетите на #55 (c19, c20, c22 и всички, които ползват `c22._all_reports`: c23, c24, c25, c26, c26k) викат R20-декорираните handler-и директно, без FastAPI. Декораторът вземаше заявката с `kwargs.pop("_sec02_request")` → `KeyError`.

Поправка, двете части:
1. **Fail closed** (`money_write._request_of`, `6034190`): без заявка трите декоратора (`strip_money_for_non_finance`, `strip_for_budget_view`, `strip_pulse_for_non_finance`) махат парите. Не показват нищо и не падат. Тест: `test_sec71_m1_decorators_fail_closed_without_a_request`.
2. **Тестовете на #55 подават истинска заявка за своята роля** (`a8ef905`):
   * при всяко извикване на декориран handler има `_sec02_request=_sec02_req()` — истински `starlette.requests.Request`, добавен с AST точно на тези извиквания;
   * ролята е `user=` на теста (`_user()`: „u-<tenant>“, Owner). В enforce декораторът пита **истинския** Tenant Guard и Permission Service. `warehouse_canonical_conftest.sec02_owner_in_enforce` регистрира tenant-ите на теста, активното членство на потребителя и Owner company assignment-а, който `_user()` представя. Всеки друг потребител минава през истинския loader (същият подход като c26a / c26f с `_load_assignments`);
   * **нито едно assertion не е променено.**

Резултат: **44 файла / 1121 passed** (= main) — `warehouse_suite.txt`. Файловете са пуснати поотделно, с документираната среда (`PERMISSION_SERVICE_MODE=enforce`, `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`, `MONGO_TEST_DB`). c26j е пуснат повторно самостоятелно: Mongo контейнерът се рестартира по време на общото пускане (Docker daemon-ът, не тестът) → 58 passed.

## Gates (локален реален MongoDB 7.0 rs0, файл по файл)
Виж `test_summary.txt` в тази папка.

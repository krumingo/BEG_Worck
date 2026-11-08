# OH-01 — сливане на main `fddb018` в #74

Клон `claude/oh-01-overhead` (#74) @ `31a9478` + `origin/main` @ `fddb018` („Merge PR #77“; преди това #69, #71, #80, #85). Сливането е с merge commit **`182ea57`** (родители `31a9478`, `fddb018`), без rebase и без force-push. Регенерираните доказателства (PM-01, SEC-01-C01/C02/C03) са в същия merge commit; тази папка е в следващия. Merge в main няма — чака „да“ от Крум.

## Принцип

Всички страни остават:
* **#69 (SEC-01)** — правата за запис на пари (`require_money_write`, Р14), Idempotency-Key (Р29), суми в цели центове;
* **#71 (SEC-02)** — четенията по Р20: режийните са само за финансови роли (Р20-1, `check_overhead_access`), `require_finance_read` в `full_cost.py`;
* **#77 (ACT-01)** — клиентски актове (без пресичане с режийните);
* **#74 (OH-01)** — без hard delete (архив), версии на разпределението и на snapshot-а, едно активно разпределение (pointer), Р38 етикет, един източник на режийни (FG-89/FG-127).

**Един ключ на `POST /overhead/snapshots/compute`** — пътят на OH-01 (`KeyedWrite`); правото — на #69. Самият #69 е записал в кода: „at merge, #74's version of this block wins“.

## Конфликти и как са решени

| Файл | Какво се сблъска | Решение |
|---|---|---|
| `backend/app/routes/overhead.py` — сигнатурата на compute | #69: `_sec01 = require_money_write("finance.overhead_snapshot_compute.execute")` + `idempotency_key`; OH-01: `idempotency_key` + docstring | **И двете:** `data, _sec01 (#69), idempotency_key (един Header), user`. |
| `overhead.py` — стъпка 6 на compute (2 блока) | #69: `MoneyWrite.begin(...)` + `insert_once` + audit; OH-01: `KeyedWrite("overhead.snapshot.compute")` под org/period lock, версия, supersede, Р38, audit веднъж | **Тялото на OH-01** (един ключов път; иначе една заявка би резервирала два ключа). Неизползваният `from app.permissions.money_input import MoneyWrite` е махнат. Правилата на #69 за ключа са същите: 428 без ключ, replay при същото тяло, 409 при друго, ключ per tenant+action+user. |
| `backend/app/routes/full_cost.py` — `GET /project-net-profit` | main (#77 / material waste): `material` без брак + `waste`; OH-01: Р38 полетата `overhead_recalculating` / `overhead_label` | **И двете** в един `costs` речник. И двата money-write gate-а на #69 в `full_cost.py` са запазени (`POST /overhead-snapshots`, `POST /overhead-allocation/compute/{project_id}`), както и всички `require_finance_read` на #71. |
| `backend/server.py` — startup | main: AUTH-01 индекси + ACT-01 индекси; OH-01: `ensure_overhead_indexes_for_installation` (всички tenant бази, FG-98) | **И двата блока**. |
| `frontend/src/lib/idempotency.js`, `frontend/src/lib/__tests__/idempotency.test.js` (add/add) | #74 носеше копие от ранния #69; main има разширената версия (#70 `createKeyHolder`, `apiErrorText`) | **Версията на main** — тя съдържа `createIdempotencyHolder` и `idempotencyHeaders` със същото поведение (проверено), които ползват страниците на OH-01. |
| `docs/evidence/PM-01/matrix.csv` (+ `run_meta.json`) | генерирани файлове | **Регенерирани само с harness-а на PM-01** (`tests/test_pm_01_permission_matrix.py --harness`, реален Mongo rs0): 768 route-а, 18 432 клетки, 3 режима, 0 пропуснати. |

## Последици от сливането (без текстов конфликт)

| Къде | Какво и защо |
|---|---|
| `backend/tests/test_sec_01_c03_payment_amount_idempotency.py` (assert за `overhead_compute`) | Compute на OH-01 записва и реда на period lock-а (`op.overhead_period_locks`, счетоводство на „един активен snapshot за период“, FG-86). Очакването е `["op.overhead_period_locks", "op.overhead_snapshots"]`; **„един snapshot за ключ“ (`admin_snapshots_after == 1`) е непроменено**. |
| `backend/tests/test_sec_01_c02_flow_guard_money_writes.py` (`expected()`) | `POST /overhead-allocation/compute/{project_id}` след FG-89 е **read-only проекция** на публикуваното OH-01 разпределение: финансова роля → 200, **нищо записано**; правото на #69 остава първа dependency (не-финанси → 403, чужд обект → 404). |
| `docs/evidence/SEC-01-C01/C02/C03/results.json` | Регенерирани с harness-ите си върху сливането (compute: + `op.audit_events`, `op.overhead_period_locks`; `oh_alloc`: без запис). |
| `check_overhead_access` (`overhead.py`) | Р20-1 на #71 (само Owner/Admin/Accountant и за четене) е влязъл без конфликт и важи за всички overhead route-ове на OH-01 (архив, версии, списъци). |

Без промяна, проверени с инструментите си:
* `docs/architecture/W0-03E-A1_INVENTORY.md` — изходът на `backend/scripts/w0_03e_a1_inventory.py` се съдържа изцяло в документа.
* `docs/architecture/W0-03E-A2B_INVENTORY.md` — `backend/scripts/w0_03e_a2b_inventory.py --out` дава байтово същия файл.

## PM-01 спрямо main `fddb018`

Само route-овете на OH-01 (`pm01_cells_vs_main.csv`, 36 клетки):

| Route | Клетки | Какво |
|---|---|---|
| `DELETE /api/overhead/categories/{cat_id}`, `/costs/{cost_id}`, `/assets/{asset_id}` | по 9 | Owner/Admin/Accountant × 3 режима: 404 → **428** (без ключ), нищо записано — изтриването е архив с ключ (Р29) |
| `POST /api/overhead/snapshots/{snapshot_id}/allocate` | 9 | 404 → **428** (без ключ), нищо записано |

`POST /api/overhead/snapshots/compute` е 428 и на main (#69) — без промяна.

## Gates

Виж `test_summary.txt` в тази папка.

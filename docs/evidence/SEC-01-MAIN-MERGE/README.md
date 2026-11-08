# SEC-01 (PR #69) — сливане на main `d226c49` (#72 и #70 в main)

> Merge commit (без rebase) на `origin/main` @ `d226c49` в `claude/sec-01-money-write-permissions` @ `3fb55f2`. Без deploy, без merge на PR-а.

## Конфликти и как са решени
| Файл | Решение |
|---|---|
| `frontend/src/lib/idempotency.js` | И двете страни добавиха файла. **Обединение:** `createKeyHolder` + `apiErrorText` (#70, ползвани от PaymentsPage, InvoicesPage, InvoiceEditorPage, FinancialAccountsPage) и `createIdempotencyHolder` (#69, ProjectOperationsPage, MaterialWastePanel); общи `newIdempotencyKey`, `idempotencyHeaders`. |
| `frontend/src/lib/__tests__/idempotency.test.js` | Обединение на двата набора тестове. |
| `docs/architecture/W0-03E-A1_INVENTORY.md` | **Регенериран** от кода (`scripts/w0_03e_a1_inventory.py`), заглавието от main: 377 достъпа — FIXED 131, SAFE 246. |
| `docs/evidence/PM-01/run_meta.json`, `matrix.csv` | **Регенерирани само с harness-а на PM-01** върху сливането. |

`backend/app/services/money_amount.py` — байт по байт еднакъв с main (сливането е без конфликт, както беше планирано в SEC-01-C03-B). `#72` вдига `IDEMPOTENCY_IN_PROGRESS` като 409 в `RecoverableWrite.begin`, който `MoneyWrite` вика.

## PM-01 матрицата (регенерирана)
- 18 096 клетки (= main). Спрямо **main**: точно **455** клетки = промените на #69 (SEC-01 120 + C01 65 + C02 180 + C03 54 + A 9 + C 27) — `pm01_cells_vs_main.csv`.
- Спрямо head-а на #69 (`3fb55f2`): 48 нови клетки (нови route-ове от main) и 63 променени — 7 route-а на #70 (`/finance/payments`, `/allocate`, `/invoices/{id}/payments`, `/transfers`, `/account-funding`, `/other-income`, `/other-expense`) × финансовите роли × 3 режима → **428** (Р29 на #70: PM-01 не праща ключ).

## Проверки (реална MongoDB 7.0 replica set, `-rs`)
| Набор | Резултат |
|---|---|
| SEC-01-C03 / SEC-01 / C01 / C02 / PM-01 (реален Mongo) | 6 / 8 / 7 / 9 / 6 — **36 passed, 0 skipped** |
| PAY-01 (#70) + W0-04-C01 (#72) + AUTH-01/02 + ST-02 | **952 passed** |
| R0 | **814 passed** |
| W0 (DB-free) | **1094 passed / 15 failed / 79 skipped** — същите 15 `test_w0_03e_legacy_routes` (main добави W0 тестове) |
| Guards | A1 436 / 0, A2C 216 / 0 |
| Frontend | `yarn test` 7 suites / **116 passed**; `yarn build` — Compiled |

---

# Второ сливане: main `cd03324` (#55 TASK 5C склад, #78)

Merge commit (без rebase) на `origin/main` @ `cd03324` в `claude/sec-01-money-write-permissions` @ `b2b3ae0`.

## Конфликти и как са решени (и двете поведения запазени)
| Файл | Решение |
|---|---|
| `app/permissions/catalog.py` | Обединение: действията на SEC-01/C01/C02 **и** складовите действия на TASK 5C; ролята Accountant получава складовите четения/фира на #55 **и** `MONEY_WRITE_ACTIONS` на #69. |
| `app/routes/procurement.py` | И двата импорта: `require_money_write` (#69) и legacy-writer guard на #55. |
| `app/routes/sales.py` | `POST /sales/commit`: тялото на #55 (**410** `SALE_DEPLETION_PENDING_CANONICAL_ACTION`, нищо записано) + guard-ът на #69 като първа зависимост → нефинансова роля **403**, финансова **410**. |
| `tests/test_pm_01_permission_matrix.py` | Обединение на `ENFORCE_EXTRA_WRITES` (#69 парите + #55 migration execute). |
| `docs/evidence/PM-01/matrix.csv`, `run_meta.json` | **Регенерирани само с harness-а**, реален Mongo, 0 skipped. |
| `docs/architecture/W0-03E-A1_INVENTORY.md` | Регенериран от кода (380 достъпа — FIXED 131, SAFE 249). |

## PM-01
- 18 408 клетки (= main). Спрямо **main `cd03324`: точно 455** клетки = промените на #69 (`pm01_cells_vs_main_cd03324.csv`).
- Спрямо head-а на #69: 312 нови клетки и 177 променени — всички от #55: пенсионираните складови писачи (`warehouse/batches`, `/consume`, `warehouse-issue`, `warehouse-return`, `project-consumption`, `post-to-warehouse`, `sales/commit`) → **410**.

## Доказателство на SEC-01-C02
`results.json` регенериран с harness-а: точно **18** реда променени = `sales_commit` × 3 финансови роли × 2 фирми × 3 режима, 201 (пише) → **410, нищо**. Тестът на C02 следва #55 (финансова роля → 410).

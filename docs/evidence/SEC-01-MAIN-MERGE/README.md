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

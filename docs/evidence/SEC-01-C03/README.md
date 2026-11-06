# SEC-01-C03 — сума и повторна заявка при плащания (одит на PR #69)

> Пакет: `docs/architecture/tasks/SEC-01-C03_PAYMENT_AMOUNT_IDEMPOTENCY.md` (клон `claude/happy-meitner-bmcnel` @ `407a034`) — прилагане на канона, без ново бизнес решение: CLAUDE.md §14 (validation/DQ + idempotency key за всеки consequential write), FLOW-006, Р14, Р16.
> Находки: одит на `f33b2ba` в PR #69 (`docs/audit/probes/sec01/probe_sec01_c02_payments.py` @ `claude/audit-log`).
> База: PR #69 @ `471eaaa`. Само нов commit. Няма миграция, няма промяна на данни.

## 1. Сумата — крайно число > 0, иначе 422 и нищо записано

Нов модул `backend/app/permissions/money_input.py`, функция `money_value(value, field, allow_zero=False)`:

- приема JSON число или числов низ (формите пращат низове);
- отказва `None`, булеви, `""`, `"abc"`, `"1,5"`, `NaN`, `±Infinity`, всичко, което препълва float (`"1e309"`, `10**400`), отрицателни и 0 → **422 `AMOUNT_INVALID`** (`detail.field` казва кое поле);
- горен лимит: в канона и моделите няма → само крайност (`1e300` минава).

Проверката е в началото на handler-а, след охраната за права и **преди всяко четене/запис**:

| Route | Поле | Файл |
|---|---|---|
| `POST /api/finance/cash-transactions` | `amount` | `routes/reports.py` |
| `POST /api/finance/overhead-transactions` | `amount` | `routes/reports.py` |
| `POST /api/finance/bonus-payments` | `amount` | `routes/reports.py` |
| `POST /api/overhead-snapshots` | `amount` | `routes/full_cost.py` |
| `POST /api/subcontractor-payments` | `amount` (> 0), `vat_amount` (≥ 0, по избор) | `routes/subcontractors.py` |
| `POST /api/labor-entries` | `hours` | `routes/labor_smr.py` |
| `POST /api/projects/{project_id}/material-waste` | `qty` | `routes/material_waste.py` |

Промени в поведението, които се виждат:

- cash/bonus/overhead: досега **нямаше никаква** проверка (липсваща сума → ред с 0, низ → записан като низ). Сега сумата се записва като число.
- subcontractor payment: досега `amount <= 0` → **400** след четенето на пакета; сега → **422** преди него.

## 2. `Idempotency-Key` — повторът не плаща втори път

Използван е **съществуващият** механизъм: каноничният W0-04 регистър (`app/audit/idempotency.py`, колекция `audit_idempotency` в базата на фирмата) през `RecoverableWrite` (`app/permissions/workflow.py`) — същото като `PUT /users/{id}` (`Idempotency-Key`, `routes/auth.py`). `MoneyWrite` в `money_input.py` е тънка обвивка:

| Случай | Отговор |
|---|---|
| същият ключ + същото тяло | **201 с оригиналния отговор**, нов ред няма |
| същият ключ + друго тяло | **409 `IDEMPOTENCY_CONFLICT`**, нищо записано |
| същият ключ, докато първата заявка още тече | **409 `IDEMPOTENCY_IN_PROGRESS`** (може да се повтори) |
| първата заявка е паднала по средата | същата заявка я довършва: id-тата са изведени от ключа, вече направен insert се пропуска (`needs_insert`; самият `insert_one` остава в route-а, видим за A1 guard-а), одит редът е стъпка — нищо не се записва два пъти |
| **без ключ** | приема се както досега (всяка заявка е нова команда) — за да не се чупят сегашните клиенти |

- Ключът е с обхват **фирма + действие + потребител**: чужд ключ никога не връща (и не показва) чужд отговор.
- Ключ над 200 знака → 422.
- Плащането към подизпълнител: двата реда (Outflow в `finance_payments` и записът в `subcontractor_payments`) + `log_audit` минават под един ключ; сумите на пакета се преизчисляват (идемпотентно).

**Фронтенд** (`frontend/src/lib/idempotency.js`): формата пази **един ключ, докато тялото е същото** (повтор след timeout или двоен клик → същия ключ) и взима нов ключ при промяна на тялото или след успех. Включено в:
- `pages/ProjectOperationsPage.js` — плащане към подизпълнител и режийни (`/subcontractor-payments`, `/overhead-snapshots`);
- `components/MaterialWastePanel.js` — фира.

`cash/bonus/overhead-transactions` и `labor-entries` нямат форма във фронтенда (grep) — сървърът е готов, клиентът ще праща ключ, когато има.

Грешките 409/422 вече се показват с текста си (`detail.message`), не като `[object Object]`.

## 3. SEC-R1 — потвърдено на `471eaaa`

Одитът е проверил `f33b2ba`; поправката е в `471eaaa` (Допълнение A към C02). Потвърдено в два теста на реален Mongo:

- `test_sec_01_c02_flow_guard_money_writes.py` (матричният тест на парите) **вече съдържа** пробата: изтекло членство (Technician, P2) и бъдещо (SiteManager, P2) → 403, нищо записано, трите режима. Минава.
- В C03 harness-а е добавена същата проба отново, на текущия head: P1 (членство без дати) → 201; P2 (изтекло/бъдещо) → 403 и нищо записано, за труд и фира, off/shadow/enforce (`results.json` → `sec_r1`).
- PM-01 матрицата (752 route-а) работи върху ST-01 **без членства** по дизайн (`test_the_fixture_has_no_project_membership`), затова там проба за членство не се добавя.

## Резултат (реална MongoDB 7.0 replica set, ST-01 фирма A + съществуващите записи на PM-01/C02; актьор Accountant)

`results.json`:

- **207 извиквания с невалидна сума** (`nan`, `inf`, `-inf`, `1e309`, `""`, `abc`, `-1`, `0`, липсваща) × 8 проби × 3 режима → всички **422, 0 бизнес записа** (oplog).
- За всяка проба и режим: валидна без ключ → 201, 201 и **2 реда** (старото поведение); същият ключ два пъти → 201, 201, **1 ред**, вторият отговор е идентичен с първия и не пише нищо; същият ключ с друго тяло → **409, нищо записано**. При плащането към подизпълнител — **точно 1 Outflow** в `finance_payments` за ключовата серия.
- SEC-R1: виж т. 3.

**PM-01 матрицата (всички 752 route-а), ново пускане:** точно **54 клетки** са променени = 6 route-а × 3 финансови роли (Owner/Admin/Accountant) × 3 режима (`pm01_cells_changed.csv`). PM-01 праща тяло само със задължителните полета, т.е. **без сума**:

| Route | Преди | Сега |
|---|---|---|
| cash / bonus / overhead transactions, overhead snapshots, labor entries | 201, **пише ред със сума 0** (или `None`) | 422, нищо записано |
| subcontractor payments | 404 (несъществуващ пакет) | 422 (сумата се проверява първо), нищо записано |

Фирата не е променена (PM-01 праща `qty: 1`). Нефинансовите клетки не са променени (403 остава преди проверката на сумата). `matrix.csv` и `run_meta.json` са регенерирани.

## Дълг (записан, не поправен)

- **SEC-01-C03-D1:** заявка **без** ключ все още може да се повтори (старите клиенти, API без ключ). Задължителен ключ за парите е решение за Крум / W0-05.
- **SEC-01-C03-D2:** атомичността на резервацията при **едновременни** заявки с един ключ разчита на уникалния индекс на `audit_idempotency.id` (`scripts/w0_04_bootstrap_audit_indexes.py`). Без пуснат bootstrap две едновременни заявки могат и двете да започнат. Последователен повтор е защитен и без индекса.
- **SEC-01-C03-D3:** заявка, прекъсната без да стигне до `fail` (срив на процеса), оставя ключа „started“ → повторът получава 409 `IDEMPOTENCY_IN_PROGRESS` завинаги за този ключ (fail-closed: нито едно двойно плащане). Изход: нов ключ. Таймаут на резервацията — W0-05.
- Плащането над `certified_total` все още се приема (одитът: бизнес правило за Крум).
- Остават: SEC-01-C02-D1 (без W0-05 write service, Approval, сторно, транзакция), D2–D6, SEC-01-D1, C01-D2, C01-D4, FG-28.

## Rollback

Revert на commit-а. Няма миграция. Редовете в `audit_idempotency` са счетоводство на регистъра и не пречат на стария код.

## Как се повтаря

```bash
cd backend
PYTHONPATH=. pytest tests/test_sec_01_c03_payment_amount_idempotency.py -v --noconftest
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
  PYTHONPATH=. pytest tests/test_sec_01_c03_payment_amount_idempotency.py -v --noconftest
PYTHONPATH=. python tests/test_sec_01_c03_payment_amount_idempotency.py --harness \
  --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
```

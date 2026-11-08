# WH-REV-01 — сторно на получена доставка от доставчик: доказателства

Пакет: `docs/architecture/tasks/WH-REV-01_SUPPLIER_RECEIPT_REVERSAL.md` (на `claude/happy-meitner-bmcnel` @ `0accacb`).
Клон: `claude/wh-rev-01-receipt-reversal` от `main` @ `cd03324`.
Канон: FLOW-009 (корекция чрез обратно движение), FLOW-043 D-04 (един път на разход), CLAUDE.md §2.9 (без hard delete), §7 (сторно, не редакция), §14.

## Пропуската (възпроизведена първо)

На `main` @ `cd03324` след първото свързано движение разпределението на ред от фактура е заключено (409, FG-109 / F-55-C26-03). Канонично сторно на получаване няма, затова грешното засичане не може да се поправи.

`tests/test_wh_rev_01_receipt_reversal.py` пуснат върху `cd03324`: **75 failed / 1 passed** (`base_main_cd03324.txt`).

## Какво е направено

- **Нов endpoint:** `POST /api/warehouse/canonical/receipts/{movement_id}/reverse`. Тялото е `{reason, notes?}`, а `Idempotency-Key` е задължителен хедър (Р29: без ключ → 428, нищо не е прочетено или записано).
- **Сторното е нов ред в регистъра:**
  - действие `reverse_supplier_receipt` (складово получаване) или `reverse_supplier_receipt_to_project` (директна доставка);
  - `reverses_movement_id` сочи оригинала;
  - в транзакцията взема точно слоя на получаването `(receipt, 1)` от кофата, която получаването е отворило, по неговата собствена цена, обратно към доставчика;
  - **оригиналният ред остава** — нищо не е изтрито или редактирано.
- **Решението е в транзакцията на движението:**
  - получаването съществува и е от правилния вид → иначе 422 `RECEIPT_NOT_REVERSIBLE`;
  - не е сторнирано → иначе 409 `RECEIPT_ALREADY_REVERSED`;
  - целият му слой още е в кофата → иначе 409 `RECEIPT_ALREADY_ISSUED`, с изброени движенията, които са го взели (те се сторнират / връщат първо).
- **Свързано получаване** (`invoice_line_id`):
  - сторното взема същото заключване на реда от фактура (C26l Addendum K) и покритото количество пада атомарно;
  - всички четения на свързани получавания (покрито количество, FG-109 заключване, Path B, over-link / project-conflict предупреждения, ценова история) пропускат сторнираните (`warehouse_movements/reversal.py`);
  - затова разпределението се отключва и може да се поправи;
  - редът на сторното носи `reversed_invoice_line_id` (само следа, никога `invoice_line_id`).
- **Разход:** сторнирана директна доставка дава ред `receipt_reversal` с −V в разхода на обекта (нов `COST_KIND`). Rebuild минава през същия projector.
- **Права (R16 / R28):** същото право като получаването — `warehouse.receive_from_supplier` или `..._to_project` — във всеки режим. Стойностите в отговора следват value policy-то (Р20 / Р32). `/movements` отказва действията за сторно (422): само новият път ги записва.
- **AuditEvent:** в транзакцията на движението (`structured_diff.reverses_movement_id`). При срив след него няма запис; повторение със същия ключ дава един запис.

## Тестове — `tests/test_wh_rev_01_receipt_reversal.py` (real Mongo rs, off / shadow / enforce): 76 passed

| Тест | Какво доказва |
|---|---|
| `test_gap_a_locked_line_is_corrected_through_a_receipt_reversal` | заключен ред → сторно 201 → преразпределението минава; оригиналът остава |
| `test_warehouse_receipt_reversed_reallocated_and_delivered_again` | склад: сторно → наличност 0 → L към Q → нова доставка в Q → P/Q 0/100, партидата е източена; live + rebuild ×2 |
| `test_direct_delivery_reversed_the_project_cost_follows` | директна: P canon 100 → сторно → canon 0, Path B 100 (фактурата още е на P) → L към Q → доставка в Q → P/Q 0/100 (Q canon 100, Path B 0); live + rebuild ×2 |
| `test_reversal_of_an_issued_lot_is_409_and_names_what_took_it` | изпратени 4 от 10 → 409 `RECEIPT_ALREADY_ISSUED`, `taken_by` = изпращането, остават 6; нищо записано |
| `test_reversal_of_a_consumed_direct_delivery_is_409` | вложени 3 от директната доставка → 409 |
| `test_double_reversal_wrong_kind_unknown_and_missing_key` | второ сторно → 409; сторно на сторно → 422; непознат / чужд tenant → 404; без ключ → 428 |
| `test_movements_endpoint_refuses_a_reversal_action` | `/movements` не приема сторно |
| `test_same_key_is_one_reversal_and_a_crash_after_the_audit_event_writes_nothing` | срив след AuditEvent → 0 реда, 0 събития; същият ключ → един ред, едно събитие (replay); същият ключ с друга причина → 409 |
| `test_reversal_racing_an_issue` ×10 × 3 | сторно ∥ изпращане на 4: печели точно едното, наличността никога не е отрицателна; live + rebuild ×2 |
| `test_rights_are_the_rights_of_the_receipt` (8 роли × 3 режима) | Owner / Admin: и двете; Warehousekeeper: само складово; Accountant / SiteManager / Technician / Viewer / Driver: 403, нищо записано |

## Gates (fresh Mongo per file)

- `regression_per_file.txt`:
  - WH-REV-01, R0, warehouse canonical, `test_codex_c23_independent`, PAY-01, AUTH, R0-03, ST-02 и permission тестовете (вкл. PM-01) → **3368 passed**;
  - първите 2 failure-а (речникът на действията и frontend копието на правата) са поправени и пуснати отново: **32 passed**.
- **W0** (`w0.txt`): **1094 / 15 / 83**, същите 15 както на `main`. 83 skipped, защото real-Mongo W0 тестовете искат `W0_03_REAL_MONGO_URL`; PM-01 по-долу е пуснат с реален Mongo.
- **Guards** (`guards.txt`): A2C **0** (235 модула), A1 **0** (474 единици).
- **PM-01** (`docs/evidence/PM-01/`, регенериран с harness-а срещу реален Mongo replica set):
  - **6 passed, 0 skipped**;
  - новият маршрут дава еднакъв отговор в трите режима: 428 без ключ за ролите с `warehouse.write_command`, 403 за останалите;
  - нищо не е записано.
- **Inventories:** W0-03E-A1 и A2B са регенерирани (A1: 377 достъпа, нито един UNSCOPED; A2B: само изместени номера на редове).
- **Frontend:** `yarn test` 17 suites / 170 passed; `yarn build` OK. `warehouseCanonicalAccess.json` носи двете нови действия, а изборът на команда ги изключва, защото `/movements` не ги приема.

## Отворено

- Няма UI бутон „Сторно“: пакетът изисква API, тестове и права. Екранът за сторниране е отделна задача, ако Крум го иска.

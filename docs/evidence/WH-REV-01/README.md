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

## Допълнение A (08.11) — FG-195, FG-197, Р46, Р47

- **FG-197 (празна причина):** `e9633aa` — причината се изчиства; празна → 422 `REASON_REQUIRED`, нищо не е записано (route + service).
- **FG-195 (тихо преместване на разход след сторно):** промяна на разпределение / qty / мярка / цена на ред, чиито свързани получавания са сторнирани, е **корекция** — при всеки статус на фактурата, вкл. Paid:
  - без причина → **409 `ALLOCATION_CORRECTION_REQUIRED`** (същият код като #81 за проста промяна на Paid фактура), нищо не е записано;
  - с причина → в една транзакция под заключването на реда се записват промяната, версия на реда преди нея (`invoice_versions`, kind `invoice_line_correction`) и каноничен AuditEvent `invoice_line.allocation_corrected` (before/after, сторнирани получавания, статус на фактурата);
  - ред, който никога не е бил свързан, следва старото правило;
  - PUT на ред от Paid фактура остава отказан от правилото „само Draft“ (400).
  - **#81:** ще добави endpoint / версия за корекция на разпределение на Paid фактура. PR-ът, който се слее втори, ги обединява.
- **Р46 (FG-194):** право на сторно = Warehousekeeper, Accountant, Owner, Admin, и за двата вида:
  - нови действия в каталога `warehouse.reverse_supplier_receipt` и `warehouse.reverse_supplier_receipt_to_project` (по едно разрешение на действие);
  - маршрутът и услугата ги проверяват във всеки режим;
  - Procurement вече не сторнира;
  - копието на правата във frontend е обновено.
- **Р47 (FG-196):** модел за кредитно известие няма, затова е минимален:
  - в транзакцията на сторното на свързано получаване се записва `expected_credit_notes` — очакван кредит = сторнираният дял от реда с ДДС, плюс DQ задача към Счетоводителя „очаква кредитно известие“;
  - фактурата се маркира `awaiting_credit_note`; този запис уважава заключването на плащане от PAY-01 (409 `INVOICE_BUSY`, докато плащане я държи);
  - `GET /api/finance/expected-credit-notes` (Owner / Admin / Accountant) показва задачите;
  - плащане (quick-pay и allocate — всички пътища на FLOW-006 към фактура) над нетно полученото → **409 `INVOICE_AWAITS_CREDIT_NOTE`**, нищо не е записано;
  - **дълг към t26:** пълно кредитно известие (регистриране, закриване на очакването, счетоводен модел).
- **Не е направено (по пакета):** Approval за сторно (FG-22 / W0-07) — дълг.

### Тестове и gates след допълнението
- `test_wh_rev_01_receipt_reversal.py`: **101 passed**. Нови тестове:
  - FG-195: Paid + allocate, PUT при Draft, ред без връзка;
  - Р46: матрица с 8 роли + procurement в enforce;
  - Р47: очакван кредит, DQ задача, quick-pay и allocate 409, replay, `INVOICE_BUSY`.
- Base `e9633aa` (`-k "fg195 or r46 or r47"`): **13 failed / 3 passed**. Трите са редът без връзка, който важи и на base.
- Пълна регресия на дървото преди последните промени: 3391 passed. Единственият failure беше `test_every_canonical_action_maps_to_a_distinct_permission` — оправен с отделни разрешения. Три грешки на ST-02 fixture-а бяха временни (162 passed при повторение).
- Финални gates на крайното дърво: WH-REV-01 101, C26l-L 153, C26l-N 72, shape 12, c19 25, actions 7, C26e (матрица на режимите) 272, PAY-01 reversal 91, PAY-01 serialisation 108 — **всички passed**.
- W0: **1094 / 15 / 83**, същите 15. A2C **0** (235), A1 **0** (474).
- PM-01 регенериран с harness-а срещу реален Mongo: **6 passed, 0 skipped**.
- Inventories: A1 379 достъпа, 0 UNSCOPED; A2B добавя `expected_credit_notes` (TenantData).
- Frontend: 170 passed, build OK.

## Допълнение B (09.11) — merge на `main` @ `1525a1e` (#81)

`main` е слят с merge commit (двете страни запазени). WH-REV-01 приема механизмите на #81:

- **FG-213 — една корекция:**
  - сторнираният ред вече използва полето на #81 `correction_reason` (в allocate и PUT); собственото `reason` и записът в `invoice_versions` отпадат;
  - версията е в `invoice_line_allocation_versions` (id `{line}:v{n}`, брояч `allocation_version`), с `reversed_receipts`;
  - събитието е едно — `finance.invoice_line.allocation_corrected` (`audit_allocation_change`, разширено с `extra`: сторнирани получавания и промени в qty / мярка / цена);
  - без причина → 409 `ALLOCATION_CORRECTION_REQUIRED`. При Paid фактура първа отговаря проверката на #81 (същият код).
  - `@staticmethod` е запазен на `_plan_receipt_reversal` / `_expect_credit_note` / `_bind_invoice_line_price`.
- **FG-214 — DQ в `dq_issues`:**
  - `expected_credit_notes` пази само очакването;
  - задачата „очаква кредитно известие“ е един отворен `dq_issues` (`dq-credit-note-{invoice}`, тип `INVOICE_AWAITS_CREDIT_NOTE`, owner accountant) + `alarm_events`;
  - AuditEvent `dq.credit_note.opened` в транзакцията на сторното (`invoice_allocation.sync_credit_note_issue`);
  - replay не добавя втори запис.
- **FG-216:** тестовете засяват `md_item` (Master вече е strict в route-а).
- **#81 заключване на доставната фактура:** сторното взема и увеличава същото `link_lock_seq` на доставната фактура, което получаването е взело.
- **Р45 (разпределение по ред)** идва от `main` без промяна.
- Inventories (A1: 394 достъпа, 0 UNSCOPED; A2B) и PM-01 са регенерирани с инструментите им.

### Gates след merge-а (реален Mongo rs, fresh per file)
- WH-REV-01 **101**; R0 **814**; PAY-01 **630**; SEC-01 **30**; SEC-02 **31**; warehouse canonical (44 файла) **1121** — всички passed, 0 failed.
- PM-01 (harness): **6 passed, 0 skipped**.
- W0: **1176 / 16** — същите 16 failure-а като `main` @ `1525a1e` (пуснат отделно за сравнение).
- Guards: A2C **0** (243 модула), A1 **0** (490 единици).
- Frontend: `yarn test` **182 passed**, `yarn build` OK.
- `@staticmethod` проверен с AST на `_plan_receipt_reversal`, `_expect_credit_note`, `_bind_invoice_line_price`, `_lock_invoice_line`.

## Допълнение C (09.11) — WHREV82-M1 (AUDIT-2): сторнирано получаване отключва доставната фактура
- **Проблем (probe `docs/audit/probes/whrev01/test_probe_whrev01_silock.py` на `claude/audit-log`):** `procurement._supplier_invoice_link` броеше и сторнирано получаване. След сторно 201 редакцията на редовете на доставната фактура оставаше 409 `SUPPLIER_INVOICE_LINKED` завинаги.
- **Поправка:** същото правило `warehouse_movements.reversal.without_reversed` в транзакцията на заключването. Сторнираното получаване и редът на сторното не заключват. Ново, живо получаване заключва отново.
- **Red на `e07320d`:** probe 3 failed (off / shadow / enforce); новият тест `test_whrev82_m1_*` 3 failed — 409 `SUPPLIER_INVOICE_LINKED` след сторното.
- **Green:**
  - probe 3 passed; `test_wh_rev_01_receipt_reversal.py` **104 passed**;
  - WH-FIX-01 a3 138, f81 132, post_55 47; SEC-01 30; SEC-02 31 — всички passed;
  - A2C 0 / A1 0; inventories регенерирани — без промяна.

## Допълнение D (09.11) — Codex CHANGES_REQUESTED: F-82-01, F-82-02 (Р47: платено ≤ нетно получено)
- **F-82-01 [P1] — сторно след вече завършено плащане:**
  - в транзакцията на сторното, след CAS-а на фактурата (той сериализира сторното спрямо PAY-01 плащанията), се четат активните `payment_allocations` и всички очаквани кредити, вкл. това сторно;
  - ако платеното е над `total − кредити` → **409 `INVOICE_PAID_ABOVE_NET`**, нищо не е записано;
  - плащане никога не се анулира автоматично (първо се сторнира в FLOW-006).
- **F-82-02 [P2] — quick-pay с 0.01 над лимита:**
  - едно общо правило `services/credit_note_rule.py`: цели центове, без толеранс;
  - едно и също в quick-pay и allocate (`finance._r47_refusal`) → 409 `INVOICE_AWAITS_CREDIT_NOTE`, без паричен запис.
- **Red на `108afc0`:** новите тестове — **12 failed** / 3 passed. Трите са точната граница („платено = нетно“), която минава и преди, и след поправката.
- **Нови тестове (off / shadow / enforce):**
  - плащането завършва първо (сторното е задържано след проверката на правата, преди транзакцията);
  - вече платена фактура;
  - точна граница;
  - net 0 срещу 0.01;
  - 1 цент над положително net (quick-pay + allocate);
  - unit тест на правилото.
- **Green:**
  - WH-REV-01 **120 passed**; R0 **814**; PAY **630**; SEC-01 **30**; SEC-02 **31**; warehouse 44 файла **1121** — всички passed;
  - W0 **1176 / 16** (същите 16 като `main` @ `1525a1e`); A2C **0** (244), A1 **0** (492);
  - PM-01 harness **6 passed, 0 skipped**; inventories регенерирани — без промяна.

## Допълнение E (14.11) — Р84 (FG-570): връщане по вече платена фактура
Канон: Р84 (Крум, 14.11.2026, `claude/happy-meitner-bmcnel` @ `01845564`), като Р49(6).

**Какво се променя.** Сторното вече **не се отказва** с 409 `INVOICE_PAID_ABOVE_NET` (премахнат). Връщането се записва в склада.

**Вземане към доставчика.**
- Ако фактурата е платена над нетната стойност, която сторното оставя (`total − очаквани кредити`), надплатената част от **това** сторно става **едно вземане** в `supplier_claims`.
- Вземането е ограничено до кредита на сторното и намалено с вече отворените вземания.
- Идентификаторът е детерминиран (`claim_{movement}`), а записът е `$setOnInsert` → повторението не добавя второ.
- Вземането е свързано с фактурата, сторното, получаването и очакването (`expected_credit_note_id`).
- Пази основата: обща сума, платено, очакван кредит.
- Записва се в транзакцията на движението, с AuditEvent `finance.supplier_claim.opened` (само при първото записване).

**Без автоматично нетиране.** Плащането и статусът на фактурата не се пипат.

**Дълг.** Връщане на сумата (FLOW-006) или изрично прихващане по Р49(6) са след #84 / t26. При merge с #84: вземането се съгласува с изчисленото там `credit_balance`, за да няма двоен източник.

### Тестове (off / shadow / enforce)
- **Платено 120, връщане 48** (принуден ред: плащането завършва първо) → движението е записано; очакване 48; **вземане 48**; 1 AuditEvent; плащането (120) и статусът Paid остават.
- **Платено 100** → вземане **28** (само надплатеното).
- **Повторение със същия ключ** → 1 ред, **1 вземане**, 1 AuditEvent.
- **Неплатено / платено точно нетното (72)** → без вземане; пътят по Р47 е непроменен (очакване 48, плащане 0.01 → 409 `INVOICE_AWAITS_CREDIT_NOTE`).
- Unit тест на `overpaid_cents`.

**Red на `cd454ea`:** новите тестове — 9 failed (409 `INVOICE_PAID_ABOVE_NET`) / 3 passed. Трите са пътят без надплащане.

### Gates на `642227b` (реален Mongo rs, fresh per file)
- WH-REV-01 **123**; warehouse 44 файла **1121**; PAY **630**; SEC-01 **30**; SEC-02 **31**; R0 **814** — всички passed, 0 failed.
- W0 **1176 / 16** — същите 16 като `main` @ `3863610`.
- A2C **0** (245); A1 **0** (494).
- PM-01 harness **6 passed, 0 skipped**; `run_meta.json` както го е написал harness-ът (779 маршрута / 18696 клетки).
- Inventories: A1 без промяна (394); A2B добавя `supplier_claims`.

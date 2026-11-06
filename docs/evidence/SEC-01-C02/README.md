# SEC-01-C02 — останалите записи на пари извън правилата (FLOW Guard)

> Пакет: `docs/architecture/tasks/SEC-01-C02_FLOW_GUARD_MONEY_WRITES.md` (клон `claude/happy-meitner-bmcnel`), одобрен от Крум 06.11.2026 (Р9, Р14, Р16 — `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`).
> Находки: `docs/flow-guard/DIVERGENCES.md` @ `claude/flow-guard` — FG-24, FG-26, FG-27, FG-30, FG-31.
> FLOW-002 (роли/права), FLOW-006 (единен платежен регистър), FLOW-028 (трудът е основа за заплата), CLAUDE.md §2.5, §2.9, §7. W0-02 Permission Service, W0-05 (не е започнат).
> База: PR #69 @ `aee3169`. Само нови commit-и. Няма миграция, няма промяна на данни.

## FG-27 — плащане към подизпълнител

`POST /api/subcontractor-payments` (`routes/subcontractors.py:500`):

1. **Кой:** само Owner/Admin/Accountant (Р14), действие `finance.subcontractor_payment.create`. Всички други — 403, нищо записано, в трите режима.
2. **През единния регистър:** до W0-05 единният платежен регистър на FLOW-006 е `finance_payments` (`IMPLEMENTATION_WAVES.md` W0-05: „един `finance_payments` write service“). Досега плащането се записваше в `subcontractor_payments` **винаги**, а в `finance_payments` — **само ако** се намери сметка. Тоест можеше да има плащане извън регистъра.
   - Сега: ако сметката не се намери → **409 `PAYMENT_LEDGER_ACCOUNT_REQUIRED`**, преди какъвто и да е запис. Подадена несъществуваща `account_id` → 404, нищо.
   - Иначе първо се пише редът в `finance_payments` (Outflow), после записът в `subcontractor_payments`, който сочи към него (`finance_payment_id`), и обратно (`subcontractor_payment_id`). Добавен е `log_audit` (както при другите плащания във `finance.py`).
   - **Няма втори регистър:** `subcontractor_payments` остава запис за разпределение по пакета, не отделен ledger.
3. **Дълг SEC-01-C02-D1:** записът не минава през W0-05 write service (няма такъв), няма idempotency key, няма Approval и няма API за сторно. Двата записа не са в една транзакция. За W0-05 / R1 Payment.

## FG-24 — труд и фира за член SiteManager/Technician (Р16)

Потвърдено с нова проба (`labor_create`, `waste_create`, `labor_sync`): член SiteManager и член Technician на P1 → 201/200 и записват; на P2 (не са членове) → 403; Viewer и Driver — 403, дори като членове. Еднакво в off/shadow/enforce.

Тестовете не заключват грешното поведение: `tests/test_sec_01_money_write_permissions.py` работи върху ST-01 без никакво членство (нов тест `test_the_fixture_has_no_project_membership`), затова отказът там е отказ за **не-член** — точно Р16. Добавен е коментар `R16_PATHS`, че файлът не твърди „SiteManager никога не пише труд“.

## FG-26 — sync на труда без изтриване

`POST /api/labor-entries/sync-from-work-reports` (`routes/labor_smr.py:90`) вече **не прави `delete_many`**. Сравнява редовете, които дават работните отчети сега, с активните синхронизирани редове:

| Случай | Какво се записва |
|---|---|
| същият ред | нищо |
| ред, който отчетът вече не дава (напр. 3 ч → 1 ч) | **сторно ред** (−часове, −стойност, същата дата и пакет, `entry_kind="reversal"`, `reverses_entry_id`), а оригиналът получава `reversed_by_entry_id`; не се трие и не се редактира |
| нов ред | вмъква се |

Втори sync без промяна не пише нищо. Сумите (заплата, печалба, режийни) остават верни без филтър, защото сторното носи отрицателните стойности. Броячите на „несвързани записи“ (`labor-warnings`, `full_cost.py`) броят само активните редове (`ACTIVE_LABOR_ROW`). Закрива дълг SEC-01-C01-D3.

Доказателство (`results.json` → `sequences.labor_sync`): SiteManager член, два sync-а; 0 изтривания в oplog-а; двата seed реда са налице; 3 ч + сторно −3 ч + 1 ч; сума 3 ч / 60 EUR; вторият sync — `[]`.

## FG-30 — останалите парични записи

Всички — Р14 (Owner/Admin/Accountant), guard като **първа** зависимост, преди всяко четене:

| Route | Файл:ред | Действие |
|---|---|---|
| `POST /api/client-acts/{act_id}/confirm` | `routes/revenue_expense.py:168` | `revenue.client_act_confirm.execute` |
| `POST /api/subcontractor-acts/{act_id}/confirm` | `routes/subcontractors.py:433` | `subcontract.act_confirm.execute` |
| `PUT /api/supplier-invoices/{inv_id}` | `routes/procurement.py:368` | `procurement.supplier_invoice.update` |
| `POST /api/worker-calendar` | `routes/overhead_realtime.py:63` | `overhead.worker_calendar.create` |
| `PUT /api/worker-calendar/{entry_id}` | `routes/overhead_realtime.py:104` | `overhead.worker_calendar.update` |
| `POST /api/worker-calendar/bulk` | `routes/overhead_realtime.py:128` | `overhead.worker_calendar_bulk.execute` |
| `POST /api/worker-calendar/sync-from-sessions` | `routes/overhead_realtime.py:163` | `overhead.worker_calendar_sync.execute` |
| `POST /api/overhead-allocation/compute/{project_id}` | `routes/full_cost.py:192` | `finance.overhead_allocation.execute` |
| `PUT /api/ocr-invoice/{intake_id}/approve` | `routes/ocr_invoice.py:180` | `ocr_invoice.intake.approve` |
| `POST /api/sales/commit` | `routes/sales.py:200` | `sales.sale_commit.execute` |
| `POST /api/pricing/refresh` | `routes/pricing.py:45` | `pricing.material_price_refresh.execute` |

`POST /api/worker-calendar` и `sync-from-sessions` не са в списъка на FG-30, но пишат същата колекция (същият принцип като C01: всички записи по ресурса). `PUT /api/fixed-expenses` вече има О/А/Сч проверка — не е пипан. В нито един от тези route-ове няма hard delete.

## FG-31 — PM-01 отчетът

`docs/architecture/PM-01_PERMISSION_MODE_REPORT.md`: §5.1 е обозначен като **долна граница** с препратка към пробите върху съществуващи записи; в §5 е отбелязано, че за труд и фира правилото е Р16, не каталогът.

## Резултат (реална MongoDB 7.0 replica set, ST-01 фирми A и B + съществуващи записи)

`results.json` — 1047 извиквания: 16 проби × 8 роли × 2 фирми × (P1 и P2 за проектните) × 3 режима + B→A върху записи/обекти на A. Записът се мери от oplog-а, с `org_id` на всеки ред; за всяко извикване се проверява и че **няма нито едно изтриване**.

| | off | shadow | enforce |
|---|---|---|---|
| Финансова роля | 200/201, пише само във фирмата си | същото | същото |
| Плащане без сметка (фирма B) | **409, нищо** | 409 | 409 |
| Друга роля | **403, нищо записано** | **403, нищо** | **403**, само `audit_events` |
| Р16 член P1 / не-член P2 | 201 / 403 | същото | същото (+AuditEvent) |
| B → запис на A | 404 (финанси), 403 (други), нищо в A | същото | същото |

**PM-01 матрицата (всички 752 route-а), ново пускане:** точно **180 клетки** са променени = 12-те route-а × 5 нефинансови роли × 3 режима, всички към 403 без бизнес запис (`pm01_cells_changed.csv`). Финансовите клетки не са променени.

Повторното C01 пускане е регенерирано: единствената разлика е, че `labor_sync` на P1 вече не пише (редът съвпада с отчета; преди се изтриваше и пресъздаваше).

## Решения за Крум

- **SiteManager губи** (досега имаше достъп през UI-а, `ADMIN_ROLES` във `frontend/src/App.js:117`): потвърждаване на акт към клиент и към подизпълнител, плащане към подизпълнител, преглед на фактура на доставчик, одобряване на OCR фактура, продажба от склада, календара на работниците, разпределение на режийни, обновяване на цена. Връщането на някое от тях е една зависимост.
- **Без касова сметка не може да се плати на подизпълнител** (409). Ако се иска плащане по банка без сметка в системата — това е отделно решение за W0-05.

## Дълг (записан, не поправен)

- **SEC-01-C02-D1:** плащането към подизпълнител — без W0-05 write service, idempotency key, Approval, сторно, транзакция.
- **SEC-01-C02-D2:** `GET /api/pricing/material?force=true` прави същото обновяване на цената като `POST /pricing/refresh` и не е охранен.
- **SEC-01-C02-D3:** sync на труда — без idempotency key; два едновременни sync-а могат да вмъкнат двоен ред (както и преди).
- **SEC-01-C02-D4:** още отворени записи по същите ресурси, които FG-30 не изброява: `POST/PUT /client-acts`, `POST /client-acts/from-offer/{id}`, `POST /supplier-invoices`, `.../post-to-warehouse`, `POST /subcontractor-acts`, пакетите на подизпълнители, `PUT /ocr-invoice/{id}/review|reject`, `PUT /execution-packages/{id}`. Оркестраторът да реши пакета.
- Остават: SEC-01-D1, SEC-01-C01-D2, SEC-01-C01-D4, FG-28.

## Rollback

Revert на commit-а. Няма миграция. Редовете, създадени от новия sync (сторно + `reversed_by_entry_id`), остават валидни и при стария код (сумите им са верни), но старият sync би ги изтрил.

## Как се повтаря

```bash
cd backend
PYTHONPATH=. pytest tests/test_sec_01_c02_flow_guard_money_writes.py -v --noconftest
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
  PYTHONPATH=. pytest tests/test_sec_01_c02_flow_guard_money_writes.py -v --noconftest
PYTHONPATH=. python tests/test_sec_01_c02_flow_guard_money_writes.py --harness \
  --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
```

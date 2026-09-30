# W0-03E — legacy migration, adapters and isolation proof (implementation note)

> **Статус:** IMPLEMENTED BEHIND `MASTER_DATA_MODE` — Draft PR, не е merge-нат, не е деплойван.
> Нито една миграция не е изпълнена срещу реални данни. **Никой запис по миграцията не може
> да се изпълни в този build**: всяко execute / rollback / mapping решение изисква trusted
> Approval, а W0-07 не е започнат (fail closed). Живи са dry run-ът, reconciliation отчетът,
> резолюцията на стари id и отказите.
> **База:** `main` = `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`, Task W0-03E / C01.
> **Канон:** [FLOW-032](../flows/FLOW-032.md), [contract §4–§6 W0-03E](W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md),
> §4.5 (Крум, 20.09.2026), [TENANCY_MODEL](TENANCY_MODEL.md) §2/§6 (D-15), CLAUDE.md §2/§7/§8/§14.
> Текстът на contract-а не е пипан.

## 1. Какво има

| Файл | Роля |
|---|---|
| `backend/app/master_data/legacy_sources.py` | регистър на 15-те legacy източника и на 46 полета, които пазят legacy id (pure) |
| `backend/app/master_data/legacy_plan.py` | inventory + детерминистичен план + `plan_token`; **само чете** |
| `backend/app/master_data/legacy_migration.py` | execute / resume / verify / reconcile / rollback / човешко решение по pending |
| `backend/app/master_data/legacy_adapter.py` | резолюция на стар id, read annotation, guard за изтриване, аванси, отчет за аванси |
| `backend/app/routes/master_data.py` | 10 нови endpoint-а под `/api/master-data/legacy/…` |
| 9 legacy route файла + `models/hr.py` | scoped delete + guard; аванс само към Master Person в enforce |
| `backend/scripts/w0_03e_legacy_migration_report.py` | read-only отчет върху **възстановено копие** на локален Mongo |
| `backend/tests/test_w0_03e_*.py` | 26 + 84 + 25 (C02) + 6 теста (in-memory, routes, корекции, real Mongo) |

## 2. Source → Master покритие

| Legacy колекция | Canonical | Как се решава |
|---|---|---|
| `users` | person | всеки потребител = отделен запис; име без идентификатор, което съвпада с друго → **pending** |
| `persons` | person | ЕГН е авторитетен; същият ЕГН два пъти в `persons` → **pending** (дубликат в източника) |
| `employee_profiles` | person | FK `user_id` → **attach** към лицето на потребителя; липсващ user → **blocked** |
| `companies` | organization (роля client, `legacy_role=project_owner`) | ЕИК/VAT авторитетни |
| `clients` | organization (client) | фирмен запис (`companyName`/`name`/ЕИК) → organization; **частно лице → pending `ENTITY_TYPE_AMBIGUOUS`** |
| `counterparties` | organization (supplier/client/both) | `type=person` или непознат тип → **pending**; липсващ тип = legacy default `supplier` |
| `subcontractors` | organization (subcontractor) | ЕИК/VAT |
| `work_types` | activity | нормализирано име |
| `smr_groups` | activity | **винаги pending `PROJECT_SCOPED_ACTIVITY`** — обектов ред никога не е Master СМР (FLOW-032); човек може да го map-не към официална дейност |
| `items` | item | SKU авторитетен; същото име + различен SKU = два записа |
| `asset_item_types` | asset_type (`asset_level=category`) | |
| `asset_items` | asset_type (`asset_level=model`) | име в scope марка+модел |
| `asset_units` | physical_asset | сериен № / QR / инвентарен №; `asset_type_id` → мигрирания модел или `asset_type_unresolved` |
| `warehouses` | location (`location_kind=warehouse`) | |
| `location_nodes` | location | `parent_id` → мигрирания родител; висящ родител → **blocked**; родител pending/blocked → дете **pending** |

**Една фирма — един запис.** Равен ЕИК/VAT между `companies`/`clients`/`counterparties`/
`subcontractors` → един organization с `legacy_refs` от всеки източник и роли в тях; VAT от
контрагента се добавя към записа, създаден в същия run. Към вече съществуващ Master се добавя
само `legacy_ref` (нищо не се копира). Противоречиви идентификатори → **pending
`IDENTIFIER_CONFLICT`**.

**Име не е идентичност.** Група без авторитетен идентификатор, чието нормализирано име съвпада с
друга група или с активен Master в същия scope → **pending `NAME_MATCH_NO_AUTHORITY`** с кандидати.
Точно съвпадение също. Няма fuzzy, няма праг, `auto_merges = 0`.

## 3. Как работи миграцията

```text
GET  legacy/plan            → dry run: inventory, решение за всеки документ, plan_token (0 writes)
POST legacy/migration       → plan_token + idempotency_key + confirmation + Approval
       idempotency key → per-tenant lock → run (замразен план, schema_version=1)
       → на batch: fingerprint на източника, Master (детерминистичен id), reverse row,
         1 AuditEvent на batch, checkpoint
       → verify на всеки планиран запис → reconciliation evidence → completed AuditEvent
GET  legacy/reconcile       → преброяване преди/след; zero_lost
POST legacy/rollback[/preview] → reverse rows → rolled_back (с история), Master-и на run-а →
                              archived, legacy_refs на run-а от стари Master-и → $pull. Нищо не се трие.
POST legacy/mappings/decide → човек: map / create_new / decline (с Approval)
GET  legacy/resolve         → стар id → reverse row → Master → merge redirect → canonical
```

- **Tenant.** Само от W0-01 resolver-а. Legacy `org_id` идва от registry mapping-а на контекста
  (`TenantContext.org_id`) и е само доказателство: избира кои legacy редове са на tenant-а и се
  пише в `legacy_refs`. Редове с друг `org_id` не се четат и не се броят (C03: броят им е данни на другия tenant); редове без `org_id` се броят като data quality и се изключват. `org_id`
  от caller-а, различен от tenant-а → **отказ** (`LEGACY_ORG_MISMATCH`); `tenant_id`/`org_id` в
  body → отказ.
- **Reverse reference.** `md_legacy_refs`, един ред на legacy документ, `_id` =
  sha256(tenant, collection, legacy_id). Статуси `mapped`/`pending`/`blocked`/`declined`/
  `rolled_back`. Резолюцията изисква и двете посоки да съвпадат и `org_id` да е на tenant-а;
  иначе `LEGACY_REFERENCE_INCONSISTENT`.
- **Idempotency / resume.** Същата заявка след прекъсване продължава след последния checkpoint;
  прекъснатият batch се прилага отново идемпотентно (детерминистични id, `$addToSet`, reverse
  row по `_id`). Друг run не може да влезе, докато run-ът е прекъснат (lock-ът остава за него).
  Източник, променен след dry run-а → `STALE_PLAN`, run-ът остава `interrupted` и може да бъде
  rollback-нат.
- **Няма тихо частично успешно.** `performed` само след verify на всеки запис, reconciliation и
  AuditEvent. Verify провал → `verification_failed`, без completed събитие.
- **Plan size.** До 20 000 записа на run; по-голям план се разделя по домейн (`sources=`).

## 4. Изтриване — всички пътища

| Път | Преди | Сега (всички режими) | `enforce` |
|---|---|---|---|
| `auth.py` DELETE `/users/{id}` | `delete_one({"id"})` | `{"id","org_id"}` | used/migrated → archive (`is_active=false`) |
| `clients.py` DELETE `/clients/{id}` | `delete_one({"id"})`, soft update без org | двете scoped | archive |
| `counterparties.py` DELETE | `delete_one({"id"})`, soft update без org | двете scoped | archive (`active=false`) |
| `locations.py` DELETE `/locations/{id}` | `delete_one({"id"})` | scoped | used/migrated → **409** (няма archive поле) |
| `projects.py` DELETE `/persons/{id}` | `delete_one({"id"})`; project count без org | scoped | archive |
| `projects.py` DELETE `/companies/{id}` | същото | scoped | archive |
| `smr_groups.py` DELETE | `delete_one({"id"})` + unassign без org | всичко scoped; guard **преди** unassign | **409** |
| `warehouses.py` POST `/dev/reset-warehouses` | `delete_many({"org_id"})` | **премахнато**: по id, scoped, през guard | used/migrated → archive, отчетени в `kept` |
| `assets_items.py` DELETE | scoped | + guard | archive |
| `assets_units.py` DELETE | scoped, без проверка за употреба | + guard | custody/movement/repair → archive |

`enforce` guard: server-side tenant (иначе 403), data path = resolved tenant DB (иначе 409),
W0-02 действие `master_data.legacy.delete` (default deny; само Owner/Admin), употреба по
регистъра от §1 + собственост по `md_legacy_refs`. Неизползван и немигриран запис → scoped hard
delete. Всеки изход → canonical AuditEvent (`deleted` / `archived_instead_of_delete` /
`delete_refused`, denial с `error_code`).

## 5. Аванси (§4.5)

- `enforce`: нов аванс/заем изисква **един доказан** официален Master Person. Всяко
  подадено поле за получател трябва да сочи него, иначе отказ (422, denial AuditEvent)
  **преди** запис на аванс или плащане (C02, находка 1 от ревюто):
  - `person_id` — активен Master Person на tenant-а (през merge redirect към canonical);
  - `user_id` — само с **доказано** мапване (`mapped` reverse reference, записът го носи
    обратно). Немапнат или непознат служител → `ADVANCE_RECIPIENT_UNMAPPED`, **дори ако е
    подаден валиден `person_id`** — нищо не доказва, че е същият човек;
  - `user_id` и `person_id` към различни canonical записи → `ADVANCE_PERSON_MISMATCH`;
  - `guest_name` е текст за показване, не идентичност: ако е подаден, трябва да е
    официалното име или потвърден alias на избрания човек (версионираната W0-03C
    нормализация, точно равенство — проверка за съгласуваност, не търсене) → иначе
    `ADVANCE_RECIPIENT_NAME_CONFLICT`;
  - `guest_name` сам или нищо → `ADVANCE_REQUIRES_MASTER_PERSON`. Човек не се създава.
  Новият аванс носи `master_person_id`. `off`/`shadow` — непроменено.
- Съществуващите `guest_name` аванси не се пипат. `legacy/advances/mapping-report` и скриптът
  ги изброяват с кандидати по точно име — **само предложения**, `auto_mapped = 0`.

## 6. Права и audit

Нови действия: `master_data.migration.plan|execute|rollback|map`, `master_data.legacy.delete`.
Owner/Admin чрез пълния си набор; `office` получава само `migration.map` (FLOW-032: офисът мапва).
Отказ на execute/rollback/map/legacy.delete се записва в audit веригата (както D). Всеки успех и
всеки отказ по миграцията е canonical W0-04 AuditEvent с `correlation_id` = run и
`idempotency_key`; непроверен `approval_id` се пази само като `claimed_approval_id`.

## 7. Режими

`off` — инертно: route-овете отговарят както преди, не се чете Master Data, няма audit
(доказано с landmine тестове). `shadow` — нищо не пише, не блокира, само лог. `enforce` — пише
само с trusted Approval. Не е активиран никъде.

## 8. Доказателства

| Suite | Резултат (C03 head) |
|---|---|
| `test_w0_03e_legacy_migration.py` (mongomock-motor) | 26 passed |
| `test_w0_03e_legacy_routes.py` | 84 passed |
| `test_w0_03e_c02_corrections.py` (находки 1 и 2) | 25 passed |
| `test_w0_03e_c03_isolation.py` (C03, A/B isolation × off/shadow/enforce) | 20 passed |
| `test_w0_03e_real_mongo.py` (MongoDB 8.0.23, loopback, disposable DB) | 8 passed |
| Съседни W0-03A–D, W0-01, W0-02, W0-04 | без регресия (точните числа — в PR HANDOFF) |

## 9. Технически интерпретации за ревю (не бизнес решения)

1. **Всяко migration write е критично** (CLAUDE.md §8 „критична миграция/rollback"), защото
   никой канон не казва кое не е. Затова и mapping решенията изискват Approval — по-строго от
   W0-03B3 review. Може да се облекчи само с решение на Крум.
2. **Частно лице в `clients`** и **`counterparties.type=person`** не стават organization — pending.
3. **`smr_groups` не стават Master activity** (FLOW-032 разделя Master СМР от обектово СМР).
4. **Роля на `companies` = client** с `legacy_role=project_owner` — техническо съответствие, не нова роля.
5. **`off` запазва legacy поведението** за изтриване на използван запис (записано като дълг);
   новите откази са само в `enforce`. Scoping-ът на самото изтриване важи във всички режими,
   защото не променя отговора на легитимна заявка.

## 10. Остатъчни ограничения

- W0-07 Approval runtime липсва → нито един migration write не може да се изпълни в build-а.
- Адаптерите покриват пътищата от инвентара в §11. Останалите legacy **четения** на
  идентичности (списъци, търсения, dashboard-и) не са част от импорт/експорт/справки/AI и
  минават през `legacy_adapter.annotate` домейн по домейн (contract §4.1 стъпка 3).
- Регистърът на референции покрива основните 46 полета, не всичките 3673 `org_id` употреби.
  Непокрито поле не прави изтриване по-малко строго от преди, но не се брои в reconciliation.
- `supplier_id` в `supplier_invoices`/`warehouse_batches` не се валидира от legacy writer-а;
  брои се като препратка към `counterparties` (по-консервативно за изтриване).
- Database-per-tenant: доказано с отделни DB handles и с два org-а в една legacy DB; реален
  per-tenant resolver срещу Atlas не е пипан.
- Premature: production миграция, index build, `MASTER_DATA_MODE` активиране, W0-06.

## 11. Импорт / експорт / справки / AI — инвентар и покритие (C02, находка 2 от ревюто)

Инвентар на **идентичностните** пътища от тези четири групи: пътища, които четат, пишат или
връщат id от 15-те колекции, или внасят свободен текст за идентичност. Как е намерен: grep
по route декораторите за import/export/report/excel/ocr/intake/ai и по достъпите до 15-те
колекции в тези файлове. Покритие = tenant-safe адаптер + фокусиран тест в
`tests/test_w0_03e_c02_corrections.py`. Стария id остава навсякъде.

| # | Път | Идентичност | Адаптер | Тест |
|---|---|---|---|---|
| R1 | `GET /api/prices` (`reports.py`) | `supplier_id` → counterparties, `purchased_by_user_id` → users, алокации към warehouses/projects | look-up-ите са scoped по org (всички режими); `*_master_ref` в enforce | `test_reports_*[/api/prices]` |
| R2 | `GET /api/reports/turnover-by-counterparty` | `counterparty_id` | scoped look-up; `counterparty_master_ref` | `test_reports_*`, `test_report_lookups_*` |
| R3 | `GET /api/reports/turnover-by-counterparty/{id}/invoices` | `counterparty_id`, `supplier_counterparty_id` на всяка фактура | scoped look-up; двата ref-а | същите |
| R4 | `GET /api/reports/turnover-by-client` | `client_id` → counterparties | scoped look-up (чужд контрагент вече не влиза); ref | същите |
| A1 | `POST /api/ocr-invoice/upload`, `/from-media` | caller-supplied `supplier_id`; OCR текст на доставчик | enforce: `supplier_id` трябва да е на tenant-а (404 + denial audit **преди** файл/медия/intake); `supplier_master_ref`; текстът → само pending (съществуваща кука) | `test_ocr_*` |
| A2 | `POST /api/assets/batch-intake/recognize` | `matched_item` = legacy `asset_items` id | `master_ref` в enforce; остава предложение; AI → само pending | `test_ai_batch_*` |
| A3 | `POST /api/assets/ai-intake` | връща само предложение, без legacy id | няма id за адаптиране; AI → само pending (съществуваща кука `observe_ai_asset`) | `test_ai_ocr_excel_proposals_*` (C01) |
| A4 | `POST /api/assets/intake/{id}/approve`, `approve-bulk` | човешко одобрение създава legacy asset идентичности | поетапно: новият legacy запис се брои `unmigrated` и следващият план го мигрира със стария id | `test_a_legacy_identity_created_after_*` |
| I1 | `POST /api/excel-import/commit` (КСС) | свободен текст дейност/единица | само pending (съществуваща кука) | `test_excel_import_hooks_*[kss]` |
| I2 | `POST /api/smr-analyses/import-excel` | същото | същата кука | същият |
| I3 | `POST /api/historical/import-confirm` | свободен текст | само pending | `test_excel_import_hooks_*[historical]` |
| I4 | `POST /api/offers/import-confirm` | свободен текст дейност/единица в редовете | **нова** кука `observe_excel_offer_lines`: само pending, никога Master/alias/link | `test_offer_import_*`, `test_excel_import_hooks_*[offer]` |
| I5 | `POST /api/projects/{id}/import-client-invoice` | копира данни от собственика (companies/persons/clients) | `owner_master_ref` в enforce; записът в проекта scoped по org | `test_client_invoice_import_*` |
| E1 | `GET /api/reports/company-finance-export` | само седмични суми и името на организацията | **не е идентичностен** — няма id от 15-те колекции | — |
| E2 | `GET /api/smr-analyses/{id}/export-excel` | КСС редове (свободен текст, `line_id`) | **не е идентичностен** | — |

`off`: отговорите са непроменени, нищо от Master Data не се чете (landmine тестове);
scoping-ът на look-up-ите в справките важи и в `off`, защото променя отговора само когато
id на чужда фирма би показал нейното име. Няма път от инвентара, който да изисква нов
архитектурен избор.

## 12. C03 — tenant isolation на join-ове и look-up-и в обхвата

Находка от C02 ревюто (възпроизведена на реален Mongo): `/prices` съпоставяше `invoice_lines`
на tenant-а, но join-ваше `invoices` по гол `invoice_id == id` — фактура на tenant B със същото
id връщаше своя номер, дата и доставчик в отговора на tenant A. Поправено; и всеки join/look-up
в обхвата е проверен. Tenant predicate = `org_id` от **автентикираната сесия** (server-side,
`user["org_id"]`), никога от заявката; в `enforce` адаптерите изискват и W0-01 контекстът да
съвпада с него.

| Път | Колекция | Ключ | Tenant predicate | Резултат |
|---|---|---|---|---|
| `GET /prices` | `invoice_lines` | — (`$match`) | `org_id` | SAFE |
| `GET /prices` | `invoices` (`$lookup`) | `invoice_id` → `id` | `$filter` върху join-натия масив по `org_id` **преди** всеки `$match`/`$project`; чужда фактура → редът остава без данни за фактура | **FIXED (C03)** |
| `GET /prices` | `counterparties` / `users` / `projects` / `warehouses` | `supplier_id` / `purchased_by_user_id` / `ref_id` | `org_id` | SAFE (C02) |
| `GET /prices` | `md_legacy_refs`/Master (annotation) | `supplier_id`, `purchased_by_user_id` | W0-01 tenant + reverse-ref `_id` на tenant-а | SAFE |
| `GET /reports/turnover-by-counterparty` | `invoices` (aggregate) | — | `org_id` в `$match` | SAFE |
| същото | `counterparties` | `_id` на групата | `org_id` | SAFE (C02) |
| `GET /reports/turnover-by-counterparty/{id}/invoices` | `invoices` | `supplier_counterparty_id` | `org_id` | SAFE |
| същото | `counterparties` | path id | `org_id` | SAFE (C02) |
| `GET /reports/turnover-by-client` | `invoices` (aggregate) | — | `org_id` | SAFE |
| същото | `counterparties` | `_id` на групата | `org_id` | SAFE (C02) |
| `GET /reports/company-finance-summary`, `-compare`, `-export` | `invoices`, `cash_transactions`, `overhead_transactions`, `bonus_payments`, `payment_slips` (`paid_labor_v3`) | — | `org_id` | SAFE (не е идентичностен) |
| `GET /reports/company-finance-export` | `organizations` | собственото `org_id` | `id == org_id` на сесията | SAFE |
| `GET /smr-analyses/{id}/export-excel` | `smr_analyses` | path id | `org_id` | SAFE (не е идентичностен) |
| `POST /projects/{id}/import-client-invoice` | `projects`, `companies`, `persons`, `clients` | `owner_id` | `org_id` | SAFE; запис в проекта FIXED (C02) |
| `POST /offers/import-confirm` | `projects`, `offers` (номер) | `project_id` | `org_id` | SAFE |
| `GET /advances` | `users` (име на получател) | `advance.user_id` | липсваше | **FIXED (C03)** |
| `POST /advances` (C02 guard) | `md_person`, `md_legacy_refs`, `users`, `financial_accounts` | `person_id`, `user_id`, `account_id` | W0-01 tenant / `org_id` | SAFE |
| `POST /ocr-invoice/*` | `media_files`, `counterparties` | `media_id`, `supplier_id` | `org_id`; enforce отказ преди запис | SAFE (C02) |
| `POST /assets/batch-intake/recognize` | `asset_items`, `asset_item_types` | име / етикет | `org_id` | SAFE |
| `legacy_adapter._resolve_row`, `annotate_refs`, `resolve_legacy` | `md_legacy_refs`, `md_<type>` | `_id` = sha256(tenant, collection, id); redirect chain | `tenant_id`; `org_id` на реда = на tenant-а; обратната препратка задължителна | SAFE |
| `legacy_adapter.count_usage`, `guarded_identity_delete` | 46 референтни полета | legacy id | `org_id` | SAFE |
| `legacy_adapter.advance_mapping_report` | `advances`, `persons`, `users`, `md_person`, `md_legacy_refs` | — | `org_id` / `tenant_id` | SAFE |
| `legacy_plan.load_state` (dry run) | 15 legacy колекции | — | `org_id`; брояч на **чужди** документи (`other_org`) | **FIXED (C03)**: броят на документите на друг tenant вече не се отчита |
| `legacy_migration` reconcile / rollback / mapping | legacy + `md_*` | — | `org_id` / `tenant_id` | SAFE |
| `intake_hooks` (OCR/AI/Excel/offer) | `md_pending_mapping` | нормализиран текст | W0-01 tenant | SAFE; само pending |

Няма BLOCKED ред. Регресии: `tests/test_w0_03e_c03_isolation.py` (A/B с еднакви id на клиент,
фирма, потребител, склад, фактура и контрагент; фактура на A към id само в B; агрегация, в
която B има по-големи суми; подправен B `legacy_ref`; немапнат получател и несъвпадащ човек;
drill-down; xlsx експорт; импорт на клиентски данни, прочетен обратно) във всеки от `off`,
`shadow`, `enforce`; същите пътища на реален MongoDB в `test_w0_03e_real_mongo.py`
(`test_c03_*`). Без `$filter` 6 теста в паметта и реалният тест падат.

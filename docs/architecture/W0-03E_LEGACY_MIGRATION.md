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
| `backend/tests/test_w0_03e_*.py` | 26 + 84 + 5 теста (in-memory, routes, real Mongo) |

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
  пише в `legacy_refs`. Редове с друг `org_id` или без `org_id` се броят и се изключват. `org_id`
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

- `enforce`: нов аванс/заем изисква официален Master Person — `person_id` (активен, през
  redirect) или мапнат `user_id`. `guest_name` сам → **422 `ADVANCE_REQUIRES_MASTER_PERSON`**,
  несъвпадение → `ADVANCE_PERSON_MISMATCH`; denial AuditEvent. Новият аванс носи
  `master_person_id`. `off`/`shadow` — непроменено.
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

| Suite | Резултат |
|---|---|
| `test_w0_03e_legacy_migration.py` (mongomock-motor) | 26 passed |
| `test_w0_03e_legacy_routes.py` | 84 passed |
| `test_w0_03e_real_mongo.py` (MongoDB 8.0.23, loopback, disposable DB) | 5 passed |
| Съседни W0-03A–D, W0-01, W0-02, W0-04 | без регресия (виж PR HANDOFF за точните числа) |

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
- Read annotation е вързан към два detail route-а (`items`, `subcontractors`); останалите
  legacy четения/експорти минават през `legacy_adapter.annotate` домейн по домейн (contract §4.1
  стъпка 3). Excel/OCR/AI intake вече пише само pending (W0-03B2/C) — не е променян.
- Регистърът на референции покрива основните 46 полета, не всичките 3673 `org_id` употреби.
  Непокрито поле не прави изтриване по-малко строго от преди, но не се брои в reconciliation.
- `supplier_id` в `supplier_invoices`/`warehouse_batches` не се валидира от legacy writer-а;
  брои се като препратка към `counterparties` (по-консервативно за изтриване).
- Database-per-tenant: доказано с отделни DB handles и с два org-а в една legacy DB; реален
  per-tenant resolver срещу Atlas не е пипан.
- Premature: production миграция, index build, `MASTER_DATA_MODE` активиране, W0-06.

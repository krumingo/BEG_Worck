# W0-03 Master Data (FLOW-032) — инвентар и implementation contract

> **Статус:** `W0-03A CONTRACT IN REVIEW — RUNTIME NOT STARTED`
> **База:** `main` = `ddad542ed0d1de64b3ba9ae4639517dba03425c7`
> **Дата:** 20.09.2026
> **Метод:** само четене. Нито един runtime файл не е променян, нито една заявка не е
> изпълнявана срещу Atlas или production.

Това е инвентар на **реално съществуващото** състояние, не на желаното. Всяко твърдение
по-долу сочи файл и ред в `main` при горния SHA.

## 0. Кратък отговор

Master Data днес **не съществува като слой**. Съществуват петнадесет колекции, които се
държат като идентичности, пишат се от различни места с различни схеми, нямат нито един
уникален индекс, нямат alias, нямат merge и се трият твърдо.

Трите най-опасни находки:

1. **`persons` и `companies` се създават от два различни route-а с различни полета и
   различна нормализация.** Едната пътека пише `is_active` и малки букви за email, другата
   не. Едно и също лице или фирма влиза два пъти без нищо да го спре.
2. **Нула уникални индекса върху master data.** В целия backend `create_index` се среща
   12 пъти — за FIFO партиди, tenant registry и audit. Заради това
   `app/routes/counterparties.py:184` лови `duplicate key` грешка, която **не може да
   възникне**: индексът, който би я породил, го няма.
3. **Твърдо изтриване на идентичности**, включително
   `app/routes/warehouses.py:290` — `delete_many({"org_id": ...})`, което изтрива **всички**
   складове на фирмата с едно извикване.

## 1. Какво беше проверено

| Област | Резултат |
|---|---|
| Модели и колекции | 15 идентичностни колекции, 5 Pydantic файла |
| Route-ове | 74 файла в `app/routes/` |
| Индекси | `create_index` × 12 общо; върху master data — **0** |
| Tenant Guard | импортиран в **3** от 74 route файла |
| Permission Service | `require_permission` в идентичностните route-ове — **0** |
| Canonical AuditEvent (W0-04) | използван в идентичностните route-ове — **0** |
| Alias / external id / legacy id | **няма такова понятие** |
| Merge / redirect / duplicate | **няма** |
| Migration runner | няма; 4 ad-hoc bootstrap скрипта |
| Background jobs / scheduler | няма |

## 2. Инвентар по идентичности

### 2.1 Person / Contact / Employee / User / Worker

| Колекция | ID | Tenant | Име | Писачи | Четения | Hard delete | Audit | Permission |
|---|---|---|---|---|---|---|---|---|
| `users` | `id` (uuid4) | `org_id` | `first_name`/`last_name`/`email` | `core/seed.py:70`, `routes/auth.py:231,272`, `routes/billing.py:125`, `routes/platform.py:312` | 94 в 36 файла | `routes/auth.py:367` | legacy `log_audit` ×12 | `require_admin`, `user["role"]` |
| `persons` | `id` (uuid4) | `org_id` | `first_name`/`last_name` | **`routes/projects.py:607` и `routes/clients.py:604`** | 21 в 4 файла | `routes/projects.py:653` | само в projects пътеката | `user["role"]` |
| `employee_profiles` | `id` | `org_id` | — (ключ към `user_id`) | `routes/hr.py:122,150` | 30 в 18 файла | — | `log_audit` ×4 | `user["role"]` |

**Дублиране.** `persons` се пише от две места с **различни схеми**:

```
routes/projects.py:598-607   phone, first_name, last_name, email (без lower()), notes
routes/clients.py:596-604    email.lower(), address, notes, is_active, egn
```

`users` и `persons` описват едно и също физическо лице, но нямат връзка помежду си.
`employee_profiles` се закача за `user_id`, тоест служител без акаунт не съществува.

**Четвърта, скрита персонална идентичност:** `app/models/hr.py` — `AdvanceLoanCreate` има
`user_id: Optional` **или** `guest_name: Optional[str]`. Аванс може да се издаде на човек,
който е само низ. Този низ няма tenant, няма id и не може да бъде обединен с нищо.

### 2.2 Organization / Company / Client / Supplier / Contractor

| Колекция | ID | Tenant | Писачи | Четения | Hard delete | Audit |
|---|---|---|---|---|---|---|
| `organizations` | `id` | сам е tenant-ът | `core/seed.py:54`, `routes/billing.py:109`, `routes/platform.py:291` | 19 в 12 файла | — | — |
| `companies` | `id` | `org_id` | **`routes/projects.py:718` и `routes/clients.py:525`** | 19 в 3 файла | `routes/projects.py:772` | само projects |
| `clients` | `id` | `org_id` | `routes/clients.py:200,332` и **`routes/counterparties.py:375`** | 16 в 3 файла | `routes/clients.py:292` | `log_audit` ×2 |
| `counterparties` | `id` | `org_id` | `routes/counterparties.py:182` | 20 в 4 файла | `routes/counterparties.py:263` | `log_audit` ×3 |
| `subcontractors` | `id` | `org_id` | `routes/subcontractors.py:62` | 4 в 2 файла | — | `log_audit` ×1 |

**Пет колекции за едно понятие.** Една и съща фирма може да съществува едновременно като
`companies` (собственик на обект), `clients` (възложител), `counterparties` (контрагент по
фактура) и `subcontractors` (подизпълнител) — четири записа, четири различни `id`, без връзка.

`companies` също има два писача с различни схеми:

```
routes/projects.py:710-718   mol, address, email (без lower()), phone(normalize_phone), notes
routes/clients.py:512-525    + name, eik, vat_number, is_active, email.lower()
```

**Разминаване в имената на полетата вътре в една колекция:** `routes/clients.py:116-122`
търси едновременно по `companyName` **и** по `name` — тоест в `clients` живеят документи с
две различни имена за едно и също поле.

### 2.3 Activity / Work type / СМР дейност

| Колекция | Писач | Четения | Hard delete | Audit |
|---|---|---|---|---|
| `work_types` | `routes/work_logs.py:68` | 11 в 2 файла | — | `log_audit` ×12 в файла |
| `smr_groups` | `routes/smr_groups.py:164` | 12 в 2 файла | `routes/smr_groups.py:273` | **0** |
| `smr_analyses` | `routes/excel_import_v2.py:185` | 64 срещания | — | — |
| `activity_budgets` | `routes/excel_import_v2.py:312` | 34 срещания | — | W0-02 пилотен route |

`smr_groups` има `source_id`/`source_name` (`routes/smr_groups.py:74`) — единственият намек за
произход на идентичност в целия код, но е за групиране на редове, не за идентичност.

### 2.4 Item / Material / Product

| Колекция | Писач | Четения | Уникалност |
|---|---|---|---|
| `items` | `routes/items.py:134` | 9 в 2 файла | няма |
| `material_entries`, `material_requests` | различни | 14 / 22 | няма |
| `warehouse_batches` | `services/fifo_service.py` | 14 | **единствената реална уникалност в системата:** `create_index([("org_id",1),("batch_number",1)], unique=True)` — `services/fifo_service.py:179` |

### 2.5 Asset Type / Equipment

| Колекция | Писачи | Hard delete | Audit |
|---|---|---|---|
| `asset_item_types` | `routes/asset_item_types.py:58`, `routes/assets_intake_pending.py:112` | — | — |
| `asset_items` | `routes/assets_items.py:168`, `routes/assets_intake_pending.py:123` | `routes/assets_items.py:207` | **0** |
| `asset_units` | `routes/assets_units.py:176`, `routes/assets_intake_pending.py:146` | `routes/assets_units.py:211` | **0** |

И трите се създават и от нормалния route, и от AI intake пътеката
(`routes/assets_ai_intake.py`, `routes/assets_batch_intake.py`) — тоест AI може да създаде
нова идентичност на техника, без нищо да провери дали вече съществува.

### 2.6 Location / Site / Warehouse / Address

| Колекция | Писачи | Hard delete | Audit |
|---|---|---|---|
| `warehouses` | `routes/warehouses.py:166`, `routes/procurement.py:415` | **`routes/warehouses.py:290` — `delete_many({"org_id": ...})`** | `log_audit` ×2 |
| `location_nodes` | `routes/locations.py:116` | `routes/locations.py:191` | **0** |

Адресът не е идентичност — свободен текст в `address` полета на `companies`, `clients`,
`persons`, `organizations`.

### 2.7 Alias, нормализация, external / legacy ID

**Alias не съществува.** Търсенето за `alias|external_id|legacy_id|source_id|import_id` дава
само несвързани попадения (`Header(alias=...)`, `source_ids` при сливане на СМР редове).

Нормализация има само три функции, само в `routes/clients.py`:
`normalize_phone` (:171), `normalize_eik` (:380), `normalize_egn` (:386). **Нормализация на
име няма никъде.** Търсенето е `$regex` върху суровото име — `routes/clients.py:116-122`.

### 2.8 Merge, duplicate, redirect, historical identity

Няма. Единственото попадение е мъртъв код: `routes/counterparties.py:184` лови
`duplicate key` от Mongo, но уникален индекс върху `counterparties` не съществува.

## 3. Cross-cutting находки

### 3.1 Tenant

`org_id` се среща **3673** пъти в `app/routes/`, `tenant_id` — **4**. Master data е изцяло
`org_id`-базиран. `app/tenancy/guard.py` е импортиран в **3** route файла
(`activity_budgets.py:13`, `assets_intake_pending.py:20`, `auth.py:18`) — пилотните на W0-02.
**Нито един master data route не минава през Tenant Guard.**

### 3.2 Cross-tenant риск при изтриване

Изтриванията се правят по `id` без tenant филтър:

```
routes/auth.py:367            db.users.delete_one({"id": user_id})
routes/clients.py:292         db.clients.delete_one({"id": client_id})
routes/counterparties.py:263  db.counterparties.delete_one({"id": counterparty_id})
routes/locations.py:191       db.location_nodes.delete_one({"id": node_id})
routes/projects.py:653        db.persons.delete_one({"id": person_id})
routes/projects.py:772        db.companies.delete_one({"id": company_id})
routes/smr_groups.py:273      db.smr_groups.delete_one({"id": group_id})
```

**Важно уточнение, за да не се преувеличи рискът:** поне в `auth.py:364` изтриването е
предшествано от scoped проверка `find_one({"id": user_id, "org_id": user["org_id"]})`.
Тоест защитата съществува, но е в предходния ред, не в самата операция. При един tenant на
база това не е експлоатируемо; при database-per-tenant и при бъдещ merge/redirect механизъм
шаблонът е неприемлив. Класификация: **дълг, не активна уязвимост** — но проверка ред по ред
за всичките седем е част от W0-03E.

### 3.3 Permission

`require_permission` се среща **0 пъти** в десетте проверени идентичностни route-а. Ползват
се `require_admin` и ад-хок `user["role"]` проверки — част от 229-те legacy проверки, които
държат W0-02 отворен.

### 3.4 Audit

Нито един идентичностен route не ползва каноничния W0-04 `AuditEvent`. Ползва се legacy
`log_audit`. Без никакъв audit са: `locations`, `smr_groups`, `asset_items`, `asset_units`,
`asset_item_types`.

### 3.5 Идентификатори

`uuid4()` — 234 срещания, `str(uuid…)` — 223. Няма централна услуга за идентификатори, няма
per-tenant номерация, няма проверка за сблъсък.

### 3.6 Миграции и seed

Migration runner няма. Има 4 ad-hoc скрипта (`scripts/migrate_m19_8_*`,
`w0_01_bootstrap_tenant_registry.py`, `w0_02_bootstrap_permissions.py`,
`w0_04_bootstrap_audit_indexes.py`). Seed данни: `app/core/seed.py` създава `organizations`
и `users`. Background jobs/scheduler — няма.

### 3.7 Зависимости към други W0 items

| Зависимост | Състояние | Значение за W0-03 |
|---|---|---|
| **W0-01 Tenancy** | CORE MERGED, guard невързан | W0-03B трябва да ползва per-tenant resolver, не `org_id` |
| **W0-02 Permission** | CORE DEPLOYED, mode off | master data route-овете са част от 229-те непокрити проверки |
| **W0-04 Audit** | CORE MERGED, невързан тук | всеки master data write трябва да емитира canonical AuditEvent |
| **W0-05 Payment Core** | NOT STARTED | `counterparties` е носителят на финансовата идентичност — W0-03 определя какво W0-05 ще ползва |
| **W0-06 File Registry** | NOT STARTED | снимки/документи към идентичности ще ползват `file_id` |
| **W0-07 DQ + Approval** | NOT STARTED | **merge на две идентичности е точно Approval случай** |
| **Wave 2.1 (FLOW-027)** | Draft PR #11 | зависи от материална и СМР идентичност — блокирана до W0-03C |

## 4. Предложен каноничен модел

```text
MasterEntity (per tenant)
├── entity_type: person | organization | activity | item | asset_type | location
├── id            (canonical, immutable)
├── tenant_id
├── display_name
├── normalized_name        ← детерминистична нормализация
├── identifiers[]          ← EGN/ЕИК/VAT/IBAN/вътрешен номер, типизирани
├── aliases[]              ← исторически и правописни варианти
├── external_refs[]        ← {system, external_id}
├── legacy_refs[]          ← {collection, legacy_id}  ← миграционният мост
├── status: active | merged | archived
├── merged_into            ← redirect при merge, никога hard delete
└── audit: създаване, промяна, merge — canonical AuditEvent
```

Правилото, което решава миграцията: **никой стар `id` не се изхвърля.** Всеки влиза в
`legacy_refs`, така че всички съществуващи документи продължават да резолвват.

## 5. Предложено разделяне W0-03A – W0-03E

### W0-03A — инвентар, canonical schema и migration map (**този документ**)

- **Вход:** кодът при `ddad542`.
- **Изход:** този отчет; canonical schema; карта стара колекция → canonical тип; списък с
  нерешените въпроси.
- **Файлове:** само документация.
- **Acceptance:** всяка идентичностна колекция е описана с файл и ред; всяко дублиране има
  посочена посока на обединяване; нерешените въпроси са изброени, не скрити.
- **Тестове:** няма runtime код.
- **Migration/rollback:** неприложимо.
- **Извън scope:** какъвто и да е runtime код.
- **Задачи:** 1 (тази).

### W0-03B — core registry и per-tenant repositories

- **Вход:** одобрена схема от A.
- **Изход:** `app/master_data/` — модели, repository слой над per-tenant resolver, четене и
  запис зад feature flag `MASTER_DATA_MODE = off|shadow|enforce` (по модела на W0-02).
- **Файлове:** `app/master_data/{models,repository,service,deps}.py`; `scripts/w0_03_bootstrap_master_data.py`.
- **Acceptance:** нито един запис без tenant от resolver-а; всеки write емитира canonical
  AuditEvent; `mode=off` не променя нищо в поведението.
- **Тестове:** positive, forbidden (cross-tenant), off-режим без промяна.
- **Migration:** само създаване на колекции и индекси; без пипане на данни.
- **Rollback:** `mode=off`; колекциите остават празни.
- **Зависимости:** W0-01 resolver, W0-04 audit.
- **Извън scope:** aliases, merge, миграция на стари данни.
- **Задачи:** ~5.

### W0-03C — aliases, нормализация и уникалност

- **Вход:** B.
- **Изход:** детерминистична нормализация (име, ЕИК, ЕГН, телефон, email, IBAN);
  `aliases[]`; **първите уникални индекси в системата** — per tenant.
- **Acceptance:** нормализацията е чиста функция с таблица от случаи (кирилица/латиница,
  „ЕООД"/„ЕOOД", интервали, регистър); уникалността се налага от индекс, не от код; дублиран
  запис се отказва с машинен reason code.
- **Тестове:** таблица за нормализация; отказ при дубликат; alias резолюция.
- **Migration:** индексите се създават **след** доказано чисто множество (виж въпрос Q3).
- **Rollback:** свалянето на индекс е обратимо; нормализацията е версионирана.
- **Зависимости:** B.
- **Извън scope:** merge на вече съществуващи дубликати.
- **Задачи:** ~6.

### W0-03D — merge, redirect история и непроменими препратки

- **Вход:** C.
- **Изход:** merge операция с Approval кука (W0-07), `merged_into` redirect, неизменна
  история, резолюция на стар `id` към canonical.
- **Acceptance:** merge никога не трие; всяка стара препратка продължава да резолвва;
  обратимост при грешен merge; canonical AuditEvent с двете страни.
- **Тестове:** merge, resolve на стар id, отказ без Approval, обратимост.
- **Зависимости:** C; W0-07 за Approval (до тогава — кука `approval_id`, както в W0-02).
- **Извън scope:** автоматично засичане на дубликати.
- **Задачи:** ~6.

### W0-03E — legacy миграция, адаптери и доказателство за изолация

- **Вход:** B–D.
- **Изход:** миграция на `users`/`persons`/`employee_profiles` → person;
  `companies`/`clients`/`counterparties`/`subcontractors` → organization; адаптери за
  импорт/експорт/репорти/AI; **поправка на седемте нескоупнати изтривания**; замяна на hard
  delete с archive/merge; regression доказателство.
- **Acceptance:** нула загубени препратки; всеки стар `id` резолвва през `legacy_refs`; нула
  cross-tenant четения в isolation suite; `warehouses.py:290` вече не съществува в този вид.
- **Тестове:** миграция върху копие на реален архив (инструментът от W0-10A върши точно това);
  isolation suite; regression срещу baseline.
- **Migration/rollback:** по домейн, с dry-run и отчет преди всяко прилагане.
- **Зависимости:** B, C, D; W0-02 за permission guard-овете.
- **Извън scope:** W0-05/W0-06/W0-07 функционалност.
- **Задачи:** ~10.

**Общо: около 28 малки implementation задачи.**

## 6. Нерешени технически въпроси

1. **Q1 — една MasterEntity колекция или по една на тип?** Единната дава общ merge/alias
   механизъм; разделените дават по-чисти индекси. Решението влияе на цялото B.
2. **Q2 — `tenant_id` или `org_id` за master data?** W0-02 прие `tenant_id` с `org_id` като
   compat. Master data е удобният момент да се скъса с `org_id`, но това докосва 3673 места.
3. **Q3 — какво правим със съществуващите дубликати преди да сложим уникален индекс?**
   Индексът ще откаже да се създаде, ако данните вече нарушават правилото. Нужен е
   предварителен read-only отчет върху възстановено копие.
4. **Q4 — `guest_name` при авансите.** Става ли автоматично person, или остава свободен текст
   до изрично решение? Има финансови последици.
5. **Q5 — може ли AI intake да създава нови идентичности?** Днес може
   (`assets_ai_intake.py`). CLAUDE.md §10 изисква потвърждение от човек.
6. **Q6 — кой е носителят на финансовата идентичност за W0-05** — `counterparties` или
   canonical organization? Определя интерфейса на Payment Core.
7. **Q7 — обхват на нормализацията за български имена:** транслитерация, „ЕООД/ООД/АД",
   двойни фамилии, диакритика. Нужно е решение на Крум, не техническо предположение.

## 7. Какво изрично НЕ влиза в W0-03

Payment Core (W0-05), File Registry (W0-06), DQ/Approval runtime (W0-07), Wave 2.1 runtime,
автоматично засичане на дубликати с AI, и **осемте `begwork_w0_04_test_*` бази** — те са
отделен follow-up ([документ](../ops/FOLLOWUP_ATLAS_STRAY_W0-04_TEST_DBS.md)) и не се
докосват от W0-03.

## 8. Свързани документи

- [IMPLEMENTATION_WAVES.md](IMPLEMENTATION_WAVES.md) — Wave 0 статус и договорен ред
- [IMPLEMENTATION_GATE_MATRIX.md](IMPLEMENTATION_GATE_MATRIX.md) — FLOW-032 gate
- [TENANCY_MODEL.md](TENANCY_MODEL.md) — per-tenant модел
- [docs/flows/FLOW-032.md](../flows/FLOW-032.md) — бизнес канонът

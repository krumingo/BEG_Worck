# W0-03 Master Data (FLOW-032) — инвентар и implementation contract

> **Статус:** `W0-03B1 MERGED — W0-03B2 IN PROGRESS`
> Contract-ът е merge-нат в `main` на 20.09.2026 (`d8a213a3`). Текстът му не се пренаписва от
> имплементационните slice-ове; промяна в него изисква отделно решение.
> **База:** `main` = `ddad542ed0d1de64b3ba9ae4639517dba03425c7`
> **Дата:** 20.09.2026
> **Метод:** само четене. Нито един runtime файл не е променян, нито една заявка не е
> изпълнявана срещу Atlas или production.
> **Редакция 2 (20.09.2026):** след независимо ревю. Първата версия оставяше като „нерешени"
> три въпроса, които канонът вече е решил, и описваше шест канонични типа вместо девет.
> Поправено в раздели [4](#4-заключени-решения-от-канона), [5](#5-каноничен-модел) и
> [9](#9-traceability).
> **Редакция 3 (20.09.2026):** Крум реши последния отворен бизнес въпрос — аванс само към
> официален Master Person (§4.5). **В документа не остава нито един отворен бизнес въпрос.**

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

## 4. Заключени решения от канона

Първата версия на този документ остави четири неща като „нерешени въпроси". Независимото
ревю посочи, че три от тях вече са решени в канона, а четвъртият модел е бил непълен. Това
е моя грешка: написах contract-а, без да прочета `FLOW-032.md` и `TENANCY_MODEL.md`.
Разделът по-долу записва решенията с препратка към източника, вместо да ги преоткрива.

### 4.1 Tenant ключът е `tenant_id` от server-side resolver (D-15)

Източник: [TENANCY_MODEL.md](TENANCY_MODEL.md) §2 — *„Всяка работна сесия има един активен
`tenant_id`, определен server-side от проверената сесия"*; §6 — *„FLOW-032 е винаги per
tenant"*.

- Каноничният W0-03 слой ползва **`tenant_id`, получен единствено от resolver-а**. Никога от
  тялото на заявката, никога от заглавка, никога от JWT като authoritative източник.
- `org_id` остава **временна legacy compatibility информация**, съхранявана в
  `legacy_refs`, за да резолвват старите документи. Не е бъдещият canonical ключ.
- **W0-03B не предлага промяна на 3673-те срещания на `org_id`.** Новият слой е нов; старите
  route-ове не се пипат в B.

**Поетапна compat стратегия (реализира се в W0-03E):**

1. Master записът носи `tenant_id` и `legacy_refs[{collection, legacy_id, org_id}]`.
2. Адаптерите за legacy route-овете приемат `org_id` на входа и го резолвват към `tenant_id`
   през resolver-а; при разминаване — отказ, не догадка.
3. Домейн по домейн legacy четенията минават през адаптера, докато `org_id` не остане само в
   `legacy_refs`.
4. Премахването на `org_id` от бизнес заявките е **извън W0-03** — то е отделен дълг, който
   зависи и от W0-02 миграцията на 229-те проверки.

### 4.2 AI/OCR/Excel не създават официален Master запис

Източник: [FLOW-032](../flows/FLOW-032.md) §„Импорт, OCR и AI мапване" — *„Excel, OCR и AI не
създават автоматично нов Master хаос. Неразпознатото влиза в «За мапване»"*; §„Какво НЕ
трябва да позволява" — *„AI да променя Skill Matrix или Master Data самостоятелно"*.

**Pending-mapping contract:**

```text
свободен текст (Excel/OCR/AI/терен)
→ pending_mapping запис: {tenant_id, entity_type, raw_text, source, suggested_matches[], suggested_new?}
→ офис/упълномощен човек избира: съществуващ Master | нов Master | отказ
→ при потвърждение: alias се закача към Master записа и се ползва автоматично следващия път
```

- Pending записът **не е** Master запис и не участва в справки като идентичност.
- `suggested_matches` е предложение с обяснение, не решение.
- В **enforce** режим `routes/assets_ai_intake.py` и `routes/assets_batch_intake.py` вече не
  създават `asset_item_types`/`asset_items`/`asset_units` директно — пишат pending запис.
- В **shadow** режим нищо не се създава: само се измерва какво би било предложено и колко
  пъти предложението би съвпаднало със съществуващ Master. Това е и метриката, която
  показва готовност за enforce.

### 4.3 Една фирма — един Master запис, много роли

Източник: [FLOW-032](../flows/FLOW-032.md) §„Фирми и контрагенти" — една фирма може
едновременно да е клиент/възложител, инвеститор, платец, доставчик, подизпълнител,
транспорт, наемодател; §„Какво НЕ трябва да позволява" — *„една фирма да се дублира за всяка
роля"*.

- **Canonical organization е идентичността.** `counterparty`, `client`, `subcontractor`,
  `supplier` са **роли**, не отделни идентичности — реализират се като projections/adapters
  над canonical записа.
- **W0-05 Payment Core реферира canonical organization ID.** Не `counterparty_id`.
- Legacy `counterparty_id` (и `client_id`, и `subcontractor_id`) се пазят в `legacy_refs`.
- ЕИК е ключовият контрол срещу дублиране (FLOW-032). Промяна на банкови данни е критична и
  минава през Approval Center — кука към W0-07.
- **W0-05 не се реализира в този PR и не е част от W0-03.**

### 4.4 Skill Matrix се поддържа ръчно

Източник: [FLOW-032](../flows/FLOW-032.md) §„Хора и роли" — *„Skill Matrix в първата версия
се създава и поддържа ръчно от Крум. AI я използва за препоръки, но не променя нивата без
изрично одобрение."*

### 4.5 Аванс само към официален Master Person (решение на Крум, 20.09.2026)

**Одобрен е Вариант Б.** Аванс или заем се създава **само** за официален canonical Master
Person. Свободен текст не е самостоятелна идентичност.

Правилото, изцяло:

1. Всеки **нов** аванс реферира **canonical Master Person ID**.
2. `guest_name` **не е допустим** като самостоятелна идентичност за нов аванс.
3. Свободен текст **никога** не създава автоматично Master Person — потвърждава се от човек
   по pending-mapping пътя (§4.2).
4. Ако лицето не съществува, то първо се **създава или потвърждава** като официален Master
   Person и **чак тогава** се създава авансът. Обратният ред не се допуска.
5. Автоматично сливане на съществуващи `guest_name` записи е забранено. **Самоличност не се
   измисля** — нито от AI, нито от евристика по сходство на име.

Бизнес обосновката е финансова: докато сумата виси към низ, тя не може да бъде проследена до
лице, не влиза в справките като задължение на човек и не може да носи история.

#### Съвместимост и миграция на съществуващите записи

Днешните аванси с `guest_name` са реални финансови записи. Те **не се променят, не се сливат
и не се изтриват** — нито в рамките на W0-03A, нито автоматично по-късно.

```text
съществуващ аванс с guest_name
→ остава четим и непроменен
→ влиза в отчет „аванси, нуждаещи се от ръчно мапване"
→ офис/упълномощен човек избира съществуващ Master Person или го създава с потвърждение
→ авансът се закача за canonical ID; guest_name се запазва като alias/историческа стойност
```

- Отчетът е **read-only** и се прави върху възстановено копие, не срещу production.
- Нито един запис не се мапва автоматично, дори при точно съвпадение на името — съвпадението
  е **предложение**, не решение.
- До ръчното мапване старият запис продължава да работи; блокира се само **създаването на
  нов** аванс без canonical ID.
- В **shadow** режим нищо не се блокира: само се брои колко нови аванса биха били отказани и
  колко от тях биха имали очевиден кандидат. Това е метриката за готовност за enforce.

## 5. Каноничен модел

FLOW-032 §„Златно правило" изброява **девет** типа, които трябва да имат официален Master
запис. Първата версия на този документ описваше шест — пропуснати бяха физически актив,
мерна единица и таг/категория.

### 5.1 Каноничните типове

| Тип | Какво е | Ключов контрол срещу дублиране |
|---|---|---|
| `person` | физическо лице | ЕГН (маскирано), телефон, нормализирано име |
| `organization` | юридическо лице | **ЕИК/VAT** |
| `activity` (Master СМР) | общ тип дейност, напр. „Боядисване" | нормализирано име + категория |
| `item` | официален артикул | име + марка/модел/размер + базова единица |
| `asset_type` | модел/тип техника | производител + модел |
| `physical_asset` | конкретна бройка | **QR / сериен номер** |
| `unit` | мерна единица от контролиран списък | код |
| `location` | възел в йерархията на обекта | път в йерархията |
| `tag` | контролиран таг/категория | нормализирано име |

### 5.2 Общи полета

```text
<MasterType> (per tenant)
├── id                 canonical, immutable
├── tenant_id          само от server-side resolver
├── display_name
├── normalized_name    детерминистична нормализация (виж Q7a)
├── identifiers[]      типизирани: ЕГН | ЕИК | VAT | сериен № | QR | код
├── aliases[]          исторически, правописни и доставни варианти
├── external_refs[]    {system, external_id}
├── legacy_refs[]      {collection, legacy_id, org_id}   ← миграционният мост
├── status             active | merged | archived
├── merged_into        redirect при merge; никога hard delete
└── audit              създаване, промяна, merge — canonical AuditEvent
```

Правилото, което решава миграцията: **никой стар `id` не се изхвърля.**

### 5.3 Отношения

**Skill Matrix ↔ person.** Отделна релация `person_skill {person_id, skill_id, level,
set_by, set_at, approval_id?}`, не свободно поле в person. Поддържа се ръчно; AI може да
предлага, но не записва (§4.4).

**Роли на организация.** `organization_role {organization_id, role, valid_from, valid_to}`,
където role ∈ {client, investor, payer, supplier, subcontractor, transport, lessor, other}.
Една организация — много роли, един запис.

**Роли на човек.** Реализират се през вече съществуващия W0-02 `RoleAssignment` (scope по
фирма/обект/модул). FLOW-032: *„Работник, техник, шофьор, администратор, човек от бригада и
контакт не се дублират като отделни лица."* Person не носи роля в себе си.

**Master СМР → обектово СМР.** `project_smr {tenant_id, project_id, activity_id, location_id,
quantity, unit_id, specification, price, contract_ref}`. Едно Master СМР участва многократно
в различни помещения, оферти и допълнителни обхвати. Обектовият ред **никога** не е Master
запис и не се смесва с него.

**Item → допустими единици и конверсии.** `item_unit {item_id, unit_id, is_base}` и
`item_unit_conversion {item_id, from_unit_id, to_unit_id, factor, source}`. FLOW-032:
конверсия е допустима само когато е известна и **конкретна за артикула** — `1 палет = 48
торби` е свойство на артикула, не глобална константа. Конверсия без артикулно основание се
отказва.

**Asset type → physical asset.** `physical_asset {asset_type_id, serial, qr, location_id,
custodian_person_id, warranty, repairs[]}`. Един модел — много бройки с различни локации,
отговорници и гаранции.

**Локационна йерархия.** `location.parent_id` + ниво (обект → сграда/секция → етаж →
помещение/фасада/двор → зона → елемент). СМР може да сочи конкретен елемент или parent
scope `ALL`; `ALL` **не се размножава автоматично** по децата.

**Тагове.** `tag` с `aliases[]` — „ел.", „ток", „кабели" сочат към официален таг „Електро".

> **Дали всички типове живеят в една Mongo колекция е технически избор — виж Q1.** Канонът
> изисква един официален запис на понятие, не една таблица.

## 6. Предложено разделяне W0-03A – W0-03E

### W0-03A — инвентар, canonical schema и migration map (**този документ**)

- **Вход:** кодът при `ddad542`; `FLOW-032.md`; `TENANCY_MODEL.md`.
- **Изход:** този отчет; заключени решения; canonical типове и отношения; карта стара
  колекция → canonical тип; разделяне на технически въпроси и бизнес решения.
- **Файлове:** само документация.
- **Acceptance:** всяка идентичностна колекция е описана с файл и ред; всяко дублиране има
  посочена посока на обединяване; всяко твърдение за „решено" сочи канон; всеки останал
  отворен въпрос е класифициран като технически или бизнес.
- **Извън scope:** какъвто и да е runtime код.
- **Задачи:** 1.

### W0-03B — core registry и per-tenant repositories

- **Вход:** одобрен contract от A.
- **Изход:** `app/master_data/` — модели, repository над per-tenant resolver, четене и запис
  зад `MASTER_DATA_MODE = off|shadow|enforce`; pending-mapping колекция.
- **Файлове:** `app/master_data/{models,repository,service,deps,pending}.py`;
  `scripts/w0_03_bootstrap_master_data.py`.
- **Acceptance:**
  - `mode=off` е **поведенчески инертен** — нула промяна в отговорите и нула нови записи;
    доказва се с regression срещу baseline, не с твърдение;
  - `tenant_id` идва **само** от server-side resolver;
  - **никой път не приема tenant идентификатор от тялото на заявката** — има отрицателен тест;
  - всеки write емитира canonical W0-04 `AuditEvent`;
  - **AI/OCR не може да създаде официален Master без човешко потвърждение** — в enforce
    режим intake пътеките пишат само pending запис;
  - **официален Master Person се създава само по явен път с човешко потвърждение.** Нито
    един друг домейн — включително аванси, заплати, бригади и attendance — не може да го
    създаде като страничен ефект от свой запис (§4.5);
  - **`shadow` не пише.** Той изпълнява същите проверки като `enforce`, но не създава запис,
    не отваря колекция, не емитира AuditEvent и **никога не хвърля изключение** — отказът
    се връща като наблюдение в изхода. Shadow мери; той не бива да чупи път, който преди е
    работел. Четенето в shadow връща `None` без заявка: каноничното хранилище е празно в този
    режим, а отговор от него би дал на викащия данни, каквито legacy пътят няма;
  - **режимът се валидира от един валидатор**, независимо дали идва от средата или от явен
    аргумент; `None` означава „прочети средата", а празен низ е операторска грешка. Отказът
    настъпва **преди** tenant resolver, repository, Mongo и audit;
  - **успешен `enforce` изход не се връща без canonical AuditEvent.** Операционният запис и
    audit веригата са две колекции без обща транзакция — това **не е** атомарно. Редът е:
    първо запис, после audit; обратният ред би рискувал събитие за несъстоял се запис, което
    поврежда доказателствената верига. Ако audit-ът се провали, записът може вече да
    съществува без събитие: операцията се отчита като **неуспешна**, нищо не се изтрива
    компенсаторно (FLOW-032 забранява hard delete на Master запис), а изчистването на такъв
    неодитиран запис е работа на W0-04B/W0-03E.
- **Тестове:** positive; forbidden (cross-tenant, tenant от body); off-режим без промяна;
  intake → pending, не Master.
- **Migration:** само създаване на колекции; без пипане на данни.
- **Rollback:** `mode=off`; колекциите остават празни.
- **Зависимости:** W0-01 resolver, W0-04 audit.
- **Извън scope:** aliases, уникалност, merge, миграция на стари данни.
- **Задачи:** ~5.

### W0-03C — нормализация, aliases и уникалност

- **Вход:** B.
- **Изход:** детерминистична техническа нормализация; `aliases[]`; **първите уникални индекси
  в системата** — per tenant.
- **Acceptance:**
  - **задължително предусловие:** read-only duplicate report върху **възстановено копие**
    (инструментът от W0-10A прави точно това) — без него индекс не се създава;
  - **създаването на индекс се отказва при непочистени дубликати** и връща отчет кои записи
    го блокират, вместо да се опита частично;
  - нормализацията е **версионирана** (`normalization_version` върху записа), за да може
    бъдеща промяна да се приложи контролирано;
  - **alias mapping не прави автоматичен merge** — alias сочи към Master, но сливането на два
    Master записа е операция от D;
  - нормализацията е чиста функция с таблица от случаи.
- **Тестове:** таблица за нормализация; отказ при дубликат; отказ при създаване на индекс
  върху мръсни данни; alias резолюция без merge.
- **Rollback:** свалянето на индекс е обратимо; нормализацията е версионирана.
- **Извън scope:** merge на съществуващи дубликати; fuzzy matching.
- **Задачи:** ~6.

### W0-03D — merge, redirect история и непроменими препратки

- **Вход:** C.
- **Изход:** merge с preview, `merged_into` redirect, неизменна история, резолюция на стар
  `id` към canonical.
- **Acceptance:**
  - **merge изисква preview** — какво ще се слее, кои препратки ще се пренасочат, какво ще
    стане с конфликтните полета (FLOW-032 забранява merge без preview);
  - **критичен merge изисква Approval** (финансова/историческа тежест — FLOW-032 §„Права");
    до W0-07 — кука `approval_id`, както в W0-02;
  - **старите `id` продължават да резолвват** след merge;
  - **redirect цикъл е невъзможен** — проверка преди запис, с отрицателен тест;
  - **rollback/unmerge запазва историята** — не изтрива следата от merge-а;
  - merge никога не трие запис.
- **Тестове:** preview; merge; resolve на стар id; отказ без Approval; опит за цикъл; unmerge
  със запазена история.
- **Зависимости:** C; W0-07 за Approval.
- **Извън scope:** автоматично засичане на дубликати.
- **Задачи:** ~7.

### W0-03E — legacy миграция, адаптери и доказателство за изолация

- **Вход:** B–D.
- **Изход:** миграция `users`/`persons`/`employee_profiles` → person;
  `companies`/`clients`/`counterparties`/`subcontractors` → organization с роли;
  `work_types`/`smr_groups` → activity; `asset_*` → asset_type + physical_asset;
  `warehouses`/`location_nodes` → location; адаптери за legacy route-ове, импорт/експорт,
  справки и AI; поправка на седемте нескоупнати изтривания; замяна на hard delete с
  archive/merge.
- **Acceptance:**
  - **всички `legacy_refs` са проверени** — за всеки мигриран запис съществува обратна
    препратка и тя резолвва;
  - **нула загубени препратки** — доказва се с преброяване преди и след, не с извадка;
  - **database-per-tenant isolation suite** минава — нула cross-tenant четения;
  - **адаптери за legacy route-овете**, така че старите пътища продължават да работят;
  - **hard delete е заменен с archive/merge** там, където FLOW-032 го изисква — използван
    запис в отчет, фактура, акт, склад, актив или плащане не се изтрива;
  - `warehouses.py:290` (`delete_many` по `org_id`) вече не съществува в този вид;
  - **нов аванс без canonical Master Person ID се отказва** в enforce режим, с машинен reason
    code — отрицателен тест с `guest_name` и без `person_id` (§4.5);
  - **отчет „аванси за ръчно мапване"** изброява всички съществуващи `guest_name` записи;
    отчетът е read-only, прави се върху възстановено копие и **не мапва, не слива и не
    променя нито един запис**;
  - **нула автоматични мапвания** — дори при точно съвпадение на име предложението остава
    предложение; доказва се с тест, че точно съвпадение НЕ води до автоматична връзка;
  - съществуващите аванси с `guest_name` остават четими и непроменени след миграцията;
    `guest_name` се запазва като alias/историческа стойност, когато авансът бъде мапнат.
- **Тестове:** миграция върху възстановено копие; isolation suite; regression срещу baseline;
  отрицателни тестове за изтриване на използван запис; отрицателен тест за нов аванс без
  canonical person; тест, че точно съвпадение на име не създава автоматична връзка.
- **Migration/rollback:** по домейн, с dry-run и отчет преди всяко прилагане.
- **Зависимости:** B, C, D; W0-02 за permission guard-овете.
- **Извън scope:** W0-05/W0-06/W0-07 функционалност.
- **Задачи:** ~10.

**Общо: около 29 малки implementation задачи.**

## 7. Останали въпроси

Само технически решения. **Нито един отворен бизнес въпрос не остава** — последният (`guest_name` при аванси) беше решен от Крум на 20.09.2026 и е записан в [§4.5](#45-аванс-само-към-официален-master-person-решение-на-крум-20092026).

### Q1 (техническо) — една колекция или по една на тип

**Препоръка и default за W0-03B: колекции по тип + две общи колекции за cross-cutting
механизмите.**

| | Една `master_entities` | По колекция на тип |
|---|---|---|
| Merge/alias механика | една, обща | обща, но над няколко колекции |
| Уникални индекси | частични, с `entity_type` във всеки ключ | **чисти и селективни** — `(tenant_id, eik)` само за организации |
| Схема | разредена; валидацията отслабва | типизирана |
| Планове на заявките | по-лоши при растеж | по-добри |

FLOW-032 изисква **типово специфични** контроли — ЕИК за фирми, QR/сериен номер за физически
актив, базова единица за артикул. Това натежава в полза на разделените колекции.
Cross-cutting механизмите остават общи: `master_aliases` и `master_merges`, ключувани по
`(entity_type, entity_id)`, така че merge и alias кодът е един.

**Бизнес ефект: няма.** Това е техническо решение и не изисква Крум.

### Q3 (техническа proof задача, не въпрос) — duplicate report преди уникални индекси

Преместено като **задължително предусловие на W0-03C** (виж acceptance). Изпълнява се
read-only върху **възстановено копие** с инструмента от W0-10A — не срещу production, не
срещу Atlas. Отчетът изброява кои записи биха блокирали всеки индекс.

### Q7 (разделен на две)

**Q7a — безопасна техническа нормализация (не изисква решение на Крум).** Unicode NFC;
свиване на интервали; case folding; премахване на вътрешна пунктуация в идентификатори;
стандартизирани правни суфикси (ЕООД, ООД, АД, ЕАД, СД, ДЗЗД) към канонична форма.
Детерминистична, версионирана, покрита с таблица от случаи.

**Q7b — business matching policy (изисква решение на Крум, но не в W0-03A).**
Транслитерация кирилица ↔ латиница, fuzzy matching, прагове за „вероятен дубликат".

> **Автоматичен merge не се допуска при никакъв праг.** FLOW-032 забранява merge без preview
> и AuditEvent. Най-многото, което matching-ът прави, е да предложи — човек решава.

## 8. Какво изрично НЕ влиза в W0-03

Payment Core (W0-05), File Registry (W0-06), DQ/Approval runtime (W0-07), Wave 2.1 runtime,
автоматично засичане и сливане на дубликати, премахването на `org_id` от бизнес заявките, и
**осемте `begwork_w0_04_test_*` бази** — те са отделен follow-up
([документ](../ops/FOLLOWUP_ATLAS_STRAY_W0-04_TEST_DBS.md)) и не се докосват от W0-03.

## 9. Traceability

| Твърдение в contract-а | Източник |
|---|---|
| `tenant_id` server-side, Master Data per tenant | [TENANCY_MODEL.md](TENANCY_MODEL.md) §2, §6 (D-15) |
| Девет типа с официален Master запис | [FLOW-032](../flows/FLOW-032.md) §„Златно правило" |
| Един човек, много RoleAssignment | FLOW-032 §„Хора и роли" |
| Skill Matrix ръчна, AI само препоръчва | FLOW-032 §„Хора и роли" |
| Една фирма, много роли; ЕИК контрол; банкови данни през Approval | FLOW-032 §„Фирми и контрагенти" |
| Master СМР ≠ обектово СМР | FLOW-032 §„Master СМР и обектово СМР" |
| Локационна йерархия, `ALL` без автоматично размножаване | FLOW-032 §„Локации" |
| Базова единица, supplier aliases, OCR варианти | FLOW-032 §„Материали и доставни алиаси" |
| Конверсии само с артикулно основание | FLOW-032 §„Мерни единици и конверсии" |
| Тип/модел ≠ физически актив (QR/сериен №) | FLOW-032 §„Инструменти и активи" |
| Тагове като контролирани записи с алиаси | FLOW-032 §„Тагове и категории" |
| Excel/OCR/AI → „За мапване", офисът потвърждава | FLOW-032 §„Импорт, OCR и AI мапване" |
| Merge, не изтриване; използван запис не се трие | FLOW-032 §„Merge и архивиране" |
| Merge без preview и AuditEvent е забранен | FLOW-032 §„Какво НЕ трябва да позволява" |
| Tenant A не вижда Master Data на tenant B | FLOW-032 §„Какво НЕ трябва да позволява" |
| Аванс само към официален Master Person | **решение на Крум, 20.09.2026**, записано в §4.5 |
| Свободен текст е вход/алиас, не source of truth | FLOW-032, раздел „Златно правило" |

## 10. Свързани документи

- [IMPLEMENTATION_WAVES.md](IMPLEMENTATION_WAVES.md) — Wave 0 статус и договорен ред
- [IMPLEMENTATION_GATE_MATRIX.md](IMPLEMENTATION_GATE_MATRIX.md) — FLOW-032 gate
- [TENANCY_MODEL.md](TENANCY_MODEL.md) — per-tenant модел
- [docs/flows/FLOW-032.md](../flows/FLOW-032.md) — бизнес канонът

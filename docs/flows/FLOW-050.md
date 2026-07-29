# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 20% — BUSINESS DESIGN IN PROGRESS  
> **Последна проверка:** 29.07.2026  
> **Оставащи решения:** 12  
> **Implementation Gate:** W0-BLOCKER за multi-tenant основата; billing и entitlements се проверяват отделно  
> **Свързани FLOW:** 002, 006, 016, 032, 033, 034, 040, 042, 043, 044, 045, 046, 049

## 1. Цел

FLOW-050 определя как BEG_Work се предоставя на отделни фирми като SaaS продукт: tenant модел, изолация, абонамент, пакети, feature entitlements, плащане за системата, support access, среди, прекратяване и export.

## 2. Заключено решение: един tenant = една отделна фирма

Един tenant представлява точно една юридическа фирма.

Всеки tenant използва един и същ core продукт и логика FLOW-001–050, но има напълно отделни:

- оперативни и финансови данни;
- Master Data;
- потребители, memberships, роли и обхвати;
- обекти, оферти, договори, фактури и плащания;
- каси, банки, складове, активи и файлове;
- номерации;
- интеграции и API ключове;
- AI контекст;
- AuditEvent история;
- абонамент, пакет и настройки.

Потребителят не избира фирма във всяка форма. Tenant-ът се определя от активната сесия.

## 3. Един акаунт, няколко tenant membership-а

Един User може да има достъп до няколко фирми, но всяка работна сесия има един активен `tenant_id`.

Пример:

```text
Крум Радулов
├── BUILDING EXPRESS GROUP — Owner
├── INTERIOR EXPRESS — Owner
└── EXPERT ENGINEERING GROUP — Manager
```

При превключване на фирмата се сменя целият работен контекст. Всички нови записи автоматично принадлежат на активния tenant.

## 4. Заключено решение: изолация на данните

Всеки tenant има:

- отделна MongoDB база;
- отделно файлово пространство;
- отделни номерации;
- отделни интеграции и credentials;
- отделен backup/restore и export scope;
- отделен AI retrieval scope.

Централен `Tenant Registry` пази само техническата карта на tenant-а: `tenant_id`, юридическа фирма, database location, storage location, status, subscription, deployment и `schema_version`.

## 5. Tenant Guard

Всички API, background jobs, exports, search, files и AI tools минават през централен Tenant Guard.

Tenant Guard проверява:

- authenticated user;
- active tenant session;
- active TenantMembership;
- RoleAssignments и scope;
- принадлежността на искания ресурс към същия tenant;
- забрана за cross-tenant read/write.

`tenant_id` не се приема като свободно доверено поле от клиентската форма.

## 6. Master Data е per tenant

Master Data по FLOW-032 е винаги per tenant, включително:

- Master Person/Organization;
- СМР;
- материали и артикули;
- доставчици и клиенти;
- aliases;
- договорени и исторически цени;
- Skill Matrix;
- производителност и бизнес класификации.

Глобални са само технически справочници без бизнес и търговска стойност, например държави, валути, часови зони, system feature IDs и application versions.

## 7. TenantMembership и FLOW-002

Няма втори конкурентен permission модел.

```text
User
→ TenantMembership
   → RoleAssignments от FLOW-002
      → role/action/module/project/location/resource/amount/validity scope
```

TenantMembership отговаря дали човекът има достъп до фирмата. RoleAssignment определя какво може да прави вътре в нея.

## 8. Отношения между отделни tenant-и

Между tenant-и няма споделени оперативни записи.

Когато две свързани фирми работят помежду си, те се третират като независими контрагенти чрез официалните FLOW-ове:

```text
Tenant A
→ Counterparty: Firm B
→ договор / заявка / Work Package / акт / фактура / плащане
```

Не се допуска общ Project, обща фактура, общ Payment или общ Work Package, редактиран от два tenant-а.

Group Dashboard е допустим само като отделна read-only управленска проекция с изрично избрани tenant-и. От него не се създават официални записи.

## 9. Migration runner и schema version

Моделът database-per-tenant изисква централен migration runner.

Той:

- обхожда Tenant Registry;
- сравнява текущата `schema_version`;
- прилага липсващите миграции per tenant;
- използва migration lock и idempotency;
- валидира резултата;
- записва per-tenant status и AuditEvent;
- поддържа recovery/rollback plan.

Минимални Registry полета:

```text
tenant_id
database_name
schema_version
migration_status
last_migration_at
last_successful_migration
failed_migration
deployment_version
```

## 10. Support access

Системният оператор по подразбиране вижда само технически metadata и здравето на tenant-а.

Достъп до реални фирмени данни изисква `Support Access Request` с:

- причина и ticket;
- обхват;
- read-only/restricted-write режим;
- одобрение;
- начален и краен час;
- автоматично изтичане;
- AuditEvent и audit-of-support.

Break-glass достъпът е двустепенен, временно ограничен и автоматично известява tenant owner.

## 11. Задължителни isolation tests

Преди production трябва да минават автоматични тестове, че:

- User от Tenant A не вижда Tenant B;
- ID от Tenant B не работи в Tenant A;
- файл, search и export не връщат чужди данни;
- AI не използва чужд контекст;
- backup/restore и migration за един tenant не засягат останалите;
- RoleAssignment в една фирма не дава права в друга;
- cross-tenant shared operational record е забранен.

Тестовете влизат в Bootstrap QA Gate v0 / FLOW-042.

## 12. Плащане за BEG_Work — работна рамка

BEG_Work ще поддържа месечни, годишни и договорни абонаменти. Външен платежен оператор обработва картата и payment status, но FLOW-050 е source of truth за Subscription, Plan, Entitlement, Grace Period и access state.

Sandbox не е задължителен сам по себе си. Използва се само когато избраният оператор го предоставя и е необходим за безопасно интеграционно тестване.

## 13. Оставащи решения

1. Финални търговски пакети и имена.
2. Feature Catalog, Plan Version и Tenant Entitlement модел.
3. Full/Field/External user лимити и overages.
4. Начални цени и правила за годишна отстъпка.
5. Месечно, годишно и Enterprise договорно плащане.
6. Избор на платежен оператор и фактуриране.
7. Grace Period, Restricted, Suspended и restoration правила.
8. Demo, Trial и Partner tenant режими.
9. Tenant configuration срещу private extension и забрана за client forks.
10. Test/Staging/Production и Tenant Acceptance Environment.
11. Прекратяване, export, retention и deletion.
12. Финален AuditEvent и approval catalog за subscription/entitlements/support.

## 14. Източници / сесии

- FLOW-042 — exact tenant/environment Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесия 29.07.2026 — решение `един tenant = една отделна фирма`, активен tenant context, database-per-tenant, Tenant Guard, Master Data per tenant, TenantMembership/RoleAssignment, забрана за shared records, migration runner и support access.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).

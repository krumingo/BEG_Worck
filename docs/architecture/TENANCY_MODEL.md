# BEG_Work — Tenancy & Isolation Model

> **Решение:** D-15  
> **Дата:** 29.07.2026  
> **Статус:** APPROVED BUSINESS/ARCHITECTURE DECISION  
> **Свързани FLOW:** 002, 016, 032, 040, 042, 043, 044, 050

## 1. Основен модел

Един tenant представлява точно една юридическа фирма.

Всеки tenant използва един и същ BEG_Work core и FLOW-001–050, но има напълно отделни данни, конфигурация, права, номерации, файлове, интеграции, AI контекст, AuditEvent история и абонамент.

Не се създава отделен code fork или физическо копие на FLOW логиката за всяка фирма.

## 2. Active tenant context

Един User може да има membership в няколко tenant-а. Всяка работна сесия има един активен `tenant_id`.

При превключване се сменя целият фирмен контекст. Формите не позволяват свободен избор на фирма за всеки запис; backend определя tenant-а от проверената сесия.

## 3. Database per tenant

Стандартният модел е:

- общо приложение;
- централен Tenant Registry;
- отделна MongoDB база per tenant;
- отделно файлово пространство per tenant;
- възможност Enterprise tenant да бъде насочен към отделен cluster/deployment.

Това позволява отделни backup, restore, export, retention, migration и deletion операции.

## 4. Tenant Registry

Tenant Registry е централен технически регистър и не съдържа оперативните данни на фирмите.

Минимални полета:

```text
tenant_id
legal_name
company_identifier
status
subscription_status
plan_version_id
database_name / database_location
storage_location
deployment_id
schema_version
migration_status
last_migration_at
last_successful_migration
failed_migration
created_at
suspended_at
retention_state
```

## 5. Tenant Guard

Всички входни точки използват един централен Tenant Guard:

- REST/API;
- background jobs;
- file read/write;
- search;
- exports;
- notifications;
- AI tools/retrieval;
- webhooks и integrations;
- support sessions.

Guard-ът проверява User, active tenant, active membership, RoleAssignments, resource ownership и action scope. Cross-tenant read/write е denied by default.

## 6. Master Data per tenant

FLOW-032 е винаги per tenant.

Per-tenant бизнес данни са:

- Master Person/Organization;
- контрагенти и контакти;
- СМР;
- материали, артикули и aliases;
- доставчици и договорени цени;
- ценова история;
- Skill Matrix;
- business classifications и productivity history.

Глобални са само технически справочници без бизнес стойност: държави, валути, часови зони, system feature IDs, application/migration versions.

## 7. TenantMembership и FLOW-002

Няма втори permission engine.

```text
User
→ TenantMembership
   → RoleAssignments
```

TenantMembership доказва достъп до фирмата. RoleAssignments от FLOW-002 определят role/action/module/project/location/resource/amount/validity scope вътре в конкретното membership.

Роля в Tenant A не дава никакво право в Tenant B.

## 8. Отделни номерации

Всеки tenant има собствени sequence-и за:

- оферти;
- договори и анекси;
- фактури;
- плащания;
- Work Packages;
- дефекти;
- заявки, поръчки, доставки и други domain IDs.

Номерацията никога не се споделя между фирми.

## 9. Отделно файлово пространство

Файловете се адресират през FLOW-016 `file_id`, но физически и логически са tenant-scoped.

Пример:

```text
/tenants/{tenant_id}/...
```

Директен storage URL/path не заобикаля Tenant Guard. File metadata, relations, checksum, versions и backup state носят tenant ownership.

## 10. Отделни интеграции и secrets

Всеки tenant има собствени:

- банкови/счетоводни интеграции;
- email channels;
- storage adapters;
- API keys;
- webhook secrets;
- payment-provider references;
- external portals и communication channels.

System-wide credentials се използват само от строго ограничени platform services и никога не дават на normal support user свободен достъп до всички tenant данни.

## 11. AI isolation

BEG Brain наследява active tenant и user scope.

AI search, context, summaries, recommendations и tools не могат да използват данни от друг tenant. Cross-company Group Dashboard/analysis е отделна read-only projection, изисква изрично избрани tenant-и и право за всеки от тях.

## 12. Междуфирмени отношения

Две фирми, включително фирми на един собственик, работят помежду си като независими контрагенти.

Не се допуска shared Project/Invoice/Payment/WorkPackage между tenant-и.

Официалният модел е:

```text
Tenant A
→ Counterparty representation of Firm B
→ contract/request/package/act/invoice/payment
```

Group Dashboard е единственото разрешено обединяване и е read-only. Той не създава официални domain записи.

## 13. Migration runner

Database-per-tenant изисква централен migration runner, който:

1. чете Tenant Registry;
2. взема lock per tenant;
3. сравнява `schema_version`;
4. изпълнява липсващите migration steps;
5. валидира post-conditions;
6. записва per-tenant result и AuditEvent;
7. поддържа retry/idempotency;
8. прилага recovery/rollback plan при failure;
9. позволява canary tenant и staged rollout;
10. блокира release при критична непълна миграция.

Migration status не се отчита само глобално; всеки tenant има собствен резултат.

## 14. Support Access Request

Platform operator по подразбиране вижда само технически metadata: tenant status, subscription, deployment health, storage/database size, errors и migration status.

Достъп до бизнес данни изисква Support Access Request:

```text
support_ticket_id
tenant_id
support_user
reason
scope
access_mode
approved_by
start_at
expires_at
session_id
AuditEvent correlation
```

Поддържани режими:

- metadata only;
- read-only;
- restricted write;
- emergency break-glass.

Break-glass изисква двоен контрол, автоматично известяване на tenant owner, кратък срок и последващ доклад.

## 15. Backup, restore, export и deletion

Всеки tenant трябва да може да бъде:

- backup-нат;
- възстановен;
- export-нат;
- архивиран;
- преместен към друг deployment;
- изтрит след retention и legal-hold проверки;

без да се засягат останалите tenant-и.

`Subscription ended` не означава `data deleted`.

## 16. Задължителни isolation tests

Bootstrap QA Gate v0 / FLOW-042 трябва да доказва поне:

- Tenant A user не вижда Tenant B records;
- guessed/modified ID не пробива tenant boundary;
- files и signed links са tenant-scoped;
- search, dashboards и exports не смесват данни;
- AI retrieval/tools не използват чужд tenant;
- RoleAssignment в една фирма не дава право в друга;
- backup/restore и migration на един tenant не засягат друг;
- support access изтича и се audit-ва;
- cross-tenant shared operational record е технически забранен;
- migration retry е idempotent и version-correct.

## 17. Wave 0 задължителни deliverables

- Tenant Registry;
- Tenant Guard и database resolver;
- TenantMembership ↔ RoleAssignment integration;
- per-tenant Master Data foundation;
- per-tenant File Registry isolation;
- sequence/numbering service per tenant;
- integration/secret isolation;
- migration runner + `schema_version`;
- tenant-aware AuditEvent and idempotency;
- isolation test suite;
- Support Access Request и break-glass controls;
- per-tenant backup/restore/export proof.

## 18. Забрани

- общ operational collection без tenant boundary;
- tenant от свободно поле във форма;
- shared Project/Invoice/Payment между фирми;
- global Master Data с търговски данни;
- support staff да вижда бизнес данни без request;
- migration без per-tenant version/result;
- AI cross-tenant retrieval;
- private client fork като стандартен tenancy механизъм.

## 19. Одобрение и проследимост

Решението е одобрено от Крум на 29.07.2026 след преглед на пълната 14-точкова tenancy спецификация и допълненията за Master Data per tenant, FLOW-002 membership model, междуфирмени отношения и migration runner.

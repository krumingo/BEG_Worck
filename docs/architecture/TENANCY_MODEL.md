# BEG_Work — Tenancy & Isolation Model

> **Решение:** D-15  
> **Дата:** 29.07.2026; синхронизирано 04.08.2026  
> **Статус:** APPROVED BUSINESS/ARCHITECTURE DECISION  
> **Свързани FLOW:** 002, 016, 032, 040, 042, 043, 044, 050

## 1. Основен модел

Един tenant представлява точно една юридическа фирма.

Всеки tenant използва един и същ BEG_Work core и FLOW-001–050, но има отделни данни, конфигурация, права, номерации, File Registry, provider credentials, интеграции, AI контекст, AuditEvent история и абонамент.

Няма private client fork. Отделен Enterprise deployment не означава отделна версия; всеки deployment използва общ Release Manifest.

## 2. Active tenant context

Един User може да има membership в няколко tenant-а. Всяка работна сесия има един активен `tenant_id`, определен server-side от проверената сесия.

```text
User
→ TenantMembership
   → RoleAssignments
```

Роля в Tenant A не дава право в Tenant B.

## 3. Database per tenant

Стандартният модел е:

- общо приложение и codebase;
- централен Tenant Registry;
- отделна MongoDB база per tenant;
- customer-managed Primary Storage Provider per tenant;
- отделни File Registry metadata, credentials, numbering, integrations и AI context;
- възможност Enterprise tenant да бъде на отделен cluster/deployment, но със същия build/Release Manifest.

## 4. Tenant Registry

Tenant Registry пази техническата карта, не оперативните данни:

```text
tenant_id
legal_name
company_identifier
status
subscription_status
plan_version_id
database_name / database_location
primary_storage_provider_type
primary_storage_provider_reference
deployment_id
app_version
schema_version
configuration_version
release_manifest_id
migration_status
retention_state
created_at
suspended_at
```

Secrets и provider credentials са encrypted и tenant-scoped.

## 5. Tenant Guard

Всички входни точки използват един централен Tenant Guard:

- REST/API;
- background jobs;
- File Registry read/write;
- search и exports;
- notifications;
- AI tools/retrieval;
- webhooks и integrations;
- support sessions.

Guard-ът проверява User, active tenant, membership, RoleAssignments, resource ownership и action scope. Cross-tenant read/write е denied by default.

## 6. Master Data per tenant

FLOW-032 е винаги per tenant. Това включва Person/Organization, контрагенти, контакти, СМР, материали, доставчици, aliases, договорени цени, Skill Matrix и business history.

Глобални са само технически справочници без търговска стойност.

## 7. Отделни номерации

Всеки tenant има собствени sequence-и за оферти, договори, фактури, плащания, Work Packages, дефекти, заявки, поръчки, доставки и други domain IDs.

## 8. Customer-managed storage и File Registry

BEG_Work не хоства customer originals в Launch модела.

Всеки tenant задължително свързва собствен Primary Storage Provider:

- Google Drive / Shared Drive;
- Synology / NAS;
- S3-compatible storage;
- customer on-premise server;
- бъдещ adapter по общия contract.

Tenant activation изисква валидни credentials, read/write test, checksum round-trip и AuditEvent.

BEG_Work пази:

- File Registry;
- metadata и business relations;
- document families/versions;
- checksums и availability status;
- provider IDs и object paths;
- thumbnails, previews и OCR cache.

Клиентът отговаря за физическото съхранение, provider capacity и provider subscription.

Периодичната проверка установява missing object, permission error, checksum mismatch и невъзможност за preview regeneration. Проблемът създава Alarm/DQ issue + AuditEvent с всички засегнати business records.

## 9. Интеграции и secrets

Всеки tenant има отделни banking/accounting integrations, email channels, storage adapters, API keys, webhook secrets, payment-provider references и external portals.

System-wide credentials се използват само от ограничени platform services и не дават свободен support access до business data.

## 10. AI isolation

BEG Brain наследява active tenant и user scope. Search, summaries, recommendations и tools не могат да използват данни от друг tenant.

Group Dashboard е отделна read-only projection с изрично право за всеки включен tenant.

## 11. Междуфирмени отношения

Две фирми, включително свързани фирми, работят като независими контрагенти. Не се допуска shared Project/Invoice/Payment/WorkPackage.

```text
Tenant A
→ Counterparty representation of Firm B
→ contract/request/package/act/invoice/payment
```

## 12. Migration runner

Migration runner-ът:

1. чете Tenant Registry;
2. взема per-tenant lock;
3. сравнява `schema_version`;
4. изпълнява липсващите steps;
5. валидира post-conditions;
6. записва result и AuditEvent;
7. поддържа idempotent retry;
8. има recovery/rollback plan;
9. позволява canary/staged rollout;
10. блокира release при критична непълна миграция.

## 13. Support Access Request

Platform operator по подразбиране вижда само технически metadata.

Достъп до business data изисква Support Access Request с tenant, reason, scope, access mode, approved_by, start/expiry, session и AuditEvent correlation.

Режими: metadata-only, read-only, restricted-write и emergency break-glass. Break-glass изисква двоен контрол, owner notification и последващ доклад.

## 14. Backup, restore, export, retention и deletion

Всеки tenant трябва да може да бъде backup-нат, възстановен, export-нат, преместен и контролиранo изтрит без влияние върху други tenant-и.

`Subscription ended` не означава `data deleted`.

Стандартният termination path е:

```text
request
→ export
→ 90-day read-only retention
→ legal/incident hold check
→ explicit Approval
→ controlled deletion
→ signed disposition manifest
```

BEG_Work-managed deletion включва tenant DB, File Registry, caches, credentials, indexes, configuration и temporary exports. Customer-managed originals не се изтриват от стандартния процес.

## 15. Задължителни isolation tests

- Tenant A не вижда Tenant B records;
- guessed/modified ID не пробива boundary;
- File Registry, signed links и provider credentials са tenant-scoped;
- search, dashboards, exports и AI не смесват данни;
- RoleAssignment в една фирма не дава право в друга;
- migration/backup/restore на един tenant не засяга друг;
- support access изтича и се audit-ва;
- customer Storage Provider activation и checksum alarms работят;
- no-private-fork и Release Manifest rules се спазват;
- deletion не засяга customer-managed originals.

## 16. Wave 0 deliverables

- Tenant Registry;
- Tenant Guard/database resolver;
- TenantMembership ↔ RoleAssignment;
- per-tenant Master Data;
- customer-managed Storage Provider adapters и activation gate;
- tenant-scoped File Registry;
- numbering service;
- integration/secret isolation;
- migration runner;
- tenant-aware AuditEvent/idempotency;
- isolation tests;
- Support Access/Break-glass;
- per-tenant backup/restore/export/retention/deletion proof;
- common Release Manifest/no-fork enforcement.

## 17. Забрани

- общ operational collection без tenant boundary;
- tenant от свободно поле във форма;
- shared Project/Invoice/Payment между фирми;
- global Master Data с търговска стойност;
- support access без request;
- migration без per-tenant version/result;
- AI cross-tenant retrieval;
- private client fork;
- customer originals в BEG_Work quota като Launch модел;
- automatic deletion поради non-payment или изтекъл retention.

## 18. Проследимост

- D-15 е одобрено на 29.07.2026.
- Customer-managed storage е заключено на 03.08.2026.
- Common-code/no-fork, environments, retention и controlled deletion са заключени на 04.08.2026.

# FLOW-050 Final Governance / Environments / Retention Decision — 04.08.2026

> **Статус:** APPROVED BUSINESS DECISION  
> **Резултат:** FLOW-050 → 100% Business Lock  
> **Засегнати FLOW:** 016, 033, 034, 040, 042, 043, 044, 050  
> **PR:** Draft PR #2 — не се слива автоматично

## 1. Един общ код; без private forks

Всички tenant-и използват един общ BEG_Work код.

Позволената стълбица за клиентска нужда е:

```text
настройки
→ шаблони
→ Feature Flags / Entitlements
→ одобрени extension точки
→ обща продуктова функционалност за всички
→ или „не“
```

Одобрените extension точки могат да включват custom полета, справки, webhooks, API и Adapter интеграции, но винаги:

- са в общия код;
- са зад Feature Flag/Entitlement;
- минават през общия QA;
- участват в общия Release Manifest;
- не създават частен клиентски fork.

Отделна Enterprise инфраструктура или сървър не означава отделна версия. Tenant Registry пази точната обща app version, schema version, configuration version и Release Manifest за всеки deployment.

Всяко изключение изисква решение на Собственика на BEG_Work и ново D-решение във FLOW-043. Изключение не може да възникне тихо чрез проектна или клиентска договорка.

## 2. Среди и release governance

Каноничните среди са:

```text
Development
→ Test
→ Staging
→ Production
```

Всеки deployment пази:

- environment;
- tenant/deployment scope;
- app version;
- schema version;
- configuration version;
- Feature Flags/Entitlements snapshot;
- Release Manifest;
- дата/час;
- deployed_by и approved_by;
- rollback target;
- post-deployment verification result.

Production данни и secrets не се копират свободно в Development/Test/Staging. Използват се синтетични или анонимизирани данни и environment-specific credentials.

Production release изисква тестове, migration validation, tenant-isolation проверки, Approval, rollback plan и AuditEvent.

## 3. Tenant Acceptance Environment

Tenant Acceptance Environment (TAE) е договорна Enterprise приемателна среда, не отделен продукт и не отделен code branch.

Процесът е:

```text
Release Candidate
→ TAE deployment
→ клиентски приемателни тестове
→ exact-version Acceptance Receipt
→ Production deployment
```

Acceptance Receipt сочи към точни:

- app version;
- Release Manifest;
- schema/configuration version;
- Feature Flags/Entitlements;
- test evidence;
- одобрил представител и scope.

## 4. Termination и export

Прекратяването е отделен процес от неплатен абонамент.

```text
Termination Request
→ identity/authority check
→ obligations/disputes check
→ export preparation
→ customer confirmation
→ tenant read-only
→ retention
→ legal/incident hold check
→ deletion approval
→ controlled deletion
→ signed disposition manifest
```

Стандартният export включва машинночетими и човешки четими данни:

- business records и Master Data;
- финансови регистри;
- users, memberships и roles;
- обекти, договори, оферти, актове, фактури и плащания;
- задачи, отчети, склад и активи;
- DQ/Approval история;
- File Registry, versions, relations, provider identifiers и checksums;
- AuditEvent export според правата;
- tenant configuration и manifest.

Поддържани формати: JSON, CSV/XLSX, PDF справки, manifest и checksums.

Оригиналните клиентски файлове остават в customer-managed Storage Provider. Стандартният export не е длъжен да ги копира повторно, но включва техните provider IDs, paths/object keys, checksums, relations и списък на липсващи/недостъпни originals.

## 5. Стандартен retention

След прекратяване стандартният Launch retention е:

> **90 дни read-only.**

През този период:

- Owner/Admin може да влиза;
- може да изтегли export;
- може да плати остатъчни задължения;
- може да поиска възстановяване;
- не се създава нова оперативна дейност;
- AI и background automations са спрени;
- интеграциите и credentials се деактивират безопасно.

Enterprise може договорно да има по-дълъг retention.

Legal/incident hold блокира deletion независимо от изтеклия срок.

## 6. Controlled deletion

Изтичането на retention периода не стартира автоматично изтриване.

Изисква се едновременно:

```text
retention expired
+ няма legal/incident hold
+ export е предложен
+ клиентът е уведомен
+ изрично Approval
+ deletion job
+ verification
+ signed disposition manifest
```

BEG_Work изтрива само управляваните от него данни:

- tenant database;
- File Registry;
- thumbnails/previews/OCR cache;
- credentials и integration tokens;
- indexes;
- tenant configuration;
- временни exports;
- технически данни според retention policy.

BEG_Work не изтрива оригиналните файлове в customer-managed Storage Provider, освен при отделно изрично договорено и потвърдено действие.

## 7. Финален Approval каталог

Approval се изисква поне за:

- Enterprise tenant и договорни промени;
- custom entitlement, custom цена или ръчна отстъпка;
- повторен/удължен Trial;
- chargeback restoration;
- Support/Partner Access Grant и break-glass достъп;
- export от името на клиента;
- Production release, критична миграция и rollback;
- TAE acceptance;
- termination;
- промяна на retention;
- deletion approval;
- всяко изключение от no-private-fork принципа.

## 8. Финален AuditEvent каталог

Задължителни event types:

```text
TENANT_CREATED
TENANT_ACTIVATED
TENANT_CONFIGURATION_CHANGED
ENTITLEMENT_GRANTED
ENTITLEMENT_REVOKED
PLAN_UPGRADED
PLAN_DOWNGRADED
TRIAL_STARTED
TRIAL_EXTENDED
TRIAL_EXPIRED
PARTNER_ACCESS_GRANTED
PARTNER_ACCESS_USED
PARTNER_ACCESS_REVOKED
SUPPORT_ACCESS_GRANTED
SUPPORT_ACCESS_USED
SUPPORT_ACCESS_REVOKED
RELEASE_DEPLOYED
RELEASE_ROLLED_BACK
TAE_ACCEPTED
TAE_REJECTED
TERMINATION_REQUESTED
EXPORT_STARTED
EXPORT_COMPLETED
RETENTION_STARTED
LEGAL_HOLD_APPLIED
LEGAL_HOLD_RELEASED
DELETION_APPROVED
DELETION_EXECUTED
DISPOSITION_MANIFEST_CREATED
```

Всеки критичен AuditEvent пази tenant, actor, effective role, причина, source request, Approval, exact version/configuration, correlation ID, evidence, previous/new state, result и timestamp.

## 9. Приемателни тестове

- отделен deployment използва същия общ Release Manifest;
- няма runtime fork по tenant;
- TAE acceptance е exact-version;
- production secrets не се използват в non-production;
- termination не се стартира от dunning/suspension;
- export е проверим и съдържа manifest/checksums;
- 90-дневният retention е read-only;
- изтекъл retention не изтрива автоматично;
- legal hold блокира deletion;
- deletion изисква Approval и signed disposition manifest;
- customer-managed originals не се изтриват от стандартния BEG_Work deletion job;
- всички lifecycle действия имат AuditEvent.

## 10. Източник

Финално потвърждение на Крум Радулов от 04.08.2026.

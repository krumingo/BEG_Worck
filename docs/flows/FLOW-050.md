# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 04.08.2026  
> **Оставащи решения:** 0  
> **Implementation Gate:** W0-BLOCKER за tenancy/billing foundations; environments, retention и entitlements се проверяват отделно по FLOW-042  
> **Свързани FLOW:** 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 016, 019, 020, 021, 023, 024, 027, 028, 030, 031, 033, 034, 035, 037, 038, 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 049

## 1. Цел

FLOW-050 определя как BEG_Work се предоставя на отделни фирми като SaaS продукт: tenant модел, изолация, абонамент, пакети, feature entitlements, AI бюджети, integrations, плащане, trial/demo/partner режими, support access, среди, release governance, прекратяване, export, retention и controlled deletion.

## 2. Tenant и изолация

- един tenant = една юридическа фирма;
- една активна сесия работи с един проверен `tenant_id`;
- един User може да има няколко `TenantMembership` записа;
- правата идват от FLOW-002 `RoleAssignment`;
- всеки tenant има отделна MongoDB база, номерации, integrations/credentials, AI context и AuditEvent история;
- всички API, jobs, exports, search, files и AI tools минават през Tenant Guard;
- между tenant-и няма shared operational records;
- support достъпът е временен, scoped, одобрен и auditable;
- migration runner-ът е idempotent и пази `schema_version` per tenant.

## 3. CORE enforcement във всички пакети

Пакетите не могат да изключат Tenant Guard, Permission Service, MFA, единния Payment ledger, idempotency, AuditEvent, DQ blocking, задължителните Approval проверки, exact-version approval, no-hard-delete, File Registry/versioning и забраната AI да извършва критично действие без права и потвърждение.

## 4. Пакети по цели модули

Не се допуска половин модул. Неотделимото ядро присъства във всички платени пакети: обекти, роли, базови контрагенти, пълни финанси, Payment ledger, P&L, присъствие/отчети/труд, payroll, режийни, получени фактури, File Registry, базови справки, аларми и мобилен достъп.

### Start — „Фирмата“

`Знаеш резултата.` — цялото неотделимо ядро.

### Control — „Контролът“

`Контролираш резултата.` — Start плюс оферти/КСС, договори, допълнителни СМР, актуване, график/прогрес, материални заявки и доставки, склад/FIFO, логистика, подизпълнителски пакети, активи/QR, качество и Work Packages.

### Pro — „Автопилотът“

`Системата работи за теб.` — Control плюс BEG Brain, AI Command Center, автоматично офериране, Procurement Agent, Scenario, Resource Assignment, Managed Work Package, пълни DQ/Approval/Audit екрани, Client Portal, разширен payroll, прогнози и risk analysis.

### Enterprise

Pro + договорени корпоративни услуги: SSO, специални интеграции, отделни среди, TAE, SLA, корпоративни exports, extensions без private fork, BYOK и приоритетна поддръжка.

## 5. Feature Entitlements

```text
Feature Catalog
Plan
Plan Version
Plan Entitlement
Tenant Entitlement
Usage Limit
Feature Flag
```

Runtime достъпът изисква едновременно tenant entitlement и user permission. `Plan Version` е immutable. Downgrade не трие данни: изключените модули остават read-only и исторически видими.

## 6. Цена и потребители

BEG_Work се продава с фиксирана цена на tenant. Всички пакети включват неограничени Full/Field/External Users и неограничен брой обекти.

| Пакет | Месечно | Годишно |
|---|---:|---:|
| Start | 19,90 € | 199 € |
| Control | 39,90 € | 399 € |
| Pro | 79,90 € | 799 € |
| Enterprise | от 149 € | индивидуално |

Цените са Launch Pricing v1 без ДДС и не се променят мълчаливо за съществуващи клиенти.

## 7. Customer-managed storage

BEG_Work не хоства клиентските оригинални файлове. Всеки tenant задължително свързва собствен Primary Storage Provider при onboarding. Без валидни credentials, read/write тест и checksum round-trip tenant-ът не се активира.

Клиентът отговаря за физическото съхранение и капацитета. BEG_Work отговаря за File Registry, metadata, relations, versions, checksums, availability status, previews/OCR cache и приложната база.

Канонично решение: [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](../architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md).

## 8. План + AI

| План | Включени AI действия/месец |
|---|---:|
| Start | 100 |
| Control | 500 |
| Pro | 2 000 |
| Enterprise | договорен бюджет или BYOK |

AI add-ons:

- AI+ — 500 действия / 9,90 €;
- AI Pro — 2 000 действия / 24,90 €;
- AI Max — 5 000 действия / 49,90 €.

Клиентът вижда used/remaining, разбивка по функция, тенденция и препоръка за план + AI пакет. При 80% има предупреждение; при 100% се паузират само AI функциите. Основната работа не спира.

Канонично решение: [FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md](../architecture/FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md).

## 9. Имейл акаунти и интеграции

| План | Имейл акаунти | Стандартни интеграции |
|---|---:|---:|
| Start | 2 | 2 |
| Control | 10 | 10 |
| Pro | 30 | 30 |
| Enterprise | договорени | договорени |

Add-on `+5` струва 5 €/месец. Съществуващите връзки не се спират при достигнат лимит. Storage adapter и системният изходящ email не се броят. Специални банкови, счетоводни и custom интеграции могат да имат отделна цена.

## 10. Subscription / Billing / Dunning

- месечен и годишен абонамент се плащат предварително;
- автоматично подновяване;
- отказът влиза в сила в края на платения период;
- Upgrade — веднага, с pro-rata доплащане;
- Downgrade — от следващия billing период;
- AI add-on — веднага pro-rata, отказ от следващ период;
- Enterprise промени — чрез договор/анекс и Approval;
- Payment Provider Adapter е provider-neutral;
- Start/Control/Pro: карта и auto-renew;
- Enterprise: фактура и банков превод;
- BEG_Work не съхранява номера на карти;
- FLOW-050 остава source of truth за Subscription, Plan, Billing Period, Entitlements и Access State;
- webhook-ите са подписани, идемпотентни и проверяват event ID, сума, валута, tenant и billing period;
- автоматични повторни опити на ден 0, 3 и 7;
- от ден 0 известията отиват до Owner, финансовия администратор и billing контактите;
- ден 0–7: `GRACE`;
- ден 8–14: `RESTRICTED`;
- след ден 14: `SUSPENDED`;
- chargeback: незабавно `SUSPENDED_CHARGEBACK`, restoration само ръчно с доказателства и AuditEvent.

> **Неплатен абонамент никога не изтрива данни.**

Канонично решение: [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).

## 11. Trial / Demo / Partner

### Trial

- 14 дни Pro;
- 500 AI действия общо;
- неограничени потребители и обекти;
- задължителен Primary Storage Provider;
- без задължителна карта;
- един trial за едно ЕИК;
- повторен trial или удължаване само с manual approval и AuditEvent;
- след изтичане: 14 дни read-only → suspended;
- paid conversion запазва същия tenant и данни.

### Demo

За launch Demo е само за търговски презентации с шаблонни несекретни данни, периодичен reset и без conversion към production.

### Partner

Няма автоматичен достъп до клиентски tenant-и. Достъп се дава само чрез изричен, time-limited, revocable и auditable `Partner Access Grant` с Approval.

Канонично решение: [FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md](../architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md).

## 12. Modern Field Experience

Modern Field Experience разширява FLOW-037/030 и е общ продуктов принцип:

- PWA и offline-first;
- универсален вход `СНИМАЙ / КАЖИ / СКАНИРАЙ`;
- voice-to-record и camera-first с човешко потвърждение;
- оригиналното аудио и оригиналната снимка се пазят във File Registry преди AI обработка;
- role-aware екран `Днес`;
- контекстна комуникация, без общ чат;
- realtime push за оперативното и Daily Digest за останалото;
- QR-first действия;
- Action Inbox, passkeys и базови context suggestions във Wave 2;
- Live Activities/App Clips само при бъдещо отделно native решение;
- Digital Twin Lite отпада напълно.

Канонично решение: [MODERN_FIELD_EXPERIENCE_2026-08-04.md](../architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md).

## 13. Един общ код; без private forks

Позволената стълбица е:

```text
настройки
→ шаблони
→ Feature Flags / Entitlements
→ одобрени extension точки
→ обща продуктова функционалност за всички
→ или „не“
```

Custom полета, справки, webhooks, API и Adapter интеграции са допустими само в общия код, зад flag/entitlement, през общия QA и Release Manifest.

Отделен Enterprise сървър не означава отделна версия. Tenant Registry пази точната обща app/schema/configuration version и Release Manifest. Изключение изисква решение на Собственика на BEG_Work и ново D-решение във FLOW-043.

## 14. Среди и Tenant Acceptance Environment

```text
Development
→ Test
→ Staging
→ Production
```

Всеки deployment пази environment, tenant/deployment scope, app version, schema version, configuration version, Feature Flags/Entitlements snapshot, Release Manifest, deployed_by, approved_by, rollback target и post-deployment result.

Production данни и secrets не се копират свободно в non-production. Използват се синтетични или анонимизирани данни и environment-specific credentials.

TAE е договорна Enterprise приемателна среда със същия общ build:

```text
Release Candidate
→ TAE
→ клиентски тестове
→ exact-version Acceptance Receipt
→ Production
```

Acceptance Receipt сочи към exact app version, Release Manifest, schema/configuration version, Feature Flags/Entitlements и test evidence.

## 15. Termination / Export / Retention / Controlled Deletion

Прекратяването е отделно от неплатен абонамент:

```text
Termination Request
→ identity/authority check
→ obligations/disputes check
→ export
→ read-only
→ retention
→ legal/incident hold check
→ deletion approval
→ controlled deletion
→ signed disposition manifest
```

Стандартният Launch retention е **90 дни read-only**. Owner/Admin може да влиза, да изтегли export, да плати остатъчни задължения и да поиска restoration; нова оперативна дейност, AI и automations са спрени. Enterprise може договорно да има по-дълъг срок.

Export включва business records, Master Data, финанси, users/roles, обекти, договори, оферти, актове, фактури, плащания, задачи, отчети, склад, активи, DQ/Approval, File Registry, versions/relations/checksums, AuditEvent според правата, configuration и manifest. Формати: JSON, CSV/XLSX, PDF, manifest и checksums.

Оригиналните файлове остават в customer-managed Storage Provider. Стандартният export включва provider IDs, paths/object keys, checksums, relations и списък на липсващи originals, но не е длъжен да ги копира повторно.

Изтекъл retention не стартира автоматично deletion. Нужно е: няма hold, export е предложен, клиентът е уведомен, има изрично Approval, deletion job, verification и signed disposition manifest.

BEG_Work изтрива само tenant database, File Registry, previews/OCR cache, credentials/tokens, indexes, configuration, временни exports и управлявани технически данни. Customer-managed originals не се изтриват, освен при отделно изрично договорено действие.

## 16. Финален Approval и AuditEvent каталог

Approval се изисква поне за Enterprise/custom договорни промени, custom entitlement/цена/отстъпка, повторен/удължен Trial, chargeback restoration, Support/Partner/Break-glass Access, export от името на клиента, Production release, критична миграция/rollback, TAE acceptance, termination, retention change, deletion и изключение от no-private-fork.

Задължителни AuditEvent types включват:

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

Всеки критичен event пази tenant, actor, effective role, причина, source request, Approval, exact version/configuration, correlation ID, evidence, previous/new state, result и timestamp.

Канонично финално решение: [FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md](../architecture/FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md).

## 17. Източници / сесии

- FLOW-016 — customer-managed Storage Provider и File Registry.
- FLOW-037/030 — Modern Field Experience.
- FLOW-042 — Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесии 29.07–04.08.2026 — всички изрични решения на Крум по tenancy, packages, pricing, storage, AI, billing, trial/demo/partner, no-fork, environments, retention и controlled deletion.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).
- [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](../architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md).
- [FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md](../architecture/FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md).
- [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).
- [FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md](../architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md).
- [MODERN_FIELD_EXPERIENCE_2026-08-04.md](../architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md).
- [FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md](../architecture/FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md).

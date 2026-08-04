# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 95% — BUSINESS DESIGN IN PROGRESS  
> **Последна проверка:** 04.08.2026  
> **Оставащи решения:** 1  
> **Implementation Gate:** W0-BLOCKER за multi-tenant основата; billing, environments и entitlements се проверяват отделно  
> **Свързани FLOW:** 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 016, 019, 020, 021, 023, 024, 027, 028, 030, 031, 033, 034, 035, 038, 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 049

## 1. Цел

FLOW-050 определя как BEG_Work се предоставя на отделни фирми като SaaS продукт: tenant модел, изолация, абонамент, модулни пакети, feature entitlements, плащане, trial/demo/partner режими, support access, среди, прекратяване и export.

## 2. Tenant и изолация

- един tenant = една юридическа фирма;
- една активна сесия работи с един проверен `tenant_id`;
- един User може да има няколко `TenantMembership` записа;
- правата идват от FLOW-002 `RoleAssignment`, без втори permission модел;
- всеки tenant има отделна MongoDB база, номерации, integrations/credentials, AI context и AuditEvent история;
- всички API, jobs, exports, search, files и AI tools минават през Tenant Guard;
- между tenant-и няма shared operational records;
- support достъпът е временен, scoped, одобрен и auditable;
- migration runner-ът е idempotent и пази `schema_version` per tenant.

## 3. CORE enforcement във всички пакети

Пакетите не могат да изключат:

- Tenant Guard и tenant isolation;
- Permission Service и MFA;
- единен Payment ledger;
- idempotency;
- AuditEvent;
- DQ blocking rules;
- задължителните Approval проверки;
- exact-version approval;
- no hard delete на използвани записи;
- File Registry и versioning;
- забраната AI да извършва критично действие без права и потвърждение.

## 4. Пакети по цели модули

Не се допуска половин модул. Неотделимото ядро присъства във всички платени пакети: обекти, роли, базови контрагенти, пълни финанси, Payment ledger, P&L, присъствие/отчети/труд, payroll, режийни, получени фактури, File Registry, базови справки, аларми и мобилен достъп.

### Start — „Фирмата“

`Знаеш резултата.`

Цялото неотделимо ядро.

### Control — „Контролът“

`Контролираш резултата.`

Start плюс оферти/КСС, договори, допълнителни СМР, актуване, график/прогрес, материални заявки и доставки, склад/FIFO, логистика, подизпълнителски пакети, активи/QR, качество и Work Packages.

### Pro — „Автопилотът“

`Системата работи за теб.`

Control плюс BEG Brain, AI Command Center, автоматично офериране, Procurement Agent, Scenario, Resource Assignment, Managed Work Package, пълни DQ/Approval/Audit екрани, Client Portal, разширен payroll, прогнози и risk analysis.

### Enterprise

Pro + договорени корпоративни услуги: SSO, специални интеграции, отделни среди, Tenant Acceptance Environment, SLA, корпоративни exports, extensions без private fork, BYOK и приоритетна поддръжка.

## 5. Feature Entitlements

Каноничният модел е:

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

### Launch Pricing v1 — без ДДС

| Пакет | Месечно | Годишно |
|---|---:|---:|
| Start | 19,90 € | 199 € |
| Control | 39,90 € | 399 € |
| Pro | 79,90 € | 799 € |
| Enterprise | от 149 € | индивидуално |

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

## 10. Subscription lifecycle

- месечен и годишен абонамент се плащат предварително;
- автоматично подновяване;
- отказът влиза в сила в края на платения период;
- няма частично възстановяване при доброволно прекратяване, освен при доказана грешка на BEG_Work;
- Upgrade — веднага, с pro-rata доплащане;
- Downgrade — от следващия billing период;
- AI add-on — веднага pro-rata, отказ от следващ период;
- Enterprise промени — чрез договор/анекс и Approval.

## 11. Payment Provider Adapter

BEG_Work използва provider-neutral `Payment Provider Adapter`.

- Start/Control/Pro: карта и автоматично подновяване;
- Enterprise: фактура и банков превод;
- BEG_Work не съхранява номера на карти;
- FLOW-050 остава source of truth за Subscription, Plan, Billing Period, Entitlements и Access State;
- операторът не включва/изключва tenant достъпа директно;
- webhook-ите са подписани, идемпотентни и проверяват event ID, сума, валута, tenant и billing period;
- фактурите се пазят във File Registry; корекциите са с кредитно известие.

## 12. Dunning / Grace / Restricted / Suspended

- автоматични повторни опити на ден 0, 3 и 7;
- от ден 0 известията отиват до Owner, финансовия администратор и billing контактите;
- ден 0–7: `GRACE`, системата работи нормално;
- ден 8–14: `RESTRICTED`, ограничават се AI, нови интеграции, add-ons, нови обекти и нови покани, но текущите финанси и операции продължават;
- след ден 14: `SUSPENDED`, основно read-only с плащане, export, важни документи и support;
- нормално възстановяване след проверено плащане е автоматично и идемпотентно.

Chargeback е отделен път: незабавно `SUSPENDED_CHARGEBACK`, а restoration е само с ръчно решение, доказателства и AuditEvent.

> **Неплатен абонамент никога не изтрива данни.**

Канонично решение: [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).

## 13. Trial tenant

Trial е реален tenant със следните параметри:

- срок: **14 дни**;
- пакет: **Pro**;
- AI бюджет: **500 AI действия общо**;
- потребители: неограничени;
- обекти: неограничени;
- Primary Storage Provider: задължителен;
- карта: не е задължителна;
- един trial за едно ЕИК.

Повторен trial за същото ЕИК и ръчно удължаване се допускат само с manual approval, причина и AuditEvent.

При изтичане:

```text
TRIAL_ACTIVE — 14 дни
→ TRIAL_READ_ONLY — 14 дни
→ TRIAL_SUSPENDED
```

Данните не се изтриват автоматично. При платена активация се запазват същият tenant и същите данни, без миграция.

## 14. Demo tenant

За launch Demo се използва само за търговски презентации, водени от BEG_Work.

- само шаблонни, несекретни данни;
- без реални клиентски credentials и платежни методи;
- периодичен reset;
- никога не се превръща в production tenant;
- per-visitor клониране не се разработва за launch.

## 15. Partner tenant

Partner tenant може да има безплатен или договорно намален абонамент, но няма автоматичен достъп до клиентски tenant-и.

Достъп до клиент се дава само чрез изричен `Partner Access Grant`, който е tenant-scoped, time-limited, role/action/resource-scoped, revocable и auditable. Grant-ът изисква одобрение от клиента/Owner според матрицата на права.

Канонично решение за Trial/Demo/Partner: [FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md](../architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md).

## 16. Оставащо решение

Финално обединено решение за:

- tenant configuration срещу private extension;
- забрана за client forks;
- Test / Staging / Production;
- Tenant Acceptance Environment;
- termination, export, retention и controlled deletion;
- финален AuditEvent / Approval catalog за billing, support и tenant lifecycle.

## 17. Източници / сесии

- FLOW-016 — customer-managed Storage Provider и File Registry.
- FLOW-042 — Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесии 29.07–04.08.2026 — tenancy, packages, pricing, storage, Plan + AI, integrations, subscription lifecycle, Payment Provider Adapter, dunning, chargeback, Trial/Demo/Partner и no-deletion rule.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).
- [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](../architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md).
- [FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md](../architecture/FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md).
- [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).
- [FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md](../architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md).

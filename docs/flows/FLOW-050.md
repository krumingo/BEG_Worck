# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 90% — BUSINESS DESIGN IN PROGRESS  
> **Последна проверка:** 04.08.2026  
> **Оставащи решения:** 2  
> **Implementation Gate:** W0-BLOCKER за multi-tenant основата; billing и entitlements се проверяват отделно  
> **Свързани FLOW:** 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 016, 019, 020, 021, 023, 024, 027, 028, 030, 031, 033, 034, 035, 038, 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 049

## 1. Цел

FLOW-050 определя как BEG_Work се предоставя на отделни фирми като SaaS продукт: tenant модел, изолация, абонамент, модулни пакети, feature entitlements, плащане за системата, support access, среди, прекратяване и export.

## 2. Заключено решение: един tenant = една отделна фирма

Един tenant представлява точно една юридическа фирма. Всеки tenant използва един и същ core продукт и логика FLOW-001–050, но има напълно отделни оперативни и финансови данни, Master Data, memberships, роли, обекти, документи, фактури, плащания, каси, банки, складове, номерации, интеграции, AI контекст, AuditEvent история, абонамент и настройки.

Потребителят не избира фирма във всяка форма. Tenant-ът се определя от активната проверена сесия.

## 3. Един акаунт, няколко tenant membership-а

Един User може да има достъп до няколко фирми, но всяка работна сесия има един активен `tenant_id`.

```text
User
→ TenantMembership
   → RoleAssignments от FLOW-002
```

TenantMembership определя дали човекът принадлежи към фирмата. RoleAssignment определя какво може да прави в нея.

## 4. Заключено решение: изолация на данните

Всеки tenant има отделна MongoDB база, номерации, integrations/credentials, backup/restore/export scope и AI retrieval scope.

Централен `Tenant Registry` пази `tenant_id`, юридическа фирма, database location, customer-managed storage provider, status, subscription, deployment и `schema_version`.

Всички API, background jobs, exports, search, files и AI tools минават през Tenant Guard. Между tenant-и няма shared operational records. Support достъпът е временен, scoped, одобрен и auditable.

## 5. CORE enforcement важи за всички пакети

CORE за всички пакети са:

- Tenant Guard и tenant isolation;
- Permission Service и MFA;
- единен Payment ledger;
- idempotency;
- AuditEvent;
- DQ blocking rules;
- задължителни Approval проверки;
- exact-version approval;
- no hard delete на използвани записи;
- File Registry и versioning;
- AI не извършва критично действие без права и потвърждение.

## 6. Заключен принцип: пакетите са по цели модули

Модул е отделим само ако финансовият резултат остава пълен без него, никое заключено правило не го изисква и данните му се вливат към задължителната финансова истина.

Неотделимото ядро присъства във всички платени пакети: обекти, роли, базови контрагенти, пълни финанси, Payment ledger, P&L, присъствие/отчети/труд, payroll, режийни, получени фактури, File Registry, базови справки, аларми и мобилен достъп.

## 7. Финална модулна карта

### Start — „Фирмата“

`Знаеш резултата.`

Съдържа цялото неотделимо ядро и позволява малка фирма да управлява дейността си от начало до край и да знае реално печели ли.

### Control — „Контролът“

`Контролираш резултата.`

Start плюс оферти/КСС, договори, допълнителни СМР, актуване, график/прогрес, материални заявки и доставки, склад/FIFO, логистика, подизпълнителски пакети, активи/QR, качество и Work Packages.

### Pro — „Автопилотът“

`Системата работи за теб.`

Control плюс BEG Brain, AI Command Center, автоматично офериране, Procurement Agent, Scenario, Resource Assignment, Managed Work Package, пълни DQ/Approval/Audit екрани, Client Portal, разширен payroll, прогнози и risk analysis.

### Enterprise

Pro + договорени корпоративни услуги: SSO, специални интеграции, отделни среди, TAE, SLA, корпоративни exports, extensions без private fork, BYOK и приоритетна поддръжка.

## 8. Feature Entitlements

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

Runtime достъпът изисква едновременно tenant entitlement и user permission.

## 9. Без таксуване на потребители и обекти

BEG_Work се продава с фиксирана цена на tenant. Всички пакети включват неограничени Full/Field/External Users и неограничен брой обекти.

## 10. Launch Pricing v1 — без ДДС

| Пакет | Месечно | Годишно |
|---|---:|---:|
| Start | 19,90 € | 199 € |
| Control | 39,90 € | 399 € |
| Pro | 79,90 € | 799 € |
| Enterprise | от 149 € | индивидуално |

## 11. Downgrade правило

При downgrade данните от изключените модули остават read-only и исторически видими. Неотделимото ядро, финансовата истина и историческият P&L никога не се изключват.

## 12. Customer-managed storage

BEG_Work не хоства клиентските оригинални файлове. Всеки tenant задължително свързва собствен Primary Storage Provider при onboarding. Без валидни credentials, read/write тест и checksum round-trip tenant-ът не се активира.

Клиентът отговаря за физическото съхранение и капацитета. BEG_Work отговаря за File Registry, metadata, relations, versions, checksums, availability status, previews/OCR cache и приложната база.

Канонично решение: [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](../architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md).

## 13. План + AI

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

## 14. Имейл акаунти и интеграции

| План | Имейл акаунти | Стандартни интеграции |
|---|---:|---:|
| Start | 2 | 2 |
| Control | 10 | 10 |
| Pro | 30 | 30 |
| Enterprise | договорени | договорени |

Add-on `+5` струва 5 €/месец. Съществуващите връзки не се спират при достигнат лимит. Storage adapter и системният изходящ email не се броят. Специални банкови, счетоводни и custom интеграции могат да имат отделна цена.

## 15. Subscription lifecycle

### Месечен и годишен

- плащане предварително;
- автоматично подновяване;
- отказът влиза в сила в края на платения период;
- няма частично възстановяване при доброволно прекратяване, освен при доказана грешка на BEG_Work.

### Upgrade / downgrade

- Upgrade — веднага, с pro-rata доплащане;
- Downgrade — от следващия billing период;
- AI add-on — активира се веднага pro-rata, отказва се от следващ период;
- Enterprise промени — чрез договор/анекс и Approval.

## 16. Payment Provider Adapter

BEG_Work използва provider-neutral `Payment Provider Adapter`.

- Start/Control/Pro: карта и автоматично подновяване;
- Enterprise: фактура и банков превод;
- BEG_Work не съхранява номера на карти;
- операторът връща payment events, но FLOW-050 остава source of truth за Subscription, Plan, Billing Period, Entitlements и Access State;
- операторът не включва/изключва tenant достъпа директно;
- webhook-ите са подписани, идемпотентни и проверяват event ID, сума, валута, tenant и billing period;
- фактурите се пазят във File Registry; корекциите са с кредитно известие.

## 17. Dunning / Grace / Restricted / Suspended

### Автоматични опити

Повторни опити за плащане се правят на ден 0, 3 и 7. Всеки опит създава Payment Attempt и AuditEvent.

### Известия

От ден 0 всички известия се изпращат задължително до Owner, финансовия администратор и договорените billing контакти.

### Ден 0–7: GRACE

Системата работи нормално.

### Ден 8–14: RESTRICTED

Ограничават се AI, нови интеграции, add-ons, нови обекти и нови покани. Не се блокират фактури, плащания, каса/банка, присъствие, дневни отчети, текущи операции, аварийни действия, export и support.

### След ден 14: SUSPENDED

Tenant-ът е основно read-only. Owner/Admin могат да влязат, да преглеждат данните, да платят, да export-нат, да свалят важни документи и да ползват support.

### Restoration

При нормално просрочие провереното плащане възстановява абонамента автоматично и идемпотентно.

## 18. Chargeback — отделен път

Chargeback не минава през 7/7/14 стълбицата. Tenant-ът преминава незабавно в `SUSPENDED_CHARGEBACK`. Възстановяване се допуска само с ръчно решение от упълномощен BEG_Work оператор, доказателства и AuditEvent.

## 19. Желязно правило за данните

> **Неплатен абонамент никога не изтрива данни.**

Изтриването е отделен процес:

```text
termination request
→ export
→ договорен retention период
→ legal/incident hold проверки
→ изрично потвърждение
→ контролирано deletion/disposition
→ AuditEvent / signed manifest
```

Канонично подробно решение за секции 15–19: [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).

## 20. Оставащи решения

1. Demo / Trial / Partner tenant режими.
2. Tenant configuration срещу private extension, no client forks, Test/Staging/Production, Tenant Acceptance Environment, export/retention/deletion и финален AuditEvent/Approval catalog.

## 21. Източници / сесии

- FLOW-016 — customer-managed Storage Provider и File Registry.
- FLOW-042 — exact tenant/environment Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесии 29.07–04.08.2026 — tenancy, packages, pricing, storage, Plan + AI, integrations, subscription lifecycle, Payment Provider Adapter, dunning, chargeback и no-deletion rule.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).
- [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](../architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md).
- [FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md](../architecture/FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md).
- [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](../architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md).

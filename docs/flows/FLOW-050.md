# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 55% — BUSINESS DESIGN IN PROGRESS  
> **Последна проверка:** 30.07.2026  
> **Оставащи решения:** 7  
> **Implementation Gate:** W0-BLOCKER за multi-tenant основата; billing и entitlements се проверяват отделно  
> **Свързани FLOW:** 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 016, 019, 020, 021, 023, 024, 027, 028, 030, 031, 033, 034, 035, 038, 039, 040, 041, 042, 043, 044, 045, 046, 047, 048, 049

## 1. Цел

FLOW-050 определя как BEG_Work се предоставя на отделни фирми като SaaS продукт: tenant модел, изолация, абонамент, модулни пакети, feature entitlements, плащане за системата, support access, среди, прекратяване и export.

## 2. Заключено решение: един tenant = една отделна фирма

Един tenant представлява точно една юридическа фирма.

Всеки tenant използва един и същ core продукт и логика FLOW-001–050, но има напълно отделни оперативни и финансови данни, Master Data, memberships, роли, обекти, документи, фактури, плащания, каси, банки, складове, файлове, номерации, интеграции, AI контекст, AuditEvent история, абонамент и настройки.

Потребителят не избира фирма във всяка форма. Tenant-ът се определя от активната проверена сесия.

## 3. Един акаунт, няколко tenant membership-а

Един User може да има достъп до няколко фирми, но всяка работна сесия има един активен `tenant_id`.

```text
User
→ TenantMembership
   → RoleAssignments от FLOW-002
      → role/action/module/project/location/resource/amount/validity scope
```

TenantMembership определя дали човекът принадлежи към фирмата. RoleAssignment определя какво може да прави в нея. Няма втори конкурентен permission модел.

## 4. Заключено решение: изолация на данните

Всеки tenant има отделна MongoDB база, файлово пространство, номерации, integrations/credentials, backup/restore/export scope и AI retrieval scope.

Централен `Tenant Registry` пази техническата карта на tenant-а: `tenant_id`, юридическа фирма, database location, storage location, status, subscription, deployment и `schema_version`.

Всички API, background jobs, exports, search, files и AI tools минават през централен Tenant Guard. `tenant_id` не се приема като свободно доверено поле от клиентската форма.

Между tenant-и няма shared operational records. Свързаните фирми взаимодействат като нормални контрагенти. Group Dashboard е само read-only управленска проекция.

Database-per-tenant изисква централен idempotent migration runner с per-tenant validation, AuditEvent и recovery/rollback plan.

Support достъпът е временен, scoped, одобрен и auditable. Isolation tests са задължителни в FLOW-042.

## 5. CORE enforcement важи за всички пакети

Пакетите управляват търговските модули и работните екрани, но не могат да изключват системните инварианти.

CORE за всички пакети са:

- Tenant Guard и tenant isolation;
- Permission Service и MFA за чувствителни роли;
- единен Payment ledger;
- idempotency и защита от duplicate write/payment;
- AuditEvent;
- DQ blocking rules;
- задължителните Approval проверки;
- exact-version approval;
- no hard delete на използвани записи;
- File Registry и versioning;
- AI не извършва критично действие без права и потвърждение.

Пълните Approval Center, Data Quality Center и Audit Center могат да са отделими Pro/Enterprise екрани, но enforcement логиката работи навсякъде.

## 6. Заключен принцип: пакетите са по цели модули

Модулът е отделим само ако едновременно:

1. финансовият резултат остава пълен без него;
2. никое заключено правило не изисква съществуването му;
3. данните текат към ядрото, а не от модула към задължителната финансова истина.

Не се допуска търговски пакет да съдържа половин модул.

### Неотделимо ядро

Следните модули са преплетени в основата и присъстват във всички платени пакети:

- Обекти и подобекти — FLOW-001;
- роли, права и достъп — FLOW-002;
- базови клиенти и контрагенти — FLOW-010;
- фактури, аванси, плащания, каси и банки — FLOW-006;
- приходи, разходи, вземания и задължения;
- пълен P&L и печалба по обект — FLOW-008;
- присъствие → дневни отчети → труд като стойност — FLOW-013/014/019;
- базов payroll и изплащане — FLOW-028;
- режийни и резултат преди/след режийни — FLOW-024;
- получени фактури с редове към обект;
- файлове и документи — FLOW-016;
- базови справки, аларми и мобилен достъп;
- CORE DQ, Approval и AuditEvent enforcement.

Финансовата истина е пълна във всички пакети. Няма ограничен Payment интерфейс, втори ledger, P&L без труд или резултат без режийни.

### Отделими модули

Следните модули могат да бъдат добавяни като цели надстройки:

- оферти/КСС/версии, договори, допълнителни СМР, актуване и прогрес — FLOW-003/004/005/007/027;
- склад/FIFO и логистика — FLOW-009/012;
- материални заявки и доставки — FLOW-020;
- подизпълнителски пакети — FLOW-021;
- активи/QR — FLOW-011;
- качество/дефекти/гаранции — FLOW-039;
- Work Packages и Resource Assignment — FLOW-035/048;
- AI и автоматизации — FLOW-023/030/031/038/041/045;
- Client Portal — FLOW-046;
- Managed Work Package и бонус — FLOW-047;
- пълните DQ/Approval/Audit работни центрове — FLOW-033/034/040.

## 7. Финална модулна карта на пакетите

### BEG Work Start — „Фирмата“

**Търговско изречение:** `Знаеш резултата.`

Start съдържа цялото неотделимо ядро:

- обекти и подобекти;
- хора, роли и права;
- присъствие и дневни отчети;
- пълни финанси;
- получени и издадени фактури;
- аванси, плащания, каси и банки;
- труд като стойност;
- базов payroll;
- режийни;
- пълен P&L и печалба по обект;
- файлове и базови клиенти/контрагенти;
- базови справки и аларми;
- мобилен достъп.

Малка фирма може да управлява дейността си от начало до край и да знае реално печели ли.

В Start материалният разход влиза чрез:

```text
Получена фактура
→ редове по материали/разходи
→ обект
→ P&L
```

### BEG Work Control — „Контролът“

**Търговско изречение:** `Контролираш резултата.`

Control включва всичко от Start плюс цели модули за произхода и предварителния контрол на числата:

- оферти, КСС и версии — FLOW-003;
- договори и анекси — FLOW-005;
- допълнителни СМР — FLOW-007;
- актуване — FLOW-004;
- график, прогрес и закъснение — FLOW-027;
- материални заявки и доставки — FLOW-020;
- склад и FIFO — FLOW-009;
- логистика — FLOW-012;
- подизпълнителски пакети — FLOW-021;
- инструменти, машини и QR — FLOW-011;
- качество, дефекти и гаранции — FLOW-039;
- Work Package Engine — FLOW-035;
- производителност и план/реално;
- разширени оперативни и финансови аларми.

Финансовата истина е същата като в Start. Control показва защо числата са такива и управлява процеса, преди разходът или приходът да стане факт.

Материалните заявки и доставки остават в Control:

```text
Заявка
→ одобрение
→ поръчка
→ доставка
→ склад или директен разход
→ получена фактура
→ плащане
```

### BEG Work Pro — „Автопилотът“

**Търговско изречение:** `Системата работи за теб.`

Pro включва всичко от Control плюс AI, автоматизация и пълни управленски центрове:

- BEG Brain — FLOW-030;
- AI agent роли — FLOW-031;
- AI Command Center — FLOW-045;
- автоматично офериране и ценови анализ — FLOW-023;
- Procurement Agent — FLOW-038;
- Scenario / What-if Engine — FLOW-041;
- Resource Assignment — FLOW-048;
- Managed Work Package и бонусен модел — FLOW-047;
- пълни Data Quality Center екрани — FLOW-033;
- пълни Approval Center екрани — FLOW-034;
- пълен Audit Center — FLOW-040;
- Client Portal — FLOW-046;
- разширен payroll и акордни анализи;
- автоматични прогнози, препоръки, risk analysis и управленски dashboards.

### BEG Work Enterprise

Enterprise не е отделна модулна стъпка. Той е:

> **Pro + договорени корпоративни услуги.**

Според договора може да включва SSO, специални интеграции, отделни среди, Tenant Acceptance Environment, SLA, специални backup/retention правила, корпоративни exports, tenant-specific extensions без private fork и приоритетна поддръжка.

Marketplace остава отделен продукт и отделна бизнес спецификация.

## 8. Feature Entitlements

Достъпът не се програмира чрез твърди проверки от вида `if plan == PRO`.

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

Entitlement може да бъде `included`, `addon` или `not_entitled`.

Plan Version е immutable. Съществуващ клиент не губи договорено право мълчаливо при промяна на публичния пакет. Tenant-specific entitlement се реализира чрез конфигурация/feature flag, а не чрез private code fork.

Runtime достъпът изисква едновременно:

```text
tenant има entitlement
AND
user има permission по FLOW-002
```

## 9. Full, Field и External User — само права, не цена

- **Full User** — управленски, административни, финансови, договорни, approval или глобални права;
- **Field User** — ограничен теренен потребител за присъствие, отчети, снимки, задачи, handover и възложени обекти;
- **External User** — клиент, инвеститор, проектант, подизпълнител, доставчик или консултант със scoped AccessGrant.

Classification се извежда от реалните RoleAssignments и permissions по FLOW-002, но не участва в ценообразуването.

## 10. Заключено решение: без таксуване на потребители и обекти

BEG_Work се продава с фиксирана цена на фирма/tenant.

Всички пакети включват неограничени Full Users, Field Users, External Users и неограничен брой обекти.

Ограничения и доплащане могат да се прилагат само към ресурси с реална променлива себестойност: файлово пространство, AI използване, специални API интеграции, отделни test/acceptance среди, SLA и tenant-specific разработки.

## 11. Заключено решение: Launch Pricing v1

Работната стартова ценова рамка е без ДДС:

| Пакет | Месечно | Годишно |
|---|---:|---:|
| **BEG Work Start** | **19,90 €** | **199 €** |
| **BEG Work Control** | **39,90 €** | **399 €** |
| **BEG Work Pro** | **79,90 €** | **799 €** |
| **BEG Work Enterprise** | от **149 €** | индивидуално |

Годишната цена е приблизително равна на 10 месечни такси.

Цените са `Launch Pricing v1`, не вечни цени. Нова ценова версия може да важи за нови клиенти или след договорено подновяване. Съществуващ клиент не се премества мълчаливо към нова цена.

## 12. Downgrade правило

При слизане към по-нисък пакет данните от изключените отделими модули не се изтриват. Съществуващите записи остават read-only и исторически видими; нови записи не могат да се създават; връзки, AuditEvent, файлове и финансови факти не се губят.

Неотделимото ядро, финансовата истина и историческият P&L никога не се изключват при downgrade.

## 13. Плащане за BEG_Work — работна рамка

BEG_Work ще поддържа месечни, годишни и договорни Enterprise абонаменти. Външен платежен оператор обработва картата и payment status, но FLOW-050 е source of truth за Subscription, Plan, Entitlement, Grace Period и access state.

Sandbox не е задължителен. Използва се само когато избраният оператор го предоставя и е необходим за безопасно интеграционно тестване.

## 14. Оставащи решения

1. Точни storage, AI, integration и environment лимити/add-on цени.
2. Месечно, годишно и Enterprise договорно плащане — operational lifecycle и промени по договора.
3. Избор на платежен оператор и фактуриране.
4. Grace Period, Restricted, Suspended и restoration правила.
5. Demo, Trial и Partner tenant режими.
6. Tenant configuration срещу private extension и забрана за client forks.
7. Test/Staging/Production, Tenant Acceptance Environment, прекратяване, export, retention, deletion и финален AuditEvent/Approval catalog.

## 15. Източници / сесии

- FLOW-042 — exact tenant/environment Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесия 29–30.07.2026 — tenant isolation, модулна преплетеност, Start/Control/Pro/Enterprise, пълно финансово ядро във всички пакети, Feature Entitlements, CORE enforcement, downgrade, фиксирана цена на фирма, неограничени потребители/обекти и Launch Pricing v1.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).

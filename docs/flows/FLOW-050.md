# FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements

> **Статус:** 35% — BUSINESS DESIGN IN PROGRESS  
> **Последна проверка:** 29.07.2026  
> **Оставащи решения:** 10  
> **Implementation Gate:** W0-BLOCKER за multi-tenant основата; billing и entitlements се проверяват отделно  
> **Свързани FLOW:** 002, 006, 008, 013, 014, 016, 019, 020, 021, 024, 028, 032, 033, 034, 040, 042, 043, 044, 045, 046, 049

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

Master Data по FLOW-032 е винаги per tenant, включително Master Person/Organization, СМР, материали, доставчици, клиенти, aliases, договорени и исторически цени, Skill Matrix, производителност и бизнес класификации.

Глобални са само технически справочници без бизнес и търговска стойност.

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

Когато две свързани фирми работят помежду си, те се третират като независими контрагенти чрез официалните FLOW-ове.

Не се допуска общ Project, обща фактура, общ Payment или общ Work Package, редактиран от два tenant-а.

Group Dashboard е допустим само като отделна read-only управленска проекция с изрично избрани tenant-и. От него не се създават официални записи.

## 9. Migration runner и schema version

Моделът database-per-tenant изисква централен migration runner, който обхожда Tenant Registry, сравнява `schema_version`, прилага idempotent migrations per tenant, валидира резултата, записва AuditEvent и поддържа recovery/rollback plan.

## 10. Support access

Системният оператор по подразбиране вижда само технически metadata и здравето на tenant-а.

Достъп до реални фирмени данни изисква `Support Access Request` с причина, ticket, обхват, режим, одобрение, срок, автоматично изтичане и AuditEvent.

Break-glass достъпът е двустепенен, временно ограничен и автоматично известява tenant owner.

## 11. Задължителни isolation tests

Преди production трябва да минават автоматични тестове, че User от Tenant A не вижда Tenant B; ID, файл, search, export и AI context не преминават между tenant-и; backup/restore и migration за един tenant не засягат останалите; RoleAssignment в една фирма не дава права в друга; shared operational records са забранени.

Тестовете влизат в Bootstrap QA Gate v0 / FLOW-042.

## 12. Плащане за BEG_Work — работна рамка

BEG_Work ще поддържа месечни, годишни и договорни абонаменти. Външен платежен оператор обработва картата и payment status, но FLOW-050 е source of truth за Subscription, Plan, Entitlement, Grace Period и access state.

Sandbox не е задължителен сам по себе си. Използва се само когато избраният оператор го предоставя и е необходим за безопасно интеграционно тестване.

## 13. Заключено решение: търговски пакети

BEG_Work има четири търговски пакета:

1. **BEG Work Start** — основна организация на обекти, хора и теренна работа;
2. **BEG Work Control** — Start плюс оферти, договори, материали, доставки, подизпълнители, качество и разходна страна;
3. **BEG Work Pro** — Control плюс приходна, парична, трудова и пълна управленска логика;
4. **BEG Work Enterprise** — Pro плюс договорни enterprise функции, интеграции, специална изолация, SLA и tenant-specific extensions без отделен fork.

Marketplace остава отделен продукт и отделна бизнес спецификация.

## 14. Заключено решение: Control срещу Pro

### Control включва

- получени фактури;
- заявка → доставка → получена фактура;
- материали;
- подизпълнители;
- други разходи по фактури;
- задължения към доставчици и подизпълнители;
- склад и логистика;
- оперативни трудови часове;
- качество, дефекти и гаранции;
- разходен резултат по обект в ограничения по-долу обхват.

### Разходният резултат в Control е ограничен

```text
материали
+ подизпълнители
+ други разходи по получени фактури
```

Той е **БЕЗ труд като стойност** и **БЕЗ режийни**.

Трудовите часове остават видими оперативно, но превръщането им в парична стойност чрез ставки, payroll данни и FLOW-019/028, както и разпределението на режийните по FLOW-024, изискват Pro.

Всеки Control екран и справка, които показват разходен резултат, задължително носят ясно означение:

> `Разходен резултат без стойност на труда и без режийни.`

Не се допуска стойността да бъде представяна като пълна себестойност или пълна печалба.

### Pro добавя

- актуване;
- издадени фактури;
- аванси;
- каси и банки;
- пълния Payment интерфейс;
- заплати и акорд;
- труд като стойност;
- режийни;
- Cash Flow;
- пълен P&L и печалба по обект;
- пълни Approval, Data Quality и Audit Center екрани;
- Scenario, Resource Assignment и AI управленски анализи.

## 15. CORE enforcement важи за всички пакети

Пакетите управляват достъпните работни екрани и търговски функции, но не могат да изключват системните инварианти.

Следните правила са CORE за Start, Control, Pro и Enterprise:

- Tenant Guard и tenant isolation;
- Permission Service;
- 2FA/MFA за Owner/Admin и чувствителни роли;
- единен Payment ledger;
- idempotency и защита от duplicate write/payment;
- AuditEvent;
- DQ blocking rules;
- задължителните Approval проверки и dual approval, когато правилото го изисква;
- акорд без одобрено количество не се допуска;
- exact-version approval;
- no hard delete на използвани записи;
- File Registry и versioning;
- AI не извършва критично действие без права и потвърждение.

Пълните Approval Center, Data Quality Center и Audit Center могат да са Pro/Enterprise екрани, но enforcement логиката работи във всички пакети.

## 16. Feature Entitlements

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

Plan Version е immutable. Съществуващ клиент не губи договорено право мълчаливо при промяна на публичния пакет.

Tenant-specific entitlement се реализира чрез конфигурация/feature flag, а не чрез private code fork.

## 17. Full, Field и External User

### Full User

Потребител с управленски, административни, финансови, договорни, approval или глобални права.

### Field User

Ограничен теренен потребител, например работник, бригадир, шофьор, оператор или складов служител, който работи с присъствие, дневни отчети, снимки, задачи, handover и възложени обекти, без глобални договорни, финансови и фирмени права.

### External User

Клиент, инвеститор, проектант, подизпълнител, доставчик или консултант със scoped AccessGrant.

Billing classification се извежда от реалните RoleAssignments и permissions по FLOW-002. Не може ръчно да се маркира Full User като по-евтин Field User.

Точните включени бройки и overage цени остават отворено решение.

## 18. Справки по пакети

### Start — основни справки

- активни обекти;
- задачи по статус и срок;
- присъствие;
- дневни отчети;
- снимки;
- свободни и заети хора;
- инструменти и машини по местонахождение;
- просрочени задачи;
- липсващи отчети;
- базов график;
- основни оперативни аларми.

### Control — разширени оперативни и разходни справки

- всичко от Start;
- оферирано и договорено;
- допълнителни СМР;
- заявени, доставени и нефактурирани материали;
- получени фактури;
- задължения към доставчици и подизпълнители;
- разходи по обект/СМР/пакет/контрагент;
- ограничен разходен резултат без труд като стойност и без режийни;
- складови наличности и движения;
- доставки и остатъци;
- подизпълнителски пакети;
- качество, дефекти и гаранции;
- производителност, срокове и закъснения;
- рискове за бюджет и изпълнение.

### Pro — пълни финансови и управленски справки

- всичко от Control;
- актувано;
- фактурирано към клиент;
- платено/неплатено;
- вземания и задължения;
- каси и банки;
- Cash Flow;
- труд като стойност;
- режийни;
- пълен P&L;
- печалба преди и след режийни;
- заплати и акорд;
- прогноза до приключване;
- Scenario, Resource Assignment, Approval, DQ, Audit и AI анализи.

## 19. Downgrade правило

При слизане към по-нисък пакет:

- данните от изключените модули не се изтриват;
- съществуващите записи остават read-only;
- участват в историческите справки според правата;
- не могат да се създават нови записи в изключените модули;
- не се губят връзки, AuditEvent, файлове или финансови факти;
- при повторно активиране на по-висок пакет работата продължава върху същите данни.

Downgrade никога не води до hard delete или скриване на историческата истина.

## 20. Оставащи решения

1. Точни включени Full/Field/External user лимити и overages.
2. Ограничен платежен интерфейс за Control: кои payment действия са достъпни, без да се създава втори ledger.
3. Начални цени и правила за годишна отстъпка.
4. Месечно, годишно и Enterprise договорно плащане.
5. Избор на платежен оператор и фактуриране.
6. Grace Period, Restricted, Suspended и restoration правила.
7. Demo, Trial и Partner tenant режими.
8. Tenant configuration срещу private extension и забрана за client forks.
9. Test/Staging/Production и Tenant Acceptance Environment.
10. Прекратяване, export, retention, deletion и финален AuditEvent/Approval catalog.

## 21. Източници / сесии

- FLOW-042 — exact tenant/environment Release Manifest и Tenant Acceptance Portal.
- FLOW-043 — D-15 Tenancy & Isolation Model.
- Сесия 29.07.2026 — tenant isolation, пакети Start/Control/Pro/Enterprise, Feature Entitlements, CORE enforcement, Full/Field/External classification, reporting boundaries, Control cost limitation и downgrade rule.
- [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).

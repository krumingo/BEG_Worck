# FLOW-050 — Partial Business Close / 29–30.07.2026

> **Статус:** APPROVED PARTIAL BUSINESS CLOSE  
> **Обхват:** Tenant identity + isolation + modular packages + entitlements + Launch Pricing v1  
> **Решения:** D-15 + whole-module package boundary + fixed tenant pricing

## Заключено — tenancy

- един tenant = една юридическа фирма;
- всеки tenant използва един и същ core FLOW-001–050;
- отделни database, files, Master Data, numbering, integrations, AI context, AuditEvent и subscription;
- active tenant идва от проверената сесия;
- User може да има memberships в няколко tenant-а, но една сесия работи в един активен tenant;
- `User → TenantMembership → RoleAssignments` е единният access модел;
- Tenant Guard е централен и denied-by-default;
- няма shared operational records между фирми;
- Group Dashboard е read-only;
- migration runner изпълнява idempotent migrations per tenant;
- support достъпът е временен, scoped и auditable;
- isolation tests са задължителни в Bootstrap QA Gate v0.

## Заключено — принцип за пакетите

Пакетите се изграждат по цели модули. Модул е отделим само ако:

1. финансовият резултат остава пълен без него;
2. никое заключено правило не изисква съществуването му;
3. данните му се вливат към ядрото, а не захранват задължителната финансова истина.

Не се допуска половин модул.

## Заключено — неотделимо ядро във всички пакети

В Start, Control, Pro и Enterprise присъстват:

- Обекти — FLOW-001;
- роли/права — FLOW-002;
- базови клиенти/контрагенти — FLOW-010;
- фактури, аванси, плащания, каси и банки — FLOW-006;
- пълен P&L по обект — FLOW-008;
- присъствие → отчети → труд като стойност — FLOW-013/014/019;
- базов payroll и изплащане — FLOW-028;
- режийни — FLOW-024;
- получени фактури с редове към обект;
- файлове — FLOW-016;
- базови справки, аларми и мобилен достъп;
- CORE DQ/Approval/AuditEvent enforcement.

Няма ограничен Payment интерфейс, втори ledger, P&L без труд или резултат без режийни.

## Заключено — финална модулна карта

### Start / „Фирмата“ — „Знаеш резултата“

Съдържа цялото неотделимо ядро. Малка фирма управлява дейността си от начало до край и вижда реалния финансов резултат.

Материалният разход влиза директно чрез получена фактура с редове към обект.

### Control / „Контролът“ — „Контролираш резултата“

Всичко от Start плюс цели модули за произхода на числата:

- оферти/КСС/версии;
- договори и анекси;
- допълнителни СМР;
- актуване;
- прогрес и график;
- материални заявки и доставки;
- склад/FIFO и логистика;
- подизпълнителски пакети;
- активи/QR;
- качество/дефекти/гаранции;
- Work Packages;
- производителност, план/реално и разширени аларми.

Материалните заявки и доставки остават в Control. Финансовата истина е същата като в Start.

### Pro / „Автопилотът“ — „Системата работи за теб“

Всичко от Control плюс:

- BEG Brain и AI agent роли;
- AI Command Center;
- автоматично офериране;
- Procurement Agent;
- Scenario Engine;
- Resource Assignment;
- Managed Work Package и бонус;
- пълни DQ/Approval/Audit екрани;
- Client Portal;
- разширен payroll, прогнози, risk analysis и управленски dashboards.

### Enterprise

Enterprise е `Pro + договорени корпоративни услуги`: SSO, интеграции, отделни среди, Tenant Acceptance Environment, SLA, специални backup/retention/export правила, extensions без private fork и приоритетна поддръжка.

Marketplace остава отделен продукт.

## Заключено — entitlements, downgrade и цена

- Feature Catalog → immutable Plan Version → Plan/Tenant Entitlement → Usage Limit/Feature Flag;
- няма твърди `if plan == ...` проверки;
- runtime изисква и tenant entitlement, и user permission по FLOW-002;
- при downgrade отделимите модули остават read-only и исторически видими; нищо не се изтрива;
- неотделимото ядро и историческият P&L никога не се изключват;
- фиксирана цена на фирма/tenant;
- без такса на потребител;
- неограничени Full, Field и External Users;
- неограничен брой обекти;
- add-ons само за storage, AI, API integrations, отделни среди, SLA и tenant-specific extensions.

### Launch Pricing v1 — без ДДС

| Пакет | Месечно | Годишно |
|---|---:|---:|
| Start | 19,90 € | 199 € |
| Control | 39,90 € | 399 € |
| Pro | 79,90 € | 799 € |
| Enterprise | от 149 € | индивидуално |

## Остава отворено

1. Storage, AI, integration и environment лимити/add-on цени.
2. Месечно, годишно и Enterprise договорно плащане — operational lifecycle.
3. Payment provider и фактуриране.
4. Grace/Restricted/Suspended/restoration.
5. Demo/Trial/Partner tenant.
6. Tenant configuration/extensions и no-fork operational rules.
7. Test/Staging/Production, Tenant Acceptance Environment, export/retention/deletion и финален billing/support AuditEvent/Approval catalog.

## Техническо отражение

D-15 е Wave 0 blocker. Package enforcement не може да заобикаля FLOW-002, FLOW-006, FLOW-008, FLOW-024, FLOW-028, FLOW-033/034 и FLOW-040. Whole-module boundaries, pricing, downgrade и entitlement tests влизат във FLOW-042.

## Източници

- [FLOW-050](../flows/FLOW-050.md)
- [FLOW-043 / D-15](../flows/FLOW-043.md)
- [TENANCY_MODEL.md](TENANCY_MODEL.md)
- [WAVE_0_TENANCY_FOUNDATIONS.md](WAVE_0_TENANCY_FOUNDATIONS.md)

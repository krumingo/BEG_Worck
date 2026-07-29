# FLOW-050 — Partial Business Close / 29.07.2026

> **Статус:** APPROVED PARTIAL BUSINESS CLOSE  
> **Обхват:** Tenant identity + isolation + packages + entitlements  
> **Решения:** D-15 + package boundary

## Заключено — tenancy

- един tenant = една юридическа фирма;
- всеки tenant използва един и същ core FLOW-001–050;
- отделни database, files, Master Data, numbering, integrations, AI context, AuditEvent и subscription;
- active tenant идва от проверената сесия;
- User може да има memberships в няколко tenant-а, но една сесия работи в един активен tenant;
- `User → TenantMembership → RoleAssignments` е единният access модел;
- Tenant Guard е централен и denied-by-default;
- няма shared operational records между фирми;
- свързани фирми взаимодействат като нормални контрагенти;
- Group Dashboard е read-only и не създава официални записи;
- Tenant Registry пази database/storage/deployment и `schema_version`;
- migration runner изпълнява idempotent migrations per tenant;
- support достъпът е временен, scoped и auditable;
- isolation tests са задължителни в Bootstrap QA Gate v0.

## Заключено — пакети и entitlements

- търговски пакети: Start, Control, Pro и Enterprise;
- Marketplace остава отделен продукт;
- получени фактури и разходната страна са в Control;
- актуване, издадени фактури, каси/банки, заплати, труд като стойност, режийни и пълен P&L са в Pro;
- разходният резултат в Control е само материали + подизпълнители + други разходи по фактури;
- Control показва изрично, че резултатът е без труд като стойност и без режийни;
- трудовите часове остават видими оперативно в Control;
- CORE enforcement важи във всички пакети, независимо от видимите управленски екрани;
- entitlement моделът е Feature Catalog → Plan Version → Plan/Tenant Entitlement → Usage Limit/Feature Flag;
- няма твърди `if plan == ...` проверки и няма client forks;
- Full/Field/External classification се извежда от FLOW-002 permissions, не от ръчно billing означение;
- основните и разширените справки са изрично разделени;
- при downgrade изключените модули остават read-only и исторически видими; нищо не се изтрива.

## Остава отворено

1. Точни включени Full/Field/External user лимити и overages.
2. Ограничен платежен интерфейс за Control, винаги върху FLOW-006 ledger.
3. Цени и годишна отстъпка.
4. Месечно, годишно и Enterprise договорно плащане.
5. Payment provider и фактуриране.
6. Grace/Restricted/Suspended/restoration.
7. Demo/Trial/Partner tenant.
8. Tenant configuration/extensions и no-fork operational rules.
9. Test/Staging/Production и Tenant Acceptance Environment.
10. Export/retention/deletion и финален billing/support AuditEvent/Approval catalog.

## Техническо отражение

D-15 е Wave 0 blocker. Package enforcement не може да заобикаля FLOW-002, FLOW-006, FLOW-033/034 и FLOW-040. Downgrade и entitlement tests влизат във FLOW-042.

## Източници

- [FLOW-050](../flows/FLOW-050.md)
- [FLOW-043 / D-15](../flows/FLOW-043.md)
- [TENANCY_MODEL.md](TENANCY_MODEL.md)
- [WAVE_0_TENANCY_FOUNDATIONS.md](WAVE_0_TENANCY_FOUNDATIONS.md)

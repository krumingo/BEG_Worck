# FLOW-050 — Tenancy Decision / 29.07.2026

> **Статус:** APPROVED PARTIAL BUSINESS CLOSE  
> **Обхват:** Tenant identity + isolation model  
> **Решение:** D-15

## Заключено

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

## Не е заключено още

- търговски пакети;
- entitlements и лимити;
- цени;
- subscription lifecycle;
- payment provider;
- grace/suspension;
- trial/demo;
- tenant extensions;
- environments;
- export/retention/deletion;
- final billing/support AuditEvent catalog.

## Техническо отражение

D-15 е Wave 0 blocker. Преди feature implementation са нужни Tenant Registry, Tenant Guard, per-tenant database resolver, TenantMembership integration, migration runner, isolation tests и per-tenant restore/export proof.

## Източници

- [FLOW-050](../flows/FLOW-050.md)
- [FLOW-043 / D-15](../flows/FLOW-043.md)
- [TENANCY_MODEL.md](TENANCY_MODEL.md)
- [WAVE_0_TENANCY_FOUNDATIONS.md](WAVE_0_TENANCY_FOUNDATIONS.md)

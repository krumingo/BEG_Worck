# BEG_Work — Architecture and Implementation Index

> **Обхват:** FLOW-001–050, cross-FLOW логика, tenancy и текущият `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.  
> **PR статус:** Draft; не се слива преди изрично решение на Крум.

## Основни документи

1. [TENANCY_MODEL — D-15](TENANCY_MODEL.md)  
   Един tenant = една юридическа фирма; database-per-tenant, Tenant Guard, per-tenant Master Data, memberships/roles, migration runner и support access.

2. [FLOW-050 Tenancy Decision — 29.07.2026](FLOW_050_TENANCY_DECISION_2026-07-29.md)  
   Частично business-close решение за tenant identity и isolation model.

3. [FLOW-050 Storage Model Change — 03.08.2026](FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md)  
   Задължителен customer-managed Storage Provider при onboarding; BEG_Work пази File Registry, checksums, previews/cache и базата данни, но не хоства клиентските оригинали.

4. [Wave 0 Tenancy Foundations](WAVE_0_TENANCY_FOUNDATIONS.md)  
   Задължителен backlog за Tenant Registry, Guard, membership, DB/storage/integrations, migrations, isolation QA и per-tenant restore/export.

5. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)

6. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)

7. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

8. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)

9. [Implementation Waves](IMPLEMENTATION_WAVES.md)

10. [FLOW Documentation Index](../flows/README.md)

11. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)

12. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)

## Текущ бизнес статус

- Общо FLOW-ове: **50**
- 100% Business Lock: **48**
- Активни незавършени: **1** — FLOW-050
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **7**

FLOW-049 е затворен като отделен Marketplace продукт с API/data boundary към BEG_Work.

FLOW-050 е в последен business-close pass. Заключени са:

- един tenant = една юридическа фирма;
- един core FLOW-001–050, но отделни фирмени данни и абонамент;
- active tenant от сесията;
- отделна MongoDB база per tenant;
- задължителен собствен Primary Storage Provider на tenant-а;
- tenant не се активира без успешен provider read/write/checksum onboarding test;
- BEG_Work не хоства клиентски оригинали и не продава storage GB;
- BEG_Work пази File Registry, metadata, relations, versions, checksums, previews/cache и базата данни;
- периодични availability/checksum проверки с Alarm, Data Quality issue, AuditEvent и засегнати business records;
- Tenant Registry и Tenant Guard;
- Master Data per tenant;
- `User → TenantMembership → RoleAssignments`;
- между tenant-и няма shared operational records;
- migration runner + `schema_version`;
- Support Access Request;
- автоматични isolation tests;
- цели пакети Start/Control/Pro/Enterprise, без такса на потребител;
- Launch Pricing v1.

## Главен технически извод

Документацията е по-зряла от runtime foundations. Преди масово feature development са нужни:

- Tenant Registry, Tenant Guard и database resolver;
- TenantMembership/RoleAssignment и ExternalPrincipal/AccessGrant;
- per-tenant Master Data, File Registry, numbering и integrations;
- mandatory Storage Provider onboarding gate и provider adapters;
- encrypted tenant-specific storage credentials;
- availability/checksum scheduler и affected-record resolver;
- migration runner и schema-version control;
- canonical append-only AuditEvent, retention, integrity и visibility;
- един payment write service;
- Data Quality и Approval runtime;
- Bootstrap QA/Test/Release framework;
- per-tenant database/File Registry restore proof и ясно разграничение от customer-managed originals.

## Wave 0 — задължителна основа

1. **D-15 / FLOW-050 — Tenancy Foundations**: Tenant Registry, Guard, membership, database/master isolation, migrations, support access и isolation tests.
2. **D-11/F-02 / FLOW-016 — Customer-managed Storage**: provider adapters, activation gate, encrypted credentials, checksums, availability alarms и affected-record mapping.
3. FLOW-002 — Permission Service + External Access Grants.
4. FLOW-032 — Master Data foundation, винаги per tenant.
5. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
6. FLOW-006 — Payment Core.
7. FLOW-033/034 — Data Quality + Approval.
8. FLOW-042 — Bootstrap QA и Test/Release foundation.
9. FLOW-044 — Disaster Recovery за BEG_Work-managed data с per-tenant restore proof.

## Следващ business-close приоритет

FLOW-050 — остават:

1. AI fair-use, имейл, интеграционни и environment лимити/add-on цени;
2. месечно, годишно и Enterprise договорно плащане;
3. payment provider и фактуриране;
4. grace/restricted/suspended/restoration lifecycle;
5. demo/trial/partner tenants;
6. tenant configuration/extensions и no-fork operational rules;
7. environments, export/retention/deletion и финален billing/support AuditEvent/Approval catalog.

Storage GB, архивни срокове на customer originals и add-on `+50 GB` са окончателно извадени от текущия пакетен модел.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Документационните промени не променят runtime кода или production данните.
- FLOW-001–050 трябва да имат проследими източници.
- Master Flow Register, Decision Register, FLOW-043 и отделните FLOW файлове трябва да съвпадат преди merge.
- D-15 и D-11/F-02 са W0 blockers: feature implementation не получава PASS без tenant isolation, mandatory storage onboarding, integrity checks, migration runner и restore tests за BEG_Work-managed data.
- След merge документацията става обща основа за ChatGPT, Claude, Emergent и разработчиците.

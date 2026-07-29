# BEG_Work — Architecture and Implementation Index

> **Обхват:** FLOW-001–050, cross-FLOW логика, tenancy и текущият `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.  
> **PR статус:** Draft; не се слива преди изрично решение на Крум.

## Основни документи

1. [TENANCY_MODEL — D-15](TENANCY_MODEL.md)  
   Един tenant = една юридическа фирма; database-per-tenant, Tenant Guard, per-tenant Master Data, memberships/roles, migration runner и support access.

2. [FLOW-050 Tenancy Decision — 29.07.2026](FLOW_050_TENANCY_DECISION_2026-07-29.md)  
   Частично business-close решение за tenant identity и isolation model.

3. [Wave 0 Tenancy Foundations](WAVE_0_TENANCY_FOUNDATIONS.md)  
   Задължителен backlog за Tenant Registry, Guard, membership, DB/files/integrations, migrations, isolation QA и per-tenant restore/export.

4. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)

5. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)

6. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

7. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)

8. [Implementation Waves](IMPLEMENTATION_WAVES.md)

9. [FLOW Documentation Index](../flows/README.md)

10. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)

11. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)

## Текущ бизнес статус

- Общо FLOW-ове: **50**
- 100% Business Lock: **48**
- Активни незавършени: **1** — FLOW-050
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **12**

FLOW-049 е затворен като отделен Marketplace продукт с API/data boundary към BEG_Work.

FLOW-050 е формално създаден. Заключени са:

- един tenant = една юридическа фирма;
- един core FLOW-001–050, но отделни фирмени данни и абонамент;
- active tenant от сесията;
- отделна MongoDB база и файлово пространство per tenant;
- Tenant Registry и Tenant Guard;
- Master Data per tenant;
- `User → TenantMembership → RoleAssignments`;
- между tenant-и няма shared operational records;
- migration runner + `schema_version`;
- Support Access Request;
- автоматични isolation tests.

## Главен технически извод

Документацията е по-зряла от runtime foundations. Преди масово feature development са нужни:

- Tenant Registry, Tenant Guard и database resolver;
- TenantMembership/RoleAssignment и ExternalPrincipal/AccessGrant;
- per-tenant Master Data, File Registry, numbering и integrations;
- migration runner и schema-version control;
- canonical append-only AuditEvent, retention, integrity и visibility;
- един payment write service;
- Data Quality и Approval runtime;
- Bootstrap QA/Test/Release framework;
- per-tenant backup/restore/export доказателства.

## Wave 0 — задължителна основа

1. **D-15 / FLOW-050 — Tenancy Foundations**: Tenant Registry, Guard, membership, database/file/master isolation, migrations, support access и isolation tests.
2. FLOW-002 — Permission Service + External Access Grants.
3. FLOW-032 — Master Data foundation, винаги per tenant.
4. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
5. FLOW-006 — Payment Core.
6. FLOW-016 — File Registry.
7. FLOW-033/034 — Data Quality + Approval.
8. FLOW-042 — Bootstrap QA и Test/Release foundation.
9. FLOW-044 — Disaster Recovery с per-tenant restore proof.

## Следващ business-close приоритет

FLOW-050:

1. планове и Feature Entitlements;
2. user types/limits и цени;
3. subscription/payment/factoring rules;
4. grace/suspension/restoration;
5. demo/trial/partner tenants;
6. tenant extensions и no-fork rule;
7. environments;
8. export/retention/deletion;
9. final audit/approval catalog.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Документационните промени не променят runtime кода или production данните.
- FLOW-001–050 трябва да имат проследими източници.
- Master Flow Register, Decision Register, FLOW-043 и отделните FLOW файлове трябва да съвпадат преди merge.
- D-15 е W0 blocker: feature implementation не получава PASS без tenant isolation, migration runner и per-tenant restore tests.
- След merge документацията става обща основа за ChatGPT, Claude, Emergent и разработчиците.

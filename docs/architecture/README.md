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
   Customer-managed storage, mandatory onboarding provider, File Registry ownership и availability/checksum alarms.

4. [FLOW-050 Plan + AI Decision — 03.08.2026](FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md)  
   Твърди AI бюджети по план, клиентски usage екран, AI add-ons, Enterprise BYOK и core operations без зависимост от AI.

5. [FLOW-050 Subscription / Billing / Dunning Decision — 04.08.2026](FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md)  
   Upgrade/downgrade/cancellation, Payment Provider Adapter, dunning 0/3/7, Grace/Restricted/Suspended, chargeback и no-deletion rule.

6. [Wave 0 Tenancy Foundations](WAVE_0_TENANCY_FOUNDATIONS.md)

7. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)

8. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)

9. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

10. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)

11. [Implementation Waves](IMPLEMENTATION_WAVES.md)

12. [FLOW Documentation Index](../flows/README.md)

13. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)

14. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)

## Текущ бизнес статус

- Общо FLOW-ове: **50**
- 100% Business Lock: **48**
- Активни незавършени: **1** — FLOW-050
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **2**

FLOW-049 е затворен като отделен Marketplace продукт с API/data boundary към BEG_Work.

FLOW-050 е на 90%. Заключени са:

- tenancy/isolation и database-per-tenant;
- пакетите Start/Control/Pro/Enterprise;
- Launch Pricing v1;
- customer-managed storage;
- План + AI и AI add-ons;
- имейл/интеграционни лимити;
- subscription lifecycle;
- Payment Provider Adapter;
- dunning ден 0/3/7;
- Grace/Restricted/Suspended и restoration;
- отделен chargeback suspended path;
- неплащане никога не изтрива данни.

## Главен технически извод

Документацията е по-зряла от runtime foundations. Преди масово feature development са нужни:

- Tenant Registry, Tenant Guard и database resolver;
- TenantMembership/RoleAssignment и ExternalPrincipal/AccessGrant;
- per-tenant Master Data, File Registry, numbering и integrations;
- migration runner и schema-version control;
- AI Usage Ledger и plan/add-on budget enforcement;
- Subscription/Billing state machine и Payment Provider Adapter;
- dunning scheduler, notification routing и chargeback case handling;
- canonical append-only AuditEvent, retention, integrity и visibility;
- един payment write service;
- Data Quality и Approval runtime;
- Bootstrap QA/Test/Release framework;
- per-tenant backup/restore/export доказателства.

## Wave 0 — задължителна основа

1. **D-15 / FLOW-050 — Tenancy Foundations**: Tenant Registry, Guard, membership, database/master isolation, migrations, support access и isolation tests.
2. **FLOW-050 Billing Foundations**: Subscription, Plan Version, Entitlement, AI Usage Ledger, Payment Provider Adapter, dunning, access states, chargeback и no-deletion tests.
3. FLOW-002 — Permission Service + External Access Grants.
4. FLOW-032 — Master Data foundation, винаги per tenant.
5. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
6. FLOW-006 — Payment Core.
7. FLOW-016 — File Registry и customer-managed Storage Provider adapters.
8. FLOW-033/034 — Data Quality + Approval.
9. FLOW-042 — Bootstrap QA и Test/Release foundation.
10. FLOW-044 — Disaster Recovery с per-tenant restore proof.

## Следващ business-close приоритет

FLOW-050:

1. Demo / Trial / Partner tenant режими.
2. Tenant extensions/no-fork, environments, export/retention/deletion и финален AuditEvent/Approval catalog.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Документационните промени не променят runtime кода или production данните.
- FLOW-001–050 трябва да имат проследими източници.
- Master Flow Register, Decision Register, FLOW-043 и отделните FLOW файлове трябва да съвпадат преди merge.
- D-15 и FLOW-050 billing foundations са W0 blockers.
- Feature implementation не получава PASS без tenant isolation, migration runner, billing idempotency, dunning/chargeback tests и per-tenant restore/export proof.

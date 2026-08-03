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
   Customer-managed originals, mandatory onboarding provider, File Registry ownership и availability/checksum alarms.

4. [FLOW-050 Plan + AI Decision — 03.08.2026](FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md)  
   Месечни AI действия по план, AI add-ons, клиентски usage екран, 80/100% правила, core independence и Enterprise BYOK.

5. [Wave 0 Tenancy Foundations](WAVE_0_TENANCY_FOUNDATIONS.md)

6. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)

7. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)

8. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

9. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)

10. [Implementation Waves](IMPLEMENTATION_WAVES.md)

11. [FLOW Documentation Index](../flows/README.md)

12. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)

13. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)

## Текущ бизнес статус

- Общо FLOW-ове: **50**
- 100% Business Lock: **48**
- Активни незавършени: **1** — FLOW-050
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **5**

FLOW-049 е затворен като отделен Marketplace продукт с API/data boundary към BEG_Work.

FLOW-050 е на 75%. Заключени са:

- tenant identity/isolation и database-per-tenant;
- модулната карта Start/Control/Pro/Enterprise;
- Launch Pricing v1, entitlements и downgrade;
- customer-managed storage и mandatory provider onboarding;
- План + AI: 100/500/2 000 действия по план;
- AI add-ons 500/2 000/5 000;
- клиентски AI usage екран, 80/100% правила и core independence;
- Enterprise BYOK;
- имейл/standard integration лимити 2/10/30 и add-on +5.

## Главен технически извод

Преди масово feature development са нужни:

- Tenant Registry, Tenant Guard и database resolver;
- TenantMembership/RoleAssignment и ExternalPrincipal/AccessGrant;
- per-tenant Master Data, File Registry, numbering и integrations;
- mandatory customer Storage Provider onboarding и integrity scheduler;
- migration runner и schema-version control;
- canonical append-only AuditEvent;
- един payment write service;
- Data Quality и Approval runtime;
- AI Usage Ledger, immutable Plan Version budgets, add-on entitlements и provider-cost reconciliation;
- Bootstrap QA/Test/Release framework;
- per-tenant backup/restore/export доказателства.

## Wave 0 — задължителна основа

1. D-15 / FLOW-050 — Tenancy Foundations.
2. FLOW-002 — Permission Service + External Access Grants.
3. FLOW-032 — Master Data foundation per tenant.
4. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
5. FLOW-006 — Payment Core.
6. FLOW-016 — File Registry + mandatory customer Storage Provider + checksum/availability scheduler.
7. FLOW-050 — AI Usage Ledger, action catalog, usage budgets/add-ons, 80/100% controls и Enterprise BYOK.
8. FLOW-033/034 — Data Quality + Approval.
9. FLOW-042 — Bootstrap QA и Test/Release foundation.
10. FLOW-044 — Disaster Recovery с per-tenant restore proof.

## Следващ business-close приоритет

FLOW-050:

1. subscription operational lifecycle;
2. payment provider и фактуриране;
3. grace/restricted/suspended/restoration;
4. demo/trial/partner tenants;
5. tenant extensions/no-fork, environments, export/retention/deletion и финален AuditEvent/Approval catalog.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Документационните промени не променят runtime кода или production данните.
- FLOW-001–050 трябва да имат проследими източници.
- Master Flow Register, Decision Register, FLOW-043 и отделните FLOW файлове трябва да съвпадат преди merge.
- D-15, customer-managed storage и AI Usage Ledger са W0 blockers.
- След merge документацията става обща основа за ChatGPT, Claude, Emergent и разработчиците.

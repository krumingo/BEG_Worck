# BEG_Work — Architecture and Implementation Index

> **Обхват:** FLOW-001–050, cross-FLOW логика, tenancy и текущият `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.  
> **PR статус:** Draft; не се слива преди изрично решение на Крум.

## Основни документи

1. [TENANCY_MODEL — D-15](TENANCY_MODEL.md)  
   Един tenant = една юридическа фирма; database-per-tenant, Tenant Guard, per-tenant Master Data, memberships/roles, migration runner и support access.

2. [FLOW-050 Tenancy Decision — 29.07.2026](FLOW_050_TENANCY_DECISION_2026-07-29.md)

3. [FLOW-050 Storage Model Change — 03.08.2026](FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md)

4. [FLOW-050 Plan + AI Decision — 03.08.2026](FLOW_050_AI_FAIR_USE_DECISION_2026-08-03.md)

5. [FLOW-050 Subscription / Billing / Dunning Decision — 04.08.2026](FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md)

6. [FLOW-050 Trial / Demo / Partner Decision — 04.08.2026](FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md)

7. [Modern Field Experience — 04.08.2026](MODERN_FIELD_EXPERIENCE_2026-08-04.md)

8. [FLOW-050 Final Governance / Environments / Retention Decision — 04.08.2026](FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md)

9. [Wave 0 Tenancy Foundations](WAVE_0_TENANCY_FOUNDATIONS.md)

10. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)

11. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)

12. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

13. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)

14. [Implementation Waves](IMPLEMENTATION_WAVES.md)

15. [FLOW Documentation Index](../flows/README.md)

16. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)

17. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)

## Текущ бизнес статус

- Общо FLOW-ове: **50**
- 100% Business Lock: **49**
- Активни незавършени: **0**
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **0**

FLOW-001–050 са бизнес затворени. FLOW-018 не се развива самостоятелно и е погълнат от FLOW-039.

FLOW-050 заключва:

- tenancy/isolation и database-per-tenant;
- пакетите Start/Control/Pro/Enterprise;
- Launch Pricing v1;
- customer-managed storage;
- План + AI и AI add-ons;
- имейл/интеграционни лимити;
- subscription lifecycle;
- Payment Provider Adapter;
- dunning, Grace/Restricted/Suspended и chargeback;
- Trial/Demo/Partner;
- Modern Field Experience;
- един общ код и no-private-fork governance;
- Development/Test/Staging/Production и TAE;
- 90-дневен read-only retention;
- export, legal/incident hold и controlled deletion;
- финален Approval/AuditEvent каталог.

## Главен технически извод

Документацията е бизнес завършена, но runtime foundations още не са. Преди масово feature development са нужни:

- Tenant Registry, Tenant Guard и database resolver;
- TenantMembership/RoleAssignment и ExternalPrincipal/AccessGrant;
- per-tenant Master Data, File Registry, numbering и integrations;
- migration runner и schema-version control;
- AI Usage Ledger и plan/add-on budget enforcement;
- Subscription/Billing state machine и Payment Provider Adapter;
- dunning scheduler, notification routing и chargeback handling;
- environment/Release Manifest governance и no-fork enforcement;
- canonical append-only AuditEvent, retention, integrity и visibility;
- един payment write service;
- Data Quality и Approval runtime;
- Bootstrap QA/Test/Release framework;
- per-tenant backup/restore/export/retention/deletion доказателства.

## Wave 0 — задължителна основа

1. D-15 / FLOW-050 — Tenant Registry, Guard, membership, database/master isolation, migrations, support access и isolation tests.
2. FLOW-050 Billing Foundations — Subscription, Plan Version, Entitlement, AI Usage Ledger, Payment Provider Adapter, dunning, access states и chargeback.
3. FLOW-050 Release/Data Lifecycle — common code, Release Manifest, environments, TAE, export, retention, holds и controlled deletion.
4. FLOW-002 — Permission Service + External Access Grants.
5. FLOW-032 — Master Data foundation, винаги per tenant.
6. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
7. FLOW-006 — Payment Core.
8. FLOW-016 — File Registry и customer-managed Storage Provider adapters.
9. FLOW-033/034 — Data Quality + Approval.
10. FLOW-042 — Bootstrap QA и Test/Release foundation.
11. FLOW-044 — Disaster Recovery с per-tenant restore proof.

## Следваща стъпка

```text
финална проверка на Draft PR #2
→ CLAUDE.md v15 и таблото
→ изрично решение за merge
→ Wave 0 coding
```

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Документационните промени не променят runtime кода или production данните.
- FLOW-001–050, Master Flow Register, Decision Register, FLOW-043, Gate Matrix и Waves трябва да съвпадат преди merge.
- D-15 и FLOW-050 foundations са W0 blockers.
- Feature implementation не получава PASS без tenant isolation, migration runner, billing idempotency, environment governance, audit/approval, export/retention/deletion tests и per-tenant restore proof.

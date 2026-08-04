# BEG_Work — Implementation Gate Matrix

> **Дата:** 04.08.2026  
> **Правило:** `100% Business Lock` не означава `Implementation Gate PASS`.  
> **Последен business-close pass:** FLOW-050 е 90%; tenancy, pricing, storage, Plan + AI, integrations, subscription lifecycle, Payment Provider Adapter, dunning, chargeback и no-deletion rule са заключени.

## Легенда

- **W0-BLOCKER** — cross-cutting foundation; започва първо.
- **REFACTOR** — има работещ код, но е в конфликт с каноничния FLOW.
- **READY-W1/W2/W3/W4** — може да се разработва след predecessor-ите.
- **BUSINESS-OPEN** — остават бизнес решения.
- **LEGACY** — не се развива самостоятелно.
- **DOC/OPS** — документационен или инфраструктурен gate.

## Критични актуални gates

| FLOW | Business | Implementation Gate | Критичен predecessor / действие |
|---|---:|---|---|
| 002 | 100% | **W0-BLOCKER** | RoleAssignment + ExternalPrincipal/AccessGrant + Permission Service + migration |
| 006 | 100% | **W0/W1 REFACTOR** | one payment write service, obligations, idempotency, legacy retirement |
| 016 | 100% | **W0-BLOCKER** | provider-neutral File Registry, customer-managed Storage Provider onboarding, checksums/availability alarms |
| 032 | 100% | **W0-BLOCKER** | Master entities, aliases, merge, migration and uniqueness per tenant |
| 033/034 | 100% | **W0/W1 FOUNDATION** | DQ issue model + Approval runtime |
| 040 | 100% | **W0-BLOCKER / FOUNDATION** | canonical immutable AuditEvent, retention and visibility |
| 042 | 100% | **W0 FOUNDATION** | Bootstrap QA Gate, acceptance/migration/isolation/billing tests |
| 044 | 100% | **OPS-W0** | per-tenant DB restore and BEG_Work-managed data recovery |
| 050 | 90% | **W0-BLOCKER / BUSINESS-OPEN** | Tenant Registry/Guard, DB resolver, Subscription/Billing state machine, Plan Version/Entitlements, AI Usage Ledger, Payment Provider Adapter, dunning 0/3/7, access states, chargeback case, no-deletion tests; остава Demo/Trial/Partner и final extensions/environments/export catalog |

## FLOW-050 задължителни implementation условия

- database-per-tenant и Tenant Guard;
- TenantMembership → RoleAssignment;
- immutable Plan Version и entitlement checks;
- customer-managed Storage Provider activation gate;
- AI Usage Ledger, budget allocation и add-on proration;
- клиентски AI usage екран и 80%/100% rules;
- email/integration usage limits без прекъсване на съществуващите връзки;
- Subscription/Billing Period state machine;
- idempotent upgrade/downgrade/cancellation;
- Payment Provider Adapter и подписани webhooks;
- provider event deduplication;
- invoice/credit-note linkage;
- dunning scheduler за ден 0/3/7;
- Owner + finance-admin notification routing;
- GRACE / RESTRICTED / SUSPENDED permission matrix;
- отделен `SUSPENDED_CHARGEBACK` state;
- manual restore Approval + AuditEvent за chargeback;
- тест, че billing state никога не задейства deletion;
- отделен termination/export/retention/confirmation process.

## Release правило

Нито един FLOW получава `Implementation Gate PASS`, докато няма едновременно:

1. canonical permission enforcement;
2. source-of-truth и migration map;
3. API/tool contract;
4. positive + forbidden + correction/reversal tests;
5. AuditEvent coverage;
6. idempotency за retryable writes;
7. Data Quality / Approval връзки;
8. проверен UI за Крум;
9. rollback/restore план;
10. tenant isolation tests;
11. billing and entitlement reconciliation tests, когато FLOW използва subscription state.

## Следващ business-close приоритет

1. Demo / Trial / Partner tenant режими.
2. Tenant extensions/no-fork, environments, export/retention/deletion и финален AuditEvent/Approval catalog.

# BEG_Work — Implementation Gate Matrix

> **Дата:** 04.08.2026  
> **Правило:** `100% Business Lock` не означава `Implementation Gate PASS`.  
> **Последен business-close pass:** FLOW-001–050 са бизнес затворени; FLOW-018 е legacy и е погълнат от FLOW-039.

## Легенда

- **W0-BLOCKER** — cross-cutting foundation; започва първо.
- **REFACTOR** — има работещ код, но е в конфликт с каноничния FLOW.
- **READY-W1/W2/W3/W4** — може да се разработва след predecessor-ите.
- **LEGACY** — не се развива самостоятелно.
- **DOC/OPS** — документационен или инфраструктурен gate.

## Критични актуални gates

| FLOW | Business | Implementation Gate | Критичен predecessor / действие |
|---|---:|---|---|
| 002 | 100% | **W0-BLOCKER** | RoleAssignment + ExternalPrincipal/AccessGrant + Permission Service + migration |
| 006 | 100% | **W0/W1 REFACTOR** | един Payment write service, obligations, idempotency, legacy retirement |
| 016 | 100% | **W0-BLOCKER** | provider-neutral File Registry, mandatory customer Storage Provider onboarding, checksum/availability alarms |
| 032 | 100% | **W0-BLOCKER** | Master entities, aliases, merge, migration и uniqueness per tenant |
| 033/034 | 100% | **W0/W1 FOUNDATION** | Data Quality issue model + Approval runtime |
| 040 | 100% | **W0-BLOCKER / FOUNDATION** | canonical immutable AuditEvent, retention, integrity и visibility |
| 042 | 100% | **W0 FOUNDATION** | Bootstrap QA Gate, acceptance/migration/isolation/billing/environment tests |
| 044 | 100% | **OPS-W0** | per-tenant DB restore и BEG_Work-managed data recovery |
| 050 | 100% | **W0-BLOCKER** | Tenant Registry/Guard, DB resolver, Plan/Entitlements, AI Usage Ledger, Subscription/Billing, Payment Provider Adapter, dunning, environments, retention и controlled deletion |

## FLOW-050 задължителни implementation условия

- database-per-tenant и Tenant Guard;
- TenantMembership → RoleAssignment;
- immutable Plan Version и entitlement checks;
- customer-managed Storage Provider activation gate;
- File Registry, checksum/availability scheduler и affected-record alarms;
- AI Usage Ledger, budget allocation, add-on proration и client usage view;
- email/integration usage limits без прекъсване на съществуващите връзки;
- Subscription/Billing Period state machine;
- idempotent upgrade/downgrade/cancellation;
- Payment Provider Adapter, signed webhooks и provider-event deduplication;
- invoice/credit-note linkage;
- dunning scheduler за ден 0/3/7;
- Owner + finance-admin notification routing;
- GRACE / RESTRICTED / SUSPENDED и `SUSPENDED_CHARGEBACK` permission matrix;
- Trial/Demo/Partner state and access rules;
- common-code/no-private-fork enforcement;
- Development/Test/Staging/Production Release Manifest;
- exact-version Tenant Acceptance Environment;
- termination → export → 90-day read-only retention → hold check → Approval → controlled deletion → signed manifest;
- final Approval/AuditEvent catalog;
- Modern Field Experience Wave 2 acceptance tests.

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
11. billing and entitlement reconciliation tests;
12. environment/Release Manifest evidence;
13. export/retention/hold/deletion tests;
14. customer-managed storage integrity tests;
15. no-private-fork compliance.

## Бизнес статус

Няма оставащи бизнес решения. Следващата стъпка е финална PR проверка, CLAUDE.md v15, табло, изрично merge решение и старт на Wave 0.

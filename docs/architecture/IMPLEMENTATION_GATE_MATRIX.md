# BEG_Work — Implementation Gate Matrix

> **Дата:** 04.08.2026; implementation статус синхронизиран на 20.09.2026  
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

## Implementation статус на W0 gates — 20.09.2026

Класификацията по-горе не се сменя: gate-ът остава отворен, докато W0 item-ът не е доказан изцяло.

| FLOW | W0 item | Статус | Какво още държи gate-а отворен |
|---|---|---|---|
| 050 (tenancy / D-15) | W0-01 | CORE MERGED | Tenant Guard на всички входни точки, migration runner, support access, isolation suite |
| 002 | W0-02 | CORE DEPLOYED (`0b53bcd5`, mode off) | 229 от 232 legacy role проверки не са мигрирани; ExternalPrincipal/AccessGrant; shadow/enforce решение |
| 032 | W0-03 | NOT STARTED — следващ голям build след W0-09A/W0-10A | целият обхват |
| 040 | W0-04 | CORE MERGED | покритие на всички critical writes; retention/hold/archive/audit-of-audit (W0-04B) |
| 006 | W0-05 | NOT STARTED | целият обхват |
| 016 | W0-06 | NOT STARTED | целият обхват |
| 033/034 | W0-07 | NOT STARTED | целият обхват |
| 050 (billing) | W0-08 | NOT STARTED | целият обхват |
| 042 / 050 (release) | W0-09 | PARTIAL — W0-09A MERGED, NOT DEPLOYED | W0-09A е в `main` (`fdf4d59e`, PR #14, 14.09.2026), но не е adopt-нат в production (`DEPLOYED_COMMIT` = `0b53bcd5`); environments/TAE/QA exit gate (W0-09B) |
| 044 | W0-10 | PARTIAL — W0-10A READY TO RUN | инструментът за изолиран restore proof е в `ops/dr/` (тестван, температурно защитен), но **прогонът не е изпълнен** — restore остава недоказан; отделно стои отвореният хардуерен риск `docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md`; пълен DR (W0-10B) |
| 050 (retention) | W0-11 | NOT STARTED | целият обхват |

Wave 2.1 (FLOW-027 график/готовност) не е W0 gate; runtime кодът ѝ изисква W0-03, W0-06, W0-07 и read-only достъп до W0-05 — виж [Implementation Waves](IMPLEMENTATION_WAVES.md).

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

Няма оставащи бизнес решения. Wave 0 coding е започнал; следващата implementation стъпка е **W0-09A**, после W0-10A и W0-03 (пълният ред е в [Implementation Waves](IMPLEMENTATION_WAVES.md)).

# Wave 0 — Tenancy Foundations / D-15

> **Статус:** REQUIRED W0 FOUNDATION  
> **Дата:** 04.08.2026  
> **Източник:** FLOW-050 + D-15 + `TENANCY_MODEL.md`

Този backlog е задължителен predecessor за продаваем multi-tenant BEG_Work.

## Съответствие с каноничната W0 номерация (13.09.2026)

`W0-T01…T12` е под-backlog на tenancy изискванията, не отделни W0 items. Каноничните номера са в [Implementation Waves](IMPLEMENTATION_WAVES.md).

| Под-backlog | Каноничен W0 item | Статус |
|---|---|---|
| W0-T01 Tenant Registry, W0-T02 Tenant Guard, W0-T04 DB/Master isolation (DB част), W0-T06 sequences/integrations, W0-T07 migration runner | W0-01 | CORE MERGED — registry/guard/resolver; guard не е на всички входни точки; migration runner и sequences не са направени |
| W0-T03 TenantMembership + FLOW-002 | W0-02 | CORE DEPLOYED — ExternalPrincipal/AccessGrant не са направени |
| W0-T04 Master Data per tenant | W0-03 | NOT STARTED |
| W0-T05 customer-managed storage + File Registry | W0-06 | NOT STARTED |
| W0-T08 Support / Partner Access | W0-01 / W0-02 | NOT STARTED |
| W0-T09 Billing and entitlements | W0-08 | NOT STARTED |
| W0-T10 Environments and no-fork, W0-T11 Tenant-aware QA | W0-09 (A/B) | PARTIAL |
| W0-T12 Backup/Restore/Export/Retention/Deletion | W0-10 (A/B) и W0-11 | backup PARTIAL; restore/export/retention/deletion NOT STARTED |

## W0-T01 — Tenant Registry

- canonical tenant identity;
- one tenant = one legal company;
- database/storage-provider/deployment resolver;
- subscription/plan references;
- app/schema/configuration version;
- Release Manifest;
- lifecycle: provisioning, trial, active, grace, restricted, suspended, chargeback-suspended, terminated-read-only, deletion-pending.

## W0-T02 — Tenant Guard

- active tenant from verified session;
- denied-by-default cross-tenant access;
- resource ownership checks;
- enforcement for API, jobs, File Registry, search, exports, AI tools, notifications, webhooks and support sessions;
- no trusted free-form `tenant_id` from UI.

## W0-T03 — TenantMembership + FLOW-002

- `User → TenantMembership → RoleAssignments`;
- independent roles/scopes per tenant;
- active/invited/suspended membership states;
- tenant switch with full context reset;
- migration from legacy `users.role`;
- ExternalPrincipal/AccessGrant for clients, partners and support.

## W0-T04 — Database and Master Data isolation

- separate MongoDB database per tenant;
- Master Data per tenant;
- global technical catalogs only;
- per-tenant uniqueness, indexes and IDs;
- no shared operational records.

## W0-T05 — Customer-managed storage and File Registry

- tenant-scoped File Registry;
- mandatory Primary Storage Provider during onboarding;
- Google Drive / Synology / S3 / on-prem adapters;
- encrypted tenant credentials;
- read/write/checksum round-trip activation test;
- periodic availability/checksum scheduler;
- affected-record resolver for missing/changed originals;
- Alarm/DQ issue + AuditEvent;
- provider-neutral `file_id` and short-lived protected links;
- customer originals remain outside BEG_Work storage quota.

## W0-T06 — Sequence and integration isolation

- tenant-scoped numbering service;
- separate API keys, webhook secrets and integrations;
- tenant-aware email/notification channels;
- no cross-tenant provider credentials or signed links.

## W0-T07 — Migration runner

- iterate Tenant Registry;
- per-tenant migration lock;
- `schema_version` transitions;
- dry-run/canary/staged rollout;
- idempotent retry;
- post-migration validation;
- per-tenant AuditEvent and failure report;
- recovery/rollback plan.

## W0-T08 — Support / Partner Access

- metadata-only platform administration by default;
- Support/Partner Access Request;
- read-only/restricted-write modes;
- scope, expiry and revoke;
- two-person break-glass;
- tenant-owner notification;
- audit-of-support.

## W0-T09 — Billing and entitlement foundation

- Feature Catalog and immutable Plan Version;
- Tenant Entitlement and Usage Limit;
- AI Usage Ledger and add-on proration;
- Subscription/Billing state machine;
- Payment Provider Adapter and signed/idempotent webhooks;
- dunning 0/3/7;
- GRACE/RESTRICTED/SUSPENDED/SUSPENDED_CHARGEBACK;
- Trial/Demo/Partner states;
- no-deletion invariant.

## W0-T10 — Environments and no-fork governance

- one common codebase;
- Development/Test/Staging/Production;
- common Release Manifest;
- exact app/schema/configuration version per deployment;
- Tenant Acceptance Environment;
- no private client forks;
- exception requires owner decision and new FLOW-043 D-decision.

## W0-T11 — Tenant-aware QA

Bootstrap QA Gate v0 must include:

- Tenant A cannot read/write Tenant B;
- guessed IDs and modified URLs fail;
- search/export/File Registry/AI isolation;
- provider credentials and signed-link isolation;
- membership/role isolation;
- no shared Project/Invoice/Payment/WorkPackage;
- migration/backup/restore of one tenant does not affect others;
- support access expires and is auditable;
- billing/webhook/migration retries are idempotent;
- storage activation/checksum alarms work;
- no-private-fork and Release Manifest tests pass.

## W0-T12 — Backup / Restore / Export / Retention / Deletion proof

- per-tenant backup manifest;
- isolated restore drill;
- export of one tenant only;
- 90-day read-only retention after termination;
- legal/incident hold;
- explicit deletion Approval;
- deletion verification and signed disposition manifest;
- customer-managed originals are not deleted by the standard BEG_Work process;
- move tenant to another deployment without changing business identity.

## Exit criteria

Wave 0 tenancy foundation is not PASS until:

1. every request resolves one active tenant server-side;
2. all business data and Master Data are per tenant;
3. RoleAssignments are membership-scoped;
4. tenant isolation tests pass for API, File Registry, search, export, AI and integrations;
5. customer Storage Provider onboarding and integrity checks pass;
6. migration runner reports every active tenant at the release schema version;
7. billing/entitlement state is reconciled and idempotent;
8. backup/restore/export/retention/deletion is proven per tenant;
9. support staff cannot access business data without a recorded temporary grant;
10. no shared operational record or private client fork exists.

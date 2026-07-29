# Wave 0 — Tenancy Foundations / D-15

> **Статус:** REQUIRED W0 FOUNDATION  
> **Дата:** 29.07.2026  
> **Източник:** FLOW-050 + D-15 + `TENANCY_MODEL.md`

Този backlog е задължителен predecessor за продаваем multi-tenant BEG_Work.

## W0-T01 — Tenant Registry

- canonical tenant identity;
- one tenant = one legal company;
- database/storage/deployment resolver;
- subscription/plan references;
- `schema_version` и migration status;
- lifecycle: provisioning, active, restricted, suspended, archived, deletion-pending.

## W0-T02 — Tenant Guard

- active tenant from verified session;
- denied-by-default cross-tenant access;
- resource ownership checks;
- enforcement за API, jobs, files, search, exports, AI tools и webhooks;
- no trusted free-form `tenant_id` from UI forms.

## W0-T03 — TenantMembership + FLOW-002

- `User → TenantMembership → RoleAssignments`;
- independent roles/scopes per tenant;
- active/invited/suspended membership states;
- tenant switch with full context reset;
- compatibility/migration from current `users.role`.

## W0-T04 — Database and Master Data isolation

- separate MongoDB database per tenant;
- Master Data FLOW-032 is per tenant;
- global technical catalogs only;
- per-tenant uniqueness, indexes and IDs;
- no shared operational records.

## W0-T05 — File, sequence and integration isolation

- tenant-scoped File Registry storage;
- tenant-scoped numbering service;
- separate API keys, webhook secrets and integrations;
- tenant-aware notifications and email channels;
- signed/file links cannot cross tenant boundary.

## W0-T06 — Migration runner

- iterate Tenant Registry;
- per-tenant migration lock;
- `schema_version` transitions;
- dry-run/canary/staged rollout;
- idempotent retry;
- post-migration validation;
- per-tenant AuditEvent and failure report;
- recovery/rollback plan.

## W0-T07 — Support Access

- metadata-only platform administration by default;
- Support Access Request;
- read-only/restricted-write modes;
- expiry and revoke;
- two-person break-glass;
- tenant-owner notification;
- audit-of-support.

## W0-T08 — Tenant-aware QA

Bootstrap QA Gate v0 must include:

- Tenant A cannot read/write Tenant B;
- guessed IDs and modified URLs fail;
- search/export/file/AI isolation;
- membership/role isolation;
- no shared Project/Invoice/Payment/WorkPackage;
- migration/backup/restore for one tenant does not affect others;
- support access expires and is auditable;
- retryable migrations and provisioning are idempotent.

## W0-T09 — Per-tenant backup/restore/export proof

- separate backup manifest;
- isolated restore drill;
- export of one tenant only;
- retention/legal hold/deletion workflow;
- move tenant to another deployment without changing business identity.

## Exit criteria

Wave 0 tenancy foundation is not PASS until:

1. every request resolves one active tenant server-side;
2. all business data and Master Data are per tenant;
3. RoleAssignments are membership-scoped;
4. tenant isolation tests pass for API, files, search, export and AI;
5. migration runner reports every active tenant at the release schema version;
6. backup/restore/export is proven per tenant;
7. support staff cannot access business data without a recorded temporary grant;
8. no shared operational record exists between companies.

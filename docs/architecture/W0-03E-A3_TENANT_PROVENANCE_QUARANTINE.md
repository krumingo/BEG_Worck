# W0-03E-A3 — Tenant Provenance Quarantine Architecture

> Status: ARCHITECTURAL DECISION / IMPLEMENTATION PENDING  
> Date: 2026-10-01  
> Scope: unresolved tenant provenance for legacy operational/authorization records  
> Predecessor: W0-03E-A2 BLOCKED on exact head `43ba7e35e9b14899cc3054f1f9c65f30996162ae`

## 1. Problem

BEG_WORK requires every tenant-owned business, operational and authorization record to have explicit tenant ownership.

Legacy records such as `project_team` can exist without a trustworthy tenant owner. Such rows must not be allowed to authorize, create financial effects, or become trusted business relations.

The existing tenant-scoped DQ / pending-mapping model cannot persist these cases because it requires an already-known tenant. Assigning a guessed or placeholder tenant would violate the tenancy model.

## 2. Decision

Create a **platform control-plane quarantine registry** for unresolved tenant provenance.

This registry is **not tenant business data** and does not participate in operational reads, authorization, finance, reports, exports or Master Data.

It exists only to hold technical evidence that a legacy source record has unresolved ownership until an authorized resolution can be made.

Canonical name:

`TenantProvenanceCase`

Canonical collection/service may be implementation-defined, but it must live in the platform/control-plane domain, not inside a tenant business database.

## 3. Tenant ownership invariant

The business invariant remains unchanged:

**Every tenant-owned operational/business/authorization record must have explicit tenant ownership.**

A legacy row whose tenant cannot be proven does **not** become a canonical operational record.

Instead:

`legacy ownerless source row -> TenantProvenanceCase -> explicit resolution -> tenant-bound migration/backfill`

Until resolution, the source row remains fail-closed.

## 4. TenantProvenanceCase minimum model

Required fields:

- `case_id`
- `status`: `OPEN | RESOLVED | REJECTED`
- `source_system`
- `source_database_ref` or trusted source fingerprint
- `source_collection`
- `source_record_id`
- `source_record_hash`
- `relation_type` / entity type
- `reason_code`
- `discovered_at`
- `discovered_by`
- `candidate_tenant_ids` (optional, evidence only; never authorization)
- `resolved_tenant_id` (null until resolved)
- `resolution_method`
- `resolution_evidence`
- `resolved_by`
- `resolved_at`
- `correlation_id`
- immutable audit/history

Do not store unnecessary raw business payload in the control-plane record. Prefer source pointer + hash + minimal technical evidence. Sensitive source data stays in its original protected source.

## 5. Resolution rules

A case may become `RESOLVED` only by:

1. deterministic trusted infrastructure evidence, such as a source database uniquely mapped to one tenant in Tenant Registry; or
2. explicit authorized human resolution through a controlled admin/migration workflow.

Forbidden:

- matching `project_id`
- matching `user_id`
- matching names
- matching roles
- fuzzy matching
- insertion order
- "most likely" tenant inference
- caller-supplied tenant override

## 6. Fail-closed behavior

While a case is `OPEN` or `REJECTED`, its legacy source row:

- grants no authorization;
- creates no RoleAssignment / PermissionAssignment;
- cannot drive a financial write;
- cannot become an official business relation;
- is excluded from trusted reports/exports;
- cannot be used by Master Data merge/mapping as authoritative identity evidence.

## 7. project_team

`project_team` is a tenant-bound authorization relation.

New rows require server-derived tenant ownership.

Legacy ownerless rows:
- proven source tenant -> safe migration/backfill;
- unproven source tenant -> TenantProvenanceCase + DENY authorization.

The authorization lookup remains:

`tenant_id + project_id + user_id [+ role]`

## 8. W0-02 bootstrap hardening

`w0_02_bootstrap_permissions.py` and any equivalent permission backfill must never derive authorization from ownerless or unresolved `project_team` rows.

Backfill rules:
- only tenant-proven membership may create project-scoped permissions;
- unresolved membership creates/links a provenance case and is excluded from permission generation;
- verification must apply the same tenant-provenance rule;
- no dict keyed only by bare user ID may establish tenant ownership.

## 9. Lifecycle

Expected lifecycle:

```
legacy scan
-> provenance classification
-> PROVEN_TENANT: tenant-bound migration
-> UNRESOLVED: create/update TenantProvenanceCase
-> human/trusted resolution
-> explicit Approval where required
-> tenant-bound backfill/migration
-> audit result
```

The quarantine registry itself is platform metadata and must have access control, audit and retention.

## 10. Tests

Required:
- ownerless B membership cannot authorize A;
- unresolved case persists durably without fake tenant ownership;
- open case cannot produce permission assignments;
- resolved case for A produces only A membership;
- forged resolution tenant is denied;
- same project/user IDs in A/B do not affect resolution;
- permission bootstrap ignores unresolved rows;
- repeated scans are idempotent and do not create duplicate cases;
- source-record hash change creates a detectable conflict/review condition;
- control-plane case is never returned through tenant operational APIs.

## 11. Hard boundaries

No production migration, merge, deploy, Atlas/NAS write, live tenant reassignment or automatic human-equivalent resolution is authorized by this architecture decision.

## 12. Acceptance

PASS requires:
- durable unresolved provenance representation;
- no fake tenant assignment;
- project_team runtime remains fail-closed;
- W0-02 bootstrap hardened;
- idempotent case creation/resolution;
- independent collision and real-Mongo proof.


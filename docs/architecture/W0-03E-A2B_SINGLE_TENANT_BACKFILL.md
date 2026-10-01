# W0-03E-A2B — Single-tenant legacy ownership backfill decision

> Date: 2026-10-01
> Status: APPROVED ARCHITECTURAL / MIGRATION DECISION
> Owner decision: Krum Radulov
> Predecessor: W0-03E-A2 BLOCKED on exact head `43ba7e35e9b14899cc3054f1f9c65f30996162ae`

## 1. Current reality

At the current BEG_WORK stage there is only one operating tenant/company in the system: **BUILDING EXPRESS GROUP / BEG**.

Therefore the legacy operational data being migrated today is not genuinely multi-tenant historical data. Existing ownerless legacy business/authorization records belong to the one current BEG tenant.

## 2. Decision

For the current legacy migration:

- every ownerless legacy tenant-owned record is assigned to the **single current BEG tenant**;
- the implementation must resolve the canonical tenant ID from trusted server-side tenant/organization registry state;
- do **not** hard-code an invented tenant UUID, name string, request field, or arbitrary org_id;
- migration must first prove there is exactly one eligible active operational tenant for this legacy source;
- if that precondition is not true, migration fails closed and requires a new migration decision.

This applies to legacy operational records including authorization relations such as `project_team`.

## 3. New invariant

After backfill, every tenant-owned business/operational/authorization/relation record must carry explicit tenant ownership.

No new ownerless operational rows are permitted.

All future writers must stamp tenant ownership from the server-resolved active tenant.

## 4. Future second company

When a second company/tenant is created:

1. it is created through the normal tenant onboarding procedure;
2. its records are created with its own server-resolved tenant_id from the start;
3. no record may be created without tenant ownership;
4. no existing BEG legacy record is reinterpreted as belonging to the new tenant;
5. cross-tenant reads/writes remain denied by default.

The single-tenant legacy backfill rule is a one-time migration rule for the current historical dataset, not a general inference rule for future imports.

## 5. Migration safety conditions

Before writing:

- verify the trusted source is the current BEG legacy dataset;
- verify exactly one eligible active operational tenant exists for this migration context;
- resolve its canonical tenant_id server-side;
- produce a dry-run inventory by collection and count;
- show how many ownerless rows will be backfilled;
- show any records with conflicting existing tenant ownership separately;
- refuse conflicting ownership; do not overwrite a different existing tenant_id.

Execution must be idempotent and auditable.

## 6. project_team

For current legacy `project_team` rows:

- ownerless rows are backfilled to the single current BEG tenant during migration;
- new rows always carry server-derived tenant ownership;
- authorization lookup requires tenant_id + project_id + user_id [+ role];
- no bare project_id/user_id authorization is allowed.

After backfill, the prior unresolved-provenance blocker is removed for the current dataset.

## 7. W0-02 permission bootstrap

Permission/bootstrap code must use only tenant-bound `project_team` rows.

After the BEG backfill:
- project membership derives from the resolved BEG tenant;
- bootstrap must filter by tenant;
- ownerless rows are rejected if any remain;
- no permissions are created from bare user/project IDs.

## 8. Quarantine model

A platform provenance quarantine is **not required for the current BEG-only legacy migration** because the business owner has confirmed all current legacy operational records belong to BEG.

A quarantine/DQ provenance mechanism may still be needed in the future for external imports or genuinely ambiguous multi-tenant legacy sources, but it does not block the current W0-03E migration.

## 9. Acceptance

PASS requires:
- every current ownerless tenant-owned legacy record is either safely backfilled to the single current BEG tenant or explicitly rejected for conflicting ownership;
- zero ownerless authorization rows remain in the protected migration scope;
- all new writers stamp tenant ownership server-side;
- all authorization and protected joins remain tenant-scoped;
- W0-02 bootstrap is tenant-scoped;
- static guards pass;
- independent A/B isolation tests and real-Mongo gate pass.

## 10. Boundaries

No production migration, merge, deploy, Atlas/NAS production write, second-tenant creation, or tenant reassignment is authorized by this decision.

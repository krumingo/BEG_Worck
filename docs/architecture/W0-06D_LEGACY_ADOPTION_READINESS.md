# W0-06D — Legacy file/media adoption readiness (FLOW-016)

> Task-ID `W0-06D`, Cycle `C01`. Technical base: independently accepted W0-06C head `e3cfb4a1be95b10d8b2331d99c63c8daf7eb2bd6`, still unmerged in Draft PR #49. W0-06B Draft PR #46 is also unmerged. This document is an implementation contract for a **dry-run readiness layer**, not authorization to migrate, move, delete, overwrite or activate anything in production.

## На човешки

BEG_Work ще може да открие старите файлове и медийни връзки, да покаже на кого принадлежат, къде са сега и какво пречи да бъдат приети в единния File Registry. Ще изготви проверим план, но няма да премества, изтрива, презаписва или променя клиентски оригинали.

## Canon and predecessor

`FLOW-016` is the business source for `file_id`, customer-managed originals, relations, versions, provider identity, checksums and migration that preserves identity. `FLOW-002` governs every scan/plan read or projection. `FLOW-040` governs one append-only AuditEvent trail. `TENANCY_MODEL` requires server-resolved tenant, per-tenant isolation and eventual migration runner with lock/version/idempotent retry. The existing W0-06A inventory and `app/files/migration_map.py` are the **only declared legacy-source map and deterministic ID derivation**; do not create a competing source registry. W0-06B provides real provider binding/integrity semantics; W0-06C provides monitoring, not migration. W0-07 DQ/Approval runtime is out of scope. Review evidence and exact heads remain on the canonical `codex/claude-queue` branch.

The W0-06A generated inventory presently declares 16 sources / 35 file-bearing sites; those counts are **not frozen**. Regenerate/reconcile them against the final head. A newly found source must be classified before PASS, never silently skipped. Pointer-only rows must resolve to the owning content row; they do not mint a second File.

## Deliverable and trust boundary

Build a tenant-bound, provider-neutral **read-only scanner and deterministic planner** over the declared legacy DB sources and safe physical inventory. It may read bytes to calculate a checksum only through an explicitly permitted, tenant-scoped read surface and a bounded budget; no path supplied by a DB row may escape an allowlisted legacy root, follow a symlink/reparse point to another root, or confer ownership by filename alone. No live tenant, NAS, Drive, S3 or Atlas access is required for implementation/tests. Use disposable fixtures and loopback MongoDB only.

The scanner must reconcile both directions: DB row without original, physical object without attributable row, and pointer without a resolvable owning File. Distinguish a missing object from inaccessible storage/provider, unknown checksum and unverified ownership. Same path/name/checksum in two tenants never creates cross-tenant identity, duplicate or relation. Ambiguous ownership or business relation is blocked pending human decision, not assigned by a heuristic. Existing File Registry links are resolved within the same tenant and compared for checksum/version/location drift.

For each item retain a sanitized source identity/reference, tenant-resolution and business-relation evidence, source kind/location, expected and observed size/checksum when safely available, proposed `file_id`/FileVersion/ProviderLocation/FileRelation mapping, deterministic readiness state, reasons/blockers, scan time, and a stable fingerprint/plan hash of the observed inputs. Do not persist raw credentials, signed URLs, document bytes, unrestricted filesystem paths or sensitive provider responses in logs, AuditEvents or client projections. The authorized operator may see a protected source reference; public or cross-tenant projections may not.

## Readiness states and proposed action

Use one deterministic, documented precedence when more than one condition applies. The vocabulary is technical planning status, **not** an approval to migrate:

- `READY_TO_ADOPT`: tenant and business ownership, original, checksum/size and customer-managed verified provider location are all proven with no conflict.
- `ALREADY_REGISTERED`: exact same-tenant File/FileVersion/location/relation is already present and verified.
- `DUPLICATE_CANDIDATE`: same-tenant content may match another File; never auto-merge.
- `ORPHAN_DB_RECORD`, `ORPHAN_PHYSICAL_FILE`, `MISSING_ORIGINAL`: distinguish unreferenced DB pointer, unattributed physical object and an expected original proven absent.
- `TENANT_AMBIGUOUS`, `BUSINESS_RELATION_AMBIGUOUS`, `CHECKSUM_CONFLICT`, `UNSUPPORTED_SOURCE`, `BLOCKED`: explicit fail-closed states with evidence and reason. Provider outage/permission denied must not be mislabeled missing.

An adoption plan may propose `ADOPT_IN_PLACE` only when the original is already at a verified tenant-owned customer-managed provider location; `REGISTER_REFERENCE_ONLY` only for an existing same-tenant File with proven relation; otherwise `NEEDS_HUMAN_DECISION` or a blocked future step. **The legacy BEG_Work app disk is not a customer-managed Primary Provider** (`app/files/migration_map.py` says so explicitly). A row on that disk cannot be declared an executable in-place adoption. Do not invent a provider binding or claim that a proposed destination key is a current location. Inline base64 similarly requires a future, separately authorized provider write. An orphan physical file does not become owned merely because its path resembles a tenant root.

The dry-run must be stable for the same inputs, sorted deterministically and safe to rerun. Before any later apply, the planner's fingerprint must be recomputed against the DB row, physical evidence, provider identity, relation target and current File Registry state; drift refuses the stale plan. **W0-06D supplies the refusal/validation contract or non-mutating validation hook, not an apply/commit endpoint.** No automatic duplicate merge, relation rewrite, source-field clear, byte transfer, provider activation or destructive repair.

Scan/plan/explicit decision attempts use the one FLOW-040 AuditEvent service with tenant, actor/service principal, correlation, evidence hash and outcome; denial and drift must be visible without secrets. If a human decision interface is not in this slice, expose a decision-required record/interface only; do not invent an approval role, SLA or acceptance rule. Production execution needs separate authorization and applicable W0-07/tenant migration-runner gates.

## Required proof before final HANDOFF

Tests must cover all declared source types and both inventory directions; two tenants with colliding IDs and filenames/paths; duplicate same/different checksum; missing, inaccessible and orphan cases; tenant/business ambiguity; deterministic repeat; stale-plan drift refusal; mapping to existing File/FileVersion/ProviderLocation/FileRelation without duplicate identity; no-move/no-delete/no-overwrite invariant; FLOW-002 allow/deny and projection redaction; FLOW-040 AuditEvent; a fresh disposable loopback real-Mongo persistence/isolation gate. Run the existing W0-06A/B/C focused and relevant adjacent/static guards, generated-inventory check, `git diff --check`; report exact collected/passed/failed/skipped. NOT RUN is not PASS. Prove cleanup of all disposable DBs, processes and paths.

Claude implements only this bounded contract on the existing W0-06D branch and Draft PR, publishes final exact-head HANDOFF with changed files/tests/limitations, attempts direct PC handoff if actually available, then stops. Codex independently reviews the W0-06C→D delta and whole stacked `main→head`, reruns critical tests including real Mongo and returns bounded same-Task-ID corrections until technical PASS or a genuine blocker.

**Standing authorization:** Крум предварително разрешава на CODEX и CLAUDE да използват наличните им PC/Computer Use способности за директно предаване на задачи, corrections, HANDOFF-и и финални резултати между агентите в рамките на текущия Task-ID. Не искай Крум за ново потвърждение за тези agent-to-agent handoff действия. Използвай PC/Computer Use директно и публикувай success/failure event в GitHub. Ако платформата наложи задължително action-time confirmation, не го заобикаляй и отчети точната причина.

No merge, deploy, production migration/scheduler, live provider credentials, NAS/Atlas write, customer-original modification/deletion, W0-07 runtime, W0-06E or unrelated dashboard/FLOW change. W0-06D technical PASS does **not** execute migration or close FLOW-016 Implementation Gate.

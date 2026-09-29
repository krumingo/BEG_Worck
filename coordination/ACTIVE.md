# BEG_WORK — active implementation assignment

Status: CODEX VERDICT READY / PUBLISH PENDING
Current-Agent: CODEX
Current-State: REVIEW
Claude-State: HANDOFF_READY
Codex-State: REVIEWING
Pipeline-Step: REVIEW
Transition-Phase: INTENT
Now: Codex has completed the independent W0-03E/C01 review; verdict publication is pending
Next-Agent: GPT
Relay-State: NO_RELAY_NEEDED
Relay-From: NONE
Relay-To: NONE
Krum-Action: NONE
Dispatch-State: RUNNING
Dispatch-Run: https://claude.ai/code/session_01H4RDLb5DobWSt3AT8C1BRF
Dispatch-Observed-At: 2026-09-28T20:15:54Z
Task-ID: W0-03E
Cycle-ID: C01
Base-branch: main
Base-SHA: bbdb94dafa09a483b35ccdf6ed13604b77b86a96
Implementation-branch: codex/w0-03e-legacy-migration
PR-URL: https://github.com/krumingo/BEG_Worck/pull/32 (Draft)
PR-Head: 67c172e3066a53d0d6fa5c594997e2b7af0d1747
Merge-SHA: NONE
Main-Head: bbdb94dafa09a483b35ccdf6ed13604b77b86a96
HANDOFF-URL: https://github.com/krumingo/BEG_Worck/pull/32 (exact-head HANDOFF in PR body; Claude session ended)
Review: READY / PUBLISH PENDING — independent review completed on exact head 67c172e3066a53d0d6fa5c594997e2b7af0d1747; no published verdict yet
HANDOFF-Observed-At: 2026-09-29T04:25:28Z
Predecessor-Task-ID: W0-03D/C02
Predecessor-Review: coordination/REVIEWS/W0-03D.md (code PASS and real-Mongo 4/4 PASS on exact head ad99598543be60d83c5dbaa29e06a2e8b2063a21)
Predecessor-Integration: PR #30 merged into main at bbdb94dafa09a483b35ccdf6ed13604b77b86a96
Authorization: Krum authorized the large W0-03E package and confirmed the one regular Claude Code Cloud Send on 2026-09-28. The exact queue assignment at efe042d5aa405076769d6ae6d46396ca9a2a8079 was sent once to the selected krumingo/BEG_Worck implementation branch; the session above showed Claude responding and running tools. No Routine, duplicate session, merge or deploy.
Correction-cycles: up to two bounded technical cycles only after independent exact-head CHANGES_REQUESTED, without new business rules or expanded scope; a third correctness failure is BLOCKED.

## Canonical W0-03E/C01 implementation assignment — HANDOFF published, Codex reviewing

Repository `krumingo/BEG_Worck`; base branch `main` at **exact** `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`; implementation branch `codex/w0-03e-legacy-migration` already exists at that SHA. Task-ID `W0-03E`, Cycle-ID `C01`. Recheck all three identities and confirm there is no other active W0-03E PR/session before editing. Work only on this branch; publish one Draft PR against `main`, then final exact-head HANDOFF and STOP for independent Codex review. An intermediate push is not completion.

Read, in order: `CLAUDE.md`; `docs/architecture/IMPLEMENTATION_WAVES.md` (W0-03 and execution order); `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` (FLOW-032 gate); `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` (especially §§2–6, W0-03E, §4.5); `docs/architecture/W0-03C_UNIQUENESS_READINESS.md`; `docs/architecture/TENANCY_MODEL.md`; `docs/flows/FLOW-032.md`, `FLOW-002.md`, `FLOW-040.md`, and applicable FLOW-033/034 and locked D decisions. Inspect current `backend/app/master_data/`, tenancy, permissions, audit, all inventoried legacy routes and tests. The contract's dated status summary is historical; live `main` and exact PR evidence supersede it.

Implement the **entire canonical W0-03E legacy migration foundation as one bounded package**, not separate unrelated tasks: inventory/report and deterministic plan; dry-run that provably performs zero writes; per-tenant, batchable, resumable, idempotent execution with lock/checkpoint/schema-version/evidence/retry, explicit validation and reconciliation/rollback strategy; fail-closed ambiguous matches and partial writes. Preserve every old ID through tenant-bound `legacy_refs`, a reverse reference and deterministic resolution; reconcile counts before/after so no legacy reference silently disappears. Canonical Master uses server-resolved `tenant_id`; legacy `org_id` is compatibility evidence only, never a caller override or future tenant key. No cross-tenant guessing, fuzzy auto-merge or hard delete.

Cover all inventoried identity sources: `users`/`persons`/`employee_profiles` → person; `companies`/`clients`/`counterparties`/`subcontractors` → one organization with roles; `work_types`/`smr_groups` → activity; `items` → item; `asset_item_types`/`asset_items`/`asset_units` → asset_type/physical_asset; `warehouses`/`location_nodes` → location; source/external IDs. Ambiguous identity, even an exact name match without authoritative identity, stays a candidate in pending mapping until authorized human confirmation. AI/OCR/Excel never creates official Master as a side effect. Legacy adapters for the affected read/write routes, import/export and reports must allow staged migration while retaining old IDs and tenant checks; do not rewrite the entire backend.

Audit **all seven** delete-by-ID identity paths identified in the contract (`auth.py`, `clients.py`, `counterparties.py`, `locations.py`, `projects.py` person/company, `smr_groups.py`) **plus** `warehouses.py` bulk `delete_many({"org_id": ...})` and relevant asset deletion. Scope the actual delete/archive operation by server-resolved tenant and Master ownership; used identity cannot be hard-deleted; preserve permitted legacy behavior only when demonstrably outside Master ownership. Add cross-tenant and used-record refusal regressions. New advances in enforce mode require official Master Person ID; old `guest_name` advances remain readable and unchanged; a read-only manual-mapping report on a restored copy may propose but never auto-map. Preserve one canonical organization across client/supplier/counterparty/subcontractor roles.

For every W0-03E migration/adapter write: W0-02 permission boundary default deny, server-side tenant guard, W0-04 canonical AuditEvent including denial and correlation/idempotency evidence. Do not migrate all 229 unrelated legacy permission checks. `MASTER_DATA_MODE=off` stays inert, `shadow` stays non-writing, and no production activation occurs. W0-07 Approval runtime remains absent; do not bypass its fail-closed boundary or claim full FLOW-032 gate PASS.

Acceptance tests: positive/forbidden/correction paths for all source collections, aliases, old-ID resolution, same legacy ID and same normalized name in two tenants, forged `org_id`/tenant, cross-tenant `legacy_ref` injection, mapping ambiguity and exact-name non-auto-match, tenant A/B reads and writes, merge redirect/unmerge/history, duplicates, archive/delete refusals, new advance without canonical person, old `guest_name` preservation, AI/OCR/Excel pending behavior, permissions and AuditEvent, idempotent retry/interruption/checkpoint, counts and zero lost references, no silent partial success. Run focused and adjacent W0-03 suites; record collected/passed/failed/skipped. Add real-Mongo tests for a disposable local loopback instance; Claude may run them only if safely available. Codex independently repeats the gate after HANDOFF; skipped is never PASS.

Excluded: new business policy, fuzzy matching thresholds, automatic merge, production data migration, live index build, Atlas/NAS/production writes, `MASTER_DATA_MODE` activation, W0-06 implementation, broad W0-02 cleanup, locked FLOW/D edits, deployment and merge. If the full canonical scope cannot be completed safely in one package, do not quietly shrink it or claim PASS: publish exact partial evidence and STOP with a concrete blocker. Krum remains owner of new business rules, security/access, live operations and merge/deploy decisions.

HANDOFF must give actual diff, exact new head, Draft PR URL, source-to-Master coverage, deletion-path coverage, migration/retry/rollback evidence, permission/audit evidence, focused/adjacent/real-Mongo results and honest residual limits. Then STOP. Codex alone reviews exact head, permits at most two bounded purely technical corrections, and performs independent disposable real-Mongo gate and whole-W0-03 closure review if evidence supports it.

## Archived predecessor context — W0-03D/C02, completed

## Integration result and remaining W0-03 scope
W0-03D is accepted in `main` at merge `bbdb94dafa09a483b35ccdf6ed13604b77b86a96`; the implementation head `ad99598543be60d83c5dbaa29e06a2e8b2063a21` is an ancestor. W0-03 as a whole and FLOW-032 implementation are **not complete**. W0-03E legacy migration, adapters, reference reconciliation and database-per-tenant isolation proof remain; live critical merge also depends on trusted W0-07 Approval evidence. Await a new, explicit GPT/Krum decision before assigning any successor. No production adoption or index build is implied.

## Canonical W0-03D/C02 technical correction assignment — completed, independent PASS
Use only repository `krumingo/BEG_Worck`, branch `codex/w0-03d-merge-redirect`, existing Draft PR #30, and exact C02 base head `dd6ba1a89b4a5a488d91e082f10f82f323b91c22`. Read this ACTIVE file, the final BLOCKED evidence in `coordination/REVIEWS/W0-03D.md`, `CLAUDE.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §W0-03D, and `docs/flows/FLOW-032.md` before editing. Recheck the remote PR head; stop on mismatch.

Correct only `history()` causal ordering before limit/truncation. Apply the requested limit and hard cap 500 only to causally ordered history, never to an unsorted Mongo cursor. Ensure a returned unmerge cannot lack the merge it reverses because of pre-sort truncation; if a requested limit itself would cut off the causal predecessor, fail closed or provide a bounded, explicit and deterministic response rather than silently presenting a false history. Preserve append-only history, tenant isolation, existing merge/unmerge business rules, Approval behavior, feature-off boundary and unrelated code. No scope expansion, locked FLOW/D changes, merge, deployment, production/NAS/Atlas writes or W0-03E.

Add deterministic regression tests for `merge(seq=1) -> unmerge(seq=2) -> merge(seq=3)`, reverse physical storage order, and `history(limit=2)` showing a causal and deterministic result with no orphaned unmerge. Test the hard cap 500 with more than 500 history events arranged so unsorted truncation would select the wrong causal window. Run focused W0-03D and adjacent W0-03 suites. Run real-Mongo only against a disposable local instance if safely available; report skipped tests separately, never as PASS. Publish one final HANDOFF with exact new head, actual diff, tests, and limitations in the same PR #30; then STOP for independent Codex re-review. This C02 cycle is one bounded correction, not authorization to start C03 automatically.

## Bounded C01 correction assignment — final HANDOFF reviewed; gate BLOCKED
Use the same repository `krumingo/BEG_Worck`, implementation branch `codex/w0-03d-merge-redirect`, Draft PR #30, and exact correction base head `7a84b1721e6d874e0e5f3a140aaf7b288cfc52cd`. Read `coordination/REVIEWS/W0-03D.md` at the current queue head and change only the reviewed defect: preserve append-only history and guarantee causal `merge` → `unmerge` ordering when `recorded_at` timestamps tie. Add a deterministic equal-timestamp regression test and rerun the focused and adjacent W0-03 suites. Do not alter business rules, Approval fail-closed behavior, tenant isolation, unrelated files, locked FLOW/D, or other PRs. Do not merge, deploy, or touch production/NAS/Atlas/secrets. Publish an exact-new-head HANDOFF with actual tests and residual limits, then STOP for independent Codex re-review. This is the only permitted correction attempt; no new Task-ID or cycle.

## Human purpose
Prepare the next FLOW-032 Master Data stage: a human can inspect a proposed merge before it changes anything; historical IDs must continue to resolve, and merge history must remain immutable. This is technical implementation behind the existing feature-off boundary, not authorization to merge real data.

## Canonical authority and prerequisites
Read `CLAUDE.md`, `coordination/README.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` §6 W0-03D, `docs/architecture/W0-03C_UNIQUENESS_READINESS.md`, `docs/flows/FLOW-032.md`, and applicable locked D decisions. Recheck `main` and queue exact SHAs before editing. PRs #16–#20 completed W0-03A/B/C; PR #20 exact head `e3c4ad8cd5b204eb806c39202cc00dd586bc9049` has independent PASS and 20/20 disposable real-Mongo gate evidence, then merged to `main` at the base SHA above. W0-07 Approval runtime is NOT STARTED, so any critical merge must fail closed until trusted Approval evidence exists; an arbitrary `approval_id` string is not itself approval. No W0-03D or later active implementation PR was found at assignment time.

## In scope — one bounded W0-03D technical package
Implement a feature-off Master Data merge/redirect foundation in `backend/app/master_data/` with focused backend tests and only necessary additive, scoped API/permission wiring:

1. Deterministic, read-only preview for two same-tenant, same-entity-type Master records. Show source, target, references to redirect, alias/identifier and other conflicting fields, and exact planned effects. Preview never writes.
2. A guarded merge operation that verifies a preview/version or equivalent stale-state token, tenant and permission context, idempotency, canonical AuditEvent, and explicit trusted Approval for any critical merge. Since W0-07 is absent, fail closed when trustworthy approval cannot be checked. Do not treat a caller-provided `approval_id` or role alone as proof. Keep `MASTER_DATA_MODE=off` inert and `shadow` non-writing.
3. Preserve the source record and immutable merge history; set `merged_into` without hard delete. Resolve an old ID through redirects to the canonical target while refusing cross-tenant/type redirects and cycles. Reject a redirect cycle before any write.
4. Define safe correction/unmerge semantics that append history rather than erase a merge event; if this cannot be made atomic or safely recoverable with existing primitives, fail closed and report the exact technical limitation in HANDOFF instead of claiming a complete operation.

Use existing W0-01 tenant resolver, W0-02 permission boundary, W0-04 AuditEvent and W0-03 repository/service conventions. Any necessary permission action must be scoped and default-denied. The package may include minimal internal schema additions required for traceable history, but no new business decision or runtime activation.

## Excluded
No auto-duplicate detection, automatic merge, heuristic conflict resolution, legacy migration/adapters (W0-03E), W0-07 Approval runtime, production index build, production/NAS/Atlas writes, deployment, merge to `main`, unrelated refactors, secrets, locked FLOW/D edits or other PRs. No real Master data merge. Keep the new PR Draft.

## Acceptance tests and evidence
Tests must cover preview purity and deterministic conflict/reference reporting; changed-record/stale-preview refusal; same-tenant/type and cross-tenant/type rejection; permissions and denial audit; fail-closed missing/unverified Approval (including forged `approval_id`); `off` and `shadow` non-writing behavior; idempotent retry and interrupted/partial-write recovery; immutable history, old-ID resolution, cycle refusal, no hard delete, correction/unmerge history, and canonical AuditEvent success/failure. Run focused and adjacent W0-03 regression tests. Real Mongo tests may run only against a disposable local instance; mark unavailable/skipped honestly. Publish the actual diff, test commands/results, exact new head, residual risks and a final HANDOFF in one Draft PR; stop Claude's session for independent Codex review. Intermediate push, PR body or green CI is not HANDOFF.

## Stop conditions
STOP without inventing a business rule if canonical FLOW/D leaves a material conflict/Approval choice unresolved. STOP for uncertain base SHA, another active W0-03D task, scope expansion, trusted-Approval bypass, inability to preserve history or tenant isolation, external/production access, merge/deploy request, or need for secrets. Ask Codex to mark BLOCKED with evidence rather than guessing. Codex may send at most one bounded correction after independent review; no next task dispatch after PASS.

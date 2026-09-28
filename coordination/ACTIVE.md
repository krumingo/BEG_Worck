# BEG_WORK — active implementation assignment

Status: REVIEW
Current-Agent: CODEX
Current-State: REVIEWING
Claude-State: HANDOFF_READY
Pipeline-Step: REVIEW
Transition-Phase: OBSERVED
Now: Codex independently reviewing C02 HANDOFF on exact PR #30 head 86bb4c9229421687cacbbba5cfe4ab00074ecfbb
Next-Agent: GPT
Relay-State: NO_RELAY_NEEDED
Relay-From: NONE
Relay-To: NONE
Krum-Action: NONE
Dispatch-State: RUNNING
Dispatch-Run: https://claude.ai/code/session_01LkYSm8syiPYo2mzkk1J5Z3
Task-ID: W0-03D
Cycle-ID: C02
Base-branch: main
Base-SHA: 4f46212486e7f2704007cece774939230e0a51f0
Implementation-branch: codex/w0-03d-merge-redirect
PR-URL: https://github.com/krumingo/BEG_Worck/pull/30
PR-Head: 86bb4c9229421687cacbbba5cfe4ab00074ecfbb
Correction-base-SHA: dd6ba1a89b4a5a488d91e082f10f82f323b91c22
HANDOFF-URL: https://github.com/krumingo/BEG_Worck/pull/30#issuecomment-5872902963
HANDOFF-Head: 86bb4c9229421687cacbbba5cfe4ab00074ecfbb
Review: coordination/REVIEWS/W0-03D.md (C01 BLOCKED historical; C02 exact-head independent review in progress)
Predecessor-Task-ID: W0-03C/C03
Predecessor-Review: coordination/REVIEWS/W0-03C.md (PASS on e3c4ad8cd5b204eb806c39202cc00dd586bc9049)
Predecessor-Integration: PR #20 merged into main at 4f46212486e7f2704007cece774939230e0a51f0
Authorization: Krum explicitly authorized W0-03D/C02 and confirmed the one-time Computer Use Send on 2026-09-28. The prompt was sent to the existing Code Cloud session; Claude running tools was observed.
Correction-cycle: C02 HANDOFF received; independent exact-head review in progress; no automatic C03

## Canonical W0-03D/C02 technical correction assignment — HANDOFF received; Codex review in progress
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

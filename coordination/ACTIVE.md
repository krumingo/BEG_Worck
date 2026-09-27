# BEG_WORK — active implementation assignment

Status: WORKING
Current-Agent: CLAUDE
Current-State: WORKING
Claude-State: WORKING
Pipeline-Step: IMPLEMENTATION
Transition-Phase: OBSERVED
Now: Claude working
Next-Agent: CODEX
Relay-State: NO_RELAY_NEEDED
Relay-From: NONE
Relay-To: NONE
Krum-Action: NONE
Dispatch-State: RUNNING
Dispatch-Run: https://claude.ai/code/session_01LkYSm8syiPYo2mzkk1J5Z3
Task-ID: W0-03D
Cycle-ID: C01
Base-branch: main
Base-SHA: 4f46212486e7f2704007cece774939230e0a51f0
Implementation-branch: codex/w0-03d-merge-redirect
PR-URL: NONE
PR-Head: NONE
Review: coordination/REVIEWS/W0-03D.md (create only after independent review)
Predecessor-Task-ID: W0-03C/C03
Predecessor-Review: coordination/REVIEWS/W0-03C.md (PASS on e3c4ad8cd5b204eb806c39202cc00dd586bc9049)
Predecessor-Integration: PR #20 merged into main at 4f46212486e7f2704007cece774939230e0a51f0
Authorization: Krum confirmed one-time Computer Use Send; Claude session start observed at https://claude.ai/code/session_01LkYSm8syiPYo2mzkk1J5Z3
Correction-cycle: NONE

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

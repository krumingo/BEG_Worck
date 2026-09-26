# BEG_Work Claude assignment queue

Status: PASS
Dispatch-State: NONE
Dispatch-Run: https://claude.ai/epitaxy/session_012DCBdX2BRA6U2UR5zkdkPe
Task-ID: W0-03C
Cycle-ID: C03
Base-branch: feat/w0-03c-uniqueness-readiness
Base-SHA: ed588e9420e241f58c14146de6f0c890b38b3743
PR-URL: https://github.com/krumingo/BEG_Worck/pull/20
PR-Head: e3c4ad8cd5b204eb806c39202cc00dd586bc9049
Review: coordination/REVIEWS/W0-03C.md
Authorization: https://github.com/krumingo/BEG_Worck/pull/20#issuecomment-5847103313
Correction-cycle: C03 (new explicit bounded authorization; C02 remains BLOCKED in history)

## Human purpose
Resolve only the ambiguous `create_index` result exposed by the independent C02 review. An exception after the server creates an index must not be reported as successful rollback while the index survives. No new feature or business rule.

## Canonical authority and prerequisites
Read `CLAUDE.md`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`, `docs/architecture/IMPLEMENTATION_WAVES.md`, `docs/architecture/W0-03C_UNIQUENESS_READINESS.md`, and the applicable locked FLOW-032/D decisions. The exact C02 review in `coordination/REVIEWS/W0-03C.md` is the defect evidence, not a PASS. Verify that Draft PR #20 still has exact head `ed588e9420e241f58c14146de6f0c890b38b3743` before editing. Work only in the existing PR branch.

## In scope
Correct the `create_index` exception path in `backend/app/master_data/index_bootstrap.py` and focused tests for it. Reconcile actual server index state, including name, keys, uniqueness and relevant options/signature, before deciding claim or rollback status:

1. Expected index present with matching definition: retain this run's ledger claim and report an explicit ambiguous/applied-unconfirmed outcome, not `FAILED_ROLLED_BACK`; preserve evidence for deterministic later rollback/recovery.
2. Index provably absent: retract only this run's optimistic claim, then apply the existing safe failure/rollback behavior.
3. Reconciliation unavailable (including connection loss): fail closed, retain the claim and report an explicit ambiguous/reconciliation-required outcome.
4. Conflicting definition: retain evidence/claim, report `BLOCKED`/`CONFLICT` for human review, and never auto-delete that index.

Review rollback behavior only as needed to keep these four outcomes safe; never drop an index with a foreign or conflicting definition.

## Excluded
No other W0-03C slice, no new Task-ID, no next implementation wave, no merge, deploy, migration, production/NAS/Atlas write, real index build outside disposable local scratch, secrets, or locked FLOW/D changes. Do not touch unrelated files or PRs. Keep PR #20 Draft.

## Acceptance and evidence
Add fault-injection tests for create-then-raise with matching definition, provably absent, unreachable reconciliation, conflicting definition, rollback after recoverable cases, and refusal to delete foreign/conflicting indexes. Re-run focused regression and safe local-only real-Mongo tests where available; distinguish unavailable external tests from PASS. Publish exact new head SHA, actual diff, commands/results, status/ledger evidence and limitations in a final HANDOFF on PR #20. STOP the Claude session for independent Codex review on the stable exact head. An intermediate push, green CI, or PR body is not completion.

## Historical review outcome
C02 was `BLOCKED` on exact PR head `ed588e9420e241f58c14146de6f0c890b38b3743`: an acknowledged server-side index followed by a client exception is retracted from the ledger and survives despite `FAILED_ROLLED_BACK`. The new C03 authorization above supersedes the old dispatch block only for this narrow correction; it does not rewrite or pass the C02 review.

## C03 independent outcome
Claude's final [HANDOFF](https://github.com/krumingo/BEG_Worck/pull/20#issuecomment-5847481878) and a stable Draft PR head both identify `e3c4ad8cd5b204eb806c39202cc00dd586bc9049`. Independent Codex review of that exact head is `PASS` for the bounded C03 correction; evidence and limitations are in `coordination/REVIEWS/W0-03C.md`. This is **not** a W0-03C gate PASS: real-Mongo tests on this head and the owner-controlled NAS/production steps remain unperformed. STOP before merge, deployment, migration or any index build outside disposable local scratch. No next implementation task is dispatched.

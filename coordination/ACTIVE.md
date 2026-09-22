# BEG_Work Claude assignment queue

Status: CHANGES_REQUESTED
Dispatch-State: RUNNING
Dispatch-Run: https://claude.ai/epitaxy/session_0121FURkAfgZYfT9dqwqsyvc
Task-ID: W0-03C
Base-branch: feat/w0-03c-uniqueness-readiness
Base-SHA: be8cd207c94388e81b24173af6d690d69abcea00
PR-URL: https://github.com/krumingo/BEG_Worck/pull/20
PR-Head: be8cd207c94388e81b24173af6d690d69abcea00
Review: coordination/REVIEWS/W0-03C.md
Correction-cycle: 1-of-1

## Human purpose
Make the already-drafted unique-index bootstrap honest and recoverable after interruption, and repair the NAS command that failed before running. No new feature.

## Canonical authority and prerequisites
Read CLAUDE.md, docs/architecture/IMPLEMENTATION_GATE_MATRIX.md, IMPLEMENTATION_WAVES.md, W0-03C_UNIQUENESS_READINESS.md, and relevant FLOW-001–050 Master Data decisions. This is a correction inside PR #20, not a business-rule change. The exact PR head and independent review above are mandatory.

## In scope
Correct only findings 1–3 in the review. Ensure an interruption between create_index and ledger claim does not strand an untracked index, and final ledger-write failure cannot return APPLIED. Add fault-injection positive/forbidden tests. Fix the documented sudo/PATH or explicit Docker path command in the runbook and hook header. Keep all work on PR #20's existing branch.

## Excluded
No new implementation slice, no NEXT task, no merge, deploy, production/NAS/Atlas write, real index build, migration, secrets, or change to locked FLOW decisions. Do not mark W0-03C or Wave 0 complete.

## Acceptance and evidence
Re-run focused tests plus appropriate regression. Demonstrate the two failure windows, recovery/rollback behavior and truthful final status. Show actual diff, exact new head SHA, test commands/results and limits in an updated HANDOFF. Keep Draft PR. STOP for independent Codex re-review. If the correction cannot be safe in one bounded cycle, report BLOCKED.

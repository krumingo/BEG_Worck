# Codex independent review template

Task-ID:
PR:
Head-SHA:
Base-SHA:
Verdict: PENDING

## Scope and canonical rules
Cite FLOW/D decision and verify actual changes do not alter locked business logic.

## Diff and tests
List changed files, significant code paths, exact commands/results, and positive/forbidden/tenant/idempotency checks. A claimed test is not accepted until independently rerun or its evidence is verified.

## External evidence and limits
For NAS, Atlas, production, real database or other external evidence, say exactly what was read and what remains unverified. Never infer data safety from a PR description.

## Findings
Prioritized actionable findings with file/line or evidence link. Note pre-existing failures separately from regressions.

## Decision and next
PASS means code review evidence is sufficient for the specified slice, not merged/deployed or Implementation Gate PASS. CHANGES_REQUESTED permits one bounded correction. BLOCKED requires Krum or external state. State exact successor base and prerequisites, or WAITING_OWNER.

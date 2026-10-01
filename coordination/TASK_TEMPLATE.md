# ACTIVE assignment template

Status: IDLE
Dispatch-State: NONE
Dispatch-Run: NONE
Task-ID: NONE
Base-branch: main
Base-SHA: NONE
Predecessor-Task-ID: NONE
Predecessor-Review: NONE

Human-Summary-BG: REQUIRED — 1–2 lines in plain Bulgarian

## Human purpose
Write the same 1–2 line Bulgarian summary here in natural language: what will be done and why it matters to Krum. Avoid technical-only wording.

## Canonical authority
List exact FLOW files and D decisions. If ambiguous, BLOCKED; do not invent a rule.

## Prerequisites
List exact evidence and review artifacts for required predecessor tasks. A Draft PR is not a merge.

## In scope
List specific behavior and files. One implementation slice only.

## Excluded
List business-rule changes, unrelated cleanups, and forbidden external systems.

## Acceptance tests
Name positive, forbidden, tenant isolation, idempotency, correction/rollback and regression checks as applicable.

## Evidence required
Exact SHA, real diff, test command/output, residual risks, Draft PR and HANDOFF. Distinguish simulated from real external-system checks.

## Stop conditions
Missing prerequisite, uncertain base, existing active task with same Task-ID, conflicting canonical docs, need for production/NAS/Atlas/secrets, migration or merge, or more than one failed correction cycle. Report BLOCKED to Codex.

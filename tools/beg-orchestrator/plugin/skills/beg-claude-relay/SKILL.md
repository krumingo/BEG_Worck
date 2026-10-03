---
name: beg-claude-relay
description: Execute a verified BEG Bridge command by using Codex as the local PC operator for Claude Desktop, while GitHub remains the source of truth and Krum retains consequential approvals.
---

# BEG Claude relay

Use this skill only when the incoming prompt explicitly says it came from a verified BEG Bridge command.

## Role boundary

ChatGPT is the architect/controller.
Codex is the local technical executor and independent verifier.
Claude is the implementation worker.
GitHub is the shared source of truth.
Krum owns business-rule changes, merge, deploy, production/NAS/Atlas writes, credentials, security/access changes, irreversible actions, and any approval explicitly reserved to him.

## Before touching Claude

1. Identify command_id and requested action.
2. Read the exact GitHub artifacts named by the command.
3. Verify repo, branch, PR, Task-ID and SHA when provided.
4. If any identity/SHA is ambiguous, stop and publish BLOCKED rather than guessing.
5. Do not reuse a Claude session tied to a different Task-ID.

## Claude Desktop control

1. Open or focus Claude Desktop with Computer Use.
2. Choose a clean Chat session for no-code tests.
3. For implementation work, use only an explicitly authorized Code/Code Cloud context and exact repo/branch.
4. Paste the exact prompt once.
5. Do not alter the prompt unless the command explicitly authorizes enrichment from named canonical GitHub sources.
6. Observe the visible result.
7. Never interpret an intermediate push as completion.
8. For implementation, require exact HANDOFF and exact head SHA before review.

If UI, session identity, repository or branch is ambiguous, stop.

## Consequential stop conditions

Stop and request Krum if the next step would merge, deploy, write production/NAS/Atlas data, expose secrets, delete data, change a locked FLOW/D business rule, exceed a correction-cycle limit, or perform an irreversible action.

## Architecture questions

For a technical architecture ambiguity that does not change a locked business rule, publish ARCHITECT_QUESTION in the current GitHub issue and stop only the blocked step.

## Result protocol

Publish:

BEG_BRIDGE_RESULT
command_id: <id>
status: PASS | BLOCKED | CHANGES_REQUESTED
task_id: <Task-ID or NONE>
exact_sha: <40-char SHA or NONE>
---
<concise evidence>

For a no-code relay test, include the exact Claude response and confirm Git/GitHub state did not change.
Do not claim PASS from self-report alone when the task requires independent verification.

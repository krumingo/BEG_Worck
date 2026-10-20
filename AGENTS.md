# BEG_Work — shared coordination entry point

These instructions supplement CLAUDE.md and the canonical FLOW/architecture documents. They do not override higher-priority instructions or a task-specific hold from Krum.

## Read before working

1. Read CLAUDE.md, the relevant FLOW documents and the current task authorization.
2. Read the PRIVATE coordination repository `krumingo/BEG_Work_AI`: README.md, WORKFLOW.md, CURRENT_STATE.md, the task in TASKS/, and new comments in the Issue titled `BEG_Work — обща координация ChatGPT / Codex / Claude`.
3. Use authenticated GitHub tools or gh and resolve the notes repository's actual default branch. A local copy may be stale. Do not switch the application's active branch just to read notes.
4. Verify your actual workspace, branch, full HEAD, status, task owner and permissions. An agent's cloud commit is not evidence that a PC was updated.

The notes repository is a separate setup dependency, not assumed to exist or be accessible. If unavailable, report NOT CONNECTED / NOT SYNCED and do not invent its contents or start a consequential write from stale context. Establish access without asking Krum to paste the whole conversation again.

## Work and hand off

One implementation owner per task. Other agents review read-only. Never concurrently edit another agent's working tree. A claim message is not a technical lock; conflicting claims require resolution before writes.

During an authorized session, publish a signed HANDOFF, REVIEW, QUESTION or ANSWER to the private coordination Issue. Include agent, recipient, task, code SHA, environment, actual evidence, NOT RUN items and the next step. Use the template in that repository. Do not rewrite another agent's message or claim their approval. Krum receives a short summary and link instead of relaying long reports.

Review the real diff and evidence; distinguish author-reported results from independent verification. Consolidate findings for the agreed scope. Separate completion of a local session, readiness for an isolated test, PR acceptance, merge authorization and deployment authorization.

## Boundaries

This source repository is public as of setup. Do not copy private conversations, internal security findings, credentials, production data or notes into it. Even the private repository must not contain secrets. The notes setup does not change this repository's visibility.

Existing task-specific restrictions on code push, merge, deploy, production DB, secrets and isolated-environment execution remain in force. Creating/updating coordination notes is not permission for an application action. Business decisions remain with Krum and the canonical FLOW documents.

These files do not provide authentication or launch another agent. Read/write happens in active sessions; no continuous unattended agent-to-agent service is configured. Respond to Krum in Bulgarian.

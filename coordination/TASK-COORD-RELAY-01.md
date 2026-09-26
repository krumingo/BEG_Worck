# TASK COORD-RELAY-01 — GitHub event dispatcher (Claude implements; Codex reviews)

Status: DRAFT / NOT DISPATCHED. This file is a bounded assignment proposal, not an ACTIVE runtime task.

Repository: `krumingo/BEG_Worck`. Work on `codex/agent-relay-design` (Draft PR #21), using its exact current head SHA as the starting point. Do not touch `main`, `codex/claude-queue` or PR #20. W0-03C remains BLOCKED.

## Goal

Implement a GitHub Actions–based coordination dispatcher that observes relevant GitHub events and schedules **at most one** approved technical assignment. Codex owns task selection, independent review, and PASS/CHANGES_REQUESTED/BLOCKED verdicts; Claude writes only the scoped implementation. The system must never claim an assignment was sent merely because it wrote a PENDING file.

## Scope

1. Extend the coordination-only prototype in `coordination/RELAY_PROTOCOL.md`, `WORK_PLAN.md`, `ACTIVITY_LOG.jsonl` and `tools/agent_relay.py`. Read `CLAUDE.md`, `coordination/ACTIVE.md`, templates/reviews, Gate Matrix and Implementation Waves first. Treat exact states and SHAs as authoritative.
2. Add a GitHub Actions workflow and stdlib-first dispatcher that reacts to supported events (push/PR/review/comment and optional manual dry run), reads the queue branch by exact SHA, normalizes events, and evaluates the existing fail-closed gate. It must not trust PR body, comments, green CI or self-reported HANDOFF as independent PASS.
3. Provide durable idempotency (Task-ID + exact base SHA + dispatch generation), a single active-task lock, bounded retry/backoff, and no duplicate action on repeated/out-of-order events. A concurrent-event test is required.
4. Provide an emergency off switch that defaults OFF until explicitly enabled by the owner; while OFF, event runs may report status but cannot dispatch or change ACTIVE. Document how Krum can switch it off immediately. Do not change repository settings yourself.
5. Maintain an append-only event journal with UTC time, actor, event, Task-ID, queue/head/base SHA, decision, evidence URL/file, attempt count, problem category/count, and owner-required flag. Do not fabricate old history. Show how the dashboard can read verified status; do not change its percentages without evidence.
6. Enforce the gate: final HANDOFF, ended Claude session, stable current PR head, review artifact with independent reviewer, actual diff checked, **every applicable acceptance test PASS** on that exact SHA, and proven prerequisites before next task. An N/A test requires a reason. A changed head invalidates prior PASS.
7. Support one limited correction cycle; if a serious issue repeats or 1/1 is exhausted, hold and escalate. Explicit owner gates: new business rules, security/access, production/NAS/Atlas, destructive migration, merge and deploy.
8. Investigate whether a supported, already-authorized direct Claude Desktop Code Cloud transport can be invoked by the coordinator/Codex heartbeat without Routine, local unsigned Claude CLI or paid API key. If none is available, implement a typed outbox/adapter interface that returns `TRANSPORT_BLOCKED`; **do not simulate delivery**. Codex's 5-minute monitor may perform direct UI delivery only after a separately observed successful send.

## Exclusions

No Claude Routine; no API/OAuth key creation or request to use a paid key; no security/permission changes; no live dispatch activation; no runtime code, locked FLOW, NAS, Atlas, production, migration, merge or deploy. Do not modify `coordination/ACTIVE.md` for this meta task. Do not start W0-03D or any implementation successor. Do not create a second implementation session.

## Acceptance evidence

Add reproducible tests for: positive ready case; default-OFF kill switch; current W0-03C BLOCKED; missing/failed test; changed SHA; intermediate push; duplicate/replayed and concurrent events; exhausted correction cycle; owner-required task; stale queue snapshot; transport unavailable. Run the tests and report exact commands/results. Prove no network dispatch or ACTIVE write occurs in all HOLD cases. Provide a final HANDOFF with exact PR head SHA, diff summary, limitations and source-backed transport finding; then stop for Codex independent review. No next task before Codex's full PASS.

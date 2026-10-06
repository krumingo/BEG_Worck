# Claude–Codex implementation loop

**Mandatory document-resolution policy:** begin each new assignment or review with [DECISIONS_INDEX.md](DECISIONS_INDEX.md), then follow [docs/MD_USAGE_POLICY.md](../docs/MD_USAGE_POLICY.md) before using ACTIVE/control state, relevant FLOW/architecture, prior review and actual code. Historical documents and prompts do not override canonical decisions. Do not read every `.md` mechanically.

This branch is a coordination mailbox, separate from runtime code. `coordination/ACTIVE.md` is the only dispatch pointer; `coordination/REVIEWS/` holds independent Codex verdicts. The default state is IDLE.

Dispatch protocol: Codex writes Dispatch-State: PENDING only after validating one ACTIVE task. Claude executes only PENDING. After Codex observes the run start, Codex changes it to RUNNING and records Dispatch-Run. A scheduled Claude run seeing RUNNING must stop as IDLE, not repeat work. Codex alone returns it to PENDING for a new bounded correction or next Task-ID, or to NONE after review. The state field prevents duplicate delivery; a run status alone does not prove code completion.

## Two-phase dashboard-first lifecycle (protocol v2)

For every GPT, Codex and Claude handoff, publish and validate the pending/intended control snapshot **before** the consequential Send, review verdict publication or relay. Promote it only after the event is observed and its evidence URL is recorded. `transition.phase=INTENT` is not completion; `OBSERVED` requires evidence. The dashboard's agent cards are activities (`WORKING`, `WAITING`, `REVIEWING`, `HANDOFF_READY`, `BLOCKED`, `NOT_ACTIVE`), while `PASS`, `CHANGES_REQUESTED` and `BLOCKED` review verdicts remain outcomes, never a substitute for an agent activity.

Before Codex sends to Claude: `Dispatch-State: PENDING`, Codex `WORKING`, Claude `WAITING`, next agent `CLAUDE`, and `NOW` says Codex is preparing/sending. If Computer Use requires action-time confirmation, `Krum-Action` says `CONFIRM SEND TO CLAUDE`; the confirmation is not evidence of Claude start. After a session is observed, record its URL/ID, change Dispatch to `RUNNING`, Codex to `WAITING` and Claude to `WORKING`. An intermediate push is not completion. Only a published exact-head HANDOFF changes Claude to `HANDOFF_READY` and Codex to `REVIEWING`; GPT waits for the verdict. During review, even a locally prepared verdict remains `PENDING`/`READY` with Codex `REVIEWING`. Only after an exact-head independent verdict is published may `LAST COMPLETED` and `LAST RESULT` become Codex and `PASS`/`CHANGES_REQUESTED`/`BLOCKED`. Manual relay and `requires_krum` stay separate from the real `next_agent`.

Protocol v1 snapshots remain readable as historical data. New lifecycle transitions use v2 and must pass both the canonical engine and dashboard validation before publishing. A snapshot marked `VALID` is still only valid as of its cited timestamp and exact source SHAs; consumers must recheck live sources before action.

Direct dispatch channel (22 Sep 2026): Claude Routines are paused and MUST NOT be used. Codex sends one ACTIVE Task-ID through a regular Claude Desktop Code Cloud session connected to krumingo/BEG_Worck, observes the resulting session, and records its URL/ID in Dispatch-Run. A read-only direct-channel check fetched the coordination branch successfully without edits. Each implementation session receives only one bounded task; a second task waits for independent review. Claude Code CLI is installed locally but not logged in, so it is not the active channel. Do not silently switch to a paid API key.

Cycle: Codex selects one bounded task from the canonical FLOW and Implementation Waves documents, checks predecessors and exact base SHA, writes READY with a unique Task-ID. Claude works only that assignment, publishes an exact-SHA Draft PR and HANDOFF, then stops. Codex checks the real diff, runs relevant tests independently in an isolated checkout, distinguishes code evidence from external data evidence, and records PASS, CHANGES_REQUESTED or BLOCKED. A failed review gets a bounded correction assignment to the same Task-ID. When the defect is technical and remains inside the already-approved business scope, Codex dispatches that correction directly to Claude and independently reviews the new HANDOFF; Krum is not used as a relay. The correction loop may repeat until PASS or until a real business/security/production blocker requires Krum. A verified task may lead to another task only after GPT/Krum start the next task; never dispatch two READY tasks concurrently.

A Draft PR is not merged code. A successor may be stacked on a verified exact head only when its assignment explicitly names that head and the dependency; it must remain a separate Draft PR. Do not call a stack integration into main, release, deployment, or Implementation Gate PASS. Codex must not update progress percentages from PR self-reports alone.

Krum is asked only for a new or changed business rule, an unresolved choice that changes scope, security/access or credentials, production/NAS/Atlas operations, destructive migration, live acceptance, merge into main, or deployment. Technical implementation inside locked FLOW scope does not need a repeated copy/paste approval. The older per-change manual transfer in CLAUDE.md section 18 is superseded for this coordination loop by Krum's explicit 22 Sep 2026 instruction; its business and merge/deploy safeguards remain.

Automations and routine runs consume usage. If the Claude trigger cannot be reached or evidence cannot be verified, stop with BLOCKED; never infer success from a green run status.


## Locked agent execution loop — 06.10.2026

The mandatory handoff/review process is [AGENT_EXECUTION_LOOP.md](AGENT_EXECUTION_LOOP.md).

**Canonical route:** GPT prepares and tracks the plan → Krum hands the task once to Codex → Codex dispatches Claude directly → Claude implements and returns HANDOFF directly to Codex → Codex independently audits → if the same approved Task-ID needs technical corrections, Codex dispatches the correction directly to Claude and repeats the independent review → after PASS Codex returns the verified result to GPT → GPT verifies status, reports to Krum, visualizes the schedule and prepares the next task.

Krum is **not** a manual relay between Codex and Claude. Started tasks keep their already-approved scope and gates. New tasks should be larger functional packages, but remain independently reviewable.

Krum grants standing PC/Computer Use authorization for the coordination actions defined in AGENT_EXECUTION_LOOP.md. This does not authorize merge, deploy, production/NAS/Atlas writes, destructive migration/customer-data actions, new live credentials, business-rule changes, or security exceptions.

This section supersedes older coordination wording that required owner relay or owner approval for every bounded correction inside the same already-approved Task-ID. Real business/security/production blockers still stop for Krum.

## Mandatory GitHub event stream — 06.10.2026

Every active BEG_WORK task must use [AGENT_EVENT_PROTOCOL.md](AGENT_EVENT_PROTOCOL.md).

The current Task Issue is the append-only event stream. Codex and Claude publish structured events for task acceptance, canonical reading, preflight, dispatch attempt/success/failure, assignment receipt, implementation milestones, test start/result, HANDOFF, independent review, findings, correction dispatch, PASS/BLOCKED and final result relay.

A failed action must be published explicitly; silent failure is forbidden. This is push-based and does **not** authorize periodic polling.

If ACTIVE/CONTROL_STATE/CONTROL_BOARD lag behind a newer event with exact evidence, treat the projection as STALE, reconcile it to the event stream, and continue from the real latest event.

## Mandatory Bulgarian human summary

Every ACTIVE implementation task must contain a **1–2 line plain-Bulgarian human summary** explaining what will actually be changed and why it matters to Krum. This is not a technical restatement of the Task-ID.

Canonical field in ACTIVE/TASK template: `Human-Summary-BG`.

Every new assignment message to Codex or Claude **begins** with `На човешки:` and that exact 1–2 line text before its technical banner. The same words go into `Human-Summary-BG` and, during the active assignment/review, into the dashboard's “Какво правим”/NOW projection. After a lifecycle transition, NOW must be updated to the newly observed reality; it must not keep saying a completed action is still pending. Dashboard labels and management-facing task text are Bulgarian by default. Technical identifiers (Task-ID, Cycle-ID, SHA, PR, FLOW/Wave IDs) remain unchanged.

## No-polling rule for Codex / Work monitors

Periodic polling of GitHub for an active BEG_WORK implementation task is **forbidden by default**. Do not create or keep a 5-minute/hourly monitor whose only action is to re-read ACTIVE/CONTROL_STATE/PR state and report unchanged status.

Allowed triggers for Codex review or owner notification are event-driven only:
- a newly published final exact-head HANDOFF;
- a published PASS / CHANGES_REQUESTED / BLOCKED review result;
- an explicit Krum instruction;
- a real blocker that requires Krum's decision.

After any final review verdict, every task-specific monitor must be disabled. A CHANGES_REQUESTED verdict does **not** authorize polling, but when its fixes are technical and stay inside the same already-approved Task-ID/business scope, Codex may immediately create and directly dispatch the bounded correction cycle to Claude under `AGENT_EXECUTION_LOOP.md`. Only a real business/security/production blocker waits for Krum.

If a scheduled task wakes while no qualifying event exists, it must exit without GitHub writes, without ChatGPT notification, and without starting Codex/Claude work.

Control-board management text should explicitly show `MONITORING: OFF` once a task is waiting on Krum after a verdict.


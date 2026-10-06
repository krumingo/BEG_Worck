# BEG_WORK — LIVE DASHBOARD

> Статус: management projection.
> Source priority: Task Issue event stream → exact PR/review evidence → CONTROL_STATE/CONTROL_BOARD → IMPLEMENTATION_WAVES.
> Do not infer PASS or percentages from stale projection.
> Dashboard tracking baseline: 2026-10-06 (new event protocol). Historical durations before this date are shown only where exact timestamps exist.

## 1. Agent communication

| Agent | State | Current action | Waiting for | Last confirmed event |
|---|---|---|---|---|
| GPT | ACTIVE / COORDINATION | Maintains roadmap, task scope and dashboard | Codex review events | `CODEX_TASK_ASSIGNED` + `CLAUDE_STANDING_TASK_ASSIGNED` |
| Codex | EXPECTED NEXT | Independent W0-06B/C02 review | Must publish `HANDOFF_DETECTED` then `REVIEW_STARTED` | No post-protocol Codex event yet |
| Claude | WAITING | C02 implementation finished | Bounded correction only if Codex dispatches it | FINAL HANDOFF in PR #46 @ `d69145e...` |

### Communication path

```text
GPT → Krum → Codex → Claude → Codex ↔ Claude corrections → Codex PASS → GPT → Krum
```

## 2. Current task

- Wave: **W0**
- Item: **W0-06 File Registry**
- Task: **W0-06B**
- Cycle: **C02**
- PR: **#46**
- Exact head: **d69145e795445ca3ca18df9a6e9818b1dfb8001e**
- Current stage: **Awaiting independent Codex review pickup**
- Claude implementation: **DONE / HANDOFF PUBLISHED**
- Codex independent verdict: **PENDING**
- Merge: **NO**
- Deploy: **NO**

## 3. Current task timing

Exact timestamps available from GitHub evidence:

| Stage | Start | Finish | Wall time | Meaning |
|---|---|---|---:|---|
| C02 Claude implementation | 2026-10-06 15:25:01Z | 2026-10-06 15:33:48Z | **8m 47s** | Dispatch/start observed → final HANDOFF published |
| C02 waiting for Codex review | 2026-10-06 15:33:48Z | OPEN | live | HANDOFF published → `REVIEW_STARTED` not yet published |
| C01 Claude implementation | 2026-10-04 22:01:04Z | 2026-10-04 23:11:35Z | **1h 10m 31s** | Historical exact evidence |
| C01 review wall interval | 2026-10-04 23:11:35Z | 2026-10-05 05:41:36Z | **6h 30m 01s** | Wall interval only; not claimed as active Codex work |

**Important:** wall time and active work time are different. From the new event protocol onward, stage START/RESULT events are used to derive task timing more accurately.

## 4. Test statistics — Claude C02 handoff, not yet independently accepted

| Gate | Result |
|---|---:|
| Avatar security | 30 / 30 PASS |
| W0-06A + W0-06B focused | 451 / 451 PASS |
| FLOW-002 / tenancy | 125 / 125 PASS |
| Real Mongo W0-06 | 33 / 33 PASS |
| Static guards | 0 violations |
| Broad W0 batch | 1619 PASS / 15 FAIL / 0 SKIP |
| Live `test_media_acl.py` | NOT RUN |
| Browser/Jest acceptance | NOT RUN |

These are Claude evidence until Codex independently verifies them.

## 5. Event coverage — post-protocol

| Required event | State |
|---|---|
| GPT `PROTOCOL_UPDATED` | ✅ |
| GPT `CODEX_TASK_ASSIGNED` | ✅ |
| GPT `CLAUDE_STANDING_TASK_ASSIGNED` | ✅ |
| Codex `HANDOFF_DETECTED` | ⏳ |
| Codex `REVIEW_STARTED` | ⏳ |
| Codex `REVIEW_PROGRESS` | ⏳ |
| Codex `PASS / CHANGES_REQUESTED / BLOCKED` | ⏳ |
| Codex `RESULT_SENT_TO_GPT` | ⏳ |

## 6. Wave 0 roadmap

| Order | Item | Status |
|---:|---|---|
| 1 | WAVE-PLAN-SYNC | ✅ DONE |
| 2 | W0-09A Release core | ✅ MERGED / NOT DEPLOYED |
| 3 | W0-10A Restore proof | ✅ PASS |
| 4 | W0-03 Master Data | ◐ PARTIAL / open debt |
| 5 | **W0-06 File Registry** | ▶ **CURRENT** |
| 6 | W0-07 DQ + Approval | ○ NOT STARTED |
| 7 | W0-05 Payment Core | ○ NOT STARTED |
| 8 | W0-08 Billing / Entitlements | ○ NOT STARTED |
| 9 | W0-04B Audit lifecycle | ○ NOT STARTED |
| 10 | W0-10B Full DR | ○ NOT STARTED |
| 11 | W0-11 Export / Retention / Deletion | ○ NOT STARTED |
| 12 | W0-09B Wave-0 exit gate | ○ NOT STARTED |

### W0-06 internal execution

```text
W0-06A foundation             ◐ predecessor / reviewed with findings
W0-06B C01 providers          ◐ CHANGES_REQUESTED
W0-06B C02 avatar correction  ▶ HANDOFF DONE → CODEX REVIEW NEXT
W0-06C integrity/scheduler    ○ NEXT AFTER PASS
W0-06D legacy migration       ○ PLANNED
W0-06E final FLOW-016 gate    ○ PLANNED
```

## 7. Forecast model

Forecasts are not invented. Every new task gets a GPT estimate before dispatch:
- `estimate_low`
- `estimate_expected`
- `estimate_high`
- confidence: LOW / MEDIUM / HIGH
- reason / comparable prior tasks.

During execution, the dashboard shows:
- actual elapsed;
- stage elapsed;
- forecast remaining;
- forecast total;
- variance to expected.

### Current forecast status

- W0-06B/C02: implementation finished; **review duration forecast not yet set because Codex has not published REVIEW_STARTED**.
- W0-06C: scope known conceptually but not yet assigned; estimate will be published before task dispatch.
- Wave 0 remaining forecast: **TBD until remaining-item estimates are baselined**.
- Whole-program elapsed/remaining forecast: **historical baseline not yet reconstructed; do not invent days**.

## 8. Dashboard rule

GPT includes a current dashboard snapshot before every new task and whenever Krum asks for status/dashboard.

Codex/Claude event stream supplies the live data. The ChatGPT UI itself cannot be permanently modified or pinned by GPT; this GitHub dashboard is the persistent source and GPT renders the latest snapshot in chat.

# BEG_WORK control board

Source: `coordination/CONTROL_STATE.json` · branch: `codex/claude-queue` · protocol v2
ACTIVE source updated: 2026-10-02T05:15:45Z · CONTROL STATE: **VALID** as of 2026-10-02T05:15:45Z (LIVE_GITHUB)
**Snapshot only:** `VALID` is not live verification. Recheck source blobs, PR head and review before any consequential action.

CURRENT: W0-03E-A2C / C01 / CODEX / **WORKING**
LAST: CODEX — W0-03E-A2C/C01 canonical assignment prepared; Claude Send not yet performed / ASSIGNMENT_PENDING
RELAY: NOT_SENT · CODEX → CLAUDE
NOW: Няма да оправяме само `invoice_lines` и после да чакаме да излезе следващ теч. Ще минем целия активен backend и ще затворим всички места, където при еднакви ID-та данни могат да прескочат между две фирми. Codex подготви задачата; изпращането към Claude е PENDING.
TRANSITION: ASSIGNMENT / INTENT · verdict NONE
NEXT: CLAUDE
KRUM ACTION: REQUIRED — One-time Computer Use confirmation is required immediately before A2C Send to Claude.
WAITING FOR: One-time Computer Use Send confirmation before Claude dispatch

## Required agent banner

All three agents must read the control state and recheck live evidence before consequential work. STALE, CONFLICT or INVALID: **STOP**.

```text
BEG_WORK
TASK: W0-03E-A2C
CYCLE: C01
AGENT: GPT | CODEX | CLAUDE (select the actual sender)
ROLE: ARCHITECT | TECH_LEAD_QA | IMPLEMENTER (match AGENT)
STATE: WORKING
NEXT: CLAUDE
WAITING_FOR: One-time Computer Use Send confirmation before Claude dispatch
```

| Task | Cycle | ChatGPT | Codex | Claude | Current | Waiting for | Result |
|---|---|---|---|---|---|---|---|
| W0-03E-A2C | C01 | WAITING | WORKING | WAITING | CODEX | One-time Computer Use Send confirmation before Claude dispatch | WORKING |

## Agent cards

Current agent state is explicit in `agent_states`; history below is evidence, not a status source.

| Agent | State | Work-ID | Waiting for | Updated at (UTC) |
|---|---|---|---|---|
| GPT | WAITING | W0-03E-A2C/C01/GPT | A2C implementation and independent gate outcome | 2026-10-02T05:15:45Z |
| CODEX | WORKING | W0-03E-A2C/C01/CX | One-time Computer Use Send confirmation before Claude dispatch | 2026-10-02T05:15:45Z |
| CLAUDE | WAITING | W0-03E-A2C/C01/CL | Canonical A2C assignment; not yet sent | 2026-10-02T05:15:45Z |

GPT → **Codex (WORKING)** → Claude → Codex → GPT

## Evidence

- ACTIVE: `coordination/ACTIVE.md` · source commit `493f4669699c7ccad8205750d3ad1b94edc34d4c` · blob `7fbb26a5de504554dd43499171a66ce922478a0e`
- Dispatch session: — · dispatch state **PENDING**
- HANDOFF comment SHA-256: `—`
- Canonical docs: `CLAUDE.md` @ `e91d3230`, `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` @ `e7957b71`, `docs/architecture/IMPLEMENTATION_WAVES.md` @ `e0ce9c2a`, `docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md` @ `efa5f37c`, `docs/architecture/TENANCY_MODEL.md` @ `93997df2`, `docs/flows/FLOW-032.md` @ `94f6be34`, `docs/flows/FLOW-002.md` @ `5594ffa4`, `docs/flows/FLOW-040.md` @ `3d2ce96e`
- Wave/Flow: `W0` / `FLOW-032` · progress: **ASSIGNMENT / STAGE_ONLY** (no proven percentage)
- `control_state_commit_sha` names the previous published state commit; it cannot self-reference this file's own Git commit.

## Append-only history

Legacy events have no original Cycle-ID; `mapped_cycle` is an explicit mapping, not a rewritten historical claim.

| UTC | Original cycle | Mapped cycle | Event | Agent | State after | Exact head | Source |
|---|---|---|---|---|---|---|---|
| 2026-10-02T05:15:45Z | C01 | — | ASSIGNMENT | CODEX | WORKING | `62cf2a53` | [evidence](https://github.com/krumingo/BEG_Worck/issues/41) |

**Gate:** W0-03E-A2C is WORKING. Progression requires independent evidence and the relevant owner approval; this board grants none.

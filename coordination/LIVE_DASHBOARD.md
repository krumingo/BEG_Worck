# BEG_WORK — CENTRAL LIVE DASHBOARD

> Status: canonical management projection, schema `beg.live-dashboard/v2`.
> Generated: `2026-10-10T21:46:25Z`.
> Source priority: Task Issue events → exact PR/review evidence → `CONTROL_STATE.json` → implementation waves.
> This is a **multi-track** projection. `CONTROL_STATE.json` remains the single W0 execution-control record; this dashboard does not overwrite it.

## Active tracks

| Track | Stage | State | Responsible / next | PR / head | Next action |
|---|---|---|---|---|---|
| W0-06D / C04 | CORRECTION_PREPARING | CHANGES_REQUESTED | CODEX / CODEX | #51 / `891fb537` | Bounded C05 only after required action-time confirmation |
| LIVE-OPS-01 / TASK-5A | COMPLETE | **STAGING_ACCEPTED** | CODEX / none | #53 / `e2a07ee` | No action; separate merge gate required |
| LIVE-OPS-01 / TASK-5B | ASSIGNMENT_READY | **DISPATCH_PENDING** | CODEX / CLAUDE | none / merged main `79af297` | Dispatch the published C01 assignment once |

The W0 track is preserved from `CONTROL_STATE.json` and remains unchanged. LIVE-OPS is an additional acceptance track, not a replacement for W0.

## LIVE-OPS-A status

- Contract: `v6-contract-freeze`
- Contract SHA-256: `489525BF36D69182CC0AED49EED2BA22C9883435021C4AF81241A3CB57700C3E`
- PR #53: draft, open, unmerged
- Exact head: `e2a07ee66d5d6d59a95f6b17bb90996917790193`
- Review verdict: **PASS_CANDIDATE**
- Acceptance: **ACCEPTED**
- Blockers: **none**
- Merge / deploy / production activation: **NO / NO / NO**

### Progress

No canonical percentage is calculated because no versioned denominator exists. The previously owner-reported **37%** is retained as context only; it is not recomputed or advanced.

### Timing

| Stage | Start | Finish | Duration |
|---|---|---|---:|
| Staging acceptance | 2026-10-10 19:41:41Z | 2026-10-10 20:16:19Z | **34m 38s** |
| Implementation | missing | missing | missing — not inferred |

### Test statistics

| Gate | Passed | Failed | Skipped | Exit / status |
|---|---:|---:|---:|---|
| Backend + disposable Real Mongo | 21 | 0 | 0 | **exit code 0**, 25.93s |
| Frontend focused smoke | 14 | 0 | 0 | exit code 0 |
| Live no-write probe | 1 | 0 | 0 | DB byte-equal; POST/PUT/PATCH/DELETE = 405 |
| Tenant read separation | 1 | 0 | 0 | PASS |
| Desktop UI | 1 | 0 | 0 | PASS |
| Phone 390×844 UI | 1 | 0 | 0 | PASS |
| Source/freshness | 1 | 0 | 0 | PASS |
| Incomplete projection warning | 1 | 0 | 0 | PASS |

Pytest originally stalled in its cache provider while trying to create a cache directory inside the managed read-only worktree. The verified command disables only that cache plugin; the original tests and PR head remain unchanged. Final result: `21 passed, 6 warnings in 25.93s`, exit code `0`.

### Correction loops

- Implementation: **1**
- Staging acceptance: **1**

### Staging access

- Scope: **private LAN only**
- Public exposure: **NO**
- The private address and disposable credential are intentionally not stored in the repository; they are handed directly to the owner.

## Preserved W0 state

- Task: W0-06D / C04
- State: **CHANGES_REQUESTED**
- Stage: **CORRECTION_PREPARING**
- PR #51 head: `891fb53718e72ba218f6fa29dd7098988037e153`
- C05: prepared, **NOT SENT**
- Waiting for: platform-required action-time confirmation for C05 UI Send
- Evidence: https://github.com/krumingo/BEG_Worck/pull/51#issuecomment-6095011636

Historical W0-06B timings and test counts from dashboard v1 are retained in `LIVE_DASHBOARD.json` under `preserved_legacy_evidence`; W0-06D append-only execution history remains in `CONTROL_STATE.json` and `CONTROL_BOARD.md`.

## LIVE-OPS-B status

- Task: `LIVE-OPS-01/TASK-5B`, cycle `C01`
- Scope: Material Requests safe-write core only
- Exact code baseline: merged `main` `79af297612f57c055bb7caef3f0c48493800d1b6`
- LIVE-OPS-A dependency: separate Draft PR #53; **not** included in this baseline
- Contract: `v6-contract-freeze`, SHA-256 `489525BF36D69182CC0AED49EED2BA22C9883435021C4AF81241A3CB57700C3E`
- Current stage: canonical read and preflight complete; exact CLAUDE assignment is published and pending one direct dispatch
- Assignment: https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6102528774
- Tests: backend, Real Mongo, frontend, phone/desktop and no-write-outside-domain are all **NOT RUN** for TASK 5B
- Merge / deploy / production activation: **NO / NO / NO**

## Evidence

- LIVE-OPS PASS_CANDIDATE: https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6101397109
- Initial staging result: https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6101638979
- Prior statistics/verdict: https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6101641941
- PR #53: https://github.com/krumingo/BEG_Worck/pull/53

## Dashboard rule

This central projection may show multiple concurrent tracks. It must never erase another track merely because a newer acceptance task is active. Percentages, durations, PASS and completion are shown only from explicit evidence; missing values remain missing.

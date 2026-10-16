# Issue #26 — C01 implementation notes

Task: `ISSUE-26` · Cycle: `C01` · Agent: `CLAUDE` (Implementer) · Branch:
`codex/issue-26-c01-dashboard` · Base: `64bef5f4b352030bad51efdea494e06181baa90b`

This document records what was built, what was actually verified, and what is
explicitly unverified. It is written for the independent Codex review that follows.

---

## 1. Scope and canonical authority

| Item | Value |
|---|---|
| Issue | [#26](https://github.com/krumingo/BEG_Worck/issues/26) — live side dashboard |
| Approved direction | Issue #26 `ARCHITECT_REVIEW` comment: WPF/Win32 + WebView2, right AppBar, 420–500 px, always-on-top without focus stealing, per-user autostart after separate approval, read-only GitHub client, deterministic evidence-based progress |
| Depends on | Issue #25 control protocol — `coordination/CONTROL_STATE.schema.json`, `CONTROL_STATE.json`, `CONTROL_BOARD.md`, `tools/control_engine.py` |
| CLAUDE.md | §2 rule 12 (dashboard is a projection, never a source of truth), §10 (AI rules — no model calls here), §16 (no second source of truth, no bypassing guards) |
| Wave | Tooling for the coordination loop; no Wave 0–4 runtime code is touched |

Nothing under `coordination/`, no locked FLOW/D decision, no runtime business logic,
no PR #20 and no W0-03C artefact is modified. The entire change is additive under
`tools/dashboard/`.

### The existing W0-03C / C02 snapshot stays BLOCKED

This work reads that snapshot; it does not advance it. The published state remains
`W0-03C / C02 / CODEX / BLOCKED`, `next_agent: KRUM`, correction cycle 1-of-1
exhausted. The dashboard renders exactly that, including the KRUM ACTION banner.

## 2. Base verification

`codex/issue-26-c01-dashboard` was confirmed to start from the exact merged
control-protocol commit before any edit:

```
$ git rev-parse HEAD
64bef5f4b352030bad51efdea494e06181baa90b
$ git rev-parse origin/codex/claude-queue
64bef5f4b352030bad51efdea494e06181baa90b
$ git merge-base --is-ancestor 64bef5f4… origin/codex/claude-queue && echo ancestor
ancestor
```

## 3. Windows implementation

### Placement — right AppBar with a real fallback

`Interop/AppBarHost.cs` registers a right-edge application desktop toolbar
(`SHAppBarMessage` `ABM_NEW` → `ABM_QUERYPOS` → `ABM_SETPOS`). Registering an AppBar
makes the shell shrink the desktop work area, so maximised Codex and Claude windows
stop at the panel instead of being covered — the behaviour Issue #26 asked for.

Registration can fail, and the code treats that as an ordinary outcome, not an
error: `TryRegister` returns false, `Mode` drops to `TopmostOverlay`, the panel is
placed inside the work area instead of reserving space, and a notice travels through
`DashboardHost.AddShellNotice` into the panel's own status banner. The operator sees
*"AppBar registration was refused; docking as a topmost overlay, so maximised windows
may run underneath the panel."* rather than silently losing the guarantee.

`ABM_REMOVE` runs on close. Skipping it would leave the user's desktop permanently
narrowed until logout.

### Always-on-top without stealing focus

Three separate mechanisms, because any one of them alone leaks focus:

1. `ShowActivated = false` — the panel appears at login/launch without activating.
2. Every placement call passes `SWP_NOACTIVATE`, including the ones triggered by
   monitor, DPI and work-area changes. `SWP_SHOWWINDOW` is never used on its own.
3. Refreshes do not navigate. The document is loaded once with `NavigateToString`;
   each update is a `PostWebMessageAsJson` that replaces the body's inner HTML and
   restores scroll position. Renavigating every 8 seconds would reset scroll and can
   move focus into the WebView.

`WS_EX_TOOLWINDOW` keeps the panel out of Alt+Tab and the taskbar. A deliberate user
click still activates it — that is wanted, so the panel can be scrolled and links
followed.

On `ABN_FULLSCREENAPP` the panel yields topmost and restores it afterwards, rather
than fighting a fullscreen application for z-order, which Windows does not reliably
allow anyway.

### Monitor, DPI and work-area changes

Handled in `DashboardWindow.WndProc`:

| Message | Cause | Response |
|---|---|---|
| AppBar callback `ABN_POSCHANGED`, `ABN_WINDOWARRANGE` | another AppBar or the taskbar moved | re-apply placement |
| AppBar callback `ABN_FULLSCREENAPP` | fullscreen app entered/left | toggle topmost, re-apply |
| `WM_DISPLAYCHANGE` | monitor added/removed, resolution change | re-apply placement |
| `WM_DPICHANGED` | panel moved to a display with different scaling | re-apply placement |
| `WM_SETTINGCHANGE` / `SPI_SETWORKAREA` | taskbar moved or resized | re-apply placement |
| `WM_WINDOWPOSCHANGED`, `WM_ACTIVATE` | — | notify the shell (`ABM_WINDOWPOSCHANGED`, `ABM_ACTIVATE`) |

The manifest declares `PerMonitorV2`. Placement is computed in physical pixels from
`GetMonitorInfo`, with the configured logical width converted through
`GetDpiForWindow`; round-tripping position through WPF device-independent units is
where off-by-a-few-pixels docking bugs come from. A configured `monitor_index` that
no longer exists falls back to the primary monitor.

### Single instance and manual start

`Hosting/SingleInstance.cs` — a `Local\` mutex plus a named event. A second launch
sets the event and exits; the running instance reveals itself. Two instances would
mean two AppBar registrations competing for the same edge and double the polling.

### Autostart — OFF, and not installed by this task

`DashboardSettings.Autostart` defaults to `false`.
`AutostartCoordinator.Apply(settings, installer)` acts only when the setting and the
observed installation disagree, so with the shipped defaults the decision is
`NoAction` and the Startup folder is never touched. Tests
`AutostartIsOffInTheShippedDefaults`, `AutostartIsOffWhenTheSettingsFileOmitsIt` and
`RunningWithDefaultsNeverTouchesTheStartupFolder` cover this.

Enabling it writes one `.lnk` to the per-user Startup folder — no elevation, no
service, no registry key, and the user can delete it without the app's cooperation.

## 4. Data and verification

### Sources, read-only

Six conditional GETs per round, issued serially:
`CONTROL_STATE.json`, `CONTROL_STATE.schema.json`, `CONTROL_BOARD.md`, the cited
`ACTIVE.md`, the cited review file, and PR metadata. Serial rather than parallel
because the sources are cross-checked against each other; an interleaved round could
compare a new state against an old board.

`ReadOnlyGuardHandler` throws `ReadOnlyViolationException` on any method other than
GET/HEAD and on any request carrying a body. The prohibition lives in the transport,
not at call sites, so a future code path cannot quietly acquire write access.

### `VALID` is treated as a claim, not as truth

`ControlStateVerifier` recomputes status from scratch and takes the worst of:

1. **Schema** — a port of the subset of JSON Schema that `tools/control_engine.py`
   implements, run against the schema file fetched from the same branch. Using a
   third-party engine would silently widen or narrow the producer's contract.
2. **Protocol invariants** — a port of `validate_state`: Work-ID composition,
   agent/role/pipeline agreement, `WORKING`/`REVIEW` ownership, `NOT_ACTIVE` purity,
   `requires_krum` reasons, PR evidence completeness, review-head and review-blob
   agreement, verdict-versus-state agreement, history uniqueness and cycle bounds,
   and progress determinism. The producer throws on the first violation; the
   dashboard collects all of them, because an operator needs every reason.
3. **Cited blob SHAs** — `ACTIVE.md` and the review file are re-hashed locally as Git
   blobs and compared to `source_refs`. Trusting the SHA the API reports would only
   prove the API is self-consistent; recomputing from the bytes proves the bytes on
   screen are the bytes the producer validated.
4. **Exact PR head** — live `head.sha` and `draft` versus the cited values. A head
   that has moved is `PR_HEAD_STALE`.
5. **Board cross-check** — `CONTROL_BOARD.md` is parsed only to compare. It can
   disagree (`BOARD_MISMATCH` → CONFLICT); it can never promote a value. Test
   `BoardThatDisagreesWithTheStateIsAConflictAndNeverOverridesIt` asserts the state
   still reads `BLOCKED` when the board claims `PASS`.

Additionally, a `SYNTHETIC_TEST` snapshot is reported as CONFLICT: it is not live
evidence regardless of how well-formed it is.

Severity precedence is `INVALID > CONFLICT > STALE > VALID`, so one STALE observation
cannot be rounded up.

### Refresh, staleness and offline

Normal cadence 8 s (clamped 5–10). Conditional requests via `If-None-Match`; a quiet
branch costs 304s. On failure, bounded exponential backoff 10 → 20 → 40 → 80 → 120 s,
capped; a server `Retry-After` is honoured but still capped, so the panel recovers on
its own within about two minutes without a restart.

The last snapshot that bound a state is kept and kept on screen — explicitly marked
`STALE` and `OFFLINE`, with the age of the last successful read — rather than the
panel blanking. Staleness is measured from wall-clock age of the last successful
read, not from the snapshot's `validated_at`: a genuinely blocked task can sit
untouched for days without the panel being out of date about it.

### Never an unverified PASS

`HeaderView.StateDisplay` renders the bare protocol state only when the round is
live-verified and online; otherwise it is suffixed `(UNVERIFIED)`, and the active
pipeline step is labelled `ACTIVE (UNVERIFIED)`. Test
`AnUnverifiedPassIsNeverPresentedAsALiveVerdict`.

### Agent cards come from `agent_states`, never from history

`DashboardProjection.BuildAgentCards` reads `agent_states` only. Test
`AgentCardsComeFromAgentStatesAndNeverFromHistory` asserts the contrast directly on
the published snapshot: the newest CLAUDE history event is a `HANDOFF`, while the
published `agent_states.CLAUDE` is `NOT_ACTIVE`, and the card shows `NOT_ACTIVE`.

If a card is missing from `agent_states` the document fails its schema, no state
binds, and the panel shows the empty state — two thirds of a picture would be worse
than none.

### Progress

Taken from the validated `progress` object and nothing else. `STAGE_ONLY` renders
stage and mode with the line *"No proven percentage. Stage and verified counts
only."* and **no bar and no number** (`NoProgressBarIsDrawnWhenNoPercentageIsProven`).
`EVIDENCE_COUNT` renders `completed / total` and the percent only after the invariant
check confirms `percent == 100 * completed / total`.

### Task list

Protocol v1 publishes the active task only, so the read-model proves exactly one row.
The panel says so in words rather than implying a longer list exists.

## 5. UI

Single column at the configured width, dark and light themes, no external resources,
CSP `default-src 'none'`. Sections: status banner → BEG_WORK header (Wave, Flow,
Task-ID, Cycle-ID, Work-ID, state, current/next, waiting-for, KRUM ACTION) → progress
→ five-stage pipeline → three agent cards → task list → recent evidence → sources.

Accessibility: the banner is `role="status" aria-live="polite"`; the status word is
always spelled out, never signalled by colour alone; the active pipeline step carries
`aria-current="step"`; the progress meter has an `aria-label`; tables use scoped
headers. Every value is HTML-escaped in one place, and an evidence URL that is not
http(s) is printed as text rather than linked.

## 6. Evidence

### Verified here

| What | Result |
|---|---|
| `dotnet build BegWork.Dashboard.CrossPlatform.slnf` | **succeeded**, 0 warnings (warnings-as-errors is on) |
| `dotnet test BegWork.Dashboard.CrossPlatform.slnf` | **100 passed, 0 failed, 0 skipped** |
| Verifier accepts the real published snapshot | `PublishedSnapshotWithMatchingSourcesVerifiesAsValid` — VALID with zero findings |
| Cited blob SHAs match the working tree | `ACTIVE.md` = `4bd78006…`, `REVIEWS/W0-03C.md` = `73073676…`, `CLAUDE.md` = `e91d3230…` (via `git hash-object`) |
| No GitHub writes | `AFullRefreshRoundIssuesOnlyReadRequests`, `AnyWriteMethodIsRefusedByTheTransport` (POST/PUT/PATCH/DELETE), `AGetCarryingABodyIsAlsoRefused` |
| Token containment | `TheTokenTravelsOnlyInTheRequestHeaderAndNeverIntoTheSnapshot`, plus `RedactingLogTests` |
| Windows shell syntax | Roslyn `CSharpSyntaxTree.ParseText` over all 9 files: **0 syntax errors** |
| `Microsoft.Web.WebView2` 1.0.2903.40 | present on nuget.org |

Test environment: Ubuntu 24.04, .NET SDK 8.0.131 (`dotnet-sdk-8.0` from the Ubuntu
archive), xUnit 2.9.2.

The tests use the repository's real `coordination/` artefacts as their baseline and
mutate a clone of them for negative cases, so "the published snapshot verifies" is
evidence about the actual read-model rather than about a fixture that drifted.

### Offline layout previews — NOT a Windows run

`docs/preview/*.png` are rendered by `BegWork.Dashboard.Preview` and screenshotted
with headless Chromium at 460 px on Linux. They show the real renderer's output for
the real published snapshot, and they prove the layout and the state matrix. They
prove nothing about WPF, WebView2, AppBar docking, topmost behaviour or focus.

Each preview page carries that statement inside the panel's own status banner,
through the same shell-notice channel the Windows shell uses for AppBar fallbacks,
so a page cannot be mistaken for a live verification.

| File | Shows |
|---|---|
| `preview/verified.png` | VALID / LIVE VERIFIED, BLOCKED, KRUM ACTION REQUIRED, agent cards, pipeline on step 4 |
| `preview/stale-offline.png` | STALE + OFFLINE, three findings, `BLOCKED (UNVERIFIED)`, `ACTIVE (UNVERIFIED)` |
| `preview/conflict.png` | CONFLICT from a board that disagrees with the state |
| `preview/invalid.png` | INVALID, no projected state, explicit empty state |

Reproduce:

```bash
dotnet run --project src/BegWork.Dashboard.Preview -- <repo-root> <out-dir>
```

### UNKNOWN — no Windows host was available

The session that produced this runs on Linux, and the Ubuntu-packaged .NET SDK ships
without `Microsoft.NET.Sdk.WindowsDesktop`, so the WPF project cannot be built here
(`dotnet build src/BegWork.Dashboard.Win` fails with MSB4019 on the missing
WindowsDesktop targets; `-p:EnableWindowsTargeting=true` does not help, the targets
file is genuinely absent). Egress to `builds.dotnet.microsoft.com` is denied by the
environment's network policy, so the official SDK could not be installed either.

Therefore, and stated plainly rather than estimated:

- **Windows compilation of `BegWork.Dashboard.Win`: UNKNOWN.** Syntax parses clean;
  semantic compilation, WPF and WebView2 API agreement are unverified.
- **Windows runtime behaviour: UNKNOWN.** AppBar registration, work-area reservation,
  topmost, no-focus-steal, DPI and monitor-change handling, single instance, WebView2
  hosting and the message-push update path have not been executed.
- **Real Windows screenshots: UNKNOWN.** None exist. The PNGs in `docs/preview/` are
  Linux/Chromium renders of the HTML and are labelled as such.
- **Process resource measurements (working set, CPU, handles): UNKNOWN.** No figure is
  offered. Estimating one would be fabrication.

The first task of a Windows cycle is to run the build and the manual checklist below
and replace these UNKNOWNs with measurements.

## 7. Windows acceptance checklist for the next cycle

1. `dotnet build BegWork.Dashboard.sln -c Release` — expect 0 warnings.
2. Launch; confirm the panel docks right, spans the work area, and that a maximised
   window stops at its left edge (AppBar reservation).
3. With focus in another window, watch across several refresh cycles: the caret must
   not move and the foreground window must not change.
4. Move the panel's monitor, change resolution, change scaling, move the taskbar,
   plug and unplug a display — placement must follow each time.
5. Force AppBar failure (`reserve_desktop_space: false`) and confirm the overlay
   fallback plus the banner notice.
6. Launch a second copy; confirm no second panel and that the first reveals itself.
7. Confirm the Startup folder contains no shortcut after any of the above.
8. Measure working set, CPU over an idle hour, and handle count; record them.
9. Disconnect the network; confirm STALE + OFFLINE with the cached snapshot and the
   backoff sequence in the log; reconnect and confirm recovery to normal cadence.
10. Confirm no token appears anywhere in `%APPDATA%\BEG_Work\dashboard\logs`.

## 8. Known gaps, deliberately out of C01 scope

- No hide/show global hotkey and no tray icon. Escape hides and Ctrl+Shift+Q exits,
  both only while the panel is focused; relaunching reveals it. Issue #26 asks for a
  hotkey after a conflict check plus a tray fallback — that is C02 work.
- No settings UI. `settings.json` is edited by hand; there is no in-app autostart
  toggle.
- The board cross-check compares the banner fields only, not the whole rendered
  document. A full re-render comparison would duplicate `render_board` in C#; the
  bounded check catches the disagreements that matter without a second renderer to
  keep in sync.
- No installer or packaging.
- No CI workflow. The repository has no `.github/workflows`, and adding one is
  outside this task.
- `control_state_commit_sha` is not verified. Per `CONTROL_BOARD.md` it names the
  *previous* published state commit and cannot self-reference, so there is nothing to
  compare it against without extra history reads.

## 9. Compliance

- No file under `coordination/` is touched; `git diff --stat` is confined to
  `tools/dashboard/`.
- No locked FLOW/D decision, no runtime business logic, no PR #20, no W0-03C artefact.
- No merge, no deploy, no autostart activation, no production/NAS/Atlas access, no
  secret committed.
- No C03 and no next task is claimed. W0-03C / C02 remains BLOCKED awaiting Krum.
- No Implementation Gate PASS is claimed for anything.

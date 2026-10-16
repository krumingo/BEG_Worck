# BEG_WORK side dashboard — Issue #26, cycle C01

A Windows 11 side panel that shows the ChatGPT → Codex → Claude control state,
read-only, from the coordination branch.

**This is a bounded C01 implementation. It is not merged, not deployed, and not
installed for autostart. It writes nothing anywhere.**

---

## What it is, and what it is not

| | |
|---|---|
| Reads | `coordination/CONTROL_STATE.json`, `CONTROL_STATE.schema.json`, `CONTROL_BOARD.md`, `ACTIVE.md`, `REVIEWS/*`, PR metadata — all on `codex/claude-queue` |
| Writes | nothing — the HTTP transport refuses any non-GET (`ReadOnlyGuardHandler`) |
| Authority | none; it is a projection, per CLAUDE.md rule 12 |
| LLM usage | none; there is no model call anywhere in the code |
| Autostart | a per-user setting, **off by default**, never enabled implicitly |

The dashboard never presents an unverified value as live. `VALID` in the published
document is treated as a claim and re-checked against the bytes on the branch; the
status shown is the worst of everything observed.

## Layout

```
tools/dashboard/
├── BegWork.Dashboard.sln                  all four projects (build on Windows)
├── BegWork.Dashboard.CrossPlatform.slnf   core + preview + tests (build anywhere)
├── src/
│   ├── BegWork.Dashboard.Core/            net8.0 — read-model, verification, projection, rendering
│   ├── BegWork.Dashboard.Win/             net8.0-windows — WPF/Win32 shell + WebView2
│   └── BegWork.Dashboard.Preview/         net8.0 — renders the HTML offline for review
├── tests/BegWork.Dashboard.Core.Tests/    net8.0 — xUnit
└── docs/
    ├── ISSUE-26-C01-IMPLEMENTATION.md     design, evidence, limitations
    └── preview/                           offline layout screenshots (NOT a Windows run)
```

Everything that can be tested lives in `Core`, which targets plain `net8.0`. The
Windows shell is the thin part: window placement, focus discipline and the WebView
host. That split is what lets the verification and projection rules be tested on a
Linux CI host.

## Build and run

Cross-platform (core, preview, tests) — works on Linux, macOS and Windows:

```bash
cd tools/dashboard
dotnet build BegWork.Dashboard.CrossPlatform.slnf
dotnet test  BegWork.Dashboard.CrossPlatform.slnf
```

Render the panel's HTML offline, with no network and no Windows:

```bash
dotnet run --project src/BegWork.Dashboard.Preview -- <repo-root> <output-dir>
# writes preview-verified.html, preview-stale-offline.html, preview-conflict.html,
# preview-invalid.html, preview-no-snapshot.html
```

Windows shell — **requires Windows 11 with the .NET 8 SDK and the Evergreen
WebView2 Runtime**:

```powershell
cd tools\dashboard
dotnet build BegWork.Dashboard.sln -c Release
dotnet run --project src\BegWork.Dashboard.Win -c Release
```

The panel starts manually. A second launch does not start a second panel: it
signals the running one to reveal itself and exits.

## Configuration

`%APPDATA%\BEG_Work\dashboard\settings.json`; every key is optional.

| Key | Default | Notes |
|---|---|---|
| `repository` | `krumingo/BEG_Worck` | must match the snapshot, or the panel reports CONFLICT |
| `branch` | `codex/claude-queue` | same |
| `width` | `460` | clamped to 420–500 |
| `refresh_seconds` | `8` | clamped to 5–10 |
| `autostart` | `false` | **off by default**; see below |
| `monitor_index` | `0` | out of range falls back to the primary monitor |
| `reserve_desktop_space` | `true` | register an AppBar; `false` docks as a topmost overlay |
| `recent_activity_count` | `6` | clamped to 1–25 |
| `stale_after_seconds` | `45` | never less than two refresh cadences |

A GitHub token is read from `BEGWORK_DASHBOARD_GITHUB_TOKEN`, `GITHUB_TOKEN` or
`GH_TOKEN`. It is attached per request and is never written to a model, the WebView
document or the log; the log sink redacts it and the known token shapes regardless.
Public reads work without a token, at a lower rate limit.

## Autostart

Off by default and not installed by this task. Turning it on writes one shortcut to
the per-user Startup folder — no elevation, no service, no registry key. Setting
`autostart` back to `false` removes it. `AutostartCoordinator` acts only when the
setting and the observed installation disagree, so running the dashboard with the
shipped defaults touches nothing.

## Keyboard

The panel is frameless, has no taskbar button and no Alt+Tab entry, so these keys
work only while it is focused, i.e. after you click it:

- **Escape** — hide. Launch the executable again to bring it back.
- **Ctrl+Shift+Q** — exit, removing the AppBar reservation.

## Known gaps

See `docs/ISSUE-26-C01-IMPLEMENTATION.md` — in particular, the Windows shell has
**not been compiled or run** in the cycle that produced it.

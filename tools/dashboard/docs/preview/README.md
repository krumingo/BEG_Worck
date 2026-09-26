# Offline layout previews — NOT a Windows run

These PNGs were produced by `BegWork.Dashboard.Preview` and captured with headless
Chromium at 460 px on Linux. They show the real `DashboardHtmlRenderer` output for
the real published `coordination/` snapshot.

**They prove the layout and the STALE / CONFLICT / INVALID state matrix. They prove
nothing about WPF, WebView2, AppBar docking, always-on-top or focus behaviour.** No
Windows host was available in the cycle that produced them; see
`../ISSUE-26-C01-IMPLEMENTATION.md` §6 for what is UNKNOWN.

Each page states this inside the panel's own status banner, so a screenshot cannot
be mistaken for a live verification.

| File | State shown |
|---|---|
| `verified.png` | VALID / LIVE VERIFIED — W0-03C / C02 / CODEX / BLOCKED, KRUM ACTION REQUIRED |
| `stale-offline.png` | STALE + OFFLINE — cached snapshot, three findings, `BLOCKED (UNVERIFIED)` |
| `conflict.png` | CONFLICT — CONTROL_BOARD.md disagrees with CONTROL_STATE.json |
| `invalid.png` | INVALID — schema failure, no projected state, explicit empty state |

Reproduce from the repository root:

```bash
cd tools/dashboard
dotnet run --project src/BegWork.Dashboard.Preview -- ../.. /tmp/beg-preview
```

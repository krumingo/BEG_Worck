# ISSUE-26 / C02 — Synology-hosted web dashboard: implementation notes

```text
BEG_WORK
TASK: ISSUE-26
CYCLE: C02
AGENT: CLAUDE
ROLE: IMPLEMENTER
STATE: HANDOFF
NEXT: CODEX
WAITING_FOR: Independent Codex review of the exact Draft PR head
```

Scope: the Synology-hosted web direction only. The Windows/WPF direction of PR #28 is
superseded and none of its shell is carried forward. **W0-03C / C02 remains BLOCKED
awaiting Krum**; nothing here advances it, and this dashboard only reads its snapshot.

---

## 1. Architecture decision

Issue #26 suggests React + TypeScript + Vite with a small backend, and invites a simpler
stack if it reduces moving parts. The chosen stack is simpler in both halves:

| Layer | Chosen | Alternative considered |
|---|---|---|
| Backend | Python 3.11, standard library only | ASP.NET Core host reusing PR #28's C# `Core` |
| Frontend | Plain HTML/CSS/JS, no build step | React + TypeScript + Vite |
| Image | `python:3.11-alpine`, zero pip installs | `mcr.microsoft.com/dotnet/aspnet:8.0` |

Four reasons, in order of weight.

**1. The canonical validator is already Python.** `tools/control_engine.py` is what Codex
validates and renders with. This dashboard's schema, invariant and board logic is an
adaptation of that file, and `tests/test_canonical_engine.py` imports the canonical
engine and pins the relationship: soundness (never rejects what the engine accepts),
completeness (never accepts what the engine rejects), severity agreement on single-defect
mutations, and byte-identity of the board rendering across five inputs. PR #28's C#
`ControlStateInvariants` and `ControlStateSchemaValidator` are a *port* of the same
Python, and a port into another language cannot make that comparison — it can only be
re-read by a human and hoped to still match. CLAUDE.md §2 rule 12 says a projection must
not become a second source of truth; an unpinned re-implementation of the producer's
validator is exactly that risk. This is the decisive reason.

**2. It makes the evidence this cycle was asked for actually obtainable.** `dotnet` is not
installed in the implementation environment and the SDK download host is outside the
network policy. An ASP.NET Core choice would have reproduced PR #28's exact failure mode
— UNKNOWN build, UNKNOWN tests, no real screenshots — which is what its review rejected.
Python 3.11 and Chromium are both present, so the suite runs, the browser renders and the
footprint is measured.

**3. No bundler is the strongest possible form of "keep the token server-side".** With no
build step there is nothing that *could* inline a secret into a browser asset, and the
browser never contacts GitHub at all: it fetches one already-sanitised JSON document from
this host. The claim is structural rather than a convention to be maintained.

**4. Footprint.** The runtime image is the base image plus the source; there is no
dependency tree to track for advisories. Measured at 26.3 MiB peak RSS (§5).

The cost of this decision is that PR #28's 100 C# tests are not carried forward as code.
They were re-expressed as 189 Python tests covering the same properties plus the ones its
review raised.

---

## 2. Reuse map against PR #28

Analysed at PR #28 head `9b6eb25a696217d68839d643af8ec566707f3869` (55 files, +6522/−0,
all under `tools/dashboard/`), together with the Codex `CHANGES_REQUESTED` review.

### Reused as designs, re-expressed in Python

| From PR #28 | Here | What carried over |
|---|---|---|
| `Validation/ControlStateVerifier.cs` | `app/verify.py` | The layered worst-of verdict; treating persisted `VALID` as a claim; per-check finding codes |
| `Validation/ControlStateSchemaValidator.cs` | `app/schema.py` | Checking against the schema fetched from the same branch, rather than one baked into the build |
| `Validation/ControlStateInvariants.cs` | `app/invariants.py` | Collecting *all* findings instead of raising on the first |
| `Validation/VerificationModel.cs` | `app/status.py` | The `INVALID > CONFLICT > STALE > VALID` lattice and the merge-of-findings model |
| `Sources/GitObjectId.cs` | `app/gitblob.py` | Re-hashing fetched bytes as a Git blob instead of trusting the API's reported SHA |
| `Sources/ReadOnlyGuardHandler.cs` | `app/github.py` | Putting the write prohibition in the transport so no call site can bypass it |
| `Refresh/BackoffPolicy.cs` | `app/refresh.py` | Bounded 10 → 20 → 40 → 80 → 120 s, `Retry-After` honoured but capped |
| `Logging/RedactingLog.cs` | `app/redact.py` | Redacting the configured value *and* known credential shapes |
| `Rendering/DashboardHtmlRenderer.cs` | `static/app.css`, `static/app.js` | Status colour families, agent-card composition, evidence and history layout, the "snapshot only" caveat |
| Staleness semantics | `app/refresh.py` | Measuring age from the last successful read, not from `validated_at` |
| Its test *properties* | `tests/` | Cards from `agent_states` not history; no invented percentage; read-only round; stale PR head; conflict/invalid matrix |

### Adapted, with a deliberate change

| Area | PR #28 | Here | Why |
|---|---|---|---|
| Board cross-check | Banner fields only — its own notes list "not a full re-render" as a known gap | Full re-render compared byte-for-byte (`app/board.py`) | The canonical engine asserts exact equality (`validate_board`). Banner-only comparison lets a board drift in its history table or evidence list and still pass. Cheap to close here because the canonical renderer is Python and can be pinned to it. |
| Test fixtures | `CoordinationFixture.ReadRepositoryFile` reads working-tree bytes | `tests/conftest.py:git_blob` reads `git cat-file blob` | §3 |
| Synthetic snapshots | Reported as CONFLICT | Same, and the divergence from the canonical engine is asserted as deliberate in a named test | So a later reader cannot mistake a deliberate hardening for drift |
| Staleness and connectivity | Both surfaced as "STALE / OFFLINE" | Two independent indicators: `Status` for the protocol, `Link` for the connection | A network outage must not read as a protocol conflict, and a real CONFLICT must not be excused as a blip |

### Discarded

| Discarded | Why |
|---|---|
| `BegWork.Dashboard.Win` entirely — WPF, Win32 `SHAppBarMessage`, AppBar docking, topmost/no-activate, `WS_EX_TOOLWINDOW`, DPI and monitor handling, `app.manifest` | Issue #26 supersedes the Windows-native direction. A browser page has no AppBar to register. |
| `StartupFolderAutostartInstaller`, `SingleInstance`, `SettingsStore` | Windows autostart is out of scope and explicitly forbidden. The container's `restart: unless-stopped` covers "runs all day"; a single instance is the container. |
| WebView2 hosting and `PostWebMessageAsJson` refresh | A browser polls `/api/state`; there is no embedded webview to message. |
| The `.sln` / `.slnf` / `Directory.Build.props` build system and the Preview project | No .NET toolchain remains. The "render offline for review" need is met by the browser tests, which screenshot the real page. |
| `AutostartCoordinator` | Same as autostart. |
| PR #28's `docs/preview/*.png` | They are headless renders of the *Windows panel* HTML at 460 px. The layout here is different, and §5's screenshots are of this UI. |

**Nothing was cherry-picked wholesale.** No file from PR #28 was copied. The Python is
newly written against the canonical engine and the two reviews.

---

## 3. The CRLF fixture defect from PR #28, and how it is avoided

Codex finding 2 on PR #28: on a Windows checkout with `core.autocrlf=true`,
`dotnet test` gave 92 passed / 8 failed. `PublishedSnapshotWithMatchingSourcesVerifiesAsValid`
and seven other expected-VALID cases became STALE, and one test observed blob
`77d97a0d…` where CONTROL_STATE cites `4bd78006…`.

**Root cause, confirmed here.** The committed objects were never wrong. Checked against
the current branch:

```
$ git cat-file blob HEAD:coordination/ACTIVE.md | grep -c $'\r'
0
$ git rev-parse HEAD:coordination/ACTIVE.md
4bd7800657b9c7d60eab5b5b7560ecbfe46540da        # exactly what CONTROL_STATE cites
```

The committed blob is LF and hashes to the cited SHA. `core.autocrlf=true` rewrites LF to
CRLF **on checkout**, which changes the bytes in the working tree and therefore changes
their blob SHA. PR #28's fixture read the working tree, so it was hashing something that
was never committed.

**The fix is in the fixture, not the check.** `tests/conftest.py:git_blob()` obtains
source bytes with `git cat-file blob <ref>:<path>`, which returns the stored object
regardless of platform or `core.autocrlf`, and which is also exactly what the GitHub
contents API serves in production.

**Production verification is not weakened.** `app/verify.py:_check_blob` still requires an
exact match and still fails closed. `tests/test_blob_and_pr.py::test_a_crlf_converted_checkout_would_not_match`
feeds a CRLF-converted copy of `ACTIVE.md` through a full round and asserts the result is
STALE with `SOURCE_BLOB_MISMATCH` — so line-ending tolerance was **not** added as a
shortcut, and a tampered source cannot be smuggled past the check by adding carriage
returns.

---

## 4. Defects found during implementation

Each was found by a test that was written to assert a requirement, not by inspection.

| Defect | Symptom | Fix |
|---|---|---|
| `Status.VALID == 0`, so the best status was falsy | `/healthz` reported `control_state_status: null` whenever the state was VALID | Renumbered the enum from 1 so no member is falsy; kept the ordering `max()` relies on (`app/status.py`) |
| `Verdict.__len__` made a clean verdict falsy | `if verdict:` read as "no verdict" for a snapshot that passed every check, so a VALID round could never render as verified | Added an explicit `__bool__`; changed the call sites to test `is not None` (`app/status.py`, `app/projection.py`) |
| Token leaked into `/api/state` | The logger's redaction covered log output only. A GitHub 401 body quoting the `Authorization` header reached the browser verbatim through `last_error` | Redact at the point of storage and again in the projection (`app/refresh.py`, `app/verify.py`, `app/projection.py`); regression test in `test_server.py` |
| `server.shutdown()` called from the signal handler | Deadlock: the handler runs on the thread inside `serve_forever()`, which cannot exit until the handler returns. `docker stop` would wait 10 s and then SIGKILL | Run the shutdown on a separate thread (`app/__main__.py`); regression test asserts SIGTERM exits rc=0 in under 8 s (measured: 1.52 s) |
| Auth-header redaction stopped at the first word | `Authorization: Bearer <token>` masked only `Bearer` | Mask the remainder of the line (`app/redact.py`) |

---

## 5. Evidence

Environment: Linux 6.18, Python 3.11.15, pytest 9.1.1, Playwright 1.63.0 driving
Chromium 1194 at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.

### Tests

```bash
cd tools/web-dashboard
python3 -m pytest tests/ -q
```

**189 passed in 21.68s.** Coverage by file:

| File | Tests | Covers |
|---|---|---|
| `test_canonical_engine.py` | 41 | Drift against `tools/control_engine.py`: soundness, completeness, severity agreement on 16 single-defect mutations, board byte-identity, the deliberate SYNTHETIC_TEST divergence |
| `test_blob_and_pr.py` | 17 | Cited blob match and mismatch, CRLF rejection, unreadable and mis-pathed sources, transport integrity, oversized blob, moved PR head, draft and merged mismatch, repo/branch mismatch, unparsable state |
| `test_status_matrix.py` | 19 | VALID/STALE/CONFLICT/INVALID end to end, worst-of precedence, forged PASS never promoted, producer `VALID` claim insufficient, STAGE_ONLY, deterministic and non-deterministic percentages, aged snapshot |
| `test_readonly.py` | 26 | Every non-read method refused, GET-with-body refused, guard wraps the production transport, a full round is six GETs to six expected URLs, token reaches GitHub but not the projection, redaction cases |
| `test_refresh.py` | 22 | Cadence clamping, `If-None-Match` and 304 byte reuse, ETag invalidation, backoff escalation and cap, `Retry-After`, recovery, offline cache retention, OFFLINE vs STALE separation, loop thread lifecycle |
| `test_projection.py` | 22 | Header fields, migrated cycle label, KRUM action, three agent cards from `agent_states` not history, five-step pipeline, task area, evidence links with cited *and* observed identity, history ordering |
| `test_server.py` | 23 | `/api/state`, `/healthz` liveness under outage, every declared static asset served, allowlist routing and 404s, no source reachable, security headers, no token in any response, HEAD, SIGTERM |
| `test_ui.py` | 19 | Real Chromium: rendering, agent cards, pipeline, STAGE_ONLY drawing no bar, evidence links, each status on screen, OFFLINE, forged PASS, unavailable state, three form factors with no horizontal overflow, both themes, PWA manifest and icons |

### A live read against real GitHub

Anonymous, unauthenticated, read-only, against `codex/claude-queue`:

```
LIVE GITHUB ROUND
  requests: 6
  status  : VALID
  findings: []
  task    : W0-03C BLOCKED
  active blob observed: 4bd7800657b9c7d60eab5b5b7560ecbfe46540da
  PR head observed   : ed588e9420e241f58c14146de6f0c890b38b3743
  PR draft observed  : True
```

The dashboard independently re-derived, from live GitHub, that the cited `ACTIVE.md` blob
matches, that PR #20's exact head is still `ed588e94…` and that it is still a Draft. This
also independently corroborates that W0-03C / C02 is still BLOCKED.

### Screenshots — real browser renderings

In `docs/screenshots/`. Every one is a Chromium screenshot of this UI served by the real
server; the tests that capture them also assert their contents.

| File | What it shows |
|---|---|
| `live-desktop.png`, `live-tablet.png`, `live-phone.png` | **Live GitHub data**, 1440 / 834 / 390 px |
| `layout-desktop.png`, `layout-tablet.png`, `layout-phone.png` | The same three widths, asserted for zero horizontal overflow and card arrangement |
| `status-valid.png`, `status-stale.png`, `status-conflict.png`, `status-invalid.png` | Each control-state status |
| `link-offline.png` | OFFLINE with the cached snapshot still shown and dated |
| `forged-pass-unverified.png` | A forged `PASS` rendering as `PASS (UNVERIFIED)` |
| `state-unavailable.png` | First-round failure: `CONTROL STATE NOT AVAILABLE` |
| `theme-dark.png`, `theme-light.png` | Both colour schemes |

### Resource measurement

```bash
python3 scripts/measure_resources.py --seconds 60
```

Against live GitHub, 60 s window, 120 `/api/state` requests served, 5 refresh rounds:

| Metric | Value |
|---|---|
| Peak RSS (`VmHWM`) | **26.3 MiB** |
| Mean RSS | 26.3 MiB |
| CPU | **0.96 s over 60.3 s = 1.59 % of one core** |
| Link / status at end | ONLINE / VALID |

This is the **application process on the host**, not a container measurement — see §6.
The compose memory limit is set to 128 MiB, comfortably above the measured peak so a slow
GitHub response cannot cause an OOM kill.

---

## 6. Limitations — stated, not estimated

- **Container build and container-measured resources: UNKNOWN.** `docker build` could not
  run here: `python:3.11-alpine` returned HTTP 429 from Docker Hub, and the mirrors tried
  (`public.ecr.aws`, `ghcr.io`, `quay.io`) had their blob hosts refused by the
  environment's network policy. The Dockerfile and compose file are therefore
  **unvalidated by execution**. The figures in §5 are for the same Python process the
  container entrypoint runs, measured on the host; a container adds image size on disk
  and a small namespace overhead, neither of which is claimed here.
- **Synology runtime: UNKNOWN.** Nothing has been deployed to a NAS. Container Manager
  behaviour, DSM reverse proxy, restart-on-boot and PWA installation from the NAS are
  documented but unverified. §7 is the acceptance checklist that would close this.
- **PWA installation: partially verified.** The manifest, its icon set and the service
  worker's cache policy are asserted, and every icon the manifest names is confirmed to
  be served. An actual install to a home screen was not performed.
- **The live round is anonymous.** Authenticated reads were not exercised against real
  GitHub; the `Authorization` header path is covered by tests against the fake transport.
  Anonymous reads are limited to 60/hour, which is why a token is recommended in
  production.
- **No `docker stop` test.** SIGTERM handling is verified directly against the process
  (rc=0 in 1.52 s), which is what `docker stop` sends, but not through Docker itself.
- **Accessibility is not audited.** Colour is deliberately never the sole status carrier
  and the markup uses lists and definition lists, but no screen-reader or contrast audit
  was performed.
- **`control_state_commit_sha` is not verified.** Per `CONTROL_BOARD.md` it names the
  *previous* published state commit and cannot self-reference; the dashboard displays it
  with that explanation rather than checking it.

---

## 7. Synology acceptance checklist

To replace the UNKNOWNs in §6. None of this is authorised by this cycle.

1. Copy `tools/web-dashboard/` to the NAS; create `.env` from `.env.example` with a
   read-only fine-grained token.
2. Container Manager → Project → Create from the existing `docker-compose.yml`. Confirm
   the build completes and the image is `begwork-dashboard:0.2.0-c02`.
3. `docker stats begwork-dashboard` for 5 minutes at rest; record CPU % and MEM USAGE.
   Compare against the 26.3 MiB / 1.6 % measured on the host.
4. `curl http://<nas>:8787/healthz` → `200`, `link: ONLINE`, `control_state_status: VALID`.
5. Open `http://<nas>:8787/` on the Windows browser, the iPad and a phone. Confirm three
   cards abreast, then 2+1, then single column, with no horizontal scrolling.
6. Install as a PWA on the iPad and on the desktop; confirm it opens standalone and that
   a refresh still reaches `/api/state` (not a cached copy).
7. Pull the NAS network cable or block egress; confirm the panel goes `OFFLINE`, keeps the
   last snapshot on screen with a growing age, and recovers by itself within ~2 minutes
   of restoration without a restart.
8. `docker stop begwork-dashboard`; confirm it stops in under 10 s without SIGKILL.
9. Reboot the NAS; confirm the container returns on its own.
10. Confirm, from inside the container and from the browser's devtools, that the token
    appears in neither the served assets nor `docker logs`.

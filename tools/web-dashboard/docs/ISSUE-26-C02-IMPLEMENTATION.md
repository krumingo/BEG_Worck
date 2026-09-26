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
They were re-expressed as 229 Python tests covering the same properties plus the ones its
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
| `Refresh/BackoffPolicy.cs` | `app/refresh.py` | Bounded 10 → 20 → 40 → 80 → 120 s, `Retry-After` honoured but capped (wired through the Refresher in the C02 correction — see §4a) |
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

## 4a. C02 correction cycle — the three findings from the independent review

Codex reviewed head `5770ab8c88452bd5793dc0f79dbb595ce872f1ce` and returned
CHANGES_REQUESTED with three findings. All three were reproduced here before being
fixed, and each now has a regression suite. No fail-closed verification was relaxed.

### 1. A traceback could carry the configured token into the process log

`app/refresh.py` logs an unexpected round failure with `LOGGER.exception(...)`, which
attaches the live exception as `exc_info`. The *formatter* renders that traceback long
after every filter has run, so `RedactingFilter` — which sanitised only `msg` and `args`
— never saw it. Reproduced: an injected `ValueError("unexpected failure carrying
<token>")` gave `token_in_log = True` while `token_in_last_error = False`, exactly as
reported. The browser was protected; the log was not.

**Fix** (`app/redact.py`), in three layers:

* `RedactingFilter` now *flattens* the record: it renders the message (applying `args`),
  formats the traceback and any `stack_info`, redacts the three together into `msg`, and
  clears `exc_info` / `exc_text` / `stack_info` so no later formatter can re-render the
  originals. It is idempotent, which matters because it is installed on both the logger
  and its handlers.
* `RedactingFormatter` redacts its own complete output, covering a handler attached by
  embedding code or a future change that drops the filter.
* `install_excepthooks()` sets `sys.excepthook` and `threading.excepthook`, because an
  exception that escapes a thread bypasses `logging` entirely and is written straight to
  stderr by the interpreter — which in a container is a process log like any other.

The diagnostic is not lost: the traceback still appears, with the credential replaced by
`***REDACTED***`. Verified after the fix: `token_in_log = False`, `Traceback` present,
`***REDACTED***` present.

### 2. Unverified numeric progress reached the browser

The verifier correctly marked `EVIDENCE_COUNT {completed: 3, total: 8, percent: 90}`
INVALID with `PROGRESS_NOT_DETERMINISTIC` — `100*3//8` is 37, not 90 — but
`app/projection.py` forwarded `percent: 90` whenever the mode was not `STAGE_ONLY`, and
`static/app.js` drew "3 of 8 verified milestones · 90%" with a 90%-full bar. A number the
verifier has just rejected is not evidence of anything, and putting it on a wall display
is the invented progress Issue #26 forbids.

**Fix**, enforced in both places so neither alone is load-bearing:

* `app/projection.py` emits counts and a percentage only when `is_verified` **and** the
  mode is `EVIDENCE_COUNT`. Otherwise they are `None`, `numbers_withheld` is `true`, and
  `withheld_reason` states in words why. The stage is kept and `stage_verified` marks it.
* `static/app.js` draws a number or a bar only when the server permits it, never
  recomputing or inferring one, and labels the stage chip `UNVERIFIED` with a dashed
  amber border — a cue that does not depend on colour alone.

An arithmetically *correct* count is withheld too when the round did not verify: correct
arithmetic over unverified bytes still proves nothing. A verified `EVIDENCE_COUNT` is
unaffected and shows its justified figure; `STAGE_ONLY` remains stage-only. A cached
snapshot that verified when it was read keeps its numbers while `OFFLINE`, with its age
on screen — withholding there would destroy information rather than protect anyone.

### 3. `Retry-After` was parsed and then discarded

`app/github.py` populated `TransportError.retry_after`, `BackoffPolicy.next()` accepted
it and `README.md` promised it was honoured — but `Refresher._delay_locked` passed
`retry_after=None`. Reproduced: a 429 with `retry_after=45` scheduled the next attempt
after **10.0 s**. A unit test of the policy could not catch this, because the policy was
never the broken part.

**Fix** (`app/refresh.py`): the `Refresher` stores the hint from the failing round
(`_last_retry_after`), clears it on success and on an unexpected non-transport
exception, exposes it as `last_retry_after`, and passes it to the policy. Bounded backoff
is retained — the hint may extend the wait, never shorten it, and is still capped at
`backoff_maximum_seconds`. Measured after the fix: 45 → 45.0 s; 3600 → 120.0 s (capped);
5 → 10.0 s (below the step, ignored); no hint → 10.0 s.

### Not changed

Codex also observed that `test_sigterm_shuts_the_process_down_promptly` fails on Windows,
because `subprocess.send_signal(SIGTERM)` there maps to `TerminateProcess` and the handler
never runs (exit code 1, not 0). Codex classified this as a test-portability issue and did
not list it among the required corrections, and this correction cycle was authorised for
those three only, so it is left alone. The one-line change, if a future cycle authorises
it, is a `@pytest.mark.skipif(os.name != "posix", ...)` guard on that single test; the
property it asserts holds on the Linux container the image actually runs on, where the
measured result is rc=0 in 1.52 s.

---

## 4b. C02 combined cycle — acceptance corrections and the variant-2 redesign

Authorised by ARCHITECT AUTHORISATION and ARCHITECT UPDATE on PR #29. Two tracks were
delivered together; a third, Synology acceptance, could not be executed from the
implementation environment and is recorded as PENDING in §4c rather than simulated.

### Track 1 — acceptance corrections

**A. Mobile overflow.** Acceptance found the document widening to roughly 575 px at
390 px: a long GitHub error string and the footer had nothing to break on. The content
that causes it is what this dashboard is full of — 40-character SHAs, long API URLs and
error bodies quoted verbatim.

The redesign rebuilt the stylesheet with the discipline built in rather than patched
on: `overflow-wrap: anywhere` on every text-bearing element, `min-width: 0` on every
grid and flex child (the default `auto` minimum is what actually lets a child push a
container wider), `overflow-x: hidden` on the body as a backstop, and the one element
that genuinely cannot fit — the seven-column task table — scrolling inside its own
wrapper rather than scrolling the page.

`tests/test_mobile_overflow.py` (16 cases) measures
`documentElement.scrollWidth - window.innerWidth` at 320, 375, 390 and 430 px, with the
diagnostics section expanded so every long SHA is rendered:

- the ordinary page at all four widths;
- **the real 403 body** GitHub returns when an anonymous read is rate-limited, at all
  four widths, asserting the error is actually on the page rather than passing by
  hiding it;
- pathological input — a 400-character unbroken token in `waiting_for`, in
  `requires_krum_reason` and in a history summary, plus a 400-character URL;
- the table wrapper scrolling while the page does not;
- nothing clipped off the left edge either;
- and the desktop layout still two-column with three agent cards abreast, so the
  wrapping rules did not cost desktop readability.

**B. Synthetic acceptance mode.** `app/acceptance.py`, `BEGWORK_ACCEPTANCE_MODE`,
default false. Rather than returning hand-written payloads, a scenario takes the
snapshot already read from GitHub, changes one thing in memory and re-runs the real
`verify()`. What the reviewer sees is the production verification path catching a real
defect. Safety is asserted, not asserted-to: 46 cases in `tests/test_acceptance_mode.py`
plus 6 browser cases cover off-by-default, 404-while-disabled, zero GitHub requests,
canonical files unchanged on disk (SHA-256 before and after), the live projection
unmodified, the synthetic flag and banner, and a guard that refuses to serve a scenario
that came out verified or that failed to demonstrate the defect it names — verified by
neutering the mutation and asserting the guard fires.

**C. Cache loss on restart** is documented as an accepted v0.2 limitation in
`README.md`, with the reasoning: persisting the projection means giving the container a
writable volume, and the runtime posture is that the process writes nothing at all.
Trading that for a two-second gap after a restart is a bad exchange, and a restored
cache is by definition a reading nobody verified in this process lifetime.

**D. Runtime write protection.** Two distinct claims, kept apart because they are
different kinds of evidence. The *application* write audit (an audit hook over a full
refresh round) shows the process attempts **zero** writes anywhere — that holds on any
host and is now a regression test in `tests/test_readonly.py`. Whether the *filesystem*
refuses a write is a container property, probed by
`scripts/acceptance_probe.py writes`, which reports plainly that it is not proven on a
development host.

### Track 2 — variant-2 redesign

The variant-2 mockup image was **not available** to this session. The redesign was built
to the written target in ARCHITECT UPDATE; **no pixel fidelity to an unseen image is
claimed.**

Delivered: a dark management control center — masthead with BEG_WORK, project,
repository, branch, updated time and an honest LIVE / STALE / OFFLINE feed pill; three
accented agent cards (ChatGPT teal, Codex blue, Claude amber) showing real protocol
state, Work-ID, waiting_for and update time; a prominent current-task panel with a large
Task-ID and status; a horizontal DEFINE → BREAKDOWN → IMPLEMENT → REVIEW → DECISION →
NEXT workflow; a task table with ID / Task / Status / Progress / Current agent / Cycle /
Updated; a Next Steps panel; a Recent Activity timeline; and verification, findings and
evidence moved into a collapsed `<details>`.

Four decisions worth stating:

- **The workflow strip is presentation only.** Each step names the canonical step it
  renders, so the mapping is auditable on screen. NEXT has no canonical step — it is
  derived from `next_agent` — and is labelled `DERIVED` / `NO CANONICAL STEP` so the
  six-label strip can never be read as a change to the five-step state machine.
- **The stage meter is six discrete segments, not a filled bar,** and reads "Stage 4 of
  6 — REVIEW. Workflow position, not a completion percentage." The position derives from
  the verified `pipeline_step`; nothing about completion is claimed. Numeric progress
  remains withheld on any unverified round, as fixed in §4a.
- **Collapsing diagnostics must not hide bad news.** Blockers, KRUM ACTION and an
  explicit "this round did not verify" banner sit above the fold, uncollapsed. Only the
  detail moved.
- **The task table shows one row** because protocol v1 proves one active task, and says
  so in a footnote instead of padding the table with plausible-looking rows.

Agent identity colour is carried by a stripe and a badge; status is always a separate
pill with its word and glyph, so Claude's amber and a STALE amber are never the same
signal, and the page reads correctly in greyscale.

### Defects found by the new tests

| Defect | Symptom |
|---|---|
| `.alert { display: flex }` outranked the user-agent `[hidden]` rule | The KRUM and synthetic banners stayed on screen after being hidden — the KRUM banner would have shown when no action was required |
| The `offline` scenario tripped the acceptance guard | Revealed that the guard's "never VALID" rule was wrong for OFFLINE, where a cached verified verdict legitimately survives a dropped link; replaced with a per-scenario expectation that is strictly stronger |
| `NEXT` rendered "DERIVED" twice | The canonical-step line duplicated the derived badge; it now reads "no canonical step" |

---

## 4c. PENDING — Synology acceptance (not executed, not simulated)

Track 3 of the combined request could **not** be carried out from this session. The
implementation environment is an isolated cloud container with no network route to the
NAS, no test URL, and no access to the local secret. The instruction was explicit that
an unavailable secret is to be marked pending for Codex rather than simulated, and that
applies to the whole NAS-hosted track: fabricating a "NAS screenshot" from a local
server would be a false claim about the target environment.

**PENDING, for execution on the Synology test container at the exact head of this PR:**

1. Configure `BEGWORK_GITHUB_TOKEN` as a local env/secret on the test container only.
2. `python3 scripts/acceptance_probe.py rounds --count 5` inside the container, or
   `remote --base-url http://<nas>:8787 --count 5` from the LAN — five consecutive
   successful **authenticated** rounds with timestamps and counters.
3. `python3 scripts/acceptance_probe.py token --base-url http://<nas>:8787` — token
   containment across every served response.
4. `python3 scripts/acceptance_probe.py writes` **inside the container** — the denial
   probe is only meaningful there.
5. `BEGWORK_ACCEPTANCE_MODE=true` on the test container; open `/?acceptance=stale`,
   `conflict`, `invalid`; capture NAS-hosted screenshots.
6. NAS-hosted desktop and 390×844 screenshots from the confirmed test URL.

**What was done locally instead**, all labelled as such and none of it a substitute:

| Check | Local result | Still pending on the NAS |
|---|---|---|
| Five consecutive live rounds | **5/5 VALID**, 6 requests each, 5 served 304 from round 2 | Authenticated rounds on the NAS |
| Application write audit | **0 write attempts** over 4 live rounds | OS-level denial inside the read-only container |
| Token containment | Asserted against a synthetic token across every response, log and traceback (39 tests) | A real read-only token on the NAS |
| Screenshots | Real Chromium against a live local server, desktop / tablet / 390×844 | NAS-hosted captures from the test URL |
| STALE / CONFLICT / INVALID rendering | Demonstrated in Chromium via acceptance mode | The same, rendered on the NAS |

One diagnostic finding worth carrying into the NAS run: the anonymous 403 is unlikely to
be a steady-state problem. Conditional requests do not count against GitHub's primary
rate limit, and the local rounds show 5 of 6 requests answered `304` from the second
round onward — so a warm dashboard costs almost nothing per round. The 403 seen during
acceptance was most likely the cold-start burst or a shared-IP limit. A token is still
the right fix, and is required for a private repository regardless.

---

## 5. Evidence

Environment: Linux 6.18, Python 3.11.15, pytest 9.1.1, Playwright 1.63.0 driving
Chromium 1194 at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.

### Tests

```bash
cd tools/web-dashboard
python3 -m pytest tests/ -q
```

**229 passed in 25.71s.** Coverage by file:

| File | Tests | Covers |
|---|---|---|
| `test_log_redaction.py` | 13 | Traceback, chained-exception and `stack_info` redaction; the filter clearing `exc_info`; idempotence; formatter-only defence; uncaught main-thread and worker-thread hooks; end-to-end round |
| `test_unverified_progress.py` | 13 | Numeric progress withheld on INVALID/STALE/CONFLICT/aged and on an impossible percentage; kept for a verified EVIDENCE_COUNT and for a cached verified snapshot while OFFLINE |
| `test_canonical_engine.py` | 41 | Drift against `tools/control_engine.py`: soundness, completeness, severity agreement on 16 single-defect mutations, board byte-identity, the deliberate SYNTHETIC_TEST divergence |
| `test_blob_and_pr.py` | 17 | Cited blob match and mismatch, CRLF rejection, unreadable and mis-pathed sources, transport integrity, oversized blob, moved PR head, draft and merged mismatch, repo/branch mismatch, unparsable state |
| `test_status_matrix.py` | 17 | VALID/STALE/CONFLICT/INVALID end to end, worst-of precedence, forged PASS never promoted, producer `VALID` claim insufficient, STAGE_ONLY, deterministic and non-deterministic percentages, aged snapshot |
| `test_readonly.py` | 26 | Every non-read method refused, GET-with-body refused, guard wraps the production transport, a full round is six GETs to six expected URLs, token reaches GitHub but not the projection, redaction cases |
| `test_refresh.py` | 33 | Cadence clamping, `If-None-Match` and 304 byte reuse, ETag invalidation, backoff escalation and cap, **loop-level `Retry-After` on 429 and secondary-limit 403**, recovery, offline cache retention, OFFLINE vs STALE separation, loop thread lifecycle |
| `test_projection.py` | 22 | Header fields, migrated cycle label, KRUM action, three agent cards from `agent_states` not history, five-step pipeline, task area, evidence links with cited *and* observed identity, history ordering |
| `test_server.py` | 24 | `/api/state`, `/healthz` liveness under outage, every declared static asset served, allowlist routing and 404s, no source reachable, security headers, no token in any response, HEAD, SIGTERM |
| `test_ui.py` | 23 | Real Chromium: rendering, agent cards, pipeline, STAGE_ONLY drawing no bar, evidence links, each status on screen, OFFLINE, forged PASS, unavailable state, three form factors with no horizontal overflow, both themes, PWA manifest and icons, **withheld progress on unverified rounds** |

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

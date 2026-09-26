# BEG_WORK web dashboard

A read-only browser dashboard for the ChatGPT ↔ Codex ↔ Claude control protocol,
packaged to run on a Synology NAS under Container Manager.

It projects the control state published on `codex/claude-queue` and verifies the
evidence that state cites. Per CLAUDE.md §2 rule 12 it is a projection and an
interface, never a second source of truth: **it performs no GitHub write of any kind
and never emits an operational record.**

---

## What it shows

| Area | Contents |
|---|---|
| Header | `BEG_WORK`, Wave, Flow, Task-ID, Cycle-ID, stage, big state, KRUM ACTION |
| Status bar | control-state status, link state, last verified time and age, next read |
| Agent cards | ChatGPT / Architect, Codex / Tech Lead–QA, Claude / Implementer — state, Work-ID, waiting_for, updated_at |
| Pipeline | ChatGPT → Codex → Claude → Codex → ChatGPT, active step highlighted |
| Task | current agent and role, current Work-ID, pipeline step, next agent, waiting_for, dispatch |
| Findings | every verification finding, with its severity and a stable code |
| Evidence | ACTIVE, independent review, Draft PR, HANDOFF, canonical docs — cited identity *and* observed identity, each linked |
| History | append-only event list, newest first, each row linked to its evidence |

Agent cards are read from `agent_states` only. History is evidence, never a status
source: the newest Claude event in the current snapshot is a `HANDOFF`, and its card
correctly reads `NOT_ACTIVE`.

### The four statuses, and OFFLINE

`VALID` · `STALE` · `CONFLICT` · `INVALID` are the control-state statuses, with
precedence `INVALID > CONFLICT > STALE > VALID`. Each is shown as a word, a glyph and a
colour, so the screen reads correctly in greyscale.

`ONLINE` / `OFFLINE` is a **separate** indicator describing this dashboard's link to
GitHub. The two are never merged: a network outage must not read as a protocol
conflict, and a real `CONFLICT` must not be excused as a connectivity blip. When a
round fails, the cached snapshot stays on screen with its age, marked `OFFLINE`.

### Acceptance mode — synthetic states, off by default

Acceptance testing needs STALE, CONFLICT and INVALID on screen, and the only safe way
to get them is to manufacture them: deliberately corrupting the real queue to see a
colour change is exactly what this dashboard exists to prevent.

Set `BEGWORK_ACCEPTANCE_MODE=true` on a **test** container and the scenarios become
available at `/?acceptance=<name>` — `stale`, `conflict`, `invalid`, `offline`,
`unavailable`.

Each one takes the snapshot already read from GitHub, changes one thing **in memory**
(an ACTIVE byte, a board line, a state field) and re-runs the real verifier. What
appears is a genuine demonstration of the production verification path catching a real
defect, not a hand-written picture of one.

Four properties make it safe to ship:

- **Off unless asked.** The default is false, and while it is false the endpoint 404s
  like any unknown path — a disabled deployment reveals nothing about the feature.
- **Nothing is written.** No GitHub request is issued, no canonical queue file is
  touched, nothing is persisted, and the dashboard's own live reading is not modified.
- **It cannot pass for the truth.** Every payload carries `synthetic: true`, the page
  shows an unmissable banner, and the code refuses to serve a scenario that came out
  verified — or one that failed to demonstrate the defect it names.
- **`/healthz` reports `acceptance_mode`**, so an acceptance box is distinguishable
  from a production one at a glance.

### What it will not do

- It never promotes an unverified state. A stored `PASS` that fails verification renders
  as `PASS (UNVERIFIED)` in the header *and* on the pipeline.
- It never invents a percentage. Under `progress.mode = STAGE_ONLY` it shows the stage
  and says, in words, that no percentage is proven.
- A persisted `control_state_status: VALID` is treated as a claim, not as truth. Status
  is recomputed every round as the worst of everything observed.

---

## How a round is verified

Six conditional `GET`s per round, issued serially, then six checks whose worst result
wins:

1. **Schema** — against `CONTROL_STATE.schema.json` fetched from the same branch in the
   same round, not a copy baked into the image.
2. **Protocol invariants** — Work-ID composition, agent/role/pipeline agreement,
   WORKING/REVIEW ownership, `NOT_ACTIVE` purity, `requires_krum` reasons, PR evidence
   completeness, review head and blob, verdict-versus-state, history uniqueness and
   cycle bounds, progress determinism.
3. **Cited blob SHAs** — `ACTIVE.md` and the cited review are re-hashed locally as Git
   blobs. Trusting the SHA the API reports alongside the content would only prove the
   API is self-consistent.
4. **Exact PR head** — live `head.sha`, `draft` and `merged` against what is cited.
5. **`CONTROL_BOARD.md`** — compared against a full re-render of the state. The board may
   only ever demote the status; it can never promote a value.
6. **Transport integrity** — locally computed blob SHA against the SHA the API named for
   the same read, so truncated or rewritten content is refused rather than used.

Phase two of each round reads *the paths the state itself cites*
(`source_refs.active_path`, `source_refs.review_path`, `pr_number`), not hardcoded ones.

---

## Architecture, and why it is this small

```
browser  ──HTTP──>  dashboard container  ──read-only HTTPS──>  api.github.com
(no token,                (token lives here,
 no GitHub access)         never leaves it)
```

- **Backend: Python 3.11, standard library only.** No pip install, no third-party
  dependency tree. The container is the base image plus a few hundred kilobytes.
- **Frontend: plain HTML, CSS and JavaScript.** No React, no bundler, no `node_modules`.
  This is the main reason the token cannot leak into a browser bundle: there is no build
  step that could inline it, and the browser never talks to GitHub at all.
- **Why Python rather than a port of the C# core in PR #28:** the canonical validator
  `tools/control_engine.py` is itself Python. This dashboard's checks are an adaptation
  of it and are pinned to it by `tests/test_canonical_engine.py`, which imports the
  canonical engine and asserts agreement on verdicts and byte-identity on the board
  rendering. A port into another language cannot make that comparison, so it can drift
  from the producer unnoticed — and a projection that drifts becomes a second opinion
  about protocol truth.

---

## Install on Synology (Container Manager)

**These are instructions. Nothing here has been deployed to a NAS, and deploying is
Krum's decision.**

### 1. Create a read-only GitHub token

A fine-grained personal access token, scoped as narrowly as it will go:

| Setting | Value |
|---|---|
| Repository access | Only select repositories → `krumingo/BEG_Worck` |
| Contents | **Read-only** |
| Pull requests | **Read-only** |
| Everything else | No access |

Nothing more is needed. The dashboard's transport refuses any request that is not a
`GET` or `HEAD`, so a token with write scope would still never be used to write — but do
not grant it.

Without a token the dashboard reads anonymously: this works only for a public repository
and is limited to 60 requests/hour, which is below what a 15 s cadence needs.

### 2. Copy the project to the NAS

Put this directory (`tools/web-dashboard/`) somewhere on the NAS, for example
`/volume1/docker/begwork-dashboard/`. File Station, `git clone` over SSH, or an SMB copy
all work.

### 3. Create the `.env` file

Next to `docker-compose.yml`:

```bash
cp .env.example .env
```

Edit `.env` and set `BEGWORK_GITHUB_TOKEN`. **`.env` is git-ignored — never commit it,
and never paste a token into an issue, a pull request or a screenshot.**

### 4. Create the project in Container Manager

1. Open **Container Manager** → **Project** → **Create**.
2. **Project name:** `begwork-dashboard`.
3. **Path:** the folder from step 2.
4. **Source:** *Use existing docker-compose.yml*. Container Manager reads this file
   directly.
5. Review the configuration it shows, then **Next** → **Done**. The first build pulls
   `python:3.11-alpine` and takes a minute or two.

DSM will build the image and start the container. It restarts with the NAS
(`restart: unless-stopped`).

### 5. Open it

```
http://<nas-address>:8787/
```

Host port `8787` keeps clear of DSM's own services; change the left-hand side of the
`ports:` mapping in `docker-compose.yml` if it clashes with something.

To reach it from outside the LAN, put it behind DSM's **Login Portal → Reverse Proxy**
with HTTPS rather than forwarding the port directly. The dashboard has no authentication
of its own — it is a read-only projection, but it does disclose repository activity, so
treat it as internal.

### 6. Install it as an app (optional)

The dashboard ships a web manifest and a service worker, so a browser can install it:

- **Desktop Edge/Chrome:** the install icon in the address bar, or ⋯ → *Apps → Install*.
- **iPad / iPhone (Safari):** *Share* → *Add to Home Screen*.
- **Android (Chrome):** ⋮ → *Add to Home screen*.

The service worker caches only the static shell. `/api/state` and `/healthz` are never
cached, in either direction — a cached verdict would present a stale snapshot as a
current one, which is the precise failure this dashboard exists to prevent.

### 7. Check it is healthy

```bash
curl http://<nas-address>:8787/healthz
```

```json
{"status":"ok","link":"ONLINE","control_state_status":"VALID","snapshot_available":true,
 "last_verified_at":"2026-09-25T19:54:03Z","age_seconds":4.1,"aged":false,
 "consecutive_failures":0,"rounds":37}
```

The status code is **liveness**: it stays `200` whenever the process can serve, including
while GitHub is unreachable. Restarting a dashboard that is waiting out an outage would
discard the cached snapshot, which is the one thing still worth showing. **Readiness** is
in the body — `link`, `consecutive_failures` and `age_seconds`.

---

## Configuration

Every setting is an environment variable; see `.env.example` for the annotated list.

| Variable | Default | Notes |
|---|---|---|
| `BEGWORK_GITHUB_TOKEN` | *(empty)* | Server-side only. Never sent to the browser. |
| `BEGWORK_REPOSITORY` | `krumingo/BEG_Worck` | A snapshot naming a different repo is a `CONFLICT`. |
| `BEGWORK_BRANCH` | `codex/claude-queue` | Likewise for the branch. |
| `BEGWORK_REFRESH_SECONDS` | `15` | Clamped to 10–30. |
| `BEGWORK_STALE_AFTER_SECONDS` | `120` | Age of the last successful read at which it is shown as AGED. |
| `BEGWORK_BACKOFF_INITIAL_SECONDS` | `10` | Backoff runs 10 → 20 → 40 → 80 → 120 s. |
| `BEGWORK_BACKOFF_MAX_SECONDS` | `120` | A server `Retry-After` is honoured — it may extend the wait, never shorten it — and is still capped here. |
| `BEGWORK_VERIFY_PULL_REQUEST` | `true` | Switching it off reports the PR head as unverified rather than hiding it. |
| `BEGWORK_PORT` / `BEGWORK_HOST` | `8080` / `0.0.0.0` | Inside the container. |

---

## Run it locally

```bash
cd tools/web-dashboard
BEGWORK_GITHUB_TOKEN=<read-only token> python3 -m app
# http://127.0.0.1:8080/
```

No virtualenv and no dependencies are needed to run it: Python 3.11+ is enough.

### Tests

```bash
cd tools/web-dashboard
python3 -m pip install pytest playwright      # test-only dependencies
python3 -m pytest tests/ -q      # 229 tests
```

The browser tests skip themselves if no Chromium is available; set `BEGWORK_CHROME` to
point at one. They drive a real browser against a real server and capture the
screenshots in `docs/screenshots/` as they assert, so a screenshot cannot show something
the assertions do not hold.

Fixtures read **canonical committed blob bytes** via `git cat-file blob`, never the
working tree, so they are unaffected by `core.autocrlf` on a Windows checkout. The
production blob check remains fail-closed and a CRLF-converted source is still correctly
rejected — `tests/test_blob_and_pr.py::test_a_crlf_converted_checkout_would_not_match`
pins that.

### Measure its footprint

```bash
python3 scripts/measure_resources.py --seconds 60
```

### Acceptance evidence

`scripts/acceptance_probe.py` produces the evidence an acceptance review asks for. It
runs both here and inside the deployed container, and **never prints the token** — it
reads `BEGWORK_GITHUB_TOKEN` only to search for that value in responses and reports
whether it was found.

```bash
python3 scripts/acceptance_probe.py rounds --count 5          # consecutive live rounds
python3 scripts/acceptance_probe.py writes                    # write audit + denial probe
python3 scripts/acceptance_probe.py token --base-url http://127.0.0.1:8080
python3 scripts/acceptance_probe.py remote --base-url http://<nas>:8787 --count 5 \
    --require-auth --auth-evidence "fine-grained PAT <date>: repo-scoped, Contents:read, PRs:read"
```

`remote` counts a refresh cycle only when the target's `/healthz.rounds` counter is
**strictly higher** than at the previously counted cycle, and fails if no new round
arrives inside a bounded window. Polling five times is not five cycles: a target whose
refresh loop has stopped would otherwise pass the very check meant to prove it running.

It also keeps two claims apart. That the target *refreshes* is proven by the counter.
That it *authenticates with read-only scope* is not fully provable from outside: the
dashboard publishes whether a token is configured but never exposes the token, so scope
has to be confirmed in GitHub's token settings and passed in with `--auth-evidence`,
where it is reported as operator-attested rather than probe-verified. Without it the
probe reports the authenticated claim as **NOT CLAIMED** instead of implying it.

Exit codes: `0` everything asked for was proven, `1` something failed, `2` a check could
not be proven from this host or surface — so an acceptance gate checking `rc == 0` never
reads an unproven claim as a passed one.

`writes` reports two different things. The **audit** shows what the application tries to
do and is valid on any host. The **denial probe** shows whether the filesystem refuses a
write, which only means something inside the hardened container; on a development host
it says so instead of claiming the protection was verified.

---

## Known limitations (v0.2)

**The verified snapshot is lost when the container restarts.** The cache lives in
process memory only. After a restart the dashboard shows `CONTROL STATE NOT AVAILABLE`
until the first round completes — normally a second or two, longer if GitHub is
unreachable at that moment.

This is **accepted for v0.2** rather than fixed, deliberately. Persisting the last
verified projection would mean giving the container a writable volume, and the whole
runtime posture here is that the process writes nothing at all (`read_only: true`, no
cache directory, no log file, an audit-hook test asserting zero writes). Trading that
property away to avoid a two-second gap after a restart is a bad exchange — and a
restored cache is by definition a reading nobody verified in this process lifetime,
which would need its own staleness handling to be shown honestly.

If a future cycle decides the gap matters, the scope is narrow: one declared cache path
under the tmpfs, written atomically, loaded only as a clearly-marked aged snapshot, and
never as a verified one.

## Boundaries

- No GitHub writes. Enforced in the transport, not at call sites.
- No LLM or AI call anywhere.
- The token never reaches the browser, a log line, a response or a screenshot.
- The dashboard never writes `coordination/` state, and grants no PASS, merge or deploy.

See `docs/ISSUE-26-C02-IMPLEMENTATION.md` for the implementation notes, the reuse map
against PR #28, the evidence and the limitations.

# RC-01 — evidence: build identity in API and UI

Task: `docs/architecture/tasks/RC-01_BUILD_IDENTITY.md` (on `claude/happy-meitner-bmcnel`). Base `main` @ `c0e34e1`. Draft PR, not merged, not deployed.
Source of the requirement: `docs/evidence/INTEGRATED-RC-2026-10-25/02-release-gates.md`, step 4.

## Where things are decided

| Question | Answer in the code |
|---|---|
| Where the SHA comes from | Git objects only: `ops/release/beg_release/build_info.py` (`beg.build-info/v1` = `{schema, build_sha, build_time, source: "git-objects"}`). `release_build.py` writes it as `build_info.json` next to `artifact.tar` (in `SHA256SUMS`, `build_sha == release.app.commit`). `write_build_info.py` stamps a build context: `--commit <ref>` (rev-parse; refuses a dirty tree) or `--from-bundle <bundle>` (refuses `build_info.json != manifest commit`). |
| Why not inside the artifact | A commit cannot contain its own id, and `artifact.tar` must stay byte-identical to the Git tree (W0-09A). `backend/BUILD_INFO.json` and `frontend/BUILD_INFO.json` are git-ignored build outputs. |
| Backend | `app/core/build_info.py` + `GET /api/version` in `app/routes/health.py`, no auth. Order: `backend/BUILD_INFO.json` → `BUILD_SHA`/`BUILD_TIME` env → `"unknown"`. File wins over a contradicting env and the disagreement is logged (12-char prefixes only). Invalid file/env values (not 40 lowercase hex) are ignored. |
| Response | exactly `build_sha`, `build_time`, `environment_label`, `source` (`build-info-file` / `env` / `none`). No secrets, paths or host names. `schema_version` is not returned: the app has no schema version yet (manifest `app_schema_version: null`). `/api/health` unchanged. |
| Environment label | R0-07 policy: the raw `ENV` must be exactly `production`/`staging`/`development`/`test`; anything else (unset, `prod`, `PRODUCTION`, `" test"`, `"test\n"`) → `unknown`. `ENVIRONMENT` is not read. |
| Frontend constant | `frontend/build-info.js`, called by `craco.config.js` before CRA reads the env: `frontend/BUILD_INFO.json` → `REACT_APP_BUILD_SHA` → `"unknown"`, baked into the bundle as `REACT_APP_BUILD_SHA`/`REACT_APP_BUILD_TIME`. |
| UI | `src/components/BuildIdentity.js` on the login screen (under the card), at the bottom of the desktop sidebar and in the mobile menu footer: `v <first 12>` (full SHA in the tooltip), the environment label, and a warning: mismatch → „Версията на интерфейса и сървъра се различава“ (+ server's 12 chars); `unknown` on either side → „Непотвърдена версия: липсва build SHA“; `/api/version` unreachable → „Версията на сървъра не може да се провери“. |
| Synology | **Not wired.** `release_deploy.sh` does not write `BUILD_INFO.json` into `repo/` (its `verify_tree` would also refuse the extra file). Until that is approved separately, a Synology build shows `unknown` plus the warning — visible, never a silently wrong version. |

## Tests

| Suite | Result |
|---|---|
| `tests/test_rc_01_build_identity.py` | **31 passed**: file / env only / nothing → `unknown` / env contradicting the file (file wins, logged, no secret in the log) / malformed env and file ignored / allowlisted keys and no secrets, paths or hostname (file, env, none) / 11 `ENV` label cases / `/api/health` unchanged / real `server.app` serves `/api/version` without auth / **one release build: manifest commit == `build_info.json` == `/api/version` == frontend constant** (`release_verify.py bundle` PASS, `BUILD_SHA` set to another SHA cannot override) / tampered bundle refused. |
| Mutation (`mutation_on_main.txt`) | the same test file against main's code (no route): **28 failed / 3 passed** (the 3: `/api/health` unchanged and the two `write_build_info.py` refusal paths). Without `app/core/build_info.py` the file does not even collect. |
| `tests/test_r0_0*.py` + RC-01 | **454 passed, 391 skipped** (the skips are the real-MongoDB variants; see below). |
| W0 DB-free (`tests/test_w0_*.py --noconftest`) | main **1085 / 15 / 50**, branch **1085 / 15 / 50**, the same 15 `test_w0_03e_legacy_routes` failures (`w0_main_summary.txt`, `w0_branch_summary.txt`). |
| A1 / A2C guards | `w0_03e_a1_tenant_access_guard.py`: 414 units, **0 violations**; `w0_03e_a2c_tenant_boundary_guard.py`: 204 modules, **0 violations**; static guard tests 122 passed. |
| `ops/release/tests` | `test_artifact` 42 OK (1 skip), `test_deploy_tools` + `test_isolated_runner` 37 OK. |
| `yarn test` | **5 suites, 92 passed** (new `BuildIdentity.test.js`: SHA shown + tooltip, mismatch warning, `unknown` frontend, `unknown` server, unreachable server, malformed constant). |
| `yarn build` | passes (only the pre-existing `exhaustive-deps` warnings in other files); with `frontend/BUILD_INFO.json` for `c0e34e1…` the full 40-char SHA is in `build/static/js/main.*.js`. |

Real MongoDB: not needed — RC-01 reads/writes no database. The Docker Hub pull of `mongo:7.0` was rate-limited (429) in this session, so the R0 real-Mongo variants were skipped, not run.

Python: tests ran in a Python 3.11 venv with `backend/requirements.txt` + `requirements-dev.txt` (the system 3.13 pip could not replace a Debian package).

## Local run for the Bot session (exact commands)

From the repository root, on the PR head. MongoDB on `127.0.0.1:27019` (single-node replica set):

```bash
docker run -d --rm --name rc01mongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all
docker exec rc01mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
```

1. Stamp the build identity from Git objects (refuses a dirty working tree):

```bash
python3 ops/release/write_build_info.py --commit HEAD
# -> backend/BUILD_INFO.json and frontend/BUILD_INFO.json, build_sha = git rev-parse HEAD
```

2. Backend (`ENV=test` → label `test`):

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt     # once
MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \
DB_NAME=rc01_bot BEG_SYSTEM_DB=rc01_bot_system ENV=test \
JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')" \
CORS_ORIGINS=http://127.0.0.1:3000 \
uvicorn server:app --host 127.0.0.1 --port 8001
curl -s http://127.0.0.1:8001/api/version     # same build_sha as backend/BUILD_INFO.json
```

3. Frontend (the SHA is baked in at build time):

```bash
cd frontend
yarn install --frozen-lockfile                              # once
REACT_APP_BACKEND_URL=http://127.0.0.1:8001 yarn build
grep -l "$(git rev-parse HEAD)" build/static/js/main.*.js   # the full SHA is in the bundle
cd .. && python3 docs/evidence/RC-01/spa_server.py frontend/build 3000
```

Open `http://127.0.0.1:3000/login`: under the login card `v <12 chars>  TEST`, full SHA in the tooltip (`[data-testid=build-sha]`, attribute `title` / `data-full-sha`). After login the same at the bottom of the sidebar (desktop) or in the menu footer (mobile, `[data-testid=mobile-menu-toggle]`). `[data-testid=build-identity]` carries `data-build-status` = `match` / `mismatch` / `unknown` / `unreachable`.

4. Forced mismatch: restart only the backend with a different build identity, e.g.

```bash
python3 ops/release/write_build_info.py --commit HEAD~1 --target "$PWD"   # rewrites both files; the built frontend keeps HEAD
# restart uvicorn (step 2) -> /api/version shows HEAD~1, the UI shows the warning
```

`[data-testid=build-warning-mismatch]`: „Версията на интерфейса и сървъра се различава“, plus `сървър: <12 chars of HEAD~1>`. Run `write_build_info.py --commit HEAD` again afterwards. `unknown`: delete `backend/BUILD_INFO.json`, unset `BUILD_SHA`, restart.

Bot screenshots and JSON go into this directory (task steps 1–4; 390×844 without horizontal scroll).

# BOT RC-01 — build identity @ `44c9c3cfa668cf9a601f65960680eac11ef70ec7`

Branch `claude/rc-01-build-identity`. Local, synthetic data, `ENV=test`. **PASS 22/22.** Screenshots `01…18_*.png` (1280 and 390×844), `bot_result.json` (per-step detail, `/api/version` JSON for the match / mismatch / unknown cases).

## Exact commands
```bash
git fetch origin claude/rc-01-build-identity
git worktree add -f /tmp/botwt/44c9c3c 44c9c3cfa668cf9a601f65960680eac11ef70ec7
(cd /tmp/botwt/44c9c3c && python3 ops/release/write_build_info.py --commit HEAD)           # stamps backend/ and frontend/BUILD_INFO.json
docs/evidence/BOT/runner/start_stack.sh /tmp/botwt/44c9c3c ENV=test                        # Mongo RS, backend, frontend build with the SHA, UI on :3000
# second frontend build WITHOUT build info, served on :3001 (for the "unknown" case)
(cd /tmp/botwt/44c9c3c/frontend && mv BUILD_INFO.json /tmp/fe.json && REACT_APP_BACKEND_URL=http://127.0.0.1:8001 CI=false BUILD_PATH=build_unknown yarn build; mv /tmp/fe.json BUILD_INFO.json)
node docs/evidence/BOT/runner/serve_spa.js /tmp/botwt/44c9c3c/frontend/build_unknown 3001 &
BOT_OUT=$PWD/docs/evidence/BOT/RC-01-44c9c3c BOT_SHA=44c9c3c NODE_PATH=$(npm root -g) node docs/evidence/BOT/RC-01-44c9c3c/RC-01.js
```
The bot restarts only the backend between cases (`docs/evidence/BOT/backend_ctl.sh`): stamp `HEAD` → mismatch with `HEAD~1` (`c0e34e1…`) → delete `backend/BUILD_INFO.json` (unknown) → stamp `HEAD` again.

## Results
| Task check | Result |
|---|---|
| 1. Full SHA of a known build on the login screen and in the menu: 12 chars shown, full 40-char SHA in the tooltip (`title`) | PASS at 1280 (login, sidebar bottom) and 390 (login, mobile menu footer); `data-build-status=match`, env label `TEST` |
| 2. `/api/version` (no auth) returns the same SHA; exactly `build_sha, build_time, environment_label, source`, no secrets/paths/host | PASS (`environment_label: test`, `source: build-info-file`) |
| 3. Backend built from another SHA → mismatch warning „Версията на интерфейса и сървъра се различава“ + server's 12 chars | PASS on the login screen and in the menu, at both widths |
| 4. `unknown` without build info | PASS: backend with no file/env → `/api/version` `build_sha: "unknown"`, `source: "none"`; UI with SHA → "Непотвърдена версия" warning (`status=unknown`); UI built without build info → shows `unknown` (tooltip `unknown`) at both widths |
| 5. 390×844 no horizontal scroll | PASS on login, dashboard, open menu, mismatch warning, menu with warning, unknown state |

Not covered: Synology/release-bundle path (the task says it is not wired), `unreachable` backend state, a real `ENV=production|staging` label.
Bot note: one first-run failure was my selector (hidden desktop sidebar copy matched first on a phone); fixed to `:visible`, the rerun is the committed evidence.

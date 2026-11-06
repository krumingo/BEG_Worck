# BOT runner (local Playwright) — reusable

Local, synthetic-data-only browser bot. Never touches production/Synology. Smoke-proven on `main` @ `c0e34e1` (8/8, see `RUNNER-smoke-c0e34e1/`).

## Files (`docs/evidence/BOT/runner/`)
| File | Purpose |
|---|---|
| `start_stack.sh <worktree> [ENV=…]` | MongoDB 7 replica set in Docker (`botmongo`, 127.0.0.1:27019), FastAPI on 127.0.0.1:8001, production frontend build served on 127.0.0.1:3000. Extra args become backend env (e.g. `ENV=test`). Starts `dockerd` if needed. |
| `stop_stack.sh` | Stops backend, static server and `botmongo`. |
| `serve_spa.js` | Static server with SPA fallback for the CRA build. |
| `lib.js` | Helpers: `run`, `context('desktop'\|'phone')` (1280×800 / 390×844 @2x), `step`, `shot`, `login`. Writes `bot_result.json`. |
| `smoke.js` | login → dashboard → logout at 1280 and 390×844. |

## Exact commands (per request)
```bash
SHA=<full head sha>; SHORT=${SHA:0:7}; TASK=<task>
git fetch origin <pr-branch> && git worktree add -f /tmp/botwt/$SHORT $SHA
docs/evidence/BOT/runner/start_stack.sh /tmp/botwt/$SHORT        # add ENV=test etc. when the task needs it
BOT_OUT=$PWD/docs/evidence/BOT/$TASK-$SHORT BOT_SHA=$SHORT \
  NODE_PATH=$(npm root -g) node docs/evidence/BOT/runner/<task-script>.js
docs/evidence/BOT/runner/stop_stack.sh
```
Python venv is created once at `/tmp/botvenv` (`BOT_VENV` to override); logs in `/tmp/botrun`.
Chromium comes preinstalled (`require('playwright')` via global `NODE_PATH`); do **not** run `playwright install`.

## Synthetic data
- Backend env: `DB_NAME=bot_op`, `BEG_SYSTEM_DB=bot_sys`, `JWT_SECRET=bot-local-secret`, `ENV=development`.
- Startup seed (real seed path) creates one firm + admin: `admin@bot-a.test` / `BotPass-12345!` (synthetic, local only).
- Second firm and other roles: not part of the smoke; each task script creates them through the real API (admin → users, or `/auth/signup`) with `@bot-a.test` / `@bot-b.test` addresses. Seeding helpers get added to `runner/` when the first task needs them.

## Notes
- Phone logout path: `mobile-menu-toggle` → `mobile-logout`; desktop: `logout-button`.
- The bcrypt `__about__` warning in `backend.log` is harmless.
- Reset between runs: `stop_stack.sh` removes the Mongo container (`--rm`), so each run starts empty.
- Result contract: `bot_result.json` = `{task, sha, steps[{step, pass, screenshot, error?}], passed, total, verdict}`.

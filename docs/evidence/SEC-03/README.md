# SEC-03 — Emergent removal and SEC-SCAN hardening (Р75, Р76)

Package: `docs/architecture/tasks/SEC-03_EMERGENT_REMOVAL_AND_HARDENING.md` (branch `claude/happy-meitner-bmcnel`).
Source findings: `docs/security/SEC_SCAN_2026-11-09.md` (branch `claude/sec-scan`), H-1, M-1…M-5, L-6.
Branch `claude/sec-03-emergent-removal` from main `1525a1e`. Draft PR, no merge, no deploy, no production access.

## What changed

| Item | Finding | Change | Files |
|---|---|---|---|
| A1 | H-1, L-6 | `index.html` loads no third-party script: `emergent-main.js`, the `DataCloneError` suppressor, the framed `debug-monitor.js` + Tailwind CDN loader, the "Made with Emergent" badge, its Google font, the Emergent title and description are removed. Title and description: `BEG_Work`. | `frontend/public/index.html` |
| A2 | — | Nothing in `frontend/src` depended on those scripts. The dev-server-only `plugins/visual-edits` is untouched (Р75: the Emergent code-applying workflow stays; L-4 is not in the package). | — |
| A3 | M-4 | nginx: `Content-Security-Policy` (`default-src 'self'; script-src 'self'; … frame-ancestors 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, all `always`. The same CSP (without `frame-ancestors`, which a meta tag cannot carry) as `<meta http-equiv>` in `index.html`. CRA no longer inlines its runtime chunk (`INLINE_RUNTIME_CHUNK=false`). The analytics host enters the meta CSP `connect-src` only when `REACT_APP_POSTHOG_KEY` is set (for #88). | `nginx.conf`, `frontend/public/index.html`, `frontend/craco.config.js` |
| B4 | M-1 | `deps/auth.py`: no `dev-secret-key`. `JWT_SECRET` missing or < 32 bytes → `JwtSecretMissing` at import, so the app refuses to start. The only exception is an explicit test run: the pytest runner, or `ENV`/`ENVIRONMENT` set and non-production. There a short secret is accepted, and a missing one becomes a random key for that process only, never a known string. `utils/crypto.py` uses the same key and has no fallback of its own. | `backend/app/deps/auth.py`, `backend/app/utils/crypto.py` |
| B5 | M-3 | `POST /api/internal/run-reminder-jobs`: the caller is either a service with `X-Internal-Job-Key` equal to env `INTERNAL_JOB_KEY` (≥ 32 bytes, `hmac.compare_digest`; no key configured closes this path), or a Platform Admin. Otherwise 401/403. The scope is explicit: `tenant_id`, which must be a known tenant, or `all_tenants=true`; with neither → 400. Each tenant runs through its own `TenantData` view (`run_reminder_jobs_for_org`), with one canonical AuditEvent per tenant run (`reminder_jobs.triggered`, FLOW-013, R3). The in-process 15-minute scheduler is unchanged. | `backend/app/routes/attendance.py` |
| B6 | M-5 | Print windows: every interpolated name/text is HTML-escaped (`src/lib/escapeHtml.js`). The QR print window has no inline `<script>`; the opener prints. | `frontend/src/components/PayRunPrintView.js`, `UnitQrBlock.js` |
| C7 | M-2 | `emergentintegrations`, `EMERGENT_LLM_KEY` and `EMERGENT_API_KEY` are removed from `ai_proposal.py`, `smr_analysis.py`, `assets_batch_intake.py` and `assets_ai_intake.py`. The W0 test that faked the Emergent module now fakes the new adapter, with the same assertions. | as listed, `backend/tests/test_w0_03e_c02_corrections.py` |
| C8 | Р76 | One adapter, `app/services/ai_provider.py`, over the official `anthropic==2.3.0` (released 2026-10-23), pinned together with its new dependencies. `idna` is bumped 3.11→3.20 because `httpx2` needs ≥ 3.18. The key comes only from `ANTHROPIC_API_KEY` and the model only from `ANTHROPIC_MODEL`; there is no key and no model id in the code. A static test checks this, including the AuditEvent label: `model_and_version()` = `anthropic/<configured model>`. | `backend/app/services/ai_provider.py`, `backend/requirements.txt`, `backend/app/master_data/intake_hooks.py` |
| C9 | §10 | The adapter writes nothing; callers return proposals, as before. ЕГН and IBAN in text are replaced with `[скрито]` before the call. Logs carry only the error type: no request, no response, no key. Without AI: the photo endpoints → **503 "AI не е настроен"** (before: 500); the SMR proposal → rule-based with that reason; the SMR breakdown → the existing manual 60/40 split. | same |
| C10 | — | Per-tenant flag `ai_enabled` (`feature_flags` row, `module_code: "ai_enabled"`), **off by default** (no row = off). A Platform Admin turns it on with `PUT /api/feature-flags {"module_code":"ai_enabled","enabled":true}`; the first toggle creates the row. Module codes still 404 when unknown. | `backend/app/routes/auth.py`, `ai_provider.py` |
| ops | — | The release-harness fixtures (`ops/release/tests/harness.py`, `synology/make_package.py`) read the live server's hand-copied `nginx.conf` from its own blob (`LIVE_NGINX_BLOB`) instead of HEAD's file, which SEC-03 changed. The scenario "nginx.conf now tracked, same bytes" is unchanged; release tests 81 = main. This collides with the ST-02 scope guard (see Open below). | `ops/release/tests/harness.py`, `ops/release/tests/synology/make_package.py` |

## Deployment settings (for INSTRUKCII.md — not edited: ops/synology is outside this package, ST-02 guard)

- `JWT_SECRET`: **at least 32 characters**, otherwise the server does not start (`openssl rand -hex 32` gives 64).
- Optional: `ANTHROPIC_API_KEY` (the firm's own key, only in `.env` / secret store) and `ANTHROPIC_MODEL` (the model Krum chooses). Without either, AI answers "AI не е настроен" and manual work continues. AI is switched on per firm with the `ai_enabled` flag (Platform Admin); it is off by default.
- Optional: `INTERNAL_JOB_KEY` (≥ 32 characters) only if an external service should trigger `/api/internal/run-reminder-jobs`; the built-in 15-minute loop does not need it.

## Release Manifest note (deployment)

**At the next deployment, the live server's hand-copied `nginx.conf` must be replaced by the tracked root `nginx.conf` from this branch** (the M-4 security headers: CSP with `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, `Referrer-Policy`). After that deployment, `LIVE_NGINX_BLOB` in `ops/release/tests/harness.py` must be updated to the new blob. Otherwise the headers never reach production; the meta CSP in `index.html` alone cannot block framing.

## Q3, resolved (orchestrator: option A)

`backend/tests/test_st_02_staging_stack.py::test_ops_release_tools_are_not_modified_by_st02`: the allowed set now includes exactly `ops/release/tests/harness.py` and `ops/release/tests/synology/make_package.py` ("SEC-03: fixture reads the live nginx.conf blob (b87dfcd)"). Nothing else changed: the "nothing under ops/synology/" assertion is unchanged and still holds. ST-02 file: 159 passed, 3 errors. The 3 are the same R26 bundle tests that error on main in this environment.

## Not done here (recorded as debt, decisions for Krum / orchestrator)

1. **PostHog on main (H-2).** The package says not to touch PostHog while #88 is not on main, so the snippet bytes stay. The CSP (`script-src 'self'`) blocks that inline snippet and its remote `array.js` in the browser. In effect, main's legacy PostHog sends nothing once SEC-03 is deployed; the e2e shows exactly one blocked inline script, whose hash is the PostHog snippet's. #88's bundled posthog-js needs only `connect-src` to its host. The meta CSP adds that host when `REACT_APP_POSTHOG_KEY` is set; the nginx header must add it then too. (Orchestrator, Q1: agreed: strict CSP, legacy snippet blocked, no remote-script whitelist.)
2. **AI photo originals (§4).** The photo endpoints store nothing; they only return proposals. The canonical File Registry (W0-06) is not on main, and a second registry is forbidden (§16). Debt: "AI photo original → File Registry when W0-06 lands". Until then `ai_enabled` is off, so no photo reaches any model. (Orchestrator: agreed, recorded as debt.)
3. **`smr-analyses/{id}/ai-breakdown`** writes the AI split into analysis lines. That is existing behaviour, protected by `manual_override`, and is not changed here. Recorded as debt against §10's draft → confirm rule.
4. `frontend/plugins/visual-edits` (L-4), `.emergent/` (I-3), dependency trimming (L-5), CORS default (L-1), avatar route (L-2), X-Forwarded-For (L-3): not in this package.

## Evidence

| File | What |
|---|---|
| `01_red_on_main_1525a1e.txt` | `tests/test_sec_03_emergent_removal.py` run unchanged on an `origin/main` worktree: 16 failed, 27 errors (they need SEC-03 code), 2 passed. |
| `02_red_green_http_probe.txt` + `red_green_probe.py` | The same HTTP calls on main and on the fix. Main: reminder trigger with no credentials or a guessed key → **200, job ran**; AI → **500** "EMERGENT_LLM_KEY not configured"; main starts with the dev JWT secret. Fix: the start is refused without JWT_SECRET; with ENV=test → 401/401 (job not run), 503 "AI не е настроен". |
| `03_frontend_red_on_main_1525a1e.txt` | The two SEC-03 jest files on main's components and template: 7 failed, 2 passed (escape helper + an ordinary name). |
| `04_startup_refusal_without_jwt_secret.txt` | `uvicorn server:app` without JWT_SECRET → `JwtSecretMissing`, exit 1. |
| `e2e_fix/` | Production build + the repository's `nginx.conf` (nginx:alpine) + backend + real Mongo; the Playwright bot (`e2e_bot.js`, pre-installed Chromium) records every request. **24/24 PASS**: headers present, title BEG_Work, login and 7 screens render under the CSP, AI 503, reminder 401/403, framing by another origin blocked, requests only to the app origin and Google Fonts (none to emergent.sh / tailwind CDN / posthog), every script from the app origin. |
| `e2e_main/` | The same bot against main's build and main's `nginx.conf`: **12 FAIL**: no CSP/XFO/nosniff/Referrer-Policy, Emergent title and badge, framable, requests to `assets.emergent.sh` (10), `us-assets.i.posthog.com` (9), `cdn.tailwindcss.com` (1, framed), scripts from 3 foreign origins. |
| `05_gates.txt` | All gates, real Mongo 7.0 rs0: R0 814, W0 16 = main (identical set), PAY 630, SEC-01 30, SEC-02 31, PM-01 6/0 (matrix regenerated), A2C 0 / A1 0, warehouse 44 files / 1121, release tests 81 = main, jest 191, build, e2e 24/24. |

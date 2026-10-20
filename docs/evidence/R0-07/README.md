# R0-07 — evidence: dev reset only in dev/test (AUD-039)

Task: `docs/architecture/tasks/R0-07_DEV_RESET_DEV_TEST_ONLY.md` (on `claude/happy-meitner-bmcnel`). Base `main` @ `23f223ef`. Draft PR, not merged.

## Change
- `backend/app/routes/warehouses.py`: `POST /api/dev/reset-warehouses` has a route dependency that runs **before authentication**: unless `ENV` is explicitly `development` or `test` (trimmed, case-insensitive) → **404**, nothing read or written. `ENVIRONMENT` is no longer used. Roles: only Admin/Owner, others 403. `guarded_identity_delete` is kept. The route stays registered (the check is per request, so the behaviour follows the environment without an import-time snapshot).
- `backend/app/core/stripe_config.py`: **unchanged** (back to main; see C01).
- `backend/tests/test_w0_03e_legacy_routes.py`: the two existing reset tests now set `ENV=test` (they relied on the old fail-open default).

## Tests
- `tests/test_r0_07_dev_reset.py`: 61 passed on mongomock + real MongoDB (Docker `mongo:7.0` single-node replica set, `127.0.0.1:27018` only, `wiredTigerFileHandleCloseIdleTime=5`).
- Mutation (the same test file against `main`'s app code): 41 failed / 20 passed — cases 1, 2, 3, 5 (SiteManager/Warehousekeeper) and the gate-before-auth case fail; see `mutation_on_main.txt`.
- W0 DB-free (`tests/test_w0_*.py`): main 1085 passed / 15 failed / 50 skipped; branch 1085 / 15 / 50, identical 15 failures (`w0_*_summary.txt`).
- A1 and A2C static guards: 46 passed, 0 violations. The A1 inventory did not need regeneration.

## Bot test (local, test data only)
Backend `uvicorn server:app` on 127.0.0.1:8001 with Docker MongoDB, built frontend served on 127.0.0.1:3000, Playwright with the preinstalled Chromium (`playwright install` not run). Seed through the real API: `seed_warehouses.py`.

| Run | Result | Evidence |
|---|---|---|
| `ENV` unset, Admin via UI: reset POST from the session | **404**; list in UI and API unchanged | `01_`, `02_no_env_*.png`, `bot_result_no-env.json` |
| `ENV=test`, Warehousekeeper | **403**, nothing deleted | `bot_result_env-test.json` |
| `ENV=test`, Admin | **200**, `deleted_count: 3`; list empty | `03_`, `04_env_test_*.png` |

## Debt (not fixed)
1. **off/shadow hard delete.** With `MASTER_DATA_MODE=off|shadow`, `guarded_identity_delete` returns `None` and the route hard-deletes every warehouse of the firm without a usage check (stock, movements); only `enforce` archives used ones. Archiving instead is not a small same-file change (it needs a usage check from the master-data module), so it is left. It is reachable only in dev/test now.
2. **Production must have `ENV=production` or no `ENV`.** Anything but development/test is closed, so this is safe by default; verifying the production server's environment belongs to R0-08 (production read-only).
3. `warehouse_permission` and the other warehouse routes are untouched.

Not run: production access, migrations, merge, deploy.

## C01 (Codex F-01) — strict ENV
`is_dev_or_test_env()` normalized `ENV` (`strip().lower()`), so `TEST`, `Development`, `" test "` opened the destructive route. Now the route checks the RAW `os.environ.get("ENV")` against `("development", "test")` — no strip, no lower; anything else → 404 before auth/DB. The helper was removed and `stripe_config.py` is back to main's text: billing (`is_mock_billing_allowed`) normalizes on purpose (R0-01), so the reset got its own strict check in `warehouses.py` rather than a flag on a shared helper.
- Tests: `TEST`, `Test`, `Development`, `DEVELOPMENT`, `" test "`, `" development "`, `"test\n"`, `"development\n"`, `"\ttest"`, `"test "` → 404, byte-equal (mongomock + real Mongo); removed from positive cases. Billing normalization still holds (`test_08`).
- R0-07 + R0-01 billing + legacy-routes: 240 passed (mongomock + real). Mutation vs `af88f29`: 21 failed (20 strict-env cases + test_08), `mutation_C01_on_af88f29.txt`. W0 DB-free 1085/15/50, same 15 as main. A1/A2C guards 46 passed.
- No bot re-run: the bot's cases (unset `ENV`, `ENV=test` exact) behave exactly as before; only non-exact spellings changed, covered by the HTTP-level tests above.

# R0-04 — AUTH-01 finished on the new main (PR #56)

Task package: `docs/architecture/tasks/R0-04_AUTH_01_FINISH.md` (branch `claude/happy-meitner-bmcnel`).
Merge of `main` @ `c0e34e1` (R0-01…R0-07, R0-03 identity) into PR #56 @ `5e9700c` (C01) with a merge commit.
No rebase, no force-push, no production, no migration, no data change, no unique index.

## Conflicts (6) and how they were resolved — R0-03 is the single source for identity

| File | Resolution |
|---|---|
| `backend/app/routes/auth.py` | login = R0-03 contract + `av` claim (F-02) + `login_ambiguous` security event (F-08); `POST /users` = R0-03 (409 `EMAIL_EXISTS` / 503); PR #56's `EMAIL_NOT_AVAILABLE` check and helper imports removed |
| `backend/app/routes/platform.py` | main (R0-03 bootstrap: 409 / 503) |
| `backend/app/tenancy/onboarding.py` | main (R0-03 `installation_databases_for` + `users_with_email`) |
| `backend/app/tenancy/ownership.py` | `TECHNICAL` = main's `billing_webhook_rejections` + PR #56's `auth_rate_limits`, `auth_security_events` |
| `backend/scripts/w0_03e_a2c_tenant_boundary_guard.py` | main's lists + `reset_user_password.py` operator script; `auth_duplicate_emails_report.py` removed |
| `docs/architecture/W0-03E-A2B_INVENTORY.md` | regenerated with `scripts/w0_03e_a2b_inventory.py` (§2 identical to main) |

Removed (duplicates of R0-03): `app/utils/email_identity.py`, `data_access.resolve_identities_by_email`,
`scripts/auth_duplicate_emails_report.py`. Forgot-password and the CLI now use `app.tenancy.identity`
(`normalize_email`, `users_with_email`) on the login registry.

## Behaviour after the merge

| Case | Result |
|---|---|
| Forgot-password, email held by >1 User | same generic 200, no token, `forgot_ambiguous` security event |
| Login, duplicate email | R0-03 unchanged: 401 unless a password matches, then 409 `DUPLICATE_IDENTITY` + `auth.login_refused` AuditEvents; now also `login_ambiguous` |
| Old JWT after reset / recovery | 401 (F-02, `av` ≠ `auth_version`) |
| Successful reset | legacy `audit_logs` row + canonical W0-04 AuditEvent `user.password_reset` in the same transaction; no password/hash/token |
| Successful CLI recovery | legacy row + AuditEvent `user.password_recovery_cli` (actor_type `system`) in the same transaction |
| Standalone MongoDB | refused before any write: reset 503 `RESET_NOT_COMPLETED`, forgot generic 200 with no token (`forgot_processing_failed` event), CLI exit 7 — **required R0-08 production check: replica set** |

`app/audit/store.record_event` and `user_role_policy.audit_user_change` take an optional `session`
(default unchanged) so the AuditEvent joins the transaction.

## Tests

| Suite | Result |
|---|---|
| `tests/test_auth_01_*.py` + `tests/test_r0_0*.py`, mongomock | **490 passed**, 391 skipped (real-Mongo-only cases) |
| same, real MongoDB 7.0 replica set (Docker, `127.0.0.1:27019`) | **881 passed**, 0 skipped |
| `tests/test_auth_01_*.py` alone, real MongoDB | 67 passed |
| W0 DB-free `tests/test_w0_*.py` | **1085 passed / 15 failed / 50 skipped** — the same 15 pre-existing `test_w0_03e_legacy_routes` failures as main |
| A2C guard / A1 guard | 210 modules / 424 units, **0 violations** |
| Frontend `yarn test` / `yarn build` | 101/101 passed / exit 0 |

F-01…F-08 after the merge (tests in `test_auth_01_c01_corrections.py` unless noted):
F-01 `test_f01_*` (failure injection at every boundary, + `test_a_failing_audit_event_rolls_the_whole_reset_back`,
`test_the_audit_event_is_inside_the_transaction` in `test_auth_01_r0_04_merge.py`) ·
F-02 `test_f02_*`, `test_old_jwt_is_refused_after_a_reset_new_login_works` ·
F-03 `test_f03_*` (now R0-03's 409 + single implementation) ·
F-04 `test_f04_*` (trusted proxies, shared limiter) · F-05 `test_f05_*` · F-06 `test_f06_*` ·
F-07 `test_f07_*` (hidden prompt only) · F-08 `test_f08_*`, `test_duplicate_identity_login_contract_is_unchanged_and_recorded`.

### Mutation

- `mutation_on_5e9700c.txt`: the new / changed tests against the C01 head: 8 fail, 3 pass. The 3 passing
  (forgot duplicate, old JWT, standalone refusal) are behaviours C01 already had; they guard them through
  the merge. On `main` every AUTH-01 test fails (no reset endpoint exists there).
- `mutation_merged_mutants.txt`: 6 mutants of the merged code, mongomock and real MongoDB — all killed
  (M3 "AuditEvent outside the transaction" is killed only on the real replica set, by
  `test_the_audit_event_is_inside_the_transaction`; mongomock has no real transactions).

## Bot test — PASS (`bot_result.json`, 15/15)

Local backend (`uvicorn`, `ENV=test`, random `JWT_SECRET`, no SMTP, `PASSWORD_RESET_DEV_LOG_URL=1`),
MongoDB replica set in Docker, `yarn build` served on 127.0.0.1:3000, Playwright Chromium. Firm seeded
through `POST /billing/signup` (`seed_firm.py`). Script: `password_recovery_bot.js`.

1. `00_old_session_logged_in.png` — tab A logged in with the old password.
2. `01_forgot_generic_confirmation.png` — login → „Забравена парола?“ → email → generic confirmation.
3. `02a_reset_success.png`, `02b_login_with_new_password.png` — link from the dev log → new password → login; the old password → 401.
4. `03_old_session_rejected_to_login.png` — tab A's next navigation → `/login`; API `/auth/me` with the old JWT → 401.
5. `04_reused_link_invalid.png` — the same link again → „невалиден линк“; the password is unchanged.
6. `05_{375,1280}px_{login,forgot,reset}.png` — `scrollWidth == innerWidth` on every page.

`audit_bot_db.json`: the bot database afterwards — one `user.password_reset` AuditEvent, the legacy rows,
one `reset_token_replay` security event, the token row (`used_at` set, no hash), `auth_version: 1`.
The reset token appears in no committed file (checked).

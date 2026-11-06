# R0-03 — evidence: roles without escalation, one email = one User (AUD-025, AUTH-01 F-03)

Task: `docs/architecture/tasks/R0-03_ROLES_EMAIL.md` (on `claude/happy-meitner-bmcnel`). Base `main` @ `db94561`. Draft PR, not merged.

## Where things are decided

| Question | Answer in the code |
|---|---|
| Role hierarchy | `app/services/user_role_policy.py`: `Owner` > `Admin` > others. Own role → 403; grant above own (also on `POST /users`) → 403; only an Owner changes an Owner's role / `is_active`, resets its password or deletes it → 403; last active Owner demoted/deactivated/deleted → 409. All before any write. |
| Actor rank, `off`/`shadow` | `users.role` — it is what decides authorization in these modes. |
| Actor rank, `enforce` | Only the FLOW-002 RoleAssignments of the active tenant (company scope, active, in validity) — the records the Permission Service decides from. No fallback to `users.role`. The Permission Service gives `owner` and `admin` the same actions, so it holds no hierarchy; R0-03 adds it on top. No second source of roles. A target counts as an Owner if either source says so. |
| Last-Owner count | tenant `users` with role `Owner`, active (counting fewer can only refuse more). |
| User registry, `off`/`shadow` | the global legacy `users` collection (login and the session loader read only it). |
| User registry, `enforce` | `POST /users` writes into `ctx.db()`. The email check covers the global DB **and** every database the Tenant Registry names (`app/tenancy/identity.py: installation_databases`). `off`/`shadow` never touch the registry. |
| Normalization | `strip().lower()` on create (stored normalized), login and every check. Old rows are matched case-insensitively with surrounding whitespace (`email_match_filter`) and re-checked in Python. |
| Creation paths | `POST /users` (off/shadow and enforce), `POST /billing/signup` → `onboard_tenant` (and `scripts/create_company.py` through it), platform bootstrap (idempotent contract kept: an existing identity in any spelling → `created: false`, nothing written), installation seed. All → 409 `EMAIL_EXISTS` (bootstrap: no write). |
| Email change | No route after A1: `/employees/{id}/basic` refuses `email`; `PUT /users` has no email field. |
| Login | >1 User for the email: wrong password → 401 as usual; correct password of one of them → 409 `DUPLICATE_IDENTITY`, no token, generic message, one canonical AuditEvent per affected firm. |
| AuditEvent | canonical W0-04 envelope (FLOW-040, R3) next to the existing legacy `audit_logs`: `user.role_status_changed` (before/after of role / is_active), `user.admin_password_reset` (no hash), `user.deleted` (off/shadow; in master-data enforce the adapter already writes its own event), `auth.login_refused`. |
| Unique index | `ensure_user_email_unique_index` (collation `en`/strength 2 on `users.email`) is prepared and **not called**. Collation instead of a second `email_normalized` field: no backfill, no extra field every path must keep in sync. It does not fold whitespace — the report lists such rows. |

## Tests
- `tests/test_r0_03_roles_email.py`: **304 passed** (151 cases on mongomock + the same 151 on real MongoDB + 2 backend-independent; Docker `mongo:7.0`, single-node replica set, `127.0.0.1:27019`). Every role row runs in `off`, `shadow` and `enforce`.
- Together with the touched suites (`test_w0_02_pr_fixes`, `test_w0_03e_a2b_onboarding_bootstrap`, `test_w0_03e_legacy_routes`, `test_r0_07_dev_reset`, `test_r0_05_pay_run_selected_only`), mongomock + real: 661 passed / 15 failed — the 15 are the pre-existing `test_w0_03e_legacy_routes` failures, identical to main (`tests_branch_mongomock_and_real.txt`).
- Mutation (the same test file against `main`'s app code, mongomock): **123 failed / 30 passed**. Rows 1, 2, 4, 5, 6, 7, 8, 11, 12 fail on main (so do 10, 13 and the AuditEvent checks of 6b/7b/9); the 30 passing are positive/isolation rows (3, 5b, 8b, 9b, 10d, 14, 15b) — `mutation_on_main.txt`.
- W0 DB-free (`tests/test_w0_*.py --noconftest`): main **1085 / 15 / 50**; branch **1085 / 15 / 50**, the same 15 failures (`w0_*_summary.txt`).
- A1 and A2C guards: **0 violations** (203 modules / 412 units); static guard tests 61 passed.
- Changed existing assertions (400 → 409 `EMAIL_EXISTS`, a deliberate contract change of the task): `test_w0_03e_a2b_onboarding_bootstrap.py` (signup duplicate), `test_w0_02_pr_fixes.py` (enforce duplicate, 2 lines).
- Guard tiers: `app/tenancy/identity.py: users_with_email` added to `PRE_TENANT_FUNCTIONS` (`users` only — the search is across tenants on purpose); the report script added to `OPERATOR_SCRIPTS` + `READ_ONLY_DIAGNOSTIC`. `docs/architecture/W0-03E-A2B_INVENTORY.md` regenerated (line numbers; the global email read moved from `onboarding.py` into `identity.users_with_email`). A1 inventory unchanged. The A2C inventory doc was already stale on main since R0-01 and is not test-enforced; not regenerated here (would mix unrelated drift).

## Bot test (local, test data only) — PASS
Backend `uvicorn server:app` on 127.0.0.1:8001 (`DB_NAME=r003_bot`, `BEG_SYSTEM_DB=r003_bot_system`, `ENV=test`, `BILLING_PROVIDER=mock`, random `JWT_SECRET`, `PERMISSION_SERVICE_MODE` default `off`), Docker MongoDB, `yarn build` served on 127.0.0.1:3000, Playwright with the preinstalled Chromium. Seed through the real API (`seed_roles.py`); for step 5 only, `plant_legacy_duplicate.py` copies one user into the other firm in the disposable DB (the API can no longer create a duplicate).

| Step | Result | Evidence |
|---|---|---|
| 1 Accountant: own card; `/basic role=Admin` → 400, `/basic email` → 400, `PUT /users/self` → 403; role still Accountant | PASS | `01_`, `02_accountant_card_*.png` |
| 1b Admin: employee edit form — role/email locked; name+phone save works (no 400) | PASS | `03_`, `03b_*.png` |
| 2 Admin → Owner's password via UI → refused; API 403; demote/delete Owner 403; grant Owner 403; Owner logs in with old password | PASS | `04_admin_reset_owner_password_refused.png` |
| 3 Owner → Admin becomes Наблюдател (Viewer) | PASS | `05_owner_changed_admin_to_viewer.png`, `audit_events_bot_db.json` |
| 4 Firm B Owner creates `  Admin@R003A.test ` (firm A's email) → alert, API 409 `EMAIL_EXISTS`, nothing created, no firm named | PASS | `06_firm_b_create_with_firm_a_email_refused.png` |
| 5 Login `IVAN@r003b.test` held by 2 users → message on the login page, no token, API 409 `DUPLICATE_IDENTITY` | PASS | `07_login_duplicate_identity_refused.png` |

All assertions: `bot_result.json`. Duplicates report on the bot DB (dev data): **1 duplicated email, 2 users** — the planted one (`duplicates_report_bot_db.json`, masked).

### UI changes (minimal, forced by the change)
- `EmployeeDetailPage.js`: the save sent `role` and `email` to `/basic` on every save — it would now always get 400. It sends only name and phone; the email and role fields are shown read-only.
- `LoginPage.js`, `SignupPage.js`: they rendered `detail` directly in JSX; an object detail (`{error_code, message}`) would crash React. They show `detail.message` (or the string as before). Same one-liner in `UsersPage.js` / `EmployeesPage.js` / `EmployeeDetailPage.js` alerts (no `[object Object]`).

## Debt (not fixed)
1. **Approval** for changes that touch an Owner (CLAUDE.md §8) — the canonical DQ/Approval runtime does not exist yet (W0); the rule is "only an Owner".
2. **Unique index** on `users.email` — prepared (`ensure_user_email_unique_index`), run only after the duplicates report is clean and Krum's "да" (R0-09). Until then two concurrent creations of the same new email can both pass the check.
3. **Merging existing duplicates** (R0-09). Such accounts cannot log in (409) until resolved.
4. **Full User / TenantMembership model** (R0-04 / PR #56).
5. Last-Owner check is not atomic (two Owners demoting each other at the same instant could both pass) — no multi-document transaction in the legacy path.
6. `enforce` retry of an interrupted `PUT /users` re-reads the already-changed target, so a lost R0-03 AuditEvent is not re-written on retry (the legacy audit and permission events are).
7. `scripts/promote_platform_admin.py` finds and updates by exact email (not normalized; with duplicates it takes the first) — operator script, out of scope.
8. Off/shadow `POST /users` checks the plan's user limit before the email (pre-existing order): a full firm gets 403 LIMIT before 409.
9. Off/shadow `DELETE /users` is still a hard delete for an unused user (pre-existing; master-data enforce archives).
10. `AdminResetPasswordModal` shows its generic "password reset failed" for the 403 (it ignores non-string details) — not changed.

Not run: production access, migrations, data changes, index creation, merge, deploy.

## C01 (Codex F-01..F-04, review of `dcaf204`)
- **F-01** `app/services/user_role_policy.py`: in `enforce` the decision "this target is an Owner" and the count of the OTHER active Owners come from active, company-scoped, currently valid `owner` RoleAssignments of the tenant whose User is an active user of this tenant (`registry.list_tenant_role_assignments`, new, tenant-scoped). `off`/`shadow` unchanged (`users.role`). This applies to `PUT /users` (role and `is_active`) and to `DELETE`. In enforce a `role` equal to a stale `users.role` mirror still counts as a change when the target holds an owner assignment (the sync would revoke it). Self-delete is still 400.
- **F-02/F-03** `app/tenancy/identity.py`: one fail-closed enumeration (`_scan`). It covers the global DB plus every `tenant_registry` record's database. A record with no, empty or non-string `database_name`, or a database that cannot be opened, raises `IdentityCheckUnavailable`. Callers:
  - `POST /users` (enforce; off/shadow still read only the global DB and never the registry, as W0-02 PR-05 requires);
  - onboarding / signup (`installation_databases_for`; refuses before its first write, signup answers 503);
  - platform bootstrap (any existing spelling anywhere → **409 `EMAIL_EXISTS`**, nothing written — the "already exists" audit row is gone too; uncheckable → 503);
  - seed (skips, writes nothing; logs masked emails only).
  - The live-server tests in `tests/test_platform_bootstrap.py` now expect 409 (not run here: they need a running server).
- **F-04** `POST /auth/change-password`: canonical W0-04 AuditEvent `user.own_password_change` on success (`result=success`) and on a wrong current password (`result=denied`, `error_code=INVALID_CURRENT_PASSWORD`), with no diff, password or hash. The legacy `log_audit` rows stay.
- **Tests:**
  - `test_r0_03_roles_email.py`: **362 passed**, mongomock + real MongoDB.
  - All `tests/test_r0_0*.py` together with `test_w0_02_pr_fixes`, A2B onboarding and legacy routes: 927 passed / 15 failed — only the pre-existing legacy-routes 15 (`c01_tests_mongomock_and_real.txt`).
  - Mutation, the C01 test file against `dcaf204` (mongomock): 31 failed / 151 passed. Every new F-01..F-04 test fails there; the passing ones are the earlier rows plus the two positive controls (seed of a new email, self-delete still 400) (`mutation_C01_on_dcaf204.txt`).
  - W0 DB-free: 1085 / 15 / 50, the same 15 (`w0_branch_C01_summary.txt`).
  - A2C / A1: 0 violations.
  - `W0-03E-A2B_INVENTORY.md` regenerated: line numbers, and two fewer raw `users` reads, because seed and bootstrap now go through `identity.users_with_email`.
- **No UI change**, so no bot re-run.

## C02 (Codex re-review of `eda9b8c`; F-01, F-04 closed)
- `POST /users` now checks the email across the whole installation **in every mode**, and fails closed (503 `IDENTITY_CHECK_UNAVAILABLE`) around the full enumeration **and** the search; nothing is written in either case. The write still goes to the mode-selected database.
  - `off`/`shadow` use `installation_databases_for(global_db, registry.system_db)`. This is the same direct read-only `tenant_registry` path as onboarding: no resolver, no Permission Service, so W0-02 PR-05 still holds.
  - `enforce` is unchanged.
  - `users_with_email` also turns an unreadable database into `IdentityCheckUnavailable`. Onboarding now covers its search with the same guard.
- `test_11d` was replaced by `test_11d*` (off and shadow, mongomock + real):
  - a foreign-DB duplicate (`CROSS@example.com` vs `cross@example.com`) → 409, no write;
  - a registry record with no, empty or non-string `database_name` → 503, byte-equal state (operational and system DB);
  - a fresh email with a healthy registry → 201, written to the mode's DB.
  - Each asserts that the resolver is not called, and that the Permission Service is not called in `off`.
- **Results:**
  - `test_r0_03_roles_email.py`: **388 passed** (mongomock + real).
  - All `test_r0_0*` plus W0-02 PR fixes, A2B onboarding and legacy routes: 953 passed / 15 failed — only the pre-existing legacy-routes 15 (`c02_tests_mongomock_and_real.txt`).
  - Mutation against `eda9b8c`: 12 failed (every 11d / 11d2 case); 11d3, the fresh-email positive control, passes on both (`mutation_C02_on_eda9b8c.txt`).
  - W0 DB-free: 1085 / 15 / 50, the same 15.
  - A2C / A1: 0.
  - A2B inventory regenerated (line numbers only).
- No UI change, so no bot run.

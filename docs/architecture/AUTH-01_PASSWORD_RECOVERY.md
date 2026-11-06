# AUTH-01 — Owner access recovery + Forgot Password MVP

> Scope: OWNER-FIRST PILOT (Issue #52, package comment 6196842918). Not commercial SaaS hardening.
> C01: corrections to CODEX review CHANGES_REQUESTED F-01…F-08 (PR #56 comment 6216184918).
> R0-04: merged onto `main` after R0-03 (identity) — R0-03 is the single source for the email identity.
> Status: Draft PR #56, awaiting CODEX independent re-review. Not a production PASS.

## What exists

| Path | Who | What |
|---|---|---|
| `backend/scripts/reset_user_password.py` | operator, server shell only | break-glass: sets the OWNER's password (AUTH-02: Owner only, `--operator` + `--reason` required, Owner notified); dry run first; hidden prompt only |
| `backend/scripts/r0_03_email_duplicates_report.py` (R0-03) | operator | READ-ONLY list of emails shared by several users |
| `POST /api/auth/forgot-password` | anyone | always the same 200 answer; all account-dependent work runs after the response |
| `POST /api/auth/reset-password` | holder of the link | consumes the token once and sets the password, atomically |
| `POST /api/auth/change-password` | logged-in user | unchanged (does not end other sessions) |
| `POST /api/admin/set-password/{id}` | Admin/Owner, for ANOTHER user | self still refused; AUTH-02 (FG-11): one transaction, ends the target's older sessions and revokes their open links |
| `/forgot-password`, `/reset-password?token=…` | browser | screens; login shows "Забравена парола?", demo credentials removed |

There is **no** HTTP recovery endpoint that bypasses the token. The CLI is the emergency path.

## Owner decisions applied in C01

* **One email = one User across the installation** (F-03, decision Р6). Since R0-04 this is exactly the
  R0-03 implementation, `app/tenancy/identity.py` (`normalize_email`, `users_with_email`, whole-installation
  fail-closed search): `POST /users`, onboarding, bootstrap and seed answer 409 `EMAIL_EXISTS` /
  503 `IDENTITY_CHECK_UNAVAILABLE`. PR #56's own helper (`app/utils/email_identity.py`,
  `resolve_identities_by_email`) and report script were removed in the merge.
* **Existing duplicates** (listed by `scripts/r0_03_email_duplicates_report.py`) stay fail-closed until
  fixed by hand: login keeps the R0-03 contract (401, or 409 `DUPLICATE_IDENTITY` only for a caller who
  knows one of the passwords) and now also writes a `login_ambiguous` security event; forgot-password
  answers the same generic 200, mints no token and writes `forgot_ambiguous`; the CLI exits 3.
  Forgot-password and the CLI read the same registry as login (the global `users` collection).
* **Security events kept 730 days** (F-08, TTL; AUTH-02 / FG-10: FLOW-040 §R3 requires ≥ 2 years — the earlier 180 days had no recorded decision).
* **HMAC key** (AUTH-02 / FG-16): `AUTH_EVENT_HMAC_KEY` or `JWT_SECRET` must be set; the built-in dev key is used only when `ENV`/`ENVIRONMENT` explicitly label a non-production deployment, otherwise the auth surface fails closed.

## Atomicity (F-01) — MongoDB transactions

`app/services/auth_tx.py` runs each multi-document auth change in ONE transaction:

| Operation | In one transaction |
|---|---|
| reset-password | conditional token claim · new hash · `$inc auth_version` · revoke remaining tokens · audit `password_reset_completed` · W0-04 AuditEvent `user.password_reset` |
| recovery CLI | new hash + marker `LOCAL_RECOVERY_CLI` (filter: active **Owner**) · `$inc auth_version` · revoke open tokens · audit `password_recovery_cli` (with operator + reason) · W0-04 AuditEvent `user.password_recovery_cli` (`actor_type=human`, `actor_id=break_glass:<operator>`, reason, `source_channel=break_glass_cli`, **R1**) · one in-app notification per active Owner |
| admin set-password (AUTH-02) | new hash · `$inc auth_version` · revoke the target's open tokens · audit `admin_password_reset` · W0-04 AuditEvent `user.admin_password_reset` |
| forgot (mint) | insert `pending` token · audit `password_reset_requested` |
| forgot (settle) | delivered: mark `sent` + revoke OLDER tokens + audit · not delivered: revoke ONLY the new token + audit |

A failure inside leaves everything as it was. The API answers **503 `RESET_NOT_COMPLETED`** ("the password
was not changed"); the CLI exits **6** ("NOTHING CHANGED"). Transactions need a **replica set**
(MongoDB Atlas is one). On a standalone `mongod` these operations are refused before any write
(API 503, CLI exit **7**). For local development run `mongod --replSet rs0` + `rs.initiate()`.

### Standalone MongoDB (no replica set) — exact behaviour (R0-04)

`auth_tx.transactions_supported` asks the server (`hello`: `setName` or `mongos`); on a standalone it is
false and `run_in_transaction` raises `TransactionsUnavailable` **before the first write**:

| Path | Answer | Written |
|---|---|---|
| `POST /auth/reset-password` | 503 `{"error_code": "RESET_NOT_COMPLETED"}` | nothing (password, token, `audit_logs`, `audit_events` unchanged); only a `reset_not_completed` security event |
| `POST /auth/forgot-password` | the generic 200 (the work runs after the response) | no token, no mail; only a `forgot_processing_failed` security event |
| `scripts/reset_user_password.py` | exit **7** "NOTHING CHANGED" | nothing |

Login, change-password and admin reset do not use transactions and are not affected.
**Required R0-08 production check:** prove the production MongoDB is a replica set
(`db.hello().setName` non-empty, `isWritablePrimary: true`) before AUTH-01 is enabled; otherwise
forgot/reset/recovery silently produce no links and every reset answers 503.

## Sessions end after recovery (F-02)

`users.auth_version` (absent = 0). Every JWT carries `av`. `get_current_user` refuses a token whose `av`
differs from the user's `auth_version` (401 "Session expired"). Self-service reset and the recovery CLI
increment it, so every session issued before the recovery stops working. Tokens and users that predate
this are both version 0 and keep working.

## Recovery command (server shell)

Inside the backend container:

```
python scripts/reset_user_password.py --email Krum@begfull.bg \
    --operator "Иван Петров" --reason "Owner locked out, ticket 123" --dry-run   # look, write nothing
python scripts/reset_user_password.py --email Krum@begfull.bg \
    --operator "Иван Петров" --reason "Owner locked out, ticket 123"             # hidden prompt, twice
```

AUTH-02 (Р19): `--operator` (2–120 chars) and `--reason` (10–500 chars) are required — blank, control
characters, a password hash or the new password itself are refused before anything is written. Only an
`Owner` can be recovered this way (FG-8); other users are reset by their Owner/Admin in the app. After the
commit every active Owner of the tenant has an in-app notification (written in the same transaction) and,
when SMTP is configured, an e-mail (best effort).

The password can be entered **only** at the hidden prompt (F-07). There is no argument or stdin option,
and the command refuses to run without a terminal: use `docker exec -it`. Exit codes: 0 ok · 1 usage/no
terminal · 2 not found · 3 ambiguous · 4 disabled/unusable · 5 invalid password · 6 nothing changed (no
commit) · 7 nothing changed (no transactions) · 8 not an Owner (nothing changed). It never prints the password or a hash.

Fast-path files for a container that does not yet include this PR: `scripts/reset_user_password.py`,
`app/tenancy/identity.py` (R0-03), `app/services/auth_tx.py` and `app/services/user_role_policy.py`
(+ `app/audit/`). Prefer deploying the whole merged PR.

## Forgot / reset flow

1. **Before the response (F-05):** the shared per-IP limit and scheduling one background task. The
   handler does identical work for every email.
2. **After the response** (`password_reset.process_forgot_request`): per-email limit → exactly one active
   user (else a security event) → mint a `pending` token (SHA-256 stored only) → send → settle.
3. **Delivery (F-06):** `delivery_status` is `pending → sent | dev_logged | failed | not_configured`.
   A failed or unconfigured delivery revokes only the new token; the user's older links stay usable.
   No automatic retry; the user asks again (3 per 15 min).
4. **Reset:** policy check → token pre-checks (each failure is one generic 400 + a security event) →
   the transaction above.

Collection `password_reset_tokens` (org-keyed): `id, org_id, user_id, token_hash, requested_at,
expires_at, used_at, requested_ip, delivery_status` (+ `revoked_reason`). Indexes: unique `token_hash`,
TTL `expires_at`, `(user_id, used_at)`.

## Rate limits (F-04)

`app/services/rate_limit.py`: shared atomic counters in MongoDB (`auth_rate_limits`, fixed window,
`$inc`+upsert, TTL). All workers/instances on the same database share them. Keys are keyed HMACs.
Fail closed.

| Limit | Value | Over the limit |
|---|---|---|
| forgot per IP | 10 / 15 min | 429 |
| forgot per email | 3 / 15 min | silent (same 200) |
| reset per IP | 20 / 15 min | 429 |

`app/utils/client_ip.py`: the client IP is the socket peer. `X-Forwarded-For` / `X-Real-IP` count
**only** when the peer is in `TRUSTED_PROXIES` (comma-separated IPs/CIDRs). The chain is walked from the
right. **Synology:** set `TRUSTED_PROXIES` to the docker network of the nginx container (e.g.
`172.16.0.0/12`). Without it every visitor shares nginx's IP: safe, but the per-IP limits then apply to
everyone together.

## Security events (F-08)

`app/services/auth_events.py` → `auth_security_events` (TECHNICAL, TTL 730 days): `id, ts, expires_at,
event, ip, subject (keyed HMAC of the email), token_ref (token row id or keyed HMAC), org_id, user_id,
detail`. No email, token or password is stored. HMAC key: `AUTH_EVENT_HMAC_KEY`, else `JWT_SECRET`.

Events: `forgot_no_match`, `forgot_ambiguous`, `forgot_not_eligible`, `forgot_processing_failed`,
`rate_limited_ip`, `rate_limited_email` (once per window), `reset_token_invalid`, `reset_token_expired`,
`reset_token_replay`, `reset_user_inactive`, `reset_not_completed`, `reset_delivery_failed`,
`reset_delivery_not_configured`, `login_ambiguous`. Successful actions stay in the tenant's `audit_logs`;
a successful reset / recovery also writes the canonical W0-04 AuditEvent (FLOW-040 R3, `audit_events`,
via `user_role_policy.audit_user_change`) inside the same transaction — no password, hash or token.

## E-mail (`app/services/mailer.py`)

| Variable | Meaning |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` (default 587) | SMTP server |
| `SMTP_USER`, `SMTP_PASSWORD` | optional login |
| `SMTP_FROM` | sender, e.g. `BEG_Work <no-reply@begfull.bg>` |
| `SMTP_SECURITY` | optional `ssl` / `starttls` / `none` (default: `ssl` on 465, else `starttls`) |
| `APP_PUBLIC_URL` | browser origin; the link is `APP_PUBLIC_URL/reset-password?token=…` |
| `PASSWORD_RESET_DEV_LOG_URL=1` | LOCAL DEV ONLY: print the link when no e-mail is configured; ignored with `ENV=production` |

## Known limits / debt (recorded, not fixed here)

1. `app/routes/platform.py` bootstrap still uses its own in-memory limiter and trusts `X-Forwarded-For`
   (outside AUTH-01 scope).
2. Email uniqueness is enforced in application code (R0-03); the unique index is prepared, not created
   (R0-09). Two simultaneous creates of the same new email could still race.
3. Forgot-password / the CLI search the login registry (global `users`) like login does, not every tenant
   database. Today every tenant resolves to that database; when a tenant database moves out, login and
   recovery move together (R0-04 debt, R0-03 "Access to companies is a TenantMembership question").
4. Mint / settle / denials still write only the legacy `audit_logs` + security events; the canonical
   AuditEvent is written for the successful reset and recovery.
5. Change Password and Admin Reset do not end other sessions (kept as before, per review).
6. Transactions need a replica set — required R0-08 production check (above).

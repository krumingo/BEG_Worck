# AUTH-01 — Owner access recovery + Forgot Password MVP

> Scope: OWNER-FIRST PILOT (Issue #52, package comment 6196842918). Not commercial SaaS hardening.
> Status: implementation on a Draft PR, awaiting CODEX independent review. Not a production PASS.

## What exists after AUTH-01

| Path | Who | What |
|---|---|---|
| `backend/scripts/reset_user_password.py` | operator, server shell only | sets ONE active user's password; dry run first |
| `POST /api/auth/forgot-password` | anyone | always the same 200 answer; mints a 30-min one-time token for exactly one active user and e-mails the link |
| `POST /api/auth/reset-password` | holder of the link | consumes the token once and sets the password |
| `POST /api/auth/change-password` | logged-in user | unchanged |
| `POST /api/admin/set-password/{id}` | Admin/Owner, for ANOTHER user | unchanged (self is still refused) |
| `/forgot-password`, `/reset-password?token=…` | browser | new screens; login shows "Забравена парола?", demo credentials removed |

There is **no** HTTP recovery endpoint that bypasses the token. The CLI is the emergency path.

## Recovery command (server shell)

Inside the backend container (`begwork-backend`, workdir `/app`):

```
python scripts/reset_user_password.py --email Krum@begfull.bg --dry-run   # look, write nothing
python scripts/reset_user_password.py --email Krum@begfull.bg             # asks the password twice, hidden
```

Exit codes: 0 ok · 1 usage · 2 not found · 3 ambiguous (case-only duplicate) · 4 disabled/unusable ·
5 invalid password · 6 write did not apply. It never prints the password or a hash. It writes
`password_reset_at`, `password_reset_by = LOCAL_RECOVERY_CLI`, revokes the user's open reset links and
adds an `audit_logs` row `password_recovery_cli`.

## Tokens

Collection `password_reset_tokens` (org-keyed, classified in `app/tenancy/ownership.py`):
`id, org_id, user_id, token_hash, requested_at, expires_at, used_at, requested_ip` (+ `revoked_reason`).

* plaintext = `secrets.token_urlsafe(32)`; stored = SHA-256 hex only;
* indexes (created at startup, `password_reset.ensure_indexes`): unique `token_hash`,
  TTL `expires_at` (`expireAfterSeconds=0`), `(user_id, used_at)`;
* a new request revokes the user's older open tokens; a successful reset revokes all remaining ones;
* single use = one conditional `find_one_and_update` on `used_at: None` and not expired;
* the token is claimed BEFORE the password write — a crash in between leaves the old password and a spent
  link (ask again), never a reusable link behind a changed password.

## E-mail (provider abstraction, `app/services/mailer.py`)

| Variable | Meaning |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` (default 587) | SMTP server |
| `SMTP_USER`, `SMTP_PASSWORD` | optional login |
| `SMTP_FROM` | sender, e.g. `BEG_Work <no-reply@begfull.bg>` |
| `SMTP_SECURITY` | optional `ssl` / `starttls` / `none` (default: `ssl` on 465, else `starttls`) |
| `APP_PUBLIC_URL` | browser origin; the link is `APP_PUBLIC_URL/reset-password?token=…` |
| `PASSWORD_RESET_DEV_LOG_URL=1` | LOCAL DEV ONLY: print the link to the console when no e-mail is configured; ignored with `ENV=production` |

Without `SMTP_HOST`/`SMTP_FROM`/`APP_PUBLIC_URL` the API answers exactly the same and the server logs
`PASSWORD_RESET_EMAIL_NOT_SENT` (no token, no link). Delivery runs after the response (background task),
and a provider failure is logged as `PASSWORD_RESET_EMAIL_FAILED` without the link.

## E-mail comparison

`app/utils/email_identity.py`: `strip().lower()`, bounded (254), escaped + anchored case-insensitive
regex, re-checked in Python. Used by login, forgot-password, the CLI and the user-create duplicate check
(per organization, as before). Nothing stored is rewritten. **More than one row matching up to letter
case = ambiguous → refused** (login 401 + server warning `LOGIN_REFUSED_AMBIGUOUS_EMAIL`, no token,
CLI exit 3 listing the rows).

## Rate limits (MVP, existing in-memory `RateLimiter`, per process)

forgot-password: 10 / 15 min per IP (429) and 3 / 15 min per e-mail (silent, same 200);
reset-password: 20 / 15 min per IP (429).

## Known limits / debt (recorded, not fixed here)

1. Rate limits are in-memory per process and keyed on `get_client_ip`, which trusts `X-Forwarded-For`.
2. Login and forgot-password read `users` by email across the installation; e-mail uniqueness is still
   per organization (unchanged business rule). The same address in two organizations is now refused as
   ambiguous instead of resolved to whichever row MongoDB returned first.
3. Audit rows use the legacy `log_audit` (`audit_logs`) like the existing auth routes, not the W0-04
   canonical AuditEvent envelope.
4. The password write and the token revocation are separate writes (no multi-document transaction);
   the ordering above keeps the failure mode safe.
5. A known account does a few more database writes than an unknown one before the identical response;
   the e-mail itself is sent after the response.

# MEDIA-SEC-01 — media findings of FLOW Guard pass 44 (FLOW-029 sweep on main 3863610)

Branch `claude/media-sec-01` from main `3863610`. Canon: CLAUDE.md §2 rules 9 and 11, §3, §4, §14, §15; FLOW-029.

| Finding | Severity | Fix |
|---|---|---|
| FG-540 | HIGH | `GET /api/media/avatar/{filename}` needs a login (no token → **401**). The file is resolved ONLY through a non-retired `media_files` row of the caller's tenant with `context_type="profile"`; the disk path is built from that row's `stored_filename` (strict `{name}.{ext}` shape, must sit directly in the upload dir). Another tenant's avatar, a non-avatar media file (site photo / receipt / OCR invoice), an orphan file on disk, an unknown name and every traversal probe → the same **404**. Frontend: every avatar `<img src>` now goes through `components/AuthImage.js` (authenticated `API.get(..., {responseType: "blob"})` → `blob:` URL, the app's existing PDF pattern). |
| FG-542 | HIGH | `DELETE /api/media/{id}` never deletes. Linked file, or a file used by a missing-SMR attachment / client-approval signature, a scanned document, an OCR intake or a user's avatar → **409 `MEDIA_IN_USE`**, nothing written. An unused file → `status="retired"` (+ reason, who, when), the row and the original file stay, one transaction with the canonical AuditEvent **`media.file.retire`** (`project.photo.retire` pattern: reason + `Idempotency-Key` required, replay returns the same answer). Retired files are hidden from `GET /api/media`, and their file is served to Owner/Admin only. |
| FG-541 | medium | Project photos — list, upload, file, retire — check `can_access_project` (the check `GET /projects/{id}` uses). Non-member → **403** before the upload is read: no file, no row, no audit row. Verified in off, shadow and enforce. A removed uploader can no longer retire. |
| FG-556 | medium | (pass 45 on 35df04e) `_media_usages` also covers `work_reports.photos`, `extra_work_drafts.photos`, `pending_expenses.media_id`/`media_url` and `finance_payments` receipt references (by id, stored name or `/api/media/...` url, plain list or sub-document) → **409 `MEDIA_IN_USE`**. Another tenant's row never blocks. No writer on 3863610 stores a receipt on `finance_payments` yet; the check covers `media_id`, `receipt_media_id(s)`, `receipt_file_id`, `receipt_url`, `attachments.media_id/url` so the first writer is protected. |
| FG-558 | low | (pass 45) `GET /api/media/{id}` of a retired file → **404** for non-Owner/Admin (the owner of the file included). |
| FG-544 | medium | `POST /api/media/link` refuses to re-link an already linked file (**409 `MEDIA_ALREADY_LINKED`**); linking to the SAME record again is a no-op 200; a retired file → 409. The write is a compare-and-set on "still unlinked". Additive only — no FLOW-029 archive model. |

## Krum's decisions R83 (10.11.2026), implemented

| # | Decision | Implementation |
|---|---|---|
| R83(1) | A project Viewer, even a member, only reads photos | The one upload guard (`app/deps/upload_guard.py`, FG-575) at every upload entry point: company role `Viewer` or project role `Viewer` → **403** before the file is read (no file, no row). List/file stay readable for members. Off / shadow / enforce tested. |
| R83(2) | A file used in an (approved) record is removed only with the Owner's approval + reason + AuditEvent; the file stays; the record keeps its reference and shows the file was retired; no approval → 409 | No generic Approval runtime exists on main, so a minimal flow (collection `media_retire_requests`): `POST /api/media/{id}/retire-request` (`media_policy.RETIRE_REQUEST_ROLES` — interim: **Admin** only, reason + `Idempotency-Key`, one pending per file, AuditEvent `media.file.retire_request`) → `POST /api/media/retire-requests/{rid}/approve` (`RETIRE_APPROVER_ROLES` — **Owner**, **not the requester** → `SELF_APPROVAL_FORBIDDEN`; retires with `retired_in_use`, `retired_uses`, `retire_approved_by`; AuditEvent `media.file.retire` with requester + approver) or `/reject` (Owner, reason; AuditEvent `media.file.retire_request.reject`). `GET /api/media-retire-requests` for Owner/Admin. The record is not touched; `GET /api/media/{id}` answers a reader **410 `MEDIA_RETIRED`** (`{media_id, retired: true}`, no metadata). `DELETE` of a used file stays **409 `MEDIA_IN_USE`** (with `request_path`). An Owner's own request is an open question to Krum (interim: Owners do not file). |
| R83(3) | Only a fresh profile upload is an avatar; no linking as avatar; avatar changes audited; old avatars retired by owner or Admin | `POST /media/upload` with `context_type="profile"` sets `media_files.avatar = true`; `/api/media/avatar/...` serves only such rows. `POST /media/link` with `profile` → **409 `AVATAR_LINK_REFUSED`**. `PUT /api/users/{id}` and `PUT /api/employees/{id}/basic` accept `avatar_url` only as `/api/media/avatar/<name>` of a non-retired avatar row of THAT user in the tenant (or empty to clear), else **400 `AVATAR_NOT_ALLOWED`** before any write; every change writes AuditEvent **`user.avatar.change`** (`app/services/media_avatar.py`). An avatar's own profile link is not a "use"; being someone's current avatar is — so the current one → 409, an old one is retired (direct `DELETE`) by the file owner, the profile's user or Admin/Owner; others → 403. |
| R83(4) | Backfill for legacy avatars: dry run counts only; apply idempotent with AuditEvent; never automatic; deploy needs Krum's "да" | `backend/scripts/media_sec_01_avatar_backfill.py` — see below. **Not run anywhere but the scratch test database.** |

## FLOW Guard pass 46 on d634bf4 — fixed

| Finding | Fix |
|---|---|
| FG-576 (high) | **One file-holders registry** `backend/app/services/file_holders.py` (`HOLDERS` + `register_finder`). Added the holders the 409 missed: `offers.approval.evidence_file_id`, `warehouse_transactions.file_ids`, `finance_payments` / `subcontractor_payments.cash_receipt_file_id` (the real #83 field), `audit_events.related_file_ids` (read only through `app.audit.store.event_with_related_file`). One test per holder. |
| FG-577 (medium, §8) | The retire request stores the holders, `uses_version` (hash) and the file's `ref_version`; the approval re-reads and refuses **409 `RETIRE_REQUEST_STALE`** on any difference. While a request is pending, `/media/link` and every reference writer refuse **409 `RETIRE_REQUEST_PENDING`**. |
| FG-575 (medium) | **One upload guard** `backend/app/deps/upload_guard.require_uploader` at every upload entry point: `/media/upload`, `/technician/photo-invoice`, `/ocr-invoice/upload`, `/supplier-invoices/{id}/upload-file`, `/projects/{id}/photos`. Company or project Viewer → 403 before the file is read (nothing written). `/smr-analyses/import-excel` already allowed only Admin/Owner/SiteManager. |
| FG-579 (write skew) | Every reference writer calls `file_holders.claim` — a CAS `$inc ref_version` on the file row (refuses retired / pending) — **in the same transaction as its reference write** (`claimed_write`): missing-SMR attachment + client signature, extra-work draft, technician report photos + missing-SMR photos, scan doc, OCR pending expense, offer acceptance evidence (inside its transaction), avatar (`users.avatar_url`), `/media/link`. The retire paths CAS on `ref_version`. Tested with a forced race: the retire sees the conflict and refuses 409. |
| FG-578 | Backfill: only files UPLOADED as profile (no `linked_at`); `--approved-by` = an active Owner's **user id** (the run is that Owner's tenant only); every `update_one` checked (`conflict` → transaction rolled back); `--revert` mode; dry run default. |
| minor | `uses` (record ids) only for Owner/Admin (`file_holders.redact`; others get `use_kinds` + `uses_count`); `hr.py` / `auth.py` avatar write + `user.avatar.change` in ONE transaction; `/media/link` writes AuditEvent `media.file.link` (FG-544). |

**Interim decisions, one constant each** (`backend/app/services/media_policy.py`), until Krum answers: avatars visible to everyone in the firm (`AVATAR_VISIBILITY`); an **Admin** files the retire request and an **Owner** approves (`RETIRE_REQUEST_ROLES` / `RETIRE_APPROVER_ROLES`); no restore (`RESTORE_ENABLED = False`).

**The Owner-approval flow is INTERIM** — debt to **W0-07** (canonical Approval runtime); it must not become a second Approval source of truth. Each request carries `interim_until: "W0-07"`.

Red before / green after: the new `tests/test_media_sec_01.py` on `d634bf4` → **19 failed** (`red_pass46_on_d634bf4.txt`); on this branch → **42 passed**.

## R83(4) — legacy avatar backfill (runbook, needs Krum's "да")

Until it is applied, a legacy avatar (uploaded before MEDIA-SEC-01, no `avatar` flag) shows initials instead of the photo.

```bash
# 1. dry run — counts and plan, writes nothing (the tenant = the approving Owner's)
MONGO_URL=... DB_NAME=<tenant db> python backend/scripts/media_sec_01_avatar_backfill.py \
    --approved-by <Owner user id>
# 2. after Krum's "да" for THAT plan
MONGO_URL=... DB_NAME=<tenant db> python backend/scripts/media_sec_01_avatar_backfill.py \
    --approved-by <Owner user id> --plan-sha <plan_sha from step 1> --apply
# undo: the same two steps with --revert
```

* `flag` — `media_files` row of the same tenant with the stored name, not retired, UPLOADED as the user's profile photo (`context_type="profile"`, `context_id` = the user, no `linked_at`) → `avatar: true` (+ `avatar_url` rewritten from `/api/media/file/` to `/api/media/avatar/` form), one transaction per user with AuditEvent `media.avatar.backfill` (actor `system`, approver in the diff).
* `already` — nothing to do. `skip:*` (`url_shape`, `no_media_in_tenant`, `retired`, `not_a_profile_photo`, `another_users_profile`, `linked_not_uploaded_as_profile`) — reported only; a person re-uploads.
* `--approved-by` that is not an active Owner's user id, or a plan SHA that is not the current plan → refused, nothing written. A write that matches nothing aborts that user's transaction (`conflict`). A second apply writes 0.
* `--revert` — removes exactly the flags this script set and restores the user's previous `avatar_url` while it is still the one the backfill wrote; AuditEvent `media.avatar.backfill_revert`.

## Evidence

* `results.json` — a run of `tests/test_media_sec_01.py --harness` (whole `server.app`, ST-01 tenants A/B, real logins, local Mongo 7.0 rs0). Never hand-edited.
* `test_summary.txt` — the gate numbers.

## Debt / out of scope (recorded, not fixed)

* **FG-543, FG-545, FG-546** — out of scope by instruction (FG-545 = the FLOW-029 archive model, Wave 2).
* `MissingSMRPage.js:712` still shows attachments with a plain `<img src=".../api/media/file/...">`. That route already required a login before this change, so these images most likely don't load today. The same `AuthImage` fix applies.
* `EmployeesPage.js` uploads a new employee's avatar with `context_type="avatar"`, which is not in `MEDIA_CONTEXT_TYPES` → 400, swallowed silently (**pre-existing debt**, recorded per pass 46).
* Retired media has no "restore" path yet (same as retired project photos) — open question to Krum (`media_policy.RESTORE_ENABLED`).
* **W0-07**: the interim Owner-approval flow (`media_retire_requests`) moves into the canonical Approval runtime.
* **FG-579 residual — warehouse canonical**: the movement routes claim the attached `file_ids` BEFORE `service.execute`, which runs its own transaction that a caller cannot join (the warehouse service is locked; joining needs a hook in it). A retire racing a movement inside that gap is not excluded; the holder check still sees the movement afterwards. Fix with a pre-commit hook in the warehouse service (separate task).
* **FG-579 residual — OCR from-media**: `create_ocr_intake` (service) inserts without a session; the claim runs just before it.
* **#83 merge (FG-555)**: CP-01's `bank_account_guard.receipt_references` should read the registry (`file_holders.find_holders(..., kinds=RECEIPT_KINDS)`) instead of its own `_RECEIPT_HOLDERS` loop, and the CP-01 payment writers that set `cash_receipt_file_id` should call `file_holders.claimed_write`. FLOW Guard's 5-point recipe applies.
* The frontend has no screen yet for the retire request / Owner approval (API only); `EmployeesPage` new-employee avatar keeps failing silently (now also refused by R83(3), as it passes a `/api/media/file/` URL).
* `GET /api/media/{id}` order changed: the media ACL runs first, then the retired rule (403 for a user without access, 410 for a reader with access).

## Merge note

* **FG-555** — the merge with #83 is done by whichever of the two PRs merges second (orchestrator decision). This PR does not merge #83.

## Resolved / waiting

* **FG-557** — RESOLVED (FLOW Guard pass 46).
* Waiting for Krum: who sees avatars; an Owner's own retire request; restoring a retired file — each one constant in `media_policy.py`.

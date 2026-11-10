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
| R83(1) | A project Viewer, even a member, only reads photos | `POST /api/projects/{id}/photos`: company role `Viewer` or project role `Viewer` → **403** before the file is read (no file, no row). List/file stay readable for members. Off / shadow / enforce tested. |
| R83(2) | A file used in an (approved) record is removed only with the Owner's approval + reason + AuditEvent; the file stays; the record keeps its reference and shows the file was retired; no approval → 409 | No generic Approval runtime exists on main, so a minimal flow (collection `media_retire_requests`): `POST /api/media/{id}/retire-request` (file owner / Admin / Owner, reason + `Idempotency-Key`, one pending per file, AuditEvent `media.file.retire_request`) → `POST /api/media/retire-requests/{rid}/approve` (role **Owner** only, **not the requester** → `SELF_APPROVAL_FORBIDDEN`; retires with `retired_in_use`, `retired_uses`, `retire_approved_by`; AuditEvent `media.file.retire` with requester + approver) or `/reject` (Owner, reason; AuditEvent `media.file.retire_request.reject`). `GET /api/media-retire-requests` for Owner/Admin. The record is not touched; `GET /api/media/{id}` answers a reader **410 `MEDIA_RETIRED`** (`{media_id, retired: true}`, no metadata). `DELETE` of a used file stays **409 `MEDIA_IN_USE`** (with `request_path`). With a single Owner, an Owner's own request can only be rejected — a second Owner is needed to approve it. |
| R83(3) | Only a fresh profile upload is an avatar; no linking as avatar; avatar changes audited; old avatars retired by owner or Admin | `POST /media/upload` with `context_type="profile"` sets `media_files.avatar = true`; `/api/media/avatar/...` serves only such rows. `POST /media/link` with `profile` → **409 `AVATAR_LINK_REFUSED`**. `PUT /api/users/{id}` and `PUT /api/employees/{id}/basic` accept `avatar_url` only as `/api/media/avatar/<name>` of a non-retired avatar row of THAT user in the tenant (or empty to clear), else **400 `AVATAR_NOT_ALLOWED`** before any write; every change writes AuditEvent **`user.avatar.change`** (`app/services/media_avatar.py`). An avatar's own profile link is not a "use"; being someone's current avatar is — so the current one → 409, an old one is retired (direct `DELETE`) by the file owner, the profile's user or Admin/Owner; others → 403. |
| R83(4) | Backfill for legacy avatars: dry run counts only; apply idempotent with AuditEvent; never automatic; deploy needs Krum's "да" | `backend/scripts/media_sec_01_avatar_backfill.py` — see below. **Not run anywhere but the scratch test database.** |

## R83(4) — legacy avatar backfill (runbook, needs Krum's "да")

Until it is applied, a legacy avatar (uploaded before MEDIA-SEC-01, no `avatar` flag) shows initials instead of the photo.

```bash
# 1. dry run — counts and plan, writes nothing
MONGO_URL=... DB_NAME=<tenant db> python backend/scripts/media_sec_01_avatar_backfill.py
# 2. after Krum's "да" for THAT plan
MONGO_URL=... DB_NAME=<tenant db> python backend/scripts/media_sec_01_avatar_backfill.py \
    --apply --approved-by "Крум" --plan-sha <plan_sha from step 1>
```

* `flag` — `media_files` row of the same tenant with the stored name, not retired, `context_type="profile"`, `context_id` = the user → `avatar: true` (+ `avatar_url` rewritten from `/api/media/file/` to `/api/media/avatar/` form), one transaction per user with AuditEvent `media.avatar.backfill` (actor `system`, approver in the diff).
* `already` — nothing to do. `skip:*` (`url_shape`, `no_media_in_tenant`, `retired`, `not_a_profile_photo`, `another_users_profile`) — reported only; a person re-uploads.
* `--apply` without `--approved-by`, or with a plan SHA that is not the current plan → refused, nothing written. A second apply writes 0.

## Evidence

* `results.json` — a run of `tests/test_media_sec_01.py --harness` (whole `server.app`, ST-01 tenants A/B, real logins, local Mongo 7.0 rs0). Never hand-edited.
* `test_summary.txt` — the gate numbers.

## Debt / out of scope (recorded, not fixed)

* **FG-543, FG-545, FG-546** — out of scope by instruction (FG-545 = the FLOW-029 archive model, Wave 2).
* `MissingSMRPage.js:712` still shows attachments with a plain `<img src=".../api/media/file/...">`. That route already required a login before this change, so these images most likely don't load today. The same `AuthImage` fix applies.
* `EmployeesPage.js` uploads a new employee's avatar with `context_type="avatar"`, which is not in `MEDIA_CONTEXT_TYPES` → 400, swallowed silently (pre-existing).
* Retired media has no "restore" path yet (same as retired project photos).
* The frontend has no screen yet for the retire request / Owner approval (API only); `EmployeesPage` new-employee avatar keeps failing silently (now also refused by R83(3), as it passes a `/api/media/file/` URL).
* `GET /api/media/{id}` order changed: the media ACL runs first, then the retired rule (403 for a user without access, 410 for a reader with access).

## Merge note

* **FG-555** — the merge with #83 is done by whichever of the two PRs merges second (orchestrator decision). This PR does not merge #83.

## Waiting for the orchestrator

* **FG-557** — not touched until the orchestrator answers.

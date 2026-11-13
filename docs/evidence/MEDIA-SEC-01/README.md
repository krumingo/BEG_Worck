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

## FLOW Guard pass 47 on 1844627 — fixed

| Finding | Fix |
|---|---|
| FG-587 (medium) | `app/deps/upload_guard.project_of_context` resolves the project of EVERY media context (workReport, delivery, attendance, machine, missingSMR, site, project); `require_uploader_for_context` guards `POST /media/upload` **and** `POST /media/link` → a company or project Viewer cannot add a file to a project by linking (403, nothing written). |
| FG-588 (medium, proven race) | **Option 4 — the durable pending-holder marker** (orchestrator + FLOW Guard, 6 conditions). The warehouse routes (`POST /warehouse/canonical/movements`, `/project-writeoff`, and material waste through it) call `file_holders.mark_pending` BEFORE `service.execute`: one conditional update (not retired AND no pending retire request) that `$push`es `{id, route, user, ref, at}` and `$inc`s `ref_version`; a miss → 409, the movement does not run. DELETE / retire-request / retire-approve count a pending marker as a holder (409 `MEDIA_IN_USE`, `pending_link`, shown to Owner/Admin as „в процес на свързване", no ids for others), and their final CAS requires no pending holders AND the `ref_version` read. After the movement commits the marker is confirmed, on failure released (`settle_pending`: idempotent, by marker id, CAS, removes only its own entry; arguments are built inside the guarded call). A crash-left marker is released only by `POST /api/media/{id}/pending-holders/{marker}/release` (Owner/Admin) after `media_policy.PENDING_HOLDER_MIN_AGE_SECONDS` (3600) AND a registry proof of no reference (incl. `warehouse_transactions.file_ids`); never retires (rule replaced in pass 48 — see below); AuditEvent `media.file.pending_holder_release` (actor, marker, proof). The locked warehouse service is NOT touched. |
| FG-590 | (a) `EmployeesPage.js` new-employee avatar: `context_type="profile"` + `/api/media/avatar/<name>`; (b) `find_holders` runs every registered finder for every kind query (a #83 finder answers under `kinds=RECEIPT_KINDS`). |
| FG-575 / FG-579 | Per FLOW Guard, the FG-575 remainder was exactly FG-587; the FG-579 remainders are FG-588 (fixed above), OCR from-media (debt, below) and #83 (at its merge). |

Interleavings (FLOW Guard condition 6), each a test: claim → DELETE 409 → movement commits → movement holds the file; claim → movement fails → release → DELETE works; stale release too recent / with a reference (kept) / without one (released, audited, not retired); parallel approve vs claim (approve wins, claim 409) and DELETE vs claim (claim wins, DELETE 409); two writers' markers on one file; and the REAL warehouse route with a stub service that attempts a retire DURING the movement (refused; marker confirmed / released). Red on `56ea33b`: 6 failed (`red_fg588_on_56ea33b.txt`); FG-587/590 red on `1844627`: `red_pass47_on_1844627.txt`.

## FLOW Guard pass 48 on cb19aeb — fixed

| Finding | Fix |
|---|---|
| FG-595 (medium) | A marker that outlived its COMMITTED movement no longer blocks the Owner retire forever. `release_stale` (Owner/Admin, `Idempotency-Key`) decides by the marker's OWN `ref` only (orchestrator, pass 48): the marker's OWN movement exists — the FULL idempotency scope (FLOW Guard, as in R29): this tenant + the marker's user as the movement's `actor_id` + `idempotency_key == marker.ref` + the marker's action (recorded on the marker since pass 48) → **late-confirmed**; another user's movement under the same key string is NOT own (even when other holders exist, at any age — its movement committed); no such row AND older than `PENDING_HOLDER_MIN_AGE_SECONDS` → **released** (even when other holders exist); no such row AND younger → 409 `PENDING_HOLDER_TOO_RECENT`, nothing changes. Other holders stay real holders: every retire path still sees them. CAS on the marker + `ref_version` +1, Only that marker id is pulled (CAS). AuditEvent `media.file.pending_holder_confirm_late` / `media.file.pending_holder_release`: the actor, `proof.decision` (`confirm` / `release`), the own movement ids (or none) plus `age_seconds`, the own scope and the other holders. The routes' `finally` settles through `file_holders.settle_shielded` (`asyncio.shield`), so a client disconnect / middleware cancel after the commit cannot skip the settle. Tests: a marker left behind by a committed movement → late-confirmed → retire request 201 → Owner approve 200 → `retired`; own movement + another holder → confirmed, DELETE still 409; another key's movement only + age passed → released, DELETE still 409 (`warehouse_movement`); same key, different user → not own (young 409, old released, no confirm event; the release audit names the Admin); a request cancelled twice (during the movement and during the settle) → marker settled. |
| FG-596 | `warehouse_canonical._markers_for`: the Idempotency-Key replay check runs BEFORE the marker — when a movement with the same `{org_id, idempotency_key, action}` already committed, no marker is placed and the service returns its stored result. Test: a replay while a retire request is pending → 200, no marker (on cb19aeb: 409 `RETIRE_REQUEST_PENDING`). |
| FG-598 | `POST /api/media/{id}/pending-holders/{marker}/release` requires `Idempotency-Key` (428 without); the granted settle runs in `lifecycle.keyed_transaction` (a replay returns the same answer, also after the marker is gone). A refused release (too recent) → 409 AND an AuditEvent `media.file.pending_holder_release_refused` (actor, marker, age) — inside the keyed transaction since pass 49 (FG-610). |
| FG-597 | Stays debt (OCR from-media, below). |

Mixed case (orchestrator, pass 48): settled by the marker's own ref only — other holders keep the file held, so removing the marker is safe.

Red-before: `red_pass48_on_cb19aeb.txt` — the new tests on cb19aeb: 5 failed; `red_pass48_scope_on_35cc099.txt` — on 35cc099 (key-string-only own): 2 failed, incl. another user's same-key movement confirming the marker.

## FLOW Guard pass 49 on 35cc099 — fixed

FG-607, FG-608, FG-595, FG-596 resolved by FLOW Guard; the own-ref rule proven.

| Finding | Fix |
|---|---|
| FG-609 | "Own" = org + `actor_id` + action + key in `release_stale` (above), AND in `warehouse_canonical._markers_for`: the replay pre-check is THIS user's committed movement (`actor_id` = the same value the route gives the service and the marker). Test: another user's committed movement under the same key + action → the marker IS placed; the same user's → none. |
| FG-610 | The refusal's AuditEvent is written INSIDE `keyed_transaction`; the refusal is the key's stored answer. A replayed key → the same 409, ONE `media.file.pending_holder_release_refused` event. |
| `mark_pending` rollback | Catches `BaseException` (incl. `CancelledError`), rolls back the markers already placed (shielded), re-raises; the marker is recorded before its write, so a cancel between the write and the bookkeeping leaves nothing behind. Test: a cancel between the 1st and the 2nd file → no marker on either. |

Red-before: `red_pass49_on_700629f.txt` — 3 failed (2 refusal events on a replay; the 1st file's marker leaked; another user's movement skipped the marker). `red_pass48_on_cb19aeb.txt` regenerated with the same tests: 7 failed.

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
* ~~`EmployeesPage.js` new-employee avatar with `context_type="avatar"`~~ — fixed in pass 47 (FG-590a).
* Retired media has no "restore" path yet (same as retired project photos) — open question to Krum (`media_policy.RESTORE_ENABLED`).
* **W0-07**: the interim Owner-approval flow (`media_retire_requests`) moves into the canonical Approval runtime.
* **FG-588 option (a) — debt**: a pre-commit hook in the (locked) warehouse service so the claim runs INSIDE `service.execute`'s transaction; needs Krum. Option 4 (pending-holder marker) closes the proven race meanwhile.
* **OCR from-media (`ocr_invoice.py` from-media) — debt (FG-597)**: claim-then-write outside one transaction; unreachable today (pre-existing 500: `create_ocr_intake` calls `extract_invoice_text(media_id=...)` without a tenant). Before that 500 is fixed, the route gets the pending-holder pattern (or the claim inside the write's transaction).
* **#83 merge (FG-555 / FG-589)**: `"retired"` goes into `bank_account_guard._INACTIVE_FILE_STATES` (and a pending retire request is refused); the `cash_receipt_file_id` writers in `finance.py` / `subcontractors.py` use `file_holders.claimed_write`; `receipt_references` uses `find_holders(kinds=RECEIPT_KINDS)`. FLOW Guard's 5-point recipe applies.
* The frontend has no screen yet for the retire request / Owner approval (API only); `EmployeesPage` new-employee avatar keeps failing silently (now also refused by R83(3), as it passes a `/api/media/file/` URL).
* `GET /api/media/{id}` order changed: the media ACL runs first, then the retired rule (403 for a user without access, 410 for a reader with access).

## Merge note

* **FG-555** — the merge with #83 is done by whichever of the two PRs merges second (orchestrator decision). This PR does not merge #83.

## Resolved / waiting

* **FG-557** — RESOLVED (FLOW Guard pass 46).
* Waiting for Krum: who sees avatars; an Owner's own retire request; restoring a retired file — each one constant in `media_policy.py`.

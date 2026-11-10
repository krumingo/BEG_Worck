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

## Evidence

* `results.json` — a run of `tests/test_media_sec_01.py --harness` (whole `server.app`, ST-01 tenants A/B, real logins, local Mongo 7.0 rs0). Never hand-edited.
* `test_summary.txt` — the gate numbers.

## Debt / out of scope (recorded, not fixed)

* **FG-543, FG-545, FG-546** — out of scope by instruction (FG-545 = the FLOW-029 archive model, Wave 2).
* `MissingSMRPage.js:712` still shows attachments with a plain `<img src=".../api/media/file/...">`. That route already required a login before this change, so these images most likely don't load today. The same `AuthImage` fix applies.
* `EmployeesPage.js` uploads a new employee's avatar with `context_type="avatar"`, which is not in `MEDIA_CONTEXT_TYPES` → 400, swallowed silently (pre-existing).
* Retired media has no "restore" path yet (same as retired project photos).

## Merge note

* **FG-555** — the merge with #83 is done by whichever of the two PRs merges second (orchestrator decision). This PR does not merge #83.

## Waiting for the orchestrator

* **FG-557** and the Krum question below — not touched until the orchestrator answers.

## Open business question (for Krum, via the orchestrator)

* A **Viewer who IS a member** of a project can still upload project photos (membership is the only rule, as for the other member-level project routes). Should Viewer be read-only for photos?

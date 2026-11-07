# OFF-01: a superseded offer version cannot be accepted; a sent offer is never deleted

Package: `docs/architecture/tasks/OFF-01_OFFER_VERSION_ACCEPT_AND_NO_DELETE.md` (branch `claude/happy-meitner-bmcnel` @ 174b4ee). Findings: FLOW Guard pass 13, **FG-129** (high) and **FG-130** (medium), both on main `d226c49`.

Canon: FLOW-003 „Версии“, „Клиентско одобрение“, „Interim Approval Receipt“, „Какво НЕ трябва да позволява“ (стара/заменена версия да бъде одобрена след публикуване на нова), „Минимална проверка“ (invalidation на approval при нова версия); FLOW-002 (клиентски линк); CLAUDE.md §2.9, §8, §14; R29 (Idempotency-Key).

## Source of truth

`offers` is the source of truth (FLOW-003). Every version is its own document; the chain is `parent_offer_id` (old → new, existing field) and, new, `superseded_by` (new → old). No second registry is created. Canonical AuditEvents go to `audit_events` (W0-04); the legacy `audit_logs` rows (`log_audit`) and `offer_events` rows are kept, as before.

## What was wrong (proved by tests that fail on main)

| # | Problem on main | Test |
|---|---|---|
| FG-129 | `POST /offers/{id}/new-version` only inserted the new version. The old **Sent** version stayed acceptable through `/accept` and through the public link `/offers/review/{token}/respond`, so a client could accept a replaced price/scope with the old link. | `test_01`, `test_02`, `test_09`, `test_11` |
| FG-130 | `DELETE /offers/{id}` hard-deleted Sent / Rejected (anything but Accepted) offers that the client had already received. | `test_03` |

Test file `backend/tests/test_off_01_offer_version_accept.py` run against main `d226c49` code (only the test file added): **39 failed, 3 passed**. The 3 that pass are `test_12` (forbidden roles / other tenant) in the three modes — a regression check that already held on main.

## Data model (additive, no migration, no backfill)

| Record | New fields |
|---|---|
| superseded version | `superseded_by` (new version id), `superseded_at`, `superseded_by_user`; `status: "Superseded"` + `status_before_supersede` (an **Accepted** version keeps `Accepted`, see debt D-OFF01-2) |
| revoked review link | `review_token` is **kept**; `review_token_status: "revoked"`, `review_token_revoked_at`, `review_token_revoked_reason` (`superseded` / `cancelled`) |
| link binding | `review_token_version` — written by `/send`: the link is bound to this offer id **and** this exact version |
| accepted offer | `accepted_by`, `approval {method, channel, version, evidence_file_id, note / client_name, comment, verification, accepted_at}` |
| cancelled offer | `status: "Cancelled"`, `status_before_cancel`, `cancel_reason`, `cancelled_by`, `cancelled_at` |

Rows written before OFF-01 have none of these fields: `superseded_by: None` matches a missing field, and a link without `review_token_version` is treated as bound to its own document's version. Nothing to backfill.

`OFFER_STATUSES` gains `Superseded` and `Cancelled` (also labelled in the PDF/XLSX export and the UI).

## Endpoints

| Endpoint | Before | After |
|---|---|---|
| `POST /offers/{id}/new-version` | insert only | One transaction: a conditional write on the old version (`status` as read, `superseded_by: None`) marks it superseded and revokes its link; the new Draft is inserted; legacy audit row + canonical `offers.offer.superseded`. Loser of a race → 409 (`OFFER_VERSION_SUPERSEDED` or `OFFER_STATE_CHANGED`). A superseded version cannot be versioned again (one head per chain). |
| `POST /offers/{id}/accept` | status check, then a separate update | Optional body `{approval_method: signed_pdf / verified_email / internal_unspecified, evidence_file_id, note}` (anything else → 422). One transaction: the write's filter is `status: Sent, superseded_by: None, version: <read>`; canonical `offers.offer.accepted` with `entity_version`, approval method, evidence `related_file_ids`, total, currency. Superseded → **409 `OFFER_VERSION_SUPERSEDED`**. |
| `POST /offers/review/{token}/respond` (public) | status check, then a separate update | One transaction: the filter binds token + offer id + exact version + `status: Sent` + not superseded + link not revoked; canonical `offers.offer.client_approved` / `client_rejected` / `client_revision_requested` (actor `external_principal`, channel `magic_link`, the token is NOT logged). Superseded → **409 `OFFER_VERSION_SUPERSEDED`** with a neutral Bulgarian text; revoked/cancelled link → **409 `OFFER_NOT_OPEN`**. No internal id, org or project in the answer. `offer_events` now written through the tenant view. |
| `GET /offers/review/{token}` | — | Unchanged; it now shows status `Superseded` / `Cancelled` (the page hides the buttons). |
| `POST /offers/{id}/cancel` | — (new) | Admin/Owner (same as delete). Reason required (400 `REASON_REQUIRED`; PAY-01 length/character rule). Allowed from Sent / Rejected / NeedsRevision, and from a Draft that may not be deleted (a new version, or once sent). One transaction: status `Cancelled` + reason + who/when, link revoked, canonical `offers.offer.cancelled`. Accepted / Superseded / Cancelled / unsent Draft → 409 `OFFER_NOT_CANCELLABLE`. |
| `DELETE /offers/{id}` | hard delete of anything but Accepted | Only a Draft that was never sent (no `sent_at`, no link, no `sent` event) and is not a version of another offer. Anything else → **409 `OFFER_IN_USE`** ("анулирайте я"), nothing changed. Accepted was 400, now 409. |

**Idempotency-Key (R29)** on new-version / accept / respond / cancel: missing → 428 `IDEMPOTENCY_KEY_REQUIRED`, nothing written; the same key → the first answer byte-for-byte, nothing written twice; the same key with another request → 409 `IDEMPOTENCY_KEY_REUSED`. The 428 comes **after** the existing 404 / 403 checks, so no permission answer changed.

**Mechanisms reused, none added:** `auth_tx.run_in_transaction`, `record_event(..., session=...)`, the PAY-01 `_require_key` / `_once` (W0-04 `begin_idempotent` / `complete_idempotent` / `fail_idempotent`), `check_reason`. A deployment without transactions refuses these four writes with 503 `TRANSACTIONS_UNAVAILABLE` and writes nothing (`test_08`) — the same rule as AUTH-01: production is a replica set.

## Permissions

Unchanged: accept / reject / delete / cancel → Admin, Owner; new-version → `can_manage_project` (Admin, Owner, the project's SiteManager). Positive and forbidden cases in off / shadow / enforce (`test_03`, `test_06`, `test_07`, `test_12`).

PM-01 matrix regenerated **only by the harness** (`python tests/test_pm_01_permission_matrix.py --harness`, local `mongo:7.0` replica set `rs0`). See the section "PM-01" below for the exact changed cells.

## Frontend

- `OfferEditorPage.js`: „Приеми“ and „Нова версия“ send an `Idempotency-Key` (one per click, kept for a retry after a lost connection — `lib/idempotency.js` from PAY-01) and show `detail.message`.
- `OfferReviewPage.js`: the client's answer sends an `Idempotency-Key`; labels `Заменена с нова версия` / `Анулирана`; the error text is the neutral message.
- `ProjectDetailPage.js`: status labels for the two new statuses.
- No cancel button yet (debt D-OFF01-6).

## Tests — `backend/tests/test_off_01_offer_version_accept.py`

12 tests; transactional ones on real Mongo, the pre-transaction refusals also on mongomock; each in off / shadow / enforce → **42 cases, 0 skipped**.

| Test | Proves |
|---|---|
| 01 | new version supersedes the old (fields, link revoked & kept, AuditEvent); `/accept` of the old → 409, nothing written; no second new version of it |
| 02 | old link: approve / reject / revision → 409 neutral Bulgarian, no internal ids; the page still opens with status Superseded |
| 03 | DELETE Sent / Rejected / Accepted / Superseded / Cancelled / NeedsRevision / new-version draft / once-sent draft → 409 `OFFER_IN_USE`, DB byte-identical; unsent draft removable; roles unchanged (mongomock + real) |
| 04 | current version accepted with exact-version evidence; replay; key reuse 409; 422 for an unknown method; plain button records `internal_unspecified` |
| 05 | public approval of the current version; `magic_link` evidence; token not in the event; replay; reject/revision events |
| 06 | cancel: reason required, roles, status + reason + event, link revoked, replay; cancelled → no accept / no client answer / no second cancel; Accepted not cancellable; other tenant 404 |
| 07 | no key → 428 on all four, nothing written; 403/404 still first (mongomock + real) |
| 08 | no transactions → 503, nothing written |
| 09 | ×10 new-version ∥ accept of the old: exactly one wins, never both |
| 10 | ×10 two new-versions: exactly one, one superseded event |
| 11 | ×10 new-version ∥ public approve: exactly one wins |
| 12 | forbidden roles and the other tenant: nothing written |

Race coverage (ad hoc, 30 rounds each, enforce): new-version ∥ accept → new-version won 15, accept won 15; new-version ∥ public approve → 1 / 29. Both outcomes occur, and in every round exactly one request succeeded.

## Gates

Run on this branch, real `mongo:7.0` replica set `rs0` (`W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27017/?replicaSet=rs0`):

| Gate | Result |
|---|---|
| OFF-01 + PM-01 + all `test_pay_01*` + A1 collision matrix | **683 passed, 0 skipped** (PM-01 real-Mongo reproduction included) |
| R0 (`tests/test_r0_*.py`) | **814 passed** |
| W0 (`tests/test_w0_*.py`) | 1173 passed, **15 failed — all 15 in `test_w0_03e_legacy_routes.py`** (the known baseline, the same as on main) |
| A2C tenant boundary guard | 214 modules, 0 violations |
| A1 tenant access guard | 432 units, 0 violations |
| A1 inventory | regenerated by its script: 380 accesses (FIXED 132, SAFE 248), up from 374 — every new row TenantData-scoped |
| A2B inventory | regenerated by its script: one line — `offer_events` writers (respond now writes through the tenant view) |
| PM-01 matrix | regenerated by the harness: only the new `POST /api/offers/{offer_id}/cancel` (24 cells, 404, nothing written); no existing cell changed |

## Debts (canon silent — Krum decides; nothing invented)

| ID | Debt |
|---|---|
| D-OFF01-1 | FLOW-003 carrier 3 (one-time approval page) requires **limited validity and an identity check**. The review link has neither: no expiry, no identity check. Recorded as `verification: "link_token_only"` in the approval. |
| D-OFF01-2 | **Closed by Addendum A §2** (FLOW-003/005): an Accepted offer gets no new version → 409 `OFFER_ACCEPTED_USE_ANNEX`. |
| D-OFF01-3 | Cancelling an **Accepted** offer is refused (409): it touches contract/annex rules (FLOW-004) the canon does not state here. |
| D-OFF01-4 | Undoing a mistaken new version (cancel the new draft → the old one stays superseded, it is not reopened). Whether to "un-supersede" is a business rule. |
| D-OFF01-5 | **Partly closed by Addendum A §3**: a given `evidence_file_id` is now checked. Still open: `/accept` does not REQUIRE a carrier file; the plain button records `internal_unspecified`. |
| D-OFF01-6 | No UI button for „Анулирай“ yet (API only). |
| D-OFF01-7 | **Closed by Addendum A §1** (audit OFF79-01). |
| D-OFF01-8 | `NeedsRevision` (client asked for a correction) cannot be versioned (`new-version` allows only Sent/Accepted/Rejected — unchanged rule); the client's request has no path to a new version. |
| D-OFF01-9 | A crash between the transaction commit and `complete_idempotent` leaves the key STARTED: a retry with the same key gets 409 `IDEMPOTENCY_IN_PROGRESS` (never a double write). The same limitation as PAY-01's `_once`. |
| D-OFF01-10 | `_require_key` / `_once` are imported from `app.routes.finance` (reuse, not a copy). Moving them into a shared service is a refactor for later. |
| D-OFF01-12 | The evidence file is checked in `media_files`, the tenant's current file store. The canonical File Registry (W0-06, Gate Matrix: NOT STARTED) does not exist yet; once it does, `_check_evidence_file` must read it instead. A file not linked to anything is accepted as "linkable"; the acceptance does not link it. |
| D-OFF01-11 | Two audit trails remain (legacy `audit_logs` + `offer_events` + canonical `audit_events`): W0-04 known debt. |


## Addendum A (07.11) — audit OFF79-01 (blocking), D-OFF01-2, D-OFF01-5

Package: the same file, section „Допълнение A“ @ `1a15df3`. Audit probe: `claude/audit-log` `docs/audit/probes/off01/test_probe_off01.py`, copied unchanged to `backend/tests/test_off_01_audit_probe.py`.

**Reproduced first** (`b764069` = tests only, on `ea9df81` code):
- probe: **9 failed**, 45 passed. All 9 failures are O1 × {Sent, Accepted, Superseded} × 3 modes. `restore 200 | total 1200.0 -> 12.0 | client approve 200 | final status Accepted total 12.0`.
- `test_off_01`: **12 failed**, 42 passed (the new tests 13, 14, 15).

| # | Fix | Test |
|---|---|---|
| §1 OFF79-01 | `POST /offers/{id}/versions/{n}/restore` and `DELETE /offers/{id}/versions/{n}` → **409 `OFFER_IN_USE`** unless the offer is a draft that was never sent (the same `_draft_was_used` rule as `DELETE /offers/{id}`). A never-sent draft restores and deletes snapshots as before. | `test_13` (mongomock + real), probe O1 |
| §2 D-OFF01-2 | `new-version` of an **Accepted** offer → **409 `OFFER_ACCEPTED_USE_ANNEX`**. Draft, Sent and Rejected may be versioned; the old one always becomes `Superseded` (approval void), so the chain never holds two accepted versions. | `test_14` |
| §3 D-OFF01-5 | `/accept` with `evidence_file_id` → it must be a file of THIS tenant (`media_files`) → else **422 `EVIDENCE_FILE_NOT_FOUND`**. It must also be unlinked or linked to the offer's project → else **422 `EVIDENCE_FILE_NOT_LINKABLE`**. Nothing written. | `test_15`, probe O7 (now 422) |

After the fix: `test_off_01` + probe → **108 passed, 0 skipped**.

Changed rules, noted: new-version of a **Draft** is now allowed (Addendum A §2 lists Draft); before it was 400. Accepted was allowed, now 409.

## Round 3 (07.11) — OFF79-03 and legacy pairs (non-blocking audit items, before Codex)

Requested by the orchestrator after the audit closed OFF79-01 at `449c1f4`. The package has no Addendum B. Both items stay inside the package: OFF79-03 is a race in the Addendum A §1 fix itself. The second item enforces Addendum A §2 („никога няма две приети версии“) on data written before OFF-01.

**Reproduced first** (`ac8d320` = tests only, on `449c1f4` code): `test_16` and `test_17` fail in all three modes (6 failed).

| Item | Fix | Test |
|---|---|---|
| OFF79-03: restore checked "unsent draft" by a read and then wrote unconditionally. Racing `/send`, it left the offer Sent at 12 while the send snapshot said 1200. | `/send` is now a CAS on the draft as read (status Draft, `sent_at` empty, not superseded, same `updated_at`). The loser gets **409 `OFFER_CHANGED`**, and the snapshot is written only after the CAS, so it equals what was sent. `restore` is a CAS on the same condition, written BEFORE its backup; the loser gets **409 `OFFER_IN_USE`**. `PUT /offers/{id}` and `PUT /offers/{id}/lines` carry Draft / never sent / not superseded in their write filter; the loser gets **409 `OFFER_IN_USE`**. | `test_16`: ×10 restore ∥ send and ×10 lines PUT ∥ send, × 3 modes. Exactly one wins every round. A Sent offer always has total 1200 and exactly one Sent snapshot with 1200. |
| Legacy pairs: v1/v2 linked before OFF-01 (v1 never marked superseded) could both end Accepted. | `/accept` and the public approve walk the `parent_offer_id` family (up to the root, down to every version), inside the acceptance transaction. Another Accepted version → **409 `OFFER_FAMILY_ALREADY_ACCEPTED`** (public: neutral text, no ids). A `$inc family_accept_guard` on the family root makes two concurrent acceptances of one family write-conflict, so the check cannot be skewed. | `test_17`: a pair, a 3-version chain, and ×10 accept(v1) ∥ public approve(v2) × 3 modes → exactly one Accepted. |

New field: `family_accept_guard` (a counter on a family's root offer; a concurrency stamp only, no business meaning).

**Debt D-OFF01-13:** legacy pairs are now guarded at accept time, but the older version is still not marked `Superseded` (no backfill). A migration that marks every parent with a child as superseded is a data change → Krum.

## Round 4 (07.11) — OFF79-04 (medium): one CAS per draft write with derived totals

**Reproduced first** (`852e12f` = tests only, on `e0dce63` code): `test_18` (30 rounds/mode) fails in 3 of 3 modes, twice in a row. The audit probe O10 fails 6 of 45. Symptom: `PUT /offers/{id} {"vat_percent": 9}` ∥ `/send` → Sent with VAT 9 and total 1200 (should be 1090), and the PUT answers 200.

**Sweep — every write of an offer's derived totals (`subtotal`, `vat_amount`, `total`):**

| Write | Before | After |
|---|---|---|
| `PUT /offers/{id}` (header, VAT) | 2 writes: header, then the totals (result unchecked) | the totals are computed first from the lines as read, then ONE CAS (draft filter + `updated_at`); lost → 409 `OFFER_IN_USE`. The totals are always rewritten, consistent with the lines. |
| `PUT /offers/{id}/lines` | CAS on draft only (cd0eea1) | + `updated_at`, so a concurrent VAT change is not overwritten with stale totals |
| `POST /offers/{id}/versions/{n}/restore` | CAS draft + `updated_at` (cd0eea1) | unchanged |
| `POST /offers/{id}/send` (freezes the totals in the snapshot) | CAS draft + `updated_at` (cd0eea1) | unchanged |
| `POST /offers/{id}/new-version` (copies lines and totals) | parent CAS on status / not superseded | + `updated_at` (a Draft can now be versioned, Addendum A §2) |
| `POST /offers`, `POST /offers/import-confirm`, extra-works create-offer | insert a new document | not racy, unchanged |

No other module writes offer totals (`grep offers.update_one|update_many|find_one_and_update|replace_one` → only `offers.py` and `offer_versions.py`). There is no discount write on offers.

`test_16` was relaxed to the real invariant. A restore or lines PUT that finished BEFORE `/send` read the offer is legitimately sent, so both answer 200. A Sent offer always equals its one Sent snapshot (lines and total), and its totals add up. The test is still red on `449c1f4` (6 of 6).

**Gates on `bfc41f5`** (real `mongo:7.0` rs0, run one after another):

| Gate | Result |
|---|---|
| OFF-01 (63 cases) + audit probe (147) + PM-01 + all `test_pay_01*` + A1 collision matrix | **851 passed, 0 skipped** |
| R0 | **814 passed** |
| W0 | 1173 passed, **the same 15** failed (`test_w0_03e_legacy_routes.py`) |
| A2C / A1 guards | 214 modules / 432 units, 0 violations |
| A1 inventory | 384 accesses (FIXED 132, SAFE 252), regenerated by its script |
| PM-01 | harness re-run: matrix byte-identical (only `seconds` changed, not committed) |

Note: an earlier gate run (on `cd0eea1`) showed 75 W0 failures because the local `mongod` crashed (exit 14) while two suites ran against it at once. The server was recreated and every gate re-run sequentially; the numbers above are from that clean run.

## Round 5 (07.11) — Addendum B, FLOW Guard pass 14 (package @ `c559ad7`)

**Reproduced first** (`fcfe9f0` = tests only, on `bfc41f5` code): **12 failed**, 3 passed. The 3 that pass are `test_20` on mongomock, which does not interleave two requests; on real Mongo it fails in all 3 modes.

| FG | Fix | Test |
|---|---|---|
| FG-135 (high): a legacy pair (v1 Sent 1200, v2 Sent 1500, v1 never superseded) — the client accepted v1 by its old link | Any version that has a newer version (a child, by `parent_offer_id`) is superseded, whatever the child's status. `/accept`, the public respond (approve, reject, revision), new-version and `GET /offers/review/{token}` refuse it with `OFFER_VERSION_SUPERSEDED`. The check runs before AND inside the transaction (inside `_family_guard` for approve). No data migration: legacy rows are untouched. | `test_19` (child Sent / Draft / Rejected / Cancelled) |
| FG-136: DELETE ∥ send hard-deleted a just-sent offer, and send answered 500 | `DELETE /offers/{id}` is one conditional single-document delete: unsent, unlinked draft (`status Draft`, `sent_at` / `review_token` / `parent_offer_id` / `superseded_by` empty) with the `updated_at` as read. It is atomic on its own, so no transaction is needed. If `/send` won → 409 `OFFER_IN_USE`. `/send` never answers 500: if the offer vanished it returns 409 `OFFER_CHANGED`. | `test_20` ×10 × 3 modes, mongomock + real |
| FG-137: `signed_pdf` without a file was accepted | `signed_pdf` without `evidence_file_id` → 422 `EVIDENCE_FILE_REQUIRED` (the file is then checked as in Addendum A §3). `verified_email` → 422 `VERIFIED_EMAIL_NOT_SUPPORTED`. There is no model of a verified client address and no record of the e-mail citing offer id + version, so it is never accepted without proof (debt D-OFF01-14). | `test_21` |
| FG-138 part 1: a revoked or superseded link returned the whole old offer with prices | Superseded (also a legacy parent with a child) → **410** `OFFER_VERSION_SUPERSEDED`; cancelled or revoked → **410** `OFFER_NOT_OPEN`. The answer is a neutral Bulgarian text only, with no title, lines, prices, totals or ids. The review page shows the message. | `test_22` |
| FG-138 part 2: the client view shows `material_unit_cost` / `labor_unit_cost` | **HELD** — the orchestrator is asking Krum first. Not changed. | — |
| FG-139 (low): `review_token` stored in plaintext | **Debt D-OFF01-15**, not a small change. The editor rebuilds the "copy link" from `offer.review_token` on every load, so a hash-only store needs a new "re-issue link" flow. `resolve_review_token` (the one deliberate cross-tenant lookup), the respond CAS and the review page key on the plaintext. Existing tokens need a migration or a dual lookup. | — |

My own tests were adjusted only where Addendum B changes the expected answer:
- `test_02`: the review page is now 410.
- `test_04`: `verified_email` is now 422, so the key-reuse case uses `signed_pdf` with another file.
- `test_17`: a parent with a child is now `OFFER_VERSION_SUPERSEDED`; only the newest version can win the race.

New debts:

| ID | Debt |
|---|---|
| D-OFF01-14 | `verified_email` needs a verified client address (FLOW-002 contacts) and the e-mail itself (cites offer id + version) in the File Registry; until both exist it is refused (422). |
| D-OFF01-15 | FG-139: hash-only storage of `review_token` (sha256) with a re-issue flow for the link and a migration of existing tokens. |

### R43 (Krum, 07.11.2026) — FG-138 part 2, decided

Canon: `RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md` Р43 @ `d420096`. Red first: `539c8f3` (tests only), `test_23` fails in 3 of 3 modes on `3a291a4`.

| Client-facing output | After |
|---|---|
| `GET /offers/review/{token}` | each line → `client_line()`: `id, activity_name, unit, qty, unit_price (= material + labour), line_total, note, sort_order`. No `material_unit_cost`, `labor_unit_cost`, `line_material_cost`, `line_labor_cost`, `labor_hours_per_unit`. |
| `POST /offers/review/{token}/respond` | it already returned only `{ok, status}` (tested) |
| `GET /offers/{id}/pdf` (the document sent to the client) | the columns „Мат./ед“, „Труд/ед“ and „Мат. общо“ are replaced by one „Ед. цена“ (tested by extracting the PDF text) |
| `OfferReviewPage.js` | one „Ед. цена“ column |

| ID | Debt |
|---|---|
| D-OFF01-16 | `GET /offers/{id}/xlsx` still has the material/labour split. It is the internal working export (the same format as the import). If it is ever sent to a client, it needs a client variant. |

### Gates on `dde064a` (real `mongo:7.0` rs0, run sequentially)

| Gate | Result |
|---|---|
| OFF-01 (81 cases) + audit probe (147) + PM-01 + all `test_pay_01*` + A1 collision matrix | **869 passed, 0 skipped** |
| R0 | **814 passed** |
| W0 | 1173 passed, **the same 15** failed (`test_w0_03e_legacy_routes.py`) |
| A2C / A1 guards | 214 modules / 432 units, 0 violations |
| A1 inventory | 385 accesses (FIXED 132, SAFE 253), regenerated by its script |
| PM-01 | harness re-run: matrix byte-identical |

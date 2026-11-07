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
| D-OFF01-2 | A new version of an **Accepted** offer: the accepted version keeps status `Accepted` (it was accepted; budgets/P&L read it) and only gets `superseded_by`. Which version counts for budgets, contracts and acts once the new one is accepted is not in the canon. |
| D-OFF01-3 | Cancelling an **Accepted** offer is refused (409): it touches contract/annex rules (FLOW-004) the canon does not state here. |
| D-OFF01-4 | Undoing a mistaken new version (cancel the new draft → the old one stays superseded, it is not reopened). Whether to "un-supersede" is a business rule. |
| D-OFF01-5 | Internal `/accept` does not yet REQUIRE an Interim Approval Receipt carrier (signed PDF / verified email with `file_id`). It records the method sent, or `internal_unspecified`. Making it mandatory changes the button's behaviour → Krum. |
| D-OFF01-6 | No UI button for „Анулирай“ yet (API only). |
| D-OFF01-7 | `POST /offers/{id}/versions/{n}/restore` (`offer_versions.py`) overwrites the lines of an offer in ANY status (also Sent/Accepted) — a silent edit FLOW-003 forbids; `DELETE /offers/{id}/versions/{n}` hard-deletes version snapshots. Out of this package. |
| D-OFF01-8 | `NeedsRevision` (client asked for a correction) cannot be versioned (`new-version` allows only Sent/Accepted/Rejected — unchanged rule); the client's request has no path to a new version. |
| D-OFF01-9 | A crash between the transaction commit and `complete_idempotent` leaves the key STARTED: a retry with the same key gets 409 `IDEMPOTENCY_IN_PROGRESS` (never a double write). The same limitation as PAY-01's `_once`. |
| D-OFF01-10 | `_require_key` / `_once` are imported from `app.routes.finance` (reuse, not a copy). Moving them into a shared service is a refactor for later. |
| D-OFF01-11 | Two audit trails remain (legacy `audit_logs` + `offer_events` + canonical `audit_events`): W0-04 known debt. |

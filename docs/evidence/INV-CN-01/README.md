# INV-CN-01: invoices locked at issue, cancellation, credit and debit notes (FLOW-006)

- **Package:** `docs/architecture/tasks/INV-CN-01_CREDIT_DEBIT_NOTES.md` (branch `claude/happy-meitner-bmcnel` @ 344c197).
- **Decisions:** Р49, plus Р47 for the incoming side (`RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`).
- **Oracle:** Q004 (`claude/flow-guard` @ 19ca622).
- **Canon:** FLOW-006 §Корекции; FLOW-025 L101, L124, L144; FLOW-004 L96–104; FLOW-005 L98; FLOW-010 L352–360 and L389; FLOW-034 L68 and L72; CLAUDE.md §2.9, §7, §8.
- **Branch:** `claude/inv-cn-01-credit-notes`, from main cd03324. It is a draft PR: nothing is merged or deployed.

## Source of truth

| Record | Where | Rule |
|---|---|---|
| Invoice | `invoices` | Its own `total` and `lines` are never rewritten after issue. It also carries **derived** sums (`credited_amount`, `debited_amount`, `offset_in_amount`, `offset_out_amount`, `refunded_amount`, `credit_balance`). `update_invoice_status` recomputes them from the source rows inside the same transaction. |
| Credit / debit note | `credit_debit_notes` (new) | A separate immutable document (FLOW-025 L144) with `kind`, `direction`, `number`, `original_invoice_id`, lines that point at the original's lines (qty or amount), net/VAT/gross kept separately, `reason`, `file_id`, `basis`, `version`, `approval`. |
| Refund of a credit balance | `finance_payments` (the ONE ledger) | A payment row with `refund_invoice_id`. |
| Offset | `invoice_offsets` (new) | An explicit record with both source invoices, `pending_approval` → `approved`. |
| Number sequence | `org_counters` `{counter_type: "invoice_document_number"}` | One atomic per-tenant counter shared by outgoing invoices and outgoing notes. It is seeded once, above the highest number already used. |
| Supplier credit awaited | `expected_credit_notes` (from PR #82) | Read and closed here; written by #82. |

## Statuses and lock (Р49.1–2)

- `Draft` (no number, editable) → `POST /finance/invoices/{id}/issue` → `Issued`. Issuing assigns the number and locks the invoice. `send` → `Sent`; a Draft is issued first. Payments then move it to `PartiallyPaid` / `Paid`.
- **Lock:** any change to an amount, line, VAT rate, counterparty, number, date or project of a non-Draft invoice → **409 `INVOICE_LOCKED`**, and nothing is written. Only `notes` and `due_date` stay editable.
- **No hard delete:** an outgoing invoice that carries a number → **409 `INVOICE_NUMBERED`**. An unnumbered draft can still be deleted.
- **Cancellation:** requires a reason (400) and an Idempotency-Key (428).
  - An outgoing invoice can be cancelled only while it is `Issued`: not sent, no payment, no note, not in a VAT period. The number stays, with status `Cancelled`.
  - Otherwise → **409 `USE_CREDIT_NOTE`**.
  - A draft → 409 `INVOICE_NOT_ISSUED`.

## Notes (Р49.2–5, 7)

- **Endpoints:**
  - `POST /finance/credit-notes`
  - `POST /finance/credit-notes/{id}/approve`
  - `GET /finance/credit-notes[?invoice_id]`
  - `GET /finance/credit-notes/{id}`
  - `GET /finance/invoices/{id}/corrections` (read-only; it also computes the 14-day escalation)
- **Outgoing note:** an Owner, Admin or Accountant creates it as `pending_approval`, with no number and no effect. The **Owner** approves the **exact version**:
  - the author approving → 409 `SAME_PERSON_APPROVAL`;
  - a non-Owner → 403;
  - another version → 409 `VERSION_MISMATCH`.
  - Only on approval does the note get its number and change the open amount.
- **Credit cap:** credited per line ≤ invoiced on the line − already credited → otherwise **409 `CREDIT_EXCEEDS_INVOICED`**. It is checked at creation and again at approval, inside the transaction that claims the invoice, so it is safe under concurrency.
- **Debit to a client:** requires an approved act of the same project (`basis: {type: "act", id}`) → otherwise **422 `DEBIT_NOTE_BASIS_REQUIRED`**.
- **Effect:** the note changes the open receivable or payable; the invoice total and the contract value are never touched. P&L: approved outgoing notes change the project revenue (net) of the original invoice's project, dated by the note's own `issue_date`.
- **Act (Р49.5):** `act_id` on an outgoing invoice requires an `Accepted` act.
  - At issue, the act's net invoiced amount (issued invoices − credited + debit notes on this act) must stay ≤ the act's net value → otherwise **409 `ACT_OVER_INVOICED`**. The act document is claimed in the transaction, so this is safe under concurrency.
  - A credit note gives the amount back. The act's quantities are never touched.

## Paid invoice (Р49.6)

- A credit on a paid invoice leaves a `credit_balance`. Nothing is netted automatically.
- **(a)** `POST /finance/invoices/{id}/refund`: a payment in `finance_payments`. It requires an Idempotency-Key and is capped at the balance (409 `REFUND_EXCEEDS_BALANCE`).
- **(b)** `POST /finance/offsets` creates a `pending_approval` offset. The scope must be the same contract (409 `OFFSET_ACROSS_CONTRACTS`), and the amount must be ≤ both the balance and the target's open amount (409 `OFFSET_EXCEEDS_BALANCE`).
  - **Every** offset needs a second approval: `POST /finance/offsets/{id}/approve` by the Owner, a different person, on the exact version. The "large" threshold is not decided (D3), so no amount was invented.

## Incoming credit note (Р47, Р49.8)

- The Accountant registers it with the supplier's number. A duplicate (same supplier, same number) → **409 `DUPLICATE_CREDIT_NOTE`** (unique index).
- It is matched with the invoice's open `expected_credit_notes`:
  - **equal to the cent:** the rows become `fulfilled`, the DQ task closes, and the note applies, so the payable and the payment limit are recomputed;
  - **a difference:** the note is registered but **not applied** (the limit stays), and the rows get the DQ `разлика в кредитно известие`;
  - **nothing awaited:** the note applies.
- **Escalation:** after 14 days the Owner sees `escalate_to_owner` on the corrections read. It is computed on read and nothing is stored.

## Every write

Every write follows the same steps:

1. `finance_permission` (Owner/Admin/Accountant), or Owner only for an approval.
2. Idempotency-Key (R29, 428), via `_once` = `begin_idempotent`.
3. One transaction through `auth_tx.run_in_transaction`, with a CAS on every document it decides on (`claim_invoice`, the act claim, the conditional note/offset update).
4. Canonical `record_event(..., session=...)` in the same transaction.

Indexes are created idempotently before the transaction (`invoice_corrections.ensure_indexes`). On a deployment without transactions, the response is 503 `TRANSACTIONS_UNAVAILABLE` and nothing is written.

## UI (minimal)

- `InvoiceEditorPage`: an "Издадена"/"Изпратена" status, editing only for Draft, "Анулирай" (asks for a reason, sends a key) only for an Issued, unsent invoice, and errors shown in Bulgarian (`detail.message`).
- The new `InvoiceCorrectionsPanel` has "Кредитно известие" and "Дебитно известие" buttons, the list of notes, "Одобри" for the Owner (not for the author), and the awaited supplier credit with its escalation.

## Changes to existing tests (intended by Р49, not a regression)

`tests/test_pay_01_payment_reversal.py` has two assertions that encoded the behaviour Р49 changes:

- `test_04`: cancelling a **Sent** invoice is now 409 `USE_CREDIT_NOTE` (it was 200).
- `test_06`: deleting a **numbered** draft is now 409 (it was 200); an unnumbered draft still deletes.

All other PAY-01 assertions are unchanged.

## Rollback

Revert the PR. The rows already written stay valid for the previous code: the derived invoice fields are ignored, and notes and offsets live in their own collections.

The new partial unique indexes constrain only documents that carry `issued_number` / `number`. They can be dropped by name (`inv_cn_01_*`).

Invoices issued meanwhile have status `Issued`, which the previous code does not know. A one-line data fix maps `Issued` → `Sent` (they are official in both meanings). This needs Krum's approval if it is ever needed.

## Overlap with open PRs: "whichever merges second"

| PR | Overlap | Who resolves it |
|---|---|---|
| #82 WH-REV-01 | Both add `expected_credit_notes` to `ownership.py` (keep one entry). | Whichever merges second. |
| #82 WH-REV-01 | #82's `_awaited_credit` cap in quick-pay/allocate and this branch's `_invoice_remaining` (now the adjusted total) touch neighbouring lines in `finance.py`: keep both. | Whichever merges second. |
| #82 WH-REV-01 | The PM-01 matrix and the A1/A2B inventories must be regenerated with the harness/scripts on the merge, never hand-merged. | Whichever merges second. |
| #69 SEC-01 | New endpoints use `finance_permission` (Owner/Admin/Accountant), like the rest of `finance.py` on main. Moving issue/cancel/notes/refund/offset to `require_money_write(...)` plus catalog actions belongs to whichever merges second. The 1-cent quick-pay tolerance is main's rule (#69 makes it whole cents). | Whichever merges second. |

**FG-196 coupling with #82 (orchestrator request):** registering the incoming credit note through `POST /finance/credit-notes` is the step that lifts #82's 409 `INVOICE_AWAITS_CREDIT_NOTE`.

- It reads #82's `expected_credit_notes` rows (`invoice_id`, `amount`, `status: open`, `dq_task`).
- When they match to the cent, it sets them `fulfilled` and closes `dq_task`.
- It also sets `awaiting_credit_note: false` on the invoice, so `_awaited_credit` returns 0 and the cap becomes the net payable.

`test_r47_registration_releases_the_pr82_cap` checks this. On a local trial merge with #82 @ 1622f62: **161 passed, 0 skipped** (`r47_coupling_pr82.txt`).

## Addendum A (FLOW Guard pass on 7446d85 + Р51): point → code → test

Every test below runs on real Mongo in off / shadow / enforce. The same test file run against the previous head 3893b9f fails all of them (`addendum_a_red_on_3893b9f.txt`).

| Point | Fix | Test |
|---|---|---|
| **FG-217** second draft → 500 | A draft stores **no** `invoice_no` field. The number index is partial (`invoice_no > ""`) and keyed by `direction`, so a supplier number never blocks our series. On a tenant still on the legacy unique+sparse index, a clash is 409 `INVOICE_NUMBER_TAKEN`, never 500. `scripts/inv_cn_01_migrate.py` (dry run by default, `--apply --actor`) drops the legacy index. | `test_fg217_many_drafts_and_supplier_numbers_never_block_our_series` |
| **FG-218** manual number blocks the series | `take_number` skips a number already used by our series, inside the same transaction, so the series never blocks. | `test_fg218_a_manual_number_inside_the_series_is_skipped_never_blocks` |
| **FG-219** "до стотинка" | Exact equality after rounding to cents. A 1-cent difference is a mismatch (DQ, not applied). | `test_incoming_credit_note_matches_awaited_credit_and_lifts_the_limit` (35.99 vs 36.00) |
| **FG-220** linked by the Accountant | `expected_credit_note_ids` is required when the invoice has an open awaited credit (422 `EXPECTED_CREDIT_LINK_REQUIRED`); a wrong or closed id → 422 `EXPECTED_CREDIT_LINK_INVALID`. Nothing is ever linked by amount. | same test; `test_r47_registration_releases_the_pr82_cap` |
| **FG-222** offset basis | `legal_basis` + `file_id` + `source_credit_note_id` (an applied credit note on the source invoice) are required (422 `OFFSET_BASIS_REQUIRED`). The amount must be ≤ the unused part of that note. | `test_offset_same_contract_needs_a_second_person` |
| **Р49(1)** legacy numbered drafts | Treated as issued (locked) right away (`is_locked`). The migration makes them `Issued` with `issued_number` and one AuditEvent each (`finance.invoice.issued_by_migration`). It is idempotent, with a dry-run report. | `test_r49_1_legacy_numbered_draft_is_locked_and_migrated_to_issued` |
| **Р49(1)** due date after issue | Needs a `reason` (400 `DUE_DATE_REASON_REQUIRED`) and writes an AuditEvent `finance.invoice.due_date_changed`. | `test_r49_1_due_date_after_issue_needs_a_reason_and_an_audit_event` |
| **Р51(1)** cancellation approval | `POST …/cancel` is the proposal (reason, key). `…/cancel/approve` is by the Owner, another person, on the exact version (409 `SAME_PERSON_APPROVAL` / `VERSION_MISMATCH`). `…/cancel/reject` is by the Owner or the proposer. Every condition is re-checked at approval. | `test_cancel_issued_unsent_invoice_keeps_its_number`, `test_r51_1_the_proposer_cannot_approve_and_a_proposal_can_be_rejected` |
| **Р51(2)** supplier debit note | Basis (`order` / `additional_delivery` / `annex` + ref) and `file_id` are required (422). The note stays `pending_approval` until the Owner approves; until then a payment above the open amount → 409 `DEBIT_NOTE_NOT_APPROVED`. | `test_r51_2_supplier_debit_note_needs_basis_file_and_owner_before_it_is_payable` |
| **Р51(3)** supplier invoice entered by mistake | The Accountant cancels it with a reason, if it is not paid and not linked to a warehouse receipt; otherwise 409 `USE_CORRECTION`. An invoice with any number is never deleted. | `test_r51_3_supplier_invoice_entered_by_mistake_is_cancelled_not_deleted` |
| **Р51(4)** / D3 | Every offset needs a second person (the Owner). | `test_offset_same_contract_needs_a_second_person` |

## Addenda B (Р52) and C (Р53, FLOW Guard re-check @ 71957db): point → code → test

Every test runs on real Mongo in off / shadow / enforce. The same file fails these tests on the previous head 5cce932 (`addenda_bc_red_on_5cce932.txt`), except D12, which pins existing behaviour.

| Point | Fix | Test |
|---|---|---|
| **Р52(1) D8** | A supplier credit/debit note **linked to a receipt reversal** (`expected_link.rows`) only changes the payable; it has no second P&L effect. A note **without** a reversal changes the cost of the original line's project once: Path B project allocations by quantity share, else the line's / invoice's project (`supplier_note_cost_effect`, `expense.supplier_notes_cost_reduction`). | `test_r52_d8_unlinked_supplier_credit_reduces_project_cost_once_linked_does_not`; with a **real #82 reversal** on the trial merge: `r52_d8_trial_merge_pr82.md` (3 passed) |
| **Р52(2) D7** | A mismatch closes either (a) when a corrected note is registered — the DQ closes and the mismatched note is `superseded_by` — or (b) when the **Owner** accepts the difference (`POST /finance/credit-notes/{id}/accept-difference`, reason + AuditEvent; the Accountant → 403). The note then applies with its real amount, so the limit = net received − the note. | `test_r52_d7_owner_accepts_the_difference_limit_uses_the_real_amount`, `test_incoming_credit_note_matches_awaited_credit_and_lifts_the_limit` |
| **Р52(3) D12** | The counter is not reset on a prefix change (`BG-0003` after `INV-0002`). | `test_r52_d12_prefix_change_does_not_reset_the_counter` |
| **FG-231 / Р53(1)** | Supplier invoices are unique per (org, `supplier_key`, number): ЕИК, else counterparty record, else name. Ours are unique per (org, outgoing, number). Two partial unique indexes; 409 `DUPLICATE_SUPPLIER_INVOICE`. The migration backfills `supplier_key` and refuses while conflicts exist. | `test_fg231_same_number_from_two_suppliers_is_fine_same_supplier_is_a_duplicate`, `test_fg231_migration_backfills_supplier_key_and_reports_conflicts` |
| **FG-232** | PUT of a draft uses `invoice.get("invoice_no")` (a draft has none), so there is no KeyError. Tested with the exact InvoiceEditorPage payload. | `test_fg232_editor_put_of_a_draft_with_a_typed_number_is_not_a_500` |
| **FG-233** | Cancelling a wrong supplier invoice also checks receipts linked **only by `invoice_id`**, and bumps the per-line locks in the cancel transaction → 409 `USE_CORRECTION`. | `test_r51_3_supplier_invoice_entered_by_mistake_is_cancelled_not_deleted` |
| **FG-234 / Р53(2)** | Only the Accountant or Admin proposes an outgoing cancellation (the Owner → 403 `CANCEL_ROLE_REQUIRED`); the Owner approves. A pending proposal becomes `superseded` (AuditEvent `finance.invoice.cancellation_superseded`) when the invoice is sent or paid. | `test_r51_1_the_proposer_cannot_approve_and_a_proposal_can_be_rejected` |
| **FG-235** | Changing the notes of an issued/sent invoice writes AuditEvent `finance.invoice.notes_changed`. A wrong supplier invoice is cancelled by the **Accountant only** (Admin/Owner → 403). | `test_fg235_notes_change_on_a_sent_invoice_is_audited`, `test_r51_3_…` |
| **FG-217** Release Manifest | The migration step (dry run → Owner approval → `--apply`) is documented. | `RELEASE_MANIFEST_NOTE.md` |
| VAT of a supplier line (found by the D8 trial test) | A note line on an `invoice_lines` row uses the line as invoiced: `line_total_ex_vat` and VAT = `vat_amount` / net, else the module's 20 % default (same reading as `compute_line`). | the trial-merge D8 test (48.00 = expected) |
| **INV84-01** (canon-backed test changes, Р49.1 / Р49.2 / Р51(3)) | The two `c26l_n_invoice_status` tests follow the new rules (see the debt table row INV84-01). | `warehouse_suite.txt` |

## FLOW Guard pass 25 (on 081f35b): point → code → test

| Point | Fix | Test |
|---|---|---|
| **FG-246** (high) | `_cancel_blockers`: an invoice that is the source or target of a **pending or approved offset** is not cancelled → 409 `USE_CREDIT_NOTE`. Approving an offset supersedes a pending cancellation proposal of both invoices (AuditEvent `finance.invoice.cancellation_superseded`, cause `offset`). | `test_fg246_an_invoice_in_an_offset_is_not_cancelled_and_the_offset_supersedes_a_proposal` |
| **FG-247** (a)–(d) | The supplier-note effect lives **inside `canonical_material_cost.project_material_cost`**, THE cost source of every reader (P&L, financial results, full cost, SMR reports; D-04). The P&L no longer adds its own correction.<br>• (a) Only a line that IS in the project's cost base counts: a supplier `invoice_lines` row allocated to the project (Path B), by share. A credit never takes more than the line's counted value. An invoice with only embedded lines has no cost base, so a credit on it changes nothing.<br>• (b) One number for every reader.<br>• (c) `project_input_vat` is corrected pro rata (20 → 10).<br>• (d) Each note is a cost line dated by the note's `issue_date`, so it lands in the note's period. | `test_r52_d8_unlinked_supplier_credit_reduces_project_cost_once_linked_does_not` (it reads the helper, the P&L, the financial results, input VAT and `cost_by_period`) |
| **FG-248** | Before the migration, the runtime duplicate check also matches legacy rows without `supplier_key` by ЕИК, else counterparty record, else name. The per-supplier unique index is built **only by the migration**, after its backfill — never at startup. | `test_fg248_before_the_migration_a_legacy_supplier_number_still_blocks_a_duplicate` |
| **FG-233** | A supplier receipt that names the invoice (`invoice_id`) writes the per-invoice lock document (`invoice_lock:<org>:<invoice>`) in its transaction and refuses a cancelled invoice (409 `INVOICE_CANCELLED`). The cancel writes the same document in its transaction, so the two never both commit. | `tests/test_inv_cn_01_fg233_receipt_race.py` (after cancel → refused; after receipt → 409 `USE_CORRECTION`; **racing → exactly one commits**) |
| Merge | main **0750d75** (#71 SEC-02) merged with a merge commit (5463b8e). PM-01 and `run_meta` regenerated by the harness. | `gates.txt` |

## Addendum D (Р55, FLOW Guard pass 25 decisions): point → code → test

| Point | Fix | Test |
|---|---|---|
| **FG-249 / Р55(1)** | A supplier invoice must carry the supplier's **ЕИК**, or for a foreign supplier its tax number (`counterparty_foreign_tax_no`, new optional field; supplier identity `tax:<number>`) → otherwise 422 `SUPPLIER_TAX_ID_REQUIRED`. A PUT that changes the number **or** the supplier identity is checked per supplier → 409 `DUPLICATE_SUPPLIER_INVOICE`; a `DuplicateKeyError` in the update transaction is a 409, never a 500. The migration gives every legacy supplier invoice without one the DQ task `dq_tasks.supplier_tax_id_missing` (assignee: accountant). | `test_fg249_supplier_tax_id_is_mandatory_duplicates_by_put_are_409_legacy_gets_dq` |
| **FG-250 / Р55(2)** | A supplier credit/debit note is registered by the **Accountant only** (others → 403 `REGISTRAR_ROLE_REQUIRED`). The Owner accepts a difference and must not be the registrant → 409 `SAME_PERSON_APPROVAL`. | `test_fg250_accountant_registers_owner_accepts_never_the_same_person` |
| **FG-251 / Р55(3)** | When the Owner accepts a difference on a note linked to a reversal, the part the supplier did not credit stays a cost of the original line's project. It is net (the note's own VAT ratio), by the line's project share, and dated on the **acceptance** (its period), as a line of THE cost source. The AuditEvent carries `difference_gross` and `cost_period`. | `test_fg251_an_accepted_difference_after_a_reversal_is_project_cost_in_the_acceptance_period` (36.00 awaited, 30.00 credited → +5.00 net in the acceptance month; helper and P&L agree) |
| Main | **ec7ddd8** (#85 docs, R55) merged with a merge commit (5692247). | — |

## FG-264 (FLOW Guard on 2c2e75f) and the FG-249 note

| Point | Fix | Test |
|---|---|---|
| **FG-264** | A supplier invoice's create, and any edit of its number or supplier, decides "same supplier + number?" and writes **in ONE transaction under the (supplier, number) lock document** (`org_counters`, `_id supplier_invoice_lock:<org>:<supplier_key>:<number>`), so concurrent requests are serialised with or without the unique index. The per-supplier unique index is built **at startup and at first use** (`ensure_indexes`) wherever the data allows, which covers every fresh/new tenant and every migrated one. A legacy database whose rows collide refuses the build and keeps the lock-serialised check until `inv_cn_01_migrate.py` backfills and builds it. | `test_fg264_parallel_creates_of_one_supplier_number_one_wins_with_or_without_the_index`: 6 parallel POSTs → **1×201 + 5×409**, (a) on a fresh tenant with no migration, (b) on a legacy database where the index cannot be built |
| **FG-249 note** | The DQ for a legacy supplier invoice without ЕИК / tax number is a **canonical `dq_issues` record** (new tenant collection, registered in `ownership.py`): one per (kind, entity) with a deterministic id, `kind = supplier_tax_id_missing`, `entity_type = finance.invoice`, `assignee_role = accountant`, `status = open`. It is idempotent. | `test_fg249_…` (record shape + a second apply adds nothing) |

Red proof against 2c2e75f: `fg264_red_on_2c2e75f.txt`.

## Addendum E: Р58 (FG-265, decided by Krum 08.11)

| Point | Fix | Test |
|---|---|---|
| **Р58** (+ Q007) | When the Owner accepts a supplier credit difference, the uncredited difference (net, by the note's own VAT ratio) is **split over the note's lines and the target frozen at acceptance** (`difference_accepted.split`): a line received **into the warehouse** (a canonical ledger movement naming the line, or the invoice with no line) → `company`; any other line → `project` (FG-251, unchanged). The company part is a **company cost (loss on the return) in the period of acceptance**; `difference_accepted.company_cost` and the **AuditEvent** `finance.credit_note.difference_accepted` carry the split, `company_cost` and `cost_period`. **FIFO prices and the warehouse ledger are not touched.** A read-only `GET /finance/company-costs/accepted-differences?period=YYYY-MM` derives the company cost from the accepted notes (no second ledger); the panel shows it on the note. Q007: it is a separate line "Фирмени загуби (не се разпределят)" of the final company result (`/org/pnl-attribution`; D17). | `test_r58_an_accepted_difference_on_a_warehouse_line_is_a_company_cost_fifo_unchanged`: a note on a warehouse line + a project line, difference 12.00 gross → 10.00 net = 5.00 company (period of acceptance, in the reader; not in the project's cost) + 5.00 project (FG-251); the warehouse ledger is byte-identical before/after; AuditEvent fields; another tenant sees nothing; 3 modes |

Red proof against b99c0eb: `r58_red_on_b99c0eb.txt`. On b99c0eb the warehouse part of an accepted difference was booked **nowhere**.

## FLOW Guard pass 27 (on caea933): point → code → test

| Point | Fix | Test |
|---|---|---|
| **FG-269** | The target of an accepted difference is decided **per line by the destination of the line's own canonical receipt** (`classify_difference_line`): `receive_from_supplier` (into a warehouse) → `company` (Р58); `receive_from_supplier_to_project` (direct delivery) → `project` **of that delivery** (Р55(3)), stored as `split[].project_id`, so the project gets the whole line part even without a Path B allocation. | `test_fg269_fg270_the_difference_follows_each_line_s_own_receipt_destination`, part 1: a direct delivery to prj-1 → `project/direct_delivery/prj-1`, +5.00 on prj-1, company losses 0 |
| **FG-270** | A receipt linked **only by `invoice_id`** never reclassifies a line. A line allocated to a project stays `project` (`allocation`). A line that cannot be determined (invoice-level receipt only, or mixed warehouse/direct receipts, or direct deliveries to several projects) → `undetermined`: **no automatic cost** and a canonical `dq_issues` record (`accepted_difference_line_undetermined`, entity `note:line`, `assignee_role=accountant`). | the same test, part 2: the allocated line → project (+5.00), the other → `undetermined` + DQ, company losses 0 |
| **FG-271** | **One** shape, `company_losses_block` (same label, `includes` text, amount, drill-down lines), returned by **every company-result reader**: `/org/pnl-attribution`, `/org/pnl-overview` (+ `totals.company_losses`, `totals.final_profit`; projects untouched) and `/finance/stats`. One UI component, `CompanyLossesLine`, shows it in the dashboard P&L overview, the Финансов pulse result tile, the profit-attribution widget, Финансов анализ and the finance overview. Never in a project P&L. | the `test_r58_…` scenario: the three readers return the identical block; no project row carries it; no overhead record is written |

Red proofs against ef7cddd: `fg_pass27_red_on_ef7cddd.txt`. FG-269: a direct delivery became `company`. FG-270: both lines became `company`. FG-271: neither reader had the line.

## FLOW Guard pass 28 (after the audit of e75b558): point → code → test

| Point | Fix | Test |
|---|---|---|
| **Journal** | Every accepted difference now has an **append-only cost journal**, `difference_accepted.postings`. It holds the `booking` made at acceptance, any FG-277 `resolution`, and any FG-276 `reversal`. Each posting carries its line, signed net, target (project + optional SMR, or company), time, period, author and reason. The project cost (`project_material_cost`) and the company losses read **only** this journal. Nothing in it is edited or deleted. | all below |
| **FG-277** | `POST /finance/credit-notes/{id}/difference-lines/{line_id}/resolve`, body `{target: project\|company, project_id, package_id?, reason}`. Rights per **Р14** (Owner / Admin / Accountant; Viewer and SiteManager → 403); another tenant → 404; Idempotency-Key (428 without), replay-safe. It runs in a transaction under the invoice claim, with a CAS on the journal and an **AuditEvent** `finance.credit_note.difference_line_resolved`. An `undetermined` line is booked in the **acceptance period**. The DQ issue closes. A second resolve → 409. | `test_fg277_fg276_fg278_resolve_reverse_and_scope_of_an_accepted_difference` |
| **FG-276** | `POST /finance/credit-notes/{id}/reverse-difference`, **Owner only**, with a reason. It **appends** reversal postings (−net on the same target, project and SMR) in the **period of the reversal**. Earlier postings stay byte-identical. Each reversed line reopens as a DQ issue for the Accountant and is re-booked through FG-277 in the current period. A second reversal with nothing booked → 409. AuditEvent `finance.credit_note.difference_reversed`. The note (the tax document) and the payable are unchanged. | same test |
| **FG-278** | `company_losses_block(period)` takes the reader's period scope and echoes it as `scope`. Every company-result reader in main sums projects **cumulatively** (no reader has a period filter), so each passes `None` → `{"basis": "cumulative"}`. A period filter, such as `/finance/company-costs/accepted-differences?period=` or a future period reader, gets only that period's postings. `final_profit` never mixes scopes. | same test: three readers, the same block and scope; cumulative 12.00 versus the 2025-01 period 7.00 |
| **FG-271 UI rest** | `CompanyLossesLine` now always shows the line, its amount, the final result and the "what it includes" text; only the drill-down folds. The **„Текущ фирмен резултат“** tile (Финансов pulse, FLOW-015) shows `final_profit`, with the split "Обекти / Фирмени загуби". The profit-attribution **heading** shows the final result. The Финансов анализ **„Печалба“** card shows the final result and the losses. D18 (the FLOW-009 warehouse-loss view) stays a debt. | jest `CompanyLosses.fg271.test.js` (4 tests) |

Red proofs against e75b558: `fg_pass28_red_on_e75b558.txt`. The backend fails 3/3: there is no resolve path. Jest fails 4/4.

## Approved on cdd3dc8 (Krum, 09.11): FG-278 status scope + Р63 (FG-281)

| Point | Fix | Test |
|---|---|---|
| **FG-278 (status scope)** | Every company-result reader now uses **one** project scope, `company_result_project_filter`: **every project of the org, of every status**. Each project is counted on its own P&L; `compute_project_pnl` counts only that project's records, so a subproject is counted once. Before, `/org/pnl-overview` counted only Active/Draft/Paused while `/org/pnl-attribution` counted all root projects, so one Completed project made the two readers disagree. Both readers echo `scope = {projects: all, project_statuses: all}`, and totals, company losses and `final_profit` agree. | `test_fg278_every_company_result_reader_uses_one_project_status_scope`: a Completed project with −100.00; both readers have identical totals |
| **Р63 (FG-281)** | After a reversal, the Accountant (Р14 roles) proposes the re-booking of a line through `…/difference-lines/{line}/resolve`. **The same destination as the reversed booking applies at once.** A line booked by its allocation goes back to that allocation: `target=project` with no id. **Another project, company cost, or a Completed project** → an append-only `proposals` entry only; nothing is booked and the line is locked (409) until decided. `…/difference-proposals/{id}/approve`: **Owner only** (other roles → 403), **never the proposer** (403 `SAME_PERSON_APPROVAL`), another tenant → 404. It posts the re-booking in the current period and closes the DQ issue. `…/reject`: the Owner, or the proposer withdrawing. Decisions are append-only (`decisions`); every write uses the Idempotency-Key, a transaction with CAS on `journal_version`, and an AuditEvent (`difference_rebooking_proposed/approved/rejected`). The panel shows the open lines, the reversal and the proposals. | `test_r63_rebooking_after_a_reversal_same_place_at_once_else_another_owner` |

Red proofs against cdd3dc8: `r63_fg278_red_on_cdd3dc8.txt`.

## Р64 (D20, FG-415) + FG-416 + FG-282; main 1525a1e (#81) merged

| Point | Fix | Test |
|---|---|---|
| **Р64 (FG-415)** | A project is "open" only when it is **Active or Paused** (`OPEN_PROJECT_STATUSES`). A Р63 re-booking onto any other status (Completed, Archived, Finished, Stopped, Cancelled, warranty …), or onto a project that is missing, becomes **a proposal even to the same place**. This covers the projects of the line's own allocation when the destination is "back to the allocation". The status is read **inside the transaction**, both when proposing and **again at the approval**; the decision and the AuditEvent record it. A project that disappeared → 409. The Owner who approves is never the proposer. | `test_r63_…`: Archived + same place → proposal `closed_project` with `{prj-1: Archived}`; the non-Owner gets 403; another Owner approves and the status is re-read as `Completed`; company → company with no project involved → at once |
| **FG-416** | The approve idempotency fingerprint now includes the comment. The same key with another body → 409 `IDEMPOTENCY_KEY_REUSED`; the same key and body → the replay. | same test |
| **FG-282** | Closed by #81 (WH81-03: every project revenue reader filters `direction: Issued`), checked after the merge and pinned by a test. | `test_fg278_…`: a Received invoice of a Completed project → revenue 0, expense > 0 |
| **Merge of #81** | Merged with a merge commit, both sides kept. In `create_invoice`, the WH-FIX-01 Р45 stamp, AuditEvent and DQ run **in the same transaction** as the FG-264 supplier-number insert (an `after_insert` hook). `update_invoice` keeps `_stamp_and_refresh` and the FG-249 409. The FG-233 per-invoice lock sits beside the WH-FIX-01 per-supplier-invoice lock. `_lock_invoice` sits beside `_bind_invoice_line_price`, each with its own `@staticmethod`. | the WH-FIX-01 suites in the gates |

Red proofs against 5242cba: `r64_fg416_fg282_red_on_5242cba.txt`.

## Debts after Addendum A

| # | Status |
|---|---|
| D1 contract model | **Open (needs the model).** No contract on invoices: an offset's "same contract" stays direction + project + counterparty ЕИК, all present. |
| D2 annex model | **Open (needs the model).** An outgoing debit note's basis is an approved act. A supplier debit note's basis `annex` is a reference plus `file_id`, not a record. |
| D3 offset threshold | **Closed by Р51(4).** Every offset needs a second person. |
| D4 VAT ledger / period close | **Open (needs the model).** Cancellation checks `vat_ledger_period`, which nothing sets yet. |
| D5 File Registry | **Open (needs #44).** `file_id` is now **required** for offsets and supplier debit notes, but is not validated against a registry. |
| D6 supplier invoice cancel / delete | **Closed by Р51(3).** |
| D7 resolving a supplier-note mismatch | **Fixed by Р52(2).** |
| D8 P&L cost side of supplier notes | **Fixed by Р52(1).** An ACCEPTED difference on a warehouse line is a company cost (Р58, above). One residual case is open: a credit without a reversal on a line received **into a warehouse** (not allocated to a project) has no project to apply to here. Its effect belongs to the FIFO layer value (FLOW-009), outside this PR. |
| D9 refund reversal | **Fixed.** A reversed refund recomputes its invoice (`test_d9_…`). |
| D10 reject / withdraw | **Fixed** for notes, offsets and cancellation proposals (`test_d10_…`, `test_r51_1_…`, the offset test). A full Approval Center is out of scope. |
| D11 legacy numbered drafts | **Fixed** by the migration with a dry-run report (run on production only after the Owner approves the report). |
| D12 prefix change | **Closed by Р52(3).** No reset; a test pins it. |
| D13 every client invoice from an act or contract stage | **Open (needs the contract-stage model).** |
| INV84-01 | **Fixed.** `test_fg140_claim_honours_the_pay01_invoice_lock` now cancels through the current path: a reason and an Idempotency-Key. The invoice is a **supplier** invoice, so by Р51(3) the Accountant cancels in one step. The core assertion is unchanged: under the PAY-01 lock → 409 `INVOICE_BUSY`, nothing written; after release → Cancelled; in 3 modes. In `test_fg140_send_and_delete_are_conditional`, the stale read is an unnumbered draft (only such a draft may be deleted, Р49/Р51(3)), so the conditional delete is still what refuses. |
| D14 out of scope | Act correction (t24), VAT ledger/export, e-invoice/SAF-T, partial release of retentions, full Approval Center. |
| D15 Overdue in P&L; Paid stays Paid | **Fixed** (`test_d15_…`). Overdue now counts as issued revenue. |
| D16 approver | **Closed.** The Owner approves (Р49.4, Р51). |
| D17 Р58 company cost in company reports | **Closed by the canon (oracle Q007, FLOW-015 / FLOW-024 L170-180).** The company result readers in main (`/org/pnl-attribution`, and per FG-271 also `/org/pnl-overview` and `/finance/stats`) now have a separate line **"Фирмени загуби (не се разпределят)"** (`company_losses`: label, `includes` text, amount, drill-down lines) and `totals.final_profit = profit − company_losses`. The existing `profit` (the sum of projects) is unchanged. The cost is never in a project P&L and never in the overhead allocation base. The dashboard widget shows the line with its drill-down. Test: the `test_r58_…` scenario; red proof `q007_red_on_caea933.txt`. |
| D18 FLOW-009 warehouse losses view | **Open (no such view in main).** Q007 also wants the Р58 company loss visible in a warehouse losses view (FLOW-009). Main has only per-project material waste (`/projects/{id}/material-waste`), no company-level warehouse-losses view. Per Q007 no new screen is invented. Spec for whoever builds it: show the `company_cost_lines` (Р58 accepted differences on warehouse lines) as losses on return, by acceptance period, with drill-down to the note. |
| D19 subprojects in the company result | **Note.** The one scope counts every project on its own P&L. Whether a parent's P&L should instead aggregate its subprojects (`compute_aggregated_pnl`) for the company result is not in the canon. |
| D20 Р63 "Completed" | **Closed by Р64.** Every status other than Active / Paused needs the Owner, even for the same place. |
| SEC-01 (#69, now in main) | **Open.** `finance.py` routes, old and new, still use `finance_permission` (Owner/Admin/Accountant); #69 did not migrate `finance.py`. Moving the whole module to `require_money_write` plus catalog actions is one follow-up, so the module keeps a single rule. |

## Gates (`gates.txt`, FG-278 + Р63 head 639b389; main 44e8d97 merged; real Mongo = disposable local mongo:7.0 rs0, a fresh container per block)

| Gate | Result |
|---|---|
| INV-CN-01 (`test_inv_cn_01_credit_notes.py`, 48 scenarios × 3 modes, + `test_inv_cn_01_fg233_receipt_race.py`, 3 × 3) | **153 passed**, 0 skipped |
| ACT-01 (#77, no regression) | 113 passed |
| OH-01 (#74, no regression) | 231 passed |
| OFF-01 (#79) + SUB-ADV-01 (#76), no regression | 246 passed |
| Red proofs | main cd03324: 57/57; 3893b9f: Addendum A; 5cce932: Addenda B/C; 081f35b: FG-246/247/248, and the FG-233 file does not import; d32a33f: FG-249/250/251; 2c2e75f: FG-264/FG-249 note; b99c0eb: Р58 (`r58_red_on_b99c0eb.txt`); caea933: Q007 (`q007_red_on_caea933.txt`); ef7cddd: FG-269/270/271 (`fg_pass27_red_on_ef7cddd.txt`); e75b558: FG-277/276/278 + FG-271 UI (`fg_pass28_red_on_e75b558.txt`); **cdd3dc8: Р63 + FG-278 status scope** (`r63_fg278_red_on_cdd3dc8.txt`) |
| PAY-01 family | 630 passed |
| R0 (real) | **814 passed** |
| W0 real | 16 failed / 1176 passed — **identical to main in the same environment**: the known 15 `legacy_routes` plus 1 order-dependent `test_w0_03e_real_mongo::test_r1_…` that arrived with #71 (alone: 9 passed) |
| W0 DB-free | the same 15, 1094 passed |
| A2C / A1 guards | 244 / 492, **0 violations**; A1/A2B inventories regenerated by their scripts |
| PM-01 (real, `-rs`) | 6 passed, **0 skipped**; matrix and run_meta regenerated by the harness after the merge of main 44e8d97 (rows for the resolve / reverse / proposal endpoints) |
| Frontend `yarn test` | 20 suites, 183 passed (+ jest `CompanyLosses.fg271.test.js`) |
| Warehouse suite (43 canonical files) | **1117 / 1121**. The 4 failures are in `c13_mongo`, the same as on main here. `material_ledger` is a live-server test that cannot run here. (`warehouse_suite.txt`) |
| Trial merge with #82 @ 1622f62 | INV-CN-01 + FG-233 race + WH-REV-01 + D8 reversal test: **239 passed**, 0 skipped (`r52_d8_trial_merge_pr82.md`, with the `service.py` conflict note) |

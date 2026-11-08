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

## Debts after Addendum A

| # | Status |
|---|---|
| D1 contract model | **Open (needs the model).** No contract on invoices: an offset's "same contract" stays direction + project + counterparty ЕИК, all present. |
| D2 annex model | **Open (needs the model).** An outgoing debit note's basis is an approved act. A supplier debit note's basis `annex` is a reference plus `file_id`, not a record. |
| D3 offset threshold | **Closed by Р51(4).** Every offset needs a second person. |
| D4 VAT ledger / period close | **Open (needs the model).** Cancellation checks `vat_ledger_period`, which nothing sets yet. |
| D5 File Registry | **Open (needs #44).** `file_id` is now **required** for offsets and supplier debit notes, but is not validated against a registry. |
| D6 supplier invoice cancel / delete | **Closed by Р51(3).** |
| D7 resolving a supplier-note mismatch | **Open (for Krum).** |
| D8 P&L cost side of supplier notes | **Open.** A credit for a reversed receipt is already removed from cost by #82 at the warehouse; reducing cost path B again would count it twice. The rule for which credit reduces which cost is not in the canon. |
| D9 refund reversal | **Fixed.** A reversed refund recomputes its invoice (`test_d9_…`). |
| D10 reject / withdraw | **Fixed** for notes, offsets and cancellation proposals (`test_d10_…`, `test_r51_1_…`, the offset test). A full Approval Center is out of scope. |
| D11 legacy numbered drafts | **Fixed** by the migration with a dry-run report (run on production only after the Owner approves the report). |
| D12 prefix change | **Open (Krum: the counter is NOT reset).** This is the current behaviour. |
| D13 every client invoice from an act or contract stage | **Open (needs the contract-stage model).** |
| D14 out of scope | Act correction (t24), VAT ledger/export, e-invoice/SAF-T, partial release of retentions, full Approval Center. |
| D15 Overdue in P&L; Paid stays Paid | **Fixed** (`test_d15_…`). Overdue now counts as issued revenue. |
| D16 approver | **Closed.** The Owner approves (Р49.4, Р51). |
| SEC-01 (#69, now in main) | **Open.** `finance.py` routes, old and new, still use `finance_permission` (Owner/Admin/Accountant); #69 did not migrate `finance.py`. Moving the whole module to `require_money_write` plus catalog actions is one follow-up, so the module keeps a single rule. |

## Gates (`gates.txt`; after Addendum A and the merge of main 8c52e92; real Mongo = disposable local mongo:7.0, replica set rs0)

| Gate | Result |
|---|---|
| INV-CN-01 (30 scenarios × off/shadow/enforce) | **90 passed**, 0 skipped |
| The same file on main cd03324 / on 3893b9f | first version: 57/57 failed on main (`main_cd03324_red.txt`); Addendum A tests failed on 3893b9f (`addendum_a_red_on_3893b9f.txt`) |
| PAY-01 family + 5C-C26l invoice suites | 630 passed, 0 failed. The 299 skipped are the warehouse real-Mongo cases, which run only with `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`. They were not run here: the local Mongo hits its 20000 open-files cap. |
| R0 (real) | **814 passed** |
| W0 real / DB-free | the same **15** failures (all in `test_w0_03e_legacy_routes.py`), 1177 / 1094 passed |
| A2C / A1 guards | 239 modules / 482 units, **0 violations**; A1/A2B inventories regenerated by their scripts |
| PM-01 (real, `-rs`) | 6 passed, **0 skipped**. The matrix was regenerated by the harness: +4 routes / +96 cells (cancel approve/reject, note reject, offset reject), 0 existing cells changed. |
| Frontend `yarn test` | 17 suites, 173 passed |
| Trial merge with #82 @ 1622f62 (before Addendum A) | 161 passed, 0 skipped (`r47_coupling_pr82.txt`) |

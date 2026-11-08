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

## Debts: business decisions not in the package or the canon (nothing invented)

| # | Debt | What was done instead |
|---|---|---|
| D1 | No contract model on invoices, so "the same contract" for an offset is undefined. | The strictest scope available: same direction + same project + same counterparty ЕИК, all present. Anything else → 409. |
| D2 | No annex model. | A debit note to a client accepts only an approved act of the same project as its basis. |
| D3 | The threshold for a "large" offset (FLOW-034 L72) is not decided by Krum. | **Every** offset needs the Owner's second approval. No amount was invented. |
| D4 | No VAT ledger and no period close in main. | Cancellation checks `vat_ledger_period`, which nothing sets yet. "A closed period is not touched" cannot be enforced; notes are dated by their own `issue_date`. |
| D5 | The File Registry (PR #44) is not in main. | `file_id` is stored but not validated. |
| D6 | Р49 covers outgoing invoices only. Cancelling or deleting **supplier** invoices is not decided. | Main's rule is kept (not Paid, no allocations), now with reason + key. A supplier draft that carries the supplier's number can still be deleted. |
| D7 | Incoming note with a difference: there is no decision or endpoint for resolving the DQ (accept the difference / reject the note). | The note stays registered and not applied. |
| D8 | The P&L **cost** side for incoming notes is not done: material cost path B (`canonical_material_cost`) does not yet reduce. | Only the revenue side is done. |
| D9 | Reversing a refund payment through PAY-01 `DELETE /finance/payments/{id}` does not recompute the invoice's derived sums until its next write. | A reversal path through the invoice is needed. |
| D10 | No reject/withdraw for pending notes and offsets, and no Approval Center (out of scope). | A pending row has no effect. |
| D11 | Legacy outgoing **drafts already numbered** before INV-CN-01: they keep their number at issue and cannot be deleted (409). How many exist in production is unknown (no production access). | A read-only report is needed before deploy. |
| D12 | A prefix change continues the one shared counter. | Whether the number resets with a new prefix is not decided. |
| D13 | FLOW-025 L124 (every client invoice from an approved act or contract stage) is enforced only when `act_id` is given. | There is no contract-stage model. |
| D14 | Act correction (t24), VAT ledger/export, e-invoice/SAF-T, partial release of retentions, full Approval Center. | Out of scope per the package. |
| D15 | Pre-existing, not changed here: `Overdue` invoices are not counted in project P&L revenue; a `Paid` invoice whose payments are all cancelled stays `Paid`. | — |
| D16 | Who may approve. | The approver is the **Owner** only (Р49.4 "Собственик одобрява"). Whether an Admin may also approve is not decided. |

## Gates (`gates.txt`; real Mongo = disposable local mongo:7.0, replica set rs0)

| Gate | Result |
|---|---|
| INV-CN-01 (`tests/test_inv_cn_01_credit_notes.py`, off/shadow/enforce) | **57 passed**, 0 skipped; 60 with the R47 coupling test added afterwards |
| The same file on main cd03324 | **57 failed** (`main_cd03324_red.txt`) |
| PAY-01 family + 5C-C26l invoice suites | 630 passed, 0 failed |
| R0 (real) | **814 passed** |
| W0 (real) | 15 failed (all in `test_w0_03e_legacy_routes.py`, the known baseline), 1177 passed |
| W0 (DB-free) | the same 15 failed, 1094 passed |
| A2C / A1 guards | 236 modules / 476 units, **0 violations** |
| PM-01 (real, `-rs`) | 6 passed, **0 skipped**. The matrix was regenerated **by the harness**: +10 routes (+240 cells), 0 existing cells changed. |
| Frontend `yarn test` | 17 suites, 170 passed |

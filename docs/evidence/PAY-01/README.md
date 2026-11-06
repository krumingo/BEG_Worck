# PAY-01: payments are reversed, never deleted

Package: `docs/architecture/tasks/PAY-01_PAYMENT_REVERSAL_NO_HARD_DELETE.md` (branch `claude/happy-meitner-bmcnel` @ b659a73). Krum approved it as decision R23 on 06.11.2026. Finding: FLOW Guard FG-34 @ main 07da9ab.

Canon: CLAUDE.md §2.9 and §7, FLOW-006 §Корекции, FLOW-043 D-03 (one Payment ledger) and D-08 (one AuditEvent).

## Source of truth

The source of truth is `finance_payments` (FLOW-006). No second ledger is created: the reversal row lives in the same collection. Allocations stay in `payment_allocations`.

## Data model (additive, no migration)

| Row | New fields |
|---|---|
| original payment | `status: "reversed"`, `reversed_by_payment_id`, `reversed_at`, `reversed_by`, `reversal_reason` |
| reversal row | `status: "reversal"`, `reverses_payment_id`, opposite `direction`, same `amount`, `account_id`, `currency`; `reversal_reason`, `created_by` |
| allocation | `status: "cancelled"`, `cancelled_at`, `cancelled_by`, `cancel_reason` |

- **Rows written before PAY-01** have no `status` field. They are active, so no backfill is needed.
- **Reversal row id:** it is deterministic, `uuid5("beg-payment-reversal:<payment id>")`, and is written with an upsert. One original can never have two reversal rows.
- **The rule itself** lives in `backend/app/services/payment_state.py`. It is pure logic with no DB access: `active_payments()`, `active_allocations()`, `payment_counts()`.

## Endpoints

| Endpoint | Before | After |
|---|---|---|
| `DELETE /finance/payments/{id}` | `delete_one` | A reason is required (body, `?reason=`) → 400 `REASON_REQUIRED`. A conditional write sets `status = reversed`, then the reversal row is added. A second reversal → 409. The reversal row itself → 409. The same `Idempotency-Key` → the first result. The same key on another request → 409. A payment with active allocations → 400 (unchanged rule). Both sides of an own-account transfer are reversed together. |
| `DELETE /finance/invoices/{inv}/payments/{alloc}` | `delete_one` on the allocation, and on the payment if no allocation was left | A reason is required. The allocation gets `status = cancelled` (repeat → 409). If the payment has no active allocation left, it is **reversed**. That is the same visible effect as before, now without a delete. The invoice's paid and remaining amounts are recomputed from active allocations. |
| `POST /finance/payments/{id}/allocate` | — | A reversed payment or a reversal row → 409. |
| `DELETE /finance/invoices/{id}` | Draft only (400) | Not a draft → **409**. A draft with any allocation, cancelled ones included → **409**. An unused draft can still be deleted. |
| `DELETE /finance/accounts/{id}` | 400 if it has payments | **409**. "Used" includes reversed payments. An unused account can still be deleted. |

## Canonical AuditEvent and idempotency

- **AuditEvent:** the events are `finance.payment.reversed` and `finance.allocation.cancelled`. They use the W0-04 `build_event` + `record_event`, with `source_flow` FLOW-006, retention R1, and the actor, reason, a structured diff and the idempotency key. Each event is written to the same database as the business write, and only after that write.
- **Legacy audit log:** the existing `audit_logs` entries (`log_audit`) are kept. Two parallel audit records are known debt W0-04, and this package does not fix it.
- **Idempotency:** W0-04 `begin_idempotent` / `complete_idempotent` / `fail_idempotent`, with action `finance.payment.reverse` or `finance.allocation.cancel`.
- **Crash between the two writes:** the original can be left `reversed` with no reversal row. The next request on that payment adds the row. The upsert means there is never a second one.

## Permissions

The rule is unchanged: Owner, Admin and Accountant only (`finance_permission`). It is checked before any read or write. Viewer, SiteManager and Technician get 403 with nothing written, tested in off, shadow and enforce.

**PR #69 (SEC-01)** does not touch `finance.py`; it touches only other routes, `permissions/money_write.py` and `catalog.py`. The two PRs therefore merge without a conflict in either order.

Moving these four endpoints to `require_money_write` is a follow-up, once #69 is merged:
- add `Depends(require_money_write("finance.payment.reverse", module="M5", resource_type="payment"))` (and similar for allocation cancel and the invoice and account delete), declared before `require_m5`;
- add the catalog actions for `accountant`;
- `finance_permission` then stays as a second check.

## Affected reports (each now reads only active rows)

1. `GET /finance/accounts`: the `current_balance` of each account (`finance.py` list_accounts).
2. `GET /finance/stats`: `cash_balance` and `bank_balance`, on the Finance dashboard and in the KPI cards.
3. `update_invoice_status`: invoice `paid_amount`, `remaining_amount` and `status`. These feed the receivables and payables in `/finance/stats`, the aging report, upcoming payments, and every invoice list.
4. `GET /finance/invoices/{id}`: `allocations`.
5. `GET /finance/invoices/{id}/payments`.
6. `POST /finance/invoices/{id}/cancel`: the active-allocation check.
7. `GET /finance/payments`: reversed pairs are hidden by default; `?include_reversed=true` shows them. The allocated and unallocated amounts come from active allocations.
8. `GET /finance/payments/{id}`: allocations.
9. `POST /finance/payments/{id}/allocate`: the available amount.
10. `app/services/project_pnl.py` `compute_project_pnl`: `other_cost` (documentless expenses). This also feeds the P&L trend and project financial results.
11. `app/routes/projects.py`: a project's invoices with their payment allocations.

**PR #55** (warehouse 5C, draft) changes `project_pnl.py` (materials) but not the `other_docs` query. This PR changes only that one query plus one import line, so a merge conflict, if any, is trivial.

On main, `projects.py` and `pay_runs.py` contain no other reader of `finance_payments`. The other modules only write to it: pay_runs (salary), hr (advances) and subcontractors.

## Tests

`backend/tests/test_pay_01_payment_reversal.py` runs 13 tests. All except the static check run on mongomock and on real Mongo (`mongo:7.0` replica set `rs0`), in all three modes: **91 cases**.

| Run | Result |
|---|---|
| This branch | 91 passed |
| main 07da9ab (same test file + `payment_state.py`) | **61 failed**, 30 passed |

The 30 cases that pass on main are the regression checks that already held there: 403 for non-finance roles, cross-tenant 404, and project P&L 0 (on main the payment was deleted).

The full DB-free baseline and both guards are in the HANDOFF message.

## Rollback

Revert the PR's commits. Data written meanwhile:
- **Reversed payments:** old code ignores `status`. A reversed pair then counts in both directions. That nets to 0 on each account balance, but gross inflow and outflow are inflated.
- **Cancelled allocations:** old code would count them as paid again.

So before a revert, list the PAY-01 rows: `finance_payments` with `status` in (reversed, reversal), and `payment_allocations` with `status = cancelled`. Krum decides what happens to them. Nothing is deleted automatically.

There is no schema change and no index.

## Known debt (recorded, not fixed)

- **PAY-01-D1:** the business write and the AuditEvent are not in one transaction (W0-04).
- **PAY-01-D2:** an invoice is treated as "used" only by allocations. Scan-doc links and procurement `source_invoice_id` are not checked.
- **PAY-01-D3:** there is no Approval step for a reversal yet. The canonical DQ/Approval runtime comes with W0-07.

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

Full DB-free suite (`PYTHONPATH=. pytest --noconftest -q -p no:cacheprovider`):

| Tree | Passed | Failed | Skipped |
|---|---|---|---|
| main 07da9ab | 1621 | 166 | 442 |
| this branch | 1667 | 166 | 487 |

- **Same environment for both:** this container, with `REACT_APP_BACKEND_URL` pointing at a closed local port.
- **Errors:** the 993 errors are live-API tests that need a running server. They are identical on both trees.
- **Failures:** the FAILED/ERROR set is **byte-identical** between main and the branch (`diff` is empty). The 15 failures in `test_w0_03e_legacy_routes.py` are among them.
- **What the branch adds:** +46 passed and +45 skipped, all from the new PAY-01 tests (their real-Mongo cases skip when no URL is set).
- **These are not the reference numbers:** they differ from the 1085 / 15 / 50 reference because this container collects more test files. The comparison that matters is main against branch on the same machine.

Two existing files had to change because the contract changed:
- `test_w0_03e_a1_collision_matrix.py`: the allocation DELETE now sends a reason. The isolation assertions are unchanged.
- `docs/architecture/W0-03E-A1_INVENTORY.md`: regenerated with `scripts/w0_03e_a1_inventory.py`. It went from 359 to 362 accesses, all SAFE or FIXED, none UNSCOPED.

Real Mongo (`mongo:7.0` replica set) results:

| Files | Result |
|---|---|
| PAY-01, A1 real, A2B gate, A2C two-tenant boundary, R0-06 | 157 passed |

Guards:

| Guard | Result |
|---|---|
| `w0_03e_a2c_tenant_boundary_guard.py` | 205 modules, 0 violations |
| `w0_03e_a1_tenant_access_guard.py` | 416 units, 0 violations |

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

## PAY-01-C01 Part 1: amounts and reasons

Package: `docs/architecture/tasks/PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md` (branch `claude/happy-meitner-bmcnel` @ 1f147de). Canon: CLAUDE.md §14 (validation/DQ), FLOW-006, R23. Part 2 (INT-70x69) waits for #69.

### PAY-N1: an amount is a finite number > 0, otherwise 422 and nothing is written

The rule lives in `backend/app/services/money_amount.py` (`positive_amount`). It is pure logic in its own module, so it does not conflict with SEC-01-C03 (#69), which applies the same rule to its own routes. The two are unified at merge.

| Endpoint | Before | After |
|---|---|---|
| `POST /finance/payments` | NaN/inf/1e309 stored, then 500; -1 and 0 stored | 422, nothing written |
| `POST /finance/invoices/{id}/payments` | NaN/inf stored, then 500 | 422 |
| `POST /finance/transfers`, `/account-funding`, `/other-expense`, `/other-income` | NaN/inf stored (`round(nan) <= 0` is false); ≤ 0 → 400 | 422 for every bad amount, ≤ 0 included |
| `POST /finance/payments/{id}/allocate` | NaN/inf allocated; ≤ 0 silently skipped | every item is checked **before the first write**: one bad item → 422, 0 rows |

- **Refused values:** NaN, ±Infinity, 1e309 (parsed as inf), -1, 0, null, and every non-number: `""`, any string (numeric text such as `"12.5"` too), `true`/`false`, lists and objects.
- **Only a JSON number is accepted (audit L1):** the check runs before any coercion. On the dict-based routes `positive_amount` does it. On the two Pydantic routes (`PaymentCreate.amount`, `AllocationInput.amount`), a `mode="before"` validator (`strict_number`) runs first, so `true` is no longer turned into 1.0. The frontend always sends numbers (`parseFloat`), so the UI is not affected.
- **Rounding:** the routes that rounded to 2 decimals still do (a value that rounds to 0 → 422).
- **Error format:** the 422 `detail` is a plain Bulgarian message, because the finance pages show `err.response.data.detail` as it is.
- **Order of checks:** permission is checked first, so a non-finance role still gets 403.

### PAY-N2: reversal / cancellation reason

`check_reason` is called from `_Request`, so it covers both `DELETE /finance/payments/{id}` and `DELETE /finance/invoices/{id}/payments/{alloc}`, with the reason in the body or in `?reason=`. A reason longer than 500 characters gets 400 `REASON_TOO_LONG`. A reason containing any character of Unicode category **Cc** (NUL, ESC, DEL, C1), **Cf** (soft hyphen U+00AD, zero-width, bidi embeddings, overrides and isolates, word joiner, BOM, ALM, tag characters U+E0000–U+E007F), **Zl** (U+2028), **Zp** (U+2029) or **Cs** (lone surrogates) gets 400 `REASON_INVALID_CHARS`. Cf, Zl and Zp were added after audit L2. The check runs before the idempotency key is taken, so nothing is written: no row, no audit entry, no key. A reason of exactly 500 characters is accepted. The UI already shows `detail.message`.

### Tests

`backend/tests/test_pay_01_c01_amounts_reason.py` runs on mongomock and on real Mongo (`mongo:7.0`, `rs0`), in off, shadow and enforce: **153 cases**, after the L1/L2 fixes.

| Run | Result |
|---|---|
| PAY-01-C01 + PAY-01 on this branch | 244 passed (153 + 91) |
| PAY-01-C01 on a0dec8b (`finance.py` from before) | first version: **114 of 128 failed** |
| PAY-01-C01 on 61d45d3 (before the L1/L2 fixes) | **69 failed**, 84 passed: `true` / `"12.5"` accepted, Cf/Zl/Zp reasons accepted |
| R0 (`tests/test_r0_*.py`, real Mongo) | 814 passed |
| W0 (`tests/test_w0_*.py`, real Mongo) | 1135 passed, 15 failed, all 15 in `test_w0_03e_legacy_routes.py` (the known baseline) |
| `w0_03e_a2c_tenant_boundary_guard.py` | 206 modules, 0 violations |
| `w0_03e_a1_tenant_access_guard.py` | 418 units, 0 violations |
| A1 inventory regenerated | table byte-identical to `W0-03E-A1_INVENTORY.md` |
| frontend `yarn test` | 5 suites, 92 passed |

### Rollback

Revert the commit. There is no data, schema or index change, and the rows written meanwhile are all valid amounts.

## PAY-01-C01 Addendum A: payments owned by another module (FLOW Guard FG-45)

Package addendum: `PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md` §Допълнение A (branch `claude/happy-meitner-bmcnel` @ 9336d69).

A `finance_payments` row written by another module must be reversed in that module. Otherwise the module's own register (pay run, advance, subcontractor package) and the Payment ledger diverge (FLOW-006). Until each module has its own reversal, Finance refuses: **409 `SOURCE_MODULE_REVERSAL_REQUIRED`**, with `source_module` in the detail and nothing written (no row, no AuditEvent, no idempotency key). For subcontractors, Part 2 (after #69) replaces this 409 with a real reversal in the module.

### How the origin is detected

The rule is `source_module()` in `backend/app/services/payment_state.py`. It is pure logic and reads the fields those modules write. On this branch they are the only writers of `finance_payments` outside `finance.py`:

| Module (writer) | Field read | `source_module` |
|---|---|---|
| `subcontractors.py` create payment | `subcontractor_payment_id` | `subcontractor` |
| `pay_runs.py` `_write_salary_outflows` | `category == "Заплата"` (`reference` = run id) | `pay_run` |
| `hr.py` create advance / loan | `category` in `"Аванс"`, `"Заем"` | `hr_advance` |
| `hr.py` loan repayment | `category == "Връщане заем"` | `hr_advance` |
| (future link by id) | `pay_run_id` / `advance_id` | `pay_run` / `hr_advance` |

Finance-owned rows stay reversible. These are manual payments, invoice quick-pay, transfers, account funding, other expense (`Други`) and other income (`Други приход`). A static test (`test_markers_written_by_source_modules`) fails if a module stops writing the field the rule reads.

### Where it is enforced

- **`DELETE /finance/payments/{id}`:** the check runs right after the reason check and before the idempotency key is taken.
- **`DELETE /finance/invoices/{inv}/payments/{alloc}`:** the 409 applies only when this is the payment's **last** active allocation, because only then would the payment be reversed. Cancelling one of several allocations is still allowed.

### Tests

`backend/tests/test_pay_01_c01_source_module.py`: **62 cases**, on mongomock and real Mongo, in off, shadow and enforce.

- **Payment reversal:** pay run, advance, loan, loan repayment and subcontractor → 409, with and without a key, 0 rows written.
- **Allocation cancel:** cancelling the last allocation of such a payment → 409. A non-last allocation can still be cancelled.
- **Control case:** a manual payment is still reversed.
- **Pure rule and static markers:** `source_module()` is tested on its own, and `test_markers_written_by_source_modules` checks the module markers.

| Run | Result |
|---|---|
| Addendum A + PAY-01-C01 + PAY-01 on this branch | 306 passed (62 + 153 + 91) |
| Addendum A tests on 8910939 | **55 failed**, 7 passed (the pure rule, markers and manual-payment control tests are expected to pass) |

**A1 inventory:** regenerated. The `remove_invoice_payment` `finance_payments` read moved one row, with the same content and FIXED status. Totals are unchanged: 362 accesses.

**Rollback:** revert the commit. Nothing is written by this change.

## PAY-01-C01 Addendum B: Idempotency-Key required on money writes (decision R29)

Package addendum: `PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md` §Допълнение B (branch `claude/happy-meitner-bmcnel` @ 48af2ea). Р29 was decided by Krum on 06.11.2026 (`RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`).

### Backend (`finance.py`)

| Write | Action (W0-04 registry) | Before | After |
|---|---|---|---|
| `POST /finance/payments` | `finance.payment.create` | no key support | key **required** |
| `POST /finance/invoices/{id}/payments` (quick-pay) | `finance.invoice_payment.create` | none | required |
| `POST /finance/transfers` | `finance.transfer.create` | none | required |
| `POST /finance/account-funding` | `finance.account_funding.create` | none | required |
| `POST /finance/other-expense` | `finance.other_expense.create` | none | required |
| `POST /finance/other-income` | `finance.other_income.create` | none | required |
| `POST /finance/payments/{id}/allocate` | `finance.payment.allocate` | none | required |
| `DELETE /finance/payments/{id}` (reversal) | `finance.payment.reverse` | optional | required |
| `DELETE /finance/invoices/{inv}/payments/{alloc}` (cancel) | `finance.allocation.cancel` | optional | required |

**Rules**
- **No key** (header missing, empty or blank) → **428 `IDEMPOTENCY_KEY_REQUIRED`**. The status code is the one SEC-01-C03 (#69) names. Nothing is read or written.
- **Order of checks:** permission (403), then key (428), then amount (422), then key reservation, then the write.
- **Wrapper:** the seven POSTs run through `_once()`. It reserves the key with `begin_idempotent`, runs the write, then stores the JSON result with `complete_idempotent`.

**Outcomes for a key**

| Case | Response |
|---|---|
| Same key, same request | The stored result, byte-identical; nothing is written again. |
| Same key, different request | 409 `IDEMPOTENCY_KEY_REUSED`, nothing written. |
| Same key while the first attempt has not finished | 409 `IDEMPOTENCY_IN_PROGRESS`. |
| A refusal inside the write (400/404/409) | The key is marked **failed** (W0-04). A retry with the same key and the same request runs again; it is never a replayed success. |

Keys are per tenant (`tenant_id` is part of the record id).

### Frontend

- **Helper:** `src/lib/idempotency.js` provides a key holder (`createKeyHolder`). It keeps one key per form submission: a double click, or a retry after a network error with no response, reuses the key. Once the server has answered, the next submission gets a fresh key. It also provides `apiErrorText`, which shows the `message` of an object detail instead of `[object Object]`.
- **Call sites:** all 11 calls to these endpoints send the key. The batch pay derives `batchKey:invoiceId`, so a retried batch replays the invoices already paid.

| Page | Calls |
|---|---|
| `PaymentsPage` | payment, allocate, other expense, other income, reversal (already sent a key) |
| `FinancialAccountsPage` | transfer, funding |
| `InvoiceEditorPage` | quick-pay, allocation cancel (already sent a key) |
| `InvoicesPage` | quick-pay, batch pay |

### Tests

`backend/tests/test_pay_01_c01_idempotency.py`: **120 cases**, on mongomock and real Mongo, in off, shadow and enforce.

**What the cases check**
- **No key → 428:** each of the 7 POSTs is called without a key, with an empty key and with a blank key. Each gets 428 and writes 0 rows (no audit entry, no key record). Reversal and cancel without a key also → 428.
- **Same key → one write:** a repeated request returns the same status and body, and the row count goes up only once (payment 1, quick-pay 1+1, transfer 2, allocate 1 allocation).
- **Key conflicts:** the same key with another body → 409 REUSED; a key that is still in progress → 409 IN_PROGRESS.
- **Failed key:** a key that failed can be retried.
- **Per tenant:** keys of different tenants do not collide.
- **Permission first:** a non-finance role still gets 403 before the key check.

**Contract changes in existing tests**
- In `test_pay_01_payment_reversal.py`, `hdr()` now sends a fresh key by default; `key=False` sends none.
- `test_12` now compares only the business collections, and asserts the refused allocate is recorded as a **failed** key.
- `test_w0_03e_a1_collision_matrix.py` sends keys on its quick-pay and cancel calls.

`frontend/src/lib/__tests__/idempotency.test.js`: 6 tests.

| Run | Result |
|---|---|
| All PAY-01* tests + A1 collision matrix | 431 passed |
| R29 file on 45768f3 | **108 failed**, 12 passed (the per-tenant and 403 cases, which already held) |
| frontend `yarn test` | 6 suites, 98 passed |

The A1 inventory was regenerated and is identical. The A1 and A2C guards report 0 violations.

### Known debt (recorded, not fixed)

- **PAY-01-C01-D4: a crash leaves the key stuck.** If the process dies after the business write and before `complete_idempotent`, the key stays `started`. Retries then get 409 IN_PROGRESS rather than a replay. Recovery needs a deterministic row id per key, or a check of the steps already done.
- **PAY-01-C01-D5: allocate was not atomic. FIXED, see §D5 below.** The coordinator ruled that CLAUDE.md §14 (idempotency plus a domain transaction for every money write) and FLOW-006 (a payment is never counted twice) already require the fix, so it needed no new decision.
- **PAY-01-C01-D6: live-API tests do not send the key.** `test_invoice_payments.py`, `test_invoice_workflow_p0.py` and `test_m5_finance.py` run against a deployed server and cannot run here. They do not send the key (nor the PAY-01 reason), so they need updating before they are run against this build.

## Audit fix C01A-1: concurrent cancels must not reverse a module-owned payment

**Finding (audit of 45768f3, MEDIUM-HIGH):** a "Заплата" payment has two allocations, and two requests cancel them concurrently. Before the fix both returned 200 and the payment ended up **reversed**. Two things allowed it:
- The FG-45 pre-check counted the other allocations **before** cancelling.
- The reversal that runs after the cancel had no source-module guard.

**Fix**
1. **Guard in the reversal path itself.** `_reverse_one()` refuses a module-owned payment, whoever calls it, with 409 `SOURCE_MODULE_REVERSAL_REQUIRED`, before any write. The origin fields are written once, at creation, so reading them cannot race.
2. **Atomic last-allocation decision.** For a module-owned payment, the allocation cancel runs under `_payment_lock()`, a short exclusive lock on the payment row.
   - It is taken with one conditional `update_one` that sets `allocation_lock {token, at}` only when no live lock is there.
   - A second request gets 409 `PAYMENT_BUSY` and writes nothing.
   - Under the lock, the route re-counts the other active allocations: none left → 409, nothing written; otherwise the cancel runs.
   - The lock is always released (`finally`, `$unset` by token). A lock older than 30 s, left by a crashed request, can be taken over.
   - Finance-owned payments do not take the lock; their behaviour is unchanged.

**Tests** (in `test_pay_01_c01_source_module.py`; mongomock + real Mongo, three modes: 18 cases)
- **The audit's probe:** 10 rounds of two concurrent cancels (`asyncio.gather`). At most one returns 200; the other gets 409 (SOURCE_MODULE_REVERSAL_REQUIRED or PAYMENT_BUSY). The payment is never reversed, it has no reversal row, it keeps at least one active allocation, and no lock is left on it.
  - On 670b5b9 (before the fix) this probe **fails on real Mongo** in all three modes, which reproduces the finding. Mongomock does not interleave the two requests, so it cannot show the race.
- **Direct call:** calling `_reverse_one()` on a subcontractor payment → 409, nothing written.
- **Stale lock:** a lock older than 30 s is taken over, and the cancel succeeds.

| Run | Result |
|---|---|
| All PAY-01* tests + A1 collision matrix | 449 passed |
| A1 / A2C guards | 418 units / 206 modules, 0 violations |

**A1 inventory:** regenerated. The cancel's writes moved into the helper `_cancel_allocation`, and the new `_payment_lock` and `_reverse_one` reads were added. Every new row is tenant-scoped (TenantData, SAFE). Totals: 367 accesses (FIXED 129, SAFE 238), up from 362. The one row that went from FIXED to SAFE only moved into the helper.

**Known debt PAY-01-C01-D7:** the lock is a field on the `finance_payments` row (`allocation_lock`). While a cancel runs, it is visible to readers for a few milliseconds. It is never left behind except by a crash, and a crashed lock becomes stale after 30 s.

## D5: allocate is atomic and cannot count a payment twice

**Before (8aac73d)**
- The items of `POST /finance/payments/{id}/allocate` were written one by one, each with a random id.
- If item 2 was refused (for example, more than the invoice's remaining amount), the allocation for item 1 stayed.
- The key was marked failed, and every retry with the same key wrote item 1 **again**.
- The same happened when a failure came after the first write.

**Now**
1. **Validate first.** Every item is checked before the first write:
   - the amount available on the payment, the invoice's existence, a cancelled invoice and the direction;
   - the invoice's remaining amount, counted together across items on the same invoice.

   A refused request leaves no allocation.
2. **Deterministic upsert.** Each allocation id is `uuid5(tenant, payment, idempotency key, item index)`, written with `update_one(..., $setOnInsert, upsert=True)`.
   - A retry of the same key after a failure finds the rows it already wrote and never adds a second.
   - Rows this key already wrote do not count against its own available or remaining amounts.
   - The invoice remaining amount is computed from the active allocations, the same rule as `update_invoice_status`.
   - Invoice statuses are recomputed once per invoice, after all the writes.

**Tests** (`test_pay_01_c01_idempotency.py`; mongomock + real Mongo, three modes: 18 cases)
- **Refused item:** a refused second item → 400 and 0 allocations, on three retries with the same key.
- **Failure after the writes:** the invoice recompute raises once and the key is marked failed. The retry → 200 with exactly one row per item, and the invoice paid and remaining amounts are correct. A replay changes nothing.
- **Two items on one invoice:** they are checked together; 60 + 60 > 100 → 400 with 0 rows.

| Run | Result |
|---|---|
| D5 tests on 8aac73d | **18 failed** (the duplicate and partial-write cases are reproduced) |
| All `test_pay_01*` + A1 collision matrix | 467 passed |
| A1 / A2C guards | 0 violations |

**A1 inventory:** regenerated. The allocate insert became a tenant-scoped upsert, and a per-invoice active-allocation read was added. Totals: 368 accesses (FIXED 130, SAFE 238).

## Addendum C: concurrent allocate cannot exceed a payment or an invoice (audit D5-R1/R2)

Package addendum: `PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md` §Допълнение C (branch `claude/happy-meitner-bmcnel` @ 4d5ab0b).

**Finding (HIGH, debt from main).** Concurrent allocates with **different** keys over-allocated, 5 times out of 5:
- 160 allocated on a payment of 100;
- 1600 allocated on an invoice of 1200.

Each request checked "available" and then wrote, with nothing between the two.

**Fix**
- **One lock helper.** `_row_lock(update, exists, …)` generalises the C01A-1 lock: one conditional `update_one` sets `allocation_lock {token, at}` on the row.
  - A concurrent holder → 409, nothing written. A missing row → 404.
  - A lock older than 30 s can be taken over, and the lock is always released by its token.
  - `_payment_lock` and `_invoice_lock` pass their own `tenant.finance_payments` / `tenant.invoices` calls, so every access stays tenant-scoped (A1 guard: 0 violations).
- **`POST /finance/payments/{id}/allocate`** locks the payment, then every distinct invoice in sorted order. All checks re-read under the locks and the writes happen there too: the payment's available amount from active allocations, and each invoice's remaining amount via `_invoice_remaining()`, computed from active allocations rather than the stored `remaining_amount`. A concurrent request gets 409 `PAYMENT_BUSY` or `INVOICE_BUSY`.
- **`POST /finance/invoices/{id}/payments` (quick-pay)** also checks an invoice's remaining amount, so it now runs under the invoice lock. Two concurrent quick-pays, or a quick-pay and an allocate, can no longer over-pay an invoice.
  - Same D5 rule: the payment and allocation ids are derived from the idempotency key and written as upserts, so a failed-key retry never creates a second payment.
  - The response's invoice is read after the unlock, so it never shows the lock field.
- **The cancel path (C01A-1)** uses the same `_payment_lock`. Allocate and cancel on one payment therefore serialise too.

**IDEM-IDX-1** (the unique index on `audit_idempotency` that is missing at startup) is fixed separately in W0-04-C01. It is not duplicated here. The PAY-01 test harness now creates the W0-04 indexes exactly as the bootstrap does, by reusing `scripts/w0_04_bootstrap_audit_indexes.PLANNED_INDEXES`, on mongomock and on real Mongo.

### Tests

These are in `test_pay_01_c01_idempotency.py`; mongomock + real Mongo, three modes: **24 cases**.

| Test | What it checks |
|---|---|
| R1 | 6 parallel allocates of 40 from one payment of 100, each to a different invoice → at most 100 allocated. |
| R2 | 6 parallel allocates of 400 from 6 payments to one invoice of 1200 → at most 1200 allocated; the invoice's paid and remaining amounts match the active allocations. |
| Concurrent quick-pays | 6 parallel quick-pays of 40 on an invoice of 100 → at most 100. |
| Quick-pay retry | A failure after the first write, then a retry with the same key → exactly one payment and one allocation. |

In every concurrent test, each refusal is 409 `PAYMENT_BUSY` or `INVOICE_BUSY`, or 400 for over the limit. Rows written = number of successes, so a refused request writes nothing, and no lock field is left behind.

| Run | Result |
|---|---|
| Concurrent tests on 42bbdfc | **fail on real Mongo** in all three modes; R1, R2 and the quick-pay over-payment are reproduced (mongomock does not interleave the requests) |
| Quick-pay retry on 42bbdfc | fails on both backends (duplicate payment) |
| All `test_pay_01*` + A1 collision matrix | 491 passed |
| A1 / A2C guards | 418 units / 206 modules, 0 violations |

**A1 inventory:** regenerated. The new rows are the lock, remaining-amount and quick-pay helpers, all TenantData-scoped. Totals: 371 accesses (FIXED 129, SAFE 242).

**Contract notes**
- The quick-pay 404 for a missing invoice now reads "Invoice <id> not found", the same text allocate uses.
- An over-limit allocate stays **400**, as before. Only a concurrent request refused by a lock is 409.

## Addendum D: a money write must name a project of its own tenant (FLOW Guard FG-50)

Package addendum: `PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md` §Допълнение D (branch `claude/happy-meitner-bmcnel` @ 4b91217).

Among the money POSTs in `finance.py`, **`/finance/other-expense`** and **`/finance/other-income`** are the only ones that take a `project_id`. Payment, quick-pay, transfer, funding and allocate take none. (`POST /finance/invoices` also takes a project, but it creates a document, not a money movement, so it is outside R29's list.)

- **The rule:** `_require_tenant_project()` reads `tenant.projects` (TenantData, this tenant only). If the project is missing, belongs to another tenant, or `project_id` is not a string → **422 `PROJECT_NOT_FOUND`**.
- **Order:** the check runs before the idempotency key is reserved, so nothing is written: no row, no AuditEvent, no key record.
- **Unchanged:** other expense without a project still returns 400 ("Изберете обект"). Other income without a project, `null` or `""`, is still allowed.
- **Test seed:** the PAY-01 harness now seeds the projects `prj-1` and `prj-a` (tenant A) and `prj-b` (tenant B).

**Tests** (`test_pay_01_c01_idempotency.py`; mongomock + real Mongo, three modes: 24 cases)
- **Refusals:** a missing project, tenant B's `prj-b`, a number, an operator object and a list → 422 and nothing written, on both routes. A project of this tenant → 201.
- **Unchanged behaviour:** other income without a project → 201; other expense without a project → 400.

| Run | Result |
|---|---|
| FG-50 tests on b5bfde2 | **12 failed** (the project checks); the 12 control cases already held |
| All `test_pay_01*` + A1 collision matrix | 515 passed |
| A1 / A2C guards | 0 violations |

**A1 inventory:** regenerated, adding one tenant-scoped project read. Totals: 372 accesses (FIXED 129, SAFE 243).

## PAY-01-C01-E: Codex review of 31ed258 (CHANGES_REQUESTED, PR comment 6704681914)

### F-70-01 [P1]: reversal and allocate were not serialised

**Finding.** The scenario is a payment of 100 and an invoice of 100.
1. `DELETE /finance/payments/{id}` checked "no active allocations" and was paused just before `_reverse_one`.
2. Meanwhile `allocate 80` completed (200).
3. The reversal then completed too (200).

The payment ended up **reversed while an allocation of 80 stayed active**, and the invoice showed `paid_amount = 80`. Only allocate took the payment lock, and a lock helps only if every writer takes it.

**Fix**
- **Reversal:** `DELETE /finance/payments/{id}` takes the **same payment lock** as allocate, cancel and the C01A-1 path. For an own-account transfer it locks **both legs, in sorted id order**.
  - The payment is **re-read under the locks**, so the allocation check and the reversal decide on committed state.
  - A concurrent request → 409 `PAYMENT_BUSY`, nothing written (the lock is taken before the idempotency key).
- **Allocation cancel:** it can reverse a payment when it cancels the last allocation. It now **always** takes the payment lock (before, only module-owned payments did), then the invoice lock, in the same order allocate uses.
- **Result:** reversal, cancel, allocate and quick-pay are serialised on the rows they read and change.

### F-70-02 [P1]: an interrupted reversal was recovered without its AuditEvent

**Finding.** `_ensure_reversal_row` failed after the original had been marked `reversed`. The retry with the same key returned **200** and repaired the reversal row (one row), but recorded **0** `finance.payment.reversed` events. `_repair_pair` restored only the row, and `_reverse_one` no longer found an active original, so it never reached its audit step.

**Fix**
- **`_audit_once()`** records a once-per-entity canonical event exactly once. A payment is reversed once and an allocation is cancelled once, so the **event identity is (tenant, action, entity id)**.
  - It checks `app.audit.store.has_event()`, a new read-only helper, and records only when the event is missing.
  - It always runs under the payment lock, so the check and the write cannot race.
- **Reversal:** `_repair_pair()` now restores the reversal row **and** its audit. Both the normal path and the recovery path go through `_reversal_audit()` → `_audit_once()`.
- **Allocation cancel:** it had the same gap. A retry whose first attempt had cancelled the allocation skipped the audit. Now the first run and the recovery both go through `_audit_once()`.

### Tests

`backend/tests/test_pay_01_c01_e_serialisation.py`: **66 cases**, on mongomock and real Mongo, in off, shadow and enforce. The interleavings are real HTTP requests; one request is paused at a precise point with an `asyncio.Event`. No financial logic is replaced.

**F-70-01 races**
- **Reversal paused before `_reverse_one`, then allocate** (the Codex probe) → allocate 409 `PAYMENT_BUSY`, reversal 200, no active allocation left on the reversed payment.
- **Allocate paused under its lock, then reversal** → reversal 409; allocate 200. A later reversal → 400 (the payment has allocations).
- **Cancel of the last allocation paused before it reverses the payment, then allocate to another invoice** → allocate 409; the cancel reverses the payment, with no active allocation left.
- **Transfer reversal paused** → both legs hold the lock, and reversing the other leg → 409. After the release, both legs are reversed: two reversal rows, no lock left.
- **Every case** checks the invariant: a reversed payment has no active allocation, and each invoice's `paid_amount` equals the sum of its active allocations.

**F-70-02 interruptions**
- **Reversal, one test per point:** before / after the reversal row, before / after the audit, before the key completes.
- **Retry with the same key:** 200, **exactly one** reversal row and **exactly one** `finance.payment.reversed` event. A replay of the completed key changes nothing.
- **Allocation cancel interrupted before / after its audit:** exactly one `finance.allocation.cancelled` event and one `finance.payment.reversed` event, plus one reversal row.

| Run | Result |
|---|---|
| Codex's own probes (from the review), unchanged, on real Mongo | **31ed258: 6 failed**, this head: **6 passed** |
| The new file on 31ed258 | **60 failed**, 6 passed (only the "before the key completes" interruption already recovered correctly) |
| All `test_pay_01*` + A1 collision matrix + `test_w0_04*` (the audit store changed) | 613 passed |
| A1 / A2C guards | 0 violations |

**A1 inventory:** regenerated, adding the tenant-scoped read of a transfer's legs. Totals: 373 accesses (FIXED 130, SAFE 243).

## #72 compatibility: `IDEMPOTENCY_IN_PROGRESS` is mapped to 409

W0-04-C01 (#72 @ 13dd8d7) adds a third answer of `begin_idempotent`: `in_progress`. It goes to a request that lost the compare-and-set retake of a **failed** key.

**Problem.** Both callers in `finance.py` treated any answer other than `duplicate` as a fresh start:
- `_once()`, used by the seven money POSTs;
- `_begin()`, used by the reversal and the allocation cancel.

After a merge with #72, they would therefore have run the write a second time.

**Fix (8cf0f4a).** Only an explicit `started` runs the write. Any other status → **409 `IDEMPOTENCY_IN_PROGRESS`**, nothing written. This works with and without #72.

| Run | Result |
|---|---|
| `test_72_in_progress_from_begin_idempotent_is_409`: transfer (via `_once`) and reversal (via `_begin`) on mongomock + real Mongo, three modes, 12 cases | 12 passed; **12 failed on cfb9d74** |
| **Trial merge** of this branch with `origin/claude/w0-04-c01-audit-indexes` @ 13dd8d7, done locally and not pushed | no conflicts |
| On the trial merge: all `test_pay_01*` + A1 collision matrix + `test_w0_04*` | 652 passed |
| On the trial merge: A1 / A2C guards | 432 units / 214 modules, 0 violations |

## PAY-01-C01-F: Codex F-70-03, an interrupted transfer reversal recovers both legs (review 6705298706 @ f71dce2)

Codex closed F-70-01 and F-70-02 and confirmed the STARTED guard.

**Finding F-70-03 [P1].** The scenario is a transfer of 50, `DELETE` of leg 1 with key K, interrupted on the **second** `_ensure_reversal_row`, after leg 2 was already marked `reversed`. The retry with K returned 200 and completed the key with **1 reversal row and 1 event**. If the interruption came on the second `_reversal_audit`, the retry left 2 rows but 1 event. The recovery repaired only the URL payment, and `active_payments(transfer_id)` no longer saw leg 2.

**Fix**
- **Which legs:** under the sorted leg locks, `delete_payment` takes **all original legs** of the transfer: active and already reversed, but not reversal rows. The URL leg comes first, then by id.
- **Per leg:** an active leg is reversed with `_reverse_one`. A leg that an interrupted attempt already marked reversed goes through `_repair_pair`, which restores its deterministic reversal row (upsert) and its canonical event (`_audit_once`), each exactly once.
- **The key:** it is completed only after every leg has its row and its event. The response always lists **both** legs with their deterministic reversal ids.
- **A different key on an interrupted transfer:** still 409 (already reversed), but it first completes the missing rows and events of both legs.

**Tests.** These are in `test_pay_01_c01_e_serialisation.py`; mongomock and real Mongo, three modes: **30 cases**.
- **Leg-2 interruptions:** one test per point, before or after the row and before or after the audit.
- **What the retry must leave:** 200, both legs reversed, **exactly one** reversal row and **one** `finance.payment.reversed` event per leg, a response with both legs, no lock left, and a replay that is identical and writes nothing.
- **A new key on an interrupted transfer:** 409, with both legs' rows and events completed.

| Run | Result |
|---|---|
| Codex's own transfer probes from 6705298706, unchanged, on real Mongo | **f71dce2: 6 failed**, this head: **6 passed** |
| The 30 new cases on f71dce2 | **30 failed** |
| All `test_pay_01*` + A1 collision matrix + `test_w0_04*` | 655 passed |
| A1 / A2C guards | 418 units / 206 modules, 0 violations |

**A1 inventory:** regenerated. The read of a transfer's legs now selects every original leg, and there is one per-leg re-read; both are tenant-scoped. Totals: 374 accesses (FIXED 131, SAFE 243).

## PAY-01-C01-G: a new key on a half-reversed transfer completes it (audit PAY70-04 @ 0713a81)

**Finding (blocker, 6/6).**
1. A transfer reversal is interrupted after leg 1 is fully done (row and event) but before leg 2 is marked.
2. A retry with a **new** key on leg 1 got 409 "already reversed" and left leg 2 **active**. The transfer stayed half-reversed and one account was off by 50.

The UI makes a fresh key on every click (`PaymentsPage.js:254`), so a user retrying after a 500 lands exactly here.

**Fix.** This is the "already reversed and not a retry of the same key" branch of `delete_payment`, which runs under the sorted leg locks.
- **Leg that still counts:** it is reversed first, with the original reversal reason and after the usual allocation check. If it has allocations → 409 `TRANSFER_LEG_ALLOCATED`.
- **Reversed legs:** every reversed leg gets its missing row and event (`_repair_pair`), each exactly once.
- **The answer:** it stays **409**, because a new key is not a second reversal. The detail now shows the repaired state: `{error_code: "PAYMENT_ALREADY_REVERSED", message, reversals: [{payment_id, status, reversal_payment_id}, …], completed_legs: [ids this request reversed]}`. The UI shows `detail.message`.
- **New key on the active leg (leg 2):** the normal path reverses it, repairs leg 1 and answers 200 with both legs.

**Tests.** These are in `test_pay_01_c01_e_serialisation.py`; mongomock + real Mongo, three modes: 12 cases.
- **New key on leg 1:** 409 `PAYMENT_ALREADY_REVERSED` with `completed_legs = [leg 2]` and both legs `reversed`. Each leg has 1 reversal row and 1 event, and both account balances are back to their opening amounts. A further new key → 409 with `completed_legs = []` and nothing written.
- **New key on leg 2:** 200 with both legs, and the same end state.

| Run | Result |
|---|---|
| Both tests on 0713a81 | the new key on leg 1 **fails 6/6** (leg 2 stays active); the new key on leg 2 already held there (control) |
| All `test_pay_01*` + A1 collision matrix + `test_w0_04*` | 667 passed |
| A1 / A2C guards | 0 violations; the A1 inventory is unchanged (374) |

## Merge of main 7b6da64 (#72 W0-04-C01): merge-ready check

**Merge.** `origin/main` 7b6da64 was merged into `claude/pay-01-payment-reversal` with merge commit `1ad9509`: no rebase, no force-push. There were **no conflicts**; `backend/app/audit/store.py` auto-merged, keeping main's linear audit chain and this branch's read-only `has_event`. After the merge, `scripts/w0_04_bootstrap_audit_indexes.PLANNED_INDEXES` **is** `app.audit.indexes.PLANNED_INDEXES`, the list that startup and onboarding use. So the PAY test harness creates exactly the indexes created at startup, with no change to the harness.

**PM-01 matrix: regenerated with the harness only** (`python tests/test_pm_01_permission_matrix.py --harness`, local replica set).
- **Why:** the first run against the committed matrix differed in 63 cells.
- **What changed:** all 63 are the expected R29 contract: 7 money POSTs × the 3 finance roles (owner, admin, accountant) × 3 modes. The probe sends no `Idempotency-Key`, so each cell is now **428, nothing written**. Before, the cells were 400/404, or 201 with a write for `POST /finance/payments`. The 7 POSTs are payment, quick-pay, transfer, account-funding, other-expense, other-income and allocate.
- **What stayed the same:** 0 rows were added or removed (18096), and no other route, role or mode changed.
- **Files:** only `matrix.csv` and `run_meta.json` (the run duration) changed.

**Results on the merge (real Mongo `mongo:7.0` rs0, `W0_03_REAL_MONGO_URL` set; `-rs`)**

| Suite | Result |
|---|---|
| PAY: all `test_pay_01*` + A1 collision matrix | 635 passed, 0 skipped |
| W0-04 / C01: `test_w0_04*` | 70 passed, 0 skipped |
| 6 parallel begins with one key: `test_six_parallel_begin_with_one_key_have_exactly_one_winner` (startup indexes via `ensure_audit_indexes`) + the no-index variant | 2 passed |
| PM-01: `test_pm_01_permission_matrix.py`, after the harness regeneration | 6 passed, **0 skipped** |
| R0 | 814 passed |
| W0: `test_w0_*` | 1173 passed, 15 failed, the same 15 in `test_w0_03e_legacy_routes.py` |
| A2C / A1 guards | 214 modules / 432 units, 0 violations |
| A1 inventory | identical (no regeneration needed) |
| frontend `yarn test` | 113 passed |

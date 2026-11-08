# WH-FIX-01 — evidence (post-#55 FLOW-009 residue)

Package: `docs/architecture/tasks/WH-FIX-01_POST_55_RESIDUE.md` (claude/happy-meitner-bmcnel @ 6db6f4b).
Branch `claude/wh-fix-01-post-55`, cut from main `cd03324`. No merge, no deploy, no production access.

Environment: local disposable `mongo:7.0` replica set `rs0` (docker), `W0_03_REAL_MONGO_URL` /
`MONGO_URL=mongodb://127.0.0.1:27017`, `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`.
Run from `backend/`: `PYTHONPATH=. pytest --noconftest -q -p no:cacheprovider …`.

## Files

| File | What |
|---|---|
| `01_red_on_main_cd03324.txt` | `tests/test_wh_fix_01_post_55.py` run on a clean worktree of main `cd03324` |
| `02_green_after_fix.txt` | the same file on the fix |
| `03_gates.txt` | warehouse suite, R0, W0, PAY-01, A2C/A1 guards, PM-01 — main vs fix |
| `04_a2_a3_red_on_main.txt` | `tests/test_wh_fix_01_a3_r44_allocation.py` on main `cd03324` (48 failed / 6 passed — the 6 are the "Issued invoices unaffected" control) |

## Red → green per item

The one test that passes on main is `test_fg161_owner_still_sees_every_value` — a positive
control (Owner keeps every value), green on both sides by design. Every other test is red on
main with a behavioural assertion (no setup errors):

| Item | Test(s) | Red on main |
|---|---|---|
| FG-193 | `test_fg193_*` (scanner on main's projects.py, 4 indirect patterns, real create-sub-project) | scanner sees nothing; ledger rows rewritten to child А |
| FG-192 | `test_fg192_*` | free-text item_id accepted; route not strict |
| FG-191 | `test_fg191_*` | client price 10 ≠ line 12.5 accepted; omitted price stored as 0; no DQ warning |
| FG-150 | `test_fg150_*` | card / aggregate = 0 instead of 100 |
| FG-154 | `test_fg154_*` | {p-1: 1200, p-2: 1200} instead of {480, 720} |
| FG-161 | `test_fg161_*` (5 roles + batches/stock/dashboard) | money on project rows / to Viewer |
| FG-157 | `test_fg157_*` | linked invoice edited; no AuditEvent; status set to "paid" |
| FG-159 | `test_fg159_*` (off / shadow / enforce + refusals) | no canonical movement; no rights / key / item checks |
| FG-163 | `test_fg163_*` | type change / deactivate with stock accepted |
| FG-190 | `test_fg190_*` | canonical issues/consumption invisible to the quantity reports |
| FG-164 | `test_fg164_*` | stock screen empty for canonical warehouses |

## Decisions taken inside the package / open for Крум (debt, not invented rules)

1. **FG-191 — price without an invoice line.** The package says "financial role + reason (or DQ)".
   Р32 lets the warehousekeeper enter the unit price at receipt, and `procurement` also holds the
   receive right (5C-C26 Addendum A left it unchanged). A role restriction or a mandatory reason
   would be a new business rule, so the **DQ path** was taken: the receipt is accepted and listed
   as `MANUAL_PRICE_WITHOUT_INVOICE_LINE` in the integrity warnings. **Open for Крум:** should
   procurement keep entering manual prices; is a reason mandatory?
2. **FG-191 — unknown invoice_line_id** on a warehouse receipt stays FG-53 debt (treated as "no line" → DQ).
3. **FG-193 — sub-project А and warehouse history.** The ledger stays on the parent (the canonical
   project of a subproject IS its parent, 5C-C26d). Child А's own screens do not show that history
   unless a reader follows `parent_project_id`. Legacy (pre-canon) rows in `warehouse_transactions`
   also stay on the parent now. **Open:** should child-А views read the parent's warehouse history?
4. **FG-157 — supplier-invoice correction path.** Edits past review (`uploaded`/`reviewed`) now
   return 409 `SUPPLIER_INVOICE_CORRECTION_ONLY`; no correction endpoint for supplier invoices
   exists yet (canon open → debt).
5. **FG-159 — UI.** `frontend/src/components/MaterialWastePanel.js` posts free text without
   `item_id` / `file_ids` / `Idempotency-Key`; it will now get 422/428. The UI must be moved to the
   Master item picker + evidence upload (separate UI task).
6. **FG-161 — legacy routes decide money by the session role** in every mode (the same rule
   tables as the canonical reads; Р28 parity). Enforce-mode RoleAssignments are used only by the
   canonical reads.
7. **FG-164 — legacy main-warehouse balance** is still listed (labelled `source: "legacy"`) beside
   the canonical stock. If the tenant's migration already opened canonical balances from it, the
   screen shows both — depends on migration state (debt; `warehouse_migration` readiness).
8. **FG-154 — invoices with a header-level allocation to several projects and no lines** cannot be
   split; they are listed in `unsplit_invoices` (DQ) and counted on no project.
9. **FG-192 test fixture.** The pre-WH-FIX-01 real-Mongo fixture (`canonical_mongo_db`) seeds no
   Master Data; it lowers the module default to non-strict for its own test only. Production code
   has no env flag; the route constructs the service with `strict_master_identity=True`.
   New fixture `strict_mongo_db` keeps the production default.

## Addenda A2 + A3 (08.11) — FG-155 per canon (oracle Q001) and Р44

`backend/app/services/invoice_allocation.py`, tests `tests/test_wh_fix_01_a3_r44_allocation.py`
(off / shadow / enforce × mongomock + real Mongo, 54 tests, 0 skipped):

* A line's allocation state is derived from `allocations[]` (source, no second truth): final
  `allocated` only at 100 %, otherwise the interim `pending_allocation` („чака разпределение").
  The final state always needs 100 % — `require_full_allocation` is effectively True for the final
  status and cannot be switched off; the tenant setting of the same name still only decides
  whether an interim partial allocation may be SAVED (unchanged).
* The remainder is in no project result (Path B and the FG-154 split count allocated qty only;
  test: line 100, 60 → P&L(P) = 600 = 60 × 10). Nothing is defaulted.
* **Р44**: quick-pay and payment-allocate to a supplier (Received) invoice with any line < 100 % →
  409 `INVOICE_NOT_FULLY_ALLOCATED`, nothing written (full and partial amounts tested). These are
  the only two writers of `payment_allocations` in the code base.
* `GET /api/invoice-lines/invoices-to-allocate` (Owner / Admin / Accountant; others 403) —
  „фактури за разпределяне" with drill-down to the lines; syncs ONE deduplicated DQ issue
  (`dq_issues`, „фактура без обект или разпределение", owner Accountant, deadline
  `allocation_dq_deadline_days` per tenant, default 3, then escalated to Owner, severity high) and
  ONE alarm (`alarm_events`, warning → critical on escalation). Full allocation RESOLVES both
  (never deleted).
* An allocation change (`POST /invoice-lines/{id}/allocate`, `PUT /invoice-lines/{id}` with
  allocations) writes a canonical AuditEvent `finance.invoice_line.allocation_corrected` in the
  same transaction.

Debt / still open (A2/A3 "ЧАКА решение на Крум" — not programmed):
* Approval for an allocation to overhead; where the pending item is shown (project vs company);
  a value tolerance for amount-only lines.
* The DQ issue / alarm are refreshed when the pending list is read (and resolve on the next read
  after allocation); a scheduler / canonical DQ runtime (Wave 0) should own them later.
* Company-level reports that sum whole Received invoice totals (e.g. `dashboard.py` income/expense
  views, `reports.py`, `revenue_expense.py` subcontract fallback by header `project_id`) were not
  re-cut to allocated shares — FG-155 #2 "not in the company result" needs a separate pass over
  those reports (listed, not changed here).
* An invoice with NO lines and NO header allocation has nothing to allocate; Р44 is literal ("a
  line not 100 % allocated") so it is not blocked — open for Крум. (With a header allocation it is
  pending, A4 #8.)
* Sending (finalizing) a Received invoice with pending lines is not blocked (only payment, Р44).

## Not in scope (package)

FG-153, FG-162 — untouched. FG-155 — done per Addenda A2/A3 above.

## Audit fixes (PR comment 6719287307) and Addendum A4 (Р45)

| Finding | Fix | Test |
|---|---|---|
| WHFIX81-01 FG-157 check-then-act | per-supplier-invoice lock document (`warehouse_ledger_counters`, `supplier_invoice_lock:<org>:<invoice>`) written in the PUT transaction AND in every linking receipt's movement transaction (by `invoice_id` or a line id of the invoice); the link decision is taken inside the PUT transaction | `test_whfix81_01_*` — the receipt commits between the pre-check and the write → 409, nothing written |
| WHFIX81-02 UI waste form | `MaterialWastePanel.js`: Master items with stock on the project (`/project-material-ledger`), photo uploaded first (`/media/upload` → `file_ids`), `Idempotency-Key`, errors in Bulgarian | `MaterialWastePanel.whfix01.test.js` (red on the old panel) + `test_whfix81_02_the_ui_payload_is_a_canonical_write_off` |
| WHFIX81-03 / A4 | the line is the allocation unit (Q002); header-only / percentage invoices → `to_allocate`; single header destination written on lines (AuditEvent, same tx); line percentages → exact amounts (cumulative rounding); migration script (dry-run, idempotent, per tenant) | `test_whfix81_03_*`, `test_a4_*` (3 modes × mongomock + real) |
| WHFIX81-04 | A1 inventory regenerated with `scripts/w0_03e_a1_inventory.py`; `03_gates.txt` added | `test_w0_03e_a1_static_guard`, `test_w0_03e_a2b_static_guard` |
| WHFIX81-05 | POST material-waste decides Р27 first (403 before any 422/428); PM-01 harness seeds a Master item and sends a valid body + key; matrix regenerated with `--harness` on real Mongo | `test_pm_01_permission_matrix.py` (real Mongo, 0 skipped) |
| non-blocking | FG-191 line price stored with 4 decimals | `test_fg191_line_price_is_stored_quantized` |

W0 expectations changed (A4 #13), each quoted in the test:
`test_w0_03e_a1_collision_matrix.py` (×3 modes), `test_w0_03e_a1_real_mongo.py` (×3, same body),
`test_w0_03e_r1_exports.py` (×3), `test_w0_03e_real_mongo.py` (×1) — the finance-by-project report
no longer counts the header-only invoices: `items == []`, `pr-only-b` is read from the bucket's
header destinations, and `inv-shared` (its line is fully allocated to warehouses, so the line wins
over its header `pr-x`) is final and on no project. Canon: FLOW-020 L54/L73 (the line is the
unit), FLOW-008 L142 (unallocated not in project P&L), FLOW-009 L84 („Остатъкът не изчезва").

Debt: a REVERSED receipt (WH-REV-01 / #82) should not lock a supplier invoice — the reversal field
is not on this base; whichever PR merges second carries that rule.

## Codex review @ 625ece1 (comment 6722712113) — F-81-01 / F-81-02

Red run: `08_f81_red_on_625ece1.txt` (`tests/test_wh_fix_01_f81_readers.py` on a clean worktree of
`625ece1`: 78 failed / 24 passed — the passes are the 100 % cases, where old and new agree, and
the Received by-project control). HTTP, off / shadow / enforce × mongomock + real Mongo.

| Finding | Fix | Test |
|---|---|---|
| F-81-01 supplier invoices in official aggregates | one per-line projection `invoice_allocation.received_line_allocations` (allocated qty / line qty × line amount; `invoice_lines` docs, else embedded lines; Received only). Readers moved to it: `/reports/finance-details/summary` (company, `project_id`, `warehouse_id` filters; the unallocated rest in the new `expenses_invoices_to_allocate` / `_count`, not in the result), `/reports/company-finance-series`, `/reports/company-finance-summary` + the export (weekly, ex VAT), `get_month_finance_totals` (compare, incl. VAT — its own basis kept), `/project-profit/{id}` subcontract fallback (the line share to the project, no header `project_id`) | `test_f81_01_*` 0 / 60 / 100 % → 0 / 600 / 1000 |
| F-81-02 Issued income changed by line allocation | `_finance_by_project_rows`: Issued invoices never enter the per-line share; the header allocation gets the whole total, exactly as main's pipeline | `test_f81_02_*` (line to the header project / to another project × `invoice_lines` / embedded) → 500 on the header project |

Decisions inside the finding (recorded, not new rules):
* **D-04 / project P&L:** `invoice_lines` documents allocated to a project are already in the
  material cost (Path B, FG-17). The subcontract fallback therefore reads only invoices whose lines
  are embedded, so a cost is not counted twice. On main, a header `project_id` and Path B could
  count the same invoice twice.
* **Company result:** an allocation to any destination counts: project, warehouse, overhead.
  At 100 % the figure equals main's.
* **Not changed (document volume, not a result):** these readers list or total whole invoices per
  counterparty, not a company or project result. Open for Крум if they should also be re-cut.
  * turnover / by-counterparty / top-counterparties;
  * the transactions list;
  * outstanding payables.
* **Pre-existing, not touched (debt):** these project readers query `invoices` by `project_id`
  with no `direction` filter, so a supplier invoice with a header project counts as revenue there.
  This is main's behaviour and outside R45.
  * `project_pnl`;
  * `project_financial_results`;
  * project dashboard card 5 / `count_invoices`.

Gates @ `c3257a6` (real Mongo rs0, `-rs`, baseline main `4bca18a`): R0 814 / 0 skipped · W0 the
same 15 (identical set) · PAY-01 630 · SEC-01 30/30 · PM-01 6 / 0 skipped · A2C 237/0 · A1 478/0 ·
warehouse 4 failed + 16 errors (identical to main) · WH-FIX-01 suites 287 passed (185 + 102 new).

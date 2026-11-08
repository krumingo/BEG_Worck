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
| `03_gates.txt` | warehouse suite, R0, W0, A2C/A1 guards, PM-01 — main vs fix |

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

## Not in scope (package)

FG-153, FG-155, FG-162 — untouched.

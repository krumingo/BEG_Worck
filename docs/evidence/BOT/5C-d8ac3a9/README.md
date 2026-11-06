# BOT 5C re-run — PR #55 @ `d8ac3a9983b9f933361d456ea8fcbb81711906e0`

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, `PERMISSION_SERVICE_MODE=enforce`, **no local workarounds**.
**Result: FAIL 63/81.** `bot_result.json` has every step with detail; screenshots `01…*.png` at 1280 and 390×844. Earlier run (639ca80): `../5C-C18-639ca80/`.

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/d8ac3a9 d8ac3a9983b9f933361d456ea8fcbb81711906e0
docs/evidence/BOT/5C-d8ac3a9/setup.sh /tmp/botwt/d8ac3a9
BOT_OUT=$PWD/docs/evidence/BOT/5C-d8ac3a9 BOT_SHA=d8ac3a9 NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-d8ac3a9/5C-C20.js
docs/evidence/BOT/runner/stop_stack.sh
```
**Start state = a real install** (step 0 asserts it): the tenant already has W0-04 `audit_events` (created by user creation), the legacy unique index `warehouse_batches(org_id,batch_number)` plus a legacy batch row; the canonical indexes come only from the application's own startup hook (no `indexes.py`, nothing cleared or dropped). Synthetic seeding that is NOT the product path: second firm via the seed path, registry bootstrap, authoritative company assignment for the two admins, two `md_item` rows, one execution package + planned material (direct insert, for the cost reports).

## Previous findings, re-checked
| Earlier | Now |
|---|---|
| F-1 first write fails with existing AuditEvents; indexes only from tests | **PASS** (1.1 receive 200 on a tenant with audit events; canonical indexes created at startup) |
| F-2 second inbound batch fails on the legacy batch index | **PASS** (1.1b) |
| F-3 integrity-warnings 500 / false all-clear | **PASS**: API 200, empty state shown; forced 500 and network failure both show the error state, not "no alarms" (1.7, 1.7b, 1.7c) |
| F-4 direct dispatch credits the project | **PASS**: direct dispatch to a project refused (4xx), project holds nothing before acceptance, the form has a fixed in-transit destination (1.3p, 1.3q, 1.3r) |
| F-5 identical consume resend → 409 | **PASS** (2.8: 200, `replay:true`, same movement, no extra row) |
| F-6 screens / SMR field | **PASS**: Accountant sees read tabs only (3.6, both widths); Warehousekeeper has a screen with write tab, actions receive/dispatch/accept, no consume, and receives through it (3.5, 3.9); consume form has a required SMR field and posts with it (2.5, 2.6) |

Scenario with no workaround: 10 → 3+4+3 (UI 1280) and 10 → 8+2 (UI 390) end with **0 unresolved discrepancies** (1.5, 2.4); consume 3 with SMR through the form; keeper 200/403/200, technician and viewer 403 on everything, accountant write 403; tenant B sees nothing of A and can write in its own database (4.1–4.4).

## New findings (fail)
**F-9 — Project P&L ignores canonical material cost.** After receive 10 @10, dispatch 5, accept 5, consume 3 the cost is **30** (rows `cost_recognized`, accept rows 0), and it is 30 in: `/material-entries`, `/material-cost/by-execution-package`, `/project-net-profit`, `/project-profit`. But `/projects/{id}/pnl`, `/pnl/summary` and `/pnl/breakdown` show `material_cost` **0** and `total_expense` **0** — in every stage, also after sync and recompute. `services/project_pnl.py` takes material cost from invoice lines and legacy `warehouse_transactions.lines` (`qty_issued`), not from `material_entries`/the ledger. So the project page (finance card, P&L dashboard; screen C.5 shows no 30) overstates profit by the consumed material; the financial page (project-net-profit) shows 30. Two profit numbers for one project.
**F-10 — Package reports need two manual API calls with no trigger.** The package reports (`/execution-packages/{id}/financial`, `financial-breakdown`, `net-financial`, and by-execution-package) show **0** until `POST /material-entries/sync/{project}` (mapping) and `POST /execution-packages/recompute-material/{project}` have been called; after both they show 30 (C.3d). Nothing in the frontend or backend calls them (grep). The project financial screen shows 30 in one block and 0 `material_actual` in the package block until someone calls the API by hand.
**F-11 — Project material ledger shows nothing for canonical stock.** `/project-material-ledger/{project}` returns `ledger: []` for projects that received, accepted and consumed canonical stock, so the project page has no material ledger section (2.10). (It rendered in the 639ca80 run only because other stock existed.)

## Not covered
Reservation, quarantine, write-off, return-to-supplier, SiteManager project-scope consume, the org-level P&L overview/aggregator. Numbers were asserted from JSON fields whose key names contain `material`+`cost/actual/total/net` (budget/planned excluded) plus `total_expense` for the summary; screens by text.

# BOT 5C — PR #55 @ `8025871c5e2d4afe79df86532c3b0cfd83cb19cc` (5C-C26f…C26j: Р32, Р34, Р35, F-16)

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, **no workarounds**, tenant with W0-04 `audit_events` + legacy batch index/row (step 0). `FILE_REGISTRY_ENABLED=1` for the write-off evidence (placeholder `file_ids`). Two runs of the same scenario (screenshots at 1280 and 390×844 + `bot_result.json` in each folder):

| Run | Folder | Result |
|---|---|---|
| `PERMISSION_SERVICE_MODE=enforce` | `enforce/` | **256/259 PASS; the 3 others are "no screen"; no failed step** |
| `PERMISSION_SERVICE_MODE=shadow` | `shadow/` | **253/257 PASS; the 4 others are "no screen"; no failed step**; no `PERMISSION_SHADOW_MISMATCH` in the log |

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/8025871 8025871c5e2d4afe79df86532c3b0cfd83cb19cc
for M in enforce shadow; do
  docs/evidence/BOT/runner/stop_stack.sh
  BOT_MODE=$M docs/evidence/BOT/5C-8025871/setup.sh /tmp/botwt/8025871
  BOT_MODE=$M BOT_OUT=$PWD/docs/evidence/BOT/5C-8025871/$M BOT_SHA=8025871 NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-8025871/5C-C28.js
done
```
Synthetic, not the product path: second firm, registry bootstrap, admin and project-manager assignments (`grant_admins.py`, `grant_role.py`), `md_item` rows, execution packages, the legacy issue row, one `invoice_lines` row.

## What is new — results (both modes unless noted)
**Р35 — tabs „Централен склад“ and „Цени“ (P.2–P.8).**
- SiteManager (member) and Technician (member) open the screen with both tabs (1280 and 390×844). „Централен склад“ shows the quantity AND the prices (value 24150, each layer with its unit price). Neither can move anything at the central warehouse: receive, dispatch from it and a warehouse transfer are all 403 and the stock stays 8000. The Technician has no write tab; the SiteManager's write tab lists **project actions only** (accept, consume, project transfers, quarantine entry) — no receive, dispatch or warehouse transfer.
- Scope: price history for a project the SiteManager is not in → 403; a Technician never added → 403 (UI: error state, no prices); Warehousekeeper and Viewer → 403; Accountant → 200.
**Price history (P.0, P.1, P.4).** An article bought 3 times from one supplier at 10, 12, 11 (accepted on the project) shows in „Цени“ with the flag „⚑ Различни цени от един и същ доставчик“ (code `SAME_SUPPLIER_DIFFERENT_PRICE`, supplier, prices 10/11/12), the best price „Най-добра цена: 10 (sup-A, date)“ and its 3 purchases. An article bought twice from two different suppliers (5 and 6) is listed without the flag, best 5; an article bought once is absent. Checked in the API and on the screens (SiteManager, Technician, 1280; SiteManager 390×844, no horizontal scroll).
**Р32 / Р34 — the keeper's money (R32.*, R34.*).** The Warehousekeeper's history shows **no money on any project row** (consume, фира, dispatch to project, accept) and **the unit price on warehouse receipt rows**; his central warehouse stock read and the „Централен склад“ tab show the value and the layer unit prices (1280 and 390×844); his receive response carries `unit_value`, his dispatch-to-project response none; his integrity warnings have no money; he has the price input on the receive form (Р32: he enters the price at receipt) and no „Цени“ tab; he cannot open the project financial page. The Accountant (control) still sees money on the project rows.
**F-16 (shadow reads)** from the previous run is fixed: Technician and Viewer now get 403 on the canonical reads in shadow (steps 3.2, 3.3 pass), as in enforce.

## Regression — all PASS in both modes
Labels in Bulgarian; Р27/Р30 write-off rights by role (Admin, Accountant, member SiteManager/Technician 2xx with one row; non-members, keeper, viewer 403 and nothing written; project manager in enforce); write-off from a warehouse; R28 shadow writes with identical numbers; R17/R18/R21/FG-17 (cost 0 in transit → 50 at accept, consume adds nothing, return 100 → 70 via transit + quarantine, accept into free refused, direct return/transfer refused, layers 7000@1 + 2000@2.5, 14500/12500/27000, stock 24150, P&L = net profit = 150, both screens); 10→3+4+3 (UI 1280) and 10→8+2 (UI 390) end with 0 unresolved; warehouse→warehouse 10 accepted 6+4; SMR consume; resend returns the original; integrity-warnings error state; roles; tenant isolation (API + UI); 390×844 without horizontal scroll.

## No screen (not counted as pass)
Write-off through the form (no evidence `file_ids` field); quarantine release (form sends source state `free` only); the Path B invoice line; project manager (Р30) in the shadow run (no legacy role). Profit by period, material summary, project profit and package financial reports have no frontend screen (API assertions).

## Not covered
Expired project membership dates, reservation, return-to-supplier, org-level P&L overview, pulse/centralized reports, the `off` mode, File Registry itself, price history from direct supplier-to-project deliveries and Path B invoice lines (only warehouse receipts accepted on the project were driven).

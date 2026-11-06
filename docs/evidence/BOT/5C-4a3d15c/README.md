# BOT 5C — PR #55 @ `4a3d15c62bf88cb03e676d7807a0a8c6f782f0f2` (5C-C25…C26e: Р20, Р27, Р28, Р30, labels)

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, **no workarounds**, tenant with W0-04 `audit_events` + legacy batch index/row (step 0). `FILE_REGISTRY_ENABLED=1` for the write-off evidence (placeholder `file_ids`).
Two runs of the same scenario, evidence in two folders (screenshots at 1280 and 390×844 + `bot_result.json` each):

| Run | Folder | Result |
|---|---|---|
| `PERMISSION_SERVICE_MODE=enforce` | `enforce/` | **236/240** — 3 no-screen, 1 failed step (R20.5, an observation) |
| `PERMISSION_SERVICE_MODE=shadow` (Р28) | `shadow/` | **231/238** — 4 no-screen, 3 failed steps (R20.5 and two shadow-mode read gates, see F-16) |

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/4a3d15c 4a3d15c62bf88cb03e676d7807a0a8c6f782f0f2
for M in enforce shadow; do
  docs/evidence/BOT/runner/stop_stack.sh
  BOT_MODE=$M docs/evidence/BOT/5C-4a3d15c/setup.sh /tmp/botwt/4a3d15c
  BOT_MODE=$M BOT_OUT=$PWD/docs/evidence/BOT/5C-4a3d15c/$M BOT_SHA=4a3d15c NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-4a3d15c/5C-C27.js
done
```
Synthetic, not the product path: second firm, registry bootstrap, admin assignments, the PM's company `project_manager` assignment (`grant_role.py`; there is no legacy role for it), `md_item` rows, execution packages, the legacy issue row, one `invoice_lines` row.

## New in this head — results
- **Labels (Bulgarian)** — PASS in both runs: the dispatch form's fixed destination reads „в път · очаква приемане“; the stock panel shows `в път:<id> (в път)`, `(карантина)`, `(свободна)` and no raw `in_transit` / `quarantine`.
- **R27 / R30 — write-off from a project, by role** (new `POST /warehouse/canonical/project-writeoff`; denied = 403 `R27_WRITE_OFF_NOT_ALLOWED`, nothing written; allowed = 201 and exactly one ledger row) — **all PASS in both runs**: Admin ✔, Accountant ✔, SiteManager member ✔ / non-member 403, Technician member ✔ / non-member 403 / never added 403, Warehousekeeper 403, Viewer 403; enforce only (no legacy role exists): project manager as team manager of the project ✔ (Р30), only a technician on another project 403, no membership 403. Write-off from a WAREHOUSE: Admin 200, Accountant 403, Warehousekeeper 403. The generic `/movements` route does not bypass Р27 (Warehousekeeper write_off from a project → 403).
- **R20 — no prices for a Warehousekeeper** — API PASS in both runs: balance, stock, history and integrity-warnings answer 200 with no money field and `values_hidden: true`; his own command response carries no `unit_value`/layer values; the Accountant (finance role) still sees values on stock and history (control). UI PASS (1280 and 390×844): stock panel, history and alarms show quantities only; he cannot open the project financial page.
  **R20.5 (observation, FAIL in both runs):** the Warehousekeeper's receive form still shows the „Единична стойност“ price **input**. No price is displayed anywhere; this may be intended (price entered at receipt) — reported, not judged.
- **R28 — canonical writes in shadow** — PASS: the whole write scenario (receive, dispatch, accept incl. partial 3+4+3 / 8+2, consume with SMR, return, project→project, transfers, write-off, all 4 cost scenarios, tenant B) runs in shadow with the same numbers as in enforce; legacy role decides (keeper 200/403, technician/viewer/accountant writes 403); the shadow log shows no `PERMISSION_SHADOW_MISMATCH` line.
- **R17 / R18 / R21 / FG-17 regression** — all PASS in both runs (cost 0 in transit → 50 at accept; consume adds nothing; return 100 → 70 via transit + quarantine; accept into free refused; direct return and direct project→project refused; 7000@1 + 2000@2.5 layers, consume 14500, фира 12500, total 27000, stock 24150; P&L = net profit = project profit = 150, both screens 150).

## F-16 — shadow mode: canonical READS have no role gate (failed steps 3.2, 3.3 of the shadow run)
With `PERMISSION_SERVICE_MODE=shadow` a **Technician and a Viewer get 200** on `GET /warehouse/canonical/balance`, `/stock`, `/history` (enforce: 403). Values are hidden (`values_hidden: true`), but quantities, movement history, locations and projects of the whole tenant are readable. Cause: in shadow the legacy check decides and the canonical read routes have no legacy role check; the shadow log records it as `NEW_ONLY_DENY action=warehouse.read_stock` (2×) and `NEW_ONLY_ALLOW` for the allowed roles. Writes are not affected (Р28: legacy_gate decides them in shadow, all denials PASS).

## No screen (not counted as pass)
Write-off through the form (no evidence `file_ids` field); quarantine release (form sends source state `free` only); the Path B invoice line; project manager (Р30) in the shadow run (no legacy role). Profit by period, material summary, project profit and package financial reports have no frontend screen (API assertions).

## Not covered
Expired project membership dates (team API not driven with dates), reservation, return-to-supplier, org-level P&L overview, pulse/centralized reports, the `off` mode, File Registry itself.

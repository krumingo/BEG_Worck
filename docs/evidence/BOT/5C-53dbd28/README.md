# BOT 5C re-run — PR #55 @ `53dbd282402770c0f5c3237d9e6a9cd91dbe1128` (5C-C23)

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, `PERMISSION_SERVICE_MODE=enforce`, **no workarounds**, on a tenant that already has W0-04 `audit_events` and a legacy batch index + row (step 0). Backend started with `FILE_REGISTRY_ENABLED=1` (write-off evidence; the `file_ids` value is a placeholder).
**Result: 101/103 PASS; the 2 others are "no screen" (not counted as pass). No failed step.** `bot_result.json` has every step with detail; screenshots `01…*.png` at 1280 and 390×844. Same scenario as `../5C-a427923/` (98/102), plus the two new checks below.

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/53dbd28 53dbd282402770c0f5c3237d9e6a9cd91dbe1128
docs/evidence/BOT/5C-53dbd28/setup.sh /tmp/botwt/53dbd28
BOT_OUT=$PWD/docs/evidence/BOT/5C-53dbd28 BOT_SHA=53dbd28 NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-53dbd28/5C-C24.js
docs/evidence/BOT/runner/stop_stack.sh
```

## The two fixes asked for
- **F-14 `/profit-by-period`** — PASS. Summed over periods: material **130**, waste **20**, total **150** (same meaning as every other report). Per period: 2026-01 material 100 / waste 0 (legacy), current month material 30 / waste 20 (`material_total` 50); `material_undated` and `waste_undated` 0 (step C.7b). All 12 reports × 3 stages (30 → 130 → 150) and the financial page + P&L dashboard + financial-results card (1280 all stages, 390×844 stage 3) pass.
- **F-15 „Материални отклонения“ card** — PASS. After the canonical write-off of 2 the Finance-tab card shows the tiles Материали 1 · Записи 1 · Отпадък кол. **2**, the split line „Ръчни записи: 0 · 0 / Отписвания от склада: **1 · 2**“, and one row with the badge „отписване от склада“, it-cost, 2 bag, date (step C.7). The API summary agrees (`writeoff_items 1`, `writeoff_qty 2`, `writeoff_value 20`).

## Everything else re-run, all PASS
Scenario with no workaround (10→3+4+3 UI 1280, 10→8+2 UI 390, SMR consume = one cost row, identical resend returns the original, integrity-warnings 200 and error state on forced failure, direct dispatch refused, fixed in-transit destination); warehouse→warehouse transfer 10 accepted 6+4 → 0 unresolved, direct transfer refused, over-acceptance refused, 390 form OK; roles (keeper has a screen, accountant read-only, technician/viewer 403), tenant isolation (API + UI, both widths); 390×844 no horizontal scroll; project Finance tab ledger shows the canonical trail.

## No screen (not counted as pass)
- Write-off through the form: it cannot attach the evidence `file_ids` the write-off requires (UI attempt recorded in the step); the write-off is posted by API.
- Profit by period, material summary, project profit and package financial / net-financial have no frontend screen; asserted through their API only.

## Not covered
Reservation, quarantine, return-to-supplier, SiteManager project-scope consume, org-level P&L overview, pulse/centralized reports, File Registry itself.

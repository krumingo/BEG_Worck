# BOT 5C final run — PR #55 @ `a427923983158879ef1dd3d008eb967217ccecf5` (5C-C19..C22)

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, `PERMISSION_SERVICE_MODE=enforce`, **no workarounds** (no cleared audit events, no dropped batch index; canonical indexes come from the app's startup hook).
**Result: FAIL 98/102** — 2 failures, 2 "no screen" (counted as not passed). `bot_result.json` has every step with detail; screenshots `01…*.png` at 1280 and 390×844. Previous runs: `../5C-C18-639ca80/`, `../5C-d8ac3a9/`.

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/a427923 a427923983158879ef1dd3d008eb967217ccecf5
docs/evidence/BOT/5C-a427923/setup.sh /tmp/botwt/a427923
BOT_OUT=$PWD/docs/evidence/BOT/5C-a427923 BOT_SHA=a427923 NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-a427923/5C-C23.js
docs/evidence/BOT/runner/stop_stack.sh
```
Start state as a real install (step 0): tenant has W0-04 `audit_events`, a legacy batch row and the legacy unique `warehouse_batches(org_id,batch_number)` index. Configuration: backend started with `FILE_REGISTRY_ENABLED=1` (the write-off requires evidence and fails closed without it; the bot passes a placeholder `file_ids` — the registry is not exercised). Synthetic, not the product path: second firm, registry bootstrap, admin assignments, `md_item` rows, one execution package + planned material, and the legacy issue row (legacy writers are retired).

## 1. Same project material cost everywhere (the 30 → 130 → 150 check)
Flow: receive 10 @10, dispatch 5, accept 5, consume 3 (all through the UI, SMR on the form). Then a legacy issue of 100 dated 2026-01-10 (before the tenant's first canonical movement), then a write-off 2 @10 from the project.

| Stage | Expected material / фира / total | Result |
|---|---|---|
| 1 canonical only | 30 / 0 / 30 | **all 12 reports PASS** + financial page, P&L dashboard and financial-results card (1280) |
| 2 + legacy 100 before cutover | 130 / 0 / 130 | **all PASS** (material entries list = canonical rows only, by design: 30) |
| 3 + write-off 2@10 | 130 / **20 фира** / 150 | **all PASS except profit-by-period**; screens PASS at 1280 and 390×844, no horizontal scroll; exactly one cost row for the write-off (20) |

Reports checked per stage: `/project-material-summary`, `/material-entries`, `/material-cost/by-execution-package`, package `/financial`, `/financial-breakdown`, `/net-financial`, `/project-net-profit` (financial page), `/project-profit`, `/projects/{id}/pnl`, `/pnl/summary` (card), `/pnl/breakdown`, `/profit-by-period`. Screens: financial page (Материали / Фира / Общ разход + the card), project page Finance tab (P&L dashboard breakdown + financial-results card).

**Failures**
- **F-14 `/profit-by-period`** (stage 3): summed over periods `material` = **150** while every other report keeps `material` = 130 (consumption + legacy) with `waste` 20 beside it. Its `waste` is 20 and `total_cost` 150, so the totals agree, but `material` includes the фира; a reader that adds `material` + `waste` gets 170. Same word, two meanings.
- **C.7 (observation)** Finance tab card „Материални отклонения“ (the manual waste register) shows `Записи 0 · Отпадък кол. 0` after the canonical write-off of 2; it is a separate register, not cost, but it disagrees with the project's write-off.

**No screen** (not counted as pass): the write-off through the form (it cannot attach the evidence `file_ids`; the UI attempt is recorded in the step), and profit by period, material summary, project profit and package financial/net-financial have no frontend screen (asserted through their API only).

## 2. Warehouse → warehouse transfer (Р11)
Receive 10 @12 (UI) → direct transfer (destination = the other warehouse) **refused** 4xx, nothing moved → UI form has a fixed in-transit destination plus a target-warehouse field → transfer 10 CEN→WH2 (UI) puts the stock in transit (CEN 0, WH2 0) → accept 6 then 4 at WH2 (UI): 1 open discrepancy after 6, **0 unresolved after 4**, WH2 holds 10 → a further acceptance is refused. Form usable at 390×844 without horizontal scroll. All PASS (T.1–T.7). The form has no way to attempt a direct transfer (by design), so the refusal is checked through the API.

## 3. Repeated checks — all PASS
- Scenario with no workaround: first write with audit events (200), second batch with the legacy index (200), direct dispatch refused, fixed in-transit dispatch destination, 10→3+4+3 (UI 1280) and 10→8+2 (UI 390) end with 0 unresolved, consume 3 through the form with SMR → exactly one cost row, identical resend returns the original, integrity-warnings 200 / error state on forced 500 and network failure.
- Roles: keeper 200/403/200 and has a screen (write tab, receive/dispatch/accept only, receives through it); technician and viewer 403 everywhere and do not get the write form; accountant write 403 and sees read tabs only (1280 and 390).
- Tenant isolation: B sees nothing of A (API + UI at both widths), B cannot accept A's dispatch, B writes in its own database, A still sees its stock.
- 390×844: no horizontal scroll on the canonical page, the SMR form, the transfer form and both finance screens; project page Finance tab shows the material ledger with the canonical trail (dispatched 20, consumed 4, remaining 16).

## Not covered
Reservation, quarantine, return-to-supplier, SiteManager project-scope consume, org-level P&L overview, pulse/centralized reports that call the same helper (not read), File Registry itself (placeholder evidence id).

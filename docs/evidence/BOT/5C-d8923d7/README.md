# BOT 5C re-run — PR #55 @ `d8923d77182cb14393775f3f2f57c0a22dbd746f` (5C-C24, C25 + Addendum A)

Branch `task5c/live-ops-01-canonical-stock-core`. Local, synthetic data, `PERMISSION_SERVICE_MODE=enforce`, **no workarounds**; tenant already has W0-04 `audit_events` and a legacy batch index + row (step 0). Backend started with `FILE_REGISTRY_ENABLED=1` (write-off evidence; `file_ids` are placeholders).
**Result: 214/217 PASS; the 3 others are "no screen" (not counted as pass). No failed step.** `bot_result.json` has every step with detail; screenshots `01…*.png` at 1280 and 390×844. Earlier runs: `../5C-53dbd28/` (101/103), `../5C-a427923/`, `../5C-d8ac3a9/`, `../5C-C18-639ca80/`.

## Exact commands
```bash
git fetch origin task5c/live-ops-01-canonical-stock-core
git worktree add -f /tmp/botwt/d8923d7 d8923d77182cb14393775f3f2f57c0a22dbd746f
docs/evidence/BOT/5C-d8923d7/setup.sh /tmp/botwt/d8923d7
BOT_OUT=$PWD/docs/evidence/BOT/5C-d8923d7 BOT_SHA=d8923d7 NODE_PATH=$(npm root -g) node docs/evidence/BOT/5C-d8923d7/5C-C26.js
docs/evidence/BOT/runner/stop_stack.sh
```
Synthetic, not the product path: second firm, registry bootstrap, admin assignments, `md_item` rows, execution packages + planned materials, the legacy issue row, one `invoice_lines` row (Path B). Report values are read from the report JSON; screens by labelled text (Материали / Фира / Общ разход).

## The new cases
**R17 — cost at ACCEPT, a return lowers it (A, B).** receive 10 @10, dispatch 5: project cost **0** (in transit) on every report; accept 5: **50** appears on all 6 project-level reports and on the financial page / P&L dashboard / financial-results card (1280); packages 0. Consume 3: project still **50** (consume adds nothing), packages show the 30 allocated; the consume row is an allocation (`total_value 0`, `movement_value 30`). + legacy 100 before cutover: 150 (package 130). + write-off 2@10: total stays **150**, material 130, **фира 20**, on all 10 reports and both screens (1280 and 390×844); the Finance-tab waste card shows „Отписвания от склада: 1 · 2“. Return: accept 10 @10 = 100 → return 3 stays 100 while in transit → after acceptance in quarantine **70** on every report.
**R18 — every move in transit, a return to quarantine (B).** Direct return refused (4xx); return through the UI goes `in_transit` (stock panel shows the in-transit row 3, warehouse holds neither free nor quarantine; project cost unchanged); accepting it into FREE is refused (`QUARANTINE_STATE_VIOLATION`); accepting into the warehouse QUARANTINE works (UI "Приемане в: карантина"); stock then = quarantine 3, project 7; quarantined stock cannot be reused (dispatch refused); after the release (API) it is free with value conserved (30) and reusable. Direct project→project move refused; UI project→project transfer 2 is in transit (B 70, C 0) and after acceptance at C: B 50, C 20. Warehouse→warehouse 10 accepted 6+4 → 0 unresolved (T.*, re-run).
**R21 — three batch prices (C).** receive 7000@1, 11000@2.5, 5000@3.33, dispatch 15000, accept 9000 → layers **7000@1 + 2000@2.5** (not pro-rata); the remainder keeps **6000@2.5** (value 15000); accept 6000 → 6000@2.5, 0 unresolved; cost **27000** on all reports; consume 10000 = **14500** (7000@1 + 3000@2.5); write-off 5000 = **12500** (5000@2.5; pro-rata would be 9800); material 14500 / фира 12500 / total 27000 on every report incl. package; warehouse keeps 3000@2.5 + 5000@3.33 = **24150**.
**FG-17 — P&L and net profit show the same number (D).** invoice line 100 (Path B) + accept 5 @10 (50) + consume 3 + write-off 2: `/pnl` total expense = `/project-net-profit` = `/project-profit` = **150**, фира 20 on all 10 reports; the financial page and the P&L dashboard both show Общ разход 150 (and the financial-results card -150).

## Re-run, all PASS
First write with existing AuditEvents; second batch with the legacy index; direct dispatch refused, fixed in-transit destination; 10→3+4+3 (UI 1280) and 10→8+2 (UI 390) end with 0 unresolved; consume with SMR through the form = one allocation row; identical resend returns the original; integrity-warnings 200 and error state on forced 500/network failure; roles (keeper has a screen, accountant read-only, technician/viewer 403); tenant isolation (API + UI, both widths); 390×844 no horizontal scroll; project Finance tab ledger shows the canonical trail.

## No screen (not counted as pass)
- Write-off through the form: no way to attach the evidence `file_ids` (UI attempt recorded); posted by API.
- Quarantine release: the form sends the source state `free` only, so a quarantine source cannot be entered; released by API.
- The Path B supplier invoice line cannot be created from the warehouse screen; seeded directly. Profit by period, material summary, project profit and package financial/net-financial have no frontend screen of their own (asserted through their API).

## Observation (not a failure)
The stock panel shows the in-transit state as the raw `in_transit` label (and `quarantine`), not „в път“; the form hints use „в транзит“.

## Not covered
Reservation, return-to-supplier, SiteManager project-scope consume, org-level P&L overview, pulse/centralized reports, File Registry itself, project→project partial acceptance and discrepancies.

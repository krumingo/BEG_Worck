# R0-06 — evidence: a paid Pay Run is not reopened and not paid twice (AUD-043)

Task package: `docs/architecture/tasks/R0-06_PAID_PAY_RUN_NO_REOPEN_NO_DOUBLE_PAY.md` (on `claude/happy-meitner-bmcnel`).
FLOW-028, FLOW-006, FLOW-033/034 (Approval — no runtime yet). Draft PR, not merged.

## Bot test (local copy, test data only)

| Part | How it ran |
|---|---|
| MongoDB | Docker `mongo:7.0` (server 7.0.45), published on `127.0.0.1:27018` only, single-node replica set, `wiredTigerFileHandleCloseIdleTime=5` |
| Backend | `uvicorn server:app` on `127.0.0.1:8001`; `DB_NAME=r006_bot`, `BEG_SYSTEM_DB=r006_bot_system`, `ENV=test`, `BILLING_PROVIDER=mock`, a random per-run `JWT_SECRET` |
| Frontend | `yarn build` with `REACT_APP_BACKEND_URL=http://127.0.0.1:8001`, served as a SPA on `127.0.0.1:3000` |
| Seed | `seed_pay_run.py` — the R0-05 seed (one firm, Owner → Pro via mock checkout, one Admin, three workers with pay profiles, 15 approved 8h reports for 05–09.10.2026) plus one cash account „Каса“ (`/finance/accounts`), all through the real API |
| Bot | `paid_pay_run_bot.js`, Playwright with the preinstalled Chromium (`/opt/pw-browsers/chromium`); `playwright install` was not run |

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Admin logs in through the UI → `/pay-runs` → 05.10–11.10 → „Зареди“ → all three → „Потвърди плащане“ | PASS — `POST /api/pay-runs` 200 (`PR-0001`), the UI-chained `POST …/mark-paid` 200; the history row shows „Платен“ | `01_payment_step_three_employees.png` |
| 2 | Open the paid run | PASS — status „Платен“; the UI has **no** „Отвори за редакция“ and no „Маркирай платен“ button for a paid run | `02_paid_run_detail_no_reopen_button.png` |
| 2 | No button → same session through the API: reopen the whole run, reopen one row, PATCH | PASS — all three **409** „Платен Pay Run не се отваря и не се променя — корекцията е reversal + Approval (W0-07/FLOW-033), още не е налична“ | `03_api_reopen_patch_refused_409.png` |
| 3 | Same session: a second `mark-paid`, then 5 parallel ones | PASS — **409** „Already paid“ every time; the run is unchanged (status, version, rows, history) | `04_api_mark_paid_again_refused_one_outflow_each.png` |
| 3 | `GET /api/finance/payments?direction=Outflow` | PASS — exactly **one** salary Outflow per employee for this run (500 / 500 / 400 = 1400); one `marked_paid` history entry | `api_paid_run.json` |

`bot_result.json` holds every assertion. The bot exits 0 only when all of them hold. Result: **PASS**.

## Contrast on main @ 078b8e7

`main_contrast.json` (`main_contrast.py`, the same seed and API calls against a backend running main):
create + mark-paid → **reopen of the paid run 200** → PATCH 200 → **mark-paid again 200** → every employee
has **two** salary Outflows (Ivan 500+500, Petar 500+500, Georgi 400+400) = **2800 €** for a 1400 € run.

`concurrency_probe.json` (`concurrency_probe.py`, 8 parallel `mark-paid` on one run, real MongoDB replica set):

| Code | Winners (200) | Outflows | Outflow total | Advance deductions |
|---|---|---|---|---|
| R0-06 head | **1** (7 × 409) | **2** | **750** | **1** |
| main, run 1 | 3 | 6 | 2250 | 3 |
| main, run 2 | 2 | 4 | 1500 | 2 |

Expected: 2 Outflows (450 + 300 = 750), the advance reduced once by 50.

Reproduce (after starting MongoDB, the backend and the static frontend as above):

```
python seed_pay_run.py http://127.0.0.1:8001 > seed.json
NODE_PATH=$(npm root -g) node paid_pay_run_bot.js http://127.0.0.1:3000 http://127.0.0.1:8001 seed.json .
# contrast: same seed against a backend running main @ 078b8e7
python main_contrast.py http://127.0.0.1:8001 seed.json
# concurrency probe, from backend/
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?directConnection=true' PYTHONPATH=. python ../docs/evidence/R0-06/concurrency_probe.py
```

## R0-06-C01 — Codex F-01 / F-02

### Interleavings (F-01) and an early failure (F-02) — `interleaving_probe.py` → `interleaving_probe.json`

Real MongoDB replica set, fault-controlled: the first operation is parked inside its downstream sync,
mark-paid is called, then the first operation resumes.

| Scenario | 5eb0369 (R0-06) | C01 head |
|---|---|---|
| reopen parked in `sync_on_reopen`, then mark-paid | both 200 → run **paid**, allocations **reversed**, 2 Outflows | mark-paid **409**; run `reopened`, no Outflow |
| PATCH draft→confirmed parked in `sync_on_confirm`, then mark-paid | both 200 → run **paid**, allocations **provisional** | mark-paid **409**; run `confirmed`, allocations `provisional`, no Outflow |
| first payment effect fails | run **`paid`** (+`paid_effects=failed`), counted as a paid run | run **`payment_failed`**, not counted as paid |

(On 5eb0369 the early failure is injected into `_apply_paid_effects`, which does not exist as separate steps there.)

### Bot test — unfinished payment shown as NOT completed (`payment_failed_bot.js`)

The backend runs through `fault_server.py`: the real app with one injected failure in the **last**
payment effect (`_mark_slips_paid`), so the salary Outflows are already written when the payment breaks.
Test-only launcher; product code is not changed.

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Admin creates the run in the UI, „Потвърди плащане“ | create 200; the chained mark-paid fails (the 500 carries no CORS headers, so the browser reports `net::ERR_FAILED`); toast „Грешка“ | `05_payment_failed_error_toast.png` |
| 2 | Reload → „История“ | PASS — the row shows **„НЕзавършено плащане“** (red), not „Платен“ | `06_history_payment_failed.png` |
| 2 | Open the run | PASS — badge „НЕзавършено плащане“, warning „Плащането НЕ е завършено — нужна е проверка. Повторно плащане е блокирано.“, rows „Незавършено“, no pay / reopen button | `07_detail_payment_not_completed_warning.png` |
| 3 | Same session, API | PASS — list/detail `payment_failed`, `paid_effects=failed`, lock kept (token not exposed); `?status=paid` empty; audit-check **critical** `payment_incomplete`; a second mark-paid / reopen / PATCH → **409**; Outflows 3 before and 3 after (no second payment) | `08_api_payment_failed_not_paid.png`, `api_payment_failed.json`, `bot_result_payment_failed.json` |

Result: **PASS**. The happy-path bot above (`01`–`04`, `bot_result.json`) was re-run on the C01 head: **PASS**.

```
# from backend/: the fault-injecting launcher instead of server:app
PYTHONPATH=. python -m uvicorn --app-dir ../docs/evidence/R0-06 fault_server:app --host 127.0.0.1 --port 8001
python seed_pay_run.py http://127.0.0.1:8001 > seed.json
NODE_PATH=$(npm root -g) node payment_failed_bot.js http://127.0.0.1:3000 http://127.0.0.1:8001 seed.json .
```

## R0-06-C02 — Codex F-02a: a slip is paid only when its Pay Run is paid

`slip_readers_probe.py` → `slip_readers_probe.json`: the payment breaks AFTER the slip update committed
(slips really written `paid`), real MongoDB replica set.

| Reader | f9fe490 (C01) | C02 head |
|---|---|---|
| run status | `payment_failed` | `payment_failed` |
| raw `payment_slips.status` | paid, paid | paid, paid (unchanged — recorded value kept) |
| HR `legacy_payslips` / `legacy_payslip_one` | **Paid**, Paid | Generated, Generated (+ `payment_incomplete`) |
| `GET /payment-slips`, `/payment-slips/{id}` | **paid** | confirmed (+ `payment_incomplete`, `recorded_status=paid`) |
| `GET /payment-slips?status=paid` | **2** | 0 |
| `GET /payroll-weeks` slip status | **paid** | confirmed |
| `GET /my-pay-summary` owed (Ivan) | **0** | 450 |
| cashflow payroll estimate | **dropped** | 950 |
| paid labor (`paid_labor_v3`, `_paid_alloc_rows`) | 0 / 0 (C01) | 0 / 0 |

No bot test for C02: no UI file changed. The UI reads these APIs, which now return the effective
status; the C01 bot already shows the run as „НЕзавършено плащане“.

The password in the seed and bot scripts is a throwaway value for a disposable local database. It is not a credential.
After the runs the local MongoDB held only `admin,config,local`.

# R0-05 — evidence: Pay Run processes only the selected employees (AUD-023)

Task package: `docs/architecture/tasks/R0-05_PAY_RUN_SELECTED_ONLY.md` (on `claude/happy-meitner-bmcnel`).
FLOW-028, FLOW-006, FLOW-013. Draft PR, not merged.

## Bot test (local copy, test data only)

| Part | How it ran |
|---|---|
| MongoDB | Docker `mongo:7.0` (server 7.0.45), published on `127.0.0.1:27018` only, single-node replica set |
| Backend | `uvicorn server:app` on `127.0.0.1:8001`; `DB_NAME=r005_bot`, `BEG_SYSTEM_DB=r005_bot_system`, `ENV=test`, `BILLING_PROVIDER=mock`, a random per-run `JWT_SECRET` |
| Frontend | `yarn build` with `REACT_APP_BACKEND_URL=http://127.0.0.1:8001`, served as a SPA on `127.0.0.1:3000` |
| Seed | `seed_pay_run.py`, through the real API only (see below) |
| Bot | `pay_run_bot.js`, Playwright with the preinstalled Chromium (`/opt/pw-browsers/chromium`); `playwright install` was not run |

Seed, all through the API: `/billing/signup` creates one test firm (Owner). The signup plan has no payroll
module (M4), so the Owner upgrades to Pro through `/billing/create-checkout-session`, which the backend
answers with the mock provider only when `BILLING_PROVIDER=mock` and `ENV` is development/test. The Owner
then creates one Admin and three workers (`/users`), their pay profiles (`/employees`: Ivan Alpha Daily 100,
Petar Bravo Hourly 12.5, Georgi Charlie Daily 80), one project (`/projects`), 8h daily reports for
Mon 05.10 – Fri 09.10.2026 (`/daily-reports/batch-save`) and approves all 15 (`/daily-reports/{id}/approve`).

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Admin logs in through the UI → `/pay-runs` → period 05.10–11.10 → „Зареди“ | PASS — the preview grid lists all three (500 / 500 / 400 €) | `01_preview_three_employees.png` |
| 2 | Untick Petar and Georgi, „Напред →“, „Напред → Плащане“ | PASS — one employee ticked; the payment step shows only Ivan | `02_payment_step_one_employee.png` |
| 2 | „Потвърди плащане“ | PASS — the UI sends `rows=[Ivan, paid_now_amount=500]`, `POST /api/pay-runs` 200 (`PR-0001`); the run detail shows only Ivan; the slips tab shows one slip (`SL-00001`, Ivan) | `03_created_run_one_employee.png`, `04_slips_one_slip.png` |
| 3 | Same session: `GET /api/pay-runs/{id}`, `/api/payment-slips`, `/api/pay-runs/{id}/allocations` | PASS — exactly 1 row (Ivan), `totals.employees=1`, 1 slip in the tenant, allocations only for Ivan | `05_api_pay_run_one_row.png`, `api_pay_run.json` |

`bot_result.json` holds every assertion, the request rows the UI sent and the API record. The bot exits 0
only when all of them hold. Result: **PASS**.

Note: the UI's „Потвърди плащане“ chains `POST /pay-runs/{id}/mark-paid` right after the create (existing
behaviour, not touched by R0-05), so the run ends `paid`.

### Contrast on main

`main_contrast.json`: the same seed against main @ `41f2aff` and the same request (one row, Ivan, 500)
created a run with **three** rows — Petar 500 and Georgi 400 included as paid — `totals.paid = 1400`.

Reproduce (after starting MongoDB, the backend and the static frontend as above):

```
python seed_pay_run.py http://127.0.0.1:8001 > seed.json
NODE_PATH=$(npm root -g) node pay_run_bot.js http://127.0.0.1:3000 http://127.0.0.1:8001 seed.json .
```

The password in the seed and bot scripts is a throwaway value for a disposable local database. It is not a credential.

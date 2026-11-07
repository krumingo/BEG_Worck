# BOT LAB-02 — PR #75 @ `0c85678bdccb67b212d13de509bb4d2fd688d3c3` (branch `claude/lab-02-quantity-approval`)

Local, synthetic data, Permission Service mode `off` (the default), production frontend build, Playwright with the preinstalled Chromium, **everything at 390×844**. **Result: 23/29 PASS; 6 failed steps, all about the screen language/feedback (below). The whole money scenario passes.** `bot_result.json` has every step with detail; screenshots `*.png`.

## Exact commands
```bash
git fetch origin claude/lab-02-quantity-approval
git worktree add -f /tmp/botwt/0c85678 0c85678bdccb67b212d13de509bb4d2fd688d3c3
docs/evidence/BOT/LAB02-0c85678/setup.sh /tmp/botwt/0c85678
BOT_OUT=$PWD/docs/evidence/BOT/LAB02-0c85678 BOT_SHA=0c85678 NODE_PATH=$(npm root -g) node docs/evidence/BOT/LAB02-0c85678/LAB-02.js
docs/evidence/BOT/runner/stop_stack.sh
```
Seeding: users, project and team through the real API; synthetic direct inserts for what has no API here — all feature flags on, the worker's akord profile, the SMR package „Шпакловка“ (м2), a `Present` attendance and an SMR type. The worker's draft is created by the real `POST /technician/daily-report`.

## Scenario — result per step
| # | Step | Result |
|---|---|---|
| 1 | Finance (Accountant, 390) sets **Akord 5 EUR / м2** on „Шпакловка“ with a reason → „версия 1“; pay type, rate, version and AuditEvent stored; SiteManager and worker get 403 on the rates (R31) | **PASS** |
| 2 | The worker (Technician, 390) opens Обекти → Обект Витоша → his draft → „Изработено количество“ = **120** → Запази; the report holds quantity 120 | **PASS** |
| 3 | The SiteManager approves the report (API: the report approval list has no path in this bot) and then, on the phone, the quantity: sees „Въведено от работника: 120“, „Одобри количеството“ → „одобрено: 120 м2“, **no price shown to him**; finance sees 120 м2, rate 5 snapshot; the SiteManager's response carries no `piece_rate` | **PASS** |
| 4 | **Pay run shows 600**: API preview `earned_amount = 600`; the „Седмичен“ pay-run screen (390) shows 600 on the worker's row; the approval screen shows „120 м2 × 5 = 600“ | **PASS** |
| 5 | The worker tries to approve his own entry (1000 м2): **403**; the list and the classification are 403 too; the approval stays and the pay run still shows 600; opening `/labor-quantities` directly sends him to `/tech` | **PASS** |
| 6 | Editing the report afterwards (approver edits the quantity 120 → 100): **the approval is voided (kept as `void`)**, version bumped, the pay run no longer shows 600; the SiteManager screen shows the line waiting again („Въведено: 100“, „Одобри количеството“); approving the OLD version → **409** | **PASS** |
| 7 | The approver marks the line **DOWNTIME** with the reason „Дъжд — няма достъп до обекта“ → an active DOWNTIME classification with the reason; the pay run shows `downtime_amount > 0`, `labor_amount 0` and no 600; empty reason writes nothing | **PASS** (the on-screen refusal message, 7.1, **FAILS** — see F-2) |
| 8 | No hard delete: replaced approval kept, AuditEvents for terms / approval / correction / classification | **PASS** |

## Failed steps (screen language and feedback at 390 px)
- **F-1 — Latin text on Bulgarian screens.** The pay-run screen (4.3) shows the pay type as **„Akord“**. The subtitle of „Количества и акорд“ (1.3, 3.3, 7.4) ends with the reference **„(FLOW-028)“**, an internal canon code shown to users. No other Latin word on any of the 5 checked screens (the technician editor 2.2 is clean; the Latin allow-list is EUR, BEG, Work, VIT, Emergent, Made, with). **No horizontal scroll** on any of them.
- **F-2 — no message is ever shown (3.2b, 7.1).** The screens report every result with `toast()` from `sonner` („Количеството е одобрено“, „Напишете причина за престоя“, „Черновата е обновена“, every error such as the stale-version 409), but **no `<Toaster/>` is mounted anywhere in the frontend** (the same on `main`); the page holds 0 toast elements. The actions work and the lists refresh, but the user never sees a confirmation or an error — e.g. „Престой“ without a reason does nothing visible, and a refused approval (403 / 409) is silent.

## Not covered
The report approval screen for SiteManagers (AllReports bulk approve) was not driven — the report was approved by API; Permission Service modes `shadow` / `enforce` (the PR's own tests cover roles × 3 modes); the `en` language; a second SMR; the reopened / paid pay-run paths; the worker's own edit of a submitted report (R36 author limits, covered by the PR's tests).

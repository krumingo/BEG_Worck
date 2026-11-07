# LAB-01 — evidence

Package: `docs/architecture/tasks/LAB-01_LABOR_COST_PER_FLOW_019_028.md` (branch `claude/happy-meitner-bmcnel` @ 4b91217).
Canon: FLOW-019, FLOW-028, CLAUDE.md §7, FLOW-043 D-02, R31.

## One labor calculation
`backend/app/services/labor_cost.py`:
- `compute_person_labor(profile, lines, smr_terms)` — one person, one set of report lines;
- `project_labor_cost(org_id, project_id, date_from, date_to)` — one project, built from the per-person calculation.

Rules: only APPROVED lines; akord = `approved_quantity` × piece rate (line → execution package `labor_piece_rate`; never the profile hourly rate);
salary = the Pay Run time formulas over approved hours/days; missing rate / quantity / piece rate → 0 + DQ warning (no default 25 / 200 / 18);
`cost_type` DOWNTIME / DOWNTIME_UNCLASSIFIED → its own cost type. Pay type priority: line `pay_type` → execution package `labor_pay_type` → profile.
Per-line amounts of one person add up to the cent to that person's total.

## Consumers moved onto it
| Consumer | Before | After |
|---|---|---|
| Pay Run preview / create / PATCH (`routes/pay_runs.py`) | `calc_earned` on the profile; akord = hours × rate (FG-48) | `compute_person_labor` per line (FG-48, FG-49) |
| Labor sync (`POST /labor-entries/sync-from-work-reports`) | every work report, hours × rate (FG-51) | Approved work reports only, priced by the service |
| Expected vs actual — "изхарчено" by SMR (`services/expected_actual.py`) | work_sessions incl. unapproved, default wage | `project_labor_cost`; DOWNTIME its own block |
| Activity budget summary / burn (`routes/activity_budgets.py`) | daily_work_logs × default 25; offer labor counted as spent; work_sessions burn | `project_labor_cost` by SMR; offer labor is budget only |
| Project P&L labor line + monthly trend (`services/project_pnl.py`) | work_sessions | `project_labor_cost`; `downtime_cost` shown apart |
| All-reports listing `labor_value` (`routes/all_reports.py`) | hours × rate (× OT coef) for every status | the service amount for approved lines; non-approved = 0 |

## Tests (`tests-LAB-01.txt`)

## LAB-01-B (FLOW Guard pass 5: FG-64, FG-66) — `tests-LAB-01-B.txt`
- **FG-64:** nothing that prices a line is read from the worker-filled report line.
  - The line's `pay_type`, `piece_rate` and `approved_quantity` are ignored, and the normalizer no longer passes them through.
  - The piece rate and pay type come only from the SMR package (`execution_packages.labor_piece_rate` / `labor_pay_type`). The package must belong to the line's project. The approval record may name the package.
  - The approved quantity comes only from `labor_quantity_approvals`: status `approved`, an `approved_by`, and an approver who is not the worker. No writer exists yet; that approval flow is FG-65, Krum decides.
- **FG-66:** `remaining_after_payment` is never negative. When previously paid exceeds the re-priced earned amount, remaining is 0 and the row carries `correction_item` (`FLOW028_CORRECTION`, amount, reason). The preview totals have `corrections`, and the preview shows a warning. Paying 0 on such a row is allowed; any positive amount is refused.

## LAB-01-C (audit LAB01B-1) — `tests-LAB-01-C.txt`
- **Pricing package:** it comes only from the package named in the approver's `labor_quantity_approvals` record. The line's own `execution_package_id` no longer selects a price or pay type, and it is not even loaded. With no approver-named package, the line is priced by the profile.
- **`PUT /daily-reports`:** `day_entries` are validated and rebuilt from the same fields POST and the batch save store (`id, project_id, smr_id, extra_work_id, work_description, hours_worked, note`). These fields give 400: `execution_package_id`, `pay_type`, `piece_rate`, `approved_quantity`, `labor_pay_type`, `labor_piece_rate`, `cost_type`, `activity_type`. So do non-list or non-object entries and negative or non-numeric hours. Unknown fields are not stored. Approved reports still cannot be edited.
- **Probe as a test:** the audit probe is now `test_lab01c_probe_worker_chosen_package_does_not_change_pay`; the probe itself reports `FAILS: none`.

## LAB-01-D (FLOW Guard pass 6: FG-72, FG-73, FG-66, FG-76) — `tests-LAB-01-D.txt`
- **FG-72 — approvals bind to an exact entry, once:**
  - A labor approval binds to (report id, `report_version`, entry id); the normalizer carries all three on every line.
  - Entry ids must be unique per report: a duplicate id in `PUT /daily-reports` gives 400.
  - Any change or reset of a report (PUT, reject, reset, batch merge, technician draft edit, work-report edit) bumps `report_version` and voids its approvals (`status: void`, kept, never deleted).
  - One approval key is counted at most once: the earliest approval wins, and a duplicate line gets DQ `DUPLICATE_REPORT_ENTRY`.
- **FG-73 — owner-only edits:** `PUT /daily-reports/{id}` is allowed only for the report owner (`employee_id`). Everyone else gets 403 and must go through approve / reject / reset.
- **FG-66 — the correction is a record:** `app/services/payroll_corrections.py` writes one `payroll_corrections` record per (run, employee).
  - It is idempotent and starts as `pending_approval`, with `approval_status: awaiting_approval_runtime` because W0-07 is not started.
  - It writes a canonical AuditEvent (FLOW-028, R1) on create, update and supersede, and an open `dq_alerts` entry.
  - It is never applied, and it is superseded (not deleted) when the overpayment disappears.
- **FG-76 — one "spent" number:** the budget-burn warning (`/progress-warnings`) reads `project_labor_cost`, not work_sessions. Expected-actual has done so since LAB-01; #71 changes only that route's visibility, not the service.

## LAB-01-D-C01 (audit notes on 21d4ed1) — `tests-LAB-01-D-C01.txt`
- **(a) Decided corrections stay untouched:**
  - A run edit re-prices only `pending_approval` / `superseded` corrections that are not `applied`. The write filter enforces this too.
  - An approved, applied or other decided correction is never rewritten or superseded. A new difference opens the DQ alert `PAYROLL_CORRECTION_CHANGED_AFTER_DECISION` (decided amount vs new amount) instead.
- **(b) Void before the write:** `void_labor_approvals` (version bump + void) now runs **before** the content or status write in PUT, reject, reset, batch merge, the technician draft edit and the work-report edit. If the write then fails, the approvals stay void, which is the safe side.

## LAB-01-E (FLOW Guard pass 7: FG-78, FG-79, FG-80) — `tests-LAB-01-E.txt`
- **FG-78:** `PUT /technician/draft/{id}` is allowed only for the draft's owner (`submitted_by` or `worker_id`), otherwise 403. Only a `Draft` can be edited; a submitted report gives 400.
- **FG-79:** `POST /daily-reports/batch-save` checks every existing report first, before any write:
  - the owner (`employee_id` or `created_by`) is required, otherwise 403;
  - only DRAFT or REJECTED reports can be changed, otherwise 409;
  - one refusal means nothing is written for anyone in the batch;
  - a content change bumps the version and voids approvals (before the write).
- **FG-80 — corrections:** one `payroll_corrections` record per underlying overpayment, keyed `overpayment:employee:<id>:period:<start>..<end>:source:paid_pay_runs_of_period`. It is the same record across runs (`pay_run_ids`) and is superseded per employee + period.
- **FG-80 — R29 idempotency:** `POST /pay-runs` requires `Idempotency-Key` (W0-04 registry, per tenant, action `pay_run.create`).
  - No key → 428.
  - Same key + same body → the first run is returned (`idempotent_replay`).
  - Same key + another body → 409; a key still in progress → 409.
  - A refused attempt (4xx) can be retried under the same key.
  - Frontend `PayRunsPage.js` sends one key per request body; a double click or retry reuses it. The frontend build was not run here (no node_modules).
  - The R0-05 / R0-06 / LAB-01 test clients add a fresh key per `POST /pay-runs` (`tests/pay_run_idempotency.py`); their assertions are unchanged.

## LAB-01-F (FLOW Guard pass 8: FG-84, FG-85) — `tests-LAB-01-F.txt`
- **FG-84:** a correction is keyed by its **paid source**: the employee + the paid pay-run lines that make up "previously paid" (`overpayment:employee:<id>:source:paid_pay_run_lines:<run ids>`).
  - It is no longer keyed by the period of the run that noticed it.
  - A weekly, wider or monthly run that rests on the same paid lines finds the same record (`source_pay_run_ids`, `source_lines`, `pay_run_ids`). A different amount re-prices that record; it never creates a second one.
  - A pending correction is superseded only when a run covers all of its source runs and no longer shows that overpayment.
- **FG-85:** the concurrency test `test_fg85_concurrent_creates_with_one_key_give_one_run` (6 concurrent creates with one key give exactly 1 run) needs #72's unique `audit_idempotency` index.
  - It is skipped on this branch alone.
  - On a local trial merge with #72 @ 8ac194a it passed 5/5 on real Mongo; that run is section B of the evidence.
  - `IdempotencyUnprotected` from #72 maps to 503 (fail closed, nothing written).

## LAB-01-G (F2 — CLAUDE.md §7: no automatic netting of receivables and payables) — `tests-LAB-01-G.txt`
- **"Paid before" is capped:** an earlier paid line counts only up to the LAB-01 earned amount of the days it covered (`allocate_paid_sources` in `pay_runs.py`).
  - Paid lines are taken in run order and share the earned of overlapping days.
  - The excess is a **receivable** from the person.
  - Later earnings are paid in full; they are never reduced by an earlier overpayment.
  - Rows show `previously_paid` (counted), `previously_paid_total` (what was paid) and `receivable_from_overpayment`.
- **One record per receivable:** one `payroll_corrections` record per (employee, paid source line), key `overpayment:employee:<id>:source:pay_run:<run>`.
  - It is created once and stays `pending_approval` until an explicit approved decision (W0-07 not started → `awaiting_approval_runtime` + DQ alert).
  - No pay run, draft or confirmed, supersedes, re-prices, absorbs or applies it.
  - A recomputation with another amount only opens a DQ alert: `PAYROLL_CORRECTION_RECOMPUTED`, or `…CHANGED_AFTER_DECISION` for a decided record.
- **Test:** a draft monthly run with 600 of later earnings shows remaining **600** (not 540). The 60 correction stays pending and unchanged; paying 600 is allowed, 601 is refused.

## LAB-01-H (R36, LAB-01 Addendum A, Krum 07.11.2026) — `tests-LAB-01-H.txt`
- **One rule** (`app/services/report_corrections.py`) for `PUT /daily-reports/{id}`, `PUT /technician/draft/{id}` and `POST /daily-reports/batch-save`:
  - the **author** (the worker, or whoever entered the report) corrects only their own DRAFT or returned report; any other status gives 400;
  - **Admin, Owner and the SiteManager of the report's project(s)** (`can_manage_project`; every project the report has or would get) correct ANY report, approved included;
  - anyone else gets 403.
- **Every edit is audited:** one canonical AuditEvent with actor, `occurred_at` and `structured_diff` before/after. The action is `daily_report.corrected` for an approver and `daily_report.edited` for the author. An approver's correction also sets `corrected_by` / `corrected_at`.
- **Approved reports:** correcting one bumps `report_version` and voids its quantity approvals before the write (FG-72). The report stays APPROVED with the corrected values.
- **Interpretation:** a report already in payroll (`payroll_status` batched/paid) gets 409 for everyone. FLOW-028 says "Корекции след плащане: няма тихо редактиране", so these go through the correction / reversal path, not an in-place edit.
- **Batch-save:** all existing reports are checked first; one refusal means nothing is written, including new reports in the same batch.
- **Tests:** `tests/test_lab_01_h_r36.py`, 25 cases across Admin / Owner / SiteManager of the project / SiteManager of another project / Technician / Accountant / author × draft / returned / submitted / approved / payroll. FG-73 and FG-79 tests were updated to R36.

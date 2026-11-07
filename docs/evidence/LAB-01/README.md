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

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

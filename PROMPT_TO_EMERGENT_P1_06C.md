TASK: P1-0.6C — Apply prepared BEG_Work payroll patch package

TYPE:
Implement the uploaded patch package only.
Do not rewrite payroll.
Do not migrate data.
Do not backfill old slips.
Do not modify production data.
Do not change payroll_sync.py, mark-paid sync, or previously_paid algorithm.
Do not touch frontend/deploy/root package files.

CONTEXT:
The previous P1-0.6A was reported as done, but Codex reviewed BEG_Worck/main and found the actual diff was missing. This ZIP contains the prepared patch package generated outside Emergent.

FILES IN PATCH PACKAGE:
- tools/apply_p1_06c_payroll_patch.py
- backend/tests/test_pay_runs_p1_06c_helpers.py
- README_P1_06C_BG.md

ACTIONS:
1. Ensure you are in the BEG_Worck repo root.
2. Copy/keep the patch package files in the repo.
3. Run:

```bash
pwd
git branch --show-current
git status --short
python tools/apply_p1_06c_payroll_patch.py
python -m py_compile backend/app/routes/pay_runs.py
PYTHONPATH=backend pytest backend/tests/test_pay_runs_p1_06c_helpers.py -q
```

4. Verify:

```bash
rg -n "_build_report_lines|_validate_no_overpayment|report_lines|selected_report_ids|remaining_before_payment" backend/app/routes/pay_runs.py
git diff --name-only
git diff -- backend/app/routes/pay_runs.py backend/tests/test_pay_runs_p1_06c_helpers.py
```

EXPECTED CODE CHANGES:
- Add _money_float(), _validate_no_overpayment(), _build_report_lines() in backend/app/routes/pay_runs.py.
- Create/update/reconfirm paths must block paid_now_amount > earned + bonuses - deductions - previously_paid + 0.01.
- Negative paid_now_amount must be rejected.
- If remaining_before_payment is already negative, positive paid_now_amount must be rejected.
- New and replacement v3 payment_slips must include report_lines[], selected_report_ids, and report_line_count.
- Update/reconfirm rebuilt employee_rows must preserve day_cells and selected_report_ids.

RETURN:
STATUS:
CHANGED FILES:
TESTS RUN:
TEST RESULTS:
GIT STATUS:
RG OUTPUT:
DIFF SUMMARY:
FULL DIFF FOR pay_runs.py AND TEST FILE:
RISKS/TODO:

Do not claim success unless the git diff shows backend/app/routes/pay_runs.py changed and tests exist in backend/tests/.

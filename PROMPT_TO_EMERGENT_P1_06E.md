TASK: P1-0.6E — Apply payroll patch package correctly after failed P1-0.6C

TYPE:
Implementation from uploaded ZIP package only.
Mini-fix only.
Do not rewrite payroll.
Do not migrate data.
Do not backfill old slips.
Do not modify production data.
Do not change payroll_sync.py, mark-paid sync, or previously_paid algorithm.
Do not touch frontend/deploy/root package files.

CONTEXT:
Codex re-reviewed P1-0.6C and returned FAIL.
The claimed patch was not present in the workspace.
Codex found:
- backend/app/routes/pay_runs.py was not changed
- backend/tests/test_pay_runs_p1_06c_helpers.py was missing
- tools/apply_p1_06c_payroll_patch.py was missing
- only unrelated root package-manager files were changed: yarn.lock, .yarnrc.yml, package.json

This uploaded ZIP is P1-0.6E. It contains a fresh patch applier and test file.

FILES IN ZIP:
- tools/apply_p1_06e_payroll_patch.py
- README_P1_06E_BG.md
- PROMPT_TO_EMERGENT_P1_06E.md

IMPORTANT WORKSPACE CHECK:
Before editing, run:

```bash
pwd
git branch --show-current
git status --short
git diff --name-only
```

You must be inside the BEG_Worck repo root.
If you are not in BEG_Worck, stop and report.

CLEAN UNRELATED ROOT PACKAGE CHANGES FIRST:
Codex found unrelated package-manager changes from prior attempts. Remove them from this payroll patch before applying code.

Run safely:

```bash
git checkout -- yarn.lock || true
if ! git ls-files --error-unmatch .yarnrc.yml >/dev/null 2>&1; then rm -f .yarnrc.yml; fi
if ! git ls-files --error-unmatch package.json >/dev/null 2>&1; then rm -f package.json; fi
git status --short
```

APPLY PATCH:
Copy the ZIP contents into the repo root so that this file exists:

```bash
tools/apply_p1_06e_payroll_patch.py
```

Then run:

```bash
python tools/apply_p1_06e_payroll_patch.py
python -m py_compile backend/app/routes/pay_runs.py
PYTHONPATH=backend pytest backend/tests/test_pay_runs_p1_06e_helpers.py -q
```

VERIFY REAL DIFF:
Run and return output:

```bash
git status --short
git diff --name-only
rg -n "_build_report_lines|_validate_no_overpayment|report_lines|selected_report_ids|remaining_before_payment|paid_now_amount" backend/app/routes/pay_runs.py
find backend -maxdepth 4 -type f | sort | rg "test_pay_runs_p1_06e|pay_runs"
git diff -- backend/app/routes/pay_runs.py backend/tests/test_pay_runs_p1_06e_helpers.py tools/apply_p1_06e_payroll_patch.py
```

EXPECTED CODE CHANGES:
1. `backend/app/routes/pay_runs.py` contains:
   - `_money_float()`
   - `_validate_no_overpayment()`
   - `_build_report_lines()`

2. Overpayment guard enforces:
   - `paid_now_amount >= 0`
   - `paid_now_amount <= earned_amount + bonuses_amount - deductions_amount - previously_paid + 0.01`
   - if `remaining_before_payment` is already negative, positive `paid_now_amount` is rejected
   - invalid values raise HTTP 400

3. Guard is called before:
   - initial create freezes employee_rows
   - initial confirmed slips are inserted
   - update/reconfirm rebuilds employee_rows
   - replacement slips are inserted

4. New and replacement `payment_slips` include:
   - `report_lines`
   - `selected_report_ids`
   - `report_line_count`

5. Update/reconfirm rebuilt `employee_rows` preserve:
   - `day_cells`
   - `selected_report_ids`

6. Tests exist and pass:
   - `backend/tests/test_pay_runs_p1_06e_helpers.py`

RETURN FORMAT:
STATUS:
CHANGED FILES:
CLEANUP DONE:
TESTS RUN:
TEST RESULTS:
GIT STATUS:
RG OUTPUT:
DIFF SUMMARY:
FULL DIFF:
RISKS/TODO:

Do not claim success unless:
- `git diff --name-only` includes `backend/app/routes/pay_runs.py`
- test file exists under `backend/tests/`
- pytest command passes
- rg output shows `_build_report_lines` and `_validate_no_overpayment`
- unrelated root package-manager changes are gone

# P1-0.6E — BEG_Work Payroll mini-fix package

## Цел
Този ZIP е корекция след неуспешен P1-0.6C. Codex показа, че patch-ът не е бил реално приложен в workspace-а.

Този пакет трябва да приложи реални промени в:

- `backend/app/routes/pay_runs.py`
- `backend/tests/test_pay_runs_p1_06e_helpers.py`

## Какво добавя

- `_money_float()`
- `_validate_no_overpayment()`
- `_build_report_lines()`
- overpayment guard в create и update/reconfirm paths
- `report_lines[]`, `selected_report_ids`, `report_line_count` в нови и replacement `payment_slips`
- запазване на `day_cells` и `selected_report_ids` при update/reconfirm

## Какво не пипа

- `payroll_sync.py`
- mark-paid sync
- `previously_paid` алгоритъм
- production DB
- migrations
- frontend
- root package/yarn файлове

## Минимална проверка

```bash
python tools/apply_p1_06e_payroll_patch.py
python -m py_compile backend/app/routes/pay_runs.py
PYTHONPATH=backend pytest backend/tests/test_pay_runs_p1_06e_helpers.py -q
rg -n "_build_report_lines|_validate_no_overpayment|report_lines|selected_report_ids|remaining_before_payment" backend/app/routes/pay_runs.py
```

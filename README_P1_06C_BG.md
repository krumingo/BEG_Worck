# P1-0.6C — BEG_Work payroll patch package

Този ZIP е нашата част от workflow-а: **кодът се подготвя тук**, ти го качваш в Emergent, Emergent го прилага върху проекта, след това Codex и аз проверяваме реалния diff.

## Какво поправя patch-ът

Файл за промяна в проекта:

```text
backend/app/routes/pay_runs.py
```

Добавя:

1. `_money_float()` — безопасно money/numeric преобразуване.
2. `_validate_no_overpayment()` — guard срещу надплащане.
3. `_build_report_lines()` — замразява `day_cells[].reports[]` / `day_cells[].report_ids` в `payment_slips[].report_lines[]`.
4. `selected_report_ids` в новите и replacement `payment_slips`.
5. `report_line_count` в slips.
6. Preserve на `day_cells` и `selected_report_ids` при update/reconfirm.
7. Focused helper tests в `backend/tests/test_pay_runs_p1_06c_helpers.py`.

## Какво НЕ пипа

- `payroll_sync.py`
- `previously_paid` алгоритъма
- mark-paid логиката
- production DB
- migrations/backfills
- frontend/deploy/root package files

## Инструкции към Emergent

1. Качи този ZIP в Emergent заедно с текущия BEG_Work project ZIP или върху workspace-а на проекта.
2. Разархивирай patch package-а в root на repo-то, така че да се появи:

```text
tools/apply_p1_06c_payroll_patch.py
backend/tests/test_pay_runs_p1_06c_helpers.py
```

3. Пусни:

```bash
python tools/apply_p1_06c_payroll_patch.py
python -m py_compile backend/app/routes/pay_runs.py
PYTHONPATH=backend pytest backend/tests/test_pay_runs_p1_06c_helpers.py -q
git diff -- backend/app/routes/pay_runs.py backend/tests/test_pay_runs_p1_06c_helpers.py
```

4. Върни в чата:

```text
STATUS
CHANGED FILES
TEST COMMANDS + OUTPUT
git status --short
git diff --name-only
git diff -- backend/app/routes/pay_runs.py backend/tests/test_pay_runs_p1_06c_helpers.py
rg -n "_build_report_lines|_validate_no_overpayment|report_lines|selected_report_ids|remaining_before_payment" backend/app/routes/pay_runs.py
```

## Очакван резултат

Codex трябва после да намери реално:

```text
def _build_report_lines(...)
def _validate_no_overpayment(...)
payment_slips contain report_lines[]
payment_slips contain selected_report_ids
update/reconfirm preserves day_cells + selected_report_ids
tests exist and pass
```


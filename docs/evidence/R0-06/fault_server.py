"""R0-06-C01 bot test only — the real backend app with ONE injected failure.

The last payment effect (_mark_slips_paid) raises, so a mark-paid ends as
`payment_failed` AFTER the salary Outflows were written — the realistic worst case.
Never used outside a disposable local database; product code is not changed.

    cd backend
    PYTHONPATH=. python -m uvicorn --app-dir ../docs/evidence/R0-06 fault_server:app --host 127.0.0.1 --port 8001
"""
from server import app  # noqa: F401  (the app uvicorn serves)
from app.routes import pay_runs


async def _injected_failure(*args, **kwargs):
    raise RuntimeError("R0-06-C01 bot: injected failure in _mark_slips_paid")

pay_runs._mark_slips_paid = _injected_failure

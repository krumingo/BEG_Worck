"""LAB-01-E (R29): POST /pay-runs requires an ``Idempotency-Key``. Test clients that
create Pay Runs and are not about idempotency itself use this httpx request hook: it
gives every POST /api/pay-runs that has no key a fresh one (as the frontend does)."""
import uuid


async def add_pay_run_idempotency_key(request):
    if (request.method == "POST" and request.url.path == "/api/pay-runs"
            and "idempotency-key" not in request.headers):
        request.headers["Idempotency-Key"] = "test-" + uuid.uuid4().hex


EVENT_HOOKS = {"request": [add_pay_run_idempotency_key]}

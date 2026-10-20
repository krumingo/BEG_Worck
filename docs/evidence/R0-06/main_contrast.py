"""R0-06 contrast — the same seed and the same API calls as the bot, against a backend
running main @ 078b8e7 (before R0-06): create + mark-paid, reopen the paid run, PATCH,
mark-paid again. Prints each status and the salary Outflows per employee.
Test data only (disposable local database).

    python main_contrast.py http://127.0.0.1:8001 seed.json > main_contrast.json
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
seed = json.load(open(sys.argv[2]))
PASSWORD = "R006-bot-test-only!"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


_, login = call("POST", "/auth/login", {"email": seed["admin_email"], "password": PASSWORD})
tok = login["token"]
_, preview = call("GET", "/pay-runs/generate?period_start=%s&period_end=%s"
                  % (seed["period_start"], seed["period_end"]), token=tok)
rows = [{"employee_id": r["employee_id"], "paid_now_amount": r["earned_amount"]} for r in preview["rows"]]
body = {"run_type": "weekly", "period_start": seed["period_start"], "period_end": seed["period_end"],
        "rows": rows, "status": "confirmed"}
out = {}
st, run = call("POST", "/pay-runs", body, tok)
out["create"] = st
run_id = run["id"]
out["mark_paid"] = call("POST", "/pay-runs/%s/mark-paid" % run_id, {"payment_method": "cash"}, tok)[0]
out["reopen_paid"] = call("POST", "/pay-runs/%s/reopen" % run_id, {"employee_ids": [], "reason": "contrast"}, tok)
out["patch_after_reopen"] = call("PATCH", "/pay-runs/%s" % run_id, body, tok)[0]
out["mark_paid_again"] = call("POST", "/pay-runs/%s/mark-paid" % run_id, {"payment_method": "cash"}, tok)
_, pays = call("GET", "/finance/payments?direction=Outflow", token=tok)
mine = [p for p in pays if p.get("reference") == run_id]
per = {}
for p in mine:
    per.setdefault(p["counterparty_name"], []).append(p["amount"])
out["salary_outflows_per_employee"] = per
out["salary_outflow_total"] = sum(p["amount"] for p in mine)
print(json.dumps(out, indent=2, ensure_ascii=False))

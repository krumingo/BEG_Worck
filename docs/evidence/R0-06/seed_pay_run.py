"""R0-06 bot test — seed one TEST tenant through the real API only.

/billing/signup (Owner) → mock-checkout upgrade to Pro (local test env only) → the Owner creates one Admin and three workers (/users),
their pay profiles (/employees), one project (/projects), daily reports for
Mon–Fri of one week (/daily-reports/batch-save) and approves every report
(/daily-reports/{id}/approve), and one cash account „Каса" (/finance/accounts) so the
salary Outflows have somewhere to leave from. Test data only; the password is a throwaway
local test value, never used outside a disposable local database.

    python seed_pay_run.py http://127.0.0.1:8001 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "R006-bot-test-only!"
DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
PERIOD = ("2026-10-05", "2026-10-11")
WORKERS = [("Ivan", "Alpha", {"pay_type": "Daily", "daily_rate": 100}),
           ("Petar", "Bravo", {"pay_type": "Hourly", "hourly_rate": 12.5}),
           ("Georgi", "Charlie", {"pay_type": "Daily", "daily_rate": 80})]


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


signup = call("POST", "/billing/signup", {"org_name": "R006 Test Firm", "owner_name": "Owner R006",
                                          "owner_email": "owner@r006.test", "password": PASSWORD})
owner = signup["token"]
# The signup plan has no payroll module (M4). Upgrade to Pro through the mock checkout,
# which the backend allows only with BILLING_PROVIDER=mock in ENV development/test.
call("POST", "/billing/create-checkout-session", {"plan_id": "pro", "origin_url": "http://127.0.0.1:3000"}, owner)
admin_email = "admin@r006.test"
call("POST", "/users", {"email": admin_email, "password": PASSWORD, "first_name": "Admin",
                        "last_name": "R006", "role": "Admin"}, owner)
workers = []
for first, last, prof in WORKERS:
    u = call("POST", "/users", {"email": "%s@r006.test" % first.lower(), "password": PASSWORD,
                                "first_name": first, "last_name": last, "role": "Technician"}, owner)
    call("POST", "/employees", dict(prof, user_id=u["id"], position="Worker"), owner)
    workers.append({"id": u["id"], "name": "%s %s" % (first, last)})
project = call("POST", "/projects", {"code": "R006-1", "name": "R006 Site", "status": "Active"}, owner)
report_ids = []
for day in DAYS:
    call("POST", "/daily-reports/batch-save", {"project_id": project["id"], "report_date": day, "entries": [
        {"employee_id": w["id"], "work_description": "Masonry", "hours_worked": 8} for w in workers]}, owner)
    entries = call("GET", "/daily-reports/project-entries/%s?date=%s" % (project["id"], day), token=owner)
    for e in entries["by_employee"]:
        call("POST", "/daily-reports/%s/approve" % e["report_id"], {}, owner)
        report_ids.append(e["report_id"])
cash = call("POST", "/finance/accounts", {"name": "Каса", "type": "Cash", "currency": "EUR"}, owner)
print(json.dumps({"cash_account_id": cash["id"], "org_id": signup["organization"]["id"], "admin_email": admin_email,
                  "period_start": PERIOD[0], "period_end": PERIOD[1], "project_id": project["id"],
                  "workers": workers, "approved_reports": len(report_ids)}, indent=2))

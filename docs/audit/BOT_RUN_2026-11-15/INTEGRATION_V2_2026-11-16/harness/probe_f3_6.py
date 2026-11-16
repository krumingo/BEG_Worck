"""INTEGRATION probe for F3-6 (not part of process_bot cycles).

In the cycles the second path (POST /daily-reports for a person/day/object already reported
via the technician) is now refused (F3-4), so step 6 is never reached. This probe checks the
same rule on its own: a report entered ONLY through POST /daily-reports (a free day for W1),
then approved, must give exactly one work_session (P&L labor reads work_sessions).
The SiteManager who entered it may not approve it (four-eyes, LAB-R96 step 2), so the
approval is attempted by the SiteManager (expect 403) and then made by Admin.
Writes run/probe_f3_6.jsonl through process_bot.rec."""
import sys
from datetime import date, timedelta

sys.argv = [sys.argv[0]]
import process_bot as pb  # noqa: E402

pb.OUT = pb.os.path.join(pb.RUN, "probe_f3_6.jsonl")
F = "F3-6-probe"
P = pb.MDB.projects.find_one({"code": {"$regex": "^PB-"}}, sort=[("created_at", -1)])["id"]
W1 = pb.W[1]
for i, off in enumerate((40, 41, 42)):
    D = (date.today() + timedelta(days=off)).isoformat()
    st, _, txt = pb.api("Technician", "POST", f"/technician/site/{P}/attendance", {"date": D, "workers": [
        {"worker_id": W1, "worker_name": pb.WNAME[W1], "status": "Present"}]})
    pb.rec(F, "1.attendance", "Technician", "POST", f"/technician/site/{P}/attendance", st, "200", pb.short(txt)[:120],
           st == 200 or None)
    body = {"employee_id": W1, "report_date": D, "day_status": "WORKING", "notes": f"probe F3-6 #{i + 1}",
            "day_entries": [{"project_id": P, "work_description": "Зидария", "hours_worked": 8}]}
    st, j, txt = pb.api("SiteManager", "POST", "/daily-reports", body)
    pb.rec(F, "4'.second_path_only", "SiteManager", "POST", "/daily-reports", st, "201 (свободен ден)", pb.short(txt)[:200],
           st == 201 or None)
    if st != 201:
        continue
    rid = j["id"]
    st, j, txt = pb.api("SiteManager", "POST", f"/daily-reports/{rid}/submit")
    pb.rec(F, "5.submit", "SiteManager", "POST", f"/daily-reports/{rid}/submit", st, "SUBMITTED", pb.short(txt)[:160],
           st == 200 or None)
    st, j, txt = pb.api("SiteManager", "POST", f"/daily-reports/{rid}/approve", {})
    pb.rec(F, "6a.self_approve", "SiteManager", "POST", f"/daily-reports/{rid}/approve", st, "403 (одобрява друг)",
           pb.short(txt)[:160], st == 403)
    st, j, txt = pb.api("Admin", "POST", f"/daily-reports/{rid}/approve", {})
    ws = pb.MDB.work_sessions.count_documents({"approved_report_id": rid})
    pb.rec(F, "6.approve_second_path", "Admin", "POST", f"/daily-reports/{rid}/approve", st,
           "APPROVED + work_session (за да влезе трудът в P&L)",
           {"status": (j or {}).get("approval_status") if st == 200 else pb.short(txt), "work_sessions": ws},
           (ws == 1) if st == 200 else None)

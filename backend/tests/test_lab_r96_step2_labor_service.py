"""
LAB-R96 step 2 — the "Отчет на труда" service (``app/services/labor_report_service.py``).

Р96 / Р100 / Р101 / Р102. Unit tests of the service through the real routes, on the same
in-process harness as ``test_lab_r96_rules.py`` (FastAPI app with the real routers, real JWT,
``mongomock_motor`` and — when ``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB — a
real replica set; one fresh ``fixtest_lab2_<hex>`` database per test, dropped afterwards):

* the conflict payload ("Вече има отчет": existing line id, date, object, activity, who, status);
* Idempotency-Key: a repeated submit returns the first lines, nothing new;
* offline sync: the same local id twice → one set of lines; another record for the same key →
  a visible conflict (``already_recorded``), nothing written;
* who may report for whom (worker / technician member / technician not member / office);
* backdating (Admin without a reason), four-eyes on bulk and on "Моят ден";
* AuditEvents for create / update / submit / approve / reject;
* a void frees the slot; the partial unique index (real MongoDB);
* tenant isolation (another tenant's identical line neither conflicts nor is shown);
* the old-format adapters keep their GET shapes (``/daily-reports/{id}``, project-entries,
  batch-save with ``line_id``, "Дневници");
* Р101: the clock answers 410 CLOCK_REMOVED.

    PYTHONPATH=. pytest tests/test_lab_r96_step2_labor_service.py -v --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests import test_lab_r96_rules as h
from tests.test_lab_r96_rules import (
    A, ORG, P, P2, TODAY, W0, W1, WT_A, YESTERDAY, backend, daily_log, daily_report, headers, mark,
    seed, tech_report,
)

__all__ = ["backend"]
DB_PREFIX = "fixtest_lab2_"
ORG2 = "ORG-LABR96-OTHER"


class _Db(h._Db):
    def __init__(self, backend):
        super().__init__(backend)
        self.name = DB_PREFIX + uuid.uuid4().hex[:10]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            assert self.name.startswith(DB_PREFIX)
            await self.client.drop_database(self.name)
            self.client.close()


def run(monkeypatch, backend, scenario, present=(W0, W1, h.W2)):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await seed(op, present)
            h._patch_db(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h._app()),
                                         base_url="http://labr96") as c:
                return await scenario(c, op)
    return asyncio.run(body())


def detail(r):
    return r.json()["detail"]


async def lines(op, **flt):
    return await op.employee_daily_reports.find({"org_id": ORG, **flt}, {"_id": 0}).to_list(100)


# ═══════════════════════════════════════════════════════════════════ conflict
def test_conflict_payload_names_the_existing_line(monkeypatch, backend):
    async def scenario(c, op):
        first = await tech_report(c)
        rid = first.json()["draft_report_ids"][0]
        r = await tech_report(c, hours=4)
        assert r.status_code == 409, r.text
        d = detail(r)
        assert d["error_code"] == "LABOR_LINE_EXISTS"
        assert d["message"].startswith("Вече има отчет за W0-HOURLY на %s по Обект P / %s" % (TODAY, A))
        e = d["existing"]
        assert (e["line_id"], e["date"], e["project_id"], e["project_name"], e["activity"], e["hours"],
                e["status"], e["entered_by"], e["worker_id"]) == (rid, TODAY, P, "Обект P", A, 8, "Draft",
                                                                  "tech", W0)
        assert e["entered_by_name"] == "tech Staff"
        assert len(await lines(op, worker_id=W0)) == 1
    run(monkeypatch, backend, scenario)


def test_conflict_ignores_case_and_spaces_but_not_another_activity(monkeypatch, backend):
    async def scenario(c, op):
        assert (await tech_report(c)).status_code == 200
        r = await c.post("/api/technician/daily-report", headers=headers("tech"), json={
            "project_id": P, "entries": [{"worker_id": W0, "smr_type": "  шпакловка ", "hours": 1}]})
        assert r.status_code == 409, r.text
        r = await c.post("/api/technician/daily-report", headers=headers("tech"), json={
            "project_id": P, "entries": [{"worker_id": W0, "smr_type": "Боя", "hours": 1}]})
        assert r.status_code == 200, r.text
        assert sorted(x["smr_type"] for x in await lines(op, worker_id=W0)) == ["Боя", A]
    run(monkeypatch, backend, scenario)


def test_two_entries_with_the_same_key_in_one_request_are_refused(monkeypatch, backend):
    async def scenario(c, op):
        r = await c.post("/api/technician/daily-report", headers=headers("tech"), json={
            "project_id": P, "entries": [{"worker_id": W0, "smr_type": A, "hours": 4},
                                         {"worker_id": W0, "smr_type": A, "hours": 4}]})
        assert r.status_code == 409 and detail(r)["existing"].get("same_request") is True, r.text
        assert await lines(op) == []
    run(monkeypatch, backend, scenario)


def test_an_old_format_row_is_an_existing_line(monkeypatch, backend):
    """Historic rows (employee_id / report_date / day_entries) are not migrated, but they hold
    their slot: a new line for the same key is "Вече има отчет" pointing at the old row."""
    async def scenario(c, op):
        await op.employee_daily_reports.insert_one({
            "id": "old-1", "org_id": ORG, "employee_id": W0, "report_date": TODAY,
            "day_status": "WORKING", "approval_status": "DRAFT", "created_by": "admin",
            "day_entries": [{"id": "e1", "project_id": P, "work_description": A, "hours_worked": 8}]})
        r = await tech_report(c)
        assert r.status_code == 409, r.text
        e = detail(r)["existing"]
        assert (e["format"], e["report_id"], e["line_id"], e["hours"]) == ("old", "old-1", "e1", 8)
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ idempotency / offline
def test_idempotency_key_replays_the_first_answer(monkeypatch, backend):
    async def scenario(c, op):
        body = {"project_id": P, "entries": [{"worker_id": W0, "smr_type": A, "hours": 8}]}
        hdr = dict(headers("tech"), **{"Idempotency-Key": "idem-1"})
        r1 = await c.post("/api/technician/daily-report", headers=hdr, json=body)
        r2 = await c.post("/api/technician/daily-report", headers=hdr, json=body)
        assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
        assert r2.json()["idempotent_replay"] is True
        assert r2.json()["draft_report_ids"] == r1.json()["draft_report_ids"]
        rows = await lines(op, worker_id=W0)
        assert len(rows) == 1 and rows[0]["idempotency_key"] == "idem-1"
        hd = dict(headers("admin"), **{"Idempotency-Key": "idem-2"})
        d1 = await c.post("/api/daily-reports", headers=hd, json={
            "employee_id": W1, "report_date": TODAY, "day_status": "WORKING",
            "day_entries": [{"project_id": P, "work_description": A, "hours_worked": 8}]})
        d2 = await c.post("/api/daily-reports", headers=hd, json={
            "employee_id": W1, "report_date": TODAY, "day_status": "WORKING",
            "day_entries": [{"project_id": P, "work_description": A, "hours_worked": 8}]})
        assert d1.status_code == d2.status_code == 201 and d2.json()["id"] == d1.json()["id"]
        assert len(await lines(op, worker_id=W1)) == 1
    run(monkeypatch, backend, scenario)


def test_offline_sync_same_local_id_once_other_record_is_a_visible_conflict(monkeypatch, backend):
    async def scenario(c, op):
        from app.services import offline_sync as sync
        from app.services.offline_sync_handlers import daily_report as handler
        tech = await op.users.find_one({"id": "tech"}, {"_id": 0})
        payload = {"project_id": P, "entries": [{"worker_id": W0, "smr_type": A, "hours": 6}]}

        def env(local_id):
            return {"local_id": local_id, "payload": payload, "captured_at": TODAY + "T09:00:00+00:00"}
        ctx = {"captured_date": TODAY, "device_id": "dev-1"}
        a = await handler(tech, env("loc-1"), ctx)
        b = await handler(tech, env("loc-1"), ctx)
        assert b.get("already") is True and b["draft_report_ids"] == a["draft_report_ids"]
        rows = await lines(op, worker_id=W0)
        assert len(rows) == 1 and rows[0]["sync_local_id"] == "loc-1" and rows[0]["labor_key"]
        with pytest.raises(sync.SyncConflict) as ei:
            await handler(tech, env("loc-2"), ctx)
        assert ei.value.kind == "already_recorded"
        assert ei.value.office["line_id"] == rows[0]["id"]
        assert "Вече има отчет" in ei.value.office["message"]
        assert len(await lines(op, worker_id=W0)) == 1
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ who for whom
def test_who_may_report_for_whom(monkeypatch, backend):
    async def scenario(c, op):
        # a worker for another person → 403; for himself → 200
        r = await c.post("/api/technician/daily-report", headers=headers(W1), json={
            "project_id": P, "entries": [{"worker_id": W0, "smr_type": A, "hours": 8}]})
        assert r.status_code == 403 and detail(r)["error_code"] == "LABOR_REPORT_FORBIDDEN", r.text
        r = await c.post("/api/technician/daily-report", headers=headers(W1), json={
            "project_id": P, "entries": [{"smr_type": A, "hours": 8}]})
        assert r.status_code == 200, r.text
        # a technician on an object whose team he is not in → 403 (W0 present there)
        await mark(op, W0, "Present", project=P2)
        r = await tech_report(c, project=P2)
        assert r.status_code == 403, r.text
        # the technician of P → 200; the office for anyone (any object) → 201
        assert (await tech_report(c)).status_code == 200
        await mark(op, h.W2, "Present", project=P2)
        r = await c.post("/api/daily-reports", headers=headers("admin"), json={
            "employee_id": h.W2, "report_date": TODAY, "day_status": "WORKING",
            "day_entries": [{"project_id": P2, "work_description": A, "hours_worked": 8}]})
        assert r.status_code == 201, r.text
        assert len(await lines(op, worker_id=W0, project_id=P2)) == 0
    run(monkeypatch, backend, scenario)


def test_admin_backdate_needs_a_reason(monkeypatch, backend):
    async def scenario(c, op):
        await mark(op, W0, "Present", day=YESTERDAY)
        r = await daily_report(c, day=YESTERDAY, who="admin", notes=None)
        assert r.status_code == 400 and detail(r)["error_code"] == "LABOR_BACKDATE_REASON_REQUIRED", r.text
        r = await daily_report(c, day=YESTERDAY, who="sm", notes="причина")
        assert r.status_code == 400 and detail(r)["error_code"] == "LABOR_BACKDATE_FORBIDDEN", r.text
        assert await lines(op) == []
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ four-eyes / audit
def test_four_eyes_on_bulk_approve_and_audit_trail(monkeypatch, backend):
    async def scenario(c, op):
        r = await tech_report(c, who="sm")
        rid = r.json()["draft_report_ids"][0]
        rb = await c.post("/api/daily-reports/bulk-approve", headers=headers("sm"), json={"report_ids": [rid]})
        assert rb.json()["failed"] == [{"id": rid, "reason": "self_approval"}], rb.text
        ru = await c.put("/api/technician/draft/" + rid, headers=headers("tech"), json={"hours": 7})
        assert ru.status_code == 200 and ru.json()["last_edited_by"] == "tech", ru.text
        # the corrector may not approve either; another person may
        ra = await c.post("/api/daily-reports/%s/approve" % rid, headers=headers("admin"), json={})
        assert ra.status_code == 200, ra.text
        doc = (await lines(op, id=rid))[0]
        assert (doc["status"], doc["approved_by"], doc["hours"]) == ("APPROVED", "admin", 7)
        acts = [(e["action"], e["actor_id"]) for e in await op.audit_events.find(
            {"entity_type": "labor_line", "entity_id": rid}, {"_id": 0}).sort("sequence", 1).to_list(20)]
        assert acts == [("labor_line.created", "sm"), ("labor_line.updated", "tech"),
                        ("labor_line.approved", "admin")], acts
        # an approved line is locked
        assert (await c.put("/api/technician/draft/" + rid, headers=headers("sm"), json={"hours": 9})).status_code == 400
    run(monkeypatch, backend, scenario)


def test_my_day_report_lines_are_labor_lines_with_four_eyes(monkeypatch, backend):
    async def scenario(c, op):
        r = await h.work_report_draft(c)
        assert r.status_code == 201, r.text
        wr = r.json()["id"]
        rows = await lines(op, worker_id=W0)
        assert [(x["smr_type"], x["hours"], x["work_report_id"], x["entry_mode"]) for x in rows] == [
            (A, 8, wr, "my_day")]
        assert (await op.work_reports.find_one({"id": wr}))["lines"] == []          # no hours in the header
        g = await c.get("/api/work-reports/" + wr, headers=headers(W0))
        assert [(x["activity_name"], x["hours"]) for x in g.json()["lines"]] == [(A, 8)]
        assert (await c.post("/api/work-reports/%s/submit" % wr, headers=headers(W0))).status_code == 200
        assert (await lines(op, worker_id=W0))[0]["status"] == "Submitted"
        ra = await c.post("/api/work-reports/%s/approve" % wr, headers=headers("admin"))
        assert ra.status_code == 200, ra.text
        line = (await lines(op, worker_id=W0))[0]
        assert line["status"] == "APPROVED"
        assert await op.work_sessions.count_documents({"approved_report_id": line["id"]}) == 1
        acts = sorted(e["action"] for e in await op.audit_events.find(
            {"entity_type": "labor_line", "entity_id": line["id"]}, {"_id": 0}).to_list(20))
        assert acts == ["labor_line.approved", "labor_line.created", "labor_line.submitted"], acts
    run(monkeypatch, backend, scenario)


def test_reject_is_audited_and_void_frees_the_slot(monkeypatch, backend):
    async def scenario(c, op):
        rid = (await tech_report(c)).json()["draft_report_ids"][0]
        rj = await c.post("/api/daily-reports/%s/reject" % rid, headers=headers("admin"), json={"reason": "грешка"})
        assert rj.status_code == 200 and rj.json()["status"] == "REJECTED"
        ev = await op.audit_events.find_one({"action": "labor_line.rejected", "entity_id": rid}, {"_id": 0})
        assert ev and ev["reason"] == "грешка"
        rid2 = (await tech_report(c, wid=W1)).json()["draft_report_ids"][0]
        assert (await c.delete("/api/technician/draft/" + rid2, headers=headers("tech"))).status_code == 200
        raw = await op.employee_daily_reports.find_one({"id": rid2}, {"_id": 0})
        assert raw["status"] == "voided" and "labor_key" not in raw and raw["voided_labor_key"]
        assert (await tech_report(c, wid=W1)).status_code == 200      # the slot is free again
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ tenant isolation
def test_another_tenants_identical_line_neither_conflicts_nor_shows(monkeypatch, backend):
    async def scenario(c, op):
        from app.services.labor_report_service import labor_key
        await op.employee_daily_reports.insert_one({
            "id": "other-tenant-line", "org_id": ORG2, "worker_id": W0, "date": TODAY, "project_id": P,
            "smr_type": A, "hours": 8, "status": "Draft", "labor_key": labor_key(W0, TODAY, P, A)})
        r = await tech_report(c)
        assert r.status_code == 200, r.text
        r2 = await tech_report(c)
        assert detail(r2)["existing"]["line_id"] == r.json()["draft_report_ids"][0]
        assert (await c.get("/api/daily-reports/other-tenant-line", headers=headers("admin"))).status_code == 404
        assert (await c.post("/api/daily-reports/other-tenant-line/approve", headers=headers("admin"),
                             json={})).status_code == 404
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ adapters keep their shapes
def test_old_format_endpoints_keep_their_shapes(monkeypatch, backend):
    async def scenario(c, op):
        r = await daily_report(c, who="admin")
        assert r.status_code == 201, r.text
        body = r.json()
        assert (body["employee_id"], body["report_date"], body["approval_status"], body["total_hours"]) == (
            W0, TODAY, "DRAFT", 8)
        lid = body["day_entries"][0]["line_id"]
        raw = await op.employee_daily_reports.find_one({"id": lid}, {"_id": 0})
        assert (raw["worker_id"], raw["smr_type"], raw["hours"], raw["entry_mode"]) == (W0, A, 8, "daily_report_form")
        assert "employee_id" not in raw                                   # one format: the flat line
        g = (await c.get("/api/daily-reports/" + body["id"], headers=headers("admin"))).json()
        assert [e["hours_worked"] for e in g["day_entries"]] == [8] and g["employee_id"] == W0
        pe = (await c.get("/api/daily-reports/project-entries/%s?date=%s" % (P, TODAY), headers=headers("admin"))).json()
        assert [(x["employee_id"], x["entries"][0]["line_id"]) for x in pe["by_employee"]] == [(W0, lid)]
        # the object screen saves the same line back (line_id) → update, not a conflict
        rb = await c.post("/api/daily-reports/batch-save", headers=headers("admin"), json={
            "project_id": P, "report_date": TODAY,
            "entries": [{"employee_id": W0, "work_description": A, "hours_worked": 6, "line_id": lid}]})
        assert rb.status_code == 200, rb.text
        assert [(x["id"], x["hours"]) for x in await lines(op, worker_id=W0)] == [(lid, 6)]
        # the day dialog: submit, and the whole day approved by another person
        assert (await c.post("/api/daily-reports/%s/submit" % lid, headers=headers("admin"))).json()["approval_status"] == "SUBMITTED"
        ra = await c.post("/api/daily-reports/%s/approve" % lid, headers=headers("owner"), json={"scope": "day"})
        assert ra.status_code == 200 and ra.json()["approval_status"] == "APPROVED", ra.text
        # "Дневници": the log stores no hours, its entries come from the labor lines
        rl = await daily_log(c, wid=W1)
        assert rl.status_code == 201, rl.text
        log = await op.daily_work_logs.find_one({"id": rl.json()["id"]}, {"_id": 0})
        assert log["entries"] == [] and log["labor_lines"] is True
        gl = (await c.get("/api/daily-logs/" + log["id"], headers=headers("admin"))).json()
        assert [(e["user_id"], e["hours"]) for e in gl["entries"]] == [(W1, 8)] and gl["total_hours"] == 8
    run(monkeypatch, backend, scenario)


def test_smr_group_report_hours_without_person_and_day_point_to_the_daily_report(monkeypatch, backend):
    async def scenario(c, op):
        r = await c.post("/api/smr-groups/%s/report" % h.GRP_A, headers=headers("admin"),
                         json={"mode": "group_total", "total_hours": 16})
        assert r.status_code == 400 and detail(r)["error_code"] == "LABOR_NEEDS_PERSON_DAY", r.text
        r = await h.smr_group_report(c, wid=W1)
        assert r.status_code == 200 and len(r.json()["labor_line_ids"]) == 1, r.text
        assert [x["entry_mode"] for x in await lines(op, worker_id=W1)] == ["smr_group_report"]
    run(monkeypatch, backend, scenario)


def test_clock_is_removed(monkeypatch, backend):
    async def scenario(c, op):
        for path in ("/api/work-sessions/start", "/api/work-sessions/end"):
            r = await c.post(path, headers=headers(W0), json={"site_id": P})
            assert r.status_code == 410 and detail(r)["error_code"] == "CLOCK_REMOVED", r.text
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ the partial unique index
def test_partial_unique_index_refuses_a_second_line_and_ignores_historic_rows(monkeypatch, backend):
    if backend != "real":
        pytest.skip("unique indexes are a real-MongoDB property")

    async def scenario(c, op):
        from pymongo.errors import DuplicateKeyError
        from app.services.offline_sync import ensure_sync_indexes
        from app.services import labor_report_service as labor
        # historic duplicates without labor_key do not stop the index
        for i in (1, 2):
            await op.employee_daily_reports.insert_one({"id": "hist-%d" % i, "org_id": ORG, "worker_id": W0,
                                                        "date": YESTERDAY, "project_id": P, "smr_type": A})
        assert "lab_r96_labor_line_unique" not in await ensure_sync_indexes(op, op.name)
        key = labor.labor_key(W0, TODAY, P, A)
        await op.employee_daily_reports.insert_one({"id": "x1", "org_id": ORG, "labor_key": key})
        with pytest.raises(DuplicateKeyError):
            await op.employee_daily_reports.insert_one({"id": "x2", "org_id": ORG, "labor_key": key})
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG)
        with pytest.raises(labor.LaborLineExists):
            await labor.insert_line(tenant, {"id": "x3", "org_id": ORG, "worker_id": W0, "date": TODAY,
                                             "project_id": P, "smr_type": A, "labor_key": key})
    run(monkeypatch, backend, scenario)


def test_daily_log_work_type_constant_is_the_activity(monkeypatch, backend):
    """"Дневници" and the technician path share one key: a log of W0 for work type A after the
    technician's line of A is "Вече има отчет" (kept at this endpoint's 400)."""
    async def scenario(c, op):
        assert (await tech_report(c)).status_code == 200
        r = await daily_log(c)
        assert r.status_code == 400 and detail(r)["error_code"] == "LABOR_LINE_EXISTS", r.text
        assert await op.daily_work_logs.count_documents({}) == 0
        assert WT_A
    run(monkeypatch, backend, scenario)

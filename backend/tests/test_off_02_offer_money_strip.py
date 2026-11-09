"""
OFF-02 — FLOW Guard FG-350 (R20): no client price or total in an offer WRITE response for a
caller without the finance right, exactly like the reads (SEC-02-A ``strip_money_for_non_finance``).

FG-350: GET /offers/{id} strips the money for a SiteManager, but the writes he may call
returned the whole offer — prices, line totals, subtotal / VAT / total:
  POST /offers, PUT /offers/{id}/lines, POST /offers/{id}/new-version,
  POST /offers/{id}/versions (snapshot), POST /offers/{id}/versions/{n}/restore,
  POST /offers/import-confirm, POST /extra-works/create-offer,
  POST /projects/{id}/smr-to-offer.
The Admin/Owner-only offer transitions (accept, reject, cancel) are covered too: in enforce
the finance right comes from the Permission Service, not from the role name.

Who may WRITE an offer is unchanged (a separate question for Krum); only what the response
shows changes. Finance roles still get every money field.

Real MongoDB replica set (``W0_03_REAL_MONGO_URL``), PERMISSION_SERVICE_MODE off / shadow /
enforce, the OFF-01 harness.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27017/?replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_off_02_offer_money_strip.py -q --noconftest -p no:cacheprovider
"""
import json

import pytest

import tests.test_off_01_offer_version_accept as T
from tests.test_off_01_offer_version_accept import (  # noqa: F401  (fixtures)
    ORG_A, PRJ_A, TOKEN, backend, code, get, hdr, mode, offer_doc, run)

#: The money keys of an offer and its lines (R20-5M) that must never reach a non-finance
#: caller. ``total`` / ``subtotal`` / ``vat_amount`` / ``line_total`` / unit prices.
OFFER_MONEY_KEYS = ("subtotal", "vat_amount", "total", "line_total", "material_unit_cost",
                    "labor_unit_cost", "line_material_cost", "line_labor_cost", "unit_price",
                    # the import preview's parsed lines
                    "material_price", "labor_price")


def money_keys_in(payload) -> set:
    """Every key of ``payload`` (at any depth) that is one of the offer money keys."""
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in OFFER_MONEY_KEYS:
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(payload)
    return found


@pytest.fixture(autouse=True)
def _with_extra_works(monkeypatch):
    monkeypatch.setitem(T.USERS, "driver-a", (ORG_A, "Driver"))
    """The OFF-01 app + the extra-works router (create-offer, smr-to-offer)."""
    real_app = T._app

    def app(mp, op, sysdb, mode_):
        a = real_app(mp, op, sysdb, mode_)
        from app.routes import extra_works as ew, missing_smr as ms, smr_analysis as sa
        for module in (ew, ms, sa):
            mp.setattr(module, "db", op, raising=False)
            a.include_router(module.router, prefix="/api")
        return a
    monkeypatch.setattr(T, "_app", app)


LINE = {"activity_name": "Мазилка", "unit": "m2", "qty": 10, "material_unit_cost": 8,
        "labor_unit_cost": 12}


async def _seed_drafts(op, n=2):
    ids = []
    for i in range(n):
        did = "ewd-%d" % i
        await op.extra_work_drafts.insert_one({
            "id": did, "org_id": ORG_A, "project_id": PRJ_A, "status": "draft",
            "title": "Допълнително СМР %d" % i, "qty": 4, "unit": "m2",
            "ai_material_price_per_unit": 10, "ai_labor_price_per_unit": 15,
            "ai_total_price_per_unit": 25, "created_at": "2026-11-01T10:00:00+00:00"})
        ids.append(did)
    return ids


async def _calls(c, op, who):
    """Every offer write response ``who`` can get, as {name: response}."""
    out = {}
    out["create"] = await c.post("/api/offers", headers=T.hdr(who), json={
        "project_id": PRJ_A, "title": "Кухня", "vat_percent": 20, "lines": [LINE]})
    oid = out["create"].json().get("id")
    out["lines"] = await c.put("/api/offers/%s/lines" % oid, headers=T.hdr(who),
                               json={"lines": [dict(LINE, qty=12)]})
    out["snapshot"] = await c.post("/api/offers/%s/versions" % oid, headers=T.hdr(who),
                                   json={"note": "ръчно"})
    out["restore"] = await c.post("/api/offers/%s/versions/1/restore" % oid, headers=T.hdr(who))
    sent_id = "sent-" + who
    await op.offers.insert_one(offer_doc(sent_id, token="tsn" + who[:4] + "q" * 17))
    out["new_version"] = await c.post("/api/offers/%s/new-version" % sent_id, headers=T.hdr(who))
    out["import_confirm"] = await c.post("/api/offers/import-confirm", headers=T.hdr(who), json={
        "project_id": PRJ_A, "title": "Импорт", "lines": [
            {"activity_name": "Боя", "unit": "m2", "qty": 5, "material_unit_cost": 3,
             "labor_unit_cost": 4}]})
    drafts = await _seed_drafts(op)
    out["extra_create_offer"] = await c.post("/api/extra-works/create-offer", headers=T.hdr(who),
                                             json={"draft_ids": drafts[:1]})
    out["smr_to_offer"] = await c.post("/api/projects/%s/smr-to-offer" % PRJ_A, headers=T.hdr(who),
                                       json={"source_ids": drafts[1:]})
    return out


def test_01_a_writer_without_the_finance_read_right_gets_no_money(monkeypatch, backend, mode):
    """FG-350: every offer write answers through the SEC-02 strip, like the read. Since R67
    only Owner / Admin / Accountant may write, the strip is the defence in depth for an
    enforce assignment that grants an offer write without finance.money_values.read — here
    forced by making money_values_visible answer False for the (writing) Admin."""
    import app.permissions.money_write as mw

    async def no_finance_read(request, user):
        return False
    monkeypatch.setattr(mw, "money_values_visible", no_finance_read)

    async def scenario(c, op):
        out = await _calls(c, op, "admin-a")
        leaks = {}
        for name, r in out.items():
            assert r.status_code in (200, 201), (name, r.status_code, r.text[:300])
            found = money_keys_in(r.json())
            if found:
                leaks[name] = sorted(found)
        assert leaks == {}, leaks
        # the write itself happened as before (only the response is stripped)
        created = await get(op, out["create"].json()["id"])
        assert created["total"] == 288.0 and created["lines"][0]["line_total"] == 240.0
    run(monkeypatch, backend, mode, scenario)


def test_02_finance_roles_still_get_the_money(monkeypatch, backend, mode):
    """Finance roles: unchanged — the totals and prices are in every write response."""
    async def scenario(c, op):
        out = await _calls(c, op, "admin-a")
        for name in ("create", "lines", "restore", "new_version", "import_confirm",
                     "extra_create_offer"):
            r = out[name]
            assert r.status_code in (200, 201), (name, r.text[:300])
            assert "total" in money_keys_in(r.json()), (name, r.text[:300])
        assert "subtotal" in out["smr_to_offer"].json()
        assert out["snapshot"].status_code in (200, 201)
    run(monkeypatch, backend, mode, scenario)


def test_03_admin_only_transitions_strip_for_a_caller_without_the_finance_right(
        monkeypatch, backend, mode):
    """accept / reject / cancel return the offer: in every mode a finance caller keeps the
    money; the response goes through the same SEC-02 strip as GET (enforce: the Permission
    Service decides, not the role name)."""
    async def scenario(c, op):
        for name, path, body in (("accept", "accept", None), ("reject", "reject", {"reason": "x"}),
                                 ("cancel", "cancel", {"reason": "x"})):
            oid = "tr-" + name
            await op.offers.insert_one(offer_doc(oid, token="ttr" + name[:3] + "w" * 18))
            r = await c.post("/api/offers/%s/%s" % (oid, path), headers=T.hdr("admin-a"), json=body)
            assert r.status_code == 200, (name, r.text)
            assert "total" in money_keys_in(r.json()), name
        import app.routes.offers as r_offers
        for name in ("accept_offer", "reject_offer", "cancel_offer", "create_offer",
                     "update_offer_lines", "create_offer_version", "import_offer_confirm"):
            assert getattr(getattr(r_offers, name), "sec02_strips_money", False), name
    run(monkeypatch, backend, mode, scenario)


def _xlsx() -> bytes:
    """A one-line import file in the template's layout (Описание, Мярка, К-во, Мат., Труд)."""
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Описание / Вид СМР", "Мярка", "Количество", "Цена материал", "Цена труд",
               "Обща цена"])
    ws.append(["Мазилка", "м2", 10, 8, 12, 200])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_04_import_preview_answers_like_the_read(monkeypatch, backend, mode):
    """POST /offers/import-preview echoes the parsed prices: stripped for a SiteManager like
    every other offer response; a finance role still sees them."""
    async def scenario(c, op):
        files = {"file": ("offer.xlsx", _xlsx(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        site = await c.post("/api/offers/import-preview", headers=T.hdr("site-a"), files=files)
        assert site.status_code == 200, site.text[:300]
        assert money_keys_in(site.json()) == set(), site.text[:400]
        assert "Мазилка" in site.text                         # the quantities / names stay
        fin = await c.post("/api/offers/import-preview", headers=T.hdr("admin-a"), files=files)
        assert fin.status_code == 200, fin.text[:300]
        assert {"material_price", "labor_price"} <= money_keys_in(fin.json()), fin.text[:400]
    run(monkeypatch, backend, mode, scenario)



# ═════════════ R67 (Krum, 09.11.2026; FG-350, OFF89-N1): who may WRITE an offer at all
FORBIDDEN = ("site-a", "tech-a", "viewer-a", "driver-a")
ALLOWED = ("owner-a", "admin-a", "acct-a")
BUSINESS = ("offers", "offer_versions", "offer_events", "extra_work_drafts", "missing_smr",
            "smr_analyses", "audit_logs")


def _writes():
    """Every offer mutation route (R67), with a body that would pass validation."""
    return [
        ("POST", "/api/offers", {"project_id": PRJ_A, "title": "Кухня", "lines": [LINE]}),
        ("PUT", "/api/offers/d1", {"title": "Ново"}),
        ("PUT", "/api/offers/d1/lines", {"lines": [{"activity_name": "Мазилка", "unit": "m2", "qty": 10}]}),
        ("POST", "/api/offers/d1/send", None),
        ("POST", "/api/offers/s1/accept", None),
        ("POST", "/api/offers/s1/reject", {"reason": "x"}),
        ("POST", "/api/offers/s1/new-version", None),
        ("POST", "/api/offers/s1/cancel", {"reason": "x"}),
        ("DELETE", "/api/offers/d1", None),
        ("POST", "/api/offers/import-confirm", {"project_id": PRJ_A, "title": "Импорт",
                                                 "lines": [{"activity_name": "Боя", "qty": 1}]}),
        ("POST", "/api/offers/d1/versions", {"note": "n"}),
        ("POST", "/api/offers/d1/versions/1/restore", None),
        ("DELETE", "/api/offers/d1/versions/1", None),
        ("POST", "/api/extra-works/create-offer", {"draft_ids": ["ewd-0"]}),
        ("POST", "/api/projects/%s/smr-to-offer" % PRJ_A, {"source_ids": ["ewd-1"]}),
        ("POST", "/api/missing-smr/ms-1/to-offer", None),
        ("POST", "/api/missing-smr/batch-to-offer", {"ids": ["ms-1"]}),
        ("POST", "/api/smr-analyses/an-1/to-offer", None),
    ]


async def _seed_r67(op):
    await op.offers.insert_one(offer_doc("d1", status="Draft"))
    await op.offers.insert_one(offer_doc("s1", token=TOKEN))
    await op.offer_versions.insert_one({
        "id": "ver-d1-1", "org_id": ORG_A, "project_id": PRJ_A, "offer_id": "d1",
        "version_number": 1, "created_at": "2026-11-01T09:00:00+00:00", "created_by": "admin-a",
        "snapshot_json": {"title": "Баня", "lines": [], "subtotal": 0, "vat_amount": 0, "total": 0}})
    await _seed_drafts(op)


async def _call(c, who, method, path, body):
    h = T.hdr(who)
    return await (c.request(method, path, headers=h, json=body) if body is not None
                  else c.request(method, path, headers=h))


def test_05_r67_every_other_role_gets_403_and_nothing_is_written(monkeypatch, backend, mode):
    """R67: SiteManager / Technician / Viewer / Driver → 403 on EVERY offer write, before
    anything is read or written (the business collections are byte-identical)."""
    async def scenario(c, op):
        await _seed_r67(op)
        before = await T.snap(op, BUSINESS)
        bad = []
        for who in FORBIDDEN:
            for method, path, body in _writes():
                r = await _call(c, who, method, path, body)
                if r.status_code != 403:
                    bad.append((who, method, path, r.status_code, r.text[:120]))
        assert bad == [], bad
        assert await T.snap(op, BUSINESS) == before
    run(monkeypatch, backend, mode, scenario)


def test_06_r67_owner_admin_accountant_may_write_offers(monkeypatch, backend, mode):
    """R67: Owner, Admin and Accountant pass the gate on every offer write (no 401/403), and
    the Accountant — refused before on create / accept / reject / cancel / delete — writes."""
    async def scenario(c, op):
        bad = []
        for who in ALLOWED:
            for coll in ("offers", "offer_versions", "extra_work_drafts"):  # fresh data per role
                await op[coll].delete_many({})
            await _seed_r67(op)
            for method, path, body in _writes():
                r = await _call(c, who, method, path, body)
                if r.status_code in (401, 403):
                    bad.append((who, method, path, r.status_code, r.text[:120]))
        assert bad == [], bad
        # the Accountant's full cycle on a fresh offer
        r = await c.post("/api/offers", headers=T.hdr("acct-a"), json={
            "project_id": PRJ_A, "title": "Счетоводител", "vat_percent": 20, "lines": [LINE]})
        assert r.status_code == 201, r.text
        oid = r.json()["id"]
        assert (await c.put("/api/offers/%s/lines" % oid, headers=T.hdr("acct-a"),
                            json={"lines": [dict(LINE, qty=12)]})).status_code == 200
        s = await c.post("/api/offers/%s/send" % oid, headers=T.hdr("acct-a"))
        assert s.status_code == 200, s.text
        a = await c.post("/api/offers/%s/accept" % oid, headers=T.hdr("acct-a"))
        assert a.status_code == 200 and a.json()["status"] == "Accepted", a.text
        assert "total" in a.json()                                # a finance role sees money
    run(monkeypatch, backend, mode, scenario)


def test_07_off89_n1_a_site_manager_cannot_zero_the_prices(monkeypatch, backend, mode):
    """AUDIT-2 OFF89-N1: a SiteManager saw the lines without prices (stripped) and PUT them
    back — every price became 0. Now: 403, the stored prices and totals are untouched; the
    client's own magic-link answer is unchanged."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("d2", status="Draft"))
        g = await c.get("/api/offers/d2", headers=T.hdr("site-a"))
        assert g.status_code == 200 and "total" not in g.json()         # the read stays, stripped
        stripped_lines = g.json()["lines"]
        assert all("material_unit_cost" not in l for l in stripped_lines)
        r = await c.put("/api/offers/d2/lines", headers=T.hdr("site-a"),
                        json={"lines": stripped_lines})
        assert r.status_code == 403, r.text
        doc = await get(op, "d2")
        assert doc["total"] == 1200.0 and doc["lines"][0]["material_unit_cost"] == 40
        # the client-link flow is not an offer write of a staff role: unchanged
        await op.offers.insert_one(offer_doc("s2", token="tcl" + "m" * 21))
        resp = await T.respond(c, "tcl" + "m" * 21, "approve")
        assert resp.status_code == 200 and resp.json()["status"] == "Accepted", resp.text
    run(monkeypatch, backend, mode, scenario)


#: R67: every offer write route and its one Permission Service action (catalog.OFFER_WRITE_ACTIONS).
R67_ROUTES = {
    ("POST", "/api/offers"): "offers.offer.create",
    ("PUT", "/api/offers/{offer_id}"): "offers.offer.update",
    ("PUT", "/api/offers/{offer_id}/lines"): "offers.offer_lines.update",
    ("POST", "/api/offers/{offer_id}/send"): "offers.offer_send.execute",
    ("POST", "/api/offers/{offer_id}/accept"): "offers.offer_accept.execute",
    ("POST", "/api/offers/{offer_id}/reject"): "offers.offer_reject.execute",
    ("POST", "/api/offers/{offer_id}/new-version"): "offers.offer_version.create",
    ("POST", "/api/offers/{offer_id}/cancel"): "offers.offer_cancel.execute",
    ("DELETE", "/api/offers/{offer_id}"): "offers.offer.delete",
    ("POST", "/api/offers/import-confirm"): "offers.offer_import.create",
    ("POST", "/api/offers/{offer_id}/versions"): "offers.offer_snapshot.create",
    ("POST", "/api/offers/{offer_id}/versions/{version_number}/restore"):
        "offers.offer_snapshot_restore.execute",
    ("DELETE", "/api/offers/{offer_id}/versions/{version_number}"): "offers.offer_snapshot.delete",
    ("POST", "/api/extra-works/create-offer"): "offers.offer_from_extra_works.create",
    ("POST", "/api/projects/{project_id}/smr-to-offer"): "offers.offer_from_smr.create",
    ("POST", "/api/missing-smr/{item_id}/to-offer"): "offers.offer_from_missing_smr.create",
    ("POST", "/api/missing-smr/batch-to-offer"): "offers.offer_from_missing_smr_batch.create",
    ("POST", "/api/smr-analyses/{analysis_id}/to-offer"): "offers.offer_from_smr_analysis.create",
}

#: FG-472: app/routes/offer_budget.py is NOT mounted in server.py (no served route, no PM-01
#: cell, no frontend caller). Its write is gated all the same (if it is ever mounted); checked
#: on the router itself, not on the served app.
UNMOUNTED_R67_ROUTES = {
    ("PUT", "/offer-budgets/{offer_id}"): "offers.offer_budget.update",
}


def test_08_r67_every_offer_write_carries_its_action_first_and_only_finance_holds_them():
    """Static: each R67 route's FIRST dependency is require_money_write with its own action;
    the catalog grants these actions to Owner, Admin and Accountant only."""
    import server
    from fastapi.routing import APIRoute
    from app.permissions.catalog import (ACTIONS, OFFER_WRITE_ACTIONS, PERMISSION_MATRIX,
                                         is_significant_action)
    found = {}
    for route in server.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if (method, route.path) in R67_ROUTES:
                calls = [d.call for d in route.dependant.dependencies]
                found[(method, route.path)] = calls
    assert set(found) == set(R67_ROUTES), sorted(set(R67_ROUTES) ^ set(found))
    for key, calls in found.items():
        assert getattr(calls[0], "sec01_action", None) == R67_ROUTES[key], key
    assert set(R67_ROUTES.values()) | set(UNMOUNTED_R67_ROUTES.values()) == OFFER_WRITE_ACTIONS
    assert OFFER_WRITE_ACTIONS <= ACTIONS
    from app.routes import offer_budget
    assert not any(isinstance(r, APIRoute) and r.path.startswith("/api/offer-budgets")
                   for r in server.app.routes)                              # still unmounted
    for route in offer_budget.router.routes:
        for method in route.methods:
            if (method, route.path) in UNMOUNTED_R67_ROUTES:
                first = route.dependant.dependencies[0].call
                assert first.sec01_action == UNMOUNTED_R67_ROUTES[(method, route.path)]
    get = next(r for r in offer_budget.router.routes if r.path == "/offer-budgets/{offer_id}"
               and "GET" in r.methods)
    assert getattr(get.endpoint, "sec02_strips_money", False)
    assert all(is_significant_action(a) for a in OFFER_WRITE_ACTIONS)     # denials audited
    holders = {rid for rid, acts in PERMISSION_MATRIX.items() if acts & OFFER_WRITE_ACTIONS}
    assert holders == {"owner", "admin", "accountant"}


# ═════════ FLOW Guard FG-472 (R67 + R20): the offer execution budget (cost / margin)
BUDGET_MONEY = ("sale_material_unit", "sale_labor_unit", "sale_total", "sale",
                "budget_material_unit_cost", "budget_labor_unit_cost", "budget_material_total",
                "budget_labor_total", "budget_total", "budget", "material_margin_percent",
                "labor_margin_percent", "margin_value", "margin_percent")


@pytest.fixture
def _with_budget_router(monkeypatch):
    real_app = T._app

    def app(mp, op, sysdb, mode_):
        a = real_app(mp, op, sysdb, mode_)
        from app.routes import offer_budget as ob
        mp.setattr(ob, "db", op, raising=False)
        a.include_router(ob.router, prefix="/api")
        return a
    monkeypatch.setattr(T, "_app", app)


def _budget_keys(payload) -> set:
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in BUDGET_MONEY:
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(payload)
    return found


BUDGET_BODY = {"lines": [{"line_id": "ln-b1", "budget_material_unit_cost": 30,
                          "budget_labor_unit_cost": 45, "material_margin_percent": 25,
                          "labor_margin_percent": 25, "planned_labor_hours": 3, "notes": "n"}]}


def test_09_fg472_only_finance_writes_the_offer_budget(monkeypatch, _with_budget_router, backend, mode):
    """FG-472: PUT /offer-budgets/{id} was open to every M2 role and wrote no AuditEvent.
    R67: Owner / Admin / Accountant only (403 before any read or write); each save writes
    one canonical AuditEvent with what changed."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("b1", status="Draft"))
        before = await T.snap(op, ("offer_line_budgets", "offers"))
        for who in FORBIDDEN:
            r = await c.put("/api/offer-budgets/b1", headers=T.hdr(who), json=BUDGET_BODY)
            assert r.status_code == 403, (who, r.text)
        assert await T.snap(op, ("offer_line_budgets", "offers")) == before
        for who in ALLOWED:
            r = await c.put("/api/offer-budgets/b1", headers=T.hdr(who), json=BUDGET_BODY)
            assert r.status_code == 200 and r.json()["saved"] == 1, (who, r.text)
        row = await op.offer_line_budgets.find_one({"offer_id": "b1", "line_id": "ln-b1"}, {"_id": 0})
        assert row["budget_material_unit_cost"] == 30 and row["updated_by"] == "acct-a"
        ev = await op.audit_events.find({"action": "offers.offer_budget.updated"}, {"_id": 0}).to_list(None)
        assert len(ev) == 3 and {e["actor_id"] for e in ev} == set(ALLOWED)
        assert ev[0]["entity_id"] == "b1" and ev[0]["source_flow"] == "FLOW-003"
        assert ev[0]["structured_diff"]["lines"][0]["line_id"] == "ln-b1"
    run(monkeypatch, backend, mode, scenario)


def test_10_fg472_the_budget_read_shows_no_money_to_a_non_finance_role(
        monkeypatch, _with_budget_router, backend, mode):
    """FG-472: GET /offer-budgets/{id} returned sale prices, budget costs and margin to every
    role. Non-finance: names, units, quantities, hours and notes only; finance: everything."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("b2", status="Draft"))
        await op.offer_line_budgets.insert_one({
            "org_id": ORG_A, "offer_id": "b2", "line_id": "ln-b2", "budget_material_unit_cost": 30,
            "budget_labor_unit_cost": 45, "material_margin_percent": 25, "labor_margin_percent": 25,
            "planned_labor_hours": 3, "notes": "n"})
        for who in FORBIDDEN:
            r = await c.get("/api/offer-budgets/b2", headers=T.hdr(who))
            assert r.status_code == 200, (who, r.text)
            assert _budget_keys(r.json()) == set(), (who, sorted(_budget_keys(r.json())))
            line = r.json()["lines"][0]
            assert line["activity_name"] == "Плочки" and line["qty"] == 10
            assert line["planned_labor_hours"] == 3
        for who in ALLOWED:
            r = await c.get("/api/offer-budgets/b2", headers=T.hdr(who))
            assert r.status_code == 200, r.text
            keys = _budget_keys(r.json())
            assert {"sale_total", "budget_total", "margin_value", "margin_percent"} <= keys, keys
            assert r.json()["totals"]["sale"] == 1000.0
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════ F-89-01 [P1] (Codex, PR #89): the review token is a bearer secret
#: The keys that carry the public review link (``/offers/review/{token}``): whoever holds
#: one sees the client prices (public GET) and can make the offer Accepted (public approve).
REVIEW_KEYS = ("review_token", "review_url")


@pytest.fixture
def _with_projects_router(monkeypatch):
    """The OFF-01 app + the projects router (the project dashboard lists the extra offers)."""
    real_app = T._app

    def app(mp, op, sysdb, mode_):
        a = real_app(mp, op, sysdb, mode_)
        from app.routes import projects as rp
        mp.setattr(rp, "db", op, raising=False)
        a.include_router(rp.router, prefix="/api")
        return a
    monkeypatch.setattr(T, "_app", app)


def _review_keys_in(payload) -> set:
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in REVIEW_KEYS:
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(payload)
    return found


async def _seed_review(op):
    """A Sent offer with a live review link (the main offer), its snapshot and an event, and
    a Sent EXTRA offer with its own link — the project dashboard lists the extra offers."""
    await op.offers.insert_one(offer_doc("rt1", token=TOKEN, review_token_version=1,
                                         review_token_status="active"))
    await op.offers.insert_one(offer_doc("rt-extra", token="tkx" + "e" * 21, offer_type="extra",
                                         offer_no="OFF-0002", review_token_version=1))
    await op.offer_versions.insert_one({
        "id": "ov-rt1", "org_id": ORG_A, "project_id": PRJ_A, "offer_id": "rt1",
        "version_number": 1, "created_at": "2026-11-02T10:00:00+00:00", "created_by": "admin-a",
        "note": "Автоматичен snapshot при изпращане", "is_auto_backup": True,
        "snapshot_json": {"offer_no": "OFF-0001", "status": "Sent", "version": 1, "lines": []}})
    await op.offer_events.insert_one({
        "id": "oe-rt1", "org_id": ORG_A, "offer_id": "rt1", "event_type": "sent",
        "actor": "admin-a@off01.example", "created_at": "2026-11-02T10:00:00+00:00",
        "details": {"sent_by": "admin-a"}})


def _staff_surfaces():
    """Every internal GET that answers with an offer (whole, in a list, nested in a version,
    a history or the project dashboard)."""
    return {
        "single": "/api/offers/rt1",
        "list": "/api/offers",
        "list_project": "/api/offers?project_id=%s" % PRJ_A,
        "list_sent": "/api/offers?status=Sent",
        "versions": "/api/offers/rt1/versions",
        "version_1": "/api/offers/rt1/versions/1",
        "events": "/api/offers/rt1/events",
        "dashboard": "/api/projects/%s/dashboard" % PRJ_A,
    }


def test_11_f89_01_no_internal_response_gives_staff_the_review_link(
        monkeypatch, _with_projects_router, backend, mode):
    """F-89-01: GET /offers/{id} (quantity-only after the SEC-02 strip) still carried
    ``review_token``. A SiteManager read it, opened the public review (prices — R20) and
    approved it (Accepted — R67). Now no internal response of a non-finance caller carries the
    token or a review URL, in any surface; the chain "internal response → public read →
    approve" cannot be started; finance keeps the link; the client's link still works."""
    secrets = (TOKEN, "tkx" + "e" * 21)

    async def scenario(c, op):
        await _seed_review(op)
        leaks = {}
        for who in FORBIDDEN:
            for name, url in _staff_surfaces().items():
                r = await c.get(url, headers=T.hdr(who, key=False))
                if r.status_code != 200:
                    continue                 # refused: nothing handed out
                bad = sorted(_review_keys_in(r.json())) + [s for s in secrets if s in r.text]
                bad += ["/offers/review/"] if "/offers/review/" in r.text else []
                if bad:
                    leaks["%s %s" % (who, name)] = bad
        assert leaks == {}, leaks
        # the reads did answer the SiteManager (the surfaces were really exercised)
        for name in ("single", "list_project", "versions", "events"):
            r = await c.get(_staff_surfaces()[name], headers=T.hdr("site-a", key=False))
            assert r.status_code == 200, (name, r.status_code, r.text[:200])
        assert (await get(op, "rt1"))["status"] == "Sent"
        # finance keeps the link where it is shown today (the offer editor, the send answer)
        for who in ALLOWED:
            r = await c.get("/api/offers/rt1", headers=T.hdr(who, key=False))
            assert r.status_code == 200 and r.json()["review_token"] == TOKEN, (who, r.text[:200])
        # the client's link still works end to end
        r = await c.get("/api/offers/review/%s" % TOKEN)
        assert r.status_code == 200, r.text[:200]
        r = await T.respond(c, TOKEN)
        assert r.status_code == 200, r.text[:300]
        assert (await get(op, "rt1"))["status"] == "Accepted"
    run(monkeypatch, backend, mode, scenario)


def test_12_f89_01_the_send_answer_keeps_the_link_only_for_finance(monkeypatch, backend, mode):
    """The send answer is the one place the link is handed out: finance gets ``review_url``
    and the token; the strip (defence in depth: an enforce assignment that grants the send
    without finance.money_values.read) removes both."""
    import app.permissions.money_write as mw

    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("sd1", status="Draft"))
        r = await c.post("/api/offers/sd1/send", headers=T.hdr("acct-a"))
        assert r.status_code == 200, r.text[:300]
        token = r.json()["review_token"]
        assert r.json()["review_url"] == "/offers/review/%s" % token
        await op.offers.insert_one(offer_doc("sd2", status="Draft"))

        async def no_finance_read(request, user):
            return False
        monkeypatch.setattr(mw, "money_values_visible", no_finance_read)
        r = await c.post("/api/offers/sd2/send", headers=T.hdr("admin-a"))
        assert r.status_code == 200, r.text[:300]
        stored = (await get(op, "sd2"))["review_token"]
        assert _review_keys_in(r.json()) == set() and stored not in r.text, r.text[:300]
        assert r.json()["status"] == "Sent"
    run(monkeypatch, backend, mode, scenario)

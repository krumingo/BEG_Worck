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
    """The OFF-01 app + the extra-works router (create-offer, smr-to-offer)."""
    real_app = T._app

    def app(mp, op, sysdb, mode_):
        a = real_app(mp, op, sysdb, mode_)
        from app.routes import extra_works as ew
        mp.setattr(ew, "db", op, raising=False)
        a.include_router(ew.router, prefix="/api")
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


def test_01_site_manager_gets_no_money_from_any_offer_write(monkeypatch, backend, mode):
    """FG-350: every write a SiteManager may call answers WITHOUT prices or totals."""
    async def scenario(c, op):
        out = await _calls(c, op, "site-a")
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

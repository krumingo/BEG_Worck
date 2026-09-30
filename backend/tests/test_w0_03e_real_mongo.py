"""
W0-03E against a REAL, disposable, local MongoDB.

Skipped unless ``W0_03_REAL_MONGO_URL`` names a plain local server — the same
local-only guard as test_w0_03c_real_mongo.py (no Atlas, no NAS, no
``mongodb+srv``); each test works in its own ``w003c_realmongo_<random>``
database and drops exactly that database afterwards::

    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27017 pytest tests/test_w0_03e_real_mongo.py -v --noconftest

What only a server can prove:

  * the dry run leaves the database byte-for-byte unchanged (``dbHash``);
  * a real run never changes a legacy collection (``dbHash`` of exactly those);
  * ``$addToSet``/``$pull`` of dict entries, the ``_id`` duplicate handling and
    the lock upsert race behave as the double assumes;
  * concurrent requests: one run, never two; an interrupted run resumes;
  * the audit hash chain stays valid across refusal, run, resume and rollback.
Approval comes from the test-only verifier; the build has none that approves.
"""
import asyncio

import pytest

from app.audit.store import AUDIT_COLLECTION, verify_chain
from app.master_data import legacy_adapter as la
from app.master_data import legacy_migration as lm
from app.master_data import legacy_plan as lp
from app.master_data import models
from app.master_data.deps import MODE_ENFORCE
from app.master_data.merge import MasterDataApprovalRequired
from app.master_data.models import build_entity, new_identifier

from tests.test_w0_03c_real_mongo import _refusal, scratch
from tests.test_w0_03d_merge_redirect import TrustedTestVerifier
from tests.test_w0_03e_legacy_migration import (
    LEGACY, NOW, ORG_A, ORG_B, T_A, T_B, Ctx, dry, go, reference_docs, repo, seed,
)

pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


async def prepare(db):
    await seed(db)
    m = build_entity(tenant_id=T_A, entity_type=models.ENTITY_ORGANIZATION,
                     display_name="Монтаж АД", entity_id="org-existing", now=NOW)
    m["identifiers"] = [new_identifier(models.ENTITY_ORGANIZATION, "eik", "987654321")]
    await db["md_organization"].insert_one(m)


async def db_hash(db, collections=None):
    cmd = {"dbHash": 1}
    if collections:
        cmd["collections"] = collections
    out = await db.command(cmd)
    return out["md5"], out.get("collections")


async def events(db, tenant=T_A):
    return await db[AUDIT_COLLECTION].find({"tenant_id": tenant}, {"_id": 0}).sort(
        "sequence", 1).to_list(None)


def test_dry_run_and_refusal_leave_the_server_unchanged():
    async def body(db, _name):
        await prepare(db)
        before = await db_hash(db)
        first = await dry(db)
        assert await dry(db) == first
        assert await db_hash(db) == before
        with pytest.raises(MasterDataApprovalRequired):
            await go(db, first["plan_token"], verifier=None)
        # the only new document is the refusal's AuditEvent
        names = set(await db.list_collection_names())
        assert AUDIT_COLLECTION in names
        assert await db[lp.REFS_COLLECTION].count_documents({}) == 0
        assert await db[lm.RUNS_COLLECTION].count_documents({}) == 0
        assert (await events(db))[-1]["error_code"] == "APPROVAL_REQUIRED"
    scratch(body)


def test_run_resume_reconcile_and_rollback_on_a_real_server():
    async def body(db, _name):
        await prepare(db)
        legacy = LEGACY + list(reference_docs(ORG_A))
        legacy_before = await db_hash(db, legacy)
        p = await dry(db)
        with pytest.raises(lm._Interrupted):
            await go(db, p["plan_token"], batch_size=4, _fail_after="batch:1")
        with pytest.raises((lm.MigrationBusy, lm.MigrationStalePlan)):
            await go(db, p["plan_token"], key="intruder", batch_size=4)
        out = await go(db, p["plan_token"], batch_size=4)
        assert out.performed and out.resumed
        assert await db_hash(db, legacy) == legacy_before
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["zero_lost"] and report["counts"]["unmigrated"] == 0
        assert await db[lp.REFS_COLLECTION].count_documents({}) == len(p["items"])
        c1 = await la.resolve_legacy(Ctx(db), collection="counterparties", legacy_id="cp1",
                                     mode=MODE_ENFORCE, repository=repo(db))
        assert sorted(i["kind"] for i in c1["entity"]["identifiers"]) == ["eik", "vat"]
        ok, why = verify_chain(await events(db))
        assert ok, why

        prev = await lm.preview_rollback(Ctx(db), run_id=out.run_id, mode=MODE_ENFORCE,
                                         repository=repo(db))
        done = await lm.rollback(Ctx(db), run_id=out.run_id, preview_token=prev["preview_token"],
                                 idempotency_key="rb", reason="real-mongo check", confirmation=True,
                                 approval_id="APR-rb", mode=MODE_ENFORCE, repository=repo(db),
                                 approval_verifier=TrustedTestVerifier())
        assert done.performed
        existing = await db["md_organization"].find_one({"id": "org-existing"})
        assert existing["legacy_refs"] == []                         # $pull of the run's entry
        assert await db["md_person"].count_documents({"status": "active"}) == 0
        assert await db_hash(db, legacy) == legacy_before
        ok, why = verify_chain(await events(db))
        assert ok, why
    scratch(body)


def test_concurrent_requests_produce_one_run():
    async def body(db, _name):
        await prepare(db)
        p = await dry(db)
        results = await asyncio.gather(*[go(db, p["plan_token"], key="same") for _ in range(4)]
                                       + [go(db, p["plan_token"], key="other-%d" % i) for i in range(3)],
                                       return_exceptions=True)
        performed = [r for r in results if not isinstance(r, Exception) and r.performed]
        refused = [r for r in results if isinstance(r, Exception)]
        assert len(performed) == 1, results
        assert all(isinstance(r, (lm.MigrationBusy, lm.MigrationStalePlan)) for r in refused), refused
        assert await db[lm.RUNS_COLLECTION].count_documents({}) == 1
        assert await db[lp.REFS_COLLECTION].count_documents({}) == len(p["items"])
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["zero_lost"]
        completed = [e for e in await events(db)
                     if e["action"] == "master_data.legacy_migration.completed"]
        assert len(completed) == 1
    scratch(body)


def test_two_orgs_in_one_legacy_database_stay_apart():
    async def body(db, _name):
        await prepare(db)
        await seed(db, ORG_B)
        a = await go(db, (await dry(db))["plan_token"])
        b_ctx = Ctx(db, tenant_id=T_B, org_id=ORG_B, user_id="owner-b")
        b = await go(db, (await dry(db, ctx=b_ctx))["plan_token"], ctx=b_ctx)
        assert a.performed and b.performed
        for ctx, tenant in ((Ctx(db), T_A), (b_ctx, T_B)):
            r = await la.resolve_legacy(ctx, collection="companies", legacy_id="c1",
                                        mode=MODE_ENFORCE, repository=repo(db, tenant))
            assert r["entity"]["tenant_id"] == tenant
            assert all(e["org_id"] == ctx.org_id for e in r["entity"]["legacy_refs"])
            report = await lm.reconcile(ctx, mode=MODE_ENFORCE, repository=repo(db, tenant))
            assert report["zero_lost"]
        with pytest.raises(la.LegacyOrgMismatch):
            await la.resolve_legacy(Ctx(db), collection="companies", legacy_id="c1", org_id=ORG_B,
                                    mode=MODE_ENFORCE, repository=repo(db))
        for tenant in (T_A, T_B):
            ok, why = verify_chain(await events(db, tenant))
            assert ok, why
    scratch(body)


def test_the_restored_copy_report_script_is_read_only(tmp_path):
    from scripts import w0_03e_legacy_migration_report as script
    from tests.test_w0_03c_real_mongo import REAL_URL

    async def body(db, name):
        await prepare(db)
        before = await db_hash(db)
        report = await script.build_report(db, T_A, ORG_A)
        assert await db_hash(db) == before
        assert report["read_only"] and report["advances"]["auto_mapped"] == 0
        assert report["plan"]["plan_token"] == (await dry(db))["plan_token"]
        out = tmp_path / "r.json"
        assert await asyncio.to_thread(script.main, [
            "--mongo-url", REAL_URL, "--db", name, "--tenant-id", T_A, "--org-id", ORG_A,
            "--out", str(out)]) == 0
        assert await db_hash(db) == before and out.exists()
        with pytest.raises(PermissionError):
            await script.ReadOnlyDb(db)["users"].insert_one({"id": "x"})
    scratch(body)
    assert script.main(["--mongo-url", "mongodb+srv://x.mongodb.net", "--db", "d",
                        "--tenant-id", "t", "--org-id", "o"]) == 2


def test_c02_recipient_identity_and_report_refs_on_a_real_server(monkeypatch):
    from fastapi import HTTPException
    from app.master_data.deps import ENV_MODE
    monkeypatch.setenv(ENV_MODE, "enforce")

    async def body(db, _name):
        await prepare(db)
        await go(db, (await dry(db))["plan_token"])
        ctx = Ctx(db)

        async def resolved(user):
            return ctx
        monkeypatch.setattr(la, "context_for", resolved)
        user = {"id": "owner-1", "org_id": ORG_A}
        u1 = (await la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode=MODE_ENFORCE,
                                      repository=repo(db)))["canonical_id"]
        for kw, code in ((dict(user_id="u2", person_id=u1), la.REASON_ADVANCE_UNMAPPED),
                         (dict(person_id=u1, guest_name="Друг човек"), la.REASON_ADVANCE_NAME_CONFLICT)):
            with pytest.raises(HTTPException) as info:
                await la.advance_master_person(user, **dict(dict(person_id=None, user_id=None,
                                                                 guest_name=None), **kw))
            assert info.value.detail["error_code"] == code
        ok = await la.advance_master_person(user, person_id=u1, user_id="u1",
                                            guest_name="Иван Петров")
        assert ok["master_person_id"] == u1
        rows = [{"supplier_id": "cp1"}, {"supplier_id": "cp3"}]
        await la.annotate_refs(user, rows, {"supplier_id": "counterparties"})
        assert rows[0]["supplier_master_ref"]["status"] == "mapped"
        assert rows[1]["supplier_master_ref"]["status"] == "pending"
        denials = [e for e in await events(db) if e["action"] == "master_data.advance.create_refused"]
        assert len(denials) == 2
        ok_chain, why = verify_chain(await events(db))
        assert ok_chain, why
    scratch(body)


def test_c03_reports_imports_and_adapters_are_tenant_isolated_on_a_real_server(monkeypatch):
    """The reproduced C02 leak, on the server that reproduced it: the actual
    route pipelines run against MongoDB, with tenant B holding the same ids."""
    from app.master_data.deps import ENV_MODE
    from app.routes import hr, projects, reports
    from tests.test_w0_03e_c03_isolation import ADMIN, _world, assert_no_b, b_canonical_ids_async

    async def body(db, _name):
        await _world(db)
        for module in (reports, hr, projects):
            monkeypatch.setattr(module, "db", db)
        b_ids = await b_canonical_ids_async(db)
        user = dict(ADMIN)
        for mode in ("off", "shadow", "enforce"):
            monkeypatch.setenv(ENV_MODE, mode)
            if mode == "enforce":
                ctx = Ctx(db)

                async def resolved(u):
                    return ctx
                monkeypatch.setattr(la, "context_for", resolved)
            prices = await reports.get_price_history(
                user=user, page=1, page_size=20, sort_by="created_at", sort_dir="desc", search=None,
                item_id=None, supplier_id=None, project_id=None, warehouse_id=None, date_from=None,
                date_to=None)
            rows = {r["line_id"]: r for r in prices["items"]}
            assert rows["line-a"]["invoice_no"] == "A-INV-1"
            assert "invoice_no" not in rows["line-a2"]
            filtered = await reports.get_price_history(
                user=user, page=1, page_size=20, sort_by="created_at", sort_dir="desc", search=None,
                item_id=None, supplier_id="cp-b-hidden-supplier", project_id=None, warehouse_id=None,
                date_from=None, date_to=None)
            assert filtered["items"] == [] and filtered["total"] == 0
            turnover = await reports.get_turnover_by_counterparty(
                user=user, page=1, page_size=20, sort_by="sum_total", sort_dir="desc",
                counterparty_id=None, date_from=None, date_to=None, type="purchases")
            assert turnover["grand_totals"]["total_amount"] == 10
            drill = await reports.get_counterparty_invoices(
                counterparty_id="cp1", user=user, page=1, page_size=20, date_from=None,
                date_to=None, type="all")
            clients = await reports.get_turnover_by_client(
                user=user, page=1, page_size=20, sort_by="sum_total", sort_dir="desc",
                client_id=None, date_from=None, date_to=None)
            advances = await hr.list_advances(user=user, user_id=None, status=None)
            assert [a["user_name"] for a in advances if a["id"] == "adv-foreign-user"] == ["Unknown"]
            imported = await projects.import_client_invoice(project_id="pr-x", user=user)
            assert imported["invoice_details"]["company_name"] == "А Клиент ООД"
            for payload in (prices, filtered, turnover, drill, clients, advances, imported):
                assert_no_b(None, payload, b_ids=b_ids)
            if mode == "enforce":
                assert rows["line-a"]["supplier_master_ref"]["status"] == "mapped"
        # the database proves the scoping did not cross in either direction
        theirs = await db["projects"].find_one({"id": "pr-x", "org_id": ORG_B})
        assert "invoice_details" not in theirs
    scratch(body)


def test_c03_pending_mapping_decision_stays_inside_the_tenant_on_a_real_server():
    async def body(db, _name):
        from tests.test_w0_03e_c03_isolation import _world, assert_no_b, b_canonical_ids_async
        await _world(db)
        ctx = Ctx(db, user_id="office-1")
        b_ids = await b_canonical_ids_async(db)
        u3 = (await la.resolve_legacy(ctx, collection="users", legacy_id="u3", mode=MODE_ENFORCE,
                                      repository=repo(db)))["canonical_id"]
        out = await lm.resolve_mapping(ctx, collection="users", legacy_id="u2", decision="map",
                                       canonical_entity_id=u3, idempotency_key="d1",
                                       confirmation=True, approval_id="APR-d1", mode=MODE_ENFORCE,
                                       repository=repo(db), approval_verifier=TrustedTestVerifier())
        assert out.performed and out.entity_id == u3
        # tenant B's identical legacy id stays pending in B, untouched by A's decision
        b_row = await db[lp.REFS_COLLECTION].find_one({"_id": lp.ref_row_id(T_B, "users", "u2")})
        assert b_row["status"] == "pending" and b_row["entity_id"] is None
        # a B Master cannot be the target of A's decision
        b_person = await db["md_person"].find_one({"tenant_id": T_B, "status": "active"})
        with pytest.raises(lm.MasterDataRefused):
            await lm.resolve_mapping(ctx, collection="persons", legacy_id="p1", decision="map",
                                     canonical_entity_id=b_person["id"], idempotency_key="d2",
                                     confirmation=True, approval_id="APR-d2", mode=MODE_ENFORCE,
                                     repository=repo(db), approval_verifier=TrustedTestVerifier())
        # ...and the refusal says exactly what it says for an id that exists nowhere:
        # A learns nothing about B (no existence oracle)
        with pytest.raises(lm.MasterDataRefused) as ghost:
            await lm.resolve_mapping(ctx, collection="persons", legacy_id="p1", decision="map",
                                     canonical_entity_id="no-such-person", idempotency_key="d3",
                                     confirmation=True, approval_id="APR-d3", mode=MODE_ENFORCE,
                                     repository=repo(db), approval_verifier=TrustedTestVerifier())
        refusals = [e for e in await events(db, T_A)
                    if e["action"] == "master_data.legacy_mapping.resolve_refused"]
        assert [r["reason"].replace(b_person["id"], "X") for r in refusals[:1]] == [
            str(ghost.value).replace("no-such-person", "X")]
        for tenant in (T_A, T_B):
            ok, why = verify_chain(await events(db, tenant))
            assert ok, why
        # the only B id in A's audit is the one A's caller itself submitted
        assert_no_b(None, await events(db, T_A), b_ids=b_ids - {b_person["id"]})
    scratch(body)

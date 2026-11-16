"""
FIX-ADV-01 — ``POST /api/advances`` is idempotent and writes its money through MoneyWrite.

Defect on de720f94: ``create_advance`` (``app/routes/hr.py``) ignored the ``Idempotency-Key``
header; the same key sent 3 times created 3 ``advances`` rows and 3 ``finance_payments``
Outflow rows (CLAUDE.md §14: an idempotency key on every consequential write; §2.5 / FLOW-006:
one Payment ledger, a retry is not a second payment). Fix: the SUB-ADV-01 pattern
(``app/routes/subcontractors.py`` ``create_subcontractor_advance``): ``MoneyWrite.begin`` ->
key-derived ids -> ``insert_once(mw.unique(doc))`` -> ``mw.step("audit", ...)`` -> replay.
No business rule changes: the permission check (``payroll_permission``), the Master Person
logic, the response shape and the audit action ``advance_created`` stay.

Rules under test, in off, shadow and enforce, on a real MongoDB replica set (ST-01 tenants):
  same key   one key x3 -> 201 x3, 1 advance, 1 finance_payments row, 1 audit row, identical
             bodies; 4 concurrent requests with one key -> still 1 advance and 1 payment;
             same key + different body -> 409 IDEMPOTENCY_CONFLICT, nothing written.
  new keys   two keys -> 2 advances, 2 payments (no double-click heuristics).
  no key     -> 428 IDEMPOTENCY_KEY_REQUIRED, nothing written (R29, Krum 06.11.2026), with
             and without ``account_id``; a blank key too.
  forbidden  Viewer, Technician, SiteManager, Driver -> 403 and nothing written.
  scope      the same key by another user of the tenant, or by a user of tenant B -> a new
             advance of its own (never a replay of someone else's response).

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27021/?directConnection=true&replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_fix_adv_01_advance_idempotency.py -v --noconftest -p no:cacheprovider
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MODES = ("off", "shadow", "enforce")
DB_PREFIX = "fixtest_adv_"
SYNTH_PASSWORD = "FixAdv-Synthetic-Pass-2026!"   # synthetic users of a scratch database
ROLES = ("owner", "accountant", "admin", "requester", "technician", "viewer", "driver")
FORBIDDEN = ("viewer", "technician", "requester", "driver")


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "fixadv_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════════════════════════════════════ the harness
def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX) and sys_name.startswith(DB_PREFIX)
    pm = _pm01()
    import server
    import httpx
    from fastapi.testclient import TestClient

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"],
                            "users": {u["key"]: u for u in t["users"]}}
        for tk in ("A", "B"):
            doc = {"id": "fixadv-%s-cash" % tk, "org_id": fx[tk]["tenant_id"],
                   "name": "Каса %s" % tk, "type": "cash", "account_type": "Cash"}
            tc.portal.call(lambda: op_db.financial_accounts.insert_one(dict(doc)))
        for name in ("audit_idempotency", "audit_logs"):
            if name not in tc.portal.call(lambda: op_db.list_collection_names()):
                tc.portal.call(lambda: op_db.create_collection(name))
        # The W0-04 unique indexes of the key registry, as in a bootstrapped tenant.
        tc.portal.call(lambda: op_db.audit_idempotency.create_index([("id", 1)], unique=True))
        tc.portal.call(lambda: op_db.audit_idempotency.create_index(
            [("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))

        tokens: Dict[str, str] = {}
        for tk in ("A", "B"):
            for role in ROLES:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tk]["users"][role]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tk, role, r.status_code, r.text[:200])
                tokens[tk + ":" + role] = r.json()["token"]

        def body_for(tk: str, amount: float = 100) -> Dict[str, Any]:
            return {"user_id": fx[tk]["users"]["technician"]["id"], "type": "Advance",
                    "amount": amount, "account_id": "fixadv-%s-cash" % tk,
                    "issued_date": "2026-11-16", "note": "FIX-ADV-01"}

        def counts(tk: str = "A") -> Dict[str, int]:
            org = fx[tk]["tenant_id"]
            return {
                "advances": tc.portal.call(lambda: op_db.advances.count_documents({"org_id": org})),
                "payments": tc.portal.call(lambda: op_db.finance_payments.count_documents(
                    {"org_id": org, "direction": "Outflow"})),
                "audit": tc.portal.call(lambda: op_db.audit_logs.count_documents(
                    {"org_id": org, "action": "advance_created"})),
            }

        def delta(after: Dict[str, int], before: Dict[str, int]) -> Dict[str, int]:
            return {k: after[k] - before[k] for k in after}

        def post(who: str, body: Dict[str, Any], key: Optional[str]) -> Dict[str, Any]:
            headers = {"Authorization": "Bearer " + tokens[who]}
            if key is not None:
                headers["Idempotency-Key"] = key
            resp = tc.post("/api/advances", json=body, headers=headers)
            try:
                payload = resp.json()
            except Exception:                                     # noqa: BLE001
                payload = resp.text[:300]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return {"status": resp.status_code, "body": payload,
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None}

        out: Dict[str, Any] = {"modes": {}}
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            m: Dict[str, Any] = {}

            # ── one key x3 -> one advance, one payment, identical responses
            key = "fixadv-" + uuid.uuid4().hex
            c0 = counts()
            same = [post("A:accountant", body_for("A"), key) for _ in range(3)]
            m["same_key"] = {"statuses": [r["status"] for r in same],
                             "bodies_identical": all(r["body"] == same[0]["body"] for r in same),
                             "advance_id": (same[0]["body"] or {}).get("id"),
                             "payment_id": (same[0]["body"] or {}).get("payment_id"),
                             "delta": delta(counts(), c0)}
            adv_id = m["same_key"]["advance_id"]
            pay_id = m["same_key"]["payment_id"]
            m["same_key"]["payment_rows_for_advance"] = tc.portal.call(
                lambda: op_db.finance_payments.count_documents({"id": pay_id})) if pay_id else 0
            m["same_key"]["advance_payment_link"] = bool(adv_id and tc.portal.call(
                lambda: op_db.advances.count_documents({"id": adv_id, "payment_id": pay_id})))

            # ── same key, different body -> 409, nothing written
            c0 = counts()
            conflict = post("A:accountant", body_for("A", 250), key)
            m["same_key_other_body"] = {"status": conflict["status"],
                                        "error_code": conflict["error_code"],
                                        "delta": delta(counts(), c0)}

            # ── 4 concurrent requests with one key
            ckey = "fixadv-" + uuid.uuid4().hex
            hdr = {"Authorization": "Bearer " + tokens["A:accountant"], "Idempotency-Key": ckey}
            c0 = counts()

            async def burst():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post("/api/advances", json=body_for("A"),
                                                          headers=hdr) for _ in range(4)])
            rs = tc.portal.call(burst)
            m["concurrent_same_key"] = {"statuses": sorted(r.status_code for r in rs),
                                        "delta": delta(counts(), c0)}

            # ── different keys -> two advances
            c0 = counts()
            two = [post("A:accountant", body_for("A"), "fixadv-" + uuid.uuid4().hex)
                   for _ in range(2)]
            m["different_keys"] = {"statuses": [r["status"] for r in two],
                                   "distinct_ids": len({(r["body"] or {}).get("id") for r in two}),
                                   "delta": delta(counts(), c0)}

            # ── no key -> 428, nothing written (R29), with and without a ledger account
            m["no_key"] = {}
            no_account = {k: v for k, v in body_for("A").items() if k != "account_id"}
            for case, body, nkey in (("with_account", body_for("A"), None),
                                    ("without_account", no_account, None),
                                    ("blank_key", body_for("A"), "   ")):
                c0 = counts()
                nok = post("A:accountant", body, nkey)
                m["no_key"][case] = {"status": nok["status"], "error_code": nok["error_code"],
                                     "delta": delta(counts(), c0)}

            # ── forbidden roles (with a key) -> 403, nothing written
            m["forbidden"] = {}
            for role in FORBIDDEN:
                c0 = counts()
                r = post("A:" + role, body_for("A"), "fixadv-" + uuid.uuid4().hex)
                m["forbidden"][role] = {"status": r["status"], "delta": delta(counts(), c0)}

            # ── the same key by another user of A, and by a user of tenant B
            c0, b0 = counts(), counts("B")
            other_user = post("A:owner", body_for("A"), key)
            other_tenant = post("B:owner", body_for("B"), key)
            m["key_scope"] = {
                "other_user": {"status": other_user["status"],
                               "new_id": (other_user["body"] or {}).get("id") not in (None, adv_id)},
                "other_tenant": {"status": other_tenant["status"],
                                 "new_id": (other_tenant["body"] or {}).get("id")
                                 not in (None, adv_id),
                                 "org": (other_tenant["body"] or {}).get("org_id")
                                 == fx["B"]["tenant_id"]},
                "delta_A": delta(counts(), c0), "delta_B": delta(counts("B"), b0)}
            out["modes"][mode] = m
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
    return out


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX + "op_" + suffix, DB_PREFIX + "sys_" + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "fixadv-local-" + uuid.uuid4().hex
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child",
           "--mongo-url", mongo_url, "--out-json", str(out_json)]
    try:
        subprocess.run(cmd, cwd=str(BACKEND), timeout=timeout, check=True, env=env)
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        for name in (op_name, sys_name):
            assert name.startswith(DB_PREFIX)
            c.drop_database(name)
        c.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="FIX-ADV-01 advance idempotency")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _pm01()._check_local(args.mongo_url)
    if args.child:
        run_harness(args.mongo_url, Path(args.out_json))
    else:
        run_in_child(args.mongo_url, Path(args.out_json))
    return 0


# ═══════════════════════════════════════════════════════════════════ rule assertions
ONE = {"advances": 1, "payments": 1, "audit": 1}
NONE = {"advances": 0, "payments": 0, "audit": 0}


def check_result(result: Dict[str, Any]) -> None:
    assert set(result["modes"]) == set(MODES)
    for mode, m in result["modes"].items():
        s = m["same_key"]
        assert s["statuses"] == [201, 201, 201], (mode, s)
        assert s["delta"] == ONE, (mode, s)                         # the defect: was 3/3/3
        assert s["bodies_identical"], (mode, s)
        assert s["payment_id"] and s["payment_rows_for_advance"] == 1, (mode, s)
        assert s["advance_payment_link"], (mode, s)
        c = m["same_key_other_body"]
        assert (c["status"], c["error_code"], c["delta"]) == (409, "IDEMPOTENCY_CONFLICT",
                                                              NONE), (mode, c)
        cc = m["concurrent_same_key"]
        assert cc["delta"] == ONE, (mode, cc)
        assert 201 in cc["statuses"] and set(cc["statuses"]) <= {201, 409}, (mode, cc)
        d = m["different_keys"]
        assert d["statuses"] == [201, 201] and d["distinct_ids"] == 2, (mode, d)
        assert d["delta"] == {"advances": 2, "payments": 2, "audit": 2}, (mode, d)
        assert set(m["no_key"]) == {"with_account", "without_account", "blank_key"}
        for case, n in m["no_key"].items():
            assert (n["status"], n["error_code"], n["delta"]) == (
                428, "IDEMPOTENCY_KEY_REQUIRED", NONE), (mode, case, n)
        for role, f in m["forbidden"].items():
            assert (f["status"], f["delta"]) == (403, NONE), (mode, role, f)
        k = m["key_scope"]
        assert k["other_user"] == {"status": 201, "new_id": True}, (mode, k)
        assert k["other_tenant"] == {"status": 201, "new_id": True, "org": True}, (mode, k)
        assert k["delta_A"] == ONE and k["delta_B"] == ONE, (mode, k)


# ═══════════════════════════════════════════════════════════════════ static checks
def test_the_route_takes_the_key_and_keeps_its_permission_check():
    import server
    from app.routes import hr
    route = next(r for r in server.app.routes
                 if getattr(r, "path", None) == "/api/advances" and "POST" in r.methods)
    assert "idempotency_key" in inspect.signature(route.endpoint).parameters
    src = inspect.getsource(hr.create_advance)
    assert src.index("payroll_permission(user)") < src.index("MoneyWrite.begin(")
    assert src.index("advance_master_person(") < src.index("MoneyWrite.begin(")
    assert "mw.unique(" in src and "insert_once()" in src
    assert '"advance_created"' in src and "entry_id=mw.new_id(" in src
    assert "uuid.uuid4()" not in src                     # every id comes from mw.new_id


# ═══════════════════════════════════════════════════════════════════ real MongoDB run
def _real_refusal() -> str:
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if not url:
        return "W0_03_REAL_MONGO_URL not set"
    try:
        import pymongo
        c = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
        c.admin.command("hello")
        c.close()
    except Exception as exc:                                  # noqa: BLE001
        return "MongoDB not reachable: %s" % exc
    return ""


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_a_fresh_real_mongo_run_follows_the_rules_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    check_result(json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    sys.exit(main())

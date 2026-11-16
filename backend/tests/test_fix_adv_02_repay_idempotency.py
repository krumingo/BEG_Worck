"""
FIX-ADV-02 — ``POST /api/advances/{id}/repay`` and ``/apply-deduction`` follow R29.

Defect on f3246b0c: ``repay_advance`` (``app/routes/hr.py``) took no ``Idempotency-Key``: the
same repayment sent 3 times wrote 3 ``finance_payments`` Inflow rows, 3 ``repayments`` entries
and decremented ``remaining_amount`` 3 times (CLAUDE.md §14; §2.5 / FLOW-006: a retry is not
a second payment), and a request without a key was accepted. R29 (Krum 06.11.2026): a money
write without a key -> 428 IDEMPOTENCY_KEY_REQUIRED; same key -> replay; same key + different
body -> 409. ``apply_advance_deduction`` (a balance reduction) had the same defect.

Rules under test, in off, shadow and enforce, on a real MongoDB replica set (ST-01 tenants):
  same key    one key x3 -> 200 x3, ONE repayment entry, remaining reduced once, ONE Inflow;
              4 concurrent requests with one key -> still once;
              same key + different amount -> 409 IDEMPOTENCY_CONFLICT, nothing written.
  no key      -> 428 IDEMPOTENCY_KEY_REQUIRED, nothing written (missing and blank key).
  over-repay  an amount above the remaining balance is capped at it (the existing rule):
              remaining 0, Closed, the Inflow = the remaining balance; a further repayment of
              the closed advance -> 400, nothing written; a retry of the closing key -> replay.
  race        4 concurrent repayments under DIFFERENT keys -> the balance never goes below 0
              and every applied entry has exactly one Inflow (no lost update).
  forbidden   Viewer, Technician, SiteManager, Driver -> 403 and nothing written.
  tenant      a user of tenant B repaying A's advance -> 404, nothing written in A or B.
  deduction   ``apply-deduction``: one key x3 -> reduced once; no key -> 428.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27141/?directConnection=true&replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_fix_adv_02_repay_idempotency.py -v --noconftest -p no:cacheprovider
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
DB_PREFIX = "fixtest_adv2_"
SYNTH_PASSWORD = "FixAdv2-Synthetic-Pass-2026!"   # synthetic users of a scratch database
ROLES = ("owner", "accountant", "admin", "requester", "technician", "viewer", "driver")
FORBIDDEN = ("viewer", "technician", "requester", "driver")


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "fixadv2_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
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
            doc = {"id": "fixadv2-%s-cash" % tk, "org_id": fx[tk]["tenant_id"],
                   "name": "Каса %s" % tk, "type": "cash", "account_type": "Cash"}
            tc.portal.call(lambda: op_db.financial_accounts.insert_one(dict(doc)))
        for name in ("audit_idempotency", "audit_logs"):
            if name not in tc.portal.call(lambda: op_db.list_collection_names()):
                tc.portal.call(lambda: op_db.create_collection(name))
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

        def call(who: str, path: str, key: Optional[str], json_body=None) -> Dict[str, Any]:
            headers = {"Authorization": "Bearer " + tokens[who]}
            if key is not None:
                headers["Idempotency-Key"] = key
            resp = tc.post(path, json=json_body, headers=headers)
            try:
                payload = resp.json()
            except Exception:                                     # noqa: BLE001
                payload = resp.text[:300]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return {"status": resp.status_code, "body": payload,
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None}

        def new_loan(tk: str = "A", amount: float = 100) -> str:
            r = call(tk + ":accountant", "/api/advances", "fixadv2-create-" + uuid.uuid4().hex, {
                "user_id": fx[tk]["users"]["technician"]["id"], "type": "Loan",
                "amount": amount, "account_id": "fixadv2-%s-cash" % tk,
                "issued_date": "2026-11-16", "note": "FIX-ADV-02"})
            assert r["status"] == 201, r
            return r["body"]["id"]

        def repay(who: str, adv: str, amount, key: Optional[str]) -> Dict[str, Any]:
            return call(who, "/api/advances/%s/repay?amount=%s" % (adv, amount), key)

        def state(adv: str, tk: str = "A") -> Dict[str, Any]:
            org = fx[tk]["tenant_id"]
            doc = tc.portal.call(lambda: op_db.advances.find_one({"id": adv})) or {}
            rows = tc.portal.call(lambda: op_db.finance_payments.find(
                {"org_id": org, "direction": "Inflow"}).to_list(None))
            return {"remaining": doc.get("remaining_amount"), "status": doc.get("status"),
                    "repayments": len(doc.get("repayments") or []),
                    "repaid": round(sum(e["amount"] for e in doc.get("repayments") or []), 2),
                    "deductions": len(doc.get("manual_deductions") or []),
                    "inflows": len(rows), "inflow_sum": round(sum(r["amount"] for r in rows), 2)}

        def changed(before, after) -> Dict[str, Any]:
            return {k: (before[k], after[k]) for k in before if before[k] != after[k]}

        out: Dict[str, Any] = {"modes": {}}
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            m: Dict[str, Any] = {}

            # ── one key x3 -> one repayment, remaining reduced once, one Inflow
            adv = new_loan()
            key = "fixadv2-" + uuid.uuid4().hex
            s0 = state(adv)
            same = [repay("A:accountant", adv, 40, key) for _ in range(3)]
            s1 = state(adv)
            m["same_key"] = {"statuses": [r["status"] for r in same],
                             "remaining_in_bodies": [(r["body"] or {}).get("remaining_amount")
                                                     for r in same],
                             "before": s0, "after": s1}

            # ── same key, different amount -> 409, nothing written
            c = repay("A:accountant", adv, 50, key)
            m["same_key_other_body"] = {"status": c["status"], "error_code": c["error_code"],
                                        "changed": changed(s1, state(adv))}

            # ── no key / blank key -> 428, nothing written
            m["no_key"] = {}
            for case, nkey in (("missing", None), ("blank", "   ")):
                b = state(adv)
                r = repay("A:accountant", adv, 10, nkey)
                m["no_key"][case] = {"status": r["status"], "error_code": r["error_code"],
                                     "changed": changed(b, state(adv))}

            # ── 4 concurrent requests with one key
            adv_c = new_loan()
            ckey = "fixadv2-" + uuid.uuid4().hex
            hdr = {"Authorization": "Bearer " + tokens["A:accountant"], "Idempotency-Key": ckey}

            async def burst(path, headers_list):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post(path, headers=h)
                                                  for h in headers_list])
            b = state(adv_c)
            rs = tc.portal.call(lambda: burst("/api/advances/%s/repay?amount=25" % adv_c,
                                              [hdr] * 4))
            m["concurrent_same_key"] = {"statuses": sorted(r.status_code for r in rs),
                                        "before": b, "after": state(adv_c)}

            # ── 4 concurrent repayments under different keys (30 each on 100)
            adv_r = new_loan()
            b = state(adv_r)
            hs = [{"Authorization": "Bearer " + tokens["A:accountant"],
                   "Idempotency-Key": "fixadv2-" + uuid.uuid4().hex} for _ in range(4)]
            rs = tc.portal.call(lambda: burst("/api/advances/%s/repay?amount=30" % adv_r, hs))
            m["race_different_keys"] = {"statuses": sorted(r.status_code for r in rs),
                                        "before": b, "after": state(adv_r)}

            # ── over-repay: capped at the remaining balance, then closed -> 400
            ok = "fixadv2-" + uuid.uuid4().hex
            b = state(adv)
            over = repay("A:accountant", adv, 500, ok)
            a = state(adv)
            again_b = a
            closed = repay("A:accountant", adv, 10, "fixadv2-" + uuid.uuid4().hex)
            after_closed = state(adv)
            replay = repay("A:accountant", adv, 500, ok)
            m["over_repay"] = {"status": over["status"], "before": b, "after": a,
                               "closed_status": closed["status"],
                               "closed_changed": changed(again_b, after_closed),
                               "replay_status": replay["status"],
                               "replay_changed": changed(after_closed, state(adv))}

            # ── forbidden roles (with a key) -> 403, nothing written
            adv_f = new_loan()
            m["forbidden"] = {}
            for role in FORBIDDEN:
                b = state(adv_f)
                r = repay("A:" + role, adv_f, 10, "fixadv2-" + uuid.uuid4().hex)
                m["forbidden"][role] = {"status": r["status"], "changed": changed(b, state(adv_f))}

            # ── tenant isolation: B repays A's advance -> 404; B's own key space is separate
            bA, bB = state(adv_f), state("none", "B")
            cross = repay("B:owner", adv_f, 10, "fixadv2-" + uuid.uuid4().hex)
            m["tenant"] = {"status": cross["status"],
                           "changed_A": changed(bA, state(adv_f)),
                           "changed_B": changed(bB, state("none", "B"))}
            adv_b = new_loan("B")
            shared = "fixadv2-" + uuid.uuid4().hex
            ra = repay("A:accountant", adv_f, 10, shared)
            rb = repay("B:accountant", adv_b, 10, shared)
            m["tenant"]["same_key_each_tenant"] = {
                "statuses": [ra["status"], rb["status"]],
                "A": state(adv_f), "B": state(adv_b, "B")}

            # ── apply-deduction: one key x3 -> once; no key -> 428
            adv_d = new_loan()
            dkey = "fixadv2-" + uuid.uuid4().hex
            b = state(adv_d)
            ds = [call("A:accountant", "/api/advances/%s/apply-deduction?amount=15" % adv_d, dkey)
                  for _ in range(3)]
            a = state(adv_d)
            dn = call("A:accountant", "/api/advances/%s/apply-deduction?amount=15" % adv_d, None)
            m["deduction"] = {"statuses": [r["status"] for r in ds], "before": b, "after": a,
                              "no_key": {"status": dn["status"], "error_code": dn["error_code"],
                                         "changed": changed(a, state(adv_d))}}
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
    env["JWT_SECRET"] = "fixadv2-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="FIX-ADV-02 repay idempotency")
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
def check_result(result: Dict[str, Any]) -> None:
    assert set(result["modes"]) == set(MODES)
    for mode, m in result["modes"].items():
        s = m["same_key"]
        assert s["statuses"] == [200, 200, 200], (mode, s)
        assert s["before"]["remaining"] == 100 and s["after"]["remaining"] == 60, (mode, s)
        assert s["after"]["repayments"] == 1 and s["after"]["status"] == "Open", (mode, s)
        assert s["after"]["inflows"] - s["before"]["inflows"] == 1, (mode, s)   # was 3
        assert round(s["after"]["inflow_sum"] - s["before"]["inflow_sum"], 2) == 40, (mode, s)
        assert s["remaining_in_bodies"] == [60, 60, 60], (mode, s)
        c = m["same_key_other_body"]
        assert (c["status"], c["error_code"], c["changed"]) == (
            409, "IDEMPOTENCY_CONFLICT", {}), (mode, c)
        for case, n in m["no_key"].items():
            assert (n["status"], n["error_code"], n["changed"]) == (
                428, "IDEMPOTENCY_KEY_REQUIRED", {}), (mode, case, n)
        cc = m["concurrent_same_key"]
        assert 200 in cc["statuses"] and set(cc["statuses"]) <= {200, 409}, (mode, cc)
        assert cc["after"]["remaining"] == 75 and cc["after"]["repayments"] == 1, (mode, cc)
        assert cc["after"]["inflows"] - cc["before"]["inflows"] == 1, (mode, cc)
        rc = m["race_different_keys"]
        a, b = rc["after"], rc["before"]
        assert set(rc["statuses"]) <= {200, 409, 400} and 200 in rc["statuses"], (mode, rc)
        assert a["remaining"] >= 0, (mode, rc)
        assert round(100 - a["remaining"], 2) == a["repaid"], (mode, rc)          # no lost update
        assert a["inflows"] - b["inflows"] == a["repayments"] == rc["statuses"].count(200), (mode, rc)
        assert round(a["inflow_sum"] - b["inflow_sum"], 2) == a["repaid"], (mode, rc)
        o = m["over_repay"]
        assert o["status"] == 200, (mode, o)
        assert o["after"]["remaining"] == 0 and o["after"]["status"] == "Closed", (mode, o)
        assert round(o["after"]["inflow_sum"] - o["before"]["inflow_sum"], 2) == 60, (mode, o)
        assert o["after"]["inflows"] - o["before"]["inflows"] == 1, (mode, o)
        assert o["closed_status"] == 400 and o["closed_changed"] == {}, (mode, o)
        assert o["replay_status"] == 200 and o["replay_changed"] == {}, (mode, o)
        for role, f in m["forbidden"].items():
            assert (f["status"], f["changed"]) == (403, {}), (mode, role, f)
        t = m["tenant"]
        assert (t["status"], t["changed_A"], t["changed_B"]) == (404, {}, {}), (mode, t)
        st = t["same_key_each_tenant"]
        assert st["statuses"] == [200, 200], (mode, st)
        assert st["A"]["remaining"] == 90 and st["B"]["remaining"] == 90, (mode, st)
        d = m["deduction"]
        assert d["statuses"] == [200, 200, 200], (mode, d)
        assert d["after"]["remaining"] == 85, (mode, d)                          # was 55
        assert d["after"]["inflows"] == d["before"]["inflows"], (mode, d)        # no cash move
        assert (d["no_key"]["status"], d["no_key"]["error_code"], d["no_key"]["changed"]) == (
            428, "IDEMPOTENCY_KEY_REQUIRED", {}), (mode, d)


# ═══════════════════════════════════════════════════════════════════ static checks
@pytest.mark.parametrize("path, fn", [("/api/advances/{advance_id}/repay", "repay_advance"),
                                      ("/api/advances/{advance_id}/apply-deduction",
                                       "apply_advance_deduction")])
def test_the_route_takes_the_key_and_keeps_its_permission_check(path, fn):
    import server
    from app.routes import hr
    route = next(r for r in server.app.routes
                 if getattr(r, "path", None) == path and "POST" in r.methods)
    assert "idempotency_key" in inspect.signature(route.endpoint).parameters
    src = inspect.getsource(getattr(hr, fn))
    assert src.index("payroll_permission(user)") < src.index("MoneyWrite.begin(")
    assert "_reduce_advance_once(" in src and "uuid.uuid4()" not in src


def test_the_repayment_inflow_is_inserted_once_per_key():
    from app.routes import hr
    src = inspect.getsource(hr.repay_advance)
    assert "insert_once()" in src and "mw.unique(" in src
    assert 'mw.new_id("finance_payment")' in src and 'mw.new_id("repayment")' in src


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

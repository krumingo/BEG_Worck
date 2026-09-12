#!/usr/bin/env python3
"""Strict validation harness, not a production migration/deploy command.

A failing safety gate stops later DB phases. A successful process alone is not
proof: test node identities and migration state contracts are checked separately.
App/driver imports occur only after a guard. Evidence is written to a fresh dir.
STANDARD APPLICATION SUITE is deliberately NOT RUN, never implicitly PASS.
"""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from w0_02_validation_env import VALIDATION_ENV, require_runtime_env

MIG = BACKEND / "scripts/w0_02_bootstrap_permissions.py"
MANIFEST = BACKEND / "scripts/w0_02_validation_manifest.json"
PHASES = ("NEGATIVES", "MOCK SUITE", "REAL-MONGO SUITE", "MIGRATION CHECKS")


class ValidationFailure(RuntimeError):
    pass


def expect(condition, message):
    if not condition:
        raise ValidationFailure(message)


def child_env(extra=None):
    # No inheritance of MONGO_* / pytest filters / alternative module paths.
    env = {k: v for k, v in os.environ.items()
           if k in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "LANG", "LC_ALL"}}
    env.update(VALIDATION_ENV)
    env.update({"PYTHONPATH": str(BACKEND), "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                "PYTHON_DOTENV_DISABLED": "1", "BEG_VALIDATION_MODE": "1",
                "PERMISSION_SERVICE_MODE": "off", "W0_02_REAL_MONGO": "0",
                "W0_02_VALIDATION": "1", "PYTEST_ADDOPTS": "",
                "PYTEST_PLUGINS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    if extra:
        env.update(extra)
    return env


class Harness:
    def __init__(self, evidence):
        self.evidence = Path(evidence).resolve()
        self.evidence.mkdir(parents=True, exist_ok=False)
        self.sequence = 0

    def command(self, label, cmd, *, env=None, expected=0, timeout=600):
        self.sequence += 1
        stem = self.evidence / f"{self.sequence:03d}-{label}"
        timed_out = False
        try:
            p = subprocess.run([str(c) for c in cmd], cwd=str(BACKEND),
                               env=child_env(env), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            def text(value):
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")
            p = subprocess.CompletedProcess(cmd, 124, text(exc.stdout), text(exc.stderr))
        except OSError as exc:
            p = subprocess.CompletedProcess(cmd, 126, "", str(exc))
        stem.with_suffix(".stdout.txt").write_text(p.stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(p.stderr, encoding="utf-8")
        stem.with_suffix(".json").write_text(json.dumps({
            "command": [str(c) for c in cmd], "exit_code": p.returncode,
            "expected_exit": expected, "timed_out": timed_out,
        }, indent=2), encoding="utf-8")
        print(f"{label}: exit={p.returncode}; evidence={stem.name}", flush=True)
        expect(not timed_out and p.returncode == expected,
               f"{label}: expected exit {expected}, got {p.returncode}; see full logs")
        return p

    def negatives(self):
        for key, wrong in (("MONGO_URL", "mongodb://invalid-w002.invalid:27017"),
                           ("DB_NAME", "invalid_w002_operation"),
                           ("BEG_SYSTEM_DB", "invalid_w002_system")):
            p = self.command("negative-" + key.lower(), [sys.executable, MIG],
                             env={key: wrong}, expected=3, timeout=20)
            expect("FAIL-CLOSED" in p.stdout + p.stderr,
                   f"{key}: exit 3 was not produced by the validation guard")

    def suite(self, mode):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        expected_nodes = manifest[mode]
        expect(expected_nodes and len(expected_nodes) == len(set(expected_nodes)),
               "Test manifest is empty or contains duplicate nodes")
        out = self.evidence / (mode + "-pytest.json")
        expect(not out.exists(), "Refusing stale pytest evidence")
        command = [sys.executable, "-m", "pytest", "--noconftest",
                   "-p", "no:cacheprovider", "-p", "scripts.w0_02_validation_pytest_plugin",
                   "-c", os.devnull, "--rootdir", str(BACKEND), "-o", "addopts=", "-v"]
        # The mock suite collects the WHOLE file (new tests cannot silently disappear).
        # Real suite receives explicit class selectors, not a fuzzy -k filter.
        selectors = ["tests/test_w0_02_permission_core.py"] if mode == "mock" else sorted(
            {n.rsplit("::", 1)[0] for n in expected_nodes})
        self.command(mode + "-pytest", command + selectors, env={
            "W0_02_REAL_MONGO": "1" if mode == "real" else "0",
            "W002_PYTEST_EVIDENCE": str(out)}, timeout=900)
        expect(out.is_file(), "pytest produced no structured evidence")
        verify_test_report(json.loads(out.read_text(encoding="utf-8")), expected_nodes)
        print(f"{mode}: exact manifest satisfied ({len(expected_nodes)} tests)", flush=True)

    def migrate(self, label, args):
        return self.command("migration-" + label, [sys.executable, MIG, *args], timeout=120)

    async def migration(self):
        # Deliberately stricter than ce78527: existing PR-01 defects must FAIL,
        # not be hidden by weakening assertions. Only synthetic test DBs are used.
        live = require_runtime_env()
        from scripts.w0_02_validation_seed import guarded_client, reset_docs, seed_docs
        client = guarded_client(*(live[k] for k in VALIDATION_ENV))
        op, sy = client[live["DB_NAME"]], client[live["BEG_SYSTEM_DB"]]
        try:
            await reset_docs(op, sy)
            await seed_docs(op, sy)
            sentinel = {
                "id": "app-sentinel", "user_id": "synthetic-manual", "tenant_id": "T1",
                "role_id": "LEGACY_VIEWER", "scope_type": "project", "scope_id": "P_OTHER",
                "module": None, "permissions": ["budget.read"], "max_amount": 100,
                "valid_from": None, "valid_to": "2027-01-01T00:00:00+00:00",
                "status": "active", "created_by": "test:application",
            }
            await sy.tenant_role_assignments.insert_one(sentinel)
            await op.audit_events.insert_one({"id": "audit-sentinel", "synthetic": True})
            original_legacy = {u: await sy.tenant_role_assignments.find_one({"user_id": u})
                               for u in ("u_admin", "u_view", "u_tech", "u_sm")}
            original_app = await sy.tenant_role_assignments.find_one({"id": "app-sentinel"})
            original_op, original_sys = await snapshot(op), await snapshot(sy)

            async def op_unchanged(label):
                expect(await snapshot(op) == original_op,
                       label + ": operational contents/indexes changed")

            self.migrate("dry", [])
            expect(await snapshot(sy) == original_sys, "dry-run changed system state")
            await op_unchanged("dry-run")

            self.migrate("apply", ["--apply"])
            expected_map = {"u_admin": "admin", "u_view": "LEGACY_VIEWER",
                            "u_tech": "LEGACY_TECHNICIAN", "u_sm": "site_manager"}
            for uid, role in expected_map.items():
                rows = await sy.tenant_role_assignments.find(
                    {"user_id": uid, "scope_type": "company"}).to_list(None)
                expect(len(rows) == 1 and rows[0].get("role_id") == role,
                       f"apply: wrong company mapping for {uid}")
            projects = {}
            for uid, perms in (("u_view", {"budget.read"}),
                               ("u_sm", {"budget.read", "budget.write"})):
                rows = await sy.tenant_role_assignments.find(
                    {"user_id": uid, "scope_type": "project", "scope_id": "P1"}).to_list(None)
                expect(len(rows) == 1 and set(rows[0].get("permissions", [])) == perms,
                       f"apply: wrong project backfill for {uid}")
                projects[uid] = rows[0]["id"]
            expect(await sy.tenant_role_assignments.find_one({"id": "app-sentinel"}) == original_app,
                   "apply overwrote an application-owned assignment (PR-01)")
            await op_unchanged("apply")
            applied = await snapshot(sy)
            self.migrate("reapply", ["--apply"])
            expect(await snapshot(sy) == applied, "reapply was not content-idempotent (PR-01)")
            await op_unchanged("reapply")

            # Subsequent legitimate modifications must survive another bootstrap.
            await sy.tenant_role_assignments.update_one({"id": projects["u_view"]}, {"$set": {
                "status": "revoked", "revoked_by": "test:application", "revoke_reason": "regression"}})
            await sy.tenant_role_assignments.update_one({"id": projects["u_sm"]}, {"$set": {
                "valid_to": "2020-01-01T00:00:00+00:00"}})
            protected = await snapshot(sy)
            self.migrate("reapply-protected", ["--apply"])
            expect(await snapshot(sy) == protected, "reapply reset revoke/expiry/restrictions (PR-01)")
            await op_unchanged("reapply-protected")

            before_verify = await snapshot(sy)
            self.migrate("verify", ["--verify"])
            expect(await snapshot(sy) == before_verify, "verify changed system contents")
            await op_unchanged("verify")

            late = dict(sentinel, id="late-project-assignment", user_id="synthetic-late",
                        scope_id="P_LATE", migrated_from="project_team")
            late.pop("_id", None)
            await sy.tenant_role_assignments.insert_one(late)
            late_before = await sy.tenant_role_assignments.find_one({"id": late["id"]})
            protected_docs = {uid: await sy.tenant_role_assignments.find_one({"id": aid})
                              for uid, aid in projects.items()}
            self.migrate("revert", ["--revert", "--apply"])
            expect(await sy.tenant_role_assignments.find_one({"id": late["id"]}) == late_before,
                   "revert deleted/changed a later application-created project assignment")
            expect(await sy.tenant_role_assignments.find_one({"id": "app-sentinel"}) == original_app,
                   "revert changed an application assignment")
            for uid, before in protected_docs.items():
                expect(await sy.tenant_role_assignments.find_one({"id": before["id"]}) == before,
                       "revert changed a subsequently revoked/expired assignment")
            for uid, before in original_legacy.items():
                expect(await sy.tenant_role_assignments.find_one({"id": before["id"]}) == before,
                       "revert failed to restore an untouched legacy mirror exactly")
            await op_unchanged("revert")
        finally:
            client.close()


def verify_test_report(report, expected_nodes):
    expect(report.get("schema") == 1 and report.get("exit_code") == 0,
           "Invalid/failed pytest report")
    expect(not report.get("deselected") and not report.get("collection_errors")
           and not report.get("internal_errors"), "pytest deselected/skipped collection or errored")
    selected = report.get("selected", [])
    expect(len(selected) == len(expected_nodes) and set(selected) == set(expected_nodes),
           "Collected tests do not exactly match the mandatory manifest")
    expected = {(node, phase) for node in expected_nodes for phase in ("setup", "call", "teardown")}
    seen = []
    for item in report.get("reports", []):
        expect(item.get("outcome") == "passed" and item.get("wasxfail") is None,
               "A test phase failed/skipped/xfail/xpass")
        seen.append((item.get("nodeid"), item.get("when")))
    expect(len(seen) == len(expected) and set(seen) == expected,
           "Missing/duplicate test execution or incomplete teardown")


async def snapshot(db):
    from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
    result = {}
    for name in sorted(await db.list_collection_names()):
        docs = [dumps(d, json_options=CANONICAL_JSON_OPTIONS, sort_keys=True)
                async for d in db[name].find({})]
        indexes = await db[name].index_information()
        result[name] = {"documents": sorted(docs), "indexes": indexes}
    return result


def execute(harness, only):
    results = {k: "NOT RUN" for k in PHASES}
    results["STANDARD APPLICATION SUITE"] = "NOT RUN"
    selected = {
        "negatives": ["NEGATIVES"], "mock": ["NEGATIVES", "MOCK SUITE"],
        "real": ["NEGATIVES", "REAL-MONGO SUITE"],
        "migration": ["NEGATIVES", "MIGRATION CHECKS"], "all": list(PHASES),
    }[only]
    current = None
    try:
        if only in ("real", "migration", "all"):
            require_runtime_env()
        for current in selected:
            if current == "NEGATIVES": harness.negatives()
            elif current == "MOCK SUITE": harness.suite("mock")
            elif current == "REAL-MONGO SUITE": harness.suite("real")
            else: asyncio.run(harness.migration())
            results[current] = "PASS"
    except (Exception, SystemExit) as exc:
        results[current or "PREFLIGHT"] = "FAIL"
        results["failure"] = str(exc)
        (harness.evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    failed = any(v == "FAIL" for v in results.values())
    summary = {"python": platform.python_version(), "requested": only, "results": results,
               "exit_code": 1 if failed else 0,
               "scope": "Specialized validation only. NOT merge/deploy approval."}
    (harness.evidence / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary["exit_code"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", choices=["negatives", "mock", "real", "migration", "all"], default="all")
    p.add_argument("--evidence", required=True, help="New directory; refuses an existing one")
    args = p.parse_args(argv)
    return execute(Harness(args.evidence), args.only)


if __name__ == "__main__":
    sys.exit(main())

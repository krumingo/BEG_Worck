#!/usr/bin/env python3
"""
ST-01 — API part of Krum's acceptance scenarios against a running backend.

Reads ``scenarios/acceptance_scenarios.json`` and the synthetic users of
``st01_fixture.json`` (created by ``seed_synthetic.py``), logs in over real HTTP
and writes ``result.json``: one status per step and per scenario.

Statuses — never more optimistic than the evidence:

* ``pass``    — the step's API check ran and every assertion held;
* ``fail``    — the check ran and an assertion did not hold (reason recorded);
* ``blocked`` — the canonical function or screen does not exist on this build
  (``NO_CANONICAL_FUNCTION`` / ``NO_SCREEN``), the runner has no check for it
  (``NO_RUNNER_CHECK``), it is browser-only (``UI_NOT_RUN_BY_API_RUNNER``), or
  the backend could not be reached (``UNREACHABLE``).

A scenario is ``pass`` only if every step passed; ``fail`` if any step failed;
otherwise ``blocked``. The browser part is run by the Bot session from the same
scenario list.

The runner WRITES synthetic material requests into tenant A (it is a staging
acceptance run). It refuses a non-local ``--base-url`` unless ``--allow-remote``
is given. The password comes from ``$ST01_SEED_PASSWORD`` (or ``--password-env``)
and is never written to the result. Exit 0 = result written and nothing
failed; 1 = at least one step failed; 2 = refused.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "st01_fixture.json"
SCENARIOS_PATH = HERE / "scenarios" / "acceptance_scenarios.json"
DEFAULT_PASSWORD_ENV = "ST01_SEED_PASSWORD"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

PASS, FAIL, BLOCKED = "pass", "fail", "blocked"
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2
#: Roles that may not create a material request on main (Admin/Owner/SiteManager may).
NON_REQUESTER_ROLES = ("denied", "viewer", "technician", "driver", "accountant", "warehousekeeper")


class Refused(Exception):
    pass


class CheckFailed(AssertionError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_base_url(base_url: str, allow_remote: bool) -> None:
    parsed = urlparse(base_url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise Refused("--base-url must be an http(s) URL")
    if not allow_remote and parsed.hostname.lower() not in LOCAL_HOSTS:
        raise Refused("host %r is not local (an isolated staging host needs --allow-remote; "
                      "never production)" % parsed.hostname)


def expect(cond: bool, message: str) -> None:
    if not cond:
        raise CheckFailed(message)


# ═══════════════════════════════════════════════════════════════════ context
class Ctx:
    """Logged-in synthetic users, tenant ids and memoized check results."""

    def __init__(self, client, fixture: Dict[str, Any], password: str):
        self.c = client
        self.fixture = fixture
        self.password = password
        self.roles = {r["key"]: r for r in fixture["roles"]}
        self.tenants = {t["key"]: t for t in fixture["tenants"]}
        self._tokens: Dict[Tuple[str, str], str] = {}
        self._me: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._projects: Dict[str, Dict[str, Any]] = {}
        self.results: Dict[str, Tuple[str, str]] = {}

    def email(self, tenant: str, role: str) -> str:
        return "st01.%s@%s" % (role, self.tenants[tenant]["email_domain"])

    async def login(self, tenant: str, role: str, fresh: bool = False) -> str:
        key = (tenant, role)
        if fresh or key not in self._tokens:
            r = await self.c.post("/api/auth/login",
                                  json={"email": self.email(tenant, role), "password": self.password})
            expect(r.status_code == 200, "login %s/%s answered %s" % (tenant, role, r.status_code))
            self._tokens[key] = r.json()["token"]
        return self._tokens[key]

    async def call(self, tenant: str, role: str, method: str, path: str,
                   body: Any = None, fresh: bool = False):
        token = await self.login(tenant, role, fresh=fresh)
        kwargs: Dict[str, Any] = {"headers": {"Authorization": "Bearer " + token}}
        if body is not None:
            kwargs["json"] = body
        return await self.c.request(method, path, **kwargs)

    async def me(self, tenant: str, role: str) -> Dict[str, Any]:
        key = (tenant, role)
        if key not in self._me:
            r = await self.call(tenant, role, "GET", "/api/auth/me")
            expect(r.status_code == 200, "/auth/me %s/%s answered %s" % (tenant, role, r.status_code))
            self._me[key] = r.json()
        return self._me[key]

    async def project(self, tenant: str) -> Dict[str, Any]:
        """The tenant's synthetic project, found by code through its own owner."""
        if tenant not in self._projects:
            code = self.tenants[tenant]["project"]["code"]
            r = await self.call(tenant, "owner", "GET", "/api/projects")
            expect(r.status_code == 200, "GET /projects for %s answered %s" % (tenant, r.status_code))
            rows = r.json()
            rows = rows.get("items", rows) if isinstance(rows, dict) else rows
            match = [p for p in rows if isinstance(p, dict) and p.get("code") == code]
            expect(len(match) == 1, "tenant %s sees %d projects with code %s (seed missing?)"
                   % (tenant, len(match), code))
            self._projects[tenant] = match[0]
        return self._projects[tenant]

    async def create_request(self, tenant: str = "A", role: str = "requester", label: str = ""):
        project = await self.project(tenant)
        body = {"project_id": project["id"], "notes": "ST-01 runner %s %s" % (label, uuid.uuid4().hex[:8]),
                "lines": [{"material_name": "ST01 synthetic material", "qty_requested": 3, "unit": "бр"}]}
        return await self.call(tenant, role, "POST", "/api/material-requests", body)

    async def request_count(self, tenant: str) -> int:
        project = await self.project(tenant)
        r = await self.call(tenant, "owner", "GET", "/api/material-requests?project_id=%s" % project["id"])
        expect(r.status_code == 200, "GET /material-requests answered %s" % r.status_code)
        return len(r.json())


# ═══════════════════════════════════════════════════════════════════ checks
async def check_health(ctx: Ctx) -> str:
    r = await ctx.c.get("/api/health")
    expect(r.status_code == 200, "/api/health answered %s" % r.status_code)
    return "health 200"


async def check_owner_login(ctx: Ctx) -> str:
    a, b = await ctx.me("A", "owner"), await ctx.me("B", "owner")
    for t, me in (("A", a), ("B", b)):
        expect(me.get("role") == "Owner", "owner of %s has role %r" % (t, me.get("role")))
        expect(me.get("email") == ctx.email(t, "owner"), "owner of %s logged into another account" % t)
    expect(a.get("org_id") and a.get("org_id") != b.get("org_id"), "owners of A and B share a tenant")
    r = await ctx.c.post("/api/auth/login", json={"email": ctx.email("A", "owner"),
                                                   "password": ctx.password + "-wrong"})
    expect(r.status_code == 401, "a wrong password answered %s, not 401" % r.status_code)
    return "both owners log into their own tenant; wrong password 401"


async def check_login_all_roles(ctx: Ctx) -> str:
    n = 0
    for t in ctx.tenants:
        tenant_id = (await ctx.me(t, "owner"))["org_id"]
        for key, role in ctx.roles.items():
            me = await ctx.me(t, key)
            expect(me.get("role") == role["legacy_role"],
                   "%s/%s has role %r, expected %r" % (t, key, me.get("role"), role["legacy_role"]))
            expect(me.get("org_id") == tenant_id, "%s/%s is not in tenant %s" % (t, key, t))
            expect("password_hash" not in me, "/auth/me leaks password_hash")
            n += 1
    return "%d users logged in with the expected role and tenant" % n


async def check_cross_tenant_project(ctx: Ctx) -> str:
    for mine, theirs in (("A", "B"), ("B", "A")):
        foreign = await ctx.project(theirs)
        r = await ctx.call(mine, "owner", "GET", "/api/projects")
        expect(foreign["code"] not in r.text, "%s's project list shows %s's project" % (mine, theirs))
        for role in ("owner", "admin", "requester"):
            r = await ctx.call(mine, role, "GET", "/api/projects/%s" % foreign["id"])
            expect(r.status_code == 404, "%s/%s read %s's project by id: %s"
                   % (mine, role, theirs, r.status_code))
            expect(foreign["code"] not in r.text, "%s/%s got %s's project data" % (mine, role, theirs))
    return "foreign project id answers 404 for owner/admin/requester in both directions"


async def check_cross_tenant_warehouse(ctx: Ctx) -> str:
    for mine, theirs in (("A", "B"), ("B", "A")):
        r = await ctx.call(mine, "owner", "GET", "/api/warehouses")
        expect(r.status_code == 200, "GET /warehouses for %s answered %s" % (mine, r.status_code))
        expect(ctx.tenants[mine]["warehouse"]["code"] in r.text, "%s does not see its own warehouse" % mine)
        expect(ctx.tenants[theirs]["warehouse"]["code"] not in r.text,
               "%s sees %s's warehouse" % (mine, theirs))
    return "each tenant sees only its own warehouse"


async def check_cross_tenant_request(ctx: Ctx) -> str:
    r = await ctx.create_request("A", "requester", "isolation")
    expect(r.status_code == 201, "requester A could not create a request: %s" % r.status_code)
    req = r.json()
    before = await ctx.call("A", "owner", "GET", "/api/material-requests/%s" % req["id"])
    expect(before.status_code == 200, "A cannot read its own request")
    path = "/api/material-requests/%s" % req["id"]
    for role in ("owner", "admin", "requester"):
        for method, p, body in (("GET", path, None),
                                ("PUT", path, {"notes": "OVERWRITTEN-BY-B", "status": "cancelled"}),
                                ("POST", path + "/submit", None),
                                ("DELETE", path, None)):
            r = await ctx.call("B", role, method, p, body)
            expect(r.status_code == 404, "B/%s %s on A's request answered %s" % (role, method, r.status_code))
            expect("ST-01 runner" not in r.text, "B/%s got A's request data" % role)
    after = await ctx.call("A", "owner", "GET", path)
    expect(after.status_code == 200, "A's request vanished after B's attempts")
    expect(after.json() == before.json(), "A's request changed after B's attempts")
    return "B's GET/PUT/submit/DELETE on A's request: 404, A's record unchanged"


async def check_denied_zero_write(ctx: Ctx) -> str:
    before = await ctx.request_count("A")
    for role in NON_REQUESTER_ROLES:
        r = await ctx.create_request("A", role, "denied")
        expect(r.status_code == 403, "%s creating a request answered %s, not 403" % (role, r.status_code))
        detail = (r.json() or {}).get("detail") if r.headers.get("content-type", "").startswith(
            "application/json") else None
        expect(bool(detail), "%s got a 403 without a message" % role)
    after = await ctx.request_count("A")
    expect(after == before, "denied creates wrote %d records" % (after - before))
    return "%d roles refused with 403 + message; zero records written" % len(NON_REQUESTER_ROLES)


async def check_create_persists_relogin(ctx: Ctx) -> str:
    project = await ctx.project("A")
    r = await ctx.create_request("A", "requester", "persist")
    expect(r.status_code == 201, "create answered %s" % r.status_code)
    created = r.json()
    r = await ctx.call("A", "requester", "GET", "/api/material-requests/%s" % created["id"], fresh=True)
    expect(r.status_code == 200, "after relogin the request answered %s" % r.status_code)
    got = r.json()
    expect(got["id"] == created["id"] and got["project_id"] == project["id"],
           "id or project id changed after relogin")
    expect(got.get("request_number") == created.get("request_number"), "request number changed")
    expect([l["id"] for l in got.get("lines", [])] == [l["id"] for l in created.get("lines", [])],
           "line ids changed after relogin")
    return "request %s survives relogin with stable id/project/line ids" % created.get("request_number")


async def check_submit_once(ctx: Ctx) -> str:
    r = await ctx.create_request("A", "requester", "submit")
    expect(r.status_code == 201, "create answered %s" % r.status_code)
    path = "/api/material-requests/%s" % r.json()["id"]
    first = await ctx.call("A", "requester", "POST", path + "/submit")
    expect(first.status_code == 200 and first.json().get("status") == "submitted",
           "submit answered %s" % first.status_code)
    second = await ctx.call("A", "requester", "POST", path + "/submit")
    expect(second.status_code in (200, 400, 409), "duplicate submit answered %s" % second.status_code)
    now = await ctx.call("A", "requester", "GET", path)
    expect(now.json().get("status") == "submitted", "status after duplicate submit: %r"
           % now.json().get("status"))
    expect(now.json().get("submitted_at") == first.json().get("submitted_at"),
           "a duplicate submit rewrote submitted_at (second transition)")
    return "one transition draft→submitted; duplicate submit answered %s and changed nothing" \
        % second.status_code


CHECKS: Dict[str, Callable[[Ctx], Awaitable[str]]] = {
    "health.api_up": check_health,
    "auth.owner_login": check_owner_login,
    "auth.login_all_roles": check_login_all_roles,
    "isolation.cross_tenant_project": check_cross_tenant_project,
    "isolation.cross_tenant_warehouse": check_cross_tenant_warehouse,
    "isolation.cross_tenant_request": check_cross_tenant_request,
    "roles.denied_zero_write": check_denied_zero_write,
    "request.create_persists_relogin": check_create_persists_relogin,
    "request.submit_once": check_submit_once,
}


# ═══════════════════════════════════════════════════════════════════ runner
def scenario_status(step_statuses: List[str]) -> str:
    if not step_statuses:
        return BLOCKED
    if FAIL in step_statuses:
        return FAIL
    if all(s == PASS for s in step_statuses):
        return PASS
    return BLOCKED


async def run_step(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, Any]:
    out = {"id": step["id"], "action": step.get("action", ""), "ui": bool(step.get("ui"))}
    if step.get("blocked"):
        out.update(status=BLOCKED, reason_code=step["blocked"], reason=step.get("reason", ""))
        return out
    if step.get("ui"):
        out.update(status=BLOCKED, reason_code="UI_NOT_RUN_BY_API_RUNNER",
                   reason="browser step: run by the Bot session from the same list")
        return out
    check_id = step.get("api_check")
    out["api_check"] = check_id
    fn = CHECKS.get(check_id or "")
    if fn is None:
        out.update(status=BLOCKED, reason_code="NO_RUNNER_CHECK",
                   reason="no API check %r in run_scenarios.py" % check_id)
        return out
    if check_id not in ctx.results:
        try:
            ctx.results[check_id] = (PASS, await fn(ctx))
        except CheckFailed as exc:
            ctx.results[check_id] = (FAIL, str(exc))
        except Exception as exc:  # transport/JSON errors are evidence too, never a pass
            name = type(exc).__name__
            if "Connect" in name or "Timeout" in name:
                ctx.results[check_id] = (BLOCKED, "UNREACHABLE: %s" % name)
            else:
                ctx.results[check_id] = (FAIL, "%s: %s" % (name, str(exc)[:300]))
    status, detail = ctx.results[check_id]
    out["status"] = status
    if status == PASS:
        out["evidence"] = detail
    elif status == BLOCKED:
        out.update(reason_code="UNREACHABLE", reason=detail)
    else:
        out["reason"] = detail
    return out


async def run(client, scenarios_doc: Dict[str, Any], fixture: Dict[str, Any],
              password: str, base_url: str = "") -> Dict[str, Any]:
    ctx = Ctx(client, fixture, password)
    scenarios = []
    for sc in scenarios_doc["scenarios"]:
        steps = [await run_step(ctx, step) for step in sc["steps"]]
        scenarios.append({"id": sc["id"], "title": sc["title"], "flows": sc.get("flows", []),
                          "roles": sc.get("roles", []), "expected": sc.get("expected", ""),
                          "status": scenario_status([s["status"] for s in steps]),
                          "steps": steps})
    counts = {k: sum(1 for s in scenarios if s["status"] == k) for k in (PASS, FAIL, BLOCKED)}
    step_counts = {k: sum(1 for s in scenarios for st in s["steps"] if st["status"] == k)
                   for k in (PASS, FAIL, BLOCKED)}
    return {"schema": "beg.st-01-scenario-result/v1", "generated_at": _now(),
            "base_url": base_url, "scope": "api", "scenario_source": scenarios_doc.get("source"),
            "summary": {"scenarios": counts, "steps": step_counts,
                        "total_scenarios": len(scenarios)},
            "note": "blocked is not pass: the function/screen is missing or not run here",
            "scenarios": scenarios}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ST-01 API scenario runner")
    p.add_argument("--base-url", default="http://127.0.0.1:8001")
    p.add_argument("--allow-remote", action="store_true",
                   help="allow a non-local isolated staging host (never production)")
    p.add_argument("--scenarios", default=str(SCENARIOS_PATH))
    p.add_argument("--fixture", default=str(FIXTURE_PATH))
    p.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    p.add_argument("--out", default="result.json")
    p.add_argument("--timeout", type=float, default=30.0)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        check_base_url(args.base_url, args.allow_remote)
        password = os.environ.get(args.password_env, "")
        if not password:
            raise Refused("no password: set $%s" % args.password_env)
    except Refused as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    import httpx

    async def go():
        async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as c:
            return await run(c, load_json(Path(args.scenarios)), load_json(Path(args.fixture)),
                             password, base_url=args.base_url)
    result = asyncio.run(go())
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return EXIT_FAILED if result["summary"]["steps"][FAIL] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

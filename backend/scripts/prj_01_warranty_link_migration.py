#!/usr/bin/env python3
"""
PRJ-01 / R54(1) (FG-236) — link every legacy "Warranty" project to its ORIGINAL project.

Krum, 08.11.2026 (R54): the existing projects of type "Warranty" are linked to the original
project (a migration with an AuditEvent; the history stays); new warranty work is done in
the original project (FLOW-001 P-08, P-13; FLOW-039); the type does not change after the
first record. Nothing here deletes, merges or re-types a project.

How the original is determined — and nothing else is guessed:

* ``--map WARRANTY_ID=ORIGINAL_ID`` — a person's decision (e.g. the answer to a DQ issue);
* otherwise the project's own ``parent_project_id``: the warranty project was filed UNDER
  that project, so that project is its original;
* in both cases the original must exist in the SAME tenant and must not be a Warranty
  project itself. Anything else → a Data Quality issue (``dq_issues``,
  ``PROJECT_WARRANTY_ORIGINAL_UNKNOWN``), never a link. Same client + same address is NOT
  used: FLOW-001 P-15 says that is often a NEW project.

Properties:

* **Dry run by default.** It prints the plan and its SHA-256. ``--apply`` needs
  ``--approved-by`` and ``--plan-sha`` equal to the plan of the moment — the approved dry
  run, not another one (else ``PlanMismatch``, nothing written).
* **One transaction per project**: the link (or the DQ issue) and its canonical AuditEvent
  (``project.warranty_link`` / ``dq.issue.open``, actor ``system``, approver in the diff).
* **Idempotent.** A linked project is ``already``; an open DQ issue is ``dq_open``; a second
  run writes nothing.

    MONGO_URL=... DB_NAME=... python scripts/prj_01_warranty_link_migration.py
    MONGO_URL=... DB_NAME=... python scripts/prj_01_warranty_link_migration.py \\
        --apply --approved-by "Крум" --plan-sha <sha from the dry run> [--map W=O ...]

Running it against production is an operator decision outside PRJ-01 (no production access
here).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WARRANTY = "Warranty"
DQ_TYPE = "PROJECT_WARRANTY_ORIGINAL_UNKNOWN"
DQ_OWNER_ROLE = "admin"          # PRJ-01-D4: who resolves it (projects: Owner/Admin, P-07)
MIGRATION = "PRJ-01"


class PlanMismatch(RuntimeError):
    """``--apply`` was given a plan hash that is not the current plan — nothing written."""


class NotApproved(RuntimeError):
    """``--apply`` without ``--approved-by`` — nothing written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dq_id(org_id: str, project_id: str) -> str:
    """The ONE open DQ row per (tenant, type, project) — the CP-01 / #81 id scheme."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-dq:%s:%s:%s:%s" % (
        org_id, DQ_TYPE, "project", project_id)))


async def build_plan(db, mapping: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    mapping = mapping or {}
    rows: List[Dict[str, Any]] = []
    async for p in db.projects.find({"type": WARRANTY}, {"_id": 0}).sort([("org_id", 1),
                                                                          ("id", 1)]):
        org, wid = p.get("org_id"), p.get("id")
        base = {"org_id": org, "project_id": wid, "code": p.get("code")}
        if not org:
            rows.append({**base, "action": "dq", "why": "ownerless"})
            continue
        if p.get("warranty_of_project_id"):
            rows.append({**base, "action": "already", "original": p["warranty_of_project_id"]})
            continue
        candidate, source = (mapping[wid], "operator_mapping") if wid in mapping else \
            (p.get("parent_project_id"), "parent_project_id")
        original = None
        if candidate and candidate != wid:
            original = await db.projects.find_one({"id": candidate, "org_id": org},
                                                  {"_id": 0, "id": 1, "type": 1})
        if original and original.get("type") != WARRANTY:
            rows.append({**base, "action": "link", "original": original["id"], "source": source})
            continue
        open_dq = await db.dq_issues.find_one({"id": dq_id(org, wid), "org_id": org,
                                               "status": "open"}, {"_id": 1})
        rows.append({**base, "action": "dq_open" if open_dq else "dq",
                     "why": "no_candidate" if not candidate else "candidate_invalid"})
    return rows


def plan_sha(rows: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"link": 0, "dq": 0, "already": 0, "dq_open": 0}
    for r in rows:
        out[r["action"]] += 1
    return out


async def _event(db, session, *, org: str, action: str, entity_type: str, entity_id: str,
                 reason: str, diff: Dict[str, Any]) -> None:
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(tenant_id=org, actor_type=ACTOR_SYSTEM, actor_id="migration:PRJ-01",
                        action=action, source_flow="FLOW-001",
                        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
                        entity_type=entity_type, entity_id=entity_id, reason=reason,
                        structured_diff=diff, tool_or_endpoint="scripts/prj_01_warranty_link_migration.py",
                        source_channel="migration")
    await record_event(db, event, session=session)


async def _apply_row(db, row: Dict[str, Any], approved_by: str) -> bool:
    """One project, one transaction. Returns whether anything was written."""
    from app.services.auth_tx import run_in_transaction
    from app.tenancy.data_access import TenantData
    org, wid = row["org_id"], row["project_id"]
    if not org:
        return False                       # ownerless: reported, never written (A2B)
    tenant = TenantData.for_resolved_org(db, org)
    now = _now()

    async def link(session):
        res = await tenant.projects.update_one(
            {"id": wid, "type": WARRANTY, "warranty_of_project_id": {"$exists": False}},
            {"$set": {"warranty_of_project_id": row["original"],
                      "warranty_link": {"source": row["source"], "migration": MIGRATION,
                                        "approved_by": approved_by, "linked_at": now}}},
            session=session)
        if res.modified_count != 1:
            return False
        await _event(db, session, org=org, action="project.warranty_link",
                     entity_type="project", entity_id=wid,
                     reason="Р54: гаранционният обект се свързва с оригиналния обект",
                     diff={"before": {"warranty_of_project_id": None},
                           "after": {"warranty_of_project_id": row["original"]},
                           "source": row["source"], "approved_by": approved_by})
        # FG-256: the DQ issue of this project (if any) is resolved by the decision
        rid = dq_id(org, wid)
        res = await tenant.dq_issues.update_one(
            {"id": rid, "status": "open"},
            {"$set": {"status": "resolved", "resolved_at": now, "resolved_by": approved_by,
                      "resolution": {"warranty_of_project_id": row["original"],
                                     "source": row["source"]}, "updated_at": now}},
            session=session)
        if res.modified_count == 1:
            await _event(db, session, org=org, action="dq.issue.resolve",
                         entity_type="dq_issue", entity_id=rid,
                         reason="Р54: оригиналният обект е посочен (%s)" % row["source"],
                         diff={"before": {"status": "open"},
                               "after": {"status": "resolved",
                                         "warranty_of_project_id": row["original"]}})
        return True

    async def dq(session):
        rid = dq_id(org, wid)
        doc = {"id": rid, "org_id": org, "type": DQ_TYPE, "code": DQ_TYPE,
               "title": "Гаранционен обект без определен оригинален обект",
               "message": "Гаранционният обект %s няма оригинален обект, който да се определи "
                          "без предположение — посочете го (--map %s=<id>)." % (
                              row.get("code") or wid, wid),
               "entity_type": "project", "entity_id": wid, "status": "open",
               "severity": "warning", "owner_role": DQ_OWNER_ROLE, "opened_at": now,
               "created_at": now, "updated_at": now, "occurrences": 1,
               "created_by": "migration:PRJ-01",
               "data": {"why": row.get("why"), "approved_by": approved_by}}
        res = await tenant.dq_issues.update_one({"id": rid}, {"$setOnInsert": doc},
                                                upsert=True, session=session)
        if res.upserted_id is None:
            return False
        await _event(db, session, org=org, action="dq.issue.open", entity_type="dq_issue",
                     entity_id=rid, reason="Р54: оригиналният обект не може да се определи",
                     diff={"after": {"type": DQ_TYPE, "project_id": wid, "status": "open"}})
        return True

    if row["action"] == "link":
        return await run_in_transaction(db, link)
    if row["action"] == "dq":
        return await run_in_transaction(db, dq)
    return False


async def migrate(db, apply: bool = False, approved_by: Optional[str] = None,
                  plan_sha: Optional[str] = None,
                  mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    rows = await build_plan(db, mapping)
    sha = globals()["plan_sha"](rows)
    result = {"plan": rows, "plan_sha": sha, "counts": counts(rows), "applied": False}
    if not apply:
        return result
    if not (approved_by or "").strip():
        raise NotApproved("--apply needs --approved-by")
    if plan_sha != sha:
        raise PlanMismatch("the approved plan is not the current plan — run the dry run again")
    written = 0
    for row in rows:
        written += bool(await _apply_row(db, row, approved_by.strip()))
    result.update({"applied": True, "written": written})
    return result


def _parse_map(values: List[str]) -> Dict[str, str]:
    out = {}
    for v in values or []:
        w, sep, o = v.partition("=")
        if not sep or not w or not o:
            raise SystemExit("--map expects WARRANTY_ID=ORIGINAL_ID, got %r" % v)
        out[w] = o
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PRJ-01 warranty projects → original project")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--approved-by")
    ap.add_argument("--plan-sha")
    ap.add_argument("--map", action="append", default=[])
    args = ap.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        res = asyncio.run(migrate(db, apply=args.apply, approved_by=args.approved_by,
                                  plan_sha=args.plan_sha, mapping=_parse_map(args.map)))
    except (PlanMismatch, NotApproved) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

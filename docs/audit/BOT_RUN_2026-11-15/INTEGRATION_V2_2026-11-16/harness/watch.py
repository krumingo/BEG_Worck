"""Every change in the demo database (insert/update/replace/delete), with time and keys.
INTEGRATION_V2: Mongo URL / DB / run dir from BOT_MONGO / BOT_DB / BOT_RUN."""
import json, os, time, sys
from pymongo import MongoClient
c = MongoClient(os.environ.get("BOT_MONGO", "mongodb://127.0.0.1:27192/?directConnection=true"))
out = open(os.path.join(os.environ.get("BOT_RUN", "/tmp/claude-0/demo_int2/ui/run"), "db.jsonl"), "a", buffering=1, encoding="utf8")
with c[os.environ.get("BOT_DB", "demoint2ui_begwork")].watch(full_document="updateLookup") as s:
    for ch in s:
        doc = ch.get("fullDocument") or {}
        upd = (ch.get("updateDescription") or {})
        rec = {"t": time.time(), "op": ch["operationType"], "coll": ch.get("ns", {}).get("coll"),
               "id": str((ch.get("documentKey") or {}).get("_id")), "doc_id": doc.get("id"),
               "has_org": ("org_id" in doc) if doc else None, "org": doc.get("org_id"),
               "fields": sorted(list((upd.get("updatedFields") or {}).keys()))[:25] if upd else sorted(doc.keys())[:40],
               "removed": upd.get("removedFields") if upd else None,
               "status": doc.get("status") or doc.get("approval_status"), "by": doc.get("created_by") or doc.get("updated_by")}
        out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

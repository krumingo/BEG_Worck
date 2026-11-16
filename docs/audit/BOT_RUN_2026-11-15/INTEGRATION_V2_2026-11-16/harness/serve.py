"""Demo wrapper (outside the repo): real backend app + built frontend on one port,
plus a request log of every /api call (who, what, status, how long).

INTEGRATION_V2: logs the bot's `x-correlation-id` per request (screen action <-> server by
id, not by a time window). With BOT_SERIALIZE_WRITES=1 every mutating /api request runs
alone (one asyncio lock) and the lock is held BOT_SETTLE seconds after the response, so a
database change seen by watch.py belongs to exactly one write request (`t`..`t_end`), not
to a window shared by 8 concurrent bots. Reads are not serialized."""
import asyncio, os, sys, json, time, base64, threading
TREE = os.environ["BOT_TREE"]   # the integration worktree
sys.path.insert(0, os.path.join(TREE, "backend"))
from server import app
from fastapi.responses import FileResponse
from starlette.requests import Request

BUILD = os.path.join(TREE, "frontend", "build")
LOG = open(os.path.join(os.environ["BOT_RUN"], "backend.jsonl"), "a", buffering=1, encoding="utf8")
LOCK = threading.Lock()
SERIALIZE = os.environ.get("BOT_SERIALIZE_WRITES") == "1"
SETTLE = float(os.environ.get("BOT_SETTLE", "0.4"))
WRITE_LOCK = asyncio.Lock()
MUT = {"POST", "PUT", "PATCH", "DELETE"}

def _who(auth):
    try:
        p = auth.split(".")[1]; p += "=" * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        return d.get("user_id") or d.get("sub")
    except Exception:
        return None

async def _handle(request, call_next, body):
    t0 = time.time()
    err = None
    status = None
    try:
        resp = await call_next(request)
        status = resp.status_code
    except Exception as e:  # crash inside the app
        status, err, resp = 599, repr(e)[:300], None
        raise
    finally:
        t1 = time.time()
        if SERIALIZE and request.method in MUT:
            await asyncio.sleep(SETTLE)   # let the change stream deliver this request's changes
        rec = {"t": t0, "ms": round((t1 - t0) * 1000), "t_end": time.time(), "method": request.method,
               "path": request.url.path, "query": str(request.url.query)[:200], "status": status,
               "user": _who(request.headers.get("authorization", "")), "bot": request.headers.get("x-bot-role"),
               "corr": request.headers.get("x-correlation-id"), "serialized": SERIALIZE and request.method in MUT,
               "idem": request.headers.get("idempotency-key"), "body": body[:600].decode("utf8", "replace"), "err": err}
        with LOCK:
            LOG.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return resp

@app.middleware("http")
async def log_api(request: Request, call_next):
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    body = await request.body()
    if SERIALIZE and request.method in MUT:
        async with WRITE_LOCK:
            return await _handle(request, call_next, body)
    return await _handle(request, call_next, body)

@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    f = os.path.realpath(os.path.join(BUILD, path))
    if path and f.startswith(BUILD) and os.path.isfile(f):
        return FileResponse(f)
    return FileResponse(os.path.join(BUILD, "index.html"))

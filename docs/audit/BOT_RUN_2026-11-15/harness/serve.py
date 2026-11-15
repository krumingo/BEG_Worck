"""Demo wrapper (outside the repo): real backend app + built frontend on one port,
plus a request log of every /api call (who, what, status, how long)."""
import os, sys, json, time, base64, threading
sys.path.insert(0, "/tmp/claude-0/wtmain/backend")
from server import app
from fastapi.responses import FileResponse
from starlette.requests import Request

BUILD = "/tmp/claude-0/wtmain/frontend/build"
LOG = open("/tmp/claude-0/demo/run/backend.jsonl", "a", buffering=1, encoding="utf8")
LOCK = threading.Lock()

def _who(auth):
    try:
        p = auth.split(".")[1]; p += "=" * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        return d.get("user_id") or d.get("sub")
    except Exception:
        return None

@app.middleware("http")
async def log_api(request: Request, call_next):
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    body = await request.body()
    t0 = time.time()
    err = None
    try:
        resp = await call_next(request)
        status = resp.status_code
    except Exception as e:  # crash inside the app
        status, err, resp = 599, repr(e)[:300], None
        raise
    finally:
        rec = {"t": t0, "ms": round((time.time() - t0) * 1000), "method": request.method,
               "path": request.url.path, "query": str(request.url.query)[:200], "status": status,
               "user": _who(request.headers.get("authorization", "")), "bot": request.headers.get("x-bot-role"),
               "idem": request.headers.get("idempotency-key"), "body": body[:600].decode("utf8", "replace"), "err": err}
        with LOCK:
            LOG.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return resp

@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    f = os.path.realpath(os.path.join(BUILD, path))
    if path and f.startswith(BUILD) and os.path.isfile(f):
        return FileResponse(f)
    return FileResponse(os.path.join(BUILD, "index.html"))

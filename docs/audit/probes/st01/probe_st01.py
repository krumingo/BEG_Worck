"""CLAUDE AUDIT probes on ST-01 (claude/st-01-staging-fixtures).

    cd <worktree>/backend && PYTHONPATH=. python <this file> <worktree>
PST-1 runner against a dead backend (closed port): exit code must not be 0 ("nothing failed")
PST-2 runner URL tricks: http://127.0.0.1.evil.com, http://localhost@evil.com, userinfo → refused w/o --allow-remote
PST-3 seed target: production names refused even with --allow-remote (begwork, BegWork_x, $DB_NAME)
PST-4 seed target: mongodb+srv:// (Atlas) without --allow-remote → refused
"""
import json, os, subprocess, sys, tempfile
W = sys.argv[1]
sys.path.insert(0, os.path.join(W, "ops", "staging"))
import run_scenarios as rs
import seed_synthetic as ss
fails = []

out = os.path.join(tempfile.mkdtemp(), "r.json")
env = dict(os.environ, ST01_SEED_PASSWORD="x" * 16)
p = subprocess.run([sys.executable, os.path.join(W, "ops/staging/run_scenarios.py"), "--base-url",
                    "http://127.0.0.1:9", "--out", out, "--timeout", "2"], env=env, capture_output=True, text=True)
summ = json.load(open(out))["summary"] if os.path.exists(out) else None
print("PST-1 exit", p.returncode, summ)
if p.returncode == 0: fails.append("PST-1 dead backend exits 0")

for u in ("http://127.0.0.1.evil.com:8001", "http://localhost@evil.com", "http://evil.com#@127.0.0.1",
          "http://[::1].evil.com", "file:///etc/passwd", "http://LOCALHOST"):
    try:
        rs.check_base_url(u, False); ok = True
    except Exception:
        ok = False
    expect_ok = u == "http://LOCALHOST"
    if ok != expect_ok: fails.append("PST-2 %s accepted=%s" % (u, ok))

for name in ("begwork", "BegWork_prod", "begwork_system"):
    try:
        ss.check_target(url="mongodb://prod:27017", db_name=name, system_db_name="s1", confirm_db=name,
                        allow_remote=True, env={}); fails.append("PST-3 %s accepted" % name)
    except ss.SeedRefused:
        pass
try:
    ss.check_target(url="mongodb://x", db_name="st", system_db_name="sys", confirm_db="st",
                    allow_remote=True, env={"DB_NAME": "st"}); fails.append("PST-3 $DB_NAME accepted")
except ss.SeedRefused:
    pass
try:
    ss.check_target(url="mongodb+srv://u:p@cluster0.abc.mongodb.net", db_name="st", system_db_name="sys",
                    confirm_db="st", allow_remote=False, env={}); fails.append("PST-4 srv accepted")
except ss.SeedRefused:
    pass
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)

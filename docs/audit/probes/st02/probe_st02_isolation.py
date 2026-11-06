"""CLAUDE AUDIT probe ST-02: does ops/staging/isolation_check.py catch non-isolated staging models?

    python3 probe_st02_isolation.py <PR worktree>
Start from a model that PASSES, apply one hostile mutation at a time, expect ISOLATION FAIL.
"""
import copy, sys
sys.path.insert(0, sys.argv[1] + "/ops/staging")
import isolation_check as ic

P = "begwork-staging"
BASE = {
    "name": P,
    "services": {
        "backend": {"container_name": P + "-backend", "networks": {"st02": None},
                    "environment": {"ENV": "staging", "PERMISSION_SERVICE_MODE": "enforce",
                                    "MONGO_URL": "mongodb://mongo:27017/?replicaSet=rs0", "DB_NAME": "st02_staging", "PUBLIC_URL": "http://127.0.0.1:18080",
                                    "JWT_SECRET": "x"}},
        "frontend": {"container_name": P + "-frontend", "networks": {"st02": None},
                     "ports": [{"host_ip": "127.0.0.1", "published": "18080", "target": 80}]},
        "mongo": {"container_name": P + "-mongo", "networks": {"st02": None},
                  "command": ["--replSet", "rs0", "--bind_ip_all"],
                  "volumes": [{"type": "volume", "source": "st02-mongo-data", "target": "/data/db"}]},
    },
    "networks": {"st02": {"name": P + "_net"}},
    "volumes": {"st02-mongo-data": {"name": P + "_mongo_data"}},
}
assert ic.check(BASE, P, "18080", "enforce") == [], ic.check(BASE, P, "18080", "enforce")


def mut(desc, fn):
    m = copy.deepcopy(BASE); fn(m)
    errs = ic.check(m, P, "18080", "enforce")
    print("%-4s %s" % ("ok" if errs else "MISS", desc))
    return bool(errs)


cases = [
    ("backend MONGO_URL -> external production cluster",
     lambda m: m["services"]["backend"]["environment"].update(MONGO_URL="mongodb+srv://u:p@prod-cluster.mongodb.net")),
    ("backend MONGO_URL -> host LAN address of the production mongo",
     lambda m: m["services"]["backend"]["environment"].update(MONGO_URL="mongodb://192.168.1.10:27017")),
    ("backend DB_NAME = production database name (begwork)",
     lambda m: m["services"]["backend"]["environment"].update(DB_NAME="begwork")),
    ("backend bind-mounts the production data dir /volume1/docker/begwork",
     lambda m: m["services"]["backend"].update(volumes=[{"type": "bind", "source": "/volume1/docker/begwork", "target": "/data"}])),
    ("backend mounts /var/run/docker.sock",
     lambda m: m["services"]["backend"].update(volumes=[{"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}])),
    ("backend privileged: true", lambda m: m["services"]["backend"].update(privileged=True)),
    ("mongo publishes 0.0.0.0:27017",
     lambda m: m["services"]["mongo"].update(ports=[{"host_ip": "", "published": "27017", "target": 27017}])),
    ("mongo data on an EXTERNAL (production) volume",
     lambda m: m["volumes"]["st02-mongo-data"].update(external=True, name="begwork_mongo_data")),
    ("backend network_mode host", lambda m: m["services"]["backend"].update(network_mode="host")),
    # extra cases added for ST-02-C01
    ("backend MONGO_URL host 'mongo.evil.com' (prefix trick)",
     lambda m: m["services"]["backend"]["environment"].update(MONGO_URL="mongodb://mongo.evil.com:27017/?replicaSet=rs0")),
    ("backend MONGO_URL with second host in seed list",
     lambda m: m["services"]["backend"]["environment"].update(MONGO_URL="mongodb://mongo:27017,10.0.0.5:27017/?replicaSet=rs0")),
    ("backend MONGO_URL 'mongodb://user@...@prod' userinfo trick",
     lambda m: m["services"]["backend"]["environment"].update(MONGO_URL="mongodb://mongo:x@prod.example.com:27017/")),
    ("backend DB_NAME 'BEGWORK' (case)", lambda m: m["services"]["backend"]["environment"].update(DB_NAME="BEGWORK")),
    ("backend BEG_SYSTEM_DB = begwork_system",
     lambda m: m["services"]["backend"]["environment"].update(BEG_SYSTEM_DB="begwork_system")),
    ("frontend bind-mounts /volume1/docker/begwork",
     lambda m: m["services"]["frontend"].update(volumes=[{"type": "bind", "source": "/volume1/docker/begwork/x", "target": "/x"}])),
    ("mongo bind-mounts the production mongo data dir",
     lambda m: m["services"]["mongo"].update(volumes=[{"type": "bind", "source": "/volume1/docker/begwork/mongo", "target": "/data/db"}])),
    ("backend cap_add SYS_ADMIN", lambda m: m["services"]["backend"].update(cap_add=["SYS_ADMIN"])),
    ("backend pid: host", lambda m: m["services"]["backend"].update(pid="host")),
    # extra cases added for ST-02-C02 (FG-5)
    ("backend PUBLIC_URL = public production address",
     lambda m: m["services"]["backend"]["environment"].update(PUBLIC_URL="https://app.begwork.bg")),
    ("backend PUBLIC_URL = 127.0.0.1.evil.com", lambda m: m["services"]["backend"]["environment"].update(
        PUBLIC_URL="http://127.0.0.1.evil.com:18080")),
    ("backend CORS_ORIGINS = *", lambda m: m["services"]["backend"]["environment"].update(CORS_ORIGINS="*")),
    ("backend CORS_ORIGINS includes an external origin", lambda m: m["services"]["backend"]["environment"].update(
        CORS_ORIGINS="http://127.0.0.1:18080,https://evil.example")),
    ("frontend build arg REACT_APP_BACKEND_URL external", lambda m: m["services"]["frontend"].update(
        build={"args": {"REACT_APP_BACKEND_URL": "https://app.begwork.bg"}})),
    ("mongo env BOOTSTRAP_ADMIN_PASSWORD", lambda m: m["services"]["mongo"].update(
        environment={"BOOTSTRAP_ADMIN_PASSWORD": "x"})),
    ("backend SEED_ADMIN_EMAIL", lambda m: m["services"]["backend"]["environment"].update(SEED_ADMIN_EMAIL="a@b")),
]
missed = [d for d, f in cases if not mut(d, f)]
print("MISSED:", missed or "none")
sys.exit(1 if missed else 0)

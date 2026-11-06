#!/usr/bin/env python3
"""ST-02 — prove that a merged compose model is the isolated staging project.

    docker compose -p <project> -f docker-compose.yml -f docker-compose.staging.yml config --format json \
        | ST02_PROJECT=<project> ST02_HTTP_PORT=<port> ST02_MODE=<flag> python3 isolation_check.py

Prints one line per finding and ``ISOLATION PASS`` / ``ISOLATION FAIL``. Never prints an
environment value (the model contains the staging .env); only key names and fixed facts.
Stdlib only (runs in the verifier image with --network none).

Rules:
* project name = ST02_PROJECT and starts with ``begwork-staging``;
* services are exactly backend, frontend, mongo; container names are ``<project>-<service>``;
  no production container name (``begwork-backend``, ``begwork-frontend``) anywhere;
* the only published port is frontend 127.0.0.1:ST02_HTTP_PORT -> 80 (never 8080, never 0.0.0.0);
* every service is only on the network ``<project>_net``; no external network, no host network;
* MongoDB is a replica set (``--replSet``) on the named volume ``<project>_mongo_data``;
* backend ENV=staging and PERMISSION_SERVICE_MODE=ST02_MODE;
* no backend environment key for real email, billing or LLM providers;
* ST02-1 (ST-02-C01): the backend database must be the staging stack's own MongoDB. Every
  ``mongodb://`` value in the backend environment (``MONGO_URL`` is required) has the plain
  ``mongodb://`` scheme (never ``mongodb+srv``) and only the hosts ``mongo`` /
  ``<project>-mongo``, or a host the staging configuration explicitly allows
  (``ST02_ALLOWED_MONGO_HOSTS``, comma-separated hostnames; never an IP address, never a
  wildcard); ``DB_NAME`` (required) and ``BEG_SYSTEM_DB`` are not production names
  (``begwork``, ``begwork_beg``, ``begwork_system``) and not in the ``begwork*`` family;
* no service bind-mounts anything outside the staging root (``ST02_BASE``), anything under
  the production root ``/volume1/docker/begwork`` or a Docker socket; named volumes are the
  project's own non-external ``<project>_*`` volumes;
* no service is ``privileged``, adds capabilities/devices, sets an ``unconfined``/disabled
  ``security_opt`` or shares a host pid/ipc/uts/userns/cgroup namespace; no network uses the ``host`` driver;
* ST02_HTTP_PORT is not a production port (80, 443, 8001, 8080, 27017) and is 1024..65535.

Refusal = ``ISOLATION FAIL`` and exit 1; the callers (staging_up.py before the staging MongoDB
starts, staging_deploy.sh before any container action) then start nothing.
"""
import json
import os
import re
import sys

PRODUCTION_CONTAINERS = {"begwork-backend", "begwork-frontend"}
SERVICES = {"backend", "frontend", "mongo"}
FORBIDDEN_ENV = re.compile(r"(STRIPE|SMTP|SENDGRID|MAILGUN|POSTMARK|RESEND|SES_|TWILIO|EMERGENT|OPENAI|ANTHROPIC|LLM)", re.I)
REQUIRED_ABSENT_VALUES = ("BILLING_PROVIDER",)
# Mirrors backend/app/master_data/index_bootstrap.py PRODUCTION_DATABASES / PRODUCTION_PREFIX
# (this file must stay stdlib-only and import nothing from the application).
PRODUCTION_DATABASES = {"begwork", "begwork_beg", "begwork_system"}
PRODUCTION_DB_PREFIX = "begwork"
PRODUCTION_BASE = "/volume1/docker/begwork"
PRODUCTION_PORTS = {"80", "443", "8001", "8080", "27017"}
DB_ENV_KEYS = ("DB_NAME", "BEG_SYSTEM_DB")
HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
DANGEROUS_KEYS = ("cap_add", "devices", "device_cgroup_rules")
DOCKER_SOCKET_DIRS = {"/var/run", "/run", "/var/run/docker", "/run/docker"}
HOST_NAMESPACES = ("pid", "ipc", "uts", "userns_mode", "cgroup")


def parse_allowed_hosts(raw):
    """``ST02_ALLOWED_MONGO_HOSTS`` -> (set of hostnames, [errors]). Never an IP, never a wildcard."""
    hosts, errors = set(), []
    for h in (raw or "").split(","):
        h = h.strip().lower()
        if not h:
            continue
        if IPV4.match(h) or ":" in h or not HOSTNAME.match(h):
            errors.append("ST02_ALLOWED_MONGO_HOSTS entry is not a plain hostname (IP addresses and wildcards are refused)")
        else:
            hosts.add(h)
    return hosts, errors


def mongo_url_problem(value, allowed):
    """None if ``value`` is a plain mongodb:// URL to allowed hosts only, else a reason (never the value)."""
    value = value.strip()
    scheme, sep, rest = value.partition("://")
    scheme = scheme.lower()
    if not sep:
        return "is not a mongodb:// URL"
    if scheme == "mongodb+srv":
        return "uses mongodb+srv (an external DNS-resolved cluster); only the staging MongoDB is allowed"
    if scheme != "mongodb":
        return "uses the scheme %r; only mongodb:// to the staging MongoDB is allowed" % scheme
    hostpart = re.split(r"[/?]", rest, maxsplit=1)[0]
    hostpart = hostpart.rpartition("@")[2]
    if not hostpart:
        return "has no host"
    for h in hostpart.split(","):
        h = h.strip().lower()
        if h.startswith("["):
            return "points to an IP address, not the staging MongoDB service"
        name, _, port = h.partition(":")
        if port and port != "27017":
            return "uses a port other than 27017"
        if name not in allowed:
            if IPV4.match(name) or name in ("localhost", "host.docker.internal", "gateway.docker.internal"):
                return "points to a host/LAN address, not the staging MongoDB service"
            return "points to a host other than the staging MongoDB service"
    return None


def is_production_db(name):
    n = (name or "").strip().lower()
    return n in PRODUCTION_DATABASES or n.startswith(PRODUCTION_DB_PREFIX)


def _under(path, root):
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def volume_problems(name, svc, model, project, base):
    out = []
    top = model.get("volumes") or {}
    for v in svc.get("volumes") or []:
        if isinstance(v, str):  # short syntax should not appear in `compose config --format json`
            out.append("service %s has an unparsed volume entry" % name)
            continue
        vtype, src = v.get("type"), str(v.get("source") or "")
        if vtype == "bind":
            norm = os.path.normpath(src) if src.startswith("/") else src
            if "docker.sock" in src or norm in DOCKER_SOCKET_DIRS:
                out.append("service %s mounts the Docker socket" % name)
            elif not src.startswith("/"):
                out.append("service %s bind-mounts a relative path" % name)
            elif norm == "/":
                out.append("service %s bind-mounts the host root /" % name)
            elif _under(src, PRODUCTION_BASE):
                out.append("service %s bind-mounts the production root %s" % (name, PRODUCTION_BASE))
            elif not base:
                out.append("service %s has a bind mount but the staging root (ST02_BASE) is unknown" % name)
            elif not _under(src, base) or os.path.normpath(src) == os.path.normpath(base):
                out.append("service %s bind-mounts a path outside the staging root" % name)
        elif vtype == "volume":
            decl = top.get(src) if src else None
            if decl is None:
                out.append("service %s uses an undeclared/anonymous volume source" % name)
            elif decl.get("external") or not str(decl.get("name", "")).startswith(project + "_"):
                out.append("service %s volume %s is not an own non-external %s_* volume" % (name, src, project))
        elif vtype == "tmpfs":
            pass
        else:
            out.append("service %s has a %s mount" % (name, vtype))
    return out


def check(model, project, port, mode, base=None, allowed_mongo_hosts=""):
    errors = []

    def err(msg):
        errors.append(msg)

    if not re.match(r"^begwork-staging[a-z0-9-]*$", project or ""):
        err("ST02_PROJECT %r is not a begwork-staging project" % project)
    if model.get("name") != project:
        err("compose project name is %r, expected %r" % (model.get("name"), project))
    services = model.get("services") or {}
    if set(services) != SERVICES:
        err("services are %s, expected %s" % (sorted(services), sorted(SERVICES)))
    published = []
    for name, svc in sorted(services.items()):
        cname = svc.get("container_name")
        if cname in PRODUCTION_CONTAINERS:
            err("service %s uses the production container name %s" % (name, cname))
        if cname != "%s-%s" % (project, name):
            err("service %s container_name %r, expected %s-%s" % (name, cname, project, name))
        if svc.get("network_mode"):
            err("service %s sets network_mode %r" % (name, svc.get("network_mode")))
        nets = sorted((svc.get("networks") or {}).keys())
        if nets != ["st02"]:
            err("service %s networks %s, expected only st02" % (name, nets))
        for p in svc.get("ports") or []:
            published.append((name, str(p.get("host_ip", "")), str(p.get("published", "")), int(p.get("target", 0))))
    if published != [("frontend", "127.0.0.1", str(port), 80)]:
        err("published ports %s, expected only frontend 127.0.0.1:%s->80" % (published, port))
    if any(pub == "8080" for _, _, pub, _ in published):
        err("production port 8080 is published")
    networks = model.get("networks") or {}
    st02 = networks.get("st02") or {}
    if st02.get("name") != "%s_net" % project or st02.get("external"):
        err("network st02 must be the own non-external network %s_net" % project)
    for key, net in networks.items():
        if net.get("external"):
            err("external network %s is used" % key)
    mongo = services.get("mongo") or {}
    if "--replSet" not in (mongo.get("command") or []):
        err("mongo is not started as a replica set")
    vols = [v.get("source") for v in mongo.get("volumes") or []]
    named = (model.get("volumes") or {}).get(vols[0] if vols else "", {})
    if not vols or named.get("name") != "%s_mongo_data" % project or named.get("external"):
        err("mongo data must be the own named volume %s_mongo_data" % project)
    env = (services.get("backend") or {}).get("environment") or {}
    if env.get("ENV") != "staging":
        err("backend ENV is not staging")
    if env.get("PERMISSION_SERVICE_MODE") != mode:
        err("backend PERMISSION_SERVICE_MODE differs from the staging parameter")
    bad = sorted(k for k in env if FORBIDDEN_ENV.search(k) or k in REQUIRED_ABSENT_VALUES)
    if bad:
        err("backend environment has real-provider keys: %s" % bad)

    # ---- ST02-1: the database the backend writes to
    allowed, host_errors = parse_allowed_hosts(allowed_mongo_hosts)
    for e in host_errors:
        err(e)
    allowed |= {"mongo", "%s-mongo" % project}
    if not str(env.get("MONGO_URL") or "").strip():
        err("backend MONGO_URL is missing (it must point to the staging MongoDB service)")
    for key in sorted(env):
        val = str(env.get(key) or "")
        if key == "MONGO_URL" or val.strip().lower().startswith("mongodb"):
            problem = mongo_url_problem(val, allowed) if val.strip() else None
            if problem:
                err("backend %s %s" % (key, problem))
    if not str(env.get("DB_NAME") or "").strip():
        err("backend DB_NAME is missing")
    for key in DB_ENV_KEYS:
        if env.get(key) is not None and is_production_db(str(env.get(key))):
            err("backend %s is a production database name (begwork / begwork_beg / begwork_system / begwork*)" % key)

    # ---- ST02-1: mounts, privileges, host namespaces (every service)
    for name, svc in sorted(services.items()):
        errors.extend(volume_problems(name, svc, model, project, base))
        if svc.get("privileged"):
            err("service %s is privileged" % name)
        for k in DANGEROUS_KEYS:
            if svc.get(k):
                err("service %s sets %s" % (name, k))
        if any(re.search(r"unconfined|disable", str(o), re.I) for o in svc.get("security_opt") or []):
            err("service %s weakens security_opt (unconfined/disabled)" % name)
        for k in HOST_NAMESPACES:
            if str(svc.get(k) or "").startswith("host"):
                err("service %s shares the host %s namespace" % (name, k))
    for key, net in networks.items():
        if str((net or {}).get("driver") or "") == "host":
            err("network %s uses the host driver" % key)
    p = str(port or "")
    if p in PRODUCTION_PORTS or not p.isdigit() or not 1024 <= int(p) <= 65535:
        err("ST02_HTTP_PORT %r is a production/privileged port" % p)
    return errors


def main():
    try:
        model = json.load(sys.stdin)
    except ValueError:
        print("compose config output is not JSON")
        print("ISOLATION FAIL")
        return 1
    project = os.environ.get("ST02_PROJECT", "")
    port = os.environ.get("ST02_HTTP_PORT", "")
    mode = os.environ.get("ST02_MODE", "")
    errors = check(model, project, port, mode, base=os.environ.get("ST02_BASE", ""),
                   allowed_mongo_hosts=os.environ.get("ST02_ALLOWED_MONGO_HOSTS", ""))
    for e in errors:
        print("isolation: " + e)
    if not errors:
        print("isolation: project %s, containers %s-{backend,frontend,mongo}, only 127.0.0.1:%s->frontend:80, "
              "network %s_net, mongo replica set on %s_mongo_data, ENV=staging, flag = parameter, "
              "no real-provider keys, backend database = staging MongoDB (not a production name), "
              "no bind mount outside the staging root, no docker socket, not privileged" % (project, project, port, project, project))
    print("ISOLATION PASS" if not errors else "ISOLATION FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

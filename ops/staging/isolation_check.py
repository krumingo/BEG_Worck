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
* no backend environment key for real email, billing or LLM providers.
"""
import json
import os
import re
import sys

PRODUCTION_CONTAINERS = {"begwork-backend", "begwork-frontend"}
SERVICES = {"backend", "frontend", "mongo"}
FORBIDDEN_ENV = re.compile(r"(STRIPE|SMTP|SENDGRID|MAILGUN|POSTMARK|RESEND|SES_|TWILIO|EMERGENT|OPENAI|ANTHROPIC|LLM)", re.I)
REQUIRED_ABSENT_VALUES = ("BILLING_PROVIDER",)


def check(model, project, port, mode):
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
    errors = check(model, project, port, mode)
    for e in errors:
        print("isolation: " + e)
    if not errors:
        print("isolation: project %s, containers %s-{backend,frontend,mongo}, only 127.0.0.1:%s->frontend:80, "
              "network %s_net, mongo replica set on %s_mongo_data, ENV=staging, flag = parameter, "
              "no real-provider keys" % (project, project, port, project, project))
    print("ISOLATION PASS" if not errors else "ISOLATION FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

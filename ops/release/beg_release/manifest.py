"""Release manifest (beg.release-manifest/v1) and deployment record (beg.deployment-record/v1).

The manifest describes WHAT is released and is immutable after build: its ``release``
object is hashed into ``release_sha256``. What HAPPENED at deploy/rollback time is a
separate deployment record that references the manifest hash. Both are validated
strictly (unknown keys, formats, secret-like content, migration policy).
"""
import hashlib
import re

from .inputs import canonical_json

MANIFEST_SCHEMA = "beg.release-manifest/v1"
RECORD_SCHEMA = "beg.deployment-record/v1"
ENVIRONMENTS = ("development", "test", "staging", "production")
APPROVAL_TYPES = ("merge", "review", "deploy", "validation")
RECORD_ACTIONS = ("adopt", "deploy", "rollback")
RECORD_STATUSES = ("ADOPTED", "DEPLOYED", "PRECHECK_FAILED", "ROLLED_BACK", "ROLLBACK_DONE", "ROLLBACK_FAILED")

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RELEASE_ID = re.compile(r"^rel-\d{8}T\d{6}Z-[0-9a-f]{12}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
PATHLIKE = re.compile(r"^/[A-Za-z0-9._/-]*$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/@%+=,-]*$")

SECRET_VALUE_PATTERNS = [
    re.compile(r"mongodb(\+srv)?://[^\s/]*:[^\s@]*@", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    re.compile(r"(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{6,}", re.I),
]
SECRET_KEY_NAMES = re.compile(r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)", re.I)

# Required keys per object; the JSON Schema file mirrors these (parity-tested).
REQUIRED = {
    "manifest": ["schema", "release", "release_sha256"],
    "release": ["release_id", "app", "artifact", "environment", "deployment", "schema_version",
                "configuration", "feature_flags", "entitlements", "build", "services_to_rebuild",
                "previous", "rollback_target", "approvals", "smoke", "created_at", "created_by"],
    "app": ["repository", "commit", "tree", "commit_time", "reachable_from"],
    "artifact": ["format", "file", "sha256", "size_bytes", "file_count", "tree_verified", "legacy_extras"],
    "deployment": ["id", "layout", "tenant_scope"],
    "tenant_scope": ["mode", "tenants"],
    "schema_version": ["app_schema_version", "migrations"],
    "migrations": ["declared", "policy", "approval_ref"],
    "configuration": ["version", "layout_source_commit", "layout_files", "required_env_keys", "build_args"],
    "entitlements": ["status", "snapshot", "reference"],
    "build": ["tool", "python", "git", "services", "unpinned_base_images", "rebuild_reason",
              "tools_source_commit", "tools"],
    "service": ["container", "dockerfile", "base_images", "copy_sources", "input_file_count", "fingerprint"],
    "release_ref": ["release_id", "commit", "tree", "release_sha256"],
    "approval": ["type", "ref"],
    "smoke": ["base_url", "health_path", "http_paths", "containers", "health_timeout_sec",
              "restart_sample_sec", "log_service"],
    "record": ["schema", "action", "status", "release_id", "release_sha256", "commit", "tree",
               "environment", "deployment_id", "started_at", "finished_at", "actor",
               "previous_release_id", "rollback_target_release_id", "services_rebuilt",
               "migrations", "verification", "smoke", "failure", "evidence_dir"],
}


def release_sha256(release):
    return hashlib.sha256(canonical_json(release)).hexdigest()


class _V:
    def __init__(self):
        self.errors = []

    def err(self, path, msg):
        self.errors.append("%s: %s" % (path, msg))

    def obj(self, value, path, kind):
        if not isinstance(value, dict):
            self.err(path, "must be an object")
            return False
        missing = [k for k in REQUIRED[kind] if k not in value]
        extra = [k for k in value if k not in REQUIRED[kind]]
        if missing:
            self.err(path, "missing keys %s" % missing)
        if extra:
            self.err(path, "unknown keys %s" % extra)
        return not missing

    def match(self, value, path, rx, what):
        if not isinstance(value, str) or not rx.match(value):
            self.err(path, "must be %s" % what)

    def integer(self, value, path, minimum=0):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            self.err(path, "must be an integer >= %d" % minimum)

    def str_list(self, value, path, rx=None, what="string", allow_empty=True):
        if not isinstance(value, list) or (not allow_empty and not value):
            self.err(path, "must be a %slist" % ("" if allow_empty else "non-empty "))
            return
        for i, item in enumerate(value):
            if not isinstance(item, str) or (rx and not rx.match(item)):
                self.err("%s[%d]" % (path, i), "must be %s" % what)
        if len(set(value)) != len(value):
            self.err(path, "must not contain duplicates")


def _scan_secrets(value, path, v):
    if isinstance(value, dict):
        for k, item in value.items():
            if SECRET_KEY_NAMES.search(k) and isinstance(item, str) and item and not ENV_KEY.match(item):
                v.err("%s.%s" % (path, k), "secret-like key carries a value")
            _scan_secrets(item, "%s.%s" % (path, k), v)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _scan_secrets(item, "%s[%d]" % (path, i), v)
    elif isinstance(value, str):
        for rx in SECRET_VALUE_PATTERNS:
            if rx.search(value):
                v.err(path, "secret-like value is not allowed in release metadata")
                break


def _release_ref(value, path, v):
    if value is None:
        return
    if v.obj(value, path, "release_ref"):
        v.match(value["release_id"], path + ".release_id", RELEASE_ID, "a release id")
        v.match(value["commit"], path + ".commit", HEX40, "a 40-hex commit")
        v.match(value["tree"], path + ".tree", HEX40, "a 40-hex tree")
        v.match(value["release_sha256"], path + ".release_sha256", HEX64, "a sha256")


def validate_manifest(m):
    v = _V()
    if not v.obj(m, "manifest", "manifest"):
        return v.errors
    if m["schema"] != MANIFEST_SCHEMA:
        v.err("manifest.schema", "must be %s" % MANIFEST_SCHEMA)
    r = m["release"]
    if not v.obj(r, "release", "release"):
        return v.errors
    v.match(r["release_id"], "release.release_id", RELEASE_ID, "rel-<UTC>-<commit12>")
    if v.obj(r["app"], "release.app", "app"):
        a = r["app"]
        v.match(a["commit"], "release.app.commit", HEX40, "a 40-hex commit")
        v.match(a["tree"], "release.app.tree", HEX40, "a 40-hex tree")
        v.integer(a["commit_time"], "release.app.commit_time", 1)
        if not isinstance(a["repository"], str) or not a["repository"]:
            v.err("release.app.repository", "must be a non-empty string")
        if not isinstance(a["reachable_from"], (str, type(None))):
            v.err("release.app.reachable_from", "must be a ref name or null")
        if isinstance(r["release_id"], str) and isinstance(a.get("commit"), str) and \
                not r["release_id"].endswith(a["commit"][:12]):
            v.err("release.release_id", "must end with the first 12 hex of app.commit")
    if v.obj(r["artifact"], "release.artifact", "artifact"):
        art = r["artifact"]
        if art["format"] != "tar-pax-git-objects-v1":
            v.err("release.artifact.format", "must be tar-pax-git-objects-v1")
        if art["file"] != "artifact.tar":
            v.err("release.artifact.file", "must be artifact.tar")
        v.match(art["sha256"], "release.artifact.sha256", HEX64, "a sha256")
        v.integer(art["size_bytes"], "release.artifact.size_bytes", 1)
        v.integer(art["file_count"], "release.artifact.file_count", 1)
        if art["tree_verified"] is not True:
            v.err("release.artifact.tree_verified", "must be true (build fails closed otherwise)")
        if not isinstance(art["legacy_extras"], dict):
            v.err("release.artifact.legacy_extras", "must be an object")
        else:
            for p, blob in art["legacy_extras"].items():
                v.match(blob, "release.artifact.legacy_extras.%s" % p, HEX40, "a blob sha")
    if r["environment"] not in ENVIRONMENTS:
        v.err("release.environment", "must be one of %s" % (ENVIRONMENTS,))
    if v.obj(r["deployment"], "release.deployment", "deployment"):
        d = r["deployment"]
        v.match(d["id"], "release.deployment.id", NAME, "a deployment id")
        v.match(d["layout"], "release.deployment.layout", NAME, "a layout id")
        if v.obj(d["tenant_scope"], "release.deployment.tenant_scope", "tenant_scope"):
            if d["tenant_scope"]["mode"] not in ("deployment-wide", "tenant-list"):
                v.err("release.deployment.tenant_scope.mode", "must be deployment-wide or tenant-list")
            v.str_list(d["tenant_scope"]["tenants"], "release.deployment.tenant_scope.tenants", NAME, "a tenant id")
    if v.obj(r["schema_version"], "release.schema_version", "schema_version"):
        sv = r["schema_version"]
        if not isinstance(sv["app_schema_version"], (str, type(None))):
            v.err("release.schema_version.app_schema_version", "must be a string or null")
        if v.obj(sv["migrations"], "release.schema_version.migrations", "migrations"):
            mig = sv["migrations"]
            v.str_list(mig["declared"], "release.schema_version.migrations.declared", NAME, "a migration id")
            if mig["policy"] != "NOT_RUN_BY_DEFAULT":
                v.err("release.schema_version.migrations.policy", "must be NOT_RUN_BY_DEFAULT")
            if isinstance(mig["declared"], list) and mig["declared"] and not mig["approval_ref"]:
                v.err("release.schema_version.migrations.approval_ref",
                      "declared migrations require a separate approval reference")
    if v.obj(r["configuration"], "release.configuration", "configuration"):
        c = r["configuration"]
        v.match(c["version"], "release.configuration.version", HEX64, "a sha256")
        v.match(c["layout_source_commit"], "release.configuration.layout_source_commit", HEX40, "a commit")
        if not isinstance(c["layout_files"], dict) or not c["layout_files"]:
            v.err("release.configuration.layout_files", "must be a non-empty object")
        else:
            for name, digest in c["layout_files"].items():
                v.match(digest, "release.configuration.layout_files.%s" % name, HEX64, "a sha256")
        v.str_list(c["required_env_keys"], "release.configuration.required_env_keys", ENV_KEY, "an env KEY name")
        if not isinstance(c["build_args"], dict):
            v.err("release.configuration.build_args", "must be an object")
    if not isinstance(r["feature_flags"], dict):
        v.err("release.feature_flags", "must be an object")
    else:
        for key, spec in r["feature_flags"].items():
            if not ENV_KEY.match(key):
                v.err("release.feature_flags", "invalid flag key %r" % key)
            if not isinstance(spec, dict) or set(spec) != {"expected", "source"} \
                    or not isinstance(spec.get("expected"), str) or not SAFE_VALUE.match(spec.get("expected", "")):
                v.err("release.feature_flags.%s" % key, "must be {expected: safe string, source: string}")
    if v.obj(r["entitlements"], "release.entitlements", "entitlements"):
        if r["entitlements"]["status"] not in ("NOT_IMPLEMENTED", "SNAPSHOT"):
            v.err("release.entitlements.status", "must be NOT_IMPLEMENTED or SNAPSHOT")
    if v.obj(r["build"], "release.build", "build"):
        b = r["build"]
        if not isinstance(b["services"], dict) or not b["services"]:
            v.err("release.build.services", "must be a non-empty object")
        else:
            for name, svc in b["services"].items():
                p = "release.build.services.%s" % name
                v.match(name, p, NAME, "a service name")
                if v.obj(svc, p, "service"):
                    v.match(svc["container"], p + ".container", NAME, "a container name")
                    v.match(svc["fingerprint"], p + ".fingerprint", HEX64, "a sha256")
                    v.integer(svc["input_file_count"], p + ".input_file_count", 1)
        v.str_list(b["unpinned_base_images"], "release.build.unpinned_base_images")
        v.match(b["tools_source_commit"], "release.build.tools_source_commit", HEX40, "a commit")
        if not isinstance(b["tools"], dict) or not b["tools"]:
            v.err("release.build.tools", "must be a non-empty {path: sha256} object")
        else:
            for tpath, digest in b["tools"].items():
                if not re.match(r"^tools/[A-Za-z0-9._/-]+$", tpath) or ".." in tpath:
                    v.err("release.build.tools", "invalid tool path %r" % tpath)
                v.match(digest, "release.build.tools.%s" % tpath, HEX64, "a sha256")
        if isinstance(r["services_to_rebuild"], list) and isinstance(b.get("services"), dict):
            unknown = [s for s in r["services_to_rebuild"] if s not in b["services"]]
            if unknown:
                v.err("release.services_to_rebuild", "unknown services %s" % unknown)
    v.str_list(r["services_to_rebuild"], "release.services_to_rebuild", NAME, "a service name")
    _release_ref(r["previous"], "release.previous", v)
    _release_ref(r["rollback_target"], "release.rollback_target", v)
    if r["previous"] is not None and r["rollback_target"] != r["previous"]:
        v.err("release.rollback_target", "must equal release.previous (immediate rollback target)")
    if not isinstance(r["approvals"], list):
        v.err("release.approvals", "must be a list")
    else:
        for i, ap in enumerate(r["approvals"]):
            if v.obj(ap, "release.approvals[%d]" % i, "approval"):
                if ap["type"] not in APPROVAL_TYPES:
                    v.err("release.approvals[%d].type" % i, "must be one of %s" % (APPROVAL_TYPES,))
                if not isinstance(ap["ref"], str) or not ap["ref"].strip():
                    v.err("release.approvals[%d].ref" % i, "must be a non-empty reference")
        if r["environment"] == "production" and not any(
                isinstance(ap, dict) and ap.get("type") == "deploy" for ap in r["approvals"]):
            v.err("release.approvals", "a production release requires a deploy approval reference")
    if v.obj(r["smoke"], "release.smoke", "smoke"):
        s = r["smoke"]
        if not isinstance(s["base_url"], str) or not re.match(r"^https?://[A-Za-z0-9.:-]+$", s["base_url"]):
            v.err("release.smoke.base_url", "must be http(s)://host[:port]")
        v.match(s["health_path"], "release.smoke.health_path", PATHLIKE, "an absolute path")
        v.str_list(s["http_paths"], "release.smoke.http_paths", PATHLIKE, "an absolute path", allow_empty=False)
        v.str_list(s["containers"], "release.smoke.containers", NAME, "a container name", allow_empty=False)
        v.integer(s["health_timeout_sec"], "release.smoke.health_timeout_sec", 5)
        v.integer(s["restart_sample_sec"], "release.smoke.restart_sample_sec", 0)
        v.match(s["log_service"], "release.smoke.log_service", NAME, "a service name")
        if isinstance(r.get("build"), dict) and isinstance(r["build"].get("services"), dict)                 and s["log_service"] not in r["build"]["services"]:
            v.err("release.smoke.log_service", "must be one of the built services")
    v.match(r["created_at"], "release.created_at", TS, "UTC YYYY-MM-DDTHH:MM:SSZ")
    v.match(r["created_by"], "release.created_by", NAME, "an actor name")
    v.match(m["release_sha256"], "manifest.release_sha256", HEX64, "a sha256")
    if not v.errors and m["release_sha256"] != release_sha256(r):
        v.err("manifest.release_sha256", "does not match the canonical hash of release (manifest was modified)")
    _scan_secrets(m, "manifest", v)
    return v.errors


def validate_record(rec):
    v = _V()
    if not v.obj(rec, "record", "record"):
        return v.errors
    if rec["schema"] != RECORD_SCHEMA:
        v.err("record.schema", "must be %s" % RECORD_SCHEMA)
    if rec["action"] not in RECORD_ACTIONS:
        v.err("record.action", "must be one of %s" % (RECORD_ACTIONS,))
    if rec["status"] not in RECORD_STATUSES:
        v.err("record.status", "must be one of %s" % (RECORD_STATUSES,))
    v.match(rec["release_id"], "record.release_id", RELEASE_ID, "a release id")
    v.match(rec["release_sha256"], "record.release_sha256", HEX64, "a sha256")
    v.match(rec["commit"], "record.commit", HEX40, "a commit")
    v.match(rec["tree"], "record.tree", HEX40, "a tree")
    if rec["environment"] not in ENVIRONMENTS:
        v.err("record.environment", "invalid environment")
    v.match(rec["deployment_id"], "record.deployment_id", NAME, "a deployment id")
    v.match(rec["started_at"], "record.started_at", TS, "a UTC timestamp")
    v.match(rec["finished_at"], "record.finished_at", TS, "a UTC timestamp")
    v.match(rec["actor"], "record.actor", NAME, "an actor name")
    for key in ("previous_release_id", "rollback_target_release_id"):
        if rec[key] != "NONE":
            v.match(rec[key], "record.%s" % key, RELEASE_ID, "a release id or NONE")
    v.str_list(rec["services_rebuilt"], "record.services_rebuilt", NAME, "a service name")
    if rec["migrations"] != "NOT_RUN":
        v.err("record.migrations", "must be NOT_RUN (W0-09A never runs migrations)")
    for key in ("verification", "smoke"):
        if rec[key] not in ("PASS", "FAIL", "SKIPPED"):
            v.err("record.%s" % key, "must be PASS, FAIL or SKIPPED")
    if not isinstance(rec["failure"], str) or not SAFE_VALUE.match(rec["failure"].replace(" ", "")):
        v.err("record.failure", "must be a safe string")
    v.match(rec["evidence_dir"], "record.evidence_dir", re.compile(r"^[A-Za-z0-9._:/-]+$"), "a path")
    _scan_secrets(rec, "record", v)
    return v.errors


def render_plan(manifest, previous_state=None):
    """Flat, shell-safe plan for the bash orchestrator (no JSON parsing in bash)."""
    r = manifest["release"]
    s = r["smoke"]
    plan = {
        "RELEASE_ID": r["release_id"],
        "RELEASE_SHA256": manifest["release_sha256"],
        "COMMIT": r["app"]["commit"],
        "TREE": r["app"]["tree"],
        "ENVIRONMENT": r["environment"],
        "DEPLOYMENT_ID": r["deployment"]["id"],
        "LAYOUT": r["deployment"]["layout"],
        "ARTIFACT_SHA256": r["artifact"]["sha256"],
        "ALL_SERVICES": ",".join(sorted(r["build"]["services"])),
        "SERVICES_TO_REBUILD": ",".join(r["services_to_rebuild"]),
        "CONTAINERS": ",".join(s["containers"]),
        "HTTP_PATHS": ",".join(s["http_paths"]),
        "HEALTH_BASE_URL": s["base_url"],
        "HEALTH_PATH": s["health_path"],
        "HEALTH_TIMEOUT_SEC": str(s["health_timeout_sec"]),
        "RESTART_SAMPLE_SEC": str(s["restart_sample_sec"]),
        "LOG_SERVICE": s["log_service"],
        "LOG_CONTAINER": r["build"]["services"][s["log_service"]]["container"],
        "PREVIOUS_RELEASE_ID": (r["previous"] or {}).get("release_id", "NONE"),
        "PREVIOUS_TREE": (r["previous"] or {}).get("tree", "NONE"),
        "SERVICE_CONTAINERS": ",".join("%s:%s" % (n, r["build"]["services"][n]["container"])
                                       for n in sorted(r["build"]["services"])),
        "LEGACY_EXTRAS": ",".join("%s=%s" % (k, v) for k, v in sorted(r["artifact"]["legacy_extras"].items()))
                         or "NONE",
        "FLAG_KEYS": ",".join(sorted(r["feature_flags"])),
        "MIGRATIONS_DECLARED": str(len(r["schema_version"]["migrations"]["declared"])),
    }
    for key, spec in sorted(r["feature_flags"].items()):
        plan["FLAG_EXPECT_" + key] = spec["expected"]
    for k, val in plan.items():
        if not ENV_KEY.match(k) or not SAFE_VALUE.match(val):
            raise ValueError("unsafe plan entry %s" % k)
    return plan


def plan_text(plan):
    return "".join("%s=%s\n" % (k, plan[k]) for k in sorted(plan))

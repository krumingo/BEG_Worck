#!/usr/bin/env python3
"""W0-09A — verify a release bundle and the deployment layout (never prints secret values).

On Synology it runs inside ``python:3.11-slim`` with ``--network none``; in tests and on
the build PC it runs with any Python 3.8+. Exit codes: 0 PASS, 2 FAIL, 3 usage error.

  bundle  --bundle B [--base BASE] [--mode deploy|adopt|inspect] [--stage DIR]
          [--plan-out F] [--report-out F] [--probe-dir D]
  tree    --dir D --tree SHA [--allow-extra PATH=BLOB ...] [--mode-hint-tar T] [--probe-dir D]
  manifest --manifest F
  record  --record F
  redact  --env ENVFILE --in LOG --out LOG
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from beg_release import gitobj, manifest as mf  # noqa: E402
from beg_release.gitobj import ReleaseError  # noqa: E402

ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


class Report:
    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail=""):
        self.checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" - " + detail) if detail else ""))
        return ok

    @property
    def ok(self):
        return all(c["status"] == "PASS" for c in self.checks)


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def read_sha256sums(path):
    sums = {}
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^([0-9a-f]{64})  ([A-Za-z0-9._/-]+)$", line)
            if not m or ".." in m.group(2) or m.group(2).startswith("/"):
                raise ReleaseError("malformed SHA256SUMS line: %r" % line)
            sums[m.group(2)] = m.group(1)
    return sums


def env_keys_and_values(env_path):
    """Parse KEY=VALUE lines. Values stay in memory only for comparisons/redaction."""
    data = {}
    with open(env_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ENV_LINE.match(line.rstrip("\r\n"))
            if m:
                value = m.group(2).strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                data[m.group(1)] = value
    return data


def cmd_bundle(a):
    rep = Report()
    bundle = os.path.abspath(a.bundle)
    try:
        sums = read_sha256sums(os.path.join(bundle, "SHA256SUMS"))
    except (OSError, ReleaseError) as exc:
        rep.add("sha256sums.readable", False, str(exc))
        return finish(rep, a)
    bad = [name for name, digest in sums.items()
           if not os.path.isfile(os.path.join(bundle, *name.split("/")))
           or gitobj.sha256_file(os.path.join(bundle, *name.split("/"))) != digest]
    bad += ["%s (not listed)" % name for name in ("artifact.tar", "manifest.json") if name not in sums]
    if not rep.add("sha256sums.match", not bad, "%d files" % len(sums) if not bad else "mismatch: %s" % bad[:5]):
        return finish(rep, a)

    with open(os.path.join(bundle, "manifest.json"), "r", encoding="utf-8") as f:
        doc = json.load(f)
    errors = mf.validate_manifest(doc)
    if not rep.add("manifest.valid", not errors, "; ".join(errors[:5])):
        return finish(rep, a)
    r = doc["release"]

    tool_files = {k for k in sums if k.startswith("tools/")}
    rep.add("tools.match_manifest", tool_files == set(r["build"]["tools"])
            and all(sums[k] == r["build"]["tools"][k] for k in tool_files),
            "%d tool files from %s" % (len(tool_files), r["build"]["tools_source_commit"][:12]))
    artifact = os.path.join(bundle, "artifact.tar")
    rep.add("artifact.sha256", gitobj.sha256_file(artifact) == r["artifact"]["sha256"] == sums.get("artifact.tar"),
            r["artifact"]["sha256"])
    try:
        tree, tar_map = gitobj.tree_sha_of_tar(artifact)
        rep.add("artifact.tree_identity", tree == r["app"]["tree"] and len(tar_map) == r["artifact"]["file_count"],
                "archive hashes to %s, manifest tree %s, %d files" % (tree, r["app"]["tree"], len(tar_map)))
        rep.add("artifact.no_env_files", not [p for p in tar_map if re.search(r"(^|/)\.env($|\.)", p)
                                                and not p.endswith((".example", ".sample", ".template"))])
    except ReleaseError as exc:
        rep.add("artifact.tree_identity", False, str(exc))
        return finish(rep, a)

    if a.mode == "deploy":
        rep.add("migrations.not_declared", not r["schema_version"]["migrations"]["declared"],
                "W0-09A never runs migrations; declared migrations need a separate approved step")
    if a.base:
        base = os.path.abspath(a.base)
        for name, digest in sorted(r["configuration"]["layout_files"].items()):
            path = os.path.join(base, name)
            actual = gitobj.sha256_file(path) if os.path.isfile(path) else None
            rep.add("layout.%s" % name, actual == digest,
                    "matches the versioned layout file" if actual == digest else "live layout file differs or is missing")
        env_path = os.path.join(base, ".env")
        if rep.add("env.present", os.path.isfile(env_path)):
            env = env_keys_and_values(env_path)
            missing = [k for k in r["configuration"]["required_env_keys"] if k not in env]
            rep.add("env.required_keys", not missing, "missing key names: %s" % missing if missing else
                    "%d required key names present (values not read into output)" % len(r["configuration"]["required_env_keys"]))
            for key, spec in sorted(r["feature_flags"].items()):
                ok = key not in env or env[key] == spec["expected"]
                rep.add("flag.%s" % key, ok, "absent (app default) or equal to expected" if ok
                        else "set in .env to a value different from the release expectation")
            del env

    if a.stage:
        try:
            gitobj.safe_extract(artifact, a.stage)
            fs_modes = gitobj.fs_preserves_modes(a.probe_dir or os.path.dirname(os.path.abspath(a.stage)))
            ok, detail = gitobj.verify_dir_tree(a.stage, r["app"]["tree"], fs_modes=fs_modes,
                                                mode_hint={p: m for p, (m, _, _) in tar_map.items()})
            rep.add("stage.tree_identity", ok, detail)
        except ReleaseError as exc:
            rep.add("stage.tree_identity", False, str(exc))

    if rep.ok and a.plan_out:
        _write(a.plan_out, mf.plan_text(mf.render_plan(doc)))
    return finish(rep, a)


def cmd_tree(a):
    rep = Report()
    extras = {}
    for item in a.allow_extra or []:
        path, _, blob = item.partition("=")
        extras[path] = blob
    hint = None
    # Exec bits are verified on disk whenever the filesystem keeps them. Only where it cannot
    # (NTFS, ACL-mapped shares — detected by a chmod probe) they come from the release artifact.
    fs_modes = gitobj.fs_preserves_modes(a.probe_dir or os.path.dirname(os.path.abspath(a.dir)))
    if a.mode_hint_tar and not fs_modes:
        hint = {path: mode for path, (mode, _sha, _data) in gitobj.tar_entries(a.mode_hint_tar).items()}
    try:
        ok, detail = gitobj.verify_dir_tree(a.dir, a.tree, allow_extra=extras, mode_hint=hint, fs_modes=fs_modes)
    except ReleaseError as exc:
        ok, detail = False, str(exc)
    rep.add("tree.identity", ok, detail)
    return finish(rep, a)


def cmd_manifest(a):
    with open(a.manifest, "r", encoding="utf-8") as f:
        errors = mf.validate_manifest(json.load(f))
    for e in errors:
        print("ERROR %s" % e)
    print("manifest %s" % ("VALID" if not errors else "INVALID"))
    return 0 if not errors else 2


def cmd_record(a):
    with open(a.record, "r", encoding="utf-8") as f:
        errors = mf.validate_record(json.load(f))
    for e in errors:
        print("ERROR %s" % e)
    print("record %s" % ("VALID" if not errors else "INVALID"))
    return 0 if not errors else 2


def cmd_redact(a):
    values = sorted({v for v in env_keys_and_values(a.env).values() if len(v) >= 6}, key=len, reverse=True)
    with open(a.input, "rb") as f:
        text = f.read().decode("utf-8", "replace")
    count = 0
    for value in values:
        if value in text:
            count += text.count(value)
            text = text.replace(value, "***REDACTED***")
    with open(a.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("redacted %d occurrence(s) of .env values" % count)
    return 0


def finish(rep, a):
    if getattr(a, "report_out", None):
        _write(a.report_out, json.dumps({"result": "PASS" if rep.ok else "FAIL", "checks": rep.checks},
                                        indent=2, ensure_ascii=False) + "\n")
    print("RESULT %s" % ("PASS" if rep.ok else "FAIL"))
    return 0 if rep.ok else 2


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("--bundle", required=True)
    b.add_argument("--base")
    b.add_argument("--mode", choices=("deploy", "adopt", "inspect"), default="inspect")
    b.add_argument("--stage")
    b.add_argument("--plan-out")
    b.add_argument("--report-out")
    b.add_argument("--probe-dir", help="writable dir on the same filesystem as --stage (mode probe)")
    t = sub.add_parser("tree")
    t.add_argument("--dir", required=True)
    t.add_argument("--tree", required=True)
    t.add_argument("--allow-extra", action="append")
    t.add_argument("--mode-hint-tar", help="artifact whose member modes stand in for exec bits the filesystem cannot keep")
    t.add_argument("--probe-dir", help="writable dir on the same filesystem as --dir (mode probe)")
    t.add_argument("--report-out")
    m = sub.add_parser("manifest")
    m.add_argument("--manifest", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--record", required=True)
    rd = sub.add_parser("redact")
    rd.add_argument("--env", required=True)
    rd.add_argument("--in", dest="input", required=True)
    rd.add_argument("--out", dest="output", required=True)
    a = p.parse_args(argv)
    try:
        return {"bundle": cmd_bundle, "tree": cmd_tree, "manifest": cmd_manifest,
                "record": cmd_record, "redact": cmd_redact}[a.cmd](a)
    except (OSError, ValueError, ReleaseError) as exc:
        print("VERIFY ERROR: %s" % exc)
        print("RESULT FAIL")
        return 2


if __name__ == "__main__":
    sys.exit(main())

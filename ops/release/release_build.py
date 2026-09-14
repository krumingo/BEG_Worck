#!/usr/bin/env python3
"""W0-09A — build an exact-version release bundle from a Git commit.

    python ops/release/release_build.py --commit origin/main --environment production \
        --deployment-id synology-begwork --previous-manifest <current manifest.json> \
        --approval deploy:<reference> --out <dir>

Output: <out>/<release_id>/{artifact.tar, manifest.json, SHA256SUMS, tools/...}

Fails closed (exit 2) when the archive is not byte-identical to the Git tree, a build
input is not versioned, the compose layout drifted, the target is not reachable from
the release ref, the previous release is not an ancestor, or the manifest is invalid.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from beg_release import TOOL_VERSION  # noqa: E402
from beg_release import gitobj, inputs, manifest as mf  # noqa: E402
from beg_release.gitobj import ReleaseError  # noqa: E402

LAYOUT_JSON = "ops/release/synology/layout.json"
TOOLS_PREFIX = "ops/release/"
TOOLS_EXCLUDE = ("ops/release/tests/",)
ENV_FILE = re.compile(r"(^|/)\.env($|\.)")
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")


def _now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stamp():
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _actor(explicit):
    name = explicit or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-") or "unknown"
    return name[:64]


def build(args):
    repo = os.path.abspath(args.repo)
    commit, tree, commit_time = gitobj.resolve_commit(repo, args.commit)

    if args.environment == "production" and args.allow_unmerged:
        raise ReleaseError("--allow-unmerged is not allowed for production")
    if args.reachable_from and not args.allow_unmerged:
        if not gitobj.is_ancestor(repo, commit, args.reachable_from):
            raise ReleaseError("commit %s is not reachable from %s" % (commit, args.reachable_from))

    tools_commit, _, _ = gitobj.resolve_commit(repo, args.tools_ref or commit)
    tools_entries = gitobj.ls_tree(repo, tools_commit)
    if LAYOUT_JSON not in tools_entries:
        raise ReleaseError("%s is not versioned in %s" % (LAYOUT_JSON, tools_commit))

    # --- exact-version artifact from Git objects -------------------------------
    entries = gitobj.ls_tree(repo, commit)
    env_files = sorted(p for p in entries if ENV_FILE.search(p) and not p.endswith(ENV_TEMPLATE_SUFFIXES))
    if env_files:
        raise ReleaseError("secret-bearing .env file(s) are versioned in %s: %s" % (commit, env_files[:5]))
    blobs = gitobj.read_blobs(repo, [sha for _, sha in entries.values()])
    if gitobj.tree_sha(entries) != tree:
        raise ReleaseError("listed entries do not hash to the commit tree")
    data = gitobj.build_tar(entries, blobs, commit_time)

    legacy_extras = {}
    for item in args.legacy_extra or []:
        if not args.baseline:
            raise ReleaseError("--legacy-extra is only allowed for a --baseline (adoption) manifest")
        path, _, blob = item.partition("=")
        if not path or not re.match(r"^[0-9a-f]{40}$", blob) or path in entries:
            raise ReleaseError("invalid --legacy-extra %r" % item)
        legacy_extras[path] = blob

    # --- tools and layout from the tools commit --------------------------------
    tool_paths = sorted(p for p in tools_entries
                        if p.startswith(TOOLS_PREFIX) and not p.startswith(TOOLS_EXCLUDE))
    tool_blobs = gitobj.read_blobs(repo, [tools_entries[p][1] for p in tool_paths])
    layout = json.loads(tool_blobs[tools_entries[LAYOUT_JSON][1]].decode("utf-8"))
    layout_dir = layout["versioned_layout_dir"].rstrip("/") + "/"
    layout_entries = {name: tools_entries.get(layout_dir + name) for name in layout["layout_files"]}
    missing = [n for n, e in layout_entries.items() if e is None]
    if missing:
        raise ReleaseError("missing build input: layout files not versioned: %s" % missing)
    layout_blobs_raw = gitobj.read_blobs(repo, [e[1] for e in layout_entries.values()])
    layout_blobs = {n: layout_blobs_raw[e[1]] for n, e in layout_entries.items()}

    effective = dict(entries)
    for path, blob in legacy_extras.items():
        effective[path] = (gitobj.MODE_FILE, blob)
    services, layout_sha, unpinned = inputs.inventory(layout, effective, layout_blobs)

    previous = None
    if args.previous_manifest:
        with open(args.previous_manifest, "r", encoding="utf-8") as f:
            previous = json.load(f)
        errors = mf.validate_manifest(previous)
        if errors:
            raise ReleaseError("previous manifest invalid: %s" % errors[:3])
        prel = previous["release"]
        if prel["deployment"]["id"] != args.deployment_id or prel["environment"] != args.environment:
            raise ReleaseError("previous manifest belongs to %s/%s, not %s/%s" % (
                prel["deployment"]["id"], prel["environment"], args.deployment_id, args.environment))
        if prel["app"]["commit"] == commit:
            raise ReleaseError("target commit equals the previous release commit")
        if not args.allow_non_descendant and not gitobj.is_ancestor(repo, prel["app"]["commit"], commit):
            raise ReleaseError("previous release %s is not an ancestor of %s (use the rollback tool to go back)"
                               % (prel["app"]["commit"], commit))
    elif not args.no_previous:
        raise ReleaseError("pass --previous-manifest (current release) or --no-previous explicitly")
    rebuild, reason = inputs.services_to_rebuild(services, previous)

    if args.declare_migration and not args.migration_approval:
        raise ReleaseError("--declare-migration requires --migration-approval")

    approvals = []
    for item in args.approval or []:
        typ, _, ref = item.partition(":")
        approvals.append({"type": typ, "ref": ref})

    smoke = dict(layout["smoke"])
    smoke["containers"] = [services[n]["container"] for n in sorted(services)]
    config_version = inputs.sha256_json({
        "layout": layout["layout"], "layout_files": layout_sha,
        "required_env_keys": layout["required_env_keys"], "feature_flags": layout["feature_flags"],
        "build_args": {n: s["build_args"] for n, s in layout["services"].items()}, "smoke": smoke,
    })
    prev_ref = None
    if previous:
        prev_ref = {"release_id": previous["release"]["release_id"],
                    "commit": previous["release"]["app"]["commit"],
                    "tree": previous["release"]["app"]["tree"],
                    "release_sha256": previous["release_sha256"]}

    git_version = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    release_id = "rel-%s-%s" % (_stamp(), commit[:12])
    bundle_tools = {"tools/" + p[len(TOOLS_PREFIX):]: hashlib.sha256(tool_blobs[tools_entries[p][1]]).hexdigest()
                    for p in tool_paths}
    release = {
        "release_id": release_id,
        "app": {"repository": args.repository, "commit": commit, "tree": tree,
                "commit_time": commit_time, "reachable_from": None if args.allow_unmerged else args.reachable_from},
        "artifact": {"format": "tar-pax-git-objects-v1", "file": "artifact.tar",
                     "sha256": gitobj.sha256_bytes(data), "size_bytes": len(data),
                     "file_count": len(entries), "tree_verified": False, "legacy_extras": legacy_extras},
        "environment": args.environment,
        "deployment": {"id": args.deployment_id, "layout": layout["layout"],
                       "tenant_scope": {"mode": "deployment-wide", "tenants": []}},
        "schema_version": {"app_schema_version": None,
                           "migrations": {"declared": sorted(set(args.declare_migration or [])),
                                          "policy": "NOT_RUN_BY_DEFAULT",
                                          "approval_ref": args.migration_approval}},
        "configuration": {"version": config_version, "layout_source_commit": tools_commit,
                          "layout_files": layout_sha, "required_env_keys": layout["required_env_keys"],
                          "build_args": {n: s["build_args"] for n, s in layout["services"].items()}},
        "feature_flags": {k: {"expected": v, "source": "app default; the key must be absent from .env or equal"}
                          for k, v in layout["feature_flags"].items()},
        "entitlements": {"status": "NOT_IMPLEMENTED", "snapshot": None, "reference": "W0-08"},
        "build": {"tool": TOOL_VERSION, "python": platform.python_version(), "git": git_version,
                  "services": services, "unpinned_base_images": unpinned, "rebuild_reason": reason,
                  "tools_source_commit": tools_commit, "tools": bundle_tools},
        "services_to_rebuild": rebuild,
        "previous": prev_ref,
        "rollback_target": prev_ref,
        "approvals": approvals,
        "smoke": smoke,
        "created_at": _now_utc(),
        "created_by": _actor(args.created_by),
    }

    out_root = os.path.abspath(args.out)
    bundle = os.path.join(out_root, release_id)
    if os.path.exists(bundle):
        raise ReleaseError("bundle directory already exists: %s" % bundle)
    os.makedirs(os.path.join(bundle, "tools"))
    artifact_path = os.path.join(bundle, "artifact.tar")
    with open(artifact_path, "wb") as f:
        f.write(data)

    # Independent identity proof: re-read the written archive and rebuild the tree hash.
    written_tree, tar_map = gitobj.tree_sha_of_tar(artifact_path)
    if written_tree != tree or len(tar_map) != len(entries):
        raise ReleaseError("artifact is NOT byte-identical to Git tree %s (archive hashes to %s)" % (tree, written_tree))
    for path, (mode, sha, _) in tar_map.items():
        if entries[path] != (mode, sha):
            raise ReleaseError("artifact entry %s differs from the Git tree" % path)
    release["artifact"]["tree_verified"] = True

    for p in tool_paths:
        dest = os.path.join(bundle, "tools", *p[len(TOOLS_PREFIX):].split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(tool_blobs[tools_entries[p][1]])

    doc = {"schema": mf.MANIFEST_SCHEMA, "release": release, "release_sha256": mf.release_sha256(release)}
    errors = mf.validate_manifest(doc)
    if errors:
        raise ReleaseError("manifest failed validation: %s" % errors)
    manifest_bytes = (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    with open(os.path.join(bundle, "manifest.json"), "wb") as f:
        f.write(manifest_bytes)

    sums = {"artifact.tar": release["artifact"]["sha256"],
            "manifest.json": hashlib.sha256(manifest_bytes).hexdigest()}
    sums.update(bundle_tools)
    with open(os.path.join(bundle, "SHA256SUMS"), "wb") as f:
        f.write("".join("%s  %s\n" % (sums[k], k) for k in sorted(sums)).encode("ascii"))

    summary = {
        "bundle": bundle, "release_id": release_id, "release_sha256": doc["release_sha256"],
        "commit": commit, "tree": tree, "artifact_sha256": release["artifact"]["sha256"],
        "files": len(entries), "services_to_rebuild": rebuild, "rebuild_reason": reason,
        "unpinned_base_images": unpinned, "previous": prev_ref["release_id"] if prev_ref else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=".")
    p.add_argument("--commit", required=True, help="commit-ish to release")
    p.add_argument("--environment", required=True, choices=mf.ENVIRONMENTS)
    p.add_argument("--deployment-id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--repository", default="krumingo/BEG_Worck")
    p.add_argument("--reachable-from", default="origin/main")
    p.add_argument("--allow-unmerged", action="store_true", help="non-production only")
    p.add_argument("--previous-manifest")
    p.add_argument("--no-previous", action="store_true")
    p.add_argument("--allow-non-descendant", action="store_true")
    p.add_argument("--approval", action="append", help="type:reference, e.g. deploy:BEG_Work_AI#1-comment-123")
    p.add_argument("--tools-ref", help="take tools/layout from this commit (baseline manifests of old releases)")
    p.add_argument("--baseline", action="store_true", help="manifest for adopting an already-deployed commit")
    p.add_argument("--legacy-extra", action="append", help="PATH=BLOB file present in the live tree (baseline only)")
    p.add_argument("--declare-migration", action="append")
    p.add_argument("--migration-approval")
    p.add_argument("--created-by")
    args = p.parse_args(argv)
    try:
        return build(args)
    except ReleaseError as exc:
        print("RELEASE BUILD FAILED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

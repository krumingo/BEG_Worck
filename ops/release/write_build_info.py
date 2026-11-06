#!/usr/bin/env python3
"""RC-01 — stamp a build context with its build identity (`beg.build-info/v1`).

    python ops/release/write_build_info.py --commit HEAD
    python ops/release/write_build_info.py --from-bundle <bundle dir> --target <extracted tree>

Writes ``backend/BUILD_INFO.json`` and ``frontend/BUILD_INFO.json`` under ``--target``
(default: the repository root). Both files are git-ignored and are not part of the
release artifact: a commit cannot contain its own id, and the artifact must stay
byte-identical to the Git tree.

The commit id and time come from Git objects (``--commit``, resolved with rev-parse;
uncommitted working-tree changes are refused unless ``--allow-dirty``, which marks
nothing — it only lets a developer stamp a scratch build), or from a verified release
bundle's ``build_info.json`` (``--from-bundle``; must equal ``manifest.release.app.commit``).
Stdlib only.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from beg_release import build_info as bi  # noqa: E402
from beg_release import gitobj  # noqa: E402
from beg_release.gitobj import ReleaseError  # noqa: E402

TARGETS = ("backend", "frontend")


def from_git(repo, ref, allow_dirty):
    commit, _, commit_time = gitobj.resolve_commit(repo, ref)
    if not allow_dirty:
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip()
        if head == commit and dirty:
            raise ReleaseError("working tree has uncommitted changes; the build would not be %s" % commit[:12])
    return bi.make(commit, bi.utc(commit_time))


def from_bundle(bundle):
    with open(os.path.join(bundle, bi.BUNDLE_FILE), "r", encoding="utf-8") as f:
        info = json.load(f)
    with open(os.path.join(bundle, "manifest.json"), "r", encoding="utf-8") as f:
        release = json.load(f)["release"]
    errors = bi.validate(info)
    if errors:
        raise ReleaseError("bundle build_info.json invalid: %s" % errors)
    if info["build_sha"] != release["app"]["commit"]:
        raise ReleaseError("bundle build_info.json %s != manifest commit %s"
                           % (info["build_sha"], release["app"]["commit"]))
    return info


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=".")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--commit", help="commit-ish resolved from Git objects")
    src.add_argument("--from-bundle", help="release bundle directory (release_build.py output)")
    p.add_argument("--target", help="directory holding backend/ and frontend/ (default: --repo)")
    p.add_argument("--allow-dirty", action="store_true")
    args = p.parse_args(argv)
    repo = os.path.abspath(args.repo)
    target = os.path.abspath(args.target or repo)
    try:
        info = from_bundle(args.from_bundle) if args.from_bundle else from_git(repo, args.commit, args.allow_dirty)
        written = []
        for sub in TARGETS:
            d = os.path.join(target, sub)
            if not os.path.isdir(d):
                raise ReleaseError("missing %s/ under %s" % (sub, target))
            path = os.path.join(d, bi.FILE_NAME)
            with open(path + ".tmp", "wb") as f:
                f.write(bi.to_bytes(info))
            os.replace(path + ".tmp", path)
            written.append(path)
    except (ReleaseError, OSError, ValueError, KeyError) as exc:
        print("WRITE BUILD INFO FAILED: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"build_sha": info["build_sha"], "build_time": info["build_time"], "written": written}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

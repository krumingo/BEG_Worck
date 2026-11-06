#!/usr/bin/env python3
"""RC-01 — stamp a build context with its build identity (`beg.build-info/v1`).

    python ops/release/write_build_info.py --commit HEAD
    python ops/release/write_build_info.py --from-bundle <bundle dir> --target <extracted tree>

Writes ``backend/BUILD_INFO.json`` and ``frontend/BUILD_INFO.json`` under ``--target``
(default: the repository root). Both files are git-ignored and are not part of the
release artifact: a commit cannot contain its own id, and the artifact must stay
byte-identical to the Git tree.

The commit id and time come from Git objects (``--commit``, resolved with rev-parse;
the stamped tree (``--target``, default ``--repo``) must be a Git work tree whose HEAD is
exactly that commit — a mismatch is refused (exit 2) and nothing is written; uncommitted
working-tree changes are refused unless ``--allow-dirty``, which marks nothing — it only
lets a developer stamp a scratch build), or from a verified release
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


def _git_out(path, *args):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def from_git(repo, ref, allow_dirty, target):
    """Identity of the tree at ``target``, taken only from Git objects.

    ``ref`` is resolved in ``repo``. The tree being stamped (``target``) must be a Git
    work tree whose ``HEAD`` is exactly that commit; anything else (another checkout,
    a plain directory, a detached copy) is refused — use ``--from-bundle`` for an
    extracted release tree. ``--allow-dirty`` only tolerates uncommitted changes in a
    tree that is at the right commit; it never tolerates a different commit.
    """
    commit, _, commit_time = gitobj.resolve_commit(repo, ref)
    rc, top = _git_out(target, "rev-parse", "--show-toplevel")
    if rc != 0 or os.path.realpath(top) != os.path.realpath(target):
        raise ReleaseError("%s is not the root of a Git work tree; --commit cannot prove what it contains "
                           "(use --from-bundle)" % target)
    rc, head = _git_out(target, "rev-parse", "--verify", "HEAD^{commit}")
    if rc != 0 or head != commit:
        raise ReleaseError("--commit %s resolves to %s but the tree being built is at HEAD %s; refusing to stamp "
                           "a SHA the build is not" % (ref, commit, head or "(none)"))
    if not allow_dirty:
        _, dirty = _git_out(target, "status", "--porcelain", "--untracked-files=no")
        if dirty:
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
    tmps = []
    try:
        info = (from_bundle(args.from_bundle) if args.from_bundle
                else from_git(repo, args.commit, args.allow_dirty, target))
        dirs = [os.path.join(target, sub) for sub in TARGETS]
        for sub, d in zip(TARGETS, dirs):  # all checks before any write: refuse → nothing written
            if not os.path.isdir(d):
                raise ReleaseError("missing %s/ under %s" % (sub, target))
        data = bi.to_bytes(info)
        for d in dirs:
            path = os.path.join(d, bi.FILE_NAME)
            tmps.append(path)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
        written = []
        for path in tmps:
            os.replace(path + ".tmp", path)
            written.append(path)
        tmps = []
    except (ReleaseError, OSError, ValueError, KeyError) as exc:
        for path in tmps:
            try:
                os.remove(path + ".tmp")
            except OSError:
                pass
        print("WRITE BUILD INFO FAILED: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"build_sha": info["build_sha"], "build_time": info["build_time"], "written": written}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

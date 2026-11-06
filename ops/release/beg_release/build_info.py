"""RC-01 — build identity `beg.build-info/v1`.

One small JSON document that says which commit a build was made from. It is derived only
from immutable Git objects (the resolved commit id and its committer time), never from a
runtime variable. The same document is written

* into the release bundle as ``build_info.json`` (listed in SHA256SUMS) by release_build.py;
* into ``backend/BUILD_INFO.json`` and ``frontend/BUILD_INFO.json`` of a build context by
  write_build_info.py (both paths are git-ignored: a commit cannot contain its own id).

The backend serves it at ``GET /api/version``; the frontend build bakes it in. Stdlib only.
"""
import json
import re
import time

SCHEMA = "beg.build-info/v1"
SOURCE = "git-objects"
FILE_NAME = "BUILD_INFO.json"
BUNDLE_FILE = "build_info.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
KEYS = ("schema", "build_sha", "build_time", "source")


def utc(epoch):
    """Git committer time (epoch seconds) as UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch)))


def make(commit, commit_time):
    """``commit``: 40 lowercase hex; ``commit_time``: UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    info = {"schema": SCHEMA, "build_sha": commit, "build_time": commit_time, "source": SOURCE}
    errors = validate(info)
    if errors:
        raise ValueError("invalid build info: %s" % "; ".join(errors))
    return info


def validate(info):
    if not isinstance(info, dict):
        return ["build info is not an object"]
    errors = []
    if set(info) != set(KEYS):
        errors.append("keys must be exactly %s" % sorted(KEYS))
    if info.get("schema") != SCHEMA:
        errors.append("schema must be %s" % SCHEMA)
    if not isinstance(info.get("build_sha"), str) or not SHA_RE.match(info["build_sha"]):
        errors.append("build_sha must be 40 lowercase hex")
    if not isinstance(info.get("build_time"), str) or not TIME_RE.match(info["build_time"]):
        errors.append("build_time must be UTC YYYY-MM-DDTHH:MM:SSZ")
    if info.get("source") != SOURCE:
        errors.append("source must be %s" % SOURCE)
    return errors


def to_bytes(info):
    return (json.dumps(info, indent=2, sort_keys=True) + "\n").encode("utf-8")

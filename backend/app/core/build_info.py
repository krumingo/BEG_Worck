"""RC-01 — build identity of the running backend (`GET /api/version`).

Source order (CLAUDE.md §6: every deployment keeps its app version):

1. ``backend/BUILD_INFO.json`` (``beg.build-info/v1``), written at build time from Git
   objects by ``ops/release/write_build_info.py`` / ``release_build.py``. It wins.
2. ``BUILD_SHA`` (and optional ``BUILD_TIME``) environment variables — a fallback only,
   never the sole source when the file exists. A file/env disagreement is logged and the
   file is served.
3. Neither → ``build_sha = "unknown"``; the UI shows it as an unverified build.

The environment label follows the R0-07 policy: the raw ``ENV`` value must be exactly one
of the known names (no strip, no lower); anything else is ``unknown``.

The response is a positive allowlist — no secrets, paths or host names.
"""
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

BUILD_INFO_FILE = Path(__file__).resolve().parents[2] / "BUILD_INFO.json"
SCHEMA = "beg.build-info/v1"
UNKNOWN = "unknown"
ENVIRONMENT_LABELS = ("production", "staging", "development", "test")
RESPONSE_KEYS = ("build_sha", "build_time", "environment_label", "source")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def environment_label(env=None):
    """R0-07 fail-closed: exact raw match only."""
    raw = os.environ.get("ENV") if env is None else env
    return raw if raw in ENVIRONMENT_LABELS else UNKNOWN


def _valid_sha(value):
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def _valid_time(value):
    return isinstance(value, str) and bool(_TIME_RE.match(value))


def _read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("RC-01: build info file is unreadable; ignoring it")
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not _valid_sha(data.get("build_sha")):
        logger.warning("RC-01: build info file is not a valid %s document; ignoring it", SCHEMA)
        return None
    return {"build_sha": data["build_sha"],
            "build_time": data["build_time"] if _valid_time(data.get("build_time")) else None}


def _read_env():
    sha = os.environ.get("BUILD_SHA")
    if sha is None:
        return None
    if not _valid_sha(sha):
        logger.warning("RC-01: BUILD_SHA is not a 40-char lowercase hex commit id; ignoring it")
        return None
    t = os.environ.get("BUILD_TIME")
    return {"build_sha": sha, "build_time": t if _valid_time(t) else None}


def current_version(path=None):
    file_info = _read_file(BUILD_INFO_FILE if path is None else path)
    env_info = _read_env()
    if file_info:
        if env_info and env_info["build_sha"] != file_info["build_sha"]:
            logger.warning("RC-01: BUILD_SHA %s disagrees with build info file %s; serving the file",
                           env_info["build_sha"][:12], file_info["build_sha"][:12])
        info, source = file_info, "build-info-file"
    elif env_info:
        info, source = env_info, "env"
    else:
        info, source = {"build_sha": UNKNOWN, "build_time": None}, "none"
    return {"build_sha": info["build_sha"], "build_time": info["build_time"],
            "environment_label": environment_label(), "source": source}

"""Dashboard configuration.

Everything is read from the process environment so that the container image carries
no configuration and no credential. The GitHub token lives only in this object,
inside the server process; ``Settings.redacted()`` is what may be logged or served,
and it never contains the token. See ``projection.py`` for the browser-facing view.
"""

from __future__ import annotations

import dataclasses
import os

DEFAULT_REPOSITORY = "krumingo/BEG_Worck"
DEFAULT_BRANCH = "codex/claude-queue"

CONTROL_STATE_PATH = "coordination/CONTROL_STATE.json"
CONTROL_SCHEMA_PATH = "coordination/CONTROL_STATE.schema.json"
CONTROL_BOARD_PATH = "coordination/CONTROL_BOARD.md"

# Issue #26 asks for 10-30 s. 15 s is inside that band and, with conditional
# requests, costs no rate-limit budget on an unchanged snapshot.
DEFAULT_REFRESH_SECONDS = 15
MIN_REFRESH_SECONDS = 10
MAX_REFRESH_SECONDS = 30

# A snapshot older than this in wall-clock terms is shown as aged. This is the age of
# the last *successful read*, never the distance from validated_at: a genuinely
# blocked task can legitimately sit untouched for days without the dashboard being
# out of date about it.
DEFAULT_STALE_AFTER_SECONDS = 120


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclasses.dataclass(frozen=True, slots=True)
class Settings:
    repository: str = DEFAULT_REPOSITORY
    branch: str = DEFAULT_BRANCH
    token: str = ""
    api_base: str = "https://api.github.com"
    host: str = "0.0.0.0"
    port: int = 8080
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS
    backoff_initial_seconds: int = 10
    backoff_maximum_seconds: int = 120
    request_timeout_seconds: int = 15
    verify_pull_request: bool = True

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            repository=_env("BEGWORK_REPOSITORY", DEFAULT_REPOSITORY),
            branch=_env("BEGWORK_BRANCH", DEFAULT_BRANCH),
            token=_env("BEGWORK_GITHUB_TOKEN"),
            api_base=_env("BEGWORK_API_BASE", "https://api.github.com").rstrip("/"),
            host=_env("BEGWORK_HOST", "0.0.0.0"),
            port=_env_int("BEGWORK_PORT", 8080, 1, 65535),
            refresh_seconds=_env_int(
                "BEGWORK_REFRESH_SECONDS",
                DEFAULT_REFRESH_SECONDS,
                MIN_REFRESH_SECONDS,
                MAX_REFRESH_SECONDS,
            ),
            stale_after_seconds=_env_int(
                "BEGWORK_STALE_AFTER_SECONDS", DEFAULT_STALE_AFTER_SECONDS, 30, 3600
            ),
            backoff_initial_seconds=_env_int("BEGWORK_BACKOFF_INITIAL_SECONDS", 10, 1, 120),
            backoff_maximum_seconds=_env_int("BEGWORK_BACKOFF_MAX_SECONDS", 120, 5, 900),
            request_timeout_seconds=_env_int("BEGWORK_REQUEST_TIMEOUT_SECONDS", 15, 2, 120),
            verify_pull_request=_env_flag("BEGWORK_VERIFY_PULL_REQUEST", True),
        )

    @property
    def has_token(self) -> bool:
        return bool(self.token)

    def redacted(self) -> dict:
        """A description of the configuration that is safe to log or serve."""
        return {
            "repository": self.repository,
            "branch": self.branch,
            "api_base": self.api_base,
            "refresh_seconds": self.refresh_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "verify_pull_request": self.verify_pull_request,
            # The presence of a credential is operationally useful; its value is not.
            "token_configured": self.has_token,
        }

"""Refresh loop: cadence, bounded backoff, and the cached last-good snapshot.

Two independent axes are kept apart on purpose.

``Link`` is about this dashboard: did the most recent round reach GitHub? A failed
round does not change what the control state says, so it must not be reported as a
protocol problem. It is reported as OFFLINE.

``Status`` is about the control state: what did verification find in the bytes? A
snapshot can be perfectly VALID and shown while the link is OFFLINE -- that is the
normal case a second after the network drops, and the honest thing to show is the
last verified state plus how old it is.

A cached snapshot therefore stays on screen when a round fails, marked with its age.
Blanking the screen would destroy information; presenting it as current would invent
some.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import threading

from .github import GitHubReadOnlyClient, ReadOnlyViolation, TransportError
from .redact import redact
from .settings import Settings
from .status import Link, Status
from .verify import VerifiedSnapshot, read_snapshot, verify

LOGGER = logging.getLogger("begwork.dashboard")


class BackoffPolicy:
    """Bounded exponential backoff.

    Bounded in both directions on purpose: far enough that a rate-limited or offline
    dashboard stops hammering the API, capped low enough that it recovers by itself
    within a couple of minutes once the network returns, with nobody restarting it.
    """

    __slots__ = ("initial", "maximum", "maximum_doublings")

    def __init__(self, initial: float = 10.0, maximum: float = 120.0, maximum_doublings: int = 6) -> None:
        if initial <= 0:
            raise ValueError("initial backoff must be positive")
        if maximum < initial:
            raise ValueError("maximum backoff cannot be below the initial delay")
        self.initial = float(initial)
        self.maximum = float(maximum)
        self.maximum_doublings = max(1, min(16, int(maximum_doublings)))

    def next(self, consecutive_failures: int, retry_after: float | None = None) -> float:
        """Delay before the next attempt. ``consecutive_failures`` is 1 for the first."""
        if consecutive_failures <= 0:
            return 0.0
        doublings = min(consecutive_failures - 1, self.maximum_doublings)
        delay = min(self.initial * (2 ** doublings), self.maximum)
        if retry_after is not None and retry_after > delay:
            # A server hint is honoured, but still capped: an hour-long Retry-After must
            # not park the dashboard for an hour.
            delay = min(retry_after, self.maximum)
        return delay


@dataclasses.dataclass(frozen=True, slots=True)
class DashboardState:
    """Everything the projection needs about the current round."""

    verified: VerifiedSnapshot | None
    link: Link
    last_success_at: dt.datetime | None
    last_attempt_at: dt.datetime | None
    last_error: str | None
    consecutive_failures: int
    next_attempt_in: float
    rounds: int
    settings: Settings
    now: dt.datetime

    @property
    def status(self) -> Status | None:
        return self.verified.status if self.verified else None

    @property
    def age_seconds(self) -> float | None:
        if self.last_success_at is None:
            return None
        return max(0.0, (self.now - self.last_success_at).total_seconds())

    @property
    def is_aged(self) -> bool:
        """Whether the last successful read is older than the configured threshold.

        Measured from the read, not from ``validated_at``: a task that is legitimately
        blocked for days is not thereby a stale reading.
        """
        age = self.age_seconds
        return age is not None and age > self.settings.stale_after_seconds

    @property
    def has_data(self) -> bool:
        return self.verified is not None


class Refresher:
    """Owns the cached snapshot and decides when to read again. Thread-safe."""

    def __init__(
        self,
        client: GitHubReadOnlyClient,
        settings: Settings,
        backoff: BackoffPolicy | None = None,
        clock=None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._backoff = backoff or BackoffPolicy(
            settings.backoff_initial_seconds, settings.backoff_maximum_seconds
        )
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._verified: VerifiedSnapshot | None = None
        self._link = Link.OFFLINE  # Nothing has been read yet, so not yet online.
        self._last_success_at: dt.datetime | None = None
        self._last_attempt_at: dt.datetime | None = None
        self._last_error: str | None = None
        # The server's own Retry-After hint from the most recent failed round, if it gave
        # one. Kept so the backoff can honour it: parsing the header and then ignoring it
        # means a 429 is retried on the local schedule and the rate limit is hit again.
        self._last_retry_after: float | None = None
        self._failures = 0
        self._rounds = 0

    @property
    def settings(self) -> Settings:
        return self._settings

    def tick(self) -> DashboardState:
        """Perform one round. Never raises for an ordinary read failure."""
        attempted_at = self._clock()
        try:
            snapshot = read_snapshot(self._client, self._settings, now=attempted_at)
            verified = verify(snapshot, self._settings)
        except ReadOnlyViolation:
            # A write attempt is a defect in this program, not a network condition. It
            # must not be absorbed into the offline path and retried quietly.
            raise
        except TransportError as error:
            with self._lock:
                self._failures += 1
                self._rounds += 1
                self._link = Link.OFFLINE
                # Redacted at the point of storage: this string is served at /api/state,
                # and an upstream 401 body can quote the Authorization header back at us.
                self._last_error = redact(str(error), self._settings.token)
                self._last_attempt_at = attempted_at
                self._last_retry_after = error.retry_after
            LOGGER.warning(
                "refresh failed (%s consecutive, retry_after=%s): %s",
                self._failures,
                error.retry_after,
                error,
            )
            return self.current()
        except Exception as error:  # noqa: BLE001 - one bad round must not kill the loop
            with self._lock:
                self._failures += 1
                self._rounds += 1
                self._link = Link.OFFLINE
                self._last_error = redact(f"{error.__class__.__name__}: {error}", self._settings.token)
                self._last_attempt_at = attempted_at
                # An unexpected failure carries no server hint; fall back to plain backoff.
                self._last_retry_after = None
            LOGGER.exception("refresh raised unexpectedly")
            return self.current()

        with self._lock:
            self._verified = verified
            self._link = Link.ONLINE
            # The refresher's own clock, not wall-clock inside the reader: age must be
            # measured on one timeline or a test cannot pin it and a clock skew cannot be
            # reasoned about.
            self._last_success_at = attempted_at
            self._last_attempt_at = attempted_at
            self._last_error = None
            self._failures = 0
            self._last_retry_after = None
            self._rounds += 1
        LOGGER.info(
            "refresh ok: status=%s findings=%s requests=%s",
            verified.status.label,
            len(verified.verdict),
            verified.snapshot.request_count,
        )
        return self.current()

    def current(self) -> DashboardState:
        with self._lock:
            return DashboardState(
                verified=self._verified,
                link=self._link,
                last_success_at=self._last_success_at,
                last_attempt_at=self._last_attempt_at,
                last_error=self._last_error,
                consecutive_failures=self._failures,
                next_attempt_in=self._delay_locked(),
                rounds=self._rounds,
                settings=self._settings,
                now=self._clock(),
            )

    def _delay_locked(self) -> float:
        if self._failures == 0:
            return float(self._settings.refresh_seconds)
        # Honoured when the server asked for longer than the current step, and still
        # capped by the policy's maximum so an hour-long hint cannot park the dashboard.
        return self._backoff.next(self._failures, self._last_retry_after)

    @property
    def last_retry_after(self) -> float | None:
        with self._lock:
            return self._last_retry_after

    @property
    def delay_seconds(self) -> float:
        with self._lock:
            return self._delay_locked()


class RefreshLoop:
    """A daemon thread that ticks the refresher and waits the delay it asks for."""

    def __init__(self, refresher: Refresher) -> None:
        self._refresher = refresher
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="begwork-refresh", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._refresher.tick()
            self._stop.wait(self._refresher.delay_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

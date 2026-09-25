"""Control-state status lattice and findings.

The persisted ``control_state_status`` field is a *claim* made by the producer at
``validated_at``. This dashboard folds that claim in as one finding among many and
reports the worst of everything it observed in the current round, so a stored
``VALID`` can never by itself put ``VALID`` on the screen.

``OFFLINE`` is deliberately *not* a member of this lattice. A control state has a
protocol status; a dashboard has a link state. Collapsing the two would let a
network outage read as a protocol conflict, or a genuine CONFLICT be excused as a
connectivity blip. They are rendered as two separate indicators.
"""

from __future__ import annotations

import enum
from typing import Iterable, NamedTuple


@enum.unique
class Status(enum.IntEnum):
    """Ordered so that ``max()`` is 'the worst thing observed'.

    Numbering starts at 1 deliberately. With ``VALID = 0`` the best possible status is
    falsy, so ``if status:`` reads as "not valid" for exactly the case that matters most,
    and a missing status becomes indistinguishable from a good one. Starting at 1 keeps
    the ordering that ``max()`` relies on while making every member truthy.
    """

    VALID = 1
    STALE = 2
    CONFLICT = 3
    INVALID = 4

    @property
    def label(self) -> str:
        return self.name

    @classmethod
    def parse(cls, value: str) -> "Status":
        try:
            return cls[str(value).strip().upper()]
        except KeyError:
            # An unrecognised status is never quietly downgraded to VALID.
            return cls.INVALID


@enum.unique
class Link(enum.StrEnum):
    """Whether the most recent refresh round reached GitHub."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class Finding(NamedTuple):
    """One observation. ``code`` is stable and machine-readable; ``message`` is for people."""

    status: Status
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"status": self.status.label, "code": self.code, "message": self.message}


class Verdict:
    """The worst-of status over a set of findings, keeping every finding."""

    __slots__ = ("_findings",)

    def __init__(self, findings: Iterable[Finding] = ()) -> None:
        self._findings = tuple(findings)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self._findings

    @property
    def status(self) -> Status:
        return max((item.status for item in self._findings), default=Status.VALID)

    @property
    def is_valid(self) -> bool:
        return self.status is Status.VALID

    def merge(self, *others: "Verdict") -> "Verdict":
        merged = list(self._findings)
        for other in others:
            merged.extend(other.findings)
        return Verdict(merged)

    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self._findings)

    def worst_first(self) -> tuple[Finding, ...]:
        # Stable sort: severity descending, original order preserved within a severity.
        return tuple(sorted(self._findings, key=lambda item: -int(item.status)))

    def as_dicts(self) -> list[dict]:
        return [item.as_dict() for item in self.worst_first()]

    def __len__(self) -> int:
        return len(self._findings)

    def __bool__(self) -> bool:
        """Always true.

        Without this, ``__len__`` makes a clean Verdict falsy, so ``if verdict:`` would
        read "there is no verdict" for the one case that matters most -- a snapshot that
        passed every check. A Verdict object that exists is a verdict; emptiness means it
        found nothing wrong. Callers distinguishing "no verdict" must test ``is None``.
        """
        return True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Verdict({self.status.label}, {len(self._findings)} findings)"


CLEAN = Verdict()

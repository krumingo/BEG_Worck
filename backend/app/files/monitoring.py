"""
W0-06C — the periodic integrity RUNNER over the registered originals (FLOW-016).

W0-06B built the check: :meth:`app.files.integrity.FileIntegrityService.check`
asks one provider about one original and returns the versioned
``beg.w0-06b.file_integrity_finding/v1`` result. It has no scheduler and keeps
no history, so a problem is only known while someone is looking at it.

This module adds exactly the missing technical layer, and nothing else:

* a tenant-resolved, provider-neutral runner that walks bounded pages of the
  tenant's current originals and calls that same check — there is no second
  verifier, no second result contract and no provider code here;
* durable runs with a per-item checkpoint, so a crashed run resumes without
  skipping a file or duplicating its finding, alarm or audit effect;
* an atomic per-tenant lease with a fence token, so two workers in two
  processes cannot run the same tenant at once and a worker that has lost its
  lease can no longer commit;
* a finding HISTORY — ``open`` / ``observed`` / ``resolved`` / ``reopened`` —
  with one open finding per deterministic identity, so a daily check does not
  raise the same alarm thirty times;
* a technical alarm level (``informational`` / ``warning`` / ``critical``)
  that is a deterministic normalization of the W0-06B severity, with the
  original severity kept beside it.

What it deliberately does NOT do
--------------------------------

* It does not decide WHEN to run in production. There is no cron, no default
  cadence and no SLA here: :class:`MonitorPolicy` is supplied by the caller
  and its scheduling fields default to "no automatic production activation".
* It does not invent an owner, a deadline, a recipient or an escalation. The
  FLOW-033/034 DQ/Approval runtime is W0-07; the ``dq_handoff`` block of the
  W0-06B result is passed through untouched and stays ``not_consumed``.
* It never repairs, moves, deletes or adopts a customer original. A changed
  object is never accepted as a new version, and a provider outage is never
  rewritten into "the file is gone".
* It grants itself nothing. The service principal is an ordinary FLOW-002
  principal of ONE tenant and the run fails closed, before any provider
  access, when its RoleAssignment does not allow the action.

Resolution is type-specific on purpose
--------------------------------------

A retry that simply succeeds does not close a finding. Each type needs the
proof that matches what failed, and an incomplete proof leaves the finding
open:

====================  ===========================================================
finding type          what closes it
====================  ===========================================================
``provider_unavailable``  a full provider verification succeeds
``missing_original``      an identified object is there AND its content was compared
``checksum_mismatch``     the canonical expected checksum (and size) match again
``permission_failure``    a real content read/compare succeeds, not a reachable stat
``external_change``       the recorded provider identity/version matches again
====================  ===========================================================

Canon: FLOW-016 §"Периодична проверка на наличността и целостта", FLOW-002,
FLOW-040, TENANCY_MODEL, and ``docs/architecture/W0-06C_INTEGRITY_MONITORING.md``.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from app.audit.envelope import (
    ACTOR_HUMAN,
    ACTOR_SYSTEM,
    RESULT_FAILURE,
    RESULT_SUCCESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R3_SECURITY_ACCESS,
)
from app.files import audit_trail
from app.files import models as m
from app.files.authorization import FileAccessDenied, authorize, sensitivity_action
from app.files.integrity import (
    FINDING_SCHEMA,
    FINDING_TYPES,
    AffectedRecordResolver,
    FileIntegrityService,
)
from app.files.providers.base import (
    VERIFY_READ_AND_HASH,
    VERIFY_SERVER_CHECKSUM,
)
from app.files.registry import FileNotFound
from app.permissions import service as permission_service

# --------------------------------------------------------------- collections
#: The tenant's ONE monitor control row: the lease, its fence token and the
#: last/next/result metadata of the runner. One document per tenant.
MONITOR_STATE_COLLECTION = "storage_integrity_monitor_state"
#: One document per RUN: its cursor, its per-item checkpoint and its counts.
MONITOR_RUNS_COLLECTION = "storage_integrity_runs"
#: The finding history. One OPEN document per deterministic identity.
MONITOR_FINDINGS_COLLECTION = "storage_integrity_findings"

MONITOR_COLLECTIONS = frozenset({MONITOR_STATE_COLLECTION, MONITOR_RUNS_COLLECTION,
                                 MONITOR_FINDINGS_COLLECTION})

ID_PREFIX_RUN = "fir_"
ID_PREFIX_FINDING = "fif_"

#: The indexes this package needs, as ``(collection, keys, options)``.
#:
#: The unique one is the contract's "one open finding per deterministic
#: identity", enforced by the SERVER rather than by a read-then-write in this
#: module: two workers racing to create the same identity cannot both succeed,
#: and a fence-filtered update that cannot match is rejected outright
#: (``DuplicateKeyError``) instead of quietly inserting a second row.
MONITOR_INDEXES = (
    (MONITOR_FINDINGS_COLLECTION, [("org_id", 1), ("id", 1)],
     {"unique": True, "name": "uniq_integrity_finding_identity"}),
    (MONITOR_FINDINGS_COLLECTION, [("org_id", 1), ("state", 1), ("file_id", 1)],
     {"name": "integrity_finding_state_file"}),
    (MONITOR_RUNS_COLLECTION, [("org_id", 1), ("id", 1)],
     {"unique": True, "name": "uniq_integrity_run"}),
)


async def ensure_monitor_indexes(tenant) -> List[str]:
    """Create :data:`MONITOR_INDEXES` for one tenant. Idempotent.

    Index creation is a schema step, so it is NOT done implicitly on a
    monitoring pass: the canon gives migrations their own runner with a
    per-tenant lock. This is the callable that an index bootstrap (and the test
    harness) uses, and until it has run for a tenant the identity uniqueness is
    not server-enforced for that tenant.
    """
    created: List[str] = []
    for collection, keys, options in MONITOR_INDEXES:
        created.append(await tenant.collection(collection)._raw.create_index(
            keys, **options))
    return created

# ------------------------------------------------------------ FLOW-002 actions
#: Running the periodic check. A tenant-scoped service principal needs THIS
#: action in a live RoleAssignment of that tenant; nothing here creates one.
ACTION_MONITOR_RUN = "file.integrity.monitor"
#: Reading the finding/alarm projection.
ACTION_MONITOR_READ = "file.integrity.monitor.read"

# --------------------------------------------------------- FLOW-040 actions
ACTION_RUN_STARTED = "file.integrity.monitor.started"
ACTION_RUN_FINISHED = "file.integrity.monitor.finished"
ACTION_FINDING_OPENED = "file.integrity.finding.opened"
ACTION_FINDING_OBSERVED = "file.integrity.finding.observed"
ACTION_FINDING_RESOLVED = "file.integrity.finding.resolved"
ACTION_FINDING_REOPENED = "file.integrity.finding.reopened"
ACTION_FINDING_AFFECTED_REFRESHED = "file.integrity.finding.affected_refreshed"

_RETENTION: Dict[str, str] = {
    ACTION_RUN_STARTED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_RUN_FINISHED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_FINDING_OPENED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_FINDING_OBSERVED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_FINDING_RESOLVED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_FINDING_REOPENED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_FINDING_AFFECTED_REFRESHED: RETENTION_R2_PROJECT_OPERATIONAL,
    audit_trail.ACTION_PERMISSION_FAILED: RETENTION_R3_SECURITY_ACCESS,
}

# ------------------------------------------------------------- vocabularies
FINDING_OPEN = "open"
FINDING_RESOLVED = "resolved"
FINDING_STATES = frozenset({FINDING_OPEN, FINDING_RESOLVED})

TRANSITION_OPENED = "open"
TRANSITION_OBSERVED = "observed"
TRANSITION_RESOLVED = "resolved"
TRANSITION_REOPENED = "reopened"
TRANSITIONS = (TRANSITION_OPENED, TRANSITION_OBSERVED, TRANSITION_RESOLVED,
               TRANSITION_REOPENED)

_TRANSITION_ACTIONS = {
    TRANSITION_OPENED: ACTION_FINDING_OPENED,
    TRANSITION_OBSERVED: ACTION_FINDING_OBSERVED,
    TRANSITION_RESOLVED: ACTION_FINDING_RESOLVED,
    TRANSITION_REOPENED: ACTION_FINDING_REOPENED,
}

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_TAKEN_OVER = "taken_over"

#: Technical alarm levels. They say how loud the TECHNICAL problem is; they do
#: not name an owner, a deadline or a recipient (that is W0-07 / FLOW-033).
ALARM_INFORMATIONAL = "informational"
ALARM_WARNING = "warning"
ALARM_CRITICAL = "critical"
ALARM_LEVELS = (ALARM_INFORMATIONAL, ALARM_WARNING, ALARM_CRITICAL)

#: The deterministic normalization of the EXISTING W0-06B severity
#: (:func:`app.files.models.severity_of`) onto the three alarm levels. The
#: severity is kept beside the level on every finding, so nothing is lost.
#:
#: ``critical`` is reserved for what W0-06B already calls critical — a failure
#: on a file attached to MORE THAN ONE business record — because that is the
#: only escalation point the canon actually defines. Inventing a finer split
#: would be inventing a threshold, which W0-06C must not do.
ALARM_BY_SEVERITY: Dict[str, str] = {
    "info": ALARM_INFORMATIONAL,
    "low": ALARM_INFORMATIONAL,
    "medium": ALARM_WARNING,
    "high": ALARM_WARNING,
    "critical": ALARM_CRITICAL,
}

#: How a provider OUTAGE is classified over repeated observations. Without an
#: explicitly supplied threshold the answer is "not classified" — never an
#: invented number, and never a reason to close the finding.
OUTAGE_UNCLASSIFIED = "unclassified"
OUTAGE_TRANSIENT = "transient"
OUTAGE_PERSISTENT = "persistent"

#: The finding type a provider outage produces, and the only one the
#: transient/persistent classification applies to.
FINDING_PROVIDER_UNAVAILABLE = "provider_unavailable"
FINDING_MISSING = "missing_original"
FINDING_CHECKSUM_MISMATCH = "checksum_mismatch"
FINDING_PERMISSION_FAILURE = "permission_failure"
FINDING_EXTERNAL_CHANGE = "external_change"

#: Every finding type the W0-06B result can carry. Asserted against the B
#: contract so a new availability state cannot slip through unmonitored.
MONITORED_FINDING_TYPES = frozenset({FINDING_MISSING, FINDING_PERMISSION_FAILURE,
                                     FINDING_CHECKSUM_MISMATCH, FINDING_PROVIDER_UNAVAILABLE,
                                     FINDING_EXTERNAL_CHANGE})

#: The relation types whose target IS a project record, so their ``record_id``
#: is what a FLOW-002 project ``scope_id`` is compared against.
#: ``RELATION_SITE`` targets the ``sites`` collection, not ``projects``, so a
#: site is deliberately NOT read as a project: that mapping is a business rule
#: and W0-06C does not invent one.
PROJECT_RELATION_TYPES: FrozenSet[str] = frozenset({m.RELATION_PROJECT,
                                                    m.RELATION_SUB_PROJECT})

#: A module name no real module may use. Requesting it asks the Permission
#: Service one question: is this grant restricted to some module at all?
MODULE_PROBE = "__beg_work_w0_06c_module_probe__"

#: Verification methods in which the CONTENT was actually compared. A verdict
#: that compared nothing is not proof that a missing, corrupt or forbidden
#: object is well again.
CONTENT_METHODS = frozenset({VERIFY_SERVER_CHECKSUM, VERIFY_READ_AND_HASH})

#: Outcomes worth another attempt inside one run: a provider that cannot be
#: reached now may be reachable in a moment. A missing, changed or forbidden
#: object is a determinate answer and is never retried into a different one.
RETRYABLE_AVAILABILITY = frozenset({m.AVAILABILITY_PROVIDER_UNREACHABLE})


class MonitorConfigurationRefused(ValueError):
    """The supplied policy or principal cannot be used. Nothing ran."""


class MonitorLeaseLost(RuntimeError):
    """Another worker owns this tenant's run now; this worker must not commit."""


class MonitorEvidenceRefused(ValueError):
    """A value that must never be stored reached a finding or an audit event."""


# ------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """A FIXED-WIDTH UTC timestamp, so a lexicographic compare is a time compare."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _is_duplicate_key(exc: BaseException) -> bool:
    return type(exc).__name__ == "DuplicateKeyError" or getattr(exc, "code", None) == 11000


#: What a stored evidence string may never look like: a credential, a bearer
#: token or a signed/pre-signed provider URL.
_URLISH = re.compile(
    r"(://)|(\bbearer\b)|(x-amz-)|(signature=)|(sig=)|(access_token)|(refresh_token)"
    r"|(\btoken=)|(password=)|(secret=)|(-----BEGIN)", re.IGNORECASE)

#: A provider error text is a class name and a code (``_safe_error``), never a
#: body. The cap is a second belt: a long provider message is truncated rather
#: than stored whole.
_MAX_ERROR_CHARS = 200


def assert_no_secrets(value: Any, path: str = "evidence") -> None:
    """Refuse a secret-like key or a token/URL-like value anywhere in ``value``.

    The forbidden KEY list is :data:`app.files.audit_trail.FORBIDDEN_DIFF_KEYS`
    — the same one the audit envelope enforces, so the finding record and the
    AuditEvent cannot disagree about what a secret is.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            low = str(key).lower()
            if any(marker in low for marker in audit_trail.FORBIDDEN_DIFF_KEYS) \
                    and item not in (None, False, True) \
                    and not low.endswith(("_names", "_present")):
                raise MonitorEvidenceRefused(
                    "refusing to store a secret-like field %s.%s" % (path, key))
            assert_no_secrets(item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_secrets(item, "%s[%d]" % (path, index))
    elif isinstance(value, str) and _URLISH.search(value):
        raise MonitorEvidenceRefused(
            "refusing to store a token/URL-like value at %s" % path)


def sanitize_error(text: Optional[str]) -> Optional[str]:
    """A provider error reduced to something safe to keep, or ``None``."""
    if not text:
        return None
    cleaned = " ".join(str(text).split())[:_MAX_ERROR_CHARS]
    if _URLISH.search(cleaned):
        return "PROVIDER_ERROR_REDACTED"
    return cleaned or None


def alarm_level(severity: Optional[str]) -> Optional[str]:
    """The technical alarm level of a W0-06B severity, or ``None`` for "none"."""
    return ALARM_BY_SEVERITY.get(severity or "")


def finding_identity(*, org_id: str, file_id: str, version_no: int, location_id: str,
                     provider_binding_id: Optional[str], finding_type: str) -> str:
    """The deterministic identity of ONE problem.

    Tenant + file + version + location + finding type, as FLOW-016 asks, AND
    the provider binding: after a provider migration the same bytes at the same
    logical place are a DIFFERENT physical problem, and the old one must not be
    silently reused or silently closed.
    """
    parts = (org_id, file_id, str(version_no), location_id,
             provider_binding_id or "-", finding_type)
    return "|".join("%d:%s" % (len(p), p) for p in parts)


def finding_id_for(identity: str) -> str:
    return ID_PREFIX_FINDING + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _transition_key(finding_id: str, transition: str, marker: str) -> str:
    raw = "|".join((finding_id, transition, marker))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# -------------------------------------------------------------- the principal
@dataclass(frozen=True)
class ServicePrincipal:
    """The runner's FLOW-002 identity: one user, one tenant, nothing implicit.

    It is an ORDINARY principal. ``authorize`` reads its live RoleAssignments
    through the real W0-02 Permission Service, so a service account without an
    assignment that allows :data:`ACTION_MONITOR_RUN` is denied exactly like a
    person would be. There is no system bypass and no role is granted here.
    """

    user_id: str
    tenant_id: str
    actor_type: str = ACTOR_SYSTEM

    def __post_init__(self):
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise MonitorConfigurationRefused("the service principal needs a user_id")
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise MonitorConfigurationRefused("the service principal needs a tenant_id")


def service_principal(*, tenant_id: str, user_id: str) -> ServicePrincipal:
    """Build the runner's tenant-scoped principal. Both values are required."""
    return ServicePrincipal(user_id=user_id, tenant_id=tenant_id)


# ------------------------------------------------------------------ the policy
@dataclass(frozen=True)
class MonitorPolicy:
    """Every bound and every threshold the runner obeys, supplied explicitly.

    The defaults are SAFE, not productional: they bound one manual/test run.
    ``recheck_after_seconds`` and ``persistent_outage_after`` default to
    ``None``, which means "the canon has not approved a cadence or an outage
    threshold yet, so do not invent one".
    """

    #: Documents fetched per page.
    batch_size: int = 25
    #: Provider checks performed in one run. The hard ceiling on provider work.
    max_items_per_run: int = 200
    #: Candidate locations examined in one run, including the ones skipped as
    #: not-current or out of scope. The hard ceiling on the walk itself.
    max_scanned_per_run: int = 1000
    #: Attempts per item. 1 = no retry. Only a provider OUTAGE is retried.
    max_attempts: int = 1
    #: Deterministic exponential backoff: base * 2 ** (attempt - 1), capped.
    backoff_base_seconds: float = 0.0
    backoff_max_seconds: float = 0.0
    #: How long a claim stays valid without renewal. A crashed worker's run can
    #: be taken over once this has passed.
    lease_ttl_seconds: int = 300
    #: Consecutive outage observations before an outage counts as persistent.
    #: ``None`` = not classified. It NEVER closes a finding either way.
    persistent_outage_after: Optional[int] = None
    #: Which location roles are in scope.
    roles: Tuple[str, ...] = (m.LOCATION_ROLE_PRIMARY,)
    #: FLOW-016's risk / document-type inputs, wired as an explicit SCOPE
    #: restriction rather than an invented ranking. Empty = every category /
    #: sensitivity is in scope.
    categories: Tuple[str, ...] = ()
    sensitivities: Tuple[str, ...] = ()
    #: A location verified more recently than this is not due. ``None`` = no
    #: cadence is assumed, so every candidate is due when a run is triggered.
    recheck_after_seconds: Optional[int] = None

    def __post_init__(self):
        self._positive("batch_size", self.batch_size)
        self._positive("max_items_per_run", self.max_items_per_run)
        self._positive("max_scanned_per_run", self.max_scanned_per_run)
        self._positive("max_attempts", self.max_attempts)
        self._positive("lease_ttl_seconds", self.lease_ttl_seconds)
        for name in ("backoff_base_seconds", "backoff_max_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise MonitorConfigurationRefused("%s must be a number >= 0" % name)
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise MonitorConfigurationRefused(
                "backoff_max_seconds must not be below backoff_base_seconds")
        if self.max_scanned_per_run < self.max_items_per_run:
            raise MonitorConfigurationRefused(
                "max_scanned_per_run must not be below max_items_per_run")
        if self.persistent_outage_after is not None:
            self._positive("persistent_outage_after", self.persistent_outage_after)
        if self.recheck_after_seconds is not None:
            if not isinstance(self.recheck_after_seconds, int) \
                    or isinstance(self.recheck_after_seconds, bool) \
                    or self.recheck_after_seconds < 0:
                raise MonitorConfigurationRefused(
                    "recheck_after_seconds must be an integer >= 0 or None")
        if not self.roles:
            raise MonitorConfigurationRefused("at least one location role must be in scope")
        self._subset("roles", self.roles, m.LOCATION_ROLES)
        self._subset("categories", self.categories, m.CATEGORIES)
        self._subset("sensitivities", self.sensitivities, m.SENSITIVITIES)

    @staticmethod
    def _positive(name: str, value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise MonitorConfigurationRefused("%s must be an integer >= 1" % name)

    @staticmethod
    def _subset(name: str, values: Sequence[str], allowed) -> None:
        unknown = sorted(set(values) - set(allowed))
        if unknown:
            raise MonitorConfigurationRefused("unknown %s: %s" % (name, ", ".join(unknown)))

    def backoff_for(self, attempt: int) -> float:
        """The wait before attempt ``attempt`` (1-based). Deterministic, capped."""
        if attempt <= 1 or self.backoff_base_seconds <= 0:
            return 0.0
        return min(self.backoff_base_seconds * (2 ** (attempt - 2)), self.backoff_max_seconds)

    def as_record(self) -> Dict[str, Any]:
        """The policy as stored on a run — the evidence of what bounded it."""
        return {"batch_size": self.batch_size, "max_items_per_run": self.max_items_per_run,
                "max_scanned_per_run": self.max_scanned_per_run,
                "max_attempts": self.max_attempts,
                "backoff_base_seconds": self.backoff_base_seconds,
                "backoff_max_seconds": self.backoff_max_seconds,
                "lease_ttl_seconds": self.lease_ttl_seconds,
                "persistent_outage_after": self.persistent_outage_after,
                "roles": list(self.roles), "categories": list(self.categories),
                "sensitivities": list(self.sensitivities),
                "recheck_after_seconds": self.recheck_after_seconds}


@dataclass(frozen=True)
class _Lease:
    """A held claim: who holds it and with which fence token."""

    holder: str
    fence: int
    expires_at: str


@dataclass
class _Counts:
    scanned: int = 0
    checked: int = 0
    ok: int = 0
    attempts: int = 0
    retries: int = 0
    skipped_not_current: int = 0
    skipped_out_of_scope: int = 0
    skipped_not_due: int = 0
    skipped_unreadable: int = 0
    findings_opened: int = 0
    findings_observed: int = 0
    findings_resolved: int = 0
    findings_reopened: int = 0

    def as_record(self) -> Dict[str, int]:
        return dict(self.__dict__)


#: The count names a stored run may restore. A run document written by an
#: older build cannot inject an unknown field into the counter.
_COUNT_FIELDS = frozenset(_Counts().as_record())


@dataclass
class _Cursor:
    """Where the walk is. Two phases, so no null/string comparison is needed."""

    phase: str = "unverified"
    last_verified_at: Optional[str] = None
    last_id: Optional[str] = None

    def as_record(self) -> Dict[str, Any]:
        return {"phase": self.phase, "last_verified_at": self.last_verified_at,
                "last_id": self.last_id}

    @classmethod
    def from_record(cls, row: Optional[Mapping[str, Any]]) -> "_Cursor":
        if not row:
            return cls()
        return cls(phase=row.get("phase") or "unverified",
                   last_verified_at=row.get("last_verified_at"),
                   last_id=row.get("last_id"))


# ===================================================================== runner
class FileIntegrityMonitor:
    """One tenant's periodic integrity runner and its finding history.

    Built from the tenant's already resolved :class:`~app.files.registry.FileRegistry`
    and :class:`~app.files.storage.StorageProviderService`, exactly like
    :class:`~app.files.integrity.FileIntegrityService`: the only tenant it can
    act for is the one inside those views, and it never takes an ``org_id``
    argument.
    """

    def __init__(self, registry, storage, *, integrity=None,
                 policy: Optional[MonitorPolicy] = None, worker_id: Optional[str] = None,
                 clock=None, sleep=None):
        if registry.org_id != storage.org_id:
            raise MonitorConfigurationRefused(
                "registry and storage service belong to different tenants")
        self._registry = registry
        self._storage = storage
        self._integrity = integrity if integrity is not None \
            else FileIntegrityService(registry, storage)
        if self._integrity.org_id != registry.org_id:
            raise MonitorConfigurationRefused(
                "the integrity service belongs to a different tenant")
        self.policy = policy if policy is not None else MonitorPolicy()
        self.org_id = registry.org_id
        #: The same resolved tenant view the registry holds. ``AffectedRecordResolver``
        #: reads it the same way; no second tenant resolution exists here.
        self._tenant = registry._tenant
        self._resolver = self._integrity.resolver
        self.worker_id = worker_id or ("worker-" + uuid.uuid4().hex[:12])
        self._clock = clock or _now
        self._sleep = sleep

    # ------------------------------------------------------------- handles
    @property
    def state(self):
        return self._tenant.collection(MONITOR_STATE_COLLECTION)

    @property
    def runs(self):
        return self._tenant.collection(MONITOR_RUNS_COLLECTION)

    @property
    def findings(self):
        return self._tenant.collection(MONITOR_FINDINGS_COLLECTION)

    @property
    def _locations(self):
        return self._registry.locations

    def _state_id(self) -> str:
        """A deterministic per-tenant ``_id``: the one row two workers race on."""
        return "integrity_monitor:%d:%s" % (len(self.org_id), self.org_id)

    def now(self) -> datetime:
        return self._clock()

    # --------------------------------------------------------------- audit
    async def _audit(self, *, action: str, actor_id: str, entity_type: str, entity_id: str,
                     result: str = RESULT_SUCCESS, reason: Optional[str] = None,
                     structured_diff: Optional[Dict[str, Any]] = None,
                     related_file_ids: Optional[List[str]] = None,
                     entity_version: Optional[str] = None,
                     idempotency_key: Optional[str] = None,
                     correlation_id: Optional[str] = None,
                     error_code: Optional[str] = None,
                     actor_type: str = ACTOR_SYSTEM) -> Dict[str, Any]:
        """One FLOW-040 envelope through the W0-06B entry point. Sanitized first."""
        assert_no_secrets(structured_diff or {}, "structured_diff")
        return await audit_trail.record(
            self._tenant, action=action, actor_id=actor_id,
            retention_class=_RETENTION[action], entity_type=entity_type, entity_id=entity_id,
            result=result, reason=reason, structured_diff=structured_diff,
            related_file_ids=related_file_ids, entity_version=entity_version,
            idempotency_key=idempotency_key, correlation_id=correlation_id,
            error_code=error_code, actor_type=actor_type)

    async def _authorize(self, principal, action: str, *, entity_id: str,
                         scope_type: Optional[str] = None, scope_id: Optional[str] = None):
        """FLOW-002 BEFORE anything else. A denial is audited and then raised.

        ``scope_type``/``scope_id`` are passed straight through to the
        Permission Service, so a project-scoped assignment is judged against
        the project the caller actually asked for instead of being handed an
        unscoped request it can never satisfy.
        """
        try:
            return await authorize(principal, action, org_id=self.org_id,
                                   scope_type=scope_type, scope_id=scope_id)
        except FileAccessDenied as denied:
            await self._audit(
                action=audit_trail.ACTION_PERMISSION_FAILED,
                actor_id=getattr(principal, "user_id", None) or "anonymous",
                entity_type="file_integrity_monitor", entity_id=entity_id,
                result=RESULT_FAILURE, reason="integrity monitor denied: %s" % denied.action,
                error_code=denied.reason_code,
                actor_type=getattr(principal, "actor_type", ACTOR_HUMAN),
                structured_diff={"action": denied.action, "reason_code": denied.reason_code,
                                 "tenant_id": self.org_id,
                                 "scope_type": scope_type, "scope_id": scope_id})
            raise

    # ---------------------------------------------------------- the lease
    async def _claim(self) -> Optional[_Lease]:
        """Claim this tenant's monitor row atomically, or return ``None``.

        Two steps, both atomic, and together they are the whole exclusion:

        1. ``find_one_and_update`` takes the row only when it is free or its
           claim has EXPIRED, and ``$inc`` makes the fence token strictly
           larger than every previous holder's. One of two racing workers wins
           because the server applies the two updates one after the other.
        2. if there is no row yet, ``insert_one`` creates it; the ``_id`` index
           exists on every MongoDB, so the loser of a first-ever race gets a
           duplicate-key error and simply does not get the lease.
        """
        now = self.now()
        expires = _iso(now + timedelta(seconds=self.policy.lease_ttl_seconds))
        row = await self.state.find_one_and_update(
            {"_id": self._state_id(),
             "$or": [{"holder": None}, {"expires_at": {"$lte": _iso(now)}}]},
            {"$set": {"holder": self.worker_id, "acquired_at": _iso(now),
                      "expires_at": expires, "released_at": None},
             "$inc": {"fence": 1}},
            return_document=True)
        if row is not None:
            return _Lease(holder=self.worker_id, fence=int(row.get("fence") or 1),
                          expires_at=expires)
        try:
            await self.state.insert_one(
                {"_id": self._state_id(), "fence": 1, "holder": self.worker_id,
                 "acquired_at": _iso(now), "expires_at": expires, "released_at": None,
                 "last_run_id": None, "last_run_at": None, "last_status": None,
                 "last_result": None, "next_due_at": None, "runs_total": 0,
                 "created_at": _iso(now)})
        except Exception as exc:                                      # noqa: BLE001
            if _is_duplicate_key(exc):
                return None                 # a live claim of another worker
            raise
        return _Lease(holder=self.worker_id, fence=1, expires_at=expires)

    async def _renew(self, lease: _Lease) -> _Lease:
        """Extend the claim, proving it is still ours. Raises when it is not.

        The filter carries the fence token, so a worker that was taken over
        matches nothing: it learns it lost BEFORE it touches a provider or
        commits a checkpoint.
        """
        now = self.now()
        expires = _iso(now + timedelta(seconds=self.policy.lease_ttl_seconds))
        result = await self.state.update_one(
            {"_id": self._state_id(), "holder": lease.holder, "fence": lease.fence},
            {"$set": {"expires_at": expires, "renewed_at": _iso(now)}})
        if getattr(result, "matched_count", 0) != 1:
            raise MonitorLeaseLost(
                "the monitor claim of %s (fence %d) is no longer held"
                % (lease.holder, lease.fence))
        return _Lease(holder=lease.holder, fence=lease.fence, expires_at=expires)

    async def _verify_lease(self, lease: _Lease, *, what: str) -> None:
        """Prove the claim is STILL ours, without extending it. Raises if not.

        This is called immediately after every awaited provider call returns
        and before any finding, history, alarm or AuditEvent write. The
        provider call is the one place where a worker sits long enough for its
        claim to expire, so it is where a taken-over worker has to learn it
        lost — BEFORE it writes, not after. The fenced ``_checkpoint`` alone
        could not give that: it runs after the finding and the audit event were
        already appended, so a stale worker could still overwrite the newer
        owner's evidence and raise an alarm the newer owner never saw.

        An EXPIRED claim counts as lost even when nobody has taken over yet: at
        that moment any other worker is entitled to claim the tenant, so
        writing under it is exactly the hazard. A provider slower than
        ``lease_ttl_seconds`` therefore ends the pass instead of risking a
        double write; the run resumes from its checkpoint on the next pass.
        """
        row = await self.state.find_one(
            {"_id": self._state_id(), "holder": lease.holder, "fence": lease.fence},
            {"_id": 0, "expires_at": 1})
        if row is None:
            raise MonitorLeaseLost(
                "the monitor claim of %s (fence %d) was taken over; refusing to %s"
                % (lease.holder, lease.fence, what))
        expires_at = row.get("expires_at")
        if not expires_at or expires_at <= _iso(self.now()):
            raise MonitorLeaseLost(
                "the monitor claim of %s (fence %d) expired during the provider call; "
                "refusing to %s" % (lease.holder, lease.fence, what))

    async def _commit_item(self, lease: _Lease, *, run_id: str,
                           location: Mapping[str, Any],
                           result: Mapping[str, Any]) -> None:
        """Take the RIGHT to write this item's finding. The commit point.

        This is the one operation that decides whether this worker may produce
        a side effect, and it is a conditional WRITE, not a check:

        * it targets the per-tenant claim row — the document a takeover
          actually mutates (``_claim`` ``$inc``s the fence there, and touches
          nothing else), so the server itself refuses a worker whose claim has
          moved;
        * its filter carries the holder AND the fence AND a live ``expires_at``,
          so matching proves the claim was held, unexpired, at this instant;
        * the same atomic update RENEWS the claim, so a worker that commits
          here holds the tenant for another full ``lease_ttl_seconds``. A
          takeover cannot then land before the finding write unless the process
          stalls for a whole TTL between two adjacent database operations.

        ``_verify_lease`` cannot do this job: a read tells you what WAS true,
        and the C02 review proved the gap — a takeover landing between that
        read and the first ``insert_one`` persisted a stale finding, a stale
        transition and a stale AuditEvent. Refusing here means nothing is
        written at all, which is the property the contract asks for.

        A single ``update_one`` is atomic on one document; MongoDB cannot make
        a write to the findings collection conditional on this row without a
        multi-document transaction, so the claim is proven on this row first
        and the write follows under a freshly renewed claim.
        """
        now = self.now()
        expires = _iso(now + timedelta(seconds=self.policy.lease_ttl_seconds))
        applied = await self.state.update_one(
            {"_id": self._state_id(), "holder": lease.holder, "fence": lease.fence,
             "expires_at": {"$gt": _iso(now)}},
            {"$set": {"expires_at": expires, "renewed_at": _iso(now),
                      "last_commit": {"run_id": run_id, "fence": lease.fence,
                                      "location_id": location.get("id"),
                                      "version_no": location.get("version_no"),
                                      "availability": result.get("availability"),
                                      "at": _iso(now)}}})
        if getattr(applied, "matched_count", 0) != 1:
            raise MonitorLeaseLost(
                "the monitor claim of %s (fence %d) is not live; refusing to write any "
                "finding, history, alarm or audit event for location %s"
                % (lease.holder, lease.fence, location.get("id")))

    def _fenced(self, lease: _Lease, flt: Mapping[str, Any]) -> Dict[str, Any]:
        """``flt`` plus the fencing condition every finding write carries.

        A finding records the fence of the run that last wrote it, and a write
        is accepted only from a fence at least as new. So even if a stale
        worker's write somehow raced past :meth:`_verify_lease`, it cannot
        clobber what a newer owner already wrote. The ``$exists`` branch keeps
        a finding written before this field existed updatable.
        """
        return dict(flt, **{"$or": [{"fence": {"$exists": False}},
                                    {"fence": {"$lte": lease.fence}}]})

    @staticmethod
    def _fence_rejected(result: Any, lease: _Lease, what: str) -> None:
        if getattr(result, "matched_count", 0) != 1:
            raise MonitorLeaseLost(
                "a newer owner already wrote this finding (fence %d); refusing to %s"
                % (lease.fence, what))

    async def _release(self, lease: _Lease, *, run_id: str, status: str,
                       result: Mapping[str, Any], next_due_at: Optional[str]) -> None:
        """Free the claim and publish the last/next/result metadata.

        Fenced: a worker that has been taken over cannot overwrite the new
        owner's claim or its result with its own stale one.
        """
        await self.state.update_one(
            {"_id": self._state_id(), "holder": lease.holder, "fence": lease.fence},
            {"$set": {"holder": None, "expires_at": None, "released_at": _iso(self.now()),
                      "last_run_id": run_id, "last_run_at": _iso(self.now()),
                      "last_status": status, "last_result": dict(result),
                      "next_due_at": next_due_at},
             "$inc": {"runs_total": 1}})

    async def _abandon_claim(self, lease: _Lease) -> None:
        """Give the claim back without publishing a result: no run happened."""
        await self.state.update_one(
            {"_id": self._state_id(), "holder": lease.holder, "fence": lease.fence},
            {"$set": {"holder": None, "expires_at": None,
                      "released_at": _iso(self.now())}})

    async def monitor_state(self, ctx) -> Optional[Dict[str, Any]]:
        """The tenant's last/next/result metadata. FLOW-002 checked.

        This row is TENANT-WIDE: it describes every pass over every original.
        It is therefore a company-scope read, and a project-scoped grant cannot
        satisfy it — asking for the whole tenant is not a project request. A
        module-restricted grant is refused for the same reason as
        :meth:`list_findings`.
        """
        await self._authorize(ctx, ACTION_MONITOR_READ, entity_id=self.org_id)
        await self._module_unrestricted(ctx, ACTION_MONITOR_READ, scope_type=None,
                                        scope_id=None, entity_id=self.org_id)
        return await self.state.find_one({"_id": self._state_id()}, {"_id": 0})

    # ------------------------------------------------------------ the walk
    def _due_before(self) -> Optional[str]:
        if self.policy.recheck_after_seconds is None:
            return None
        return _iso(self.now() - timedelta(seconds=self.policy.recheck_after_seconds))

    async def _page(self, cursor: _Cursor, limit: int) -> List[Dict[str, Any]]:
        """One bounded page of candidate locations, in a total order.

        Phase ``unverified`` drains the never-checked locations ordered by
        ``id``; phase ``verified`` walks the rest oldest-check-first, ordered
        by ``(last_verified_at, id)``. Splitting them keeps every comparison
        inside one BSON type, so the same page comes back on mongomock and on a
        real server — a cursor that compared a string with ``null`` would not.
        """
        base: Dict[str, Any] = {"role": {"$in": list(self.policy.roles)},
                                "superseded_at": None, "destroyed_at_provider": None}
        if cursor.phase == "unverified":
            flt = dict(base, last_verified_at=None)
            if cursor.last_id is not None:
                flt["id"] = {"$gt": cursor.last_id}
            rows = await self._locations.find(flt, {"_id": 0}).sort(
                [("id", 1)]).limit(limit).to_list(None)
            return list(rows)
        flt = dict(base, last_verified_at={"$ne": None})
        if cursor.last_verified_at is not None:
            flt = {"$and": [flt, {"$or": [
                {"last_verified_at": {"$gt": cursor.last_verified_at}},
                {"last_verified_at": cursor.last_verified_at,
                 "id": {"$gt": cursor.last_id or ""}}]}]}
        rows = await self._locations.find(flt, {"_id": 0}).sort(
            [("last_verified_at", 1), ("id", 1)]).limit(limit).to_list(None)
        return list(rows)

    async def _in_scope(self, location: Mapping[str, Any], counts: _Counts
                        ) -> Optional[Dict[str, Any]]:
        """``(file, version)`` when this location is a CURRENT original in scope.

        A superseded location, an old version, a file that is no longer active
        and a file outside the configured category / sensitivity scope are all
        out of scope — counted, never checked, and never reported as a problem.
        """
        file_row = await self._registry.get_file(location["file_id"])
        if not file_row or file_row.get("status") != m.FILE_ACTIVE:
            counts.skipped_not_current += 1
            return None
        current = await self._registry.current_version(location["file_id"])
        if not current or current.get("version_no") != location.get("version_no"):
            counts.skipped_not_current += 1
            return None
        if self.policy.categories and file_row.get("category") not in self.policy.categories:
            counts.skipped_out_of_scope += 1
            return None
        if self.policy.sensitivities \
                and file_row.get("sensitivity") not in self.policy.sensitivities:
            counts.skipped_out_of_scope += 1
            return None
        return {"file": file_row, "version": current}

    # ------------------------------------------------------------- the run
    async def run_once(self, principal, *, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Run ONE bounded pass for this tenant. The only entry point.

        There is no loop, no timer and no cron behind it: a caller (a test, an
        operator command, or a future scheduler that is NOT part of W0-06C)
        decides when a pass happens.
        """
        await self._authorize(principal, ACTION_MONITOR_RUN, entity_id=self.org_id)
        lease = await self._claim()
        if lease is None:
            # Another worker holds this tenant. Nothing is checked, no provider
            # is contacted and no finding or audit event is written.
            return {"status": "skipped_locked", "tenant_id": self.org_id,
                    "worker_id": self.worker_id, "run_id": None, "counts": _Counts().as_record()}
        try:
            run = await self._open_run(principal, lease, run_id=run_id)
        except Exception:
            # Nothing ran, so the claim must not be left held: a refused or
            # failed run must never wedge this tenant until the lease expires.
            await self._abandon_claim(lease)
            raise
        counts = _Counts(**{k: int(v) for k, v in (run.get("counts") or {}).items()
                            if k in _COUNT_FIELDS})
        cursor = _Cursor.from_record(run.get("cursor"))
        processed = set(run.get("processed_location_ids") or [])
        exhausted = False
        status = RUN_COMPLETED
        try:
            exhausted = await self._walk(principal, run, lease, counts, cursor, processed)
        except MonitorLeaseLost:
            raise
        except Exception as exc:                                      # noqa: BLE001
            status = RUN_FAILED
            await self._finish_run(run, lease, counts, cursor, status=status,
                                   exhausted=False, error=type(exc).__name__)
            await self._audit(
                action=ACTION_RUN_FINISHED, actor_id=principal.user_id,
                entity_type="file_integrity_run", entity_id=run["id"], result=RESULT_FAILURE,
                reason="integrity monitor run failed", correlation_id=run["id"],
                error_code=type(exc).__name__,
                structured_diff={"counts": counts.as_record(), "error": type(exc).__name__})
            await self._release(lease, run_id=run["id"], status=status,
                                result={"counts": counts.as_record(),
                                        "error": type(exc).__name__},
                                next_due_at=self._next_due_at())
            raise
        await self._finish_run(run, lease, counts, cursor, status=status, exhausted=exhausted)
        # Computed ONCE: the returned result and the stored monitor state must
        # name the same next-due moment, not two readings of the clock.
        next_due_at = self._next_due_at()
        result = {"status": status, "run_id": run["id"], "tenant_id": self.org_id,
                  "worker_id": self.worker_id, "fence": lease.fence,
                  "started_at": run["started_at"], "finished_at": _iso(self.now()),
                  "counts": counts.as_record(), "cursor": cursor.as_record(),
                  "exhausted": exhausted, "policy": self.policy.as_record(),
                  "next_due_at": next_due_at,
                  "finding_schema": FINDING_SCHEMA}
        await self._audit(
            action=ACTION_RUN_FINISHED, actor_id=principal.user_id,
            entity_type="file_integrity_run", entity_id=run["id"], correlation_id=run["id"],
            reason="integrity monitor run finished", idempotency_key=None,
            structured_diff={"counts": counts.as_record(), "exhausted": exhausted,
                             "policy": self.policy.as_record()})
        await self._release(lease, run_id=run["id"], status=status,
                            result={"counts": counts.as_record(), "exhausted": exhausted},
                            next_due_at=next_due_at)
        return result

    def _next_due_at(self) -> Optional[str]:
        """When the next pass becomes due, or ``None`` when no cadence is set."""
        if self.policy.recheck_after_seconds is None:
            return None
        return _iso(self.now() + timedelta(seconds=self.policy.recheck_after_seconds))

    async def _open_run(self, principal, lease: _Lease, *, run_id: Optional[str]
                        ) -> Dict[str, Any]:
        """Resume the named/crashed run under the new fence, or start a fresh one.

        A run left ``running`` by a crashed worker is TAKEN OVER rather than
        duplicated: its cursor, its checkpoint and its counts are the new
        owner's starting point, so no file is checked twice and none is skipped.
        """
        if run_id:
            existing = await self.runs.find_one({"id": run_id}, {"_id": 0})
            if existing is None:
                raise MonitorConfigurationRefused("no run %r in this tenant" % run_id)
            if existing.get("status") != RUN_RUNNING:
                raise MonitorConfigurationRefused(
                    "run %r is %s; a finished run is history and is never reopened"
                    % (run_id, existing.get("status")))
        else:
            rows = await self.runs.find({"status": RUN_RUNNING}, {"_id": 0}).to_list(None)
            existing = sorted(rows, key=m.sort_key)[-1] if rows else None
        now = _iso(self.now())
        if existing is not None:
            await self.runs.update_one(
                {"id": existing["id"]},
                {"$set": {"status": RUN_RUNNING, "lease_holder": lease.holder,
                          "fence": lease.fence, "worker_id": self.worker_id,
                          "resumed_at": now, "updated_at": now,
                          "policy": self.policy.as_record()},
                 "$inc": {"takeovers": 0 if existing.get("lease_holder") is None else 1}})
            row = await self.runs.find_one({"id": existing["id"]}, {"_id": 0})
            await self._audit(
                action=ACTION_RUN_STARTED, actor_id=principal.user_id,
                entity_type="file_integrity_run", entity_id=row["id"], correlation_id=row["id"],
                reason="integrity monitor run resumed",
                structured_diff={"resumed": True, "fence": lease.fence,
                                 "cursor": row.get("cursor"),
                                 "policy": self.policy.as_record()})
            return row
        row = {"id": ID_PREFIX_RUN + uuid.uuid4().hex, "status": RUN_RUNNING,
               "worker_id": self.worker_id, "lease_holder": lease.holder, "fence": lease.fence,
               "started_at": now, "created_at": now, "updated_at": now, "finished_at": None,
               "resumed_at": None, "takeovers": 0, "error": None, "exhausted": False,
               "policy": self.policy.as_record(), "cursor": _Cursor().as_record(),
               "processed_location_ids": [], "counts": _Counts().as_record(),
               "finding_schema": FINDING_SCHEMA}
        await self.runs.insert_one(dict(row))
        await self._audit(
            action=ACTION_RUN_STARTED, actor_id=principal.user_id,
            entity_type="file_integrity_run", entity_id=row["id"], correlation_id=row["id"],
            reason="integrity monitor run started",
            structured_diff={"resumed": False, "fence": lease.fence,
                             "policy": self.policy.as_record()})
        return row

    async def _checkpoint(self, run: Mapping[str, Any], lease: _Lease, counts: _Counts,
                          cursor: _Cursor, location_id: Optional[str]) -> None:
        """Commit the walk's position. FENCED: a stale worker cannot commit.

        The filter carries the holder and the fence token the worker started
        with. A newer owner has already rewritten both on the run document, so
        this update matches nothing and the stale worker stops instead of
        rewinding the new owner's cursor or double-counting its work.
        """
        update: Dict[str, Any] = {
            "$set": {"cursor": cursor.as_record(), "counts": counts.as_record(),
                     "updated_at": _iso(self.now())}}
        if location_id is not None:
            update["$addToSet"] = {"processed_location_ids": location_id}
        result = await self.runs.update_one(
            {"id": run["id"], "lease_holder": lease.holder, "fence": lease.fence}, update)
        if getattr(result, "matched_count", 0) != 1:
            raise MonitorLeaseLost(
                "run %s was taken over; this worker must not commit" % run["id"])

    async def _finish_run(self, run: Mapping[str, Any], lease: _Lease, counts: _Counts,
                          cursor: _Cursor, *, status: str, exhausted: bool,
                          error: Optional[str] = None) -> None:
        result = await self.runs.update_one(
            {"id": run["id"], "lease_holder": lease.holder, "fence": lease.fence},
            {"$set": {"status": status, "finished_at": _iso(self.now()),
                      "updated_at": _iso(self.now()), "counts": counts.as_record(),
                      "cursor": cursor.as_record(), "exhausted": exhausted, "error": error}})
        if getattr(result, "matched_count", 0) != 1:
            raise MonitorLeaseLost(
                "run %s was taken over; this worker must not close it" % run["id"])

    async def _walk(self, principal, run: Mapping[str, Any], lease: _Lease, counts: _Counts,
                    cursor: _Cursor, processed: set) -> bool:
        """Walk bounded pages until a bound is reached. ``True`` = nothing left.

        The cursor is advanced ONLY past a location this run has finished with.
        When a bound is reached mid-page the walk returns without touching it,
        so the committed cursor still points at the last completed item and the
        next run picks that location up instead of stepping over it.
        """
        while True:
            if counts.scanned >= self.policy.max_scanned_per_run \
                    or counts.checked >= self.policy.max_items_per_run:
                return False
            lease = await self._renew(lease)
            remaining = min(self.policy.batch_size,
                            self.policy.max_scanned_per_run - counts.scanned)
            page = await self._page(cursor, remaining)
            if not page:
                if cursor.phase == "unverified":
                    # The never-verified locations are drained; walk the rest
                    # oldest-check-first from the start of the second phase.
                    cursor.phase, cursor.last_id, cursor.last_verified_at = "verified", None, None
                    await self._checkpoint(run, lease, counts, cursor, None)
                    continue
                return True
            for location in page:
                # Every bound is tested BEFORE the cursor moves.
                if counts.scanned >= self.policy.max_scanned_per_run \
                        or counts.checked >= self.policy.max_items_per_run:
                    return False
                if location["id"] in processed:
                    # Already walked in THIS run: its check moved it forward in
                    # the order and the page caught it again. Not re-checked,
                    # not re-counted, but the cursor must still pass it.
                    self._advance(cursor, location)
                    await self._checkpoint(run, lease, counts, cursor, None)
                    continue
                outcome = await self._consider(principal, run, lease, counts, location,
                                               processed)
                if outcome is False:
                    return False
                self._advance(cursor, location)
                await self._checkpoint(run, lease, counts, cursor, location["id"])

    @staticmethod
    def _advance(cursor: _Cursor, location: Mapping[str, Any]) -> None:
        """Move the cursor onto ``location``, in the phase's own sort key."""
        if cursor.phase == "unverified":
            cursor.last_id = location["id"]
        else:
            cursor.last_verified_at = location.get("last_verified_at")
            cursor.last_id = location["id"]

    async def _consider(self, principal, run: Mapping[str, Any], lease: _Lease,
                        counts: _Counts, location: Mapping[str, Any], processed: set):
        """Skip or check one candidate. ``False`` = a bound stopped the walk."""
        counts.scanned += 1
        processed.add(location["id"])
        due_before = self._due_before()
        last = location.get("last_verified_at")
        if due_before is not None and last is not None and last > due_before:
            counts.skipped_not_due += 1
            return True
        if await self._in_scope(location, counts) is None:
            return True
        if counts.checked >= self.policy.max_items_per_run:   # pragma: no cover - guarded above
            processed.discard(location["id"])
            counts.scanned -= 1
            return False
        lease = await self._renew(lease)
        await self._check_one(principal, run, lease, counts, location)
        return True

    # ------------------------------------------------------------ one item
    async def _check_one(self, principal, run: Mapping[str, Any], lease: _Lease,
                         counts: _Counts, location: Mapping[str, Any]) -> Dict[str, Any]:
        """One original, through the W0-06B check, with bounded retry.

        Only a provider OUTAGE is retried. A missing, changed or forbidden
        object is a determinate answer: retrying it could only produce the same
        answer or hide a real problem behind an accidental success.
        """
        result = None
        for attempt in range(1, self.policy.max_attempts + 1):
            wait = self.policy.backoff_for(attempt)
            if wait and self._sleep is not None:
                await self._sleep(wait)
            counts.attempts += 1
            if attempt > 1:
                counts.retries += 1
            try:
                # No idempotency key is reused across attempts on purpose. The
                # W0-06B request fingerprint of an integrity check includes the
                # OBSERVATION TIME, so two genuinely different checks of one
                # item can never share a key: handing back an earlier run's key
                # would make a legitimate re-check fail with an idempotency
                # CONFLICT instead of recording what the provider said. The
                # monitor's idempotency lives where it is meaningful and is
                # tested there: the per-item checkpoint (an item already walked
                # in this run is not walked again), the deterministic finding
                # identity (one open finding and one alarm per problem) and the
                # per-transition event key (one lifecycle event per transition).
                # Every real check is its own FLOW-040 event because every real
                # check happened.
                result = await self._integrity.check(
                    principal, file_id=location["file_id"],
                    version_no=location.get("version_no"), role=location["role"])
            except FileNotFound:
                # The registry changed under the walk (a version or location is
                # gone). Not a provider problem and not a finding.
                counts.skipped_unreadable += 1
                return {"status": "skipped_unreadable"}
            # The awaited call above is the long one. Before this result is
            # allowed to become a finding, an alarm, a history entry or an
            # AuditEvent — and before another attempt hits the provider — the
            # claim must still be ours.
            await self._verify_lease(lease, what="record an integrity check")
            if result["availability"] not in RETRYABLE_AVAILABILITY:
                break
        counts.checked += 1
        if result is None:                                            # pragma: no cover
            counts.skipped_unreadable += 1
            return {"status": "skipped_unreadable"}
        if result["ok"]:
            counts.ok += 1
        await self._apply_result(principal, run, lease, counts, location, result)
        return result

    # --------------------------------------------------- finding lifecycle
    async def _apply_result(self, principal, run: Mapping[str, Any], lease: _Lease,
                            counts: _Counts, location: Mapping[str, Any],
                            result: Mapping[str, Any]) -> None:
        """Turn one W0-06B result into finding history. Never a new check.

        Nothing below writes until :meth:`_commit_item` has atomically proven
        this worker still holds a live claim. That call is the gate for the
        whole method — the finding, its history, its alarm level and its
        AuditEvents all sit behind it.
        """
        await self._commit_item(lease, run_id=run["id"], location=location, result=result)
        severity = result.get("severity") or m.severity_of(
            result["availability"], len(result.get("affected_records") or []))
        finding_type = result.get("finding_type")
        if finding_type is not None and finding_type not in MONITORED_FINDING_TYPES:
            raise MonitorConfigurationRefused(
                "unknown W0-06B finding type %r — classify it before monitoring it"
                % finding_type)
        if finding_type is not None:
            await self._observe(principal, run, lease, counts, location, result,
                                finding_type, severity)
        # Whether or not THIS check found a problem, every other open finding of
        # this location is re-judged against its own type-specific proof. A
        # result that cannot prove a type fixed leaves that finding open.
        await self._try_resolve(principal, run, lease, counts, location, result,
                                skip_type=finding_type)

    def _identity_of(self, location: Mapping[str, Any], result: Mapping[str, Any],
                     finding_type: str) -> Tuple[str, str]:
        identity = finding_identity(
            org_id=self.org_id, file_id=result["file_id"],
            version_no=result["version_no"], location_id=result["location_id"],
            provider_binding_id=result.get("provider_binding_id")
            or location.get("provider_binding_id"),
            finding_type=finding_type)
        return identity, finding_id_for(identity)

    @staticmethod
    def _evidence(result: Mapping[str, Any]) -> Dict[str, Any]:
        """The expected/observed evidence, with provider coordinates left out.

        ``container`` and ``object_key`` are provider PATHS. FLOW-016 forbids a
        path from being the identity of a file, and an alarm projection has no
        business carrying one, so the finding keeps the stable ``location_id``
        and the provider binding instead.
        """
        expected = dict(result.get("expected") or {})
        observed = dict(result.get("observed") or {})
        observed["error"] = sanitize_error(observed.get("error"))
        evidence = {"expected": expected, "observed": observed,
                    "method": result.get("method"),
                    "availability": result.get("availability")}
        assert_no_secrets(evidence)
        return evidence

    async def _observe(self, principal, run: Mapping[str, Any], lease: _Lease,
                       counts: _Counts, location: Mapping[str, Any],
                       result: Mapping[str, Any], finding_type: str,
                       severity: str) -> Dict[str, Any]:
        """Open, re-observe or reopen the ONE finding of this identity."""
        identity, finding_id = self._identity_of(location, result, finding_type)
        now = _iso(self.now())
        affected = list(result.get("affected_records") or [])
        groups = result.get("affected_by_group") or AffectedRecordResolver.grouped(affected)
        evidence = self._evidence(result)
        existing = await self.findings.find_one({"id": finding_id}, {"_id": 0})
        shared = {
            "identity": identity, "schema": FINDING_SCHEMA,
            "file_id": result["file_id"], "version_no": result["version_no"],
            "location_id": result["location_id"], "role": result.get("role"),
            "provider_kind": result.get("provider_kind"),
            "provider_binding_id": result.get("provider_binding_id"),
            "finding_type": finding_type, "availability": result["availability"],
            "severity": severity, "alarm_level": alarm_level(severity),
            "evidence": evidence,
            "affected_record_count": len(affected),
            "affected_records": affected, "affected_by_group": groups,
            "affected_as_of": now,
            "recovery": result.get("recovery"),
            # The W0-07 hand-off travels unchanged: W0-06C consumes nothing and
            # creates no DQ issue, owner, deadline or escalation.
            "dq_handoff": dict(result.get("dq_handoff") or {}),
            "last_seen": now, "last_run_id": run["id"], "updated_at": now,
        }
        if existing is None:
            consecutive = 1
            row = dict(shared, id=finding_id, state=FINDING_OPEN, first_seen=now,
                       opened_at=now, resolved_at=None, reopened_at=None, created_at=now,
                       occurrences=1, consecutive_observations=consecutive,
                       resolution=None, resolution_blocked_reason=None,
                       outage_persistence=self._outage_persistence(finding_type, consecutive),
                       transitions=[], transition_keys=[],
                       # the fence of the run that wrote this finding last
                       fence=lease.fence)
            assert_no_secrets(row, "finding")
            try:
                await self.findings.insert_one(dict(row))
            except Exception as exc:                                  # noqa: BLE001
                if not _is_duplicate_key(exc):
                    raise
                # Another worker created this exact identity first and the
                # unique index refused the second row. There is one finding per
                # identity, as the contract requires; carry on down the fenced
                # UPDATE path, which refuses us outright if that worker's fence
                # is newer than ours.
                existing = await self.findings.find_one({"id": finding_id}, {"_id": 0})
                if existing is None:                      # pragma: no cover - defensive
                    raise
            else:
                counts.findings_opened += 1
                await self._transition(principal, run, lease, finding_id,
                                       TRANSITION_OPENED, result, marker=now,
                                       severity=severity, finding_type=finding_type)
                return row
        reopened = existing.get("state") == FINDING_RESOLVED
        consecutive = 1 if reopened else int(existing.get("consecutive_observations") or 0) + 1
        update: Dict[str, Any] = dict(
            shared, state=FINDING_OPEN, consecutive_observations=consecutive,
            outage_persistence=self._outage_persistence(finding_type, consecutive),
            resolution=None, resolution_blocked_reason=None, fence=lease.fence)
        if reopened:
            update["reopened_at"] = now
            update["resolved_at"] = None
        assert_no_secrets(update, "finding")
        applied = await self.findings.update_one(
            self._fenced(lease, {"id": finding_id}),
            {"$set": update, "$inc": {"occurrences": 1}})
        self._fence_rejected(applied, lease, "re-observe this finding")
        if reopened:
            counts.findings_reopened += 1
        else:
            counts.findings_observed += 1
        await self._transition(
            principal, run, lease, finding_id,
            TRANSITION_REOPENED if reopened else TRANSITION_OBSERVED, result,
            marker=now, severity=severity, finding_type=finding_type)
        return await self.findings.find_one({"id": finding_id}, {"_id": 0})

    def _outage_persistence(self, finding_type: str, consecutive: int) -> Optional[str]:
        """Transient or persistent — only for an OUTAGE, and only with a policy.

        A provider outage is never evidence that the bytes are gone, so this
        classification changes the LABEL on the outage and nothing else. With
        no approved threshold the answer is ``unclassified``: W0-06C does not
        invent one, and neither value ever closes a finding.
        """
        if finding_type != FINDING_PROVIDER_UNAVAILABLE:
            return None
        threshold = self.policy.persistent_outage_after
        if threshold is None:
            return OUTAGE_UNCLASSIFIED
        return OUTAGE_PERSISTENT if consecutive >= threshold else OUTAGE_TRANSIENT

    async def _transition(self, principal, run: Mapping[str, Any], lease: _Lease,
                          finding_id: str, transition: str, result: Mapping[str, Any], *,
                          marker: str, severity: Optional[str], finding_type: str,
                          reason: Optional[str] = None) -> bool:
        """Append ONE lifecycle transition, idempotently, and audit it.

        The append is conditional on the transition's key being absent, so the
        same observation replayed by a resumed run cannot grow the history or
        raise the alarm twice.
        """
        key = _transition_key(finding_id, transition, marker)
        entry = {"transition": transition, "at": marker, "run_id": run["id"],
                 "event_key": key, "availability": result.get("availability"),
                 "severity": severity, "alarm_level": alarm_level(severity),
                 "method": result.get("method"), "reason": reason}
        assert_no_secrets(entry, "transition")
        applied = await self.findings.update_one(
            self._fenced(lease, {"id": finding_id, "transition_keys": {"$ne": key}}),
            {"$push": {"transitions": entry}, "$addToSet": {"transition_keys": key}})
        if getattr(applied, "matched_count", 0) != 1:
            # Either this exact transition is already recorded (idempotent
            # replay) or a newer owner has moved the finding past this fence.
            # Both mean: append nothing and audit nothing.
            return False
        await self._audit(
            action=_TRANSITION_ACTIONS[transition], actor_id=principal.user_id,
            entity_type="file_integrity_finding", entity_id=finding_id,
            entity_version=str(result.get("version_no")),
            result=RESULT_SUCCESS if transition == TRANSITION_RESOLVED else RESULT_FAILURE,
            reason=reason or ("integrity finding %s: %s" % (transition, finding_type)),
            correlation_id=run["id"], idempotency_key=key,
            related_file_ids=[result["file_id"]],
            structured_diff={"finding_id": finding_id, "finding_type": finding_type,
                             "transition": transition, "severity": severity,
                             "alarm_level": alarm_level(severity),
                             "availability": result.get("availability"),
                             "method": result.get("method"),
                             "location_id": result.get("location_id"),
                             "provider_kind": result.get("provider_kind"),
                             "provider_binding_id": result.get("provider_binding_id"),
                             "affected_record_count": len(result.get("affected_records") or []),
                             "affected_by_group": result.get("affected_by_group"),
                             "evidence": self._evidence(result)})
        return True

    async def _try_resolve(self, principal, run: Mapping[str, Any], lease: _Lease,
                           counts: _Counts, location: Mapping[str, Any],
                           result: Mapping[str, Any], *,
                           skip_type: Optional[str]) -> None:
        """Close the open findings of this location that this result PROVES fixed."""
        rows = await self.findings.find(
            {"location_id": result["location_id"], "version_no": result["version_no"],
             "state": FINDING_OPEN}, {"_id": 0}).to_list(None)
        now = _iso(self.now())
        for row in sorted(rows, key=m.sort_key):
            finding_type = row.get("finding_type")
            if finding_type == skip_type:
                continue        # this very check just observed it again
            if row.get("provider_binding_id") != result.get("provider_binding_id"):
                # A different provider binding's problem. This check says
                # nothing about it, so it stays open.
                continue
            proven, reason = resolution_proof(finding_type, result)
            if not proven:
                blocked = await self.findings.update_one(
                    self._fenced(lease, {"id": row["id"]}),
                    {"$set": {"resolution_blocked_reason": reason, "updated_at": now,
                              "fence": lease.fence}})
                self._fence_rejected(blocked, lease, "record a blocked resolution")
                continue
            closed = await self.findings.update_one(
                self._fenced(lease, {"id": row["id"]}),
                {"$set": {"state": FINDING_RESOLVED, "resolved_at": now,
                          "resolution_blocked_reason": None, "updated_at": now,
                          "consecutive_observations": 0, "fence": lease.fence,
                          "resolution": {"reason": reason, "run_id": run["id"],
                                         "availability": result.get("availability"),
                                         "method": result.get("method"), "at": now,
                                         "evidence": self._evidence(result)}}})
            self._fence_rejected(closed, lease, "resolve this finding")
            counts.findings_resolved += 1
            await self._transition(principal, run, lease, row["id"], TRANSITION_RESOLVED,
                                   result, marker=now, severity=row.get("severity"),
                                   finding_type=finding_type, reason=reason)

    # ------------------------------------------------- affected-record refresh
    async def refresh_affected_records(self, ctx, *, file_id: Optional[str] = None
                                       ) -> Dict[str, Any]:
        """Re-resolve the affected business records of the open findings.

        A relation added or removed after the check changes WHAT a finding
        affects and therefore its W0-06B severity and its alarm level. The
        counts are refreshed from the active FileRelations of the SAME tenant
        only, through the W0-06B resolver — there is no second resolution path
        and no cross-tenant read.
        """
        await self._authorize(ctx, ACTION_MONITOR_RUN, entity_id=file_id or self.org_id)
        flt: Dict[str, Any] = {"state": FINDING_OPEN}
        if file_id:
            flt["file_id"] = file_id
        rows = await self.findings.find(flt, {"_id": 0}).to_list(None)
        changed = 0
        now = _iso(self.now())
        for row in sorted(rows, key=m.sort_key):
            affected = await self._resolver.resolve(row["file_id"])
            groups = AffectedRecordResolver.grouped(affected)
            severity = m.severity_of(row["availability"], len(affected))
            level = alarm_level(severity)
            same = (int(row.get("affected_record_count") or 0) == len(affected)
                    and (row.get("affected_by_group") or {}) == groups
                    and row.get("severity") == severity
                    and row.get("alarm_level") == level)
            if same:
                continue
            await self.findings.update_one(
                {"id": row["id"]},
                {"$set": {"affected_records": affected, "affected_by_group": groups,
                          "affected_record_count": len(affected), "severity": severity,
                          "alarm_level": level, "affected_as_of": now,
                          "updated_at": now}})
            changed += 1
            await self._audit(
                action=ACTION_FINDING_AFFECTED_REFRESHED, actor_id=ctx.user_id,
                entity_type="file_integrity_finding", entity_id=row["id"],
                entity_version=str(row.get("version_no")),
                reason="affected records refreshed", related_file_ids=[row["file_id"]],
                structured_diff={"finding_id": row["id"],
                                 "affected_record_count": len(affected),
                                 "affected_by_group": groups, "severity": severity,
                                 "alarm_level": level,
                                 "previous_severity": row.get("severity"),
                                 "previous_alarm_level": row.get("alarm_level"),
                                 "previous_affected_record_count":
                                     row.get("affected_record_count")})
        return {"tenant_id": self.org_id, "examined": len(rows), "updated": changed,
                "refreshed_at": now}

    # ------------------------------------------------- the alarm projection
    async def list_findings(self, ctx, *, project_id: Optional[str] = None,
                            state: Optional[str] = None,
                            alarm_level_in: Optional[Sequence[str]] = None,
                            finding_type: Optional[str] = None,
                            file_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """This tenant's findings/alarms, scoped by FLOW-002 before disclosure.

        FOUR narrower rights apply on top of :data:`ACTION_MONITOR_READ`, and
        all four are enforced BEFORE any affected-record label or provider
        identifier leaves this method:

        * **tenant** — the view itself cannot reach another tenant's documents,
          and a caller of another tenant is refused as ``CROSS_TENANT``;
        * **project** — ``project_id`` is the scope the caller asks for, and it
          is passed to the Permission Service as the requested project scope. A
          project-scoped assignment therefore gets its OWN project and nothing
          else, and gets nothing at all without naming one (asking for every
          project is a company-scope request it cannot satisfy);
        * **module** — a module-restricted grant is refused outright, see
          :meth:`_module_unrestricted`;
        * **sensitivity** — a restricted or confidential file's alarm is listed
          only for a caller who also holds that file's sensitivity action
          (FLOW-016: reaching a file does not grant payroll, bank or personal
          documents).

        A caller whose grant is narrower than company scope receives a NARROWED
        view: only the affected records of the project it asked for, with the
        number of undisclosed records stated rather than their labels, and
        without the provider identifiers. See :meth:`_project_of`.
        """
        scope_type, scope_id = ("project", project_id) if project_id else (None, None)
        await self._authorize(ctx, ACTION_MONITOR_READ, entity_id=file_id or self.org_id,
                              scope_type=scope_type, scope_id=scope_id)
        await self._module_unrestricted(ctx, ACTION_MONITOR_READ,
                                        scope_type=scope_type, scope_id=scope_id,
                                        entity_id=file_id or self.org_id)
        company_wide = await self._allowed(ctx, ACTION_MONITOR_READ)

        flt: Dict[str, Any] = {}
        if state is not None:
            if state not in FINDING_STATES:
                raise MonitorConfigurationRefused("unknown finding state %r" % state)
            flt["state"] = state
        if finding_type is not None:
            flt["finding_type"] = finding_type
        if file_id is not None:
            flt["file_id"] = file_id
        if alarm_level_in:
            unknown = sorted(set(alarm_level_in) - set(ALARM_LEVELS))
            if unknown:
                raise MonitorConfigurationRefused(
                    "unknown alarm level: %s" % ", ".join(unknown))
            flt["alarm_level"] = {"$in": list(alarm_level_in)}

        rows = await self.findings.find(flt, {"_id": 0}).to_list(None)
        allowed: List[Dict[str, Any]] = []
        for row in sorted(rows, key=m.sort_key):
            if project_id is not None and project_id not in self._projects_of(row):
                continue        # this alarm does not touch the project asked for
            if not await self._may_read_file(ctx, row["file_id"]):
                continue
            allowed.append(self._disclose(row, company_wide=company_wide,
                                          project_id=project_id))
        return allowed

    @staticmethod
    def _projects_of(row: Mapping[str, Any]) -> FrozenSet[str]:
        """The PROJECT ids this finding's affected records name.

        Only the relation types whose target IS the ``projects`` collection
        count, because that is what a FLOW-002 project ``scope_id`` is compared
        against. A site relation targets ``sites``, a different collection, so
        it is NOT read as a project here: mapping a site onto a project is a
        business rule, and W0-06C does not invent one.
        """
        return frozenset(
            str(record.get("record_id"))
            for record in (row.get("affected_records") or [])
            if record.get("relation_type") in PROJECT_RELATION_TYPES
            and record.get("record_id"))

    def _disclose(self, row: Mapping[str, Any], *, company_wide: bool,
                  project_id: Optional[str]) -> Dict[str, Any]:
        """One finding as this caller is allowed to see it.

        A company-scoped grant sees the finding as recorded. A narrower grant
        sees the same ALARM — type, severity, level, state, history, the total
        number of affected records — but only the affected records of the
        project it is scoped to, and no provider identifiers: a record in
        another group cannot be shown to be inside that project without a
        business mapping this package must not invent, so it is counted and
        withheld rather than guessed at either way.
        """
        out = dict(row)
        records = list(row.get("affected_records") or [])
        total = int(row.get("affected_record_count") or len(records))
        if company_wide:
            out["disclosure"] = {"scope": "company", "project_id": project_id,
                                 "affected_records_withheld": 0,
                                 "provider_identifiers": True}
            return out
        visible = [r for r in records
                   if r.get("relation_type") in PROJECT_RELATION_TYPES
                   and str(r.get("record_id")) == project_id]
        out["affected_records"] = visible
        out["affected_by_group"] = AffectedRecordResolver.grouped(visible)
        out["affected_record_count"] = total          # the alarm's own weight
        # `identity` is the deterministic key and it ENCODES the provider
        # binding and the location, so withholding the fields while leaving the
        # key behind would disclose them anyway. The opaque `id` stays: it is a
        # hash, and a caller needs something to refer to the alarm by.
        for field in ("provider_binding_id", "provider_kind", "location_id", "evidence",
                      "identity"):
            out.pop(field, None)
        out["disclosure"] = {"scope": "project", "project_id": project_id,
                             "affected_records_withheld": total - len(visible),
                             "provider_identifiers": False}
        return out

    async def _allowed(self, ctx, action: str, *, scope_type: Optional[str] = None,
                       scope_id: Optional[str] = None) -> bool:
        """Would FLOW-002 allow this, yes or no? Silent: it audits nothing.

        Used for the two PROBES below, which ask the Permission Service a
        question rather than make a decision. A probe that came back ``False``
        is not a denial of anything the caller asked for, so auditing it would
        fill the chain with refusals nobody attempted.
        """
        try:
            await authorize(ctx, action, org_id=self.org_id,
                            scope_type=scope_type, scope_id=scope_id)
            return True
        except FileAccessDenied:
            return False

    async def _module_unrestricted(self, ctx, action: str, *, scope_type: Optional[str],
                                   scope_id: Optional[str], entity_id: str) -> None:
        """Refuse a module-restricted grant. FAIL CLOSED, by design.

        ``_evaluate_one`` enforces an assignment's ``module`` only when the
        caller names a requested module, so a company-scoped grant restricted
        to one module would otherwise project EVERY module's findings. Deciding
        which module a finding belongs to would need a file/relation → module
        mapping, and the canon has none: ``module`` appears only as per-route
        literals, with no registry and no mapping from a file category or a
        relation group. Inventing one is exactly what this task forbids.

        So the question asked here is the only one that can be answered from
        the canon: *is the grant restricted to some module at all?* Requesting
        the reserved :data:`MODULE_PROBE` is denied by any assignment that
        names a module and allowed by any assignment that names none. If every
        matching grant is module-restricted, the projection refuses rather than
        guessing which findings are in that module.
        """
        if await self._allowed(ctx, action, scope_type=scope_type, scope_id=scope_id):
            if not await self._allowed_for_module(ctx, action, scope_type, scope_id):
                denied = FileAccessDenied(action, permission_service.REASON_MODULE_NOT_ALLOWED)
                await self._audit(
                    action=audit_trail.ACTION_PERMISSION_FAILED,
                    actor_id=getattr(ctx, "user_id", None) or "anonymous",
                    entity_type="file_integrity_monitor", entity_id=entity_id,
                    result=RESULT_FAILURE,
                    reason="integrity alarm projection refused: module-restricted grant",
                    error_code=denied.reason_code,
                    actor_type=getattr(ctx, "actor_type", ACTOR_HUMAN),
                    structured_diff={"action": action, "reason_code": denied.reason_code,
                                     "tenant_id": self.org_id,
                                     "module_probe": MODULE_PROBE})
                raise denied

    async def _allowed_for_module(self, ctx, action: str, scope_type: Optional[str],
                                  scope_id: Optional[str]) -> bool:
        try:
            decision = await permission_service.evaluate_permission(
                ctx, action, module=MODULE_PROBE, scope_type=scope_type,
                scope_id=scope_id, resource_tenant_id=self.org_id)
        except Exception:                                             # noqa: BLE001
            return False                                   # fail closed, always
        return bool(decision.allowed)

    async def _may_read_file(self, ctx, file_id: str) -> bool:
        """The file's own sensitivity right, evaluated through FLOW-002."""
        file_row = await self._registry.get_file(file_id)
        if not file_row:
            return False
        action = sensitivity_action(file_row.get("sensitivity"))
        if action is None:
            return True
        return await self._allowed(ctx, action)


# ------------------------------------------------------- the resolution rules
def _complete_content_proof(expected: Mapping[str, Any], observed: Mapping[str, Any],
                            method: Optional[str], *, require_read: bool
                            ) -> Tuple[bool, str]:
    """Was the object POSITIVELY identified and its content actually compared?

    One rule, used by every type that needs content evidence, so no type can
    quietly accept less than another:

    * ``require_read`` demands a real ``read_and_hash`` — bytes BEG_Work
      actually fetched. A provider-reported digest (``server_checksum``) comes
      from ``stat()``, which an adapter may answer without ever performing an
      authorized read, so it cannot prove read access was restored.
    * otherwise some real content method is still required: a verdict that
      compared nothing (``none``) or only a length (``size_only``) is not
      evidence that the right bytes are back.
    * whatever the canonical record EXPECTS must have been observed and must
      match. A missing observed checksum or a missing observed size next to a
      known expected one is an incomplete proof, not a pass.
    """
    if require_read and method != VERIFY_READ_AND_HASH:
        return False, "incomplete_proof:no_authorized_read"
    if method not in CONTENT_METHODS:
        return False, "incomplete_proof:no_content_comparison"

    want_sum, got_sum = expected.get("checksum"), observed.get("checksum")
    if want_sum:
        if not got_sum:
            return False, "incomplete_proof:no_observed_checksum"
        if (want_sum.get("algorithm") or "") != (got_sum.get("algorithm") or "") \
                or want_sum.get("value") != got_sum.get("value"):
            return False, "incomplete_proof:checksum_still_differs"

    want_size, got_size = expected.get("size_bytes"), observed.get("size_bytes")
    if want_size is not None:
        if got_size is None:
            return False, "incomplete_proof:no_observed_size"
        if want_size != got_size:
            return False, "incomplete_proof:size_still_differs"
    return True, ""


def resolution_proof(finding_type: Optional[str], result: Mapping[str, Any]
                     ) -> Tuple[bool, str]:
    """``(proven, reason)`` — the TYPE-SPECIFIC proof that a finding is fixed.

    A provider that answers at all is not proof, and neither is a verdict that
    merely failed to contradict the record. Each type needs the evidence that
    answers what actually failed, and an incomplete proof is never a
    resolution: the finding stays open and the reason says what is missing.

    ====================  ===========================================================
    finding type          what closes it
    ====================  ===========================================================
    ``provider_unavailable``  a COMPLETE object + content verification
    ``missing_original``      an identified object whose content was compared
    ``checksum_mismatch``     the canonical checksum AND size observed and matching
    ``permission_failure``    an authorized READ of the bytes, never a reachable stat
    ``external_change``       the recorded provider identity matching again
    ====================  ===========================================================
    """
    if finding_type not in MONITORED_FINDING_TYPES:
        return False, "unknown_finding_type"
    if not result.get("ok"):
        return False, "still_failing:%s" % result.get("availability")

    expected = result.get("expected") or {}
    observed = result.get("observed") or {}
    method = result.get("method")

    if finding_type == FINDING_PROVIDER_UNAVAILABLE:
        # An outage is closed by a verification that actually completed, not by
        # the provider merely answering: ``available`` can come back with
        # nothing compared at all when there is no provider digest and no
        # readable body, and that says nothing about the bytes.
        proven, reason = _complete_content_proof(expected, observed, method,
                                                 require_read=False)
        return (True, "provider_verification_succeeded") if proven else (False, reason)

    if finding_type == FINDING_MISSING:
        proven, reason = _complete_content_proof(expected, observed, method,
                                                 require_read=False)
        if not proven:
            return False, reason
        if expected.get("provider_file_id") and observed.get("provider_file_id") \
                and expected["provider_file_id"] != observed["provider_file_id"]:
            return False, "incomplete_proof:provider_object_not_identified"
        return True, "identified_original_present_and_compared"

    if finding_type == FINDING_CHECKSUM_MISMATCH:
        # A checksum finding cannot be closed without a canonical checksum to
        # close it against, whatever else the provider reports.
        if not expected.get("checksum"):
            return False, "incomplete_proof:no_checksum_comparison"
        proven, reason = _complete_content_proof(expected, observed, method,
                                                 require_read=False)
        return (True, "canonical_checksum_and_size_match") if proven else (False, reason)

    if finding_type == FINDING_PERMISSION_FAILURE:
        # The access that failed is READ access. A reachable ``stat`` — which
        # is where a provider-reported digest comes from — does not prove it
        # came back, so only bytes BEG_Work actually read will close this.
        proven, reason = _complete_content_proof(expected, observed, method,
                                                 require_read=True)
        return (True, "authorized_content_read_succeeded") if proven else (False, reason)

    # external_change: the recorded provider identity must match again. Bytes
    # alone are never enough — adopting a replaced object silently is exactly
    # what FLOW-016 forbids, so an unprovable identity leaves it open for an
    # explicit decision.
    pairs = (("provider_file_id", expected.get("provider_file_id"),
              observed.get("provider_file_id")),
             ("provider_version_id", expected.get("provider_version_id"),
              observed.get("provider_version_id")))
    compared = False
    for name, want, got in pairs:
        if want is None:
            continue
        if got is None:
            return False, "requires_explicit_decision:%s_unobserved" % name
        if want != got:
            return False, "requires_explicit_decision:%s_still_differs" % name
        compared = True
    if not compared:
        return False, "requires_explicit_decision:no_recorded_provider_identity"
    return True, "recorded_provider_identity_matches_again"


#: The B contract and the C monitor must name the same five problems. A new
#: availability state in W0-06B would otherwise be scheduled and never
#: reported, which is the exact failure this assertion exists to prevent.
assert MONITORED_FINDING_TYPES == {v for v in FINDING_TYPES.values() if v is not None}

#: Every relation this package reads as a project must actually target the
#: ``projects`` collection. If a relation type is ever retargeted, the project
#: scope of the alarm projection must be reconsidered rather than silently
#: comparing a FLOW-002 project id against some other collection's id.
assert {m.RELATION_TARGETS[r] for r in PROJECT_RELATION_TYPES} == {"projects"}
assert MODULE_PROBE not in ("", None) and MODULE_PROBE.startswith("__beg_work")
assert set(ALARM_BY_SEVERITY.values()) <= set(ALARM_LEVELS)

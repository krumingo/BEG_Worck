"""
W0-06D — legacy file/media adoption READINESS. A dry run, and nothing else.

W0-06A answered two questions on paper: the inventory says WHERE every
file-bearing field is today, and :mod:`app.files.migration_map` says what each
row would become. Both are pure: they never opened a database, never looked at
a disk and never asked a provider. So the plan has never been compared with
reality, and nobody can yet answer the only question that matters before a
migration: *which of these rows could actually be adopted, and what is in the
way of the rest?*

This module answers that, and refuses to do anything else:

* a tenant-bound, provider-neutral **read-only scanner** over the declared
  legacy DB sources and a safe physical inventory;
* **reconciliation in both directions** — a DB row whose original is not
  there, a physical object no row can be attributed to, and a pointer with no
  resolvable owning File;
* a **deterministic readiness state** per item, from one documented precedence,
  with the distinctions the contract insists on: a missing object is not an
  unreachable provider, an unknown checksum is not a checksum conflict, and an
  orphan is not an owner;
* a **plan fingerprint** and a NON-MUTATING validation hook that refuses a
  stale plan when any observed input has drifted.

What it deliberately does NOT do
--------------------------------

* **There is no apply, commit, migrate or adopt endpoint.** Not disabled, not
  flagged off — absent. The contract gives W0-06D the refusal/validation side
  of the eventual migration and nothing else, so there is no code path here
  that moves, copies, deletes, overwrites or rewrites anything: no byte
  transfer, no relation rewrite, no source-field clear, no duplicate merge, no
  provider activation, no destructive repair.
* **It mints no second source registry.** :data:`migration_map.LEGACY_SOURCES`
  is the only declared legacy-source map and
  :func:`migration_map.deterministic_file_id` the only id derivation. A source
  this module does not recognise is reported as ``UNSUPPORTED_SOURCE``, never
  guessed at.
* **It invents no business approval.** There is no approver, role, deadline,
  SLA or acceptance rule here. Where a human must decide, the item says
  ``NEEDS_HUMAN_DECISION`` and carries the evidence; FLOW-033/034 is W0-07.
* **It never declares the application disk adoptable.** ``ADOPT_IN_PLACE`` is
  reachable only from a verified, tenant-owned, customer-managed provider
  location, and ``legacy_app_disk`` is not one of
  :data:`app.files.models.CUSTOMER_MANAGED_PROVIDER_KINDS` — so the rule is
  structural, not a comment. Inline base64 is the same: it needs a future,
  separately authorised provider write.
* **A filename confers nothing.** An orphan physical object does not become
  owned because its path resembles a tenant root, and the same path, name or
  checksum in two tenants never produces one identity, duplicate or relation —
  the owner is inside the derived ``file_id``.

Reading bytes
-------------

A checksum can only be computed by reading the object, which is the one
genuinely dangerous thing a "read-only" scanner does. It is therefore off by
default and, when switched on, fenced four ways: an allowlisted root, a
real-path containment check that a DB-supplied path cannot escape, a refusal of
any symlink or reparse point, and a bounded budget of objects and bytes. Every
one of those fences is applied in :meth:`LegacyRootInventory._observe`, which
is the single way into a ``stat``, an ``open`` or a ``read`` — so the physical
walk and a path a database row named are gated identically, and a path that
fails any fence is reported, not read. Nothing is opened for writing anywhere
in this module.

What the C02 correction changed
-------------------------------

The C01 independent review found four ways this module said more than it had
proven. None of them changed the architecture; all four made a claim require
the evidence behind it.

1. **Readiness is observed, never inferred.** ``READY_TO_ADOPT`` and
   ``ADOPT_IN_PLACE`` rested on ``verified_location`` alone — a fact about the
   registry. A stored ``available`` status with nothing observed on disk was
   enough. Readiness now needs the actual legacy original observed, its
   checksum AND its size observed, a proven owner, the registered object
   proven to be the SAME object, and the verified customer-managed location.
   Each missing piece is named in ``reasons``.
2. **A relation identity, not a relation count.** ``ALREADY_REGISTERED`` and
   ``REGISTER_REFERENCE_ONLY`` accepted ``relation_count > 0``, so one
   unrelated relation satisfied a plan proposing a different target. The exact
   proposed ``(relation_type, record_id)`` pairs are now compared against this
   tenant's active relations, and each target is resolved in this tenant.
3. **A budget belongs to a pass.** The counters lived on the inventory, which
   ``validate_plan`` reuses, so a second look at unchanged inputs started
   with the first one's budget spent and raised ``AdoptionPlanStale`` with
   nothing drifted. :class:`ScanPass` holds them, and one pass charges one
   object once — the physical walk and the DB rows share the limit.
4. **The caps are enforced during the read.** They were checked once against
   the size ``stat`` reported and the read then ran to EOF, so a file that
   grew, or a stream that returned more than it declared, was hashed past
   both caps. The read is now bounded by a single ceiling and an overrun
   fails closed.

What the C03 correction changed
-------------------------------

The C02 independent review found three places where a bound was declared and
not actually enforced. The architecture is unchanged; each fix moves a check
to where it cannot be bypassed.

1. **An object limit that every entry path obeys.** ``max_objects`` was
   checked and charged in ``walk`` alone, so ``observe_path`` — the DB-row
   path — obeyed no object limit at all: at ``max_objects=0`` a row naming an
   existing file was still opened and hashed. The limit belongs to the object,
   so it is charged in :meth:`LegacyRootInventory._observe`. A refusal is not
   cached, because it is not an observation; a cached observation of the same
   object still reuses its one charge.
2. **A read that cannot exceed its budget.** The previous fix asked for one
   byte past the ceiling so an overrun would surface immediately — which
   settled the verdict but not the budget: at a cap of zero it physically read
   and charged a byte. The ceiling is now the declared size, already proven
   within both caps, every ``read`` asks for at most what is owed, and nothing
   is opened at a zero ceiling. Growth is caught by a second ``stat`` instead.
3. **The walk gates its file entries.** It filtered symlinked *directories*
   and then handed filenames straight to ``_observe``, which never consulted
   :func:`path_within_root`; a symlink FILE in a real directory was therefore
   followed out of the allowlisted root. The gate now runs on every entry,
   before the stat, the open and the cache.

Canon: `docs/architecture/W0-06D_LEGACY_ADOPTION_READINESS.md`, FLOW-016,
FLOW-002, FLOW-040, TENANCY_MODEL, and the W0-06A inventory and migration map.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.audit.envelope import (
    ACTOR_HUMAN,
    ACTOR_SYSTEM,
    RESULT_FAILURE,
    RESULT_SUCCESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R3_SECURITY_ACCESS,
)
from app.files import audit_trail
from app.files import migration_map as mp
from app.files import models as m
from app.files.authorization import FileAccessDenied, authorize, sensitivity_action
from app.files.monitoring import assert_no_secrets, sanitize_error

#: ``beg.<slice>.<thing>/<version>`` like every other W0-06 result contract, so
#: a stored scan can be recognised and migrated by a later slice.
ADOPTION_SCHEMA = "beg.w0-06d.legacy_adoption_readiness/v1"

# --------------------------------------------------------------- collections
#: One document per scan RUN: its inputs, its budget, its counts, its hash.
ADOPTION_SCANS_COLLECTION = "legacy_adoption_scans"
#: One document per observed ITEM: its evidence, its state, its proposal.
ADOPTION_ITEMS_COLLECTION = "legacy_adoption_items"

ADOPTION_COLLECTIONS: FrozenSet[str] = frozenset({
    ADOPTION_SCANS_COLLECTION, ADOPTION_ITEMS_COLLECTION})

ID_PREFIX_SCAN = "adsc_"
ID_PREFIX_ITEM = "adit_"

# ------------------------------------------------------------ FLOW-002 actions
#: Running a dry-run scan. A tenant-scoped principal needs THIS action in a
#: live RoleAssignment of that tenant; nothing here grants one.
ACTION_ADOPTION_SCAN = "file.adoption.scan"
#: Reading the readiness projection. Separate from running it, because an
#: operator who may look at the plan is not thereby allowed to produce one.
ACTION_ADOPTION_READ = "file.adoption.read"

#: FLOW-040 action names of this slice.
AUDIT_SCAN_STARTED = "file.adoption.scan.started"
AUDIT_SCAN_FINISHED = "file.adoption.scan.finished"
AUDIT_PLAN_VALIDATED = "file.adoption.plan.validated"
AUDIT_PLAN_REFUSED = "file.adoption.plan.refused"
AUDIT_DECISION_REQUIRED = "file.adoption.decision_required"

_RETENTION: Dict[str, str] = {
    AUDIT_SCAN_STARTED: RETENTION_R2_PROJECT_OPERATIONAL,
    AUDIT_SCAN_FINISHED: RETENTION_R2_PROJECT_OPERATIONAL,
    AUDIT_PLAN_VALIDATED: RETENTION_R2_PROJECT_OPERATIONAL,
    AUDIT_PLAN_REFUSED: RETENTION_R2_PROJECT_OPERATIONAL,
    AUDIT_DECISION_REQUIRED: RETENTION_R2_PROJECT_OPERATIONAL,
    audit_trail.ACTION_PERMISSION_FAILED: RETENTION_R3_SECURITY_ACCESS,
}

# ------------------------------------------------------------- the directions
#: The item came from a declared legacy DB row.
DIRECTION_DB_ROW = "db_row"
#: The item came from the physical inventory and no row claimed it.
DIRECTION_PHYSICAL_OBJECT = "physical_object"

DIRECTIONS: FrozenSet[str] = frozenset({DIRECTION_DB_ROW, DIRECTION_PHYSICAL_OBJECT})

# -------------------------------------------------------- the readiness states
READY_TO_ADOPT = "READY_TO_ADOPT"
ALREADY_REGISTERED = "ALREADY_REGISTERED"
DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
ORPHAN_DB_RECORD = "ORPHAN_DB_RECORD"
ORPHAN_PHYSICAL_FILE = "ORPHAN_PHYSICAL_FILE"
MISSING_ORIGINAL = "MISSING_ORIGINAL"
TENANT_AMBIGUOUS = "TENANT_AMBIGUOUS"
BUSINESS_RELATION_AMBIGUOUS = "BUSINESS_RELATION_AMBIGUOUS"
CHECKSUM_CONFLICT = "CHECKSUM_CONFLICT"
UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
BLOCKED = "BLOCKED"
#: The source declares no file content at all (``NO_FILE_CONTENT``). Counted
#: apart from both ready and blocked, exactly as W0-06A's summary does: a row
#: with nothing to adopt is neither work to do nor work that is stuck.
NO_CONTENT = "NO_CONTENT"

READINESS_STATES: FrozenSet[str] = frozenset({
    READY_TO_ADOPT, ALREADY_REGISTERED, DUPLICATE_CANDIDATE, ORPHAN_DB_RECORD,
    ORPHAN_PHYSICAL_FILE, MISSING_ORIGINAL, TENANT_AMBIGUOUS,
    BUSINESS_RELATION_AMBIGUOUS, CHECKSUM_CONFLICT, UNSUPPORTED_SOURCE,
    BLOCKED, NO_CONTENT,
})

#: THE precedence. One order, documented once, applied by
#: :func:`readiness_state` and by nothing else, so two items with the same
#: evidence can never be classified differently.
#:
#: It runs from "we cannot even say whose this is" down to "this is fine",
#: because a safety answer must beat a convenience answer:
#:
#: 1. ``UNSUPPORTED_SOURCE`` — the source is not declared, so no later question
#:    is even meaningful;
#: 2. ``TENANT_AMBIGUOUS`` — no owner, or more than one. Everything else in
#:    this module is tenant-scoped, so this must be settled first;
#: 3. ``CHECKSUM_CONFLICT`` — the registry already holds this identity with
#:    DIFFERENT content. Louder than "already registered", which is the same
#:    comparison with the opposite answer;
#: 4. ``BUSINESS_RELATION_AMBIGUOUS`` — the row implies a relation nothing can
#:    resolve. Adopting it would attach a file to the wrong record;
#: 5. ``MISSING_ORIGINAL`` — the original is PROVEN absent. Below ambiguity,
#:    because "absent" is only meaningful once the owner is known;
#: 6. ``ORPHAN_PHYSICAL_FILE`` / ``ORPHAN_DB_RECORD`` — nothing on the other
#:    side of the reconciliation;
#: 7. ``ALREADY_REGISTERED`` — exact same-tenant identity, verified;
#: 8. ``DUPLICATE_CANDIDATE`` — content may match ANOTHER file. Never merged;
#: 9. ``READY_TO_ADOPT`` — only with zero blockers;
#: 10. ``BLOCKED`` — the honest fallback. Anything with a blocker that no
#:     state above named is blocked, never "ready".
STATE_PRECEDENCE: Tuple[str, ...] = (
    UNSUPPORTED_SOURCE,
    TENANT_AMBIGUOUS,
    CHECKSUM_CONFLICT,
    BUSINESS_RELATION_AMBIGUOUS,
    MISSING_ORIGINAL,
    ORPHAN_PHYSICAL_FILE,
    ORPHAN_DB_RECORD,
    ALREADY_REGISTERED,
    DUPLICATE_CANDIDATE,
    READY_TO_ADOPT,
    BLOCKED,
)

# ----------------------------------------------------------- proposed actions
#: The original is ALREADY at a verified, tenant-owned, customer-managed
#: provider location, so adopting it registers identity without moving bytes.
#: Unreachable for ``legacy_app_disk`` by construction.
PROPOSE_ADOPT_IN_PLACE = "ADOPT_IN_PLACE"
#: An existing same-tenant File with a proven relation: the row becomes a
#: reference/relation, not a second File.
PROPOSE_REGISTER_REFERENCE_ONLY = "REGISTER_REFERENCE_ONLY"
#: A human must answer before anything can be proposed.
PROPOSE_NEEDS_HUMAN_DECISION = "NEEDS_HUMAN_DECISION"
#: Technically coherent, but it needs a step this slice is not allowed to
#: propose — a provider onboarding, a byte transfer, a separate authorisation.
PROPOSE_BLOCKED_FUTURE_STEP = "BLOCKED_FUTURE_STEP"
#: Nothing to adopt.
PROPOSE_NO_ACTION = "NO_ACTION"

PROPOSED_ACTIONS: FrozenSet[str] = frozenset({
    PROPOSE_ADOPT_IN_PLACE, PROPOSE_REGISTER_REFERENCE_ONLY,
    PROPOSE_NEEDS_HUMAN_DECISION, PROPOSE_BLOCKED_FUTURE_STEP, PROPOSE_NO_ACTION,
})

# ------------------------------------------------------------------ the reasons
#: W0-06D's own reasons. The W0-06A blockers travel through unchanged beside
#: them, so a reviewer sees both the paper blocker and what reality added.
REASON_SOURCE_NOT_DECLARED = "SOURCE_NOT_DECLARED"
REASON_ORIGINAL_ABSENT = "ORIGINAL_PROVEN_ABSENT"
#: The crucial distinction the contract spells out: a provider or filesystem
#: that could not be read says NOTHING about whether the bytes exist.
REASON_SOURCE_INACCESSIBLE = "SOURCE_INACCESSIBLE"
REASON_CHECKSUM_UNKNOWN = "CHECKSUM_NOT_READ"
REASON_CHECKSUM_DIFFERS = "CHECKSUM_DIFFERS_FROM_REGISTERED"
REASON_SIZE_DIFFERS = "SIZE_DIFFERS_FROM_REGISTERED"
REASON_LOCATION_DRIFT = "REGISTERED_LOCATION_DIFFERS"
REASON_OWNERSHIP_UNVERIFIED = "OWNERSHIP_UNVERIFIED"
REASON_UNATTRIBUTED_OBJECT = "NO_ATTRIBUTABLE_DB_ROW"
REASON_POINTER_WITHOUT_FILE = "POINTER_HAS_NO_OWNING_FILE"
REASON_PATH_OUTSIDE_ROOT = "PATH_ESCAPES_ALLOWLISTED_ROOT"
REASON_PATH_IS_LINK = "PATH_IS_SYMLINK_OR_REPARSE_POINT"
REASON_NOT_CUSTOMER_MANAGED = "CURRENT_LOCATION_NOT_CUSTOMER_MANAGED"
REASON_BUDGET_EXHAUSTED = "CHECKSUM_BUDGET_EXHAUSTED"
REASON_CONTENT_READ_NOT_PERMITTED = "CONTENT_READ_NOT_PERMITTED"
REASON_DUPLICATE_SAME_CHECKSUM = "SAME_CHECKSUM_AS_ANOTHER_FILE"
#: C01 review defect 1: readiness was being read off a stored location status.
#: These name what was actually missing instead.
REASON_ORIGINAL_NOT_OBSERVED = "LEGACY_ORIGINAL_NOT_OBSERVED"
REASON_SIZE_UNKNOWN = "SIZE_NOT_OBSERVED"
REASON_SAME_OBJECT_UNPROVEN = "OBSERVED_OBJECT_NOT_PROVEN_SAME"
#: C02 review defects 1 and 2: a bounded inventory that is not actually
#: bounded, and a bounded read that physically overran its cap.
REASON_OBJECT_BUDGET_EXHAUSTED = "OBJECT_BUDGET_EXHAUSTED"
REASON_SIZE_UNCERTAIN = "SIZE_UNCERTAIN_AT_READ_TIME"
#: C01 review defect 2: a relation COUNT is not a relation identity.
REASON_RELATION_NOT_REGISTERED = "PROPOSED_RELATION_NOT_REGISTERED"
REASON_RELATION_TARGET_MISSING = "RELATION_TARGET_NOT_IN_THIS_TENANT"
REASON_NO_PROPOSED_RELATION = "NO_PROPOSED_BUSINESS_RELATION"

#: Keys that may never appear in a stored evidence block, a projection or an
#: AuditEvent. ``assert_no_secrets`` (W0-06C) already refuses credential-shaped
#: keys; these are the W0-06D additions — a raw filesystem path is not a secret
#: but it is not a client's business either, and FLOW-016 forbids a path from
#: being an identity.
REDACTED_EVIDENCE_KEYS: Tuple[str, ...] = (
    "absolute_path", "real_path", "provider_response", "raw_row", "bytes",
    "signed_url", "presigned_url",
)


class AdoptionScanRefused(ValueError):
    """The scan was asked for something it must not do. Fail closed."""


class AdoptionPlanStale(RuntimeError):
    """An observed input drifted since the plan was made. The plan is refused.

    Raised by :meth:`LegacyAdoptionReadiness.validate_plan`, which is the ONLY
    thing W0-06D offers in place of an apply endpoint: it re-observes and says
    no. It never repairs the plan and never executes the stale one.
    """

    def __init__(self, scan_id: str, drifted: Sequence[Mapping[str, Any]]):
        super().__init__(
            "adoption plan %s is stale: %d item(s) drifted" % (scan_id, len(drifted)))
        self.scan_id = scan_id
        self.drifted = list(drifted)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _digest(payload: Any) -> str:
    """A stable sha256 over canonical JSON. The basis of every fingerprint."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        .encode("utf-8")).hexdigest()


# ===================================================== the physical inventory
@dataclass(frozen=True)
class PhysicalObject:
    """One object the safe inventory really saw. Never a path it was told about."""

    #: Path RELATIVE to the allowlisted root. The absolute path never leaves
    #: the scanner: FLOW-016 forbids a path from being an identity, and a
    #: client projection has no business holding the server's filesystem.
    relative_path: str
    root: str
    size_bytes: Optional[int]
    checksum: Optional[Dict[str, str]]
    #: Why the checksum is absent, when it is.
    checksum_reason: Optional[str] = None
    readable: bool = True
    refusal: Optional[str] = None

    @property
    def legacy_location(self) -> str:
        """The location string the migration map would produce for this object."""
        return "%s/%s" % (self.root.rstrip("/"), self.relative_path)


def path_within_root(root: str, candidate: str) -> Tuple[bool, Optional[str]]:
    """``(safe, refusal)`` for one candidate path under one allowlisted root.

    This is the gate a DB-supplied path must pass before the scanner will so
    much as ``stat`` it, and it is deliberately a pure function so a test can
    hammer it without a filesystem.

    Two different refusals, because they are two different attacks:

    * ``PATH_ESCAPES_ALLOWLISTED_ROOT`` — after resolving ``..`` and any link,
      the real path is not inside the root. ``/app/backend/uploads/../../etc``
      is the obvious form; the subtle one is a root-looking prefix such as
      ``/app/backend/uploads-evil``, which a plain ``startswith`` accepts and
      ``commonpath`` does not;
    * ``PATH_IS_SYMLINK_OR_REPARSE_POINT`` — the path, or any directory on the
      way to it, is a link. Such a path may resolve inside the root today and
      somewhere else after the next write, so it is refused outright rather
      than resolved. "It resolves inside the root" is not a safety property
      when another process owns the link.
    """
    if not isinstance(candidate, str) or not candidate:
        return False, REASON_PATH_OUTSIDE_ROOT
    real_root = os.path.realpath(root)
    absolute = candidate if os.path.isabs(candidate) \
        else os.path.join(real_root, candidate)
    # Any link on the way to the object, not just the object itself.
    probe = absolute
    while True:
        if os.path.islink(probe):
            return False, REASON_PATH_IS_LINK
        parent = os.path.dirname(probe)
        if parent == probe or len(parent) < len(real_root):
            break
        probe = parent
    real = os.path.realpath(absolute)
    try:
        if os.path.commonpath([real_root, real]) != real_root:
            return False, REASON_PATH_OUTSIDE_ROOT
    except ValueError:                       # different drives on Windows
        return False, REASON_PATH_OUTSIDE_ROOT
    return True, None


@dataclass
class ScanPass:
    """The budget counters of ONE independent scan pass.

    C01 review defect 3. These counters used to live on
    :class:`LegacyRootInventory`, which ``validate_plan`` reuses: a second pass
    over unchanged inputs therefore started with the first pass's budget
    already spent, so an item hashed the first time came back
    ``CHECKSUM_BUDGET_EXHAUSTED`` the second time, its fingerprint changed, and
    :class:`AdoptionPlanStale` was raised with nothing whatsoever having
    drifted. A budget is a property of a PASS, so it lives here and the
    inventory holds none.

    ``seen`` is the other half of the fix: one pass charges one object ONCE.
    The physical walk and the DB rows that name the same object share this
    pass's limit — which is what "shared limit" has to mean — and a row whose
    object the walk already observed reuses that observation instead of
    re-hashing it. Without it the same object could be charged twice in one
    pass, which is both wasteful and non-deterministic at an exact limit.
    """

    budget: "ScanBudget"
    objects_seen: int = 0
    checksums_read: int = 0
    bytes_read: int = 0
    truncated: bool = False
    #: ``absolute real path -> what this pass already observed about it``.
    seen: Dict[str, "PhysicalObject"] = field(default_factory=dict)

    def as_record(self) -> Dict[str, Any]:
        return {"objects_seen": self.objects_seen,
                "checksums_read": self.checksums_read,
                "bytes_read": self.bytes_read, "truncated": self.truncated,
                "budget": self.budget.as_record()}


@dataclass
class ScanBudget:
    """How much the scanner may look at. Exceeding a bound stops it, politely.

    A readiness scan runs over a customer's real disk, so it is bounded in
    every dimension a runaway could grow: how many objects it walks, how many
    it hashes and how many bytes it reads. A bound that is reached is reported
    as a reason on the affected items, never as a silent truncation — an item
    the scan did not look at must not read as an item that is fine.
    """

    max_objects: int = 5_000
    max_checksum_objects: int = 500
    max_checksum_bytes: int = 256 * 1024 * 1024
    #: Reading bytes is the one genuinely dangerous thing here, so it is OFF
    #: unless a caller explicitly permits it for this scan.
    allow_content_read: bool = False
    #: Objects larger than this are never hashed, whatever the budget allows.
    max_object_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        for name in ("max_objects", "max_checksum_objects", "max_checksum_bytes",
                     "max_object_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise AdoptionScanRefused("%s must be a non-negative integer" % name)
        self.allow_content_read = bool(self.allow_content_read)

    def as_record(self) -> Dict[str, Any]:
        return {"max_objects": self.max_objects,
                "max_checksum_objects": self.max_checksum_objects,
                "max_checksum_bytes": self.max_checksum_bytes,
                "max_object_bytes": self.max_object_bytes,
                "allow_content_read": self.allow_content_read}


class LegacyRootInventory:
    """A read-only walk of allowlisted legacy roots. Opens nothing for writing.

    Every object it reports was really seen under a root the caller allowlisted,
    reached without traversing a link, and hashed only inside the budget. A
    path it was merely TOLD about — by a database row — goes through
    :meth:`observe_path`, which applies the same gate and answers with evidence
    instead of bytes when the gate refuses.
    """

    def __init__(self, roots: Sequence[str], *, budget: Optional[ScanBudget] = None,
                 opener=None, declared_roots: Optional[Mapping[str, str]] = None):
        if not roots:
            raise AdoptionScanRefused("a physical inventory needs at least one root")
        #: Resolved once. A root given as a relative path or through a link
        #: would otherwise mean something different on every call.
        self.roots: Tuple[str, ...] = tuple(
            sorted({os.path.realpath(r) for r in roots if isinstance(r, str) and r}))
        if not self.roots:
            raise AdoptionScanRefused("no usable allowlisted root")
        self.budget = budget or ScanBudget()
        #: Injected in tests; the default is the real, READ-only open.
        self._opener = opener or (lambda path: open(path, "rb"))
        #: ``declared legacy root -> the allowlisted root it is mounted at here``.
        #:
        #: :data:`app.files.migration_map.LEGACY_UPLOADS_ROOT` is the path of the
        #: LIVE application (``/app/backend/uploads``). A readiness scan is run
        #: against whatever that directory is on the machine doing the scanning
        #: — a restored copy, a staging mount, a test fixture — and it must not
        #: have to pretend the production path exists locally. So a declared
        #: root may be mapped onto an allowlisted one.
        #:
        #: This widens nothing. The translation is a prefix rewrite onto a root
        #: the CALLER allowlisted, and the resulting path then goes through the
        #: identical containment and symlink gate; a mapped path that climbs out
        #: of its new root is refused exactly like an unmapped one. With no map,
        #: the declared roots are the real roots, as in production.
        mapped: Dict[str, str] = {}
        for declared, actual in (declared_roots or {}).items():
            real = os.path.realpath(actual)
            if real not in self.roots:
                raise AdoptionScanRefused(
                    "declared root %r is mapped to %r, which is not allowlisted"
                    % (declared, actual))
            mapped[declared.rstrip("/")] = real
        #: Longest declared prefix first, so ``/uploads/projects`` is matched
        #: before ``/uploads``.
        self.declared_roots: Tuple[Tuple[str, str], ...] = tuple(
            sorted(mapped.items(), key=lambda kv: (-len(kv[0]), kv[0])))
        #: The LAST pass this inventory served, for :meth:`as_record` only. The
        #: counters themselves live on the pass (C01 review defect 3), so a
        #: reused inventory cannot carry a spent budget into the next pass.
        self.last_pass: Optional[ScanPass] = None

    def open_pass(self) -> ScanPass:
        """A fresh budget for one independent pass. Nothing is carried over."""
        self.last_pass = ScanPass(budget=self.budget)
        return self.last_pass

    def translate(self, location: str) -> str:
        """A declared legacy path, rewritten onto the root it is mounted at.

        Unmapped paths come back unchanged, so production needs no map at all.
        """
        for declared, actual in self.declared_roots:
            if location == declared:
                return actual
            if location.startswith(declared + "/"):
                return os.path.join(actual, location[len(declared) + 1:])
        return location

    # ---------------------------------------------------------------- walking
    def walk(self, pass_: Optional[ScanPass] = None) -> List[PhysicalObject]:
        """Every object under every allowlisted root, in a stable order.

        ``pass_`` carries the budget. Omitting it opens a fresh one, which is
        the honest default: a walk with no pass is its own pass.
        """
        pass_ = pass_ if pass_ is not None else self.open_pass()
        found: List[PhysicalObject] = []
        for root in self.roots:
            if not os.path.isdir(root):
                # A declared root that is not there is EVIDENCE, not an error:
                # the migration map names roots of the live application, and a
                # test fixture or a fresh install has fewer of them.
                continue
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                # Sorted in place so the walk order is the same on every run
                # and on every filesystem.
                dirnames.sort()
                dirnames[:] = [d for d in dirnames
                               if not os.path.islink(os.path.join(directory, d))]
                for name in sorted(filenames):
                    if pass_.objects_seen >= self.budget.max_objects:
                        # The limit itself is charged and enforced in
                        # :meth:`_observe`, which both entry paths share (C02
                        # review defect 1). Stopping here as well keeps the
                        # walk from reading a whole tree it may not inspect.
                        pass_.truncated = True
                        return sorted(found, key=lambda o: (o.root, o.relative_path))
                    absolute = os.path.join(directory, name)
                    relative = os.path.relpath(absolute, root)
                    found.append(self._observe(root, relative, absolute, pass_))
        return sorted(found, key=lambda o: (o.root, o.relative_path))

    # ------------------------------------------------------- a path we were told
    def observe_path(self, location: Optional[str],
                     pass_: Optional[ScanPass] = None) -> Optional[PhysicalObject]:
        """Look at a path a DATABASE ROW named. ``None`` when no root owns it.

        The row is untrusted input: it may name a path under no allowlisted
        root at all, a path that climbs out of one, or a link. Each answer is
        distinct, and none of them reads a byte before the gate has passed.
        """
        if not isinstance(location, str) or not location:
            return None
        pass_ = pass_ if pass_ is not None else self.open_pass()
        location = self.translate(location)
        for root in self.roots:
            safe, refusal = path_within_root(root, location)
            if refusal == REASON_PATH_IS_LINK:
                return PhysicalObject(relative_path=os.path.basename(location), root=root,
                                      size_bytes=None, checksum=None, readable=False,
                                      refusal=REASON_PATH_IS_LINK,
                                      checksum_reason=REASON_PATH_IS_LINK)
            if not safe:
                continue
            relative = os.path.relpath(os.path.realpath(location), root)
            absolute = os.path.join(root, relative)
            if not os.path.exists(absolute):
                return PhysicalObject(relative_path=relative, root=root, size_bytes=None,
                                      checksum=None, readable=False,
                                      refusal=REASON_ORIGINAL_ABSENT,
                                      checksum_reason=REASON_ORIGINAL_ABSENT)
            return self._observe(root, relative, absolute, pass_)
        # Named a path, but under no root this scan is allowed to look at. That
        # is a refusal with evidence, not an absent object: saying "missing"
        # here would be exactly the mislabelling the contract forbids.
        return PhysicalObject(relative_path=os.path.basename(location),
                              root=self.roots[0], size_bytes=None, checksum=None,
                              readable=False, refusal=REASON_PATH_OUTSIDE_ROOT,
                              checksum_reason=REASON_PATH_OUTSIDE_ROOT)

    # ------------------------------------------------------------------ one object
    def _observe(self, root: str, relative: str, absolute: str,
                 pass_: ScanPass) -> PhysicalObject:
        """Observe ONE object. The only way into a stat, an open or a read.

        C02 review defect 3. ``walk`` used to filter symlinked *directories*
        and then hand every filename straight to this method, which stat'd,
        opened and hashed it without ever consulting
        :func:`path_within_root`. A symlink FILE sitting in a perfectly real
        directory was therefore followed out of the allowlisted root — the
        exact thing the gate exists to refuse, and the exact thing
        ``observe_path`` already refused for a DB-supplied path. The two entry
        paths were inconsistent; now they are not. The gate runs before the
        stat, before the open, and before the cache, so a refused object never
        becomes a cached observation and never charges the budget.

        C02 review defect 1. ``max_objects`` was checked and charged in
        ``walk`` alone, so ``observe_path`` — the DB-row entry path — obeyed no
        object limit at all: at ``max_objects=0`` a row naming an existing
        file was still opened and hashed, with ``objects_seen`` left at 0. The
        limit belongs to the object, not to the way the object was reached, so
        it is charged here. A cached observation of the SAME object reuses its
        one charge, which is what keeps the C02 shared-limit accounting and
        its determinism intact.
        """
        safe, refusal = path_within_root(root, absolute)
        if not safe:
            return PhysicalObject(relative_path=relative, root=root,
                                  size_bytes=None, checksum=None, readable=False,
                                  refusal=refusal, checksum_reason=refusal)
        key = os.path.realpath(absolute)
        cached = pass_.seen.get(key)
        if cached is not None:
            return PhysicalObject(
                relative_path=relative, root=root, size_bytes=cached.size_bytes,
                checksum=cached.checksum, checksum_reason=cached.checksum_reason,
                readable=cached.readable, refusal=cached.refusal)
        if pass_.objects_seen >= self.budget.max_objects:
            # Not permitted to inspect this object at all. That is a refusal
            # with evidence, never an absent or an unverified-but-fine object,
            # and it is deliberately NOT cached: it is not an observation.
            pass_.truncated = True
            return PhysicalObject(relative_path=relative, root=root,
                                  size_bytes=None, checksum=None, readable=False,
                                  refusal=REASON_OBJECT_BUDGET_EXHAUSTED,
                                  checksum_reason=REASON_OBJECT_BUDGET_EXHAUSTED)
        pass_.objects_seen += 1
        observed = self._observe_uncached(root, relative, absolute, pass_)
        pass_.seen[key] = observed
        return observed

    def _observe_uncached(self, root: str, relative: str, absolute: str,
                          pass_: ScanPass) -> PhysicalObject:
        size: Optional[int] = None
        try:
            size = os.path.getsize(absolute)
        except OSError as exc:
            # Could not even stat it. The bytes may be perfectly fine; what
            # failed is this scan's access, and that is what gets recorded.
            return PhysicalObject(relative_path=relative, root=root, size_bytes=None,
                                  checksum=None, readable=False,
                                  refusal=REASON_SOURCE_INACCESSIBLE,
                                  checksum_reason=REASON_SOURCE_INACCESSIBLE)
        checksum, reason = self._checksum(absolute, size, pass_)
        return PhysicalObject(relative_path=relative, root=root, size_bytes=size,
                              checksum=checksum, checksum_reason=reason, readable=True)

    #: How much is read per syscall. Small enough that an overrun is noticed
    #: after one chunk rather than after a whole file.
    CHUNK_BYTES = 1024 * 1024

    def _declared_size_still_holds(self, absolute: str, size: int) -> bool:
        """Is the object still exactly the size the read was bounded by?

        This is how growth is detected WITHOUT reading a byte past the cap
        (C02 review defect 2). The previous fix asked for one byte beyond the
        ceiling so an overrun would show up in the first chunk; that answered
        the classification but not the budget — at a cap of zero it still
        physically read and charged one byte. A second ``stat`` costs nothing
        and proves the same thing from outside the budget.
        """
        try:
            return os.path.getsize(absolute) == size
        except OSError:
            return False

    def _checksum(self, absolute: str, size: Optional[int], pass_: ScanPass
                  ) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """The object's sha256, or the precise reason there is none.

        The read is bounded by the object's declared size, which the three
        pre-read gates have already proven to be within both the per-object
        cap and what is left of the pass's byte budget. So the ceiling IS the
        declared size, every ``read`` asks for at most what is still owed, and
        **no byte beyond the cap is ever requested** — at a cap of zero
        nothing is opened at all.

        Three ways this fails closed, none of which needs an over-cap byte:

        * the stream ends early — the object is not what it declared, so
          ``SIZE_UNCERTAIN_AT_READ_TIME`` rather than a checksum of a prefix;
        * the object no longer has its declared size once the read is done —
          it grew or shrank underneath the scan, same refusal;
        * a handle returns MORE than it was asked for, which a real file
          object never does but an injected one can. The bytes are already in
          hand, so they are charged honestly and the object gets no checksum.

        C01 review defect 4 and C02 review defect 2 are both answered here:
        the caps bound the physical read, not merely the verdict.
        """
        if not self.budget.allow_content_read:
            return None, REASON_CONTENT_READ_NOT_PERMITTED
        if size is None:
            # Nothing to bound the read by. Refusing is the only honest
            # answer: a read with no ceiling is not a budgeted read.
            return None, REASON_SIZE_UNCERTAIN
        if size > self.budget.max_object_bytes:
            return None, REASON_BUDGET_EXHAUSTED
        if pass_.checksums_read >= self.budget.max_checksum_objects:
            return None, REASON_BUDGET_EXHAUSTED
        remaining = self.budget.max_checksum_bytes - pass_.bytes_read
        if size > remaining:
            return None, REASON_BUDGET_EXHAUSTED
        #: Proven above to be within the per-object cap AND the pass's
        #: remaining bytes, so reading exactly this much exceeds neither.
        ceiling = size
        digest = hashlib.sha256()
        read = 0
        try:
            if ceiling > 0:
                with self._opener(absolute) as handle:
                    while read < ceiling:
                        chunk = handle.read(min(self.CHUNK_BYTES, ceiling - read))
                        if not chunk:
                            break
                        if len(chunk) > ceiling - read:
                            # Asked for what was owed and got more. Charge the
                            # bytes that really arrived; hash none of them.
                            pass_.bytes_read += read + len(chunk)
                            return None, REASON_BUDGET_EXHAUSTED
                        read += len(chunk)
                        digest.update(chunk)
            if read != ceiling:
                pass_.bytes_read += read
                return None, REASON_SIZE_UNCERTAIN
            if not self._declared_size_still_holds(absolute, size):
                pass_.bytes_read += read
                return None, REASON_SIZE_UNCERTAIN
        except OSError:
            pass_.bytes_read += read
            return None, REASON_SOURCE_INACCESSIBLE
        pass_.checksums_read += 1
        pass_.bytes_read += read
        return m.checksum(digest.hexdigest()), None

    def as_record(self) -> Dict[str, Any]:
        """What this inventory did, for the scan document. No paths."""
        last = self.last_pass
        return {"roots": len(self.roots),
                "declared_roots_mapped": len(self.declared_roots),
                "objects_seen": last.objects_seen if last else 0,
                "checksums_read": last.checksums_read if last else 0,
                "bytes_read": last.bytes_read if last else 0,
                "truncated": last.truncated if last else False,
                "budget": self.budget.as_record()}


# ====================================================== one observed item
@dataclass
class ReadinessItem:
    """What the scan found about ONE legacy row or ONE physical object.

    Everything a reviewer needs is here and nothing a client must not see: the
    source identity is a *protected reference*, the location is relative to an
    allowlisted root, and the raw row never travels.
    """

    direction: str
    source_key: Optional[str]
    collection: Optional[str]
    legacy_reference: str
    org_id: Optional[str]
    #: What :mod:`app.files.migration_map` says this row would become.
    plan: Optional[Dict[str, Any]]
    state: str
    proposed_action: str
    reasons: Tuple[str, ...]
    #: The W0-06A blockers, carried through unchanged.
    blockers: Tuple[str, ...]
    expected: Dict[str, Any]
    observed: Dict[str, Any]
    registry: Dict[str, Any]
    relations: Tuple[Dict[str, Any], ...]
    #: sha256 of exactly the inputs the decision was made from. Re-computed
    #: before any later apply; a difference refuses the plan.
    fingerprint: str
    item_id: str
    scanned_at: str

    def as_record(self) -> Dict[str, Any]:
        return {
            "schema": ADOPTION_SCHEMA, "id": self.item_id,
            "direction": self.direction, "source_key": self.source_key,
            "collection": self.collection, "legacy_reference": self.legacy_reference,
            "org_id": self.org_id, "plan": self.plan, "state": self.state,
            "proposed_action": self.proposed_action,
            "reasons": list(self.reasons), "blockers": list(self.blockers),
            "expected": dict(self.expected), "observed": dict(self.observed),
            "registry": dict(self.registry),
            "relations": [dict(r) for r in self.relations],
            "fingerprint": self.fingerprint, "scanned_at": self.scanned_at,
            "decision_required": self.decision_required,
        }

    @property
    def decision_required(self) -> bool:
        """A human must answer before this item can move at all."""
        return self.proposed_action in (PROPOSE_NEEDS_HUMAN_DECISION,
                                        PROPOSE_BLOCKED_FUTURE_STEP)


def readiness_state(*, direction: str, candidates: Mapping[str, bool],
                    has_blockers: bool) -> str:
    """THE classifier. One precedence, applied in one place.

    ``candidates`` maps a state to whether its own condition holds. The first
    state of :data:`STATE_PRECEDENCE` whose condition holds wins, so two items
    with the same evidence can never be classified differently and adding a
    state means adding it to the order — not writing another ``if``.
    """
    if direction not in DIRECTIONS:
        raise AdoptionScanRefused("unknown reconciliation direction %r" % direction)
    for state in STATE_PRECEDENCE:
        if state == READY_TO_ADOPT:
            # Ready is the one state that is not a condition of its own: it is
            # the absence of every blocker AND of every state above it.
            if not has_blockers and candidates.get(READY_TO_ADOPT):
                return READY_TO_ADOPT
            continue
        if state == BLOCKED:
            return BLOCKED
        if candidates.get(state):
            return state
    return BLOCKED                                    # pragma: no cover - defensive


def propose_action(state: str, *, at_customer_managed_location: bool,
                   has_owning_file: bool, evidence_complete: bool = False,
                   relations_match: bool = False) -> str:
    """What may be PROPOSED for this state. Never what will be done.

    Three gates, all structural rather than advisory:

    * ``ADOPT_IN_PLACE`` needs the original to be at a verified, tenant-owned,
      customer-managed provider location ALREADY **and** the full observed
      evidence behind it. The migration map reports every legacy row at
      ``legacy_app_disk``, which is not in
      :data:`app.files.models.CUSTOMER_MANAGED_PROVIDER_KINDS`, so an
      application-disk row cannot reach this branch at all;
    * ``REGISTER_REFERENCE_ONLY`` needs an existing same-tenant File **and the
      exact proposed relation proven registered on it**. A pointer with
      nothing behind it, or with some other relation, is a decision — not a
      reference;
    * ``evidence_complete`` is passed in rather than inferred. C01's review
      found readiness being read off a stored location status; this parameter
      exists so no caller can reach ``ADOPT_IN_PLACE`` without the observed
      proof, even if a future state were to be added above.
    """
    if state == NO_CONTENT:
        return PROPOSE_NO_ACTION
    if state == ALREADY_REGISTERED:
        return PROPOSE_NO_ACTION
    if state == READY_TO_ADOPT:
        if at_customer_managed_location and evidence_complete:
            return PROPOSE_ADOPT_IN_PLACE
        if has_owning_file and relations_match:
            return PROPOSE_REGISTER_REFERENCE_ONLY
        # Coherent, but the bytes are not anywhere this slice may adopt from,
        # or the relation that would carry the reference is not proven.
        return PROPOSE_BLOCKED_FUTURE_STEP
    if state in (TENANT_AMBIGUOUS, BUSINESS_RELATION_AMBIGUOUS, CHECKSUM_CONFLICT,
                 DUPLICATE_CANDIDATE, ORPHAN_DB_RECORD, ORPHAN_PHYSICAL_FILE,
                 UNSUPPORTED_SOURCE):
        return PROPOSE_NEEDS_HUMAN_DECISION
    # MISSING_ORIGINAL and BLOCKED: nothing to propose until the blocker moves.
    return PROPOSE_BLOCKED_FUTURE_STEP


def item_fingerprint(*, direction: str, source_key: Optional[str],
                     legacy_reference: str, org_id: Optional[str],
                     plan: Optional[Mapping[str, Any]],
                     observed: Mapping[str, Any],
                     registry: Mapping[str, Any],
                     relations: Sequence[Mapping[str, Any]]) -> str:
    """sha256 over EXACTLY the inputs the readiness decision was made from.

    The contract requires a later apply to recompute this against the DB row,
    the physical evidence, the provider identity, the relation target and the
    current File Registry state, and to refuse the plan on any difference. So
    every one of those is inside the hash, and nothing else is: the scan time,
    the item id and the readiness label are deliberately OUT, because a
    fingerprint that changed when the clock moved would refuse every plan and
    teach an operator to ignore it.
    """
    return _digest({
        "direction": direction,
        "source_key": source_key,
        "legacy_reference": legacy_reference,
        "org_id": org_id,
        # The plan is itself a pure function of the row, so hashing the plan
        # hashes the row fields the decision actually depended on.
        "plan": dict(plan or {}),
        "observed": dict(observed),
        "registry": dict(registry),
        "relations": [dict(r) for r in relations],
    })


def _redact(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """Drop the keys that must never be stored, projected or audited."""
    out = {k: v for k, v in evidence.items() if k not in REDACTED_EVIDENCE_KEYS}
    assert_no_secrets(out, "evidence")
    return out


# ================================================================= the service
class LegacyAdoptionReadiness:
    """One tenant's dry-run legacy adoption readiness. Read-only by construction.

    Built from the tenant's already resolved :class:`~app.files.registry.FileRegistry`
    exactly like the W0-06B/C services: the only tenant it can act for is the
    one inside that view, and it never takes an ``org_id`` argument. The legacy
    rows are read through the SAME tenant view, so a legacy collection cannot
    be read unscoped and a row of another tenant cannot enter this scan.

    There is no method on this class that writes outside its own two
    collections, and none at all that touches a legacy row, a customer
    original, a provider or a File Registry record.
    """

    def __init__(self, registry, *, inventory: Optional[LegacyRootInventory] = None,
                 clock=None, sources: Sequence[mp.LegacySource] = mp.LEGACY_SOURCES):
        self._registry = registry
        self.org_id = registry.org_id
        self._tenant = registry._tenant
        #: ``None`` means "no physical inventory in this scan" — a legitimate
        #: configuration (a DB-only readiness pass), and one that must not be
        #: confused with "the originals are missing": with no inventory the
        #: physical side is UNKNOWN, not absent.
        self._inventory = inventory
        self._clock = clock or _now
        #: The declared source map. Injectable so a test can prove an UNKNOWN
        #: source is refused, never so a caller can add one.
        self._sources: Tuple[mp.LegacySource, ...] = tuple(sources)
        for source in self._sources:
            if source.key not in mp.SOURCES_BY_KEY:
                raise AdoptionScanRefused(
                    "source %r is not declared in the W0-06A migration map; W0-06D "
                    "does not mint a second source registry" % source.key)

    # ------------------------------------------------------------- handles
    @property
    def scans(self):
        return self._tenant.collection(ADOPTION_SCANS_COLLECTION)

    @property
    def items(self):
        return self._tenant.collection(ADOPTION_ITEMS_COLLECTION)

    def now(self) -> datetime:
        return self._clock()

    # --------------------------------------------------------------- audit
    async def _audit(self, *, action: str, actor_id: str, entity_id: str,
                     result: str = RESULT_SUCCESS, reason: Optional[str] = None,
                     structured_diff: Optional[Dict[str, Any]] = None,
                     related_file_ids: Optional[List[str]] = None,
                     correlation_id: Optional[str] = None,
                     idempotency_key: Optional[str] = None,
                     error_code: Optional[str] = None,
                     actor_type: str = ACTOR_HUMAN) -> Dict[str, Any]:
        """One FLOW-040 envelope through the W0-06B entry point. Sanitized first."""
        assert_no_secrets(structured_diff or {}, "structured_diff")
        return await audit_trail.record(
            self._tenant, action=action, actor_id=actor_id,
            retention_class=_RETENTION[action], entity_type="legacy_adoption",
            entity_id=entity_id, result=result, reason=reason,
            structured_diff=structured_diff, related_file_ids=related_file_ids,
            correlation_id=correlation_id, idempotency_key=idempotency_key,
            error_code=error_code, actor_type=actor_type)

    async def _authorize(self, ctx, action: str, *, entity_id: str):
        """FLOW-002 BEFORE anything else. A denial is audited and then raised."""
        try:
            return await authorize(ctx, action, org_id=self.org_id)
        except FileAccessDenied as denied:
            await self._audit(
                action=audit_trail.ACTION_PERMISSION_FAILED,
                actor_id=getattr(ctx, "user_id", None) or "anonymous",
                entity_id=entity_id, result=RESULT_FAILURE,
                reason="legacy adoption readiness denied: %s" % denied.action,
                error_code=denied.reason_code,
                actor_type=getattr(ctx, "actor_type", ACTOR_HUMAN),
                structured_diff={"action": denied.action,
                                 "reason_code": denied.reason_code,
                                 "tenant_id": self.org_id})
            raise

    # ------------------------------------------------------- reading the rows
    async def _legacy_rows(self, source: mp.LegacySource) -> List[Dict[str, Any]]:
        """This TENANT's rows of one declared legacy collection, in a stable order.

        Through :class:`~app.tenancy.data_access.TenantCollection`, so the
        tenant predicate is added by the layer and a row of another tenant
        cannot be returned — which is what makes the two-tenant collision case
        structurally impossible rather than merely untested.
        """
        rows = await self._tenant.collection(source.collection).find(
            {}, {"_id": 0}).to_list(None)
        return sorted(rows, key=lambda r: str(r.get("id") or ""))

    # ----------------------------------------------- the registry comparison
    async def _relation_target_exists(self, relation_type: str, record_id: str) -> bool:
        """Does the business record this relation names exist IN THIS TENANT?

        The same question :meth:`app.files.registry.FileRegistry._assert_relation_target`
        asks before CREATING a relation, asked here without raising, because a
        readiness scan reports rather than refuses. Read through the tenant
        view, so a record id that belongs to another tenant — including one
        that collides with a real id here — resolves to nothing.
        """
        target = m.RELATION_TARGETS.get(relation_type)
        if not target or not record_id:
            return False
        found = await self._tenant.collection(target).find_one(
            {"id": record_id}, {"_id": 0, "id": 1})
        return bool(found)

    async def _registry_state(self, file_id: Optional[str],
                              observed_checksum: Optional[Mapping[str, Any]],
                              observed_size: Optional[int] = None,
                              planned_relations: Sequence[Mapping[str, Any]] = ()
                              ) -> Dict[str, Any]:
        """What the SAME tenant's File Registry already holds for this identity.

        Everything here is a same-tenant read through the registry's own
        helpers. ``duplicate_of`` is a checksum lookup, which can only ever
        return this tenant's files: ``find_by_checksum`` goes through the
        tenant view too.

        C01 review defect 2. This used to reduce every FileRelation to
        ``relation_count``, and a nonzero count was then accepted as
        "already registered" — so a file carrying one UNRELATED relation
        satisfied a plan that proposed ``project=missing-project``. A count is
        not an identity. The planned ``(relation_type, record_id)`` pairs are
        now compared one by one against this tenant's ACTIVE relations, and
        each planned target is additionally resolved in this tenant, because a
        relation to a record that does not exist here is not a relation.
        """
        state: Dict[str, Any] = {
            "file_exists": False, "version_no": None, "checksum_matches": None,
            "size_matches": None, "registered_size": None, "availability": None,
            "provider_kind": None, "customer_managed": False,
            "verified_location": False, "relation_count": 0,
            "relations_registered": [], "relations_missing": [],
            "relation_targets_missing": [], "relations_match": False,
            "duplicate_of": [],
        }
        planned = sorted({(str(r.get("relation_type")), str(r.get("record_id")))
                          for r in planned_relations})
        if observed_checksum:
            others = await self._registry.find_by_checksum(observed_checksum)
            state["duplicate_of"] = sorted(
                row["id"] for row in others if row.get("id") != file_id)
        # A planned target is resolved whether or not the file exists: an
        # unresolvable target is a blocker on its own, not a detail of a
        # comparison that may never happen.
        targets_missing = [list(pair) for pair in planned
                           if not await self._relation_target_exists(*pair)]
        state["relation_targets_missing"] = targets_missing
        if not file_id:
            state["relations_missing"] = [list(p) for p in planned]
            return state
        row = await self._registry.get_file(file_id)
        if not row:
            state["relations_missing"] = [list(p) for p in planned]
            return state
        state["file_exists"] = True
        version = await self._registry.current_version(file_id)
        if version:
            state["version_no"] = version.get("version_no")
            state["registered_size"] = version.get("size_bytes")
            expected = version.get("checksum") or {}
            if observed_checksum and expected:
                state["checksum_matches"] = (
                    m.checksum_key(observed_checksum) == m.checksum_key(expected))
            if observed_size is not None and version.get("size_bytes") is not None:
                state["size_matches"] = observed_size == version.get("size_bytes")
            location = await self._registry.primary_location(
                file_id, version["version_no"])
            if location:
                state["availability"] = location.get("availability")
                state["provider_kind"] = location.get("provider_kind")
                state["customer_managed"] = (
                    location.get("provider_kind") in m.CUSTOMER_MANAGED_PROVIDER_KINDS)
                # "Verified" is the provider's own answer, not our hope: only
                # an AVAILABLE location counts, so an unverified or unreachable
                # one can never support an in-place adoption.
                state["verified_location"] = (
                    location.get("availability") == m.AVAILABILITY_AVAILABLE
                    and state["customer_managed"])
        relations = await self._registry.list_relations(file_id)
        state["relation_count"] = len(relations)
        registered = {(str(r.get("relation_type")), str(r.get("record_id")))
                      for r in relations}
        state["relations_registered"] = sorted(
            [list(p) for p in planned if p in registered])
        state["relations_missing"] = sorted(
            [list(p) for p in planned if p not in registered])
        # The exact match the contract asks for: every proposed relation is
        # really registered on THIS file, and every proposed target really
        # exists in THIS tenant. An empty proposal proves nothing, so it is
        # not a match either.
        state["relations_match"] = bool(
            planned and not state["relations_missing"] and not targets_missing)
        return state

    # ------------------------------------------------------------ classifying
    def _classify(self, *, direction: str, plan: Optional[mp.PlanEntry],
                  observed: Mapping[str, Any], registry: Mapping[str, Any],
                  source: Optional[mp.LegacySource]
                  ) -> Tuple[str, List[str], bool]:
        """``(state, reasons, evidence_complete)`` for one item.

        Pure, so it is directly testable — which is how the C01 review
        reproduced both classification defects, and how the C02 regressions
        pin them.
        """
        reasons: List[str] = []
        blockers = list(plan.blockers) if plan else []

        if direction == DIRECTION_PHYSICAL_OBJECT:
            # An object nothing claims. A path that looks like a tenant root
            # does NOT make it owned: there is no row, so there is no owner.
            reasons.append(REASON_UNATTRIBUTED_OBJECT)
            reasons.append(REASON_OWNERSHIP_UNVERIFIED)
            return ORPHAN_PHYSICAL_FILE, reasons, False

        if source is None:
            reasons.append(REASON_SOURCE_NOT_DECLARED)
            return UNSUPPORTED_SOURCE, reasons, False

        if plan is not None and plan.action == mp.ACTION_NONE:
            return NO_CONTENT, reasons, False

        owns_bytes = source.action == mp.ACTION_REGISTER
        pointer_only = source.action in (mp.ACTION_RELATE,
                                         mp.ACTION_REPLACE_WITH_FILE_ID)

        no_owner = plan is None or plan.org_id is None
        if no_owner:
            reasons.append(mp.BLOCKER_NO_OWNER)
        relation_ambiguous = mp.BLOCKER_NO_RELATION in blockers \
            or mp.BLOCKER_UNMAPPED_CONTEXT in blockers
        if observed.get("checksum_reason"):
            reasons.append(observed["checksum_reason"])
        if registry.get("checksum_matches") is False:
            reasons.append(REASON_CHECKSUM_DIFFERS)
        if observed.get("size_bytes") is not None \
                and observed.get("registered_size") is not None \
                and observed["size_bytes"] != observed["registered_size"]:
            reasons.append(REASON_SIZE_DIFFERS)

        proven_absent = observed.get("refusal") == REASON_ORIGINAL_ABSENT \
            or observed.get("state") == "absent"
        inaccessible = observed.get("refusal") in (
            REASON_SOURCE_INACCESSIBLE, REASON_PATH_OUTSIDE_ROOT, REASON_PATH_IS_LINK,
            # C02 review defect 1. An object the scan was not PERMITTED to
            # inspect says nothing about whether its bytes are there, so a
            # truncated inventory must never be read as a missing original —
            # and must never be read as evidence of readiness either.
            REASON_OBJECT_BUDGET_EXHAUSTED)
        if inaccessible:
            # The decisive distinction of this contract: an unreadable source
            # says nothing about whether the bytes are there.
            reasons.append(observed["refusal"])

        pointer_unresolved = pointer_only and not registry.get("file_exists")
        if pointer_unresolved:
            reasons.append(REASON_POINTER_WITHOUT_FILE)
        if registry.get("duplicate_of"):
            reasons.append(REASON_DUPLICATE_SAME_CHECKSUM)
        if registry.get("file_exists") and not registry.get("customer_managed"):
            reasons.append(REASON_NOT_CUSTOMER_MANAGED)

        # ---- C01 review defect 2: an exact relation identity, not a count ----
        if registry.get("relation_targets_missing"):
            reasons.append(REASON_RELATION_TARGET_MISSING)
        if registry.get("file_exists") and registry.get("relations_missing"):
            reasons.append(REASON_RELATION_NOT_REGISTERED)
        if owns_bytes or pointer_only:
            if not (plan and plan.relations):
                reasons.append(REASON_NO_PROPOSED_RELATION)

        # ---- C01 review defect 1: readiness is OBSERVED, never inferred ----
        # The review's counterexample was a same-tenant File whose stored
        # location said ``available`` while the scan had observed nothing at
        # all: state ``unknown``, no checksum, no size, no relation. A stored
        # status is a fact about the registry, not proof about THIS legacy
        # original, so each piece of evidence is now required explicitly and
        # its absence is named.
        original_observed = observed.get("state") == "present" and not inaccessible
        checksum_observed = bool(observed.get("checksum"))
        size_observed = observed.get("size_bytes") is not None
        same_object = (registry.get("checksum_matches") is True
                       and registry.get("size_matches") is True)
        if owns_bytes:
            if not original_observed:
                reasons.append(REASON_ORIGINAL_NOT_OBSERVED)
            if not checksum_observed:
                reasons.append(REASON_CHECKSUM_UNKNOWN)
            if not size_observed:
                reasons.append(REASON_SIZE_UNKNOWN)
            if original_observed and checksum_observed and size_observed \
                    and registry.get("file_exists") and not same_object:
                reasons.append(REASON_SAME_OBJECT_UNPROVEN)

        #: Everything the contract requires before a row may be called ready:
        #: a proven owner, the actual legacy original observed, its checksum
        #: AND size observed, the registered object proven to be the SAME
        #: object, and a verified customer-managed location. Every clause is
        #: necessary; none of them can be substituted by a stored status.
        evidence_complete = bool(
            owns_bytes
            and not no_owner
            and original_observed
            and checksum_observed
            and size_observed
            and registry.get("file_exists")
            and same_object
            and registry.get("verified_location"))

        #: ALREADY_REGISTERED is the same evidence PLUS the exact relation
        #: identity. It is not a weaker claim than readiness — it is a
        #: stronger one, so it cannot rest on less.
        exact_match = bool(evidence_complete and registry.get("relations_match"))

        #: A pointer-only row owns no bytes, so it can never be "ready"; what
        #: it can be is a reference to an already-verified File of this
        #: tenant, and only with the exact relation proven.
        reference_ready = bool(
            pointer_only and not no_owner and registry.get("file_exists")
            and registry.get("verified_location") and registry.get("relations_match"))

        candidates = {
            TENANT_AMBIGUOUS: no_owner,
            CHECKSUM_CONFLICT: registry.get("checksum_matches") is False
            or registry.get("size_matches") is False,
            BUSINESS_RELATION_AMBIGUOUS: bool(
                relation_ambiguous or registry.get("relation_targets_missing")),
            # Only ever from PROVEN absence, and only for a source that is
            # supposed to own bytes at all.
            MISSING_ORIGINAL: bool(owns_bytes and proven_absent and not inaccessible),
            ORPHAN_DB_RECORD: pointer_unresolved,
            ALREADY_REGISTERED: exact_match or reference_ready,
            DUPLICATE_CANDIDATE: bool(registry.get("duplicate_of")),
            READY_TO_ADOPT: evidence_complete,
        }
        state = readiness_state(direction=direction, candidates=candidates,
                                has_blockers=bool(blockers))
        return state, reasons, evidence_complete

    # ------------------------------------------------------------------ scan
    async def scan(self, ctx, *, scan_id: Optional[str] = None,
                   source_keys: Optional[Sequence[str]] = None,
                   persist: bool = True) -> Dict[str, Any]:
        """ONE dry-run readiness pass. Reads; proposes; writes no legacy state.

        The only documents it creates are its own scan and item records in this
        tenant's two adoption collections. It does not touch a legacy row, a
        customer original, a provider or any File Registry collection — a
        static guard and a direct regression both hold that line.
        """
        await self._authorize(ctx, ACTION_ADOPTION_SCAN, entity_id=self.org_id)
        run_id = scan_id or (ID_PREFIX_SCAN + uuid.uuid4().hex)
        started = _iso(self.now())

        wanted = list(source_keys) if source_keys is not None \
            else [s.key for s in self._sources]
        unknown = sorted(set(wanted) - set(mp.SOURCES_BY_KEY))
        if unknown:
            # Fail closed rather than silently skip: the contract says a newly
            # found source must be classified before PASS, never dropped.
            raise AdoptionScanRefused(
                "undeclared legacy source(s) %s; classify them in the W0-06A "
                "migration map first" % ", ".join(unknown))
        selected = tuple(mp.SOURCES_BY_KEY[k] for k in sorted(set(wanted)))

        await self._audit(
            action=AUDIT_SCAN_STARTED, actor_id=ctx.user_id, entity_id=run_id,
            correlation_id=run_id, reason="legacy adoption readiness scan started",
            structured_diff={"sources": [s.key for s in selected],
                             "physical_inventory": self._inventory is not None,
                             "budget": (self._inventory.budget.as_record()
                                        if self._inventory else None)})

        # ONE budget for this pass, shared by the physical walk and by every
        # DB row that names an object (C01 review defect 3). A later pass over
        # unchanged inputs opens its own, so the same inputs decide the same
        # way and a revalidation cannot invent drift.
        scan_pass = self._inventory.open_pass() if self._inventory else None
        physical = self._inventory.walk(scan_pass) if self._inventory else []
        #: Which physical objects a DB row claimed. What is left over is the
        #: other direction of the reconciliation.
        claimed: set = set()
        items: List[ReadinessItem] = []

        for source in selected:
            for row in await self._legacy_rows(source):
                item = await self._item_for_row(source, row, run_id=run_id,
                                                scanned_at=started, claimed=claimed,
                                                scan_pass=scan_pass)
                items.append(item)

        for obj in physical:
            if obj.legacy_location in claimed:
                continue
            items.append(self._item_for_object(obj, run_id=run_id, scanned_at=started))

        # Sorted by the stable identity of the item, never by iteration order,
        # so two scans of the same inputs produce byte-identical plans.
        items.sort(key=lambda i: (i.direction, i.source_key or "",
                                  i.legacy_reference, i.org_id or ""))
        summary = summarise_items(items)
        plan_hash = _digest([i.fingerprint for i in items])

        record = {
            "schema": ADOPTION_SCHEMA, "id": run_id, "tenant_id": self.org_id,
            "started_at": started, "finished_at": _iso(self.now()),
            "actor_id": ctx.user_id,
            "sources": [s.key for s in selected],
            "declared_sources": len(mp.LEGACY_SOURCES),
            "inventory": self._inventory.as_record() if self._inventory else None,
            "summary": summary, "plan_hash": plan_hash,
            "items": len(items),
            # Stated, not implied: this slice has no apply path at all.
            "executable": False,
            "dry_run": True,
        }
        if persist:
            await self.scans.insert_one(dict(record))
            for item in items:
                await self.items.insert_one(
                    dict(item.as_record(), scan_id=run_id, tenant_id=self.org_id))
            for item in items:
                if not item.decision_required:
                    continue
                # A decision-REQUIRED record, and nothing more: no approver,
                # no deadline, no acceptance rule. W0-07 owns those.
                await self._audit(
                    action=AUDIT_DECISION_REQUIRED, actor_id=ctx.user_id,
                    entity_id=item.item_id, correlation_id=run_id,
                    idempotency_key=item.fingerprint,
                    reason="legacy adoption needs a human decision: %s" % item.state,
                    related_file_ids=[item.plan["file_id"]]
                    if item.plan and item.plan.get("file_id") else None,
                    structured_diff={"state": item.state,
                                     "proposed_action": item.proposed_action,
                                     "reasons": list(item.reasons),
                                     "blockers": list(item.blockers),
                                     "source_key": item.source_key,
                                     "evidence_hash": item.fingerprint})

        await self._audit(
            action=AUDIT_SCAN_FINISHED, actor_id=ctx.user_id, entity_id=run_id,
            correlation_id=run_id, reason="legacy adoption readiness scan finished",
            structured_diff={"summary": summary, "plan_hash": plan_hash,
                             "items": len(items), "dry_run": True})
        return dict(record, item_records=[i.as_record() for i in items])

    # -------------------------------------------------------------- one row
    async def _item_for_row(self, source: mp.LegacySource, row: Mapping[str, Any],
                            *, run_id: str, scanned_at: str, claimed: set,
                            scan_pass: Optional[ScanPass] = None) -> ReadinessItem:
        plan = mp.plan_row(source, row)
        observed: Dict[str, Any] = {"state": "unknown", "size_bytes": None,
                                    "checksum": None, "checksum_reason": None,
                                    "refusal": None, "relative_path": None,
                                    "registered_size": None}
        if plan.current_physical_location and self._inventory is not None:
            seen = self._inventory.observe_path(plan.current_physical_location,
                                                scan_pass)
            if seen is None:
                observed["state"] = "unknown"
            else:
                claimed.add(seen.legacy_location)
                observed.update({
                    "state": "present" if seen.readable else "absent_or_unreadable",
                    "size_bytes": seen.size_bytes, "checksum": seen.checksum,
                    "checksum_reason": seen.checksum_reason, "refusal": seen.refusal,
                    "relative_path": seen.relative_path})
                if seen.refusal == REASON_ORIGINAL_ABSENT:
                    observed["state"] = "absent"
        elif plan.current_physical_location:
            # A location is expected but this scan has no physical inventory.
            # UNKNOWN, emphatically not absent.
            observed["state"] = "unknown"
            observed["checksum_reason"] = REASON_CHECKSUM_UNKNOWN

        planned_relations = [{"relation_type": r.relation_type,
                              "record_id": r.record_id} for r in plan.relations]
        registry = await self._registry_state(
            plan.file_id, observed.get("checksum"),
            observed_size=observed.get("size_bytes"),
            planned_relations=planned_relations)
        observed["registered_size"] = registry.get("registered_size")

        state, reasons, evidence_complete = self._classify(
            direction=DIRECTION_DB_ROW, plan=plan, observed=observed,
            registry=registry, source=source)
        proposal = propose_action(
            state, at_customer_managed_location=bool(registry.get("verified_location")),
            has_owning_file=bool(registry.get("file_exists")),
            evidence_complete=evidence_complete,
            relations_match=bool(registry.get("relations_match")))
        expected = {
            "source_key": source.key, "action": source.action,
            "category": source.category, "sensitivity": source.sensitivity,
            "physical_root_declared": source.physical_root is not None,
            "owns_bytes": source.action == mp.ACTION_REGISTER,
        }
        relations = tuple({"relation_type": r.relation_type, "record_id": r.record_id,
                           "source_field": r.source_field} for r in plan.relations)
        plan_record = plan.as_dict()
        # FLOW-016: a path is never an identity, and an absolute server path is
        # not a client's business. The plan keeps the derived ids and the
        # declared root, never the resolved path.
        plan_record.pop("current_physical_location", None)
        fingerprint = item_fingerprint(
            direction=DIRECTION_DB_ROW, source_key=source.key,
            legacy_reference=plan.legacy_reference, org_id=plan.org_id,
            plan=plan_record, observed=_redact(observed), registry=registry,
            relations=relations)
        return ReadinessItem(
            direction=DIRECTION_DB_ROW, source_key=source.key,
            collection=source.collection, legacy_reference=plan.legacy_reference,
            org_id=plan.org_id, plan=plan_record, state=state,
            proposed_action=proposal, reasons=tuple(sorted(set(reasons))),
            blockers=tuple(plan.blockers), expected=expected,
            observed=_redact(observed), registry=dict(registry), relations=relations,
            fingerprint=fingerprint,
            item_id=ID_PREFIX_ITEM + _digest(
                [self.org_id, source.key, plan.legacy_reference])[:24],
            scanned_at=scanned_at)

    # ----------------------------------------------------- one orphan object
    def _item_for_object(self, obj: PhysicalObject, *, run_id: str,
                         scanned_at: str) -> ReadinessItem:
        observed = {"state": "present" if obj.readable else "absent_or_unreadable",
                    "size_bytes": obj.size_bytes, "checksum": obj.checksum,
                    "checksum_reason": obj.checksum_reason, "refusal": obj.refusal,
                    "relative_path": obj.relative_path, "registered_size": None}
        state, reasons, _evidence = self._classify(
            direction=DIRECTION_PHYSICAL_OBJECT, plan=None, observed=observed,
            registry={}, source=None)
        # No owner, so no tenant-scoped registry comparison is even attempted:
        # looking a stray object up by checksum and attaching it to whichever
        # file matched is precisely the heuristic the contract forbids.
        fingerprint = item_fingerprint(
            direction=DIRECTION_PHYSICAL_OBJECT, source_key=None,
            legacy_reference=obj.relative_path, org_id=None, plan=None,
            observed=_redact(observed), registry={}, relations=())
        return ReadinessItem(
            direction=DIRECTION_PHYSICAL_OBJECT, source_key=None, collection=None,
            legacy_reference=obj.relative_path, org_id=None, plan=None, state=state,
            proposed_action=propose_action(state, at_customer_managed_location=False,
                                           has_owning_file=False),
            reasons=tuple(sorted(set(reasons))), blockers=(),
            expected={"owns_bytes": True, "physical_root_declared": True},
            observed=_redact(observed), registry={}, relations=(),
            fingerprint=fingerprint,
            item_id=ID_PREFIX_ITEM + _digest(
                [self.org_id, "physical", obj.root, obj.relative_path])[:24],
            scanned_at=scanned_at)

    # =========================================== the validation hook (no apply)
    async def validate_plan(self, ctx, *, scan_id: str) -> Dict[str, Any]:
        """Re-observe the inputs of a stored plan and REFUSE it if they drifted.

        This is what W0-06D offers instead of an apply endpoint. It is
        non-mutating in the strict sense: it re-runs the same read-only
        observation, recomputes each item's fingerprint and compares. It never
        rewrites the stored plan, never repairs an item and — having no
        execution path at all — never carries out the plan it just approved.
        A ``valid`` answer means only "nothing observed has changed since the
        scan"; the separate authorisation an apply would need is not here.

        Raises :class:`AdoptionPlanStale` when anything drifted, and audits the
        refusal with the drifted fields so the reason is visible without
        exposing a path, a credential or a byte.
        """
        await self._authorize(ctx, ACTION_ADOPTION_SCAN, entity_id=scan_id)
        stored = await self.scans.find_one({"id": scan_id}, {"_id": 0})
        if stored is None:
            raise AdoptionScanRefused("no adoption scan %r in this tenant" % scan_id)
        previous = await self.items.find({"scan_id": scan_id}, {"_id": 0}).to_list(None)
        if not previous:
            raise AdoptionScanRefused("adoption scan %r stored no items" % scan_id)

        # The same read-only observation, NOT persisted: a validation must not
        # quietly become a second scan with its own records.
        fresh = await self.scan(ctx, scan_id=scan_id + ":revalidate",
                                source_keys=stored.get("sources"), persist=False)
        now_by_id = {i["id"]: i for i in fresh["item_records"]}
        drifted: List[Dict[str, Any]] = []
        for item in sorted(previous, key=lambda i: i["id"]):
            current = now_by_id.get(item["id"])
            if current is None:
                drifted.append({"id": item["id"], "source_key": item.get("source_key"),
                                "drift": "ITEM_NO_LONGER_OBSERVED",
                                "was": item.get("state"), "now": None})
                continue
            if current["fingerprint"] != item["fingerprint"]:
                drifted.append({
                    "id": item["id"], "source_key": item.get("source_key"),
                    "drift": sorted(_drifted_fields(item, current)),
                    "was": item.get("state"), "now": current.get("state")})
        appeared = sorted(set(now_by_id) - {i["id"] for i in previous})
        for item_id in appeared:
            drifted.append({"id": item_id,
                            "source_key": now_by_id[item_id].get("source_key"),
                            "drift": "ITEM_APPEARED_AFTER_SCAN",
                            "was": None, "now": now_by_id[item_id].get("state")})

        plan_hash = _digest([i["fingerprint"] for i in
                             sorted(fresh["item_records"],
                                    key=lambda i: (i["direction"], i["source_key"] or "",
                                                   i["legacy_reference"],
                                                   i["org_id"] or ""))])
        if drifted:
            await self._audit(
                action=AUDIT_PLAN_REFUSED, actor_id=ctx.user_id, entity_id=scan_id,
                result=RESULT_FAILURE, correlation_id=scan_id,
                reason="adoption plan refused: observed inputs drifted",
                error_code="PLAN_STALE",
                structured_diff={"stored_plan_hash": stored.get("plan_hash"),
                                 "observed_plan_hash": plan_hash,
                                 "drifted_items": len(drifted),
                                 "drift": drifted[:50]})
            raise AdoptionPlanStale(scan_id, drifted)
        await self._audit(
            action=AUDIT_PLAN_VALIDATED, actor_id=ctx.user_id, entity_id=scan_id,
            correlation_id=scan_id, idempotency_key=plan_hash,
            reason="adoption plan still matches the observed inputs",
            structured_diff={"plan_hash": plan_hash, "items": len(previous),
                             "executable": False})
        return {"scan_id": scan_id, "valid": True, "plan_hash": plan_hash,
                "items": len(previous), "drift": [],
                # Said out loud so no caller can read a validation as a green
                # light: W0-06D validates and refuses, it never applies.
                "executable": False,
                "note": "validation only; W0-06D has no apply path"}

    # ---------------------------------------------------------- the projection
    async def list_items(self, ctx, *, scan_id: Optional[str] = None,
                         state: Optional[str] = None,
                         source_key: Optional[str] = None,
                         include_source_reference: bool = False
                         ) -> List[Dict[str, Any]]:
        """The readiness projection, FLOW-002 checked and redacted.

        ``include_source_reference`` is the contract's "authorized operator may
        see a protected source reference": it is honoured only for a caller who
        also holds the scan right, so a read-only operator sees the readiness
        of an item without its legacy coordinates. A caller of another tenant
        never reaches here at all — :func:`authorize` refuses ``CROSS_TENANT``
        before a document is read.
        """
        await self._authorize(ctx, ACTION_ADOPTION_READ, entity_id=scan_id or self.org_id)
        protected = False
        if include_source_reference:
            try:
                await authorize(ctx, ACTION_ADOPTION_SCAN, org_id=self.org_id)
                protected = True
            except FileAccessDenied:
                # Asked for more than the grant allows: narrow the view rather
                # than refuse the whole read, and never widen it.
                protected = False
        flt: Dict[str, Any] = {}
        if scan_id:
            flt["scan_id"] = scan_id
        if state:
            flt["state"] = state
        if source_key:
            flt["source_key"] = source_key
        rows = await self.items.find(flt, {"_id": 0}).to_list(None)
        out = [self._disclose(row, protected=protected)
               for row in sorted(rows, key=lambda r: str(r.get("id") or ""))]
        return out

    def _disclose(self, row: Mapping[str, Any], *, protected: bool) -> Dict[str, Any]:
        """One projected item. Never a path, a credential or a raw legacy row."""
        view = {k: v for k, v in row.items() if k not in REDACTED_EVIDENCE_KEYS}
        observed = dict(view.get("observed") or {})
        observed.pop("relative_path", None)          # a path is never an identity
        view["observed"] = observed
        if not protected:
            # The legacy coordinates ARE the protected source reference: the id
            # of a legacy row, the collection it lives in and the derived plan
            # all name where a customer's file is today.
            for key in ("legacy_reference", "collection", "plan"):
                view.pop(key, None)
            view["source_reference_redacted"] = True
        assert_no_secrets(view, "projection")
        return view

    async def decisions_required(self, ctx, *, scan_id: Optional[str] = None
                                 ) -> List[Dict[str, Any]]:
        """The items a human must answer. A LIST, not an approval interface.

        There is deliberately no ``approve``, ``reject`` or ``assign`` beside
        it: inventing an approver, a role or an SLA is exactly what the
        contract forbids, and FLOW-033/034 is W0-07.
        """
        rows = await self.list_items(ctx, scan_id=scan_id)
        return [r for r in rows if r.get("decision_required")]


def summarise_items(items: Sequence[ReadinessItem]) -> Dict[str, Any]:
    """The counts a reviewer reads before approving anything.

    ``ready`` counts only ``READY_TO_ADOPT`` AND a proposal that this slice may
    actually make. ``no_content`` is counted apart from both ready and blocked,
    like W0-06A's own summary: a row with nothing to adopt is neither work to
    do nor work that is stuck, and folding it into either would misstate how
    much of the migration is ready.
    """
    by_state: Dict[str, int] = {}
    by_action: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    for item in items:
        by_state[item.state] = by_state.get(item.state, 0) + 1
        by_action[item.proposed_action] = by_action.get(item.proposed_action, 0) + 1
        for reason in item.reasons:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "items": len(items),
        "no_content": by_state.get(NO_CONTENT, 0),
        "ready": sum(1 for i in items if i.state == READY_TO_ADOPT
                     and i.proposed_action in (PROPOSE_ADOPT_IN_PLACE,
                                               PROPOSE_REGISTER_REFERENCE_ONLY)),
        "decision_required": sum(1 for i in items if i.decision_required),
        "orphan_physical": by_state.get(ORPHAN_PHYSICAL_FILE, 0),
        "orphan_db": by_state.get(ORPHAN_DB_RECORD, 0),
        "by_state": dict(sorted(by_state.items())),
        "by_proposed_action": dict(sorted(by_action.items())),
        "by_reason": dict(sorted(by_reason.items())),
    }


def _drifted_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[str]:
    """Which of the fingerprinted inputs changed. Named, never dumped.

    The drift report must be readable without exposing what drifted TO: an
    operator needs "the observed checksum changed", not the new checksum.
    """
    names: List[str] = []
    for key in ("org_id", "plan", "registry", "relations"):
        if before.get(key) != after.get(key):
            names.append(key)
    b_obs, a_obs = dict(before.get("observed") or {}), dict(after.get("observed") or {})
    for key in sorted(set(b_obs) | set(a_obs)):
        if b_obs.get(key) != a_obs.get(key):
            names.append("observed.%s" % key)
    return names


# =============================================================== module facts
# Asserted at import, so a later edit cannot drift the contract silently.

#: Every declared state is in the precedence, and the precedence invents none.
assert set(STATE_PRECEDENCE) | {NO_CONTENT} == READINESS_STATES
#: The application disk can never be a customer-managed provider, which is
#: what makes ``ADOPT_IN_PLACE`` structurally unreachable for a legacy row.
assert m.PROVIDER_LEGACY_APP_DISK not in m.CUSTOMER_MANAGED_PROVIDER_KINDS
#: W0-06D reads the declared map and never replaces it.
assert set(mp.SOURCES_BY_KEY) == {s.key for s in mp.LEGACY_SOURCES}
#: This module exposes no apply/commit/execute path. Checked by name, because a
#: method called ``apply`` is exactly what a later slice might be tempted to
#: add here instead of in the authorised migration runner.
assert not {"apply", "apply_plan", "adopt", "commit", "execute", "migrate",
            "run_migration"} & set(vars(LegacyAdoptionReadiness))

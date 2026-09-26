"""Reading and verifying one round.

A round is deliberately two-phase. Phase one reads ``CONTROL_STATE.json``, its schema
and ``CONTROL_BOARD.md``. Phase two parses the state and then reads *the paths the
state itself cites* -- ``source_refs.active_path``, ``source_refs.review_path`` and the
cited PR number. Fetching hardcoded paths instead would verify a snapshot against
whatever happens to live at a familiar location, which is not the same claim.

Requests are issued serially. Six conditional GETs at a 10-30 s cadence is a trivial
load, and serial ordering keeps the request log a readable, assertable sequence.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

from . import board as board_module
from . import invariants, schema
from .github import FetchedFile, GitHubReadOnlyClient, PullRequestInfo, TransportError
from .gitblob import sha_equal, short
from .redact import redact
from .settings import CONTROL_BOARD_PATH, CONTROL_SCHEMA_PATH, CONTROL_STATE_PATH, Settings
from .status import CLEAN, Finding, Status, Verdict


@dataclasses.dataclass(frozen=True, slots=True)
class Snapshot:
    """The bytes read in one round, plus what could not be read and why."""

    fetched_at: dt.datetime
    control_state: FetchedFile
    control_schema: FetchedFile
    board: FetchedFile | None = None
    active: FetchedFile | None = None
    review: FetchedFile | None = None
    pull_request: PullRequestInfo | None = None
    notes: tuple[str, ...] = ()
    request_count: int = 0
    conditional_hits: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class VerifiedSnapshot:
    """A verified round: the bound state (when usable), the verdict and the bytes."""

    state: dict | None
    verdict: Verdict
    snapshot: Snapshot

    @property
    def status(self) -> Status:
        return self.verdict.status

    @property
    def verified_at(self) -> dt.datetime:
        return self.snapshot.fetched_at


def read_snapshot(
    client: GitHubReadOnlyClient, settings: Settings, now: dt.datetime | None = None
) -> Snapshot:
    """Read one round. Raises ``TransportError`` only if the state itself is unreadable."""
    before = len(client.request_log)
    fetched_at = now or dt.datetime.now(dt.timezone.utc)
    notes: list[str] = []

    # The state and its schema are the two files without which there is nothing to show.
    control_state = client.file(CONTROL_STATE_PATH, settings.branch)
    control_schema = client.file(CONTROL_SCHEMA_PATH, settings.branch)

    board = _optional(client, CONTROL_BOARD_PATH, settings.branch, notes)

    state: dict | None = None
    try:
        parsed = json.loads(control_state.text)
        state = parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        state = None

    active = review = None
    pull_request = None
    if state is not None:
        refs = state.get("source_refs") if isinstance(state.get("source_refs"), dict) else {}
        active_path = refs.get("active_path")
        if isinstance(active_path, str) and active_path:
            active = _optional(client, active_path, settings.branch, notes)
        review_path = refs.get("review_path")
        if isinstance(review_path, str) and review_path:
            review = _optional(client, review_path, settings.branch, notes)
        number = state.get("pr_number")
        if settings.verify_pull_request and isinstance(number, int):
            try:
                pull_request = client.pull_request(number)
            except TransportError as error:
                notes.append(redact(f"PR #{number} metadata could not be read: {error}"))

    requests = client.request_log[before:]
    hits = sum(1 for item in (control_state, control_schema, board, active, review) if getattr(item, "from_cache", False))
    return Snapshot(
        fetched_at=fetched_at,
        control_state=control_state,
        control_schema=control_schema,
        board=board,
        active=active,
        review=review,
        pull_request=pull_request,
        notes=tuple(notes),
        request_count=len(requests),
        conditional_hits=hits,
    )


def _optional(
    client: GitHubReadOnlyClient, path: str, ref: str, notes: list[str]
) -> FetchedFile | None:
    """Read a supporting file. A failure degrades the verdict; it does not end the round."""
    try:
        return client.file(path, ref)
    except TransportError as error:
        notes.append(redact(f"{path} could not be read: {error}"))
        return None


def verify(snapshot: Snapshot, settings: Settings) -> VerifiedSnapshot:
    """Verify one round and return the worst-of verdict with every finding."""
    try:
        state_object = json.loads(snapshot.control_state.text)
    except json.JSONDecodeError as error:
        return VerifiedSnapshot(
            None,
            Verdict([Finding(Status.INVALID, "CONTROL_STATE_UNPARSED", f"CONTROL_STATE.json is not valid JSON: {error}")]),
            snapshot,
        )
    if not isinstance(state_object, dict):
        return VerifiedSnapshot(
            None,
            Verdict([Finding(Status.INVALID, "CONTROL_STATE_NOT_OBJECT", "CONTROL_STATE.json is not a JSON object.")]),
            snapshot,
        )

    try:
        schema_object = json.loads(snapshot.control_schema.text)
    except json.JSONDecodeError as error:
        return VerifiedSnapshot(
            state_object,
            Verdict([Finding(Status.INVALID, "SCHEMA_UNPARSED", f"CONTROL_STATE.schema.json is not valid JSON: {error}")]),
            snapshot,
        )

    verdict = (
        schema.validate(state_object, schema_object)
        .merge(invariants.validate(state_object))
        .merge(_configured_target(state_object, settings))
        .merge(_transport_integrity(snapshot))
        .merge(_cited_blobs(state_object, snapshot))
        .merge(_pull_request(state_object, snapshot, settings))
        .merge(board_module.cross_check(state_object, snapshot.board.text if snapshot.board else None))
        .merge(_notes(snapshot))
    )
    return VerifiedSnapshot(state_object, verdict, snapshot)


def _notes(snapshot: Snapshot) -> Verdict:
    return Verdict(
        Finding(Status.STALE, "SOURCE_READ_FAILED", note) for note in snapshot.notes
    )


def _configured_target(state: dict, settings: Settings) -> Verdict:
    """The snapshot must describe the repository and branch this dashboard was pointed at."""
    findings: list[Finding] = []
    if state.get("repository") != settings.repository:
        findings.append(
            Finding(
                Status.CONFLICT,
                "REPOSITORY_MISMATCH",
                f"Snapshot names repository {state.get('repository')!r}; this dashboard is configured for {settings.repository!r}.",
            )
        )
    if state.get("branch") != settings.branch:
        findings.append(
            Finding(
                Status.CONFLICT,
                "BRANCH_MISMATCH",
                f"Snapshot names branch {state.get('branch')!r}; this dashboard is configured for {settings.branch!r}.",
            )
        )
    return Verdict(findings)


def _transport_integrity(snapshot: Snapshot) -> Verdict:
    """The locally computed blob SHA must equal the one the API reported for the same read.

    A disagreement means the bytes in hand are not the blob the API named -- truncation,
    a proxy rewriting content, a corrupted decode. Whatever the cause, the content
    cannot be trusted for a blob comparison.
    """
    findings: list[Finding] = []
    for label, item in (
        ("CONTROL_STATE.json", snapshot.control_state),
        ("CONTROL_STATE.schema.json", snapshot.control_schema),
        ("CONTROL_BOARD.md", snapshot.board),
        ("ACTIVE", snapshot.active),
        ("REVIEW", snapshot.review),
    ):
        if item is None or not item.api_reported_sha:
            continue
        if not sha_equal(item.blob_sha, item.api_reported_sha):
            findings.append(
                Finding(
                    Status.INVALID,
                    "BLOB_TRANSPORT_MISMATCH",
                    f"{label}: bytes received hash to {short(item.blob_sha)} but the API named blob {short(item.api_reported_sha)}.",
                )
            )
    return Verdict(findings)


def _cited_blobs(state: dict, snapshot: Snapshot) -> Verdict:
    refs = state.get("source_refs") if isinstance(state.get("source_refs"), dict) else {}
    findings: list[Finding] = []
    _check_blob(findings, snapshot.active, refs.get("active_path"), refs.get("active_blob_sha"), "ACTIVE")
    if refs.get("review_blob_sha"):
        _check_blob(
            findings,
            snapshot.review,
            refs.get("review_path") or "coordination/REVIEWS/",
            refs.get("review_blob_sha"),
            "REVIEW",
        )
    return Verdict(findings)


def _check_blob(
    findings: list[Finding],
    file: FetchedFile | None,
    cited_path: object,
    cited_sha: object,
    label: str,
) -> None:
    if not isinstance(cited_sha, str) or not cited_sha:
        return
    if file is None:
        findings.append(
            Finding(
                Status.STALE,
                "SOURCE_UNVERIFIED",
                f"{label} source {cited_path!r} was not read this round, so its cited blob is unverified.",
            )
        )
        return
    if isinstance(cited_path, str) and file.path != cited_path:
        findings.append(
            Finding(
                Status.CONFLICT,
                "SOURCE_PATH_MISMATCH",
                f"{label} was read from {file.path!r} but the snapshot cites {cited_path!r}.",
            )
        )
        return
    if not sha_equal(file.blob_sha, cited_sha):
        findings.append(
            Finding(
                Status.STALE,
                "SOURCE_BLOB_MISMATCH",
                f"{label} {cited_path!r} is blob {short(file.blob_sha)} on the branch but the snapshot cites {short(cited_sha)}.",
            )
        )


def _pull_request(state: dict, snapshot: Snapshot, settings: Settings) -> Verdict:
    number = state.get("pr_number")
    if number is None:
        return CLEAN
    if not settings.verify_pull_request:
        return Verdict(
            [
                Finding(
                    Status.STALE,
                    "PR_VERIFICATION_DISABLED",
                    f"PR #{number} head verification is switched off in this deployment, so the cited exact head is unverified.",
                )
            ]
        )
    pr = snapshot.pull_request
    if pr is None:
        return Verdict(
            [
                Finding(
                    Status.STALE,
                    "PR_UNVERIFIED",
                    f"PR #{number} metadata was not read this round, so the cited exact head is unverified.",
                )
            ]
        )
    findings: list[Finding] = []
    if pr.number != number:
        return Verdict(
            [
                Finding(
                    Status.CONFLICT,
                    "PR_NUMBER_MISMATCH",
                    f"Read PR #{pr.number} but the snapshot cites #{number}.",
                )
            ]
        )
    if not sha_equal(pr.head_sha, state.get("pr_head_sha")):
        findings.append(
            Finding(
                Status.STALE,
                "PR_HEAD_STALE",
                f"PR #{pr.number} head is {short(pr.head_sha)} but the snapshot was validated against {short(state.get('pr_head_sha'))}.",
            )
        )
    draft = state.get("pr_draft")
    if isinstance(draft, bool) and draft != pr.draft:
        findings.append(
            Finding(
                Status.CONFLICT,
                "PR_DRAFT_MISMATCH",
                f"PR #{pr.number} draft flag is {pr.draft} but the snapshot records {draft}.",
            )
        )
    if pr.merged:
        findings.append(
            Finding(
                Status.CONFLICT,
                "PR_MERGED",
                f"PR #{pr.number} is merged, but the snapshot still describes it as work in progress.",
            )
        )
    return Verdict(findings)

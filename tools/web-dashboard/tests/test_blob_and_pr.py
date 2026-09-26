"""Cited-source verification: blob bytes and the exact PR head.

CONTROL_STATE cites its evidence by Git blob SHA and by exact PR head SHA. Those
citations are the whole basis on which a snapshot claims to describe reality, so the
dashboard re-derives both rather than believing either.
"""

from __future__ import annotations

import pytest
from app.gitblob import blob_sha1
from app.github import TransportError
from app.status import Status
from app.verify import read_snapshot, verify

from conftest import ACTIVE_PATH, REVIEW_PATH, CONTROL_STATE_PATH


def round_verdict(client, settings):
    return verify(read_snapshot(client, settings), settings)


# ---------------------------------------------------------------- blob identity


def test_the_published_snapshot_verifies_against_canonical_committed_bytes(client, settings):
    """The positive case, on the real repository contents.

    This is the test that failed on the reviewer's Windows checkout in PR #28. It passes
    here on any platform because the fixture reads committed blob bytes rather than a
    checked-out file whose line endings Git may have rewritten.
    """
    result = round_verdict(client, settings)
    assert result.status is Status.VALID, result.verdict.as_dicts()
    assert result.verdict.findings == ()


def test_the_cited_active_blob_sha_matches_the_bytes_actually_read(client, settings, published_state):
    result = round_verdict(client, settings)
    observed = result.snapshot.active.blob_sha
    assert observed == published_state["source_refs"]["active_blob_sha"]


def test_a_changed_active_file_is_reported_stale(fake_github, client, settings):
    """If ACTIVE.md moves on the branch, the snapshot no longer describes it."""
    fake_github.set_file(ACTIVE_PATH, b"# a different ACTIVE than the one cited\n")
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "SOURCE_BLOB_MISMATCH" in result.verdict.codes()


def test_a_changed_review_file_is_reported_stale(fake_github, client, settings):
    fake_github.set_file(REVIEW_PATH, b"# a different review\n")
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "SOURCE_BLOB_MISMATCH" in result.verdict.codes()


def test_a_crlf_converted_checkout_would_not_match(canonical_bytes, fake_github, client, settings):
    """The production blob check stays fail-closed.

    The fixture fix in this suite is about reading the right bytes, not about accepting
    the wrong ones. CRLF-converted content is genuinely a different blob, and the
    dashboard must still refuse it -- otherwise a tampered source could be smuggled past
    the check by adding carriage returns.
    """
    lf = canonical_bytes[ACTIVE_PATH]
    crlf = lf.replace(b"\n", b"\r\n")
    assert crlf != lf, "the fixture file must contain newlines for this test to mean anything"
    assert blob_sha1(crlf) != blob_sha1(lf)

    fake_github.set_file(ACTIVE_PATH, crlf)
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "SOURCE_BLOB_MISMATCH" in result.verdict.codes()


def test_an_unreadable_cited_source_is_unverified_not_assumed_good(fake_github, client, settings):
    fake_github.fail_paths[ACTIVE_PATH] = TransportError("HTTP 500", status=500)
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "SOURCE_UNVERIFIED" in result.verdict.codes()


def test_a_source_served_from_a_different_path_is_a_conflict(fake_github, client, settings, published_state):
    """The dashboard reads the path the snapshot cites; a different path is not a substitute."""
    import base64
    import json as _json

    from app.github import Response

    original = fake_github.request

    def rerouted(method, url, headers, timeout):
        if "/contents/" in url and ACTIVE_PATH in url.replace("%2F", "/"):
            content = fake_github.files[ACTIVE_PATH]
            payload = {
                "type": "file",
                "path": "coordination/SOMEWHERE_ELSE.md",
                "encoding": "base64",
                "size": len(content),
                "sha": blob_sha1(content),
                "content": base64.b64encode(content).decode("ascii"),
            }
            return Response(200, {}, _json.dumps(payload).encode("utf-8"))
        return original(method, url, headers, timeout)

    fake_github.request = rerouted
    result = round_verdict(client, settings)
    assert result.status is Status.CONFLICT
    assert "SOURCE_PATH_MISMATCH" in result.verdict.codes()


def test_bytes_that_disagree_with_the_api_reported_blob_are_invalid(fake_github, client, settings):
    """Truncation or rewriting in transit must not be treated as content."""
    import base64
    import json as _json

    from app.github import Response

    original = fake_github.request

    def truncating(method, url, headers, timeout):
        if "/contents/" in url and ACTIVE_PATH in url.replace("%2F", "/"):
            content = fake_github.files[ACTIVE_PATH]
            payload = {
                "type": "file",
                "path": ACTIVE_PATH,
                "encoding": "base64",
                "size": len(content),
                # The API names the true blob, but only half the bytes arrive.
                "sha": blob_sha1(content),
                "content": base64.b64encode(content[: len(content) // 2]).decode("ascii"),
            }
            return Response(200, {}, _json.dumps(payload).encode("utf-8"))
        return original(method, url, headers, timeout)

    fake_github.request = truncating
    result = round_verdict(client, settings)
    assert result.status is Status.INVALID
    assert "BLOB_TRANSPORT_MISMATCH" in result.verdict.codes()


def test_an_oversized_blob_is_refused_rather_than_read_as_empty(fake_github, client, settings):
    """The contents API omits content above 1 MB; an empty file is not the same thing."""
    import json as _json

    from app.github import Response

    original = fake_github.request

    def oversized(method, url, headers, timeout):
        if "/contents/" in url and ACTIVE_PATH in url.replace("%2F", "/"):
            payload = {"type": "file", "path": ACTIVE_PATH, "encoding": "none", "size": 2_000_000, "sha": "0" * 40}
            return Response(200, {}, _json.dumps(payload).encode("utf-8"))
        return original(method, url, headers, timeout)

    fake_github.request = oversized
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "SOURCE_UNVERIFIED" in result.verdict.codes()


# ---------------------------------------------------------------- exact PR head


def test_a_moved_pr_head_is_reported_stale(fake_github, client, settings, published_state):
    """A Draft PR whose head has moved is no longer the head that was reviewed."""
    number = published_state["pr_number"]
    fake_github.pull_requests[number]["head"]["sha"] = "a" * 40
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "PR_HEAD_STALE" in result.verdict.codes()


def test_a_pr_that_left_draft_is_a_conflict(fake_github, client, settings, published_state):
    number = published_state["pr_number"]
    fake_github.pull_requests[number]["draft"] = False
    result = round_verdict(client, settings)
    assert result.status is Status.CONFLICT
    assert "PR_DRAFT_MISMATCH" in result.verdict.codes()


def test_a_merged_pr_contradicts_a_snapshot_describing_work_in_progress(
    fake_github, client, settings, published_state
):
    number = published_state["pr_number"]
    fake_github.pull_requests[number]["merged"] = True
    result = round_verdict(client, settings)
    assert result.status is Status.CONFLICT
    assert "PR_MERGED" in result.verdict.codes()


def test_unreadable_pr_metadata_leaves_the_head_unverified(fake_github, client, settings, published_state):
    fake_github.pull_requests.clear()
    result = round_verdict(client, settings)
    assert result.status is Status.STALE
    assert "PR_UNVERIFIED" in result.verdict.codes()


def test_disabling_pr_verification_is_reported_not_hidden(client, settings, fake_github):
    """Switching a check off degrades the verdict; it does not make the claim verified."""
    import dataclasses

    relaxed = dataclasses.replace(settings, verify_pull_request=False)
    result = verify(read_snapshot(client, relaxed), relaxed)
    assert result.status is Status.STALE
    assert "PR_VERIFICATION_DISABLED" in result.verdict.codes()


def test_a_snapshot_for_another_repository_or_branch_is_a_conflict(client, settings, fake_github):
    import dataclasses

    elsewhere = dataclasses.replace(settings, branch="main")
    result = verify(read_snapshot(client, elsewhere), elsewhere)
    assert result.status is Status.CONFLICT
    assert "BRANCH_MISMATCH" in result.verdict.codes()


def test_an_unparsable_control_state_is_invalid_and_binds_nothing(fake_github, client, settings):
    fake_github.set_file(CONTROL_STATE_PATH, b"{ this is not json")
    result = round_verdict(client, settings)
    assert result.status is Status.INVALID
    assert "CONTROL_STATE_UNPARSED" in result.verdict.codes()
    assert result.state is None


def test_a_missing_control_state_ends_the_round_as_a_transport_error(fake_github, client, settings):
    """Without the state there is nothing to project, and that is not a verdict."""
    del fake_github.files[CONTROL_STATE_PATH]
    with pytest.raises(TransportError):
        read_snapshot(client, settings)

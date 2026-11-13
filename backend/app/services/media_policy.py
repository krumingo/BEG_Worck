"""
MEDIA-SEC-01 — the media rules that are a BUSINESS decision, in one place.

FLOW Guard pass 46: three questions are open with Krum (who sees avatars; an Owner's own
retire request; restoring a retired file). Until he answers, the orchestrator's interim
choices apply. Each one is a single constant here, so a later decision changes one line
(plus its test), not the routes.

R83(2) — the Owner-approval flow is an INTERIM substitute for the canonical Approval
runtime (W0-07). It is debt to W0-07 and must not become a second Approval source of
truth: when W0-07 lands, ``media_retire_requests`` moves into it.
"""
from __future__ import annotations

#: who sees an avatar — interim: everyone in the firm (the tenant); "self_and_admin" would
#: limit it to the user and Owner/Admin (open question to Krum)
AVATAR_VISIBILITY = "tenant"

#: R83(2) / pass 46 interim: an Admin files the retire request of a USED file …
RETIRE_REQUEST_ROLES = frozenset({"Admin"})
#: … and an Owner approves or rejects it (never the requester — second-person check)
RETIRE_APPROVER_ROLES = frozenset({"Owner"})

#: restoring a retired file — interim: not offered (open question to Krum)
RESTORE_ENABLED = False

#: R83(1) / FG-575: company roles that never upload a file, at ANY upload entry point
UPLOAD_DENIED_ROLES = frozenset({"Viewer"})
#: project-team roles that only read a project's files
UPLOAD_DENIED_PROJECT_ROLES = frozenset({"Viewer"})

#: who may see WHICH records use a file (ids of payments, users, …) in a 409 / a request
USAGE_DETAIL_ROLES = frozenset({"Owner", "Admin"})


def may_see_usage_detail(user: dict) -> bool:
    return (user or {}).get("role") in USAGE_DETAIL_ROLES


#: FG-588 condition 4: a pending-holder marker is released as stale only when it is older than
#: this — far above the warehouse movement transaction's lifetime (seconds)
PENDING_HOLDER_MIN_AGE_SECONDS = 3600

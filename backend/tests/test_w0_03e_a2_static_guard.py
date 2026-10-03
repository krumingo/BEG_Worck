"""
W0-03E-A2 / C01 — the static guard is portable AND catches a bare membership read.

Two separate A1 review findings are pinned here.

**Portability.** On the reviewed A1 head the guard exited 1 on a clean tree in
a Windows environment and 0 on POSIX: ``_rel()`` built its comparison key with
``str(PurePath)``, which yields ``app\\services\\paid_labor.py`` on Windows,
while ``HELPER_MODULES`` holds POSIX strings. The membership test was therefore
false and three helper modules were judged by the stricter tier, reporting four
violations that were a path-normalization failure, not four data leaks. A guard
whose verdict depends on the host separator proves nothing. These tests assert
the POSIX key directly and simulate the Windows flavour with
``PureWindowsPath``, so they are deterministic on both platforms.

**The A2 rule.** ``A2-TEAM`` rejects any ``project_team`` access outside
``app.tenancy.project_team``, over the WHOLE ``app/`` tree rather than the A1
protected set, because a membership question answered anywhere decides access
everywhere. A deliberately injected bare-id lookup must fail the guard, and no
exclusion may make it pass.

Run:  pytest tests/test_w0_03e_a2_static_guard.py -v --noconftest
"""
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_03e_a1_tenant_access_guard as guard  # noqa: E402

SCRIPT = BACKEND / "scripts" / "w0_03e_a1_tenant_access_guard.py"
RELATION = "app/tenancy/project_team.py"


def team_rules(source, rel="app/routes/attendance.py"):
    return {v[2] for v in guard.check_team_relation(source, rel)}


# ------------------------------------------------------- Windows/POSIX portability
def test_the_windows_separator_was_the_a1_failure_and_is_normalized_now():
    """The exact mechanism, reproduced without needing a Windows host."""
    win = PureWindowsPath("app/services/paid_labor.py")
    assert str(win) == "app\\services\\paid_labor.py"        # what A1 compared
    assert str(win) not in guard.HELPER_MODULES              # ...so the tier was wrong
    assert win.as_posix() == "app/services/paid_labor.py"    # what A2 compares
    assert win.as_posix() in guard.HELPER_MODULES            # ...so the tier is right


def test_every_configured_module_resolves_to_its_own_posix_key():
    for rel in guard.PROTECTED_MODULES + guard.HELPER_MODULES + tuple(guard.PROTECTED_FUNCTIONS):
        path, key = guard._rel(rel)
        assert key == rel, (rel, key)
        assert "\\" not in key
        assert PurePosixPath(key) == PurePosixPath(rel)
        assert path.is_absolute() and path.exists(), rel


def test_an_absolute_path_also_yields_the_backend_relative_posix_key():
    for rel in guard.HELPER_MODULES:
        _, key = guard._rel(str(BACKEND / rel))
        assert key == rel, (rel, key)


def test_a_windows_style_argument_is_accepted_on_a_posix_interpreter():
    """``guard.py app\\services\\paid_labor.py`` must mean the same file."""
    rel = "app/services/paid_labor.py"
    _, key = guard._rel(rel.replace("/", "\\"))
    assert key == rel
    # and the CLI agrees with the POSIX spelling
    both = []
    for arg in (rel, rel.replace("/", "\\")):
        r = subprocess.run([sys.executable, str(SCRIPT), arg], cwd=BACKEND,
                           capture_output=True, text=True)
        both.append((r.returncode, r.stdout.strip().splitlines()[-1]))
    assert both[0] == both[1], both
    assert both[0][0] == 0, both


def test_the_helper_tier_is_decided_by_the_normalized_key():
    """A helper module keeps its tier (A1-IDENTITY waived) under either spelling."""
    source = 'async def f(db, org):\n    return await db.users.find_one({"org_id": org})\n'
    # helper tier: an identity collection WITH a literal tenant predicate is allowed
    assert guard.check_source(source, "app/services/paid_labor.py", helper=True) == []
    # a route is not a helper: the same line is an A1-IDENTITY violation
    assert "A1-IDENTITY" in {v[2] for v in guard.check_source(source, "app/routes/finance.py")}


# --------------------------------------------------------------- the A2-TEAM rule
def test_the_clean_tree_passes_and_the_script_exits_zero():
    units, violations = guard.check_protected_surface()
    assert violations == [], "\n".join("%s:%d %s %s" % v for v in violations)
    # A1's 40 units plus every module of the app tree (A2-TEAM)
    assert units > 40
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 violation(s)" in r.stdout


@pytest.mark.parametrize("snippet", [
    # the exact A1 defect: a membership answered from an id pair alone
    'async def f(db, user, pid):\n'
    '    return await db.project_team.find_one({"project_id": pid, "user_id": user["id"]})\n',
    # scoping it by hand is still a second access path, so still refused
    'async def f(db, user, pid):\n'
    '    return await db.project_team.find_one({"project_id": pid, "org_id": user["org_id"]})\n',
    # a subscript instead of an attribute
    'async def f(db, pid):\n'
    '    return await db["project_team"].find_one({"project_id": pid})\n',
    # an alias of the collection
    'async def f(db, pid):\n'
    '    coll = db.project_team\n'
    '    return await coll.find_one({"project_id": pid})\n',
    # the pre-bound collection import
    'from app.db import project_team\n'
    'async def f(pid):\n'
    '    return await project_team.find_one({"project_id": pid})\n',
    # a differently named raw handle
    'async def f(legacy_db, pid):\n'
    '    return await legacy_db.project_team.count_documents({"project_id": pid})\n',
])
def test_a_bare_membership_access_is_rejected_wherever_it_appears(snippet):
    assert "A2-TEAM" in team_rules(snippet)
    # and in a module the A1 protected set never covered
    assert "A2-TEAM" in team_rules(snippet, "app/routes/technician.py")


def test_the_relation_module_itself_is_the_one_accessor():
    source = (BACKEND / RELATION).read_text(encoding="utf-8")
    assert guard.check_team_relation(source, RELATION) == []
    # the SAME source placed anywhere else is reported: the exemption is the
    # module path, and that module reaches the collection only via TenantData
    assert 'tenant.collection(COLLECTION)' in source
    assert "db.project_team" not in source


def test_going_through_the_relation_accessors_is_clean():
    source = (
        'from app.tenancy import project_team\n'
        'async def f(tenant, user, pid):\n'
        '    return await project_team.is_member(tenant, user["id"], pid)\n')
    assert team_rules(source) == set()


def test_the_rule_covers_the_whole_app_tree_not_just_the_protected_set():
    files = guard.team_relation_files()
    for must in ("app/routes/attendance.py", "app/routes/work_logs.py",
                 "app/routes/technician.py", "app/routes/media.py",
                 "app/routes/hr.py", "app/routes/daily_reports.py",
                 "app/routes/activity_budgets.py", "app/routes/projects.py",
                 "app/deps/auth.py", "app/db/__init__.py", RELATION):
        assert must in files, must
    assert all("\\" not in f for f in files)


def test_an_injected_bare_lookup_fails_the_real_script_on_a_real_module():
    """End-to-end: inject into the tree, run the CLI, expect exit 1; then restore."""
    target = BACKEND / "app" / "routes" / "attendance.py"
    original = target.read_text(encoding="utf-8")
    anchor = "def _team(user: dict):"
    assert original.count(anchor) == 1
    unsafe = ('async def _injected(db, user, pid):\n'
              '    return await db.project_team.find_one(\n'
              '        {"project_id": pid, "user_id": user["id"], "active": True})\n\n\n')
    try:
        target.write_text(original.replace(anchor, unsafe + anchor), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND,
                           capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "A2-TEAM" in r.stdout
        assert "app/routes/attendance.py" in r.stdout
    finally:
        target.write_text(original, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND,
                       capture_output=True, text=True)
    assert r.returncode == 0, "the tree must be clean again: " + r.stdout + r.stderr


def test_no_exclusion_can_silence_the_rule():
    """The only allowed path is the relation module; there is no allowlist knob."""
    assert guard.TEAM_ALLOWED_MODULES == (RELATION,)
    snippet = 'async def f(db, pid):\n    return await db.project_team.find_one({"id": pid})\n'
    for rel in guard.team_relation_files():
        found = guard.check_team_relation(snippet, rel)
        assert (found == []) is (rel == RELATION), rel

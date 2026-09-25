"""Browser tests: the UI is driven in a real Chromium against a real server.

These are the tests that make the screenshots in ``docs/screenshots/`` evidence rather
than decoration -- the same fixture that asserts the layout also captures it, so a
screenshot cannot show something the assertions do not hold.

Skipped, rather than failed, when Playwright or a Chromium binary is unavailable: a
missing browser is an absent tool, not a defect in the dashboard. Set
``BEGWORK_CHROME`` to override the executable that is used.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

import pytest
from app.github import GitHubReadOnlyClient, TransportError
from app.refresh import Refresher
from app.server import make_server
from app.settings import Settings

playwright_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

SCREENSHOT_DIR = pathlib.Path(__file__).resolve().parents[1] / "docs" / "screenshots"

CHROME_CANDIDATES = [
    os.environ.get("BEGWORK_CHROME", ""),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

# Issue #26's three form factors.
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 960},
    "tablet": {"width": 834, "height": 1112},
    "phone": {"width": 390, "height": 844},
}


def _chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def browser():
    executable = _chrome()
    with playwright_api.sync_playwright() as driver:
        try:
            instance = (
                driver.chromium.launch(executable_path=executable)
                if executable
                else driver.chromium.launch()
            )
        except Exception as error:  # noqa: BLE001
            pytest.skip(f"no usable Chromium: {error}")
        yield instance
        instance.close()


class ServedDashboard:
    """A running dashboard plus the handles a test needs to perturb it."""

    def __init__(self, base, refresher, fake_github):
        self.base = base
        self.refresher = refresher
        self.github = fake_github


@pytest.fixture
def served(fake_github):
    settings = Settings(
        repository="krumingo/BEG_Worck", branch="codex/claude-queue", host="127.0.0.1", port=0
    )
    client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()
    server = make_server(refresher, settings)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield ServedDashboard(f"http://127.0.0.1:{server.server_address[1]}", refresher, fake_github)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def open_page(browser, served, viewport="desktop"):
    page = browser.new_page(viewport=VIEWPORTS[viewport])
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(served.base + "/", wait_until="networkidle")
    # Every test waits for the task id, so nothing below races the first fetch.
    page.wait_for_function("document.getElementById('f-task').textContent !== '—'", timeout=10_000)
    return page, errors


def shoot(page, name):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(target), full_page=True)
    assert target.stat().st_size > 5_000, f"{target} looks empty"
    return target


# ------------------------------------------------------------------ it renders


def test_the_dashboard_renders_the_control_state_with_no_script_errors(browser, served):
    page, errors = open_page(browser, served)
    assert page.inner_text("#f-task") == "W0-03C"
    assert page.inner_text("#f-cycle") == "C02 (migrated)"
    assert page.inner_text("#f-wave") == "W0"
    assert page.inner_text("#f-flow") == "FLOW-032"
    assert page.inner_text("#f-stage") == "REVIEW"
    assert page.inner_text("#f-state") == "BLOCKED"
    assert page.inner_text("#f-status-value") == "VALID"
    assert page.inner_text("#f-link-value") == "ONLINE"
    assert page.inner_text("#f-krum-value") == "REQUIRED"
    assert errors == []
    page.close()


def test_the_three_agent_cards_render_their_protocol_state(browser, served):
    page, _ = open_page(browser, served)
    cards = page.locator(".agent")
    assert cards.count() == 3
    assert [cards.nth(i).locator(".agent__name").inner_text() for i in range(3)] == [
        "ChatGPT",
        "Codex",
        "Claude",
    ]
    assert cards.nth(0).get_attribute("data-state") == "NOT_ACTIVE"
    assert cards.nth(1).get_attribute("data-state") == "BLOCKED"
    assert cards.nth(2).get_attribute("data-state") == "NOT_ACTIVE"
    # The Codex card carries its Work-ID, waiting_for and timestamp.
    codex = cards.nth(1).inner_text()
    assert "W0-03C/C02/CX" in codex
    assert "2026-09-22T06:17:02Z" in codex
    page.close()


def test_the_pipeline_shows_five_steps_with_the_review_step_active(browser, served):
    page, _ = open_page(browser, served)
    steps = page.locator(".pipeline__step")
    assert steps.count() == 5
    assert [steps.nth(i).locator(".pipeline__agent").inner_text() for i in range(5)] == [
        "ChatGPT",
        "Codex",
        "Claude",
        "Codex",
        "ChatGPT",
    ]
    active = page.locator(".pipeline__step--active")
    assert active.count() == 1
    assert "REVIEW" in active.inner_text()
    assert "BLOCKED" in active.inner_text()
    page.close()


def test_stage_only_progress_draws_no_bar_and_states_why(browser, served):
    page, _ = open_page(browser, served)
    assert page.locator(".progress__bar").count() == 0
    note = page.inner_text(".progress__note")
    assert "STAGE_ONLY" in note
    assert "no percentage" in note.lower()
    # No stray percentage anywhere in the progress area.
    assert "%" not in page.inner_text("#f-progress")
    page.close()


def test_history_and_evidence_links_are_present_and_point_at_github(browser, served, published_state):
    page, _ = open_page(browser, served)
    assert page.locator(".event").count() == len(published_state["history"])
    hrefs = page.eval_on_selector_all(
        "#f-evidence a, #f-history a", "nodes => nodes.map(n => n.href)"
    )
    assert hrefs
    assert all(href.startswith("https://github.com/krumingo/BEG_Worck/") for href in hrefs)
    # External links must not leak the referrer of an internal dashboard.
    rels = page.eval_on_selector_all("#f-evidence a", "nodes => nodes.map(n => n.rel)")
    assert all("noreferrer" in rel for rel in rels)
    page.close()


def test_the_page_never_receives_the_token(browser, served):
    """Belt and braces at the last possible point: the rendered document itself."""
    page, _ = open_page(browser, served)
    content = page.content()
    assert "ghp_" not in content
    assert "Bearer" not in content
    assert "Authorization" not in content
    page.close()


# --------------------------------------------------- the four statuses, on screen


@pytest.mark.parametrize("status", ["VALID", "STALE", "CONFLICT", "INVALID"])
def test_each_status_is_visually_distinct_and_named_in_words(status, browser, served, published_state, mutate):
    """Distinguishable by more than colour: the word itself is on screen, and the
    styling hook differs so a reviewer can confirm the distinction in a screenshot."""
    if status == "STALE":
        served.github.set_file("coordination/ACTIVE.md", b"moved on\n")
    elif status == "CONFLICT":
        board = served.github.files["coordination/CONTROL_BOARD.md"].decode("utf-8")
        served.github.set_file(
            "coordination/CONTROL_BOARD.md", board.replace("## Evidence", "## Evidence altered").encode("utf-8")
        )
    elif status == "INVALID":
        served.github.set_state(mutate(published_state, lambda s: s.__setitem__("wave", "not-a-wave")))
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        f"document.getElementById('f-status-value').textContent === '{status}'", timeout=10_000
    )
    chip = page.locator("#f-status")
    assert chip.get_attribute("data-status") == status
    assert page.inner_text("#f-status-value") == status

    if status == "VALID":
        assert page.inner_text("#f-verified").startswith("verified")
        assert "No findings" in page.inner_text("#f-findings")
    else:
        assert "NOT verified" in page.inner_text("#f-verified")
        assert page.locator(".finding").count() >= 1
        # Every finding names its own severity in words.
        assert status in page.inner_text("#f-findings")

    shoot(page, f"status-{status.lower()}")
    assert errors == []
    page.close()


def test_offline_is_shown_as_its_own_state_alongside_the_cached_snapshot(browser, served):
    """The cached reading stays on screen, dated, with the link marked OFFLINE."""
    served.github.fail_everything = TransportError("simulated network outage")
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        "document.getElementById('f-link-value').textContent === 'OFFLINE'", timeout=10_000
    )
    assert page.locator("#f-link").get_attribute("data-link") == "OFFLINE"
    # The snapshot is still there and still says BLOCKED.
    assert page.inner_text("#f-task") == "W0-03C"
    assert page.inner_text("#f-state") == "BLOCKED"
    # And the status verdict is not rewritten into a protocol problem by the outage.
    assert page.inner_text("#f-status-value") == "VALID"
    assert "simulated network outage" in page.inner_text("#f-error")

    shoot(page, "link-offline")
    assert errors == []
    page.close()


def test_a_forged_pass_renders_as_unverified_on_screen(browser, served, published_state, mutate):
    """The safety property, verified in the browser rather than only in the payload."""
    served.github.set_state(
        mutate(
            published_state,
            lambda s: (
                s.__setitem__("state", "PASS"),
                s["agent_states"]["CODEX"].__setitem__("state", "PASS"),
            ),
        )
    )
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        "document.getElementById('f-state').textContent.includes('UNVERIFIED')", timeout=10_000
    )
    assert page.inner_text("#f-state") == "PASS (UNVERIFIED)"
    assert "UNVERIFIED" in page.inner_text(".pipeline__step--active")
    shoot(page, "forged-pass-unverified")
    assert errors == []
    page.close()


def test_the_unavailable_state_is_shown_when_nothing_could_ever_be_read(browser, fake_github):
    """First-round failure: an explicit CONTROL STATE NOT AVAILABLE, not a blank page."""
    fake_github.fail_everything = TransportError("no route to github")
    settings = Settings(repository="krumingo/BEG_Worck", branch="codex/claude-queue", host="127.0.0.1", port=0)
    client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()
    server = make_server(refresher, settings)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        page = browser.new_page(viewport=VIEWPORTS["desktop"])
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/", wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('f-state').textContent.includes('NOT AVAILABLE')", timeout=10_000
        )
        assert page.inner_text("#f-state") == "CONTROL STATE NOT AVAILABLE"
        assert page.inner_text("#f-link-value") == "OFFLINE"
        assert "CONTROL STATE NOT AVAILABLE" in page.inner_text("#f-gate")
        shoot(page, "state-unavailable")
        page.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ------------------------------------------------------------------ responsive


@pytest.mark.parametrize("form_factor", list(VIEWPORTS))
def test_the_layout_works_at_each_form_factor_without_horizontal_scrolling(
    form_factor, browser, served
):
    """Issue #26's layout requirement, asserted rather than eyeballed.

    Horizontal overflow is the specific failure that makes a dashboard unusable on a
    phone, so it is measured: the document must not be wider than the viewport.
    """
    page, errors = open_page(browser, served, form_factor)
    width = VIEWPORTS[form_factor]["width"]

    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"{form_factor}: {overflow}px of horizontal overflow"

    # All three cards are rendered at every size; only their arrangement changes.
    cards = page.locator(".agent")
    assert cards.count() == 3
    boxes = [cards.nth(i).bounding_box() for i in range(3)]
    assert all(box and box["width"] > 0 and box["height"] > 0 for box in boxes)

    rows = {round(box["y"]) for box in boxes}
    if form_factor == "desktop":
        # Three abreast: one row.
        assert len(rows) == 1, f"desktop should place three cards side by side, got {len(rows)} rows"
    elif form_factor == "phone":
        # Single column: three distinct rows.
        assert len(rows) == 3, f"phone should stack the cards, got {len(rows)} rows"

    # Nothing may be clipped out of the viewport horizontally.
    for box in boxes:
        assert box["x"] >= -1
        assert box["x"] + box["width"] <= width + 1

    shoot(page, f"layout-{form_factor}")
    assert errors == []
    page.close()


def test_the_phone_layout_keeps_the_blocker_and_krum_action_visible(browser, served):
    """Narrow screens may compress, but must not hide the two things that need action."""
    page, _ = open_page(browser, served, "phone")
    assert page.locator("#f-krum").is_visible()
    assert page.inner_text("#f-krum-value") == "REQUIRED"
    assert page.locator("#f-krum-reason").is_visible()
    assert "correction cycle" in page.inner_text("#f-krum-reason").lower()
    assert page.locator("#f-state").is_visible()
    page.close()


def test_the_dark_and_light_themes_both_render(browser, served):
    """Both schemes are shipped, so both are checked and captured."""
    for scheme in ("dark", "light"):
        page = browser.new_page(viewport=VIEWPORTS["desktop"], color_scheme=scheme)
        page.goto(served.base + "/", wait_until="networkidle")
        page.wait_for_function("document.getElementById('f-task').textContent !== '—'", timeout=10_000)
        background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        assert background not in ("", "rgba(0, 0, 0, 0)"), f"{scheme}: body has no background"
        shoot(page, f"theme-{scheme}")
        page.close()


# ------------------------------------------------------------------ PWA surface


def test_the_manifest_and_icons_make_the_page_installable(browser, served):
    page, _ = open_page(browser, served)
    href = page.get_attribute("link[rel=manifest]", "href")
    assert href == "/manifest.webmanifest"

    manifest = json.loads(
        page.evaluate(
            "async () => (await fetch('/manifest.webmanifest')).text()",
        )
    )
    assert manifest["name"] == "BEG_WORK Control"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])

    # Every icon the manifest names must actually be served.
    statuses = page.evaluate(
        "async (srcs) => { const out = []; for (const s of srcs) { out.push((await fetch(s)).status); } return out; }",
        [icon["src"] for icon in manifest["icons"]],
    )
    assert set(statuses) == {200}
    page.close()


# ------------------------------- unverified progress must not reach the screen


def test_an_impossible_percentage_draws_no_number_and_no_bar(browser, served, published_state, mutate):
    """The C02 review finding, asserted where it was visible: in the browser.

    A state claiming ``3 of 8 · 90%`` is INVALID (100*3//8 is 37). Before the fix the page
    rendered "3 of 8 verified milestones · 90%" with a 90%-full bar.
    """
    served.github.set_state(
        mutate(
            published_state,
            lambda s: s.__setitem__(
                "progress",
                {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 90},
            ),
        )
    )
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        "document.getElementById('f-status-value').textContent === 'INVALID'", timeout=10_000
    )

    progress_text = page.inner_text("#f-progress")
    assert page.locator(".progress__bar").count() == 0, "a progress bar was drawn for an unverified round"
    assert "%" not in progress_text
    assert "90" not in progress_text
    assert "verified milestones" not in progress_text
    # The stage survives, explicitly labelled.
    assert "REVIEW" in progress_text
    assert "UNVERIFIED" in progress_text
    assert "did not verify" in progress_text

    shoot(page, "progress-unverified-withheld")
    assert errors == []
    page.close()


@pytest.mark.parametrize("status", ["STALE", "CONFLICT"])
def test_no_bar_is_drawn_on_any_unverified_status(status, browser, served, published_state, mutate):
    """Even an arithmetically correct count is withheld when the round did not verify."""
    deterministic = {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 37}
    served.github.set_state(mutate(published_state, lambda s: s.__setitem__("progress", dict(deterministic))))
    if status == "STALE":
        served.github.set_file("coordination/ACTIVE.md", b"moved on\n")
    else:
        board = served.github.files["coordination/CONTROL_BOARD.md"].decode("utf-8")
        served.github.set_file(
            "coordination/CONTROL_BOARD.md", board.replace("## Evidence", "## Evidence altered").encode("utf-8")
        )
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        f"document.getElementById('f-status-value').textContent === '{status}'", timeout=10_000
    )
    assert page.locator(".progress__bar").count() == 0
    text = page.inner_text("#f-progress")
    assert "37%" not in text
    assert "UNVERIFIED" in text
    assert errors == []
    page.close()


def test_a_verified_evidence_count_does_draw_its_justified_bar(browser, served, published_state, mutate):
    """The suppression must not swallow a proven figure."""
    served.github.set_state(
        mutate(
            published_state,
            lambda s: s.__setitem__(
                "progress",
                {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 37},
            ),
        )
    )
    served.refresher.tick()

    page, errors = open_page(browser, served)
    page.wait_for_function(
        "document.getElementById('f-status-value').textContent === 'VALID'", timeout=10_000
    )
    assert page.locator(".progress__bar").count() == 1
    text = page.inner_text("#f-progress")
    assert "3 of 8 verified milestones · 37%" in text
    assert "UNVERIFIED" not in text
    width = page.evaluate("() => document.querySelector('.progress__fill').style.width")
    assert width == "37%"
    shoot(page, "progress-verified-evidence-count")
    assert errors == []
    page.close()

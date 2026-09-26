"""No horizontal document overflow, at any phone width, with any content.

Acceptance on the NAS found the document widening to roughly 575 px at 390 px: a long
GitHub error string and the footer had nothing to break on, so they pushed the page
wider than the screen and the whole layout scrolled sideways.

The content that causes it is exactly the content this dashboard is full of -- 40-char
SHAs, long API URLs, and GitHub error bodies quoted verbatim. So these tests drive the
real page at the four widths the architect named and measure
``documentElement.scrollWidth`` against the viewport, with the worst strings the app can
actually produce.
"""

from __future__ import annotations

import json
import threading

import pytest
from app.github import GitHubReadOnlyClient, TransportError
from app.refresh import Refresher
from app.server import make_server
from app.settings import Settings

playwright_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

from test_ui import VIEWPORTS, _chrome, browser, open_diagnostics, shoot  # noqa: E402,F401

#: The widths named in the acceptance review, smallest first. 320 is an iPhone SE in
#: portrait -- the narrowest screen anyone will realistically open this on.
PHONE_WIDTHS = (320, 375, 390, 430)

#: The real shape of the failure: GitHub's 403 rate-limit body, quoted by the client
#: into ``last_error`` and rendered on the page. One unbroken 300-character run.
RATE_LIMIT_403 = (
    "HTTP 403 for https://api.github.com/repos/krumingo/BEG_Worck/contents/"
    "coordination/CONTROL_STATE.json: {\"message\":\"API rate limit exceeded for "
    "203.0.113.42. (But here's the good news: Authenticated requests get a higher rate "
    "limit. Check out the documentation for more details.)\",\"documentation_url\":"
    "\"https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting\"}"
)


def serve(fake_github, **settings_overrides):
    settings = Settings(
        repository="krumingo/BEG_Worck", branch="codex/claude-queue", host="127.0.0.1", port=0,
        **settings_overrides,
    )
    client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()
    server = make_server(refresher, settings)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread, refresher, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def narrow_server(fake_github):
    server, thread, refresher, base = serve(fake_github)
    try:
        yield base, refresher, fake_github
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def load(browser, base, width, expand_diagnostics=True):
    page = browser.new_page(viewport={"width": width, "height": 844})
    page.goto(base + "/", wait_until="networkidle")
    page.wait_for_function("document.getElementById('f-task').textContent !== '—'", timeout=10_000)
    if expand_diagnostics:
        # Measure the worst case: every long SHA and URL rendered, nothing collapsed.
        open_diagnostics(page)
    return page


def overflow(page) -> int:
    """Pixels by which the document is wider than the viewport. Must be <= 0."""
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def widest_offender(page) -> str:
    """Name the element that overflows, so a failure says what to fix."""
    return page.evaluate(
        """() => {
          const limit = window.innerWidth;
          let worst = null;
          for (const node of document.querySelectorAll('body *')) {
            const box = node.getBoundingClientRect();
            if (box.right > limit + 1) {
              const over = box.right - limit;
              if (!worst || over > worst.over) {
                worst = {
                  over: Math.round(over),
                  tag: node.tagName.toLowerCase(),
                  cls: node.className && node.className.toString().slice(0, 60),
                  id: node.id,
                  text: (node.textContent || '').trim().slice(0, 60)
                };
              }
            }
          }
          return worst ? JSON.stringify(worst) : 'none';
        }"""
    )


# ---------------------------------------------------------------- the four widths


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_no_horizontal_overflow_at_phone_widths(width, browser, narrow_server):
    base, _, _ = narrow_server
    page = load(browser, base, width)
    assert overflow(page) <= 1, f"{width}px: overflows by {overflow(page)}px — {widest_offender(page)}"
    page.close()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_no_horizontal_overflow_with_a_github_403_error(width, browser, narrow_server):
    """The exact acceptance blocker: a long rate-limit error widened the document."""
    base, refresher, fake_github = narrow_server
    fake_github.fail_everything = TransportError(RATE_LIMIT_403, status=403, retry_after=60.0)
    refresher.tick()

    page = load(browser, base, width)
    # The error really is on the page -- this is not passing by hiding the content.
    assert "rate limit exceeded" in page.inner_text("#f-error")
    assert overflow(page) <= 1, f"{width}px with a 403: overflows by {overflow(page)}px — {widest_offender(page)}"
    if width == 390:
        shoot(page, "mobile-390-github-403")
    page.close()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_no_horizontal_overflow_with_pathological_protocol_text(
    width, browser, fake_github, published_state, mutate
):
    """Unbroken strings with no spaces are the hardest case for wrapping.

    A waiting_for or a summary is free text from the queue; if one ever arrives as a
    single 400-character token the page must still fit the screen.
    """
    monster = "X" * 400
    url = "https://github.com/krumingo/BEG_Worck/" + "verylongpathsegment/" * 20
    fake_github.set_state(
        mutate(
            published_state,
            lambda s: (
                s.__setitem__("waiting_for", monster),
                s["agent_states"]["CODEX"].__setitem__("waiting_for", monster),
                s.__setitem__("requires_krum_reason", monster),
                s.__setitem__("dispatch_run_url", url),
                s["history"][0].__setitem__("summary", monster),
            ),
        )
    )
    server, thread, _, base = serve(fake_github)
    try:
        page = load(browser, base, width)
        assert overflow(page) <= 1, (
            f"{width}px with unbreakable text: overflows by {overflow(page)}px — {widest_offender(page)}"
        )
        page.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_task_table_scrolls_inside_its_wrapper_not_the_page(browser, narrow_server):
    """A seven-column table cannot fit 320 px, so the wrapper scrolls, never the body."""
    base, _, _ = narrow_server
    page = load(browser, base, 320)
    assert overflow(page) <= 1

    wrapper = page.evaluate(
        """() => {
          const w = document.querySelector('.table-wrap');
          return { scrollable: w.scrollWidth > w.clientWidth + 1,
                   overflowX: getComputedStyle(w).overflowX };
        }"""
    )
    assert wrapper["overflowX"] == "auto"
    # The table is genuinely wider than 320 px, so this really is the scrolling case.
    assert wrapper["scrollable"] is True
    page.close()


def test_nothing_is_clipped_off_the_left_edge(browser, narrow_server):
    """Overflow can also be hidden by pushing content off-screen; check both edges."""
    base, _, _ = narrow_server
    page = load(browser, base, 320)
    offenders = page.evaluate(
        """() => Array.from(document.querySelectorAll('body *'))
             .filter(n => n.getBoundingClientRect().left < -1)
             .map(n => n.tagName + '.' + (n.className || '')).slice(0, 5)"""
    )
    assert offenders == []
    page.close()


# ------------------------------------------------------- desktop stays readable


def test_the_desktop_layout_is_unaffected_by_the_wrapping_rules(browser, narrow_server):
    """Breaking anywhere must not turn desktop text into a ragged column."""
    base, _, _ = narrow_server
    page = browser.new_page(viewport=VIEWPORTS["desktop"])
    page.goto(base + "/", wait_until="networkidle")
    page.wait_for_function("document.getElementById('f-task').textContent !== '—'", timeout=10_000)

    assert overflow(page) <= 1
    # The two-column management layout is in effect, not a stacked phone layout.
    boxes = page.evaluate(
        """() => {
          const focus = document.querySelector('.panel--focus').getBoundingClientRect();
          const next = document.querySelector('.panel--next').getBoundingClientRect();
          return { sameRow: Math.abs(focus.y - next.y) < 4, focusWidth: focus.width };
        }"""
    )
    assert boxes["sameRow"] is True, "focus and next-steps should share a row on desktop"
    assert boxes["focusWidth"] > 500

    # Three agent cards abreast.
    rows = page.evaluate(
        "() => new Set(Array.from(document.querySelectorAll('.agent')).map(n => Math.round(n.getBoundingClientRect().y))).size"
    )
    assert rows == 1
    page.close()


def test_the_api_payload_is_unchanged_by_any_of_this(narrow_server):
    """The wrapping fix is presentational; the projection must not have shifted."""
    import urllib.request

    base, _, _ = narrow_server
    with urllib.request.urlopen(base + "/api/state", timeout=5) as reply:
        payload = json.loads(reply.read())
    assert payload["verified"] is True
    assert payload["header"]["task_id"] == "W0-03C"

// R68 evidence — what PostHog sends from a production build.
// Usage: node analytics-check.js <base-url> <out-json> <expect: on|off>
//   off: build without REACT_APP_POSTHOG_KEY → nothing may load.
//   on:  build with a test key and REACT_APP_POSTHOG_HOST=<base>/__posthog; the real
//        posthog-js array.js is served by server.js, every request is logged and decoded.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.argv[2];
const OUT = process.argv[3];
const EXPECT = process.argv[4] || "off";
const REVIEW_TOKEN = "rvTOKEN_9f3Kq2xY7pL0aB4cD8eF";
const RESET_TOKEN = "rsTOKEN_Zz81Qw";
const PROJECT_ID = "p-SECRET-4711";
const SECRETS = ["BG80BNBG96611020345678", "7501010010", "Иван", "Петров", "1234.56", "12345,67", "Test-Passw0rd", REVIEW_TOKEN, RESET_TOKEN, PROJECT_ID];
const res = { expect: EXPECT, checks: [] };
let failed = 0;
const check = (name, ok, detail) => {
  res.checks.push({ name, ok: !!ok, detail });
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
};

(async () => {
  // Test harness only: posthog-js treats navigator.webdriver / the "HeadlessChrome" brand as a
  // bot and sends nothing. Look like a normal browser so the real sending path is exercised.
  const browser = await chromium.launch({ args: ["--disable-blink-features=AutomationControlled"] });
  // posthog-js drops events from "HeadlessChrome" (bot filter): use a normal desktop UA.
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  });
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => false });
    if (navigator.userAgentData) {
      const brands = [{ brand: "Chromium", version: "126" }, { brand: "Google Chrome", version: "126" }];
      Object.defineProperty(navigator, "userAgentData", { get: () => ({ brands, mobile: false, platform: "Linux" }) });
    }
  });
  const external = [];
  // PWA88-N1: every request the browser makes, with its type, to prove no remote script.
  const allRequests = [];
  ctx.on("request", (r) => allRequests.push({ url: r.url(), type: r.resourceType() }));
  await ctx.route((u) => !u.href.startsWith(BASE), (r) => { external.push(r.request().url()); r.abort(); });
  // ── FG-470: the client opens the offer magic link / a reset link ──────────────────
  const review = await ctx.newPage();
  await review.goto(`${BASE}/offers/review/${REVIEW_TOKEN}`);
  await review.waitForTimeout(2500);
  res.review_page = await review.evaluate(() => ({ posthog: !!window.posthog, script: !!document.querySelector('script[data-analytics="posthog"]') }));
  await review.goto(`${BASE}/reset-password?token=${RESET_TOKEN}`);
  await review.waitForTimeout(1500);
  res.reset_page = await review.evaluate(() => ({ posthog: !!window.posthog, script: !!document.querySelector('script[data-analytics="posthog"]') }));
  await review.close();
  // Arriving at the app FROM the review link (referrer carries the token).
  const fromLink = await ctx.newPage();
  await fromLink.goto(`${BASE}/login`, { referer: `${BASE}/offers/review/${REVIEW_TOKEN}` });
  await fromLink.waitForTimeout(2500);
  res.referrer_seen_by_page = await fromLink.evaluate(() => document.referrer);
  await fromLink.close();

  const page = await ctx.newPage();
  await page.goto(`${BASE}/login?iban=BG80BNBG96611020345678#egn=7501010010`);
  // Field content that must never leave the app.
  await page.getByTestId("login-email-input").fill("ivan.petrov.BG80BNBG96611020345678@example.test");
  await page.getByTestId("login-password-input").fill("7501010010");
  await page.getByTestId("login-email-input").click();
  await page.getByText("Забравена парола?").hover();
  await page.getByTestId("login-email-input").fill("a@example.test");
  await page.getByTestId("login-password-input").fill("Test-Passw0rd!");
  await page.getByTestId("login-submit-button").click();
  await page.getByTestId("dashboard-layout").waitFor();
  await page.getByText("Иван Петров").first().click().catch(() => {});
  await page.evaluate(() => setTimeout(() => { throw new TypeError("IBAN BG80BNBG96611020345678 ЕГН 7501010010"); }, 0));
  // An id in the path: a page view on a project URL (the Technician test user would be
  // redirected on a full load, so the SPA route is entered the way the router does it).
  await page.evaluate((id) => {
    window.history.pushState({}, "", `/projects/${id}`);
    if (window.posthog && window.posthog.capture) window.posthog.capture("$pageview");
    window.history.pushState({}, "", "/tech");
  }, PROJECT_ID);
  // SPA navigation onto the review route after analytics is loaded: a page view there is dropped.
  await page.evaluate((t) => {
    window.history.pushState({}, "", `/offers/review/${t}`);
    if (window.posthog && window.posthog.capture) window.posthog.capture("$pageview");
    window.history.pushState({}, "", "/tech");
  }, REVIEW_TOKEN);
  await page.waitForTimeout(4000);
  const state = await page.evaluate(() => {
    const ph = window.posthog;
    if (!ph) return { loaded: false, scriptTag: !!document.querySelector('script[data-analytics="posthog"]') };
    const cfg = ph.config || {};
    return {
      loaded: true,
      real_library: typeof ph.capture === "function" && !!ph.config,
      disable_session_recording: cfg.disable_session_recording,
      autocapture: cfg.autocapture,
      mask_all_text: cfg.mask_all_text,
      recording_started: typeof ph.sessionRecordingStarted === "function" ? ph.sessionRecordingStarted() : null,
    };
  });
  res.client_state = state;
  // Flush the queue before reading the log.
  await page.evaluate(() => window.posthog && window.posthog._flush && window.posthog._flush()).catch(() => {});
  await page.waitForTimeout(1500);
  const log = await (await page.request.get(`${BASE}/__test/posthog-log`)).json();
  res.requests = log.map((r) => ({ method: r.method, path: r.path }));
  const events = [];
  for (const r of log) {
    if (!r.body) continue;
    try {
      const parsed = JSON.parse(r.body);
      const arr = Array.isArray(parsed) ? parsed : parsed.batch || [parsed];
      arr.forEach((e) => e && e.event && events.push({ event: e.event, properties: e.properties }));
    } catch { /* non-JSON body */ }
  }
  res.events = events;
  const everything = JSON.stringify(log) + JSON.stringify(external);
  res.external_requests = external;

  // Scripts may come only from the app's own bundle on its own origin.
  const appScript = (u) => u.startsWith(`${BASE}/static/js/`) || u === `${BASE}/service-worker.js`;
  const foreignScripts = allRequests.filter((r) => r.type === "script" && !appScript(r.url)).map((r) => r.url);
  const phStatic = allRequests.filter((r) => /posthog/i.test(r.url) || /\/__posthog\/(static|.*\.js)/.test(r.url)).filter((r) => r.type === "script" || /\.js(\?|$)/.test(r.url) || /\/static\//.test(r.url)).map((r) => r.url);
  res.script_requests = allRequests.filter((r) => r.type === "script").map((r) => r.url);
  const isPosthogUrl = (u) => /posthog/i.test(u) || u.startsWith(`${BASE}/__posthog/`);
  check("PWA88-N1: no script loaded from any PostHog host", !foreignScripts.some(isPosthogUrl), foreignScripts.filter(isPosthogUrl));
  // Other third-party scripts are pre-existing (index.html, debt D5) — listed, not judged here.
  res.other_third_party_scripts = [...new Set(foreignScripts.filter((u) => !isPosthogUrl(u)))];
  console.log(`INFO  other third-party scripts (pre-existing, D5): ${JSON.stringify(res.other_third_party_scripts)}`);
  check("PWA88-N1: nothing fetched from a PostHog static/CDN path (array.js, recorder, surveys, toolbar)", phStatic.length === 0 && !log.some((r) => /^\/static\//.test(r.path) || /\.js$/.test(r.path)), phStatic);

  if (EXPECT === "off") {
    check("no key: window.posthog absent and no analytics script", !state.loaded && !state.scriptTag, state);
    check("no key: no request to any PostHog host", !external.some((u) => /posthog/.test(u)) && log.length === 0, external.filter((u) => /posthog/.test(u)));
  } else {
    check("bundled posthog-js initialised (no runtime loader)", state.loaded && state.real_library, state);
    check("PWA88-N1: no /decide call (no remote config)", !log.some((r) => /^\/(decide|flags)/.test(r.path)), log.map((r) => r.path));
    check("client: disable_session_recording true", state.disable_session_recording === true);
    check("client: autocapture false, text masked", state.autocapture === false && state.mask_all_text === true);
    check("client: recording not started despite /decide asking for it", state.recording_started !== true, state.recording_started);
    const recordingReq = log.filter((r) => /^\/s\/|^\/ses|recorder|rrweb/.test(r.path));
    check("no recording/snapshot request left the app", recordingReq.length === 0, recordingReq.map((r) => r.path));
    check("events: only $pageview / app_error", events.length > 0 && events.every((e) => ["$pageview", "app_error"].includes(e.event)), [...new Set(events.map((e) => e.event))]);
    check("events: no $snapshot / $autocapture / $exception", !events.some((e) => /\$snapshot|\$autocapture|\$exception|\$rageclick/.test(e.event)));
    const leaked = SECRETS.filter((s) => everything.includes(s));
    check("no field content (ЕГН / IBAN / amounts / names / password) in any request", leaked.length === 0, leaked);
    check("FG-470: review link page loads no analytics", res.review_page && !res.review_page.posthog && !res.review_page.script, res.review_page);
    check("FG-470: reset-password page loads no analytics", res.reset_page && !res.reset_page.posthog && !res.reset_page.script, res.reset_page);
    check("FG-470: review token in no request (page, referrer, SPA, decide, cookies)", !everything.includes(REVIEW_TOKEN), res.referrer_seen_by_page ? "referrer was set" : "referrer not set");
    check("FG-470: reset token / project id in no request", !everything.includes(RESET_TOKEN) && !everything.includes(PROJECT_ID));
    const paths = events.map((e) => e.properties && e.properties.$pathname).filter(Boolean);
    check("FG-470: only route templates are sent", paths.length > 0 && paths.every((p) => /^\/[a-z\-/:A-Za-z]*$/.test(p)) && paths.includes("/projects/:projectId"), [...new Set(paths)]);
    const urls = events.map((e) => e.properties && e.properties.$current_url).filter(Boolean);
    check("page URLs carry no query string or hash", urls.every((u) => !/[?#]/.test(u)), urls);
    const errs = events.filter((e) => e.event === "app_error");
    check("app_error carries only error_kind", errs.every((e) => Object.keys(e.properties || {}).every((k) => !/message|stack|exception/i.test(k))), errs.map((e) => e.properties && e.properties.error_kind));
  }
  await browser.close();
  res.summary = { passed: res.checks.filter((c) => c.ok).length, failed };
  fs.writeFileSync(OUT, JSON.stringify(res, null, 2) + "\n");
  console.log(`\n${res.summary.passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

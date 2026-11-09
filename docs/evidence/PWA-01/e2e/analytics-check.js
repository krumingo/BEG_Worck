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
const SECRETS = ["BG80BNBG96611020345678", "7501010010", "Иван", "Петров", "1234.56", "12345,67", "Test-Passw0rd"];
const res = { expect: EXPECT, checks: [] };
let failed = 0;
const check = (name, ok, detail) => {
  res.checks.push({ name, ok: !!ok, detail });
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
};

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const external = [];
  await ctx.route((u) => !u.href.startsWith(BASE), (r) => { external.push(r.request().url()); r.abort(); });
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

  if (EXPECT === "off") {
    check("no key: window.posthog absent and no analytics script", !state.loaded && !state.scriptTag, state);
    check("no key: no request to any PostHog host", !external.some((u) => /posthog/.test(u)) && log.length === 0, external.filter((u) => /posthog/.test(u)));
  } else {
    check("real posthog-js loaded from the local test host", state.loaded && state.real_library, state);
    check("client: disable_session_recording true", state.disable_session_recording === true);
    check("client: autocapture false, text masked", state.autocapture === false && state.mask_all_text === true);
    check("client: recording not started despite /decide asking for it", state.recording_started !== true, state.recording_started);
    const recordingReq = log.filter((r) => /^\/s\/|^\/ses|recorder|rrweb/.test(r.path));
    check("no recording/snapshot request left the app", recordingReq.length === 0, recordingReq.map((r) => r.path));
    check("events: only $pageview / app_error", events.length > 0 && events.every((e) => ["$pageview", "app_error"].includes(e.event)), [...new Set(events.map((e) => e.event))]);
    check("events: no $snapshot / $autocapture / $exception", !events.some((e) => /\$snapshot|\$autocapture|\$exception|\$rageclick/.test(e.event)));
    const leaked = SECRETS.filter((s) => everything.includes(s));
    check("no field content (ЕГН / IBAN / amounts / names / password) in any request", leaked.length === 0, leaked);
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

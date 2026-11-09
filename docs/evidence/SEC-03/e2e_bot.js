// SEC-03 e2e bot — the production build behind the repository's own nginx.conf.
//
//   node e2e_bot.js <app_url> <seed.json> <out_dir>
//
// Records EVERY request the browser makes, every CSP violation and console error,
// while an Owner logs in through the UI and opens a set of screens; then checks:
//   * no request to any host other than the app origin and Google Fonts (none to emergent.sh,
//     cdn.tailwindcss.com, posthog);
//   * the document carries CSP (script-src 'self', frame-ancestors 'none'), X-Frame-Options DENY,
//     nosniff, Referrer-Policy;
//   * the app can NOT be framed by another origin;
//   * photo AI -> 503 "... изисква файлов регистър ..." (FG-522; never 500); AI settings: off, Owner-only switch;
//   * /api/internal/run-reminder-jobs: no credentials -> 401, tenant Owner -> 403.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("playwright");

const [APP, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "SEC03-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const appOrigin = new URL(APP).origin;
// ANALYTICS=1: the build was made with REACT_APP_POSTHOG_KEY (#88 / R68), so the bundled
// posthog-js may talk to its host — which the build-templated CSP must then allow.
const ANALYTICS_HOST = process.env.ANALYTICS === "1" ? (process.env.ANALYTICS_HOST || "us.i.posthog.com") : null;
const ALLOWED_THIRD_PARTY = new Set(["fonts.googleapis.com", "fonts.gstatic.com", ...(ANALYTICS_HOST ? [ANALYTICS_HOST] : [])]);
const results = { started_at: new Date().toISOString(), app: APP, steps: [], requests: [], csp_violations: [], console_errors: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  // ANALYTICS run: posthog-js treats navigator.webdriver as a bot and sends nothing; this
  // flag (with the normal UA below) makes it behave as for a person, so the CSP is tested.
  const browser = await chromium.launch(ANALYTICS_HOST ? { args: ["--disable-blink-features=AutomationControlled"] } : {});
  // ANALYTICS run: posthog-js drops events from "HeadlessChrome" user agents (bot filter),
  // so a normal desktop UA is used to make it really send — through the CSP under test.
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 },
    ...(ANALYTICS_HOST ? { userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" } : {}) });
  ctx.on("request", (r) => results.requests.push({ url: r.url(), type: r.resourceType() }));
  if (ANALYTICS_HOST) {
    // posthog-js also treats userAgentData brands ("HeadlessChrome") as a bot.
    await ctx.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "userAgentData", { get: () => undefined });
    });
  }
  await ctx.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window.__csp = window.__csp || []).push({ directive: e.violatedDirective, blocked: e.blockedURI, sample: e.sample });
    });
  });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") results.console_errors.push(m.text().slice(0, 300)); });

  // headers of the document
  const resp = await page.goto(`${APP}/login`);
  const h = resp.headers();
  const csp = h["content-security-policy"] || "";
  check("document CSP: script-src 'self' only", /script-src 'self';/.test(csp), csp);
  check("document CSP: frame-ancestors 'none'", /frame-ancestors 'none'/.test(csp), csp);
  check("X-Frame-Options DENY", h["x-frame-options"] === "DENY", h["x-frame-options"]);
  check("X-Content-Type-Options nosniff", h["x-content-type-options"] === "nosniff", h["x-content-type-options"]);
  check("Referrer-Policy", h["referrer-policy"] === "strict-origin-when-cross-origin", h["referrer-policy"]);
  check("title is BEG_Work", (await page.title()) === "BEG_Work", await page.title());
  check("no Emergent badge in the DOM", (await page.locator("#emergent-badge").count()) === 0, null);
  await page.screenshot({ path: path.join(OUT, "01_login.png") });

  // login through the UI
  await page.getByTestId("login-email-input").fill(seed.owner_email);
  await page.getByTestId("login-password-input").fill(PASSWORD);
  await page.getByTestId("login-submit-button").click();
  await page.waitForFunction(() => !!localStorage.getItem("bw_token"), null, { timeout: 30000 });
  await page.waitForLoadState("networkidle");
  check("login works under the CSP", true, page.url());
  await page.screenshot({ path: path.join(OUT, "02_after_login.png") });

  const screens = ["/projects", "/employees", "/pay-runs", "/offers", "/assets/items", "/finance", "/settings"];
  for (const s of screens) {
    await page.goto(`${APP}${s}`);
    await page.waitForLoadState("networkidle");
    const rootChildren = await page.evaluate(() => document.getElementById("root").children.length);
    check(`screen ${s} renders`, rootChildren > 0, rootChildren);
  }
  await page.screenshot({ path: path.join(OUT, "03_assets_items.png") });

  // API checks from the logged-in session
  const api = await page.evaluate(async () => {
    const t = localStorage.getItem("bw_token");
    const ai = await fetch("/api/assets/ai-intake", { method: "POST",
      headers: { Authorization: "Bearer " + t, "Content-Type": "application/json" },
      body: JSON.stringify({ image_base64: "/9j/" + "A".repeat(300) }) });
    const settings = await fetch("/api/ai/settings", { headers: { Authorization: "Bearer " + t } });
    const put = (v, key, reason) => fetch("/api/ai/settings", { method: "PUT",
      headers: { Authorization: "Bearer " + t, "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
      body: JSON.stringify(reason ? { enabled: v, reason } : { enabled: v }) });
    const nokey = await put(true, null, "e2e"); const noreason = await put(true, "e2e-k0", null);
    const run = Math.random().toString(36).slice(2);
    const on = await put(true, "e2e-on-" + run, "SEC-03 e2e"); const off = await put(false, "e2e-off-" + run, "SEC-03 e2e");
    const anon = await fetch("/api/internal/run-reminder-jobs?all_tenants=true", { method: "POST" });
    const owner = await fetch("/api/internal/run-reminder-jobs?all_tenants=true", { method: "POST",
      headers: { Authorization: "Bearer " + t } });
    return { ai: [ai.status, (await ai.json()).detail], settings: await settings.json(), owner_switch: [on.status, off.status], switch_guards: [nokey.status, noreason.status], anon: anon.status, owner: owner.status };
  });
  check("photo AI -> 503 'изисква файлов регистър' (FG-522)", api.ai[0] === 503 && /изисква файлов регистър/.test(api.ai[1]), api.ai);
  check("AI is off for the tenant by default", api.settings.enabled === false, api.settings);
  check("the Owner switches AI on and off (FG-519)", api.owner_switch[0] === 200 && api.owner_switch[1] === 200, api.owner_switch);
  check("the switch needs an Idempotency-Key (428) and a reason (422) (FG-538)",
    api.switch_guards[0] === 428 && api.switch_guards[1] === 422, api.switch_guards);
  check("reminder trigger without credentials -> 401", api.anon === 401, api.anon);
  check("reminder trigger as tenant Owner -> 403", api.owner === 403, api.owner);
  results.csp_violations = await page.evaluate(() => window.__csp || []);

  // framing from another origin
  const framer = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<html><body><iframe id="f" src="${APP}/login" width="800" height="600"></iframe></body></html>`);
  }).listen(0, "127.0.0.1");
  await new Promise((r) => framer.on("listening", r));
  const fpage = await ctx.newPage();
  await fpage.goto(`http://localhost:${framer.address().port}/`);
  await fpage.waitForTimeout(3000);
  const child = fpage.frames().find((f) => f !== fpage.mainFrame());
  let framedRendered = false;
  try { framedRendered = !!(child && (await child.evaluate(() => !!document.getElementById("root")))); } catch (e) { framedRendered = false; }
  check("the app cannot be framed by another origin", !framedRendered, { child_url: child && child.url() });
  await fpage.screenshot({ path: path.join(OUT, "04_framing_blocked.png") });
  framer.close();

  // the request log
  const hosts = {};
  for (const r of results.requests) {
    let u; try { u = new URL(r.url); } catch (e) { continue; }
    if (!/^https?:$/.test(u.protocol)) continue;
    hosts[u.host] = (hosts[u.host] || 0) + 1;
  }
  results.hosts = hosts;
  const foreign = Object.keys(hosts).filter((host) => {
    const origin = `http://${host}`;
    return origin !== appOrigin && !ALLOWED_THIRD_PARTY.has(host) && !host.startsWith("localhost:");
  });
  check("no request to any third-party host (except Google Fonts)", foreign.length === 0, { hosts });
  check("no request to emergent.sh", !results.requests.some((r) => /emergent\.sh|emergentagent/.test(r.url)), null);
  check("no request to cdn.tailwindcss.com", !results.requests.some((r) => /tailwindcss\.com/.test(r.url)), null);
  check("no request to any PostHog ASSET host (no remote script, #88 no-external build)",
    !results.requests.some((r) => /assets\.i\.posthog\.com/.test(r.url)), null);
  if (ANALYTICS_HOST) {
    check("analytics on: the bundled posthog-js really sent to " + ANALYTICS_HOST + " (allowed by the CSP)",
      results.requests.some((r) => new URL(r.url).host === ANALYTICS_HOST), null);
  }
  if (!ANALYTICS_HOST) {
    check("no analytics key -> no request to PostHog", !results.requests.some((r) => /posthog/.test(r.url)), null);
  }
  check("NO CSP violation at all (FG-539: analytics allowed by the templated CSP when configured)",
    results.csp_violations.length === 0, results.csp_violations);
  const cspConsole = results.console_errors.filter((t) => /Content Security Policy/i.test(t));
  check("no CSP violation reported on ANY page (console)", cspConsole.length === 0, cspConsole.slice(0, 3));
  check("every script came from the app origin", results.requests.filter((r) => r.type === "script")
    .every((r) => new URL(r.url).origin === appOrigin || new URL(r.url).host.startsWith("localhost:")),
  results.requests.filter((r) => r.type === "script").map((r) => r.url));

  results.finished_at = new Date().toISOString();
  results.request_count = results.requests.length;
  fs.writeFileSync(path.join(OUT, "bot_result.json"), JSON.stringify(results, null, 1));
  await browser.close();
  console.log(failed ? "BOT FAILED" : "BOT PASSED");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

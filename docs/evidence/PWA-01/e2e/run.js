// PWA-01 evidence — Playwright (pre-installed Chromium) against a production build.
// Usage: node run.js <base-url> <out-dir>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.argv[2] || "http://localhost:4173";
const OUT = path.resolve(process.argv[3] || ".");
const results = { base: BASE, checks: [], cache_snapshots: {} };
let failed = 0;

function check(name, ok, detail) {
  results.checks.push({ name, ok: !!ok, ...(detail === undefined ? {} : { detail }) });
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
}

const PHONE_ANDROID = {
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
};
const PHONE_IOS = {
  ...PHONE_ANDROID,
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
};
const DESKTOP = { viewport: { width: 1366, height: 820 }, deviceScaleFactor: 2 };

async function newContext(browser, opts) {
  const ctx = await browser.newContext({ ...opts, locale: "bg-BG", serviceWorkers: "allow" });
  // Third-party scripts in index.html (analytics, fonts) are not part of the shell.
  await ctx.route((url) => !url.href.startsWith(BASE), (route) => route.abort());
  return ctx;
}

async function swReady(page) {
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  if (!(await page.evaluate(() => !!navigator.serviceWorker.controller))) {
    await page.reload();
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  }
}

const cacheSnapshot = (page) =>
  page.evaluate(async () => {
    const out = {};
    for (const name of await caches.keys()) {
      const c = await caches.open(name);
      out[name] = (await c.keys()).map((r) => new URL(r.url).pathname);
    }
    return out;
  });

const apiInCaches = (snap) => Object.values(snap).flat().filter((p) => /^\/(api|uploads|ws)(\/|$)/.test(p));

async function login(page, email) {
  await page.goto(`${BASE}/login`);
  await page.getByTestId("login-email-input").fill(email);
  await page.getByTestId("login-password-input").fill("Test-Passw0rd!");
  await page.getByTestId("login-submit-button").click();
  await page.getByTestId("dashboard-layout").waitFor();
}

const shot = (page, name) => page.screenshot({ path: path.join(OUT, name) });

(async () => {
  const browser = await chromium.launch();

  // ── Desktop ───────────────────────────────────────────────────────────────
  const desk = await newContext(browser, DESKTOP);
  const page = await desk.newPage();
  await page.goto(`${BASE}/login`);

  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href");
  check("index.html links the manifest", manifestHref === "/manifest.webmanifest", manifestHref);
  const manifest = await (await page.request.get(`${BASE}${manifestHref}`)).json();
  results.manifest = manifest;
  check("manifest: name/short_name/start_url/scope/display/lang",
    manifest.name === "BEG_Work" && manifest.short_name && manifest.start_url === "/" && manifest.scope === "/" && manifest.display === "standalone" && manifest.lang === "bg");
  const sizes = manifest.icons.map((i) => `${i.sizes}:${i.purpose}`);
  check("manifest: 192/512 any + maskable icons", ["192x192:any", "512x512:any", "192x192:maskable", "512x512:maskable"].every((s) => sizes.includes(s)), sizes);
  for (const icon of [...manifest.icons.map((i) => i.src), "/icons/apple-touch-icon.png"]) {
    const r = await page.request.get(`${BASE}${icon}`);
    check(`icon ${icon} served`, r.ok() && r.headers()["content-type"] === "image/png", r.status());
  }
  check("apple-touch-icon + apple meta tags", (await page.locator('link[rel="apple-touch-icon"]').count()) === 1 && (await page.getAttribute('meta[name="apple-mobile-web-app-capable"]', "content")) === "yes");

  await swReady(page);
  const sw = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    const version = await new Promise((resolve) => {
      const ch = new MessageChannel();
      ch.port1.onmessage = (e) => resolve(e.data);
      navigator.serviceWorker.controller.postMessage({ type: "GET_VERSION" }, [ch.port2]);
    });
    return { scope: reg.scope, active: reg.active && reg.active.state, scriptURL: reg.active && reg.active.scriptURL, version };
  });
  results.service_worker = sw;
  check("service worker active, scope /", sw.active === "activated" && sw.scope === `${BASE}/`, sw);
  check("SW version = RC-01 build identity", /^bw-shell-[0-9a-f]{12}-/.test(sw.version.cache) && /^[0-9a-f]{40}$/.test(sw.version.build_sha), sw.version);

  const cdp = await desk.newCDPSession(page);
  const inst = await cdp.send("Page.getInstallabilityErrors");
  results.installability_errors = inst.installabilityErrors;
  check("Chromium installability: no errors", inst.installabilityErrors.length === 0, inst.installabilityErrors);

  await shot(page, "desktop-login.png");
  await login(page, "a@example.test");
  // Touch API + uploads while online so there is something the SW could have stored.
  await page.evaluate(async () => {
    const h = { Authorization: `Bearer ${localStorage.getItem("bw_token")}` };
    await fetch("/api/payments", { headers: h });
    await fetch("/api/auth/me", { headers: h });
    await fetch("/uploads/photo-1.png");
  });
  await page.waitForTimeout(500);
  // Desktop: the install button appears once the browser offers the prompt. Headless
  // Chromium never fires beforeinstallprompt, so the event is dispatched the same way.
  await page.evaluate(() => {
    const e = new Event("beforeinstallprompt", { cancelable: true });
    e.prompt = () => {};
    e.userChoice = Promise.resolve({ outcome: "dismissed" });
    window.dispatchEvent(e);
  });
  check("desktop: install button in the sidebar", await page.getByTestId("pwa-install-sidebar").isVisible());
  await shot(page, "desktop-dashboard.png");

  let snap = await cacheSnapshot(page);
  results.cache_snapshots.after_login_online = snap;
  check("Cache Storage: only the app-shell cache exists", Object.keys(snap).length === 1 && Object.keys(snap)[0].startsWith("bw-shell-"), Object.keys(snap));
  check("Cache Storage: no /api, /uploads or /ws entry", apiInCaches(snap).length === 0, apiInCaches(snap));
  check("Cache Storage: shell has index.html + js + css", ["/index.html"].every((u) => Object.values(snap)[0].includes(u)) && Object.values(snap)[0].some((u) => /^\/static\/js\/main\..*\.js$/.test(u)) && Object.values(snap)[0].some((u) => /^\/static\/css\/main\..*\.css$/.test(u)));

  // ── Offline ───────────────────────────────────────────────────────────────
  await desk.setOffline(true);
  await page.reload();
  await page.getByTestId("pwa-offline-banner").waitFor({ timeout: 10000 });
  const offlineText = await page.getByTestId("pwa-offline-banner").innerText();
  check("offline: shell opens from cache", (await page.locator("#root").count()) === 1 && (await page.title()) === "BEG_Work");
  check("offline: Без връзка bar visible", offlineText.includes("Без връзка"), offlineText);
  const apiOffline = await page.evaluate(async () => {
    try { await fetch("/api/payments"); return "answered"; } catch (e) { return "network-error"; }
  });
  check("offline: /api is not answered from any cache", apiOffline === "network-error", apiOffline);
  const deepNav = await desk.newPage();
  await deepNav.goto(`${BASE}/tech/tools`);
  check("offline: deep link navigation falls back to the shell", (await deepNav.locator("#root").count()) === 1);
  await deepNav.close();
  await page.waitForTimeout(800);
  await shot(page, "desktop-offline.png");
  await desk.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));

  // D1 (fixed): an offline reload keeps the session — the user stays inside the shell.
  const keptToken = await page.evaluate(() => localStorage.getItem("bw_token"));
  results.d1_offline_reload_token = keptToken ? "kept" : "dropped";
  check("D1 offline reload: token kept", !!keptToken, results.d1_offline_reload_token);
  check("D1 offline reload: still inside the shell (dashboard layout, no login page)",
    (await page.getByTestId("dashboard-layout").count()) === 1 && (await page.getByTestId("login-page").count()) === 0);

  // ── Logout clears local data ─────────────────────────────────────────────
  await page.goto(`${BASE}/tech`);
  await page.getByTestId("dashboard-layout").waitFor();
  await page.evaluate(async () => {
    localStorage.setItem("tenant_a_draft", "{\"note\":\"чернова\"}");
    sessionStorage.setItem("tenant_a_session", "x");
    const c = await caches.open("bw-legacy-api");
    await c.put("/api/legacy-left-over", new Response("{}"));
  });
  await page.getByTestId("logout-button").click();
  await page.getByTestId("login-page").waitFor();
  await page.waitForTimeout(300);
  const afterLogout = await page.evaluate(() => ({ local: Object.keys(localStorage).sort(), session: Object.keys(sessionStorage) }));
  snap = await cacheSnapshot(page);
  results.after_logout = { ...afterLogout, caches: Object.keys(snap) };
  results.cache_snapshots.after_logout = snap;
  check("logout: no token / user / tenant marker / tenant draft in localStorage",
    !afterLogout.local.some((k) => ["bw_token", "bw_user", "bw_pwa_tenant", "tenant_a_draft"].includes(k)), afterLogout.local);
  check("logout: sessionStorage empty", afterLogout.session.length === 0, afterLogout.session);
  check("logout: only the app-shell cache remains", Object.keys(snap).every((n) => n.startsWith("bw-shell-")) && apiInCaches(snap).length === 0, Object.keys(snap));

  // ── Tenant switch clears the previous tenant's data ──────────────────────
  await login(page, "a@example.test");
  await page.evaluate(async () => {
    localStorage.setItem("tenant_a_draft", "x");
    sessionStorage.setItem("tenant_a_session", "x");
    await (await caches.open("bw-legacy-api")).put("/api/legacy-left-over", new Response("{}"));
    // The active session now belongs to tenant B (another company's login on this device).
    localStorage.setItem("bw_token", "token-org-b");
  });
  await page.reload();
  await page.getByTestId("dashboard-layout").waitFor();
  await page.waitForTimeout(300);
  const afterSwitch = await page.evaluate(() => ({ local: Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])), session: Object.keys(sessionStorage) }));
  snap = await cacheSnapshot(page);
  results.after_tenant_switch = { local_keys: Object.keys(afterSwitch.local).sort(), session: afterSwitch.session, caches: Object.keys(snap) };
  check("tenant switch: tenant A draft + session storage cleared", !("tenant_a_draft" in afterSwitch.local) && afterSwitch.session.length === 0);
  check("tenant switch: tenant B login kept, marker = org-b", afterSwitch.local.bw_token === "token-org-b" && afterSwitch.local.bw_pwa_tenant === "org-b");
  check("tenant switch: only the app-shell cache remains", Object.keys(snap).every((n) => n.startsWith("bw-shell-")), Object.keys(snap));

  // ── Update prompt ────────────────────────────────────────────────────────
  await page.request.get(`${BASE}/__test/bump-sw`);
  await page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration(); await r.update(); });
  await page.getByTestId("pwa-update-banner").waitFor({ timeout: 15000 });
  check("update: Има нова версия bar shown, page not reloaded silently", await page.getByTestId("pwa-update-banner").isVisible());
  await shot(page, "desktop-update-available.png");
  const before = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL && performance.timeOrigin);
  await Promise.all([page.waitForEvent("load", { timeout: 15000 }), page.getByTestId("pwa-update-apply").click()]);
  const after = await page.evaluate(() => performance.timeOrigin);
  check("update: Обнови activates the new worker and reloads once", after !== before);
  await desk.close();

  // ── Phone (Android) ──────────────────────────────────────────────────────
  const phone = await newContext(browser, PHONE_ANDROID);
  const p2 = await phone.newPage();
  await p2.goto(`${BASE}/login`);
  await swReady(p2);
  await shot(p2, "phone-login.png");
  await login(p2, "a@example.test");
  await shot(p2, "phone-dashboard.png");
  await p2.evaluate(() => {
    const e = new Event("beforeinstallprompt", { cancelable: true });
    e.prompt = () => {};
    e.userChoice = Promise.resolve({ outcome: "dismissed" });
    window.dispatchEvent(e);
  });
  await p2.getByTestId("mobile-menu-toggle").click();
  await p2.getByTestId("pwa-install-menu").waitFor();
  check("phone: install button in the menu", await p2.getByTestId("pwa-install-menu").isVisible());
  await p2.waitForTimeout(800);
  await shot(p2, "phone-menu-install.png");
  await p2.keyboard.press("Escape");
  await phone.setOffline(true);
  await p2.reload();
  await p2.getByTestId("pwa-offline-banner").waitFor({ timeout: 10000 });
  check("phone offline: shell + Без връзка bar", await p2.getByTestId("pwa-offline-banner").isVisible());
  check("D1 phone offline reload: still inside the shell", (await p2.getByTestId("dashboard-layout").count()) === 1);
  await p2.waitForTimeout(800);
  await shot(p2, "phone-offline.png");
  snap = await cacheSnapshot(p2);
  results.cache_snapshots.phone_offline = snap;
  check("phone: no /api, /uploads or /ws entry in Cache Storage", apiInCaches(snap).length === 0);
  await phone.close();

  // ── Phone (iOS Safari user agent): install instructions ──────────────────
  const ios = await newContext(browser, PHONE_IOS);
  const p3 = await ios.newPage();
  await login(p3, "a@example.test");
  await p3.getByTestId("mobile-menu-toggle").click();
  await p3.getByTestId("pwa-install-menu").click();
  await p3.getByTestId("pwa-ios-steps").waitFor();
  const steps = await p3.getByTestId("pwa-ios-steps").innerText();
  check("iOS: Сподели → Добави към началния екран steps", steps.includes("Сподели") && steps.includes("Добави към началния екран"));
  await p3.waitForTimeout(500);
  await shot(p3, "phone-ios-install-steps.png");
  await ios.close();

  await browser.close();
  results.summary = { passed: results.checks.filter((c) => c.ok).length, failed };
  fs.writeFileSync(path.join(OUT, "cache-check.json"), JSON.stringify(results, null, 2) + "\n");
  console.log(`\n${results.summary.passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

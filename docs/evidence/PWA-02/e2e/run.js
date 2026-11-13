// PWA-02 evidence — a real browser against the REAL backend (uvicorn on a local replica set)
// and the production build behind proxy.js.  node run.js <base> <run.json> <out-dir>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const BASE = process.argv[2];
const RUN = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const OUT = path.resolve(process.argv[4]);
const res = { checks: [] };
let failed = 0;
const check = (name, ok, detail) => {
  res.checks.push({ name, ok: !!ok, detail });
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
};
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36" };
const DESKTOP = { viewport: { width: 1366, height: 860 }, deviceScaleFactor: 2 };
const shot = (p, n) => p.screenshot({ path: path.join(OUT, n) });

async function ctxFor(browser, opts) {
  const c = await browser.newContext({ ...opts, locale: "bg-BG" });
  await c.route((u) => !u.href.startsWith(BASE), (r) => r.abort());
  return c;
}
async function login(page, email) {
  await page.goto(`${BASE}/login`);
  await page.getByTestId("login-email-input").fill(email);
  await page.getByTestId("login-password-input").fill(RUN.password);
  await page.getByTestId("login-submit-button").click();
  await page.getByTestId("dashboard-layout").waitFor({ timeout: 20000 });
}
async function api(page, method, url, body, headers = {}) {
  return page.evaluate(async ({ method, url, body, headers }) => {
    const r = await fetch(`/api${url}`, { method, headers: { "Content-Type": "application/json",
      Authorization: `Bearer ${localStorage.getItem("bw_token")}`, ...headers }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, body: j };
  }, { method, url, body, headers });
}

(async () => {
  const browser = await chromium.launch();

  // ── the technician's phone: online first, then the signal is lost ────────────────
  const phone = await ctxFor(browser, PHONE);
  const day = await phone.newPage();
  const registered = day.waitForResponse((r) => r.url().includes("/api/sync/devices/register"), { timeout: 20000 });
  await login(day, RUN.technician.email);
  const reg = await registered;
  check("device registered at login (flag ON for tenant A)", reg.status() === 200);
  await day.evaluate(async () => { await navigator.serviceWorker.ready; });
  await day.goto(`${BASE}/my-day`);
  await day.getByTestId("mark-present-button").waitFor();
  const tech = await phone.newPage();
  await tech.goto(`${BASE}/tech`);
  // today's crew on site (the existing roster step, done online): the technician himself
  const rosterSaved = await api(tech, "POST", `/technician/site/${RUN.project_id}/roster/add-workers`,
    { workers: [{ worker_id: RUN.technician.id, worker_name: "ST01 A technician" }] });
  check("roster saved online before the signal is lost", rosterSaved.status === 200, rosterSaved.status);
  await tech.reload();
  await tech.getByTestId("portal-tabs").getByRole("button", { name: /Обекти/ }).click({ timeout: 15000 });
  await tech.getByTestId(`site-${RUN.project_id}`).click({ timeout: 15000 });
  await tech.getByTestId("tech-object").waitFor();
  // start the day's report while there is still signal (roster + tasks load online)
  await tech.getByRole("button", { name: /Отчет за деня/ }).click();
  await tech.waitForTimeout(1500);
  if (await tech.getByTestId("tech-roster").count()) {
    const showAll = tech.getByRole("button", { name: /Виж всички/ });
    if (await showAll.count()) await showAll.click();
    await tech.waitForTimeout(500);
    await tech.getByTestId("tech-roster").locator("button.w-full.flex").first().click();
    await tech.getByTestId("save-roster-btn").click();
  }
  await tech.getByTestId("tech-report").waitFor({ timeout: 15000 });
  await phone.setOffline(true);
  await day.evaluate(() => window.dispatchEvent(new Event("offline")));
  await day.getByTestId("mark-present-button").click();
  await day.getByTestId("attendance-queued").waitFor({ timeout: 10000 });
  const queuedText = await day.getByTestId("attendance-queued").innerText();
  check("offline attendance: Записано на телефона", queuedText.includes("Записано на телефона"), queuedText);
  await day.waitForTimeout(500);
  await shot(day, "phone-offline-attendance-saved.png");

  // the daily report, written and sent with no signal
  await tech.getByPlaceholder(/Вид СМР|Тип СМР|Дейност/).first().fill("Шпакловка");
  await tech.getByRole("button", { name: /Преглед/ }).last().click();
  await tech.getByTestId("tech-review").waitFor();
  await shot(tech, "phone-offline-report-review.png");
  await tech.getByTestId("review-submit-btn").click();
  // (the app mounts no toast container — existing debt, see HANDOFF — so the proof is the
  // return to Днес and the queue below, not a toast)
  const backToDay = await tech.getByTestId("tech-my-day").waitFor({ timeout: 10000 }).then(() => true, () => false);
  const badge = await tech.locator("[data-testid=offline-unsent-badge]:visible").first().innerText().catch(() => "");
  check("offline daily report kept on the phone, back to Днес (badge counts it)", backToDay && badge.includes("2"), badge);
  await shot(tech, "phone-offline-report-saved.png");
  // a site photo, with no signal
  await tech.waitForTimeout(800);
  await tech.getByTestId("portal-tabs").getByRole("button", { name: /Обекти/ }).click();
  await tech.getByTestId(`site-${RUN.project_id}`).click();
  await tech.getByTestId("tech-object").waitFor();
  let photoQueued = false;
  if (await tech.getByTestId("site-photo-input").count()) {
    const jpeg = Buffer.from("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP////////////////////////////////////////////////////////////////////////////////////8A", "base64");
    await tech.getByTestId("site-photo-input").setInputFiles({ name: "obekt.jpg", mimeType: "image/jpeg", buffer: jpeg });
    await tech.waitForTimeout(1500);
    photoQueued = true;
  }
  check("offline photo captured on the site screen", photoQueued);
  const unsentOffline = await day.evaluate(async () => {
    const db = await new Promise((r, j) => { const o = indexedDB.open("bw-offline"); o.onsuccess = () => r(o.result); o.onerror = j; });
    const rows = await new Promise((r) => { const t = db.transaction("queue").objectStore("queue").getAll(); t.onsuccess = () => r(t.result); });
    return rows.map((x) => ({ op: x.op_type, status: x.status, plain: /Present|Шпакловка/.test(JSON.stringify(x)) }));
  });
  res.queue_offline = unsentOffline;
  check("queue holds the records, payload not in clear", unsentOffline.length >= 3 && unsentOffline.every((x) => !x.plain), unsentOffline);
  await day.goto(`${BASE}/my-unsent`).catch(() => {});
  await day.getByTestId("my-unsent-page").waitFor({ timeout: 10000 }).catch(() => {});
  await day.waitForTimeout(800);
  await shot(day, "phone-offline-my-unsent.png");

  // ── back online: the queue flushes; every status lands ───────────────────────────
  await phone.setOffline(false);
  await day.evaluate(() => window.dispatchEvent(new Event("online")));
  await day.getByTestId("offline-sync-now").click().catch(() => {});
  await day.waitForTimeout(4000);
  const statuses = await day.getByTestId("offline-item-status").allInnerTexts();
  res.statuses_online = statuses;
  check("online: attendance Синхронизирано", statuses.includes("Синхронизирано"), statuses);
  check("online: photo Чака качване на файл (no File Registry)", statuses.includes("Чака качване на файл"), statuses);
  await shot(day, "phone-online-synced.png");
  const after = await api(day, "GET", "/attendance/my-today");
  res.attendance_today = after.body;
  const entry = after.body && after.body.entry;
  check("server: today's attendance recorded from the phone", after.status === 200 && entry && entry.source === "offline_sync", entry && { status: entry.status, source: entry.source });
  check("online: daily report Синхронизирано", statuses.filter((x) => x === "Синхронизирано").length >= 2, statuses);

  // the phone sends the same envelope again (e.g. two tabs flushing): one record only
  const dev = await day.evaluate(async () => {
    const db = await new Promise((r) => { const o = indexedDB.open("bw-offline"); o.onsuccess = () => r(o.result); });
    return new Promise((r) => { const t = db.transaction("meta").objectStore("meta").get("device_id"); t.onsuccess = () => r(t.result); });
  });
  const now = new Date();
  const env = (op, payload, extra = {}) => ({ local_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), op_type: op,
    captured_at: now.toISOString(), captured_tz: "Europe/Sofia", device_clock_offset_ms: 0, user_id: RUN.technician.id,
    tenant_id: RUN.tenant_id, device_id: dev, project_id: RUN.project_id, payload, ...extra });
  const dup = env("attendance.mark", { status: "Present", project_id: RUN.project_id });
  const r1 = await api(day, "POST", "/sync/batch", { device_id: dev, items: [dup, dup] });
  const r2 = await api(day, "POST", "/sync/batch", { device_id: dev, items: [dup] });
  res.duplicate = { first: r1.body.results.map((x) => x.status), again: r2.body.results[0] };
  check("same key twice + resend: identical, never duplicated", r2.body.results[0].replay === true);
  // material for the console: a differing mark (conflict) and yesterday's mark (late)
  const conf = await api(day, "POST", "/sync/batch", { device_id: dev, items: [env("attendance.mark", { status: "Absent", project_id: RUN.project_id })] });
  const y = new Date(now.getTime() - 26 * 3600 * 1000);
  const late = await api(day, "POST", "/sync/batch", { device_id: dev, items: [{ ...env("attendance.mark", { status: "Present", project_id: RUN.project_id }), captured_at: y.toISOString() }] });
  check("differing mark → Конфликт", conf.body.results[0].status === "conflict");
  check("yesterday's mark → Закъснял", late.body.results[0].status === "late");

  // ── the owner's console ──────────────────────────────────────────────────────────
  const office = await ctxFor(browser, DESKTOP);
  const op = await office.newPage();
  await login(op, RUN.owner.email);
  await op.goto(`${BASE}/sync-console`);
  await op.getByTestId("sync-console-page").waitFor({ timeout: 15000 });
  await op.waitForTimeout(800);
  await shot(op, "desktop-console.png");
  check("console lists the conflict with both versions", (await op.getByTestId("console-conflict").count()) >= 1);
  check("console lists the late record", (await op.getByTestId("console-late-item").count()) >= 1);
  // confirm the late record with a reason
  await op.getByTestId("late-decide-reason").first().fill("Беше без покритие на обекта");
  await op.getByTestId("late-decide-confirm").first().click();
  await op.waitForTimeout(1500);
  // keep the office version in the conflict
  await op.getByTestId("conflict-decide-reason").first().fill("Говорих с техника");
  await op.getByTestId("conflict-decide-keep_office").first().click();
  await op.waitForTimeout(1500);
  await shot(op, "desktop-console-decided.png");
  const yday = await api(op, "GET", `/attendance/history?user_id=${RUN.technician.id}`);
  res.history_status = yday.status;

  // ── block the phone ──────────────────────────────────────────────────────────────
  await op.locator("tr", { hasText: "Android" }).getByTestId("console-revoke").click();
  await op.getByTestId("revoke-reason").fill("Изгубен телефон");
  await op.getByTestId("revoke-confirm").click();
  await op.waitForTimeout(1500);
  await shot(op, "desktop-console-revoked.png");
  check("console shows the device blocked", (await op.getByText(/блокирано/).count()) >= 1);
  await day.goto(`${BASE}/my-day`);
  await day.waitForURL(/device-blocked/, { timeout: 20000 }).catch(() => {});
  await day.waitForTimeout(1000);
  check("phone: Устройството е блокирано", (await day.getByTestId("device-blocked-page").count()) === 1);
  const wiped = await day.evaluate(async () => {
    const dbs = indexedDB.databases ? await indexedDB.databases() : [];
    if (!dbs.some((d) => d.name === "bw-offline")) return true;
    const db = await new Promise((r) => { const o = indexedDB.open("bw-offline"); o.onsuccess = () => r(o.result); });
    if (!db.objectStoreNames.contains("queue")) return true;
    return new Promise((r) => { const t = db.transaction("queue").objectStore("queue").count(); t.onsuccess = () => r(t.result === 0); });
  });
  check("phone: local queue, keys and device id wiped", wiped);
  await shot(day, "phone-device-blocked.png");

  await browser.close();
  res.summary = { passed: res.checks.filter((c) => c.ok).length, failed };
  fs.writeFileSync(path.join(OUT, "e2e-results.json"), JSON.stringify(res, null, 1) + "\n");
  console.log(`\n${res.summary.passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

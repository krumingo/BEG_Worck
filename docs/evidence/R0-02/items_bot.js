// R0-02 bot test — two tenants, the items page, and the filter attack.
//
//   node items_bot.js <frontend_url> <api_url> <seed.json> <out_dir>
//
// (1) Admin of A logs in through the UI, opens /data/items -> screenshot; only A's SKUs.
// (2) In the SAME browser session (A's token from localStorage) the page itself
//     requests /api/items?filters=org_id=<B> -> must be 400 with no B data;
//     the response is recorded as JSON and rendered into a screenshot.
// (3) Admin of B logs in in a fresh context -> screenshot; only B's SKUs.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "R002-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const results = { started_at: new Date().toISOString(), steps: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
}

async function login(browser, email) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${FRONT}/login`);
  await page.getByTestId("login-email-input").fill(email);
  await page.getByTestId("login-password-input").fill(PASSWORD);
  await page.getByTestId("login-submit-button").click();
  await page.waitForFunction(() => !!localStorage.getItem("bw_token"), null, { timeout: 30000 });
  return { ctx, page };
}

async function itemsPage(page, file) {
  await page.goto(`${FRONT}/data/items`);
  await page.getByTestId("data-table").waitFor({ timeout: 30000 });
  await page.getByTestId("data-table-row-0").waitFor({ timeout: 30000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  const text = await page.getByTestId("data-table").innerText();
  return text;
}

function seen(text, skus) {
  return skus.filter((s) => text.includes(s));
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  try {
    // (1) A sees only A
    const a = await login(browser, seed.A.admin_email);
    const aText = await itemsPage(a.page, "01_admin_A_items.png");
    check("1 A items page shows all A items", seen(aText, seed.A.skus).length === seed.A.skus.length,
      { seen: seen(aText, seed.A.skus) });
    check("1 A items page shows no B item", seen(aText, seed.B.skus).length === 0,
      { leaked: seen(aText, seed.B.skus) });

    // (2) same session, the attack request
    const attackUrl = `${API}/api/items?filters=${encodeURIComponent("org_id=" + seed.B.org_id)}`;
    const resp = await a.page.evaluate(async (url) => {
      const r = await fetch(url, { headers: { Authorization: "Bearer " + localStorage.getItem("bw_token") } });
      return { status: r.status, body: await r.text() };
    }, attackUrl);
    const leaked = seed.B.skus.filter((s) => resp.body.includes(s));
    results.attack = { url: attackUrl.replace(API, "<api>"), status: resp.status, body: resp.body };
    check("2 filters=org_id=<B> is 400", resp.status === 400, { status: resp.status });
    check("2 response carries no B data", leaked.length === 0 && !resp.body.includes('"items"'),
      { leaked, body: resp.body });
    // render the recorded response for a visual record
    const shot = await a.ctx.newPage();
    await shot.setContent(`<html><body style="font:16px monospace;padding:24px">
      <h2>R0-02 attack request (session of Admin A)</h2>
      <p><b>GET</b> ${results.attack.url.replace(/</g, "&lt;")}</p>
      <p><b>B org_id:</b> ${seed.B.org_id}</p>
      <p><b>HTTP status:</b> ${resp.status}</p>
      <pre style="background:#eee;padding:12px;white-space:pre-wrap">${resp.body.replace(/</g, "&lt;")}</pre>
      <p>B SKUs found in body: ${leaked.length ? leaked.join(", ") : "none"}</p></body></html>`);
    await shot.screenshot({ path: path.join(OUT, "02_admin_A_attack_org_id_B_400.png") });
    await a.ctx.close();

    // (3) B sees only B
    const b = await login(browser, seed.B.admin_email);
    const bText = await itemsPage(b.page, "03_admin_B_items.png");
    check("3 B items page shows all B items", seen(bText, seed.B.skus).length === seed.B.skus.length,
      { seen: seen(bText, seed.B.skus) });
    check("3 B items page shows no A item", seen(bText, seed.A.skus).length === 0,
      { leaked: seen(bText, seed.A.skus) });
    await b.ctx.close();
  } catch (e) {
    check("bot ran to the end", false, { error: String(e) });
  } finally {
    await browser.close();
  }
  results.finished_at = new Date().toISOString();
  results.result = failed ? "FAIL" : "PASS";
  fs.writeFileSync(path.join(OUT, "bot_result.json"), JSON.stringify(results, null, 2) + "\n");
  console.log("BOT " + results.result);
  process.exit(failed ? 1 : 0);
})();

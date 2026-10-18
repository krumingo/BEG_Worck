// R0-07 bot test — POST /api/dev/reset-warehouses only in dev/test (AUD-039).
//
//   node reset_bot.js <frontend_url> <api_url> <seed.json> <out_dir> <run: no-env|env-test>
//
// no-env  : Admin logs in through the UI, opens the warehouse list (screenshot), sends the reset
//           POST from the session -> 404; the list after a reload is unchanged (screenshot).
// env-test: Warehousekeeper logs in, POST -> 403, list unchanged; then Admin: POST -> 200 and the
//           warehouses are gone from the list (screenshot).
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT, RUN] = process.argv.slice(2);
const PASSWORD = "R007-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const results = { started_at: new Date().toISOString(), run: RUN, steps: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
}

async function login(browser, email) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${FRONT}/login`);
  await page.getByTestId("login-email-input").fill(email);
  await page.getByTestId("login-password-input").fill(PASSWORD);
  await page.getByTestId("login-submit-button").click();
  await page.waitForFunction(() => !!localStorage.getItem("bw_token"), null, { timeout: 30000 });
  return page;
}

async function reset(page) {
  return page.evaluate(async (api) => {
    const r = await fetch(`${api}/api/dev/reset-warehouses`, {
      method: "POST", headers: { Authorization: "Bearer " + localStorage.getItem("bw_token") } });
    return { status: r.status, body: await r.text() };
  }, API);
}

async function apiList(page) {
  return page.evaluate(async (api) => {
    const r = await fetch(`${api}/api/warehouses?page_size=100`, {
      headers: { Authorization: "Bearer " + localStorage.getItem("bw_token") } });
    const j = await r.json();
    return (j.items || j.data || j).map((w) => w.name).sort();
  }, API);
}

async function showList(page, shot) {
  await page.goto(`${FRONT}/data/warehouses`);
  await page.getByTestId("warehouses-page-title").waitFor({ timeout: 30000 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT, shot), fullPage: true });
  return (await page.locator("body").innerText());
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  const names = seed.warehouses.map((w) => w.name);
  try {
    if (RUN === "no-env") {
      const page = await login(browser, seed.admin_email);
      const before = await showList(page, "01_no_env_list_before.png");
      check("1 list shows the three seeded warehouses", names.every((n) => before.includes(n)), { names });
      const r = await reset(page);
      results.reset_response = r;
      check("1 reset without ENV -> 404", r.status === 404, r);
      const after = await showList(page, "02_no_env_list_after_404.png");
      check("1 list unchanged after the 404", names.every((n) => after.includes(n)), { names });
      check("1 API list unchanged", JSON.stringify(await apiList(page)) === JSON.stringify([...names].sort()), {});
    } else {
      const keeper = await login(browser, seed.keeper_email);
      const rk = await reset(keeper);
      results.keeper_response = rk;
      check("2 Warehousekeeper, ENV=test -> 403", rk.status === 403, rk);
      check("2 nothing deleted by the 403", (await apiList(keeper)).length === names.length, {});
      const page = await login(browser, seed.admin_email);
      const before = await showList(page, "03_env_test_list_before.png");
      check("2 list shows the three warehouses", names.every((n) => before.includes(n)), { names });
      const r = await reset(page);
      results.admin_response = r;
      check("2 Admin, ENV=test -> 200 with deleted_count 3", r.status === 200 && JSON.parse(r.body).deleted_count === 3, r);
      const after = await showList(page, "04_env_test_list_after_reset.png");
      check("2 list is empty after the reset", names.every((n) => !after.includes(n)), {});
    }
  } catch (e) {
    check("bot ran without exception", false, String(e));
  } finally {
    results.finished_at = new Date().toISOString();
    results.pass = !failed;
    fs.writeFileSync(path.join(OUT, `bot_result_${RUN}.json`), JSON.stringify(results, null, 2));
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})();

// LAB-02 bot scenario — the screens at 390 px (iPhone width), against a real backend
// (uvicorn on a throw-away local database seeded by seed_lab02_bot.py) and the real
// production build of the frontend. Screenshots go to OUT_DIR.
//
//   API=http://127.0.0.1:8011 WEB=http://127.0.0.1:3011 OUT_DIR=... LAB02_BOT_PW=... node lab02_bot.js
const { chromium } = require("playwright");

const API = process.env.API;
const WEB = process.env.WEB;
const OUT = process.env.OUT_DIR;
const PW = process.env.LAB02_BOT_PW;
const results = [];
const check = (name, ok, extra = "") => { results.push({ name, ok, extra }); console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); };

async function login(email) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: PW }),
  });
  if (!r.ok) throw new Error(`login ${email}: ${r.status} ${await r.text()}`);
  return r.json();
}

async function pageAs(browser, who) {
  const { token, user } = await login(`${who}@lab02.example`);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: "bg-BG" });
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem("bw_token", t);
    localStorage.setItem("bw_user", JSON.stringify(u));
    localStorage.setItem("i18nextLng", "bg");
  }, [token, user]);
  const page = await ctx.newPage();
  return { page, ctx, token };
}

(async () => {
  const browser = await chromium.launch();
  try {
    // 1) Accountant: the piece-rate tab, sets 5 EUR / м2 for Шпакловка
    {
      const { page, ctx } = await pageAs(browser, "bot-acct");
      await page.goto(`${WEB}/labor-quantities`, { waitUntil: "networkidle" });
      await page.getByTestId("labor-quantities-page").waitFor();
      check("accountant sees the piece-rate tab only", await page.getByText("За одобрение").count() === 0
            && await page.getByText("Акордни цени").count() > 0);
      await page.getByTestId("lt-row-pkg-sh").waitFor();
      await page.getByTestId("lt-paytype").selectOption("Akord");
      await page.getByTestId("lt-rate").fill("5");
      await page.screenshot({ path: `${OUT}/01-accountant-piece-rate.png`, fullPage: true });
      await page.getByTestId("lt-save").click();
      await page.getByText("версия 1").waitFor({ timeout: 10000 });
      await page.screenshot({ path: `${OUT}/02-accountant-saved.png`, fullPage: true });
      check("accountant saved the piece rate (version 1)", true);
      await ctx.close();
    }
    // 2) SiteManager: the approval list (no prices), approves 120 м2
    {
      const { page, ctx } = await pageAs(browser, "bot-sm");
      await page.goto(`${WEB}/labor-quantities`, { waitUntil: "networkidle" });
      await page.getByTestId("lq-item-R-AK").waitFor();
      check("site manager does not see the piece-rate tab", await page.getByText("Акордни цени").count() === 0);
      await page.screenshot({ path: `${OUT}/03-sitemanager-pending.png`, fullPage: true });
      await page.getByTestId("lq-approve").click();
      await page.getByText("одобрено: 120 м2").waitFor({ timeout: 10000 });
      const body = await page.content();
      check("site manager sees the approval without a price", !body.includes("× 5"));
      await page.screenshot({ path: `${OUT}/04-sitemanager-approved.png`, fullPage: true });
      await ctx.close();
    }
    // 3) Admin: sees the approved quantity with the akord formula; Pay Run preview = 600
    {
      const { page, ctx, token } = await pageAs(browser, "bot-admin");
      await page.goto(`${WEB}/labor-quantities`, { waitUntil: "networkidle" });
      await page.getByText("120 м2 × 5 = 600").waitFor({ timeout: 10000 });
      await page.screenshot({ path: `${OUT}/05-admin-formula.png`, fullPage: true });
      check("admin sees 120 м2 × 5 = 600", true);
      const r = await fetch(`${API}/api/pay-runs/generate?period_start=2026-11-02&period_end=2026-11-08`,
                            { headers: { Authorization: `Bearer ${token}` } });
      const rows = (await r.json()).rows || [];
      const w = rows.find((x) => x.employee_id === "bot-worker");
      check("Pay Run preview earned = 600 (120 м2 × 5)", !!w && w.earned_amount === 600, JSON.stringify(w && w.earned_amount));
      await page.goto(`${WEB}/pay-runs`, { waitUntil: "networkidle" });
      await page.screenshot({ path: `${OUT}/06-admin-pay-runs.png`, fullPage: false });
      await ctx.close();
    }
    // 4) the worker (Technician) cannot open the approval screen
    {
      const { page, ctx, token } = await pageAs(browser, "bot-worker");
      const r = await fetch(`${API}/api/labor-quantities/pending?project_id=P`, { headers: { Authorization: `Bearer ${token}` } });
      check("worker gets 403 on the approval list", r.status === 403, String(r.status));
      await page.goto(`${WEB}/labor-quantities`, { waitUntil: "networkidle" });
      await page.screenshot({ path: `${OUT}/07-worker-redirected.png`, fullPage: false });
      check("worker is sent away from the screen", !page.url().includes("/labor-quantities"), page.url());
      await ctx.close();
    }
  } catch (e) {
    check("scenario ran without an exception", false, String(e && e.message));
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\nbot scenario: ${results.length - failed}/${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
})();

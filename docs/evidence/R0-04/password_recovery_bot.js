// R0-04 bot test — AUTH-01 Forgot/Reset Password on the merged branch (PR #56 on R0-03 main).
//
//   node password_recovery_bot.js <frontend_url> <api_url> <backend_log> <out_dir>
//
// Local backend + built frontend, MongoDB replica set in Docker, SMTP not configured,
// PASSWORD_RESET_DEV_LOG_URL=1 (the reset link is read from the backend's dev log line).
// 0  Tab A: the owner logs in with the old password (the "old session").
// 1  Tab B: login -> "Забравена парола?" -> email -> generic confirmation.
// 2  Link from the dev log -> new password -> success -> login with the new password works;
//    the old password is refused (API 401).
// 3  Tab A (old session): next navigation -> sent to /login (F-02: the JWT "av" is stale).
// 4  The same link a second time -> "invalid link" state.
// 5  375px and 1280px: login, forgot and reset pages have no horizontal scroll.
// The token is never written to the results or the screenshots' file names.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, LOG, OUT] = process.argv.slice(2);
const EMAIL = "owner@r004.test";
const OLD_PW = "R004-bot-old-pass!";
const NEW_PW = "R004-bot-new-Pass-77!";
const results = { started_at: new Date().toISOString(), steps: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: true });
}

async function devLink(after) {
  for (let i = 0; i < 40; i++) {
    const lines = fs.readFileSync(LOG, "utf8").split("\n").slice(after);
    const hit = lines.reverse().find((l) => l.includes("DEV ONLY") && l.includes("reset URL: "));
    if (hit) return hit.split("reset URL: ")[1].trim();
    await new Promise((r) => setTimeout(r, 250));
  }
  return null;
}

async function apiLogin(password) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password }) });
  return r.status;
}

async function noHorizontalScroll(page) {
  return page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth,
                                innerWidth: window.innerWidth }));
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  try {
    // 0 — the old session
    const ctxA = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const tabA = await ctxA.newPage();
    await tabA.goto(`${FRONT}/login`);
    await tabA.getByTestId("login-email-input").fill(EMAIL);
    await tabA.getByTestId("login-password-input").fill(OLD_PW);
    await tabA.getByTestId("login-submit-button").click();
    await tabA.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
    const oldToken = await tabA.evaluate(() => localStorage.getItem("bw_token") || localStorage.getItem("token"));
    check("0 old session logged in", !!oldToken && !tabA.url().includes("/login"), { url: new URL(tabA.url()).pathname });
    await shot(tabA, "00_old_session_logged_in.png");

    // 1 — forgot password from the login page
    const ctxB = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const tabB = await ctxB.newPage();
    await tabB.goto(`${FRONT}/login`);
    await tabB.getByTestId("forgot-password-link").click();
    await tabB.waitForURL(/\/forgot-password/);
    const logLines = fs.readFileSync(LOG, "utf8").split("\n").length - 1;
    await tabB.getByTestId("forgot-email-input").fill(EMAIL);
    await tabB.getByTestId("forgot-submit-button").click();
    await tabB.getByTestId("forgot-password-confirmation").waitFor({ timeout: 10000 });
    check("1 generic confirmation shown", true, { url: new URL(tabB.url()).pathname });
    await shot(tabB, "01_forgot_generic_confirmation.png");

    // 2 — link from the dev log -> new password -> success -> login
    const link = await devLink(logLines);
    check("2a dev-log link present", !!link && link.startsWith(FRONT + "/reset-password?token="), { link: link ? "<redacted>" : null });
    await tabB.goto(link);
    await tabB.getByTestId("reset-new-password").fill(NEW_PW);
    await tabB.getByTestId("reset-confirm-password").fill(NEW_PW);
    await tabB.getByTestId("reset-submit-button").click();
    await tabB.getByTestId("reset-password-success").waitFor({ timeout: 10000 });
    await shot(tabB, "02a_reset_success.png");
    await tabB.getByTestId("reset-go-to-login").click();
    await tabB.waitForURL(/\/login/);
    await tabB.getByTestId("login-email-input").fill(EMAIL);
    await tabB.getByTestId("login-password-input").fill(NEW_PW);
    await tabB.getByTestId("login-submit-button").click();
    await tabB.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
    check("2b login with the new password", !tabB.url().includes("/login"), { url: new URL(tabB.url()).pathname });
    await shot(tabB, "02b_login_with_new_password.png");
    check("2c old password refused (API)", (await apiLogin(OLD_PW)) === 401, {});

    // 3 — the old tab's session is rejected
    const me = await fetch(`${API}/api/auth/me`, { headers: { Authorization: "Bearer " + oldToken } });
    check("3a old JWT -> 401 (API)", me.status === 401, { status: me.status });
    await tabA.goto(`${FRONT}/users`);
    await tabA.waitForURL(/\/login/, { timeout: 15000 });
    check("3b old tab sent to /login", tabA.url().includes("/login"), { url: new URL(tabA.url()).pathname });
    await shot(tabA, "03_old_session_rejected_to_login.png");

    // 4 — the same link a second time
    const ctxC = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const tabC = await ctxC.newPage();
    await tabC.goto(link);
    await tabC.getByTestId("reset-new-password").fill("R004-bot-third-Pass-88!");
    await tabC.getByTestId("reset-confirm-password").fill("R004-bot-third-Pass-88!");
    await tabC.getByTestId("reset-submit-button").click();
    await tabC.getByTestId("reset-link-invalid").waitFor({ timeout: 10000 });
    check("4 reused link -> invalid", true, {});
    await shot(tabC, "04_reused_link_invalid.png");
    check("4b password unchanged by the reused link", (await apiLogin(NEW_PW)) === 200, {});

    // 5 — widths
    for (const width of [375, 1280]) {
      const ctx = await browser.newContext({ viewport: { width, height: 800 } });
      const page = await ctx.newPage();
      for (const [name, url] of [["login", "/login"], ["forgot", "/forgot-password"],
                                 ["reset", "/reset-password?token=" + "x".repeat(43)]]) {
        await page.goto(FRONT + url);
        await page.waitForLoadState("networkidle");
        const m = await noHorizontalScroll(page);
        check(`5 ${width}px ${name} no horizontal scroll`, m.scrollWidth <= m.innerWidth, m);
        await shot(page, `05_${width}px_${name}.png`);
      }
      await ctx.close();
    }
  } catch (err) {
    check("unexpected error", false, { error: String(err).replace(/token=[^\s"]+/g, "token=<redacted>") });
  } finally {
    await browser.close();
    results.finished_at = new Date().toISOString();
    results.result = failed ? "FAIL" : "PASS";
    fs.writeFileSync(path.join(OUT, "bot_result.json"), JSON.stringify(results, null, 2));
    process.exit(failed ? 1 : 0);
  }
})();

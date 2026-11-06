// R0-03 bot test — roles without escalation, one email = one User (AUD-025, AUTH-01 F-03).
//
//   node roles_email_bot.js <frontend_url> <api_url> <seed.json> <out_dir>
//
// 1  Accountant: opens their own employee card (the UI gives an Accountant no edit button), sends
//    PUT /employees/{self}/basic {role: Admin}, {email} and PUT /users/{self} {role: Admin} from the
//    session -> 400 / 400 / 403; after a reload the card still says Accountant.
// 1b Admin: edits that card — role and email are locked; a name+phone save from the UI works
//    (the form no longer sends role/email to /basic).
// 2  Admin: Users page -> "set password" for the Owner -> refused in the dialog; API 403; the
//    Owner still logs in with the old password (hash unchanged).
// 3  Owner: Users page -> edit the Admin -> role Наблюдател (Viewer) -> saved; list shows it.
// 4  Owner of firm B: Users page -> new user with firm A's admin email in other case -> alert
//    "already registered"; API 409 EMAIL_EXISTS; no user created.
// 5  Login with an email that 2 Users hold (pre-R0-03 data, inserted directly into the
//    disposable DB by the runner) -> message on the login page, no token, no crash.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "R003-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const results = { started_at: new Date().toISOString(), steps: [] };
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

async function api(page, method, url, body) {
  return page.evaluate(async ([base, method, url, body]) => {
    const r = await fetch(base + url, {
      method, headers: { "Content-Type": "application/json",
                         Authorization: "Bearer " + localStorage.getItem("bw_token") },
      body: body === undefined ? undefined : JSON.stringify(body) });
    let parsed; const text = await r.text();
    try { parsed = JSON.parse(text); } catch { parsed = text; }
    return { status: r.status, body: parsed };
  }, [API, method, url, body]);
}

async function anonLogin(page, email, password) {
  return page.evaluate(async ([base, email, password]) => {
    const r = await fetch(base + "/api/auth/login", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
    const j = await r.json();
    return { status: r.status, has_token: !!j.token, detail: j.detail || null };
  }, [API, email, password]);
}

async function shot(page, name) {
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, name), fullPage: true });
}

async function usersPage(page) {
  await page.goto(`${FRONT}/users`);
  await page.getByTestId("users-table").waitFor({ timeout: 30000 });
  await page.waitForTimeout(800);
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  const A = seed;
  try {
    // ── 1 Accountant (the UI shows no edit button to an Accountant: requests from the session) ──
    {
      const page = await login(browser, A.acct_a.email);
      await page.goto(`${FRONT}/employees/${A.acct_a.id}`);
      await page.getByText("acct@r003a.test").first().waitFor({ timeout: 30000 });
      await shot(page, "01_accountant_card_before.png");
      check("1 Accountant sees no edit button", (await page.getByTestId("edit-employee-btn").count()) === 0, {});
      const r1 = await api(page, "PUT", `/api/employees/${A.acct_a.id}/basic`, { role: "Admin" });
      const r2 = await api(page, "PUT", `/api/users/${A.acct_a.id}`, { role: "Admin" });
      const r3 = await api(page, "PUT", `/api/employees/${A.acct_a.id}/basic`, { email: "boss@r003a.test" });
      results.step1 = { basic_role: r1, users_role: r2, basic_email: r3 };
      check("1 /basic role=Admin -> 400", r1.status === 400 && r1.body.detail.error_code === "FIELD_NOT_ALLOWED", r1);
      check("1 PUT /users self role=Admin -> 403", r2.status === 403, r2);
      check("1 /basic email -> 400", r3.status === 400, r3);
      const me = await api(page, "GET", "/api/auth/me");
      check("1 role and email unchanged", me.body.role === "Accountant" && me.body.email === A.acct_a.email,
            { role: me.body.role, email: me.body.email });
      await page.reload();
      await page.getByText("acct@r003a.test").first().waitFor({ timeout: 30000 });
      await shot(page, "02_accountant_card_after_role_unchanged.png");
      check("1 card still shows Accountant", (await page.locator("body").innerText()).includes("Accountant"), {});
    }
    // ── 1b Admin edits the Accountant's card: role/email locked, name+phone save works ──
    {
      const page = await login(browser, A.admin_a.email);
      await page.goto(`${FRONT}/employees/${A.acct_a.id}`);
      await page.getByTestId("edit-employee-btn").waitFor({ timeout: 30000 });
      await page.getByTestId("edit-employee-btn").click();
      await page.getByTestId("edit-form").waitFor();
      const roleLocked = await page.getByTestId("role-select").isDisabled();
      const emailLocked = await page.getByTestId("email-input").isDisabled();
      await page.locator('[data-testid="edit-form"] input').first().fill("Счетоводител-Бот");
      await page.getByTestId("phone-input").fill("+359888000111");
      await shot(page, "03_admin_edit_form_role_email_locked.png");
      check("1b edit form: role and email are locked", roleLocked && emailLocked, { roleLocked, emailLocked });
      let alertText = null;
      page.once("dialog", async (d) => { alertText = d.message(); await d.dismiss(); });
      await page.getByTestId("save-employee-btn").click();
      await page.getByTestId("edit-employee-btn").waitFor({ timeout: 30000 });
      await page.waitForTimeout(1500);
      const users = await api(page, "GET", "/api/users");
      const u = users.body.find((x) => x.id === A.acct_a.id);
      check("1b UI save of name/phone works (no 400), role unchanged",
            !alertText && u.first_name === "Счетоводител-Бот" && u.phone === "+359888000111" && u.role === "Accountant",
            { alertText, first_name: u.first_name, phone: u.phone, role: u.role });
      await shot(page, "03b_admin_saved_name_phone.png");
    }
    // ── 2 Admin -> Owner's password ─────────────────────────────────────────────
    {
      const page = await login(browser, A.admin_a.email);
      await usersPage(page);
      await page.getByTestId(`user-actions-${A.owner_a.id}`).click();
      await page.getByTestId(`reset-password-${A.owner_a.id}`).click();
      await page.getByTestId("new-password-input").fill("Hijack-Pass-123!");
      await page.getByTestId("confirm-password-input").fill("Hijack-Pass-123!");
      await page.getByTestId("reset-password-submit").click();
      await page.getByTestId("reset-password-error").waitFor({ timeout: 15000 });
      await shot(page, "04_admin_reset_owner_password_refused.png");
      check("2 dialog shows the refusal", await page.getByTestId("reset-password-error").isVisible(), {});
      const r = await api(page, "POST", `/api/admin/set-password/${A.owner_a.id}`, { new_password: "Hijack-Pass-123!" });
      const r2 = await api(page, "PUT", `/api/users/${A.owner_a.id}`, { role: "Viewer" });
      const r3 = await api(page, "DELETE", `/api/users/${A.owner_a.id}`);
      const r4 = await api(page, "PUT", `/api/users/${A.acct_a.id}`, { role: "Owner" });
      results.step2 = { set_password: r, demote_owner: r2, delete_owner: r3, grant_owner: r4 };
      check("2 API set-password on Owner -> 403", r.status === 403 && r.body.detail.error_code === "OWNER_CHANGE_REQUIRES_OWNER", r);
      check("2 API demote Owner -> 403", r2.status === 403, r2);
      check("2 API delete Owner -> 403", r3.status === 403, r3);
      check("2 API grant Owner -> 403", r4.status === 403 && r4.body.detail.error_code === "ROLE_ABOVE_OWN_FORBIDDEN", r4);
      const old = await anonLogin(page, A.owner_a.email, PASSWORD);
      const hijack = await anonLogin(page, A.owner_a.email, "Hijack-Pass-123!");
      check("2 Owner still logs in with the old password", old.status === 200 && old.has_token, old);
      check("2 the attempted password does not work", hijack.status === 401 && !hijack.has_token, hijack);
    }
    // ── 3 Owner changes the Admin's role ───────────────────────────────────────
    {
      const page = await login(browser, A.owner_a.email);
      await usersPage(page);
      await page.getByTestId(`user-actions-${A.admin_a.id}`).click();
      await page.getByTestId(`edit-user-${A.admin_a.id}`).click();
      await page.getByTestId("user-role-select").click();
      await page.getByRole("option", { name: "Наблюдател" }).click();
      await page.getByTestId("user-save-button").click();
      await page.getByTestId("user-dialog").waitFor({ state: "detached", timeout: 15000 });
      await usersPage(page);
      const row = await page.getByTestId(`user-row-${A.admin_a.id}`).innerText();
      await shot(page, "05_owner_changed_admin_to_viewer.png");
      check("3 list shows the former Admin as Наблюдател", row.includes("Наблюдател"), { row });
      const users = await api(page, "GET", "/api/users");
      const u = users.body.find((x) => x.id === A.admin_a.id);
      results.step3 = { admin_after: { id: u.id, role: u.role } };
      check("3 API role is Viewer", u.role === "Viewer", { role: u.role });
    }
    // ── 4 another firm's email ─────────────────────────────────────────────────
    {
      const page = await login(browser, A.owner_b.email);
      await usersPage(page);
      let alertText = null;
      page.once("dialog", async (d) => { alertText = d.message(); await d.dismiss(); });
      await page.getByTestId("add-user-button").click();
      await page.getByTestId("user-email-input").fill("  Admin@R003A.test ");
      await page.getByTestId("user-password-input").fill(PASSWORD);
      await page.getByTestId("user-firstname-input").fill("Copy");
      await page.getByTestId("user-lastname-input").fill("Cat");
      await page.getByTestId("user-save-button").click();
      await page.waitForTimeout(1500);
      await shot(page, "06_firm_b_create_with_firm_a_email_refused.png");
      check("4 UI alert says the email is registered", (alertText || "").includes("already registered"), { alertText });
      const r = await api(page, "POST", "/api/users", { email: "ADMIN@r003a.test", password: PASSWORD,
                                                        first_name: "Copy", last_name: "Cat", role: "Viewer" });
      results.step4 = { create: r, ui_alert: alertText };
      check("4 API -> 409 EMAIL_EXISTS", r.status === 409 && r.body.detail.error_code === "EMAIL_EXISTS", r);
      check("4 no firm is named in the answer", !JSON.stringify(r.body).includes("R003 Firm A"), {});
      const users = await api(page, "GET", "/api/users");
      check("4 firm B still has 2 users", users.body.length === 2, { n: users.body.length });
    }
    // ── 5 duplicate identity at login ──────────────────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
      const page = await ctx.newPage();
      await page.goto(`${FRONT}/login`);
      await page.getByTestId("login-email-input").fill("IVAN@r003b.test");
      await page.getByTestId("login-password-input").fill(PASSWORD);
      await page.getByTestId("login-submit-button").click();
      await page.getByTestId("login-error").waitFor({ timeout: 15000 });
      await shot(page, "07_login_duplicate_identity_refused.png");
      const msg = await page.getByTestId("login-error").innerText();
      const token = await page.evaluate(() => localStorage.getItem("bw_token"));
      const r = await anonLogin(page, "ivan@r003b.test", PASSWORD);
      results.step5 = { ui_message: msg, api: r };
      check("5 login page shows the identity message, no crash", msg.includes("identity"), { msg });
      check("5 no token stored", !token, {});
      check("5 API -> 409 DUPLICATE_IDENTITY, no token", r.status === 409 && !r.has_token
            && r.detail.error_code === "DUPLICATE_IDENTITY", r);
    }
  } catch (e) {
    check("bot ran without exception", false, String(e));
  } finally {
    results.finished_at = new Date().toISOString();
    results.pass = !failed;
    fs.writeFileSync(path.join(OUT, "bot_result.json"), JSON.stringify(results, null, 2));
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})();

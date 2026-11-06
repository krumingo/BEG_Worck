// R0-06 bot test — a paid Pay Run is not reopened and not paid twice (AUD-043).
//
//   node paid_pay_run_bot.js <frontend_url> <api_url> <seed.json> <out_dir>
//
// (1) Admin logs in through the UI, opens /pay-runs, loads the seeded week, keeps all
//     three employees and presses „Потвърди плащане“ (the UI chains create → mark-paid)
//     -> screenshots; the run is `paid` in the UI.
// (2) The paid run's detail has no „Отвори за редакция“ button, so the reopen attempt
//     (whole run, one row) and a PATCH go through the API from the same session -> 409.
// (3) A second mark-paid, and then 5 parallel ones, from the same session -> all 409;
//     the API shows exactly one salary Outflow per employee for this run.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "R006-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const results = { started_at: new Date().toISOString(), steps: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
}

async function render(ctx, file, title, obj) {
  const view = await ctx.newPage();
  await view.setContent(`<html><body style="font:13px monospace;background:#fff;color:#111;padding:16px">
    <h3>${title.replace(/</g, "&lt;")}</h3><pre>${JSON.stringify(obj, null, 2).replace(/</g, "&lt;")}</pre></body></html>`);
  await view.screenshot({ path: path.join(OUT, file), fullPage: true });
  await view.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const page = await ctx.newPage();
    await page.goto(`${FRONT}/login`);
    await page.getByTestId("login-email-input").fill(seed.admin_email);
    await page.getByTestId("login-password-input").fill(PASSWORD);
    await page.getByTestId("login-submit-button").click();
    await page.waitForFunction(() => !!localStorage.getItem("bw_token"), null, { timeout: 30000 });

    // (1) create + pay through the UI
    await page.goto(`${FRONT}/pay-runs`);
    await page.getByTestId("period-picker").waitFor({ timeout: 30000 });
    const dates = page.getByTestId("period-picker").locator('input[type="date"]');
    await dates.nth(0).fill(seed.period_start);
    await dates.nth(1).fill(seed.period_end);
    await page.getByTestId("period-picker").getByRole("button", { name: "Зареди" }).click();
    await page.getByTestId("weekly-grid").waitFor({ timeout: 30000 });
    for (const w of seed.workers) await page.getByTestId(`grid-row-${w.id}`).waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: "Напред →", exact: true }).click();
    await page.getByRole("button", { name: "Напред → Плащане" }).click();
    await page.getByTestId("create-payrun-btn").waitFor({ timeout: 30000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, "01_payment_step_three_employees.png"), fullPage: true });

    const [createResp, paidResp] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/pay-runs") && r.request().method() === "POST"),
      page.waitForResponse((r) => /\/api\/pay-runs\/[^/]+\/mark-paid$/.test(r.url()) && r.request().method() === "POST"),
      page.getByTestId("create-payrun-btn").click(),
    ]);
    const created = await createResp.json();
    const runId = created.id;
    results.pay_run_id = runId;
    check("1 POST /api/pay-runs is 200", createResp.status() === 200, { status: createResp.status(), number: created.number });
    check("1 UI-chained POST mark-paid is 200", paidResp.status() === 200, { status: paidResp.status(), body: await paidResp.json() });

    await page.getByTestId("history-table").waitFor({ timeout: 30000 });
    await page.getByTestId(`run-${runId}`).waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);
    const rowText = await page.getByTestId(`run-${runId}`).innerText();
    check("1 history row shows the run as „Платен“", rowText.includes("Платен"), { rowText });
    await page.getByTestId(`run-${runId}`).locator("button").last().click();
    await page.getByTestId("payrun-detail-modal").waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, "02_paid_run_detail_no_reopen_button.png"), fullPage: true });
    const reopenButtons = await page.getByTestId("reopen-all-btn").count();
    const markPaidButtons = await page.getByTestId("mark-paid-btn").count();
    check("2 paid run detail: no „Отвори за редакция“ and no „Маркирай платен“ button",
      reopenButtons === 0 && markPaidButtons === 0, { reopenButtons, markPaidButtons });
    await page.keyboard.press("Escape");

    // (2)+(3) API from the same session
    const api = await page.evaluate(async ({ API, runId, seed }) => {
      const h = { Authorization: "Bearer " + localStorage.getItem("bw_token"), "Content-Type": "application/json" };
      const call = async (method, url, body) => {
        const r = await fetch(`${API}/api${url}`, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
        let j = null; try { j = await r.json(); } catch (e) { /* empty */ }
        return { status: r.status, body: j };
      };
      const runBefore = (await call("GET", `/pay-runs/${runId}`)).body;
      const out = {};
      out.reopen_all = await call("POST", `/pay-runs/${runId}/reopen`, { employee_ids: [], reason: "bot R0-06" });
      out.reopen_row = await call("POST", `/pay-runs/${runId}/reopen`, { employee_ids: [seed.workers[0].id], reason: "bot R0-06" });
      out.patch = await call("PATCH", `/pay-runs/${runId}`, { run_type: "weekly", period_start: seed.period_start,
        period_end: seed.period_end, status: "confirmed",
        rows: seed.workers.map((w) => ({ employee_id: w.id, paid_now_amount: 0 })) });
      out.mark_paid_again = await call("POST", `/pay-runs/${runId}/mark-paid`, { payment_method: "cash" });
      out.mark_paid_parallel = (await Promise.all([1, 2, 3, 4, 5].map(() =>
        call("POST", `/pay-runs/${runId}/mark-paid`, { payment_method: "cash" })))).map((r) => r.status);
      const runAfter = (await call("GET", `/pay-runs/${runId}`)).body;
      const pays = (await call("GET", `/finance/payments?direction=Outflow`)).body;
      return { runBefore, runAfter, out, pays };
    }, { API, runId, seed });

    const rows = api.runAfter.employee_rows || [];
    const outflows = (Array.isArray(api.pays) ? api.pays : (api.pays.items || [])).filter((p) => p.reference === runId);
    const record = {
      pay_run: { id: runId, number: api.runAfter.number, status: api.runAfter.status, paid_at: api.runAfter.paid_at,
                 paid_effects: api.runAfter.paid_effects, version: api.runAfter.version,
                 history_actions: (api.runAfter.history || []).map((x) => x.action),
                 rows: rows.map((r) => ({ employee_id: r.employee_id, name: `${r.first_name} ${r.last_name}`,
                                          paid_now_amount: r.paid_now_amount, row_status: r.row_status })) },
      refused_attempts: {
        reopen_all: api.out.reopen_all, reopen_row: api.out.reopen_row, patch: api.out.patch,
        mark_paid_again: api.out.mark_paid_again, mark_paid_parallel_statuses: api.out.mark_paid_parallel,
      },
      salary_outflows_for_this_run: outflows.map((p) => ({ id: p.id, user_id: p.user_id, counterparty_name: p.counterparty_name,
                                                          amount: p.amount, account_id: p.account_id, method: p.method })),
    };
    results.api_record = record;
    fs.writeFileSync(path.join(OUT, "api_paid_run.json"), JSON.stringify(record, null, 2));

    check("2 reopen of the paid run (whole) -> 409", api.out.reopen_all.status === 409, api.out.reopen_all);
    check("2 reopen of one row of the paid run -> 409", api.out.reopen_row.status === 409, api.out.reopen_row);
    check("2 PATCH of the paid run -> 409", api.out.patch.status === 409, api.out.patch);
    check("3 second mark-paid -> 409", api.out.mark_paid_again.status === 409, api.out.mark_paid_again);
    check("3 five parallel mark-paid -> all 409", api.out.mark_paid_parallel.every((s) => s === 409), api.out.mark_paid_parallel);
    check("3 the run is unchanged by the refused attempts (status paid, same version, rows not reopened)",
      api.runAfter.status === "paid" && api.runAfter.version === api.runBefore.version
        && JSON.stringify(api.runAfter.employee_rows) === JSON.stringify(api.runBefore.employee_rows)
        && JSON.stringify(api.runAfter.history) === JSON.stringify(api.runBefore.history),
      { status: api.runAfter.status, version: api.runAfter.version });
    const paidRows = rows.filter((r) => (r.paid_now_amount || 0) > 0);
    const perEmployee = {};
    for (const p of outflows) perEmployee[p.user_id] = (perEmployee[p.user_id] || 0) + 1;
    check("3 exactly one salary Outflow per employee with paid > 0, amounts equal paid_now",
      outflows.length === paidRows.length && paidRows.length === 3
        && paidRows.every((r) => perEmployee[r.employee_id] === 1
          && outflows.find((p) => p.user_id === r.employee_id).amount === Math.round(r.paid_now_amount * 100) / 100),
      { outflows: outflows.length, paid_rows: paidRows.length, perEmployee });
    check("3 one marked_paid history entry", record.pay_run.history_actions.filter((a) => a === "marked_paid").length === 1,
      record.pay_run.history_actions);

    await render(ctx, "03_api_reopen_patch_refused_409.png",
      `Admin session: reopen / reopen row / PATCH on paid ${record.pay_run.number}`,
      { reopen_all: api.out.reopen_all, reopen_row: api.out.reopen_row, patch: api.out.patch });
    await render(ctx, "04_api_mark_paid_again_refused_one_outflow_each.png",
      `Admin session: mark-paid again + 5 parallel; GET /api/finance/payments?direction=Outflow (reference=${runId})`,
      { mark_paid_again: api.out.mark_paid_again, mark_paid_parallel_statuses: api.out.mark_paid_parallel,
        pay_run: record.pay_run, salary_outflows_for_this_run: record.salary_outflows_for_this_run });
  } catch (e) {
    check("bot ran without error", false, { error: String(e) });
  } finally {
    results.finished_at = new Date().toISOString();
    results.result = failed ? "FAIL" : "PASS";
    fs.writeFileSync(path.join(OUT, "bot_result.json"), JSON.stringify(results, null, 2));
    await browser.close();
    console.log(results.result);
    process.exit(failed ? 1 : 0);
  }
})();

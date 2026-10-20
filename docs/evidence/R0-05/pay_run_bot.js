// R0-05 bot test — a Pay Run with ONE of three employees selected (AUD-023).
//
//   node pay_run_bot.js <frontend_url> <api_url> <seed.json> <out_dir>
//
// (1) Admin logs in through the UI, opens /pay-runs, loads the seeded week
//     -> screenshot; the preview grid shows all three employees.
// (2) Unticks two employees in the grid, goes to the payment step and confirms
//     ("Потвърди плащане") -> screenshots of the payment step, the created run's
//     detail and the slips tab; only one employee and one slip.
// (3) Same browser session fetches the created Pay Run and the slips through the
//     API -> exactly one row / one slip; the record is saved as JSON and rendered
//     into a screenshot.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "R005-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const [KEEP, ...DROP] = seed.workers;
const results = { started_at: new Date().toISOString(), selected: KEEP, unselected: DROP, steps: [] };
let failed = false;

function check(step, cond, detail) {
  results.steps.push({ step, pass: !!cond, detail });
  if (!cond) failed = true;
  console.log(`${cond ? "PASS" : "FAIL"} ${step}: ${JSON.stringify(detail)}`);
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

    // (1) preview with all three
    await page.goto(`${FRONT}/pay-runs`);
    await page.getByTestId("period-picker").waitFor({ timeout: 30000 });
    const dates = page.getByTestId("period-picker").locator('input[type="date"]');
    await dates.nth(0).fill(seed.period_start);
    await dates.nth(1).fill(seed.period_end);
    await page.getByTestId("period-picker").getByRole("button", { name: "Зареди" }).click();
    await page.getByTestId("weekly-grid").waitFor({ timeout: 30000 });
    for (const w of seed.workers) await page.getByTestId(`grid-row-${w.id}`).waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, "01_preview_three_employees.png"), fullPage: true });
    const gridText = await page.getByTestId("weekly-grid").innerText();
    const shown = seed.workers.filter((w) => gridText.includes(w.name.split(" ")[0]));
    check("1 preview grid lists all three employees", shown.length === 3, { shown: shown.map((w) => w.name) });

    // (2) keep ONE, untick the other two, go to payment, confirm
    for (const w of DROP) {
      await page.getByTestId(`grid-row-${w.id}`).locator('input[type="checkbox"]').uncheck();
    }
    const ticked = [];
    for (const w of seed.workers) {
      if (await page.getByTestId(`grid-row-${w.id}`).locator('input[type="checkbox"]').isChecked()) ticked.push(w.name);
    }
    check("2 grid has exactly one employee ticked", ticked.length === 1 && ticked[0] === KEEP.name, { ticked });
    await page.getByRole("button", { name: "Напред →", exact: true }).click();
    await page.getByRole("button", { name: "Напред → Плащане" }).click();
    await page.getByTestId("create-payrun-btn").waitFor({ timeout: 30000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, "02_payment_step_one_employee.png"), fullPage: true });

    const [req, resp] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith("/api/pay-runs") && r.method() === "POST"),
      page.waitForResponse((r) => r.url().endsWith("/api/pay-runs") && r.request().method() === "POST"),
      page.getByTestId("create-payrun-btn").click(),
    ]);
    const sent = JSON.parse(req.postData() || "{}");
    results.create_request_rows = sent.rows;
    check("2 UI sends exactly the one selected employee", (sent.rows || []).length === 1 && sent.rows[0].employee_id === KEEP.id,
      { rows: (sent.rows || []).map((r) => ({ employee_id: r.employee_id, paid_now_amount: r.paid_now_amount })) });
    const created = await resp.json();
    check("2 POST /api/pay-runs is 200", resp.status() === 200, { status: resp.status(), number: created.number });
    const runId = created.id;
    results.pay_run_id = runId;

    // result in the UI: history row + detail modal, then the slips tab
    await page.getByTestId("history-table").waitFor({ timeout: 30000 });
    await page.getByTestId(`run-${runId}`).waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);   // let the mark-paid that the UI chains settle and the list refresh
    await page.getByTestId(`run-${runId}`).locator("button").last().click();
    await page.getByTestId("payrun-detail-modal").waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, "03_created_run_one_employee.png"), fullPage: true });
    const modalText = await page.getByTestId("payrun-detail-modal").innerText();
    const inModal = seed.workers.filter((w) => modalText.includes(w.name.split(" ")[0])).map((w) => w.name);
    check("2 created run shows only the selected employee", inModal.length === 1 && inModal[0] === KEEP.name, { inModal });
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Фишове" }).click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, "04_slips_one_slip.png"), fullPage: true });

    // (3) API check from the same session
    const api = await page.evaluate(async ({ API, runId }) => {
      const h = { Authorization: "Bearer " + localStorage.getItem("bw_token") };
      const run = await (await fetch(`${API}/api/pay-runs/${runId}`, { headers: h })).json();
      const slips = await (await fetch(`${API}/api/payment-slips?page_size=100`, { headers: h })).json();
      const allocs = await (await fetch(`${API}/api/pay-runs/${runId}/allocations`, { headers: h })).json();
      return { run, slips, allocs };
    }, { API, runId });
    const rows = api.run.employee_rows || [];
    const slipItems = api.slips.items || [];
    const allocItems = Array.isArray(api.allocs) ? api.allocs : (api.allocs.employees || []);
    const record = {
      pay_run: { id: api.run.id, number: api.run.number, status: api.run.status, totals: api.run.totals,
                 employee_rows: rows.map((r) => ({ employee_id: r.employee_id, name: `${r.first_name} ${r.last_name}`,
                   earned_amount: r.earned_amount, paid_now_amount: r.paid_now_amount,
                   remaining_after_payment: r.remaining_after_payment })) },
      payment_slips: slipItems.map((s) => ({ slip_number: s.slip_number, employee_id: s.employee_id,
                                             pay_run_id: s.pay_run_id, paid_now_amount: s.paid_now_amount })),
      allocations_employee_ids: allocItems.map((a) => a.employee_id),
    };
    results.api_record = record;
    check("3 API: the Pay Run has exactly one row, the selected employee",
      rows.length === 1 && rows[0].employee_id === KEEP.id && api.run.totals.employees === 1,
      { rows: rows.length, employee_id: rows[0] && rows[0].employee_id });
    check("3 API: exactly one slip in the tenant, for the selected employee",
      slipItems.length === 1 && slipItems[0].employee_id === KEEP.id && slipItems[0].pay_run_id === runId,
      { slips: slipItems.length });
    check("3 API: no allocation for the unselected employees",
      !allocItems.some((a) => DROP.some((w) => w.id === a.employee_id)), { allocations: record.allocations_employee_ids });

    fs.writeFileSync(path.join(OUT, "api_pay_run.json"), JSON.stringify(record, null, 2));
    const view = await ctx.newPage();
    await view.setContent(`<html><body style="font:14px monospace;background:#fff;color:#111;padding:16px">
      <h3>GET ${API}/api/pay-runs/${runId} + /api/payment-slips + /allocations (Admin session)</h3>
      <pre>${JSON.stringify(record, null, 2).replace(/</g, "&lt;")}</pre></body></html>`);
    await view.screenshot({ path: path.join(OUT, "05_api_pay_run_one_row.png"), fullPage: true });
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

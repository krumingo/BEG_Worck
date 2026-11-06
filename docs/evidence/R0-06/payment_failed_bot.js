// R0-06-C01 bot test — an unfinished payment is shown as NOT completed (Codex F-02).
//
//   node payment_failed_bot.js <frontend_url> <api_url> <seed.json> <out_dir>
//
// The backend runs through fault_server.py: the last payment effect (slips) fails, so the
// salary Outflows are already written when the payment breaks.
// (1) Admin creates the run in the UI and presses „Потвърди плащане“ -> mark-paid fails (500).
// (2) After a reload the history row shows „НЕзавършено плащане“ (not „Платен“); the detail
//     shows the warning and no pay / reopen button -> screenshots.
// (3) Same session through the API: list/detail say payment_failed + paid_effects=failed,
//     ?status=paid does not contain the run, audit-check flags it critical, a second mark-paid /
//     reopen / PATCH -> 409 and no second Outflow.
// Exit code 0 only when every assertion holds.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [FRONT, API, SEED, OUT] = process.argv.slice(2);
const PASSWORD = "R006-bot-test-only!";
const seed = JSON.parse(fs.readFileSync(SEED, "utf8"));
const results = { started_at: new Date().toISOString(), injected_failure: "_mark_slips_paid (last payment effect)", steps: [] };
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

    // (1) create + pay through the UI; the payment breaks in its last effect
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
    // The backend's 500 handler sends no CORS headers, so Chromium may report the failed
    // mark-paid as a failed request instead of a response — accept either.
    const isMarkPaid = (req) => /\/api\/pay-runs\/[^/]+\/mark-paid$/.test(req.url()) && req.method() === "POST";
    const paidOutcome = Promise.race([
      page.waitForEvent("response", { predicate: (r) => isMarkPaid(r.request()), timeout: 30000 })
        .then((r) => ({ status: r.status() })),
      page.waitForEvent("requestfailed", { predicate: isMarkPaid, timeout: 30000 })
        .then((req) => ({ status: 0, failure: (req.failure() || {}).errorText })),
    ]);
    const [createResp, paidResp] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/pay-runs") && r.request().method() === "POST"),
      paidOutcome,
      page.getByTestId("create-payrun-btn").click(),
    ]);
    const created = await createResp.json();
    const runId = created.id;
    results.pay_run_id = runId;
    check("1 POST /api/pay-runs is 200", createResp.status() === 200, { status: createResp.status(), number: created.number });
    check("1 UI-chained mark-paid fails (injected; 500 or a failed request)", paidResp.status === 0 || paidResp.status >= 500, paidResp);
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(OUT, "05_payment_failed_error_toast.png"), fullPage: true });

    // (2) operator view after a reload
    await page.reload();
    await page.getByTestId("tab-history").click();
    await page.getByTestId(`run-${runId}`).waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    const rowText = await page.getByTestId(`run-${runId}`).innerText();
    check("2 history row shows „НЕзавършено плащане“, not „Платен“",
      rowText.includes("НЕзавършено плащане") && !rowText.includes("Платен"), { rowText });
    await page.screenshot({ path: path.join(OUT, "06_history_payment_failed.png"), fullPage: true });
    await page.getByTestId(`run-${runId}`).locator("button").last().click();
    await page.getByTestId("payrun-detail-modal").waitFor({ timeout: 30000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, "07_detail_payment_not_completed_warning.png"), fullPage: true });
    const warning = await page.getByTestId("payrun-incomplete-warning").innerText().catch(() => "");
    check("2 detail shows the „НЕ е завършено“ warning", warning.includes("НЕ е завършено"), { warning });
    const modalText = await page.getByTestId("payrun-detail-modal").innerText();
    check("2 detail rows say „Незавършено“, the modal never says „Платен“",
      !/Платен(?!о)/.test(modalText) && (modalText.match(/Незавършено/g) || []).length >= 3, { modalHasPlatenBadge: /Платен(?!о)/.test(modalText) });
    const reopenButtons = await page.getByTestId("reopen-all-btn").count();
    const markPaidButtons = await page.getByTestId("mark-paid-btn").count();
    check("2 detail offers no pay / reopen button", reopenButtons === 0 && markPaidButtons === 0, { reopenButtons, markPaidButtons });
    await page.keyboard.press("Escape");

    // (3) API from the same session
    const api = await page.evaluate(async ({ API, runId, seed }) => {
      const h = { Authorization: "Bearer " + localStorage.getItem("bw_token"), "Content-Type": "application/json" };
      const call = async (method, url, body) => {
        const r = await fetch(`${API}/api${url}`, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
        let j = null; try { j = await r.json(); } catch (e) { /* empty */ }
        return { status: r.status, body: j };
      };
      const out = {};
      out.list = (await call("GET", "/pay-runs")).body;
      out.list_paid = (await call("GET", "/pay-runs?status=paid")).body;
      out.detail = (await call("GET", `/pay-runs/${runId}`)).body;
      out.audit = (await call("GET", "/pay-runs/audit-check")).body;
      out.pays_before = (await call("GET", "/finance/payments?direction=Outflow")).body;
      out.mark_paid_again = await call("POST", `/pay-runs/${runId}/mark-paid`, { payment_method: "cash" });
      out.reopen = await call("POST", `/pay-runs/${runId}/reopen`, { employee_ids: [], reason: "bot C01" });
      out.patch = await call("PATCH", `/pay-runs/${runId}`, { run_type: "weekly", period_start: seed.period_start,
        period_end: seed.period_end, status: "confirmed", rows: seed.workers.map((w) => ({ employee_id: w.id, paid_now_amount: 0 })) });
      out.pays_after = (await call("GET", "/finance/payments?direction=Outflow")).body;
      return out;
    }, { API, runId, seed });

    const item = (api.list.items || []).find((i) => i.id === runId) || {};
    const mine = (p) => (Array.isArray(p) ? p : (p.items || [])).filter((x) => x.reference === runId);
    const record = {
      list_item: { number: item.number, status: item.status, paid_effects: item.paid_effects, paid_effects_error: item.paid_effects_error, op_lock: item.op_lock },
      detail: { status: api.detail.status, paid_effects: api.detail.paid_effects, op_lock: api.detail.op_lock,
                history_actions: (api.detail.history || []).map((x) => x.action) },
      list_status_paid_ids: (api.list_paid.items || []).map((i) => i.id),
      audit_issues: (api.audit.issues || []).filter((i) => i.type === "payment_incomplete"),
      refused: { mark_paid_again: api.mark_paid_again, reopen: api.reopen, patch: api.patch },
      salary_outflows_before: mine(api.pays_before).map((p) => ({ counterparty_name: p.counterparty_name, amount: p.amount })),
      salary_outflows_after: mine(api.pays_after).length,
    };
    results.api_record = record;
    fs.writeFileSync(path.join(OUT, "api_payment_failed.json"), JSON.stringify(record, null, 2));
    check("3 list + detail: payment_failed, paid_effects=failed, lock kept",
      item.status === "payment_failed" && item.paid_effects === "failed" && api.detail.status === "payment_failed"
        && api.detail.op_lock && !api.detail.op_lock.token, record.list_item);
    check("3 ?status=paid does not contain the run", !record.list_status_paid_ids.includes(runId), record.list_status_paid_ids);
    check("3 audit-check flags the run as a critical incomplete payment",
      record.audit_issues.some((i) => i.severity === "critical" && i.message.includes(created.number)), record.audit_issues);
    check("3 second mark-paid / reopen / PATCH -> 409",
      api.mark_paid_again.status === 409 && api.reopen.status === 409 && api.patch.status === 409,
      [api.mark_paid_again.status, api.reopen.status, api.patch.status]);
    check("3 no second Outflow (one per employee, written before the failure)",
      record.salary_outflows_before.length === 3 && record.salary_outflows_after === 3,
      { before: record.salary_outflows_before.length, after: record.salary_outflows_after });

    const view = await ctx.newPage();
    await view.setContent(`<html><body style="font:13px monospace;background:#fff;color:#111;padding:16px">
      <h3>Admin session — payment_failed run ${created.number}: list / detail / ?status=paid / audit-check / refused retries / Outflows</h3>
      <pre>${JSON.stringify(record, null, 2).replace(/</g, "&lt;")}</pre></body></html>`);
    await view.screenshot({ path: path.join(OUT, "08_api_payment_failed_not_paid.png"), fullPage: true });
  } catch (e) {
    check("bot ran without error", false, { error: String(e) });
  } finally {
    results.finished_at = new Date().toISOString();
    results.result = failed ? "FAIL" : "PASS";
    fs.writeFileSync(path.join(OUT, "bot_result_payment_failed.json"), JSON.stringify(results, null, 2));
    await browser.close();
    console.log(results.result);
    process.exit(failed ? 1 : 0);
  }
})();

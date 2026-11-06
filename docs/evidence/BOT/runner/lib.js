// Shared bot helpers. Usage: const bot = require('./lib'); await bot.run('name', async (b) => {...});
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const UI = process.env.BOT_UI || 'http://127.0.0.1:3000';
const API = process.env.BOT_API || 'http://127.0.0.1:8001';
const VIEWPORTS = { desktop: { width: 1280, height: 800 }, phone: { width: 390, height: 844 } };

async function run(name, fn, { outDir = process.env.BOT_OUT || '.', sha = '' } = {}) {
  fs.mkdirSync(outDir, { recursive: true });
  const result = { task: name, sha, started: new Date().toISOString(), steps: [] };
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const b = { UI, API, VIEWPORTS, browser, outDir, result, seq: 0,
    async context(vp) {
      const ctx = await browser.newContext({ viewport: VIEWPORTS[vp], deviceScaleFactor: vp === 'phone' ? 2 : 1 });
      const page = await ctx.newPage();
      page.on('pageerror', e => (result.pageErrors ||= []).push(String(e).slice(0, 300)));
      return { ctx, page, vp };
    },
    async shot(page, label) {
      const f = `${String(++b.seq).padStart(2, '0')}_${label}.png`;
      await page.screenshot({ path: path.join(outDir, f) });
      return f;
    },
    // step(label, async () => cond|void, page?) — passes if fn returns !== false and does not throw
    async step(label, fn, page) {
      const s = { step: label, pass: false };
      try { const r = await fn(); s.pass = r !== false; if (r && typeof r === 'object') s.detail = r; }
      catch (e) { s.error = String(e).split('\n')[0].slice(0, 300); }
      if (page) try { s.screenshot = await b.shot(page, label.replace(/\W+/g, '_').slice(0, 40)); } catch {}
      result.steps.push(s); console.log(s.pass ? 'PASS' : 'FAIL', label, s.error || '');
    },
    async login(page, email, password) {
      await page.goto(UI + '/login');
      await page.getByTestId('login-email-input').fill(email);
      await page.getByTestId('login-password-input').fill(password);
      await page.getByTestId('login-submit-button').click();
    },
  };
  try { await fn(b); } finally {
    await browser.close();
    result.passed = result.steps.filter(s => s.pass).length; result.total = result.steps.length;
    result.verdict = result.passed === result.total && result.total > 0 ? 'PASS' : 'FAIL';
    result.finished = new Date().toISOString();
    fs.writeFileSync(path.join(outDir, 'bot_result.json'), JSON.stringify(result, null, 2));
    console.log(`${result.verdict} ${result.passed}/${result.total}`);
  }
  return result;
}
module.exports = { run, UI, API, VIEWPORTS };

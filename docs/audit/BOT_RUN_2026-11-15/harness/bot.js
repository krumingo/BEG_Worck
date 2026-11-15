// Role bots for the BEG_Work demo (deterministic code, no AI).
// One browser context per role; each bot logs in through the real UI and, for
// DURATION_MIN minutes, walks the screens it can reach, opens forms, fills them
// with synthetic data and submits. Everything the frontend sends and receives
// is written to run/fe_*.jsonl for comparison with the backend log and the
// database change log.
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://localhost:8765';
const RUN = '/tmp/claude-0/demo/run';
const DURATION_MIN = Number(process.env.DURATION_MIN || 180);
const SEED = JSON.parse(fs.readFileSync(path.join(RUN, 'seed.json'), 'utf8'));
const END = Date.now() + DURATION_MIN * 60000;

// role → [login, device]. Field roles use a phone, office roles a PC.
const PHONE = devices['iPhone 13'];
const PC = { viewport: { width: 1440, height: 900 } };
const BOTS = [
  ['Admin', PC], ['Accountant', PC], ['Warehousekeeper', PC], ['Viewer', PC],
  ['SiteManager', PC], ['Technician', PHONE], ['Driver', PHONE], ['Worker', PHONE],
];

const SKIP = /изход|logout|смени парола|парола|made with emergent|upgrade|абонамент|stripe|плати с карта|език|^bg$|^en$|изтрий акаунт|reset|възстанов/i;
const OPEN = /^(\+|нов|нова|ново|добави|създай|въведи|регистрирай|заяви|запиши|импорт|сканирай|започни|приключи|check)/i;
const NEXT = /^(напред|следващ|next|продължи)/i;
const NAV = new Set(['Табло','Обекти','СМР и Оферти','Отчети','Персонал','Финанси','Склад','Активи','Справочници','Настройки','Алармы','Аларми','Заявки','Връщания','Профил']);
const SUBMIT = /^(запази|създай|добави|изпрати|потвърди|одобри|приеми|запиши|save|submit|ok|да|продължи|генерирай|приключи|начисли|плати)/i;
const RISKY = /изтрий|анулирай|отхвърли|сторно|архивирай|премахни|delete|cancel/i;

let seed = 1;
function rnd() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
const pick = (a) => a[Math.floor(rnd() * a.length)];
const now = () => Date.now() / 1000;

function writer(name) {
  const s = fs.createWriteStream(path.join(RUN, name), { flags: 'a' });
  return (o) => s.write(JSON.stringify(o) + '\n');
}
const W = { net: writer('fe_network.jsonl'), act: writer('fe_actions.jsonl'), err: writer('fe_errors.jsonl') };

async function fillVisible(page, role) {
  const scope = (await page.$('[role="dialog"]')) ? page.locator('[role="dialog"]').last() : ((await page.$('main')) ? page.locator('main').first() : page.locator('body'));
  const inputs = scope.locator('input:visible, textarea:visible, select:visible');
  const n = Math.min(await inputs.count(), 25);
  let filled = 0;
  for (let i = 0; i < n; i++) {
    const el = inputs.nth(i);
    try {
      const tag = await el.evaluate((e) => e.tagName.toLowerCase());
      const type = ((await el.getAttribute('type')) || '').toLowerCase();
      if (['hidden', 'file', 'submit', 'button', 'password'].includes(type)) continue;
      if (await el.isDisabled()) continue;
      if (tag === 'select') {
        const opts = await el.locator('option').evaluateAll((o) => o.map((x) => x.value).filter((v) => v));
        if (opts.length) { await el.selectOption(pick(opts)); filled++; }
      } else if (type === 'checkbox' || type === 'radio') {
        if (rnd() < 0.5) { await el.check({ timeout: 1000 }).catch(() => {}); filled++; }
      } else if (type === 'number') {
        await el.fill(String(Math.round(1 + rnd() * 99))); filled++;
      } else if (type === 'date') {
        await el.fill(new Date().toISOString().slice(0, 10)); filled++;
      } else if (type === 'email') {
        await el.fill(`bot${Math.floor(rnd() * 1e5)}@example.com`); filled++;
      } else if (type === 'tel') {
        await el.fill('0888' + String(Math.floor(100000 + rnd() * 899999))); filled++;
      } else {
        const v = await el.inputValue().catch(() => '');
        if (!v) { await el.fill(`Бот ${role} ${Math.floor(rnd() * 1000)}`); filled++; }
      }
    } catch (e) { /* element went away */ }
  }
  // Radix/shadcn comboboxes: open and choose an option
  const combos = scope.locator('button[role="combobox"]:visible');
  const cn = Math.min(await combos.count(), 6);
  for (let i = 0; i < cn; i++) {
    try {
      await combos.nth(i).click({ timeout: 1500 });
      const opt = page.locator('[role="option"]:visible');
      const k = await opt.count();
      if (k) { await opt.nth(Math.floor(rnd() * k)).click({ timeout: 1500 }); filled++; }
      else await page.keyboard.press('Escape');
    } catch (e) { await page.keyboard.press('Escape').catch(() => {}); }
  }
  return filled;
}

async function clickByText(page, re, role, kind, allowRisky) {
  const btns = page.locator('button:visible, [role="button"]:visible, a[role="button"]:visible');
  const n = Math.min(await btns.count(), 120);
  const cand = [];
  for (let i = 0; i < n; i++) {
    const t = ((await btns.nth(i).innerText().catch(() => '')) || (await btns.nth(i).getAttribute('aria-label').catch(() => '')) || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 40 || SKIP.test(t) || NAV.has(t)) continue;
    if (!allowRisky && RISKY.test(t)) continue;
    if (re.test(t)) cand.push([i, t]);
  }
  if (!cand.length) return null;
  const [i, t] = pick(cand);
  try {
    if (await btns.nth(i).isDisabled()) return null;
    await btns.nth(i).click({ timeout: 3000 });
    W.act({ t: now(), role, kind, label: t, url: page.url() });
    return t;
  } catch (e) { return null; }
}

async function runBot(browser, role, ctxOpts) {
  const u = SEED.users[role];
  const ctx = await browser.newContext({ ...ctxOpts, extraHTTPHeaders: { 'x-bot-role': role } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  page.on('dialog', (d) => { W.act({ t: now(), role, kind: 'browser-dialog', label: d.message().slice(0, 200), url: page.url() }); d.accept().catch(() => {}); });
  page.on('console', (m) => { if (m.type() === 'error') W.err({ t: now(), role, kind: 'console', text: m.text().slice(0, 400), url: page.url() }); });
  page.on('pageerror', (e) => W.err({ t: now(), role, kind: 'pageerror', text: String(e).slice(0, 400), url: page.url() }));
  await ctx.route('**/*', (r) => {
    const url = r.request().url();
    if (url.startsWith(BASE) || url.startsWith('data:') || url.startsWith('blob:')) return r.continue();
    W.net({ t: now(), role, blocked: true, method: r.request().method(), url: url.slice(0, 200), page: page.url() });
    return r.abort();
  });
  const started = new Map();
  page.on('request', (rq) => { if (rq.url().includes('/api/')) started.set(rq, now()); });
  page.on('requestfinished', async (rq) => {
    if (!rq.url().includes('/api/')) return;
    const resp = await rq.response().catch(() => null);
    let body = null;
    if (resp && resp.status() >= 400) body = (await resp.text().catch(() => '')).slice(0, 300);
    W.net({ t: started.get(rq) || now(), end: now(), role, method: rq.method(), url: rq.url().replace(BASE, '').slice(0, 220),
      status: resp ? resp.status() : null, req: (rq.postData() || '').slice(0, 400), resp: body, page: page.url().replace(BASE, '') });
    started.delete(rq);
  });
  page.on('requestfailed', (rq) => { if (rq.url().includes('/api/')) W.net({ t: started.get(rq) || now(), role, method: rq.method(), url: rq.url().replace(BASE, ''), status: 'FAILED', failure: (rq.failure() || {}).errorText, page: page.url().replace(BASE, '') }); });

  async function login() {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    await page.fill('input[type=email]', u.email);
    await page.fill('input[type=password]', u.password);
    await page.click('button[type=submit]');
    await page.waitForTimeout(4000);
    W.act({ t: now(), role, kind: 'login', label: u.email, url: page.url() });
  }
  await login();
  const visits = new Map();
  let shots = 0;
  while (Date.now() < END) {
    try {
      if (page.url().includes('/login')) await login();
      // 1) choose a screen: least visited link first, with some randomness
      const hrefs = await page.$$eval('a[href^="/"]', (as) => [...new Set(as.map((a) => a.getAttribute('href')))]).catch(() => []);
      const links = hrefs.filter((h) => h && !/logout|login|billing|password/i.test(h));
      if (links.length && rnd() < 0.7) {
        links.sort((a, b) => (visits.get(a) || 0) - (visits.get(b) || 0));
        const h = rnd() < 0.7 ? links[0] : pick(links);
        visits.set(h, (visits.get(h) || 0) + 1);
        await page.goto(BASE + h, { waitUntil: 'domcontentloaded' }).catch(() => {});
        W.act({ t: now(), role, kind: 'visit', label: h, url: page.url() });
        await page.waitForTimeout(1800);
      }
      // 2) act on the screen
      const r = rnd();
      if (r < 0.45) {
        const opened = await clickByText(page, OPEN, role, 'open', false);
        if (opened) {
          await page.waitForTimeout(1200);
          let f = await fillVisible(page, role);
          for (let step = 0; step < 6; step++) {   // multi-step wizards: fill, Напред →, fill …
            const nx = await clickByText(page, NEXT, role, 'next', false);
            if (!nx) break;
            await page.waitForTimeout(700);
            f += await fillVisible(page, role);
          }
          W.act({ t: now(), role, kind: 'fill', label: `${f} полета`, url: page.url() });
          await clickByText(page, SUBMIT, role, 'submit', false);
          await page.waitForTimeout(1800);
          await page.keyboard.press('Escape').catch(() => {});
        }
      } else if (r < 0.65) {
        // open a row / card to reach detail screens
        const rows = page.locator('table tbody tr:visible, [data-testid*="card"]:visible, [data-testid*="row"]:visible');
        const k = await rows.count();
        if (k) { await rows.nth(Math.floor(rnd() * k)).click({ timeout: 3000 }).catch(() => {}); W.act({ t: now(), role, kind: 'open-row', label: String(k), url: page.url() }); await page.waitForTimeout(1500); }
      } else if (r < 0.75) {
        await clickByText(page, /одобри|потвърди|приеми|изпрати|плати|начисли|генерирай|приключи/i, role, 'decide', false);
        await page.waitForTimeout(1500);
      } else if (r < 0.80) {
        await clickByText(page, RISKY, role, 'risky', true);
        await page.waitForTimeout(1200);
        await clickByText(page, SUBMIT, role, 'confirm', true);
        await page.waitForTimeout(1500);
      } else if (r < 0.92) {
        // tabs inside a screen
        const tabs = page.locator('[role="tab"]:visible');
        const k = await tabs.count();
        if (k) { const i = Math.floor(rnd() * k); const t = await tabs.nth(i).innerText().catch(() => ''); await tabs.nth(i).click({ timeout: 2000 }).catch(() => {}); W.act({ t: now(), role, kind: 'tab', label: t.slice(0, 40), url: page.url() }); await page.waitForTimeout(1200); }
      } else {
        // double click on a submit-like button: duplicate protection
        const b = await clickByText(page, OPEN, role, 'open-for-double', false);
        if (b) { await page.waitForTimeout(800); await fillVisible(page, role);
          const s = page.locator('[role="dialog"] button:visible').filter({ hasText: SUBMIT });
          if (await s.count()) { await s.first().dblclick({ timeout: 2000 }).catch(() => {}); W.act({ t: now(), role, kind: 'double-submit', label: 'dblclick', url: page.url() }); }
          await page.waitForTimeout(1800); await page.keyboard.press('Escape').catch(() => {}); }
      }
    } catch (e) {
      W.err({ t: now(), role, kind: 'bot', text: String(e).slice(0, 300), url: page.url() });
      if (shots < 15) { shots++; await page.screenshot({ path: path.join(RUN, `shot_${role}_${shots}.png`) }).catch(() => {}); }
      await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' }).catch(() => {});
    }
  }
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  fs.writeFileSync(path.join(RUN, 'bots_started.json'), JSON.stringify({ start: now(), end: END / 1000, bots: BOTS.map((b) => b[0]) }));
  await Promise.all(BOTS.map(([role, opt], i) => { seed = 1000 + i; return runBot(browser, role, opt).catch((e) => W.err({ t: now(), role, kind: 'bot-fatal', text: String(e).slice(0, 400) })); }));
  await browser.close();
  fs.writeFileSync(path.join(RUN, 'bots_done.json'), JSON.stringify({ done: now() }));
})();

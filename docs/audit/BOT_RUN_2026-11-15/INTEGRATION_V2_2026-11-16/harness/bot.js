// Role bots for the BEG_Work demo (deterministic code, no AI).
// One browser context per role; each bot logs in through the real UI and, for
// DURATION_MIN minutes, walks the screens it can reach, opens forms, fills them
// with synthetic data and submits. Everything the frontend sends and receives
// is written to run/fe_*.jsonl for comparison with the backend log and the
// database change log.
//
// INTEGRATION_V2 (BL-13b) changes against BOT_RUN_2026-11-15/harness/bot.js:
//  1. every action and navigation runs under a hard timeout (ACTION_MS, Promise.race);
//     on a timeout the bot logs `timeout` and recovers by going to the role's home
//     screen; if that also hangs, the page is replaced by a fresh one (and re-login).
//     In run A 6 of 8 bots stalled in the first 30 s: Playwright calls such as
//     innerText()/evaluate()/inputValue() on elements that went away each waited the
//     default timeout, inside loops over up to 120 buttons / 25 inputs.
//  2. button texts are read in ONE evaluateAll per screen (no per-element waits);
//     element reads use a short per-call timeout.
//  3. one PRNG per role, seeded from the role name (run A shared one global seed
//     between 8 concurrent bots, so the run was not reproducible — Codex review).
//  4. every action gets an id; every /api request the page makes while that action
//     runs carries `x-correlation-id: <role>:<n>:<kind>` (added in the route handler);
//     serve.py logs it, so screen ↔ server is joined by id, not by a time window.
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BOT_BASE || 'http://localhost:8768';
const RUN = process.env.BOT_RUN || '/tmp/claude-0/demo_int2/ui/run';
const DURATION_MIN = Number(process.env.DURATION_MIN || 30);
const ACTION_MS = Number(process.env.ACTION_MS || 15000);
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
const BTN_SEL = 'button:visible, [role="button"]:visible, a[role="button"]:visible';

// Deterministic per-role PRNG (mulberry32, 32-bit integer math), seed = FNV-1a of the role
// name. Run A's LCG `(s * 1103515245 + 12345) % 2^31` loses precision once s is large
// (the product exceeds 2^53), so its sequence was not a proper LCG either.
function seedOf(role) { let h = 2166136261; for (const ch of role) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; } return h; }
function mkRng(role) {
  let s = seedOf(role);
  const rnd = () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return { rnd, pick: (a) => a[Math.floor(rnd() * a.length)] };
}
const now = () => Date.now() / 1000;

function writer(name) {
  const s = fs.createWriteStream(path.join(RUN, name), { flags: 'a' });
  return (o) => s.write(JSON.stringify(o) + '\n');
}
const W = { net: writer('fe_network.jsonl'), act: writer('fe_actions.jsonl'), err: writer('fe_errors.jsonl') };

class Timeout extends Error {}
function withTimeout(p, ms, label) {
  let h;
  const t = new Promise((_, rej) => { h = setTimeout(() => rej(new Timeout(`timeout ${ms}ms: ${label}`)), ms); });
  return Promise.race([Promise.resolve(p), t]).finally(() => clearTimeout(h));
}

async function runBot(browser, role, ctxOpts) {
  const u = SEED.users[role];
  const { rnd, pick } = mkRng(role);
  // serviceWorkers 'block': the PWA service worker must not fetch /api past the route
  // handler below (its requests would carry no correlation id)
  const ctx = await browser.newContext({ ...ctxOpts, serviceWorkers: 'block', extraHTTPHeaders: { 'x-bot-role': role } });
  let seq = 0;
  let corr = `${role}:0:login`;
  let page = null;
  let home = BASE + '/';
  let lastAct = Date.now();
  const act = (kind, label) => { lastAct = Date.now(); W.act({ t: now(), role, kind, label, url: page ? page.url() : '', corr }); };

  await ctx.route('**/*', (r) => {
    const url = r.request().url();
    if (url.startsWith(BASE) && url.includes('/api/')) {
      return r.continue({ headers: { ...r.request().headers(), 'x-correlation-id': corr } }).catch(() => {});
    }
    if (url.startsWith(BASE) || url.startsWith('data:') || url.startsWith('blob:')) return r.continue().catch(() => {});
    W.net({ t: now(), role, blocked: true, method: r.request().method(), url: url.slice(0, 200), page: page ? page.url() : '' });
    return r.abort().catch(() => {});
  });

  async function newPage() {
    if (page) await withTimeout(page.close(), 5000, 'close').catch(() => {});
    const p = await ctx.newPage();
    p.setDefaultTimeout(4000);
    p.setDefaultNavigationTimeout(12000);
    p.on('dialog', (d) => { W.act({ t: now(), role, kind: 'browser-dialog', label: d.message().slice(0, 200), url: p.url(), corr }); d.accept().catch(() => {}); });
    p.on('console', (m) => { if (m.type() === 'error') W.err({ t: now(), role, kind: 'console', text: m.text().slice(0, 400), url: p.url(), corr }); });
    p.on('pageerror', (e) => W.err({ t: now(), role, kind: 'pageerror', text: String(e).slice(0, 400), url: p.url(), corr }));
    const started = new Map();
    p.on('request', (rq) => { if (rq.url().includes('/api/')) started.set(rq, [now(), rq.headers()['x-correlation-id'] || corr]); });
    p.on('requestfinished', async (rq) => {
      if (!rq.url().includes('/api/')) return;
      const resp = await rq.response().catch(() => null);
      let body = null;
      if (resp && resp.status() >= 400) body = (await resp.text().catch(() => '')).slice(0, 300);
      const [t0, c] = started.get(rq) || [now(), corr];
      W.net({ t: t0, end: now(), role, corr: c, method: rq.method(), url: rq.url().replace(BASE, '').slice(0, 220),
        status: resp ? resp.status() : null, req: (rq.postData() || '').slice(0, 400), resp: body, page: p.url().replace(BASE, '') });
      started.delete(rq);
    });
    p.on('requestfailed', (rq) => {
      if (!rq.url().includes('/api/')) return;
      const [t0, c] = started.get(rq) || [now(), corr];
      W.net({ t: t0, role, corr: c, method: rq.method(), url: rq.url().replace(BASE, ''), status: 'FAILED', failure: (rq.failure() || {}).errorText, page: p.url().replace(BASE, '') });
      started.delete(rq);
    });
    page = p;
  }

  async function login() {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    await page.fill('input[type=email]', u.email);
    await page.fill('input[type=password]', u.password);
    await page.click('button[type=submit]');
    await page.waitForTimeout(4000);
    if (!page.url().includes('/login')) home = page.url();
    act('login', u.email);
  }

  async function fillVisible() {
    const scope = (await page.$('[role="dialog"]')) ? page.locator('[role="dialog"]').last() : ((await page.$('main')) ? page.locator('main').first() : page.locator('body'));
    const inputs = scope.locator('input:visible, textarea:visible, select:visible');
    const n = Math.min(await inputs.count(), 25);
    let filled = 0;
    for (let i = 0; i < n; i++) {
      const el = inputs.nth(i);
      try {
        const [tag, type, disabled, value] = await el.evaluate((e) => [e.tagName.toLowerCase(), (e.getAttribute('type') || '').toLowerCase(), !!e.disabled, e.value || ''], null, { timeout: 1000 });
        if (['hidden', 'file', 'submit', 'button', 'password'].includes(type) || disabled) continue;
        if (tag === 'select') {
          const opts = await el.locator('option').evaluateAll((o) => o.map((x) => x.value).filter((v) => v));
          if (opts.length) { await el.selectOption(pick(opts), { timeout: 1500 }); filled++; }
        } else if (type === 'checkbox' || type === 'radio') {
          if (rnd() < 0.5) { await el.check({ timeout: 1000 }).catch(() => {}); filled++; }
        } else if (type === 'number') {
          await el.fill(String(Math.round(1 + rnd() * 99)), { timeout: 1500 }); filled++;
        } else if (type === 'date') {
          await el.fill(new Date().toISOString().slice(0, 10), { timeout: 1500 }); filled++;
        } else if (type === 'email') {
          await el.fill(`bot${Math.floor(rnd() * 1e5)}@example.com`, { timeout: 1500 }); filled++;
        } else if (type === 'tel') {
          await el.fill('0888' + String(Math.floor(100000 + rnd() * 899999)), { timeout: 1500 }); filled++;
        } else if (!value) {
          await el.fill(`Бот ${role} ${Math.floor(rnd() * 1000)}`, { timeout: 1500 }); filled++;
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

  async function clickByText(re, kind, allowRisky) {
    const btns = page.locator(BTN_SEL);
    // one read for all labels (run A read each label with its own wait → minutes per screen)
    const labels = await btns.evaluateAll((els) => els.slice(0, 120).map((e) => ((e.innerText || e.getAttribute('aria-label') || '') + '').trim().replace(/\s+/g, ' ')));
    const cand = [];
    labels.forEach((t, i) => {
      if (!t || t.length > 40 || SKIP.test(t) || NAV.has(t)) return;
      if (!allowRisky && RISKY.test(t)) return;
      if (re.test(t)) cand.push([i, t]);
    });
    if (!cand.length) return null;
    const [i, t] = pick(cand);
    try {
      if (await btns.nth(i).isDisabled({ timeout: 1000 })) return null;
      await btns.nth(i).click({ timeout: 3000 });
      act(kind, t);
      return t;
    } catch (e) { return null; }
  }

  // one step of the walk; each call below runs under withTimeout(ACTION_MS)
  const visits = new Map();
  const known = new Set();
  async function visitStep() {
    // the PC sidebar keeps its screens in collapsed groups (Обекти, Персонал, Финанси, Склад …):
    // their links are not in the DOM until the group is opened. Run A only saw the 4-6 links of
    // the open group. Open one or two groups (the toggle itself is not counted as an action).
    if (rnd() < 0.6) {
      const navBtns = page.locator('button:visible');
      const labels = await navBtns.evaluateAll((els) => els.slice(0, 60).map((e) => (e.innerText || '').trim()));
      const groups = labels.map((t, i) => [i, t]).filter(([, t]) => NAV.has(t));
      for (let k = 0; k < Math.min(2, groups.length); k++) {
        const [i, t] = pick(groups);
        await navBtns.nth(i).click({ timeout: 1500 }).catch(() => {});
        W.act({ t: now(), role, kind: 'menu', label: t, url: page.url(), corr });
        await page.waitForTimeout(300);
      }
    }
    const hrefs = await page.$$eval('a[href^="/"]', (as) => [...new Set(as.map((a) => a.getAttribute('href')))]).catch(() => []);
    let links = hrefs.filter((h) => h && !/logout|login|billing|password/i.test(h));
    links.forEach((h) => known.add(h));
    // dead-end screens (no links, e.g. /assets/batch-intake, a scanner overlay): run A's bots
    // stayed there for the whole run, every step finding nothing to do. Use the links seen before.
    // least-visited first over every link seen so far (also on dead ends)
    links = [...known];
    if (!(links.length && rnd() < 0.7)) return;
    links.sort((a, b) => (visits.get(a) || 0) - (visits.get(b) || 0));
    const h = rnd() < 0.7 ? links[0] : pick(links);
    visits.set(h, (visits.get(h) || 0) + 1);
    await page.goto(BASE + h, { waitUntil: 'domcontentloaded' }).catch(() => {});
    act('visit', h);
    await page.waitForTimeout(1800);
  }
  async function actStep() {
    const r = rnd();
    if (r < 0.45) {
      const opened = await clickByText(OPEN, 'open', false);
      if (opened) {
        await page.waitForTimeout(1200);
        let f = await fillVisible();
        for (let step = 0; step < 6; step++) {   // multi-step wizards: fill, Напред →, fill …
          const nx = await clickByText(NEXT, 'next', false);
          if (!nx) break;
          await page.waitForTimeout(700);
          f += await fillVisible();
        }
        act('fill', `${f} полета`);
        await clickByText(SUBMIT, 'submit', false);
        await page.waitForTimeout(1800);
        await page.keyboard.press('Escape').catch(() => {});
      }
    } else if (r < 0.65) {
      // open a row / card to reach detail screens
      const rows = page.locator('table tbody tr:visible, [data-testid*="card"]:visible, [data-testid*="row"]:visible');
      const k = await rows.count();
      if (k) { await rows.nth(Math.floor(rnd() * k)).click({ timeout: 3000 }).catch(() => {}); act('open-row', String(k)); await page.waitForTimeout(1500); }
    } else if (r < 0.75) {
      await clickByText(/одобри|потвърди|приеми|изпрати|плати|начисли|генерирай|приключи/i, 'decide', false);
      await page.waitForTimeout(1500);
    } else if (r < 0.80) {
      await clickByText(RISKY, 'risky', true);
      await page.waitForTimeout(1200);
      await clickByText(SUBMIT, 'confirm', true);
      await page.waitForTimeout(1500);
    } else if (r < 0.92) {
      // tabs inside a screen
      const tabs = page.locator('[role="tab"]:visible');
      const k = await tabs.count();
      if (k) { const i = Math.floor(rnd() * k); const t = await tabs.nth(i).innerText({ timeout: 1000 }).catch(() => ''); await tabs.nth(i).click({ timeout: 2000 }).catch(() => {}); act('tab', t.slice(0, 40)); await page.waitForTimeout(1200); }
    } else {
      // double click on a submit-like button: duplicate protection
      const b = await clickByText(OPEN, 'open-for-double', false);
      if (b) {
        await page.waitForTimeout(800); await fillVisible();
        const s = page.locator('[role="dialog"] button:visible').filter({ hasText: SUBMIT });
        if (await s.count()) { await s.first().dblclick({ timeout: 2000 }).catch(() => {}); act('double-submit', 'dblclick'); }
        await page.waitForTimeout(1800); await page.keyboard.press('Escape').catch(() => {});
      }
    }
  }

  let shots = 0;
  async function recover(e) {
    W.err({ t: now(), role, kind: e instanceof Timeout ? 'timeout' : 'bot', text: String(e).slice(0, 300), url: page ? page.url() : '', corr });
    if (shots < 15) { shots++; await withTimeout(page.screenshot({ path: path.join(RUN, `shot_${role}_${shots}.png`) }), 5000, 'shot').catch(() => {}); }
    corr = `${role}:${++seq}:recover`;
    try {
      await withTimeout(page.goto(home, { waitUntil: 'domcontentloaded' }), ACTION_MS, 'recover-home');
      act('recover', home.replace(BASE, ''));
    } catch (e2) {
      W.err({ t: now(), role, kind: 'page-replaced', text: String(e2).slice(0, 300), url: '', corr });
      await withTimeout(newPage(), ACTION_MS, 'new-page').catch(() => {});
      await withTimeout(login(), 30000, 'relogin').catch(() => {});
    }
  }

  await newPage();
  await withTimeout(login(), 30000, 'login').catch(recover);
  while (Date.now() < END) {
    for (const [kind, fn] of [['visit', visitStep], ['act', actStep]]) {
      if (Date.now() >= END) break;
      corr = `${role}:${++seq}:${kind}`;
      try {
        if (page.url().includes('/login')) await withTimeout(login(), 30000, 'relogin');
        await withTimeout(fn(), ACTION_MS, kind);
        // no logged action for 2×ACTION_MS although every step returned: a dead end
        if (Date.now() - lastAct > 2 * ACTION_MS) throw new Timeout(`idle ${2 * ACTION_MS}ms (no action possible) at ${page.url().replace(BASE, '')}`);
      } catch (e) { await recover(e); }
    }
    await page.waitForTimeout(300).catch(() => {});   // no busy loop on an empty screen
  }
  corr = `${role}:${++seq}:end`;
  await withTimeout(ctx.close(), 10000, 'ctx-close').catch(() => {});
}

(async () => {
  const browser = await chromium.launch();
  // added after the run (see README §3): if the browser dies, stop — otherwise every call fails
  // at once and recover() loops without a pause (an aborted trial wrote 0.9 GB of errors).
  browser.on('disconnected', () => { if (Date.now() < END) { W.err({ t: now(), role: '-', kind: 'bot-fatal', text: 'browser disconnected' }); process.exit(2); } });
  fs.writeFileSync(path.join(RUN, 'bots_started.json'), JSON.stringify({ start: now(), end: END / 1000, action_ms: ACTION_MS, bots: BOTS.map((b) => [b[0], seedOf(b[0])]) }));
  await Promise.all(BOTS.map(([role, opt]) => runBot(browser, role, opt).catch((e) => W.err({ t: now(), role, kind: 'bot-fatal', text: String(e).slice(0, 400) }))));
  await withTimeout(browser.close(), 20000, 'browser-close').catch(() => {});
  fs.writeFileSync(path.join(RUN, 'bots_done.json'), JSON.stringify({ done: now() }));
  process.exit(0);
})();

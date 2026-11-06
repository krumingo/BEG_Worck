// BOT RC-01 @44c9c3c — build identity. Needs stack from README (ENV=test, UI :3000 built with the SHA, UI :3001 built without build info).
const { execFileSync } = require('child_process');
const bot = require('../runner/lib');
const WT = '/tmp/botwt/44c9c3c', CTL = __dirname + '/../backend_ctl.sh';
const git = (...a) => execFileSync('git', ['-C', WT, ...a]).toString().trim();
const SHA = git('rev-parse', 'HEAD'), PREV = git('rev-parse', 'HEAD~1'), S12 = SHA.slice(0, 12);
const stamp = (commit) => execFileSync('python3', [WT + '/ops/release/write_build_info.py', '--commit', commit, '--target', WT]).toString();
const restart = () => execFileSync(CTL, [WT, 'ENV=test']).toString();
const UI2 = 'http://127.0.0.1:3001';
const ver = async () => (await fetch(bot.API + '/api/version')).json();
const noHScroll = (p) => p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);
const ident = async (p) => ({ status: await p.getByTestId('build-identity').first().getAttribute('data-build-status'), text: (await p.getByTestId('build-sha').first().innerText()).trim(), title: await p.getByTestId('build-sha').first().getAttribute('title'), env: (await p.getByTestId('build-env').first().innerText().catch(() => '')).trim() });
async function openMenuAndGet(p) { await p.getByTestId('mobile-menu-toggle').click(); await p.waitForTimeout(500); }

bot.run('RC-01', async (b) => {
  b.result.facts = { head: SHA, prev: PREV };
  stamp(SHA); restart();
  // --- 1/2 match ---
  const v = await ver(); b.result.version_json_match = v;
  await b.step('2 /api/version returns the same full SHA as the build (no auth)', async () => ({ ok: v.build_sha === SHA, json: v }));
  await b.step('2b /api/version has exactly the allowed keys, no secrets/paths/host', async () => { const k = Object.keys(v).sort().join(','); return { ok: k === 'build_sha,build_time,environment_label,source' && v.environment_label === 'test', keys: k }; });
  for (const [vp, tag] of [['desktop', '1280'], ['phone', '390']]) {
    const { ctx, page } = await b.context(vp);
    await page.goto(b.UI + '/login'); await page.getByTestId('build-identity').waitFor(); await page.waitForTimeout(800);
    await b.step(`1 [${tag}] login screen shows first 12 chars, full SHA in tooltip, status=match`, async () => { const i = await ident(page); return { ok: i.text.includes(S12) && !i.text.includes(SHA) && i.title === SHA && i.status === 'match', ...i }; }, page);
    if (vp === 'phone') await b.step('5 [390] login: no horizontal scroll', async () => noHScroll(page), page);
    await b.login(page, 'admin@bot-a.test', 'BotPass-12345!'); await page.getByTestId('main-content').waitFor(); await page.waitForTimeout(1200);
    if (vp === 'desktop') {
      await b.step('1 [1280] menu (sidebar bottom) shows first 12 chars + full SHA tooltip', async () => { const i = await ident(page); return { ok: i.text.includes(S12) && i.title === SHA && i.status === 'match', ...i }; }, page);
    } else {
      await openMenuAndGet(page);
      await b.step('1 [390] mobile menu footer shows first 12 chars + full SHA tooltip', async () => { const i = await ident(page); return { ok: i.text.includes(S12) && i.title === SHA && i.status === 'match', ...i }; }, page);
      await b.step('5 [390] menu open: no horizontal scroll', async () => noHScroll(page), page);
      await page.keyboard.press('Escape'); await page.waitForTimeout(300);
      await b.step('5 [390] dashboard: no horizontal scroll', async () => noHScroll(page), page);
    }
    await ctx.close();
  }
  // --- 3 mismatch: backend built from another SHA ---
  stamp(PREV); restart(); const v2 = await ver(); b.result.version_json_mismatch = v2;
  await b.step('3.0 backend now reports a different SHA (HEAD~1)', async () => ({ ok: v2.build_sha === PREV && v2.build_sha !== SHA, server: v2.build_sha }));
  for (const [vp, tag] of [['desktop', '1280'], ['phone', '390']]) {
    const { ctx, page } = await b.context(vp);
    await page.goto(b.UI + '/login'); await page.getByTestId('build-identity').waitFor(); await page.waitForTimeout(1200);
    await b.step(`3 [${tag}] login: mismatch warning visible („Версията на интерфейса и сървъра се различава“) + server 12 chars`, async () => { const w = page.getByTestId('build-warning-mismatch'); const t = (await w.innerText()).replace(/\s+/g, ' '); const i = await ident(page); return { ok: await w.isVisible() && t.includes('Версията на интерфейса и сървъра се различава') && t.includes(PREV.slice(0, 12)) && i.status === 'mismatch', warning: t, ...i }; }, page);
    if (vp === 'phone') await b.step('5 [390] mismatch warning: no horizontal scroll', async () => noHScroll(page), page);
    await b.login(page, 'admin@bot-a.test', 'BotPass-12345!'); await page.getByTestId('main-content').waitFor(); await page.waitForTimeout(1200);
    if (vp === 'phone') await openMenuAndGet(page);
    await b.step(`3 [${tag}] after login the menu shows the mismatch warning too`, async () => ({ ok: await page.locator('[data-testid=build-warning-mismatch]:visible').count().then(n => n > 0) }), page);
    if (vp === 'phone') await b.step('5 [390] menu with warning: no horizontal scroll', async () => noHScroll(page), page);
    await ctx.close();
  }
  // --- 4 unknown ---
  execFileSync('rm', ['-f', WT + '/backend/BUILD_INFO.json']); restart(); const v3 = await ver(); b.result.version_json_unknown_backend = v3;
  await b.step('4a no build info on the backend: /api/version build_sha = "unknown", source none', async () => ({ ok: v3.build_sha === 'unknown' && v3.source === 'none', json: v3 }));
  for (const [vp, tag] of [['desktop', '1280'], ['phone', '390']]) {
    const { ctx, page } = await b.context(vp);
    await page.goto(b.UI + '/login'); await page.getByTestId('build-identity').waitFor(); await page.waitForTimeout(1200);
    await b.step(`4b [${tag}] frontend has SHA, backend unknown: status=unknown + "Непотвърдена версия" warning`, async () => { const i = await ident(page); const w = page.getByTestId('build-warning-unknown'); return { ok: i.status === 'unknown' && await w.isVisible(), warning: (await w.innerText().catch(() => '')).replace(/\s+/g, ' '), ...i }; }, page);
    await page.goto(UI2 + '/login'); await page.getByTestId('build-identity').waitFor(); await page.waitForTimeout(1200);
    await b.step(`4c [${tag}] no build info on frontend AND backend: UI shows "unknown"`, async () => { const i = await ident(page); return { ok: i.text.includes('unknown') && i.status === 'unknown' && i.title === 'unknown', ...i }; }, page);
    if (vp === 'phone') await b.step('5 [390] unknown state: no horizontal scroll', async () => noHScroll(page), page);
    await ctx.close();
  }
  stamp(SHA); restart();
}, { outDir: process.env.BOT_OUT, sha: process.env.BOT_SHA });

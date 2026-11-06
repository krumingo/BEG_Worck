// Smoke: login -> dashboard -> logout at 1280 and 390x844.
const bot = require('./lib');
const EMAIL = 'admin@bot-a.test', PASS = 'BotPass-12345!';
bot.run('RUNNER-smoke', async (b) => {
  for (const vp of ['desktop', 'phone']) {
    const { ctx, page } = await b.context(vp);
    const tag = vp === 'desktop' ? '1280' : '390';
    await b.step(`${tag} login page renders`, async () => { await page.goto(b.UI + '/login'); await page.getByTestId('login-card').waitFor({ timeout: 15000 }); }, page);
    await b.step(`${tag} login succeeds and leaves /login`, async () => {
      await b.login(page, EMAIL, PASS);
      await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 });
    }, page);
    await b.step(`${tag} dashboard shows authenticated layout`, async () => {
      await page.getByTestId('main-content').waitFor({ timeout: 15000 });
      return !page.url().includes('/login');
    }, page);
    await b.step(`${tag} logout returns to /login`, async () => {
      if (vp === 'desktop') await page.getByTestId('logout-button').click();
      else { await page.getByTestId('mobile-menu-toggle').click(); await page.getByTestId('mobile-logout').click(); }
      await page.waitForURL(/\/login/, { timeout: 15000 });
    }, page);
    await ctx.close();
  }
}, { outDir: process.env.BOT_OUT, sha: process.env.BOT_SHA });

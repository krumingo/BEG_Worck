// BOT LAB-02 @ 0c85678 — quantity entry + approval and the piece rate per SMR (R33). Synthetic data, 390x844.
const { execFileSync } = require('child_process');
const bot = require('../runner/lib');
const API = bot.API, PW = 'BotPass-12345!';
const mongo = (db, js) => execFileSync('docker', ['exec', 'botmongo', 'mongosh', '--quiet', db, '--eval', js]).toString().trim();
const jq = (db, js) => JSON.parse(mongo(db, `JSON.stringify(${js})`));
async function http(method, path, token, body, headers = {}) {
  const r = await fetch(API + '/api' + path, { method, headers: { 'content-type': 'application/json', ...(token ? { authorization: 'Bearer ' + token } : {}), ...headers }, body: body ? JSON.stringify(body) : undefined });
  let j = null; try { j = await r.json(); } catch {}
  return { status: r.status, body: j };
}
const login = async (e) => (await http('POST', '/auth/login', null, { email: e, password: PW })).body.token;
const idem = () => ({ 'Idempotency-Key': 'bot-' + Date.now() + '-' + Math.random().toString(36).slice(2) });
const LATIN_OK = new Set(['EUR', 'BEG', 'Work', 'VIT', 'Emergent', 'Made', 'with']);

bot.run('LAB02-0c85678', async (b) => {
  const S = {};
  const phone = async (email) => { const c = await b.context('phone'); await b.login(c.page, email, PW); await c.page.waitForTimeout(1500); return c; };
  const noH = (p) => p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  // Everything on screen in Bulgarian: Latin words (3+ letters) other than a short allow-list are listed
  const bg = async (p, scope = 'main') => { const t = (await p.locator(scope).first().innerText().catch(() => '')) || ''; const words = [...new Set((t.match(/[A-Za-z]{3,}/g) || []).filter(w => !LATIN_OK.has(w)))]; return { latin_words: words, chars: t.length, cyrillic: (t.match(/[А-Яа-я]/g) || []).length }; };

  // ---------- seed (real API; synthetic direct inserts where no API exists) ----------
  const admin = await login('admin@bot-a.test'); const me = (await http('GET', '/auth/me', admin)).body; const org = me.org_id || me.user?.org_id;
  mongo('bot_op', `db.feature_flags.updateMany({org_id:'${org}'},{$set:{enabled:true}})`);
  for (const [e, r, f] of [['acct@bot-a.test', 'Accountant', 'Счетоводител'], ['sm@bot-a.test', 'SiteManager', 'Ръководител'], ['worker@bot-a.test', 'Technician', 'Иван']]) await http('POST', '/users', admin, { email: e, password: PW, first_name: f, last_name: 'Бот', role: r });
  const users = (await http('GET', '/users', admin)).body; const uid = (e) => users.find(u => u.email === e).id;
  S.P = (await http('POST', '/projects', admin, { code: 'VIT', name: 'Обект Витоша' })).body.id; S.worker = uid('worker@bot-a.test'); S.sm = uid('sm@bot-a.test');
  await http('POST', `/projects/${S.P}/team`, admin, { user_id: S.sm, role_in_project: 'SiteManager' }); await http('POST', `/projects/${S.P}/team`, admin, { user_id: S.worker, role_in_project: 'Technician' });
  S.today = new Date().toISOString().slice(0, 10);
  mongo('bot_op', `db.employee_profiles.insertOne({org_id:'${org}',user_id:'${S.worker}',pay_type:'Akord',hourly_rate:15});db.execution_packages.insertOne({id:'pkg-sh',org_id:'${org}',project_id:'${S.P}',activity_name:'Шпакловка',unit:'м2',qty:400});db.activity_budgets.insertOne({id:'ab1',org_id:'${org}',project_id:'${S.P}',type:'Шпакловка'});db.attendance_entries.insertOne({id:'att1',org_id:'${org}',date:'${S.today}',user_id:'${S.worker}',project_id:'${S.P}',status:'Present'})`);
  const tk = { admin, acct: await login('acct@bot-a.test'), sm: await login('sm@bot-a.test'), worker: await login('worker@bot-a.test') };
  const draft = await http('POST', '/technician/daily-report', tk.worker, { project_id: S.P, date: S.today, entries: [{ worker_id: S.worker, worker_name: 'Иван Бот', smr_type: 'Шпакловка', hours: 8 }] });
  S.reportId = jq('bot_op', `db.employee_daily_reports.find({worker_id:'${S.worker}',date:'${S.today}'},{_id:0,id:1}).toArray()[0].id`);
  await b.step('0 seed: tenant, Accountant, SiteManager of the project, Technician-worker on akord, SMR „Шпакловка“ (м2), the worker\'s draft report of 8 h (8 attendance Present)', async () => ({ ok: draft.status === 200 && !!S.reportId, draft: draft.status, report_id: S.reportId }));
  const pay = async () => { const r = await http('GET', `/pay-runs/generate?period_start=${S.today}&period_end=${S.today}`, tk.admin); const row = (r.body?.rows || []).find(x => x.employee_id === S.worker); return { status: r.status, row }; };
  const quantityDoc = () => jq('bot_op', `db.employee_daily_reports.find({id:'${S.reportId}'},{_id:0,quantity:1,status:1,approval_status:1,report_version:1,hours:1}).toArray()[0]`);

  // ---------- 1. Finance sets the piece rate on the SMR ----------
  { const c = await phone('acct@bot-a.test'); const p = c.page;
    await p.goto(b.UI + '/labor-quantities'); await p.getByTestId('labor-quantities-page').waitFor(); await p.getByTestId('lt-paytype').first().waitFor({ timeout: 15000 });
    const tabsText = (await p.locator('main').innerText()).replace(/\s+/g, ' ');
    await b.step('1.1 [390 Счетоводител] screen „Количества и акорд“ opens with the tab „Акордни цени“ and no approval tab; the SMR „Шпакловка“ is listed', async () => ({ ok: /Акордни цени/.test(tabsText) && !/За одобрение/.test(tabsText) && /Шпакловка/.test(tabsText), excerpt: tabsText.slice(0, 160) }), p);
    await p.getByTestId('lt-paytype').first().selectOption('Akord'); await p.getByTestId('lt-rate').first().fill('5'); await p.getByPlaceholder('Основание (договор, анекс…)').first().fill('Анекс № 1');
    await p.screenshot({ path: b.outDir + '/01a_accountant_piece_rate_filled.png' });
    await p.getByTestId('lt-save').first().click(); await p.getByText('версия 1').first().waitFor({ timeout: 10000 });
    const terms = await http('GET', `/labor-terms?project_id=${S.P}`, tk.acct); const t0 = (terms.body?.items || [])[0];
    await b.step('1.2 [390 Счетоводител] sets Akord 5 EUR / м2 on „Шпакловка“ with a reason → „версия 1“; the API holds pay type Akord, rate 5, version 1', async () => ({ ok: t0?.labor_pay_type === 'Akord' && Number(t0?.labor_piece_rate) === 5 && Number(t0?.labor_terms_version) === 1, pay_type: t0?.labor_pay_type, rate: t0?.labor_piece_rate, version: t0?.labor_terms_version, audit_events: jq('bot_op', `db.audit_events.countDocuments({action:'labor_terms.set'})`) }), p);
    const nl = await bg(p); await b.step('1.3 [390] the finance screen is in Bulgarian and has no horizontal scroll', async () => ({ ok: nl.latin_words.length === 0 && await noH(p), no_hscroll: await noH(p), ...nl }));
    const smTerms = await http('GET', `/labor-terms?project_id=${S.P}`, tk.sm); const wTerms = await http('GET', `/labor-terms?project_id=${S.P}`, tk.worker);
    await b.step('1.4 (R31) the SiteManager and the worker cannot read piece rates: both 403', async () => ({ ok: smTerms.status === 403 && wTerms.status === 403, sm: smTerms.status, worker: wTerms.status }));
    await c.ctx.close(); }

  // ---------- 2. The worker enters 120 m2 in the daily report ----------
  { const c = await phone('worker@bot-a.test'); const p = c.page;
    await p.getByText('Обекти', { exact: true }).first().click(); await p.getByText(/Витоша/).first().click(); await p.locator('button:has(svg.lucide-pencil)').first().waitFor({ timeout: 15000 });
    await p.locator('button:has(svg.lucide-pencil)').first().click(); await p.getByTestId('draft-quantity').waitFor();
    await p.getByTestId('draft-quantity').fill('120'); await p.screenshot({ path: b.outDir + '/02a_worker_draft_quantity_120.png' });
    const edTxt = (await p.locator('body').innerText()).replace(/\s+/g, ' ');
    await p.getByRole('button', { name: 'Запази' }).click(); await p.getByText('Черновата е обновена').first().waitFor({ timeout: 10000 }).catch(() => {});
    const q = await quantityDoc();
    await b.step('2.1 [390 worker] in the draft editor „Изработено количество (м2, бр., м…)“ he enters 120 and saves → „Черновата е обновена“; the report holds quantity 120', async () => ({ ok: Number(q.quantity) === 120 && /Изработено количество/.test(edTxt), quantity: q.quantity, status: q.status || q.approval_status }), p);
    const nl = await bg(p, 'body'); await b.step('2.2 [390 worker] the technician screen with the quantity field: Bulgarian, no horizontal scroll', async () => ({ ok: nl.latin_words.length === 0 && await noH(p), no_hscroll: await noH(p), ...nl }));
    await c.ctx.close(); }

  // ---------- 3. The SiteManager approves ----------
  const ap = await http('POST', `/daily-reports/${S.reportId}/approve`, tk.sm, {});
  await b.step('3.0 the SiteManager approves the daily report itself (API — the approval list of reports has no phone path in this bot) → APPROVED', async () => ({ ok: ap.status === 200, status: ap.status, report_status: (await quantityDoc())?.status }));
  { const c = await phone('sm@bot-a.test'); const p = c.page;
    await p.goto(b.UI + '/labor-quantities'); await p.getByTestId('labor-quantities-page').waitFor(); await p.getByTestId(`lq-item-${S.reportId}`).waitFor({ timeout: 15000 });
    const txt = (await p.getByTestId(`lq-item-${S.reportId}`).innerText()).replace(/\s+/g, ' ');
    await b.step('3.1 [390 SiteManager] sees the worker\'s line: „Въведено от работника: 120“, SMR „Шпакловка (м2)“, no piece-rate tab', async () => ({ ok: /Въведено от работника:\s*120/.test(txt) && !/Акордни цени/.test(await p.locator('main').innerText()), line: txt.slice(0, 200) }), p);
    await p.getByTestId('lq-approve').click(); const toastShown = await p.getByText('Количеството е одобрено').first().waitFor({ timeout: 3000 }).then(() => true).catch(() => false); const toastEls = await p.locator('[data-sonner-toast]').count(); await p.getByText(/одобрено: 120 м2/).first().waitFor({ timeout: 10000 });
    const after = (await p.locator('main').innerText()).replace(/\s+/g, ' ');
    await b.step('3.2 [390 SiteManager] „Одобри количеството“ → „одобрено: 120 м2“ and NO price is shown to him (R31)', async () => ({ ok: /одобрено: 120 м2/.test(after) && !/× 5|= 600|600/.test(after), excerpt: (after.match(/.{0,40}одобрено: 120.{0,40}/) || [''])[0] }), p);
    await b.step('3.2b [390 SiteManager] the success message „Количеството е одобрено“ is shown to the user after approving', async () => ({ ok: toastShown, message_visible: toastShown, toast_elements_on_page: toastEls, note: 'screens call toast() from sonner; no <Toaster/> is mounted anywhere in the app (also on main), so none of the messages of this screen can be seen' }), p);
    const nl = await bg(p); await b.step('3.3 [390 SiteManager] the approval screen is in Bulgarian and has no horizontal scroll', async () => ({ ok: nl.latin_words.length === 0 && await noH(p), no_hscroll: await noH(p), ...nl }));
    const pendSm = (await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.sm)).body, pendFin = (await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.admin)).body;
    await b.step('3.4 the approval is stored with the SMR terms snapshot: 120 м2, rate 5 for finance; the SiteManager\'s response carries no piece_rate', async () => { const it = (pendFin.items || []).find(i => i.report_id === S.reportId), is = (pendSm.items || []).find(i => i.report_id === S.reportId); return { ok: Number(it?.approval?.approved_quantity) === 120 && Number(it?.approval?.piece_rate) === 5 && is?.approval && !('piece_rate' in is.approval) && !JSON.stringify(pendSm.packages || []).includes('piece_rate'), finance: it?.approval && { qty: it.approval.approved_quantity, unit: it.approval.unit, piece_rate: it.approval.piece_rate }, site_manager_keys: Object.keys(is?.approval || {}) }; });
    await c.ctx.close(); }

  // ---------- 4. The pay run shows 600 ----------
  { const pr = await pay();
    const c = await phone('admin@bot-a.test'); const p = c.page; await p.goto(b.UI + '/pay-runs'); await p.getByTestId('pay-runs-page').waitFor(); await p.waitForTimeout(3500);
    const rowTxt = (await p.getByTestId(`grid-row-${S.worker}`).innerText().catch(() => '')).replace(/\s+/g, ' ');
    await b.step('4.1 [API] pay-run preview for the day: the akord worker earns 600 = 120 м2 × 5', async () => ({ ok: pr.row && Number(pr.row.earned_amount) === 600, earned_amount: pr.row?.earned_amount, labor_amount: pr.row?.labor_amount, downtime_amount: pr.row?.downtime_amount }));
    await p.screenshot({ path: b.outDir + '/04a_pay_runs_600.png' });
    await b.step('4.2 [390 Админ] the „Седмичен“ pay-run screen shows 600 on the worker\'s row', async () => ({ ok: /(^|[^\d.,])600([.,]00)?(?!\d)/.test(rowTxt), row: rowTxt.slice(0, 220) }), p);
    const nl = await bg(p); await b.step('4.3 [390 Админ] pay-run screen: Bulgarian (Latin words listed), no page-level horizontal scroll', async () => ({ ok: nl.latin_words.length === 0 && await noH(p), no_hscroll: await noH(p), ...nl }));
    const fin = (await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.admin)).body; const it = (fin.items || []).find(i => i.report_id === S.reportId);
    await p.goto(b.UI + '/labor-quantities'); await p.getByText(/120 м2 × 5 = 600/).first().waitFor({ timeout: 10000 }).catch(() => {});
    await b.step('4.4 [390 Админ] the approval screen shows the akord formula „120 м2 × 5 = 600“', async () => ({ ok: (await p.getByText(/120 м2 × 5 = 600/).count()) > 0 }), p);
    await c.ctx.close(); }

  // ---------- 5. The worker cannot approve his own entry ----------
  const it0 = (await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.admin)).body.items.find(i => i.report_id === S.reportId);
  const wSelf = await http('POST', '/labor-quantities/approve', tk.worker, { report_id: S.reportId, entry_id: it0.entry_id || null, report_version: it0.report_version, approved_quantity: 1000, execution_package_id: 'pkg-sh' }, idem());
  const wPend = await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.worker); const wCls = await http('POST', '/labor-quantities/classify', tk.worker, { report_id: S.reportId, report_version: it0.report_version, cost_type: 'LABOR', reason: 'x' }, idem());
  const afterSelf = (await pay()).row;
  await b.step('5.1 [API] the worker tries to approve his own entry (1000 м2): refused 403; the list and the DOWNTIME/LABOR classification are 403 as well', async () => ({ ok: wSelf.status === 403 && wPend.status === 403 && wCls.status === 403, approve: wSelf.status, pending: wPend.status, classify: wCls.status, detail: String(wSelf.body?.detail || '').slice(0, 120) }));
  await b.step('5.2 nothing changed: the approval stays 120 м2 and the pay run still shows 600', async () => ({ ok: Number(afterSelf?.earned_amount) === 600, earned_amount: afterSelf?.earned_amount, approvals_active: jq('bot_op', `db.labor_quantity_approvals.countDocuments({report_id:'${S.reportId}',status:'approved'})`) }));
  { const c = await phone('worker@bot-a.test'); const p = c.page; await p.goto(b.UI + '/labor-quantities'); await p.waitForTimeout(2500);
    await b.step(`5.3 [390 worker] opening the approval screen directly: he is sent away (landed ${p.url().replace(b.UI, '')}), no approval button`, async () => ({ ok: !p.url().includes('/labor-quantities') && (await p.getByTestId('lq-approve').count()) === 0, landed: p.url().replace(b.UI, '') }), p); await c.ctx.close(); }

  // ---------- 6. Editing the report afterwards voids the approval ----------
  const ver0 = it0.report_version;
  const edit = await http('PUT', '/labor-quantities/entry', tk.sm, { report_id: S.reportId, quantity: 100 });
  const afterEdit = (await pay()).row; const pend2 = (await http('GET', `/labor-quantities/pending?project_id=${S.P}`, tk.sm)).body.items.find(i => i.report_id === S.reportId);
  await b.step('6.1 [API] the approver edits the report line afterwards (quantity 120 → 100, R36): 200, the old approval is VOID (kept), version bumped, the pay run no longer shows 600', async () => ({ ok: edit.status === 200 && jq('bot_op', `db.labor_quantity_approvals.countDocuments({report_id:'${S.reportId}',status:'void'})`) >= 1 && pend2.report_version > ver0 && Number(afterEdit?.earned_amount || 0) !== 600, status: edit.status, version_before: ver0, version_after: pend2.report_version, voided: jq('bot_op', `db.labor_quantity_approvals.countDocuments({report_id:'${S.reportId}',status:'void'})`), earned_after_edit: afterEdit?.earned_amount }));
  { const c = await phone('sm@bot-a.test'); const p = c.page; await p.goto(b.UI + '/labor-quantities'); await p.getByTestId(`lq-item-${S.reportId}`).waitFor({ timeout: 15000 });
    const t = (await p.getByTestId(`lq-item-${S.reportId}`).innerText()).replace(/\s+/g, ' ');
    await b.step('6.2 [390 SiteManager] the line is waiting for approval again: „Въведено от работника: 100“, button „Одобри количеството“ (not „Коригирай“), no „одобрено:“ text', async () => ({ ok: /Въведено от работника:\s*100/.test(t) && /Одобри количеството/.test(t) && !/одобрено:/.test(t), line: t.slice(0, 220) }), p);
    const staleAudit = jq('bot_op', `db.audit_events.countDocuments({action:{$regex:'^report\\\\.|labor_quantity|daily_report'}})`);
    await c.ctx.close();
    S.staleAudit = staleAudit; }
  // an approval of the OLD version is refused
  const stale = await http('POST', '/labor-quantities/approve', tk.sm, { report_id: S.reportId, entry_id: it0.entry_id || null, report_version: ver0, approved_quantity: 120, execution_package_id: 'pkg-sh' }, idem());
  await b.step('6.3 [API] approving the OLD report version is refused with 409 (stale version)', async () => ({ ok: stale.status === 409, status: stale.status, detail: String(stale.body?.detail || '').slice(0, 120) }));

  // ---------- 7. The approver marks a line as DOWNTIME with a reason ----------
  { const c = await phone('sm@bot-a.test'); const p = c.page; await p.goto(b.UI + '/labor-quantities'); await p.getByTestId(`lq-item-${S.reportId}`).waitFor({ timeout: 15000 });
    await p.getByTestId('lq-downtime').click(); await p.getByText('Напишете причина за престоя').first().waitFor({ timeout: 8000 }).catch(() => {});
    const noReason = jq('bot_op', `db.labor_line_classifications.countDocuments({report_id:'${S.reportId}'})`);
    await b.step('7.1 [390 SiteManager] „Престой“ without a reason is refused on screen („Напишете причина за престоя“) and writes nothing', async () => ({ ok: noReason === 0 && (await p.getByText('Напишете причина за престоя').count()) > 0, rows_written: noReason }), p);
    await p.getByPlaceholder('Причина за престой').fill('Дъжд — няма достъп до обекта'); await p.getByTestId('lq-downtime').click(); await p.getByText('Редът е отбелязан като престой').first().waitFor({ timeout: 10000 }).catch(() => {});
    const cls = jq('bot_op', `db.labor_line_classifications.find({report_id:'${S.reportId}',status:'active'},{_id:0,cost_type:1,reason:1,classified_by:1}).toArray()`); const pr = (await pay()).row;
    await b.step('7.2 [390 SiteManager] reason „Дъжд — няма достъп до обекта“ + „Престой“ → „Редът е отбелязан като престой“; an active DOWNTIME classification with the reason is stored', async () => ({ ok: cls.length === 1 && cls[0].cost_type === 'DOWNTIME' && /Дъжд/.test(cls[0].reason || ''), classification: cls }), p);
    await b.step('7.3 [API] the pay run shows the line as downtime apart from labor: downtime_amount > 0, labor_amount 0', async () => ({ ok: Number(pr?.downtime_amount) > 0 && Number(pr?.labor_amount || 0) === 0, earned_amount: pr?.earned_amount, labor_amount: pr?.labor_amount, downtime_amount: pr?.downtime_amount }));
    const nl = await bg(p); await b.step('7.4 [390 SiteManager] the screen after the DOWNTIME mark: Bulgarian, no horizontal scroll', async () => ({ ok: nl.latin_words.length === 0 && await noH(p), no_hscroll: await noH(p), ...nl }), p);
    await c.ctx.close(); }
  { const c = await phone('admin@bot-a.test'); const p = c.page; await p.goto(b.UI + '/pay-runs'); await p.getByTestId('pay-runs-page').waitFor(); await p.waitForTimeout(3500);
    const rowTxt = (await p.getByTestId(`grid-row-${S.worker}`).innerText().catch(() => '')).replace(/\s+/g, ' ');
    await b.step('7.5 [390 Админ] the pay-run screen after the DOWNTIME mark no longer shows 600 for the worker (no akord pay for the downtime line)', async () => ({ ok: !/(^|[^\d.,])600([.,]00)?(?!\d)/.test(rowTxt), row: rowTxt.slice(0, 220) }), p); await c.ctx.close(); }
  // no hard delete anywhere
  await b.step('8 no hard delete: the replaced approval and the classification records are kept (void/active rows exist), AuditEvents written for terms, approval, correction and classification', async () => { const ev = jq('bot_op', `db.audit_events.find({},{_id:0,action:1}).toArray().map(e=>e.action)`); const has = (re) => ev.some(a => re.test(a)); return { ok: jq('bot_op', `db.labor_quantity_approvals.countDocuments({report_id:'${S.reportId}'})`) >= 1 && has(/labor_terms\.set/) && has(/labor_quantity\.approved/) && has(/classif|downtime/i), actions: [...new Set(ev)].filter(a => /labor|report|classif/i.test(a)) }; });
  b.result.facts = S;
}, { outDir: process.env.BOT_OUT, sha: process.env.BOT_SHA });

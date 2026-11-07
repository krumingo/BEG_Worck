// BOT 5C final run — PR #55 @ 8025871. Synthetic data, enforce mode, NO local workarounds.
// Start state = real install: W0-04 AuditEvents exist (created by user creation), legacy unique batch index + a legacy batch row exist.
const { execFileSync } = require('child_process');
const bot = require('../runner/lib');
const API = bot.API, PW = 'BotPass-12345!', ITEM = 'it-cement', ITEM_K = 'it-keeper', ITEM_C = 'it-cost';
const mongo = (db, js) => execFileSync('docker', ['exec', 'botmongo', 'mongosh', '--quiet', db, '--eval', js]).toString().trim();
const jq = (db, js) => JSON.parse(mongo(db, `JSON.stringify(${js})`));
async function http(method, path, token, body) {
  const r = await fetch(API + '/api' + path, { method, headers: { 'content-type': 'application/json', ...(token ? { authorization: 'Bearer ' + token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  let j = null; try { j = await r.json(); } catch {}
  return { status: r.status, body: j };
}
const login = async (email) => (await http('POST', '/auth/login', null, { email, password: PW })).body.token;
let keyN = 0; const key = (p) => `${p}-${Date.now()}-${++keyN}`;
const mv = (token, b) => http('POST', '/warehouse/canonical/movements', token, { idempotency_key: key(b.action), currency: 'BGN', ...b });
const loc = (t, id, state = 'free') => ({ location_type: t, location_id: id, state });
const code = (r) => r.body?.detail?.error_code;
const MODE = process.env.BOT_MODE || 'enforce'; const okS = (r) => r.status === 200 || r.status === 201;
const woProj = (token, pid, item, qty, fid = 'file-bot-wo', extra = {}) => http('POST', '/warehouse/canonical/project-writeoff', token, { project_id: pid, item_id: item, unit: 'bag', quantity: String(qty), idempotency_key: key('wo'), reason: 'brak (bot)', file_ids: [fid], ...extra });

bot.run('5C-8025871', async (b) => {
  const S = {}, P = {};
  // ---------- setup via real API ----------
  const admin = await login('admin@bot-a.test'); const adminB = await login('admin@bot-b.test');
  for (const [email, role] of [['wk@bot-a.test', 'Warehousekeeper'], ['tech@bot-a.test', 'Technician'], ['viewer@bot-a.test', 'Viewer'], ['acc@bot-a.test', 'Accountant'], ['sm@bot-a.test', 'SiteManager'], ['tech2@bot-a.test', 'Technician'], ['pm@bot-a.test', 'Viewer']])
    await http('POST', '/users', admin, { email, password: PW, first_name: role, last_name: 'Bot', role });
  const me = (await http('GET', '/auth/me', admin)).body; S.orgA = me.org_id || me.user?.org_id;
  S.project = (await http('POST', '/projects', admin, { code: 'BOT-P1', name: 'Bot Project 1' })).body.id;
  S.project2 = (await http('POST', '/projects', admin, { code: 'BOT-P2', name: 'Bot Project 2 (cost check)' })).body.id;
  const mkSmr = async (pid, name) => (await http('POST', `/projects/${pid}/smr-groups`, admin, { name })).body?.id;
  S.smr = await mkSmr(S.project, 'Bot SMR 1'); S.smr2 = await mkSmr(S.project2, 'Bot SMR 2');
  for (const id of [ITEM, ITEM_K, ITEM_C]) mongo('bot_op', `db.md_item.insertOne({id:'${id}',tenant_id:'${S.orgA}',canonical_unit:'bag',name:'${id} (synthetic)'})`);
  // execution package + planned material for the cost reports (synthetic, direct insert)
  S.pkg = 'pkg-bot-1';
  mongo('bot_op', `db.execution_packages.insertOne({id:'${S.pkg}',org_id:'${S.orgA}',project_id:'${S.project2}',name:'Bot package',title:'Bot package',status:'active',material_budget_total:200,actual_material_cost:0,created_at:new Date().toISOString()});db.planned_materials.insertOne({id:'pm-bot-1',org_id:'${S.orgA}',project_id:'${S.project2}',status:'active',item_id:'${ITEM_C}',material_name:'${ITEM_C}',execution_package_id:'${S.pkg}',planned_total_cost:200})`);
  const tk = { wk: await login('wk@bot-a.test'), tech: await login('tech@bot-a.test'), viewer: await login('viewer@bot-a.test'), acc: await login('acc@bot-a.test') };

  const recv = (token, q, id = ITEM, uv = '5') => mv(token, { action: 'receive_from_supplier', item_id: id, unit: 'bag', quantity: String(q), unit_value: uv, source: loc('supplier', 'sup1'), destination: loc('central_warehouse', 'CEN') });
  const dispApi = (token, q, id = ITEM, pid = S.project) => mv(token, { action: 'dispatch_warehouse_to_project', item_id: id, unit: 'bag', quantity: String(q), project_id: pid, source: loc('central_warehouse', 'CEN'), destination: loc('in_transit', 'pending', 'in_transit') });
  const openDisc = (id) => jq('bot_op', `(()=>{const rows=db.warehouse_transactions.find({dispatch_movement_id:'${id}'}).toArray();const res=new Set(rows.filter(r=>r.action==='discrepancy_resolved').map(r=>r.resolves_discrepancy_movement_id));return rows.filter(r=>r.action==='transit_discrepancy'&&!res.has(r.movement_id)).length})()`);
  const inTransit = (id) => jq('bot_op', `db.warehouse_in_transit.find({}).toArray().filter(x=>JSON.stringify(x).includes('${id}')).map(x=>({unresolved:Object.keys(x.unresolved_discrepancies||{}).length}))`);

  // ---------- UI helpers ----------
  const field = (page, label) => page.locator('.wh-field', { hasText: label }).first();
  async function cmdUI(page, c) {
    if (!(await page.getByTestId('wh-tab-commands').count())) await openCanonical(page);
    await page.getByTestId('wh-tab-commands').click();
    await page.getByTestId('wh-action-select').selectOption(c.action);
    await field(page, 'Артикул (item_id)').locator('input').fill(c.item || ITEM);
    await field(page, 'Количество').first().locator('input').fill(String(c.qty));
    const uv = field(page, 'Единична стойност'); if (await uv.count()) await uv.locator('input').fill(c.unitValue || '');
    await field(page, 'Източник').locator('select').selectOption(c.src?.[0] || 'supplier'); await field(page, 'Източник').locator('input').fill(c.src?.[1] || '');
    if (c.target) { await page.getByTestId('wh-transfer-target-type').selectOption(c.target[0]); await page.getByTestId('wh-transfer-target-id').fill(c.target[1]); }
    else if (c.action !== 'dispatch_warehouse_to_project') { await field(page, 'Дестинация').locator('select').selectOption(c.dst?.[0] || 'central_warehouse'); await field(page, 'Дестинация').locator('input').fill(c.dst?.[1] || ''); }
    await page.locator('.wh-field', { hasText: 'Проект' }).first().locator('input').fill(c.project || '');
    if (c.reason) await field(page, 'Причина').locator('input').fill(c.reason);
    if (c.smr) await page.getByTestId('wh-smr-id').fill(c.smr);
    if (c.acceptState) await page.getByTestId('wh-accept-state').selectOption(c.acceptState);
    if (c.dispatchId) { await field(page, 'Dispatch movement id').locator('input').fill(c.dispatchId); await field(page, 'Количество прието').locator('input').fill(String(c.accepted)); await field(page, 'Количество заявено').locator('input').fill(String(c.requested)); }
    const [resp] = await Promise.all([page.waitForResponse(r => r.url().includes('/warehouse/canonical/movements') && r.request().method() === 'POST'), page.getByRole('button', { name: 'Запиши движение' }).click()]);
    let j = null; try { j = await resp.json(); } catch {}
    await page.waitForTimeout(400);
    return { status: resp.status(), body: j };
  }
  async function stockUI(page, item) {
    if (!(await page.getByTestId('wh-tab-stock').count())) await openCanonical(page);
    await page.getByTestId('wh-tab-stock').click();
    await page.locator('.wh-field', { hasText: 'Артикул' }).first().locator('input').fill(item);
    await page.getByRole('button', { name: 'Прочети наличност' }).click(); await page.waitForTimeout(900);
    return page.locator('.wh-stock-row').allInnerTexts();
  }
  const noHScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  const openCanonical = async (page) => { await page.goto(b.UI + '/warehouse/canonical'); await page.getByTestId('wh-tab-stock').waitFor({ timeout: 15000 }); };

  // ---------- 0. real-install preconditions ----------
  const pre = jq('bot_op', `({audit_events: db.audit_events.countDocuments({}), legacy_batches: db.warehouse_batches.countDocuments({batch_number:{$ne:null}}), legacy_unique_index: db.warehouse_batches.getIndexes().some(i=>i.unique&&JSON.stringify(i.key)==='{"org_id":1,"batch_number":1}'), canonical_indexes: db.warehouse_transactions.getIndexes().length-1})`);
  await b.step('0 precondition: tenant already has W0-04 AuditEvents, a legacy batch row and the legacy unique batch_number index; canonical indexes came from app startup', async () => ({ ok: pre.audit_events > 0 && pre.legacy_batches > 0 && pre.legacy_unique_index && pre.canonical_indexes >= 6, ...pre }));

  // ---------- RUN 1 @1280 ----------
  const d0 = await b.context('desktop'); const p0 = d0.page;
  await b.login(p0, 'admin@bot-a.test', PW); await openCanonical(p0);
  const r1 = await cmdUI(p0, { action: 'receive_from_supplier', qty: 10, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('1.1 [1280 UI] receive 10 to central warehouse on a tenant with existing AuditEvents -> 200 (F-1)', async () => ({ ok: r1.status === 200, status: r1.status, code: code(r1) }), p0);
  const r1b = await cmdUI(p0, { action: 'receive_from_supplier', item: ITEM_K, qty: 5, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('1.1b [1280 UI] second receive (other item) with the legacy batch index present -> 200 (F-2)', async () => ({ ok: r1b.status === 200, status: r1b.status, code: code(r1b), message: (r1b.body?.detail?.message || '').slice(0, 200) }), p0);
  S.rows1 = (await stockUI(p0, ITEM)).join('|');
  await b.step('1.2 [1280 UI] stock panel shows 10 at central_warehouse:CEN', async () => ({ ok: /central_warehouse:CEN[\s\S]*10/.test(S.rows1), rows: S.rows1 }), p0);
  // direct dispatch to a project must be refused
  const direct = await mv(admin, { action: 'dispatch_warehouse_to_project', item_id: ITEM_K, unit: 'bag', quantity: '1', project_id: S.project, source: loc('central_warehouse', 'CEN'), destination: loc('project', S.project) });
  const kBal = await http('GET', `/warehouse/canonical/balance/${ITEM_K}`, admin);
  await b.step('1.3p direct dispatch to a project (destination project/free) is refused and credits nothing', async () => ({ ok: direct.status >= 400 && direct.status < 500 && !(kBal.body?.balances || []).some(r => r.location_type === 'project'), status: direct.status, error_code: code(direct), balances: (kBal.body?.balances || []).map(r => `${r.location_type}:${r.state}=${r.quantity}`) }));
  await p0.getByTestId('wh-tab-commands').click(); await p0.getByTestId('wh-action-select').selectOption('dispatch_warehouse_to_project');
  await b.step('1.3q [1280 UI] dispatch form has a FIXED destination read in Bulgarian „в път · очаква приемане“ (no destination picker)', async () => { const txt = (await p0.getByTestId('wh-dispatch-in-transit').innerText()).trim(); return { ok: /в път/.test(txt) && !/in_transit/.test(txt) && (await field(p0, 'Дестинация').locator('select').count()) === 0, text: txt }; }, p0);
  const d1 = await cmdUI(p0, { action: 'dispatch_warehouse_to_project', qty: 10, src: ['central_warehouse', 'CEN'], project: S.project });
  S.disp1 = d1.body?.movement_id;
  await b.step('1.3 [1280 UI] dispatch 10 to project -> 200 (in transit)', async () => ({ ok: d1.status === 200, status: d1.status, code: code(d1) }), p0);
  const projBefore = await http('GET', `/warehouse/canonical/balance/${ITEM}`, admin);
  await b.step('1.3r project holds nothing before acceptance (stock in transit)', async () => ({ ok: !(projBefore.body?.balances || []).some(r => r.location_type === 'project' && r.state === 'free' && Number(r.quantity) > 0), balances: (projBefore.body?.balances || []).map(r => `${r.location_type}:${r.state}=${r.quantity}`) }));
  const accs = [];
  for (const q of [3, 4, 3]) { const r = await cmdUI(p0, { action: 'accept_project_delivery', qty: q, dst: ['project', S.project], project: S.project, dispatchId: S.disp1, accepted: q, requested: 10, src: ['supplier', ''] }); accs.push({ q, status: r.status, code: code(r), open: await openDisc(S.disp1) }); }
  await b.step('1.4 [1280 UI] accept 3 + 4 + 3 all -> 200', async () => ({ ok: accs.every(a => a.status === 200), accs }), p0);
  await b.step('1.5 unresolved discrepancies after 3+4+3 == 0 (all accepts succeeded; ledger + in-transit projection)', async () => ({ ok: accs.every(a => a.status === 200) && accs[2].open === 0, open_after_each: accs.map(a => a.open), in_transit: await inTransit(S.disp1) }), p0);
  S.rows1b = await stockUI(p0, ITEM);
  await b.step('1.6 [1280 UI] stock: project holds 10', async () => ({ ok: /project:/.test(S.rows1b.join('|')) && /10/.test(S.rows1b.join('|')), rows: S.rows1b }), p0);
  await p0.getByTestId('wh-tab-warnings').click(); await p0.waitForTimeout(1200);
  const iw = await http('GET', '/warehouse/canonical/integrity-warnings', admin);
  await b.step('1.7 [1280 UI] integrity-warnings API 200 and panel shows the empty state (F-3)', async () => ({ ok: iw.status === 200 && await p0.getByTestId('wh-warnings-empty').isVisible(), api_status: iw.status, error_type: iw.body?.error_type }), p0);
  // forced backend failure -> error state, never a false all-clear
  await p0.route('**/integrity-warnings', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'boom' }) }));
  await p0.getByTestId('wh-tab-stock').click(); await p0.getByTestId('wh-tab-warnings').click(); await p0.waitForTimeout(1200);
  await b.step('1.7b [1280 UI] backend integrity-warnings call fails (forced 500) -> panel shows an ERROR state, not "no alarms"', async () => { const err = await p0.getByTestId('wh-warnings-error').isVisible(); const empty = await p0.getByTestId('wh-warnings-empty').isVisible(); return { ok: err && !empty, error_visible: err, empty_visible: empty, text: (await p0.getByTestId('wh-warnings-error').innerText().catch(() => '')).slice(0, 160) }; }, p0);
  await p0.unroute('**/integrity-warnings');
  await p0.route('**/integrity-warnings', (r) => r.abort('failed'));
  await p0.getByTestId('wh-tab-stock').click(); await p0.getByTestId('wh-tab-warnings').click(); await p0.waitForTimeout(1200);
  await b.step('1.7c [1280 UI] network failure on integrity-warnings -> error state', async () => ({ ok: await p0.getByTestId('wh-warnings-error').isVisible() && !(await p0.getByTestId('wh-warnings-empty').isVisible()) }), p0);
  await p0.unroute('**/integrity-warnings');
  await b.step('1.8 [1280] no horizontal scroll', async () => noHScroll(p0), p0);
  await d0.ctx.close();

  // ---------- RUN 2 @390x844: receive 10, dispatch 10, accept 8+2, consume 3 with SMR ----------
  const m = await b.context('phone'); const pm = m.page;
  await b.login(pm, 'admin@bot-a.test', PW); await openCanonical(pm);
  const r2 = await cmdUI(pm, { action: 'receive_from_supplier', qty: 10, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('2.1 [390 UI] receive 10 -> 200', async () => ({ ok: r2.status === 200, status: r2.status, code: code(r2) }), pm);
  const d2 = await cmdUI(pm, { action: 'dispatch_warehouse_to_project', qty: 10, src: ['central_warehouse', 'CEN'], project: S.project });
  S.disp2 = d2.body?.movement_id;
  await b.step('2.2 [390 UI] dispatch 10 -> 200', async () => ({ ok: d2.status === 200, status: d2.status, code: code(d2) }), pm);
  const a8 = await cmdUI(pm, { action: 'accept_project_delivery', qty: 8, dst: ['project', S.project], project: S.project, dispatchId: S.disp2, accepted: 8, requested: 10, src: ['supplier', ''] }); const open8 = await openDisc(S.disp2);
  await b.step('2.3 [390 UI] accept 8 -> 200 and exactly 1 open discrepancy', async () => ({ ok: a8.status === 200 && open8 === 1, status: a8.status, open: open8 }), pm);
  const a2 = await cmdUI(pm, { action: 'accept_project_delivery', qty: 2, dst: ['project', S.project], project: S.project, dispatchId: S.disp2, accepted: 2, requested: 10, src: ['supplier', ''] }); const open2 = await openDisc(S.disp2);
  await b.step('2.4 [390 UI] accept 2 -> 200 and zero unresolved discrepancies', async () => ({ ok: a2.status === 200 && open2 === 0, status: a2.status, open: open2 }), pm);
  await pm.getByTestId('wh-tab-commands').click(); await pm.getByTestId('wh-action-select').selectOption('consume_to_smr');
  await b.step('2.5 [390 UI] consume form has an SMR field (required before submit)', async () => { const vis = await pm.getByTestId('wh-smr-id').isVisible(); await field(pm, 'Артикул (item_id)').locator('input').fill(ITEM); await field(pm, 'Количество').first().locator('input').fill('3'); const disabled = await pm.getByRole('button', { name: 'Запиши движение' }).isDisabled(); return { ok: vis && disabled, smr_field_visible: vis, submit_disabled_without_smr: disabled }; }, pm);
  const c1 = await cmdUI(pm, { action: 'consume_to_smr', qty: 3, src: ['project', S.project], dst: ['central_warehouse', ''], project: S.project, smr: S.smr });
  await b.step('2.6 [390 UI] consume 3 bound to the SMR through the form -> 200', async () => ({ ok: c1.status === 200, status: c1.status, code: code(c1), message: c1.body?.detail?.message }), pm);
  const mid = c1.body?.movement_id;
  const rows = jq('bot_op', `db.material_entries.find({movement_id:'${mid}'},{_id:0,movement_id:1,smr_id:1,quantity:1,total_value:1,movement_value:1,cost_recognized:1,movement_kind:1}).toArray()`);
  const smrRows = jq('bot_op', `db.material_entries.countDocuments({smr_id:'${S.smr}',movement_kind:'consume'})`);
  // identical resend (same key + body) through the API
  const cbody = { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project), idempotency_key: key('resend'), currency: 'BGN' };
  const c2a = await http('POST', '/warehouse/canonical/movements', admin, cbody); const c2b = await http('POST', '/warehouse/canonical/movements', admin, cbody);
  const rowsAfter = jq('bot_op', `db.material_entries.countDocuments({movement_id:'${c2a.body?.movement_id}'})`);
  await b.step('2.7 (R17) the UI consume writes exactly ONE SMR allocation row: value 15 in movement_value, cost_recognized false, total_value 0 (cost is recognised at accept, not here)', async () => ({ ok: rows.length === 1 && smrRows === 1 && rows[0].cost_recognized === false && Number(rows[0].total_value) === 0 && Number(rows[0].movement_value) === 15, rows_for_movement: rows, consume_rows_for_smr: smrRows }));
  await b.step('2.8 identical consume resend returns the ORIGINAL result (200, replay:true, same movement_id) and adds no row (F-5)', async () => ({ ok: c2a.status === 200 && c2b.status === 200 && c2b.body?.replay === true && c2b.body?.movement_id === c2a.body?.movement_id && rowsAfter === 1, first: c2a.status, resend: c2b.status, replay: c2b.body?.replay, same_id: c2b.body?.movement_id === c2a.body?.movement_id, error_code: code(c2b), rows_for_movement: rowsAfter }));
  await b.step('2.9 [390] no horizontal scroll (form with SMR field)', async () => noHScroll(pm), pm);
  await pm.goto(b.UI + '/projects/' + S.project); await pm.waitForTimeout(2000); await pm.getByTestId('tab-finance').click(); await pm.waitForTimeout(2500);
  await b.step('2.10 [390] project page, Finance tab: material ledger visible with the canonical trail (dispatched 20, consumed 4, remaining 16)', async () => { const t = (await pm.locator('[data-testid="material-ledger"]').innerText().catch(() => '')).replace(/\s+/g, ' '); return { ok: t.length > 0 && /16/.test(t), text: t.slice(0, 240) }; }, pm);
  await m.ctx.close();

  // ---------- COST CHECKS (R17 cost at ACCEPT, R21 batch prices, FG-17) ----------
  const sum = (a, f) => a.reduce((x, e) => x + Number(f(e) || 0), 0);
  const PL = 'project', KL = 'package';
  const EX = {
    'material summary (/project-material-summary)': [PL, '/project-material-summary/{P}', (x) => ({ m: x.actual.material_cost_basis.consumption_cost, w: x.actual.waste_value, t: x.actual.net_material_cost })],
    'package material (/material-cost/by-execution-package)': [KL, '/material-cost/by-execution-package/{K}', (x) => ({ m: x.material_actual_cost, w: x.material_waste_cost, t: x.material_total_cost })],
    'package financial': [KL, '/execution-packages/{K}/financial', (x) => ({ m: x.actual.material, w: x.actual.waste, t: x.actual.total })],
    'package breakdown (/financial-breakdown)': [KL, '/execution-packages/financial-breakdown/{P}', (x) => ({ m: x.packages[0].material_actual, w: x.packages[0].material_waste, t: x.packages[0].total_actual })],
    'package net-financial': [KL, '/execution-packages/{K}/net-financial', (x) => ({ m: x.costs.material, w: x.costs.waste, t: x.costs.gross_cost })],
    'net profit (financial page data)': [PL, '/project-net-profit/{P}', (x) => ({ m: x.costs.material, w: x.costs.waste, t: x.costs.gross_cost })],
    'project profit': [PL, '/project-profit/{P}', (x) => ({ m: x.expenses.material, w: x.expenses.waste, t: x.expenses.total })],
    'P&L (/pnl)': [PL, '/projects/{P}/pnl', (x) => ({ m: x.expense.material_cost, w: x.expense.material_waste_cost, t: x.expense.total_expense })],
    'P&L summary (card)': [PL, '/projects/{P}/pnl/summary', (x) => ({ m: x.material_cost, w: x.material_waste_cost, t: x.total_expense })],
    'profit by period': [PL, '/profit-by-period/{P}', (x) => ({ m: sum(x.periods, p => p.material), w: sum(x.periods, p => p.waste), t: sum(x.periods, p => p.total_cost) })],
  };
  // chk(label, projectId, pkgId, expected project-level {m,w,t}, expected package-level {m,w,t}|null)
  const chk = async (label, pid, pkg, expP, expK) => {
    for (const [name, [lvl, path, fn]] of Object.entries(EX)) {
      if (lvl === KL && (!expK || !pkg)) continue;
      const exp = lvl === KL ? expK : expP;
      const r = await http('GET', path.replace('{P}', pid).replace('{K}', pkg), admin); let got = null, err = '';
      try { got = r.status === 200 ? fn(r.body) : null; } catch (e) { err = String(e).slice(0, 100); }
      const okv = got && ['m', 'w', 't'].every(k => Math.abs(got[k] - exp[k]) < 0.005);
      await b.step(`${label} ${name}: material ${exp.m} / фира ${exp.w} / total ${exp.t}`, async () => ({ ok: !!okv, status: r.status, got, expected: exp, err }));
    }
  };
  const metric = (t, label, euro) => { if (euro) { const m = t.match(new RegExp(label + '\\s*(-?[\\d][\\d.,]*)\\s*€', 'i')); return m ? Number(m[1].replace(',', '.')) : null; } const m = t.match(new RegExp(label + '[^\\d\\-]{0,14}(-?[\\d][\\d.,]*)', 'i')); return m ? Number(m[1].replace(/,(?=\d{3}\b)/g, '').replace(',', '.')) : null; };
  const screens = async (label, pid, exp, page, tag) => {
    const out = {};
    for (const [name, path] of [['financial page', `/projects/${pid}/financial`], ['project page, Finance tab (P&L dashboard)', `/projects/${pid}`]]) {
      await page.goto(b.UI + path); await page.waitForTimeout(3000);
      const onProject = path.endsWith(pid); let t;
      if (onProject) { await page.getByTestId('tab-finance').click(); await page.waitForTimeout(2500); await page.getByTestId('project-pnl-dashboard').getByRole('button', { name: 'Детайлна разбивка' }).click(); await page.waitForTimeout(800); t = (await page.getByTestId('project-pnl-dashboard').innerText()).replace(/\s+/g, ' ').replace(/(\d) (?=\d{3}\b)/g, '$1').replace(/(\d),(?=\d{3}\b)/g, '$1'); S.frc = (await page.getByTestId('financial-results-card').innerText()).replace(/\s+/g, ' ').replace(/(\d) (?=\d{3}\b)/g, '$1').replace(/(\d),(?=\d{3}\b)/g, '$1'); }
      else t = (await page.locator('main').first().innerText()).replace(/\s+/g, ' ');
      const got = { m: metric(t, 'Материали', onProject), w: metric(t, 'Фира', onProject), t: metric(t, 'Общ(?:о)? разход', onProject) }; out[name] = got;
      await b.step(`${label} [${tag}] screen "${name}": Материали ${exp.m}, Фира ${exp.w}, Общ разход ${exp.t}`, async () => ({ ok: got.m === exp.m && (exp.w === 0 ? (got.w === null || got.w === 0) : got.w === exp.w) && got.t === exp.t && (!onProject || new RegExp('Директни разходи\\s*-?' + exp.t + '\\s*€').test(S.frc)) && (tag === '1280' || await noHScroll(page)), got, expected: exp }), page);
    }
    return out;
  };
  const mkItem = (id) => mongo('bot_op', `db.md_item.insertOne({id:'${id}',tenant_id:'${S.orgA}',canonical_unit:'bag',name:'${id} (synthetic)'})`);
  const mkPkg = (pid, pkg, item) => mongo('bot_op', `db.execution_packages.insertOne({id:'${pkg}',org_id:'${S.orgA}',project_id:'${pid}',name:'Pkg ${pkg}',title:'Pkg ${pkg}',status:'active',material_budget_total:200,actual_material_cost:0,created_at:new Date().toISOString()});db.planned_materials.insertOne({id:'pm-${pkg}',org_id:'${S.orgA}',project_id:'${pid}',status:'active',item_id:'${item}',material_name:'${item}',execution_package_id:'${pkg}',planned_total_cost:200})`);
  const mkProject = async (code_) => { const id = (await http('POST', '/projects', admin, { code: code_, name: code_ })).body.id; const smr = (await http('POST', `/projects/${id}/smr-groups`, admin, { name: 'smr ' + code_ })).body?.id; return { id, smr }; };
  const dc = await b.context('desktop'); const pc = dc.page; await b.login(pc, 'admin@bot-a.test', PW); await openCanonical(pc);

  // ===== A. R17: cost appears at ACCEPT, consume only allocates, legacy before cutover, write-off = фира =====
  const A = { id: S.project2, smr: S.smr2, pkg: S.pkg };
  const c_r = await cmdUI(pc, { action: 'receive_from_supplier', item: ITEM_C, qty: 10, unitValue: '10', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  const c_d = await cmdUI(pc, { action: 'dispatch_warehouse_to_project', item: ITEM_C, qty: 5, src: ['central_warehouse', 'CEN'], project: A.id });
  await chk('A.0 (R17) after DISPATCH 5, before accept: project cost 0 (stock in transit)', A.id, A.pkg, { m: 0, w: 0, t: 0 }, { m: 0, w: 0, t: 0 });
  const c_a = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_C, qty: 5, dst: ['project', A.id], project: A.id, dispatchId: c_d.body?.movement_id, accepted: 5, requested: 5, src: ['supplier', ''] });
  await b.step('A.1 [1280 UI] receive 10 @10, dispatch 5, accept 5 -> 200', async () => ({ ok: [c_r, c_d, c_a].every(r => r.status === 200), statuses: [c_r, c_d, c_a].map(r => r.status), codes: [c_r, c_d, c_a].map(code) }), pc);
  await chk('A.1 (R17) after ACCEPT 5 @10: project cost 50 appears; packages 0 (nothing allocated yet)', A.id, A.pkg, { m: 50, w: 0, t: 50 }, { m: 0, w: 0, t: 0 });
  await screens('A.1', A.id, { m: 50, w: 0, t: 50 }, pc, '1280');
  const c_c = await cmdUI(pc, { action: 'consume_to_smr', item: ITEM_C, qty: 3, src: ['project', A.id], dst: ['central_warehouse', ''], project: A.id, smr: A.smr });
  await b.step('A.2 [1280 UI] consume 3 with SMR -> 200', async () => ({ ok: c_c.status === 200, status: c_c.status, code: code(c_c) }), pc);
  await chk('A.2 (R17) after CONSUME 3: project cost STILL 50 (consume adds no cost); packages show the 30 allocated', A.id, A.pkg, { m: 50, w: 0, t: 50 }, { m: 30, w: 0, t: 30 });
  mongo('bot_op', `db.warehouse_transactions.insertOne({id:'legacy-issue-1',org_id:'${S.orgA}',project_id:'${A.id}',type:'issue',created_at:'2026-01-10T08:00:00+00:00',issue_date:'2026-01-10',lines:[{material_name:'${ITEM_C}',qty_issued:10,unit_price:10,total_price:100}]})`);
  await chk('A.3 + legacy issue 100 dated before cutover: project 150 (50 + 100); package 130', A.id, A.pkg, { m: 150, w: 0, t: 150 }, { m: 130, w: 0, t: 130 });
  await pc.goto(b.UI + '/warehouse/canonical'); await pc.getByTestId('wh-tab-stock').waitFor();
  const woUI = await cmdUI(pc, { action: 'write_off', item: ITEM_C, qty: 2, src: ['project', A.id], dst: ['central_warehouse', ''], project: A.id, reason: 'broken (bot)' });
  b.noScreen('A.4a write-off 2 @10 from the project through the form: the form cannot attach the evidence (file_ids) the write-off requires', 'UI attempt answered ' + woUI.status + ' ' + (woUI.body?.detail?.error_code || ''), { ui_status: woUI.status, ui_code: woUI.body?.detail?.error_code });
  const wo = await woProj(admin, A.id, ITEM_C, 2);
  await b.step('A.4 [API /project-writeoff] write-off 2 @10 from the project with evidence -> 2xx', async () => ({ ok: okS(wo), status: wo.status, code: code(wo), message: wo.body?.detail?.message }));
  await chk('A.4 + write-off 2@10: project total stays 150 (фира is inside the accepted cost), material 130, фира 20', A.id, A.pkg, { m: 130, w: 20, t: 150 }, { m: 130, w: 20, t: 150 });
  await screens('A.4', A.id, { m: 130, w: 20, t: 150 }, pc, '1280');
  { await pc.goto(b.UI + `/projects/${A.id}`); await pc.waitForTimeout(2500); await pc.getByTestId('tab-finance').click(); await pc.waitForTimeout(2500);
    const wc = (await pc.getByTestId('waste-writeoff-count').innerText().catch(() => '')).replace(/\s+/g, ' '); const rowsW = await pc.getByTestId('waste-writeoff-row').allInnerTexts().catch(() => []);
    await b.step('A.5 [1280] Finance tab "Материални отклонения" shows the write-off: "Отписвания от склада: 1 · 2" and one badge row', async () => ({ ok: /1\s*·\s*2/.test(wc) && rowsW.length === 1 && /отписване от склада/i.test(rowsW[0]), counter: wc, rows: rowsW.map(x => x.replace(/\s+/g, ' ')) }), pc); }
  const ent = (await http('GET', `/material-entries?project_id=${A.id}`, admin)).body || [];
  await b.step('A.6 material entries: accept row = project cost 50; consume row = allocation (total_value 0, movement_value 30); write-off row = фира allocation 20', async () => { const by = (k) => ent.filter(e => e.movement_kind === k); return { ok: by('accept').length === 1 && Number(by('accept')[0].total_value) === 50 && by('consume').length === 1 && Number(by('consume')[0].total_value) === 0 && Number(by('consume')[0].movement_value) === 30 && by('write_off').length === 1 && Number(by('write_off')[0].movement_value) === 20, rows: ent.map(e => ({ kind: e.movement_kind, total_value: e.total_value, movement_value: e.movement_value, cost_recognized: e.cost_recognized })) }; });
  { const mc = await b.context('phone'); await b.login(mc.page, 'admin@bot-a.test', PW); await screens('A.4', A.id, { m: 130, w: 20, t: 150 }, mc.page, '390'); await mc.ctx.close(); }

  // ===== B. R17 return lowers the cost; R18 every transfer in transit, return -> quarantine =====
  const PB = await mkProject('BOT-PB'), PC_ = await mkProject('BOT-PC'); const ITEM_B = 'it-ret'; mkItem(ITEM_B);
  await pc.goto(b.UI + '/warehouse/canonical'); await pc.getByTestId('wh-tab-stock').waitFor();
  const bR = await cmdUI(pc, { action: 'receive_from_supplier', item: ITEM_B, qty: 10, unitValue: '10', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN-R'] });
  const bD = await cmdUI(pc, { action: 'dispatch_warehouse_to_project', item: ITEM_B, qty: 10, src: ['central_warehouse', 'CEN-R'], project: PB.id });
  const bA = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_B, qty: 10, dst: ['project', PB.id], project: PB.id, dispatchId: bD.body?.movement_id, accepted: 10, requested: 10, src: ['supplier', ''] });
  await b.step('B.1 [1280 UI] receive 10 @10, dispatch 10, accept 10 on project B -> 200', async () => ({ ok: [bR, bD, bA].every(r => r.status === 200), statuses: [bR, bD, bA].map(r => r.status) }), pc);
  await chk('B.1 project B cost 100 after accepting 10 @10', PB.id, null, { m: 100, w: 0, t: 100 }, null);
  const directRet = await mv(admin, { action: 'transfer_project_to_warehouse', item_id: ITEM_B, unit: 'bag', quantity: '3', project_id: PB.id, source: loc('project', PB.id), destination: loc('central_warehouse', 'CEN-R', 'quarantine') });
  await b.step('B.2 (R18) direct return (destination = the warehouse) is refused and moves nothing', async () => ({ ok: directRet.status >= 400 && directRet.status < 500, status: directRet.status, code: code(directRet), message: (directRet.body?.detail?.message || '').slice(0, 140) }));
  const ret = await cmdUI(pc, { action: 'transfer_project_to_warehouse', item: ITEM_B, qty: 3, src: ['project', PB.id], target: ['central_warehouse', 'CEN-R'], project: PB.id });
  await b.step('B.3 (R18) [1280 UI] return 3 to the warehouse -> 200', async () => ({ ok: ret.status === 200, status: ret.status, code: code(ret), target_state: ret.body?.envelope?.transfer_target?.state, destination: ret.body?.envelope?.destination?.location_type }), pc);
  const rowsT = await stockUI(pc, ITEM_B);
  await b.step('B.4 (R18) [1280 UI] while the return is not accepted the stock panel shows it „в път“ (row 3, no raw in_transit); warehouse holds neither free nor quarantine', async () => ({ ok: rowsT.some(r => /в път/.test(r) && /\b3\b/.test(r)) && !rowsT.some(r => /in_transit/.test(r)) && !rowsT.some(r => /central_warehouse:CEN-R/.test(r) && /\n\s*[1-9]/.test(r)), rows: rowsT.map(r => r.replace(/\s+/g, ' ')) }), pc);
  await chk('B.5 (R17) return in transit: project B still carries the lot (cost 100 until accepted)', PB.id, null, { m: 100, w: 0, t: 100 }, null);
  const toFree = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_B, qty: 3, dst: ['central_warehouse', 'CEN-R'], project: '', dispatchId: ret.body?.movement_id, accepted: 3, requested: 3, src: ['supplier', ''], acceptState: 'free' });
  await b.step('B.6 (R18) [1280 UI] accepting the return into FREE stock is refused', async () => ({ ok: toFree.status >= 400 && toFree.status < 500, status: toFree.status, code: code(toFree) }), pc);
  const toQ = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_B, qty: 3, dst: ['central_warehouse', 'CEN-R'], project: '', dispatchId: ret.body?.movement_id, accepted: 3, requested: 3, src: ['supplier', ''], acceptState: 'quarantine' });
  await b.step('B.7 (R18) [1280 UI] accepting the return into QUARANTINE -> 200', async () => ({ ok: toQ.status === 200, status: toQ.status, code: code(toQ), dest_state: toQ.body?.envelope?.destination?.state }), pc);
  await chk('B.8 (R17) after the return is accepted: project B cost 70 (7 x 10) on every report', PB.id, null, { m: 70, w: 0, t: 70 }, null);
  const rowsQ = await stockUI(pc, ITEM_B);
  await b.step('B.9 (R18) [1280 UI] stock panel in Bulgarian: warehouse „карантина“ 3, project „свободна“ 7, nothing „в път“', async () => ({ ok: rowsQ.some(r => /CEN-R/.test(r) && /\(карантина\)/.test(r) && /\b3\b/.test(r)) && rowsQ.some(r => /project:/.test(r) && /\(свободна\)/.test(r) && /\b7\b/.test(r)) && !rowsQ.some(r => /в път|in_transit|quarantine/.test(r)), rows: rowsQ.map(r => r.replace(/\s+/g, ' ')) }), pc);
  const reuse = await mv(admin, { action: 'dispatch_warehouse_to_project', item_id: ITEM_B, unit: 'bag', quantity: '1', project_id: PB.id, source: loc('central_warehouse', 'CEN-R'), destination: loc('in_transit', 'pending', 'in_transit') });
  await b.step('B.10 (R18) quarantined stock cannot be reused: dispatch of 1 from free stock is refused', async () => ({ ok: reuse.status >= 400, status: reuse.status, code: code(reuse) }));
  const rel = await mv(admin, { action: 'quarantine_release', item_id: ITEM_B, unit: 'bag', quantity: '3', source: loc('central_warehouse', 'CEN-R', 'quarantine'), destination: loc('central_warehouse', 'CEN-R') });
  b.noScreen('B.11 quarantine release: the form sends the source with state free only, so a quarantine source cannot be entered', 'released by API', { api_status: rel.status });
  await b.step('B.11b [API] quarantine release after the quality check -> 200; value conserved (3 x 10 = 30 free)', async () => { const bal = await http('GET', `/warehouse/canonical/stock/${ITEM_B}?location_type=central_warehouse&location_id=CEN-R&state=free`, admin); return { ok: rel.status === 200 && Number(bal.body?.total_value ?? bal.body?.stock?.total_value) === 30, rel: rel.status, code: code(rel), stock: bal.body }; });
  const reuse2 = await mv(admin, { action: 'dispatch_warehouse_to_project', item_id: ITEM_B, unit: 'bag', quantity: '1', project_id: PB.id, source: loc('central_warehouse', 'CEN-R'), destination: loc('in_transit', 'pending', 'in_transit') });
  await b.step('B.12 after release the stock is reusable: dispatch of 1 -> 200', async () => ({ ok: reuse2.status === 200, status: reuse2.status, code: code(reuse2) }));
  // project -> project transfer
  const directPP = await mv(admin, { action: 'transfer_project_to_project', item_id: ITEM_B, unit: 'bag', quantity: '2', project_id: PB.id, source: loc('project', PB.id), destination: loc('project', PC_.id) });
  await b.step('B.13 (R18) direct project -> project move (destination = the other project) is refused', async () => ({ ok: directPP.status >= 400 && directPP.status < 500, status: directPP.status, code: code(directPP) }));
  const pp = await cmdUI(pc, { action: 'transfer_project_to_project', item: ITEM_B, qty: 2, src: ['project', PB.id], target: ['project', PC_.id], project: PB.id });
  await b.step('B.14 (R18) [1280 UI] transfer 2 project B -> project C -> 200, in transit', async () => ({ ok: pp.status === 200 && pp.body?.envelope?.destination?.location_type === 'in_transit', status: pp.status, code: code(pp) }), pc);
  await chk('B.15 (R17) project->project in transit: B still 70, C still 0', PB.id, null, { m: 70, w: 0, t: 70 }, null);
  await chk('B.15 project C still 0', PC_.id, null, { m: 0, w: 0, t: 0 }, null);
  const ppa = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_B, qty: 2, dst: ['project', PC_.id], project: PC_.id, dispatchId: pp.body?.movement_id, accepted: 2, requested: 2, src: ['supplier', ''] });
  await b.step('B.16 [1280 UI] project C accepts the 2 -> 200', async () => ({ ok: ppa.status === 200, status: ppa.status, code: code(ppa) }), pc);
  await chk('B.17 (R17) after acceptance at C: project B 50 (lot left), project C 20 (lot arrived)', PB.id, null, { m: 50, w: 0, t: 50 }, null);
  await chk('B.17 project C 20', PC_.id, null, { m: 20, w: 0, t: 20 }, null);

  // ===== C. R21: partial accept with three batch prices — FIFO layers, фира/consume follow them =====
  const PD = await mkProject('BOT-PD'); const ITEM_D = 'it-r21'; mkItem(ITEM_D); mkPkg(PD.id, 'pkg-r21', ITEM_D);
  await pc.goto(b.UI + '/warehouse/canonical'); await pc.getByTestId('wh-tab-stock').waitFor();
  const rr = [];
  for (const [q, pr] of [[7000, '1'], [11000, '2.5'], [5000, '3.33']]) rr.push(await cmdUI(pc, { action: 'receive_from_supplier', item: ITEM_D, qty: q, unitValue: pr, src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN-D'] }));
  const cD = await cmdUI(pc, { action: 'dispatch_warehouse_to_project', item: ITEM_D, qty: 15000, src: ['central_warehouse', 'CEN-D'], project: PD.id });
  await b.step('C.1 [1280 UI] receive 7000@1, 11000@2.5, 5000@3.33 and dispatch 15000 -> all 200', async () => ({ ok: [...rr, cD].every(r => r.status === 200), statuses: [...rr, cD].map(r => r.status) }), pc);
  const cA1 = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_D, qty: 9000, dst: ['project', PD.id], project: PD.id, dispatchId: cD.body?.movement_id, accepted: 9000, requested: 15000, src: ['supplier', ''] });
  const layers = (r) => (r.body?.envelope?.layer_allocations || []).map(a => `${Number(a.quantity)}@${Number(a.unit_value)}`);
  await b.step('C.2 (R21) [1280 UI] accept 9000 takes the dispatched layers oldest first: 7000@1 + 2000@2.5 (not pro-rata)', async () => ({ ok: cA1.status === 200 && JSON.stringify(layers(cA1)) === JSON.stringify(['7000@1', '2000@2.5']), status: cA1.status, layers: layers(cA1), code: code(cA1) }), pc);
  await chk('C.3 (R21) project cost after accepting 9000 = 7000x1 + 2000x2.5 = 12000', PD.id, null, { m: 12000, w: 0, t: 12000 }, null);
  const remDisc = jq('bot_op', `db.warehouse_transactions.find({movement_id:'${cA1.body?.unresolved_discrepancy_movement_id || cA1.body?.envelope?.unresolved_discrepancy_movement_id || ''}'}).toArray().map(d=>({qty:d.quantity,layers:(d.layer_allocations||[]).map(a=>a.quantity+'@'+a.unit_value),value:d.total_value}))`);
  const openD = jq('bot_op', `db.warehouse_transactions.find({action:'transit_discrepancy',dispatch_movement_id:'${cD.body?.movement_id}'}).toArray().map(d=>({qty:d.quantity,layers:(d.layer_allocations||[]).map(a=>Number(a.quantity)+'@'+Number(a.unit_value)),value:Number(d.total_value)}))`);
  await b.step('C.4 (R21) the unresolved remainder keeps the leftover layer 6000@2.5 (value 15000)', async () => ({ ok: openD.length === 1 && openD[0].qty === '6000' && JSON.stringify(openD[0].layers) === JSON.stringify(['6000@2.5']) && openD[0].value === 15000, discrepancy: openD }));
  const cA2 = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_D, qty: 6000, dst: ['project', PD.id], project: PD.id, dispatchId: cD.body?.movement_id, accepted: 6000, requested: 15000, src: ['supplier', ''] });
  await b.step('C.5 (R21) [1280 UI] accept 6000 takes 6000@2.5; 0 unresolved afterwards', async () => ({ ok: cA2.status === 200 && JSON.stringify(layers(cA2)) === JSON.stringify(['6000@2.5']) && await openDisc(cD.body?.movement_id) === 0, status: cA2.status, layers: layers(cA2), open: await openDisc(cD.body?.movement_id) }), pc);
  await chk('C.6 project cost 27000 after both acceptances (7000x1 + 8000x2.5)', PD.id, 'pkg-r21', { m: 27000, w: 0, t: 27000 }, { m: 0, w: 0, t: 0 });
  const cC = await cmdUI(pc, { action: 'consume_to_smr', item: ITEM_D, qty: 10000, src: ['project', PD.id], dst: ['central_warehouse', ''], project: PD.id, smr: PD.smr });
  const cW = await woProj(admin, PD.id, ITEM_D, 5000);
  const val = (r) => (r.body?.envelope?.layer_allocations || []).reduce((x, a) => x + Number(a.quantity) * Number(a.unit_value), 0);
  await b.step('C.7 (R21) consume 10000 follows the batches oldest first: 7000@1 + 3000@2.5 = 14500', async () => ({ ok: cC.status === 200 && Math.abs(val(cC) - 14500) < 0.01, status: cC.status, value: val(cC), layers: layers(cC) }), pc);
  await b.step('C.8 (R21) [API] write-off 5000 takes 5000@2.5 = 12500 (pro-rata would have been 9800)', async () => ({ ok: okS(cW) && Math.abs(val(cW) - 12500) < 0.01, status: cW.status, value: val(cW), layers: layers(cW) }));
  await chk('C.9 (R21) cost 27000 unchanged, фира 12500 (material 14500); package = consumed 14500 + фира 12500', PD.id, 'pkg-r21', { m: 14500, w: 12500, t: 27000 }, { m: 14500, w: 12500, t: 27000 });
  const wh = await http('GET', `/warehouse/canonical/stock/${ITEM_D}?location_type=central_warehouse&location_id=CEN-D&state=free`, admin);
  await b.step('C.10 (R21) warehouse keeps the remaining batches exactly: 3000@2.5 + 5000@3.33 = value 24150', async () => ({ ok: Math.abs(Number(wh.body?.total_value ?? wh.body?.stock?.total_value) - 24150) < 0.01, stock: wh.body }));
  await screens('C.9', PD.id, { m: 14500, w: 12500, t: 27000 }, pc, '1280');

  // ===== D. FG-17: project P&L and net profit show the same number (invoice Path B + warehouse) =====
  const PE = await mkProject('BOT-PE'); const ITEM_E = 'it-fg17'; mkItem(ITEM_E);
  mongo('bot_op', `db.invoice_lines.insertOne({id:'il-fg17',org_id:'${S.orgA}',allocation_type:'project',allocation_ref_id:'${PE.id}',line_total_ex_vat:100,vat_amount:20,description:'supplier invoice line (direct to project)',qty:10,created_at:'2026-11-01T10:00:00+00:00'})`);
  await pc.goto(b.UI + '/warehouse/canonical'); await pc.getByTestId('wh-tab-stock').waitFor();
  const eR = await cmdUI(pc, { action: 'receive_from_supplier', item: ITEM_E, qty: 10, unitValue: '10', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN-E'] });
  const eD = await cmdUI(pc, { action: 'dispatch_warehouse_to_project', item: ITEM_E, qty: 5, src: ['central_warehouse', 'CEN-E'], project: PE.id });
  const eA = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_E, qty: 5, dst: ['project', PE.id], project: PE.id, dispatchId: eD.body?.movement_id, accepted: 5, requested: 5, src: ['supplier', ''] });
  const eC = await cmdUI(pc, { action: 'consume_to_smr', item: ITEM_E, qty: 3, src: ['project', PE.id], dst: ['central_warehouse', ''], project: PE.id, smr: PE.smr });
  const eW = await woProj(admin, PE.id, ITEM_E, 2);
  await b.step('D.1 [1280 UI] invoice line 100 (Path B, direct to project) + receive 10, dispatch 5, accept 5, consume 3, write-off 2 (API) -> all 200', async () => ({ ok: [eR, eD, eA, eC, eW].every(okS), statuses: [eR, eD, eA, eC, eW].map(r => r.status) }), pc);
  await chk('D.2 (FG-17) invoice 100 + accepted 50 = 150 everywhere, фира 20 (no max(invoice, warehouse))', PE.id, null, { m: 130, w: 20, t: 150 }, null);
  const pnlE = (await http('GET', `/projects/${PE.id}/pnl`, admin)).body, npE = (await http('GET', `/project-net-profit/${PE.id}`, admin)).body, ppE = (await http('GET', `/project-profit/${PE.id}`, admin)).body;
  await b.step('D.3 (FG-17) P&L total expense == net-profit total cost == project-profit total == 150', async () => ({ ok: pnlE.expense.total_expense === npE.costs.gross_cost && npE.costs.gross_cost === ppE.expenses.total && pnlE.expense.total_expense === 150, pnl: pnlE.expense.total_expense, net_profit: npE.costs.gross_cost, project_profit: ppE.expenses.total, pnl_basis: pnlE.warehouse_cost_basis }));
  const scr = await screens('D.4 (FG-17)', PE.id, { m: 130, w: 20, t: 150 }, pc, '1280');
  await b.step('D.5 (FG-17) the two screens show the same total: financial page "Общ разход" == project P&L dashboard "Общо разход"', async () => ({ ok: scr['financial page']?.t === scr['project page, Finance tab (P&L dashboard)']?.t && scr['financial page']?.t === 150, financial_page: scr['financial page'], pnl_dashboard: scr['project page, Finance tab (P&L dashboard)'] }));
  const invOnly = await http('GET', `/projects/${PE.id}/pnl/summary`, admin);
  b.noScreen('D.6 the supplier invoice line (Path B) cannot be created from the canonical warehouse screen; seeded directly', 'invoice_lines row inserted into the synthetic tenant DB', { pnl_summary_total_expense: invOnly.body?.total_expense });
  await dc.ctx.close();

  // ---------- WAREHOUSE -> WAREHOUSE TRANSFER (Rule B) ----------
  const tw = await b.context('desktop'); const pt = tw.page; await b.login(pt, 'admin@bot-a.test', PW); await openCanonical(pt);
  const ITEM_T = 'it-transfer'; mongo('bot_op', `db.md_item.insertOne({id:'${ITEM_T}',tenant_id:'${S.orgA}',canonical_unit:'bag',name:'transfer item (synthetic)'})`);
  const t_r = await cmdUI(pt, { action: 'receive_from_supplier', item: ITEM_T, qty: 10, unitValue: '12', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  const direct2 = await mv(admin, { action: 'transfer_warehouse_to_warehouse', item_id: ITEM_T, unit: 'bag', quantity: '10', source: loc('central_warehouse', 'CEN'), destination: loc('small_warehouse', 'WH2') });
  const stockNow = await http('GET', `/warehouse/canonical/balance/${ITEM_T}`, admin);
  await b.step('T.1 direct warehouse->warehouse transfer (destination = the other warehouse) is refused and moves nothing', async () => ({ ok: direct2.status >= 400 && direct2.status < 500 && (stockNow.body?.balances || []).every(r => !(r.location_id === 'WH2' && Number(r.quantity) > 0)), status: direct2.status, code: code(direct2), message: (direct2.body?.detail?.message || '').slice(0, 140), balances: (stockNow.body?.balances || []).map(r => `${r.location_type}:${r.location_id}:${r.state}=${r.quantity}`) }));
  await pt.getByTestId('wh-tab-commands').click(); await pt.getByTestId('wh-action-select').selectOption('transfer_warehouse_to_warehouse');
  await b.step('T.2 [1280 UI] transfer form: fixed in-transit destination + a target-warehouse field (no direct destination picker)', async () => ({ ok: await pt.getByTestId('wh-dispatch-in-transit').isVisible() && await pt.getByTestId('wh-transfer-target-id').isVisible(), }), pt);
  const tr = await cmdUI(pt, { action: 'transfer_warehouse_to_warehouse', item: ITEM_T, qty: 10, src: ['central_warehouse', 'CEN'], target: ['small_warehouse', 'WH2'] });
  S.transfer = tr.body?.movement_id;
  await b.step('T.3 [1280 UI] transfer 10 CEN -> WH2 -> 200, stock in transit (CEN 0, WH2 0)', async () => { const bal = await http('GET', `/warehouse/canonical/balance/${ITEM_T}`, admin); const rows = (bal.body?.balances || []).map(r => `${r.location_type}:${r.location_id}:${r.state}=${r.quantity}`); return { ok: tr.status === 200 && !rows.some(r => /WH2:free=[1-9]/.test(r)) && !rows.some(r => /CEN:free=[1-9]/.test(r)), status: tr.status, code: code(tr), rows }; }, pt);
  const ta = [];
  for (const q of [6, 4]) { const r = await cmdUI(pt, { action: 'accept_project_delivery', item: ITEM_T, qty: q, dst: ['small_warehouse', 'WH2'], project: '', dispatchId: S.transfer, accepted: q, requested: 10, src: ['supplier', ''] }); ta.push({ q, status: r.status, code: code(r), message: (r.body?.detail?.message || '').slice(0, 120), open: await openDisc(S.transfer) }); }
  const wh2 = await http('GET', `/warehouse/canonical/balance/${ITEM_T}`, admin);
  await b.step('T.4 [1280 UI] accept 6 then 4 at WH2 -> both 200; 1 open discrepancy after 6, 0 after 4', async () => ({ ok: ta.every(a => a.status === 200) && ta[0].open === 1 && ta[1].open === 0, ta }), pt);
  await b.step('T.5 transfer ends with 0 unresolved (ledger + in-transit projection) and WH2 holds 10, CEN 0', async () => { const rows = (wh2.body?.balances || []).map(r => `${r.location_type}:${r.location_id}:${r.state}=${r.quantity}`); return { ok: await openDisc(S.transfer) === 0 && rows.some(r => /WH2:free=10/.test(r)) && !rows.some(r => /CEN:free=[1-9]/.test(r)), open: await openDisc(S.transfer), in_transit: await inTransit(S.transfer), rows }; }, pt);
  const over = await mv(admin, { action: 'accept_project_delivery', item_id: ITEM_T, unit: 'bag', quantity: '1', accepted_quantity: '1', requested_quantity: '10', dispatch_movement_id: S.transfer, destination: loc('small_warehouse', 'WH2') });
  await b.step('T.6 over-acceptance of the finished transfer is refused', async () => ({ ok: over.status >= 400, status: over.status, code: code(over) }));
  await tw.ctx.close();
  const tm = await b.context('phone'); await b.login(tm.page, 'admin@bot-a.test', PW); await openCanonical(tm.page); await tm.page.getByTestId('wh-tab-commands').click(); await tm.page.getByTestId('wh-action-select').selectOption('transfer_warehouse_to_warehouse');
  await b.step('T.7 [390] transfer form usable on the phone, no horizontal scroll', async () => ({ ok: await tm.page.getByTestId('wh-transfer-target-id').isVisible() && await noHScroll(tm.page) }), tm.page); await tm.ctx.close();

  // ===== R27 / R30: who may write material off a PROJECT („фира") =====
  const WENV = { ...process.env, ENV: 'development', MONGO_URL: 'mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true', DB_NAME: 'bot_op', BEG_SYSTEM_DB: 'bot_sys', JWT_SECRET: 'bot-local-secret' };
  if (MODE === 'enforce') execFileSync('/tmp/botvenv/bin/python', [__dirname + '/grant_role.py', 'pm@bot-a.test', 'project_manager'], { cwd: '/tmp/botwt/' + (process.env.BOT_SHA || '8025871') + '/backend', env: WENV });
  const usersList = (await http('GET', '/users', admin)).body; const uid = (e) => usersList.find(u => u.email === e)?.id;
  const tk2 = { sm: await login('sm@bot-a.test'), tech2: await login('tech2@bot-a.test'), pm: await login('pm@bot-a.test') };
  const PX = await mkProject('BOT-R27'), PY = await mkProject('BOT-R27B'), PZ = await mkProject('BOT-R27C'); const ITEM_W = 'it-r27'; mkItem(ITEM_W);
  const wr = await mv(admin, { action: 'receive_from_supplier', item_id: ITEM_W, unit: 'bag', quantity: '60', unit_value: '10', source: loc('supplier', 'sup1'), destination: loc('central_warehouse', 'CEN-W') });
  for (const pj of [PX, PY, PZ]) { const d = await mv(admin, { action: 'dispatch_warehouse_to_project', item_id: ITEM_W, unit: 'bag', quantity: '15', project_id: pj.id, source: loc('central_warehouse', 'CEN-W'), destination: loc('in_transit', 'pending', 'in_transit') }); const a = await mv(admin, { action: 'accept_project_delivery', item_id: ITEM_W, unit: 'bag', quantity: '15', accepted_quantity: '15', requested_quantity: '15', dispatch_movement_id: d.body?.movement_id, project_id: pj.id, destination: loc('project', pj.id) }); pj.stock = a.status; }
  await b.step('R.0 stock for the write-off rights matrix: 15 on each of three projects (200)', async () => ({ ok: wr.status === 200 && [PX, PY, PZ].every(p => p.stock === 200), statuses: [wr.status, PX.stock, PY.stock, PZ.stock] }));
  const team = async (pj, email, role) => http('POST', `/projects/${pj.id}/team`, admin, { user_id: uid(email), role_in_project: role });
  const tmem = [await team(PX, 'sm@bot-a.test', 'SiteManager'), await team(PX, 'tech2@bot-a.test', 'Technician'), await team(PX, 'pm@bot-a.test', 'SiteManager'), await team(PY, 'pm@bot-a.test', 'Technician')];
  await b.step('R.1 project team set up through the API: sm + tech2 + pm on project X (pm as team manager), pm on project Y only as a technician', async () => ({ ok: tmem.every(r => r.status === 201 || r.status === 200), statuses: tmem.map(r => r.status), codes: tmem.map(code) }));
  const woCount = () => jq('bot_op', `db.warehouse_transactions.countDocuments({action:'write_off',item_id:'${ITEM_W}'})`);
  const matrix = [
    ['Admin', admin, PX, true], ['Accountant', tk.acc, PX, true], ['Warehousekeeper', tk.wk, PX, false], ['Viewer', tk.viewer, PX, false],
    ['SiteManager, member of X', tk2.sm, PX, true], ['SiteManager, NOT a member (project Y)', tk2.sm, PY, false],
    ['Technician, member of X', tk2.tech2, PX, true], ['Technician, NOT a member (project Y)', tk2.tech2, PY, false], ['Technician (never added), project X', tk.tech, PX, false],
  ];
  if (MODE === 'enforce') matrix.push(['Project manager, team MANAGER of X (Р30)', tk2.pm, PX, true], ['Project manager, only a technician on Y (Р30)', tk2.pm, PY, false], ['Project manager, no membership (Z)', tk2.pm, PZ, false]);
  for (const [label, token, pj, allowed] of matrix) {
    const before = await woCount(); const r = await woProj(token, pj.id, ITEM_W, 1); const after = await woCount();
    await b.step(`R.2 [${MODE}] write-off 1 from a project — ${label}: ${allowed ? '2xx, one row written' : '403, nothing written'}`, async () => ({ ok: allowed ? okS(r) && after === before + 1 : r.status === 403 && after === before, status: r.status, code: code(r), reason: r.body?.detail?.reason_code || r.body?.detail?.context?.reason_code, rows_written: after - before }));
  }
  if (MODE !== 'enforce') b.noScreen('R.3 project manager (Р30) cannot be tested in this mode: the legacy session roles have no project manager', 'canonical project_manager is a RoleAssignment role; exercised in the enforce run', {});
  // a write-off from a WAREHOUSE is not project cost: only the generic gate
  const whWo = (token) => mv(token, { action: 'write_off', item_id: ITEM_W, unit: 'bag', quantity: '1', source: loc('central_warehouse', 'CEN-W'), reason: 'brak', file_ids: ['file-bot-w'] });
  const w1 = await whWo(admin), w2 = await whWo(tk.acc), w3 = await whWo(tk.wk);
  await b.step(`R.4 [${MODE}] write-off from a WAREHOUSE (not project cost): Admin 200; Accountant 403; Warehousekeeper 403`, async () => ({ ok: w1.status === 200 && w2.status === 403 && w3.status === 403, admin: w1.status, accountant: w2.status, keeper: w3.status, codes: [code(w1), code(w2), code(w3)] }));
  // the generic /movements route must not let a denied role write off from a project
  const gen = await mv(tk.wk, { action: 'write_off', item_id: ITEM_W, unit: 'bag', quantity: '1', source: loc('project', PX.id), reason: 'brak', file_ids: ['file-bot-g'] });
  await b.step(`R.5 [${MODE}] the generic /movements route does not bypass Р27: Warehousekeeper write_off from a project -> 403`, async () => ({ ok: gen.status === 403, status: gen.status, code: code(gen) }));

  // ===== Р32 / Р34: the Warehousekeeper sees WAREHOUSE unit prices but no money on PROJECT rows =====
  const moneyKeys = (o, path = '', out = []) => { if (Array.isArray(o)) o.forEach((x, i) => moneyKeys(x, path + '[' + i + ']', out)); else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { if (k !== 'values_hidden' && /(value|cost|price|amount)/i.test(k)) out.push(path + '.' + k); else moneyKeys(v, path + '.' + k, out); } return out; };
  const hist = async (token, q = '') => (await http('GET', '/warehouse/canonical/history?limit=200' + q, token)).body?.rows || [];
  const touchesProject = (r) => !!(r.project_id || r.subproject_id || ['project', 'subproject'].some(t => r.source?.location_type === t || r.destination?.location_type === t));
  const kRows = await hist(tk.wk), aRows = await hist(tk.acc);
  const projRows = kRows.filter(touchesProject), whRows = kRows.filter(r => !touchesProject(r) && ['receive_from_supplier'].includes(r.action));
  await b.step(`R34.1 [${MODE}] Warehousekeeper history: every PROJECT row (consume, фира, dispatch to project, accept) carries NO money (${projRows.length} rows)`, async () => ({ ok: projRows.length >= 10 && projRows.every(r => moneyKeys(r).length === 0), project_rows: projRows.length, actions: [...new Set(projRows.map(r => r.action))], leaking: projRows.filter(r => moneyKeys(r).length).map(r => r.action).slice(0, 5) }));
  await b.step(`R32.1 [${MODE}] Warehousekeeper history: WAREHOUSE receipt rows still show the unit price (${whRows.length} rows)`, async () => ({ ok: whRows.length >= 3 && whRows.every(r => r.unit_value !== undefined && r.unit_value !== null), sample: whRows.slice(0, 2).map(r => ({ action: r.action, unit_value: r.unit_value })) }));
  await b.step(`R32.2 [${MODE}] control: Accountant sees money on the project rows too`, async () => ({ ok: aRows.filter(touchesProject).some(r => moneyKeys(r).length > 0), project_rows_with_money: aRows.filter(touchesProject).filter(r => moneyKeys(r).length).length }));
  const kStock = await http('GET', `/warehouse/canonical/stock/${ITEM_D}?location_type=central_warehouse&location_id=CEN-D&state=free`, tk.wk);
  await b.step(`R32.3 [${MODE}] Warehousekeeper reads the central warehouse stock WITH prices (total_value 24150, layer unit prices), not values_hidden`, async () => ({ ok: kStock.status === 200 && Math.abs(Number(kStock.body?.total_value) - 24150) < 0.01 && (kStock.body?.layers || []).every(l => l.unit_value !== undefined) && !kStock.body?.values_hidden, status: kStock.status, total_value: kStock.body?.total_value, layers: (kStock.body?.layers || []).map(l => l.quantity + '@' + l.unit_value) }));
  const kRecvW = await recv(tk.wk, 1, ITEM_K, '7');
  const kDispP = await mv(tk.wk, { action: 'dispatch_warehouse_to_project', item_id: ITEM_K, unit: 'bag', quantity: '1', project_id: PX.id, source: loc('central_warehouse', 'CEN'), destination: loc('in_transit', 'pending', 'in_transit') });
  await b.step(`R32.4 [${MODE}] keeper's command responses: receive to the warehouse shows unit_value 7; dispatch to a PROJECT carries no money`, async () => ({ ok: kRecvW.status === 200 && String(kRecvW.body?.envelope?.unit_value) === '7' && okS(kDispP) && moneyKeys(kDispP.body?.envelope).length === 0, receive: { status: kRecvW.status, unit_value: kRecvW.body?.envelope?.unit_value }, dispatch_project: { status: kDispP.status, code: code(kDispP), money_keys: moneyKeys(kDispP.body?.envelope).length } }));
  const kIw = await http('GET', '/warehouse/canonical/integrity-warnings', tk.wk);
  await b.step(`R34.2 [${MODE}] keeper's integrity-warnings: HTTP 200, no money`, async () => ({ ok: kIw.status === 200 && moneyKeys(kIw.body).length === 0, status: kIw.status }));
  { const c = await b.context('desktop'); await b.login(c.page, 'wk@bot-a.test', PW); await openCanonical(c.page);
    const tabsK = await c.page.locator('[data-testid^="wh-tab-"]').evaluateAll(els => els.map(e => e.getAttribute('data-testid').replace('wh-tab-', '')));
    await c.page.getByTestId('wh-tab-central').click(); await c.page.getByTestId('wh-central-item').fill(ITEM_D); await c.page.getByTestId('wh-central-location').fill('CEN-D'); await c.page.getByRole('button', { name: 'Покажи наличност и цени' }).click(); await c.page.waitForTimeout(1500);
    const val = (await c.page.getByTestId('wh-central-value').innerText().catch(() => '')).trim(); const layersK = await c.page.getByTestId('wh-central-layer').allInnerTexts().catch(() => []);
    await b.step(`R32.5 [${MODE}] [1280 UI] keeper's tab „Централен склад“ shows quantity AND unit prices (value ${val}); keeper has no „Цени“ tab; tabs: ${tabsK.join(',')}`, async () => ({ ok: tabsK.includes('central') && !tabsK.includes('prices') && /24150/.test(val) && layersK.length >= 2 && layersK.every(x => /×/.test(x)), tabs: tabsK, value: val, layers: layersK.map(x => x.replace(/\s+/g, ' ')) }), c.page);
    await c.page.getByTestId('wh-tab-commands').click(); await c.page.getByTestId('wh-action-select').selectOption('receive_from_supplier');
    await b.step(`R32.6 [${MODE}] [1280 UI] keeper's receive form has the unit-price input (he enters the price at receipt, Р32)`, async () => ({ ok: (await field(c.page, 'Единична стойност').count()) > 0 }), c.page);
    await c.page.goto(b.UI + `/projects/${PX.id}/financial`); await c.page.waitForTimeout(2500); const landed = c.page.url().replace(b.UI, ''); const fin = (await c.page.locator('body').innerText()).replace(/\s+/g, ' ');
    await b.step(`R34.3 [${MODE}] [1280 UI] keeper cannot open the project financial page (no project money): landed ${landed}`, async () => ({ ok: !landed.includes('/financial') && !/МАТЕРИАЛИ\s*\d/.test(fin), landed }), c.page);
    await c.ctx.close(); }
  { const c = await b.context('phone'); await b.login(c.page, 'wk@bot-a.test', PW); await openCanonical(c.page); await c.page.getByTestId('wh-tab-central').click(); await c.page.getByTestId('wh-central-item').fill(ITEM_D); await c.page.getByTestId('wh-central-location').fill('CEN-D'); await c.page.getByRole('button', { name: 'Покажи наличност и цени' }).click(); await c.page.waitForTimeout(1500);
    await b.step(`R32.7 [${MODE}] [390 UI] keeper's central warehouse tab shows prices, no horizontal scroll`, async () => ({ ok: /24150/.test(await c.page.getByTestId('wh-central-value').innerText().catch(() => '')) && await noHScroll(c.page) }), c.page); await c.ctx.close(); }

  // ===== Р35: tabs „Централен склад“ and „Цени“ — SiteManager / Technician see stock and prices but move nothing =====
  const ITEM_PH = 'it-price', ITEM_PH2 = 'it-price2', ITEM_PH3 = 'it-once'; for (const i of [ITEM_PH, ITEM_PH2, ITEM_PH3]) mkItem(i);
  const buy = async (item, q, price, sup) => mv(admin, { action: 'receive_from_supplier', item_id: item, unit: 'bag', quantity: String(q), unit_value: String(price), source: loc('supplier', sup), destination: loc('central_warehouse', 'CEN-P') });
  const buys = [await buy(ITEM_PH, 5, 10, 'sup-A'), await buy(ITEM_PH, 5, 12, 'sup-A'), await buy(ITEM_PH, 5, 11, 'sup-A'), await buy(ITEM_PH2, 5, 5, 'sup-A'), await buy(ITEM_PH2, 5, 6, 'sup-B'), await buy(ITEM_PH3, 5, 9, 'sup-A')];
  await b.step('P.0 purchases: article 1 bought 3 times from ONE supplier at 10, 12, 11; article 2 from two suppliers at 5 and 6; article 3 once at 9 (all 200)', async () => ({ ok: buys.every(r => r.status === 200), statuses: buys.map(r => r.status) }));
  for (const [item, q] of [[ITEM_PH, 15], [ITEM_PH2, 10], [ITEM_PH3, 5]]) { const d = await mv(admin, { action: 'dispatch_warehouse_to_project', item_id: item, unit: 'bag', quantity: String(q), project_id: PX.id, source: loc('central_warehouse', 'CEN-P'), destination: loc('in_transit', 'pending', 'in_transit') }); const a = await mv(admin, { action: 'accept_project_delivery', item_id: item, unit: 'bag', quantity: String(q), accepted_quantity: String(q), requested_quantity: String(q), dispatch_movement_id: d.body?.movement_id, project_id: PX.id, destination: loc('project', PX.id) }); if (!okS(d) || a.status !== 200) throw new Error('price scenario dispatch/accept failed ' + item + ' ' + d.status + ' ' + a.status); }
  const ph = await http('GET', `/warehouse/canonical/price-history?project_id=${PX.id}`, admin); const art = (ph.body?.articles || []);
  const pa1 = art.find(x => x.item_id === ITEM_PH), pa2 = art.find(x => x.item_id === ITEM_PH2), pa3 = art.find(x => x.item_id === ITEM_PH3);
  await b.step('P.1 [API, Admin] price history of the project: article 1 FLAGGED (SAME_SUPPLIER_DIFFERENT_PRICE, sup-A, prices 10/11/12), best price 10; article 2 not flagged, best 5; the once-bought article is absent', async () => ({ ok: !!pa1 && pa1.flagged === true && pa1.flags?.[0]?.code === 'SAME_SUPPLIER_DIFFERENT_PRICE' && pa1.flags[0].supplier === 'sup-A' && JSON.stringify(pa1.flags[0].prices) === JSON.stringify(['10', '11', '12']) && Number(pa1.best_price.unit_price) === 10 && pa1.purchase_count === 3 && !!pa2 && pa2.flagged === false && Number(pa2.best_price.unit_price) === 5 && !pa3, pa1: pa1 && { flagged: pa1.flagged, flags: pa1.flags, best: pa1.best_price, purchases: pa1.purchases.map(p => p.unit_price) }, pa2: pa2 && { flagged: pa2.flagged, best: pa2.best_price }, once_bought_present: !!pa3 }));
  const roleScreens = async (vpName, tag, email, label) => { const c = await b.context(vpName); await b.login(c.page, email, PW); await c.page.waitForLoadState('networkidle'); await c.page.goto(b.UI + '/warehouse/canonical'); await c.page.getByTestId('wh-tab-central').waitFor({ timeout: 15000 }).catch(() => {});
    const tabs = await c.page.locator('[data-testid^="wh-tab-"]').evaluateAll(els => els.map(e => e.getAttribute('data-testid').replace('wh-tab-', '')));
    let acts = []; if (tabs.includes('commands')) { await c.page.getByTestId('wh-tab-commands').click(); acts = await c.page.getByTestId('wh-action-select').locator('option').evaluateAll(o => o.map(x => x.value)); }
    await b.step(`P.2 [${MODE}] [${tag} UI] ${label}: the screen opens with the tabs „Централен склад“ and „Цени“; no action that moves stock at the central warehouse (write tab: ${tabs.includes('commands') ? 'project actions only: ' + acts.join(',') : 'none'})`, async () => ({ ok: tabs.includes('central') && tabs.includes('prices') && !acts.some(a => ['receive_from_supplier', 'receive_from_supplier_to_project', 'dispatch_warehouse_to_project', 'transfer_warehouse_to_warehouse', 'reserve', 'release_reservation', 'return_to_supplier', 'quarantine_release'].includes(a)), tabs, actions: acts }), c.page);
    await c.page.getByTestId('wh-tab-central').click(); await c.page.getByTestId('wh-central-item').fill(ITEM_D); await c.page.getByTestId('wh-central-location').fill('CEN-D'); await c.page.getByRole('button', { name: 'Покажи наличност и цени' }).click(); await c.page.waitForTimeout(1500);
    const v = (await c.page.getByTestId('wh-central-value').innerText().catch(() => '')).trim(); const lay = await c.page.getByTestId('wh-central-layer').allInnerTexts().catch(() => []);
    await b.step(`P.3 [${MODE}] [${tag} UI] ${label}: „Централен склад“ shows stock AND prices (value ${v}, ${lay.length} priced layers)`, async () => ({ ok: /24150/.test(v) && lay.length >= 2 && lay.every(x => /×/.test(x)), value: v, layers: lay.map(x => x.replace(/\s+/g, ' ')) }), c.page);
    await c.page.getByTestId('wh-tab-prices').click(); await c.page.getByTestId('wh-prices-project').fill(PX.id); await c.page.getByRole('button', { name: 'Покажи ценова история' }).click(); await c.page.waitForTimeout(1500);
    const arts = await c.page.getByTestId('wh-price-article').count(); const flag = await c.page.getByTestId('wh-price-flag').count(); const best = (await c.page.getByTestId('wh-price-best').first().innerText().catch(() => '')).replace(/\s+/g, ' '); const flagTxt = (await c.page.getByTestId('wh-price-flag').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    const rows1 = await c.page.getByTestId('wh-price-article').first().getByTestId('wh-price-row').allInnerTexts().catch(() => []);
    await b.step(`P.4 [${MODE}] [${tag} UI] ${label}: „Цени“ shows the article bought 3× from one supplier with the FLAG and the best price (${best})`, async () => ({ ok: arts === 2 && flag === 1 && /Различни цени от един и същ доставчик/.test(flagTxt) && /Най-добра цена: 10 \(sup-A/.test(best) && rows1.length === 3, articles: arts, flags: flag, flag_text: flagTxt, best, rows: rows1.map(x => x.replace(/\s+/g, ' ')) }), c.page);
    if (vpName === 'phone') await b.step(`P.5 [${MODE}] [390 UI] ${label}: price history readable on the phone, no horizontal scroll`, async () => ({ ok: await noHScroll(c.page) }), c.page);
    await c.ctx.close(); };
  await roleScreens('desktop', '1280', 'sm@bot-a.test', 'SiteManager (member of the project)');
  await roleScreens('desktop', '1280', 'tech2@bot-a.test', 'Technician (member of the project)');
  await roleScreens('phone', '390', 'sm@bot-a.test', 'SiteManager (member of the project)');
  // they cannot move anything at the central warehouse
  const cenMoves = async (token) => ({ receive: await recv(token, 1, ITEM_PH, '9'), dispatch: await mv(token, { action: 'dispatch_warehouse_to_project', item_id: ITEM_D, unit: 'bag', quantity: '1', project_id: PX.id, source: loc('central_warehouse', 'CEN-D'), destination: loc('in_transit', 'pending', 'in_transit') }), transfer: await mv(token, { action: 'transfer_warehouse_to_warehouse', item_id: ITEM_D, unit: 'bag', quantity: '1', source: loc('central_warehouse', 'CEN-D'), transfer_target: loc('small_warehouse', 'WH-X'), destination: loc('in_transit', 'pending', 'in_transit') }) });
  for (const [label, token] of [['SiteManager', tk2.sm], ['Technician', tk2.tech2]]) { const m = await cenMoves(token); const bal = await http('GET', `/warehouse/canonical/stock/${ITEM_D}?location_type=central_warehouse&location_id=CEN-D&state=free`, admin);
    await b.step(`P.6 [${MODE}] [API] ${label} cannot move anything at the central warehouse: receive, dispatch and transfer all 403; stock unchanged (8000)`, async () => ({ ok: [m.receive, m.dispatch, m.transfer].every(r => r.status === 403) && Number(bal.body?.quantity) === 8000, statuses: { receive: m.receive.status, dispatch: m.dispatch.status, transfer: m.transfer.status }, codes: [code(m.receive), code(m.dispatch), code(m.transfer)], central_quantity: bal.body?.quantity })); }
  // scope: price history only for member projects; the central stock stays readable
  const phSm = await http('GET', `/warehouse/canonical/price-history?project_id=${PY.id}`, tk2.sm), phTech = await http('GET', `/warehouse/canonical/price-history?project_id=${PX.id}`, tk.tech), phWk = await http('GET', `/warehouse/canonical/price-history?project_id=${PX.id}`, tk.wk), phAcc = await http('GET', `/warehouse/canonical/price-history?project_id=${PX.id}`, tk.acc), phView = await http('GET', `/warehouse/canonical/price-history?project_id=${PX.id}`, tk.viewer);
  await b.step(`P.7 [${MODE}] price-history scope: SiteManager on a project he is NOT in 403; Technician never added 403; Warehousekeeper 403; Viewer 403; Accountant 200 with the flag`, async () => ({ ok: phSm.status === 403 && phTech.status === 403 && phWk.status === 403 && phView.status === 403 && phAcc.status === 200 && (phAcc.body?.articles || []).some(x => x.flagged), statuses: { sm_other_project: phSm.status, tech_not_member: phTech.status, keeper: phWk.status, viewer: phView.status, accountant: phAcc.status } }));
  { const c = await b.context('desktop'); await b.login(c.page, 'tech@bot-a.test', PW); await c.page.waitForLoadState('networkidle'); await c.page.goto(b.UI + '/warehouse/canonical'); await c.page.waitForTimeout(2000); const tabsT = await c.page.locator('[data-testid^="wh-tab-"]').evaluateAll(els => els.map(e => e.getAttribute('data-testid').replace('wh-tab-', '')));
    if (tabsT.includes('prices')) { await c.page.getByTestId('wh-tab-prices').click(); await c.page.getByTestId('wh-prices-project').fill(PX.id); await c.page.getByRole('button', { name: 'Покажи ценова история' }).click(); await c.page.waitForTimeout(1500); }
    await b.step(`P.8 [${MODE}] [1280 UI] a Technician who is NOT a project member asks for the project's price history: an error state, no prices (tabs: ${tabsT.join(',') || 'none'})`, async () => ({ ok: !tabsT.includes('prices') || (await c.page.locator('[role="alert"]').count()) > 0 && (await c.page.getByTestId('wh-price-article').count()) === 0, tabs: tabsT, alert: await c.page.locator('[role="alert"]').first().innerText().catch(() => '') }), c.page); await c.ctx.close(); }

  // ---------- PERMISSIONS (API) ----------
  const cons = (token) => mv(token, { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project) });
  P.keeperReceive = await recv(tk.wk, 1, ITEM_K); P.keeperConsume = await cons(tk.wk); P.keeperRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.wk);
  P.techRecv = await recv(tk.tech, 1, ITEM_K); P.techConsume = await cons(tk.tech); P.techRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.tech);
  P.viewRecv = await recv(tk.viewer, 1, ITEM_K); P.viewConsume = await cons(tk.viewer); P.viewRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.viewer);
  P.accRecv = await recv(tk.acc, 1, ITEM_K); P.accConsume = await cons(tk.acc); P.accRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.acc);
  const st = (r) => r.status;
  await b.step('3.1 keeper (Warehousekeeper): receive 200, consume_to_smr 403, read 200', async () => ({ ok: st(P.keeperReceive) === 200 && st(P.keeperConsume) === 403 && st(P.keeperRead) === 200, receive: st(P.keeperReceive), consume: st(P.keeperConsume), read: st(P.keeperRead), receive_code: code(P.keeperReceive) }));
  await b.step('3.2 technician: receive/consume/read all 403 (direct API)', async () => ({ ok: [P.techRecv, P.techConsume, P.techRead].every(r => r.status === 403), receive: st(P.techRecv), consume: st(P.techConsume), read: st(P.techRead) }));
  await b.step('3.3 viewer: receive/consume/read all 403 (direct API)', async () => ({ ok: [P.viewRecv, P.viewConsume, P.viewRead].every(r => r.status === 403), receive: st(P.viewRecv), consume: st(P.viewConsume), read: st(P.viewRead) }));
  await b.step('3.4 accountant (read-only role): receive 403, consume 403, read 200 (direct API)', async () => ({ ok: st(P.accRecv) === 403 && st(P.accConsume) === 403 && st(P.accRead) === 200, receive: st(P.accRecv), consume: st(P.accConsume), read: st(P.accRead) }));
  // ---------- PERMISSIONS (UI) ----------
  const seen = {};
  for (const [vpName, tag] of [['desktop', '1280'], ['phone', '390']]) {
    for (const [email, label] of [['wk@bot-a.test', 'keeper'], ['acc@bot-a.test', 'accountant'], ['tech@bot-a.test', 'technician'], ['viewer@bot-a.test', 'viewer']]) {
      const c = await b.context(vpName); await b.login(c.page, email, PW); await c.page.waitForLoadState('networkidle');
      await c.page.goto(b.UI + '/warehouse/canonical'); await c.page.waitForTimeout(2000);
      const url = c.page.url().replace(b.UI, ''); const onPage = (await c.page.getByTestId('wh-tab-stock').count()) > 0;
      const tabs = onPage ? await c.page.locator('[data-testid^="wh-tab-"]').evaluateAll(els => els.map(e => e.getAttribute('data-testid').replace('wh-tab-', ''))) : [];
      let actions = []; if (tabs.includes('commands')) { await c.page.getByTestId('wh-tab-commands').click(); actions = await c.page.getByTestId('wh-action-select').locator('option').evaluateAll(o => o.map(x => x.value)); }
      seen[`${label}@${tag}`] = { url, onPage, tabs, actions };
      if (label === 'keeper') await b.step(`3.5 [${tag}] keeper HAS a warehouse screen: opens /warehouse/canonical, write tab present, actions limited to receive/dispatch/accept..., no consume`, async () => ({ ok: onPage && tabs.includes('commands') && actions.includes('receive_from_supplier') && actions.includes('dispatch_warehouse_to_project') && actions.includes('accept_project_delivery') && !actions.includes('consume_to_smr'), url, tabs, actions }), c.page);
      if (label === 'accountant') await b.step(`3.6 [${tag}] accountant sees NO write form (read tabs only)`, async () => ({ ok: onPage && !tabs.includes('commands') && tabs.length > 0, url, tabs }), c.page);
      if (label === 'technician' || label === 'viewer') await b.step(`3.7 [${tag}] ${label} does not get the warehouse write form (landed ${url})`, async () => ({ ok: !tabs.includes('commands'), url, onPage, tabs }), c.page);
      if (label === 'keeper' && vpName === 'phone') await b.step('3.8 [390] keeper screen: no horizontal scroll', async () => noHScroll(c.page), c.page);
      await c.ctx.close();
    }
  }
  // keeper does a real UI receive
  { const c = await b.context('desktop'); await b.login(c.page, 'wk@bot-a.test', PW); await openCanonical(c.page); const k = await cmdUI(c.page, { action: 'receive_from_supplier', item: ITEM_K, qty: 2, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] }); await b.step('3.9 [1280 UI] keeper receives 2 through the screen -> 200', async () => ({ ok: k.status === 200, status: k.status, code: code(k) }), c.page); await c.ctx.close(); }
  b.result.ui_visibility = seen;

  // ---------- TENANT ISOLATION ----------
  const bBal = await http('GET', `/warehouse/canonical/balance/${ITEM}`, adminB); const bHist = await http('GET', '/warehouse/canonical/history', adminB);
  const bAcc = await mv(adminB, { action: 'accept_project_delivery', item_id: ITEM, unit: 'bag', quantity: '1', accepted_quantity: '1', requested_quantity: '1', dispatch_movement_id: S.disp1, project_id: 'x', destination: loc('project', 'x') });
  const bRecv = await mv(adminB, { action: 'receive_from_supplier', item_id: 'it-b', unit: 'bag', quantity: '2', unit_value: '3', source: loc('supplier', 'supB'), destination: loc('central_warehouse', 'CEN-B') });
  const bAfter = await http('GET', `/warehouse/canonical/balance/${ITEM}`, adminB); const aStill = await http('GET', `/warehouse/canonical/balance/it-b`, admin);
  await b.step('4.1 tenant B: balance of A item empty; history empty', async () => ({ ok: (bBal.body?.balances || []).length === 0 && (bHist.body?.rows || []).length === 0, bal: bBal.body?.balances, hist: (bHist.body?.rows || []).length }));
  await b.step('4.2 tenant B cannot accept tenant A dispatch (write refused)', async () => ({ ok: bAcc.status >= 400, status: bAcc.status, code: code(bAcc) }));
  await b.step('4.2b tenant B can write in its OWN database on a fresh install (receive 2) and A does not see it', async () => ({ ok: bRecv.status === 200 && (aStill.body?.balances || []).length === 0, b_status: bRecv.status, b_code: code(bRecv), b_message: (bRecv.body?.detail?.message || '').slice(0, 160), a_sees: (aStill.body?.balances || []).length }));
  for (const [vpName, tag] of [['desktop', '1280'], ['phone', '390']]) {
    const c = await b.context(vpName); await b.login(c.page, 'admin@bot-b.test', PW); await openCanonical(c.page); const rowsB = await stockUI(c.page, ITEM);
    await b.step(`4.3 [${tag} UI] tenant B stock panel for A's item shows empty`, async () => ({ ok: rowsB.length === 0, rows: rowsB }), c.page); await c.ctx.close();
  }
  const aBal = await http('GET', `/warehouse/canonical/balance/${ITEM}`, admin);
  await b.step('4.4 control: tenant A still sees its own stock', async () => ({ ok: (aBal.body?.balances || []).length > 0, n: (aBal.body?.balances || []).length }));
  b.result.facts = S; b.result.permission_http = Object.fromEntries(Object.entries(P).map(([k, v]) => [k, v.status + (code(v) ? ' ' + code(v) : '')]));
}, { outDir: process.env.BOT_OUT, sha: process.env.BOT_SHA });

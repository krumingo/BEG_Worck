// BOT 5C-C18 — PR #55 @ 639ca80 — canonical warehouse scenario. Synthetic data only.
// Needs: stack up with PERMISSION_SERVICE_MODE=enforce, tenants registered (see README).
const { execFileSync } = require('child_process');
const bot = require('../runner/lib');
const API = bot.API, PW = 'BotPass-12345!', ITEM = 'it-cement', ITEM_K = 'it-keeper';
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

bot.run('5C-C18', async (b) => {
  const S = {}; // shared ids
  // ---------- setup via real API (tenant A admin) ----------
  const admin = await login('admin@bot-a.test'); const adminB = await login('admin@bot-b.test');
  for (const [email, role] of [['wk@bot-a.test', 'Warehousekeeper'], ['tech@bot-a.test', 'Technician'], ['viewer@bot-a.test', 'Viewer'], ['acc@bot-a.test', 'Accountant']])
    await http('POST', '/users', admin, { email, password: PW, first_name: role, last_name: 'Bot', role });
  const proj = (await http('POST', '/projects', admin, { code: 'BOT-P1', name: 'Bot Project 1' })).body; S.project = proj.id;
  const smr = await http('POST', `/projects/${S.project}/smr-groups`, admin, { name: 'Bot SMR 1' }); S.smr = smr.body?.id || 'smr-bot-1'; S.smrReal = !!smr.body?.id;
  const orgA = (await http('GET', '/auth/me', admin)).body; S.orgA = orgA.org_id || orgA.user?.org_id;
  mongo('bot_op', `db.md_item.insertOne({id:'${ITEM}',tenant_id:'${S.orgA}',canonical_unit:'bag',name:'Cement 25kg (synthetic)'});db.md_item.insertOne({id:'${ITEM_K}',tenant_id:'${S.orgA}',canonical_unit:'bag',name:'Keeper item (synthetic)'})`);
  const tk = { wk: await login('wk@bot-a.test'), tech: await login('tech@bot-a.test'), viewer: await login('viewer@bot-a.test'), acc: await login('acc@bot-a.test') };

  const recv = (token, q, id = ITEM) => mv(token, { action: 'receive_from_supplier', item_id: id, unit: 'bag', quantity: String(q), unit_value: '5', source: loc('supplier', 'sup1'), destination: loc('central_warehouse', 'CEN') });
  const disp = (token, q) => mv(token, { action: 'dispatch_warehouse_to_project', item_id: ITEM, unit: 'bag', quantity: String(q), project_id: S.project, source: loc('central_warehouse', 'CEN'), destination: loc('in_transit', 'pending', 'in_transit') });
  const acc = (token, id, q, req) => mv(token, { action: 'accept_project_delivery', item_id: ITEM, unit: 'bag', quantity: String(q), accepted_quantity: String(q), requested_quantity: String(req), dispatch_movement_id: id, project_id: S.project, destination: loc('project', S.project) });
  // append-only: a discrepancy is open iff no discrepancy_resolved row points at it
  const openDisc = (dispatchId) => jq('bot_op', `(()=>{const rows=db.warehouse_transactions.find({dispatch_movement_id:'${dispatchId}'}).toArray();const resolved=new Set(rows.filter(r=>r.action==='discrepancy_resolved').map(r=>r.resolves_discrepancy_movement_id));return rows.filter(r=>r.action==='transit_discrepancy'&&!resolved.has(r.movement_id)).length})()`);
  const inTransit = (dispatchId) => jq('bot_op', `db.warehouse_in_transit.find({}).toArray().filter(x=>JSON.stringify(x).includes('${dispatchId}')).map(x=>({unresolved:Object.keys(x.unresolved_discrepancies||{}).length}))`);

  // ---------- UI helpers ----------
  const field = (page, label) => page.locator('.wh-field', { hasText: label }).first();
  async function cmdUI(page, c) {
    await page.getByRole('button', { name: 'Движения', exact: true }).click();
    await field(page, 'Действие').locator('select').selectOption(c.action);
    await field(page, 'Артикул (item_id)').locator('input').fill(c.item || ITEM);
    await field(page, 'Количество').first().locator('input').fill(String(c.qty));
    const uv = field(page, 'Единична стойност'); if (await uv.count()) await uv.locator('input').fill(c.unitValue || '');
    await field(page, 'Източник').locator('select').selectOption(c.src?.[0] || 'supplier'); await field(page, 'Източник').locator('input').fill(c.src?.[1] || '');
    await field(page, 'Дестинация').locator('select').selectOption(c.dst[0]); await field(page, 'Дестинация').locator('input').fill(c.dst[1]);
    await field(page, 'Проект').locator('input').fill(c.project || '');
    if (c.dispatchId) { await field(page, 'Dispatch movement id').locator('input').fill(c.dispatchId); await field(page, 'Количество прието').locator('input').fill(String(c.accepted)); await field(page, 'Количество заявено').locator('input').fill(String(c.requested)); }
    const [resp] = await Promise.all([page.waitForResponse(r => r.url().includes('/warehouse/canonical/movements') && r.request().method() === 'POST'), page.getByRole('button', { name: 'Запиши движение' }).click()]);
    let j = null; try { j = await resp.json(); } catch {}
    await page.waitForTimeout(400);
    return { status: resp.status(), body: j };
  }
  async function stockUI(page, item) {
    await page.getByRole('button', { name: 'Наличност', exact: true }).click();
    await page.locator('.wh-field', { hasText: 'Артикул' }).first().locator('input').fill(item);
    await page.getByRole('button', { name: 'Прочети наличност' }).click();
    await page.waitForTimeout(900);
    return page.locator('.wh-stock-row').allInnerTexts();
  }
  const noHScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

  // ---------- 0. AS-DEPLOYED BLOCKER CHECK (before any workaround) ----------
  const d0 = await b.context('desktop'); const p0 = d0.page;
  await b.login(p0, 'admin@bot-a.test', PW); await p0.goto(b.UI + '/warehouse/canonical'); await p0.getByRole('button', { name: 'Движения', exact: true }).waitFor();
  let first;
  await b.step('0a AS-DEPLOYED (tenant already has one permission AuditEvent): UI receive 10 -> expected success', async () => {
    first = await cmdUI(p0, { action: 'receive_from_supplier', qty: 10, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
    return { status: first.status, error_code: first.body?.detail?.error_code, ok: first.status === 200 };
  }, p0);
  S.blocker = { status: first.status, code: first.body?.detail?.error_code };
  // Workaround (synthetic local DB only, documented): drop the colliding W0-04 AuditEvent so the canonical chain can start at sequence 1.
  const dropped = mongo('bot_op', `JSON.stringify([db.audit_events.countDocuments({}), db.audit_events.deleteMany({}).deletedCount, db.audit_counters.deleteMany({}).deletedCount])`);
  result_note(b, 'workaround: audit_events/audit_counters of synthetic tenant A cleared (' + dropped + '); every later step is "with workaround"');

  // ---------- RUN 1 @1280: receive 10 -> dispatch 10 -> accept 3+4+3 ----------
  const t1 = await cmdUI(p0, { action: 'receive_from_supplier', qty: 10, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('1.1 [1280 UI] receive 10 to central warehouse -> 200 (first batch of the tenant)', async () => ({ ok: t1.status === 200, status: t1.status, code: t1.body?.detail?.error_code }), p0);
  // F-3 probe (as deployed + workaround 1): ANY second inbound batch in the same tenant
  const t2 = await cmdUI(p0, { action: 'receive_from_supplier', item: ITEM_K, qty: 5, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('1.1b AS-DEPLOYED: [1280 UI] second receive (other item, 5) -> expected 200', async () => ({ ok: t2.status === 200, status: t2.status, error_code: t2.body?.detail?.error_code, message: (t2.body?.detail?.message || '').slice(0, 220) }), p0);
  const dropped2 = mongo('bot_op', `JSON.stringify(db.warehouse_batches.dropIndex('org_id_1_batch_number_1'))`);
  result_note(b, 'workaround 2: legacy unique index warehouse_batches(org_id,batch_number) dropped on the synthetic tenant A DB (' + dropped2 + '); steps below are "with workaround 1+2"');
  const t2b = await cmdUI(p0, { action: 'receive_from_supplier', item: ITEM_K, qty: 5, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('1.1c [1280 UI] after workaround 2: second receive (other item, 5) -> 200', async () => ({ ok: t2b.status === 200, status: t2b.status, error_code: t2b.body?.detail?.error_code }), p0);
  S.rows1 = (await stockUI(p0, ITEM)).join('|');
  await b.step('1.2 [1280 UI] stock panel shows 10 at central_warehouse:CEN', async () => ({ ok: /central_warehouse:CEN[\s\S]*10/.test(S.rows1), rows: S.rows1 }), p0);
  // Dispatch probe on the OTHER item: the form always sends destination state "free"
  const dprobe = await cmdUI(p0, { action: 'dispatch_warehouse_to_project', item: ITEM_K, qty: 1, src: ['central_warehouse', 'CEN'], dst: ['project', S.project], project: S.project });
  const kProj = await http('GET', `/warehouse/canonical/balance/${ITEM_K}`, admin);
  await b.step('1.3p PROBE [1280 UI] dispatch 1 to project with destination project/free: server must keep it in transit (not credit the project before acceptance)', async () => ({ ok: !(dprobe.status === 200 && (kProj.body?.balances || []).some(r => r.location_type === 'project' && r.state === 'free')), dispatch_status: dprobe.status, error_code: dprobe.body?.detail?.error_code, balances: (kProj.body?.balances || []).map(r => `${r.location_type}:${r.state}=${r.quantity}`) }), p0);
  let d1 = await cmdUI(p0, { action: 'dispatch_warehouse_to_project', qty: 10, src: ['central_warehouse', 'CEN'], dst: ['in_transit', 'pending'], project: S.project });
  S.dispatchVia = 'UI (dest=in_transit/pending, state sent as free)';
  if (d1.status !== 200) {
    await b.step(`1.3a [1280 UI] dispatch 10 via destination in_transit/pending -> ${d1.status} ${d1.body?.detail?.error_code} (UI cannot send state=in_transit)`, async () => false, p0);
    d1 = await disp(admin, 10); S.dispatchVia = 'API fallback (state=in_transit; the form cannot express it)';
  }
  S.disp1 = d1.body?.movement_id;
  await b.step(`1.3 dispatch 10 to project -> 200 [via ${S.dispatchVia}]`, async () => d1.status === 200, p0);
  const accs = [];
  for (const q of [3, 4, 3]) {
    const r = await cmdUI(p0, { action: 'accept_project_delivery', qty: q, dst: ['project', S.project], project: S.project, dispatchId: S.disp1, accepted: q, requested: 10, src: ['supplier', ''] });
    accs.push({ q, status: r.status, code: r.body?.detail?.error_code, open: await openDisc(S.disp1) });
  }
  await b.step('1.4 [1280 UI] accept 3 + 4 + 3 all -> 200', async () => ({ ok: (accs.every(a => a.status === 200)), accs, ok: accs.every(a => a.status === 200) }), p0);
  await b.step('1.5 unresolved discrepancies after 3+4+3 == 0 (ledger query; requires all three accepts to have succeeded)', async () => ({ ok: (accs.every(a => a.status === 200) && accs[2].open === 0), open_after_each: accs.map(a => a.open), in_transit: await inTransit(S.disp1) }), p0);
  S.rows1b = await stockUI(p0, ITEM);
  await b.step('1.6 [1280 UI] stock: project holds 10, central 0', async () => ({ ok: (/project:/.test(S.rows1b.join('|')) && /10/.test(S.rows1b.join('|'))), rows: S.rows1b }), p0);
  await b.step('1.7 [1280 UI] integrity-warnings panel: API must answer 200; the panel must not show a false all-clear on error', async () => {
    await p0.getByRole('button', { name: 'Аларми', exact: true }).click(); await p0.waitForTimeout(1500);
    const api = await http('GET', '/warehouse/canonical/integrity-warnings', admin); const panel = (await p0.locator('.wh-panel').first().innerText()).replace(/\s+/g, ' ');
    return { ok: api.status === 200, api_status: api.status, api_error_type: api.body?.error_type, panel_text: panel };
  }, p0);
  await b.step('1.8 [1280] no horizontal scroll', async () => noHScroll(p0), p0);
  await d0.ctx.close();

  // ---------- RUN 2 @390x844: receive 10, dispatch 10, accept 8+2, consume 3 ----------
  const m = await b.context('phone'); const pm = m.page;
  await b.login(pm, 'admin@bot-a.test', PW); await pm.goto(b.UI + '/warehouse/canonical'); await pm.getByRole('button', { name: 'Движения', exact: true }).waitFor();
  const r2 = await cmdUI(pm, { action: 'receive_from_supplier', qty: 10, unitValue: '5', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  await b.step('2.1 [390 UI] receive 10 -> 200', async () => r2.status === 200, pm);
  let d2 = await cmdUI(pm, { action: 'dispatch_warehouse_to_project', qty: 10, src: ['central_warehouse', 'CEN'], dst: [S.dispatchVia.includes('in_transit') ? 'in_transit' : 'project', S.dispatchVia.includes('in_transit') ? 'pending' : S.project], project: S.project });
  if (d2.status !== 200) d2 = await disp(admin, 10);
  S.disp2 = d2.body?.movement_id;
  await b.step(`2.2 dispatch 10 -> 200 [${d2.status === 200 && S.dispatchVia.startsWith('UI') ? 'UI 390' : 'API'}]`, async () => d2.status === 200, pm);
  const a8 = await cmdUI(pm, { action: 'accept_project_delivery', qty: 8, dst: ['project', S.project], project: S.project, dispatchId: S.disp2, accepted: 8, requested: 10, src: ['supplier', ''] });
  const open8 = await openDisc(S.disp2);
  await b.step('2.3 [390 UI] accept 8 -> 200 and exactly 1 open discrepancy (2 missing)', async () => ({ ok: (a8.status === 200 && open8 === 1), status: a8.status, open: open8 }), pm);
  const a2 = await cmdUI(pm, { action: 'accept_project_delivery', qty: 2, dst: ['project', S.project], project: S.project, dispatchId: S.disp2, accepted: 2, requested: 10, src: ['supplier', ''] });
  const open2 = await openDisc(S.disp2);
  await b.step('2.4 [390 UI] accept 2 -> 200 and zero unresolved discrepancies', async () => ({ ok: (a2.status === 200 && open2 === 0), status: a2.status, open: open2 }), pm);
  S.rows2 = await stockUI(pm, ITEM);
  await b.step('2.5 [390 UI] stock panel readable on phone (project bucket)', async () => ({ ok: (S.rows2.length > 0), rows: S.rows2 }), pm);
  await b.step('2.6 [390] no horizontal scroll', async () => noHScroll(pm), pm);
  // consume 3 to SMR: the form has no SMR field -> API for the SMR-bound write
  const c1Key = key('consume');
  const cons = { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '3', project_id: S.project, smr_id: S.smr, source: loc('project', S.project), idempotency_key: c1Key, currency: 'BGN' };
  const c1 = await http('POST', '/warehouse/canonical/movements', admin, cons);
  const c1r = await http('POST', '/warehouse/canonical/movements', admin, cons); // exact replay
  const costRows = () => jq('bot_op', `db.material_entries.find({movement_id:'${c1.body?.movement_id}'},{_id:0,movement_id:1,smr_id:1,quantity:1,total_value:1,project_id:1}).toArray()`);
  b.noScreen('2.7a consume 3 bound to an SMR: the canonical form has no SMR field (smr_id)', 'UI form can only post project-level consume; SMR binding done by API', { status: c1.status });
  await b.step('2.7 [API] consume 3 to SMR -> 200', async () => ({ ok: c1.status === 200, status: c1.status, code: c1.body?.detail?.error_code }));
  const rows = await costRows(); const allRows = jq('bot_op', `db.material_entries.countDocuments({smr_id:'${S.smr}'})`);
  await b.step('2.8 exactly one project cost row (material_entries) for the consume, also after an identical resend', async () => ({ ok: rows.length === 1 && allRows === 1, rows_for_movement: rows, rows_for_smr: allRows }));
  await b.step('2.8b identical resend of the consume (same idempotency key + body) returns the original movement (replay:true, 200)', async () => ({ ok: c1r.status === 200 && c1r.body?.replay === true && c1r.body?.movement_id === c1.body?.movement_id, status: c1r.status, error_code: c1r.body?.detail?.error_code, message: c1r.body?.detail?.message }));
  await m.page.goto(b.UI + '/projects/' + S.project); await m.page.waitForTimeout(2500);
  await b.step('2.9 [390] project page material ledger screen (cost/remaining)', async () => m.page.locator('[data-testid="material-ledger"]').count().then(n => ({ ledger_visible: n > 0 })), m.page);
  await m.ctx.close();
  const dsk = await b.context('desktop'); await dsk.page.setViewportSize({ width: 1280, height: 800 }); await b.login(dsk.page, 'admin@bot-a.test', PW);
  await dsk.page.goto(b.UI + '/projects/' + S.project); await dsk.page.waitForTimeout(2500);
  await b.step('2.10 [1280] project page material ledger screen', async () => dsk.page.locator('[data-testid="material-ledger"]').count().then(n => ({ ledger_visible: n > 0 })), dsk.page);
  await dsk.ctx.close();

  // ---------- PERMISSIONS ----------
  const P = {};
  P.keeperReceive = await recv(tk.wk, 1, ITEM_K);
  P.keeperConsume = await mv(tk.wk, { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project) });
  P.keeperRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.wk);
  P.techRecv = await recv(tk.tech, 1, ITEM_K); P.techConsume = await mv(tk.tech, { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project) }); P.techRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.tech);
  P.viewRecv = await recv(tk.viewer, 1, ITEM_K); P.viewConsume = await mv(tk.viewer, { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project) }); P.viewRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.viewer);
  P.accRecv = await recv(tk.acc, 1, ITEM_K); P.accRead = await http('GET', `/warehouse/canonical/balance/${ITEM}`, tk.acc);
  const st = (r) => r.status;
  await b.step('3.1 keeper (Warehousekeeper): receive 200, consume_to_smr 403, read 200', async () => ({ ok: (st(P.keeperReceive) === 200 && st(P.keeperConsume) === 403 && st(P.keeperRead) === 200), receive: st(P.keeperReceive), consume: st(P.keeperConsume), read: st(P.keeperRead) }));
  await b.step('3.2 technician: receive 403, consume 403, read 403 (direct API)', async () => ({ ok: ([P.techRecv, P.techConsume, P.techRead].every(r => r.status === 403)), receive: st(P.techRecv), consume: st(P.techConsume), read: st(P.techRead) }));
  await b.step('3.3 viewer: receive 403, consume 403, read 403 (direct API)', async () => ({ ok: ([P.viewRecv, P.viewConsume, P.viewRead].every(r => r.status === 403)), receive: st(P.viewRecv), consume: st(P.viewConsume), read: st(P.viewRead) }));
  await b.step('3.4 accountant (read-only role): receive 403, read 200 (direct API)', async () => ({ ok: (st(P.accRecv) === 403 && st(P.accRead) === 200), receive: st(P.accRecv), read: st(P.accRead) }));
  // UI: what each role sees
  const seen = {};
  for (const [vpName, tag] of [['desktop', '1280'], ['phone', '390']]) {
    for (const [email, label] of [['wk@bot-a.test', 'keeper'], ['tech@bot-a.test', 'technician'], ['viewer@bot-a.test', 'viewer'], ['acc@bot-a.test', 'accountant']]) {
      const c = await b.context(vpName); await b.login(c.page, email, PW); await c.page.waitForLoadState('networkidle');
      await c.page.goto(b.UI + '/warehouse/canonical'); await c.page.waitForTimeout(1500);
      const url = c.page.url().replace(b.UI, ''); const writeForm = await c.page.getByRole('button', { name: 'Движения', exact: true }).count();
      seen[`${label}@${tag}`] = { url, canonical_page: writeForm > 0 };
      const denied = label === 'accountant' ? false : true; // accountant has no write grant
      await b.step(`3.5 [${tag}] ${label} opens /warehouse/canonical -> must show NO write action (landed ${url}, write tab ${writeForm > 0 ? 'VISIBLE' : 'hidden'})`, async () => writeForm === 0, c.page);
      await c.ctx.close();
    }
  }
  b.noScreen('3.6 keeper (allowed receive/dispatch/accept on API) has no warehouse screen: /warehouse/canonical is AdminRoute (Admin/Owner/SiteManager/Accountant only) and redirects to /tech', 'role has API rights but no UI', { landed: seen['keeper@1280']?.url });
  b.result.ui_visibility = seen;

  // ---------- TENANT ISOLATION ----------
  const bBal = await http('GET', `/warehouse/canonical/balance/${ITEM}`, adminB); const bHist = await http('GET', '/warehouse/canonical/history', adminB);
  const bStock = await http('GET', `/warehouse/canonical/stock/${ITEM}?location_type=central_warehouse&location_id=CEN&state=free`, adminB);
  const bAcc = await mv(adminB, { action: 'accept_project_delivery', item_id: ITEM, unit: 'bag', quantity: '1', accepted_quantity: '1', requested_quantity: '1', dispatch_movement_id: S.disp1, project_id: 'x', destination: loc('project', 'x') });
  await b.step('4.1 tenant B: balance of A item empty; history empty; stock zero', async () => ({ ok: ((bBal.body?.balances || []).length === 0 && (bHist.body?.rows || []).length === 0), bal: bBal.body?.balances, hist_rows: (bHist.body?.rows || []).length, stock: bStock.status }));
  await b.step('4.2 tenant B cannot accept tenant A dispatch (write refused)', async () => ({ ok: (bAcc.status >= 400), status: bAcc.status, code: bAcc.body?.detail?.error_code }));
  for (const [vpName, tag] of [['desktop', '1280'], ['phone', '390']]) {
    const c = await b.context(vpName); await b.login(c.page, 'admin@bot-b.test', PW); await c.page.goto(b.UI + '/warehouse/canonical'); await c.page.getByRole('button', { name: 'Наличност', exact: true }).waitFor();
    const rowsB = await stockUI(c.page, ITEM);
    await b.step(`4.3 [${tag} UI] tenant B stock panel for A's item shows empty`, async () => ({ ok: rowsB.length === 0, rows: rowsB }), c.page); await c.ctx.close();
  }
  const aBal = await http('GET', `/warehouse/canonical/balance/${ITEM}`, admin);
  await b.step('4.4 control: tenant A still sees its own stock', async () => ({ ok: ((aBal.body?.balances || []).length > 0), balances: aBal.body?.balances }));
  b.result.facts = S; b.result.permission_http = Object.fromEntries(Object.entries(P).map(([k, v]) => [k, v.status + (v.body?.detail?.error_code ? ' ' + v.body.detail.error_code : (v.body?.detail?.reason ? ' ' + v.body.detail.reason : ''))]));
}, { outDir: process.env.BOT_OUT, sha: process.env.BOT_SHA });
function result_note(b, t) { (b.result.notes ||= []).push(t); console.log('NOTE', t); }

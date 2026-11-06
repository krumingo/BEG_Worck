// BOT 5C re-run — PR #55 @ d8ac3a9. Synthetic data, enforce mode, NO local workarounds.
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

bot.run('5C-d8ac3a9', async (b) => {
  const S = {}, P = {};
  // ---------- setup via real API ----------
  const admin = await login('admin@bot-a.test'); const adminB = await login('admin@bot-b.test');
  for (const [email, role] of [['wk@bot-a.test', 'Warehousekeeper'], ['tech@bot-a.test', 'Technician'], ['viewer@bot-a.test', 'Viewer'], ['acc@bot-a.test', 'Accountant']])
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
    await page.getByTestId('wh-tab-commands').click();
    await page.getByTestId('wh-action-select').selectOption(c.action);
    await field(page, 'Артикул (item_id)').locator('input').fill(c.item || ITEM);
    await field(page, 'Количество').first().locator('input').fill(String(c.qty));
    const uv = field(page, 'Единична стойност'); if (await uv.count()) await uv.locator('input').fill(c.unitValue || '');
    await field(page, 'Източник').locator('select').selectOption(c.src?.[0] || 'supplier'); await field(page, 'Източник').locator('input').fill(c.src?.[1] || '');
    if (c.action !== 'dispatch_warehouse_to_project') { await field(page, 'Дестинация').locator('select').selectOption(c.dst?.[0] || 'central_warehouse'); await field(page, 'Дестинация').locator('input').fill(c.dst?.[1] || ''); }
    await page.locator('.wh-field', { hasText: 'Проект' }).first().locator('input').fill(c.project || '');
    if (c.smr) await page.getByTestId('wh-smr-id').fill(c.smr);
    if (c.dispatchId) { await field(page, 'Dispatch movement id').locator('input').fill(c.dispatchId); await field(page, 'Количество прието').locator('input').fill(String(c.accepted)); await field(page, 'Количество заявено').locator('input').fill(String(c.requested)); }
    const [resp] = await Promise.all([page.waitForResponse(r => r.url().includes('/warehouse/canonical/movements') && r.request().method() === 'POST'), page.getByRole('button', { name: 'Запиши движение' }).click()]);
    let j = null; try { j = await resp.json(); } catch {}
    await page.waitForTimeout(400);
    return { status: resp.status(), body: j };
  }
  async function stockUI(page, item) {
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
  await b.step('1.3q [1280 UI] dispatch form has a FIXED in-transit destination (no destination picker)', async () => ({ ok: await p0.getByTestId('wh-dispatch-in-transit').isVisible() && (await field(p0, 'Дестинация').locator('select').count()) === 0 }), p0);
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
  const rows = jq('bot_op', `db.material_entries.find({movement_id:'${mid}'},{_id:0,movement_id:1,smr_id:1,quantity:1,total_value:1,cost_recognized:1}).toArray()`);
  const smrRows = jq('bot_op', `db.material_entries.countDocuments({smr_id:'${S.smr}',cost_recognized:true})`);
  // identical resend (same key + body) through the API
  const cbody = { action: 'consume_to_smr', item_id: ITEM, unit: 'bag', quantity: '1', project_id: S.project, smr_id: S.smr, source: loc('project', S.project), idempotency_key: key('resend'), currency: 'BGN' };
  const c2a = await http('POST', '/warehouse/canonical/movements', admin, cbody); const c2b = await http('POST', '/warehouse/canonical/movements', admin, cbody);
  const rowsAfter = jq('bot_op', `db.material_entries.countDocuments({movement_id:'${c2a.body?.movement_id}'})`);
  await b.step('2.7 exactly one project cost row for the UI consume (material_entries, by movement and by SMR)', async () => ({ ok: rows.length === 1 && smrRows === 1, rows_for_movement: rows, cost_rows_for_smr: smrRows }));
  await b.step('2.8 identical consume resend returns the ORIGINAL result (200, replay:true, same movement_id) and adds no row (F-5)', async () => ({ ok: c2a.status === 200 && c2b.status === 200 && c2b.body?.replay === true && c2b.body?.movement_id === c2a.body?.movement_id && rowsAfter === 1, first: c2a.status, resend: c2b.status, replay: c2b.body?.replay, same_id: c2b.body?.movement_id === c2a.body?.movement_id, error_code: code(c2b), rows_for_movement: rowsAfter }));
  await b.step('2.9 [390] no horizontal scroll (form with SMR field)', async () => noHScroll(pm), pm);
  await pm.goto(b.UI + '/projects/' + S.project); await pm.waitForTimeout(2500);
  await b.step('2.10 [390] project page material ledger visible', async () => ({ ok: (await pm.locator('[data-testid="material-ledger"]').count()) > 0 }), pm);
  await m.ctx.close();

  // ---------- COST CHECK: receive 10 @10, dispatch 5, accept 5, consume 3 => project material cost exactly 30 ----------
  const dc = await b.context('desktop'); const pc = dc.page; await b.login(pc, 'admin@bot-a.test', PW); await openCanonical(pc);
  const c_r = await cmdUI(pc, { action: 'receive_from_supplier', item: ITEM_C, qty: 10, unitValue: '10', src: ['supplier', 'sup1'], dst: ['central_warehouse', 'CEN'] });
  const c_d = await cmdUI(pc, { action: 'dispatch_warehouse_to_project', item: ITEM_C, qty: 5, src: ['central_warehouse', 'CEN'], project: S.project2 });
  const c_a = await cmdUI(pc, { action: 'accept_project_delivery', item: ITEM_C, qty: 5, dst: ['project', S.project2], project: S.project2, dispatchId: c_d.body?.movement_id, accepted: 5, requested: 5, src: ['supplier', ''] });
  const c_c = await cmdUI(pc, { action: 'consume_to_smr', item: ITEM_C, qty: 3, src: ['project', S.project2], dst: ['central_warehouse', ''], project: S.project2, smr: S.smr2 });
  await b.step('C.1 [1280 UI] receive 10 @10, dispatch 5, accept 5, consume 3 (with SMR) all -> 200', async () => ({ ok: [c_r, c_d, c_a, c_c].every(r => r.status === 200), statuses: [c_r, c_d, c_a, c_c].map(r => r.status), codes: [c_r, c_d, c_a, c_c].map(code) }), pc);
  // numeric collector: material-cost-like fields in each report
  const costKey = /material/i, costWord = /(cost|actual|spent|total|net)/i, notCost = /(budget|planned|baseline|variance|pct|percent|margin|ratio|count|qty|quantity|warning|unmapped_count|issued|returned|consumed_qty)/i;
  const collect = (o, path = '', out = []) => { if (/budget/i.test(path)) return out; if (Array.isArray(o)) o.forEach((x, i) => collect(x, `${path}[${i}]`, out)); else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { const p = path ? path + '.' + k : k; if (typeof v === 'number' && costKey.test(k) && costWord.test(k) && !notCost.test(k)) out.push([p, v]); else if (typeof v === 'number' && /^(mat_cost|material)$/i.test(k)) out.push([p, v]); else collect(v, p, out); } return out; };
  const reports = async (label) => {
    const eps = { 'material-entries': `/material-entries?project_id=${S.project2}`, 'material-cost/by-execution-package': `/material-cost/by-execution-package/${S.pkg}`, 'execution-package financial': `/execution-packages/${S.pkg}/financial`, 'financial-breakdown': `/execution-packages/financial-breakdown/${S.project2}`, 'net-financial': `/execution-packages/${S.pkg}/net-financial`, 'project-net-profit': `/project-net-profit/${S.project2}`, 'project-profit': `/project-profit/${S.project2}`, 'pnl': `/projects/${S.project2}/pnl`, 'pnl/summary': `/projects/${S.project2}/pnl/summary`, 'pnl/breakdown': `/projects/${S.project2}/pnl/breakdown` };
    const res = {};
    for (const [name, path] of Object.entries(eps)) { const r = await http('GET', path, admin); let f = r.status === 200 && name !== 'material-entries' ? collect(r.body) : []; if (name === 'pnl/summary' && r.status === 200) f = [['total_expense (only cost in a fresh project = the 30 of material)', r.body?.total_expense]]; res[name] = { status: r.status, fields: f }; if (name === 'material-entries' && r.status === 200) { const arr = Array.isArray(r.body) ? r.body : (r.body?.entries || r.body?.items || []); res[name].entries = arr.map(e => ({ kind: e.movement_kind, total_value: e.total_value, qty: e.quantity })); res[name].fields = [['sum(total_value)', arr.reduce((s, e) => s + Number(e.total_value || 0), 0)]]; } }
    for (const [name, v] of Object.entries(res)) await b.step(`C.${label} report "${name}": HTTP 200 and every material-cost field == 30 (found ${v.fields.length})`, async () => ({ ok: v.status === 200 && v.fields.length > 0 && v.fields.every(([, x]) => Math.abs(x - 30) < 0.005), status: v.status, fields: v.fields, entries: v.entries }));
    return res;
  };
  S.reportsA = await reports('2a (as projected at consume)');
  const sync = await http('POST', `/material-entries/sync/${S.project2}`, admin);
  await b.step('C.3 rebuild of material_entries from the ledger (sync) succeeds', async () => ({ ok: sync.status === 200, status: sync.status, body: sync.body }));
  S.reportsB = await reports('3b (after ledger rebuild + package mapping)');
  const rec = await http('POST', `/execution-packages/recompute-material/${S.project2}`, admin);
  await b.step('C.3c manual recompute of package material (API; no UI/automatic caller exists) succeeds', async () => ({ ok: rec.status === 200, status: rec.status, body: rec.body }));
  S.reportsC = await reports('3d (after manual recompute-material)');
  // screens
  const costText = async (page, label) => { await page.waitForTimeout(2500); const txt = (await page.locator('main').first().innerText()).replace(/\s+/g, ' '); return txt; };
  const has30 = (t) => /(^|[^\d.,])30([.,]00)?(?![\d])/.test(t); const has50 = (t) => /(^|[^\d.,])(50|100)([.,]00)(?![\d])/.test(t);
  for (const [vp, tag, pg] of [['desktop', '1280', pc]]) {
    await pg.goto(b.UI + `/projects/${S.project2}/financial`); const t = await costText(pg);
    await b.step(`C.4 [${tag}] project financial screen shows material cost 30 and not 50/100 (accept/receive value)`, async () => ({ ok: has30(t) && !has50(t), has30: has30(t), has50_or_100: has50(t), excerpt: (t.match(/.{0,60}30([.,]00)?.{0,40}/) || [''])[0] }), pg);
    await pg.goto(b.UI + `/projects/${S.project2}`); const t2 = await costText(pg);
    await b.step(`C.5 [${tag}] project page (finance card / P&L / material ledger) shows 30 and not 50/100`, async () => ({ ok: has30(t2) && !has50(t2), has30: has30(t2), has50_or_100: has50(t2) }), pg);
  }
  await dc.ctx.close();
  const mc = await b.context('phone'); await b.login(mc.page, 'admin@bot-a.test', PW);
  await mc.page.goto(b.UI + `/projects/${S.project2}/financial`); const tm = await costText(mc.page);
  await b.step('C.4 [390] project financial screen shows material cost 30, not 50/100, no horizontal scroll', async () => ({ ok: has30(tm) && !has50(tm) && await noHScroll(mc.page), has30: has30(tm), has50_or_100: has50(tm), no_hscroll: await noHScroll(mc.page) }), mc.page);
  await mc.ctx.close();

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

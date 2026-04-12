/**
 * PayRunPrintView — Print-ready views for pay run: group list + individual sheets.
 * Opens in a new window with print-optimized CSS.
 */

export function openGroupPrint(run, employees, allocData) {
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) return;
  const rows = employees || run?.employee_rows || [];
  const weekNum = run?.week_number || "";
  const period = `${run?.period_start || ""} — ${run?.period_end || ""}`;
  const totalNet = rows.reduce((s, r) => s + (r.paid_now_amount || 0), 0);
  const totalEarned = rows.reduce((s, r) => s + (r.earned_amount || 0), 0);
  const totalRemain = rows.reduce((s, r) => s + (r.remaining_after_payment || 0), 0);

  w.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Групов лист ${run?.number || ""}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; color: #222; padding: 15mm; }
  h1 { font-size: 16px; margin-bottom: 4px; }
  .meta { font-size: 10px; color: #666; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; font-size: 10px; }
  th { background: #f5f5f5; font-weight: 600; text-transform: uppercase; font-size: 9px; }
  .r { text-align: right; }
  .c { text-align: center; }
  .b { font-weight: 700; }
  .green { color: #16a34a; }
  .amber { color: #d97706; }
  .red { color: #dc2626; }
  .totals td { border-top: 2px solid #333; font-weight: 700; background: #fafafa; }
  .sig { width: 100px; }
  .footer { margin-top: 15px; font-size: 9px; color: #999; }
  @media print { body { padding: 10mm; } }
</style></head><body>
<h1>ГРУПОВ ЛИСТ ЗА ПЛАЩАНЕ — ${run?.number || ""}</h1>
<div class="meta">Седмица №${weekNum} | Период: ${period} | Дата: ${new Date().toISOString().slice(0, 10)}</div>
<table>
<thead><tr>
  <th class="c">№</th>
  <th>Име</th>
  <th>Длъжност</th>
  <th class="r">Брутно</th>
  <th class="r">Корекции</th>
  <th class="r">Нетно</th>
  <th class="r b">Реално платено</th>
  <th class="r">Остатък</th>
  <th class="sig">Подпис</th>
</tr></thead>
<tbody>
${rows.map((r, i) => {
  const adj = (r.bonuses_amount || 0) - (r.deductions_amount || 0);
  const net = r.earned_amount + adj;
  return `<tr>
    <td class="c">${i + 1}</td>
    <td class="b">${r.first_name || ""} ${r.last_name || ""}</td>
    <td>${r.position || "—"}</td>
    <td class="r">${(r.earned_amount || 0).toFixed(2)}</td>
    <td class="r ${adj >= 0 ? "green" : "red"}">${adj !== 0 ? adj.toFixed(2) : "—"}</td>
    <td class="r">${net.toFixed(2)}</td>
    <td class="r b green">${(r.paid_now_amount || 0).toFixed(2)}</td>
    <td class="r ${(r.remaining_after_payment || 0) > 0 ? "amber" : ""}">${(r.remaining_after_payment || 0).toFixed(2)}</td>
    <td class="sig"></td>
  </tr>`;
}).join("")}
<tr class="totals">
  <td></td><td class="b">ОБЩО</td><td></td>
  <td class="r">${totalEarned.toFixed(2)}</td>
  <td></td>
  <td class="r">${totalNet.toFixed(2)}</td>
  <td class="r b green">${rows.reduce((s, r) => s + (r.paid_now_amount || 0), 0).toFixed(2)}</td>
  <td class="r">${totalRemain.toFixed(2)}</td>
  <td></td>
</tr>
</tbody></table>
<div class="footer">
  Избрани: ${rows.length} | Общо платено: ${rows.reduce((s, r) => s + (r.paid_now_amount || 0), 0).toFixed(2)} EUR | Остатък: ${totalRemain.toFixed(2)} EUR
  <br>Изготвил: _______________ Дата: ${new Date().toISOString().slice(0, 10)}
</div>
</body></html>`);
  w.document.close();
  setTimeout(() => w.print(), 300);
}

export function openIndividualPrint(run, empRow, allocEmp) {
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) return;
  const weekNum = run?.week_number || "";
  const period = `${run?.period_start || ""} — ${run?.period_end || ""}`;
  const days = allocEmp?.day_allocations || empRow?.day_cells || [];
  const adjs = empRow?.adjustments || [];
  const BG_D = ["Нд", "Пон", "Вт", "Ср", "Чет", "Пет", "Съб"];

  w.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Фиш ${empRow?.first_name} ${empRow?.last_name}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; color: #222; padding: 15mm; }
  h1 { font-size: 14px; margin-bottom: 2px; }
  h2 { font-size: 12px; margin-bottom: 8px; color: #555; }
  .meta { font-size: 10px; color: #666; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; font-size: 10px; }
  th { background: #f5f5f5; font-weight: 600; text-transform: uppercase; font-size: 9px; }
  .r { text-align: right; }
  .c { text-align: center; }
  .b { font-weight: 700; }
  .green { color: #16a34a; }
  .amber { color: #d97706; }
  .totals td { border-top: 2px solid #333; font-weight: 700; }
  .calc { background: #f9fafb; padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 10px; }
  .calc div { display: flex; justify-content: space-between; padding: 2px 0; }
  .sig-row { display: flex; justify-content: space-between; margin-top: 20px; }
  .sig-box { text-align: center; }
  .sig-line { width: 120px; border-top: 1px solid #333; margin-top: 30px; display: inline-block; }
  @media print { body { padding: 10mm; } }
</style></head><body>
<h1>СЕДМИЧЕН ФИШ — ${empRow?.first_name || ""} ${empRow?.last_name || ""}</h1>
<h2>${empRow?.position || "—"} | ${empRow?.pay_type || ""}</h2>
<div class="meta">${run?.number || ""} | Седмица №${weekNum} | ${period}</div>

<table>
<thead><tr>
  <th>Ден</th><th>Дата</th><th class="r">Часове</th><th>Обект</th><th class="r">Сума</th>
</tr></thead>
<tbody>
${days.map(d => {
  const dt = new Date(d.date + "T12:00:00");
  const siteName = d.sites ? (d.sites.map ? d.sites.map(s => typeof s === "string" ? s : s.site_name).join(", ") : "") : "";
  return `<tr>
    <td>${BG_D[dt.getDay()]}</td>
    <td>${d.date}</td>
    <td class="r">${d.hours || 0}</td>
    <td>${siteName}</td>
    <td class="r">${(d.source_value || d.value || 0).toFixed(2)}</td>
  </tr>`;
}).join("")}
<tr class="totals">
  <td colspan="2" class="b">ОБЩО</td>
  <td class="r b">${days.reduce((s, d) => s + (d.hours || 0), 0).toFixed(1)}</td>
  <td></td>
  <td class="r b">${(empRow?.earned_amount || 0).toFixed(2)}</td>
</tr>
</tbody></table>

${adjs.length > 0 ? `<table>
<thead><tr><th>Корекция</th><th>Заглавие</th><th class="r">Сума</th></tr></thead>
<tbody>${adjs.map(a => `<tr>
  <td>${a.type === "bonus" ? "Бонус" : a.type === "advance" ? "Аванс" : a.type === "loan_repayment" ? "Заем" : a.type === "deduction" ? "Удръжка" : a.type}</td>
  <td>${a.title || ""} ${a.note ? `(${a.note})` : ""}</td>
  <td class="r ${a.type === "bonus" ? "green" : "red"}">${a.type === "bonus" ? "+" : "-"}${a.amount.toFixed(2)}</td>
</tr>`).join("")}</tbody></table>` : ""}

<div class="calc">
  <div><span>Изработено</span><span class="b">${(empRow?.earned_amount || 0).toFixed(2)} EUR</span></div>
  ${(empRow?.bonuses_amount || 0) > 0 ? `<div><span class="green">+ Бонуси</span><span class="green">+${empRow.bonuses_amount.toFixed(2)}</span></div>` : ""}
  ${(empRow?.deductions_amount || 0) > 0 ? `<div><span class="red">- Удръжки</span><span class="red">-${empRow.deductions_amount.toFixed(2)}</span></div>` : ""}
  ${(empRow?.previously_paid || 0) > 0 ? `<div><span>- Вече платено</span><span>-${empRow.previously_paid.toFixed(2)}</span></div>` : ""}
  <div style="border-top:1px solid #333;padding-top:4px;margin-top:4px"><span class="b">РЕАЛНО ПЛАТЕНО</span><span class="b green" style="font-size:13px">${(empRow?.paid_now_amount || 0).toFixed(2)} EUR</span></div>
  <div><span>Остатък</span><span class="${(empRow?.remaining_after_payment || 0) > 0 ? "amber" : ""} b">${(empRow?.remaining_after_payment || 0).toFixed(2)} EUR</span></div>
</div>

<div class="sig-row">
  <div class="sig-box">Работодател<br><span class="sig-line"></span></div>
  <div class="sig-box">Служител<br><span class="sig-line"></span></div>
</div>
</body></html>`);
  w.document.close();
  setTimeout(() => w.print(), 300);
}

export function openSelectedPrint(run, selectedRows, allocData) {
  const empMap = {};
  (allocData?.employees || []).forEach(e => { empMap[e.employee_id] = e; });
  // Print each selected as separate page
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) return;
  const BG_D = ["Нд", "Пон", "Вт", "Ср", "Чет", "Пет", "Съб"];
  const weekNum = run?.week_number || "";
  const period = `${run?.period_start || ""} — ${run?.period_end || ""}`;

  let html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Фишове избрани</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; color: #222; }
  .page { padding: 15mm; page-break-after: always; }
  .page:last-child { page-break-after: auto; }
  h1 { font-size: 14px; margin-bottom: 2px; }
  .meta { font-size: 10px; color: #666; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; font-size: 10px; }
  th { background: #f5f5f5; font-weight: 600; font-size: 9px; }
  .r { text-align: right; } .b { font-weight: 700; }
  .green { color: #16a34a; } .amber { color: #d97706; } .red { color: #dc2626; }
  .totals td { border-top: 2px solid #333; font-weight: 700; }
  .calc { background: #f9fafb; padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 10px; }
  .calc div { display: flex; justify-content: space-between; padding: 2px 0; }
  .sig-row { display: flex; justify-content: space-between; margin-top: 20px; }
  .sig-line { width: 120px; border-top: 1px solid #333; margin-top: 30px; display: inline-block; }
  @media print { .page { padding: 10mm; } }
</style></head><body>`;

  for (const empRow of selectedRows) {
    const alloc = empMap[empRow.employee_id];
    const days = alloc?.day_allocations || empRow?.day_cells || [];
    const adjs = empRow?.adjustments || [];

    html += `<div class="page">
<h1>${empRow.first_name} ${empRow.last_name} — ${empRow.position || ""}</h1>
<div class="meta">${run?.number || ""} | Сед. №${weekNum} | ${period}</div>
<table><thead><tr><th>Ден</th><th>Дата</th><th class="r">Часове</th><th>Обект</th><th class="r">Сума</th></tr></thead><tbody>
${days.map(d => {
  const dt = new Date(d.date + "T12:00:00");
  const sn = d.sites ? (Array.isArray(d.sites) ? d.sites.map(s => typeof s === "string" ? s : s.site_name).join(", ") : "") : "";
  return `<tr><td>${BG_D[dt.getDay()]}</td><td>${d.date}</td><td class="r">${d.hours || 0}</td><td>${sn}</td><td class="r">${(d.source_value || d.value || 0).toFixed(2)}</td></tr>`;
}).join("")}
<tr class="totals"><td colspan="2" class="b">ОБЩО</td><td class="r b">${days.reduce((s,d)=>s+(d.hours||0),0).toFixed(1)}</td><td></td><td class="r b">${(empRow.earned_amount||0).toFixed(2)}</td></tr>
</tbody></table>
<div class="calc">
<div><span>Изработено</span><span class="b">${(empRow.earned_amount||0).toFixed(2)} EUR</span></div>
${(empRow.bonuses_amount||0)>0?`<div><span class="green">+ Бонуси</span><span class="green">+${empRow.bonuses_amount.toFixed(2)}</span></div>`:""}
${(empRow.deductions_amount||0)>0?`<div><span class="red">- Удръжки</span><span class="red">-${empRow.deductions_amount.toFixed(2)}</span></div>`:""}
<div style="border-top:1px solid #333;padding-top:4px;margin-top:4px"><span class="b">ПЛАТЕНО</span><span class="b green" style="font-size:13px">${(empRow.paid_now_amount||0).toFixed(2)} EUR</span></div>
<div><span>Остатък</span><span class="${(empRow.remaining_after_payment||0)>0?"amber":""} b">${(empRow.remaining_after_payment||0).toFixed(2)} EUR</span></div>
</div>
<div class="sig-row"><div>Работодател<br><span class="sig-line"></span></div><div>Служител<br><span class="sig-line"></span></div></div>
</div>`;
  }

  html += `</body></html>`;
  w.document.write(html);
  w.document.close();
  setTimeout(() => w.print(), 300);
}

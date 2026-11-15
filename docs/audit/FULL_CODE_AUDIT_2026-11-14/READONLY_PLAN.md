# План за проверка на реалните данни само за четене — НЕ Е ИЗПЪЛНЕН

Състояние: **чака отделно одобрение от Крум.** Нищо от този файл не е пускано. Оркестраторът няма и не иска достъп до production.

## Правила
1. Заявките се изпълняват от **един оператор** (човек), с Mongo потребител само с роля `read`, по възможност върху **възстановен snapshot или read replica**, не върху primary.
2. Всяка заявка връща **само бройки и суми**. Няма имена, ЕГН, IBAN, номера на документи, текстове или отделни редове.
3. Всяка заявка има `maxTimeMS`. Ако изтече, се спира и не се повтаря без нов разговор.
4. Към AI се подава само изходната таблица с бройките. Сурови записи не се копират.
5. Положителен резултат **не разрешава** backfill, поправка или изтриване. Той само казва колко голям е проблемът.
6. Базата е една на фирма (database-per-tenant). Заявките се пускат в базата на една фирма; името на базата не се записва в отчета.

## Преди заявките (товар)
```js
db.invoice_lines.estimatedDocumentCount()
db.contract_payments.estimatedDocumentCount()
db.employee_daily_reports.estimatedDocumentCount()
db.labor_entries.estimatedDocumentCount()
db.pay_runs.estimatedDocumentCount()
```
Това чете само метаданни. Ако някоя колекция е над 200 000 записа, заявката за нея не се пуска, а се преработва.
Очакван товар: 5 еднократни агрегации, всяка едно обхождане на една колекция (Q1 прави и търсене по `invoices.id` за всеки ред). За фирма с десетки хиляди редове това са секунди. Без запис, без индекси, без `$out`/`$merge`.

## Q1 — причина 2 (SKLAD-01): редове на анулирани/чернови/липсващи фактури, които се броят като разход на обект
```js
db.invoice_lines.aggregate([
  {$match: {$or: [{"allocations.type": "project"}, {allocation_type: "project"}]}},
  {$lookup: {from: "invoices", localField: "invoice_id", foreignField: "id",
             pipeline: [{$project: {_id: 0, status: 1}}], as: "inv"}},
  {$project: {_id: 0, amount: "$line_total_ex_vat",
              st: {$ifNull: [{$first: "$inv.status"}, "MISSING_INVOICE"]}}},
  {$group: {_id: "$st", lines: {$sum: 1}, sum_ex_vat: {$sum: "$amount"}}}
], {maxTimeMS: 20000})
```
Изход: статус на фактурата → брой редове, сума без ДДС. Проблем има, ако за `Cancelled`, `Draft` или `MISSING_INVOICE` сумата не е 0.

## Q2 — причина 1 (PARI-02): „платени“ траншове по договори с бригади, без движение в регистъра
```js
db.contract_payments.aggregate([
  {$unwind: "$tranches"},
  {$group: {_id: "$tranches.status", tranches: {$sum: 1}, sum: {$sum: "$tranches.amount"}}}
], {maxTimeMS: 10000})
```
Изход: статус на транша → брой, сума. Сумата при `paid` е размерът на парите, които са в печалбата, но не са в регистъра на плащанията.

## Q3 — причина 3 (TRUD-02): одобрени отчети в стария формат, които никога не стават „платени“
```js
db.employee_daily_reports.aggregate([
  {$match: {approval_status: "APPROVED"}},
  {$group: {_id: {format: {$cond: [{$ifNull: ["$worker_id", false]}, "new_worker_id", "old_employee_id"]},
                  payroll: {$ifNull: ["$payroll_status", "none"]}},
            reports: {$sum: 1}}}
], {maxTimeMS: 20000})

db.pay_runs.aggregate([
  {$match: {status: {$in: ["confirmed", "paid"]}}},
  {$group: {_id: "$week_number", runs: {$sum: 1}}},
  {$match: {runs: {$gt: 1}}},
  {$count: "weeks_with_more_than_one_pay_run"}
], {maxTimeMS: 10000})
```
Изход: формат × статус на плащане → брой отчети; и брой седмици с повече от една потвърдена ведомост. Тази заявка показва само дали условието за двойно плащане съществува, не дали е имало двойно плащане.

## Q4 — причина 4 (Р96): ръчни редове за труд
```js
db.labor_entries.aggregate([
  {$group: {_id: {source: {$ifNull: ["$source", "none"]},
                  approval: {$ifNull: ["$approval_status", "none"]},
                  payroll: {$ifNull: ["$payroll_status", "none"]}},
            rows: {$sum: 1}, hours: {$sum: "$hours"}, cost: {$sum: {$ifNull: ["$labor_cost", 0]}}}}
], {maxTimeMS: 10000})
```
Изход: източник × одобрение × плащане → брой, часове, сума. Редовете с `source` различен от `work_report_sync` са ръчните.

## Какво НЕ се проверява с този план
Останалите 8 причини, отделни хора, отделни документи, съдържание на файлове. Нищо не се записва в базата.

# SUB-ADV-01 — аванс към подизпълнител, приспадан от актовете (Р39, Р40)

Пакет: `docs/architecture/tasks/SUB-ADV-01_SUBCONTRACTOR_ADVANCE.md` (клон `claude/happy-meitner-bmcnel` @ 5617d40).
Стъпва на PR #69 (`claude/sec-01-money-write-permissions` @ ccab244); слива се **след #69**.

## Засегнати FLOW / решения
FLOW-021 (даден / прихванат / оставащ аванс; забранено „аванс без прихващане/остатък“ и „плащане над измереното без Approval“),
FLOW-006 (единен Payment ledger), CLAUDE §2.5, §7 (без автоматично нетиране), §14; Р14, Р29, Р39, Р40, FG-45, FG-90.

## Source of truth
- Парите: **един** Outflow ред в `finance_payments` (FLOW-006) за аванса и за всяко плащане.
- Записът на пакета: ред в `subcontractor_payments` с `kind = "advance"` (обикновените плащания: `kind = "payment"`;
  ред без `kind` = старо обикновено плащане). Не е нов регистър — същата колекция за разпределение по пакета.
  Ledger редът сочи обратно (`subcontractor_payment_id`, `subcontractor_advance: true`) — така FG-45 от #70 го хваща.
- Броячите на пакета (атомарни): `advance_total`, `advance_deducted_total`, `advance_deducted_by_act.<act_id>`, `committed_paid_total`.

## Правила
| | |
|---|---|
| Аванс | `POST /api/subcontractor-packages/{pkg_id}/advances` — `amount` (>0, крайно), `reason` (задължителна, ≤500, без контролни знаци), `advance_date`, `account_id`. Само **Owner / Accountant** (Р39; Admin е изваден от пълния си набор само за това действие). Idempotency-Key (Р29). AuditEvent `subcontractor_advance_created`. Пакетът трябва да е потвърден и незатворен. |
| Приспадане при плащане | `POST /api/subcontractor-payments` с `act_id` + `advance_deducted` (изрично поле). `amount` остава реално платените пари. Записва се в плащането, в акта (`advance_deducted` + запис в `advance_deductions`) и AuditEvent `subcontractor_advance_deducted`. Без `act_id` → 422 `ADVANCE_DEDUCTION_NEEDS_ACT`. `payment_type: "advance"` по обикновения път → 422 `ADVANCE_NOT_A_PAYMENT`. |
| Приспадане без пари | `POST /api/subcontractor-acts/{act_id}/advance-deduction` (`amount`, `reason` по избор) — за акт, покрит от аванса. Owner/Admin/Accountant (както плащането). Без ledger ред (няма движение на пари). |
| Таван (Р40) | Едно атомарно условно обновяване на пакета: обикновени плащания + приспаднат аванс ≤ удостоверено (`PAYMENT_EXCEEDS_CERTIFIED`, както FG-90); приспаднато ≤ неприспаднат остатък (`ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING`); приспаднато по акта ≤ удостовереното по акта (`ADVANCE_DEDUCTION_EXCEEDS_ACT`). Авансът сам не влиза в `committed_paid_total` и не е надплащане по FG-90. |
| Сторно | Няма hard delete. `DELETE /api/finance/payments/{id}` на ledger реда на аванс → 409 `SOURCE_MODULE_REVERSAL_REQUIRED` (FG-45), нищо записано — докато #70 (PAY-01 Част 2) не донесе сторно в модула. |
| Екран | Пакетът показва: Удостоверено, Платено, Аванси, Приспаднато, Остатък аванс; бутон „Аванс“; в плащането — „По акт“ и „Приспаднат аванс“. |

Видимите тотали на пакета: `paid_total` (само обикновени), `advance_total`, `advance_deducted_total`, `advance_outstanding`,
`payable_total = удостоверено − платено − приспаднато`, `cash_out_total = аванси + обикновени плащания`
(= аванс + плащания по актове бруто − приспаднато).

## Доказателство (`results.json`, реален MongoDB 7.0 replica set rs0, oplog)
- роли × 3 режима: Owner, Accountant → 201; Admin, SiteManager, Technician, Viewer, Driver → 403, нищо записано;
- аванс 1000 → плащане по акт 3000 (`amount` 2000 + `advance_deducted` 1000) → платено 2000, остатък аванс 0, committed 3000, паричен поток 3000, ledger +1000 +2000; актът показва 1000;
- обикновено плащане над удостовереното → 409 `PAYMENT_EXCEEDS_CERTIFIED`, нищо записано (непроменено, вкл. пакета от C02: 101 > 100);
- 6 паралелни авански заявки с един ключ → 1 ред аванс, 1 ledger ред, `advance_total` = 1000;
- без ключ → 428; без причина / nan → 422; приспадане без акт → 422; изтриване на ledger реда на аванс → 409 `SOURCE_MODULE_REVERSAL_REQUIRED`.

## Дълг / отворено (за Крум)
- **SUB-ADV-01-D1:** сторно на аванс и на приспадане — след #70 (PAY-01 Част 2 трябва да обработи и `kind = "advance"`: връща `advance_total` и, ако е приспаднат, отказва или изисква сторно на приспадането).
- **SUB-ADV-01-D2:** няма таван на аванса спрямо договорената стойност на пакета (пакетът не го изисква; бизнес решение).
- **SUB-ADV-01-D3:** справките по паричен поток/P&L (`project_pnl`, `project_financial_results`, `revenue_snapshot`, `finance` списък) събират всички редове на `subcontractor_payments` → включват аванса като изходящи пари (касова база, коректно за паричния поток); за начислен разход по пакета авансът не е разход — не е пипано, само отбелязано.
- Приспадането по акт за Admin е разрешено (както плащането, Р14); ако Р39 трябва да важи и за приспадането — кажете.

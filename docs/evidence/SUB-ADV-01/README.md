# SUB-ADV-01 — аванс към подизпълнител, приспадан от актовете (Р39, Р40)

Пакет: `docs/architecture/tasks/SUB-ADV-01_SUBCONTRACTOR_ADVANCE.md` (клон `claude/happy-meitner-bmcnel` @ 5617d40).
Стъпва на PR #69 (`claude/sec-01-money-write-permissions`, слят head 3fb55f2); слива се **след #69 и #70**.

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

## Допълнение A (07.11) — FG-113 / FG-114 / FG-115
- **FG-113:** слят head-ът на #69 (3fb55f2: Допълнения E/F) с merge commit, без rebase/force-push. Конфликтът в
  `subcontractors.py` е решен така: резервацията по пакета носи ключовия id (`cap_reservations`, F-69-03), вкл. броячите
  на приспадането; сумата на платеното — в базата (FG-105), без авансите.
- **FG-114:** авансът първо се резервира срещу договорната стойност на пакета, атомарно (`_reserve_advance`, условен
  `$set` с id на резервацията `advance_reservations`):
  `(аванс − приспаднато) + committed (обикновени плащания + приспаднато) + новият аванс ≤ contract_total`.
  Приспаднатата част се брои веднъж. Над това → 409 `ADVANCE_EXCEEDS_PACKAGE_VALUE`, нищо записано.
  Пакет без договорна стойност → 422 `ADVANCE_PACKAGE_VALUE_REQUIRED`.
- **FG-115 (FLOW-006: каса и резултат не се смесват):** `app/services/subcontract_cost.py` —
  касата (`subcontractor_cash_out`) брои и аванса; P&L / оперативният и пълният резултат (`subcontractor_cost_recognized`)
  броят обикновените плащания + приспаднатия аванс. `project_pnl.expense.subcontractor_cost`,
  `financial-results.operating.subcontractor_direct` и тежестта на подизпълнителя ползват признатия разход;
  `financial-results.cash.breakdown.paid_subcontractors` и `revenue_snapshot.costs_paid` — касата (без промяна).
- Удръжката по акт остава Owner/Admin/Accountant (Р14). D1 (сторно) — PAY-01 Част 2; #76 се слива след #69 и #70.

## Допълнение B (07.11) — FG-103 / FG-128
- **FG-103 (две фази, трайна идентичност; без транзакция — `auth_tx` няма в основата на #69):**
  резервацията е **чакаща** (`advance_pending_total`, `advance_deduction_pending_total` / `_by_act`), докато редовете,
  които представя, не съществуват; чак тогава се потвърждава в броячите (`advance_total`, `advance_deducted_total`,
  `advance_deducted_by_act`) с едно условно обновяване по ключовия id (`advance_confirmed`,
  `advance_deduction_confirmed`) — никога два пъти. Чакащата сума държи място под тавана, но **не може да се приспадне,
  не е разход (P&L ползва `advance_deducted_total`) и не е платено**. Записът в акта е условен по id на записа
  (`advance_deductions.id`) — повтор след срив не го добавя втори път. Retry със същия ключ довършва точно веднъж.
- Тестове за срив (3 режима, срив след записа и преди отбелязването на стъпката):
  A) аванс — срив след резервацията → чакащо 1000, 0 реда, 0 ledger; приспадане 100 и плащане с приспаднати 1000 →
  409 `ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING`, нищо записано; retry → 201, 1 аванс, 1 ledger, `advance_total` 1000; повтор → replay;
  B) аванс — срив след редовете и AuditEvent → още не се приспада (чакащо 500); retry потвърждава веднъж (1500);
  C) приспадане — срив след резервацията → чакащо 200, актът — нищо, разход — нищо; retry → актът 200, приспаднато 200, веднъж;
  D) приспадане — срив след записа в акта → retry не дублира (1 запис, 150).
- **FG-128:** даден / приспаднат / оставащ аванс (`advance`: given, deducted, outstanding, pending) — в пакета
  (`GET /subcontractor-packages`, `/{id}`), в актовете (`advance_deducted`, `advance_deductions`), в плащанията (редовете
  `kind = advance`) и във финансовия преглед `GET /project-profit/{id}` → `subcontract_advances` (извън `expenses` — не е ред
  в P&L). Само за финансовите роли (Owner/Admin/Accountant; enforce — Permission Service); за останалите полетата и
  редовете се скриват (не отказ). Екранът показва колоните „Аванси / Приспаднато / Остатък аванс“ и бутона „Аванс“ само на тях.

## Codex @ 542fa2c (CHANGES_REQUESTED) + merge на main d226c49 (#70)
- **Merge (`9ba9ec7`, merge commit, без rebase):** main носи #70 (PAY-01) и #72 (W0-04-C01); #69 още не е в main, затова
  тук се среща и припокриването #69 × #70. `finance.py` = main (сторно вместо изтриване; FG-45 `_source_module_refusal`
  отказва всеки ledger ред с `subcontractor_payment_id` — вкл. аванса; собствената ни защита на старото изтриване отпада);
  `frontend/src/lib/idempotency.js` — и двата holder-а (#69 `createIdempotencyHolder`, #70 `createKeyHolder`) + `apiErrorText`;
  A1 инвентар и PM-01 — регенерирани от скриптовете. **Внимание:** при сливането на #69 с main същите конфликти ще се решават
  там; решенията тук са описани в merge commit-а.
- **F-76-01 [P1]:** един израз за поетото по пакета (`_TAKEN`): неприспаднат аванс (вкл. чакащ, минус чакащи приспадания)
  + `committed` (обикновени плащания + всички приспадания). И резервацията на аванса, и резервацията на обикновеното плащане
  проверяват `_TAKEN + нови пари ≤ contract_total` в същото атомарно обновяване → 409 `PAYMENT_EXCEEDS_PACKAGE_VALUE`
  (плащане) / `ADVANCE_EXCEEDS_PACKAGE_VALUE` (аванс). Приспадането само прехвърля сума от аванса в committed — не мени
  `_TAKEN`. Пакет без договорна стойност: само таванът по удостовереното (аванс там е отказан с 422).
- **F-76-02 [P2]:** `log_audit(..., entry_id=...)` — трайното id на операцията (от ключа) е и `_id` на реда; повтор след
  срив намира реда и не пише втори. Ползва се за `subcontractor_advance_created` и `subcontractor_advance_deducted`.
  Тези маршрути (както плащането на #69) пишат само legacy `audit_logs`; каноничен AuditEvent envelope тук не се пише.

## Дълг / отворено (за Крум)
- **SUB-ADV-01-D4:** чакаща резервация от прекъсната заявка, която никой не повтаря, остава чакаща (държи място под
  тавана, без пари и без разход). Видима е в пакета (`advance.pending`); освобождаване — с повтор със същия ключ или
  бъдещ административен инструмент (не е правен).
- **SUB-ADV-01-D1:** сторно на аванс и на приспадане — след #70 (PAY-01 Част 2 трябва да обработи и `kind = "advance"`: връща `advance_total` и, ако е приспаднат, отказва или изисква сторно на приспадането).
- ~~SUB-ADV-01-D2~~ затворен от FG-114 (таван = договорната стойност на пакета).
- ~~SUB-ADV-01-D3~~ затворен от FG-115 (P&L признава разхода при прихващане; касата показва аванса).

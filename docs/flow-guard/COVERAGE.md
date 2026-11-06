# FLOW GUARD — покритие на main по FLOW

Бавен преглед: по един FLOW на проход. Легенда:

- ✅ — изпълнено;
- ⚠️ — частично;
- ❌ — противоречи на канона;
- ⏳ — още не е изпълнено (не е разминаване, ако вълната не е стигнала дотам).

## Проход 1 — FLOW-002 (Потребители / роли / права / достъп)

- main @ `07da9ab`, 06.11.2026.
- Прочетени: `backend/app/permissions/*`, `backend/app/routes/labor_smr.py`, `backend/app/deps/modules.py`.
- Проба: `probes/fg1_labor_entries_probe.py`.

| Правило в FLOW-002 | Състояние | Къде / бележка |
|---|---|---|
| RoleAssignment с person/role/scope/module/permissions/valid_from/valid_to/status/created_by/approved_by | ✅ | `permissions/sync.py:196-205`, `:265-272`; `max_amount` покрива „сума“ |
| Обхват: фирма/обект/модул/сума/статус/период | ⚠️ | Има scope, module, max_amount и validity (`permissions/service.py:102-138`). Няма ограничение по подобект, тип документ, конкретен запис/версия и статус |
| „По-ограниченото право има предимство“ | ❌ SUSPECTED | `permissions/service.py:160-176` използва правилото на обединението: позволява, ако **кое да е** назначение позволява. Няма запис-ограничение (deny), който да бие по-широко назначение → **FG-12** |
| Основни роли (канонични) | ⚠️ | `permissions/catalog.py:90-125`: 11 канонични роли. Technician/Viewer остават като LEGACY без канонично съответствие. Няма „Подизпълнителски контакт“ и „Клиент“ — правилно, те са външни (ExternalPrincipal) |
| Permission Service е авторитетен | ⚠️ | По подразбиране `PERMISSION_SERVICE_MODE=off` (`permissions/deps.py:51`). Решават legacy проверките. Р15: staging = `shadow` |
| Критични действия: изрични права + AuditEvent | ⚠️ | Промените на права се одитират (`permissions/audit_hooks.py:59-68`). Трудът (основа за заплата) няма право и AuditEvent → **FG-1** |
| Директен URL не заобикаля правата | ❌ PROVEN | `POST/GET /api/labor-entries`: само модулен gate M2, без роля и без членство → **FG-1** |
| Двустепенно одобрение (двама различни) | ⏳ | Няма общ механизъм в `permissions/`. Зависи от W0-07 Approval runtime |
| ExternalPrincipal / AccessGrant / magic link | ⏳ | Не е изпълнено. Няма и клиентски портал в кода, така че условието „преди FLOW-046“ не е нарушено |
| AI вижда ≤ потребителя | ✅ (каталог) | `catalog.py:123`: `ai_service` без действия. AI tool проверките не са прегледани в този проход |
| Крум вижда роли/временни/рискови права | ⏳ | Не е прегледан UI |
| Промяна на права без AuditEvent е забранена | ✅ | `audit_hooks.py:59` `permission.role_assignment.*`. R0-03 (main) — смяна на роля с AuditEvent |


## Странично покритие — FLOW-009 в PR #55 (`53dbd28`, не е на main)

Това не е бавният преглед на main. Записва се, за да не се гледа два пъти.

| Правило в FLOW-009 / решение | Състояние | Бележка |
|---|---|---|
| Всяко движение е отделен неизтриваем запис (източник, количество, стойност, локации, основание) | ✅ | append-only ledger, `recorded_at` от сървъра; корекция чрез `corrects_movement_id` / ревизия |
| Rule B склад → обект: в път → приемане, частично приемане, видими разлики | ✅ | C21 тестове |
| Р11 склад → склад през „в път“ | ✅ | директен трансфер се отказва |
| обект → обект / обект → склад с потвърждение от приемащ | ❌ | **FG-18** |
| Върнат материал → карантина | ❌ | **FG-18** |
| Карантината е състояние на реална локация | ✅ | |
| Стойност на изхода по FIFO от сървъра; клиентска стойност се отказва | ✅ | |
| Материалният разход се признава само веднъж | ⚠️ | склад вътрешно — да; P&L спрямо фактурите — не (**FG-17**); моментът на признаване — **FG-20** |
| Р10 фира = разход на обекта, отделен ред | ⚠️ | в каноничния helper — да; в P&L не увеличава разхода (**FG-17**) |
| Р13 преход по дата | ✅ | освен P&L (**FG-17**) |
| Ревизия: DQ/Approval при съществена разлика | ❌ | **FG-22** |
| Наличност по складове/обекти/транспорт | ⚠️ | **FG-19** |
| AuditEvent в същата транзакция | ✅ | hash-chained |
| Няма hard delete на официални записи | ✅ | `delete_many` само върху възстановимата проекция `material_entries` |
| Плащания | ✅ | FLOW-006 не се пипа |

## Проход 2 — FLOW-006 (Фактури / аванси / плащания / ДДС)

- main @ `07da9ab`, 06.11.2026.
- Прочетени: `backend/app/routes/finance.py`, `reports.py`, `hr.py`, `subcontractors.py`, `pay_runs.py`, `dashboard.py`.
- Без проба (само четене).

| Правило в FLOW-006 | Състояние | Къде / бележка |
|---|---|---|
| Единен Payment ledger | ❌ SUSPECTED | `finance_payments` е основният, но `cash_transactions`, `bonus_payments` и `overhead_transactions` са отделни парични записи (`reports.py:939-1065`), които dashboard чете → **FG-35** |
| FLOW-021/028 създават задължения, FLOW-006 плаща | ⚠️ | Pay Run пише към `finance_payments` (`pay_runs.py:1349`, R0-05/R0-06). На main подизпълнителското плащане е отворено за всички (**FG-27**, поправено в #69) |
| Фактурата не е плащане; отделни статуси (платено/частично/просрочено) | ✅ | `payment_allocations` + `update_invoice_status` (`finance.py:1218-1226`) |
| Плащането винаги има каса/банка/източник | ⚠️ | `finance_payments` има метод/сметка. `cash_transactions` има само тип и категория, без сметка и основание (**FG-35**) |
| Net / VAT / Gross отделно | ✅ | `finance.py:50-55` (subtotal, vat_amount, total) |
| Аванси не изчезват при промяна на обхвата | ⏳ | Не е прегледано в този проход |
| Корекции: без тихо редактиране, реверс, AuditEvent | ❌ SUSPECTED | `DELETE /finance/payments/{id}` и премахването на разпределение трият плащането (`finance.py:1223,1435`) → **FG-34** |
| permission checks за плащане | ⚠️ | `finance_permission` = Admin/Owner/Accountant (`clients.py:26-28`). На main подизпълнителските плащания не се проверяват → **FG-27** (#69 ✅) |
| idempotency за плащания | ❌ | В `finance.py`, `hr.py` и `reports.py` няма idempotency ключ. В `pay_runs.py` има (R0-06). Двойно изпратена заявка = двойно плащане. Gate изискване → кандидат за W0-05 |
| двустепенно одобрение за критични суми | ⏳ | Няма. Зависи от W0-07 |
| AI да не плаща сам | ✅ | Няма AI tool с право за плащане (`catalog.py:123`) |


## Проход 3 — FLOW-040 (AuditEvent / AI Audit Log)

- main @ `8e3b190` (= `07da9ab` + PM-01 #68, без промяна в app кода), 06.11.2026.
- Прочетени: `backend/app/audit/{envelope,store,idempotency}.py`, `app/utils/audit.py`, `app/services/audit.py`; извикванията на `record_event`.
- Проба: `probes/fg37_audit_chain_race_probe.py`.

| Правило в FLOW-040 | Състояние | Къде / бележка |
|---|---|---|
| Каноничен AuditEvent envelope (§3) | ✅ | `audit/envelope.py:120-205` — полетата от §3, вкл. retention_class, legal_hold, integrity_hash/previous_hash |
| Append-only; без update/delete през API (§2, §8, §15) | ✅ | Няма `audit_events.update/delete` в `app/` |
| Hash chain по tenant (§8) | ❌ PROVEN | `audit/store.py:107-119`: `_last_event` + `insert_one` без lock, транзакция или уникален индекс (tenant_id, sequence). 20 едновременни записа → 3 различни sequence, `verify_chain` = false → **FG-37** |
| Един общ envelope, не паралелен регистър (§2; CLAUDE.md §2.8) | ⚠️ | Каноничният `audit_events` се ползва само от permissions, master_data, tenancy и `user_role_policy` (10 места). 22 route файла пишат legacy `audit_logs` (`utils/audit.py:78`, `services/audit.py:24`) — без hash, без retention_class. Това е дългът на W0-04; при пари/склад/заплати → FG-34, FG-1 |
| Задължителни събития §4.1 (вход, права, permission denied) | ⚠️ | Промените на права — ✅ (`permissions/audit_hooks.py`). Permission denied — само в `enforce` (**FG-28**) |
| §4.2 финансови (плащане, allocation, reversal, Pay Run) | ⚠️ | Pay Run (R0-05/06) — да. Плащания/allocation в `finance.py` — само legacy `log_audit` или нищо (**FG-34** → PAY-01 #70) |
| §4.3 оперативни (склад, присъствие, отчети) | ⚠️ | Каноничният склад в #55 — да (hash chain в същата транзакция). Труд/отпадък на main — не (FG-1) |
| Retention класове и минимални срокове (§6) | ⚠️ | Класовете са в envelope. Security събитията извън веригата (AUTH-01 #56) вече са 730 дни (FG-10 ✅) |
| Без raw secret/token/password (§9, §15) | ✅ | `envelope.py:98-117 mask_sensitive`, `_assert_no_secrets` (`:241`) |
| Immutable/WORM архив, signed manifest, integrity аларма (§8) | ⏳ | Няма в кода. W0-04 / FLOW-044 |
| Видимост по роля L0–L5 (§10–11) | ⏳ | Няма audit UI/API по роли в този преглед |
| Break-glass (L5) | ✅ на клона с пакетите | D-16 + AUTH-02 (#56) |
| idempotency_key в event (§3) | ⚠️ | Поле има. `audit/idempotency.py` е само за части от кода; паричните записи на main нямат idempotency (FLOW-006 coverage) |

Следващ FLOW в бавния преглед: **FLOW-028** (заплати / Pay Run).

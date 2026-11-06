# PM-01 — кой какво може в PERMISSION_SERVICE_MODE off / shadow / enforce

> Пакет: `docs/architecture/tasks/PM-01_PERMISSION_MODE_ROLE_MATRIX.md` (одобрен от Крум, 06.11.2026, Р9).
> Източник на въпроса: PR #64 `02-release-gates.md`, стъпка 5 — „Existing layout expects `PERMISSION_SERVICE_MODE=off`; LIVE-OPS writes require `enforce`. Resolve this explicitly with tested roles before building.“
> База: `main` @ `07da9ab`. FLOW-002 (потребители и роли), W0-02 Permission Service.
> **Само факти. Нищо не е променено** — нито права, нито роли, нито флагове, нито бизнес код.

## 1. Какво е проверено

* **Всички 752 endpoint-а**, които приложението реално обслужва днес (`server.app`, всеки метод поотделно). Старият списък `backend/artifacts/endpoints_inventory.csv` има само 148 реда и е остарял — затова тестът чете маршрутите от самото приложение.
* **8 роли** на фирма A от ST-01 фикстурите (`ops/staging/`): Owner, Admin, SiteManager (`requester`), Technician, Accountant, Warehousekeeper, Driver, Viewer. Истински потребители, TenantMembership и RoleAssignment по FLOW-002, истински вход с парола и JWT.
* **3 режима**: `off`, `shadow`, `enforce`.
* Общо **18 048 извиквания** (752 × 8 × 3). За всяко: HTTP статус и **дали нещо е записано** в базата (мерено от oplog-а на MongoDB, не по отговора). След всяко записване базата се връща в началното състояние, така че всяка клетка започва от едни и същи данни.
* Истинска MongoDB 7.0 (replica set, локален Docker), празни временни бази `pm01_op_*` / `pm01_sys_*`, изтрити след теста. Изходящият интернет е спрян — не се праща имейл, не се вика плащане или AI.
* Пуснато **два пъти**: двата резултата са **байт по байт еднакви** (`cmp`).

Пълният резултат: `docs/evidence/PM-01/matrix.csv` (ред за всяка клетка) и `docs/evidence/PM-01/run_meta.json`. Тестът: `backend/tests/test_pm_01_permission_matrix.py`.

## 2. Главният извод (с една дума)

**На `main` трите режима дават един и същ отговор за всяка роля на всеки endpoint.** В нито една от 6 016 клетки (endpoint × роля) статусът в `shadow` или `enforce` не е различен от `off`.

Причината е проста: от 752 endpoint-а само около **50 изобщо питат Permission Service** (4 с `require_permission`, 24 зад `require_admin`, 22 на Master Data). Останалите **~680 не гледат режима** — те решават само по стария `users.role` или по членство в проекта, във всеки режим еднакво. А там, където Permission Service решава, каталогът (`app/permissions/catalog.py`) е настроен да повтаря днешното поведение — и го повтаря точно.

Единствените разлики са в **записите**, не в достъпа:

| Къде | off | shadow | enforce |
|---|---|---|---|
| Отказан запис на потребител / одобрение на актив (`POST /api/users`, `PUT /api/users/{user_id}`, `POST /api/assets/intake/{intake_id}/approve`) за роли без право | 403, нищо не е записано | 403, нищо не е записано | 403 **+ AuditEvent „отказан достъп“** в `audit_events` |
| Owner/Admin създава потребител (`POST /api/users`) | 201, записва `users` + `audit_logs` | 201 **+ RoleAssignment (FLOW-002) + AuditEvent** | 201 **+ RoleAssignment + AuditEvent + idempotency запис** |

И двете разлики са очаквани по дизайна на W0-02 (одит на отказ в enforce; синхронизация на ролята в shadow/enforce — `app/permissions/sync.py`).

## 3. Таблица по модули

Числата във всяка роля са **„стига до функцията / отказан“** в `off`:
* „стига“ = статус под 400 (200/201 и т.н.);
* „отказан“ = 401 или 403.
Остатъкът до броя endpoint-и са 404/400/422 — функцията е стигната, но липсва запис (тестът ползва несъществуващи id за всичко освен проекта, склада и потребителя на фирма A) или тялото не е валидно.
Последните две колони = **в колко клетки статусът е различен от `off`**.

| Модул | Endpoint-и | Owner | Admin | SiteMgr | Technician | Accountant | Warehouse | Driver | Viewer | shadow ≠ off | enforce ≠ off |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `activity_budgets` | 14 | 9/0 | 9/0 | 3/7 | 3/7 | 3/7 | 3/7 | 3/7 | 3/7 | 0 | 0 |
| `ai_calibration` | 6 | 5/0 | 5/0 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 0 | 0 |
| `alarms` | 12 | 7/0 | 7/0 | 5/4 | 5/4 | 5/4 | 5/4 | 5/4 | 5/4 | 0 | 0 |
| `all_reports` | 1 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `asset_item_types` | 2 | 2/0 | 2/0 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0 | 0 |
| `assets_ai_intake` | 1 | 0/0 | 0/0 | 0/0 | 0/1 | 0/0 | 0/1 | 0/1 | 0/1 | 0 | 0 |
| `assets_batch_intake` | 1 | 0/0 | 0/0 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | 0 | 0 |
| `assets_custody` | 7 | 3/0 | 3/0 | 3/0 | 2/1 | 2/1 | 2/1 | 2/1 | 2/1 | 0 | 0 |
| `assets_intake_pending` | 7 | 4/0 | 4/0 | 1/6 | 1/6 | 1/6 | 1/6 | 1/6 | 1/6 | 0 | 0 |
| `assets_items` | 5 | 2/0 | 2/0 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 | 0 | 0 |
| `assets_qr` | 6 | 2/0 | 2/0 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 | 0 | 0 |
| `assets_repairs` | 3 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `assets_units` | 7 | 2/0 | 2/0 | 2/3 | 2/3 | 2/3 | 2/3 | 2/3 | 2/3 | 0 | 0 |
| `attendance` | 26 | 18/0 | 18/0 | 18/0 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 0 |
| `auth` | 13 | 8/4 | 8/4 | 4/9 | 4/9 | 4/9 | 4/9 | 4/9 | 4/9 | 0 | 0 |
| `billing` | 9 | 5/1 | 5/1 | 5/3 | 5/3 | 5/3 | 5/3 | 5/3 | 5/3 | 0 | 0 |
| `brigades` | 7 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0 | 0 |
| `budget_progress` | 10 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 0 | 0 |
| `cashflow_forecast` | 2 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0 | 0 |
| `centralized_reports` | 4 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `clients` | 15 | 9/0 | 9/0 | 8/3 | 8/3 | 9/0 | 8/3 | 8/3 | 8/3 | 0 | 0 |
| `counterparties` | 9 | 3/0 | 3/0 | 2/6 | 2/6 | 3/0 | 2/6 | 2/6 | 2/6 | 0 | 0 |
| `daily_reports` | 17 | 10/0 | 10/0 | 10/1 | 8/5 | 8/5 | 8/5 | 8/5 | 8/5 | 0 | 0 |
| `dashboard` | 9 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 | 9/0 | 0 | 0 |
| `employee_dossier` | 1 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `excel_import_v2` | 10 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 3/0 | 0 | 0 |
| `expected_actual` | 2 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0 | 0 |
| `extra_works` | 16 | 8/0 | 8/0 | 7/1 | 7/5 | 7/5 | 7/5 | 7/5 | 7/5 | 0 | 0 |
| `finance` | 34 | 15/0 | 15/0 | 3/30 | 1/32 | 14/1 | 1/32 | 1/32 | 1/32 | 0 | 0 |
| `financial_results` | 2 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0 | 0 |
| `full_cost` | 10 | 9/0 | 9/0 | 8/1 | 8/1 | 8/1 | 8/1 | 8/1 | 8/1 | 0 | 0 |
| `health` | 5 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 0 | 0 |
| `historical_offers` | 3 | 1/0 | 1/0 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0 | 0 |
| `hr` | 19 | 10/0 | 10/0 | 1/16 | 3/14 | 10/0 | 1/16 | 1/16 | 1/16 | 0 | 0 |
| `invoice_lines` | 13 | 5/0 | 5/0 | 5/5 | 5/5 | 5/0 | 5/5 | 5/5 | 5/5 | 0 | 0 |
| `items` | 6 | 3/0 | 3/0 | 2/3 | 2/3 | 3/1 | 3/1 | 2/3 | 2/3 | 0 | 0 |
| `labor_smr` | 6 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `locations` | 8 | 2/0 | 2/0 | 2/0 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 0 | 0 |
| `master_data` | 22 | 22/0 | 22/0 | 6/16 | 0/22 | 5/17 | 4/18 | 0/22 | 0/22 | 0 | 0 |
| `material_smr` | 7 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 0 | 0 |
| `material_waste` | 4 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `materials_baseline` | 5 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `media` | 7 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `missing_smr` | 17 | 2/0 | 2/0 | 2/0 | 2/1 | 2/1 | 2/1 | 2/1 | 2/1 | 0 | 0 |
| `mobile` | 6 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 0 | 0 |
| `morning_briefing` | 2 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0 | 0 |
| `ocr_invoice` | 8 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `offer_versions` | 5 | 0/0 | 0/0 | 0/0 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | 0 | 0 |
| `offers` | 23 | 4/0 | 4/0 | 4/0 | 4/3 | 4/3 | 4/3 | 4/3 | 4/3 | 0 | 0 |
| `overhead` | 19 | 11/0 | 11/0 | 7/11 | 2/17 | 11/0 | 2/17 | 2/17 | 2/17 | 0 | 0 |
| `overhead_realtime` | 11 | 9/0 | 9/0 | 8/1 | 8/1 | 9/0 | 8/1 | 8/1 | 8/1 | 0 | 0 |
| `pay_runs` | 14 | 6/0 | 6/0 | 4/6 | 5/5 | 5/5 | 4/6 | 4/6 | 4/6 | 0 | 0 |
| `platform` | 2 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `price_modifiers` | 9 | 7/0 | 7/0 | 6/1 | 6/1 | 6/1 | 6/1 | 6/1 | 6/1 | 0 | 0 |
| `pricing` | 6 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `procurement` | 21 | 8/0 | 8/0 | 7/1 | 6/5 | 7/4 | 7/2 | 6/5 | 6/5 | 0 | 0 |
| `project_pnl` | 7 | 7/0 | 7/0 | 2/5 | 2/5 | 3/4 | 2/5 | 2/5 | 2/5 | 0 | 0 |
| `projects` | 39 | 24/0 | 24/0 | 18/13 | 15/17 | 15/17 | 15/17 | 15/17 | 15/17 | 0 | 0 |
| `pulse` | 6 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 6/0 | 0 | 0 |
| `reports` | 13 | 12/0 | 12/0 | 12/0 | 12/0 | 12/0 | 12/0 | 12/0 | 12/0 | 0 | 0 |
| `resource_model` | 7 | 6/0 | 6/0 | 5/1 | 5/1 | 5/1 | 5/1 | 5/1 | 5/1 | 0 | 0 |
| `revenue_expense` | 12 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 0 | 0 |
| `revenue_snapshot` | 6 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `sales` | 7 | 5/0 | 5/0 | 4/1 | 4/1 | 4/1 | 4/1 | 4/1 | 4/1 | 0 | 0 |
| `scan_docs` | 7 | 2/0 | 2/0 | 2/0 | 2/0 | 2/0 | 0/6 | 2/0 | 0/6 | 0 | 0 |
| `settings` | 7 | 5/1 | 5/1 | 2/4 | 2/4 | 2/4 | 2/4 | 2/4 | 2/4 | 0 | 0 |
| `smr_analysis` | 21 | 1/0 | 1/0 | 1/0 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 0 | 0 |
| `smr_groups` | 11 | 4/0 | 4/0 | 4/0 | 3/2 | 3/2 | 3/2 | 3/2 | 3/2 | 0 | 0 |
| `subcontractor_performance` | 5 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 4/0 | 0 | 0 |
| `subcontractors` | 16 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 5/0 | 0 | 0 |
| `technician` | 27 | 17/0 | 17/0 | 17/0 | 17/2 | 17/2 | 17/2 | 17/2 | 17/2 | 0 | 0 |
| `warehouse_batches` | 8 | 5/0 | 5/0 | 4/2 | 4/2 | 4/3 | 5/0 | 4/3 | 4/3 | 0 | 0 |
| `warehouses` | 8 | 7/0 | 7/0 | 7/0 | 4/3 | 4/3 | 7/0 | 4/3 | 4/3 | 0 | 0 |
| `weekly_matrix` | 1 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 1/0 | 0 | 0 |
| `work_logs` | 18 | 5/3 | 5/3 | 4/6 | 4/6 | 4/6 | 4/6 | 4/6 | 4/6 | 0 | 0 |
| `work_sessions` | 10 | 5/0 | 5/0 | 5/1 | 5/3 | 5/3 | 5/3 | 5/3 | 5/3 | 0 | 0 |

## 4. Кой ГУБИ достъп в `enforce` в сравнение с днес

**Никой.** 0 клетки. Няма роля, която в `enforce` получава отказ (401/403/409) на endpoint, до който в `off` стига. Няма и обратното — никой не получава нов достъп.

Важно условие (не е проверено тук, виж §7): това е вярно, когато **всеки потребител има TenantMembership и RoleAssignment** в системната база, както в ST-01 фикстурите. Ако на реалните данни някой потребител няма RoleAssignment, в `enforce` той ще получи 403 на ~50-те endpoint-а, които питат Permission Service (кодът няма връщане към `users.role` — `app/permissions/deps.py`).

## 5. Кой ИМА достъп в `off`, който не трябва да има

Мярката е каталогът на ролите по FLOW-002 (`app/permissions/catalog.py`), не мое мнение:
* **Viewer** — „само четене; всяко четене е през членство в проекта, на ниво фирма не дава нищо“;
* **Driver** — без никакви действия;
* **Technician** — само подаване на актив за приемане; **освен** труд и фира на обект, на който е член (Р16, Крум 06.11.2026 — бележка на SEC-01-C02 / FG-31: каталогът тук не е „трябва“ за труда и фирата; правилото е Р16, и SiteManager също);
* **Warehousekeeper** — подаване на актив, предложение за Master Data, четене на Master Data.

В теста тези потребители **не са членове на нито един проект**. Въпреки това в `off` (и еднакво в `shadow` и `enforce`):

### 5.1. Viewer записва (28 endpoint-а — долна граница)

> **SEC-01-C02 (FG-31):** списъкът е **долна граница**, не пълен списък. Харнесът вика всеки route с несъществуващи id и празно тяло, затова DELETE по id, плащане по пакет и „sync от съществуващи данни“ нямат върху какво да действат и не показват запис (§7.6). Пропуснати тук и доказани с проби върху съществуващи записи: `DELETE /api/price-modifiers/project/{id}` (FG-25 → SEC-01-C01), `POST /api/labor-entries/sync-from-work-reports` (FG-26 → C01 + C02, без изтриване), `POST /api/subcontractor-payments` (FG-27 → C02) и паричните записи на FG-30 (C02). Пробите: `tests/test_sec_01_c01_all_money_writes.py`, `tests/test_sec_01_c02_flow_guard_money_writes.py`; разликата в матрицата — `docs/evidence/SEC-01-C02/pm01_cells_changed.csv`.

> **SEC-01 (Р14):** 8 от тези endpoint-а (`cash-transactions`, `bonus-payments`, `overhead-transactions`, `overhead-snapshots`, `price-modifiers/project/{project_id}`, `labor-entries`, `material-waste`, `client-link`) вече връщат 403 без запис за всички роли освен Owner/Admin/Accountant, еднакво в трите режима. Таблицата по-долу е състоянието на `main` @ `07da9ab`; актуалната матрица е `docs/evidence/PM-01/matrix.csv`, разликата клетка по клетка — `docs/evidence/SEC-01/pm01_cells_closed.csv` (120 клетки).

Тези извиквания **реално записаха** в базата (oplog). Последната колона показва, че Driver, Technician и Warehousekeeper могат същото.

| Модул | Endpoint | Viewer статус | Записано (колекции) | Също Driver / Technician / Warehousekeeper |
|---|---|---:|---|---|
| `ai_calibration` | `POST /api/ai-calibration/record-edit` | 200 | op.ai_calibration_events | да/да/да |
| `attendance` | `POST /api/attendance/mark` | 201 | op.attendance_entries, op.audit_logs | да/да/да |
| `billing` | `POST /api/billing/signup` | 200 | op.audit_logs, op.feature_flags, op.organizations, op.subscriptions, op.users, sys.tenant_memberships, sys.tenant_registry, sys.tenant_role_assignments | да/да/да |
| `brigades` | `POST /api/brigades` | 200 | op.audit_logs, op.brigades | да/да/да |
| `clients` | `POST /api/clients/find-or-create` | 200 | op.clients | да/да/да |
| `clients` | `POST /api/clients/person` | 201 | op.persons | да/да/да |
| `clients` | `PATCH /api/projects/{project_id}/client-link` | 200 | op.projects | да/да/да |
| `daily_reports` | `POST /api/daily-reports` | 201 | op.employee_daily_reports | да/да/да |
| `excel_import_v2` | `POST /api/excel-import/templates` | 201 | op.excel_import_templates | да/да/да |
| `full_cost` | `POST /api/overhead-snapshots` | 201 | op.overhead_snapshots | да/да/да |
| `labor_smr` | `POST /api/labor-entries` | 201 | op.labor_entries | да/да/да |
| `material_waste` | `POST /api/projects/{project_id}/material-waste` | 201 | op.material_waste_entries | да/да/да |
| `price_modifiers` | `PUT /api/price-modifiers/project/{project_id}` | 200 | op.price_modifiers_config | да/да/да |
| `projects` | `POST /api/companies` | 201 | op.audit_logs, op.companies | да/да/да |
| `projects` | `POST /api/persons` | 201 | op.audit_logs, op.persons | да/да/да |
| `pulse` | `POST /api/pulse/generate-all` | 200 | op.site_pulses | да/да/да |
| `pulse` | `GET /api/pulse/today` | 200 | op.site_pulses | да/да/да |
| `pulse` | `GET /api/sites/{site_id}/pulse` | 200 | op.site_pulses | да/да/да |
| `pulse` | `POST /api/sites/{site_id}/pulse/generate` | 200 | op.site_pulses | да/да/да |
| `reports` | `POST /api/finance/bonus-payments` | 201 | op.bonus_payments | да/да/да |
| `reports` | `POST /api/finance/cash-transactions` | 201 | op.cash_transactions | да/да/да |
| `reports` | `POST /api/finance/overhead-transactions` | 201 | op.overhead_transactions | да/да/да |
| `subcontractor_performance` | `POST /api/subcontractor-performance` | 201 | op.subcontractor_performance | да/да/да |
| `subcontractors` | `POST /api/subcontractors` | 201 | op.subcontractors | да/да/да |
| `technician` | `POST /api/technician/material-request` | 201 | op.material_requests | да/да/да |
| `technician` | `POST /api/technician/request-equipment` | 201 | op.equipment_requests | да/да/да |
| `technician` | `POST /api/technician/site/{project_id}/attendance` | 200 | op.site_daily_rosters | да/да/да |
| `technician` | `POST /api/technician/site/{project_id}/roster` | 200 | op.site_daily_rosters | да/да/да |

Бележка: `POST /api/billing/signup` е публична регистрация на нова фирма — работи и без вход, затова не е въпрос на роля (виж 5.3).

### 5.2. Viewer чете финанси, заплати и печалба на ниво фирма

> **SEC-02 (Р20):** всеки от 58-те endpoint-а в тази таблица вече има правило — 50 връщат 403 за всички роли освен Owner/Admin/Accountant (R20-1/R20-2), `expected-actual` (×2) и `centralized-reports/activities` пускат и SiteManager на обект, където е член днес (R20-2B, без цени към клиента), `all-reports` и `weekly-matrix` скриват ставките и стойностите (R20-5), а `/dashboard/stats`, `/worker-calendar` и `/billing/check-module/{code}` нямат пари и остават. Еднакво в трите режима. Регистърът: `backend/app/permissions/finance_read.py`; доказателството и таблицата endpoint → правило → източник: `docs/evidence/SEC-02/README.md`; разликата в матрицата: `docs/evidence/SEC-02/pm01_cells_changed.csv` (1215 клетки). Таблицата по-долу е състоянието преди SEC-02.

Отговор 200 (данните в теста са празни, но достъпът е отворен):

| Модул | Endpoint-и (GET), които Viewer чете с 200 |
|---|---|
| `all_reports` | `/api/all-reports` |
| `billing` | `/api/billing/check-module/{module_code}`, `/api/billing/subscription`, `/api/billing/usage` |
| `cashflow_forecast` | `/api/cashflow/forecast`, `/api/cashflow/forecast/compact` |
| `centralized_reports` | `/api/projects/{project_id}/centralized-reports`, `/api/projects/{project_id}/centralized-reports/activities`, `/api/projects/{project_id}/centralized-reports/finance`, `/api/projects/{project_id}/centralized-reports/personnel` |
| `employee_dossier` | `/api/employee-dossier/{worker_id}` |
| `expected_actual` | `/api/projects/{project_id}/expected-actual`, `/api/projects/{project_id}/expected-actual/compact` |
| `financial_results` | `/api/projects/{project_id}/financial-results`, `/api/projects/{project_id}/financial-results/breakdown` |
| `full_cost` | `/api/employee-cost/{user_id}`, `/api/financial-alerts/{project_id}`, `/api/overhead-snapshots`, `/api/overhead-snapshots/aggregate`, `/api/project-net-profit/{project_id}`, `/api/project-risk/{project_id}` |
| `hr` | `/api/contract-payments` |
| `invoice_lines` | `/api/invoice-lines/by-project/{project_id}`, `/api/invoice-lines/by-purchaser/{user_id}`, `/api/invoice-lines/by-warehouse/{warehouse_id}`, `/api/invoice-lines/unallocated` |
| `overhead` | `/api/dashboard/stats` |
| `overhead_realtime` | `/api/fixed-expenses`, `/api/overhead/realtime`, `/api/overhead/realtime/by-project`, `/api/overhead/realtime/daily`, `/api/overhead/realtime/trend`, `/api/worker-calendar` |
| `pay_runs` | `/api/pay-runs`, `/api/pay-runs/audit-check`, `/api/pay-runs/{run_id}/allocations`, `/api/payroll-weeks` |
| `project_pnl` | `/api/org/pnl-overview`, `/api/projects/{project_id}/pnl/aggregated` |
| `reports` | `/api/finance/bonus-payments`, `/api/finance/cash-transactions`, `/api/finance/overhead-transactions`, `/api/prices`, `/api/reports/company-finance-export`, `/api/reports/company-finance-summary`, `/api/reports/turnover-by-client`, `/api/reports/turnover-by-counterparty`, `/api/reports/turnover-by-counterparty/{counterparty_id}/invoices` |
| `revenue_expense` | `/api/client-acts`, `/api/execution-packages`, `/api/labor-cost/by-project/{project_id}`, `/api/project-profit/{project_id}`, `/api/project-smr-view/{project_id}` |
| `revenue_snapshot` | `/api/cash-vs-earned/{project_id}`, `/api/procurement-alerts/{project_id}`, `/api/profit-by-period/{project_id}`, `/api/revenue-snapshots` |
| `weekly_matrix` | `/api/weekly-matrix` |

Освен това Viewer (без членство) стига до 230 GET endpoint-а с 200 — почти колкото Owner (291).

### 5.3. Endpoint-и без проверка на вход

22 endpoint-а нямат `get_current_user` в зависимостите. Повечето са справочници (`.../enums`, `/api/health`, `/api/version`, `/api/roles`). Отделно внимание заслужават:
* `POST /api/internal/run-reminder-jobs` — пуска фоновите напомняния, без вход и без друга проверка в кода (`app/routes/attendance.py:897`); отговори 200;
* `POST /api/billing/signup` — създава нова фирма (organization, user, tenant_registry, membership, role assignment, subscription); по дизайн е публичен;
* `POST /api/platform/bootstrap-create-platform-admin`, `POST /api/billing/webhook`, `GET|POST /api/offers/review/{review_token}...` — имат собствена защита (токен/подпис/състояние); в теста отговориха 422 / 503 / 404 и не записаха нищо.

## 6. Какво значи това за въпроса от стъпка 5

* „Existing layout expects `off`“ — на `main` `off`, `shadow` и `enforce` дават **едни и същи отговори**; изборът на режим **не отваря и не затваря** достъп за нито една от 8-те роли.
* „LIVE-OPS writes require `enforce`“ — **на `main` няма LIVE-OPS модул.** Той е само в клона `codex/integrated-rc-2026-10-25` (`backend/app/routes/live_ops.py`, само GET). Това изискване не може да бъде проверено на тази база; същият тест трябва да се пусне върху точния RC artifact.
* Нито един режим не решава проблемите от §5 — те са в ~680 endpoint-а, които не питат Permission Service.

## 7. Какво НЕ е проверено (граници на доказателството)

1. **Членство в проект** (`project_team`). Тестовите потребители не са членове на проекта; ролите с членство може да виждат повече. Не е мерено.
2. **Реалните данни на Synology.** ST-01 фирмите имат пълни TenantMembership/RoleAssignment и `database_name` = оперативната база. Дали реалната фирма ги има (backfill W0-03E-A2B) — не е проверено. Без тях `enforce` дава 403 на ~50 endpoint-а.
3. **`MASTER_DATA_MODE`** е оставен на стойността по подразбиране (`off`). Отделен флаг, извън PM-01.
4. **Кръстосан достъп A→B** — не е част от PM-01 (покрит е от ST-01 и W0-03E тестовете).
5. **Файлове (multipart)** — не се качват; тези endpoint-и отговарят 422, освен ако отказът е преди проверката на тялото.
6. **Празни данни.** 200 означава „пуснат“, не „видял чужди записи“. 404 с несъществуващо id не казва дали ролята би видяла истински запис.
7. Два endpoint-а връщат 500 с генерираното тяло (`POST /api/pay-runs`, `POST /api/overhead/snapshots/compute`) — еднакво във всички режими и роли; записано като факт, не е поправяно.
8. Startup hook-ът на сървъра не е пуснат (без демо данни, без reminder цикъл); индексите от него липсват.

## 8. Препоръка (решението е на Крум)

1. **За staging на `main`: `PERMISSION_SERVICE_MODE=shadow`.** Отговорите са идентични с `off` (доказано за всяка клетка), а логовете `PERMISSION_SHADOW_MISMATCH` показват на живо дали реалните потребители имат правилни RoleAssignment. Единственият допълнителен запис е RoleAssignment + AuditEvent при създаване на потребител — желан по FLOW-002. `off` също е безопасен, но не дава тази информация.
2. **`enforce` — само след доказателство на реалните данни**, че всеки активен потребител има TenantMembership и RoleAssignment (виж §7.2). Иначе някой ще загуби достъп до ~50 endpoint-а. Сам по себе си `enforce` на `main` не добавя защита извън одита на отказите.
3. **LIVE-OPS:** пуснете същия тест (`--harness`) върху точния RC artifact, преди да решите режима за него. На `main` изискването не съществува.
4. **Списъкът в §5** е отделно решение за Крум: кои от тези достъпи „болят в реални данни“. По правилата на проекта той се записва като дълг и не се поправя без потвърждение. Нито един режим не го решава — трябва миграция на endpoint-ите към Permission Service, по модул.

## 9. Как се повтаря

```bash
docker run -d --rm --name pm01mongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all
docker exec pm01mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
cd backend
# нов резултат в docs/evidence/PM-01/ (~3–4 минути):
PYTHONPATH=. python tests/test_pm_01_permission_matrix.py --harness \
    --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
# регресия: пълно ново пускане трябва да съвпадне клетка по клетка с commit-натото
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
    PYTHONPATH=. pytest tests/test_pm_01_permission_matrix.py -v --noconftest
```

Тестовете без база проверяват, че матрицата покрива точно днешните endpoint-и (нов или махнат endpoint → тестът пада, докато матрицата и този отчет не се обновят), че `shadow` отговаря като `off`, и че `enforce` се различава само по одит/синхронизация на ролята.

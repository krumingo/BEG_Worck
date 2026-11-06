# SEC-01-C01 — всички записи по финансовите ресурси + Р16

> Пакет: `docs/architecture/tasks/SEC-01-C01_ALL_WRITES_ON_MONEY_RESOURCES.md` (клон `claude/happy-meitner-bmcnel`), одобрен от Крум 06.11.2026 (Р14, Р16 — `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`).
> Одит: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log`, запис #69 (SEC-S1, SEC-S2).
> FLOW-002 (роли/права), W0-02 Permission Service. FLOW-006 не е засегнат: тук няма плащане, само кой може да пише.
> База: PR #69 @ `e6c0e46`. Само нови commit-и.

## Пълен списък на write route-овете по 8-те ресурса

Търсено е по колекциите (`grep` за `insert/update/delete/replace` върху `cash_transactions`, `overhead_transactions`, `bonus_payments`, `overhead_snapshots`, `price_modifiers_config`, `labor_entries`, `material_waste_entries` и полетата `owner_type`/`owner_id` на `projects`), не само по URL.

| # | Route | Файл:ред | Колекция | Правило | Действие | Статус |
|---|---|---|---|---|---|---|
| 1 | `POST /api/finance/cash-transactions` | `routes/reports.py:941` | cash_transactions | О/А/Сч | `finance.cash_transaction.create` | SEC-01 |
| 2 | `POST /api/finance/overhead-transactions` | `routes/reports.py:997` | overhead_transactions | О/А/Сч | `finance.overhead_transaction.create` | SEC-01 |
| 3 | `POST /api/finance/bonus-payments` | `routes/reports.py:1052` | bonus_payments | О/А/Сч | `finance.bonus_payment.create` | SEC-01 |
| 4 | `POST /api/overhead-snapshots` | `routes/full_cost.py:106` | overhead_snapshots | О/А/Сч | `finance.overhead_snapshot.create` | SEC-01 |
| 5 | `POST /api/overhead/snapshots/compute` | `routes/overhead.py:316` | overhead_snapshots | О/А/Сч (същото като досегашното `check_overhead_access(write=True)`) | `finance.overhead_snapshot_compute.execute` | **C01 нов** |
| 6 | `PUT /api/price-modifiers/org` | `routes/price_modifiers.py:52` | price_modifiers_config | **само О/А** (досегашното правило в handler-а) | `pricing.org_modifier.update` | **C01 нов** |
| 7 | `PUT /api/price-modifiers/project/{id}` | `routes/price_modifiers.py:99` | price_modifiers_config | О/А/Сч | `pricing.project_modifier.update` | SEC-01 |
| 8 | `DELETE /api/price-modifiers/project/{id}` | `routes/price_modifiers.py:132` | price_modifiers_config | **отказ за всички**: О/А/Сч → 409, другите → 403; нищо не се трие | `pricing.project_modifier.delete` | **C01 нов (SEC-S1)** |
| 9 | `PATCH /api/projects/{id}/client-link` | `routes/clients.py:696` | projects.owner_* | О/А/Сч | `project.client_link.update` | SEC-01 |
| 10 | `PUT /api/projects/{id}` — **само ако** `owner_type`/`owner_id` се сменят | `routes/projects.py:260` (проверка :273) | projects.owner_* | досегашното `can_manage_project` **и** О/А/Сч → на практика О/А | `project.client_link.update` | **C01 нов** |
| 11 | `POST /api/projects` — **само ако** има `owner_type`/`owner_id` | `routes/projects.py:166` (проверка :175) | projects.owner_* | досегашното (О/А/SiteManager) **и** О/А/Сч → на практика О/А | `project.client_link.update` | **C01 нов** |
| 12 | `POST /api/labor-entries` | `routes/labor_smr.py:33` | labor_entries | **Р16** | `labor.entry.create` | SEC-01 → Р16 |
| 13 | `POST /api/labor-entries/sync-from-work-reports` | `routes/labor_smr.py:74` | labor_entries (delete_many + insert) | **Р16** | `labor.work_report_sync.execute` | **C01 нов (SEC-S2)** |
| 14 | `POST /api/execution-packages/recompute-labor/{id}` | `routes/labor_smr.py:174` | execution_packages (кеш на труда) | **Р16** | `labor.package_recompute.execute` | **C01 нов** |
| 15 | `POST /api/projects/{id}/material-waste` | `routes/material_waste.py:58` | material_waste_entries | **Р16** | `material_waste.entry.create` | SEC-01 → Р16 |

**Р16:** Owner/Admin/Accountant — навсякъде; SiteManager и Technician — само за обект, на който са членове (`project_team`, както `can_access_project`); Viewer, Driver и всички други — 403, дори да са членове.

**Не са пипани (по пакета / извън ресурсите):**
- `POST /api/execution-packages/recompute-material/{id}`, `POST /api/material-entries/sync/{id}` (`routes/material_smr.py`) — PR #55. Следваща задача: същото Р16 правило.
- `POST /projects/{id}/create-sub-project`, `/wrap-in-group`, `/projects/{group_id}/add-subproject` (`routes/projects.py:1505/1721/1819`) — **копират** клиента на родителя в новия подобект; не избират нов клиент. Не са охранени. Ако Крум иска и тях — една проверка.
- `POST /api/overhead-allocation/compute/{id}` (`routes/full_cost.py`) — само **чете** labor_entries/overhead_*; пише `project_overhead_alloc`/`execution_packages`. Извън 8-те ресурса.
- `POST /api/smr-analyses/{id}/recalculate-with-modifiers` — само чете модификаторите; пише `smr_analyses`.

## Как работи

`backend/app/permissions/money_write.py`:
- `require_money_write(action, roles=...)` — същата зависимост от SEC-01; `roles` позволява досегашното тясно правило О/А (#6).
- `require_field_cost_write(action, project_from="path"|"body")` — Р16. Същият W0-02 `require_permission`:
  - `off`/`shadow`: legacy проверка — финансова роля, или SiteManager/Technician **и** `project_team.is_member` в собствената фирма на потребителя (от сървъра, не от заявката);
  - `enforce`: решава само Permission Service със scope `project`. Фирмена роля (Accountant/Owner/Admin) покрива всеки обект. SiteManager/Technician имат действието **само** в проектното назначение, което огледално следва членството (`catalog.project_membership_actions`, ползвано от `permissions/sync.py` и `scripts/w0_02_bootstrap_permissions.py`). Отказ → 403 + AuditEvent.
- `check_money_write(...)` — същото решение, извикано в handler-а преди записа (#10, #11).
- `app/permissions/deps.py`: `require_permission` получава `scope_id_getter` (project_id от JSON тялото). Без него — поведението е непроменено.

## Резултат (реална MongoDB 7.0 replica set, ST-01 фирми A и B + съществуващи записи)

`results.json` — 1383 извиквания: 17 проби × 8 роли × 2 фирми × (P1 и P2 за проектните) × 3 режима + B→A. Записът се мери от oplog-а, с `org_id` на всеки записан ред.

Съществуващи записи (`seed_existing_records` в PM-01 harness-а): втори обект P2 без членове; членове на P1 — SiteManager, Technician, **Viewer и Driver** (добавени през реалния API в enforce, за да има и огледалните назначения); два клиента; модификатори на фирма и на P1; одобрен работен отчет и пакет на P1; ставка; по един ред във всяка финансова колекция.

| | off | shadow | enforce |
|---|---|---|---|
| Позволена роля | 200/201, пише само бизнес колекцията, **само във фирмата на извикващия** | същото | същото |
| Отказана роля | **403, нищо не е записано** | **403, нищо** | **403**, единственият запис е `audit_events` |
| DELETE модификатор, О/А/Сч | **409, нищо** | 409, нищо | 409, нищо |
| Р16: SiteManager/Technician на P1 (член) | 201/200 | същото | същото |
| Р16: SiteManager/Technician на P2 (не член) | 403 | 403 | 403 (+AuditEvent) |
| Р16: Viewer/Driver на P1 (членове) | 403 | 403 | 403 (+AuditEvent) |
| B → P1 на A, SiteManager/Technician/Viewer | 403 | 403 | 403 |

Статусът е еднакъв в трите режима за всяка клетка. Одит находките: SEC-S1 (Viewer DELETE) → 403, нищо не е изтрито; SEC-S2 (Viewer sync) → 403, нищо не е записано.

## PM-01 матрицата

Генерирана отново. Променени са точно **65 клетки**, всички на петте нови route-а (#5, #6, #8, #13, #14), всички към 403/409 без бизнес запис (`pm01_cells_changed.csv`). Никоя друга клетка не е променена.

## Дълг (записан, не е поправян — CLAUDE.md §18)

- **SEC-01-D1** (от SEC-01, остава): `PUT price-modifiers/project`, `POST material-waste` и `POST labor-entries` не проверяват, че обектът е на фирмата. Accountant на B с id на обект на A → записът е във **фирма B**; A не е записана.
- **SEC-01-C01-D2:** ценовите модификатори на обект нямат модел за архив/версия → „нулиране към фирмените“ е невъзможно (DELETE е отказан). Frontend-ът не вика DELETE.
- **SEC-01-C01-D3:** `sync-from-work-reports` прави `delete_many` на старите синхронизирани редове труд (hard delete на производни редове) и ги създава наново. Логиката не е променена.
- **SEC-01-C01-D4 (внедряване):** в `enforce` SiteManager/Technician получават Р16 правата от проектните назначения. Вече съществуващите назначения ги получават при следващата синхронизация на членството (добавяне/премахване), не автоматично; до тогава в enforce им се отказва (по-безопасната посока). Преди enforce в реална среда е нужна стъпка за обновяване на назначенията.
- **Бизнес ефект за Крум:** SiteManager вече **не може** да създаде обект с клиент или да смени клиента през `PUT /projects` (досега можеше). Без клиент — както преди.

## Как се повтаря

```bash
docker run -d --rm --name c01smongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all
docker exec c01smongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
cd backend
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
    PYTHONPATH=. pytest --noconftest tests/test_sec_01_c01_all_money_writes.py \
    tests/test_sec_01_money_write_permissions.py tests/test_pm_01_permission_matrix.py
```

## Връщане назад

Revert на commit-а на SEC-01-C01. Няма миграция и няма промяна на данни. Проектните назначения, обновени при синхронизация, съдържат допълнителни действия, които след revert не се ползват от никой route.

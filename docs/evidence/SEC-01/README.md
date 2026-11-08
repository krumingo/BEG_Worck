# SEC-01 — финансовите записи само за финансовите роли (Р14)

> Пакет: `docs/architecture/tasks/SEC-01_MONEY_WRITE_PERMISSIONS.md` (клон `claude/happy-meitner-bmcnel`), одобрен от Крум 06.11.2026 (Р14).
> Доказателство за дупката: `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md` §5.1.
> FLOW-002 (роли/права), W0-02 Permission Service. FLOW-006 (Payment ledger) **не е засегнат** — тук няма плащане, само кой може да пише.
> База: `main` @ `07da9ab` + merge на `claude/pm-01-permission-matrix` (PR #68, чист: 4 нови файла, същата база) за генератора на матрицата.

## Какво е направено

1. `backend/app/permissions/money_write.py` — една зависимост `require_money_write(action, module, resource_type)`:
   * това е съществуващият механизъм `require_permission` (`app/permissions/deps.py`) с legacy проверка `role ∈ {Admin, Owner, Accountant}`;
   * `off` — само legacy проверка; `shadow` — legacy решава, каталогът се оценява паралелно; `enforce` — решава само Permission Service; отказ → 403 + AuditEvent „отказан достъп“ (по дизайна на W0-02);
   * в `enforce` — същата защита като `require_admin` (`app/deps/auth.py:59-87`): ако базата на активния tenant не е legacy базата или org-ът на потребителя не е активният tenant → 409 преди всякакъв запис;
   * декларирана е **преди** модулната (абонаментна) зависимост → отказаната роля не стига до никакво четене.
2. `backend/app/permissions/catalog.py` — 8 нови действия (по едно на endpoint), дадени само на `accountant` (Owner/Admin ги имат чрез пълния си набор). Никоя друга роля (вкл. `office`, `site_manager`, `LEGACY_*`) не ги получава.
3. 8 endpoint-а получават зависимостта. Тялото на handler-ите **не е променено**.

## Правило по endpoint и откъде е взето

| Endpoint | Файл:ред (SEC-01) | Действие | Правило | Източник на правилото |
|---|---|---|---|---|
| `POST /api/finance/cash-transactions` | `routes/reports.py:944` | `finance.cash_transaction.create` | Owner/Admin/Accountant | По подразбиране от пакета. В `reports.py` няма друго правило (всички съседи — само `require_m5`); финансовото правило на системата: `routes/finance.py:36-38` `finance_permission` |
| `POST /api/finance/bonus-payments` | `routes/reports.py:1055` | `finance.bonus_payment.create` | Owner/Admin/Accountant | същото |
| `POST /api/finance/overhead-transactions` | `routes/reports.py:1000` | `finance.overhead_transaction.create` | Owner/Admin/Accountant | същото + `routes/overhead.py:36-41` `check_overhead_access(write=True)` |
| `POST /api/overhead-snapshots` | `routes/full_cost.py:109` | `finance.overhead_snapshot.create` | Owner/Admin/Accountant | `routes/overhead.py:36-41` (запис в режийни = Admin/Owner/Accountant). Виж бележка 1 |
| `PUT /api/price-modifiers/project/{project_id}` | `routes/price_modifiers.py:97` | `pricing.project_modifier.update` | Owner/Admin/Accountant | По подразбиране от пакета; съседите на ниво обект (`GET`/`DELETE …/project/{id}`) нямат правило. Виж бележка 1 |
| `POST /api/labor-entries` | `routes/labor_smr.py:36` | `labor.entry.create` | Owner/Admin/Accountant | По подразбиране; съседите в `labor_smr.py` (`sync-from-work-reports`, `recompute-labor`) нямат правило — няма утвърдено SiteManager правило в модула |
| `POST /api/projects/{project_id}/material-waste` | `routes/material_waste.py:62` | `material_waste.entry.create` | Owner/Admin/Accountant | По подразбиране; съседите в `material_waste.py` са само GET без правило |
| `PATCH /api/projects/{project_id}/client-link` | `routes/clients.py:700` | `project.client_link.update` | Owner/Admin/Accountant | Същият модул: `routes/clients.py:27-29` `finance_permission`, ползван от `POST/PUT/DELETE /api/clients` (`:177`, `:243`, `:282`) |

**Бележка 1 (за Крум, не е променяно):** в `full_cost.py:84` (`PUT /api/employee-cost-config`) и `price_modifiers.py:55` (`PUT /api/price-modifiers/org`) има по-тясно правило **само Admin/Owner**. Те са за друг ресурс (ставки на служители / фирмени модификатори), затова не са приети за „утвърдено правило“ на тези два endpoint-а и е приложено правилото от пакета (Owner/Admin/Accountant). Ако Крум иска Accountant да не пипа режийни snapshot-и или модификатори на обект — това е една промяна в каталога и legacy проверката.

## Резултат (реална MongoDB 7.0 replica set, ST-01 фирми A и B)

`results.json` — 402 извиквания: 8 endpoint-а × 8 роли × 2 фирми × 3 режима + кръстосани B→A. Записът се мери от oplog-а, не от отговора.

| | off | shadow | enforce |
|---|---|---|---|
| Owner / Admin / Accountant (своя фирма) | 200/201, записва точно бизнес колекцията, `org_id` = своята фирма | същото | същото |
| SiteManager / Technician / Warehousekeeper / Driver / Viewer | **403, нищо не е записано** | **403, нищо не е записано** | **403**, единственият запис е `audit_events` (отказ, по дизайна на W0-02) |
| B → проект на A, `client-link` (Accountant) | 404, нищо | 404, нищо | 404, нищо |
| B → проект на A, Viewer | 403 | 403 | 403 (+ AuditEvent) |

Статусът е еднакъв в трите режима за всяка клетка.

**Дълг SEC-01-D1 (не е поправян, извън обхвата):** `PUT /api/price-modifiers/project/{project_id}` и `POST /api/projects/{project_id}/material-waste` не проверяват, че обектът е на фирмата на потребителя. Accountant на B с id на обект на A получава 200/201; записът отива **във фирма B** (`org_id` = B), фирма A не е записана. Записано като дълг по CLAUDE.md §18 — Крум решава.

## PM-01 матрицата след SEC-01

`docs/evidence/PM-01/matrix.csv` е генерирана отново (всичките 752 endpoint-а × 8 роли × 3 режима). `pm01_cells_closed.csv` — всяка клетка, която се е променила спрямо матрицата на PR #68. Виж секцията „Промяна в PM-01“ в HANDOFF.

## Как се повтаря

```bash
docker run -d --rm --name sec01mongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all
docker exec sec01mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
cd backend
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
    PYTHONPATH=. pytest tests/test_sec_01_money_write_permissions.py tests/test_pm_01_permission_matrix.py -v --noconftest
```

## Връщане назад

Revert на commit-а на SEC-01. Няма миграция и няма промяна на данни — само кой получава 403.

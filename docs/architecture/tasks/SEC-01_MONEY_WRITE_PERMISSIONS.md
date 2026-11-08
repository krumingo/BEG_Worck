# SEC-01 — финансовите записи само за финансовите роли (Р14)

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026: Р14, записано в `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`). Без merge/deploy/данни. **Codex: да** (пари + сигурност), след вътрешния одит.
> Източник: `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md` §5.1 @ клон `claude/pm-01-permission-matrix` (PR #68) — доказано с real-Mongo матрица: Viewer/Driver/Technician/Warehousekeeper **записват** в каса, бонуси, режийни и др. (пример: `POST /api/finance/cash-transactions` има само `require_m5`, `backend/app/routes/reports.py:940`).
> База: `main` @ `07da9ab` · Клон `claude/sec-01-money-write-permissions` → Draft PR

## Обхват (само финансови записи от §5.1)
| Endpoint | Файл |
|---|---|
| `POST /api/finance/cash-transactions` | `routes/reports.py` |
| `POST /api/finance/bonus-payments` | `routes/reports.py` |
| `POST /api/finance/overhead-transactions` | `routes/reports.py` |
| `POST /api/overhead-snapshots` | `routes/full_cost.py` |
| `PUT /api/price-modifiers/project/{project_id}` | `routes/price_modifiers.py` |
| `POST /api/labor-entries` (труд = разход) | `routes/labor_smr.py` |
| `POST /api/projects/{project_id}/material-waste` (разход) | `routes/material_waste.py` |
| `PATCH /api/projects/{project_id}/client-link` (кой плаща) | `routes/clients.py` |
- Правило: **само Owner/Admin/Accountant**, освен ако съседните endpoint-и в **същия модул** вече имат друго утвърдено правило (напр. SiteManager за труд на своя обект) — тогава същото. За всеки endpoint в HANDOFF: кое правило, откъде е взето (файл:ред).
- Проверката е в същия стил като съществуващите (legacy role check в off/shadow + `require_permission` с каталожно действие, ако има такова), **преди** всякакво четене/запис. Отказ → 403, нищо не е записано.
- Каталогът `app/permissions/catalog.py`: ако липсва действие, се добавя минимално и по FLOW-002, без да се отваря достъп на други места.
## Забранено
Промяна на други endpoint-и (останалите от §5.1 и четенето §5.2 са следваща задача), промяна на бизнес правила извън правата, production, merge/deploy.
## Тестове
За всеки endpoint: Owner/Admin/Accountant → 201/200; Viewer/Driver/Technician/Warehousekeeper/SiteManager (според правилото) → 403 и **нищо не е записано** (по колекции); off/shadow/enforce еднакво; две фирми. PM-01 матрицата се пуска отново и показва, че тези клетки са затворени. Всички `tests/test_r0_0*.py`, W0 1085/15/50, A2C/A1 0.
## Предаване
`HANDOFF SEC-01` в PR-а; съобщение `SEC-01 DONE pr=<n> head=<sha> tests=<summary>`.

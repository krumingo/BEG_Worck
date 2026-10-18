# R0-07 — dev reset само в dev/test (AUD-039)

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (Sonnet е достатъчен) · Ревю: Codex · Решение: Крум
> Находка: AUD-039 · FLOW-043 (среди/release), правило „няма hard delete на използвани записи“ (CLAUDE.md §2.9)
> База: `main` @ `23f223ef40f93801e2dfbfb2b67b6c5c704820a0` (след merge на R0-06)
> Клон: `claude/r0-07-dev-reset` → Draft PR към `main`

## Какво е сега (проверено в main @ 23f223e)

- `backend/app/routes/warehouses.py:290-330`: `POST /api/dev/reset-warehouses` изтрива всички складове на фирмата. Съществуващата защита работи по склад: в `MASTER_DATA_MODE=enforce` използваните се архивират, а в `off`/`shadow` се трият.
- **Защитата за production е обратна (fail-open).** Маршрутът се блокира само ако `ENVIRONMENT == "production"`, а по подразбиране е `"development"`. `ENVIRONMENT` не се ползва никъде другаде в кода. Billing (R0-01) използва `ENV` с изричен списък от разрешени среди.
- Следствие: на сървър без `ENVIRONMENT=production` всеки Admin/Owner/SiteManager/Warehousekeeper може да изтрие складовете на фирмата си.
- Frontend-ът не вика този маршрут (`frontend/src` няма препратка).
- Няма други `/dev/*` маршрути в `backend/app`.

## Обхват

1. **Fail-closed среда.** Маршрутът работи **само** когато `ENV` е изрично `development` или `test`. Ползва се същата променлива и същият подход като `is_mock_billing_allowed()` в `app/core/stripe_config.py`; общ малък helper, ако е удобно. При липсваща, празна или всяка друга стойност (вкл. `production`, `staging`) → **404**, все едно маршрутът го няма. Нищо не се чете и не се пише. `ENVIRONMENT` престава да се ползва тук.
   - По избор, ако е чисто: маршрутът изобщо не се регистрира извън dev/test. Code избира и обосновава. Поведението навън и в двата случая е 404.
2. **Права.** Само Admin/Owner, вместо всички с `warehouse_permission`. В dev/test останалите роли → 403.
3. **Без hard delete на използвани записи.** Съществуващата логика `guarded_identity_delete` остава. Code проверява и описва какво става в `off`/`shadow`: ако там се трие склад с наличности или движения, описва го като дълг. Само ако корекцията е малка и в същия файл, архивира вместо да трие и описва решението. Business правилата за склада не се променят.
4. Записва се дълг (без поправка): production сървърът трябва да има `ENV=production` или да няма `ENV`. Проверката е част от R0-08 (production read-only).

## Забранено
- Промени в други маршрути, в правилата на склада, в UI, миграции, production, merge, deploy.
- Не се добавят нови `/dev/*` маршрути.

## Тестове (положителни + забранени)

| # | Случай | Очаквано |
|---|---|---|
| 1 | `ENV` липсва | 404, складовете непроменени (побайтово) |
| 2 | `ENV=production` / `staging` / `prod` / празно / случайна стойност | 404, нищо не се пише |
| 3 | `ENVIRONMENT=development` и **без** `ENV` (старият байпас) | 404 |
| 4 | `ENV=development` / `test`, Admin или Owner | работи, както досега (по склад, през guard-а) |
| 5 | `ENV=test`, SiteManager / Warehousekeeper / Technician | 403, нищо не се пише |
| 6 | Две фирми: reset на A не пипа складовете на B | изолация |
| 7 | Mutation: тестове 1–3 и 5 падат върху `main` | доказва поправката |

Тестове на mongomock и реален MongoDB. W0 DB-free: 1085 / 15 / 50 със същите 15 паднали като на main. A2C и A1 guard-ове: 0 нарушения.

## Тест на живо с бот (задължителен, кратък)
Локален backend с MongoDB в Docker, две пускания:
1. `ENV` не е зададен. Ботът влиза като Admin и праща `POST /api/dev/reset-warehouses` от сесията. Отговорът е 404, а списъкът складове в UI е непроменен (скрийншот).
2. `ENV=test`. Същото като Admin: работи; като Warehousekeeper: 403.

Скрийншоти и JSON в `docs/evidence/R0-07/`.

## Предаване
- Draft PR: `R0-07 — dev reset only in dev/test (AUD-039)`. Описание: base/head SHA, файлове, точни резултати, бот тест, какво не е пуснато, дълг.
- Съобщение до оркестратора: `R0-07 DONE pr=<n> head=<sha> tests=<summary> bot=<pass/fail>` или `R0-07 BLOCKED <reason>`.

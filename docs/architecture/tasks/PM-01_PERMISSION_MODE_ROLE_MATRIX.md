# PM-01 — доказателство: всички роли в PERMISSION_SERVICE_MODE off / shadow / enforce

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Само тестове и отчет — **без промяна на бизнес код, без смяна на флаг в production**. Codex: **да** (сигурност), след вътрешния одит.
> Източник: PR #64 `02-release-gates.md` стъпка 5: „Existing layout expects `PERMISSION_SERVICE_MODE=off`; LIVE-OPS writes require `enforce`. Resolve this explicitly with tested roles before building.“
> База: `main` @ `07da9ab` · Клон `claude/pm-01-permission-matrix` → Draft PR · Нови файлове само `backend/tests/test_pm_01_*.py`, `docs/evidence/PM-01/`, `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md`.

## Цел
Решението „кой режим ползваме на Synology“ е на Крум. PM-01 му дава факти: за всяка роля (Owner, Admin, SiteManager, Technician, Accountant, Warehousekeeper, Driver, Viewer) × всеки публичен endpoint в `backend/artifacts/endpoints_inventory.csv` (или актуалния инвентар) × режим (off, shadow, enforce) — позволено/отказано, и **разлики между режимите**.

## Обхват
1. Генериран тест (real Mongo, ST-01 фикстурите от `ops/staging/` за двете фирми) който вика всеки endpoint като всяка роля във всеки режим и записва резултата (статус, дали е писано нещо).
2. Отчет `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md` на прост български: таблица по модули; списък **„в enforce някой губи достъп, който има днес“** и **„в off някой има достъп, който не трябва“**; никакви промени, само факти и препоръка.
3. Тестовете, които доказват текущото поведение, остават като регресия (не се маркират xfail).

## Забранено
Промяна на права, роли, флагове, бизнес код; production; merge/deploy.

## Проверки и предаване
Новите тестове, всички `tests/test_r0_0*.py`, W0 1085/15/50, A2C/A1 0. `HANDOFF PM-01` в PR-а; съобщение `PM-01 DONE pr=<n> head=<sha> tests=<summary>`.

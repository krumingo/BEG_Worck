# ST-01 — изолирани тестови данни и сценарии за staging (без пари и сигурност в обхвата → вътрешен одит)

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026: „не спирай да програмираш“, Р9). Без merge/deploy без „да“.
> Изпълнител: Claude Code · Одит: Claude Audit · Бот: Claude Bot · Codex: **не** (не пипа пари/сигурност — само тестови данни)
> Източник: PR #64 `02-release-gates.md`, стъпки 6–7 и таблицата „Krum's acceptance scenarios“.
> База: `main` @ `c0e34e1` · Клон: `claude/st-01-staging-fixtures` → Draft PR · Нови файлове само в `ops/staging/` и `backend/tests/test_st_01_*.py` (без пипане на `ops/release/` — там работи RC-01).

## Обхват
1. `ops/staging/seed_synthetic.py`: създава **само в изрично посочена локална/staging база** (отказва production и всяка нелокална цел без флаг, както R0-03 duplicates report) два tenant-а **A** и **B** и потребители за всички роли от release gates: Owner, Admin, requester, approver, denied, Warehousekeeper, Technician, Accountant, Viewer, Driver. Парoлите идват от env/prompt, никога в Git. Идемпотентно (повторно пускане не дублира).
2. `ops/staging/scenarios/`: машинно четим списък (YAML/JSON) на сценариите на Крум от таблицата — всеки с id, роля, стъпки, очакван резултат, кой FLOW покрива и **статус „няма екран/канонична функция“**, когато функцията липсва (не се маркира като минал).
3. `ops/staging/run_scenarios.py`: изпълнява API частта на сценариите срещу локален backend и пише `result.json` (pass/fail/blocked + причина). Браузърната част прави Bot сесията по същия списък.
4. README с точните команди.

## Забранено
Production/Synology, реални данни, тайни в Git, промени в бизнес кода (само скриптове и тестове), промени в `ops/release/`.

## Тестове
`tests/test_st_01_*.py`: seed е идемпотентен; отказва нелокална цел; създава точно ролите; A и B не виждат взаимно записите си през API; runner маркира липсващ екран като `blocked`, не `pass`. Плюс всички `tests/test_r0_0*.py` зелени, W0 DB-free 1085/15/50, A2C/A1 0.

## Предаване
Draft PR `ST-01 — staging synthetic fixtures and scenario runner`, `HANDOFF ST-01`, съобщение `ST-01 DONE pr=<n> head=<sha> tests=<summary>`.

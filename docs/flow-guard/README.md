# FLOW GUARD

Сесия, поискана от Крум на 06.11.2026. Сравнява програмирания код със заключения FLOW канон и записва всяко разминаване. Не програмира функции, не merge-ва, не deploy-ва и не пипа FLOW файлове.

Канон по старшинство:

1. `docs/flows/FLOW-*.md`; при конфликт печели FLOW-043 (CLAUDE.md §18).
2. Решенията на Крум Р1..Р16 в `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md` (клон `claude/happy-meitner-bmcnel`).
3. `CLAUDE.md`.
4. Task пакетите в `docs/architecture/tasks/*.md` (същия клон).

Файлове:

- `STATE.md` — последен проверен SHA по клон/PR.
- `DIVERGENCES.md` — всички находки FG-n.
- `COVERAGE.md` — бавен преглед на main, по един FLOW на проход.

Доказателства:

- **PROVEN** — показано с тест или проба на реален MongoDB 7 (replica set, локален контейнер, бази `fg*`, изтрити след пробата).
- **SUSPECTED** — само от четене на кода.

Пробите от FLOW GUARD са в `docs/flow-guard/probes/`. Пускат се от `backend/` с `PYTHONPATH=.`; виж docstring-а на всяка проба.

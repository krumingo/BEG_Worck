# 5C-C22 — склад (PR #55): всички финансови отчети от един източник + деление по дата на прехода (Р13)

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026: Р9, Р13 — записано в `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`). Без merge/deploy/данни.
> Изпълнител: Claude Code (Opus) · Одит · Бот · Codex след чист бот (пари)
> PR: #55 — започва **след** HANDOFF 5C-C21. Вътрешен одит на c0b3b4c: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log` ee94c6c и коментарът в PR #55.

## Находки (одит, доказани с probe)
- `project_financial_results` paid_materials = 0; `centralized_reports` total_materials = 0 (100 при legacy, докато P&L казва 30); `revenue_snapshot` profit-by-period material = 0. Същият модел вероятно в `material_waste`, `pulse_generator`, `materials_baseline` — проверяват се всички.
- P&L при смесена история изпуска целия legacy разход, щом има каноничен ред.

## Обхват
1. **Един общ helper** за материален разход по обект/пакет/период (един source of truth), ползван от **всички** финансови отчети и екрани: P&L, summary/breakdown, project_financial_results, centralized_reports, revenue_snapshot, material_waste, pulse_generator, materials_baseline, package financial/breakdown/net, project-profit, net-profit.
2. **Правило Р13 — дата на прехода:** за всеки tenant се записва момент на прехода към каноничния склад (първото canonical движение или изрично зададена дата — Code описва и обосновава кое е по канона; без миграция на реални данни). Legacy редове **преди** прехода се броят; след него — само каноничните. Тест: 100 legacy (преди) + 30 canonical (след) = 130 навсякъде; legacy ред **след** прехода не се брои два пъти.
3. Фирата (Р10, C21) влиза в същия helper.

## Тестове
Real Mongo, падат на текущия head: всеки отчет показва едно и също число за един и същ сценарий (30; 130 при смесена история; фира включена). Всички досегашни gate-ове.

## Предаване
`HANDOFF 5C-C22` в PR #55; съобщение `5C-C22 DONE head=<sha> tests=<summary>`.

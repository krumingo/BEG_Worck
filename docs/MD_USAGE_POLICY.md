# BEG_WORK — Правила за използване на `.md` файловете

> Статус: задължителна repository policy за GPT, Codex и Claude.
> Каноничен клон за coordination state: `codex/claude-queue`.
> Този документ определя **как се намира** истината; не замества FLOW, архитектурните решения или live control state.

## 1. Основен принцип

GitHub е общата памет на проекта. `.md` файловете не са еднакво важни: никой агент не приема случаен стар документ за актуална истина. Ролята, местоположението и актуалността на документа определят как се използва. **Не се четат всички `.md` файлове механично преди всяка задача.**

## 2. Ред на четене при нова задача

Преди implementation, review или архитектурно решение чети в този ред:

1. [`coordination/DECISIONS_INDEX.md`](../coordination/DECISIONS_INDEX.md) — навигация, не втори source of truth;
2. [`CLAUDE.md`](../CLAUDE.md);
3. [`coordination/README.md`](../coordination/README.md);
4. [`coordination/ACTIVE.md`](../coordination/ACTIVE.md) — само текущото assignment;
5. [`coordination/CONTROL_STATE.json`](../coordination/CONTROL_STATE.json) — live state, re-check преди consequential action;
6. съответния [`FLOW-xxx.md`](flows/README.md);
7. свързаните архитектурни документи, посочени от индекса;
8. съответния предишен [`coordination/REVIEWS/`](../coordination/REVIEWS/), ако има;
9. actual code и пълния релевантен diff.

Чети само относимите FLOW и архитектурни документи. Не започвай работа само по chat текст, ако GitHub съдържа по-ново канонично решение. При липсващ документ или неразрешим конфликт спри и поискай решение; не запълвай празнината с предположение.

## 3. Йерархия при противоречие

1. Ново изрично решение на Крум;
2. каноничен FLOW или архитектурен decision документ;
3. `IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `TENANCY_MODEL.md`;
4. `coordination/ACTIVE.md` и `CONTROL_STATE.json` за текущото изпълнение;
5. independent review evidence;
6. README и operational instructions;
7. historical, recovery и memory файлове.

Новото решение на Крум се записва в правилния каноничен документ; до тогава не се приема за надеждно предадено на останалите агенти. Стар документ никога не отменя по-ново канонично решение. При неразрешим конфликт: `BLOCKED` и решение от Крум. `CONTROL_BOARD.md` е проекция на `CONTROL_STATE.json`, а не конкурентен източник.

## 4. Роли на документите

| Група | Роля и правило за употреба |
|---|---|
| A. `docs/flows/FLOW-001.md` … `FLOW-050.md` | Business requirements: поведение, бизнес правила, зависимости и забрани. Implementation не ги променя имплицитно; ако кодът противоречи на FLOW, кодът е проблемът, освен ако Крум изрично е променил решението. |
| B. `docs/flows/FLOW-043.md` | Cross-FLOW architectural decision register D-01…D-15. Чети при tenancy, finance, audit, approvals, identity, schedule, files, integrations и cross-module relations. |
| C. `docs/architecture/IMPLEMENTATION_WAVES.md` | Каноничен ред на изпълнение, зависимости и Wave 0–4. Агент не прескача реда сам. |
| D. `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` | PASS, blockers, prerequisites и gates. `PR merged ≠ Implementation Gate PASS`; преминали тестове сами не завършват целия FLOW. |
| E. `docs/architecture/TENANCY_MODEL.md` | Канон за tenant isolation. Чети при API, DB, files, search, jobs, permissions, finance, integrations, AI и migration. Никакво cross-tenant leakage. |
| F. `docs/architecture/*DECISION*.md` и други изрично посочени decision документи | Тематични архитектурни решения; чети относимия документ преди coding. |
| G. `docs/architecture/*BUSINESS_CLOSE*.md` | История/доказателство за business closure; текущият business source остава каноничният FLOW. |
| H. `docs/architecture/W0-*.md` | Implementation contracts, inventories, readiness и migration за конкретна W0 задача. Чети само при релевантност или изрична dependency. |
| I. `coordination/DECISIONS_INDEX.md` | Първа навигационна точка: „за тази тема истината е тук“. Не е втори source of truth. |
| J. `coordination/ACTIVE.md` | Текущо assignment; старите секции са история/evidence. Работи само по текущите Task-ID/Cycle-ID. |
| K. `coordination/CONTROL_STATE.json` | Machine-readable current agent, cycle, state, next agent, waiting_for, exact SHA, PR и dispatch state. Re-check live преди consequential action. |
| L. `coordination/CONTROL_BOARD.md` | Management projection на control state. При разминаване маркирай stale/conflict; не избирай удобната стойност. |
| M. `coordination/REVIEWS/*.md` | Независими Codex review доказателства: дефекти, verdict, тестове и exact SHA. Нов correction cycle чете предишния review; стар verdict не се пренаписва. |
| N. `coordination/FORECAST.md/.json` | Projection, не contractual truth и не implementation PASS. ACTIVE/control state имат предимство. |
| O. `docs/ops/*.md`, `ops/**/README*.md` | Operational instructions и доказателства за deploy, backup, restore, incidents, NAS и release. Чети преди production/NAS/deploy/restore; не действай само по обща архитектура. |
| P. `docs/project-recovery/**` | Historical recovery/provenance; не е текущ канон при наличен по-нов FLOW/architecture документ. |
| Q. `memory/*.md` | Legacy/project memory — допълнителен контекст, който не отменя FLOW, architecture, current implementation contract или ACTIVE/control. Връщане към канона изисква пренасяне в правилния документ. |
| R. root, frontend и backend `README.md` | Setup, структура и локално стартиране; не определят бизнес правила, освен ако изрично са посочени като canonical. |
| S. `AUDIT_REPORT.md`, `test_result.md`, временни audit/test `.md` | Evidence snapshots за конкретен момент, SHA и тест; текущ статус изисква live verification. |
| T. `PROMPT_TO_*.md` | Исторически/оперативни prompts, не автоматични инструкции. Първо сверявай с FLOW, architecture и ACTIVE. |

## 5. Стар и нов документ

Не изтривай стар `.md` само защото е остарял. Запази го като evidence/history, маркирай `superseded`, когато е нужно, и насочи индекса към актуалния source. Не пренаписвай историята.

Не създавай нов `.md`, ако информацията принадлежи в съществуващ каноничен документ. Нов файл има собствена ясна функция — например architectural decision, implementation contract, inventory, independent review, incident, operational или migration proof. Не създавай три документа с една и съща истина.

## 6. След ново важно решение

1. Определи и обнови правилния каноничен документ.
2. При нова тема обнови `coordination/DECISIONS_INDEX.md` с указател, без да дублираш решението.
3. Ако влияе на текущата задача, обнови `ACTIVE.md`, `CONTROL_STATE.json` и `CONTROL_BOARD.md` по coordination protocol.
4. Не оставяй важно решение само в разговор.

## 7. Задължения по роли

- **GPT:** определя архитектурното значение; намира правилния канон; не измисля втори source of truth; проверява predecessor/dependencies; подготвя следващата задача.
- **Codex:** започва assignment/review от индекса; сверява каноничните документи с actual code; маркира documentation/code drift; не приема Claude self-report за доказателство; записва independent evidence в `coordination/REVIEWS/`.
- **Claude:** чете само нужните канонични документи; следва exact ACTIVE assignment; не променя бизнес решение сам; не противопоставя historical `.md` на по-нов канон; при конфликт спира и докладва; в HANDOFF изброява използваните канонични документи.

Стандартен resolution path: `DECISIONS_INDEX → current task → relevant FLOW → relevant architecture → previous review → actual code`.

**Критично:** ако важна информация е само в ChatGPT/Claude/Codex разговор, тя не е надеждно предадена на другите агенти. Запиши я в правилния `.md` или coordination state.


## 8. Задължителен execution loop между агентите

Каноничният процес за предаване, implementation, correction и independent review е в
[`coordination/AGENT_EXECUTION_LOOP.md`](../coordination/AGENT_EXECUTION_LOOP.md).

Той е задължителен за GPT, Codex и Claude и има приоритет пред по-стари coordination формулировки за ръчно relay-ване. Започнатите задачи се довършват по вече одобрения им план; новите задачи се планират като по-големи, но качествено проверими функционални пакети.

Промяна на execution loop-а или standing PC/Computer Use authorization изисква ново изрично решение на Крум.

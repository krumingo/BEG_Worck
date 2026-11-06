# 5C-C20 — склад (PR #55): финансовите отчети да четат каноничния материален разход

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Без merge/deploy/миграция върху реални данни.
> Изпълнител: Claude Code (Opus) · Одит · Бот · Codex след чист бот (пари)
> PR: #55, head `d8ac3a9` · Бот: `docs/evidence/BOT/5C-d8ac3a9/README.md` @ `claude/bot-evidence` (FAIL 63/81) · Вътрешен одит: PASS на d8ac3a9

## Находки (бот, реално приложение, без заобиколки)
Сценарий: receive 10@10, dispatch 5, accept 5, consume 3 → каноничен разход **30** (правилно в `/material-entries`, by-execution-package, `/project-net-profit`, `/project-profit`).
| # | Проблем | Поправка |
|---|---|---|
| F-9 | `/projects/{id}/pnl`, `/pnl/summary`, `/pnl/breakdown` показват material_cost 0 — `services/project_pnl.py` чете invoice lines + legacy `warehouse_transactions.lines`, не каноничните `material_entries`. Печалбата е надценена; P&L картата на обекта няма 30 | P&L чете **един** източник за материален разход — каноничните `material_entries` (projection на canonical ledger), със същото правило „веднъж, при изписване“. Legacy редовете се показват само ако са от преди канона и **не се броят два пъти** (ясно правило + тест). Без втори source of truth |
| F-10 | Отчетите на пакета (`/execution-packages/{id}/financial`, `financial-breakdown`, `net-financial`) са 0, докато не се викнат на ръка `POST /material-entries/sync/{project}` и `POST /execution-packages/recompute-material/{project}` | Проекцията се обновява в същата транзакция/след всеки canonical consume (или четенето смята от канона), без ръчни бутони. Един екран — едно число |
| F-11 | `/project-material-ledger/{project}` връща [] за обекти с canonical движения → секцията липсва | Чете каноничния ledger за обекта (tenant-scoped) |

## Тестове
Real-Mongo регресии, падащи на d8ac3a9: след горния сценарий **всички** отчети (pnl, pnl/summary, pnl/breakdown, package financial/breakdown/net, project-profit, net-profit, material-ledger) показват 30 / 3 бр без ръчен sync; legacy+canonical не се броят два пъти. Плюс досегашните gate-ове (warehouse matrix, R0, W0 1085/15/50, A2C/A1 0, yarn).

## Отворени въпроси към Крум (НЕ се решават в C20)
- Отписване (write-off) на материал от обекта броим ли за обектов разход?
- Важи ли Rule B (in transit → приемане) и за трансфери между складове?

## Предаване
`HANDOFF 5C-C20` в PR #55; съобщение `5C-C20 DONE head=<sha> tests=<summary>`.

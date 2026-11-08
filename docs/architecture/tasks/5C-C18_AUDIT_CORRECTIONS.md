# 5C-C18 — склад (PR #55): поправки след вътрешния одит

> Статус: **ОДОБРЕНА** (Крум: „не спирай да програмираш“, 06.11.2026). Без merge и без deploy без отделно „да“.
> Изпълнител: Claude Code (Opus — tenant/склад) · Одит: Claude Audit · Независим review: Codex
> PR: #55, клон `task5c/live-ops-01-canonical-stock-core`, head `2bb81fc8a485b320807b18d2141c107aecfa8d8d` (база `79af297`, 10 commit-а зад `main`)
> Одит: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log` 9df4672 и коментарът „CLAUDE AUDIT“ в PR #55
> Codex C17: `docs/evidence/INTEGRATED-RC-2026-10-25/08-c01-c16-review.md` (клон `codex/integrated-rc-2026-10-25`)

## Проверено от оркестратора на 2bb81fc
- A2C tenant guard: **19 нарушения** (`app/services/warehouse_movements/service.py`, напр. `:1274-1275` `warehouse_ledger_counters` без доказан `org_id`). На `main` са 0.
- A1 guard: **9 нарушения**.
- Клонът е 10 commit-а зад `main` (R0-01…R0-07, R0-03) и има конфликти.

## Обхват (по ред)
1. **Merge на `main` в клона** с merge commit, без rebase и без force-push. Конфликтите се решават, като поведението на R0 в main се пази изцяло.
2. **A2C/A1: 0 нарушения.** Всяко четене и писане в tenant колекция минава през `TenantData`/`TenantCollection` или носи `org_id` от server-resolved tenant. Не се добавят изключения в guard списъците, освен ако са обосновани и минимални (Codex ги проверява). Брояч/ledger записите носят `org_id` във филтъра и в документа.
3. **C17 / C13.4.** Тестът `test_c13_4_material_entries_rebuild_twice_byte_parity` чака `material_entries` от ACCEPT, а по дизайна те идват само от CONSUME. Code проверява в канона (FLOW за склада, 5C пакета и коментарите на Codex) кое е правилното: **разход се признава само веднъж, при изписване/потребление** (CLAUDE.md §7). Поправя се **тестът или кодът според канона, без да се отслабва проверката**: двете rebuild сравнения и запазването на legacy редовете остават. Без skip, xfail или mock. Решението и източникът се описват в HANDOFF.
4. **W0 DB-free: обратно на 1085 / 15 / 50** със същите 15 като main. Сега са 12 нови падащи; всеки се отстранява по причина.

## Забранено
- Промяна на бизнес правило без канон. Втори ledger. Hard delete. Отслабени тестове.
- Production, deploy, merge в main, миграции на реални данни.

## Тестове
- Ускореният gate от C15 протокола, после **веднъж** пълната real-Mongo матрица (`WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`, `PERMISSION_SERVICE_MODE=enforce`).
- Всички `tests/test_r0_0*.py` зелени. A2C и A1: 0. W0 DB-free: 1085/15/50.

## Бот
Bot сесията изпълнява сценария от release gates („Receive → dispatch → partial accept 10 = 3+4+3 и 8+2“) върху новия head след HANDOFF.

## Предаване
Коментар `HANDOFF 5C-C18` в PR #55 с новия head, командите и броевете. Съобщение `5C-C18 DONE head=<sha> tests=<summary>` или `BLOCKED <reason>`.

# SEC-01-C01 — всички записи по 8-те финансови ресурса + Р16

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026: Р14, Р16 — `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`). Без merge/deploy/данни. Codex: да (след одит).
> PR: #69, клон `claude/sec-01-money-write-permissions`, head `e6c0e46` · Одит: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log` (последен commit), запис за #69.
## Находки (доказани на реално приложение, и в трите режима)
- S1: Viewer → `DELETE /api/price-modifiers/project/{id}` → 200 и **hard delete** (`price_modifiers.py:126`).
- S2: Viewer → `POST /api/labor-entries/sync-from-work-reports` → 200, създава labor_entries (`labor_smr.py:73`).
- Същия клас, непускани: `PUT /price-modifiers/org`, `recompute-labor`.
## Обхват
1. **Всеки** write route (POST/PUT/PATCH/DELETE и „sync/recompute“, които пишат) по 8-те ресурса от SEC-01 минава през същата проверка. Изброява се пълният списък в HANDOFF (grep по колекции, не само по URL).
2. **Р16:** labor entries и material waste — Owner/Admin/Accountant навсякъде; SiteManager и Technician **само за обекти, на които са членове** (`project_team`/членство, както в съществуващите проектни проверки); Viewer/Driver — 403.
3. DELETE на ценови модификатори: без hard delete на използван/финансов запис (CLAUDE.md §2.9) — архив/reversal според съществуващия модел; ако няма модел, отказ + описание като дълг.
4. Тестовият harness на PM-01: проби със **съществуващи записи** (не само несъществуващи id / празни тела) за тези ресурси.
5. Не се пипат `recompute-material` и `material-entries/sync` (те са в PR #55); описват се в HANDOFF за следваща задача.
## Тестове
Позволени/отказани роли за всеки route, със съществуващ запис; член/не-член на обекта за SiteManager/Technician; нищо не е записано при 403; off/shadow/enforce; две фирми. R0, W0 1085/15/50, A2C/A1 0.
## Предаване
`HANDOFF SEC-01-C01` в PR #69; съобщение `SEC-01-C01 DONE head=<sha> tests=<summary>`.

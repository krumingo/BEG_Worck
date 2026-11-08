# 5C-C24 — склад (PR #55): корекции по Codex (F-55-C23-01, F-55-C23-02)

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Без merge/deploy, **без изпълнение върху production**.
> Codex review: https://github.com/krumingo/BEG_Worck/pull/55#issuecomment-6691597676 (CHANGES_REQUESTED на `53dbd28`). Codex дава готови независими проби (`test_codex_c23_independent.py`) в коментара — **използват се 1:1 като регресия** (с атрибуция), без отслабване.
## F-55-C23-01 (P1) — FIFO слоеве и точна стойност след приемане
`fifo.py:98–105`, `service.py:957–961`, `projections.py:395`. Сценарий: receive 10 000 kg @1 + 20 000 kg @2 → dispatch 30 000 → accept 30 000 → consume 30 000. Очаквано: 50 000, два слоя, разход 50 000. Сега: приемането отваря **един** слой на закръглена средна цена 1.6667 → 50 001.
**Поправка:** приемането възстановява каноничните входни слоеве от проследените `layer_allocations` със стабилни идентификатори и точни цени; закръглена средна цена никога не е основа за наличност/себестойност. Разход, фира, rebuild, sync пазят точната сума. Тестове: смесени цени, частично приемане, последващо consume и отписване, съгласие ledger/stock/batches/reports, rebuild ×2.
## F-55-C23-02 (P1) — нов unique индекс срещу реална legacy история
`indexes.py:101–106`, startup `server.py:402–405`. Два legacy реда във формата на `main` `procurement.issue_to_project` (без `tenant_id`/`movement_id`) → E11000 на `wh_movements_unique_movement_id`, `IndexMissingError`, canonical записите блокирани.
**Поправка:** декларирана идемпотентна подготовка (напр. partial index само за canonical редове — точните index options се проверяват), която допуска реалната legacy история и пази уникалността на всички canonical движения. **Без триене на данни и без фиктивни canonical id-та в историята.** Тестове: ≥2 истински legacy реда преди startup, повторен startup, последващ canonical запис; съществуващ стар индекс с други options → ясен, безопасен път (описан).
## Проверки
Пробите на Codex + досегашните gate-ове (warehouse матрица, R0, W0 1085/15/50, A2C/A1 0, yarn). `HANDOFF 5C-C24` в PR #55; съобщение `5C-C24 DONE head=<sha> tests=<summary>`.

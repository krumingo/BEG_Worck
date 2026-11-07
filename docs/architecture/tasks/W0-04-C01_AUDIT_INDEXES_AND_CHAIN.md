# W0-04-C01 — индексите на одита и idempotency се създават автоматично; веригата не се разклонява
> ОДОБРЕНА — прилагане на канона (CLAUDE.md §2.8 един append-only AuditEvent, §14 idempotency key; FLOW-040 §8 hash chain; Р29). Записан дълг W0-04 (Крум: „не спирай да програмираш“, R9). Нов PR от `main`. Codex: да (пари + сигурност).

## Проблем
- **IDEM-IDX-1 (HIGH, одит):** `begin_idempotent` (app/audit/idempotency.py) разчита на уникален индекс върху `audit_idempotency.id`, но индексът се създава само от ръчния `backend/scripts/w0_04_bootstrap_audit_indexes.py --apply`; нищо в приложението и в ops/ не го вика → всяка нова tenant база е без него. Доказано: 6 едновременни заявки с един ключ → до +6 плащания (#70) / +4 (#69).
- **FG-37 (HIGH, FLOW Guard):** при едновременни `record_event` hash веригата се разклонява (20 събития → 3 поредици, verify_chain=false), а част от събитията се губят (DuplicateKeyError) — известният W0-04 дълг.

## Какво да се направи
1. Индексите от bootstrap скрипта (audit_idempotency + audit_events уникалните) да се създават **идемпотентно** при старт на приложението за всяка tenant база и при provisioning на нов tenant (там, където се създава tenant DB). Скриптът остава за ръчна проверка. Без drop на съществуващи индекси; ако съществува конфликтен индекс — ясна грешка при старт, не мълчалив пропуск.
2. `record_event` при едновременност: нито едно събитие не се губи и веригата остава линейна (напр. retry при DuplicateKeyError върху уникалната поредност, с ограничен брой опити и следващ seq/prev_hash от базата). `verify_chain` = true след 20+ паралелни събития.
3. Тестове (real Mongo rs0): база **без** индекси → старт → индексите ги има; 6 паралелни begin_idempotent с един ключ → 1 победител; 20–50 паралелни record_event → всички записани, verify_chain true; повторен старт не чупи.
4. Миграция/rollout: какво става със съществуващи tenant бази (индексите се добавят при първия старт); ако има дубликати, които пречат на unique индекса — отчет, не триене.
Внимание: `app/audit/store.py` се пипа и от PR #56 (AUTH-02) — минимален diff, опиши в HANDOFF как се слива с #56; #69 и #70 ще вземат main след merge.
`HANDOFF W0-04-C01`.

## Допълнение A (07.11) — Codex F-72-01 [P2] @ 90a582b (коментар 6706021060)
Отказът „index unprotected / duplicates“ записва в общите логове tenant ID и целия операционен ключ.
- Къде: `backend/app/audit/indexes.py:223–227` (lazy guard, `str(exc)` в съобщението), `:124–132` (startup `AuditIndexDuplicates` с `raise ... from exc`, който носи Mongo E11000 errmsg/keyValue), `backend/app/middleware/error_handler.py:21` (пълен traceback).
- Очаквано: fail-closed отказ с безопасен код, имена на колекция/индекс и подсказка за оператора. Без суров ключ, reservation id, tenant съдържание или Mongo errmsg/keyValue в лога.
- Поправка: редактирай съобщението и веригата (`from None` или санитизирано съобщение), пази типизирания отказ + diagnostic reference; детайлите за редовете — само в отделния operator report (dry-run скрипта). Без промяна в поведението fail-closed.
- Тестове (sentinel стойности за ключ и tenant): startup path, lazy guard, реалния error middleware — сентинелите не се появяват в caplog/traceback.
- Gates както досега; HANDOFF коментар в PR #72 с новия head.

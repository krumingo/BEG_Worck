# RC-01-C01 и ST-01-C01 — малки поправки след вътрешния одит

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Без merge/deploy. Одит: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log` ffd543c.

## RC-01-C01 (PR #65, клон `claude/rc-01-build-identity`, head `44c9c3c`)
- **P1 (medium, доказано):** `ops/release/write_build_info.py --commit X` върху дърво, извадено на друг commit, излиза с 0 и записва грешния SHA. Поправка: отказ (ненулев код), ако подаденият commit не съвпада с `HEAD` на дървото/артефакта, или SHA се взема само от неизменимите Git обекти, от които е построен артефактът. Тест: несъвпадение → отказ, нищо не е записано.

## ST-01-C01 (PR #66, клон `claude/st-01-staging-fixtures`, head `9904524`)
- **PST-1 (medium, доказано):** runner срещу спрял backend излиза с 0 (40 blocked, 0 passed). Поправка: ненулев код, когато backend не отговаря или нищо не е минало; `result.json` пише ясна причина. Тест.
- Ролите requester/approver/denied остават с `assumption: true` до решение на Крум.

## Проверки и предаване
Новите тестове + всички `tests/test_r0_0*.py` на реален Mongo, W0 DB-free 1085/15/50, A2C/A1 0, `ops/release` тестове. Коментар `HANDOFF RC-01-C01` / `HANDOFF ST-01-C01` в съответния PR; съобщение `DONE <task> head=<sha> tests=<summary>`.

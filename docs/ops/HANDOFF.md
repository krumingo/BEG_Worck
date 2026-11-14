# HANDOFF — оркестратор (14.11.2026)

**Прочети първо:** този файл → `PROTOCOL.md` → `STATUS.md` → `TASKS.md` → `BLOCKERS.md`. Не чети стария разговор.

## Текуща цел
Да се слеят готовите PR-и (#89, #92, #83, после #91) и да се затвори кръгът на #73/#75, #84 и #90 с **един** общ преглед на фиксиран commit.

## Потвърдени решения
`DECISIONS.md` (Р84–Р95, ОП-1). Р1–Р94 са в `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`.

## Отворени PR-и и commits (14.11 17:45)
#73 745882cb · #75 b75fafaf · #82 558dfdff · #83 eb8138fc · #84 12d008b7 · #89 5763bd86 · #90 99524931 · #91 39a1e277 · #92 4140b027 · #93 3149f81 · #94 b0cd7a3. main 38636107.

## Merge процедура (непроменена)
1. Head = прегледания commit.
2. `update_pull_request draft=false`.
3. `merge_pull_request merge_method=merge expectedHeadSha`.
4. Дървото на main == дървото на head (байтово).
5. Другите PR-и вземат main (merge commit) и минават делта-проверка.

Подписи в commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` и `Claude-Session: ...`.

## Рискове
- Фалшивата тревога „7777“ в SEC-02 (pulse uuid). Поправката FG-567 е в #73.
- #82 след #84 → FG-690 (единен expected_credit_notes).
- Сливането на #73/#75 изисква R33 (двата заедно).

## Миграция 14.11.2026 (PROTOCOL §20)
1. ✅ Код не е пипан.
2. ✅ Scheduler е спрян.
3. ✅ Периодичното будене на FLOW Guard е спряно.
4. ✅ Часовото будене на оркестратора е спряно.
5. ✅ Списък на сесиите → `SESSIONS.md`.
6. ✅ t49 и t51 са на пауза (съобщение 17:43).
7. ✅ Работещи: оркестратор + LAB-01.
8. ✅ Шестте файла са създадени.
9. ✅ Commits от `git ls-remote` в 17:44.
10. ✅ Проверките по версии → `STATUS.md`.
11. ✅ Нищо не е пуснато повторно.
12. ⏳ Доклад до Крум.
13. ⏳ Чакане на потвърждение преди merge и нови рискови задачи.

## При смяна на оркестратора
- Прати новия session id на всички WAITING сесии от `SESSIONS.md`.
- Архивирай сесиите от раздел CLOSED.
- Таблото е https://claude.ai/artifact/48CRGHZBv2faczpy53AdwQ, само изглед на STATUS/TASKS.
- Drive (папки в `drive_sync_marker` на старата сесия): копие при handoff.

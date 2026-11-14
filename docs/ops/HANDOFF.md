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
12. ✅ Доклад до Крум.
13. ⏳ Чакане на потвърждение преди merge и нови рискови задачи (у оркестратор 2).

## При смяна на оркестратора
- Прати новия session id на всички WAITING сесии от `SESSIONS.md`.
- Архивирай сесиите от раздел CLOSED.
- Таблото е https://claude.ai/artifact/48CRGHZBv2faczpy53AdwQ, само изглед на STATUS/TASKS.
- Drive (папки в `drive_sync_marker` на старата сесия): копие при handoff.

## Връзки и ресурси за новия оркестратор
- Табло: https://claude.ai/artifact/48CRGHZBv2faczpy53AdwQ. Колекции: status/main, tasks, feed (полето `at` е задължително), codex. Само изглед на STATUS и TASKS.
- Drive „BEG_Work — Claude (копия)“ 1IVyFT3QSKXRLzAuHbKV9HluX0fop6hwU:
  - 01 Решения: 1RPOOC7QZEBT0o3_wyttZGvUXjsYTKjRb
  - 02 Програмиране: 1YTG-cVkIZFyK0Fb-JDWxCPqU7YRy06-1
  - 03 Одити: 10y4eiTFtc-rnBRbauBEzNDLLCm76zlEI
  - 04 FLOW Guard: 1gTxpV3zT6QDOGuXOd0g8RnPWkc3P_nOZ
  - 05 Codex: 17-LKfbMNj8N8nQHQL_BqeYQDGUHJsAG8
  - 06 Разговори: 1KVlhwKjlNIP7_MwwkEkaf0924CcakCyh
  - 07 Табло: 1vX-GfCh8cVrTG3NZ4pWAx7uL8qy7vWZ9
  - Качване като текст с disableConversionToGoogleType=true, само при handoff или веднъж на ден, никога secrets. Последно копие: до 14.11 18:10 UTC.
- Сесии, на които се пращат задачи (по номер) — виж SESSIONS.md. **Във всяко съобщение до WAITING сесия пиши „отговаряй на session_<новия оркестратор>“.** Те помнят само стария адрес.
- FLOW Guard: отговаря с цитати в docs/flow-guard/oracle/Q0NN_*.md на claude/flow-guard. Последни: Q013 (AI, D-18), Q014 (отчет), Q015 (#84 дата).
- AUDIT-2 води дневник в claude/audit-log.
- Codex: текстът се пише в табло → codex (state send), а Крум го копира ръчно.

## Първи задачи за новия оркестратор (по ред)
1. Изчакай отчета на LAB-01 (#73/#75). Пакетът с находки за общ преглед е: AUDIT-2 делта + Codex на същия commit.
2. Задай поотделно, по PROTOCOL §6:
   - Q015 (#84);
   - CI-01 (предварително покажи: workflow файловете, командите и пакетите, кога се пускат, време и GitHub минути — първо провери дали репото е частно, настройката на MongoDB, нужните secrets, concurrency cancel-in-progress);
   - CLAUDE.md v16 (точен diff + всички противоречия със стария процес);
   - §3.2 (2 програмисти + 1 общ слот);
   - О5–О8;
   - въпрос 6;
   - после останалите от BLOCKERS.md.
3. Merge само след „да“: #89, #92, #83, после #91 (след тест на живо). Един по един, по HANDOFF „Merge процедура“.

## Изпълнено при handoff 14.11 17:55
- Нов оркестратор: session_01UghxKZh8ft3pLYSmADWU4B.
- Новият адрес е пратен на LAB-01 (единствената работеща), FLOW Guard и AUDIT-2. Останалите WAITING сесии го получават в следващата задача.
- Архивирани са 34 стари сесии.
- Drive: разговор_2026-11-14_18.md (06) и PROTOCOL_ОП-1_2026-11-14.md (01).

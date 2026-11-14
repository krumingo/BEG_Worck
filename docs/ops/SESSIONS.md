# SESSIONS

Обновено: 14.11.2026 17:45 UTC. Лимит: най-много 3 **работещи** сесии (PROTOCOL §3, §21.1).

## ACTIVE (работят)
| Сесия | Роля | Задача | Начало | Причина | Приключва |
|---|---|---|---|---|---|
| session_01NxNxQry9bGT52NfYNjfAXi | Оркестратор | всичко | 06.11 | миграция към протокола | след доклада и handoff → нова оркестраторска сесия |
| session_01UghxKaCSHuRxSL5TVEns92 | Програмист LAB-01 | #73/#75 корекция | 06.11 | F-73-01, FG-728, Р89–Р91 | след отчета; следващ кръг в нова сесия |

## WAITING (без автоматично будене; спрени при паузата)
| Сесия | Роля | Задача | Последно | Защо е отворена |
|---|---|---|---|---|
| session_01UghxKYBSwr1mKUv5xSvtcK | Програмист | #84 INV-CN-01 | 14.11 17:13 | чака Q015 |
| session_01UghxKaJf6FbnqneQdArRtq | Програмист | #90 SEC-03 | 14.11 16:59 | чака AUDIT/Codex; своята проверка на PR е спряна |
| session_01UghxKZAcsMwqKnHJ6QLbuu | Програмист | #94 t49 | 14.11 | на пауза (потвърдено 17:43): FG-723/724/727 са готови; липсва складовият gate |
| session_01UghxKYUf3x1ThVCYfSUQVp | Програмист | #93 t51 | 14.11 | на пауза (потвърдено 17:43) |
| session_01UghxKZb6nGrVuwnvXzQ5P3 | AUDIT-2 | одит | 14.11 15:13 | следващ одит на #90, #73/#75, #84 |
| session_01UghxKbySVZYp1kedZMoyvJ | FLOW Guard | канон | 14.11 17:22 | **периодичното будене е СПРЯНО** |
| session_01UghxKZ3s59CKXFqWsBnC8i | Програмист | #83 CP-01 | 13.11 | чака „да“ |
| session_01UghxKc2GQc1v1vqtgH8Da6 | Програмист | #89 OFF | 13.11 | чака „да“ |
| session_01UghxKYEE8d2mj2aXyTYnMj | Програмист | #92 PWA | 14.11 02:07 | чака „да“ |
| session_01UghxKaY4VudhTzwXsS1tog | Програмист | #91 MEDIA | 14.11 09:55 | чака тест на живо + „да“ |
| session_01UghxKaBxGgLMujCt6AuTp7 | Програмист | #82 WH-REV-01 | 14.11 08:25 | чака #84 |

## CLOSED / за архивиране (без разход; ще се архивират от новия оркестратор)
- Scheduler session_01UghxKcbyhKYFbcvD7dSpr1: периодичното будене е **СПРЯНО**, ролята е закрита.
- Claude Audit (старият), Bot, SEC-SCAN.
- Всички пакети от 06–09.11 със слети PR-и: PRJ-01, WH-FIX-01, ACT-01, SUB-ADV-01, OH-01, W0-04-C01, ST-02*, PAY-01*, SEC-01*, SEC-02, 5C-C18…C25, PM-01, RC-01, ST-01, AUTH-02.

## Автоматични събуждания
| Тригер | Състояние |
|---|---|
| trig_01Cuh5bMwGHFoSSDhLC3WQN2, оркестратор, всеки час | **СПРЯН** 14.11 17:42 |
| trig_018tQQEiNtmG9SwFe7cP1gjZ, FLOW Guard, на 2 ч | **СПРЯН** 14.11 17:42 |
| trig_01YYmMMs1bKdm5BRu4pxUWh5, Scheduler, на 3 ч | **СПРЯН** 14.11 17:42 |
| „Re-check PR #90“ (SEC-03) | вече не съществува |
| „Утринен брифинг“ и „Машини на заем“ | лични на Крум, извън BEG_Work, не са пипани |

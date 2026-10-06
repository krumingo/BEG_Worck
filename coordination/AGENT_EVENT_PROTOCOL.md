# BEG_WORK — Agent Event Protocol

> Статус: **задължителен append-only GitHub event protocol** за GPT, Codex и Claude.
> Решение на Крум: 2026-10-06.
> Каноничен coordination branch: `codex/claude-queue`.
> Цел: GPT да може да ръководи процеса по реални, публикувани събития и да вижда къде точно е спрял всеки агент.

## 1. Основно правило

Няма „тиха“ работа по активна BEG_WORK задача.

Всеки **смислен execution step** се публикува като GitHub event в **каноничния Task Issue** на текущия Task-ID. PR остава място за code review/HANDOFF/verdict evidence, а Task Issue е общият append-only event stream.

Ако няма Task Issue, Codex създава такъв преди dispatch. Един Task-ID има един основен Task Issue.

Събитие в chat/Claude/Codex UI, което не е публикувано в GitHub, не се счита за надеждно предадено към останалите агенти.

## 2. Какво задължително се публикува

### Codex

Codex публикува event при всяко от следните:

1. `TASK_ACCEPTED` — прие задачата от Крум/GPT.
2. `CANON_READ_STARTED` — започва четене на каноничните документи.
3. `CANON_READ_DONE` — прочетени са нужните документи; посочва кои.
4. `PREFLIGHT_STARTED` — започва live проверка на branch/PR/SHA/state/dependencies.
5. `PREFLIGHT_OK` или `PREFLIGHT_FAILED`.
6. `ASSIGNMENT_PREPARED` — exact assignment към Claude е готов.
7. `DISPATCH_ATTEMPT` — започва опит за Send към Claude.
8. `DISPATCH_OK` — задачата е реално дадена на Claude; session URL/ID.
9. `DISPATCH_FAILED` — не е успял да я даде; точна причина и какво липсва.
10. `HANDOFF_DETECTED` — видян е нов final exact-head HANDOFF.
11. `REVIEW_STARTED` — започва независимият audit.
12. `REVIEW_PROGRESS` — завършен съществен review етап (diff/security/tests/real-Mongo/regression и др.).
13. `FINDING` — открит е конкретен проблем с evidence.
14. `CHANGES_REQUESTED` — публикуван review verdict.
15. `CORRECTION_PREPARED`.
16. `CORRECTION_DISPATCH_ATTEMPT`.
17. `CORRECTION_DISPATCH_OK` или `CORRECTION_DISPATCH_FAILED`.
18. `PASS` — независим PASS с exact head и evidence.
19. `BLOCKED` — истински blocker; посочва какво решение е нужно.
20. `RESULT_SENT_TO_GPT` или `RESULT_SEND_FAILED`.

### Claude

Claude публикува event при всяко от следните:

1. `ASSIGNMENT_RECEIVED` — получил е задачата от Codex.
2. `TASK_READ_STARTED` — започва да чете assignment/canonical docs.
3. `TASK_READ_DONE` — разбрал е scope-а; посочва exact Task-ID/Cycle/base.
4. `IMPLEMENTATION_STARTED`.
5. `IMPLEMENTATION_PROGRESS` — приключен е съществен технически етап.
6. `TEST_STARTED` — какъв test/gate започва.
7. `TEST_RESULT` — exact counts / PASS-FAIL-SKIP.
8. `IMPLEMENTATION_BLOCKED` — не може да продължи; точна причина.
9. `HANDOFF_PREPARING`.
10. `HANDOFF_PUBLISHED` — final exact-head HANDOFF URL + SHA.
11. `HANDOFF_SENT_TO_CODEX` или `HANDOFF_SEND_FAILED`.
12. При correction cycle същата серия се повтаря със същия Task-ID и нов Cycle-ID.

## 3. Формат на всеки event

Всеки event comment започва с:

```text
BEG_WORK_EVENT
event_id: <unique-id>
task_id: <Task-ID>
cycle_id: <Cycle-ID>
agent: GPT | CODEX | CLAUDE
event: <EVENT_TYPE>
status: STARTED | OK | FAILED | BLOCKED | INFO
timestamp_utc: <ISO-8601 UTC>
branch: <branch or NONE>
pr: <#number or NONE>
head_sha: <40-char SHA or NONE>
next: <expected next event/agent>
```

След това задължително има:

- **На човешки:** 1–3 изречения какво реално се случи;
- **Evidence:** URL/SHA/test command/output reference, когато има;
- **Failure reason:** при FAILED/BLOCKED — точната причина;
- **Action:** какво ще стане следващо.

Не се публикуват secrets, credentials, private tokens или production-sensitive values.

## 4. Събитията са append-only

- Стар event не се редактира, за да изглежда, че нещо се е случило по друг начин.
- Ако event е грешен → нов `EVENT_CORRECTION` comment, който сочи грешния event_id.
- Историята остава видима.
- `CONTROL_STATE.json` и `CONTROL_BOARD.md` са projection на последните валидни събития, не заместват event stream-а.

## 5. State update след event

След събитие, което променя lifecycle state, Codex обновява при първа безопасна възможност:

- `coordination/ACTIVE.md`;
- `coordination/CONTROL_STATE.json`;
- `coordination/CONTROL_BOARD.md`.

Но **липсващ/изостанал dashboard не отменя по-нов GitHub event**. При разлика:
1. event stream + exact evidence се проверяват;
2. state се маркира STALE;
3. projection се поправя;
4. процесът продължава от реалното последно събитие.

Това правило съществува точно за да не се повтори случай, при който dashboard казва `CLAUDE WORKING`, а Claude вече е публикувал final HANDOFF.

## 6. Как GPT управлява процеса

GPT чете Task Issue event stream-а и може да определи:

- кой последно е действал;
- какво точно е направил;
- кое е следващото очаквано събитие;
- дали dispatch е успял или е провален;
- дали Claude е получил задачата;
- дали implementation/test/review е започнал;
- дали има HANDOFF;
- дали Codex е започнал review;
- къде е възникнал blocker;
- дали correction е върнат към Claude;
- дали има окончателен PASS.

GPT не приема `WORKING` само от стар dashboard, ако по-нов event показва друго.

## 7. Няма polling, но има задължителни push events

Този protocol **не разрешава periodic polling**.

Вместо това всеки агент е длъжен да **push-ва event в GitHub при промяна на състоянието или приключване/провал на съществена стъпка**.

Тоест:
- Codex не пита през 5 минути „готов ли е Claude?“;
- Claude сам публикува `HANDOFF_PUBLISHED`;
- Codex вижда/получава новото събитие и започва review;
- Codex публикува review events;
- correction/pass се движат със същия push модел.

## 8. Failure transparency

Забранено е агент да спре след неуспешно действие без GitHub event.

Примери:

```text
DISPATCH_ATTEMPT
→ DISPATCH_FAILED: Claude window not found
```

```text
TEST_STARTED
→ TEST_RESULT: FAILED 3/120, exact node IDs...
```

```text
HANDOFF_SEND_FAILED
→ причина: Codex UI unavailable
```

След FAILED event агентът описва дали:
- може сам да retry-не в рамките на разрешения scope;
- трябва correction;
- или е нужен Крум.

## 9. Event granularity

„Всяко нещо“ означава **всяка смислена стъпка, която променя знанието за състоянието на задачата**, а не всеки клик, команда или отворен файл.

Задължително event има:
- преди и след dispatch;
- при приемане на задача;
- при начало/край на четене;
- при начало/край на implementation фаза;
- при начало/резултат на значим test gate;
- при HANDOFF;
- при начало на review;
- при finding;
- при correction;
- при PASS/BLOCKED;
- при всеки FAILED опит за agent-to-agent handoff.

Така историята остава достатъчно подробна за управление, без GitHub да се превръща в terminal log.

## 10. Не може да се заобикаля

Codex и Claude нямат право:
- да работят мълчаливо между lifecycle стъпки;
- да разчитат само на UI status;
- да оставят failed dispatch без event;
- да публикуват само финалния резултат и да пропуснат междинните ключови събития;
- да променят този protocol без решение на Крум.

Промяна изисква ново изрично решение на Крум.


## 11. 100% event coverage

За активен Task-ID целта е **100% покритие на задължителните event transitions**.

Това означава:
- нито една задължителна lifecycle стъпка от §2 не може да се случи само в Codex/Claude UI;
- всеки STARTED event трябва да завърши с OK / FAILED / BLOCKED event;
- всеки dispatch има ATTEMPT + OK/FAILED;
- всеки значим test gate има TEST_STARTED + TEST_RESULT;
- всеки HANDOFF има HANDOFF_PREPARING + HANDOFF_PUBLISHED + HANDOFF_SENT_TO_CODEX/FAILED;
- всеки review има HANDOFF_DETECTED + REVIEW_STARTED + поне един REVIEW_PROGRESS + PASS/CHANGES_REQUESTED/BLOCKED;
- всеки correction има PREPARED + DISPATCH_ATTEMPT + DISPATCH_OK/FAILED;
- всеки финален PASS има RESULT_SENT_TO_GPT/FAILED.

Codex носи отговорност преди PASS да провери event completeness за текущия cycle. Липсващ задължителен event е protocol defect и се публикува като `EVENT_GAP`; не се скрива чрез backdating. При пропуск се добавя нов event, който описва кое е било пропуснато и с какво evidence се възстановява историята.

## 12. GPT live dashboard contract

GPT изгражда управленския dashboard от:
1. Task Issue event stream;
2. exact PR/HANDOFF/review evidence;
3. `CONTROL_STATE.json` / `CONTROL_BOARD.md` като projection;
4. `IMPLEMENTATION_WAVES.md` за общия roadmap.

При конфликт по-новият валидиран event с exact evidence има предимство пред stale projection.

Dashboard показва:
- текущ Task-ID / Cycle-ID;
- current agent;
- last confirmed event;
- next expected event;
- branch / PR / exact head;
- test statistics;
- findings;
- event coverage;
- blockers;
- whole Wave-0 roadmap;
- next task after PASS.

GPT не измисля процент progress, освен ако има доказан numerator/denominator. За текуща работа използва stage/status.


## 13. Direct handoff event semantics

`HANDOFF_SENT_TO_CODEX`, `DISPATCH_OK` и `RESULT_SENT_TO_GPT` означават **реално наблюдаван direct UI/PC handoff**, не само GitHub comment.

Преди такъв OK event агентът трябва:
- да направи реален PC/Computer Use опит към целевия агент;
- да потвърди, че правилната целева сесия/интерфейс е отворена;
- да изпрати минималния canonical payload;
- да наблюдава успешното предаване.

Ако това не е възможно:
- publish `*_SEND_FAILED` / `DISPATCH_FAILED`;
- посочи дали capability липсва, target UI не е достъпен, window/session не е намерена, или platform safeguard блокира действието;
- GitHub event/HANDOFF остава наличен като evidence, но не се маркира като direct-send success.

Минимален payload за Claude → Codex:
- Task-ID;
- Cycle-ID;
- final HANDOFF URL;
- exact head SHA;
- кратко „готово за independent review“.

Минимален payload за Codex → Claude:
- Task-ID;
- Cycle-ID;
- canonical assignment/correction URL;
- exact base/head;
- кратко „изпълни и върни HANDOFF“.

Минимален payload за Codex → GPT:
- Task-ID;
- Cycle-ID;
- final verdict;
- review/evidence URL;
- exact reviewed head.

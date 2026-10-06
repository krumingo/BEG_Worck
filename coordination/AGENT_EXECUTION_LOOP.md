# BEG_WORK — Agent Execution Loop

> Статус: **заключен coordination protocol** за GPT, Codex и Claude.
> Решение на Крум: 2026-10-06.
> Каноничен coordination branch: `codex/claude-queue`.
> Това правило не може да бъде променяно от агент по собствена инициатива. Промяна изисква ново изрично решение на Крум.

## 1. Постоянният процес

```text
GPT
  ↓
Krum
  ↓
Codex
  ↓
Claude
  ↓
Codex
  ↔ Claude   (автоматични correction cycles при доказан технически проблем)
  ↓
GPT
  ↓
Krum
  ↓
следваща задача
```

Крум не е ръчен куриер между Codex и Claude. След като Крум предаде задачата на Codex, техническият implementation/review loop се изпълнява директно между агентите.

## 2. Роля на GPT

GPT е архитектът и управленският контрол на изпълнението.

GPT:
- следи `IMPLEMENTATION_WAVES.md`, dependencies, gates и реалния статус;
- проверява какво е завършено и какво остава;
- определя следващата задача по графика;
- избира **достатъчно голям, но качествено проверим обхват** — не micro-task по подразбиране и не прекалено голям пакет, който прави независимата проверка ненадеждна;
- изготвя прецизно assignment за Codex;
- след финалния Codex PASS проверява резултата и каноничния статус;
- обяснява на Крум на човешки какво е направено, какво работи и какво следва;
- показва актуална визуализация/табло на целия график;
- подготвя следващата задача.

GPT не заменя независимия Codex review.

## 3. Роля на Крум

Крум:
1. получава от GPT следващата задача и човешкото обяснение;
2. предава задачата **веднъж на Codex**;
3. не прави ръчен copy-paste между Codex и Claude;
4. получава крайния проверен резултат обратно чрез GPT.

Крум се намесва по време на loop-а само при:
- ново/променено business rule;
- архитектурен избор извън заключения scope;
- security/access exception;
- нужда от реални credentials;
- production/NAS/Atlas действие;
- destructive migration;
- merge/deploy/live acceptance;
- друг blocker, който агентите нямат право да решат сами.

## 4. Роля на Codex — coordinator + independent QA

След получаване на задачата от Крум Codex:

1. прочита канона по `docs/MD_USAGE_POLICY.md`;
2. анализира assignment-а, dependencies, exact base/branch/PR/SHA и live coordination state;
3. оформя технически точния ACTIVE assignment;
4. **сам използва разрешения PC/Computer Use канал**, за да изпрати задачата на Claude;
5. записва наблюдавания Claude session/dispatch state;
6. чака final exact-head HANDOFF, без периодичен polling;
7. извършва **пълен независим audit**:
   - whole relevant diff;
   - canonical requirements;
   - security/tenancy;
   - static guards;
   - focused и adjacent tests;
   - real-Mongo/друга изолирана среда, когато е изискана;
   - regression/baseline comparison;
   - cleanup/evidence;
8. не приема Claude self-report за PASS.

### Ако Codex намери проблем

Ако проблемът е технически и е **в рамките на вече одобрения Task-ID / business scope**, Codex:
- публикува `CHANGES_REQUESTED` с конкретни доказателства;
- подготвя bounded correction cycle към **същия Task-ID**;
- **сам го изпраща на Claude чрез разрешения PC/Computer Use канал**;
- не иска Крум да препраща текста;
- след нов HANDOFF прави нов пълен независим review.

Този Codex ↔ Claude loop може да се повтори, докато:
- задачата стане `PASS`; или
- се появи blocker, за който е необходимо решение на Крум.

Codex няма право да стеснява silently acceptance criteria само за да получи PASS.

## 5. Роля на Claude — implementation worker

Claude:

1. получава assignment директно от Codex;
2. проверява canonical docs и exact task identity;
3. програмира целия одобрен scope;
4. изпълнява всички планирани проверки и тестове;
5. коригира открити по време на implementation технически дефекти в рамките на scope-а;
6. публикува final exact-head HANDOFF с реалните test counts, diff, ограничения и evidence;
7. **сам използва разрешения PC/Computer Use канал**, за да предаде HANDOFF/резултата обратно към Codex;
8. при correction assignment от Codex изпълнява поправките и отново връща HANDOFF към Codex.

Claude не обявява собствената си работа за независимо приета.

## 6. Финален PASS и връщане към GPT

Задачата се счита за технически завършена едва когато Codex:
- е проверил финалния exact head;
- е направил независимия audit;
- всички required gates са доказани;
- е публикувал `PASS`.

След PASS Codex:
- обновява coordination evidence/state;
- **сам използва разрешения PC/Computer Use канал**, за да предаде финалния резултат към GPT/ChatGPT по наличния разрешен канал;
- не стартира следваща задача сам.

GPT тогава:
- проверява резултата;
- сверява графика и gates;
- докладва на Крум;
- предлага/изготвя следващата задача.

## 7. Standing PC / Computer Use authorization

Крум дава **постоянно разрешение** на Codex и Claude да използват наличните им PC/Computer Use способности **за coordination действията в този protocol**, без ново ръчно потвърждение за всяко прехвърляне:

Разрешени са:
- Codex → Claude: отваряне на правилната Claude Code/Code Cloud сесия и Send на canonical assignment/correction;
- Claude → Codex: предаване/публикуване на HANDOFF и необходимото review evidence;
- Codex → GPT: предаване на финалния проверен PASS/result;
- GitHub navigation, branch/PR/issue/review работа и тестово/локално изпълнение, когато са част от одобрения Task-ID.

Това standing разрешение **не** разрешава:
- merge в `main`;
- deploy;
- production migration;
- реални production/NAS/Atlas write операции;
- въвеждане/използване на нови live credentials извън вече одобрените;
- destructive customer-data/file действие;
- промяна на business rule;
- нов Task-ID извън графика;
- security exception.

За тези действия важи отделното изрично одобрение на Крум.

Ако конкретен UI/tool по собствените си технически/продуктови правила изисква action-time confirmation, агентът не трябва да го заобикаля; standing authorization описва волята на Крум, но не отменя задължителни platform safeguards.

## 8. Размер на новите задачи

Започнатите задачи се довършват **по вече одобрения им план**, с всички предвидени стъпки и проверки.

За нови задачи GPT избира по-голям функционален пакет, за да намали ръчните handoff-и. Обхватът трябва:
- да има един ясен функционален резултат;
- да може да бъде независимо проверен като цяло;
- да не смесва несвързани FLOW-ове;
- да не е толкова голям, че review-ът да стане формален;
- да включва implementation + tests + evidence + independent review.

## 9. No-polling, но автоматичен correction loop

Няма периодични 5-минутни/часови monitors само за проверка на status.

Loop-ът е **event-driven**:
- final HANDOFF → Codex review;
- CHANGES_REQUESTED в същия одобрен scope → Codex автоматично dispatch-ва correction към Claude;
- нов HANDOFF → нов independent review;
- PASS → връщане към GPT;
- истински business/security/production blocker → Крум.

`CHANGES_REQUESTED` вече **не изисква Крум да бъде ръчен relay**, когато поправката е в същия Task-ID и не променя business scope.

## 10. Правило срещу промяна на процеса

Нито GPT, Codex, нито Claude могат самостоятелно да:
- върнат Крум като ръчен посредник между агентите;
- премахнат независимия Codex audit;
- позволят Claude self-approval;
- започнат автоматично следваща задача след PASS;
- прескочат test/review стъпки;
- променят standing PC authorization;
- заменят този loop с друг.

Всяка промяна на този процес изисква ново изрично решение на Крум и актуализация на този документ.

# BEG_WORK — Правила за използване на всички `.md` файлове

> **Статус:** ЗАДЪЛЖИТЕЛНО ПРАВИЛО (repo policy)
> **Решение на Крум:** 06.10.2026
> **Отнася се за:** ChatGPT (GPT), Codex, Claude и всеки човек, който работи по BEG_WORK
> **Канонични спътници:** `coordination/DECISIONS_INDEX.md`, `CLAUDE.md`, `coordination/README.md`

## 1. Основен принцип

GitHub е общата памет на проекта.

`.md` файловете **не са еднакво важни**. Никой агент няма право да вземе случаен стар
`.md` и да го приеме за актуална истина. Всеки документ се използва според **ролята**
му, **мястото** му и **актуалността** му.

Към 06.10.2026 в `main` има **123** `.md` файла, а в coordination branch-а
`codex/claude-queue` — още 16 (`coordination/**`). Правилото не е „прочети всичко
преди всяка задача“, а „знай кой документ е канон, кой се чете според задачата и кой
е само история/доказателство“.

## 2. Задължителен ред на четене при НОВА задача

Преди implementation, review или архитектурно решение:

1. `coordination/DECISIONS_INDEX.md`
2. `CLAUDE.md`
3. `coordination/README.md`
4. `coordination/ACTIVE.md`
5. `coordination/CONTROL_STATE.json`
6. съответния `docs/flows/FLOW-xxx.md`
7. свързаните architecture документи, посочени от `DECISIONS_INDEX.md`
8. съответния предишен review от `coordination/REVIEWS/`, ако има такъв
9. actual code / diff

Не започвай работа само по текст от chat, ако GitHub вече съдържа по-ново canonical
решение.

**Стандартният BEG_WORK document resolution path е:**

```text
DECISIONS_INDEX → current task → relevant FLOW → relevant architecture
                → previous review → actual code
```

Не четем 123 файла механично преди всяка задача.

## 3. Йерархия при противоречие

| # | Ниво | Пример |
|---|---|---|
| 1 | Ново изрично решение на Крум | записано решение в правилния `.md` |
| 2 | Каноничен FLOW / архитектурен decision документ | `FLOW-016.md`, `FLOW-043.md`, `*_DECISION_*.md` |
| 3 | Wave / Gate / Tenancy канон | `IMPLEMENTATION_WAVES.md`, `IMPLEMENTATION_GATE_MATRIX.md`, `TENANCY_MODEL.md` |
| 4 | Текущо изпълнение | `coordination/ACTIVE.md` + `CONTROL_STATE.json` |
| 5 | Independent review evidence | `coordination/REVIEWS/*.md` |
| 6 | README / operational instructions | root `README.md`, `docs/ops/**` |
| 7 | historical / recovery / memory | `docs/project-recovery/**`, `memory/**` |

Стар документ **никога** не отменя по-ново канонично решение.

Ако конфликтът не може да бъде разрешен от документите → **`BLOCKED`** и се иска
решение. Агент не „избира по-удобния“ документ.

## 4. Как се използват отделните групи `.md`

### A. `docs/flows/FLOW-001.md … FLOW-050.md` — business requirements

49 файла. Използват се за: как трябва да работи системата; бизнес правила;
зависимости между модулите; какво е позволено/забранено.

Не се променят имплицитно от implementation. **Ако кодът противоречи на FLOW → кодът
е проблемът**, освен ако Крум не е променил бизнес решението.

### B. `docs/flows/FLOW-043.md` — cross-FLOW architectural decision register

`D-01…D-15` се третират като системни правила. Чете се задължително при задача, която
засяга: tenancy, finance, audit, approvals, identity, schedule, files, integrations,
cross-module relations.

### C. `docs/architecture/IMPLEMENTATION_WAVES.md` — ред на изпълнение

Source of truth за: кое се изпълнява първо; dependencies; Wave 0 → Wave 4; кой модул
може да започне и кой още е блокиран. **Агент няма право сам да прескача реда.**

### D. `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` — какво значи PASS

Определя: PASS, blocker, implementation gate, prerequisite.

> **PR merged ≠ Implementation Gate PASS. Tests passed ≠ целият FLOW е завършен.**

### E. `docs/architecture/TENANCY_MODEL.md` — tenant isolation

Задължително се чете при: API, DB, files, search, jobs, permissions, finance,
integrations, AI, migration. Никое ново решение няма право да допуска cross-tenant
leakage.

### F. Архитектурни decision документи

Конкретни архитектурни решения, не общи бележки. Четат се **преди coding** по
съответната тема: tenancy → tenancy decision; storage → storage model decision;
billing → billing/dunning decision; retention → governance/retention decision.

Групата се разпознава **по роля, не само по име на файл**. Включва и документи без
`DECISION` в името:

- `FLOW_050_*_DECISION_*.md`, `FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md`;
- `CROSS_FLOW_AUDIT_2026-07-20.md`, `CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md`,
  `CORRECTION_PASS_2026-07-20.md` — cross-FLOW audits, изброени като канонични в
  `DECISIONS_INDEX.md` §2;
- `MODERN_FIELD_EXPERIENCE_2026-08-04.md` — каноничният Wave 2 UX източник
  (`CLAUDE.md` §9 и §17, `DECISIONS_INDEX.md` §1);
- `WAVE_0_TENANCY_FOUNDATIONS.md` — Wave 0 tenancy foundations, чете се заедно с
  `TENANCY_MODEL.md`.

### G. `docs/architecture/*BUSINESS_CLOSE*.md` — доказателства

13 файла. Доказват **как** даден FLOW е бил business-closed. Използват се за история;
при спор как е взето решение; при review на старо решение.

Самият `FLOW-xxx.md` остава основният текущ business source.

### H. `docs/architecture/W0-*.md` — implementation contracts и inventories

Четат се **само когато са свързани с текущата W0 задача**.

> `W0-03...` не влияе автоматично върху `W0-06`, освен ако dependency е **изрично**
> описана в `IMPLEMENTATION_WAVES.md` или в ACTIVE assignment-а.

Тук влизат и историческите task README-та `README_P1_06C_BG.md`,
`README_P1_06E_BG.md` — те са implementation документация на стари P1 задачи, не
setup README (виж R) и не канон.

### I. `coordination/DECISIONS_INDEX.md` — навигация

**Първата навигационна точка.** Не е втори source of truth. Казва:
„за тази тема истината се намира в този документ“. GPT, Codex и Claude го използват.

При конфликт между индекса и каноничния документ важи **каноничният документ**.

### J. `coordination/ACTIVE.md` — текущо задание

Използва се само за current execution. Старите секции са history/evidence. Агент
работи **само по текущия Task-ID / Cycle-ID**.

### K. `coordination/CONTROL_STATE.json` — machine-readable статус

Source за: current agent, cycle, state, next agent, waiting_for, exact SHA, PR,
dispatch state. **При consequential action винаги се re-check-ва live.**

### L. `coordination/CONTROL_BOARD.md` — management projection

Не е независим source of truth; трябва да отразява `CONTROL_STATE.json`. При различие
→ state се счита за **stale/conflict**.

### M. `coordination/REVIEWS/*.md` — independent review evidence

Доказани дефекти, PASS, CHANGES_REQUESTED, BLOCKED, точни тестове и SHA.

**Нов correction cycle трябва да прочете предишния review.** Не се пренаписва
историята на стар verdict.

### N. `coordination/FORECAST.md` / `.json` — projection

Не е contractual truth и не е implementation PASS. При конфликт `ACTIVE.md` и
`CONTROL_STATE.json` имат предимство.

### O. `docs/ops/*.md` и `ops/**/*.md` — operational инструкции и доказателства

deploy, backup, restore, incidents, Synology, release. **Задължително се четат преди
production / NAS / deploy / restore действие.**

Production операция никога не се прави само по общо архитектурно описание.

### P. `docs/project-recovery/**` — historical recovery artifacts

Използват се за: възстановяване на история; provenance; проверка защо е взето
решение. **Не са текущ canonical source**, ако има по-нов FLOW/architecture документ.

### Q. `memory/*.md` — legacy/project memory

12 файла. Допълнителен контекст и история. Не отменя FLOW, architecture decision,
current implementation contract или ACTIVE/control state.

Ако информация от `memory/` трябва отново да стане канонична → **пренася се** в
правилния FLOW/architecture документ.

### R. README файлове

- root `README.md`, `frontend/README.md` — setup, repository structure, developer
  instructions, локално стартиране. **Не определят бизнес правила.**
- `docs/flows/README.md` и `docs/architecture/README.md` са **каталози/индекси** на
  съответните канонични групи (`CLAUDE.md` §17). Четат се за навигация, не като
  източник на бизнес правило.

### S. Evidence snapshots

`AUDIT_REPORT.md`, `test_result.md`, `backend/artifacts/flow_map.md`, временни
audit/test `.md` и генерирани inventories.

Важат само за конкретния момент, конкретния SHA и конкретния тест. **Не се използват
като текущ статус без live verification.**

Генериран документ (например `W0-06A_FILE_INVENTORY.md`) се проверява чрез
регенериране, не чрез четене.

### T. `PROMPT_TO_*.md`

Исторически/оперативни prompt файлове. **Не се изпълняват автоматично като
инструкции.** Първо се проверява дали са още актуални спрямо FLOW, architecture и
ACTIVE.

### U. Правило по подразбиране за всеки друг `.md`

Файл, който не попада в нито една от групите по-горе, се третира като
**история/доказателство (ниво 7)** и **не може** да бъде използван като канон.

Fail-closed, не fail-open: ако агент има нужда от такъв файл като основание за
решение, първо се определя канoничното му място и съдържанието се пренася там.

## 5. Правило за „стар документ“

Никой агент не изтрива стар `.md` само защото е остарял. Вместо това:

- запазва се като evidence/history;
- маркира се `superseded`, ако е необходимо;
- `DECISIONS_INDEX.md` сочи към актуалния source.

**Историята не се пренаписва.**

## 6. Правило за нов `.md`

Не създавай нов `.md`, ако информацията принадлежи в вече съществуващ canonical
документ.

Нов файл се създава само ако има собствена ясна функция: architectural decision;
implementation contract; inventory; independent review; incident; operational proof;
migration proof.

**Забранено е да се създават 3 документа с една и съща истина.**

## 7. Задължение след ново решение

Когато Крум вземе важно решение:

1. определи кой canonical документ трябва да бъде обновен;
2. запиши решението там;
3. ако е ново направление — обнови `DECISIONS_INDEX.md`;
4. ако влияе на current task — обнови `ACTIVE.md` / `CONTROL_STATE.json` / `CONTROL_BOARD.md`;
5. **не оставяй важно решение само в chat.**

## 8. Правило за GPT

- определя архитектурното значение на решението;
- намира правилния canonical `.md`;
- не измисля нов source of truth без причина;
- проверява predecessor / dependencies;
- подготвя следващия task.

## 9. Правило за Codex

- започва assignment/review от `DECISIONS_INDEX.md`;
- проверява canonical docs;
- сверява actual code с документацията;
- маркира documentation/code drift;
- **не приема Claude self-report за доказателство**;
- записва independent evidence в `coordination/REVIEWS/`.

## 10. Правило за Claude

- чете само необходимите за задачата canonical документи;
- следва exact ACTIVE assignment;
- не променя бизнес решение по собствена инициатива;
- не използва historical `.md` срещу по-нов canonical документ;
- ако срещне конфликт → **STOP** и го докладва;
- **HANDOFF описва кои canonical docs са използвани.**

## 11. Задължително правило за всички агенти

Не четем 123 файла механично преди всяка задача. Правим:

```text
DECISIONS_INDEX → current task → relevant FLOW → relevant architecture
                → previous review → actual code
```

## 12. Критично правило

Ако важна информация съществува само в ChatGPT / Claude / Codex разговор, но не и в
GitHub — **тя не се счита за надеждно предадена** към останалите агенти.

Важното решение трябва да бъде записано в правилния `.md` или coordination state.

---

## Приложение — покритие на групите

Проверено срещу `origin/main` на 06.10.2026 (123 `.md` файла) и
`origin/codex/claude-queue` (`coordination/**`, 16 файла).

| Група | Path pattern | Файлове |
|---|---|---|
| A | `docs/flows/FLOW-0NN.md` (без 043) | 49 |
| B | `docs/flows/FLOW-043.md` | 1 |
| C | `docs/architecture/IMPLEMENTATION_WAVES.md` | 1 |
| D | `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md` | 1 |
| E | `docs/architecture/TENANCY_MODEL.md` | 1 |
| F | architecture decision / cross-FLOW audit / MODERN_FIELD_EXPERIENCE / WAVE_0_TENANCY_FOUNDATIONS | 11 |
| G | `docs/architecture/*BUSINESS_CLOSE*.md` | 13 |
| H | `docs/architecture/W0-*.md` + `README_P1_*_BG.md` | 10 |
| I–N | `coordination/**` | 16 (queue branch) |
| O | `docs/ops/*.md`, `ops/**/*.md` | 7 |
| P | `docs/project-recovery/**` | 7 |
| Q | `memory/*.md` | 12 |
| R | root `README.md`, `frontend/README.md`, `docs/flows/README.md`, `docs/architecture/README.md` | 4 |
| S | `AUDIT_REPORT.md`, `test_result.md`, `backend/artifacts/flow_map.md` | 3 |
| T | `PROMPT_TO_*.md` | 2 |
| — | `CLAUDE.md` (сам по себе си канон) | 1 |

Сумата е 122 + `CLAUDE.md` = **123 от 123 файла в `main` са класифицирани; 0 остават
извън групите** (този файл е 124-ият и е част от канона по §4.I/§2). Всеки нов `.md`, който не попада
в тези групи, попада автоматично под §4.U (история/доказателство) и не е канон,
докато не бъде класифициран тук.

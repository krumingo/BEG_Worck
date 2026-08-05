# FLOW-042 — Release / QA / Test Center

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 28.07.2026  
> **Оставащи решения:** 0  
> **Implementation Gate:** Wave 0 foundation; този FLOW управлява самия технически gate  
> **Свързани FLOW:** 002, 016, 017, 033, 034, 040, 043, 044, 045 и всички FLOW-ове чрез acceptance tests

## 1. Цел

FLOW-042 превръща всяко заключено бизнес правило в проверим тест и определя кога дадена промяна е действително готова за приемане и release.

FLOW-017 описва работния процес с GitHub, ChatGPT, Claude и Emergent. FLOW-042 описва Test Case, Test Run, доказателствата, дефектите, средите, deployment връзката и финалното приемане.

```text
Business Lock
→ техническа спецификация
→ код / branch / commit / PR
→ автоматични тестове
→ deployment в точната TEST/STAGING среда
→ ръчни Test Runs
→ доказателства
→ Business Acceptance от Крум
→ production release
→ smoke test
→ rollback при нужда
```

`100% Business Lock` не означава `Implementation Gate PASS`.

## 2. Bootstrap QA Gate v0

Докато runtime Test Center още не е реализиран, се използва задължителен GitHub-based bootstrap процес.

За всяка промяна се създава versioned Markdown/YAML QA record, който съдържа:

- Test ID и FLOW;
- Business Rule ID;
- branch, commit и PR;
- предусловия и тестова среда;
- роля и permission scope;
- тестови данни;
- стъпки;
- очакван резултат;
- забранен резултат;
- correction/reversal сценарий;
- AuditEvent, DQ и Approval очаквания;
- idempotency/offline сценарий, когато е приложимо;
- evidence links — screenshot, video, log, file или API output;
- automation result;
- технически проверил;
- решение на Крум;
- release и rollback бележка.

### Bootstrap правила

- Няма `Implementation Gate PASS` само по устно твърдение или текст от Emergent/AI.
- Критичният forbidden scenario трябва да е проверен.
- Крум е единственият, който дава финалното бизнес приемане.
- Bootstrap record-ите по-късно се мигрират в Test Center без загуба на commit, evidence и решение.
- Липсата на готов runtime Test Center не е основание да няма QA record.

## 3. Каноничен тестов модел

### 3.1 Test Case

Един постоянен Test Case проверява едно конкретно бизнес правило.

Пази:

- Test ID;
- FLOW и Business Rule ID;
- заглавие и тип тест;
- приоритет;
- предусловия;
- роля и permission scope;
- тестови данни;
- стъпки;
- очакван резултат;
- забранен резултат;
- correction/reversal;
- AuditEvent очакване;
- DQ/Approval очакване;
- idempotency/offline очакване;
- какво трябва да вижда Крум.

### 3.2 Test Run

Един Test Case има много изпълнения по различни версии.

Test Run пази:

- среда;
- branch;
- commit;
- PR;
- release candidate;
- изпълнил;
- дата и час;
- резултат;
- реално поведение;
- свързани дефекти;
- доказателства;
- повторен тест.

Неуспешното изпълнение не се изтрива след поправката.

### 3.3 Business Acceptance

Финалното приемане е отделно от техническия PASS.

Крум вижда:

- какво е променено;
- какво точно трябва да провери;
- какво трябва да стане;
- какво никога не трябва да стане;
- видео, снимки и други доказателства;
- отворени дефекти и условия.

Решения:

- `Приемам`;
- `Приемам с условие`;
- `Връщам за корекция`;
- `Отказвам release`;
- `Изисквам допълнителен тест`.

Emergent, AI, разработчик или QA не могат да дадат Business Acceptance вместо Крум.

## 4. Минимален тестов пакет за всеки FLOW

- разрешен сценарий;
- забранен сценарий;
- права и опит за заобикаляне;
- корекция / reversal;
- AuditEvent история;
- Data Quality / блокировка;
- Approval, когато е приложимо;
- екранът и справката, които вижда Крум;
- повторно изпращане / idempotency;
- offline/sync;
- tenant isolation, когато е приложимо;
- regression пакет по зависимите FLOW-ове.

## 5. Тежест на дефектите

### P0 — Критичен

Примери: загуба/повреда на данни, duplicate payment, cross-tenant leakage, заобиколено критично одобрение, грешни заплати/каса/печалба, production outage, невъзможен restore.

Правило:

```text
P0 → STOP → няма release → rollback/hotfix при production → задължителен retest
```

### P1 — Висок

Основен бизнес процес не може да завърши, забранено действие може да се заобиколи, грешна роля може да одобри, offline sync дублира, корекцията унищожава историята или ключов управленски резултат е грешен.

Правило: блокира release-а на засегнатия FLOW. Изключение има само ако функцията е напълно изключена чрез доказан feature flag и не може да засегне production.

### P2 — Среден

Има безопасен временен обходен път и няма критичен финансов, сигурностен или data-integrity риск.

Може да бъде прието само като `Прието с условие`, с:

- видим дефект;
- отговорник;
- срок;
- workaround;
- изрично решение на Крум.

### P3 — Нисък

Правопис, подравняване, некритична икона или визуално подобрение. Не блокира release и влиза в backlog.

### Матрица

| Най-висок отворен дефект | Технически PASS | Business Acceptance | Release |
|---|---|---|---|
| P0 | Не | Не | Забранен |
| P1 | Не | Не | Забранен за засегнатия FLOW |
| P2 | Условно | Само `Прието с условие` | С одобрено отклонение |
| P3 | Да | Да | Разрешен |

Регресията се маркира отделно и никога не се скрива в общ процент успешни тестове.

## 6. Product Test Center и роли

### 6.1 Управленски изглед за Крум

Показва:

- release candidate;
- засегнати FLOW-ове;
- successful/failed/not-run tests;
- P0/P1/P2/P3 дефекти;
- какво да провери лично;
- линк към точната WEB test/staging среда;
- снимки, видео и логове;
- GitHub branch, commit и PR;
- production и standby версия;
- приемане, условно приемане или връщане.

### 6.2 Технически изглед

Показва Test Cases, Test Runs, automation, environment, branch, commit, PR, deployment, logs, evidence, defects и regression history.

### 6.3 Роли

- **Автор на спецификацията:** създава/версионира Test Case и очакванията.
- **Разработчик:** свързва кода, поправя дефекти и качва технически evidence; не променя очакването, за да направи теста успешен.
- **QA/тестер:** изпълнява Test Runs, Passed/Failed, дефекти, evidence и retest.
- **Технически отговорник:** потвърждава техническа готовност и severity, предлага release candidate.
- **Крум:** единствен дава финално Business Acceptance и може да изисква по-висока severity или допълнителен тест.
- **AI:** предлага тестове, forbidden cases, dependency regression и обобщения; не приема тест, не скрива failed run и не разрешава release.

## 7. Къде физически се намира Test Center

Test Center е свързана система от три места:

```text
GitHub
→ пази кода, branch/commit/PR и техническата история

TEST/STAGING WEB среда
→ мястото, където Крум реално натиска и проверява през PC

Product Test Center в BEG_Work
→ свързва теста, версията, средата, evidence и решението
```

Докато Product Test Center не е програмиран, GitHub Bootstrap QA Gate изпълнява ролята на контролен регистър, а ръчният бизнес тест се прави в отделна WEB TEST/STAGING среда — никога директно в production.

## 8. Product Test Center срещу клиентски достъп

Пълният Product Test Center е вътрешен за собственика и разработчика на продукта.

Достъп имат само упълномощени Product Owner, разработчици, QA и технически администратори.

Клиентите не виждат:

- GitHub и кода;
- вътрешните дефекти;
- други tenant-и;
- непубликувани функции;
- общия продуктов roadmap;
- вътрешния процес ChatGPT/Claude/Emergent.

За персонална разработка клиентът може да получи ограничен **Tenant Acceptance Portal**, който показва само:

- собствената му функция;
- собствената test среда и test data;
- инструкции и evidence;
- `Приемам / Има проблем`.

## 9. Release Manifest и deployment target

Всеки Test Run и deployment са свързани с точен Release Manifest:

- `target_type`: Core Product или Tenant-specific;
- `tenant_id`;
- `environment_id`;
- branch;
- `commit_sha`;
- PR;
- `release_candidate`;
- feature flags;
- migration version;
- rollback version.

Emergent не избира свободно къде да deploy-ва. Липсващо или несъвпадащо поле блокира deployment-а.

### Core Product

```text
BEG/STAGING
→ technical tests
→ Business Acceptance от Крум
→ pilot tenants
→ разрешените пакети/tenant-и
```

### Tenant-specific

```text
конкретен tenant test environment
→ feature flag ON само в test
→ Product Acceptance
→ Tenant Acceptance, когато е необходимо
→ production flag ON само за конкретния tenant
```

Production deployment е забранен без технически PASS и необходимото бизнес приемане.

## 10. Runtime release chain

```text
FLOW правило
→ Test Case
→ branch
→ commit
→ PR
→ release candidate
→ tenant/environment deployment
→ Test Runs
→ defects/retest
→ technical PASS
→ Business Acceptance
→ Tenant Acceptance при персонална разработка
→ production deployment
→ smoke test
→ rollback readiness
```

Всеки release трябва да може да бъде възстановен до точната версия и да има AuditEvent следа.

## 11. Regression Center

Промяна в един FLOW създава regression пакет за зависимите FLOW-ове чрез dependency map.

Например промяна във FLOW-006 изисква проверки на FLOW-008, 021, 028, 036 и 046, когато са засегнати.

AI може да предложи regression пакета, но техническият отговорник го потвърждава.

## 12. Какво НЕ трябва да позволява

- `100% FLOW` да се приема автоматично за готов код;
- release без forbidden scenario test;
- приемане без конкретен commit/release candidate;
- успешно състояние без evidence;
- AI/Emergent да даде Business Acceptance;
- P0/P1 или регресия да се скрият в агрегат;
- production test с реални данни вместо отделна test/staging среда;
- client да вижда Product Test Center или други tenant-и;
- deployment без tenant/environment manifest;
- tenant-specific feature да се активира за друг tenant;
- release без rollback plan.

## 13. Ново архитектурно откритие

Обсъждането установи нужда от отделен бъдещ FLOW за multi-tenant продукта:

`FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements`.

Той трябва да опише tenant isolation, memberships, subscription packages, feature entitlements, tenant environments, support access, tenant-specific flags и deployment targets.

FLOW-050 не се включва в официалната бройка FLOW-001–049, докато не бъде формално създаден и обсъден.

## 14. Връзки

- FLOW-017 — разработка и GitHub процес;
- FLOW-040 — AuditEvent / AI audit;
- FLOW-043 — Business Lock ≠ Implementation Gate;
- FLOW-044 — backup, standby и rollback;
- FLOW-002 — роли и права;
- FLOW-016 — evidence files;
- FLOW-033/034 — DQ и Approval;
- FLOW-045 — AI orchestration;
- всички FLOW-ове — техните acceptance и regression tests.

## 15. Източници / сесии

- Каноничен архив: `BEG_Work_ALL_FLOWS_001-043_CANONICAL_FULL_2026-07-15.docx`.
- Архитектурна рамка и cross-FLOW решения: FLOW-017, FLOW-043 и FLOW-044.
- Claude Cross-FLOW Logic Audit, C-07: bootstrap QA gate, 20.07.2026.
- Изрични решения на Крум за FLOW-042 от 28.07.2026: Test Case/Test Run/Business Acceptance, P0–P3, Product Test Center, Tenant Acceptance Portal, WEB TEST/STAGING, Release Manifest и deployment target.

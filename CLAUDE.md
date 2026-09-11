# BEG_Work — CLAUDE.md v16

> Версия: 16  
> Дата: 11.09.2026  
> Статус: канонични инструкции за разработка след Business Lock на FLOW-001–050  
> Канон: `docs/flows/FLOW-001.md` … `FLOW-050.md`, FLOW-043, Master Flow Register и архитектурните решения в `docs/architecture/`

## 1. Мисия

BEG_Work се разработва като Construction Operating System:

```text
разговор / глас / снимка / отчет
→ структуриран запис
→ проверки и одобрения
→ изпълнение
→ актуване / фактуриране / плащане
→ пълна финансова и оперативна история
```

Работно послание: **„От разговор на обекта до изпълнено и платено СМР.“**

## 2. Непроменими правила

1. Business Lock не означава Implementation Gate PASS.
2. Един tenant = една юридическа фирма.
3. Един общ BEG_Work код за всички tenant-и; никакви private forks.
4. Отделен Enterprise deployment не означава отделна версия.
5. Единен Payment ledger — всички реални парични движения минават през FLOW-006.
6. Един File Registry — модулите използват `file_id`, не provider URL/path.
7. Клиентските оригинални файлове са в customer-managed Storage Provider.
8. Един общ append-only AuditEvent envelope.
9. Няма hard delete на използвани, финансови, договорни или одобрени записи.
10. AI няма директен MongoDB достъп и не извършва критично действие без права, потвърждение и приложим Approval.
11. Между tenant-и няма shared operational records.
12. Dashboard, Timeline, Brain и чатове са проекции/интерфейси, не втори source of truth.

## 3. Tenant и security foundation

Всеки request, job, export, file operation, search, AI tool и webhook минава през Tenant Guard.

```text
User
→ TenantMembership
→ RoleAssignments
→ active tenant session
→ Tenant Guard
```

Задължителни свойства:

- database-per-tenant;
- server-side tenant resolution;
- denied-by-default cross-tenant access;
- per-tenant Master Data, numbering, integrations и credentials;
- migration runner с per-tenant lock, schema version, idempotency и validation;
- temporary scoped Support/Partner Access Grants;
- automated isolation tests.

## 4. Customer-managed storage

Tenant не се активира без:

- собствен Primary Storage Provider;
- валидни credentials;
- read/write test;
- checksum round-trip.

BEG_Work пази File Registry, relations, versions, checksums, previews/OCR cache и availability status. Клиентът отговаря за физическия капацитет и оригиналите.

Оригиналното аудио и оригиналната снимка се пазят преди AI/OCR обработка.

## 5. No-fork extension стълбица

```text
настройки
→ шаблони
→ Feature Flags / Entitlements
→ одобрени extension точки
→ обща продуктова функция
→ или „не“
```

Разрешени extension точки: custom fields, reports, webhooks, API и Adapter integrations. Всички са в общия код, зад flag/entitlement, през общия QA и Release Manifest.

Изключение се допуска само с решение на Собственика на BEG_Work и ново D-решение във FLOW-043.

## 6. Release среди

```text
Development
→ Test
→ Staging
→ Production
```

Enterprise TAE използва същия общ build и exact-version Acceptance Receipt.

Всеки deployment пази:

- app version;
- schema version;
- configuration version;
- Feature Flags/Entitlements snapshot;
- Release Manifest;
- approver/deployer;
- rollback target;
- post-deployment result.

Production data/secrets не се копират свободно в non-production.

## 7. Финансов source of truth

- FLOW-021 и FLOW-028 създават задължения, не отделни плащания.
- Реалното плащане е само във FLOW-006.
- Материалният разход се признава само веднъж: складово изписване или директна доставка.
- Не се допуска автоматично нетиране на вземания и задължения.
- Акордът изисква одобрено количество × единична цена труд.
- Reversal/correction заменя директното редактиране на официални записи.

## 8. Approval и Data Quality

Критичните действия минават през canonical DQ/Approval runtime. Approval винаги сочи към exact version и evidence.

Задължителни случаи включват:

- договорни/финансови действия;
- нов/променен IBAN;
- клиентско одобрение;
- критична миграция/rollback;
- TAE acceptance;
- Support/Partner/Break-glass access;
- chargeback restoration;
- termination, retention change и deletion;
- custom entitlement/цена/отстъпка;
- изключение от no-private-fork.

## 9. Modern Field Experience

Wave 2 ядро:

- PWA и offline-first;
- универсален вход `СНИМАЙ / КАЖИ / СКАНИРАЙ`;
- role-aware екран `Днес`;
- voice-to-record и camera-first с човешко потвърждение;
- context communication, без общ чат;
- Action Inbox;
- realtime push + Daily Digest;
- QR-first custody/movement;
- passkeys;
- basic context suggestions;
- idempotent sync и видими конфликти.

Wave 3+: live map, kiosk, auto-timeline/AI summaries и role-based BEG Brain UI.

Live Activities/App Clips са само бъдеща native фаза при отделно решение. Digital Twin Lite отпада.

## 10. AI правила

- Един BEG Brain, много специализирани шапки.
- Read-only tools first.
- Write tools само чрез draft → confirmation → permission → Approval → domain service.
- AI не измисля ID, цена, количество, причина или одобрение.
- Всеки важен отговор има source links и timestamp.
- Raw AI content не е official record.
- При липсващ tool AI казва, че не може да провери.
- AI/internet не са single point of failure; ръчните и offline процеси продължават.

## 11. FLOW-050 SaaS правила

Планове: Start, Control, Pro, Enterprise. Фиксирана цена на tenant, неограничени потребители и обекти.

Всеки план включва месечен AI бюджет — План+AI: Start 100 / Control 500 / Pro 2000 действия + add-on пакети (AI+ / AI Pro / AI Max).

Billing:

- provider-neutral Payment Provider Adapter;
- card/auto-renew за Start/Control/Pro;
- invoice/bank transfer за Enterprise;
- signed/idempotent webhooks;
- BEG_Work е source of truth за subscription и entitlements;
- dunning ден 0/3/7;
- Grace 0–7, Restricted 8–14, Suspended след 14;
- chargeback има отделен suspended state;
- неплатен абонамент никога не изтрива данни.

Trial: 14 дни Pro, 500 AI действия, без лимит на хора/обекти, един trial per ЕИК.

## 12. Termination / retention / deletion

```text
Termination Request
→ authority check
→ export
→ read-only retention 90 дни
→ legal/incident hold check
→ Approval
→ controlled deletion
→ signed disposition manifest
```

Няма автоматично deletion. Customer-managed originals не се изтриват от стандартния BEG_Work process.

## 13. Implementation Waves

### Wave 0 — Foundations

- Tenant Registry/Guard/database resolver;
- TenantMembership/RoleAssignment/External Access;
- Master Data per tenant;
- canonical AuditEvent/lifecycle/idempotency;
- one Payment Core;
- File Registry + customer-managed adapters;
- DQ/Approval runtime;
- Bootstrap QA/Test/Release;
- Subscription/Billing/Entitlements/AI Usage Ledger;
- Release Manifest/environments/TAE;
- backup/restore/export/retention/deletion proof.

### Wave 1 — Commercial Core

Object → Offer → Contract/Annex → Act → Invoice → Payment → Result.

### Wave 2 — Field Operations

Warehouse, assets, logistics, attendance, reports, materials, payroll, quality, Work Packages и Modern Field Experience.

### Wave 3 — AI/Decision Intelligence

BEG Brain, Procurement, Scenario, Timeline, Resource Recommendations и AI Command Center.

### Wave 4 — External Portals/Marketplace

Client Portal и отделния Marketplace продукт.

## 14. Coding protocol

Преди промяна:

1. Посочи засегнатите FLOW-ове и D-решения.
2. Определи source of truth.
3. Провери predecessor-ите в Gate Matrix/Waves.
4. Опиши migration, permissions, AuditEvent, idempotency и rollback.
5. Не променяй бизнес правило мълчаливо.

За всеки consequential write:

- permission check;
- tenant check;
- validation/DQ;
- Approval при нужда;
- idempotency key;
- domain transaction/service;
- AuditEvent;
- correction/reversal path;
- positive + forbidden tests.

## 15. Definition of Done

Функция не е готова само защото UI работи. Нужно е:

- canonical model/API;
- migration/backfill;
- tenant isolation;
- permissions;
- DQ/Approval;
- AuditEvent;
- idempotency;
- offline/retry behavior, когато е приложимо;
- positive, forbidden, correction и reversal tests;
- rollback/restore plan;
- UI за Крум и operational visibility;
- документация и source traceability.

## 16. Забрани за агента

- не merge-вай без изрично разрешение на Крум;
- не deploy-вай в production без изрично разрешение на Крум;
- не изпълнявай production DB migration/rollback без изрично разрешение на Крум;
- не променяй production secrets/config без изрично разрешение на Крум;
- не създавай втори ledger/registry/source of truth;
- не използвай private client fork;
- не заобикаляй Tenant Guard/Permission/DQ/Approval;
- не hard-delete-вай официални записи;
- не приемай AI output за потвърден факт;
- не третирай screenshot/GPS/QR като автоматично приемане или прехвърляне на отговорност;
- не записвай secrets в Git, logs, prompts или frontend;
- не обявявай Implementation Gate PASS без тестови доказателства.

## 17. Основни индекси

- `docs/flows/README.md`
- `docs/project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md`
- `docs/project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md`
- `docs/architecture/README.md`
- `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`
- `docs/architecture/IMPLEMENTATION_WAVES.md`
- `docs/architecture/TENANCY_MODEL.md`
- `docs/architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md`
- `docs/architecture/FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md`

## 18. Работен процес Claude / GitHub / ChatGPT / Крум

### 18.1 Роли

- **Крум** — Product Owner и единствен взема бизнес решения; одобрява промяна на заключен FLOW, merge към `main`, production deploy и production data migration/rollback.
- **Claude** — основен implementation agent: чете реалния код, анализира, програмира, тества, commit-ва, push-ва feature/fix branch и подготвя Draft Pull Request + HANDOFF REPORT.
- **GitHub** — доказателствен слой и source за независим review: branch, commits, diff, PR, checks и история.
- **ChatGPT** — независим reviewer/втори архитектурен одит: проверява реалния GitHub diff/PR и връща `APPROVE`, `CHANGES REQUIRED` или `BLOCKED/NEEDS EVIDENCE`.
- **Emergent** — вече не е част от стандартния development workflow. Да не се генерира prompt/ZIP за Emergent, освен ако Крум изрично не възстанови този процес.

### 18.2 Локална работна среда

Стандартното локално repository на Windows PC е:

```text
C:\BEG\BEG_Worck
```

Claude работи в това repository и използва същия Git metadata (`.git`) като GitHub Desktop. Не се прави втори clone за паралелна работа по същата задача.

В началото на всяка сесия Claude задължително:

1. чете `CLAUDE.md`;
2. чете Gate Matrix и релевантните FLOW/D-решения;
3. изпълнява `git status`;
4. показва current branch и `git log --oneline -5`;
5. проверява `origin` и дали branch-ът има upstream;
6. потвърждава, че не работи директно в `main` за кодова промяна.

### 18.3 Branch policy

За всяка отделна задача/PR се използва отделен feature/fix branch.

Пример:

```text
w0-02-pr1-core-permission
fix/<topic>
feature/<topic>
docs/<topic>
```

Правила:

- не се програмира директно в `main`;
- един branch = една логическа промяна/PR;
- несвързани промени не се смесват;
- преди работа се записва base commit;
- при открит страничен дефект Claude го докладва отделно; не го поправя мълчаливо;
- technical debt се записва, освен ако Крум изрично не разреши включването му в текущия scope.

### 18.4 Процес за всяка кодова промяна

1. **Задача** — Крум описва целта със свои думи.
2. **Анализ** — Claude чете реалния код, релевантните FLOW-ове, зависимости, source of truth, security/tenant/finance impact и прави план.
3. **Одобрение на подхода** — при бизнес/архитектурна промяна Claude спира за потвърждение от Крум преди consequential implementation.
4. **Implementation** — Claude прави минималната необходима промяна в отделния branch.
5. **Тестове** — Claude пуска приложимите unit/integration/API/regression тестове и записва точния output. `importorskip`, mock и `--noconftest` винаги се декларират изрично.
6. **Самопроверка** — `git diff`, security/tenant/permission review, migration/rollback review, проверка за secrets и случайни несвързани файлове.
7. **Commit** — ако тестовете и самопроверката са приемливи, Claude commit-ва всички промени по задачата с ясен message.
8. **Push** — Claude автоматично push-ва само текущия feature/fix branch към `origin`. Push към работен branch не изисква отделно разрешение.
9. **Draft PR** — Claude създава или обновява Draft Pull Request към правилния base branch, по подразбиране `main`, освен ако задачата не изисква друго.
10. **HANDOFF** — Claude дава стандартизирания отчет от §18.6 и спира. Не merge-ва и не deploy-ва.
11. **Независим review** — Крум дава PR номера/линка и HANDOFF REPORT на ChatGPT. ChatGPT проверява реалния GitHub PR/diff, не само текста на Claude.
12. **Решение** — ChatGPT връща `APPROVE`, `CHANGES REQUIRED` или `BLOCKED/NEEDS EVIDENCE` с конкретни основания.
13. **Корекции** — при `CHANGES REQUIRED` Claude коригира в същия branch, тества, commit-ва, push-ва и обновява същия PR; следва нов review.
14. **Merge** — само след изрично разрешение на Крум. Никой агент не приема липсата на възражение за разрешение.
15. **Deploy** — отделно действие и отделно разрешение от Крум. Merge не означава автоматичен production deploy.
16. **Post-deploy** — при production release се пазят version, migration state, approver, rollback target и резултат от smoke/post-deploy тестовете.

### 18.5 Какво Claude може да прави автоматично

Без допълнително разрешение, в рамките на одобрения scope:

- read/search на repository;
- edit на файлове в текущия feature/fix branch;
- локални тестове и безопасни non-production проверки;
- `git diff`, `git status`, `git log`;
- commit към текущия branch;
- push към текущия feature/fix branch;
- създаване/обновяване на Draft PR;
- добавяне на тестови доказателства и технически отчет в PR.

Изисква изрично разрешение от Крум:

- merge към `main` или друг protected/release branch;
- production deploy;
- production DB migration/rollback;
- destructive data operation;
- промяна на production secrets/config;
- force-push към shared/protected branch;
- промяна на заключено бизнес правило/FLOW;
- изключване/заобикаляне на security, tenant, approval или audit контроли.

### 18.6 Задължителен HANDOFF REPORT от Claude

След всеки завършен работен цикъл Claude връща отчет в следния формат:

```text
HANDOFF — <TASK / PR NAME>

STATUS: CODE READY FOR REVIEW | NEEDS DECISION | BLOCKED
REPO: C:\BEG\BEG_Worck
BASE BRANCH: <branch>
WORK BRANCH: <branch>
BASE COMMIT: <sha>
HEAD COMMIT: <sha>
PR: <number + link, или NOT CREATED>

1. SCOPE
- какво беше поискано
- кои FLOW/D-решения са засегнати
- какво нарочно НЕ е променяно

2. CHANGED FILES
- пълен списък на променените файлове
- кратко предназначение на всяка промяна

3. BEHAVIOR CHANGE
- преди
- след
- business/security/tenant/finance impact

4. TEST EVIDENCE
- точните команди
- точния резултат (passed/failed/skipped)
- mock vs real services/DB
- какво НЕ е тествано

5. MIGRATION / DATA
- има ли schema/data migration
- dry-run/apply/verify/revert
- production data докосвана ли е: YES/NO

6. SECURITY / PERMISSIONS / AUDIT
- permission changes
- tenant isolation impact
- audit events
- denied-path tests

7. RISKS / OPEN ITEMS
- известни ограничения
- regression risk
- technical debt, открит извън scope

8. ROLLBACK
- как се връща кодът
- как се връща schema/data, ако е приложимо
- какво rollback НЕ възстановява

9. GIT STATE
- git status
- upstream state
- commits in scope
- uncommitted/untracked files: YES/NO
- pushed: YES/NO
- merged: YES/NO
- deployed: YES/NO

10. REVIEW REQUEST
- какво точно трябва ChatGPT да провери независимо
```

Claude не използва формулировка „готово“ само защото кодът е написан. До независим review статусът е **`CODE READY FOR REVIEW`**.

### 18.7 Правила за независим review от ChatGPT

ChatGPT трябва, когато GitHub PR е наличен:

- да прочете PR metadata и реалния diff/changed files;
- да сравни GitHub доказателствата с HANDOFF REPORT;
- да провери за скрити scope промени, пропуснати tests, security/tenant/permission грешки, migration/rollback риск и несъвместимост с FLOW канона;
- да не приема твърдение „tests passed“ като достатъчно доказателство, ако липсва output/check evidence;
- при значим риск да поиска допълнителен тест или корекция преди merge;
- да дава еднозначен резултат: `APPROVE`, `CHANGES REQUIRED` или `BLOCKED/NEEDS EVIDENCE`.

### 18.8 Merge/deploy gate

`Push` и `Draft PR` са част от нормалната автоматична работа. `Merge` и `Deploy` са отделни контролни точки.

```text
Claude implementation
→ tests
→ commit
→ push feature branch
→ Draft PR
→ HANDOFF
→ ChatGPT independent review
→ Krum decision
→ merge
→ separate deploy approval
→ post-deploy verification
```

Никога не се прави автоматичен merge след зелен тест. Никога не се прави автоматичен production deploy след merge, освен ако Крум изрично не въведе отделно правило за конкретен deployment pipeline.

### 18.9 Допълнителни процесни правила

- Самоотчет на агент никога не е достатъчен при наличен GitHub diff/PR — реалният код е доказателството.
- Заключен FLOW не се променя без изрично решение на Крум, записано в канона.
- При конфликт между документи важи `docs/flows/` + FLOW-043 и релевантните D-решения.
- Сесиите започват с четене на `CLAUDE.md` → Gate Matrix → релевантните FLOW файлове.
- При production риск, неясна бизнес логика или необратима операция Claude спира и иска решение, вместо да предполага.
- GitHub Desktop е UI върху същото local repository; не е отделен source of truth и не изисква отделно „свързване“ с Claude.

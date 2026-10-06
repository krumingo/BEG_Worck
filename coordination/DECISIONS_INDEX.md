# BEG_WORK — Decisions Index

> **На човешки:** Това е централният индекс на важните решения за BEG_WORK. Той не дублира каноничните документи, а показва кое решение къде живее и кое е source of truth.
>
> **Правило:** при конфликт между този индекс и каноничния документ важи каноничният документ. Този файл е навигация и управленска карта, не втори източник на истина.

Последна актуализация: 2026-10-06

---

## 1. Основни source-of-truth документи

Правилото за избор и ред на четене е [docs/MD_USAGE_POLICY.md](../docs/MD_USAGE_POLICY.md). Този индекс остава само навигация.

| Тема | Каноничен източник | Какво решава |
|---|---|---|
| FLOW каталог | [docs/flows/README.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/README.md) | Индекс на бизнес FLOW-овете |
| Архитектурни решения D-01…D-15 | [FLOW-043.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/FLOW-043.md) | Cross-FLOW архитектурни решения |
| Wave ред и зависимости | [IMPLEMENTATION_WAVES.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/IMPLEMENTATION_WAVES.md) | Каноничен ред W0-01…W0-11 и следващите Waves |
| Implementation gates | [IMPLEMENTATION_GATE_MATRIX.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/IMPLEMENTATION_GATE_MATRIX.md) | Какво означава PASS / blocker / gate |
| Tenancy | [TENANCY_MODEL.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/TENANCY_MODEL.md) | Tenant isolation, ownership и server-side active tenant |
| Master Data contract | [W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md) | Каноничен Master Data модел |
| File Registry business contract | [FLOW-016.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/FLOW-016.md) | File Registry, provider abstraction, versions, checksums, relations |
| Permissions | [FLOW-002.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/FLOW-002.md) | Роли, permissions и access checks |
| Audit | [FLOW-040.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/FLOW-040.md) | AuditEvent и traceability |
| Modern field UX | [MODERN_FIELD_EXPERIENCE_2026-08-04.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md) | PWA/offline/voice/photo/field experience |

---

## 2. Архитектурни decision документи

Тези файлове са канонични решения по конкретни теми. Индексът не преразказва съдържанието им.

- [FLOW_050_TENANCY_DECISION_2026-07-29.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_TENANCY_DECISION_2026-07-29.md)
- [FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_STORAGE_MODEL_CHANGE_2026-08-03.md)
- [FLOW_050_PLAN_PLUS_AI_DECISION_2026-08-03.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_PLAN_PLUS_AI_DECISION_2026-08-03.md)
- [FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_SUBSCRIPTION_BILLING_DUNNING_DECISION_2026-08-04.md)
- [FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_TRIAL_DEMO_PARTNER_DECISION_2026-08-04.md)
- [FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_050_FINAL_GOVERNANCE_ENVIRONMENTS_RETENTION_DECISION_2026-08-04.md)
- [CROSS_FLOW_AUDIT_2026-07-20.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/CROSS_FLOW_AUDIT_2026-07-20.md)
- [CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)
- [CORRECTION_PASS_2026-07-20.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/CORRECTION_PASS_2026-07-20.md)

---

## 3. Business-close решения

Съществуващите business-close документи остават отделни канонични доказателства:

- FLOW-010 — [FLOW_010_BUSINESS_CLOSE_2026-07-21.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_010_BUSINESS_CLOSE_2026-07-21.md)
- FLOW-012 — [FLOW_012_BUSINESS_CLOSE_2026-07-24.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_012_BUSINESS_CLOSE_2026-07-24.md)
- FLOW-025 — [FLOW_025_BUSINESS_CLOSE_2026-07-21.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_025_BUSINESS_CLOSE_2026-07-21.md)
- FLOW-036 — [FLOW_036_BUSINESS_CLOSE_2026-07-22.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_036_BUSINESS_CLOSE_2026-07-22.md)
- FLOW-037 — [FLOW_037_BUSINESS_CLOSE_2026-07-25.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_037_BUSINESS_CLOSE_2026-07-25.md)
- FLOW-038 — [FLOW_038_BUSINESS_CLOSE_2026-07-28.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_038_BUSINESS_CLOSE_2026-07-28.md)
- FLOW-039 — [FLOW_039_BUSINESS_CLOSE_2026-07-28.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_039_BUSINESS_CLOSE_2026-07-28.md)
- FLOW-040 — [FLOW_040_BUSINESS_CLOSE_2026-07-21.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_040_BUSINESS_CLOSE_2026-07-21.md)
- FLOW-041 — [FLOW_041_BUSINESS_CLOSE_2026-07-27.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_041_BUSINESS_CLOSE_2026-07-27.md)
- FLOW-042 — [FLOW_042_BUSINESS_CLOSE_2026-07-28.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_042_BUSINESS_CLOSE_2026-07-28.md)
- FLOW-046 — [FLOW_046_BUSINESS_CLOSE_2026-07-23.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_046_BUSINESS_CLOSE_2026-07-23.md)
- FLOW-048 — [FLOW_048_BUSINESS_CLOSE_2026-07-28.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_048_BUSINESS_CLOSE_2026-07-28.md)
- FLOW-049 — [FLOW_049_BUSINESS_CLOSE_2026-07-29.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/FLOW_049_BUSINESS_CLOSE_2026-07-29.md)

---

## 4. Координационни решения — GPT / Codex / Claude

Каноничният coordination source of truth е branch `codex/claude-queue`.

- [coordination/README.md](README.md) — protocol и правила за работа;
- [coordination/AGENT_EXECUTION_LOOP.md](AGENT_EXECUTION_LOOP.md) — заключен GPT → Codex → Claude → Codex execution/review loop и standing PC/Computer Use authorization;
- [coordination/AGENT_EVENT_PROTOCOL.md](AGENT_EVENT_PROTOCOL.md) — задължителен append-only GitHub event stream за всяка смислена стъпка на Codex/Claude;
- [coordination/ACTIVE.md](ACTIVE.md) — само текущото активно задание;
- [coordination/CONTROL_STATE.json](CONTROL_STATE.json) — machine-readable статус;
- [coordination/CONTROL_BOARD.md](CONTROL_BOARD.md) — management dashboard projection;
- [coordination/REVIEWS/](REVIEWS/) — независими Codex review-и;
- [coordination/FORECAST.md](FORECAST.md) / [FORECAST.json](FORECAST.json) — forecast projection.

### Заключени правила на coordination loop

1. **ChatGPT = архитект / business-system designer.**
2. **Codex = technical lead / независим QA / coordinator.**
3. **Claude = implementation worker.**
4. **GitHub = shared source of truth.**
5. Една implementation задача наведнъж: GPT подготвя → Крум предава веднъж на Codex → Codex dispatch-ва Claude → exact-head HANDOFF → независим Codex review → при технически дефект в същия Task-ID Codex сам dispatch-ва correction към Claude → review loop до PASS или истински blocker → Codex връща PASS към GPT.
6. `PASS`, `CHANGES_REQUESTED` и `BLOCKED` са review verdict-и, не agent activity states.
7. Междинен push не е HANDOFF.
8. Merge, deploy, production migration, credentials и необратими production действия искат отделно изрично решение.
9. Всеки task започва с **„На човешки:“** и същият текст се проектира в dashboard.
10. Dashboard management текстът е на български.
11. Периодичен polling/monitor за активна BEG_WORK implementation задача е **забранен по подразбиране**.
12. След `CHANGES_REQUESTED`, ако поправката е техническа и остава в вече одобрения Task-ID/business scope, Codex сам създава и dispatch-ва bounded correction към Claude; Крум не е ръчен relay. Само business/security/production blocker спира за Крум.
13. Нов review се прави само след нов final exact-head HANDOFF.
14. Krum не е execution `next_agent` и не е ръчен посредник между Codex и Claude; human decisions са отделни от agent routing.
15. Two-phase protocol: INTENT/PENDING преди действие; OBSERVED/CONFIRMED след реално доказано действие.
16. **Standing PC/Computer Use:** Codex и Claude имат постоянно разрешение от Крум да използват наличния PC/Computer Use канал за assignment/correction dispatch, HANDOFF обратно към Codex и final PASS/result към GPT, в рамките на одобрения Task-ID. Merge/deploy/production/credentials/destructive/security-exception действия остават извън това разрешение.
17. След PASS Codex не стартира следващ Task-ID; GPT проверява резултата, актуализира управленската картина и подготвя следващата по графика задача.
18. **GitHub event stream:** Codex и Claude публикуват структурирани append-only events в текущия Task Issue при приемане, четене, preflight, dispatch attempt/success/failure, implementation, tests, HANDOFF, review, findings, corrections, PASS/BLOCKED и финално връщане на резултата. Silent failure е забранен; event stream с exact evidence има предимство пред изостанал dashboard projection.

Каноничните формулировки на тези правила са в [coordination/README.md](README.md).

---

## 5. Implementation решения и независими review-и

### W0-03 — Master Data

- [W0-03C review](REVIEWS/W0-03C.md)
- [W0-03D review](REVIEWS/W0-03D.md)
- [W0-03E review](REVIEWS/W0-03E.md)
- [W0-03E-R1 review](REVIEWS/W0-03E-R1.md)
- [W0-03E-A1 review](REVIEWS/W0-03E-A1.md)
- [W0-03E-A2 review](REVIEWS/W0-03E-A2.md)
- [W0-03E-A2B review](REVIEWS/W0-03E-A2B.md)
- [W0-03E-A2C review](REVIEWS/W0-03E-A2C.md)

Свързани архитектурни/миграционни документи:
- [W0-03C_UNIQUENESS_READINESS.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03C_UNIQUENESS_READINESS.md)
- [W0-03E_LEGACY_MIGRATION.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E_LEGACY_MIGRATION.md)
- [W0-03E-A1_INVENTORY.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E-A1_INVENTORY.md)
- [W0-03E-A2_PROJECT_TEAM_INVENTORY.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E-A2_PROJECT_TEAM_INVENTORY.md)
- [W0-03E-A2B_INVENTORY.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E-A2B_INVENTORY.md)
- [W0-03E-A2B_SINGLE_TENANT_BACKFILL.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md)
- [W0-03E-A2C_INVENTORY.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/W0-03E-A2C_INVENTORY.md)

### W0-06 — File Registry

- [W0-06A review](REVIEWS/W0-06A.md)
- [W0-06B review](REVIEWS/W0-06B.md)

Current implementation references:
- Issue #43 — W0-06A
- Draft PR #44 — W0-06A predecessor, unmerged
- Issue #45 — W0-06B
- Draft PR #46 — W0-06B current package

Текущият active cycle и exact SHA не се поддържат ръчно тук. Винаги се четат от:
- [ACTIVE.md](ACTIVE.md)
- [CONTROL_STATE.json](CONTROL_STATE.json)
- [CONTROL_BOARD.md](CONTROL_BOARD.md)

Така този индекс не остарява при всеки commit.

---

## 6. Важни продуктови решения, които не трябва да се губят

Това са кратки указатели към вече заключени правила; пълното съдържание остава в canonical FLOW/architecture документите.

### File Registry
- Клиентските оригинали не се хостват от BEG_WORK.
- Всеки tenant трябва да има customer-managed Primary Storage Provider.
- Модулите използват стабилен `file_id`, не provider path/URL като business identity.
- Един файл може да има много business relations без физическо дублиране.
- Версиите не се презаписват тихо.
- Preview/OCR/cache не стават canonical original.
- Cross-tenant file access е забранен.

Source: [FLOW-016.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/flows/FLOW-016.md).

### Tenancy
- Един tenant = една юридическа компания.
- Active tenant се определя server-side.
- Standard model = DB-per-tenant.
- Role/permission в tenant A не дава права в tenant B.
- Всеки tenant-owned operational/business record носи tenant ownership.
- Isolation tests са задължителни.

Source: [TENANCY_MODEL.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/TENANCY_MODEL.md).

### Wave execution order
Каноничният ред след W0-02 е този в [IMPLEMENTATION_WAVES.md](https://github.com/krumingo/BEG_Worck/blob/main/docs/architecture/IMPLEMENTATION_WAVES.md). Не се поддържа второ копие на реда тук.

---

## 7. Как се добавя ново решение

Добавяй в този индекс само когато има поне едно от следните:

- ново архитектурно решение;
- нов/променен business rule;
- нов canonical документ;
- важен implementation PASS / CHANGES_REQUESTED / BLOCKED със самостоятелно доказателство;
- промяна на coordination protocol;
- промяна на Wave dependency/order.

Не добавяй:
- временни chat реплики;
- междинни SHA-та без lifecycle значение;
- transient WORKING status;
- дублиран текст от FLOW;
- предположения без canonical evidence.

При ново решение:
1. запиши пълното решение в правилния canonical документ;
2. добави линк/кратко описание тук;
3. ако влияе на изпълнението, обнови ACTIVE/CONTROL_STATE/CONTROL_BOARD отделно.

---

## 8. Какво този файл НЕ е

- не е пълен transcript на ChatGPT разговорите;
- не е заместител на FLOW документите;
- не е заместител на архитектурните decision файлове;
- не е live control state;
- не дава автоматично разрешение за merge/deploy/production действие;
- не променя Implementation Gate статус само с наличието си.

Целта му е една: **всеки агент или човек да може бързо да намери къде е взето дадено важно решение и кой документ е каноничният източник.**

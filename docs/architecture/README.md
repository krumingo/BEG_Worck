# BEG_Work — Architecture and Implementation Index

> **Обхват:** бизнес FLOW документация, FLOW-срещу-FLOW логика и текущият `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.  
> **PR статус:** Draft; не се слива преди изрично решение на Крум.

## Основни документи

1. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)  
   Потвърдените корекции по FLOW-008, FLOW-025, D-07 и D-12–D-14.

2. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)  
   Проверка на FLOW-001–049 срещу реалния backend/runtime код.

3. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)  
   Независима проверка FLOW срещу FLOW: пари, материали, труд, AI, външен достъп и зависимости.

4. [FLOW-010 Business Close — 21.07.2026](FLOW_010_BUSINESS_CLOSE_2026-07-21.md)  
   Комуникация, AI summary, client approval cards, verified bank accounts и финансов профил.

5. [FLOW-025 Business Close — 21.07.2026](FLOW_025_BUSINESS_CLOSE_2026-07-21.md)  
   Document requirements и lifecycle матрици преди актуване, фактуриране, плащане и project transitions.

6. [FLOW-036 Business Close — 22.07.2026](FLOW_036_BUSINESS_CLOSE_2026-07-22.md)  
   Object Timeline, project/subproject pause, blocked work, Pause Impact, filters, finance и AI summaries.

7. [FLOW-040 Business Close — 21.07.2026](FLOW_040_BUSINESS_CLOSE_2026-07-21.md)  
   AuditEvent retention, append-only/tamper-evident storage, legal hold и L0–L5 visibility.

8. [FLOW-046 Business Close — 23.07.2026](FLOW_046_BUSINESS_CLOSE_2026-07-23.md)  
   Hybrid client access, corporate representatives, allowlist visibility, contextual communication и exact-version ApprovalReceipt.

9. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)  
   Статус по всеки FLOW: foundation blocker, refactor, business-open, ready wave или legacy.

10. [Implementation Waves](IMPLEMENTATION_WAVES.md)  
    Безопасен ред: Wave 0 Foundation → Commercial Core → Field Operations → AI → Portals/Marketplace.

11. [FLOW Documentation Index](../flows/README.md)  
    Индекс към FLOW-001–049.

12. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)  
    Бизнес готовност и оставащи решения.

13. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)  
    Решения D-01–D-14 и източниците им.

## Текущ бизнес статус

- Общо FLOW-ове: **49**
- 100% Business Lock: **40**
- Активни незавършени: **8**
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **40**

Последните business-close pass-ове затвориха:

- FLOW-010 — Clients / Contacts / Counterparties;
- FLOW-025 — Document Control;
- FLOW-035 — Work Package Engine;
- FLOW-036 — Object Timeline;
- FLOW-040 — AuditEvent / AI Audit Log;
- FLOW-045 — AI Command Center;
- FLOW-046 — Client Portal.

И уточниха:

- object-scoped internal/client communication и AI summaries със source links;
- exact-version approval cards и ApprovalReceipt;
- VerifiedBankAccount и финансов профил без automatic netting;
- project/subproject `Временно спрян` срещу WorkPackage/СМР `Блокирано`;
- Pause Impact Assessment и Timeline summaries;
- hybrid client access: secure link, persistent profile и corporate representatives;
- allowlist client visibility и safe projections;
- Comment / Question / DecisionRequest / OfficialNotice context threads;
- `прочетено ≠ одобрено` и free-text `ОК` ≠ exact-version approval;
- versioned document requirements и unallocated-payment rule;
- R1–R6 audit retention, legal hold и L0–L5 visibility;
- Bootstrap QA Gate v0 и ExternalPrincipal/AccessGrant foundations.

## Главен технически извод

Документацията е по-зряла от общите runtime foundations. Съществуващата domain логика трябва да се запази, но преди масово добавяне на features са нужни:

- RoleAssignment, ExternalPrincipal/client membership и централизирани права;
- Master Data и migration map;
- canonical append-only AuditEvent, retention, integrity и visibility;
- soft-delete и idempotency;
- един payment write service;
- provider-neutral File Registry;
- Data Quality и Approval Center runtime;
- Bootstrap QA/acceptance test/release framework;
- backup/restore доказателства.

## Wave 0 — задължителна основа

1. FLOW-002 — Permission Service + External Access Grants.
2. FLOW-032 — Master Data foundation.
3. FLOW-040/043 — AuditEvent, lifecycle, idempotency, retention и visibility.
4. FLOW-006 — Payment Core.
5. FLOW-016 — File Registry.
6. FLOW-033/034 — Data Quality + Approval.
7. FLOW-042 — Bootstrap QA и Test/Release foundation.
8. FLOW-044 — Disaster Recovery.

## Следващ business-close приоритет

1. FLOW-012, FLOW-037, FLOW-041 и FLOW-042 — по 4 решения.
2. FLOW-038 и FLOW-039 — по 5 решения.
3. FLOW-048 — 6 решения.
4. FLOW-049 — 8 решения.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Не променя приложния код или базата.
- FLOW-001–049 имат секция `Източници / сесии`.
- Master Flow Register, Decision Register и отделните FLOW файлове трябва да съвпадат преди merge.
- След merge документацията ще стане обща основа за ChatGPT, Claude, Emergent и разработчиците.
- Feature implementation не получава PASS без permission, migration, tests, audit, idempotency, DQ/Approval и rollback/restore plan.
- До пълния Test Center се използва Bootstrap QA Gate v0.

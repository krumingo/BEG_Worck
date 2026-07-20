# BEG_Work — Architecture and Implementation Index

> **Обхват:** бизнес FLOW документация, FLOW-срещу-FLOW логика и текущият `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.  
> **PR статус:** Draft; не се слива преди следващите business-close решения на Крум.

## Основни документи

1. [Correction Pass — 20.07.2026](CORRECTION_PASS_2026-07-20.md)  
   Потвърдените корекции по FLOW-008, FLOW-025, D-07 и D-12–D-14.

2. [Cross-FLOW Code Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)  
   Двадесет находки от проверката на FLOW-001–049 срещу реалния backend/runtime код.

3. [Claude Cross-FLOW Logic Audit — 20.07.2026](CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)  
   Независима проверка FLOW срещу FLOW: пари, материали, труд, AI, външен достъп и зависимости. Съдържа решенията C-01–C-08.

4. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)  
   Статус по всеки FLOW: foundation blocker, refactor, business-open, ready wave или legacy.

5. [Implementation Waves](IMPLEMENTATION_WAVES.md)  
   Безопасен ред: Wave 0 Foundation → Commercial Core → Field Operations → AI → Portals/Marketplace.

6. [FLOW Documentation Index](../flows/README.md)  
   Индекс към отделните документи FLOW-001–049.

7. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)  
   Бизнес готовност и оставащи решения.

8. [Decision Register](../project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md)  
   Синхронизираните решения D-01–D-14 и техните източници.

## Текущ бизнес статус

- Общо FLOW-ове: **49**
- 100% Business Lock: **35**
- Активни незавършени: **13**
- Legacy: **1** — FLOW-018 → FLOW-039
- Оставащи конкретни решения: **53**

Последният logic-audit pass затвори:

- FLOW-035 — Work Package Engine;
- FLOW-045 — AI Command Center.

И уточни:

- Interim Approval Receipt преди пълния Client Portal;
- финансовото/KPI третиране на престоя;
- management bonus line types и VAT-neutral formula;
- Bootstrap QA Gate v0;
- ExternalPrincipal/AccessGrant за magic links.

## Главен технически извод

Документацията е по-зряла от общите runtime foundations. Съществуващият код има значителна работеща domain логика, която трябва да бъде запазена, но преди масово добавяне на features са нужни общи услуги за:

- RoleAssignment, ExternalPrincipal и централизирани права;
- Master Data и migration map;
- AuditEvent, soft-delete и idempotency;
- един payment write service;
- provider-neutral File Registry;
- Data Quality и Approval Center runtime;
- Bootstrap QA/acceptance test/release framework;
- backup/restore доказателства.

## Wave 0 — задължителна основа

1. FLOW-002 — Permission Service + External Access Grants.
2. FLOW-032 — Master Data foundation.
3. FLOW-040/043 — AuditEvent/lifecycle/idempotency.
4. FLOW-006 — Payment Core.
5. FLOW-016 — File Registry.
6. FLOW-033/034 — Data Quality + Approval.
7. FLOW-042 — Bootstrap QA и Test/Release foundation.
8. FLOW-044 — Disaster Recovery.

## Следващ business-close приоритет

1. FLOW-025 и FLOW-040 — по 2 решения.
2. FLOW-010, FLOW-036 и FLOW-046 — по 3 решения.
3. FLOW-012, FLOW-037, FLOW-041 и FLOW-042 — по 4 решения.

## Правило за PR и release

- PR #2 остава Draft до изрично решение на Крум.
- Не променя приложния код или базата.
- FLOW-001–049 имат стандартна секция `Източници / сесии`.
- Master Flow Register, Decision Register и отделните FLOW файлове трябва да съвпадат преди merge.
- След merge документацията ще стане обща основа за ChatGPT, Claude, Emergent и разработчиците.
- Feature implementation не получава PASS без permission, migration, tests, audit, idempotency, DQ/Approval и rollback/restore план.
- До пълния Test Center се използва Bootstrap QA Gate v0.

# BEG_Work — Architecture and Implementation Index

> **Обхват:** бизнес FLOW документация срещу текущия `main` код  
> **Правило:** `100% Business Lock` не означава автоматично `Implementation Gate PASS`.

## Основни документи

1. [Cross-FLOW Implementation Audit — 20.07.2026](CROSS_FLOW_AUDIT_2026-07-20.md)  
   Двадесет находки от проверката на FLOW-001–049 срещу реалния backend/runtime код.

2. [Implementation Gate Matrix](IMPLEMENTATION_GATE_MATRIX.md)  
   Статус по всеки FLOW: foundation blocker, refactor, business-open, ready wave или legacy.

3. [Implementation Waves](IMPLEMENTATION_WAVES.md)  
   Безопасен ред за паралелно програмиране: Wave 0 Foundation → Commercial Core → Field Operations → AI → Portals/Marketplace.

4. [FLOW Documentation Index](../flows/README.md)  
   Индекс към отделните документи FLOW-001–049.

5. [Master Flow Register](../project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md)  
   Бизнес готовност и оставащи решения.

## Главен технически извод

Документацията е по-зряла от общите runtime foundations. Съществуващият код има значителна работеща domain логика, която трябва да бъде запазена, но преди масово добавяне на нови features са нужни общи услуги за:

- RoleAssignment и централизирани права;
- Master Data и migration map;
- AuditEvent, soft-delete и idempotency;
- един payment write service;
- provider-neutral File Registry;
- Data Quality и Approval Center runtime;
- acceptance test/release framework;
- backup/restore доказателства.

## Wave 0 — задължителна основа

1. FLOW-002 — Permission Service.
2. FLOW-032 — Master Data foundation.
3. FLOW-040/043 — AuditEvent/lifecycle/idempotency.
4. FLOW-006 — Payment Core.
5. FLOW-016 — File Registry.
6. FLOW-033/034 — Data Quality + Approval.
7. FLOW-042 — Test/Release foundation.
8. FLOW-044 — Disaster Recovery.

## Правило за PR и release

- Този PR е документационен и остава Draft до преглед от Крум.
- Не променя приложния код или базата.
- След merge документацията става обща основа за ChatGPT, Claude, Emergent и разработчиците.
- Feature implementation не получава PASS без permission, migration, tests, audit, idempotency, DQ/Approval и rollback/restore план.

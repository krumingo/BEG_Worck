# BEG_Work — Табло за изпълнение

> Актуално към: 05.08.2026  
> Статус на документацията: FLOW-001–050 Business Lock приключен  
> PR: Draft PR #2 — готов за последна проверка, без merge  
> Следващ етап: Wave 0 — Architecture Foundations

## 1. Общ статус

| Показател | Стойност |
|---|---:|
| Общо FLOW-ове | 50 |
| Business Lock | 49 |
| Legacy | 1 — FLOW-018 → FLOW-039 |
| Активни незавършени FLOW-ове | 0 |
| Оставащи бизнес решения | 0 |
| Implementation Gate PASS | 0 — започва Wave 0 |
| PR #2 | Draft / Open / Mergeable / Not merged |

## 2. Етапи

| Етап | Статус | Следващо действие |
|---|---|---|
| Business design FLOW-001–050 | ✅ Завършен | Само контролирани промени чрез FLOW/D-решение |
| Финален документационен одит | ✅ Завършен | Поддържане на синхрон между регистрите |
| CLAUDE.md v15 | ✅ Създаден | Да стане оперативна инструкция след merge |
| Табло | ✅ Създадено | Обновяване след всеки Wave 0 PR |
| Merge на PR #2 | ⏸ Чака решение на Крум | Изрично разрешение |
| Wave 0 coding | ⏳ Не е започнал | Започва след merge |

## 3. Wave 0 — основни работни потоци

| ID | Работен поток | Статус | Основен резултат |
|---|---|---|---|
| W0-01 | Permission Service | ⬜ Не е започнат | RoleAssignment, ExternalPrincipal, AccessGrant, migration |
| W0-02 | Tenant Foundation | ⬜ Не е започнат | Tenant Registry, Guard, DB resolver, memberships |
| W0-03 | Master Data | ⬜ Не е започнат | Per-tenant Master entities, aliases, merge, uniqueness |
| W0-04 | Audit/Lifecycle/Idempotency | ⬜ Не е започнат | Canonical append-only AuditEvent и correction/reversal |
| W0-05 | Payment Core | ⬜ Не е започнат | Един payment write service и obligations/allocations |
| W0-06 | File Registry/Storage | ⬜ Не е започнат | Customer-managed provider onboarding и adapters |
| W0-07 | Data Quality + Approval | ⬜ Не е започнат | Canonical DQ issues и Approval runtime |
| W0-08 | Subscription/Billing | ⬜ Не е започнат | Plans, entitlements, AI Usage Ledger, dunning, chargeback |
| W0-09 | Release/Environments | ⬜ Не е започнат | Release Manifest, Dev/Test/Staging/Prod, TAE, rollback |
| W0-10 | QA Foundation | ⬜ Не е започнат | Bootstrap QA Gate, isolation/migration/forbidden tests |
| W0-11 | Disaster Recovery | ⬜ Не е започнат | Per-tenant backup/restore/export proof |
| W0-12 | Retention/Deletion | ⬜ Не е започнат | Export, 90-day retention, holds, controlled deletion |

## 4. Препоръчан ред за първите PR-и

```text
PR-W0-01  Bootstrap QA + ADR/schema skeleton
→ PR-W0-02 Tenant Registry + Tenant Guard + DB resolver
→ PR-W0-03 TenantMembership + RoleAssignment + External Access
→ PR-W0-04 AuditEvent + idempotency foundation
→ PR-W0-05 Master Data per tenant
→ PR-W0-06 File Registry + customer-managed provider activation
→ PR-W0-07 Payment Core
→ PR-W0-08 DQ + Approval runtime
→ PR-W0-09 Subscription/Billing/Entitlements/AI Usage
→ PR-W0-10 Release Manifest/environments/TAE
→ PR-W0-11 Backup/restore/export/retention/deletion proof
```

## 5. Wave 0 блокиращи критерии

Wave 0 не приключва, докато не са доказани:

- server-side active tenant resolution;
- cross-tenant read/write denial за API, files, search, export и AI;
- membership-scoped RoleAssignments;
- migration runner с per-tenant version/result;
- единен append-only AuditEvent;
- idempotent critical writes;
- единен Payment ledger;
- customer-managed Storage Provider activation test;
- canonical DQ/Approval runtime;
- signed/idempotent billing webhooks;
- environment-specific Release Manifest;
- per-tenant backup/restore/export;
- billing state никога да не стартира deletion;
- retention/hold/Approval/disposition manifest tests.

## 6. Рискове, които да не се допускат

| Риск | Контрол |
|---|---|
| Разработка на функции преди tenancy foundation | Gate Matrix блокира feature PR-а |
| Втори payment/file/audit регистър | Source-of-truth review преди код |
| Shared operational records между фирми | Tenant isolation tests |
| Private Enterprise fork | Common code + Release Manifest + FLOW-043 exception rule |
| Secrets в frontend/Git | Server-side encrypted credentials и secret scanning |
| AI write без контрол | Draft → Confirm → Permission → Approval → Domain service |
| Offline дубликати | idempotency keys + conflict review |
| Автоматично изтриване при неплащане | Отделен termination/retention/deletion state machine |

## 7. Следващо решение на Крум

```text
Разрешавам merge на Draft PR #2 в main
```

След това:

1. PR #2 се слива в `main`;
2. създава се първият Wave 0 coding branch/PR;
3. таблото се обновява с реален owner, срок, commit/PR и test evidence за всяка W0 задача.

## 8. Канонични връзки

- `CLAUDE.md`
- `docs/flows/README.md`
- `docs/project-recovery/2026-07-20/03_MASTER_FLOW_REGISTER_SEED.md`
- `docs/project-recovery/2026-07-20/04_DECISION_REGISTER_SEED.md`
- `docs/architecture/IMPLEMENTATION_GATE_MATRIX.md`
- `docs/architecture/IMPLEMENTATION_WAVES.md`
- `docs/architecture/WAVE_0_TENANCY_FOUNDATIONS.md`

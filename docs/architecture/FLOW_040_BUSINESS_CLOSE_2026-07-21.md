# FLOW-040 Business Close — 21.07.2026

> **FLOW:** AuditEvent / AI Audit Log  
> **Резултат:** 65% → **100% Business Lock**  
> **PR:** Draft PR #2 — не се слива автоматично

## Затворени решения

### 1. Retention и immutable storage

Въведени са канонични класове:

| Клас | Съдържание | Минимален срок |
|---|---|---:|
| R1 CRITICAL_BUSINESS | договори, approvals, плащания, payroll, bank changes, permissions, critical AI actions | 10 години след приложимата anchor дата |
| R2 PROJECT_OPERATIONAL | reports, warehouse, logistics, assets, Work Packages, quality | 7 години след project/package close |
| R3 SECURITY_ACCESS | login, denied access, session/device security metadata | 2 години |
| R4 AI_CONTENT | raw prompt/response, ако не е official evidence | 12 месеца |
| R5 TECHNICAL_DIAGNOSTIC | debug/performance traces | 90 дни |
| R6 LEGAL_OR_INCIDENT_HOLD | спор, проверка, incident, investigation | до изрично освобождаване |

Structured AI action metadata и човешкото потвърждение наследяват R1/R2/R3 според официалното действие. Използван фрагмент от разговор се заключва като AuditEvidence и наследява срока на source record-а.

Минималната архитектура е append-only event store + correction events + hash chain/signed manifests + immutable/WORM archive + off-site backup по FLOW-044.

### 2. Ролева видимост

Нивата са:

```text
L0 Personal
L1 Scoped Operational
L2 Sensitive Domain
L3 Full Tenant Audit
L4 Export / Forensics
L5 Break-glass Platform Access
```

Основни правила:

- Крум/Owner има full-tenant read-only audit; sensitive export изисква причина и допълнителна защита.
- Auditor/Compliance е read-only и не редактира domain records.
- Admin няма автоматичен достъп до payroll, банкови данни и лични AI разговори без отделно право.
- Finance/Payroll, Project Manager и теренните роли виждат само своя domain/project scope.
- Служителят вижда собствените си действия.
- ExternalPrincipal вижда само собствените си ApprovalReceipt/AccessGrant и изрично споделените events.
- AI наследява scope-а на invoking user/tool и няма собствен full-audit достъп.
- Platform support влиза в business content само чрез time-bound break-glass с две одобрения.

Прегледът на highly sensitive events, full-tenant search, export, break-glass, policy change, hold и disposition се одитират самостоятелно.

## Важни инварианти

- Няма отделен скрит AI audit log.
- AuditEvent не се update/delete-ва.
- Correction се прави с нов linked event.
- Secrets и tokens никога не се записват.
- Raw AI content е отделно от structured official action trail.
- Retention job не може да изтрие записи под hold.
- Disposition има signed manifest и собствен AuditEvent.
- Export не разширява разрешения scope.

## Implementation Gate

Business Lock не означава готов runtime. Wave 0 трябва да докаже:

- canonical schema и critical-write coverage;
- append-only и tamper-evident integrity;
- immutable archive/backup/restore;
- retention assignment, archive и disposition;
- legal/incident hold;
- role/scope/field masking;
- audit-of-audit и break-glass;
- AI request → tools → draft → human confirmation → domain execution correlation;
- idempotency и rebuild от immutable archive.

## Обновен прогрес

```text
Business Locked:          37
Активни незавършени:      11
Legacy:                    1
Оставащи решения:         49
```

## Следващ business-close приоритет

1. FLOW-010, FLOW-036 и FLOW-046 — по 3 решения;
2. FLOW-012, FLOW-037, FLOW-041 и FLOW-042 — по 4 решения;
3. FLOW-038/039, FLOW-048 и FLOW-049.

# FLOW-050 Trial / Demo / Partner Decision — 04.08.2026

> **Статус:** APPROVED BUSINESS DECISION  
> **Засегнати FLOW:** 002, 016, 040, 042, 044, 050  
> **PR:** Draft PR #2 — не се слива автоматично

## 1. Trial tenant

Trial е реален tenant с production-like данни и същите tenant-isolation правила като платения продукт.

### Параметри

- срок: **14 дни**;
- пакет: **Pro**;
- AI бюджет: **500 AI действия общо за trial периода**;
- потребители: неограничени;
- обекти: неограничени;
- Primary Storage Provider: задължителен;
- карта: не е задължителна;
- един trial за едно ЕИК.

Ограничение на броя обекти не се допуска, защото противоречи на принципа за пълни реални данни и може да изкриви теста на системата. AI бюджетът е достатъчната ресурсна спирачка.

### Повторен trial и удължаване

- повторен trial за същото ЕИК се допуска само с ръчно одобрение от упълномощен BEG_Work admin;
- удължаване на активен или изтекъл trial е изключение;
- всяко удължаване пази причина, actor, нова крайна дата и AuditEvent.

### Изтичане

```text
TRIAL_ACTIVE — 14 дни
→ TRIAL_READ_ONLY — 14 дни
→ TRIAL_SUSPENDED
```

По време на read-only периода са разрешени преглед, плащане/активация, export и support. Данните не се изтриват автоматично.

При преминаване към платен план tenant-ът се активира без миграция на данните и без създаване на нов tenant.

## 2. Demo режим за launch

За launch се избира по-простият и по-безопасен модел:

> **Demo се използва само за търговски презентации, водени от BEG_Work.**

Demo tenant:

- съдържа само шаблонни, несекретни данни;
- няма клиентски production данни;
- няма реални платежни методи, интеграции или customer credentials;
- може да се reset-ва периодично;
- не се превръща в production tenant;
- не може да бъде source за миграция към реален клиент.

Per-visitor клониране на demo tenant не се разработва за launch. Може да се разгледа по-късно при доказана нужда.

## 3. Partner tenant

Partner режимът е за внедрители, търговски партньори, счетоводни фирми или други одобрени партньори.

Partner tenant може да има безплатен или договорно намален абонамент, но:

- няма автоматичен достъп до клиентски tenant-и;
- няма наследено право само защото партньорът е свързан с клиента;
- достъп до клиентски tenant се дава само чрез изричен `Partner Access Grant`;
- grant-ът е tenant-scoped, time-limited, role/action/resource-scoped и revocable;
- изисква одобрение от клиента/Owner според матрицата на права;
- всички grant/use/revoke действия създават AuditEvent.

## 4. Забранени сценарии

- втори trial за същото ЕИК без ръчно одобрение;
- автоматично удължаване на trial;
- ограничение на броя обекти в trial;
- demo tenant да се преобразува в production;
- demo данни да се смесват с клиентски данни;
- partner да вижда клиентски tenant без отделен Access Grant;
- изтекъл trial да води до автоматично изтриване.

## 5. Implementation Gate последствия

Нужни са:

- `tenant_mode`: PRODUCTION / TRIAL / DEMO / PARTNER;
- `trial_started_at`, `trial_expires_at`, `trial_read_only_until`;
- uniqueness проверка `one trial per EIK`;
- manual override workflow с Approval/AuditEvent;
- trial AI budget ledger;
- conversion от trial към paid без data migration;
- demo reset tooling и hard separation от production credentials;
- Partner Access Grant върху FLOW-002 Permission Service;
- expiry/revoke jobs и isolation tests.

## 6. Приемателни тестове

- trial е 14 дни и Pro функционалност;
- trial има 500 AI действия общо;
- няма лимит на обекти или потребители;
- същото ЕИК не създава втори trial без manual approval;
- manual extension създава AuditEvent;
- изтекъл trial минава 14 дни read-only и после suspended;
- trial данните не се трият автоматично;
- paid conversion запазва същия tenant и данни;
- demo не може да стане production;
- partner без active Access Grant не вижда клиентски tenant;
- изтекъл/revoked Partner Access Grant прекратява достъпа.

## Източник

Изрично решение на Крум Радулов от 04.08.2026.

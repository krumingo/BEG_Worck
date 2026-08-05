# BEG_Work — CLAUDE.md v15

> Версия: 15  
> Дата: 05.08.2026  
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

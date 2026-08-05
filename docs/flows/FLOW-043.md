# FLOW-043 — Architecture Decisions / Архитектурни решения

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 04.08.2026  
> **Implementation Gate:** всяко решение се проверява технически чрез FLOW-042  
> **Одобрени решения:** D-01–D-15

## Цел

FLOW-043 е регистърът на решенията между модулите. Той предотвратява паралелни източници на истина, двойни плащания, дублирани СМР, несъвместими права, паралелни архиви и cross-tenant пробиви.

## D-01 — Канон на FLOW документацията

Последният одобрен FLOW архив и последващите изрични решения на Крум са бизнес канонът. `CLAUDE.md`, Emergent prompt-овете и техническите спецификации се синхронизират към него.

## D-02 — Акордът изисква количество

Плащането по акорд изисква одобрено измерено количество × договорена единична цена труд.

## D-03 — Единен Payment ledger

FLOW-021 и FLOW-028 създават задължения, фишове, актове и разпределения. Реалното парично движение е само в FLOW-006.

## D-04 — Материален разход без двойно броене

Материалът става разход по един път: складово изписване/консумация или директна доставка по валиден фактурен ред, никога и по двата.

## D-05 — Подизпълнителят не е нов Project

Подизпълнителското изпълнение е `SubcontractPackage` / cost center в реалния обект, не фалшив проект.

## D-06 — CrewPresence

Външна бригада може да се отчита с брой хора и задължително отговорно лице; поименни хора се пазят, когато са известни.

## D-07 — Ново СМР от терен и контролирано AI активиране

Теренният потребител може да предложи ново СМР. То е чернова/`За мапване`, минава similarity проверка, Master СМР и локация.

AI може да активира ново СМР само при валиден обект/локация, потвърден Master СМР, достатъчна спецификация, одобрено търговско третиране, exact-version клиентско одобрение когато е нужно, потвърждение от човек с право, липса на blocking risk и пълен AuditEvent. Иначе създава само чернова.

До пълния Client Portal exact-version одобрението се доказва чрез `Interim Approval Receipt`: подписан PDF/e-signature, verified email reply към точна версия или защитена еднократна approval page. Свободно „ОК“ или устно одобрение не е достатъчно.

## D-08 — Един общ AuditEvent

Domain и AI действията използват един AuditEvent envelope. FLOW-040 е изглед, не конкурентен регистър.

## D-09 — FLOW-018 и FLOW-039

FLOW-018 е legacy/MVP. FLOW-039 е каноничният Quality / Defects / Warranty модул и го поглъща.

## D-10 — Business Lock ≠ Implementation Gate

`100% Business Lock` означава решени бизнес правила. Implementation Gate изисква права, API/tool договори, миграция, тестове, rollback/restore и доказателства.

## D-11 — File Registry и Storage Provider Abstraction

FLOW-016 е единният File Registry. Модулите използват стабилен `file_id`, не provider URL/path.

Каноничният Launch модел е customer-managed storage:

- всеки tenant свързва собствен Primary Storage Provider;
- tenant не се активира без read/write/checksum test;
- оригиналите физически стоят при клиента;
- BEG_Work пази File Registry, metadata, relations, versions, checksums, availability status и preview/OCR cache;
- липсващ или променен original създава Alarm/DQ issue + AuditEvent;
- `BEG Hosted Storage` е само възможен бъдещ add-on при отделно решение.

## D-12 — Operational Resilience

AI и интернет не са single point of failure. Всеки основен процес има ръчен вход; критичните теренни процеси имат offline queue; sync използва idempotency и видим conflict review.

## D-13 — Disaster Recovery Architecture

Production, standby, replica/PITR, исторически backup, off-site immutable/offline copy и restore tests са различни слоеве. Репликацията не заменя backup.

## D-14 — Construction Operating System

BEG_Work се развива като Construction Operating System:

```text
разговор / глас / снимка / отчет
→ структурирано искане
→ липсващи въпроси
→ анализ и цена
→ писмено одобрение
→ СМР, задачи и заявки
→ изпълнение
→ актуване
→ плащане и история
```

Работно послание: **„От разговор на обекта до изпълнено и платено СМР.“**

## D-15 — Tenancy & Isolation Model

Един tenant представлява точно една юридическа фирма. Всеки tenant използва един и същ BEG_Work core и FLOW-001–050, но има отделни данни, MongoDB база, Master Data, File Registry, provider credentials, номерации, integrations, AI context, AuditEvent history, subscription и configuration.

Основни правила:

- active tenant се определя от проверената сесия;
- всички входни точки минават през Tenant Guard;
- Tenant Registry пази database, customer Storage Provider, deployment, app/schema/config version, subscription и lifecycle status;
- `User → TenantMembership → RoleAssignments` е единният access модел;
- Master Data е per tenant;
- между tenant-и няма shared Project, Invoice, Payment, WorkPackage или друг operational record;
- Group Dashboard е само read-only projection с изрични права;
- database-per-tenant използва idempotent migration runner с per-tenant lock, validation, AuditEvent и recovery;
- support достъпът е временен, scoped, одобрен и auditable;
- tenant isolation се доказва чрез FLOW-042 tests.

Пълната спецификация е в [TENANCY_MODEL.md](../architecture/TENANCY_MODEL.md).

## Общ код и no-private-fork governance

Всички tenant-и използват един общ код и Release Manifest. Позволената стълбица е:

```text
настройки
→ шаблони
→ Feature Flags / Entitlements
→ одобрени extension points
→ обща продуктова функционалност
→ или „не“
```

Отделен Enterprise deployment не означава отделна версия. Изключение изисква решение на Собственика на BEG_Work и ново D-решение във FLOW-043.

## Общи забрани

- паралелни регистри за една бизнес истина;
- плащане извън единния Payment ledger;
- AI договорно/финансово действие без изискваното одобрение;
- dashboard/timeline/chat да редактира официален запис директно;
- hard delete на използвани записи;
- cross-tenant read/write;
- global Master Data с търговска стойност;
- support достъп без причина, срок и AuditEvent;
- private client fork или скрита client-specific version;
- billing state да задейства deletion;
- standard BEG_Work deletion да изтрива customer-managed originals.

## Източници / сесии

- D-01–D-10: архитектурният одит и решенията до 20.07.2026.
- D-11: storage abstraction 15.07.2026; customer-managed storage уточнение 03.08.2026.
- D-12–D-14: 16.07.2026.
- D-15: tenancy решение 29.07.2026; no-fork/environments/retention синхронизация 04.08.2026.
- FLOW-050 и финалните architecture decision документи в Draft PR #2.

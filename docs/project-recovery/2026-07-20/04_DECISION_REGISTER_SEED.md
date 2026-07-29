# Decision Register — D-01–D-15

> **Каноничен източник:** [FLOW-043](../../flows/FLOW-043.md)  
> **Статус:** D-01–D-15 са официално одобрени бизнес/архитектурни решения. Техническото внедряване се следи отделно.

| Решение | Кратко съдържание | Статус / източник |
|---|---|---|
| D-01 | Последният одобрен FLOW архив + последващите изрични решения на Крум са канонът. | Одобрено |
| D-02 | Акордът изисква одобрено измерено количество × договорена единична цена труд. | Одобрено |
| D-03 | FLOW-021/028 създават задължения; реалното плащане е само в един Payment ledger. | Одобрено |
| D-04 | Материалът става разход по един път: складово изписване или директна доставка, никога и двете. | Одобрено |
| D-05 | Подизпълнителското изпълнение е SubcontractPackage, не фалшив Project. | Одобрено |
| D-06 | CrewPresence допуска брой хора за външна бригада с responsible person. | Одобрено |
| D-07 | Новото СМР от терен е proposal/draft; AI активира само по предварително одобрени правила, валидна локация, нужните одобрения и AuditEvent. | Одобрено на 18.07.2026 |
| D-08 | Един общ AuditEvent envelope за domain и AI; FLOW-040 е изглед. | Одобрено |
| D-09 | FLOW-018 е legacy/MVP; FLOW-039 е каноничният Quality/Defects/Warranty модул. | Одобрено |
| D-10 | Business Lock е различен от Implementation Gate. | Одобрено |
| D-11 | Един File Registry със сменяем storage provider. | Одобрено на 15.07.2026 |
| D-12 | AI/интернет не са single point of failure; има manual/offline/Excel rescue. | Одобрено на 16.07.2026 |
| D-13 | Production, standby, replica/PITR, backups и restore tests са отделни DR слоеве. | Одобрено на 16.07.2026 |
| D-14 | BEG_Work се развива като Construction Operating System. | Одобрено на 16.07.2026 |
| D-15 | Един tenant = една юридическа фирма; database/file/Master Data isolation, Tenant Guard, TenantMembership→RoleAssignments, no shared operational records, per-tenant migrations и controlled support access. | Одобрено на 29.07.2026 |

## Допълнителни потвърдени продуктови правила

- AI никога не назначава ресурс автоматично; само анализира и препоръчва.
- Marketplace е отделен продукт и база; BEG_Work използва защитена API интеграция и разрешени статистики.
- Work Package на вътрешен ръководител използва условен Management Bonus Fund.
- При съществена грешка в базовия бюджет се прави нова версия и предоговаряне.
- Клиентско одобрение е писмено и е свързано с точна версия.
- Всеки tenant използва един и същ core FLOW-001–050, но с напълно отделни фирмени данни и абонамент.

## Източници / сесии

- Каноничен FLOW архив и архитектурен одит: 12.07.2026.
- Storage abstraction: 15.07.2026.
- Operational Resilience, Disaster Recovery и Category-Defining Product: 16.07.2026.
- AI директно активиране по предварително одобрени правила: 18.07.2026.
- Корекционен проход и синхронизация на регистрите: 20.07.2026.
- D-15 Tenancy & Isolation Model: 29.07.2026; пълна спецификация в `docs/architecture/TENANCY_MODEL.md`.

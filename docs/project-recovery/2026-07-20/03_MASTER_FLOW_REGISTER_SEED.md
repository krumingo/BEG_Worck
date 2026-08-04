# Master Flow Register — FLOW-001–050

> **Актуално към:** 04.08.2026  
> **Показател:** бизнес готовност, не процент програмиран код  
> **100%:** Business Lock; Implementation Gate се проверява отделно  
> **Технически статус:** виж [Implementation Gate Matrix](../../architecture/IMPLEMENTATION_GATE_MATRIX.md)

## Обобщение

- Общо FLOW-ове: **50**
- На 100% Business Lock: **49**
- Активни незавършени FLOW-ове: **0**
- Legacy FLOW, който се поглъща от друг: **1** — FLOW-018 → FLOW-039
- Общо оставащи конкретни бизнес решения: **0**

| FLOW | Име | Готовност | Оставащи точки |
|---|---|---:|---:|
| FLOW-001 | Обекти / клиенти / структура на проекта | 100% | 0 |
| FLOW-002 | Потребители / роли / права / достъп | 100% | 0 |
| FLOW-003 | Оферта / СМР редове / Excel-КСС / версии | 100% | 0 |
| FLOW-004 | Оферта → Акт → Остатък → Прогноза | 100% | 0 |
| FLOW-005 | Договори / анекси / договорна база | 100% | 0 |
| FLOW-006 | Фактури / аванси / плащания / ДДС | 100% | 0 |
| FLOW-007 | Допълнителни СМР / допълнителни оферти | 100% | 0 |
| FLOW-008 | Обект → приходи → разходи → печалба | 100% | 0 |
| FLOW-009 | Склад / наличности / материални движения | 100% | 0 |
| FLOW-010 | Клиенти / контакти / контрагенти | 100% | 0 |
| FLOW-011 | Инструменти / машини / QR / активи | 100% | 0 |
| FLOW-012 | Логистика / доставки / курсове | 100% | 0 |
| FLOW-013 | Работници / присъствие / обект / СМР | 100% | 0 |
| FLOW-014 | Дневни отчети / снимки / доказателства | 100% | 0 |
| FLOW-015 | Dashboard / справки / аларми | 100% | 0 |
| FLOW-016 | File Registry / документи / файлове | 100% | 0 |
| FLOW-017 | Задачи / GitHub / Emergent / контрол | 100% | 0 |
| FLOW-018 | Quality / дефекти / гаранции — legacy MVP | 35% | 0* |
| FLOW-019 | СМР / труд / производителност / марж | 100% | 0 |
| FLOW-020 | Материали / заявки / доставки / фактури | 100% | 0 |
| FLOW-021 | Подизпълнители / бригади / рейтинг | 100% | 0 |
| FLOW-022 | Цени труд София | 100% | 0 |
| FLOW-023 | Автоматично офериране / анализ цена | 100% | 0 |
| FLOW-024 | Режийни / Overhead | 100% | 0 |
| FLOW-025 | Договорни документи / версии / контрол | 100% | 0 |
| FLOW-026 | Аларми за риск / загуба / кеш | 100% | 0 |
| FLOW-027 | График / човекодни / прогрес / закъснение | 100% | 0 |
| FLOW-028 | Заплати / акорд / Pay Run / фишове | 100% | 0 |
| FLOW-029 | Архив снимки и видеа по обекти | 100% | 0 |
| FLOW-030 | BEG Brain / централен AI | 100% | 0 |
| FLOW-031 | Модулни AI agent-шапки | 100% | 0 |
| FLOW-032 | Master Data / единна база | 100% | 0 |
| FLOW-033 | Data Quality Center | 100% | 0 |
| FLOW-034 | Approval Center | 100% | 0 |
| FLOW-035 | Work Package Engine | 100% | 0 |
| FLOW-036 | Object Timeline | 100% | 0 |
| FLOW-037 | Mobile Field App 2.0 | 100% | 0 |
| FLOW-038 | Procurement Agent | 100% | 0 |
| FLOW-039 | Quality / Defects / Warranty | 100% | 0 |
| FLOW-040 | AuditEvent / AI Audit Log | 100% | 0 |
| FLOW-041 | Scenario / What-if Engine | 100% | 0 |
| FLOW-042 | Release / QA / Test Center | 100% | 0 |
| FLOW-043 | Architecture Decisions D-01–D-15 | 100% | 0 |
| FLOW-044 | Disaster Recovery | 100% | 0 |
| FLOW-045 | AI Command Center | 100% | 0 |
| FLOW-046 | Client Portal | 100% | 0 |
| FLOW-047 | Managed Work Package / бонус | 100% | 0 |
| FLOW-048 | Resource Assignment | 100% | 0 |
| FLOW-049 | Marketplace / отделен продукт и API интеграция | 100% | 0 |
| FLOW-050 | Tenant Management / Абонаменти / Пакети / Feature Entitlements | 100% | 0 |

\* FLOW-018 не се доразработва като конкурентен модул. Неговата логика се консолидира във FLOW-039.

## Последни бизнес корекции и затваряния

- FLOW-037–042, FLOW-048 и FLOW-049 са затворени на 100% Business Lock през 25–29.07.2026.
- FLOW-049 е отделен Marketplace продукт и база; BEG_Work използва защитено API, Candidate/Offer snapshots и агрегирани статистики.
- FLOW-050 е затворен на 100% Business Lock на 04.08.2026.
- Един tenant = една юридическа фирма; D-15 заключва database-per-tenant, Tenant Registry, Tenant Guard, Master Data per tenant, TenantMembership→RoleAssignments, no shared records, migration runner и controlled support access.
- Пакетите са по цели отделими модули; не се допуска половин модул.
- Неотделимото ядро във всички пакети включва обекти, права, базови контрагенти, пълни финанси, единен Payment ledger, P&L, присъствие/отчети/труд като стойност, базов payroll, режийни, File Registry и CORE enforcement.
- Start / „Фирмата“ = „Знаеш резултата“; Control / „Контролът“ = „Контролираш резултата“; Pro / „Автопилотът“ = „Системата работи за теб“; Enterprise = Pro + договорени корпоративни услуги.
- Launch Pricing v1 без ДДС: Start 19,90 €/месец или 199 €/година; Control 39,90 €/месец или 399 €/година; Pro 79,90 €/месец или 799 €/година; Enterprise от 149 €/месец.
- Customer-managed storage: tenant не се активира без собствен проверен Storage Provider; BEG_Work пази File Registry, не продава storage GB.
- План + AI: Start 100, Control 500, Pro 2 000 AI действия; usage екран и add-ons; при 100% спират само AI функциите.
- Имейл/интеграции: 2/10/30 по пакет и add-on +5 за 5 €/месец; съществуващите връзки не се прекъсват.
- Subscription lifecycle, Payment Provider Adapter, dunning 0/3/7, Grace/Restricted/Suspended, отделен chargeback path и no-deletion rule са заключени.
- Trial: 14 дни Pro + 500 AI действия, без лимит на обекти/потребители; Demo е presentation-only за launch; Partner няма автоматичен клиентски достъп.
- Modern Field Experience заключва PWA/offline-first, `СНИМАЙ/КАЖИ/СКАНИРАЙ`, voice/camera originals във File Registry, context communication, Action Inbox, QR-first и вълново разделение; Digital Twin Lite отпада.
- Един общ код за всички tenant-и; настройки → шаблони → flags/entitlements → общи extension points → общ продукт или „не“; няма private forks.
- Development/Test/Staging/Production и exact-version Tenant Acceptance Environment използват общ Release Manifest.
- Standard termination retention: 90 дни read-only; export преди deletion; няма автоматично deletion; legal/incident hold, Approval, verification и signed disposition manifest са задължителни.

## Бизнес затваряне

FLOW-001–050 нямат оставащи бизнес решения. Следващата стъпка е:

```text
финална проверка на Draft PR #2
→ синхронизация на CLAUDE.md v15 и таблото
→ изрично решение за merge
→ Wave 0 coding
```

## Важно техническо уточнение

49 FLOW-а са заключени на бизнес ниво, а FLOW-018 е legacy, погълнат от FLOW-039. Business Lock не означава Implementation Gate PASS.

D-15 и FLOW-050 добавят задължителни Wave 0 foundations: Tenant Registry, Tenant Guard/database resolver, TenantMembership↔RoleAssignment, per-tenant Master Data/File Registry/numbering/integrations, migration runner + `schema_version`, AI Usage Ledger, Payment Provider Adapter, Subscription/Billing state machine, dunning scheduler, environment/Release Manifest governance, no-fork enforcement, isolation tests, Support Access Request и per-tenant backup/restore/export/retention/deletion proof.

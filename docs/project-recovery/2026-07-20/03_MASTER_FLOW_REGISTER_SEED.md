# Master Flow Register — FLOW-001–050

> **Актуално към:** 29.07.2026  
> **Показател:** бизнес готовност, не процент програмиран код  
> **100%:** Business Lock; Implementation Gate се проверява отделно  
> **Технически статус:** виж [Implementation Gate Matrix](../../architecture/IMPLEMENTATION_GATE_MATRIX.md)

## Обобщение

- Общо FLOW-ове: **50**
- На 100% Business Lock: **48**
- Активни незавършени FLOW-ове: **1** — FLOW-050
- Legacy FLOW, който се поглъща от друг: **1** — FLOW-018 → FLOW-039
- Общо оставащи конкретни бизнес решения: **12**

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
| FLOW-050 | Tenant Management / Абонаменти / Пакети / Feature Entitlements | 20% | 12 |

\* FLOW-018 не се доразработва като конкурентен модул. Неговата логика се консолидира във FLOW-039.

## Последни бизнес корекции и затваряния

- FLOW-037–042, FLOW-048 и FLOW-049 са затворени на 100% Business Lock през 25–29.07.2026.
- FLOW-049 е отделен Marketplace продукт и база; BEG_Work използва защитено API, Candidate/Offer snapshots и агрегирани статистики.
- FLOW-050 е формално създаден на 29.07.2026.
- Точка 1 на FLOW-050 е заключена: **един tenant = една юридическа фирма**.
- Точка 2 на FLOW-050 е заключена чрез D-15: database-per-tenant, Tenant Registry, Tenant Guard, Master Data per tenant, TenantMembership→RoleAssignments, no shared operational records, migration runner и controlled support access.

## Текущ приоритет за бизнес затваряне

FLOW-050 — оставащи решения:

1. Финални търговски пакети и имена.
2. Feature Catalog, Plan Version и Tenant Entitlement модел.
3. Full/Field/External user лимити и overages.
4. Начални цени и годишна отстъпка.
5. Месечно, годишно и Enterprise договорно плащане.
6. Платежен оператор и фактуриране.
7. Grace Period / Restricted / Suspended / restoration.
8. Demo / Trial / Partner tenant.
9. Tenant configuration / private extension / no client forks.
10. Test/Staging/Production и Tenant Acceptance Environment.
11. Прекратяване, export, retention и deletion.
12. AuditEvent/Approval catalog за subscription, entitlements и support.

## Важно техническо уточнение

48 FLOW-а са заключени на бизнес ниво, но Business Lock не означава Implementation Gate PASS.

D-15 добавя задължителни Wave 0 foundations:

- Tenant Registry;
- Tenant Guard и database resolver;
- TenantMembership ↔ RoleAssignment;
- per-tenant Master Data и File Registry isolation;
- per-tenant numbering/integrations/secrets;
- migration runner + `schema_version`;
- tenant isolation tests;
- Support Access Request;
- per-tenant backup/restore/export proof.

Водещи технически документи:

- [TENANCY_MODEL.md](../../architecture/TENANCY_MODEL.md)
- [Implementation Gate Matrix](../../architecture/IMPLEMENTATION_GATE_MATRIX.md)
- [Implementation Waves](../../architecture/IMPLEMENTATION_WAVES.md)
- [Cross-FLOW Code Audit](../../architecture/CROSS_FLOW_AUDIT_2026-07-20.md)
- [Claude Cross-FLOW Logic Audit](../../architecture/CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)

## Източници / сесии

- Каноничен архив FLOW-001–043.
- Последващи изрични решения на Крум от 15–29.07.2026.
- Business-close passes FLOW-010, 012, 025, 036–042, 046, 048 и 049.
- FLOW-050 / D-15 tenancy decision: 29.07.2026.
- Технически code audit срещу `main`: 20.07.2026.

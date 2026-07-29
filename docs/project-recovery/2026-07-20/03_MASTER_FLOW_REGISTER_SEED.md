# Master Flow Register — FLOW-001–049

> **Актуално към:** 29.07.2026  
> **Показател:** бизнес готовност, не процент програмиран код  
> **100%:** Business Lock; Implementation Gate се проверява отделно  
> **Технически статус:** виж [Implementation Gate Matrix](../../architecture/IMPLEMENTATION_GATE_MATRIX.md)

## Обобщение

- Общо FLOW-ове: **49**
- На 100% Business Lock: **48**
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
| FLOW-043 | Architecture Decisions D-01–D-14 | 100% | 0 |
| FLOW-044 | Disaster Recovery | 100% | 0 |
| FLOW-045 | AI Command Center | 100% | 0 |
| FLOW-046 | Client Portal | 100% | 0 |
| FLOW-047 | Managed Work Package / бонус | 100% | 0 |
| FLOW-048 | Resource Assignment | 100% | 0 |
| FLOW-049 | Marketplace boundary / API integration | 100% | 0 |

\* FLOW-018 не се доразработва като конкурентен модул. Неговата логика се консолидира във FLOW-039.

## Последни бизнес корекции и затваряния

- FLOW-003 и FLOW-005 — изрично заключени след 15.07.2026.
- FLOW-008 — възстановен на 100% Business Lock.
- FLOW-010 — затворен на 100% на 21.07.2026.
- FLOW-012 — затворен на 100% на 24.07.2026.
- FLOW-019/024 — заключено финансовото и KPI третиране на престоя.
- FLOW-025 — затворен на 100% на 21.07.2026.
- FLOW-035 — затворен на 100%: PackageTemplate, idempotent generation и финален Work Package екран.
- FLOW-036 — затворен на 100% на 22.07.2026.
- FLOW-037 — затворен на 100% на 25.07.2026.
- FLOW-038 — затворен на 100% на 28.07.2026: supplier rating, historical normalization, RFQ, AI/OCR parsing, basket optimization и Approval flow.
- FLOW-039 — затворен на 100% на 28.07.2026: defect lifecycle, warranty calendar, responsibility, versioned protocol, independent acceptance и financial/rating treatment.
- FLOW-040 — затворен на 100% на 21.07.2026.
- FLOW-041 — затворен на 100% на 27.07.2026.
- FLOW-042 — затворен на 100% на 28.07.2026.
- FLOW-045 — затворен на 100%.
- FLOW-046 — затворен на 100% на 23.07.2026.
- FLOW-048 — затворен на 100% на 28.07.2026: hard eligibility, visible ranking weights, Skill Match, current/future load, reservations/conflicts, one-main-manager rule, second manager/split-package logic и final rights matrix; само Крум назначава ръководители.
- FLOW-049 — затворен на 100% на 29.07.2026: Marketplace като отделно приложение/база, Publication/Candidate/Offer snapshots, versioned protected API, market statistics към FLOW-022/023, no-duplicate handoff към Master Data и твърда data-isolation граница.

## Следваща фаза

Всички официални FLOW-ове са затворени на бизнес ниво. Следва:

1. финален cross-FLOW consistency audit;
2. формално създаване и обсъждане на FLOW-050;
3. финализиране на Implementation Gate Matrix и Implementation Waves;
4. подготовка на Wave 0 foundation backlog;
5. отделна Marketplace Business Specification.

## Ново архитектурно откритие

По време на FLOW-042 е установена нужда от бъдещ:

`FLOW-050 — Tenant Management / Абонаменти / Пакети / Feature Entitlements`.

FLOW-050 още не е включен в официалната бройка, докато не бъде формално създаден и обсъден.

## Важно техническо уточнение

48 FLOW-а са заключени на бизнес ниво, но Business Lock не означава Implementation Gate PASS. За реалния код водещи са:

- [Cross-FLOW Code Audit](../../architecture/CROSS_FLOW_AUDIT_2026-07-20.md)
- [Claude Cross-FLOW Logic Audit](../../architecture/CLAUDE_CROSS_FLOW_LOGIC_AUDIT_2026-07-20.md)
- [FLOW-010 Business Close](../../architecture/FLOW_010_BUSINESS_CLOSE_2026-07-21.md)
- [FLOW-012 Business Close](../../architecture/FLOW_012_BUSINESS_CLOSE_2026-07-24.md)
- [FLOW-025 Business Close](../../architecture/FLOW_025_BUSINESS_CLOSE_2026-07-21.md)
- [FLOW-036 Business Close](../../architecture/FLOW_036_BUSINESS_CLOSE_2026-07-22.md)
- [FLOW-037 Business Close](../../architecture/FLOW_037_BUSINESS_CLOSE_2026-07-25.md)
- [FLOW-038 Business Close](../../architecture/FLOW_038_BUSINESS_CLOSE_2026-07-28.md)
- [FLOW-039 Business Close](../../architecture/FLOW_039_BUSINESS_CLOSE_2026-07-28.md)
- [FLOW-040 Business Close](../../architecture/FLOW_040_BUSINESS_CLOSE_2026-07-21.md)
- [FLOW-041 Business Close](../../architecture/FLOW_041_BUSINESS_CLOSE_2026-07-27.md)
- [FLOW-042 Business Close](../../architecture/FLOW_042_BUSINESS_CLOSE_2026-07-28.md)
- [FLOW-046 Business Close](../../architecture/FLOW_046_BUSINESS_CLOSE_2026-07-23.md)
- [FLOW-048 Business Close](../../architecture/FLOW_048_BUSINESS_CLOSE_2026-07-28.md)
- [FLOW-049 Business Close](../../architecture/FLOW_049_BUSINESS_CLOSE_2026-07-29.md)
- [Implementation Gate Matrix](../../architecture/IMPLEMENTATION_GATE_MATRIX.md)
- [Implementation Waves](../../architecture/IMPLEMENTATION_WAVES.md)

## Източници / сесии

- Каноничен архив FLOW-001–043.
- Последващи изрични решения на Крум от 15–29.07.2026.
- Корекционен и logic-audit pass по Draft PR #2: 20.07.2026.
- Business-close passes: FLOW-010, 012, 025, 036, 037, 038, 039, 040, 041, 042, 046, 048 и 049.
- Технически code audit срещу `main`: 20.07.2026.

# FLOW-050 Subscription / Billing / Dunning Decision — 04.08.2026

> **Статус:** APPROVED BUSINESS DECISION  
> **Засегнати FLOW:** 006, 016, 034, 040, 042, 050  
> **PR:** Draft PR #2 — не се слива автоматично

## 1. Subscription lifecycle

### Месечен абонамент

- плаща се предварително за един месец;
- подновява се автоматично;
- може да бъде отказан по всяко време;
- при отказ остава активен до края на платения период;
- няма частично възстановяване за неизползвани дни, освен при доказана грешка на BEG_Work.

### Годишен абонамент

- плаща се предварително за 12 месеца;
- цената е приблизително равна на 10 месечни такси;
- при доброволно прекратяване няма частично възстановяване;
- абонаментът остава активен до края на платения период.

### Upgrade / downgrade

- **Upgrade** — влиза в сила веднага и се начислява пропорционалната разлика за оставащия период;
- **Downgrade** — влиза в сила от следващия billing период;
- при downgrade изключените модули остават read-only и исторически видими;
- AI add-on се активира веднага pro-rata и се отказва от следващия период;
- данни не се изтриват при upgrade, downgrade или отказ.

### Enterprise

Enterprise поддържа месечен, годишен или многогодишен договор. Промени се извършват чрез договор/анекс и Approval, а плащането може да бъде по фактура и банков превод.

## 2. Payment Provider Adapter

FLOW-050 използва provider-neutral `Payment Provider Adapter`.

За Start/Control/Pro се поддържат карта и автоматично подновяване. За Enterprise се поддържат фактура и банков превод; по изключение това може да се използва и за други планове.

Конкретният платежен оператор не се заключва в бизнес FLOW-а. Избира се преди production launch според такси, България/евро, recurring payments, 3-D Secure, refunds, chargebacks, API, webhooks и счетоводно удобство.

BEG_Work не съхранява номера на карти.

Платежният оператор връща payment events, но FLOW-050 остава source of truth за:

- Subscription;
- Plan/Plan Version;
- Billing Period;
- Entitlements;
- Invoice;
- Payment Attempt/Receipt;
- Grace/Restricted/Suspended state.

Операторът не включва и не изключва tenant достъпа директно.

### Webhook правила

Всеки provider event изисква:

- подписан webhook;
- уникален provider event ID;
- idempotency;
- проверка на сума, валута, tenant и billing period;
- AuditEvent;
- защита от двойно активиране или двойно осчетоводяване.

### Фактуриране

За успешно плащане се издава фактура от продаващото BEG_Work дружество. Фактурата се изпраща до billing email, пази се във File Registry и се свързва с tenant, subscription и payment receipt. Корекцията става чрез кредитно известие, не чрез изтриване.

## 3. Dunning и access states

Каноничният път при обикновено неуспешно плащане е:

```text
ACTIVE
→ GRACE
→ RESTRICTED
→ SUSPENDED
→ RESTORED
```

### Автоматични повторни опити

Dunning прави автоматични повторни опити за плащане:

- ден 0;
- ден 3;
- ден 7.

Всеки опит създава Payment Attempt и AuditEvent. Повтореният provider event не създава второ действие.

### Уведомления

От ден 0 всички известия за неплатен абонамент се изпращат задължително до:

- Собственика на tenant-а;
- финансовия администратор;
- допълнителни договорени billing контакти.

### Ден 0–7: GRACE

Системата работи нормално. Показва се предупреждение на Owner/Admin и се изпълняват dunning опитите.

### Ден 8–14: RESTRICTED

Съществуващите данни и основните операции остават достъпни. Ограничават се:

- AI функции;
- добавяне на нови интеграции;
- активиране на add-ons;
- създаване на нови обекти;
- канене на нови потребители.

Не се блокират:

- фактури, плащания, каса и банка;
- присъствие и дневни отчети;
- текущи оперативни записи;
- аварийни и безопасност действия;
- преглед и export на собствените данни;
- плащане на абонамента и support request.

### След ден 14: SUSPENDED

Tenant-ът става основно read-only. Разрешени остават:

- вход за Owner/Admin;
- преглед на данните;
- плащане на абонамента;
- фактури и billing история;
- export;
- support;
- сваляне на важни документи.

Нови оперативни записи не се създават, освен действията за payment, export и support.

### RESTORED

След проверено успешно плащане:

```text
Payment confirmed
→ Subscription restored
→ Entitlements restored
→ Background jobs resumed
→ AuditEvent
```

Възстановяването е автоматично и идемпотентно за нормално просрочие.

## 4. Chargeback — отделен критичен път

Chargeback не минава през стандартната 7/7/14 стълбица.

При потвърден chargeback:

- tenant-ът преминава незабавно в `SUSPENDED_CHARGEBACK`;
- Owner и финансовият администратор се уведомяват веднага;
- създава се incident/case и AuditEvent;
- възстановяване се допуска само с ръчно решение от упълномощен BEG_Work оператор;
- решението съдържа основание, доказателства и свързан AuditEvent;
- автоматично payment event не възстановява достъпа без човешкото решение.

## 5. Желязно правило за данните

> **Неплатен абонамент никога не изтрива данни.**

Нито GRACE, RESTRICTED, SUSPENDED, chargeback, downgrade, отказ или изтекъл абонамент водят до автоматично физическо изтриване.

Изтриването е отделен прекратителен процес:

```text
Termination request
→ export на клиента
→ договорен retention период
→ проверки за legal/incident hold
→ изрично потвърждение
→ контролирано deletion/disposition действие
→ AuditEvent / signed manifest
```

Customer-managed original файловете остават в Storage Provider на клиента. BEG_Work контролира собствената база, File Registry, preview/cache и управляваните от него данни според отделния termination процес.

## 6. Implementation Gate

Нужни са:

- Subscription и Billing Period state machine;
- idempotent proration за upgrade и AI add-ons;
- scheduled downgrade/cancellation;
- Payment Provider Adapter;
- signed webhook verification и provider-event deduplication;
- invoice/credit-note linkage;
- dunning scheduler за ден 0/3/7;
- Owner + finance-admin notification routing;
- access-policy matrix за GRACE/RESTRICTED/SUSPENDED;
- отделен `SUSPENDED_CHARGEBACK` state;
- manual restore Approval за chargeback;
- тест, че нито един billing state не изтрива tenant данни;
- AuditEvent за payment attempt, state transition, restore, chargeback и termination.

## 7. Приемателни тестове

- upgrade се активира веднага и начислява точна pro-rata разлика;
- downgrade влиза в сила от следващия период;
- cancellation не прекъсва платения период;
- webhook retry не дублира плащане или entitlement;
- dunning опити се правят точно на ден 0/3/7;
- Owner получава всяко billing известие от ден 0;
- ден 8 активира RESTRICTED, ден 15 — SUSPENDED;
- core finance/report/export достъпът следва матрицата;
- успешно плащане възстановява нормално просрочие идемпотентно;
- chargeback води незабавно до отделно suspended състояние;
- chargeback restoration изисква ръчен actor и AuditEvent;
- неплащане никога не задейства deletion;
- deletion се допуска само чрез отделния termination/export/retention/confirmation процес.

## Източник

Изрични решения на Крум Радулов от 03–04.08.2026.

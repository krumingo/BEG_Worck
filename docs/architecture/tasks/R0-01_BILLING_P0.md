# R0-01 — Billing P0: подписан webhook + без mock в production

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (отделна сесия) · Ревю: Codex · Решение: Крум
> Находки: AUD-009 (Stripe webhook fail-open), AUD-045 (mock billing / смяна на план без плащане)
> FLOW: FLOW-050 (абонаменти, signed/idempotent webhooks, BEG_Work е source of truth за entitlements), FLOW-006, FLOW-042
> База: `main` @ `79af297612f57c055bb7caef3f0c48493800d1b6`
> Клон: `claude/r0-01-billing-p0` → Draft PR към `main`

## Защо двете находки са в един пакет

И двете са в `backend/app/routes/billing.py` и `backend/app/core/stripe_config.py`. Задействат се от една и съща липса на конфигурация (Stripe ключове) и пишат в едни и същи записи (`subscriptions`, `feature_flags`). Ако се поправят поотделно, ще има два PR-а, които пипат едни и същи редове.

## Какво е сега (проверено в main)

- `backend/app/core/stripe_config.py:33` — `STRIPE_MOCK_MODE = not is_stripe_configured()`. Mock се включва сам, щом липсва ключ, без проверка на средата.
- `backend/app/routes/billing.py:174-227` — `create_checkout_session` е достъпен за всеки логнат потребител. В mock режим записва `plan_id` и `status: "active"` и пуска всички модули на плана без плащане.
- `backend/app/routes/billing.py:332-345` — без `STRIPE_WEBHOOK_SECRET` webhook-ът приема неподписан JSON („Development mode“).
- `backend/app/routes/billing.py:354-379` — `checkout.session.completed` взема `metadata.org_id` от тялото на заявката и пише директно в `db.subscriptions` / `db.feature_flags`.

## Обхват (какво се прави)

1. **Webhook затворен по подразбиране**
   - Ако `STRIPE_WEBHOOK_SECRET` липсва → `503`, нищо не се записва. В лога има предупреждение без payload.
   - Подписът винаги се проверява с `stripe.Webhook.construct_event`. Без резервен вариант с `json.loads`.
2. **Tenant-ът не идва от заявката**
   - Фирмата се определя от запис, създаден от BEG_Work при checkout (Stripe customer id / checkout session id → `org_id`).
   - `metadata.org_id` е само кръстосана проверка. При разминаване → нищо не се записва + security log.
   - Записите минават през съществуващия tenant-scoped достъп (същия, който A2C guard-ът изисква), не през суров `db`.
3. **Idempotency**
   - Обработените `event.id` се пазят в отделна колекция с уникален индекс.
   - Повторено събитие → `200`, без втори ефект.
4. **Mock само при изрично разрешение**
   - Mock е позволен само ако `BILLING_PROVIDER=mock` **и** `ENV` е изрично `development` или `test`. Липсващ `ENV` = забранено (fail closed).
   - В production без Stripe конфигурация checkout връща `503` с ясно съобщение. Никога не сменя плана.
   - `/api/billing/config` (или съществуващият status endpoint) показва честно, че billing не е конфигуриран.
5. **Кой може да купува**
   - `create-checkout-session` и customer portal: само Owner/Admin, през съществуващия `require_admin` (или permission service, ако вече е там).
   - Останалите роли → `403`.
6. **Планът се сменя само от проверено събитие**
   - Извън mock в dev/test checkout само създава session. Планът се активира единствено от валиден подписан webhook.
7. **Read-only отчет за изложеност**
   - Нов скрипт `backend/scripts/r0_01_billing_exposure_report.py`, само четене, по подразбиране dry-run.
   - Изброява абонаментите със `stripe_subscription_id` от вида `mock_sub_*`, audit редовете `checkout_mock` и промените в плана от webhook без подпис (ако има следа).
   - Не пише нищо. Ще се пусне в production само с одобрение на Крум (стъпка 1.0).

## Забранено (извън обхвата)

- Промени по планове, цени, entitlements модела или FLOW-050 бизнес правила.
- Миграция или поправка на съществуващи абонаменти. Това е стъпка 1.9, след отчета.
- Frontend редизайн. Позволено е само показване на ясна грешка при `503` / `403`, ако е нужно.
- Пипане на други PR-и или клонове. Merge, deploy и достъп до production.

## Тестове (задължителни)

| # | Случай | Очаквано |
|---|---|---|
| 1 | webhook без `STRIPE_WEBHOOK_SECRET` | `503`, без запис |
| 2 | webhook с грешен подпис | `400`, без запис |
| 3 | валиден подписан `checkout.session.completed` | един запис за правилния tenant |
| 4 | същото събитие повторно | `200`, без втора промяна |
| 5 | `metadata.org_id` на чужда фирма | без запис, security log |
| 6 | `subscription.deleted` за чужд customer | без запис |
| 7 | checkout като Viewer / Technician | `403` |
| 8 | checkout като Owner с mock в `ENV=production` | `503`, планът е непроменен |
| 9 | checkout с `BILLING_PROVIDER=mock`, `ENV=test` | mock работи както досега |
| 10 | `ENV` липсва + mock | забранено |
| 11 | отчетът за изложеност | само четене (тест с mongomock, че не пише) |

`tests/test_m10_billing.py:218` очаква mock checkout да вдигне плана. Тестът се обновява да задава изрично `BILLING_PROVIDER=mock` + `ENV=test`. Не се изтрива.

Да се пуснат и съществуващите W0 DB-free пакети, A2C guard-ът и A1 guard-ът. Нулеви нови нарушения.

## Предаване (HANDOFF)

- Draft PR към `main` със заглавие `R0-01 — Billing P0: signed webhook + no mock in production (AUD-009, AUD-045)`.
- В описанието: точен head SHA, base SHA, кои файлове, резултати от тестовете (брой passed/failed/skipped), какво не е пуснато и защо, известни ограничения.
- Без merge и без deploy.

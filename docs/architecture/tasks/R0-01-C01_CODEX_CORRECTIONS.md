# R0-01-C01 — корекции по Codex ревю на PR #58

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (същата сесия като R0-01) · Ревю: Codex · Решение: Крум
> Вход: Codex review https://github.com/krumingo/BEG_Worck/pull/58#issuecomment-6231846215 (CHANGES_REQUESTED, F-01…F-06)
> Работи се в същия PR #58, клон `claude/r0-01-billing-p0`, върху head `92de1cffc288a8ea59565c0799036cc44ba91216`
> Модел за изпълнението: Opus (пари, сигурност)

## Преценка на оркестратора

И шестте находки се приемат. F-03 се приема **в ограничен вид**: без инструмент, който прехвърля стари данни от Stripe. Мотив: F-04 прави непознатите checkout събития повторими и записани, а остатъчният риск се покрива с проверка преди deploy (виж т. F-03).

## Корекции

### F-01 — само платен checkout включва план
- В `_resolve_checkout_completed` (или преди claim/apply) се отказва, освен ако:
  - `payment_status == "paid"`;
  - `mode == "subscription"`;
  - `subscription` е непразен низ.
- Ако условията не са изпълнени (`unpaid`, `no_payment_required`, липсва статус, грешен mode, няма subscription id):
  - планът и feature flags **не се пипат**;
  - събитието се записва трайно (виж F-04) с клас `not_paid` / `malformed`;
  - отговорът е `200`, защото Stripe няма да промени това събитие.
- Тестове: `paid` → включва; `unpaid`, `no_payment_required`, липсващ статус, `mode=payment`, празен subscription → нищо не се променя + има траен запис.

### F-02 — lease вместо вечно „processing“
- При claim се записват `processing_started_at` и `attempt_token` (uuid).
- Повторно поемане е възможно за `status=failed`, **или** за `status=processing` с `processing_started_at` по-старо от `BILLING_WEBHOOK_LEASE_SECONDS` (по подразбиране 300). Прави се с atomic `find_one_and_update`, нов токен и `attempts += 1`.
- Крайното `processed` / `failed` се записва само ако `attempt_token` съвпада. Ако не съвпада, опитът е изгубил lease-а: не пише и логва.
- Тестове:
  - два живи паралелни опита → точно един собственик;
  - „crash“ (claim без край) + доставка преди изтичане → duplicate;
  - след изтичане → поема и прилага веднъж;
  - стар опит след поемане не може да маркира `processed`;
  - `failed` → retry.

### F-03 — преход при пускане (ограничен)
- **Без** backfill от Stripe и без връщане към metadata като източник на tenant.
- Непознат checkout session → F-04 клас `unresolved` → `503`, запис, Stripe опитва пак (до ~3 дни). Така събитието не се губи и може да се поправи ръчно.
- В описанието на PR и в `docs/architecture/tasks/R0-01_BILLING_P0.md` се добавя **cutover проверка преди deploy**:
  1. в production е зададено ли `STRIPE_API_KEY`;
  2. ако да — в Stripe Dashboard няма отворени checkout sessions (или се изтичат ръчно);
  3. след deploy се гледа колекцията за отхвърлени събития за клас `unresolved`.
- Тест: непознат session → 503 + запис; след като записът в `billing_checkout_sessions` се появи, повторната доставка включва плана веднъж.

### F-04 — траен запис и класификация на отхвърлените
- Нова **системна** колекция (не tenant-scoped, без доверие в metadata), напр. `billing_webhook_rejections`:
  - уникален ключ `stripe_event_id`;
  - полета `event_type`, `reason_class` (`unresolved` | `mismatch` | `not_paid` | `malformed`), `reason`, `stripe_object_id`, `received_at`, `attempts`;
  - **без** payload, имейли и суми.
- Класове:
  - `unresolved` (няма локален запис за session/subscription) → **503**, Stripe ще опита пак;
  - `mismatch` (customer/org/plan не съвпадат с локалния запис), `not_paid`, `malformed` → **200** след трайния запис.
- Колекцията се класифицира правилно за A2C guard-а като системна (platform) колекция, не като ORG_KEYED. Обосновка в PR-а.
- Тестове: всеки клас → правилен статус + точно един запис; повторна доставка на същото → без втори запис (`attempts += 1`); нищо не се пише в tenant колекциите.

### F-05 — `metadata.plan_id` е задължителен
- Липсващ или различен `metadata.plan_id` → `mismatch`. Локалният запис остава източник на истината.
- Тестове: липсващ → mismatch; различен → mismatch; еднакъв → включва.

### F-06 — скриптът наистина само чете
- Обвивката преминава от забранителен списък към **разрешителен**: позволени са само `find`, `find_one`, `count_documents`, `distinct`, `aggregate` и `list_collection_names` / `list_indexes`. Всичко друго се отказва.
- `aggregate` проверява pipeline-а и отказва `$out` и `$merge` на всяко ниво.
- В docstring и в PR: за production се ползва read-only Mongo потребител (външната граница).
- Тест: CRUD, `$out`, `$merge`, `bulk_write`, `drop` → отказ; `find` / `aggregate` с `$match` → работят.

## Забранено

- Всичко, забранено в R0-01 (планове, цени, frontend redesign, миграции, production, merge, deploy).
- Нов commit се добавя в същия клон. Без force-push и без rebase.

## Тестове и предаване

- Всички нови тестове + съществуващите 20. Ако има MongoDB replica set, тестовете за lease и уникален индекс да минат и там. Ако няма — да се каже ясно.
- W0 DB-free пакетът: същият резултат като main (1085 / 15 / 50, същите 15). A2C и A1 guard-ове: 0 нарушения.
- В PR-а: коментар „HANDOFF C01“ с нов head SHA, кои находки как са затворени, точни резултати, какво не е пуснато.
- Отговор към оркестратора: `R0-01-C01 DONE head=<sha> tests=<summary>` или `R0-01-C01 BLOCKED <reason>`.

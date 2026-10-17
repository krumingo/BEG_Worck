# R0-01-C02 — втори кръг корекции по Codex (PR #58)

> Статус: **пусната** (Крум избра Opus за оркестратора, 17.10.2026)
> Вход: Codex re-review https://github.com/krumingo/BEG_Worck/pull/58#issuecomment-6232237913 (CHANGES_REQUESTED)
> Head преди корекцията: `3814c02d798ed5437e1d6f48339cfbd221637484`
> Затворени от Codex: F-01, F-03 (в ограничен вид), F-05, F-06. Отворени: F-02, F-04 и точка g.

## F-02 — изгубен lease не може да потвърди успех
- В `stripe_webhook` резултатът от `_finish_event(..., processed)` се проверява.
  - Ако е `False`: rejection-ът не се маркира като разрешен, и се връща `503` (retryable), за да довърши текущият собственик.
- Същото важи за пътя `failed`: ако lease-ът е изгубен, не се записва нищо и се връща `503`.
- Тест на реален MongoDB (interleaving): стар опит губи токена → не може да върне 200 и да маркира rejection; само текущият собственик стига до `processed`.

## F-04 — поправка на rejection при повторна доставка
- Когато `_claim_event` върне `None`, се проверява състоянието на реда в `billing_webhook_events`.
  - Ако е `processed`: rejection-ът за този `stripe_event_id` се маркира като разрешен за tenant-а, определен от сървъра (не от metadata). После се връща `200 duplicate`. Операцията е idempotent.
  - Ако е `processing` (жив lease) или друго: rejection-ът не се пипа и се връща `200 duplicate`, както досега.
- Тест на реален MongoDB с fault injection: грешка точно между `processed` и `resolved_at` → следващата доставка поправя `resolved_at` веднъж.

## Точка g — условие за deploy (без код)
- В описанието на PR #58, в cutover списъка, се добавя задължителна отметка:
  - Stripe акаунтът и webhook адресът са **само за BEG_Work**: няма чужди абонаменти и няма други webhook-ове.
  - Ако не са само за BEG_Work, deploy-ът спира и се отваря отделна задача за окончателна класификация на чужди абонаменти.
- Код за споделен акаунт **не** се пише сега.

## Правила
- Нов commit в `claude/r0-01-billing-p0`; без force-push и rebase; без merge, deploy и production.
- Тестове:
  - всички R0-01 тестове, на mongomock и на реален MongoDB, ако е възможно;
  - W0 DB-free: 1085 / 15 / 50 със същите 15 паднали теста;
  - A2C и A1 guard-овете: 0 нарушения.
- Коментар „HANDOFF C02“ в PR #58. Съобщение до оркестратора: `R0-01-C02 DONE head=<sha> tests=<summary>`.

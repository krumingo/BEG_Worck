# R0-03-C01 — корекции по Codex review на PR #63

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (**Opus** — сигурност) · Ревю: Codex · Решение: Крум
> PR: #63, ревюиран head `dcaf204d590ac93ab6af1a44e5749fc2bef44901`
> Codex review: https://github.com/krumingo/BEG_Worck/pull/63#issuecomment-6271219528 (CHANGES_REQUESTED)
> Обхват: само F-01…F-04. Без нов обхват, без миграции, без уникален индекс, без промяна на данни.

## Проверено от оркестратора
И четирите находки съответстват на кода на `dcaf204`. Точки 3, 5 и 6 са CLOSED и не се пипат.

## F-01 — HIGH — последният Owner в enforce може да се деактивира
`backend/app/services/user_role_policy.py:127-144`: `demotes_owner`/`deactivates_owner` и броят на останалите Owner-и гледат `legacy_rank(target.role)` и `users.role`, а в enforce рангът идва от RoleAssignment.
- Поправка: решението „това е Owner“ и броят на останалите активни Owner-и стават зависими от режима. В enforce: активни, company-scoped, валидни сега Owner RoleAssignments на активни User-и от tenant-а. В off/shadow: както сега. Важи за PUT `/users` (роля и `is_active`) и за DELETE.
- Тест (mongomock + реален Mongo): единствената owner assignment, `users.role="Admin"` → self-deactivate → 409 `LAST_ACTIVE_OWNER`, без запис в User/AuditEvent. Също за понижаване и изтриване. Отказът за самоизтриване остава.

## F-02 — HIGH — platform bootstrap и seed не проверяват цялата инсталация
`backend/app/routes/platform.py:246-316`, `backend/app/core/seed.py:46-73`, противоречащ тест `tests/test_r0_03_roles_email.py:532-542`.
- Поправка: един общ fail-closed helper за изброяване на базите в инсталацията (същият като в т. F-03), ползван от `/users`, onboarding, platform bootstrap и seed.
  - Platform bootstrap с имейл, който вече съществува (в глобалната или в друга tenant база, всяко изписване) → **409 `EMAIL_EXISTS`**, без запис и без име на фирма. Тестът на ред 532-542 се поправя според договора.
  - Seed: при съществуващ имейл където и да е → пропуска, без запис (лог без пълен имейл).
- Тестове: глобална база + отделна tenant база, `CROSS@example.com` срещу `cross@example.com`.

## F-03 — MEDIUM — onboarding не е fail-closed
`backend/app/tenancy/onboarding.py:84-87`: `distinct("database_name")` тихо прескача запис без `database_name`.
- Поправка: обхождат се записите в `tenant_registry`; всеки активен запис трябва да има база, която се отваря. Иначе onboarding спира с отказ **преди първия запис**. Ползва се общият helper от F-02.
- Тест: запис без `database_name` → отказ, нищо не е записано (побайтово).

## F-04 — MEDIUM — смяна на собствена парола без canonical AuditEvent
`backend/app/routes/auth.py:171-218`.
- Поправка: при успешна смяна → canonical W0-04 AuditEvent (actor, target, action, result, reason), **без парола и хеш**. При грешна стара парола → AuditEvent с `result="denied"`, също без тайни. Legacy `log_audit` остава.
- Тестове: успех + отказ; проверка, че събитието не съдържа паролата/хеша.

## Проверки преди предаване
- `tests/test_r0_03_roles_email.py` + новите тестове: всички зелени на mongomock и реален MongoDB.
- Mutation: новите тестове за F-01…F-04 падат на `dcaf204`.
- Всички `tests/test_r0_0*.py` зелени. W0 DB-free: 1085 / 15 / 50 със същите 15. A2C и A1: 0 нарушения.
- Бот тест: не е нужен, ако UI не се променя. Ако се промени, кратък бот тест със скрийншоти.

## Предаване
- Нов commit в същия клон `claude/r0-03-roles-email`, без пренаписване на историята.
- Коментар `HANDOFF C01` в PR #63: нов head, какво е поправено по F-01…F-04, точни резултати, mutation.
- Съобщение: `R0-03-C01 DONE head=<sha> tests=<summary>` или `R0-03-C01 BLOCKED <reason>`.

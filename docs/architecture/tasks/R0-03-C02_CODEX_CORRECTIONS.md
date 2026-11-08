# R0-03-C02 — последна корекция по Codex re-review на PR #63

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (**Opus**) · Ревю: Codex · Решение: Крум
> PR: #63, ревюиран head `eda9b8c101e153f281249a478ddb85958e0add55`
> Codex re-review: https://github.com/krumingo/BEG_Worck/pull/63#issuecomment-6294546615 (CHANGES_REQUESTED)
> Codex затвори F-01 и F-04. Остава една находка (F-02/F-03 в `POST /users` при `off`/`shadow`).

## Находка (HIGH)
`backend/app/tenancy/identity.py:120` и `backend/app/routes/auth.py:288`: в `off`/`shadow` `installation_databases(db, ctx.mode)` връща само глобалната база. Затова:
- имейл, който съществува само в друга tenant база → `201`, създава се втори User (нарушава Р6);
- запис в `tenant_registry` без `database_name` → `201` вместо `503`.
Тестът `test_11d_off_never_reads_the_registry_for_the_email_check` (`tests/test_r0_03_roles_email.py:552`) кодира грешното поведение.

## Решение на оркестратора (проверено)
Правилото на W0-02 PR-05 е „в off/shadow не се ползват Permission Service / resolver“ (`app/tenancy/guard.py:123-130`). Onboarding/signup вече чете `tenant_registry` във всеки режим (`installation_databases_for`). Проверката за имейл е **само четене** и не решава права. Затова в `off`/`shadow` тя ползва същия път като onboarding: директно четене на `tenant_registry` в системната база, без resolver и без Permission Service.

## Обхват
1. `POST /users` във **всеки режим** проверява имейла в цялата инсталация, fail-closed. Записът остава в базата, избрана от режима.
   - `off`/`shadow`: изброяване чрез `installation_databases_for(global_db, system_db)` (директно четене на регистъра, без resolver).
   - `enforce`: както сега.
   - `IdentityCheckUnavailable` около цялото изброяване и търсене → съществуващият общ `503 IDENTITY_CHECK_UNAVAILABLE`, нищо не се пише.
2. `test_11d` се заменя с тестове за `off` и `shadow` (mongomock + реален Mongo):
   - дубликат в чужда база → 409 `EMAIL_EXISTS`, без запис;
   - запис в регистъра без `database_name` → 503, базата побайтово същата;
   - нов имейл при здрав регистър → 201 (както досега);
   - Permission Service и resolver не се викат в `off` (assert).
3. Нищо друго не се променя.

## Проверки
- Всички `tests/test_r0_0*.py` зелени на двата backend-а; mutation — новите тестове падат на `eda9b8c`.
- W0 DB-free: 1085 / 15 / 50 със същите 15. A2C и A1: 0 нарушения.
- Без UI промяна → без бот тест.

## Предаване
- Нов commit в `claude/r0-03-roles-email`, без пренаписване на историята.
- Коментар `HANDOFF C02` в PR #63; съобщение `R0-03-C02 DONE head=<sha> tests=<summary>` или `BLOCKED <reason>`.

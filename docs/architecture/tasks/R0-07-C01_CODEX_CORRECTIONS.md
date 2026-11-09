# R0-07-C01 — корекция по Codex ревю на PR #62

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (същата сесия като R0-07, Sonnet) · Ревю: Codex · Решение: Крум
> Вход: https://github.com/krumingo/BEG_Worck/pull/62#issuecomment-6252438887 (CHANGES_REQUESTED, F-01 MEDIUM)
> Head преди корекцията: `af88f294cd50db14eb5ba174fe1d6057764f57f9` · същият PR #62, клон `claude/r0-07-dev-reset`

## Преценка на оркестратора

Приема се. Codex потвърди всичко останало:
- проверката на средата е преди login;
- Admin/Owner работят, другите роли получават 403;
- старият байпас с `ENVIRONMENT` е затворен;
- изолацията между фирми е запазена;
- billing не е засегнат;
- промяната в двата стари W0 теста е минимална и коректна.

Остава едно: `is_dev_or_test_env()` прави `.strip().lower()`, затова `TEST`, `Development`, `" test "` и `" development "` също пускат опасния маршрут. Пакетът R0-07 (и текстът към Codex) изискваше само точно `development` и `test`.

## Корекция — F-01
- Маршрутът `POST /api/dev/reset-warehouses` се пуска **само** при точна сурова стойност `ENV == "development"` или `ENV == "test"` (без strip и без lower). Всичко друго → 404 преди login и преди достъп до базата.
- Поведението на mock billing (`is_mock_billing_allowed`) **не се променя**. Ако общият helper остава с нормализация заради billing, reset-ът получава отделна строга проверка (например `is_dev_or_test_env(strict=True)` или отделна функция). Code избира и обосновава.
- Тестове (mongomock + реален MongoDB): `TEST`, `Development`, `" test "`, `" development "`, `"test\n"` → 404, побайтово еднакво състояние. Тези стойности се махат от положителните случаи. Регресия за billing (R0-01 test_09/test_10) остава зелена.

## Забранено
- Промени в billing поведението, в други маршрути, UI, миграции, production, merge, deploy. Нов commit в същия клон; без force-push.

## Тестове и предаване
- R0-07 тестовете на mongomock и реален MongoDB; mutation срещу `af88f29` (новите отрицателни случаи падат там). W0 DB-free 1085 / 15 / 50 (същите 15). A2C и A1: 0 нарушения. R0-01 billing тестовете.
- Бот тест: не е нужен (поведението за нормалните стойности е същото); описва се защо.
- Коментар „HANDOFF C01“ в PR #62 и съобщение: `R0-07-C01 DONE head=<sha> tests=<summary>` или `BLOCKED <reason>`.

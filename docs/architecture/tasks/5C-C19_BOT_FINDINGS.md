# 5C-C19 — склад (PR #55): поправки след бот проверката

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026: „не спирай да програмираш“; Р9). Без merge, без deploy, без пускане на миграция върху реални данни.
> Изпълнител: Claude Code (Opus) · Одит: Claude Audit · Бот: Claude Bot · Codex: след чист бот (пари/склад)
> PR: #55, клон `task5c/live-ops-01-canonical-stock-core`, head `639ca80e89db3d603d17cdded769b01aa4c92bd9`
> Доказателства: `docs/evidence/BOT/5C-C18-639ca80/README.md` @ клон `claude/bot-evidence` (FAIL 33/42). Оркестраторът потвърди F-3 (`TenantCollection.distinct()` без `session`) и че `ensure_required_indexes` не се вика при старт.

## Находки и поправка
| # | Проблем | Поправка |
|---|---|---|
| F-1 | Първи canonical запис при tenant със съществуващи W0-04 `audit_events` → `AUDIT_CHAIN_WRITE_FAILED` (sequence 1 се сблъсква с unique `(tenant_id, sequence)`). `warehouse_movements/indexes.py::ensure_required_indexes` се вика само от тестове → свеж deploy дава 503 `INDEX_MISSING` | Canonical веригата продължава от текущия последен sequence на tenant-а (един общ append-only envelope, CLAUDE.md §2.8 — без втора верига). `ensure_required_indexes` се вика при старт като останалите индекси |
| F-2 | Втора входяща партида → грешка от legacy unique индекс `warehouse_batches(org_id, batch_number)` (`fifo_service.py:181`) срещу canonical редове с `batch_number: null` | Без триене на данни и без втори ledger. Ако е нужна промяна на индекс (напр. partial filter само за непразен `batch_number`), тя е **декларирана, идемпотентна стъпка в кода/миграционния runner**, тествана на реален Mongo, **не се пуска върху production** в тази задача и е описана в HANDOFF |
| F-3 | `GET /warehouse/canonical/integrity-warnings` → 500 (`distinct()` не приема `session`, `queries.py:309`); UI показва лъжливо „няма аларми“ | Поправка на извикването/сигнатурата съвместимо с PR #56. UI показва състояние „грешка“ при неуспешна заявка, никога „всичко е наред“ |
| F-4 | Dispatch от UI с дестинация project/free връща 200 и кредитира обекта преди приемане (заобикаля Rule B) | Сървърът налага: всеки dispatch отива в in_transit/pending; директна дестинация project/free се отказва |
| F-5 | Идентично повторение на consume → 409 `IDEMPOTENCY_CONFLICT` вместо първоначалния резултат | Replay връща първоначалния резултат, както receive |
| F-6 | UI: Accountant (само четене) вижда форма за запис; Warehousekeeper (позволен по API) няма екран (`AdminRoute` → `/tech`); няма поле за СМР при consume | Видимост/маршрути по права (същия Permission Service); поле за СМР |

## Тестове
За всяка находка — real-Mongo регресионен тест, който пада на `639ca80`. Ускорен gate + пълна warehouse real-Mongo матрица; `tests/test_r0_0*.py`; W0 DB-free 1085/15/50; A2C/A1 0; `yarn test` и `yarn build`.

## Забранено
Пускане на миграция/промяна на индекс върху реална база, триене на данни, втори ledger/верига, отслабени тестове, merge, deploy.

## Предаване
`HANDOFF 5C-C19` в PR #55 и съобщение `5C-C19 DONE head=<sha> tests=<summary>`. После Bot повтаря същия сценарий.

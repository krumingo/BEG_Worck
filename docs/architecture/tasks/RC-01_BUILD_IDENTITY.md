# RC-01 — Build identity: същият пълен SHA в API и в UI

> Статус: **ОДОБРЕНА от Крум** („не спирай да програмираш“, 06.11.2026). Без merge и без deploy без отделно „да“.
> Изпълнител: Claude Code · Вътрешен одит: Claude Audit сесия · Бот: Claude Bot сесия · Независим review: Codex
> Източник: PR #64, `docs/evidence/INTEGRATED-RC-2026-10-25/02-release-gates.md`, стъпка 4 („Embed full build SHA in backend metadata and visible UI…“). Codex я е възложил на Claude.
> База: `main` @ `c0e34e1f3037010311d352683d519c3c9d7dcbfa` · Клон: `claude/rc-01-build-identity` → Draft PR към `main`
> Канон: CLAUDE.md §6 (всеки deployment пази app version, Release Manifest и rollback target); `ops/release/` (W0-09A).

## Защо
На Synology не може да се докаже коя версия работи. Codex го доказа на ръка, с 1043 файла по SMB. След deploy трябва да е видимо с един поглед: UI и API показват един и същ пълен commit SHA, плюс етикет на средата.

## Обхват
1. **Източник на идентичността.** Пълен 40-символен SHA, взет при build от неизменими Git обекти: `ops/release/release_build.py` / manifest. Записва се във файл, който влиза в артефакта, например `backend/BUILD_INFO.json` и `frontend` build константа. Редактируема runtime променлива **не е единственият** източник. Ако в един build липсват едновременно файл и env, стойността е `"unknown"` и UI го показва ясно.
2. **Backend.** `GET /api/version` без вход връща само `{build_sha, build_time, environment_label, schema_version?}`. Без тайни, без пътища, без hostname. `/api/health` остава съвместим.
3. **Frontend.**
   - SHA-то на frontend build-а е вградено при build.
   - Видимо е за всички: първите 12 знака в долния край на менюто и на login екрана, с пълния SHA в tooltip.
   - При разлика между frontend SHA и `/api/version` се показва видимо предупреждение „Версията на интерфейса и сървъра се различава“. **Това е тестван случай на несъответствие.**
4. **Етикет на средата.** `production`/`staging`/`development`/`test` идва от същата fail-closed политика като R0-07/R0-01 (`ENV`). Неизвестна стойност → `unknown`. Не се показват тайни.
5. **Release Manifest.** `ops/release` записва същия SHA. Тест доказва, че manifest, API и frontend константата съвпадат за един build.

## Забранено
- Deploy, production, промяна на Synology, промяна на `PERMISSION_SERVICE_MODE`, миграции.
- Тайни в отговора, в UI или в логовете.
- Промени извън идентичността на версията.

## Тестове
- Backend: `/api/version` с файл, само с env, без нищо (`unknown`), и с env, който противоречи на файла (файлът печели; разминаването се записва в лог). Отговорът не съдържа тайни (позитивен списък на ключовете).
- Frontend (`yarn test`): показва SHA-то; при несъответствие показва предупреждението; при `unknown` също.
- `ops/release` тест: SHA-то в manifest съвпада с API и frontend.
- Всички `tests/test_r0_0*.py` зелени. W0 DB-free: 1085 / 15 / 50 със същите 15. A2C и A1: 0 нарушения. `yarn build` минава.

## Бот (прави го Bot сесията)
Локален build с известен SHA:
1. Login екран и меню показват SHA-то (скрийншот).
2. `/api/version` показва същото (JSON).
3. Принудително несъответствие (backend с друг SHA) → предупреждение (скрийншот).
4. 390×844 без хоризонтален скрол.
Доказателства в `docs/evidence/RC-01/`.

## Предаване
- Draft PR `RC-01 — build identity in API and UI`; коментар `HANDOFF RC-01`; съобщение до оркестратора `RC-01 DONE pr=<n> head=<sha> tests=<summary>` или `RC-01 BLOCKED <reason>`.

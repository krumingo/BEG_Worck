# BEG_Work — отчет на Claude (имплементация) към 21.10.2026

> Автор: Claude (оркестратор/имплементация). Независимата проверка е в отделния отчет на Codex.
> Обхват: Етап 0 / R0 от плана за възстановяване (PR #57, `docs/architecture/tasks/BACKLOG_2026-10-17.md`).
> Легенда: **[ДОКАЗАНО]** = пуснато от мен с изход, или Codex PASS в PR; **[НЕПРОВЕРЕНО]** = твърдение без мое доказателство.
> Този отчет **не обявява Implementation Gate PASS** (CLAUDE.md §16).

## 1. Последна завършена задача и какво реално работи

**Последна слята задача:** R0-03 (AUD-025 + AUTH-01 F-03, решение Р6), PR #63.

Какво работи в `main` — доказано с тестове на mongomock и на реален MongoDB 7.0 replica set в контейнер, **не на Synology**:

| Задача | Находка | Поведение | Доказателство |
|---|---|---|---|
| R0-01 | AUD-009, AUD-045 | Stripe webhook само с валиден подпис. Mock billing е забранен извън dev/test | Codex PASS, PR #58 [ДОКАЗАНО] |
| R0-02 | AUD-026 | Артикулите се филтрират по фирма, с guard | Codex PASS, PR #59 [ДОКАЗАНО] |
| R0-05 | AUD-023 | Pay Run съдържа само избраните служители. Сумите приемат само крайни числа | Codex PASS, PR #60 [ДОКАЗАНО] |
| R0-06 | AUD-043 | Платен Pay Run не се отваря наново. Няма двойно плащане (атомарен mark-paid, `op_lock`) | Codex PASS, PR #61 [ДОКАЗАНО] |
| R0-07 | AUD-039 | `/api/dev/reset-warehouses` работи само при `ENV=development/test`, иначе дава 404. Само за Admin/Owner | Codex PASS, PR #62 [ДОКАЗАНО] |
| R0-03 | AUD-025, AUTH-01 F-03 | Няма ескалация на роли. Owner е защитен, последният Owner остава. Един имейл = един User в цялата инсталация (409/503 fail-closed). Login при дубликат дава 409 | Codex PASS, PR #63 [ДОКАЗАНО] |

**R0 находки: 7 от 7 поправени в `main`.** Етап 0 обаче **не е затворен**, защото AUTH-01 (R0-04) и проверките в production (R0-08) са отворени.

## 2. Branch, PR, пълни SHA

| PR | Branch | Merge в `main` (пълен SHA) |
|---|---|---|
| #58 R0-01 | — | `ce072b7b921522eea7d83d638cebeb5c3e873155` |
| #59 R0-02 | — | `41f2afff99ff8845dfba9396ef090426825b628d` |
| #60 R0-05 | `claude/r0-05-*` | `078b8e7c57c7b146ff790d4129984ec6075faa16` |
| #61 R0-06 | `claude/r0-06-*` | `23f223ef40f93801e2dfbfb2b67b6c5c704820a0` |
| #62 R0-07 | `claude/r0-07-dev-reset` | `db94561713bed714a56566391487a1593139a920` |
| #63 R0-03 | `claude/r0-03-roles-email` (последен head `196e7b7980e2a6ef9939785bcf59bd0460dff7c7`) | `c0e34e1f3037010311d352683d519c3c9d7dcbfa` = **текущ `main`** |
| **#56 R0-04 (отворен, draft)** | `claude/auth-owner-recovery-forgot-password-sfv359` | head `8e435a0e8823ff49d11dfe2803968b27701c688e` (merge на `main` c0e34e1 + C01 `5e9700c`), **не е слят** |

Планът и пакетите са в клон `claude/happy-meitner-bmcnel` (Draft PR #57).

## 3. Изпълнени тестове (мои пускания)

| Head | Пакет | Успешни | Неуспешни | Пропуснати |
|---|---|---|---|---|
| `196e7b7` (R0-03 финал) | `tests/test_r0_0*.py`, mongomock + реален Mongo | 814 | 0 | 0 |
| `196e7b7` | W0 DB-free `tests/test_w0_*.py` | 1085 | 15 | 50 |
| `196e7b7` | A2C guard / A1 guard | 203 модула / 412 единици | 0 нарушения | — |
| `8e435a0` (R0-04) | `tests/test_auth_01_*.py` + `tests/test_r0_0*.py`, mongomock + реален Mongo | 881 | 0 | 0 |
| `8e435a0` | W0 DB-free | 1085 | 15 | 50 |
| `8e435a0` | A2C / A1 guard | 210 / 424 | 0 нарушения | — |

- 15-те неуспешни са **същите** стари тестове в `tests/test_w0_03e_legacy_routes.py`, падат и в `main` преди R0. Записани са като дълг и не са поправени.
- **Не са пускани:** `tests/test_platform_bootstrap.py`, `tests/test_admin_set_password.py` и другите live-server тестове. Те искат работещ сървър (`base_url`).
- Frontend `yarn test` 101/101 и `yarn build` на `8e435a0`: по отчета на имплементатора. **[НЕПРОВЕРЕНО от мен]**
- Бот тестове (Playwright, локално копие, тестови данни): R0-03 PASS, R0-04 15/15 PASS. Прегледах скрийншотите в `docs/evidence/R0-03/` и `docs/evidence/R0-04/`. [ДОКАЗАНО локално]
- Mutation проверки: по отчета на имплементатора (`docs/evidence/R0-0x/mutation_*.txt`). **[НЕПРОВЕРЕНО от мен]**

## 4. Независим review и оставащи дефекти

- PR #58–#63: Codex **PASS** на крайния head на всеки. Последният: https://github.com/krumingo/BEG_Worck/pull/63#issuecomment-6295338555
- **PR #56 (R0-04): чака Codex.**
  - Последната присъда на Codex е CHANGES_REQUESTED на стария head `8892738` (F-01…F-08): https://github.com/krumingo/BEG_Worck/pull/56#issuecomment-6216184918
  - Корекциите C01 (`5e9700c`) и merge-ът R0-04 (`8e435a0`) **не са ревюирани от Codex**.
- Записан дълг, без поправка и без блокер според Codex:
  - Approval за промени по Owner, защото DQ/Approval runtime го няма;
  - уникален индекс на имейла и състезание при едновременно създаване;
  - сливане на съществуващи дубликати (R0-09);
  - пълен модел User/TenantMembership;
  - reversal + Approval за платени Pay Run-ове;
  - 15-те стари неуспешни W0 теста;
  - hard delete на потребител в off/shadow.

## 5. Слято и деплойнато на Synology

- **Слято в `main`:** всичко от т. 2 до `c0e34e1`. [ДОКАЗАНО]
- **Деплойнато на Synology (`http://192.168.1.112:8080/`): НЕИЗВЕСТНО.** [НЕПРОВЕРЕНО]
  - Нямам доказателство коя версия работи там.
  - Моят облачен контейнер не стига до LAN адреса: опитът на 20.10.2026 ~17:10 UTC даде timeout.
  - Не съм влизал и не съм деплойвал нищо. Никой deploy не е одобрен в този цикъл.

## 6. Готово за следващ deploy и какво го блокира

- **Кандидат:** `main` @ `c0e34e1f3037010311d352683d519c3c9d7dcbfa` (R0-01…R0-07 + R0-03).
- **Блокери преди deploy:**
  1. Няма Release Manifest за тази версия: app/schema/config version, флагове, rollback target (CLAUDE.md §6). Това е задача R0-10.
  2. Не е проверено какво има на Synology. Не са проверени реалните данни (R0-08, само четене): `ENV` на сървъра, mock абонаменти, дублирани имейли, дали MongoDB е replica set.
  3. Дублираните имейли в реалните данни ще получат 409 при login след deploy-а на R0-03. Нужен е отчетът `scripts/r0_03_email_duplicates_report.py` върху реалната база **преди** deploy.
  4. Решение на Крум за deploy. Няма такова.
- **R0-04 (PR #56) не е готов за deploy:** чака Codex. Изисква MongoDB replica set и SMTP/`APP_PUBLIC_URL` конфигурация.

## 7. Следваща задача, отговорен, кой е на ред

| # | Задача | Отговорен | На ред |
|---|---|---|---|
| 1 | Codex re-review на PR #56 @ `8e435a0` (текстът е готов) | Codex | **Крум** да предаде текста |
| 2 | R0-08: read-only проверки на Synology (replica set, ENV, дубликати, mock). Трябва да тръгнат **от компютър в LAN** (Claude Desktop / `claude remote-control`) с тестов акаунт | Claude (пакет), изпълнение от LAN | Крум (одобрение и достъп) |
| 3 | R0-10: Release Manifest + deploy план | Claude/ChatGPT | след R0-08 |

Последна присъда, която чака отговор от Крум: няма. Отворено е само предаването към Codex на PR #56.

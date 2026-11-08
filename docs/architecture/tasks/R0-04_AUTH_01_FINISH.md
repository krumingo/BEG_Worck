# R0-04 — AUTH-01 довършване: PR #56 върху новия main (F-01…F-08)

> Статус: **ПРЕДЛОЖЕНА — чака „да“ от Крум**
> Изпълнител: Claude Code (**Opus** — сигурност) · Ревю: Codex · Решение: Крум
> PR: #56 (draft), клон `claude/auth-owner-recovery-forgot-password-sfv359`, head `5e9700c536f36208e687a01c906e12e56f1f63b3`
> Codex review: https://github.com/krumingo/BEG_Worck/pull/56#issuecomment-6216184918 (CHANGES_REQUESTED на `8892738`, F-01…F-08)
> База сега: `main` @ `c0e34e1f3037010311d352683d519c3c9d7dcbfa` (след R0-01, R0-02, R0-05, R0-06, R0-07, R0-03)
> Решение Р6 (Крум, 18.10.2026): един имейл = един User в цялата инсталация.

## Какво е сега (проверено от оркестратора)
- PR #56 е на стария main `79af297`. Head `5e9700c` (C01) твърди, че поправя F-01…F-08, но **Codex не го е ревюирал**.
- Merge на `main` в клона дава **6 конфликта**: `backend/app/routes/auth.py`, `backend/app/routes/platform.py`, `backend/app/tenancy/onboarding.py`, `backend/app/tenancy/ownership.py`, `backend/scripts/w0_03e_a2c_tenant_boundary_guard.py`, `docs/architecture/W0-03E-A2B_INVENTORY.md`.
- **Дублиране с R0-03.** C01 на #56 реализира F-03 (един имейл = един login) по свой начин. Има свой helper за имейл, свой скрипт за дубликати `scripts/auth_duplicate_emails_report.py` и свои проверки в `POST /users`, onboarding и bootstrap. В main това вече е направено от R0-03: `app/tenancy/identity.py`, `scripts/r0_03_email_duplicates_report.py`, 409 `EMAIL_EXISTS`, 409 `DUPLICATE_IDENTITY`, fail-closed 503.

## Обхват
1. **Merge на `main` в клона на #56** с merge commit, без rebase и без force-push. Конфликтите се решават с правилото **main (R0-03) е източникът за идентичност**:
   - една реализация: `app/tenancy/identity.py` (нормализиране, търсене в цялата инсталация, fail-closed);
   - премахва се дублиращият код на #56: helper-ите за имейл и `scripts/auth_duplicate_emails_report.py`. Остава `r0_03_email_duplicates_report.py`;
   - login: договорът на R0-03 (409 `DUPLICATE_IDENTITY` само за знаещ паролата, иначе 401). Добавя се проверката `auth_version` (F-02);
   - forgot-password: при повече от един User по имейл → същият общ 200, без token, + security event (F-08);
   - `POST /users`, onboarding, bootstrap, seed: остава поведението на R0-03 (409/503). Новото от #56 се добавя само където липсва.
   - A2C/A1 guard списъците и инвентарът се регенерират с инструментите, не на ръка.
2. **F-01…F-08 остават изпълнени** след merge-а: транзакции (F-01), `auth_version` и JWT `av` (F-02), trusted proxies и споделен лимитер (F-04), тайминг (F-05), статус на доставката (F-06), CLI само с hidden prompt (F-07), `auth_security_events` (F-08). Code проверява всяка с тест след merge-а.
3. **AuditEvent.** Успешен reset/recovery пише и canonical W0-04 AuditEvent, както R0-03 за паролите (без парола, хеш, token). Legacy `audit_logs` остава.
4. **Изискване за replica set (F-01).** Транзакциите изискват MongoDB replica set. Code описва в PR-а какво става на standalone сървър: отказ преди запис, с какъв код. Записва го като задължителна проверка в R0-08 (production). **Без промяна на production.**

## Забранено
- Production, deploy, merge в main, миграции, промяна на данни, уникален индекс.
- Втора реализация на идентичност, втори регистър или втори скрипт за дубликати.
- Промяна на поведение от R0-01…R0-07 извън конфликтите.

## Тестове
- `tests/test_auth_01_password_recovery.py` + `tests/test_auth_01_c01_corrections.py` + всички `tests/test_r0_0*.py`: зелени на mongomock **и** на реален MongoDB replica set (Docker). Реалният Mongo вече е задължителен (F-01 транзакции).
- Нови тестове за слятото поведение:
  - forgot-password при дубликат → общ 200, без token, със security event;
  - login със стар JWT след reset → 401;
  - `DUPLICATE_IDENTITY` не се е променил.
- W0 DB-free: 1085 / 15 / 50 със същите 15 (или по-добре, описано). A2C и A1: 0 нарушения. Frontend `yarn test` и `yarn build`.
- Mutation: новите тестове падат на `5e9700c` или на `main`, според случая.

## Бот тест (задължителен)
Локален backend + frontend, MongoDB replica set в Docker, SMTP изключен, `PASSWORD_RESET_DEV_LOG_URL=1`:
1. Login → „Забравена парола?“ → имейл → общо потвърждение (скрийншот).
2. Линкът от dev лога → нова парола → успех → вход с новата парола (скрийншот).
3. Старият таб със старата сесия → изхвърлен към login (F-02, скрийншот).
4. Същият линк втори път → „невалиден линк“ (скрийншот).
5. 375px и 1280px без хоризонтален скрол.
Доказателства в `docs/evidence/R0-04/`.

## Предаване
- Push в клона на #56 (merge commit + корекции). Описанието на PR-а се обновява: нова база, head, поведение, тестове, дълг.
- Коментар `HANDOFF R0-04` в PR #56 и съобщение `R0-04 DONE pr=56 head=<sha> tests=<summary> bot=<pass/fail>` или `R0-04 BLOCKED <reason>`.

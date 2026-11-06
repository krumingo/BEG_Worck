# FLOW GUARD — разминавания

Формат на всяка находка:

- канон: файл и раздел, с цитат;
- код: файл:ред, PR и SHA;
- какво казва канонът / какво прави кодът;
- тежест;
- статус;
- доказателство: PROVEN или SUSPECTED;
- предложено решение: промяна в кода или решение на Крум. Никога „промени FLOW“.

Статуси:

- `open` — открита;
- `confirmed` — потвърдена от оркестратора;
- `resolved` — затворена.

## Обобщение

| ID | Тежест | Къде | Кратко | Доказателство | Статус |
|---|---|---|---|---|---|
| FG-1 | high | main `07da9ab` | `/labor-entries`: всеки потребител записва труд за всеки и чете ставките | PROVEN | open |
| FG-2 | high | #67 `e987892` + пакет ST-02 | staging по подразбиране `enforce`, а Р15 казва `shadow` | PROVEN | open |
| FG-3 | medium | #67 `e987892` | Release Manifest очаква един флаг, staging върви с друг; проверката е заобиколена | PROVEN | open |
| FG-4 | medium | #67 `e987892` | deployed_by/approved_by = `unknown` | PROVEN | open |
| FG-5 | medium | #67 `e987892` | isolation guard не проверява накъде сочат UI/API URL | PROVEN | open |
| FG-6 | low | #67 `e987892` | `ST02_ALLOWED_MONGO_HOSTS` пуска всеки хост | PROVEN | open |
| FG-7 | high | #56 `dae097b` | CLI за възстановяване = break-glass без Approval и без човек-актьор | PROVEN | open |
| FG-8 | medium | #56 `dae097b` | „owner“ CLI сменя паролата на всяка роля | PROVEN | open |
| FG-9 | medium | #56 `dae097b` | AuditEvent на възстановяването е R3, канонът иска R1 | PROVEN | open |
| FG-10 | medium | #56 `dae097b` | security събитията се трият след 180 дни; канонът иска ≥ 2 години | SUSPECTED | open |
| FG-11 | medium | #56 `dae097b` | admin set-password не прекъсва старите сесии и линкове | SUSPECTED | open |
| FG-12 | medium | main `07da9ab` | Permission Service: обединение на правата срещу „по-ограниченото има предимство“ | SUSPECTED | open |
| FG-13 | medium | пакет SEC-02 `ccb00ab` | конкретна матрица „роля × четене на финанси“, която каноничният текст не определя | SUSPECTED | open |
| FG-14 | medium | пакет SEC-02 `ccb00ab` | SiteManager е наречен „проектна ръководна роля“; каталогът го води като Технически ръководител | SUSPECTED | open |
| FG-15 | medium | пакет SEC-02 + main | Р16 дава на Technician запис на труд, а отговорът връща ставка и стойност; SEC-02 не го покрива | PROVEN | open |
| FG-16 | low | #56 `dae097b` | твърд резервен HMAC ключ в кода | SUSPECTED | open |

Находките по #55 (склад) и #69/#68 (права) се добавят, щом прегледът им приключи.

---

## FG-1 — `/labor-entries`: всеки потребител записва труд за всеки и чете ставките

- **Тежест:** high (Р3: сигурност и пари = „боли“ по дефиниция). **Статус:** open. **PROVEN.**
- **Канон:**
  - Р16: „труд (labor entries) … могат да въвеждат и **SiteManager и Technician, само за обекти, на които са членове**; Owner/Admin/Accountant — навсякъде; Viewer и Driver — не.“
  - FLOW-002 „Какво НЕ трябва да позволява“: „директен URL да заобикаля правата“.
  - FLOW-037 §3.4: „Не вижда чужди заплати, договори, маржове …“.
  - CLAUDE.md §14: всеки consequential write има permission check и AuditEvent.
- **Код (main `07da9ab`):**
  - `backend/app/routes/labor_smr.py:32-64` (`POST /labor-entries`) има само `require_m2`, т.е. модул в абонамента. Няма роля, членство или AuditEvent. `employee_id` идва от тялото на заявката, а отговорът връща `hourly_rate` и `labor_cost`.
  - `labor_smr.py:141-155` (`GET /labor-entries`) връща всички записи с ставки, без проверка на роля или членство.
- **Проба:** `docs/flow-guard/probes/fg1_labor_entries_probe.py`. Реален Mongo, ST-01 seed, без нито един член на екипа на обекта. Резултат:
  - viewer, driver, technician и warehousekeeper получават `POST` 201 за чужд служител (Owner) и виждат `labor_cost` 300.0;
  - същите роли получават `GET` 200 и виждат `hourly_rate` 37.5;
  - 0 audit реда.
- **PR #69 (SEC-01) `e6c0e46`:** добавя `require_money_write("labor.entry.create")` на `POST` (`labor_smr.py:33-38`). `GET` остава отворен — това е обхватът на SEC-02. Дали `POST` спазва Р16 (Technician/SiteManager на свои обекти) се проверява в находките за #69.
- **Решение:** промяна в кода.
  - Запис: по Р16, с проверка за членство и с AuditEvent.
  - `employee_id` на чужд служител да се позволява само на ръководни роли.
  - Четене: ставка и стойност само за роли с финансово право (SEC-02).

## FG-2 — staging по подразбиране `enforce`, а Р15 казва `shadow`

- **Тежест:** high. **Статус:** open. **PROVEN.**
- **Канон:** Р15: „тестовата инсталация (staging) тръгва с `PERMISSION_SERVICE_MODE=shadow`.“
- **Код (#67 `e987892`):**
  - `ops/staging/staging_up.py:597-598` има `default="enforce"`;
  - `ops/staging/README.md:177,197`;
  - доказателствата на репетицията: `docs/evidence/ST-02/README.md:67`, `summary.json:228` (mode = enforce);
  - `isolation_check.py:196` сравнява само с подадения параметър.
- **Пакетът също противоречи:** ST-02 `docs/architecture/tasks/ST-02_ISOLATED_STAGING_STACK.md:13` казва „по подразбиране `enforce` за staging“. Пакетът вероятно е писан преди Р15 (06.11.2026).
- **Решение:**
  - Промяна в кода: подразбиране `shadow`; `enforce`/`off` да се отказват без записано изключение от Крум. Репетицията да се пусне отново.
  - Пакетът ST-02 да се приведе към Р15 (пакетът не е FLOW).

## FG-3 — Release Manifest очаква един флаг, staging върви с друг

- **Тежест:** medium. **Статус:** open. **PROVEN** (от доказателствата на PR-а).
- **Канон:**
  - FLOW-042 §Release Manifest: „Липсващо или несъвпадащо поле блокира deployment-а.“
  - CLAUDE.md §6: всеки deployment пази „Feature Flags/Entitlements snapshot“.
- **Код (#67 `e987892`):**
  - `manifest.json:127` очаква `PERMISSION_SERVICE_MODE` = `off`;
  - `ops/staging/staging_deploy.sh:15-17,76` (`staging_overrides`) подменя очакването с параметъра на staging;
  - `verify.json` не записва действителната стойност.
- **Решение:** промяна в кода. Действителният флаг на staging да влиза в deployment записа и в manifest/environment config, така че двете да съвпадат. Ако се иска overlay за staging — решение от Крум къде се записва.

## FG-4 — deployed_by/approved_by не се записват

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** FLOW-050: „Всеки deployment пази … deployed_by, approved_by, rollback target и post-deployment result.“
- **Код (#67 `e987892`):**
  - трите `record.json:13` имат `"actor": "unknown"`;
  - `manifest.json:110` има `"created_by": "unknown"`; източникът е резервната стойност в `lib.sh:51`;
  - `staging_up.py:63` записва само validation ref, не одобряващ.
- **Решение:** промяна в кода. Deployer и approver да са задължителни параметри; без тях — отказ.

## FG-5 — isolation guard не проверява накъде сочат UI/API URL

- **Тежест:** medium. **Статус:** open. **PROVEN** (offline проба с променен compose модел).
- **Канон:**
  - CLAUDE.md §6: отделни среди; „Production data/secrets не се копират свободно в non-production“.
  - FLOW-042: „никога директно в production“.
  - Пакет ST-02-C01: отказ при production цели.
- **Код (#67 `e987892`):** `ops/staging/isolation_check.py:193-219` проверява Mongo, имената на базите и mounts. Не проверява `PUBLIC_URL`, `CORS_ORIGINS`, build arg `REACT_APP_BACKEND_URL`, нито ключове за bootstrap/seed-admin. Пробата с production URL и с `PLATFORM_BOOTSTRAP_TOKEN` получава PASS.
- **Важно:** пътят по подразбиране е безопасен (`staging_up.py:166-175` пише `127.0.0.1:<port>`). Дупката е само при ръчна редакция на `.env`.
- **Решение:** промяна в кода. Тези стойности да са задължително `127.0.0.1:<ST02_HTTP_PORT>` или изброен staging хост. Bootstrap/seed-admin ключовете да влязат в забранения списък.

## FG-6 — `ST02_ALLOWED_MONGO_HOSTS` пуска всеки хост

- **Тежест:** low. **Статус:** open. **PROVEN.**
- **Код (#67 `e987892`):** `isolation_check.py:60-71,206`, `staging_deploy.sh:100`. Стойност `nas-prod.lan` минава.
- **Решение:** решение на Крум — допуска ли се staging Mongo извън локалната машина.
  - Ако не — опцията да се махне.
  - Ако да — denylist на production хостовете.

## FG-7 — CLI за възстановяване = break-glass без Approval и без човек-актьор

- **Тежест:** high. Става blocker, ако Крум приеме, че CLI е L5 break-glass. **Статус:** open. **PROVEN.**
- **Канон:**
  - FLOW-040 §10 L5: „Временен достъп при incident/restore/support, само към необходимия scope, с две независими одобрения, срок, автоматичен revoke и пълен audit.“
  - CLAUDE.md §8: Approval е задължителен за „Support/Partner/Break-glass access“.
  - FLOW-002 „Двустепенно одобрение“: „Един човек не може да изпълни и двете стъпки …“.
- **Код (#56 `dae097b`):** `backend/scripts/reset_user_password.py:101-138, :203`.
  - Всеки с shell сменя паролата на всеки потребител с една стъпка.
  - Няма Approval, причина или именуван оператор.
  - AuditEvent записва `actor_id="LOCAL_RECOVERY_CLI"`, `actor_type="system"`.
- **Проба:** реален Mongo, база `fg56_probe`. Получен е AuditEvent `user.password_recovery_cli`, actor `LOCAL_RECOVERY_CLI`, retention `R3`.
- **Решение:** решение на Крум — L5 ли е CLI-то?
  - Ако да: промяна в кода — Approval ref (двама души), задължителен `--reason`, идентичност на оператора в AuditEvent.
  - Ако не: изключението да се запише като D-решение във FLOW-043.

## FG-8 — „owner“ CLI сменя паролата на всяка роля

- **Тежест:** medium. **Статус:** open. **PROVEN** (същата проба: потребител Technician е reset-нат).
- **Канон:** CLAUDE.md §3: „temporary scoped Support/Break-glass access grants“. FLOW-040 §11: business content само „чрез break-glass, две одобрения и time-bound access“.
- **Код (#56 `dae097b`):** `reset_user_password.py:190-204` няма проверка на роля. Покрива и `is_platform_admin`.
- **Решение:** промяна в кода — само Owner, или изричен флаг + Approval за другите роли. Крум да реши кои роли покрива.

## FG-9 — AuditEvent на възстановяването е R3, канонът иска R1

- **Тежест:** medium. **Статус:** open. **PROVEN** (пробата: `retention_class` = `R3`).
- **Канон:** FLOW-040 §R3: „Промени на права, break-glass и security incidents са R1.“
- **Код (#56 `dae097b`):** `services/user_role_policy.py:205-209` слага твърдо `RETENTION_R3_SECURITY_ACCESS`; извиква се от `reset_user_password.py:132`.
- **Решение:** промяна в кода — R1 за възстановяване през CLI. Зависи от отговора по FG-7.

## FG-10 — security събитията се трият след 180 дни; канонът иска ≥ 2 години

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (от кода; не е изпълнено).
- **Канон:** FLOW-040 §R3 (failed login, permission denied, session/device/IP metadata): „Минимално съхранение: **2 години** от събитието.“ CLAUDE.md §2.8: append-only AuditEvent.
- **Код (#56 `dae097b`):**
  - `services/auth_events.py:35` `RETENTION = timedelta(days=180)` + TTL индекс (`:68`).
  - Docstring-ът и `AUTH-01_PASSWORD_RECOVERY.md:34` го наричат „owner decision“, но такова решение няма в `docs/flows`, FLOW-043 или Decision Register.
- **Решение:** ако 180 дни не е записано решение на Крум — промяна в кода, минимум 2 години. Иначе да се запише като D-решение.

## FG-11 — admin set-password не прекъсва старите сесии и линкове

- **Тежест:** medium. **Статус:** open. **SUSPECTED.**
- **Канон:** няма изрично правило. Това е P0 по сигурност по Р3.
- **Код (#56 `dae097b`):**
  - `routes/auth.py:690-698` не прави `$inc auth_version` и не отменя `password_reset_tokens`;
  - change-password (`auth.py:234`) също не вдига `auth_version`.
  - Ефект: след reset от админ стар JWT или линк остава валиден до 30 мин.
- **Решение:** промяна в кода — `auth_version` + отмяна на токените в същата транзакция (Р3).

## FG-12 — Permission Service: обединение на правата срещу „по-ограниченото има предимство“

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (от кода).
- **Канон:** FLOW-002 „Обхват на правата“: „По-ограниченото право има предимство.“ Пакетът SEC-02 стъпва точно на това правило.
- **Код (main `07da9ab`):** `backend/app/permissions/service.py:160-176` позволява, ако **кое да е** активно назначение позволява. Няма назначение-ограничение (deny/лимит), което да бие по-широко назначение. Например обектово „само преглед“ не може да ограничи фирмено право за същия обект.
- **Днес на практика:** не-админ ролите на ниво фирма нямат `budget.*` (`catalog.py:83-89`), затова днес рядко изпъква.
- **Решение:** решение на Крум за тълкуването. Ако „по-ограниченото“ значи „ограничение/забрана бие разрешение“ — промяна в кода (deny-overrides, или max_amount/scope ограничение с предимство).

## FG-13 — SEC-02: матрица „роля × четене на финанси“, която каноничният текст не определя

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (пакет срещу канон, четене).
- **Пакет:** `docs/architecture/tasks/SEC-02_FINANCE_READ_PER_CANON.md` @ `ccb00ab`. Пише: „Не е ново бизнес решение — прилагане на заключен канон“.
- **Какво казва канонът:**
  - FLOW-002 дава модела (роля × обхват, „по-ограниченото …“), но не и таблица кой чете кои финанси.
  - FLOW-010 §4.1–4.2: себестойност/марж — за „служители и упълномощени вътрешни роли“; скрито е само от клиента.
  - FLOW-037 §3.4: Работник „не вижда чужди заплати, договори, маржове“.
  - FLOW-046: клиентът не вижда себестойност/марж/payroll.
- **Какво е ново в пакета:**
  - правила 1–2 (финанси на ниво фирма само Owner/Admin/Accountant; пари на ниво обект — не за Technician/Warehousekeeper/Driver; SiteManager — според съседните екрани);
  - правило 4 (склад: количества да, стойности не).
  - Това са конкретни решения кой е „упълномощен“. Цитираният източник за Viewer е код (`catalog.py`), не FLOW.
  - Р14 решава само записите, а за четенето определя само реда („После … четенето на финанси“).
- **Важно:** пакетът **не противоречи** на канона — посоката е по-ограничителна и съвпада с FLOW-037/046.
- **Решение:** преди старта на SEC-02 Крум да потвърди с едно изречение таблицата „роля → финансово четене“ (правила 1, 2 и 4), за да стане записано решение (Р17 или D-решение). До тогава SEC-02 може да тръгне само с безспорната част: Viewer без членство да не чете финанси (FLOW-002 + FLOW-037).

## FG-14 — SEC-02: SiteManager е наречен „проектна ръководна роля“

- **Тежест:** medium. **Статус:** open. **SUSPECTED.**
- **Пакет SEC-02 правило 2:** „**проектни ръководни роли** (SiteManager) — само на свои обекти …“.
- **Код и канон:**
  - `backend/app/permissions/catalog.py:186` мапва `SiteManager → site_manager` = „Технически ръководител“ (`catalog.py:93`).
  - Каноничният „Проектен мениджър“ (`project_manager`, `catalog.py:98`) няма legacy източник и пакетът не го споменава.
  - FLOW-037 §3.1 (екран на Техническия ръководител) не изброява пари.
- **Решение:**
  - Пакетът да назовава каноничните `role_id` (`site_manager` / `project_manager`).
  - Крум да каже дали Технически ръководител вижда пари на обекта (влиза в отговора по FG-13).

## FG-15 — Р16 дава на Technician запис на труд, а отговорът връща ставка и стойност

- **Тежест:** medium. **Статус:** open. **PROVEN** (FG-1 пробата: отговорът на `POST /labor-entries` съдържа `hourly_rate` и `labor_cost`).
- **Канон:**
  - Р16: Technician и SiteManager въвеждат труд на свои обекти.
  - SEC-02 правило 2: Technician — без пари на ниво обект.
  - FLOW-037 §3.4: без чужди заплати.
- **Код:** `backend/app/routes/labor_smr.py:57-64` (main; същото в #69) връща ставката на служителя, за когото е записът. Пакетът SEC-02 изброява GET endpoint-и от PM-01 §5.2, но не и отговорите на записите.
- **Решение:** промяна в кода, в обхвата на SEC-02:
  - `hourly_rate`/`labor_cost` скрити в отговора на `POST`/`sync` и в `GET /labor-entries` за роли без финансово право;
  - пакетът SEC-02 да добави „отговорите на записи по Р16“.

## FG-16 — твърд резервен HMAC ключ в кода

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** CLAUDE.md §16: „не записвай secrets в Git“.
- **Код (#56 `dae097b`):** `services/auth_events.py:55-56`. Резервният литерал `dev-auth-event-key-NOT-FOR-PRODUCTION` се ползва, ако няма `AUTH_EVENT_HMAC_KEY`/`JWT_SECRET`.
- **Решение:** промяна в кода — в production да отказва без ключ.

## Бележки, които не са разминавания

- #67: доказателствата казват „50 passed“, а тестовете вече са 110. 26 реда с локални пътища на scratchpad.
- #67: `schema_version` и `entitlements.snapshot` = null идват от main (W0-08 не е изпълнен). Това е дълг спрямо CLAUDE.md §6, не грешка на PR-а.
- Пакетът R0-04 мълчи за Approval/break-glass и срока на security събитията. Затова FG-7…FG-10 не са грешка на изпълнителя.

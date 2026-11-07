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
| FG-1 | high | main `07da9ab` | `/labor-entries`: всеки потребител записва труд за всеки и чете ставките | PROVEN | resolved (POST: #69; GET: #71 `6080165`, PROVEN) |
| FG-2 | high | #67 `e987892` + пакет ST-02 | staging по подразбиране `enforce`, а Р15 казва `shadow` | PROVEN | resolved (#67 `98b18ec`) |
| FG-3 | medium | #67 `e987892` | Release Manifest очаква един флаг, staging върви с друг; проверката е заобиколена | PROVEN | resolved (#67 `98b18ec`; Р26 → manifest в `675faba`) |
| FG-4 | medium | #67 `e987892` | deployed_by/approved_by = `unknown` | PROVEN | resolved (#67 `98b18ec`) |
| FG-5 | medium | #67 `e987892` | isolation guard не проверява накъде сочат UI/API URL | PROVEN | resolved (#67 `98b18ec`) |
| FG-6 | low | #67 `e987892` | `ST02_ALLOWED_MONGO_HOSTS` пуска всеки хост | PROVEN | resolved (#67 `98b18ec`; потвърдено с Р25) |
| FG-7 | high | #56 `dae097b` | CLI за възстановяване = break-glass без Approval и без човек-актьор | PROVEN | resolved по Р19 (#56 `3234446`) — виж FG-33 |
| FG-8 | medium | #56 `dae097b` | „owner“ CLI сменя паролата на всяка роля | PROVEN | resolved (#56 `3234446`) |
| FG-9 | medium | #56 `dae097b` | AuditEvent на възстановяването е R3, канонът иска R1 | PROVEN | resolved (#56 `3234446`) |
| FG-10 | medium | #56 `dae097b` | security събитията се трият след 180 дни; канонът иска ≥ 2 години | SUSPECTED | resolved (#56 `3234446`) |
| FG-11 | medium | #56 `dae097b` | admin set-password не прекъсва старите сесии и линкове | SUSPECTED | open, low — остава собствената смяна на парола |
| FG-12 | medium | main `07da9ab` | Permission Service: обединение на правата срещу „по-ограниченото има предимство“ | SUSPECTED | open — в пакета SEC-02 (добавка) |
| FG-13 | medium | пакет SEC-02 `ccb00ab` | конкретна матрица „роля × четене на финанси“, която каноничният текст не определя | SUSPECTED | resolved по Р20 |
| FG-14 | medium | пакет SEC-02 `ccb00ab` | SiteManager е наречен „проектна ръководна роля“; каталогът го води като Технически ръководител | SUSPECTED | resolved (добавка към SEC-02) |
| FG-15 | medium | пакет SEC-02 + main | Р16 дава на Technician запис на труд, а отговорът връща ставка и стойност; SEC-02 не го покрива | PROVEN | resolved (#69 `7300864` и #71, PROVEN в off) |
| FG-16 | low | #56 `dae097b` | твърд резервен HMAC ключ в кода | SUSPECTED | resolved (#56 `3234446`) |
| FG-17 | **blocker** | #55 `53dbd28` | P&L на обекта: `max(фактури, склад)`; „фира" не увеличава разхода; справките дават различни суми | PROVEN | resolved (#55 `64418eb`, PROVEN: 150 във всички справки; застъпване 100) |
| FG-18 | high | #55 `53dbd28` | трансфер от обект пристига преди приемане; връщане в склад отива в свободна наличност, не в карантина | PROVEN | resolved (#55 `64418eb`, PROVEN) |
| FG-19 | medium | #55 `53dbd28` | наличност по локации: фантомно „в път" след пълно приемане без `source` | PROVEN | resolved (#55 `64418eb`, PROVEN: 7) |
| FG-20 | high | #55 `53dbd28` + пакет 5C-C19 F-7 | кога материалът става разход на обекта: при консумация, а не при приемане; противоречи на собственото `RULE_B_COSTING_ACTIONS` | SUSPECTED | resolved по Р17 (#55 `64418eb`, PROVEN: 50) |
| FG-21 | high | #55 `53dbd28` | право за отписване (фира): project_manager да, SiteManager/Technician/Accountant не — срещу Р16/Р14 | SUSPECTED | resolved по Р27 (#55 `4a3d15c`; обходът FG-38 затворен) |
| FG-22 | medium | #55 `53dbd28` | ревизия/отписване без Approval при съществена разлика | SUSPECTED | open — дълг W0-07; записан само в commit `189e8e5`, не в HANDOFF/docs |
| FG-23 | medium | #55 `53dbd28` | складовите стойности се виждат от роли без финансово право | SUSPECTED | resolved по Р20 (#55 `4a3d15c`, всички режими; Р32 → FG-56) |
| FG-24 | **blocker** | #69 `e6c0e46` | труд и фира: член SiteManager/Technician получава 403 — срещу Р16; тестовете заковават грешното | PROVEN | resolved (#69 `aee3169`, PROVEN) |
| FG-25 | **blocker** | main `07da9ab` + #69 | Viewer hard-delete-ва ценовите модификатори на обект | PROVEN | resolved (#69 `aee3169`, PROVEN) |
| FG-26 | high | main `07da9ab` + #69 | Viewer трие и пресъздава труда през `sync-from-work-reports` (`delete_many`) | PROVEN | resolved (#69 `f33b2ba`, PROVEN) |
| FG-27 | **blocker** | main `07da9ab` + #69 | Viewer създава плащане към подизпълнител; пише `finance_payments` извън FLOW-006 | PROVEN | resolved (#69 `f33b2ba`, PROVEN) |
| FG-28 | medium | main + #69 | отказите в `off`/`shadow` не се одитират (а staging = `shadow` по Р15) | PROVEN | open — PROVEN и в #70 `8910939` и #71 `6080165` (0 AuditEvent при отказ) |
| FG-29 | medium | #69 `e6c0e46` | price-modifiers/material-waste приемат project_id без проверка, че обектът е на фирмата | SUSPECTED | partial — resolved в #69 `7300864` (PROVEN: 404, 0 реда); #71 `e6ea838` още 200/201 (стар merge на #69) |
| FG-30 | medium | main + #69 | други парични записи, достъпни за Viewer (актове, фактури, календар, overhead compute, OCR approve, sales commit) | SUSPECTED | resolved (#69 `f33b2ba`, guard-ове прочетени) |
| FG-31 | medium | #68 `4e20084` | PM-01 §5.1 не е пълен списък (пропуска DELETE/плащане); ползва каталога като „трябва", въпреки Р16 | PROVEN | open — PM-01 е в main `8e3b190`; SEC-02 добавка A регенерира матрицата |
| FG-32 | low | пакети SEC-01 / SEC-01-C01 | Technician без канонично съответствие; липсват subcontractor-payments, client-acts/confirm и др. | SUSPECTED | open |
| FG-33 | low | Р19 срещу FLOW-040 L5 | Р19 пуска break-glass без предварително одобрение; FLOW-040 L5 иска „две независими одобрения“ | SUSPECTED | resolved (Р24 → FLOW-043 D-16 + бележка във FLOW-040 L5, `b659a73` на `claude/happy-meitner-bmcnel`; влиза в main с merge) |
| FG-34 | high | main `07da9ab` | плащания се изтриват окончателно (`DELETE /finance/payments/{id}`, премахване на разпределение) | SUSPECTED | resolved (#70 `8910939`, PROVEN) |
| FG-35 | high | main `07da9ab` | каса, бонуси и режийни се пишат в отделни колекции извън `finance_payments` — втори паричен регистър | SUSPECTED | open — дълг за W0-05 (единен Payment core), записан от оркестратора |
| FG-36 | low | #67 `675faba` | `approved_by: "krum"` е свободен текст, `approval_ref: null` — няма препратка към одобрението | PROVEN | open |
| FG-37 | high | main `8e3b190` | AuditEvent hash chain се разклонява при едновременни записи (няма lock/уникален sequence) | PROVEN | resolved (#72 `e733c66`, PROVEN: 40/40 поредици, `verify_chain` true; виж FG-57) |
| FG-38 | high | #55 `64418eb` | фира от подобект: `project_id` идва от клиента → обход на Р27 и разход на грешния обект | PROVEN | resolved (#55 `4a3d15c`, PROVEN ×3 режима) |
| FG-39 | medium | #55 `64418eb` | Р20 в off/shadow гледа само RoleAssignment → legacy Owner/Admin/Accountant губят стойностите | PROVEN | resolved (#55 `4a3d15c`, PROVEN) |
| FG-40 | low | #55 `64418eb` | project_manager „свой обект“ = всеки ред в екипа, независимо от ролята | SUSPECTED | resolved по Р30 (#55 `4a3d15c`, PROVEN) |
| FG-41 | high | main / #71 `6080165` | `/work-sessions/overtime`, `/summary`, `/{id}/detail` връщат цената на чужд труд на всички роли | PROVEN | resolved (#71 `f17f7e5`, PROVEN) |
| FG-42 | high | main / #71 `6080165` | `/projects/{id}/activity-reports/{smr}` (ставка на работник) и `/labor-warnings/{id}` (бюджет) — и за не-членове | PROVEN | resolved (#71 `f17f7e5`, PROVEN) |
| FG-43 | medium | main / #71 `6080165` | activities-overview дава `actual_cost` на Viewer/Technician/Driver; Accountant получава 403 на activity-budget-summary | PROVEN | resolved (#71 `f17f7e5`, PROVEN) |
| FG-44 | medium | Р20 / #71 | „изхарчено“ срещу „себестойност“ не е определено: SiteManager вижда труд по ставки и може да изведе ставка | PROVEN | partial — #71 `e6ea838` крие едноличните СМР, но броят на работниците е за цялата история, а сумата е за периода → FG-63 |
| FG-45 | high | #70 `8910939` | сторно на плащане от Pay Run / аванс / подизпълнител не обновява модула-източник | SUSPECTED | resolved (#70 `42bbdfc`, PROVEN: 5 вида → 409) |
| FG-46 | medium | main / #70 | основните POST за плащания (`/finance/payments`, invoice payments, transfers…) без Idempotency-Key | PROVEN | resolved по Р29 в #69 `6d43284` и #70 `42bbdfc` (PROVEN: 428, 0 реда); #71 → FG-52 |
| FG-47 | low | #69 `07faab5` / #70 `8910939` | различно правило за сума: #69 приема „12“ (низ), #70 — 422 | PROVEN | partial — едно правило в #69 `7300864` и #70 `31ed258` (`money_amount.py`, идентични); #71 `e6ea838` още приема „12“ |
| FG-48 | high | main `35ae10b` | Pay Run: акорд без количество се плаща като часове × ставка | PROVEN | resolved (#73 `709815d`, PROVEN: акорд 40ч без количество → 0; 120 м2 × 5 → 600) |
| FG-49 | medium | main `35ae10b` | Pay Run: типът заплащане идва само от профила, не от СМР реда/пакета | SUSPECTED | resolved (#73 `709815d`: ред → пакет → профил) |
| FG-50 | medium | #70 `42bbdfc` (и main) | other-expense / other-income записват в регистъра към несъществуващ обект | PROVEN | partial (#70 `31ed258`, PROVEN: отказ, нищо записано) — статус 422, а #69 дава 404; other-income без обект → 201, other-expense → 400 |
| FG-51 | high | main / #71 `f17f7e5` | sync на труда от неодобрени отчети; акордът се смята по часове | SUSPECTED | resolved (#73 `709815d`: само Approved, без часове × ставка по подразбиране) |
| FG-52 | medium | #71 `f17f7e5` | #71 съдържа #69 @ `07faab5`, не `6d43284`: парични POST без Idempotency-Key минават (201) | PROVEN | resolved (#71 `e6ea838`, PROVEN: 428, 0 реда) |
| FG-53 | medium | #55 `4a3d15c` | consume/transfer от обект приемат различен `project_id` от тялото на заявката | PROVEN | resolved (#55 `81e412c`, PROVEN ×3 режима; дестинацията → FG-61) |
| FG-54 | medium | #55 `4a3d15c` | каноничните четения на склада не се решават по роля в off/shadow (F-16) | SUSPECTED | resolved (#55 `81e412c`, PROVEN ×3 режима) |
| FG-55 | low | #55 `4a3d15c` | родителят на подобект се връща в грешката преди проверката на правата | PROVEN | partial (#55 `81e412c`) — родителят вече не се връща, но 422/403 още отговаря с да/не за родителя преди правата |
| FG-56 | medium | #55 `4a3d15c` | Р32: складовият работник не вижда единичните цени (добавка E не е изпълнена) | PROVEN | resolved по Р32 (#55 `81e412c`, PROVEN ×3 режима) |
| FG-57 | low | #72 `e733c66` | `record_event` върху база без уникалния индекс пак разклонява веригата тихо (няма fail-closed) | PROVEN | open |
| FG-58 | medium | main `35ae10b` | ръчен `POST /labor-entries` без присъствие и отчет; възможно двойно броене със sync | SUSPECTED | open |
| FG-59 | high | #55 `81e412c` | роля, вързана с обект, действа в централния склад, ако добави `project_id` в тялото | PROVEN | open |
| FG-60 | medium | #55 `81e412c` | `balance` и `history` без филтър показват количества на чужди обекти на не-член SiteManager | PROVEN | open |
| FG-61 | medium | #55 `81e412c` | приемане от доставчик към обект с различен `project_id` от тялото | PROVEN | open |
| FG-62 | low | #55 `81e412c` | историята на складовия работник показва пари на обекти (CONSUME_TO_SMR) — Р32 „без финанси на обекти“ | SUSPECTED | open |
| FG-63 | high | #71 `e6ea838` | Р31: работниците се броят за цялата история, „изхарчено“ — за периода → ставката на един човек се изчислява | SUSPECTED | open |
| FG-64 | high | #73 `709815d` | акордна цена и одобрено количество идват от реда в отчета, който работникът попълва | SUSPECTED | open |
| FG-65 | high | #73 `709815d` | нищо в кода не задава одобрено количество или акордна цена на пакета → всички на акорд получават 0 | SUSPECTED | open |
| FG-66 | medium | #73 `709815d` | след преизчисление „остава за плащане“ може да стане отрицателно, вместо корекция | SUSPECTED | open |
| FG-67 | medium | main `35ae10b` | P&L „бюджет“ сумира оферти Draft + Sent + Accepted (всички версии) като договорена стойност | SUSPECTED | open |
| FG-68 | medium | main `35ae10b` | P&L: подизпълнителите се признават при плащане, не при одобрен акт | SUSPECTED | open |


---

## FG-1 — `/labor-entries`: всеки потребител записва труд за всеки и чете ставките

- **Тежест:** high (Р3: сигурност и пари = „боли“ по дефиниция). **Статус:** resolved (#69 + #71 `6080165`, проход 3). **PROVEN.**
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

- **Тежест:** high. **Статус:** resolved (#67 `98b18ec`, проход 2). **PROVEN.**
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

- **Тежест:** medium. **Статус:** resolved (#67 `98b18ec`, проход 2). **PROVEN** (от доказателствата на PR-а).
- **Канон:**
  - FLOW-042 §Release Manifest: „Липсващо или несъвпадащо поле блокира deployment-а.“
  - CLAUDE.md §6: всеки deployment пази „Feature Flags/Entitlements snapshot“.
- **Код (#67 `e987892`):**
  - `manifest.json:127` очаква `PERMISSION_SERVICE_MODE` = `off`;
  - `ops/staging/staging_deploy.sh:15-17,76` (`staging_overrides`) подменя очакването с параметъра на staging;
  - `verify.json` не записва действителната стойност.
- **Решение:** промяна в кода. Действителният флаг на staging да влиза в deployment записа и в manifest/environment config, така че двете да съвпадат. Ако се иска overlay за staging — решение от Крум къде се записва.

## FG-4 — deployed_by/approved_by не се записват

- **Тежест:** medium. **Статус:** resolved (#67 `98b18ec`, проход 2). **PROVEN.**
- **Канон:** FLOW-050: „Всеки deployment пази … deployed_by, approved_by, rollback target и post-deployment result.“
- **Код (#67 `e987892`):**
  - трите `record.json:13` имат `"actor": "unknown"`;
  - `manifest.json:110` има `"created_by": "unknown"`; източникът е резервната стойност в `lib.sh:51`;
  - `staging_up.py:63` записва само validation ref, не одобряващ.
- **Решение:** промяна в кода. Deployer и approver да са задължителни параметри; без тях — отказ.

## FG-5 — isolation guard не проверява накъде сочат UI/API URL

- **Тежест:** medium. **Статус:** resolved (#67 `98b18ec`, проход 2). **PROVEN** (offline проба с променен compose модел).
- **Канон:**
  - CLAUDE.md §6: отделни среди; „Production data/secrets не се копират свободно в non-production“.
  - FLOW-042: „никога директно в production“.
  - Пакет ST-02-C01: отказ при production цели.
- **Код (#67 `e987892`):** `ops/staging/isolation_check.py:193-219` проверява Mongo, имената на базите и mounts. Не проверява `PUBLIC_URL`, `CORS_ORIGINS`, build arg `REACT_APP_BACKEND_URL`, нито ключове за bootstrap/seed-admin. Пробата с production URL и с `PLATFORM_BOOTSTRAP_TOKEN` получава PASS.
- **Важно:** пътят по подразбиране е безопасен (`staging_up.py:166-175` пише `127.0.0.1:<port>`). Дупката е само при ръчна редакция на `.env`.
- **Решение:** промяна в кода. Тези стойности да са задължително `127.0.0.1:<ST02_HTTP_PORT>` или изброен staging хост. Bootstrap/seed-admin ключовете да влязат в забранения списък.

## FG-6 — `ST02_ALLOWED_MONGO_HOSTS` пуска всеки хост

- **Тежест:** low. **Статус:** resolved (#67 `98b18ec`, проход 2). **PROVEN.**
- **Код (#67 `e987892`):** `isolation_check.py:60-71,206`, `staging_deploy.sh:100`. Стойност `nas-prod.lan` минава.
- **Решение:** решение на Крум — допуска ли се staging Mongo извън локалната машина.
  - Ако не — опцията да се махне.
  - Ако да — denylist на production хостовете.

## FG-7 — CLI за възстановяване = break-glass без Approval и без човек-актьор

- **Тежест:** high. Става blocker, ако Крум приеме, че CLI е L5 break-glass. **Статус:** resolved (#56 `3234446` по Р19, проход 2). **PROVEN.**
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

- **Тежест:** medium. **Статус:** resolved (#56 `3234446`, проход 2). **PROVEN** (същата проба: потребител Technician е reset-нат).
- **Канон:** CLAUDE.md §3: „temporary scoped Support/Break-glass access grants“. FLOW-040 §11: business content само „чрез break-glass, две одобрения и time-bound access“.
- **Код (#56 `dae097b`):** `reset_user_password.py:190-204` няма проверка на роля. Покрива и `is_platform_admin`.
- **Решение:** промяна в кода — само Owner, или изричен флаг + Approval за другите роли. Крум да реши кои роли покрива.

## FG-9 — AuditEvent на възстановяването е R3, канонът иска R1

- **Тежест:** medium. **Статус:** resolved (#56 `3234446`, проход 2). **PROVEN** (пробата: `retention_class` = `R3`).
- **Канон:** FLOW-040 §R3: „Промени на права, break-glass и security incidents са R1.“
- **Код (#56 `dae097b`):** `services/user_role_policy.py:205-209` слага твърдо `RETENTION_R3_SECURITY_ACCESS`; извиква се от `reset_user_password.py:132`.
- **Решение:** промяна в кода — R1 за възстановяване през CLI. Зависи от отговора по FG-7.

## FG-10 — security събитията се трият след 180 дни; канонът иска ≥ 2 години

- **Тежест:** medium. **Статус:** resolved (#56 `3234446`, проход 2). **SUSPECTED** (от кода; не е изпълнено).
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

- **Тежест:** medium. **Статус:** resolved (Р20, проход 2). **SUSPECTED** (пакет срещу канон, четене).
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

- **Тежест:** medium. **Статус:** resolved (добавка към SEC-02 `73f1567`, проход 2). **SUSPECTED.**
- **Пакет SEC-02 правило 2:** „**проектни ръководни роли** (SiteManager) — само на свои обекти …“.
- **Код и канон:**
  - `backend/app/permissions/catalog.py:186` мапва `SiteManager → site_manager` = „Технически ръководител“ (`catalog.py:93`).
  - Каноничният „Проектен мениджър“ (`project_manager`, `catalog.py:98`) няма legacy източник и пакетът не го споменава.
  - FLOW-037 §3.1 (екран на Техническия ръководител) не изброява пари.
- **Решение:**
  - Пакетът да назовава каноничните `role_id` (`site_manager` / `project_manager`).
  - Крум да каже дали Технически ръководител вижда пари на обекта (влиза в отговора по FG-13).

## FG-15 — Р16 дава на Technician запис на труд, а отговорът връща ставка и стойност

- **Тежест:** medium. **Статус:** resolved (#69 `7300864`, #71; проход 5). **PROVEN** (FG-1 пробата: отговорът на `POST /labor-entries` съдържа `hourly_rate` и `labor_cost`).
- **Канон:**
  - Р16: Technician и SiteManager въвеждат труд на свои обекти.
  - SEC-02 правило 2: Technician — без пари на ниво обект.
  - FLOW-037 §3.4: без чужди заплати.
- **Код:** `backend/app/routes/labor_smr.py:57-64` (main; същото в #69) връща ставката на служителя, за когото е записът. Пакетът SEC-02 изброява GET endpoint-и от PM-01 §5.2, но не и отговорите на записите.
- **Решение:** промяна в кода, в обхвата на SEC-02:
  - `hourly_rate`/`labor_cost` скрити в отговора на `POST`/`sync` и в `GET /labor-entries` за роли без финансово право;
  - пакетът SEC-02 да добави „отговорите на записи по Р16“.

## FG-16 — твърд резервен HMAC ключ в кода

- **Тежест:** low. **Статус:** resolved (#56 `3234446`, проход 2). **SUSPECTED.**
- **Канон:** CLAUDE.md §16: „не записвай secrets в Git“.
- **Код (#56 `dae097b`):** `services/auth_events.py:55-56`. Резервният литерал `dev-auth-event-key-NOT-FOR-PRODUCTION` се ползва, ако няма `AUTH_EVENT_HMAC_KEY`/`JWT_SECRET`.
- **Решение:** промяна в кода — в production да отказва без ключ.

## FG-17 — P&L на обекта: `max(фактури, склад)`, „фира" не увеличава разхода

- **Тежест:** blocker. **Статус:** resolved (#55 `64418eb`, проход 3). **PROVEN.**
- **Канон:**
  - FLOW-009 „Разход по обект": Път А е „при изписване/консумация“; Път Б е „от разпределения фактурен ред/приемането“; „Една и съща партида не може да стане разход и по двата пътя.“
  - CLAUDE.md §7: „Материалният разход се признава само веднъж“.
  - Р10: отписването е „**разход на обекта** (намалява печалбата му, отделен ред „фира“)“.
  - Пакет 5C-C22: всички справки показват една и съща сума.
- **Код (#55 `53dbd28`):** `backend/app/services/project_pnl.py:92-94` прави `material_total = max(material_cost_invoices, material_cost_warehouse)` и после вади „фира“ от него. Двата пътя не се събират по партиди, а се взема по-голямото. Никоя друга справка не чете `invoice_lines`, т.е. има две истини за един и същ разход.
- **Проба:** реален Mongo, бази `fg55_*`, помощниците от тестовете на C21. Данни: фактурен ред 100 към обекта + консумация 30 + отписване 20.
  - P&L: материали 80, фира 20, общо **100** — фирата не е добавила разход.
  - `/project-net-profit` и `/project-profit`: себестойност **50**.
- **Решение:** промяна в кода.
  - Път Б (разпределени фактурни редове / директна доставка) и Път А (каноничният helper) да се броят като отделни партиди и да се събират.
  - Един и същ helper във всички справки.
  - Ако един фактурен ред може да захрани и складова партида — решение от Крум как се свързват.

## FG-18 — трансфер от обект пристига преди приемане; връщане не отива в карантина

- **Тежест:** high. **Статус:** resolved (#55 `64418eb`, проход 3). **PROVEN.**
- **Канон:**
  - FLOW-009 „Прехвърляния“: „движението има потвърждение от предаващ и приемащ, когато правилата го изискват“.
  - FLOW-009: „Върнат материал не става автоматично свободна наличност. Първо е `За проверка / Карантина`“.
  - FLOW-009 „Какво НЕ трябва“: „връщане директно в свободна наличност без проверка“.
  - Р11: стоката е „в път“ и е на новото място само след приемане.
- **Код (#55 `53dbd28`):**
  - `backend/app/warehouse_canonical/service.py:1301-1361` вкарва в „в път“ само склад→склад;
  - `service.py:1455-1472`: `transfer_project_to_warehouse` изисква свободен склад;
  - `queries.py:160-163` кредитира местоназначението веднага.
  - SiteManager има двете права за трансфер (`catalog.py:133-146`).
- **Проба:**
  - обект→обект: `p-two` веднага показва количество 1 и стойност 10;
  - обект→склад: свободната наличност на `wh_1` става от 5 на 6, без приемане и без карантина.
- **Решение:** промяна в кода.
  - Двата трансфера от обект през „в път“ + приемане.
  - Връщане от обект в склад → карантина.
  - Ако Крум иска кратък път за тези движения — да го запише като решение.

## FG-19 — фантомно „в път“ след пълно приемане

- **Тежест:** medium. **Статус:** resolved (#55 `64418eb`, проход 3). **PROVEN.**
- **Канон:** FLOW-009 „Какво трябва да вижда Крум“: „наличност по складове, обекти, подобекти и транспорт“.
- **Код (#55 `53dbd28`):**
  - `routes/warehouse_canonical.py:76` пуска приемане без `source`;
  - тогава `queries.py:165-178` не изпразва транзитната кофа.
- **Проба:** приети 10, изпратени 5, приети 5, консумирани 3.
  - Изгледът показва склад 5 + в път 5 + обект 2 = **12**; реално наличността е 7.
  - Проекцията `warehouse_in_transit` правилно казва 0 неприключени.
- **Решение:** промяна в кода — сървърът сам задава (или изисква) source = in-transit на съответното изпращане. Тъй като засяга сума, която Крум вижда, това е за поправка по Р3.

## FG-20 — кога материалът става разход на обекта

- **Тежест:** high. **Статус:** resolved по Р17 (#55 `64418eb`, проход 3). **SUSPECTED** като разминаване с канона. Поведението на кода е потвърдено от тестовете на PR-а.
- **Канон:**
  - FLOW-008: „складови материали само при изписване към обекта“.
  - FLOW-009 Път Б: разход „от разпределения фактурен ред/приемането“.
  - FLOW-009: „старият обект престава да носи съответния материален разход, ако материалът не е бил консумиран“ — т.е. неконсумиран материал на обекта вече носи разход.
- **Код (#55 `53dbd28`):**
  - `backend/app/services/canonical_material_cost.py:54` брои само `COST_KINDS=("consume","write_off")`;
  - `projections.py:133-142` пише разход само при consume/write_off;
  - собственото `actions.py:77-84` на PR-а (`RULE_B_COSTING_ACTIONS` = accept, consume, receive to project) цитира решение на Крум в issue #52.
- **Произход:** пакетът 5C-C19 F-7 тълкува „изписване“ като „консумация“.
- **Ефект:** приет или директно доставен, но неконсумиран материал не е разход на обекта.
- **Решение:** решение на Крум — разходът е при приемане на обекта или при консумация. После кодът и 5C-C19 F-7 да се изравнят.

## FG-21 — право за отписване (фира) срещу Р16/Р14

- **Тежест:** high. **Статус:** resolved по Р27 (#55 `4a3d15c`, проход 4). **SUSPECTED.**
- **Канон:**
  - Р16: отпадък въвеждат SiteManager и Technician на свои обекти; Owner/Admin/Accountant навсякъде.
  - Р14: парични записи само Owner/Admin/Accountant.
- **Код (#55 `53dbd28`):**
  - `warehouse.write_off` (вече пише разход „фира“) е на owner, admin и project_manager (`backend/app/permissions/catalog.py:159`); site_manager, Technician и accountant го нямат.
  - Ръчният регистър `POST material-waste` (`routes/material_waste.py:57`) няма никаква проверка на main (виж FG-24 за #69).
- **Решение:** решение на Крум — каноничното отписване „отпадък“ по Р16 ли е, или паричен запис по Р14. После каталогът и `warehouseCanonicalAccess.json` (frontend) да се изравнят.

## FG-22 — ревизия/отписване без Approval

- **Тежест:** medium. **Статус:** open. **SUSPECTED.**
- **Канон:**
  - FLOW-009 „Ревизия“: „Data Quality/Approval задача при съществена разлика“.
  - FLOW-002: „отписване на актив“ е критично действие; CLAUDE.md §8.
- **Код (#55 `53dbd28`):**
  - `warehouse_canonical/service.py:644-654` изисква само причина и `file_ids` доказателства;
  - `ApprovalRuntimeUnavailableError` (`errors.py:107`) е дефиниран, но никъде не се хвърля.
- **Решение:** промяна в кода — fail closed при съществена разлика, докато W0-07 Approval runtime не съществува. Прагът — решение на Крум.

## FG-23 — складовите стойности се виждат от роли без финансово право

- **Тежест:** medium. **Статус:** resolved по Р20 (#55 `4a3d15c`, проход 4). **SUSPECTED.**
- **Канон:** пакет SEC-02 правило 4 („Склад: количества да, стойности/себестойност не“). Основата в канона е слаба — виж FG-13.
- **Код (#55 `53dbd28`):**
  - `/warehouse/canonical/stock` и `/history` връщат `total_value`, `unit_value` и стойностни слоеве (`queries.py:81-90`) на всеки с `warehouse.read_stock`;
  - това включва site_manager, warehouse и procurement (`catalog.py:145,187,197`).
- **Решение:** зависи от отговора на Крум по FG-13. Ако правило 4 се потвърди — промяна в кода, стойностите скрити.

## FG-24 — SEC-01: член SiteManager/Technician получава 403 на труд и фира

- **Тежест:** blocker. **Статус:** resolved (#69 `aee3169`, проход 2). **PROVEN.**
- **Канон:**
  - Р16: „могат да въвеждат и **SiteManager и Technician, само за обекти, на които са членове**“.
  - Пакет SEC-01: „напр. SiteManager за труд на своя обект — тогава същото“.
- **Код (#69 `e6c0e46`):**
  - `backend/app/permissions/money_write.py:38,41-48`: `FINANCE_WRITE_ROLES=("Admin","Owner","Accountant")`, `scope="company"`;
  - използва се в `routes/labor_smr.py:36` и `routes/material_waste.py:62`;
  - `tests/test_sec_01_money_write_permissions.py` очаква 403 за SiteManager и Technician, т.е. заковава грешното. Нито тестовете, нито PM-01 проверяват членство (PM-01 §7.1).
- **Проба:** реален Mongo `fg69_*`, режим `off`. SiteManager и Technician са членове на обект A.
  - SiteManager и Technician: 403 на труд и на фира;
  - Accountant: 201;
  - Viewer и Driver: 403 (правилно).
- **Решение:** промяна в кода (SEC-01-C01 т.2).
  - Проверка за членство (`project_team`) за SiteManager/Technician на ниво обект.
  - Действието да се даде на `site_manager` в обхват обект.
  - Тестове с член и не-член.
  - Крум да каже на коя канонична роля съответства Technician (FG-32).

## FG-25 — Viewer hard-delete-ва ценовите модификатори на обект

- **Тежест:** blocker. **Статус:** resolved (#69 `aee3169`, проход 2). **PROVEN.**
- **Канон:**
  - CLAUDE.md §2.9: „Няма hard delete на използвани, финансови … записи“.
  - Р14: ценови модификатори — само Owner/Admin/Accountant.
- **Код:** `backend/app/routes/price_modifiers.py:126-129` (main и #69 `e6c0e46`, непроменен) има само `require_m2` и `delete_one`. SEC-01 защитава `PUT`, но не и `DELETE`.
- **Проба:** Owner `PUT` → 200, после Viewer `DELETE` → 200; редовете от 1 на 0.
- **Решение:** промяна в кода (SEC-01-C01 т.3) — същият money-write guard, плюс архивиране вместо изтриване.

## FG-26 — Viewer трие и пресъздава труда през sync

- **Тежест:** high. **Статус:** resolved (#69 `f33b2ba`, проход 2). **PROVEN.**
- **Канон:** Р16; CLAUDE.md §2.9 (трудът е основа за заплата — FLOW-028).
- **Код:** `backend/app/routes/labor_smr.py:73,102` (#69; същото на main) има само `require_m2` и `delete_many` върху синхронизираните редове. `recompute-labor` (`:167`) има същия отворен guard — SUSPECTED, че също пише.
- **Проба:** Viewer → 200; съществуващият синхронизиран ред е изтрит (брой 0).
- **Решение:** промяна в кода (SEC-01-C01 т.1) — guard по Р16, без изтриване на записи, които вече са основа за Pay Run.

## FG-27 — Viewer създава плащане към подизпълнител извън FLOW-006

- **Тежест:** blocker. **Статус:** resolved (#69 `f33b2ba`, проход 2). **PROVEN.**
- **Канон:**
  - CLAUDE.md §2.5 и §7: „всички реални парични движения минават през FLOW-006“.
  - FLOW-002: „плащане“ е критично действие с изрични права и AuditEvent.
  - Р14.
- **Код:** `backend/app/routes/subcontractors.py:493` (main и #69) има само `require_m2`. `:531-540` вмъква директно `finance_payments` (Outflow), ако има сметка — без Payment Core, Approval и AuditEvent.
- **Проба:** Viewer → 201; 1 ред в `subcontractor_payments`. Ред във `finance_payments` не се появи само защото тестовата сметка не се намери.
- **Решение:**
  - Промяна в кода: веднага money-write guard (влиза в SEC-01-C01 или SEC-02 — решава оркестраторът).
  - Отделно: дълг „плащане към подизпълнител извън FLOW-006 Payment Core“ за W0-05 / R1 Payment.

## FG-28 — отказите в `off`/`shadow` не се одитират

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** FLOW-040 §4.1: „permission denied и опит за direct-URL/API заобикаляне“ се одитират. Р15: staging = `shadow`.
- **Код:** `backend/app/permissions/deps.py:107-110,136-137` (main и #69) връща 403 без AuditEvent в тези режими; само `enforce` одитира.
- **Проба:** 0 audit реда при отказ на Viewer към cash-transactions в `off`. Доказателствата на PR-а (`SEC-01/results.json`) пишат `audit_events` само в `enforce`.
- **Решение:** промяна в кода — `audit_permission_denied` и в `off`/`shadow` за действия, които `is_significant_action` маркира като значими.

## FG-29 — price-modifiers / material-waste приемат чужд project_id

- **Тежест:** medium. **Статус:** open. **SUSPECTED.** README-то на PR-а го води като дълг SEC-01-D1.
- **Канон:** FLOW-002: „директен URL да заобикаля правата“.
- **Код (#69 `e6c0e46`):** `PUT price-modifiers/project/{id}` и `POST projects/{id}/material-waste` не проверяват, че обектът е на фирмата. Accountant на фирма B подава id на обект от фирма A и редът се записва във фирма B — сирак, не изтичане към A.
- **Решение:** промяна в кода — проверка за принадлежност/членство. Поправката по Р16 за фира го покрива за waste.

## FG-30 — други парични записи, до които Viewer стига

- **Тежест:** medium. **Статус:** resolved (#69 `f33b2ba`, проход 2). **SUSPECTED.** Матрицата на #69 показва, че handler-ът е достигнат (200/404, не 403).
- **Endpoint-и:**
  - `POST /api/client-acts/{act_id}/confirm` (`revenue_expense.py:167`);
  - `PUT /api/supplier-invoices/{inv_id}`;
  - `POST /api/subcontractor-acts/{id}/confirm`;
  - `POST /api/worker-calendar/bulk`, `PUT /api/worker-calendar/{entry_id}` (захранват overhead);
  - `POST /api/overhead-allocation/compute/{project_id}`;
  - `PUT/POST /api/ocr-invoice/{id}/approve`;
  - `POST /api/sales/commit`;
  - `POST /api/pricing/refresh`.
- **Канон:** Р14 („и подобни финансови записи“); FLOW-002 критични действия (фактуриране, одобрение).
- **Решение:** промяна в кода — оркестраторът ги разпределя в SEC-01-C01 или в следващ пакет.

## FG-31 — PM-01 отчетът е непълен в §5.1 и ползва каталога като „трябва“

- **Тежест:** medium. **Статус:** open. **PROVEN** (за пропуските).
- **Код (#68 `4e20084`):** `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md`.
  - §5.1 „Viewer записва (28 endpoint-а)“ звучи като пълен списък, но пропуска FG-25, FG-26 и FG-27. Харнесът ползва несъществуващи id, така че DELETE/плащане няма върху какво да действа. Това е казано само в §7.6.
  - §5 ползва каталога като правило („Technician — само подаване на актив“), а това противоречи на Р16.
- **Решение:** промяна в отчета/харнеса — проби със съществуващи записи (вече е изискано в SEC-01-C01 т.4) и бележка в §5.1, че списъкът е долна граница.

## FG-32 — пакетите SEC-01 / SEC-01-C01: Technician и обхват

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Какво липсва:**
  - SEC-01 слага труд и фира под „само финанси“, макар собствената му клауза за изключение да предвижда SiteManager.
  - C01 ползва „Technician“ без съответствие с канонична FLOW-002 роля (`catalog.py:189`: `LEGACY_TECHNICIAN`).
  - Никой пакет не изброява `subcontractor-payments`, `client-acts/confirm`, `supplier-invoices`, `worker-calendar`.
- **Решение:**
  - Крум да каже на коя канонична роля отговаря Technician (Технически ръководител, Работник или друга).
  - Оркестраторът да допълни обхвата. Това не е промяна на FLOW.

## FG-33 — Р19 пуска break-glass без предварително одобрение, а FLOW-040 L5 иска две

- **Тежест:** low. **Статус:** resolved (Р24 → FLOW-043 D-16, `b659a73`). **SUSPECTED** (решение срещу канон, четене).
- **Канон:**
  - FLOW-040 §10 L5: „… с две независими одобрения, срок, автоматичен revoke и пълен audit“.
  - CLAUDE.md §8: Approval е задължителен за Break-glass access.
  - CLAUDE.md §18: „заключен FLOW не се променя без изрично решение на Крум, записано в канона“.
- **Решение на Крум:** Р19 (06.11.2026): „изисква **име на изпълняващия човек и причина** … Без предварително одобрение (Owner не може да влезе).“ Изпълнено в #56 `3234446`:
  - `backend/scripts/reset_user_password.py` изисква `--operator`/`--reason`;
  - само Owner;
  - AuditEvent R1;
  - известие към Owner.
- **Защо е разминаване:** Р19 е изрично и по-късно решение на Крум, така че кодът е прав. Р19 обаче е записано в RECOVERY_EXECUTION_PROPOSAL, не във FLOW-043. Двата текста си противоречат, докато изключението не влезе в канона.
- **Решение:** Крум да запише Р19 като D-решение (изключение от L5 за аварийно възстановяване на Owner) във FLOW-043. Кодът не се пипа.

## FG-34 — плащания се изтриват окончателно

- **Тежест:** high (Р3: пари). **Статус:** resolved (#70 `8910939`, проход 3). **SUSPECTED** (четене).
- **Канон:**
  - FLOW-006 „Корекции“: „След плащане няма тихо редактиране. Използват се: корекция, реверс, доплащане …“ и „Всички промени имат AuditEvent.“
  - CLAUDE.md §2.9: няма hard delete на финансови записи.
- **Код (main `07da9ab`):**
  - `backend/app/routes/finance.py:1420-1435`: `DELETE /finance/payments/{payment_id}` прави `finance_payments.delete_one`, ако няма разпределения. Няма AuditEvent.
  - `finance.py:1218-1223`: премахването на плащане от фактура трие разпределението и, ако е последно, самото плащане. Пише само legacy `log_audit`.
  - Право имат финансовите роли (`finance_permission`).
- **Свързано:** `hr.py:942` трие `contract_payments` само без платени транши — това е график на задължение, не плащане. Не е включено.
- **Решение:** промяна в кода — реверс/анулиране със запис и canonical AuditEvent вместо `delete_one`. Влиза в W0-05 / R1 Payment. Ако трябва веднага (Р3) — отделен малък пакет.

## FG-35 — втори паричен регистър: каса, бонуси и режийни извън `finance_payments`

- **Тежест:** high. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-006 „Единен Payment ledger“: „Всички реални парични движения минават през един регистър.“
  - CLAUDE.md §2.5 и §16: „не създавай втори ledger“.
  - Изход R1: „няма нов паралелен ledger“.
- **Код (main `07da9ab`):**
  - `backend/app/routes/reports.py:939-960` `POST /finance/cash-transactions` пише `cash_transactions` (приход/разход в брой) без сметка, без основание и без връзка с `finance_payments`;
  - същото за `bonus_payments` (`reports.py:1065`) и `overhead_transactions` (`:1012`);
  - `dashboard.py:344,360,511,817` чете касата от `cash_transactions`;
  - `IMPLEMENTATION_WAVES.md:47` казва „един `finance_payments` write service“.
  - SEC-01 затвори кой може да пише (Р14), но не и къде се пише.
- **Решение:** промяна в кода в W0-05 / R1 Payment — тези записи да станат движения в единния регистър (или задължения + плащане през FLOW-006), с миграция. До тогава оркестраторът да го води като дълг. Бизнес правилото е ясно, не е нужно ново решение.

## FG-36 — staging: `approved_by` без препратка към одобрението

- **Тежест:** low. **Статус:** open. **PROVEN** (доказателствата на PR-а).
- **Канон:**
  - CLAUDE.md §8: „Approval винаги сочи към exact version и evidence.“
  - FLOW-050: всеки deployment пази „deployed_by, approved_by“.
- **Код (#67 `675faba`):** `docs/evidence/ST-02/rehearsal-2026-11-06-c03/*/record.json:8-9` имат `deployed_by: "claude-st02-c03"`, `approved_by: "krum"`, а в manifest-а `approval_ref: null` (`:141,151`). Името на Крум е записано от агента, без връзка към решението (пакет ST-02-C03 / Р9).
- **Решение:** промяна в кода — `--approved-by` да изисква и `--approval-ref` (пакет/съобщение/коментар), който да влезе в record и manifest. За production deploy-а това ще е задължително.

## FG-37 — AuditEvent hash chain се разклонява при едновременни записи

- **Тежест:** high. **Статус:** resolved (#72 `e733c66`, проход 5). **PROVEN.**
- **Известен дълг:** пакетът PAY-01 го споменава като „W0-04 е известен дълг за паралелни записи“. Тук е показан с проба.
- **Канон:**
  - FLOW-040 §8: „append-only primary event store; … hash chain или подписан batch manifest по tenant и период; … аларма при липсващ sequence, hash mismatch“.
  - CLAUDE.md §2.8.
- **Код (main `8e3b190`):** `backend/app/audit/store.py:107-119` (`record_event`) чете последното събитие и вмъква следващото без транзакция, lock или уникален индекс (tenant_id, sequence). Ползва се от `permissions/audit_hooks.py:70,118`, `master_data/*`, `tenancy/legacy_backfill.py:500`, `services/user_role_policy.py:209`.
- **Проба:** `docs/flow-guard/probes/fg37_audit_chain_race_probe.py`. Реален Mongo, 20 едновременни `record_event` за един tenant:
  - 20 събития, само **3** различни `sequence`;
  - `verify_chain` → false, „sequence gap: expected 2, found 1“.
- **Ефект:** при нормален паралелен трафик веригата става невалидна. Проверката на целостта би вдигала фалшиви аларми или би маскирала истинска подмяна.
- **Решение:** промяна в кода (W0-04) — уникален индекс (tenant_id, sequence) + retry при конфликт, или запис в транзакция с броячен документ на tenant. Складът в #55 вече пише веригата в транзакция — да се провери дали ползва същия механизъм.

## FG-38 — фира от подобект: обход на Р27 и разход на грешния обект

- **Тежест:** high. **Статус:** resolved (#55 `4a3d15c`, проход 4). **PROVEN.**
- **Канон:**
  - Р27: „SiteManager и Technician — само на обекти, където са членове … останалите роли — 403“.
  - FLOW-008: разходът е на обекта, който е приел материала.
  - CLAUDE.md §14: tenant/permission check на всеки consequential write.
- **Код (#55 `64418eb`):**
  - `backend/app/services/warehouse_movements/service.py:1622-1626`: при източник подобект се изисква `project_id`, но той **не се сверява** с обекта-родител на подобекта.
  - `service.py:668-671`: Р27 се решава по този `project_id` от заявката.
  - Същото в отделния endpoint `routes/warehouse_canonical.py:371-387`.
- **Проба:** реален Mongo `fg55_*`. site_manager, член само на p-other, отписва от подобект sp-1, чиято наличност е приета под p-c21.
  - Резултат: **ALLOWED**. Наличността на подобекта 5 → 4; p-other: материали −10, фира +10; p-c21 остава 50 без фира.
  - Същият потребител с `project_id=p-c21` получава 403.
- **Решение:** промяна в кода — обектът на подобекта да се взема от сървъра (записа на подобекта / приемането); различен `project_id` → отказ. Forbidden тестове за двата endpoint-а.

## FG-39 — Р20 в off/shadow гледа само RoleAssignment

- **Тежест:** medium. **Статус:** resolved (#55 `4a3d15c`, проход 4). **PROVEN** (registry loader без редове, както е в режим `off`).
- **Канон:** Р20: „Owner/Admin/Accountant виждат всичко“. 5C-C26c: еднакво решение в off/shadow/enforce. PR-05: `off` не пипа Permission Service.
- **Код (#55 `64418eb`):** `backend/app/routes/warehouse_canonical_queries.py:192-207` (`_sees_values`) винаги чете `perm._load_assignments` и не гледа legacy ролята. В `off`/`shadow` без RoleAssignment legacy Owner/Admin/Accountant получават `sees_values=False`. Fail-closed — нищо не изтича, но финансовите роли губят стойностите.
- **Решение:** промяна в кода — в off/shadow решение по legacy ролята през `LEGACY_ROLE_MAP` (като `ensure_project_write_off_legacy`); в shadow разликата да се логва. Тестове по режим.

## FG-40 — project_manager „свой обект“ = всеки ред в екипа

- **Тежест:** low. **Статус:** resolved по Р30 (#55 `4a3d15c`, проход 4). **SUSPECTED.**
- **Код (#55 `64418eb`):** `services/warehouse_movements/write_off_policy.py:118-130` приема всеки валиден ред в project_team, без значение `role_in_project`.
- **Решение:** решение на Крум — „свой обект“ за project_manager значи ли всяко участие в екипа или само ролята ръководител.

## FG-41 — цената на чужд труд се вижда от всички роли

- **Тежест:** high. **Статус:** resolved (#71 `f17f7e5`, проход 4). **PROVEN.**
- **Канон:**
  - FLOW-037 §3.4: „Не вижда чужди заплати …“.
  - Р20: „Наблюдател, техник, шофьор, складов работник — без пари“.
- **Код (main и #71 `6080165`):**
  - `backend/app/routes/work_sessions.py:444` `/work-sessions/overtime` връща `total_cost`/`overtime_cost` по име на работник, само с `get_current_user`;
  - `/work-sessions/summary` (`:337`) и `activity_budgets.py:914` `/work-sessions/{id}/detail` връщат `total_cost`.
  - Не са в списъка D1 на SEC-02.
- **Проба:** Viewer, Technician, Driver, Warehousekeeper и SiteManager → 200 със стойности, в off и enforce.
- **Решение:** промяна в кода — редове в `finance_read.py` (Р20: финансови роли — всичко; останалите — часове без пари).

## FG-42 — пари на обекта за не-членове

- **Тежест:** high. **Статус:** resolved (#71 `f17f7e5`, проход 4). **PROVEN.**
- **Канон:** FLOW-002: „директен URL да заобикаля правата“; Р20.
- **Код (main и #71 `6080165`):**
  - `activity_budgets.py:807` `/projects/{id}/activity-reports/{smr}` връща `total_cost` и ставката на всеки работник (`hourly_rate_at_date`);
  - `labor_smr.py:439` `/labor-warnings/{id}` връща `labor_budget`.
- **Проба:** Warehousekeeper, който не е член, получава 200 със стойности. Членове Viewer/Driver/Technician — също.
- **Решение:** промяна в кода — в регистъра по Р20 (бюджет/изхарчено/остатък само за SiteManager на свой обект, ставки само за финансови роли).

## FG-43 — activities-overview / activity-budget-summary

- **Тежест:** medium. **Статус:** resolved (#71 `f17f7e5`, проход 4). **PROVEN.**
- **Код (main и #71 `6080165`):**
  - `activity_budgets.py:659` (activities-overview) дава `actual_cost`, `labor_budget` и `total_budget` на членове Viewer/Technician/Driver. Отчасти е дълг D4, но `actual_cost` отива по-далеч.
  - Обратното: Accountant получава **403** на `:168` activity-budget-summary и на activities-overview — по-тясно от Р20.
- **Решение:** промяна в кода — редове по Р20; финансовите роли навсякъде.

## FG-44 — „изхарчено“ срещу „себестойност“ в Р20 не е определено

- **Тежест:** medium. **Статус:** open. **PROVEN** (поведението).
- **Канон:** Р20: site_manager „не вижда … себестойност“, но вижда „изхарченото срещу [бюджета]“.
- **Код (#71 `6080165`):** `services/expected_actual.py:85`: `actual_cost` на дейност = работни часове × ставка на работника. SiteManager получава `planned_cost`/`actual_cost`. При дейност с един работник от стойността и часовете се изчислява ставката му.
- **Решение:** решение на Крум — „изхарчено“ може ли да е трудът по реални ставки, или да е в часове, или по бюджетна ставка.

## FG-45 — сторно на плащане от друг модул не обновява модула

- **Тежест:** high. **Статус:** resolved (#70 `42bbdfc`, проход 4). **SUSPECTED** (четене).
- **Канон:**
  - FLOW-006: „FLOW-021/028 → задължение, FLOW-006 → реално плащане“;
  - „Всички промени имат AuditEvent“;
  - без разминаване между регистрите.
- **Код (#70 `8910939`):** `backend/app/routes/finance.py:1591` `delete_payment` не гледа произхода на плащането. Изплатена заплата от Pay Run (`pay_runs.py:1349`, категория „Заплата“), аванс/заем и погасяване (`hr.py:282,:373`) и подизпълнителско плащане може да се сторнират в регистъра, а Pay Run / авансът остават „платени“/„Open“. INT-70x69 покрива само подизпълнителите.
- **Решение:** промяна в кода — 409 за такива редове, докато модулът няма свое сторно. Или решение на Крум да се разшири INT-70x69 до Pay Run и аванси.

## FG-46 — основните POST за плащания без Idempotency-Key

- **Тежест:** medium. **Статус:** resolved по Р29 (#69 `6d43284`, #70 `42bbdfc`, проход 4). **PROVEN.**
- **Канон:** CLAUDE.md §14; FLOW-006 „idempotency за плащания“.
- **Код (main и #70 `8910939`):** `finance.py:1456` `POST /finance/payments`, invoice payments (`:1106`), transfers (`:400`), funding, other-expense/income. Проба: същата заявка два пъти → 2 реда.
- **Решение:** промяна в кода — PAY-01-C02 с MoneyWrite от #69, или в W0-05.

## FG-47 — две различни правила за сума

- **Тежест:** low. **Статус:** open. **PROVEN.**
- **Код:** #69 `money_input.py:59` (`money_value`) приема числов низ „12“; #70 `positive_amount` го отказва с 422.
- **Решение:** едно правило при merge (коментарът в кода вече го предвижда). Изборът е технически — оркестраторът решава.

## FG-48 — Pay Run: акорд без количество се плаща като часове × ставка

- **Тежест:** high (Р3: пари/заплати). **Статус:** resolved (#73 `709815d`, проход 5). **PROVEN.**
- **Канон:**
  - FLOW-028 „Акорд“: „При акорд количеството е задължително. `заработка = одобрено измерено количество × договорена единична цена труд`. Без одобрено количество или цена не възниква окончателно задължение и не може да има плащане.“
  - FLOW-028 „Какво НЕ трябва“: „акорд без количество/цена“.
  - CLAUDE.md §7: „Акордът изисква одобрено количество × единична цена труд.“
  - Р31 също го повтаря.
- **Код (main `35ae10b`):**
  - `backend/app/routes/pay_runs.py:219-231` (`calc_earned`, `pay == "Akord"`): ако `approved_value` е 0 → `approved_hours × hourly_rate` с формула „(акорд)“;
  - двете извиквания (`:408`, `:569`) **никога** не подават `approved_value` → акордът винаги се плаща по часове.
- **Проба:** `calc_earned({'pay_type':'Akord','hourly_rate':15}, 40, 5)` → `earned 600.0`, формула „40ч × 15.0 EUR/ч (акорд)“, без количество.
- **Решение:** промяна в кода.
  - При акорд без одобрено количество × единична цена → няма задължение (0 + DQ предупреждение „липсва количество/цена“), не плащане по часове.
  - Количеството да идва от одобреното измерване по СМР ред.

## FG-49 — Pay Run: типът заплащане идва само от профила

- **Тежест:** medium. **Статус:** resolved (#73 `709815d`, проход 5). **SUSPECTED** (четене).
- **Канон:** FLOW-028 „Видове заплащане“: „Типът заплащане се определя на ниво отчетен СМР ред/пакет, а не само в профила на човека.“
- **Код (main `35ae10b`):** `pay_runs.py:191` `pay = profile.get("pay_type")`. Един човек със смесени СМР (часови и акордни) се изчислява изцяло по типа от профила.
- **Решение:** промяна в кода — типът да се чете от отчетния ред/пакета, с профила само като подразбиране. Заедно с FG-48.

## FG-50 — other-expense / other-income към несъществуващ обект

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** FLOW-006 „разпределение към обект без проследимост“ е забранено; CLAUDE.md §14: tenant check, validation/DQ.
- **Код (#70 `42bbdfc`, същото на main):** `backend/app/routes/finance.py:551-570`, `:579-616` — `project_id` от тялото, без проверка.
- **Проба:** `POST other-expense` с `project_id="no-such-project"`, сума 12 → 201; ред във `finance_payments`, който влиза в P&L „other_cost“.
- **Решение:** промяна в кода — обектът да съществува в tenant-а (404, нищо записано). Същият клас като FG-29.

## FG-51 — sync на труда от неодобрени отчети, акордът по часове

- **Тежест:** high. **Статус:** resolved (#73 `709815d`, проход 5). **SUSPECTED** (четене).
- **Канон:**
  - FLOW-028: „Неодобреният отчет не създава официална заплата, P&L труд или трудов бюджет“;
  - акорд = одобрено количество × единична цена;
  - Р31: „изхарчено“ = от **одобрени** дневни отчети по типа заплащане.
- **Код:**
  - `backend/app/routes/labor_smr.py:91` (main `35ae10b`) / `:141` (#71 `f17f7e5`): `sync-from-work-reports` чете `work_reports` само по org и project, без `status == "Approved"`. Отчетите имат статуси Draft/Submitted/Approved/Rejected (`attendance.py:688-708`).
  - Стойността винаги е часове × ставка.
  - Тези `labor_entries` захранват трудовия разход по пакет и „изхарченото“ по СМР.
- **Решение:** промяна в кода — само одобрени отчети; акорд по количество × цена или изрично записан дълг. Логично е да влезе в пакета за изчисление по Р31 (SEC-02-C-D1) заедно с FG-48.

## FG-52 — #71 няма Р29

- **Тежест:** medium. **Статус:** resolved (#71 `e6ea838`, проход 5). **PROVEN.**
- **Канон:** Р29: „запис на пари без `Idempotency-Key` се отказва“.
- **Код (#71 `f17f7e5`):** клонът съдържа #69 @ `07faab5` (преди Р29). `money_input.py:115` — „legacy behaviour“. Проба: cash-transactions, labor-entries и material-waste без ключ → 201/201/201, 3 реда.
- **Решение:** процес — `6d43284` (и следващите поправки на #69) да влязат в #71 преди merge; PM-01 матрицата да се пусне отново.

## FG-53 — consume/transfer от обект с чужд `project_id`

- **Тежест:** medium. **Статус:** resolved (#55 `81e412c`, проход 5). **PROVEN** за записа; SUSPECTED за ефекта в справките.
- **Канон:** FLOW-009 / Р10: обектът се определя от източника на сървъра. CLAUDE.md §14: „Определи source of truth“.
- **Код (#55 `4a3d15c`):** `services/warehouse_movements/service.py:1658-1703` проверява само подобекти; `_bind_write_off_project` (`:1720-1726`) покрива само WRITE_OFF. CONSUME_TO_SMR от `p-c22` с `project_id=p-other` минава, а `projections.py:536-540` пише разпределението по СМР под `p-other`.
- **Проба:** записът носи `project_id=p-other` и в трите режима. Общият разход не се промени.
- **Права:** не е ескалация — legacy gate-ът проверява всички засегнати обекти.
- **Решение:** промяна в кода — `project_id` да се взема от източника-обект за всяко изходящо действие; различен → 422.

## FG-54 — каноничните четения на склада не се решават по роля в off/shadow

- **Тежест:** medium. **Статус:** resolved (#55 `81e412c`, проход 5). **SUSPECTED.**
- **Канон:** Р28: „правата се решават еднакво в трите [режима]“.
- **Код (#55 `4a3d15c`):** `routes/warehouse_canonical_queries.py:242,268,307,335` викат `require_permission` без `legacy_check`; в `off` `permissions/deps.py:107-110` пуска всеки логнат потребител. Стойностите се крият (FG-39 ✅), но достъпът до самите четения не е по роля.
- **Решение:** промяна в кода — четенията през legacy gate-а (добавка E към 5C-C26, F-16).

## FG-55 — родителят на подобект се връща преди проверката на правата

- **Тежест:** low. **Статус:** open. **PROVEN.**
- **Код (#55 `4a3d15c`):** `routes/warehouse_canonical.py:343-360`. Не-член получава 422 с `parent_project_id` в контекста вместо 403. Разкрива се само id на обект, без пари.
- **Решение:** промяна в кода — без родителя в грешката за неупълномощен, или първо проверката на правата.

## FG-56 — Р32: складовият работник не вижда единичните цени

- **Тежест:** medium. **Статус:** resolved по Р32 (#55 `81e412c`, проход 5). **PROVEN.**
- **Канон:** Р32: „складовият работник **може да вижда единичните цени на артикулите** в склада (приемане, наличност, история) и да въвежда единичната цена при приемане“.
- **Код (#55 `4a3d15c`):** `warehouse_canonical_queries.py:173-176` — `warehouse` не е във `FINANCE_VALUE_ROLES` и не е в `UNCHANGED_VALUE_ROLES` → `sees_values=False` и в трите режима. Въведената от него цена при приемане се маха от отговора.
- **Решение:** промяна в кода — добавка E към 5C-C26: единични цени в склада за `warehouse`, без финанси на обекти.

## FG-57 — `record_event` без уникалния индекс тихо разклонява веригата

- **Тежест:** low. **Статус:** open. **PROVEN.**
- **Канон:** FLOW-040 §8 (линейна hash верига, аларма при липсващ sequence).
- **Код (#72 `e733c66`):** `backend/app/audit/store.py:130-165`. Повторният опит разчита на уникалния индекс (tenant_id, sequence), който #72 създава при старт и при onboarding (`audit/indexes.py:99`, `server.py`, `tenancy/onboarding.py`).
- **Проба:** `docs/flow-guard/probes/fg37_audit_chain_race_probe.py` върху кода на #72.
  - Без `ensure_audit_indexes`: 20 събития → 4 поредици, `verify_chain` = false.
  - С индексите: 40 събития → 40 поредици, `verify_chain` = true.
- **Риск:** база, създадена извън старта/onboarding-а (скрипт, възстановяване от backup), пише разклонена верига без грешка.
- **Решение:** промяна в кода — `record_event` да проверява (кеширано) наличието на индекса и да отказва запис без него, или `verify_tenant_chain` да вдига аларма.

## FG-58 — ръчен запис на труд без присъствие и отчет

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-019 „Реални данни“: „Реалният труд идва само от одобрени дневни отчети“.
  - FLOW-019 „Какво НЕ трябва“: „труд без присъствие, СМР и време“, „едни и същи часове да се броят два пъти“.
  - FLOW-028: „Присъствие → Дневен отчет → Одобрен труд …“.
- **Код (main `35ae10b`; #69 добавя права, не източник):** `backend/app/routes/labor_smr.py:32-64` `POST /labor-entries` записва часове само с `project_id` (СМР/пакет по избор). Няма връзка с присъствие или одобрен отчет. Същите часове може после да дойдат и от `sync-from-work-reports` (`source=work_report_sync`) → двойно броене.
- **Решение:** промяна в кода — ръчният ред да е чернова/корекция, която влиза в разхода само след одобрение и с връзка към отчет. Или решение на Крум дали ръчен труд е допустим и при какво одобрение. Логично е в LAB-01 или след него.

## FG-59 — роля, вързана с обект, действа в централния склад с `project_id` от тялото

- **Тежест:** high. **Статус:** open. **PROVEN** (×3 режима).
- **Канон:**
  - 5C-C26g / Р28: „a project-bound role acts only THROUGH a project“, еднакво в трите режима.
  - FLOW-002: „директен URL да заобикаля правата“.
  - CLAUDE.md §14.
- **Код (#55 `81e412c`):** `backend/app/services/warehouse_movements/legacy_gate.py:51-52` — `_projects_touched` добавя `inp.project_id` от тялото, дори ако никоя локация не е обект; `:80` пропуска проверката, щом списъкът не е празен.
- **Проба:** SiteManager, член на P1, прави QUARANTINE_ENTRY в централния склад `wh_1` с `project_id=P1`. Позволено, записан 1 ред под P1. Без `project_id` → 403 R28_PROJECT_REQUIRED.
- **Решение:** промяна в кода — обектите да се броят само от локациите; `project_id` в тялото без обектова локация → 422.

## FG-60 — неотфилтрирани четения показват количества на чужди обекти

- **Тежест:** medium. **Статус:** open. **PROVEN** (×3 режима).
- **Канон:** C26f: „a project-filtered read … needs the in-date project relation“; FLOW-002 обхват по обект.
- **Код (#55 `81e412c`):** `routes/warehouse_canonical_queries.py:168` проверява връзката само когато е посочен обект; `:71-73` в off/shadow връща цялата фирма.
- **Проба:** SiteManager, който не е член, получава 403 на stock/history за P1, но 200 на `balance` и на `history` без филтър, а там има редове от P1. Само количества.
- **Решение:** решение на Крум — може ли SiteManager да вижда количествата на чужди обекти. Ако не — промяна в кода: четенията без филтър да се ограничат до обектите, където е член.

## FG-61 — приемане към обект с различен `project_id`

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** принципът от FG-38/FG-53 — обектът се определя от локацията; CLAUDE.md §14.
- **Код (#55 `81e412c`):** `services/warehouse_movements/service.py:1684-1696` връзва само **източника**.
- **Проба:** Owner приема от доставчик към P1 с `project_id=p-other` → позволено. Записът казва p-other, а наличността и разходът са на P1 (P1 = 107, p-other = 0).
- **Решение:** промяна в кода — дестинацията да се връзва по същия начин, различен → 422.

## FG-62 — складовият работник вижда пари на обекти в историята

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** Р32: вижда единичните цени „в склада (приемане, наличност, история)“, но „не вижда финансите на обекти“.
- **Код (#55 `81e412c`):** историята показва стойности и на CONSUME_TO_SMR по обекти. Отговорът на командата (`routes/warehouse_canonical.py:136`) ползва правилото за склада.
- **Решение:** решение на Крум — стойността на влагане по СМР „единична цена в склада“ ли е или „финанси на обект“.

## FG-63 — Р31: броят на работниците не е за същия период като сумата

- **Тежест:** high. **Статус:** open. **SUSPECTED** (проследено в кода, не е пуснато).
- **Канон:** Р31 / FLOW-037 §3.4: техническият ръководител вижда сумата по СМР, „без разбивка по човек, ставка …“.
- **Код (#71 `e6ea838`):**
  - `backend/app/permissions/money_write.py:395-417` (`project_labor_workers`) брои работниците за цялата история на обекта;
  - `/expected-actual?date_from&date_to` (`services/expected_actual.py:56-62`) смята `actual_cost` само за периода.
  - Ефект: период, в който е работил само един човек, показва неговото заплащане; изхарчено ÷ часове (часовете се виждат) = ставката му.
- **Решение:** промяна в кода — работниците да се броят в същия прозорец като сумата.

## FG-64 — акордната цена и количеството идват от отчета, който работникът попълва

- **Тежест:** high. **Статус:** open. **SUSPECTED** (проследено в кода).
- **Канон:** FLOW-028: „заработка = **одобрено измерено** количество × **договорена** единична цена труд“; CLAUDE.md §7.
- **Код (#73 `709815d`):**
  - `backend/app/services/report_normalizer.py:23` пренася `pay_type`, `approved_quantity` и `piece_rate` от редовете на отчета;
  - `labor_cost.py:93-99` (`resolve_piece_rate`) взема **първо** `line.piece_rate`, после договорената цена на пакета;
  - `PUT /daily-reports/{id}` (`daily_reports.py:242-264`) приема `day_entries` без валидация.
  - Ефект: всеки с M4 записва в чернова `piece_rate` и `approved_quantity`; след одобрение на отчета LAB-01 плаща точно това.
- **Решение:** промяна в кода — цената само от пакета/договора; одобреното количество само от стъпка за одобрение; полетата да се махат от входа на отчета.

## FG-65 — нищо не задава одобрено количество или акордна цена

- **Тежест:** high (оперативно). **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-028: „Без одобрено количество или цена не възниква окончателно задължение“. LAB-01 е вярно спрямо канона.
- **Код (#73 `709815d`):** одобрението на отчет (`attendance.py:704-708`) сменя само статуса. Нищо в backend/frontend не задава `approved_quantity` или `labor_piece_rate` на пакета. Ефект: след merge всички на акорд излизат с 0 и DQ предупреждение в Pay Run.
- **Решение:** решение на Крум — трябва ли поток за одобрение на количество и въвеждане на акордна цена по пакет **преди** merge на LAB-01.

## FG-66 — отрицателен остатък след преизчисление

- **Тежест:** medium. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-028 „Корекции след плащане“: „корекция; реверс; доплащане; удръжка“; CLAUDE.md §7.
- **Код (#73 `709815d`):** `already_paid` е по старите цени (часове × ставка), а новото „заработено“ е по LAB-01. Например платени 600, заработено 0 → `remaining_after_payment` = −600.
- **Решение:** промяна в кода — разликата да се показва като корекция/надплатено по FLOW-028, не като отрицателен остатък.

## FG-67 — бюджетът на P&L брои чернови и изпратени оферти

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-008: „договорени приходи“, „договорена стойност и одобрени допълнителни СМР“;
  - „прогнозата да се показва като факт“ е забранено;
  - FLOW-003: офертите са версии; актуална е една.
- **Код (main `35ae10b`):** `backend/app/services/project_pnl.py:14-25` сумира `subtotal/total` на всички оферти на обекта в статус Accepted, Sent и **Draft**. Ако има три версии на една оферта, бюджетът е тройно. `budget_vs_actual` (`:128`) се сравнява с това.
- **Решение:** промяна в кода — само текущата приета версия (+ одобрени допълнителни СМР); черновите и изпратените отделно като „прогноза/в процес“.

## FG-68 — подизпълнителите се признават по плащане, не по одобрен акт

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-008: „подизпълнителски актове и задължения“;
  - показва едновременно „платено“ и „одобрено/заработено, но неплатено“;
  - FLOW-006: „FLOW-021 → задължение, FLOW-006 → реално плащане“.
- **Код (main `35ae10b`):** `project_pnl.py:94-98` — `subcontractor_cost` = сума на `subcontractor_payments` в статус confirmed/paid/completed. Одобрен, но неплатен акт не намалява резултата; аванс към подизпълнител го намалява преди изпълнение.
- **Решение:** промяна в кода — разходът от одобрените актове/задължения; плащанията — отделна колона „платено“.

## Дневник на проходите

### Проход 2 — 06.11.2026 18:50 UTC (периодичен)

Нови SHA:

- #55 `dbda909` (5C-C24);
- #56 `3234446` (AUTH-02);
- #67 `98b18ec` (ST-02-C02);
- #69 `aee3169` (SEC-01-C01), после `f33b2ba` (SEC-01-C02);
- пакети `071d19b` (Р17–Р20, 5C-C25, AUTH-02, SEC-01-C02, ST-02-C02);
- main без промяна.

Проверки:

- **#67:** `PYTHONPATH=backend pytest backend/tests/test_st_02_staging_stack.py --noconftest` → 157 passed.
  - FG-2: `DEFAULT_MODE = "shadow"` (`staging_up.py:65`, `isolation_check.py:64`).
  - FG-3: наблюдаваният флаг се записва в `staging-deployment.json` и при разлика с параметъра deploy-ът се отказва (`staging_deploy.sh:107-142`). Production очакването в manifest-а е записано до него — обосновано.
  - FG-4: `--deployed-by`/`--approved-by` са задължителни.
  - FG-5: URL и bootstrap ключовете се проверяват.
  - FG-6: allow-list-ът е премахнат.
- **#56:** `pytest tests/test_auth_02_break_glass.py --noconftest` → 28 passed.
  - FG-7: Р19 изпълнено.
  - FG-8: само Owner.
  - FG-9: R1.
  - FG-10: `RETENTION = 730 дни`.
  - FG-11: admin path с `auth_version` + отмяна на токените. Остава собствената смяна на парола (`auth.py:232-240`) без `auth_version` → low.
  - FG-16: dev ключът само при изрично не-production `ENV`.
- **#69:** пробата `probes69` (реален Mongo) на `aee3169` и `f33b2ba`:
  - член SiteManager/Technician → 201 на труд и фира (FG-24 ✅);
  - Viewer `DELETE` модификатори → 403, редът остава; Owner/финансови → 409 без триене (FG-25 ✅);
  - Viewer sync → 403; `delete_many` в `labor_smr.py` вече го няма (FG-26 ✅);
  - Viewer `POST /subcontractor-payments` → 403, 0 реда. Плащането отива в `finance_payments` според `IMPLEMENTATION_WAVES.md:47` (FG-27 ✅);
  - отказ в `off` → 0 audit реда (FG-28 остава open);
  - FG-30: guard-ове на всичките 8 endpoint-а прочетени (`require_money_write`);
  - FG-24 за не-член не съм пробвал отделно. SEC-R1 (изтекло членство) е в SEC-01-C02 добавка A.
- **#55 C24:** точни FIFO слоеве, partial index за legacy. Нищо не се трие и не се drop-ва. Ново разминаване няма; FG-17…FG-23 чакат 5C-C25.
- **Нови решения Р17–Р20:** проверени срещу FLOW.
  - Р17 (разход при приемане) съвпада с FLOW-008/009 Път Б → затваря въпроса по FG-20.
  - Р18 (всяко преместване „в път“, връщане → карантина) съвпада с FLOW-009 → FG-18.
  - Р20 (таблица за финанси) не противоречи на FLOW-002/010 → затваря FG-13/FG-14.
  - Р19 → FG-33.
- **Бавен преглед на main:** FLOW-006 → `COVERAGE.md`; нови FG-34, FG-35.

### Проход 2b — 06.11.2026 19:05 UTC (съобщение от оркестратора, сверено с първоизточника)

Пакети `071d19b..b659a73`:

- **Р21** (частично приемане — всяка партида със своята цена) съвпада с FLOW-009 „стойността/партидата се пренасят“ → влиза в 5C-C25, добавка A.
- **Р22** (клиент на обект — само финансовите роли) не противоречи на FLOW-002/010.
- **Р23 → PAY-01** за FG-34. Пакетът е сверен с FLOW-006 §Корекции и CLAUDE.md §2.9/§7/§14:
  - сторно вместо изтриване;
  - задължителна причина;
  - AuditEvent;
  - idempotency;
  - само финансови роли;
  - справките нетират сторнираните двойки.
  - Разминаване няма.
- **Р24 → FLOW-043 D-16** + бележка за изключение във FLOW-040 L5 → FG-33 resolved. Важи в канона на клона с пакетите, докато не се слее в main.
- **FG-35** и липсата на idempotency при паричните записи → дълг за W0-05, по решение на оркестратора.
- **FG-21** (кой отписва) — още без решение.

### Проход 3 — 06.11.2026 20:50 UTC (периодичен)

Нови SHA:

- main `8e3b190` (merge PM-01 #68);
- #55 `64418eb` (5C-C25, C25-A, 5C-C26 + A/B, C26b, C26c);
- #67 `675faba` (ST-02-C03);
- #69 `07faab5` (SEC-R1, SEC-01-C03);
- нови: #70 `8910939` (PAY-01) и #71 `6080165` (SEC-02);
- пакети `3c9e57c` (Р25–Р27, 5C-C26, SEC-01-C03, PAY-01-C01, ST-02-C03, SEC-02-A).

Проверки:

- **Р25–Р27** — сверени, не противоречат на FLOW.
- **#55:** собствените тестове на PR-а (C25 + c26*) → 129 passed × off/shadow/enforce. Проби на реален Mongo:
  - FG-17: 150 навсякъде, застъпване 100, частично 40;
  - FG-18: директни трансфери се отказват; кредит само при приемане; връщане → карантина;
  - FG-19: 7;
  - FG-20: 50.
- **#67:** 162 тестa passed. Р26: режимът е в manifest-а (`ops/release/release_build.py:61-69`).
- **#69:**
  - SEC-R1: изтекло/бъдещо членство → 403;
  - суми NaN/inf/1e309/0/-1 → 422, 0 реда;
  - Idempotency-Key: повтор → 1 ред, друго тяло → 409.
  - Собствени тестове: 13 passed, 2 skipped.
- **#70:**
  - DELETE → оригиналът е `reversed` + сторно ред + 1 AuditEvent; нето 0; повтор 409;
  - отмяна на разпределение не трие нищо;
  - Viewer/SiteManager/Technician → 403.
  - Собствени тестове: 124 passed, 120 skipped (real-Mongo вариантите ползват други префикси на бази).
- **#71:** Viewer/Technician/SiteManager → 403 на финансовите GET от пробата; `/labor-entries` без ставки; Accountant вижда всичко. Собствени тестове: 12 passed, 1 skipped.
- **Бавен преглед на main:** FLOW-040 → FG-37 (PROVEN).

### Проход 4 — 06.11.2026 22:50 UTC (периодичен)

Нови SHA:

- main `35ae10b` (merge ST-02 #67 = `675faba`, проверен в проход 3);
- #55 `4a3d15c` (C26d, C26e);
- #69 `6d43284` (Р29);
- #70 `42bbdfc` (PAY-01-C01 A/B, C01A-1, D5);
- #71 `f17f7e5` (SEC-02-A/B/C);
- пакети `15a72cf` (Р28–Р32).

Проверки:

- **Р28–Р32** — сверени с FLOW-009/019/028/037. Р31 следва FLOW-019/028/037 и затваря въпроса по FG-44. Р32 уточнява Р20.
- **#55:** C26d + C26e → 269 passed (9 роли × 9 команди × 3 режима). Проби на реален Mongo:
  - FG-38: 422/403, нищо не е записано;
  - FG-39 и FG-40 — поправени;
  - регресия FG-17…20: 150 / 100 / 40 / 7 / 50;
  - Р28: 6 движения → 6 AuditEvent и в off/shadow.
- **#69:** 26 passed, 4 skipped. **#70:** 156 passed, 153 skipped. **#71:** 14 passed, 1 skipped.
  - Матрица на GET: 31 endpoint-а × 6 роли × off/enforce. Изтичанията на пари към не-финансови роли намаляват от 70 на 8; всичките 8 са SiteManager на позволените по Р20-2B бюджетни изгледи.
  - Р29 → 428 и 0 реда в #69/#70.
- **Бавен преглед на main:** FLOW-028 → FG-48 (PROVEN), FG-49.

### Проход 5 — 07.11.2026 00:50 UTC (периодичен)

Нови SHA:

- main без промяна (`35ae10b`);
- #55 `81e412c` (C26f, C26g);
- #69 `7300864` (C03-B);
- #70 `31ed258` (C01-C, C01-D);
- #71 `e6ea838` (SEC-02-D, merge #69 @ `6d43284`);
- нови: #72 `e733c66` (W0-04-C01) и #73 `709815d` (LAB-01);
- пакети `4b91217` (LAB-01, W0-04-C01 + добавки).

Проверки:

- **Пакети:** LAB-01 и W0-04-C01 са сверени с FLOW-019/028/040 — без разминаване.
- **#72:** FG-37 пробата с `ensure_audit_indexes` → 40/40, true. Без индексите → 4/20, false (FG-57). Собствени тестове: 5 passed, 10 skipped.
- **#55:** 399 passed (c26a/b/d/e/f). Проби ×3 режима:
  - FG-53: 422, 0 реда;
  - FG-54: 403;
  - FG-56: Р32 ✅;
  - регресия 150 / 100 / 40 / 7 / 50, FG-38;
  - Р28: 5 AuditEvent на режим.
- **#69:** 6 passed (real Mongo). **#70:** 258 passed, 252 skipped. **#73:** 18 passed (real Mongo).
- **#70 добавка C:** 6 рунда паралелни allocate/quick-pay → 1 успех + 1 409, фактурата не надвишава сумата. Страничен ефект: два несвързани allocate от едно плащане също получават 409 PAYMENT_BUSY (UX, low).
- **#71:** не съдържа #69 @ `7300864` → FG-29 и FG-47 там още са отворени.
- **Бавен преглед на main:** FLOW-019 → FG-58.

## Бележки, които не са разминавания

- #67: доказателствата казват „50 passed“, а тестовете вече са 110. 26 реда с локални пътища на scratchpad.
- #67: `schema_version` и `entitlements.snapshot` = null идват от main (W0-08 не е изпълнен). Това е дълг спрямо CLAUDE.md §6, не грешка на PR-а.
- Пакетът R0-04 мълчи за Approval/break-glass и срока на security събитията. Затова FG-7…FG-10 не са грешка на изпълнителя.

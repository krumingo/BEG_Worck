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
| FG-11 | medium | #56 `dae097b` | admin set-password не прекъсва старите сесии и линкове | SUSPECTED | open, low — сега е на main `0f870c3` (#56 слят): собствената смяна на парола не вдига `auth_version` |
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
| FG-28 | medium | main + #69 | отказите в `off`/`shadow` не се одитират (а staging = `shadow` по Р15) | PROVEN | open — сега и на main `d226c49` (#70 слят): Viewer POST/DELETE на плащане в enforce → 403, 0 AuditEvent |
| FG-29 | medium | #69 `e6c0e46` | price-modifiers/material-waste приемат project_id без проверка, че обектът е на фирмата | SUSPECTED | resolved (#69 `7300864`, #71 `71f9bbe`; PROVEN: 404, 0 реда) |
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
| FG-47 | low | #69 `07faab5` / #70 `8910939` | различно правило за сума: #69 приема „12“ (низ), #70 — 422 | PROVEN | resolved (#69, #70, #71 `71f9bbe`; PROVEN: „12“ → 422) |
| FG-48 | high | main `35ae10b` | Pay Run: акорд без количество се плаща като часове × ставка | PROVEN | resolved (#73 `709815d`, PROVEN: акорд 40ч без количество → 0; 120 м2 × 5 → 600) |
| FG-49 | medium | main `35ae10b` | Pay Run: типът заплащане идва само от профила, не от СМР реда/пакета | SUSPECTED | resolved (#73 `709815d`: ред → пакет → профил) |
| FG-50 | medium | #70 `42bbdfc` (и main) | other-expense / other-income записват в регистъра към несъществуващ обект | PROVEN | partial (#70 `31ed258`, PROVEN: отказ, нищо записано) — статус 422, а #69 дава 404; other-income без обект → 201, other-expense → 400 |
| FG-51 | high | main / #71 `f17f7e5` | sync на труда от неодобрени отчети; акордът се смята по часове | SUSPECTED | resolved (#73 `709815d`: само Approved, без часове × ставка по подразбиране) |
| FG-52 | medium | #71 `f17f7e5` | #71 съдържа #69 @ `07faab5`, не `6d43284`: парични POST без Idempotency-Key минават (201) | PROVEN | resolved (#71 `e6ea838`, PROVEN: 428, 0 реда) |
| FG-53 | medium | #55 `4a3d15c` | consume/transfer от обект приемат различен `project_id` от тялото на заявката | PROVEN | resolved (#55 `81e412c`, PROVEN ×3 режима; дестинацията → FG-61) |
| FG-54 | medium | #55 `4a3d15c` | каноничните четения на склада не се решават по роля в off/shadow (F-16) | SUSPECTED | resolved (#55 `81e412c`, PROVEN ×3 режима) |
| FG-55 | low | #55 `4a3d15c` | родителят на подобект се връща в грешката преди проверката на правата | PROVEN | resolved (#55 `f0d86ab`; `/movements` → FG-69) |
| FG-56 | medium | #55 `4a3d15c` | Р32: складовият работник не вижда единичните цени (добавка E не е изпълнена) | PROVEN | resolved по Р32 (#55 `81e412c`, PROVEN ×3 режима) |
| FG-57 | low | #72 `e733c66` | `record_event` върху база без уникалния индекс пак разклонява веригата тихо (няма fail-closed) | PROVEN | resolved (#72 `8ac194a`, PROVEN: без индекси 20/20, true) |
| FG-58 | medium | main `35ae10b` | ръчен `POST /labor-entries` без присъствие и отчет; възможно двойно броене със sync | SUSPECTED | resolved като механика (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`), PROVEN); остатъци → FG-423, FG-463 |
| FG-59 | high | #55 `81e412c` | роля, вързана с обект, действа в централния склад, ако добави `project_id` в тялото | PROVEN | resolved (#55 `518aab4`, PROVEN ×3: 403 R28_PROJECT_REQUIRED, 0 реда) |
| FG-60 | medium | #55 `81e412c` | `balance` и `history` без филтър показват количества на чужди обекти на не-член SiteManager | PROVEN | resolved (#55 `518aab4`, PROVEN ×3: само член-обекти) |
| FG-61 | medium | #55 `81e412c` | приемане от доставчик към обект с различен `project_id` от тялото | PROVEN | resolved (#55 `518aab4`, PROVEN ×3: 422, 0 реда) |
| FG-62 | low | #55 `81e412c` | историята на складовия работник показва пари на обекти (CONSUME_TO_SMR) — Р32 „без финанси на обекти“ | SUSPECTED | resolved по Р34 (#55 `8025871`, PROVEN; фира от централния склад → FG-96) |
| FG-63 | high | #71 `e6ea838` | Р31: работниците се броят за цялата история, „изхарчено“ — за периода → ставката на един човек се изчислява | SUSPECTED | resolved (#71 `71f9bbe`, PROVEN: периодът се игнорира за SiteManager; броенето — от същия източник) |
| FG-64 | high | #73 `709815d` | акордна цена и одобрено количество идват от реда в отчета, който работникът попълва | SUSPECTED | resolved (#73 `c422cbd`, PROVEN: 400, нищо записано; Pay Run игнорира полетата от реда) |
| FG-65 | high | #73 `709815d` | нищо в кода не задава одобрено количество или акордна цена на пакета → всички на акорд получават 0 | SUSPECTED | resolved по Р33 — LAB-02 `0c85678` въвежда одобрението на количество (PROVEN: 120 × 5 → 600); LAB-01 и LAB-02 се сливат заедно |
| FG-66 | medium | #73 `709815d` | след преизчисление „остава за плащане“ може да стане отрицателно, вместо корекция | SUSPECTED | partial — #73 `00324ab`: корекцията е запис `pending_approval` + AuditEvent + DQ; без Approval (W0-07); дублиране → FG-80 |
| FG-67 | medium | main `35ae10b` | P&L „бюджет“ сумира оферти Draft + Sent + Accepted (всички версии) като договорена стойност | SUSPECTED | open |
| FG-68 | medium | main `35ae10b` | P&L: подизпълнителите се признават при плащане, не при одобрен акт | SUSPECTED | open |
| FG-69 | medium | #55 `518aab4` | `/movements` от подобект: отказът назовава родителя и работи като да/не проверка | PROVEN | resolved (#55 `f0d86ab`, PROVEN ×3: един и същ 403, само подобектът) |
| FG-70 | high | #55 `518aab4` | член на P1 приема изпращане склад → обект, предназначено за P2, в P1 | PROVEN | resolved (#55 `f0d86ab`, PROVEN ×3: отказ, 0 реда) |
| FG-71 | low | #55 `518aab4` | роли, вързани с обект, не виждат наличността в централния склад | SUSPECTED | resolved по Р35 (#55 `8025871`, PROVEN: цени в централния склад, без движения, история само за член-обекти) |
| FG-72 | high | #73 `c422cbd` | два реда с едно id → акордът се плаща двойно; одобрението на количество не е вързано към версия | PROVEN | resolved (#73 `00324ab`, PROVEN: 120 + DUPLICATE_REPORT_ENTRY; reset → void) |
| FG-73 | medium | #73 `c422cbd` (и main) | всеки с M4 редактира чужда чернова на дневен отчет | PROVEN | resolved по Р36 (#73 `ca81286`, PROVEN); стари отчети → FG-91 |
| FG-74 | medium | #71 `71f9bbe` | Р31: колега без разход прави сумата на един човек видима → ставката се изчислява | PROVEN | resolved (#71 `dee0610`, PROVEN: само платени работници) |
| FG-75 | medium | #71 `71f9bbe` | `PUT /price-modifiers` без AuditEvent | PROVEN | resolved (#71 `dee0610`, PROVEN ×3: 1 AuditEvent с before/after) |
| FG-76 | medium | #71 / #73 | две числа за „изхарчено“: expected-actual от work_sessions срещу LAB-01 | SUSPECTED | resolved (#73 `00324ab`: всички през `project_labor_cost`) |
| FG-77 | medium | main `35ae10b` | режийни: изтриване на разходи/категории и презаписване на разпределенията (`delete_many`), без версия | SUSPECTED | resolved (main `ea57121`, проход 33, PROVEN: неизползван запис се архивира, остава в базата; без ключ → 428; три разпределения → версии [1,2,3]; P&L 400, не двойно) |
| FG-78 | high | #73 `00324ab` (и main) | `PUT /technician/draft/{id}` — всеки редактира чужд отчет в Draft/Submitted | PROVEN | resolved (#73 `c4ddd33`, PROVEN: 403, нищо записано) |
| FG-79 | high | #73 `00324ab` (и main) | `POST /daily-reports/batch-save` пренаписва одобрен отчет, а той остава одобрен | PROVEN | resolved (#73 `c4ddd33`, PROVEN: одобрен → 409/403, нищо записано) |
| FG-80 | medium | #73 `00324ab` | една надплата → корекция на всеки Pay Run; Idempotency-Key на `POST /pay-runs` не се спазва | PROVEN | resolved (#73 `ca81286`; FG-84 ✅, FG-85 с #72) |
| FG-81 | low | #71 `dee0610` | Р31: работник с 0.01 € „отключва“ сумата по СМР | SUSPECTED | resolved по Р42 (прагът остава 2 платени работника; Крум приема остатъчния риск) |
| FG-82 | low | #71 / #73 | AuditEvent се пише след бизнес записа, без транзакция | SUSPECTED | open |
| FG-83 | medium | main `35ae10b` | повторно разпределение на фактурен ред заменя старото без версия и без проверка на статуса на фактурата | SUSPECTED | open |
| FG-84 | high | #73 `c4ddd33` | надплатата се коригира втори път, ако новият Pay Run покрива периода с по-широк интервал | PROVEN | resolved (#73 `ca81286`, PROVEN: 5 run-а → 1 корекция) |
| FG-85 | high | #73 `c4ddd33` (база main) | 6 едновременни POST /pay-runs с един ключ → 4 run-а; уникалният индекс идва с #72 | PROVEN | resolved при merge с #72 (PROVEN в пробен merge: 6 паралелни → 1 run); без #72 остава → FG-95 |
| FG-86 | high | OH-01 `09409f0` | два snapshot-а за един период се разпределят и двата → режийните в P&L са двойни (862 = 2×431) | PROVEN | resolved (OH-01 `6c5c5cf`, PROVEN ×3: P&L 431; застъпващи се периоди → 409) |
| FG-87 | medium | OH-01 `09409f0` | тиха промяна на използван режиен разход (PUT → 99999, 200, без AuditEvent); обход на 409 чрез смяна на датата | PROVEN | resolved (OH-01 `6c5c5cf`, PROVEN ×3: 409, нищо не се променя; AuditEvent при позволено) |
| FG-88 | medium | OH-01 `09409f0` | `POST /overhead/snapshots/compute` без Idempotency-Key → 200 | PROVEN | resolved (OH-01 `6c5c5cf`, PROVEN: 428; replay → същото) |
| FG-89 | high | main / OH-01 | втори път за режийни: `full_cost.py:185-250` → `project_overhead_alloc` без версия, без AuditEvent | SUSPECTED | resolved (OH-01 `45178ac`, PROVEN: compute е read-only; нетната печалба = OH-01, дори с подхвърлени 99999) |
| FG-90 | medium | main `0f870c3` / #69 `7300864` | плащане към подизпълнител без таван спрямо актуваното и без задължителен акт | SUSPECTED | resolved (#69 `ccab244`, PROVEN: над актуваното → 409, 0 реда; 6 паралелни → в рамките на тавана); аванс → FG-102 |
| FG-91 | high | #73 `ca81286` | платен отчет в стар формат (`employee_id`) се поправя на място — заключването за платено не го хваща | PROVEN | resolved (#73 `3107ba0`, PROVEN: стар формат в платен run → 409, нищо не е променено) |
| FG-92 | high | LAB-02 `0c85678` | поправящият (или подалият) отчета одобрява собствената си поправка на количество | PROVEN | resolved (LAB-02 `ba08ab5`, PROVEN: поправката отваря отчета; поправил/подал → 403) |
| FG-93 | high | LAB-02 `0c85678` | одобрение и класификация на вече платен ред минават (200) | PROVEN | resolved (LAB-02 `ba08ab5`, PROVEN: approve/classify/entry на платен ред → 409) |
| FG-94 | low | LAB-02 `0c85678` | класификация като престой на ред в чернова | PROVEN | resolved (LAB-02 `ba08ab5`, PROVEN: Draft/Rejected → 409) |
| FG-95 | medium | #72 / #73 / LAB-02 | ред на merge: LAB-02 не съдържа `ca81286`; без #72 6 паралелни одобрения → 4 | PROVEN | resolved за реда #73 → LAB-02 (ca81286 и 3107ba0 са в `ba08ab5`); #72 остава задължителен преди LAB-02 за Р29 (без него до 2 записа на ключ) |
| FG-96 | medium | #55 `8025871` | складовият работник вижда стойността на фирата от централния склад | PROVEN | resolved по Р37 (#55 `4ed6077`, PROVEN ×3) |
| FG-97 | low | OH-01 `6c5c5cf` | режийните в P&L падат на 0 между ново изчисление и преразпределение | PROVEN | resolved по Р38 (OH-01 `6a4ac5b`, PROVEN: P&L 431 с „преизчислява се“ → 531 след разпределение) |
| FG-98 | low | OH-01 `6c5c5cf` | съществуващите tenant бази не получават уникалните индекси на OH-01 | SUSPECTED | resolved (OH-01 `6a4ac5b`, PROVEN: индексите и в tenant базите от регистъра) |
| FG-99 | high | #73 `3107ba0` / LAB-02 `ba08ab5` | `POST /daily-reports/{id}/reset` заобикаля заключването за платено и не пише AuditEvent | PROVEN | resolved (#73 `4da2ee6`, LAB-02 `ef16a16`, PROVEN: платен/потвърден → 409, нищо не е променено; разрешен reset → AuditEvent) |
| FG-100 | medium | LAB-02 `ba08ab5` | акордната цена се сменя от един човек — FLOW-002 иска двама за „промяна на … ставка“ | SUSPECTED | resolved по Р41 (LAB-02 `ef16a16`, PROVEN: версия + AuditEvent, одобреното остава на старата цена) — канонът → FG-107 |
| FG-101 | low | LAB-02 `ba08ab5` | двама одобряващи на една версия → и двамата 200, вторият тихо анулира първия | PROVEN | resolved (LAB-02 `ef16a16`, PROVEN: втори одобряващ → 409 ALREADY_APPROVED) |
| FG-102 | medium | #69 `ccab244` | няма път за аванс към подизпълнител (всяко плащане > актуваното → 409) | PROVEN | resolved по Р39 (SUB-ADV-01 `f42da33`, PROVEN: аванс само Owner/Accountant, изрично приспадане) — FG-113…FG-115 |
| FG-103 | high | #69 `ccab244` | резервираната платена сума (`committed_paid_total`) никога не се освобождава | SUSPECTED | resolved (SUB-ADV-01 `542fa2c`, PROVEN: срив → pending, без фантомен аванс; приспадане → 409; retry довършва) — висящият pending → FG-132 |
| FG-104 | low | #69 `ccab244` | таванът е само по пакет, не по акт | PROVEN | resolved по Р40 (таван по пакет) |
| FG-105 | low | #69 `ccab244` | `paid_total` се смята с `to_list(200)` — над 200 плащания сумата е грешна | SUSPECTED | resolved (#69 `3fb55f2`: `$group/$sum` в базата) — SUB-ADV-01 го връща → FG-113 |
| FG-106 | high | main `0f870c3` | клиентски акт: цена и количество от заявката, без остатък и без защита от двойно актуване | SUSPECTED | partial — ACT-01 `8188689` изпълнява FLOW-004 (PROVEN); остава D1 родословие на версиите (решение на Крум) |
| FG-107 | low | Р41 срещу FLOW-002 | Р41 разрешава смяна на акордна цена от един човек; FLOW-002 иска двама за „промяна на … ставка“ | SUSPECTED | resolved (FLOW-043 D-17, `96aef03` на клона с пакетите) |
| FG-108 | high | #55 `43477d8` | партида от един фактурен ред се брои двойно, ако дойде и през склада, и пряко | PROVEN | resolved (#55 `d98cead`, PROVEN: склад + пряко → 409 FULLY_LINKED, P = 100) |
| FG-109 | medium | #55 `43477d8` / main | фактурен ред се преразпределя след доставката → двата обекта носят разход | PROVEN | partial (#55 `d98cead`, PROVEN: 409 ALLOCATION_LOCKED) — обход чрез старото единично разпределение → FG-124 |
| FG-110 | medium | #73 `4da2ee6` / LAB-02 `ef16a16` | едновременни reset-и връщат бюджета няколко пъти (40 → 8 вместо 32) | PROVEN | resolved (#73 `41a43b5`, LAB-02 `f0a0757`, PROVEN: 6 паралелни → 1 × 200, 40 → 32 веднъж) |
| FG-111 | medium | #71 `5af530e` | `/alarms` показва % изхарчен бюджет на всички роли | PROVEN | partial (#71 `e90aa5f`, PROVEN: `/alarms` без пари за не-финансови) — `/alarm-rules` → FG-125 |
| FG-112 | low | #73 / LAB-02 | отказите при reset издават дали отчетът съществува и дали е в заплати | PROVEN | resolved (#73, LAB-02, PROVEN: един и същ 403) |
| FG-113 | medium | SUB-ADV-01 `f42da33` | клонът не е от head-а на #69 — губи добавки E/F (`to_list(1000)`, retry на резервацията) | PROVEN | resolved (SUB-ADV-01 `17aa55d` съдържа `3fb55f2`) |
| FG-114 | medium | SUB-ADV-01 `f42da33` | аванс без горна граница (1 000 000 при договор 5 000 → 201) | PROVEN | resolved (SUB-ADV-01 `17aa55d`, PROVEN: аванс над стойността на пакета → 409) |
| FG-115 | low | SUB-ADV-01 `f42da33` | авансът влиза в P&L като разход за подизпълнител преди изпълнение | SUSPECTED | partial (SUB-ADV-01 `17aa55d`, PROVEN: преди приспадане разходът е 0, cash_out 1000) — авансът не е отделен ред в P&L → FG-128 |
| FG-116 | low | OH-01 `45178ac` | етикетът „преизчислява се“ (Р38) липсва в новите четения на FG-89 | PROVEN | resolved (OH-01 `997abdc`, PROVEN: етикетът и старата стойност навсякъде) — разлика P&L/печалба → FG-127 |
| FG-117 | low | #72 `cb5d061` | грешките на индексите съдържат името на tenant базата | SUSPECTED | partial (#72 `04e0a1b`: само `db-<sha12>`) — един път още с името → FG-126 |
| FG-118 | medium | main `0f870c3` | допълнително СМР без „кой плаща“ — може да стане прието и актувано без финансово третиране | SUSPECTED | open |
| FG-119 | high | ACT-01 `c6c7f1c` | `POST /client-acts/{id}/confirm`: всяка роля с M2 (Viewer → 200); без ключ, транзакция и canonical AuditEvent; приема акт по заменена версия | PROVEN | resolved (ACT-01 `8188689`, PROVEN ×2 режима: 403 за не-финансови, 428 без ключ, транзакция, 1 AuditEvent, заменена версия → 409, 6 паралелни → 1) |
| FG-120 | medium | ACT-01 `c6c7f1c` | изгледът „остатък“ събира таваните на две версии (16 вместо 6) | PROVEN | resolved (ACT-01 `8188689`, PROVEN: само активната версия, `acting_blocked`) |
| FG-121 | medium | ACT-01 `c6c7f1c` | единичната цена се закръгля до цент преди умножението (1234.00 → 1230.00) | PROVEN | resolved (ACT-01 `8188689`, PROVEN: 100 × 12.345 = 1234.50, цената се пази точно) — центове при частични актове → FG-131 |
| FG-122 | medium | main / ACT-01 | `GET /client-acts` и `/{id}` показват цените на Viewer (Р20) | PROVEN | resolved (ACT-01 `c7df7ca`, PROVEN: GET client-acts зад `require_finance_read` — не-финансови роли 403, по-строго от маскирането) |
| FG-123 | low | ACT-01 `c6c7f1c` | акт по v1 може да се запише в момента на приемане на v2 (приемането е извън транзакцията) | SUSPECTED | resolved (ACT-01 `8188689`, PROVEN: 30 надпревари × 2 дървета, нито един акт след приемането на v2) |
| FG-124 | medium | #55 `d98cead` | заключването от FG-109 се заобикаля чрез старото единично разпределение (`allocation_ref_id`) | PROVEN | resolved (#55 `94c0571`, PROVEN: 409 ALLOCATION_LOCKED, P/Q 100/0) |
| FG-125 | medium | #71 `e90aa5f` | `/alarm-rules` показва прага на бюджета (80%) на всички роли | PROVEN | resolved по Р20 (SEC-02 добавка G: прагът е настройка, не сума) — свободното поле `condition` → FG-133 |
| FG-126 | low | #72 `04e0a1b` | недублирана грешка при създаване на индекс още носи името на tenant базата | PROVEN | resolved (main `2ec61f3`, #78 W0-04-C02: `AuditIndexError` + `safe_reason`, `from None`) |
| FG-127 | medium | OH-01 `997abdc` | P&L и financial-results показват 323.25, а нетната печалба/печалбата на обекта 823.25 (legacy режийни) | PROVEN | resolved (OH-01 `31a9478`, PROVEN: 823.25 навсякъде, един четец) |
| FG-128 | low | SUB-ADV-01 `17aa55d` | P&L не показва неприспаднатия аванс като отделен ред | SUSPECTED | partial (SUB-ADV-01 `542fa2c`, PROVEN: даден/приспаднат/остатък на /project-profit само за финансови роли) — `/pnl` и financial-results без аванс. Решение на Крум коя страница |
| FG-129 | high | main `d226c49` | стара версия на оферта остава приемаема (вътрешно и по клиентския линк) след нова версия | SUSPECTED | resolved (OFF-01 `2379d07`, вкл. legacy двойки — FG-135) |
| FG-130 | medium | main `d226c49` | `DELETE /offers/{id}` трие окончателно изпратена/отказана оферта | SUSPECTED | resolved (OFF-01 `2379d07`: Sent/Accepted → 409; DELETE ∥ send — FG-136) |
| FG-131 | low | ACT-01 `8188689` | частичните актове по ред с 12.345 дават 1234.51 срещу 1234.50 на офертата | PROVEN | resolved (ACT-01 `dd11e8e`, PROVEN: 33+33+34 → точно 1234.50; потвърденото не се променя) — 1 цент при потвърждаване → FG-142 |
| FG-132 | low | SUB-ADV-01 `542fa2c` | висящ pending аванс (без retry) държи място под тавана завинаги | SUSPECTED | open |
| FG-133 | low | #71 `83f1bf3` | `GET /alarm-rules` не филтрира свободното `condition` — праг в EUR би се видял от всички | SUSPECTED | partial (#71 `bfeda82`, PROVEN: `amount_eur`/`limit_eur` скрити) — `threshold` и името с EUR → FG-141 |
| FG-134 | high | main `d226c49` | дневен отчет без присъствие (или при болничен/отпуск) и със задна дата се записва само с предупреждение | SUSPECTED | open |
| FG-135 | high | OFF-01 `bfc41f5` | legacy двойка версии: старата Sent версия още се приема по стария линк, после новата е блокирана | PROVEN | resolved (OFF-01 `2379d07`, PROVEN ×3: стара версия с по-нова → 409, линк → 410, редовете не са мигрирани) |
| FG-136 | medium | OFF-01 `bfc41f5` | DELETE в надпревара със send трие току-що изпратена оферта (28/30), send → 500 | PROVEN | resolved (OFF-01 `2379d07`, PROVEN: ×10 × 3 режима — 0 изгубени, 0 × 500) |
| FG-137 | medium | OFF-01 `bfc41f5` | приемане със `signed_pdf` без файл → 200, evidence None | PROVEN | resolved (OFF-01 `2379d07`, PROVEN: без/чужд файл → 422; verified_email → 422 + дълг D-OFF01-14) |
| FG-138 | medium | OFF-01 `bfc41f5` | отменен/заменен линк още показва цялата стара оферта; клиентът вижда разбивка материал/труд | PROVEN | resolved по Р43 (OFF-01 `2379d07`, PROVEN: отменен линк → 410 без цени; клиентът и PDF — само обща цена); xlsx (вътрешен) → дълг D-OFF01-16 |
| FG-139 | low | main / OFF-01 | `offers.review_token` се пази в явен вид, не като hash | PROVEN | open — дълг D-OFF01-15 (PROVEN: токенът още е в явен вид) |
| FG-140 | high | #55 `cba5306` | редакция на ред в надпревара с изпращане променя вече изпратена/платена фактура | PROVEN | resolved (#55 `ed48595`, PROVEN: 10 случая → 409 INVOICE_NOT_DRAFT, нищо не е променено; 15×6 паралелни → 0 разминавания) |
| FG-141 | medium | #71 `bfeda82` | `/alarm-rules` още показва `threshold` и име с EUR сума на не-финансови роли | PROVEN | partial (#71 `b1ab349`, PROVEN: прагът по разрешен списък (type, metric), fail-closed) — името с EUR още се показва; решение на Крум (изключение по добавка G или маскиране) |
| FG-142 | low | ACT-01 `dd11e8e` | потвърдената стойност може да е с 1 цент различна от показаната чернова | PROVEN | resolved (ACT-01 `2cc1147`, PROVEN ×3: разлика → 409 ACT_VALUE_CHANGED, нищо не е записано) |
| FG-143 | medium | main `d226c49` | снимки и файлове на локалния диск с URL в отделни колекции, не през File Registry (`file_id`) | SUSPECTED | open — дълг W0-06 |
| FG-144 | high | main / OFF-01 `2379d07` | вътрешен reject презаписва клиентско приемане (Accepted → Rejected), без условие за статус | PROVEN | resolved (OFF-01 `acc472f`, PROVEN: 120 × 3 режима надпревари → винаги 1 × 200 + 1 × 409; Р29; AuditEvent; заменена версия → 409) |
| FG-145 | medium | #55 `ed48595` (и main) | сканирани документи: link/unlink по изпратена/платена фактура без проверка; изтриването трие оригиналния файл | PROVEN | open (main `ea57121`, проход 35, PROVEN: Техник свързва скан с платена фактура, трие скана и оригиналният файл се премахва) |
| FG-146 | medium | main / #55 | заглавието и редовете на Sent/Overdue/PartiallyPaid фактура могат да се редактират (само snapshot) | SUSPECTED | open |
| FG-147 | medium | SUB-ADV-01 `c4de7c9` | аванс и приспадане пишат само legacy `log_audit`, без canonical AuditEvent | PROVEN | open |
| FG-148 | low | SUB-ADV-01 `c4de7c9` | толерансът при актуване (0.01) може да вдигне актуваното над договора → последното плащане се отказва | SUSPECTED | open |
| FG-149 | low | OFF-01 `acc472f` | отварянето на клиентския линк сменя `updated_at` → фалшиво 409 при нова версия | PROVEN | resolved (OFF-01 `653a1a5`, PROVEN: 87 passed на реален Mongo) |
| FG-150 | high | main `2ec61f3` | изписването от склада е 0 в P&L, финансовия резултат и централните справки (четат `unit_cost`, а изписването пише `unit_price`) | SUSPECTED | resolved на #81 `5c0faa5` (още не е в main): картата „Материали“ и агрегатът през каноничния helper (`projects.py:1034-1046, 1417-1423, 2152-2161`) |
| FG-151 | high | main `2ec61f3` | стойността на изписването идва от клиента; обектът не приема (`received_by` е текст) | SUSPECTED | resolved (main `cd03324`: legacy изписване 410; изходящ `unit_value` от клиента се отказва `service.py:1413-1417`; стойност от слоевете `:1087-1098`; приемане отделно — Rule B. Входящата цена → FG-191) |
| FG-152 | high | main `2ec61f3` | `/warehouse-return` и `/project-consumption` без роля и AuditEvent; връщането отива в свободна наличност, без карантина и без стойност | SUSPECTED | resolved (main `cd03324`: `/warehouse-return` и `/project-consumption` 410 `procurement.py:566-601`; каноничното връщане отива в карантина `service.py:1460-1463, 1520-1523`, права по Р28, AuditEvent. Остатък: старите `type:return` редове не намаляват разхода отпреди cutover) |
| FG-153 | high | main `2ec61f3` | втори складов регистър (`warehouse_batches`) до `warehouse_transactions`; `/warehouse/consume` изписва без обект и основание | SUSPECTED | partial — на изчакване по заявка на оркестратора; решението за регистъра отпада (main `cd03324`: `warehouse_batches` е проекция, legacy записите 410). Остава: четенията на `fifo_service.py:142-175` и `warehouse_batches.py:72-95` ползват старата схема (`remaining_qty`, `unit_cost`) срещу проекцията (`remaining_quantity`, `unit_value`, `projections.py:228-260`) → `/warehouse/value` показва само замразените стари партиди; старата наличност не е мигрирана (`warehouse_migration.py:87-102` → 405) |
| FG-154 | high | main `2ec61f3` | P&L не чете `allocations[]` на фактурния ред (само старите `allocation_type`/`allocation_ref_id`), т.е. разделеният ред е 0 или 100% | SUSPECTED | partial (#81 `5c0faa5`: разделяне по ред `dashboard.py:766-789`; header fallback `:791-803` → FG-199) |
| FG-155 | medium | main `2ec61f3` | остатъкът от фактурния ред може да остане неразпределен; разпределение „склад“ не създава наличност | SUSPECTED | partial (#81 `5c0faa5`: състояние от `allocations[]` `invoice_allocation.py:63-95`, „фактури за разпределяне“ + DQ + аларма; не покрива header-only (FG-199) и вградени редове (FG-200); „склад“ не създава наличност) |
| FG-156 | medium | main `2ec61f3` | директна доставка влиза в склад `main`; приемането по фактура не е атомарно и е без Idempotency-Key | SUSPECTED | resolved (main `cd03324`: post-to-warehouse 410; директна доставка само към обекта на реда `service.py:1783-1815`; заключване в транзакция `:1029-1036`; задължителен `idempotency_key` `warehouse_canonical.py:76`) |
| FG-157 | medium | main `2ec61f3` | фактура на доставчик се редактира след приемане в склада, без корекционно движение | SUSPECTED | partial (#81 `5c0faa5`: редакция след преглед → 409 + AuditEvent в транзакция; няма корекционен endpoint — дълг README #4) |
| FG-158 | medium | main `2ec61f3` | отрицателни количества и надпревара при изписване/FIFO консумация → отрицателна наличност | SUSPECTED | resolved (main `cd03324`: qty > 0 `envelope.py:354-355`; FIFO и наличност в транзакция `service.py:820-860`, `NegativeStockError`; legacy пътищата 410) |
| FG-159 | medium | main `2ec61f3` | брак/фира не е складово движение: без стойност, без намаляване на наличността | SUSPECTED | resolved на #81 `5c0faa5` (още не е в main): фирата е канонично отписване през единствения писател (`routes/material_waste.py:63-104`), Р27, Idempotency-Key, AuditEvent |
| FG-160 | medium | main `2ec61f3` | `create-sub-project` пренаписва `project_id` на историческите движения и плащания, без Approval | SUSPECTED | open, по-тежко (main `cd03324`: `projects.py:1565-1585` пренаписва и каноничните редове → FG-193) |
| FG-161 | medium | main `2ec61f3` | складовите стойности се виждат от всички роли (Р20/Р34/Р35) | SUSPECTED | resolved на #81 `5c0faa5` (още не е в main): маскиране в batches/stock/value/transactions |
| FG-162 | medium | main `2ec61f3` | материалът е свободен текст (`material_name|unit`), не Master артикул; заявката става `fulfilled` без сравнение на количества | SUSPECTED | partial (main `cd03324`: `fulfilled` без сравнение изчезна; каноничната команда изисква `item_id`; заявките още са свободен текст `procurement.py:120-170`, без изпълнение по ред; Master проверката е изключена → FG-192) |
| FG-163 | low | main `2ec61f3` | склад с наличност се деактивира или сменя типа си без проверка и без одит | SUSPECTED | partial (#81 `5c0faa5`: общ 409 guard с DELETE; без AuditEvent и без транзакция около check-then-write `warehouses.py:267`) |
| FG-164 | medium | main `2ec61f3` | липсват движения склад→склад, обект→обект, „в път“, връщане към доставчик, ревизия; наличност само за склад `main` | SUSPECTED | resolved (показване) на #81 `5c0faa5`; legacy + канонично заедно след миграция (README #7) |
| FG-165 | high | main `2ec61f3` | няма регистър на проверени IBAN-и; плащане към нов/различен IBAN не се блокира | SUSPECTED | resolved (#83 CP-01 `7e0b914`, PROVEN), без FG-242 и FG-243 |
| FG-166 | high | main `2ec61f3` | дублирани контрагенти по ЕИК и по роля в 5 регистъра | SUSPECTED | open |
| FG-167 | high | main `2ec61f3` | hard delete на контрагент с история (проверката гледа само `invoices`) | SUSPECTED | resolved (#83 `ea51030`, PROVEN: DELETE на петте регистъра → 409 `COUNTERPARTY_NO_DELETE`; lifecycle неактивен/архивиран с причина и AuditEvent) |
| FG-168 | medium | main `2ec61f3` | финансовите суми по клиент/контрагент се виждат от всяка роля с модул M5 (#71 не ги покрива) | SUSPECTED | open |
| FG-169 | medium | main `2ec61f3` | профилът смесва приходи и разходи (без `direction`) и брои само 20 фактури | SUSPECTED | partial (#81 `5b08e59` WH81-03: `/clients/{id}/summary` брои приход само от издадени фактури, `routes/clients.py:782`; остават статусите (Draft/Cancelled) и `total_invoiced` от 20 фактури в counterparties; не е в main) |
| FG-170 | medium | main `2ec61f3` | клиентската карта връща 404 за клиенти фирми/лица на обекта | SUSPECTED | open |
| FG-171 | medium | main `2ec61f3` | create/update на контрагенти, клиенти, фирми, лица без право и/или без AuditEvent | SUSPECTED | resolved (#83 CP-01 `7e0b914`, PROVEN); дълг D13 (PUT на проект без ключ/AuditEvent), D14 (без legacy `audit_logs`) |
| FG-172 | medium | main `2ec61f3` | ЕГН се връща в явен вид на всеки логнат | SUSPECTED | resolved (#83 CP-01 `7e0b914`, PROVEN); дълг D19: `invoices.counterparty_eik` на физическо лице е пълно ЕГН, видимо за Admin |
| FG-173 | high | main `2ec61f3` | клиентското одобрение по линк не е ApprovalReceipt (свободно име, без контакт, hash, AuditEvent) | SUSPECTED | partial (OFF-01 #79 `f526182`, SUSPECTED: запис, вързан към версията, и AuditEvent (`offers.py:1673`); но `client_name` идва от тялото на заявката (`:1630`), без контакт и hash на версията; `verification` = `link_token_only` (`:1653`)) |
| FG-174 | low | main `2ec61f3` | ролята на контрагента е едно поле, не множество | SUSPECTED | open |
| FG-175 | low | main `2ec61f3` | IBAN-ът във фактурата е свободен текст; няма проверена собствена сметка | SUSPECTED | partial (#83 CP-01 `7e0b914`: IBAN на входяща фактура се сверява при плащане; собствената ни сметка в изходящите — дълг D20) |
| FG-176 | high | main `2ec61f3` | handover сменя локацията и затваря custody на предаващия преди ACCEPTED | SUSPECTED | open |
| FG-177 | high | main `2ec61f3` | `take` със `to_id` записва ACCEPTED custody на друг потребител; „вземи от него“ само със сканиране | SUSPECTED | open |
| FG-178 | high | main `2ec61f3` | отказът няма причина/доказателство и оставя актива без отговорник | SUSPECTED | open |
| FG-179 | medium | main `2ec61f3` | `drop` на обект прехвърля без приемане от отговорника на обекта | SUSPECTED | open |
| FG-180 | high | main `2ec61f3` | ГОСТ получател без задължителни данни и DQ блок | SUSPECTED | open |
| FG-181 | medium | main `2ec61f3` | изтекъл срок за приемане — само pull аларма след 24 ч, без напомняне/ескалация | SUSPECTED | open |
| FG-182 | high | main `2ec61f3` | няма AuditEvent за нито един преход на актив; няма Idempotency-Key | SUSPECTED | open |
| FG-183 | high | main `2ec61f3` | отписване/бракуване през PUT без Approval; `take` връща отписан актив в употреба | SUSPECTED | open |
| FG-184 | medium | main `2ec61f3` | hard delete на актив с история (режим off) | SUSPECTED | open |
| FG-185 | medium | main `2ec61f3` | AI оценка на цена става `purchase_price`; снимката е base64, не `file_id` | SUSPECTED | open |
| FG-186 | low | main `2ec61f3` | връщане от ремонт/в склад без приемане; ремонт и движения без проверка на права | SUSPECTED | open |
| FG-187 | medium | main `2ec61f3` | заявка за материал се отменя/„изпълнява“/пренаписва през общ PUT без роля, причина и одит | SUSPECTED | open |
| FG-188 | low | main `2ec61f3` | мобилният API дава на шофьора модул „Доставки“ без бекенд; моделът на снимката е URL, не `file_id` | SUSPECTED | open |
| FG-189 | low | main `2ec61f3` | транспортът в анализа на СМР е мълчалив фиксиран процент (10%) върху материала | SUSPECTED | open |
| FG-190 | medium | main `cd03324` | справките за количества (покритие, фира/„overuse“, статистика) не четат каноничния регистър | SUSPECTED | resolved на #81 `5c0faa5` с уговорка → FG-202 (свързване по име) |
| FG-191 | medium | main `cd03324` | стойността при приемане от доставчик идва от клиента, без сверка с фактурния ред | SUSPECTED | partial (#81 `5c0faa5`: свързано получаване → цената от реда, различна → 422 `service.py:1879-1909`; без ред — цена от клиента с DQ; виж FG-198) |
| FG-192 | high | main `cd03324` | проверката срещу Master артикул в каноничния склад е изключена по подразбиране | SUSPECTED | resolved на #81 `5c0faa5` (още не е в main): `STRICT_MASTER_IDENTITY_DEFAULT=True`, без env флаг (`service.py:653, 684-685`); route подава strict (`warehouse_canonical.py:132`) |
| FG-193 | high | main `cd03324` | `create-sub-project` пренаписва `project_id` на каноничните append-only складови редове извън единствения писател | SUSPECTED | resolved на #81 `5c0faa5` с уговорка → FG-203 (`projects.py:1584-1590` изключва `warehouse_transactions`; скенерът хваща `coll.update_many`) |
| FG-194 | medium | WH-REV-01 `ed8f9e7` | сторното на получаване дава на склададжията право да връща към доставчик (каталогът му го отказва); Accountant не може да сторнира | PROVEN | resolved (#82 `1622f62`, PROVEN в 3 режима: Owner/Admin/Warehousekeeper/Accountant сторнират, другите 403; права `warehouse.reverse_supplier_receipt*`; Р46) |
| FG-195 | medium | WH-REV-01 `ed8f9e7` | сторно + allocate тихо преразпределя ред от вече платена фактура (FG-83 отново достъпно) | PROVEN | resolved поотделно (#81 `c86d161`: allocate/lines на Paid изискват `correction_reason`, версия + AuditEvent; #82 `1622f62`: изисква `reason`, версия + AuditEvent, PROVEN); при сливането двата механизма се конкурират → FG-213 |
| FG-196 | low | WH-REV-01 `ed8f9e7` | сторното не създава очакване за кредитно известие — по Р44 фактурата остава платима в пълен размер | SUSPECTED | resolved (#82 + #84, потвърдено отново в проход 39 на пробното сливане `b0e72cf` × `108afc0` — FG-465) |
| FG-197 | low | WH-REV-01 `ed8f9e7` | основание от един интервал минава при сторно | SUSPECTED | resolved (#82 `1622f62`, PROVEN: `strip()` и 422 `REASON_REQUIRED`, `warehouse_canonical.py:493`) |
| FG-198 | medium | пакет WH-FIX-01 (`2a52fc4`) | т.3 (FG-191) изисква финансова роля за цена на несвързано получаване — против Р32 (склададжията въвежда единична цена при приемане) | SUSPECTED | resolved — по **Р32** (`28b5ab6` L83): складовият работник въвежда единична цена при приемане; пакетът WH-FIX-01 т.3 ще се поправи |
| FG-199 | **blocker** | #81 `5c0faa5`/`dae15da` | header-only разпределена фактура от доставчик се брои в обекта, маха се от „фактури за разпределяне“ и се плаща — против Р45/Р44 | PROVEN | resolved (#81 `c86d161`, PROVEN: header-only → pending, P&L 0, в „за разпределяне“, плащане 409; header 700/500 → 409; header + ред към склад → без разход на обекта; `invoice_allocation.py:182-188, 299-310`, header fallback в `dashboard.py` премахнат) |
| FG-200 | high | #81 `5c0faa5`/`dae15da` | фактури от доставчик, създадени от основния UI, пазят редовете вградени → броят се за разпределени и се плащат (Р44 се заобикаля) | PROVEN | resolved (#81 `c86d161`, PROVEN: вградените редове се четат — без дестинация 409 + DQ; един header проект се записва на всеки ред с AuditEvent → 201; `invoice_allocation.py:97-116, 151-168`, `finance.py:928-937`) |
| FG-201 | medium | #81 `5c0faa5`/`dae15da` | DQ задачата и ескалацията към Собственика по Р44 се обновяват само при четене на списъка; GET пише без AuditEvent | SUSPECTED | partial — дълг по решение на оркестратора (ескалацията се смята при четене, GET не пише; scheduler = дълг) |
| FG-202 | low | #81 `5c0faa5`/`dae15da` | каноничните количества се свързват с планираните/заявените материали по име, не по `item_id` | SUSPECTED | resolved (#81 `c86d161`: свързване по `item_id`, `canonical_material_cost.py:1200-1221`); остатък low: редове от `generate_planned_materials` без `item_id` → 0 (не е регресия) |
| FG-203 | low | #81 `5c0faa5`/`dae15da` | статичният скенер за писатели по каноничния регистър не хваща alias на атрибут и `getattr` | PROVEN | resolved (#81 `c86d161`, PROVEN директно: alias на атрибут и `getattr` се хващат, `legacy_inventory.py:138-172`); остатък low: `getattr(t, CONST)`, alias в скоби, walrus |
| FG-204 | high | main `cd03324` | парите на таблата (P&L на всички обекти, плащания, прогноза, Pulse) се виждат от всяка роля | SUSPECTED | partial — backend затворен с merge на #71 в main `0750d75` (`require_finance_read` на `/org/pnl-overview`, `/projects/{id}/pnl/aggregated`, pending-payments, finance-details, cashflow, morning briefing, pulse; SUSPECTED за този merge — тестовете на #71 бяха PROVEN); остава UI `isManager` в `DashboardPage.js` (SiteManager/Accountant) |
| FG-205 | high | main `cd03324` | cash-flow прогнозата брои задълженията към доставчици като постъпления и започва от 0 | SUSPECTED | partial (#81 `5b08e59` WH81-03: прогнозата брои като „Incoming“ само издадени фактури, `services/cashflow_forecast.py:20`; остава кумулативът от 0 вместо от каса/банка; не е в main) |
| FG-206 | medium | main `cd03324` | формулите на таблото се различават от официалната (`/finance/stats`); Draft/Cancelled влизат; филтрите важат частично | SUSPECTED | open |
| FG-207 | medium | main `cd03324` | Pulse пази snapshot и го показва като текущ; втори списък аларми без статус; GET пише | PROVEN | partial (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`): парите за труд вече от каноничния източник; записаният snapshot още се сервира като текущ (`pulse.py:26-31, 89-105`)) |
| FG-208 | medium | main `cd03324` | алармата няма собственик, срок и действие | SUSPECTED | open |
| FG-209 | medium | main `cd03324` | „видяна“ аларма изпада от броячите; „решена“ с едно кликване от всяка роля, без причина и одит | SUSPECTED | open |
| FG-210 | medium | main `cd03324` | auto-resolve затваря аларми, чието условие още е вярно (заради cooldown) | SUSPECTED | open |
| FG-211 | medium | main `cd03324` | алармите не се оценяват автоматично — само с бутон | SUSPECTED | open |
| FG-212 | low | main `cd03324` | всеки логнат вижда присъствието и болничните на всички служители | SUSPECTED | open |
| FG-213 | medium | #81 `c86d161` + #82 `1622f62` (пробно сливане) | две конкуриращи се корекции на разпределение след сливане на #81 и #82 (две полета, две хранилища на версии, две AuditEvent действия) | PROVEN | resolved (#82 WH-REV-01 `e07320d`, PROVEN: едно поле `correction_reason` (`models/invoice_lines.py:88-90, 129-132`), едно хранилище за версии `invoice_line_allocation_versions` (`routes/invoice_lines.py:714-724, 860-869`), едно действие (`invoice_allocation.py:484-499`); старото `reason` се пренебрегва) |
| FG-214 | medium | #81 `c86d161` + #82 `1622f62` (пробно сливане) | две DQ хранилища: „очаква кредитно известие“ не е в DQ/алармите на #81 | SUSPECTED | resolved (#82 `e07320d` + #84 `b0e72cf`: една DQ задача в `dq_issues` чрез `sync_credit_note_issue`, затваря се от регистрацията на кредитното известие) |
| FG-215 | medium | #81 `c86d161` | издадени (приходни) фактури с проект само в заглавието губят прихода по обект | PROVEN | resolved (#81 `d2fe80b`, PROVEN: издадените фактури са извън Р44/Р45 — приход като на main `4bca18a` (1200), не са в „за разпределяне“, DQ 0, плащане 201; Received без регресия, проби P1–P10 26/26) |
| FG-216 | low | #82 `1622f62` | тестовете на #82 разчитат на мекия Master режим, който #81 премахва | PROVEN | resolved (#82 WH-REV-01 `e07320d`, PROVEN: стриктна главна идентичност (`service.py:679-690`); без `md_item` → 422 `MASTER_IDENTITY_MISSING`, нищо не се записва; тестовете сеят `md_item`) |
| FG-217 | high | #84 `7446d85` | втора чернова на изходяща фактура → 500 (уникален индекс по `invoice_no` хваща null); входяща фактура с наш следващ номер блокира издаването | PROVEN | resolved след миграцията (#84 `2c2e75f`, PROVEN: преди нея 409, не 500; след `apply` старият индекс е премахнат); стъпка в Release Manifest |
| FG-218 | medium | #84 `7446d85` | номерацията засяда завинаги при сблъсък (ръчен номер в автоматичната поредица) | PROVEN | resolved (#84 `71957db`, PROVEN: броячът прескача заетите номера, `invoice_corrections.py:201-214`) |
| FG-219 | low | #84 `7446d85` | входящо кредитно известие с разлика 1 стотинка се приема за съвпадение | PROVEN | resolved (#84 `71957db`, PROVEN: точно равенство в стотинки, `invoice_corrections.py:81`) |
| FG-220 | medium | #84 `7446d85` | входящото известие се сравнява със сбора на всички очаквани, а не се свързва от Счетоводителя с конкретния ред | PROVEN | resolved (#84 `71957db`, PROVEN: изрично `expected_credit_note_ids` от Счетоводителя, без връзка → 422; покриване по ред) |
| FG-221 | medium | #84 `7446d85` | анулиране на официална фактура и смяна на падежа след изпращане — без Approval; падежът и без canonical AuditEvent | PROVEN | resolved по Р51 (1) (#84 `71957db`, PROVEN: предложение + одобрение само от Owner, същият човек → 409, изпратена/платена → 409 `USE_CREDIT_NOTE`; падежът след издаване с причина и AuditEvent); остатък → FG-234 |
| FG-222 | low | #84 `7446d85` | прихващането пази само свободен текст, без правно основание и документ | SUSPECTED | resolved (#84 `71957db`, PROVEN: `legal_basis`, `file_id`, `source_credit_note_id`; сума до неизползваното; между договори → 409); бележка: `file_id` не се проверява във File Registry (дълг, FG-143) |
| FG-223 | medium | #84 `7446d85` | входящо дебитно известие се прилага веднага, без основание и одобрение | PROVEN | resolved по Р51 (2) (#84 `71957db`, PROVEN: основание + `file_id`, pending до одобрение от Owner, плащане над него → 409 `DEBIT_NOTE_NOT_APPROVED` в quick-pay и allocate) |
| FG-224 | medium | #81 `d2fe80b` | `POST material-waste` дава 503 вместо 428 за office ролите; тестът на SEC-01 за PM-01 матрицата е червен | PROVEN | resolved (#81 `ac66058`, PROVEN: `material-waste` без ключ → 428 преди Р27; `test_sec_01…pm01` зелен на реален Mongo; проби fg22 26/26 и fg23 10/10 без регресия) |
| FG-225 | high | #83 CP-01 `ea51030` | плащане към непроверена/сменена сметка все още стига до FLOW-006 през три пътя | PROVEN | resolved (#83 CP-01 `7e0b914`, PROVEN в enforce: quick-pay, `POST /finance/payments` (със и без контрагент), allocate (`routes/finance.py:1970` → `bank_account_guard.py:88-109`), подизпълнители (методът по сметката, `bank_account_guard.py:82-85, 161-162`), other-expense (`finance.py:614-628`), в брой); изключение — плащане в брой без контрагент → FG-242 |
| FG-226 | medium | #83 CP-01 `ea51030` | пълно ЕГН изтича през invoice-details и списъка с обекти | PROVEN | resolved (#83 CP-01 `7e0b914`, PROVEN за 5 роли; в базата се пише маскирано, `routes/projects.py:167, 233, 267-290, 354, 404`) |
| FG-227 | low | #83 CP-01 `ea51030` | търсенето по ЕГН е оракул за всеки логнат; маската в Master Data е различна | PROVEN | resolved (#83 CP-01 `7e0b914`, PROVEN: търсене по ЕГН само за Accountant/Owner, `routes/clients.py:429`; маска `******1234`, `master_data/uniqueness.py:80`) |
| FG-228 | medium | #83 CP-01 `ea51030` | при смяна на IBAN въвелият и проверилият могат да са двамата одобряващи | PROVEN | resolved по Р50 (2) (#83 CP-01 `7e0b914`, PROVEN: въвелият не одобрява, проверилият може да е одобряващ, Admin 403; `routes/bank_accounts.py:300-307`) |
| FG-229 | medium | #83 CP-01 `ea51030` | ЕИК на подизпълнител не се проверява за дубликат | PROVEN | resolved (#83 CP-01 `7e0b914`, PROVEN: дублиран ЕИК подизпълнител↔контрагент → 409 + DQ; `routes/subcontractors.py:62-100`) |
| FG-230 | high | #83 CP-01 `ea51030` | клонът е от `cd03324` и конфликтира с main `4bca18a` (SEC-01); `dq_issues` с различна схема от #81 | PROVEN | resolved (#83 CP-01 `7e0b914`: базата е `4bca18a`, `git merge-tree` с main `8c52e92` без конфликти; DQ схемата е като на #81); остатък → FG-245 |
| FG-231 | medium | #84 `71957db` | два доставчика с еднакъв номер на фактура се отказват (уникалност на ниво фирма, не на издател) | PROVEN | resolved след миграцията по Р53 (1) (#84 `2c2e75f`, PROVEN: друг доставчик със същия номер → 201, същият → 409, 5 паралелни → [201, 409×4]); преди миграцията → FG-264 |
| FG-232 | medium | #84 `71957db` | PUT на чернова с ръчен номер → 500 (KeyError след поправката на FG-217) | PROVEN | resolved (#84 `081f35b`, PROVEN: `routes/finance.py:1088` `invoice.get("invoice_no")`) |
| FG-233 | medium | #84 `71957db` | грешна входяща фактура се анулира, макар да е свързана със складово приемане само по `invoice_id` | PROVEN | resolved (#84 `2c2e75f`, PROVEN: заключване на ниво фактура при приемане само с `invoice_id`, тест за надпревара в 3 режима) |
| FG-234 | low | #84 `71957db` | анулиране предлагат и Admin/Owner; предложение на Owner не може да се одобри при един Owner; висящото не отпада при изпращане | PROVEN | resolved по Р53 (2) (#84 `081f35b`, PROVEN: Owner предлага → 403; Accountant/Admin предлагат, Owner одобрява; висящото → `superseded` при изпращане/плащане; `finance.py:1384-1403, 1485, 1788, 2360`); прихващане → FG-246 |
| FG-235 | low | #84 `71957db` | промяна на `notes` на изпратена фактура без canonical AuditEvent; анулиране на грешна входяща фактура и от Admin/Owner | PROVEN | resolved (#84 `081f35b`, PROVEN: `notes` на изпратена → AuditEvent `finance.invoice.notes_changed`; Owner/Admin не анулират входяща) |
| FG-236 | high | main `8c52e92` | гаранционната работа отива в отделен обект тип „Warranty“; типът се сменя със задна дата | SUSPECTED | resolved по Р54 (1) (#86 PRJ-01 `28fb230`, PROVEN: връзка с AuditEvent, типът заключен, Warranty на всички пътища → 409); остатък → FG-273 |
| FG-237 | high | main `8c52e92` | приключен обект не може да се отвори отново (няма Completed → Active) — изходът за гаранция е нов обект | SUSPECTED | partial (#86 PRJ-01 `abc6fda`: отваряне/пауза/приключване по Р56 и D3 — resolved; маркирането „Гаранционен разход“ по P-09 липсва — PRJ-01-D2) |
| FG-238 | medium | main `8c52e92` | снимка на обекта (доказателство) се трие окончателно заедно с оригиналния файл | SUSPECTED | resolved (#86 PRJ-01 `28fb230`, PROVEN: снимката се скрива; файлът → 404 за Viewer/Technician); остатък low: метаданни със `include_retired=true` за Viewer |
| FG-239 | high | main `8c52e92` | Admin трие окончателно обект с цялата му история (разходи, плащания, снимки, отчети остават сираци) | SUSPECTED | resolved (#86 PRJ-01 `abc6fda`, PROVEN: изтрива се само празна чернова, всеки обект с история → 409 с предложение за архив/отказ) |
| FG-240 | medium | main `8c52e92` | „качество/rework“ на подизпълнител — свободна оценка без права, AuditEvent и история; „платеното“ се въвежда ръчно | SUSPECTED | resolved по Р54 (2) и Р56 (3) (#86 PRJ-01 `28fb230`, PROVEN: пишат SiteManager/Owner/Admin, скала 1–5 (`StrictInt`), „платено“ от ledger-а) |
| FG-241 | high | #83 CP-01 `7e0b914` | приход по банка (`/finance/other-income`) се проверява като изходящо плащане → в enforce (production) приход не може да се запише | PROVEN | resolved (#83 CP-01 `bc0d1c7`, PROVEN: `create_other_income` без guard, `routes/finance.py:672`; приход по банка и в брой → 201 в enforce) |
| FG-242 | medium | #83 CP-01 `7e0b914` | плащане в брой само с име на получателя (без `counterparty_id`) минава без разписка и без блок при висящ IBAN | PROVEN | resolved по Р59 (#83 CP-01 `1e455e3`, PROVEN: име/ЕИК без `counterparty_id` → 422 `COUNTERPARTY_REQUIRED` (`bank_account_guard.py:84-88`); без касов бон → 422; висящ IBAN → 409); остатък без получател → FG-290..292 |
| FG-243 | medium | #83 CP-01 `7e0b914` | висяща смяна на IBAN оцелява при архивиране и след връщането се активира без нова проверка | PROVEN | resolved (#83 CP-01 `bc0d1c7`, PROVEN: при връщане от архив висящата смяна се нулира, `master_records.py:250`; второ одобрение → 409) |
| FG-244 | low | #83 CP-01 `7e0b914` | подизпълнителите нямат „неактивен“/„архивиран“ | PROVEN | resolved (#83 CP-01 `bc0d1c7`, PROVEN: lifecycle маршрути за подизпълнители, `routes/subcontractors.py:112-127`) |
| FG-245 | medium | #83 CP-01 `7e0b914` | пълен IBAN през legacy полета и фактури за Viewer/SiteManager/Admin; `dq_issues` с две семейства след сливане с #81 | PROVEN | resolved за `dq_issues` — една регистрация в FAMILY_TASKS и в #83 (#83 CP-01 `7750f4e`, `ownership.py:129-132`) и в #84; двете форми на записа → FG-450; Р47 задачата → FG-214 |
| FG-246 | high | #84 `081f35b` | издадена фактура с одобрено прихващане се анулира — кредитното салдо на клиента изчезва | PROVEN | resolved (#84 `2c2e75f`, PROVEN: прихващане блокира анулирането (`routes/finance.py:1462-1466`), одобреното прихващане отменя висящото предложение (`routes/invoice_corrections.py:669-670`); надпревара: прихващането печели, анулирането 409) |
| FG-247 | medium | #84 `081f35b` | ефектът на входящо кредитно известие върху разхода е грешен и е само в P&L (отрицателен разход; другите справки и ДДС не се променят) | PROVEN | partial (#84 `2c2e75f`, PROVEN за Path B: без отрицателен разход, P&L и `project_material_cost` съвпадат, период по `issue_date`, ДДС коригиран, кредит над остатъка → 409; за ред, приет в склада, кредитът не коригира FIFO слоя — дълг, SUSPECTED) |
| FG-248 | medium | #84 `081f35b` | преди миграцията същият доставчик с по-рано въведена фактура се дублира | PROVEN | resolved за последователни заявки (#84 `2c2e75f`, PROVEN: стари редове — проверка по ЕИК/контрагент/име, `services/invoice_corrections.py:226-251`); паралелни → FG-264 |
| FG-249 | medium | #84 `081f35b` | PUT, който сменя само ЕИК на доставчика и създава дубликат → 500; същият доставчик с ЕИК и само с име не се хваща | PROVEN | resolved по Р55 (1) (#84 `2c2e75f`, PROVEN: без ЕИК → 422, чуждестранен данъчен номер → 201, PUT с дубликат → 409 (не 500), заключена → 409); бележка: DQ за старите без ЕИК е само поле върху фактурата, не каноничен DQ запис |
| FG-250 | low | #84 `081f35b` | Owner сам регистрира несъвпадащо входящо известие и сам приема разликата | PROVEN | resolved по Р55 (2) (#84 `2c2e75f`, PROVEN: регистрира само Accountant, приема само Owner, регистриралият ≠ приемащият) |
| FG-251 | low | #84 `081f35b` | приетата разлика по известие, свързано със сторно, не се осчетоводява никъде | SUSPECTED | partial по Р55 (3) (#84 `2c2e75f`, PROVEN за ред на обекта: +5 нето в периода на приемането, ДДС, AuditEvent); за ред, приет в склада → FG-265 |
| FG-252 | high | #86 PRJ-01 `0bd77a1` | `create-sub-project`, `wrap-in-group` и `add-subproject` създават нови обекти тип Warranty (типът се наследява от родителя) | PROVEN | resolved (#86 PRJ-01 `28fb230`, PROVEN: подобект/wrap/add на Warranty → 409 `WARRANTY_IN_ORIGINAL_PROJECT`, `projects.py:1834, 2055, 2153`) |
| FG-253 | medium | #86 PRJ-01 `0bd77a1` | свързан стар Warranty обект може да се отвори отново и пак да приема записи | PROVEN | resolved (#86 PRJ-01 `28fb230`, PROVEN: отваряне/искане за стар Warranty → 409 с `original_project_id`, `projects.py:451, 549`) |
| FG-254 | high | #86 PRJ-01 `0bd77a1` | обект с файл, качен през `/api/media/upload` (`context_type`/`context_id`), се изтрива като „празна чернова“ | PROVEN | resolved за media/QR (#86 PRJ-01 `28fb230`, PROVEN: `project_lifecycle.py:29-43, 106-115`); нова дупка → FG-272 |
| FG-255 | medium | #86 PRJ-01 `0bd77a1` | изчисленото „платено“ на подизпълнител се вижда от всяка роля | PROVEN | resolved (#86 PRJ-01 `28fb230`, PROVEN: `@strip_money_for_non_finance`; Viewer/Technician/SiteManager без пари; бележка: Accountant няма достъп до `/log`) |
| FG-256 | low | #86 PRJ-01 `0bd77a1` | PUT без приети полета създава празна версия; DQ задачата за неопределим оригинал остава отворена след `--map`; „платено“ брои само `subcontractor_payments` | PROVEN | partial (#86 PRJ-01 `abc6fda`, PROVEN: празен PUT → 422, DQ се затваря при свързване; „платено“ още през `subcontractor_payments.id` — чака решение на Крум за каноничния ключ) |
| FG-257 | high | main `ec7ddd8` | статусът при създаване не минава през таблицата на преходите; чернова без клиент става Активна | SUSPECTED | open |
| FG-258 | high | main `ec7ddd8` | клиентът се маха от Активен обект без AuditEvent | SUSPECTED | open |
| FG-259 | high | main `ec7ddd8` | пауза/възобновяване и приключване са само смяна на поле — без данните на P-04A и проверките на P-10 | SUSPECTED | open |
| FG-260 | medium | main `ec7ddd8` | платецът не е отделна страна; получателят на фактурата се попълва от клиента | SUSPECTED | open |
| FG-261 | high | main `ec7ddd8` | wrap-in-group/add-subproject създават директно Активни подобекти — без членство, без AuditEvent, и под приключен обект | SUSPECTED | open |
| FG-262 | high | main `ec7ddd8` | архивираните/приключените обекти и подобектите изпадат от финансовите суми на фирмата | SUSPECTED | open |
| FG-263 | medium | main `ec7ddd8` | използвано ниво от структурата се изтрива; промените по нивата са без AuditEvent | SUSPECTED | open |
| FG-264 | medium | #84 `2c2e75f` | уникалният индекс по доставчик се строи само от ръчния migrate скрипт — без него паралелни входящи дубликати минават (и за нови tenant-и) | PROVEN | resolved (#84 `caea933`, PROVEN: индексът при стартиране и в `ensure_indexes`; заключване (доставчик, номер) в транзакция при създаване и PUT — нов tenant без скрипта: 6 паралелни → [201, 409×5]; стара база с конфликти — без 500, миграцията работи) |
| FG-265 | low | #84 `2c2e75f` | приетата разлика по ред, приет в склада (сторно по #82), не се записва никъде | SUSPECTED | partial по **Р58** (#84 `caea933`, PROVEN: складов ред → фирмен разход в периода с AuditEvent, FIFO непроменен, задължението се преизчислява); грешна класификация → FG-269, FG-270; не е във фирмения резултат → FG-271; стара приемка без ledger ред остава без разход (low, SUSPECTED) |
| FG-266 | medium | #83 CP-01 `bc0d1c7` | пълно ЕГН (въведено, несъвпадащо с лицето) в legacy одита и в отговора при създаване на обект | PROVEN | resolved (#83 CP-01 `9f86d0b`, PROVEN: маскиране в `audit_logs` (`projects.py:396-397`, `cr.mask_for_log`), в отговора при създаване (`:248-250`), в AuditEvent и при четене на стари редове; бележка low: маскират се само ключовете `eik`/`egn`/`tax_id`) |
| FG-267 | medium | #83 CP-01 `bc0d1c7` | 10-цифрено ЕГН в `invoice_details.eik` без собственик или с фирма-собственик се показва изцяло на Admin | PROVEN | open — Krum decision (#83 CP-01 `1e455e3`: кодът прилага неодобрено правило — `projects.py:271-277` `_company_confirmed` показва 10-цифрения номер изцяло на всички роли, ако собственикът е фирма на tenant-а; `counterparty_rules.py:122-126`; решение на Крум не е открито в канона) |
| FG-268 | low | #83 CP-01 `bc0d1c7` | блокът за плащане в брой по Р50 (1) се заобикаля с вариант на името или ЕИК в тялото | PROVEN | resolved за заобикалянето с име/ЕИК (#83 CP-01 `1e455e3`, PROVEN: `bank_account_guard.py:84-103, 197-204`; всички пътища в `finance.py:621,1353,1839,1968`, `subcontractors.py:631` минават през проверката); пътят без получател → FG-290, FG-291, FG-292; `/advances` → FG-293 |
| FG-269 | medium | #84 `caea933` | директна доставка до обект се третира като „приета в склада“ — приетата разлика става фирмен разход вместо разход на обекта | PROVEN | resolved (#84 `e75b558`, PROVEN: класификация по ред `services/invoice_corrections.py:948-986`; директна доставка → разход на обекта (prj-2 +5.0), фирмена загуба 0) |
| FG-270 | medium | #84 `caea933` | едно складово приемане, вързано само към фактурата, прави всички редове на фактурата фирмен разход | PROVEN | resolved (#84 `e75b558`, PROVEN: приемане само по фактура не прекласифицира ред; ред с разпределение остава на обекта; без разпределение → DQ (→ FG-277)) |
| FG-271 | medium | #84 `caea933` | фирменият разход по Р58 не влиза в нито една справка за фирмения резултат | PROVEN | partial (#84 `cdd3dc8`: заглавието на атрибуцията, картата „Печалба (краен фирмен резултат)“ и плочката „Текущ фирмен резултат“ — направени, jest 4/4; остава изгледът за складови загуби по FLOW-009 (D18, дълг)) |
| FG-272 | high | #86 PRJ-01 `28fb230` | чернова с ред от входяща фактура, разпределен към нея само чрез `allocations[].ref_id`, се изтрива — редът остава сирак | PROVEN | open (#86 PRJ-01 `dbb04ba`, PROVEN: `GENERIC_DEPTH = 4` (`project_lifecycle.py:45`); `rows[].splits[].target` и 5 вложени нива → DELETE 200, tombstone) |
| FG-273 | medium | #86 PRJ-01 `28fb230` | стар Warranty обект, чийто оригинал е подобект, не може да се свърже — DQ задачата само ескалира; свързването после тихо преименува кода му | PROVEN | resolved по Р60 (#86 PRJ-01 `abc6fda`, PROVEN: свързване към подобекта (вкл. `--map`), кодът не се сменя, AuditEvent `project.warranty_link`; смяна на код при create-sub-project → `project.code_change` с before/after; разходите се сумират в `/pnl/aggregated` на подобекта и на корена); пробиви → FG-279, FG-280 |
| FG-274 | low | #86 PRJ-01 `28fb230` | проверката за история пуска пълно сканиране на всички колекции в една транзакция | SUSPECTED | partial (#86 PRJ-01 `dbb04ba`, PROVEN: rollback при грешка в AuditEvent; празна чернова → tombstone `status=deleted` + `project.delete`; използвана чернова → 409 `PROJECT_HAS_HISTORY`; остатък → FG-300, FG-301) |
| FG-275 | medium | #83 CP-01 `9f86d0b` | пълно ЕГН се показва на Owner/Accountant в обикновени четения без AuditEvent | PROVEN | resolved (#83 CP-01 `1e455e3`, PROVEN: `projects.py:168,249,267,311-321,410` маскират за всички роли; разкриване само Owner/Accountant (200), Admin/Viewer 403; всяко разкриване → canonical AuditEvent `person.egn.revealed` без пълното ЕГН); фактурите → FG-294 |
| FG-276 | low | #84 `ef7cddd` | приета разлика (фирмен разход) няма път за сторно/корекция | PROVEN | resolved (#84 `cdd3dc8`, PROVEN: `POST /finance/credit-notes/{id}/reverse-difference` (`routes/invoice_corrections.py:540-575`, `_difference_write` `:449-478`) — транзакция + CAS върху добавящ се дневник, Idempotency-Key (428 без), canonical AuditEvent `finance.credit_note.difference_reversed`; само Owner (Accountant/Admin 403); старите записи непроменени, нов −5.00 в периода на сторното; DQ към Счетоводителя; повторно → 409); пренасочването след сторно → FG-281 |
| FG-277 | medium | #84 `e75b558` | ред с неопределен вид (`undetermined`) не се осчетоводява никъде; DQ задачата няма изход | PROVEN | resolved (#84 `cdd3dc8`, PROVEN: `POST …/difference-lines/{line_id}/resolve` (`invoice_corrections.py:481-537`), Owner/Admin/Accountant; осчетоводява се в периода на приемането (Р58); DQ задачата се затваря с `closed_by`; AuditEvent; повторно → 409; Viewer/SiteManager 403) |
| FG-278 | low | #84 `e75b558` | фирмените загуби са за цялото време, а сумите на обектите — само за активни статуси; крайният резултат смесва обхвати | PROVEN | partial (#84 `5242cba`, PROVEN: двата четеца броят всички обекти от всички статуси (`services/pnl_aggregator.py:85-102`, `routes/project_pnl.py:92-96, 129`) — Completed/Archived/Cancelled/Finished + подобект → еднакви 1000/500/500/0/500, без двойно броене; остава: `scope` е само поле в API, никой екран не показва какво е включено (FLOW-024 L180); таблото P&L вече показва и Draft/Cancelled/Archived) |
| FG-279 | medium | #86 PRJ-01 `abc6fda` | `PUT /projects/{id}` сменя `parent_project_id` без проверка и без AuditEvent — заобикаля Р60 | PROVEN | resolved (#86 PRJ-01 `8e8be48`/`24ffe07`, PROVEN: PUT с друг родител → 409 `PARENT_CHANGE_NOT_ALLOWED` (`routes/projects.py:291-301`) — 4 опита, родителят непроменен; същата стойност/`null` → no-op; wrap-in-group прехвърля с CAS и `project.parent_change` в транзакция (`:2153-2166`); всички писатели на `parent_project_id` проверени); стари данни → FG-304; липсваща команда за преместване → FG-305 |
| FG-280 | medium | #86 PRJ-01 `abc6fda` | агрегатът на обекта и складът гледат само едно ниво — гаранцията на второ ниво не стига до корена | PROVEN | resolved (#86 PRJ-01 `8e8be48`, PROVEN: R → S → W (гаранция) и R → S2; `/aggregate` на R = 1211.0 (S = 1111.0), равно на `/pnl/aggregated`; `_project_buckets(R)` = [R, S, S2, W]; две нива, второто само за Warranty — по Р60; `resolve_subproject_parent` връща S — правилно) |
| FG-281 | medium | #84 `cdd3dc8` | след сторно на приета разлика редът се преосчетоводява където и да е (друг обект, фирмен разход, приключен обект) от един човек — заобикаля Р55 (2)/(3) и Р58 | PROVEN | resolved по Р63 (#84 `5242cba`, PROVEN: към друго място → предложение без осчетоводяване + AuditEvent; същото място → веднага, `difference_line_resolved`; одобрява само Owner, различен от предлагащия (`SAME_PERSON_APPROVAL` 403); Accountant/Admin 403; без ключ 428; повторно 409; паралелно — едно осчетоводяване (`routes/invoice_corrections.py:449-484, 519-542, 578-639`)); статусите → FG-415 / Q009 |
| FG-282 | medium | main `3699c3b` | приходът на обекта брои и входящи (`Received`) фактури с `project_id` — печалбата и `final_profit` се надуват | PROVEN | resolved (#84 `f6e0c90`, PROVEN: `services/project_pnl.py:29-31` — приход само от Issued; пробата: 200, не 400) |
| FG-290 | medium | #83 CP-01 `1e455e3` | касовият бон (`file_id`) не се проверява във File Registry — приема се всеки низ | PROVEN | partial (#83 CP-01 `4929451`, PROVEN: измислено id, чужд tenant, изтрит/архивиран файл → 422 `CASH_RECEIPT_NOT_REGISTERED`, нищо не се записва; собствен файл → 201 (`bank_account_guard.py:77-95, 119, 135`)); остатък → FG-425, FG-426 |
| FG-291 | medium | #83 CP-01 `1e455e3` | разход „без получател“ може да назове получателя (и пълно ЕГН) в свободен текст; няма категория и лимит | PROVEN | open — Krum decision (какво е „малък разход“); проход 37 (#83 `4929451`): PROVEN отново |
| FG-292 | low | #83 CP-01 `1e455e3` | бързо плащане в брой на входяща фактура без контрагент минава като разход без получател | PROVEN | open; проход 37 (#83 `4929451`): PROVEN отново; проход 38 (#83 CP-01 `7750f4e`): PROVEN отново — напълно разпределена входяща фактура без контрагент, бързо плащане в брой → 201 (Р44 спира само неразпределената) |
| FG-293 | medium | main `3699c3b` | заем/аванс в брой към външно лице по свободен текст (`/advances`) заобикаля Р59 и Р50 (1) | PROVEN | open — Krum decision (покрива ли Р59 авансите) |
| FG-294 | medium | #83 CP-01 `1e455e3` | издадена фактура с 10-цифрено ЕГН в `counterparty_eik` се връща изцяло на Admin (срещу Р48.3) и на Owner без AuditEvent | PROVEN | partial (#83 CP-01 `4929451`, PROVEN: `counterparty_eik` е `******1234` за всички роли в списък, детайл, версии и `/clients/{id}/invoices`; разкриване само Owner/Accountant (Viewer/SiteManager/Admin 403) с canonical `invoice.egn.revealed` без пълното ЕГН (`finance.py:1034-1062`)); остатък — PDF → FG-428, ДДС номер BG+ЕГН → FG-429 |
| FG-300 | low | #86 PRJ-01 `dbb04ba` | състезание в транзакцията за изтриване — оферта, вмъкната след повторната проверка, остава към tombstone | PROVEN | open (#86 `8e8be48`, PROVEN отново: `orphan_offer = 1`) |
| FG-301 | low | #86 PRJ-01 `dbb04ba` | пълното сканиране за история се пуска два пъти (извън и в транзакцията) при всяко DELETE | PROVEN | open (#86 `8e8be48`, PROVEN отново: `scan_calls = {none: 1, txn: 1}`) |
| FG-302 | low | #86 PRJ-01 `dbb04ba` | tombstone-ите се връщат в `TenantData.lookup`, тихо се пропускат от `update_many`/`delete_many`; няма път за възстановяване | SUSPECTED | open (#86 `8e8be48`: `TenantData.lookup("projects")` връща tombstone — PROVEN като механизъм, днес няма такова извикване; масовите пътища и възстановяването — SUSPECTED) |
| FG-303 | low | #86 PRJ-01 `8e8be48` | wrap-in-group създава групата извън транзакцията на прехвърлянето — при загуба остава група-сирак без AuditEvent | PROVEN | open |
| FG-304 | medium | main (код от 28.06.2026; виж `3699c3b`, `ea57121`) | PUT е позволявал смяна на `parent_project_id` без проверки — реални данни може да имат негаранционно второ ниво или цикъл, които не се обобщават | PROVEN (ефект) / SUSPECTED (данни) | open (+ Krum: вдигане или обобщаване) |
| FG-305 | low | #86 PRJ-01 `8e8be48` | няма команда за поставяне на съществуващ обект под друг корен/група или за обединяване на нива (P-06 „обедини“) | SUSPECTED | open — Krum decision |
| FG-310 | low | #81 `a7166d4` (merge `fdfad135`) | сливането на main запази остарели evidence файлове (PM-01 run_meta, SEC-01/C01/C02/C03 results) — 2 теста за evidence са червени само на #81 | PROVEN | resolved (#81 `72e7e87`, PROVEN: само evidence файлове, регенерирани от harness-ите (PM-01, SEC-01/C01/C02/C03, SEC-02); двата теста `test_the_committed_evidence_satisfies_the_package` минават; всички 5 evidence теста — 5 passed) |
| FG-315 | medium | PWA-01 `a05167a` | локалните данни са по tenant, не по потребител; изходът/401 трие всичко без предупреждение — основа, която противоречи на Р61 (5) за PWA-02 | PROVEN | open (дълг за PWA-02) |
| FG-316 | low | PWA-01 `a05167a` | изчистването не покрива IndexedDB, бисквитки и HTTP кеша | PROVEN | open |
| FG-317 | medium | PWA-01 `a05167a` | външни скриптове с запис на сесията (PostHog `session_recording`) са в инсталираното приложение — могат да запишат ЕГН/IBAN/суми | PROVEN | partial по Р68 (#88 PWA-01 `d59bcca`, PROVEN: PostHog без session recording (`analytics.js:30, 46-49`), без autocapture/heatmaps/rageclick/exceptions, маскиран текст, без identify, само `error_kind`, ключ от env, URL без query/hash; Playwright: само `array.js`, `/decide`, `/e/`); остава (SUSPECTED, Krum): `emergent-main.js` (`index.html:35`) на всяка страница; бисквитката `ph_*` оцелява при изчистването; токенът на линка → FG-470; проход 40 (#88 `62f898a` / `30206f63`, PWA88-N1): posthog-js 1.200.0 е вграден в bundle-а — без външен `array.js`, без `/decide`, без remote config/surveys/site apps/experiments (jest + evidence 18/18); остава `emergent-main.js` (`index.html`) — потвърдено и от SEC-SCAN 2026-11-09 H-1 (клон `claude/sec-scan`), Krum; решено от Крум по Р75 (09.11.2026): скриптовете и надписът на Emergent се махат — пакет SEC-03; проход 42 (#90 SEC-03 `bc52843`): остатъкът от Emergent е махнат на клона (production build — само собственият bundle; без emergent в index.html и JS) — resolved след merge/deploy и подмяна на живия nginx.conf; PostHog — чака #88 |
| FG-318 | low | PWA-01 `a05167a` | `/api` и `/uploads` нямат `Cache-Control: no-store`; e2e mock-ът го добавя и скрива липсата | SUSPECTED | open |
| FG-319 | low | PWA-01 `a05167a` | презареждане без интернет губи сесията (токенът се трие при мрежова грешка) | PROVEN | resolved (PWA-01 #88 `7c284fa` / `e571b06`, PROVEN по код + jest `AuthContext.offline.test.js`: токенът се трие само при 401 или 403 от `/auth/me` (`AuthContext.js` `sessionRejected`); при мрежова грешка/5xx потребителят идва от `bw_user`, нищо от `/api` не се кешира; блокирано устройство (Р61 (6)) получава 401/403 и сесията приключва) |
| FG-320 | low | PWA-01 `a05167a` | версията на service worker-а не е версията на работещата страница; другите табове се поемат без презареждане | PROVEN | open |
| FG-321 | low | PWA-01 `a05167a` | сесията на платформения админ (`bw_platform_token`) оцелява при изход/401/смяна на tenant | PROVEN | open — Krum decision |
| FG-325 | high | main `3699c3b` | AI измисля цена на труда без данни, без източник и дата; цената стига до офертата | PROVEN | open |
| FG-326 | high | main `3699c3b` | `ai-suggest` / `fetch-prices` презаписват цената на одобрен анализ — от всяка роля, без потвърждение и AuditEvent | PROVEN | open |
| FG-327 | high | main `3699c3b` | партидните AI ценови пътища показват цени, ставки и вътрешната подсказка на роли без пари | PROVEN | open |
| FG-328 | high | main `3699c3b` | AI цената е в лева, ставките и офертата — в евро; няма валута и ДДС | SUSPECTED (частично PROVEN) | open |
| FG-329 | medium | main `3699c3b` | вътрешната ценова подсказка смесва стари, недатирани и чужди за града данни и труд с труд+материали | PROVEN | open |
| FG-330 | medium | main `3699c3b` | импортът на исторически цени приема цена без дата, източник, валута и тип; без AuditEvent | PROVEN | open |
| FG-331 | medium | main `3699c3b` | часовите ставки и AI коефициентите се презаписват и изтриват без история и AuditEvent | PROVEN | open (+ Krum: D-17 срещу Р41) |
| FG-332 | medium | main `3699c3b` | калибрацията прилага един коефициент към труд и материал и пренася коефициент от друг град | PROVEN | open |
| FG-333 | medium | main `3699c3b` | скрити коефициенти (град, малко количество) и DEMO ставки влизат в цената без източник | PROVEN | open (+ Krum: кои условия) |
| FG-334 | low | main `3699c3b` | редовете на офертата/анализа не пазят произхода на цената | SUSPECTED | open |
| FG-335 | low | main `3699c3b` | `record-edit` приема произволни калибрационни събития от всяка роля с M2 | SUSPECTED | open |
| FG-340 | high | #73 LAB-01 `7ee87f8` (+ main) | един обект — три различни трудови разхода: P&L (LAB-01) 850, `project-profit` 150/600, `project-net-profit` 600; пакетите и бюджетите четат `labor_entries` | PROVEN | resolved по Р62 (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`), PROVEN: всички четци на общия труд по обект = `project_labor_cost` при 850 → 900 → 950 → 1190 → 1110 → 1270); остатъчни четци по дейност/сесии → FG-460, FG-461, FG-462 |
| FG-341 | low | #75 LAB-02 `5809367` | паричните пътища на LAB-02 (`labor-terms`, approve/classify, pending) са с твърди списъци роли, извън SEC-01/SEC-02 каталозите и `require_m2` | SUSPECTED | open (дълг) |
| FG-350 | medium | OFF-01 #79 `f526182` (+ main) | `POST /offers/{id}/new-version`, `POST /versions/{n}/restore` и `PUT /offers/{id}/lines` връщат клиентски цени на Технически ръководител | PROVEN | resolved по Р67 (OFF-02 `56913a4`, PROVEN: всичките 18 пишещи пътя по оферти — `require_money_write("offers.…")` като първа зависимост (`catalog.py:109-130, 244-265`, Accountant `:390`); останалите роли 403 в off/shadow/enforce; изрязване на парите на 12 пътя (`finance_read.py:278-291`); клиентският линк приема/отказва); коментарът на ТР → FG-471 |
| FG-351 | low | main `ea57121` (и OFF-01) | отварянето на клиентския линк не записва AuditEvent (само първо гледане в `offer_events`; 410 — нищо) | PROVEN | open |
| FG-352 | low | OFF-01 #79 `f526182` | evidence README спира на `5675e17`; сливането с `ea57121` (промени в harness-а) не е документирано | PROVEN | resolved (OFF-01 #79 `25c9ae8`, PROVEN: `docs/evidence/OFF-01-MAIN-MERGE/test_summary.txt` + `warehouse_suite.txt` — гейтовете на сливането с `ea57121`: OFF-01 237, ACT-01 113, PM-01 6, PAY 630, SEC-01 30, SEC-02 31, склад 1121 (= main), W0 16 failed = същите като базата на main) |
| FG-355 | high | main `ea57121` | анализът на цената се пише, одобрява, заключва и превръща в оферта от всяка роля с M2; връща себестойност/надценка; без AuditEvent | PROVEN | partial (OFF-02 `56913a4`: `to-offer` вече под Р67; остават: редове/одобрение/заключване/bulk на анализа само с `require_m2` (`smr_analysis.py:264, 300, 331, 439, 462, 481, 747, 777`), отговорите не се изрязват, без AuditEvent, to-offer от неодобрен анализ) |
| FG-356 | medium | main `ea57121` | одобреният анализ се редактира, умножава и редовете му се трият, а статусът остава `approved` | PROVEN | open |
| FG-357 | high | main `ea57121` | офертата от анализа показва на клиента себестойността като ед. цена и надценката/риска в бележката | PROVEN (main), SUSPECTED (OFF-01) | open |
| FG-358 | high | main `ea57121` | повторен запис на офертата от анализ тихо маха надценката и риска (1950 → 1500) | PROVEN | open |
| FG-359 | medium | main `ea57121` | отрицателна надценка → цена под себестойността без предупреждение; няма отстъпка с видим ефект | PROVEN | open (+ Krum: праг за Approval) |
| FG-360 | medium | main `ea57121` | `ai-breakdown` пише AI/измислена 60/40 разбивка в заключен анализ от всяка логната роля, без AuditEvent | PROVEN | open |
| FG-361 | high | main `ea57121` | „агентите“ за цени на материали симулират магазини (случайни цени, измислени URL) като проверени източници; BGN | PROVEN | open (+ Krum: демо или махане) |
| FG-362 | medium | main `ea57121` | `POST /pricing/batch` връща цени на материали на роли без пари | PROVEN | open |
| FG-363 | medium | main `ea57121` | Work Packages и планирани материали от неприета/отказана оферта, от всяка роля с M2 | PROVEN | open |
| FG-364 | low | main `ea57121` | анализът няма валута, ДДС режим и дата на цената; мостовете слагат EUR/BGN по подразбиране различно | SUSPECTED (частично PROVEN) | open |
| FG-370 | medium | main `ea57121` | амортизацията на актив се брои преди покупката и след края на полезния живот (3022.59 € за актив за 1000 €, още некупен) | PROVEN | open |
| FG-371 | high | main `ea57121` | фирменият overhead е в 4 регистъра (`overhead_costs`, `overhead_transactions`, `fixed_expenses`, ръчни `/overhead-snapshots`) с различни четци — обектите четат M9, фирмата M5 | PROVEN | open |
| FG-372 | medium | main `ea57121` | неразпределеният остатък (200 от 1000) и разход след разпределението не се виждат никъде, без етикет и аларма; късният разход не може да се архивира (409) | PROVEN | open |
| FG-373 | medium | main `ea57121` | fully loaded без разпределение показва оценка от `fixed_expenses` за текущия месец със скрит 30% коефициент като `overhead_allocation`, без етикет и предупреждение | PROVEN | open |
| FG-374 | medium | main `ea57121` | разход/категория/актив и `fixed-expenses` без Idempotency-Key и canonical AuditEvent; отрицателна сума и BGN се сумират (snapshot −8981.52) | PROVEN | open |
| FG-375 | low | main `ea57121` | разпределението няма одобрено правило; `allocation_type`/`frequency` се пренебрегват; няма обектов overhead; часовете включват неодобрени отчети | SUSPECTED | open |
| FG-376 | low | main `ea57121` | ръчно `actual_overhead_cost` на пакета (PUT под read gate, без AuditEvent) дава втори марж спрямо OH-01 дела | SUSPECTED | open |
| FG-385 | medium | main `ea57121` | дедупликацията е само cooldown: след 24 ч същият източник получава втора активна аларма; без първа/последна дата и брой | PROVEN | open |
| FG-386 | medium | main `ea57121` | правилата се трият твърдо (събитията остават с висящ `rule_id`), промени без версия и AuditEvent; приемат се непознати тип/тежест/cooldown | PROVEN | open |
| FG-387 | medium | main `ea57121` | „потвърждаване“ връща решена аларма в `acknowledged`; преходите не се проверяват, нямат история и AuditEvent | PROVEN | open |
| FG-388 | low | main `ea57121` | 3 нива вместо 5, няма „Блокиращо“; `severity:"blocking"` се приема, но не влиза в броячите | PROVEN | open |
| FG-389 | medium | main `ea57121` | няма финансова група аларми (кеш, просрочия, аванс, ретенция, Р44) и централен каталог; 8+ паралелни списъка с предупреждения без статус | PROVEN | open |
| FG-390 | medium | main `ea57121` | бюджетната аларма смята „изхарчено“ от `work_sessions` (без одобрение, вкл. Draft обекти), не по Р31 | PROVEN | resolved за двигателя на алармите (#73 `a97db46`, PROVEN: `alarm_engine.py:66-69` чете `project_labor_cost`); остават Draft обектите (`:56-58`) и прогресът (`:78-81`); брифингът и Pulse → FG-207, FG-421 |
| FG-391 | medium | main `ea57121` | алармите нямат обхват по обекти: SiteManager/Technician/Viewer виждат бюджетната тежест на всички обекти и извънредния труд по име | PROVEN | open (+ Krum decision) |
| FG-392 | low | main `ea57121` | `notify_roles` никой не чете; няма push / Action Inbox / Daily Digest за аларми | PROVEN | open |
| FG-393 | low | main `ea57121` | няма причинно-следствени вериги, финансов ефект и разлика прогноза/факт | SUSPECTED | open |
| FG-400 | high | main `ea57121` | документалният контрол по FLOW-025 не е реализиран (тип, семейство, Current, requirement snapshot, подпис, валидност, checklist) | PROVEN | open |
| FG-401 | high | main `ea57121` | изходяща фактура се издава без одобрен акт и без договорна база (на #84 — само при `act_id`) | PROVEN | open |
| FG-402 | high | main `ea57121` | входяща фактура става платима и се плаща изцяло без потвърдено получаване на стоката/услугата | PROVEN | open |
| FG-403 | high | main `ea57121` | изходящо плащане без одобрение по лимит — един Счетоводител плаща 60 000 | PROVEN | open |
| FG-404 | medium | main `ea57121` | OCR качването дава 500 (`extract_invoice_text` без `tenant`); файлът и медията остават сираци | PROVEN | open |
| FG-405 | high | main `ea57121` | OCR intake: наблюдател пренаписва сумата и отказва одобрен intake; 5 паралелни approve → 5 разхода; без дубликат и AuditEvent | PROVEN | open |
| FG-406 | medium | main `ea57121` | Р20: наблюдателят вижда сумите и суровия текст на OCR, сумата на фактурата зад скана и чакащите разходи | PROVEN | open |
| FG-407 | medium | main `ea57121` | `pending_expenses`: SiteManager одобрява, отказан → одобрен, без одит; одобреното не стига до официален запис | PROVEN | open (+ Krum decision) |
| FG-408 | low | main `ea57121` | сканове: PUT пренасочва към несъществуваща фактура, unlink/PUT/delete без AuditEvent, `file_url` вместо `file_id` | PROVEN | open |
| FG-409 | high | main `ea57121` | restore на стара версия презаписва приета оферта; версия на използвана оферта се трие окончателно (поправено на #79) | PROVEN | resolved (main `44e8d97` — merge #79 OFF-01 `25c9ae8`: `_refuse_if_used` (OFF79-01) спира restore върху използвана оферта и изтриване на версия; дървото на сливането = `git merge-tree ea57121 25c9ae8`) |
| FG-415 | low | #84 `5242cba` | праг „Completed“ при новото разнасяне не е в Р63 и се прилага неравно (само при подаден project id; не при връщане към разпределение, неопределен ред и одобрение; Archived/Cancelled/Finished — без праг) | PROVEN | resolved по Р64 (#84 `f6e0c90`, PROVEN: `OPEN_PROJECT_STATUSES = ("Active", "Paused")` (`services/invoice_corrections.py:1000`); извън тях — предложение, одобрява Owner ≠ предлагащия (Admin/Accountant/предлагащ 403); статусът се чете отново и се записва при одобрението (`routes/invoice_corrections.py:530-548, 608-628`)); остатък → FG-451 и въпроси към Крум (Stopped/Overhead/Draft/неопределен ред) |
| FG-416 | low | #84 `5242cba` | отпечатъкът за идемпотентност при одобрение е само note id + proposal id — същият ключ с друг коментар връща записаното 200 и губи коментара | PROVEN | resolved (#84 `f6e0c90`, PROVEN: същият ключ с друг коментар → 409 `IDEMPOTENCY_KEY_REUSED`, едно решение (`:628`)) |
| FG-417 | low | #84 `5242cba` | фирменият резултат се реже на 500 обекта без флаг; новият обхват (всички статуси + подобекти) стига прага по-рано | SUSPECTED | open |
| FG-420 | high | #73 LAB-01 `a97db46` (+ main) | финансови справки извън `project_labor_cost`: `/labor-cost/by-project` (всички `work_reports` вкл. Draft), `/profit-by-period` (pending ръчни редове), кеширани `actual_*_cost` на пакетите | PROVEN | resolved (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`), PROVEN: `/labor-cost/by-project`, `/profit-by-period` (без pending), пакетите (дял от числото) — равни на `project_labor_cost`) |
| FG-421 | high | #73 LAB-01 `a97db46` (+ main) | справки, които още четат `work_sessions` или черновите: activity_budgets, project_financial_results, centralized_reports („Include BOTH draft AND approved costs“), morning_briefing, projects | PROVEN | resolved (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`), PROVEN: activity-budget-summary, activities-overview, expected-actual, financial-results, Pulse, централизираната сума, site-workers, брифинг = аларма); остатък → FG-460/462 |
| FG-422 | medium | #73 LAB-01 `a97db46` | budget-health / earned-value / burn взимат `by_smr`/`labor_total` без престоя и ръчните редове, алармата — `total`: 750 / 825 / 850 за един бюджет | PROVEN | resolved (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`), PROVEN: budget-health / earned-value равни на общото число) |
| FG-423 | medium | #73 LAB-01 `a97db46` | ръчният ред се оценява часове × ставка и за акорд; няма проверка за дублиране с одобрен отчет (часовете се броят два пъти) | PROVEN | resolved (#73 LAB-01 `4d1f5a3`, PROVEN: акорд = количество × акордна цена; заобикалянето през датата (FG-491) е затворено) |
| FG-424 | medium | #73 LAB-01 `a97db46` | одобрението на ръчен ред: без отказ/сторно, без Idempotency-Key, без точна версия/стойност, записът и AuditEvent не са в една транзакция; Owner одобрява собствения си ред | PROVEN | resolved по Р66/Р73 (#73 LAB-01 `df4cf51`, PROVEN: ред без `created_by` се одобрява само от Owner (`labor_smr.py:317-321`); AuditEvent с реалния актьор и роля + `is_creator` (`:401-407`); самоодобрение 403; създателят отказва/сторнира с AuditEvent, причина 422, ключ 428; „коригира“ = отказ/сторно + нов ред, PUT/PATCH/DELETE 404); остатък → FG-492 |
| FG-425 | medium | #83 CP-01 `4929451` (+ main) | използван касов бон се трие твърдо (`DELETE /api/media/{id}` → 200, плащането сочи изтрит файл, без AuditEvent) | PROVEN | resolved по Р71 (#83 CP-01 `a5176b2`, PROVEN: `media.py:466-483` → 409 `RECEIPT_IN_USE` + AuditEvent `media.delete_refused`; проверка в `finance_payments` и `subcontractor_payments` (`bank_account_guard.py:91-101`), вкл. сторнирано плащане; 20 паралелни рунда — без сирак); архивиране — след File Registry (W0-06) |
| FG-426 | low | #83 CP-01 `4929451` | всеки файл на tenant-а минава за касов бон (снимка, видео); един бон плаща много разходи | PROVEN (поведение) / SUSPECTED (канон) | partial (#83 CP-01 `a5176b2`, PROVEN: само снимка/PDF (видео → 422); един бон за втори аванс → 201 — Krum; OCR по редове (Р72) — не е започнат, бъдещ пакет) |
| FG-427 | high | #83 CP-01 `4929451` (аванс от main) | авансът на подизпълнител (SUB-ADV-01) плаща без проверката на CP-01: непроверен IBAN, без бон, архивиран подизпълнител → 201 | PROVEN | resolved по Р71 (#83 CP-01 `a5176b2`, PROVEN: `subcontractors.py:1172-1182` — `require_selectable_party` и `check_payment_target` преди `MoneyWrite.begin`; висящ IBAN → 409; брой без бон/получател → 422; бон на друг tenant / видео → 422; неактивен/архивиран → 422; проверена сметка → 201 с `bank_account_id` и `****3456` на двата реда); остатъци → FG-480, FG-481 |
| FG-428 | medium | #83 CP-01 `4929451` (+ main) | PDF на фактурата печата пълното ЕГН на всички роли без AuditEvent | PROVEN | resolved по Р65 за фактури към физическо лице (#83 CP-01 `7750f4e`, PROVEN: ЕГН в `counterparty_eik` (вкл. `BG…`, с интервали) и входяща от лице — Viewer/SiteManager/Technician/Admin 403, Owner/Accountant 200 с пълното ЕГН; всяко сваляне → canonical `invoice.pdf.downloaded` (кой, кога, коя фактура) само с `******1234` (`finance.py:2355-2377`)); остатък → FG-429 (ДДС поле), FG-455 |
| FG-429 | medium | #83 CP-01 `4929451` | ДДС номер `BG` + ЕГН се приема и показва изцяло (списък, детайл, PDF) без маскиране и AuditEvent | PROVEN | partial по Р71 (#83 CP-01 `a5176b2`, PROVEN: `BG******1234` за всички роли във фактури, контрагенти, проекти, invoice-details, подизпълнители, оборотни справки и експорт; маскираната стойност обратно запазва записаната; одитирано разкриване за Owner/Accountant (`finance.py:1069-1090`), Admin 403; PDF за Admin — отказ); остатък → FG-482, FG-483 |
| FG-430 | medium | main `44e8d97` (и #81 `3028304`) | картата „Баланс“ на таблото на обекта брои разходите само заплати + материали — след аванс и прихващане таблото показва 0, а P&L / `/project-profit` — 2000 за подизпълнител | PROVEN | open (+ Krum: общ помощник или етикет „частичен изглед“) |
| FG-460 | medium | #73 LAB-01 `b395f0d` (+ #75 `33a3e7b`) | дейностната част на centralized-reports изпуска СМР без бюджет и редове с празно СМР (всички ръчни редове) — дейностите дават 775 при общо 850…1270 | PROVEN | resolved (#73 LAB-01 `df4cf51`, PROVEN: `centralized_reports.py:248-273` — сборът по дейности = общото число) |
| FG-461 | low | #73 LAB-01 `b395f0d` | СМР на ръчния ред е свободният `activity_name`, не СМР на пакета — бюджетът по СМР не вижда одобрения ред | PROVEN | resolved (#73 LAB-01 `df4cf51`, PROVEN: без пакет / различен свободен текст / пакет от друг обект → 422; старите редове се свързват по име или получават DQ) |
| FG-462 | medium | #73 LAB-01 `b395f0d` (+ main) | `/work-sessions/summary`, `/overtime`, `/my-today` още връщат пари за труд от суровите сесии (900 при всяка стъпка) | PROVEN | resolved за екраните за време (#73 LAB-01 `4d1f5a3`, PROVEN: `/work-sessions/summary`, `/overtime`, `/my-today`, `/work-sessions`, `/active` без пари (`work_sessions.py:32, 218-330, 374-391, 490-505`); `/summary?site_id` връща `approved_labor_cost` = официалното число; `MyDayPage.js` без пари); остатък в отговорите при запис → FG-502 |
| FG-463 | medium | #73 LAB-01 `b395f0d` (+ #75 `33a3e7b`) | едни и същи часове още се броят два пъти: втори ръчен ред за същия работник/ден се приема; отчет, одобрен след одобрен ръчен ред, брои и двата | PROVEN | resolved (#73 LAB-01 `4d1f5a3`, PROVEN: паралелно 8 създавания → 1×201; 4 одобрения → 1×200; ръчен срещу отчет (вкл. стар вид) — винаги един ред; FG-490/491 затворени) |
| FG-464 | low | #75 LAB-02 `33a3e7b` (и `48ba662`) | `PUT /labor-terms` и replay-ът връщат текущата версия на пакета, не записаната; собственият тест пада 6 от 7 пъти на реален Mongo | PROVEN | resolved (#75 LAB-02 `11b55c1`, PROVEN: `labor_quantities.py:247-262, 324-328` — отговорът и replay-ът от реда в историята на записаната версия + `current_version`; тестът `f75_01` — 8/8 в 10 пускания, файлът 52/52 в 5 пускания) |
| FG-465 | medium | #82 `e07320d` × #84 `f6e0c90` | DQ задачата и алармата „очаква кредитно известие“ остават отворени завинаги след регистрирането на кредитното известие в #84 (#84 затваря фантомен `dq_task`, не вика `sync_credit_note_issue`, втора схема на `dq_issues`) | SUSPECTED | resolved (#84 `b0e72cf` × #82 `108afc0`, PROVEN на пробно сливане: регистрацията на кредитно известие вика `sync_credit_note_issue` (`services/invoice_corrections.py:443, 1002`; `routes/invoice_corrections.py:434`), без `dq_task`; две сторнирания → Р47 задача 48 + аларма; несъвпадащо известие → CREDIT_NOTE_DIFFERENCE, Р47 остава 48; частично → 24; второто известие затваря задачата и алармата) |
| FG-470 | medium | #88 PWA-01 `d59bcca` | токенът на клиентския magic link (`/offers/review/:reviewToken`) отива в PostHog във всеки `$pageview` (`$current_url`, `$pathname`) | PROVEN | resolved (#88 PWA-01 `131d945` / `349622ab`, PROVEN по код + jest + Playwright evidence 15/15: на `/offers/review/*` и `/reset-password` аналитиката не се зарежда, всяко събитие оттам се изпуска; URL и `$pathname` стават шаблон на маршрута (`ROUTE_TEMPLATES`, тест пази всеки `<Route path>` в `App.js`); `$referrer`/`$initial_*`/`$session_entry_url` не излизат) |
| FG-471 | low | OFF-02 `56913a4` | Р67: ТР предлага количества с коментар по офертата — модел и път за коментар няма (дълг D-OFF02-2) | PROVEN (липса) | open |
| FG-472 | medium | OFF-02 `56913a4` (+ main) | `PUT`/`GET /offer-budgets/{offer_id}` отворени за всяка M2 роля: Техник/Наблюдател/ТР/Шофьор пишат бюджетни цени и марж и четат продажба/марж, без AuditEvent | PROVEN | resolved (OFF-02 `7cfeae5` / `82312a23`, PROVEN по код + червени→зелени тестове на PR-а: PUT под `require_money_write("offers.offer_budget.update")` (Owner/Admin/Accountant), в транзакция с AuditEvent `offers.offer_budget.updated` и diff; GET с `strip_money_for_non_finance` и изглед без продажба/бюджет/марж за роли без пари); бележка: без Idempotency-Key и без стойност „преди“ в diff |
| FG-490 | medium | #73 LAB-01 `df4cf51` | отчет от стар вид (`employee_id` + `day_entries`, без `project_id`) се одобрява след одобрен ръчен ред за същия ден без проверка — двата реда по 8 ч се броят (1200 → 1360) | PROVEN | resolved (#73 LAB-01 `4d1f5a3`, PROVEN: `daily_reports.py:431-451` — отчет от стар вид заключва деня за проектите в `day_entries` (без проект — всички); заключване по работник+ден (`labor_cost.py:542, 565`); след одобрен ръчен ред → 409, сумата остава 1200; паралелно — винаги един ред) |
| FG-491 | medium | #73 LAB-01 `df4cf51` | датата на ръчния ред не се валидира — „2026-10-05T00:00:00“, „2026-10-05 “, „05.10.2026“ върху ден с одобрен отчет минават (201/200), часовете се броят два пъти; четците по дата ги изпускат | PROVEN | resolved за нови редове (#73 LAB-01 `4d1f5a3`, PROVEN: `labor_smr.py:144` → 422 `INVALID_DATE`; проверките сравняват нормализирания ден (`labor_cost.py:481, 495-514`); стари редове с неправилна дата → 409 + DQ `MANUAL_ROW_NON_ISO_DATE` (`:668`)); остатък → FG-500 |
| FG-492 | low | #73 LAB-01 `df4cf51` | корекцията по Р73 не свързва новия ред със заменения; създаването на ръчен ред не пише AuditEvent | SUSPECTED | resolved по Р73 (#73 LAB-01 `4d1f5a3`, PROVEN: нов ред след отказан/сторниран за същия работник/обект/ден изисква `corrects_entry_id` (422 `CORRECTION_LINK_REQUIRED` / `_INVALID`, `labor_smr.py:149, 275-296`); създаването пише `labor.manual_entry.created` в същата транзакция (`:177-199`); 5 паралелни със същия ключ → 1 ред, 1 събитие) |
| FG-493 | low | #73 LAB-01 `df4cf51` | 4 SEC-01 гейт теста падат: C03 структурната проверка (заменен `insert_once`), C01/C02/money_write — evidence отпреди LAB73-R1 (липсва `op.labor_day_locks`, индексът записан като запис с org `None`) | PROVEN | resolved (#73 LAB-01 `4d1f5a3`, PROVEN: C03 минава — вмъкването през `mw.insert_once()` (`labor_smr.py:177`); индексът при старт (`server.py:420`); evidence регенериран; SEC-01 C01 7, C02 9, C03 6, money_write 8, SEC-02 31, PM-01 6) |
| FG-495 | medium | #83 CP-01 `b4a775f` | README §19 цитира два пъти `gates_pass39.txt` като доказателство за целия набор на реален Mongo — файлът не съществува; няма гейт файл за M3/M5 | PROVEN | resolved (#83 CP-01 `2415b5f`, PROVEN: `gates_pass40.txt` съществува, README §19/§20 го цитират; `gates_pass39.txt` — само в бележка за поправка) |
| FG-496 | medium | #83 CP-01 `b4a775f` | контрагент приема ДДС номер BG+ЕГН с тирета/точки/интервали (`BG-7501011111`, `bg.7501011111` → 201); изключването в търсенето хваща само чистия вид — Admin/Viewer намират записа по цифрите на ЕГН или по „750101“ | PROVEN | partial (#83 CP-01 `2415b5f`, PROVEN: интервал, NBSP, `-`, `.`, `/` се нормализират при създаване/промяна на контрагенти, `/companies`, `/clients/company` и фактури; Admin/Viewer/SiteManager не намират записа по цифрите на ЕГН или „750101“; търсене от Owner/Accountant → AuditEvent `party.egn_search` само с маскираната заявка); стари записи — само маскиране при четене (решение на оркестратора); остатък → FG-510 |
| FG-497 | low | #83 CP-01 `b4a775f` | `import-client-invoice` пише пълното `BG7501011111` в `projects.invoice_details` без DQ — излишно копие на ЕГН (CP83-03 / FG-226) | PROVEN | resolved (#83 CP-01 `2415b5f`, PROVEN: `projects.py:537-540` записва `BG******1111`; различна стойност → DQ `EGN_COPY_WITHOUT_CANONICAL` (`:290-319`)) |
| FG-498 | low | #83 CP-01 `b4a775f` (+ main) | стари `clients` с `vat_number`/`vatNumber` — пълна стойност за всички роли в `/clients`, `/clients/{id}`, `/summary`; изгледът на master-data плана печата `vat:BG7501011111` | PROVEN (поведение) / SUSPECTED (достижимост) | resolved (#83 CP-01 `781d185` (код `c50df5f`), PROVEN: (а) `vatNumber` маскиран за всички роли във всички пътища, импортът пази `BG******1234` (`counterparty_rules.py:198`); (б) `legacy_plan.public_view` и `uniqueness.mask_value` → `vat:BG******1111` (`uniqueness.py:73-86`)); изписванията от група Б → FG-526 |
| FG-499 | low | #83 CP-01 `b4a775f` | удръжката от аванс (`subcontractors.py:1262-1295`) още проверява преди идемпотентността и няма `completed_replay` — повторът след промяна на акта връща 409 вместо записаното 201 | SUSPECTED | resolved (#83 CP-01 `2415b5f`, PROVEN off/enforce: удръжката проверява за replay преди проверките на акта (`subcontractors.py:1283-1291`); повтор след анулиране на акта → 201 със същото id, без нов запис; друго тяло → 409 `IDEMPOTENCY_CONFLICT`; tenant B → 404) |
| FG-500 | low | #73 LAB-01 `4d1f5a3` | стари одобрени ръчни редове с неправилна дата изпадат от четците по период (общо 890, за 01–31.10 — 870; еднодневни прозорци — нито един) | PROVEN | resolved (#73 LAB-01 `d34d41b`, PROVEN: `labor_cost.py:463-469, 681` — стари редове с неправилна дата влизат в своя ден; до 25.10 — 870, от 26.10 — 40, общо и октомври 910; DQ остава); дълг: четецът зарежда до 5000 реда и филтрира в паметта |
| FG-501 | low | #73 LAB-01 `4d1f5a3` | няма UI за ръчни редове за труд (въвеждане, одобрение, отказ, сторно, корекция с връзка) | SUSPECTED | open (+ Krum) |
| FG-502 | low | #73 LAB-01 `4d1f5a3` | отговорите при start/end/split/PUT на работна сесия още връщат `labor_cost` и `hourly_rate_at_date`, вкл. на работника | SUSPECTED | resolved (#73 LAB-01 `d34d41b`, PROVEN: start/end/split/PUT без пари за Worker, Owner, SiteManager (`work_sessions.py:216, 256, 462, 548`)) |
| FG-505 | medium | main `1525a1e` (и #73 `d34d41b`) | блокът „pnl“ на `/projects/{id}/aggregate` и плочките „Труд“/графиката „Разходи“ в `ProjectDetailPage.js` ползват платения труд, не одобрения (печалба −1234 при одобрен труд 850) | PROVEN | resolved (#73 LAB-01 `06a309d`, по код; PROVEN на слетия #75 `b35d0c7`: `pnl.labor` = 1350 = `project_labor_cost`, платеният труд 1234 отделно); бележка → FG-530 |
| FG-506 | low | main `1525a1e` | картата „Баланс (касов)“ чете изплатените заплати от старото `payroll_entries`, а другите изгледи — от pay runs: два източника за „изплатени заплати“ | SUSPECTED | resolved (#73 LAB-01 `06a309d`; PROVEN на #75 `b35d0c7`: `total_salaries_paid` = 1234 = платените pay runs; „одобрен“ run (500) и старото `payroll_entries` (999) — извън) |
| FG-507 | medium | #75 LAB-02 `4fa4957` | корекция/анулиране на количество в LAB-02 след одобрен ръчен акордов ред — редът продължава да брои старото количество без DQ (20 → 30, остава 100 вместо 150) | PROVEN | partial по Р77 (#75 LAB-02 `b35d0c7`, PROVEN: първа корекция и пряко анулиране — корекцията се записва (`labor_quantity.corrected`), редът получава `correction_required` „изисква корекция“ с предложение (сторно + нов ред по новото количество), старата сума остава с DQ `MANUAL_ROW_CORRECTION_REQUIRED`, AuditEvent и аларма; новият ред се одобрява от втори човек (създателят 403, Accountant 200); двойно броене — никога); остатък → FG-531..534 |
| FG-508 | low | #75 LAB-02 `4fa4957` | ръчен акордов ред приема старо одобрение на количество, направено от самия работник (цена 250); четците на труда пренебрегват такива одобрения | PROVEN | resolved по Р66 (#75 LAB-02 `b35d0c7`, PROVEN: 409 `SELF_APPROVED_QUANTITY` за количество, одобрено от работника или от създателя на реда (`labor_smr.py:247-251, 430-442`); стар одобрен ред — брои се с DQ `MANUAL_AKORD_SELF_APPROVED_QUANTITY` (`labor_cost.py:791-795`)) |
| FG-510 | medium | #83 CP-01 `2415b5f` | ДДС номер BG+ЕГН с `_`, `:`, тире „–“, `,`, zero-width интервал или **кирилско „В“** (`ВG7501011111`) минава без нормализиране, маскиране и изключване в търсенето — пълно за Admin/Viewer, намира се по цифрите на ЕГН | PROVEN | partial (#83 `ddc6e9a`, PROVEN: входът е затворен по Р78; `mask_value`/`public_view` (`uniqueness.py:80-86`) още показват стари странни изписвания изцяло → FG-560) |
| FG-511 | low | #83 CP-01 `2415b5f` | replay-ят връща текущия запис, не оригиналния отговор (след анулиран акт — `status: cancelled`); FLOW-006 пътищата пазят първия отговор байт по байт | PROVEN (поведение) / SUSPECTED (канон) | resolved (#83 CP-01 `781d185` (код `c50df5f`), PROVEN: replay за аванс, плащане и удръжка — байт-идентичен с първия отговор след промяна на записа; друго тяло → 409 IDEMPOTENCY_CONFLICT; записаният отговор без пълен IBAN (`money_input.py:243-256`)) |
| FG-512 | low | #83 CP-01 `2415b5f` (+ main) | replay първо не е на всички парични пътища — дълг D12: `full_cost.py:123`, `labor_smr.py:93/120/302`, `reports.py:976/1042/1107` | SUSPECTED | open (отделна задача) |
| FG-513 | low | #83 CP-01 `2415b5f` | AuditEvent при търсене по ЕГН не казва кои записи са намерени — само маскираната заявка и броя | PROVEN | resolved (#83 CP-01 `781d185` (код `c50df5f`), PROVEN: AuditEvent `party.egn_search` съдържа `matched_ids`, без цифрите; таван 50 id (`master_records.py:359`)) |
| FG-515 | low | #90 SEC-03 `bc52843` | CSP в nginx е статичен `connect-src 'self'` — ще блокира PostHog след #88; заглавките стигат до production само след ръчна подмяна на живия nginx.conf | PROVEN | partial (#90 `0c04438c` (код `f34b1f25`), PROVEN: README D1–D7 — ред, проверка и връщане за всяка стъпка; липсват версии на app/схема/конфигурация (вкл. nginx), снимка на флаговете, одобряващ/изпълняващ, конкретна точка на връщане и резултат след пускането — CLAUDE.md §6; самият README го нарича вход за Release Manifest (ChatGPT, §18)); остава до създаването на манифеста |
| FG-516 | low | #90 SEC-03 `bc52843` | тестовият режим за `JWT_SECRET` включва staging/dev/local — там липсващ или къс ключ се приема (`ENV=staging JWT_SECRET=abc`) | PROVEN | resolved (#90 SEC-03 `863876b`, PROVEN: тестов режим само при `PYTEST_VERSION`; staging/dev/local/development с къс или липсващ ключ → `JwtSecretMissing`); бележка: `PYTEST_VERSION` в production би приел къс ключ — да се забрани при deploy |
| FG-517 | low | #90 SEC-03 `bc52843` | регулярният израз за скриване не хваща IBAN с малки букви и ЕГН с интервали/тирета; прекалено скрива телефони/суми/цифри в id; снимките не се минимизират | PROVEN | partial (#90 SEC-03 `863876b`, PROVEN: IBAN с малки букви, ЕГН с интервали/тирета, fullwidth цифри — скрити; телефони и суми — не); остатък → FG-535 |
| FG-518 | medium | #90 SEC-03 `bc52843` | кешът на ai-breakdown прилага стари AI резултати и при изключен `ai_enabled` или без ключ (`smr_analysis.py:991-1003` преди проверката на `:1037`) | PROVEN (код) | resolved (#90 SEC-03 `863876b`, PROVEN: `smr_analysis.py:989-1004` — проверката за AI преди кеша; при изключен AI и запис в кеша → ръчното 60/40 и „AI не е настроен“); прякото писане в анализа остава FG-360 |
| FG-519 | medium | #90 SEC-03 `bc52843` | AI извикванията не пишат canonical AuditEvent и запис за потребление; включването на `ai_enabled` — само legacy `log_audit` (`auth.py:640`) | PROVEN | partial (#90 SEC-03 `863876b`, PROVEN: всяко AI извикване → canonical `ai.call.completed`/`ai.call.failed`; ред в `ai_usage_ledger` по tenant; `PUT /api/ai/settings` само Owner + `ai.settings.changed`; старият път за feature flags отказва `ai_enabled`); остават: Approval за включване (Krum), бюджет → FG-537, атомарност → FG-536, FG-538 |
| FG-520 | low | #90 SEC-03 `bc52843` | остатъци извън обхвата: docstring и preview URL, `test_m9_alerts.py` очаква 200 без ключ, чеклистът с `EMERGENT_LLM_KEY`, dev сървърът с `*.emergent.sh`, неизползвани `openai`/`litellm` | PROVEN | partial (#90 SEC-03 `863876b`: всички остатъци махнати, 22 неизползвани зависимости — също; доверието на dev сървъра към `*.emergent.sh` остава с коментар — Krum) |
| FG-521 | low | #90 SEC-03 `bc52843` | AuditEvent за напомнянията се пише след изпълнението и не атомарно; Platform Admin пуска `all_tenants` без Support Access Grant | SUSPECTED | resolved (#90 SEC-03 `863876b`, PROVEN: събитие „started“ преди изпълнението, после „completed“/„failed“; без audit store — не се изпълнява; Platform Admin — само собствения tenant, друг/`all_tenants` → 403 `SUPPORT_ACCESS_GRANT_REQUIRED`); дребно: при `all_tenants` първият неуспешен tenant спира цикъла |
| FG-522 | medium | #90 SEC-03 `bc52843` (+ main) | оригиналната снимка не се пази преди AI обработката — клиентът я компресира, пази се само едно смалено base64 копие (дълг до W0-06) | PROVEN | временно затворен (#90 SEC-03 `863876b`, PROVEN: AI за снимки е изключен с константа — двата пътя за снимки → 503 и при включен AI, адаптерът отказва изображения); дългът по CLAUDE.md §4 до W0-06 остава |
| FG-525 | low | #83 CP-01 `781d185` (код `c50df5f`) (+ main) | `POST /subcontractors` не нормализира и не маскира ДДС номера — пази суровия вход и връща пълното BG+ЕГН в отговора 201 | PROVEN | resolved (#83 `ddc6e9a`, PROVEN: `subcontractors.py:124` нормализира, `:139` маскира отговора) |
| FG-526 | medium | #83 CP-01 `781d185` (код `c50df5f`) | ДДС номери като гръцко `Β`, `VAT BG…`, `ДДС BG…`, `BG… (физ. лице)`, `ЕГН 7501011111`, само `7501011111` не се разпознават като ЕГН — пълни за всички роли, намират се по цифрите в unified search, без одит | PROVEN | partial (Р78; #83 `ddc6e9a`, PROVEN: нов вход — 52 изписвания × 10 пътя, нищо невалидно не се записва, 422 `VAT_NUMBER_INVALID` (`counterparty_rules.py:233-267`)); старите записани стойности → FG-560 |
| FG-527 | low | #83 CP-01 `781d185` (код `c50df5f`) | нормализирането тихо поврежда данни (201, без 422/DQ): `ДДС BG…` → `CBG…`, `ЕГН …` → `EGH…`, гръцко `Β` губи B, цифри от други писмености изчезват | PROVEN | resolved (Р78; #83 `ddc6e9a`, PROVEN: нищо не се пренаписва); разделители/fullwidth/кирилски В,Г се премахват/съпоставят без съобщение — въпрос към Крум |
| FG-528 | low | #83 CP-01 `781d185` (код `c50df5f`) (регресия от `2415b5f`) | в `/counterparties?search=` заявка с по-малко от 4 цифри още намира BG+ЕГН записи за Admin/Viewer/SiteManager (`BG750` → 28, `750`/`111` → 32) — ЕГН може да се познае по 3 цифри; кратките търсения на Owner/Accountant не се одитират | PROVEN | partial (Р79; #83 `ddc6e9a`, PROVEN: `/counterparties` (`counterparties.py:122-131`) — Admin/Viewer/ТР 0 попадения при всякаква цифрова заявка); остават: стари стойности в unified search (`clients.py:414-415`, FG-560), ЕГН в полето `eik` (FG-561) |
| FG-529 | low | #83 CP-01 `781d185` (код `c50df5f`) | търсене на Owner/Accountant в `/counterparties` с fullwidth цифри намира всички BG+ЕГН записи без AuditEvent (`egn_digits_query` пази не-ASCII цифри) | PROVEN | resolved (Р79; #83 `ddc6e9a`, PROVEN: `counterparty_rules.py:270` `search_digits` — всяко търсене с цифра от Owner/Accountant се одитира в двата маршрута, без пълно ЕГН в събитието) |
| FG-530 | low | #73 LAB-01 `06a309d` (+ main) | блокът „pnl“ на агрегата смесва основи: приход по **платени** фактури, разходи по **одобрен** труд и материали | SUSPECTED | resolved (Р80; #73 `2ca349e`, PROVEN: `projects.py:2516, 2662` — приход 2270 = P&L, платени 1140 отделно с надпис; дългът на доказателствата е затворен в `ed6e88d4` — `test_fg530` минава самостоятелно); остатък → FG-565 |
| FG-531 | medium | #75 LAB-02 `b35d0c7` | втора корекция или по-късно анулиране не стига до маркирания ред: търсене само по заменените одобрения, всяко маркиране презаписва предишното — предложението остава 30/150 при реален нов ред 200, без AuditEvent и аларма | PROVEN | resolved (#75 `9e34641`, PROVEN: корекции 20→30→40 — seq 2, предложение 40/200, 2 AuditEvent; анулиране на най-новото одобрение стига до реда — seq 3, 3-ти AuditEvent) |
| FG-532 | medium | #75 LAB-02 `b35d0c7` | създателят сторнира стария ред сам (Р73) — веднага, затваря алармата; денят брои 0 до одобрението на новия ред (100 → 0 → 200), а Р77 казва, че старата сума остава до одобрението | PROVEN | resolved (Р81; #75 `9e34641`, PROVEN: `labor_smr.py` `_decide_manual_row`/`_make_reversal_effective` — сторното на създателя е само заявено, денят 100 → 200 след одобрението на Счетоводителя, никога 0; собствено потвърждение → 409 `REVERSAL_PENDING`; създател/ТР одобрява замяната → 403; отказът — само в теста (16 passed)); остатък за заплатата → FG-569 |
| FG-533 | low | #75 LAB-02 `b35d0c7` | „изисква корекция“ е само в API и като обща аларма — UI няма; ТР затваря алармата без корекция | PROVEN (код) | partial (#75 `9e34641`, PROVEN: `alarms.py:179` — затваряне преди корекцията → 409, банерът работи); остава (low, Krum): `alarms.py:156` ТР „потвърждава“ алармата по Р77 — излиза от броячите и сторното после не я затваря |
| FG-534 | low | #75 LAB-02 `b35d0c7` | при корекция анулирането, вмъкването (`labor_quantities.py:495`) и маркирането не са в една транзакция — срив по средата оставя немаркиран ред, повторът дава 409 | SUSPECTED | resolved за пътя на одобрението (#75 `9e34641`, PROVEN: срив в транзакцията връща всичко, повторът минава, 17/17); другите пътища за анулиране → FG-568 |
| FG-535 | low | #90 SEC-03 `863876b` | още стигат до модела нескрити: ЕГН след запетая/точка (CSV), ЕГН последвано от число, IBAN с NBSP/двойни интервали, ЕГН/IBAN с грешна контролна сума, ЛНЧ | PROVEN | partial (#90 `0c04438c` (код `f34b1f25`), PROVEN: скрити `800101.0008`, `800101/0008` при вярна контролна сума, ZWSP в ЕГН/IBAN); остават тънък интервал в ЕГН, `80.01.01.0008`, 6+4 с грешна контролна сума, IBAN с `.`/`_`/`/` (+ Krum) (`ai_provider.py:102, 150, 154-169`) → FG-604 |
| FG-536 | low | #90 SEC-03 `863876b` | редът в `ai_usage_ledger` се пише преди AuditEvent — при срив на audit store действието се брои без събитие, отговорът се губи, ai-breakdown пише 60/40 | PROVEN | resolved (#90 `aaef24f`, PROVEN: редът в дневника и AuditEvent в една транзакция, `ai_provider.py:262-279`) |
| FG-537 | medium | #90 SEC-03 `863876b` | `ai_usage_ledger` не се чете: няма връзка с плана и проверка преди извикването — при 2500 действия (над Pro 2000) извикването минава; няма поведение при изчерпан бюджет и няма определена единица | PROVEN | open (+ Krum) |
| FG-538 | low | #90 SEC-03 `863876b` | `PUT /api/ai/settings` включва флага преди събитието — при срив връща 500, но AI остава включен без събитие; без Idempotency-Key, причина и Approval | PROVEN | partial (#90 `aaef24f`, PROVEN: `auth.py:663-735` — без ключ 428, без причина 422, флаг и събитие в една транзакция, повтор/повторна употреба 409); без Approval (+ Krum); краен случай → FG-563 |
| FG-539 | low | #90 SEC-03 `863876b` × main `3863610` | `git merge-tree` с текущия main — конфликт в `frontend/public/index.html` (клонът пази стария inline PostHog с вграден ключ, махнат от #88) и в PM-01 `run_meta.json`; нито една страна изцяло не е вярна | PROVEN | resolved (#90 `aaef24f`, PROVEN: слетият `index.html` — PWA таговете на #88 + CSP на SEC-03, без `<script>`, Emergent и ключ `phc_`; jest 30/270) |
| FG-540 | high | main `3863610` | `/api/media/avatar/{filename}` сервира всеки качен файл (снимки, бележки, фактури) без вход и без tenant | PROVEN | resolved (MEDIA-SEC-01 `35df04e`, PROVEN: без вход → 401; файл само през ред `media_files` на tenant-а със `context_type="profile"`, пътят от реда (`media.py:243-279`); снимка от обект/бон/непознато име → 404; друг tenant → 404; 15 трика с пътя → 404; собствен аватар → 200) |
| FG-541 | medium | main `3863610` | `project_photos`: качване, списък и файл от всяка роля за всеки обект, без членство; само legacy одит | PROVEN | partial (#91 `1844627`, PROVEN: без Idempotency-Key → 201; само legacy `log_audit` (`projects.py:1269-1270`)) |
| FG-542 | high | main `3863610` | използвана медия (одобрен отчет, ново СМР) се трие физически през `DELETE /api/media/{id}`, без AuditEvent | PROVEN | partial (#91 `1844627`: почти resolved; остават `scan_docs.py` (FG-145) и прозорецът FG-588) |
| FG-543 | medium | main `3863610` | прикачени файлове към ново СМР / снимки в отчета приемат всеки `media_id` и външен URL, за чужд обект, без одит | PROVEN | open |
| FG-544 | medium | main `3863610` | медията има една връзка; `/media/link` тихо я мести и сменя кой я вижда | PROVEN | resolved (#91 `1844627`, PROVEN: `media.py:208-231` — link в транзакция с AuditEvent `media.file.link`) |
| FG-545 | medium | main `3863610` | моделът на фото/видео архива (видео, thumbnail, GPS, тагове MD, статуси, галерия, актуване, портфолио, restore) не е реализиран | PROVEN | open |
| FG-546 | low | main `3863610` | контекстите `message`/`site` и `photo-invoice` заобикалят видимостта по обекти | SUSPECTED | open |
| FG-555 | medium | MEDIA-SEC-01 `35df04e` × #83 `ddc6e9a` | конфликт в `delete_media`: на клона касов бон от `finance_payments` се оттегля с 200 (Счетоводителят губи файла); след сливане `"retired"` липсва в `_INACTIVE_FILE_STATES` на #83 — оттеглен файл минава за нов бон | PROVEN | open (#91 `cb19aeb` × #83 `ddc6e9a`, PROVEN: `git merge-tree` → `c299a20`, конфликт в `media.py`; рецептата от проход 47 и FG-589 важат) |
| FG-556 | medium | MEDIA-SEC-01 `35df04e` | `_media_usages` не проверява `work_reports.photos`, `extra_work_drafts.photos`, `pending_expenses.media_id`, `finance_payments` — снимка от одобрен отчет се оттегля (200), авторът губи достъп; няма възстановяване | PROVEN | resolved (#91 `1844627`, PROVEN — покрито от пробата на FG-576) |
| FG-557 | low | MEDIA-SEC-01 `35df04e` | всеки файл, свързан с профил, се вижда от всички в tenant-а през аватара; Admin може да свърже всеки файл (напр. бон) с профил без одит; стар аватар не може да се оттегли | PROVEN | resolved по Р83 (#91 `d634bf4` (код `f3cf9f1`), PROVEN: аватар само от ново качване с контекст profile (`media.py:136-138`); свързване като profile → 409 (`:197-200`); `check_avatar_url` само собствен ред на tenant-а (`media_avatar.py:40-61`); смяната → `user.avatar.change` (`auth.py:510-521`, `hr.py:193-204`); стар аватар може да се оттегли); остатък в скрипта → FG-578; видимостта на аватарите в tenant-а — въпрос към Крум (оркестратор) |
| FG-558 | low | MEDIA-SEC-01 `35df04e` | `GET /media/{id}` връща метаданни на оттеглен файл на не-админи; няма списък на оттеглените и възстановяване | PROVEN (код) | partial (#91 `1844627`: `media_policy.py:22` `RESTORE_ENABLED=False`; списък/възстановяване — чака Крум) |
| FG-560 | medium | #83 CP-01 `ddc6e9a` | стари записани ДДС стойности в странни изписвания (гръцко Β, `ДДС/VAT BG…`, `(физ. лице)`, `ЕГН …`, голи 10 цифри, арабски цифри, комбиниращ знак) не се маскират: всички 5 роли ги виждат изцяло в списъци, детайли и unified search; Admin/Viewer/ТР ги намират по цифри; `import-client-invoice` ги копира в обекта | PROVEN | open (+ Krum) |
| FG-561 | low | #83 `ddc6e9a` (+ main) | ЕГН в полето `eik` на контрагента (приема всякакъв брой цифри, `counterparty_rules.py:360`) — видимо изцяло и намирано по `750` от всяка роля (`counterparties.py:177`), противно на Р79 | PROVEN | open (+ Krum) |
| FG-562 | low | #83 `ddc6e9a` (+ main) | маскирана стойност (`BG******1111`) се записва като ДДС номер при PUT на запис без ДДС (`counterparties.py:312-318`, `counterparty_rules.py:498`) | PROVEN | open |
| FG-563 | low | #90 SEC-03 `aaef24f` | `complete_idempotent` извън транзакцията (`auth.py:731`), ключовете без срок (`audit/idempotency.py:186`) — срив след commit оставя ключа „в процес“ завинаги; всеки повтор 409, макар флагът да е сменен | SUSPECTED (код) | resolved за срив след commit (#90 `0c04438c` (код `f34b1f25`), PROVEN: ключът се завършва в транзакцията; повторът → 200, 1 AuditEvent; друго тяло → 409 `IDEMPOTENCY_KEY_REUSED`; срок 7 дни (`auth.py:704-741, 762-778`, `idempotency.py:88-97, 237-256`)); нов път за двойно прилагане → FG-603 |
| FG-603 | low | #90 SEC-03 `0c04438c` | възстановяването на „заседнал“ ключ може да приложи един ключ два пъти: A запазва ключа и спира, B го поема като стар и записва, A продължава и също записва — 2 събития `ai.settings.changed` за един ключ, и двете 200 (`complete_idempotent` филтрира само по `status: STARTED`, не по токена на опита; 0 реда не прекъсва транзакцията — `auth.py:762-765`, `idempotency.py:247-256`) | PROVEN | open (+ Krum) |
| FG-604 | low | #90 `0c04438c` | непоследователно скриване: голи 10 цифри се скриват и при грешна контролна сума, а 6+4 с точка/наклонена — само при вярна; тънък интервал и групирането 2+2+2+4 не се обработват | PROVEN | open (+ Krum) |
| FG-565 | low | #73 LAB-01 `2ca349e` (+ P&L на main) | `issued_revenue_net` няма филтър по вид: изпратена проформа се брои за приход (и като `proforma_future`); фактура без `subtotal` брои брутото за нето | PROVEN | open (+ Krum) |
| FG-566 | high | main `3863610` (+ #73 `2ca349e` разширява) | `GET /projects/{id}/aggregate` проверява само вход — без SEC-02 и членство: Driver/Viewer/Technician/Warehousekeeper/ТР (не членове) получават приход, печалба, труд, платени/неплатени фактури | PROVEN | resolved (#73 `ed6e88d4`, PROVEN: `get_project_aggregate` — `strip_money_for_non_finance`, `money_values_visible`, `project_team.is_member` → 403; в каталога на SEC-02 `finance_read.py:247` (R20-5M); не-член Driver/Viewer/Technician/Warehousekeeper/ТР → 403, член → 200 без пари (и в подобектите), изтекло членство → 403; Owner/Admin/Accountant — полетата по Р80; SEC-02 в off/shadow/enforce — без утечка); остатъци → FG-591, FG-592 |
| FG-567 | low | #73/#75 (тест `test_sec_02_finance_read.py:504, 523`) | „SEC-02 intermittent pulse leak“ е фалшив: тестът търси подниз `7777` в целия отговор, който съвпада с `generated_at`/uuid (~5×10⁻⁴ на пулс); пари не изтичат | PROVEN | resolved (#73 `ed6e88d4`: `money_value_leaks` — проверка по стойности на полета, без id/дати/uuid; SEC-02 31 passed) |
| FG-568 | medium | #75 LAB-02 `9e34641` | `void_labor_approvals` извън транзакция в `labor_quantities.py:357` и `daily_reports.py:332, 602, 1216` — срив при AuditEvent по Р77 оставя анулирано одобрение, без AuditEvent и аларма; повторът (200) не ги дописва | PROVEN | resolved (#75 `a665932b`, PROVEN: `void_labor_approvals` в една транзакция + поправка на полузавършено състояние; срив при AuditEvent по Р77 на `PUT /labor-quantities/entry`, `daily_reports.py:332/602/1216`, reject и PUT на отчет → пълно връщане; повторът — 1 AuditEvent, 1 аларма, без дубликат; 20 passed) |
| FG-569 | medium | #75 LAB-02 `9e34641` (+ main) | ведомостите четат само дневни отчети (`pay_runs.py:314, 501, 602` → `report_normalizer.py:33`) — одобрени ръчни акордни редове не стигат до заплатата; Р81 „в разхода **и за заплатата**“ е проверено само за разхода | SUSPECTED (код) | open (+ Krum) |
| FG-591 | low | #73 `ed6e88d4` | UI: член ТР/техник получава агрегата без парите, но `ProjectDetailPage.js:1037-1049, 1063-1065` (`AggRowMulti`) показва „Фактурирано/Платено/Неплатено/Труд/Материали/Платен труд“ като 0 €, графиката — приход 0 | PROVEN (код) | open |
| FG-592 | low | #73 `ed6e88d4` (SEC-02 harness) | в `seed_sec02_records` P1 няма подобект — редовете на агрегата във всички режими са `{"has_children": false}`; harness-ът доказва само 403/404, не махането на парите | PROVEN | open |
| FG-580 | high | main `3863610` | AI оценката (`ai_estimated_price`) на липсващо СМР се записва в записа и влиза в P&L като приход „additional_offered“ — Viewer я пуска, остава след корекция/отказ на офертата, преизчислява се след `offered`; без AuditEvent | PROVEN | open |
| FG-581 | medium | main `3863610` | оферта от AI оценките (`missing_smr.py:708-799`) от всяка роля с M2 (Viewer → 200); цялата AI сума влиза като труд, материал 0; без AuditEvent и Idempotency-Key | PROVEN | open |
| FG-582 | medium | main `3863610` | измислен процент „доверие“ в AI отговорите и черновите (`ai_proposal.py:212, 324`, `smr_analysis.py:1063, 1089`, `assets_ai_intake.py:42`, `ExtraWorkModal.js:250, 406`, `extra_works.py:431`) | PROVEN | open |
| FG-583 | medium | main `3863610` | BEG Brain липсва: 4 отделни генеративни пътя, 2 ключа, 3 вградени модела; няма каталог на tools, схема на отговора (време, обхват, източници), история и статус на AI | PROVEN (код) | open (+ Krum) |
| FG-584 | low | main `3863610` | при липсващ ключ/грешка AI връща 500/502 със суровия текст на изключението; ai-breakdown записва 60/40 и връща `error` | PROVEN (код) | open |
| FG-585 | low | main `3863610` | цени от офертите, описания, град и снимки отиват към външния модел без маскиране и без audit на prompt/резултат | SUSPECTED | open (+ Krum) |
| FG-586 | medium | main `3863610` | няма AI флаг/entitlement, дневник и бюджет — AI работи за всеки tenant/план/роля с M2; плановете в `constants.py:24-54` (free/pro/enterprise) нямат AI бюджет | PROVEN (код) | open (+ Krum, виж FG-537) |
| FG-575 | medium | #91 `d634bf4` | Viewer още качва снимки: `/media/upload` без проверка на ролята (без контекст или като член на обекта → 200), `/technician/photo-invoice` → 201; само `/projects/{id}/photos` → 403 | PROVEN | resolved (#91 `cb19aeb` — остатъкът FG-587 е затворен) |
| FG-576 | high | #91 `d634bf4` | `_media_usages` не вижда одобрени/финансови записи: доказателство за клиентско одобрение на оферта (`offers.approval.evidence_file_id`), бракуване (`warehouse_transactions.file_ids`), касови бележки (`cash_receipt_file_id` на #83), `audit_events.related_file_ids` — оттегляне от качилия (Счетоводител) 200 без Собственика | PROVEN | resolved (#91 `1844627` (код `9ba8980`), PROVEN: `services/file_holders.py:44-63, 89-97` — бон в `finance_payments`/`subcontractor_payments`, доказателство на оферта, `warehouse_transactions.file_ids`, `audit_events.related_file_ids` → DELETE 409 `MEDIA_IN_USE`) |
| FG-577 | medium | #91 `d634bf4` | одобрението на оттегляне не сочи точното състояние: заявката пази само `uses`, при одобрение се преизчисляват без сравнение; `/media/link` по време на чакаща заявка → 200 — Собственикът оттегля файл, на който вече стои плащане | PROVEN | resolved (#91 `1844627` (код `9ba8980`), PROVEN: заявката пази `uses_version`/`ref_version` (`media.py:680-686`), одобрението ги сравнява (`:726-733`) → 409 `RETIRE_REQUEST_STALE`; link при чакаща заявка → 409) |
| FG-578 | low | #91 `d634bf4` | скриптът за старите аватари маркира и съществуващ файл, свързан като профил (`linked_at`), за аватар (`media_sec_01_avatar_backfill.py:79-94`); `approved_by` — свободен текст; резултатът на `update_one` не се проверява; няма връщане | PROVEN | resolved (#91 `1844627` (код `9ba8980`), PROVEN: пропуск при `linked_at`, проверка на `matched_count`, `--approved-by` = активен Собственик, `--revert`); Krum: ид. на Собственика достатъчно ли е като „да от Крум“ |
| FG-579 | medium | #91 `d634bf4` | write skew: оттеглянето чете препращащите колекции и пише само `media_files`; нова препратка (напр. плащане с бон на #83) пише в друга колекция — двете транзакции минават | SUSPECTED (код) | partial (#91 `cb19aeb`: остават OCR from-media → FG-597 и #83 след сливане → FG-589) |
| FG-587 | medium | #91 `1844627` | Viewer на обекта (фирмен ТР/техник) още добавя снимки: качване без контекст → 200, после `/media/link` към обекта → 200 (без `require_uploader`, `media.py:155-231`); пазачът гледа обекта само при `context_type=="project"` (`:67`) | PROVEN | resolved (#91 `cb19aeb`, PROVEN: `upload_guard.py:44-82` `require_uploader_for_context` в качване (`media.py:66-68`) и link (`:168-171`); Viewer на обекта → 403 за link/missingSMR/workReport) |
| FG-588 | medium | #91 `1844627` | склад: `claim()` се записва сам, преди транзакцията на движението (`warehouse_canonical.py:248-249, 426-427`; `material_waste.py:118`) — DELETE между двете оттегля файл, който движението после ползва, без Собственика | PROVEN (стъпка по стъпка) | resolved (#91 `cb19aeb`, PROVEN: вариант 4 — `mark_pending` (`file_holders.py:228-263`) преди `service.execute` (`warehouse_canonical.py:264, 448`); `find_holders` отчита `pending_link`; крайният CAS на DELETE/заявка/одобрение с `NO_PENDING` + `ref_version` (`media.py:604, 692, 757`); `settle_pending` във `finally`; `release_stale` — Owner/Admin, ≥ 3600 s, доказателство, без оттегляне, AuditEvent; последователността от проход 47 → 409; всичките 6 условия); остатъци → FG-595, FG-596 |
| FG-589 | high | #91 `1844627` × #83 `ddc6e9a` (слято дърво `49189be`) | след сливане #83 приема оттеглен файл за касова бележка (`bank_account_guard.py:103` без `"retired"`) и писачите на `cash_receipt_file_id` (`finance.py`, `subcontractors.py`) не правят `claim` | PROVEN (код на сляното дърво) | open |
| FG-590 | low | #91 `1844627` | (a) обявената поправка на `EmployeesPage.js:134` (контекст `"avatar"`, URL `/file/`) липсва в diff-а; (b) `file_holders.py:124` пуска регистрираните finders само за вида `audit_event` — finder на #83 се пропуска при `kinds=RECEIPT_KINDS` | PROVEN | resolved (#91 `cb19aeb`, по код: `EmployeesPage.js:134-142` — `profile` и `/api/media/avatar/…`; `file_holders.py:129-134` — всички finders, филтрирани по вид) |
| FG-595 | medium | #91 `cb19aeb` | маркер, надживял записаното си движение (срив/прекъсване между commit и settle), блокира завинаги одобреното от Собственика оттегляне: `release_stale` отказва при всеки държател, вкл. собственото движение (`file_holders.py:282-322`); заявката (`media.py:684-686`) и одобрението (`:757`) изискват липса на маркери | PROVEN | resolved (#91 `35cc099`, PROVEN: правилото „по собствения ref“ (`file_holders.py:329-343`) — собствено движение → `confirmed_late` с AuditEvent, и при AuditEvent на движението и други държатели; после заявка от Admin 201, одобрение 200, файлът остава; `settle_shielded` (`:372`, `asyncio.shield`)); остатък: rollback в `mark_pending` хваща само `Exception` (`:260`) |
| FG-596 | low | #91 `cb19aeb` | повтор на движение със същия Idempotency-Key при чакаща заявка за оттегляне → 409 `RETIRE_REQUEST_PENDING` вместо запазения резултат — маркерът се поставя преди проверката за повтор (`warehouse_canonical.py:264, 448`) | PROVEN | resolved (#91 `35cc099`, PROVEN: `_markers_for` (`warehouse_canonical.py:126-141`) — повтор при чакаща заявка → 200 със запазения резултат, 1 ред, без маркер; друго тяло със същия ключ не добавя препратка) |
| FG-597 | low | #91 `cb19aeb` | OCR from-media още прави claim извън записа на intake (`ocr_invoice.py:109-110`; запис в `services/ocr_invoice.py:142-170`); маршрутът днес връща 500 (липсва `tenant`, и на main) | по код | open |
| FG-598 | low | #91 `cb19aeb` | `release_stale` без Idempotency-Key; отказано освобождаване („referenced“/„no_such_marker“) връща 200 без AuditEvent (`media.py:816-828`, `file_holders.py:296-306`) | по код | resolved (#91 `a15b614`: заедно с FG-610) |
| FG-599 | low | #84 `ebcac7f9` (и преди) | изходящо кредитно известие може да създаде Owner (201) и Admin (`routes/invoice_corrections.py:34` — само `finance_permission`); при двама Собственици единият създава, другият одобрява, без Счетоводител — Р49 (4) казва „издава Счетоводителят, одобрява Собственикът“ | PROVEN | resolved (Р49 (4); #84 `baafdf3a`, PROVEN: `routes/invoice_corrections.py:137-142` — изходящо известие от не-Счетоводител → 403 `ISSUER_ROLE_REQUIRED`; Owner/втори Owner/Admin → 403, Accountant → 201, същият одобрява → 403, Owner одобрява → 200 — еднакво в трите режима, кредитно и дебитно; входящите — без промяна (Р49 (8)); бутонът в UI само за Счетоводителя; INV-CN-01 189 passed) |
| FG-600 | low | #84 `ebcac7f9` × #82 `d6de7db` | опасност при сливането: „запази и двете страни“ в `service.py` губи `@staticmethod` на `_plan_receipt_reversal` (102 от 120 теста на WH-REV-01 падат) и дублира `expected_credit_notes` в ORG_KEYED на `ownership.py` | PROVEN | open |
| FG-607 | medium | #91 `a7e0546` | късното потвърждение се блокира от AuditEvent на самото движение (`related_file_ids`) и от всеки друг държател — за истинско движение блокировката по FG-595 остава | PROVEN | resolved (#91 `35cc099`, PROVEN: собствено движение + неговия AuditEvent / + отчет → `confirmed_late`) |
| FG-608 | medium | #91 `a7e0546` | остарял маркер без собствено движение се отказва, когато файлът има несвързани държатели — маркерът никога не се освобождава | PROVEN | resolved (#91 `35cc099`, PROVEN: движение с друг ключ, маркер 2 ч → `released`, без оттегляне, DELETE → `MEDIA_IN_USE`) |
| FG-609 | low | #91 `35cc099` | „собствено“ движение се търси по `org_id` + голия ключ + `file_ids` (`file_holders.py:331-334`), без `actor_id`/действие — движение на друг потребител/друго действие със същия ключ потвърждава чужд маркер; грешно приписване в одита (без риск за оттегляне); `_markers_for` (`warehouse_canonical.py:135-137`) — без потребител | PROVEN | resolved (#91 `700629f`/`a15b614`, PROVEN: собственото движение — по org + actor_id + ключ + действие + файл; `_markers_for` (`warehouse_canonical.py:136-142`) също с actor_id — друг потребител със същия ключ не е повтор) |
| FG-610 | low | #91 `35cc099` | отказите на освобождаването не са идемпотентни: два опита със същия ключ → две събития за отказ (одитът е извън `keyed_transaction`, `file_holders.py:340`) | PROVEN | resolved (#91 `a15b614`, PROVEN: отказът е запазеният отговор на ключа (`file_holders.py:340-353`) — 2 опита → еднакви 409, 1 събитие; `mark_pending` — маркерът се записва преди операцията, rollback при `BaseException`, защитен (`:251-269`) — отмяна между два файла → 0 маркера); бележка: отказан ключ остава 409 и след като маркерът остарее — нужен нов ключ |
| FG-570 | medium | #82 WH-REV-01 `d6de7db` | F-82-01 отказва самото сторно на приемане (физическото връщане), когато фактурата вече е платена над новото нето — „първо сторнирайте плащането“ (`service.py:2077-2096`, `credit_note_rule.py:35-38`) | PROVEN (поведение) / SUSPECTED (канон) | open (+ Krum) |
| FG-571 | medium | #82 `d6de7db` × #84 `e8be2b3` | проверката на #82 ползва суровото `invoice.total` и само отворените `expected_credit_notes`, а #84 — `adjusted_total`: след сливане второ сторно по платена фактура с регистрирано кредитно известие минава (72 ≥ 72), одобрено дебитно известие дава фалшив отказ | SUSPECTED (пробно сливане с конфликти) | partial (#84 `ebcac7f9`: на #84 сам — resolved, `payable_net`/`payable_until_credit_note` (`services/invoice_corrections.py:909, 919, 932`); след сливане с #82 — open, PROVEN на ръчно слято дърво `71a70779`: 120/72/48 + второ сторно 48 → 201 (очаквано 409); дебитно известие 20, платено 80, сторно 48 → фалшив 409; проверката на #82 (`service.py:2088`) още ползва суровото `total` → при сливането `_expect_credit_note` да ползва `payable_until_credit_note` + тестове) |
| FG-572 | medium | #84 INV-CN-01 `e8be2b3` | анулиране (предложение/одобрение/отказ, `finance.py:1650, 1665, 1736, 1744, 1788, 1797`) и смяна на падежа след издаване (`:1119, 1121, 1186-1243`) — само legacy `finance_permission`, без Permission Service: в enforce с отнети роли Admin предлага анулиране → 200, Accountant сменя падежа → 200 | PROVEN | resolved (#84 `ebcac7f9`, PROVEN: `require_money_write` първа зависимост на `finance.py:1123, 1659, 1746, 1801`, действия в `catalog.py:237-242`; enforce с отнети роли → 403 и нищо не се записва; тесните правила (Accountant предлага, Owner одобрява, двама души) — еднакво в трите режима); quick-pay 201 с отнета роля — стар пропуск на main, извън FG-572 |
| FG-573 | low | #82 `d6de7db` (PM-01 `run_meta.json`) | `run_meta` казва 777 маршрута / 18648 клетки, а матрицата има 18696 = 779 маршрута (на #84 — поправено) | PROVEN | resolved (#82 `cd454eaa`, PROVEN: `run_meta.json` 779 маршрута / 18696 клетки = матрицата; само доказателства) |
| FG-574 | medium | OFF-02 #89 `58d0e40` | сливането запази `SEC-02/results.json` на main (176 проби), а кодът регистрира 188 — `test_the_committed_evidence_satisfies_the_package` пада („Right contains 12 more“, `POST /api/offers`) | PROVEN | resolved (OFF-02 `5763bd86`, PROVEN: `test_the_committed_evidence_satisfies_the_package` минава; PM-01 777/18648 = матрицата; само доказателства) |
| FG-480 | low | #83 CP-01 `a5176b2` | редът на пакета записва `payment_method` от заявката (по подразбиране „bank“), а регистърът — от сметката: аванс в брой е „bank“ в пакета и „Cash“ в регистъра | PROVEN | resolved (#83 CP-01 `b4a775f`, PROVEN: методът на реда на пакета — от сметката (`subcontractors.py:732-733, 1217-1219`); сметка банка + заявка „cash“ → `bank`/`Bank`; каса + „bank“ → `cash`/`Cash`) |
| FG-481 | low | #83 CP-01 `a5176b2` | проверките вървят преди replay-а по Idempotency-Key: повтор на изпълнен аванс след архивиране на подизпълнителя връща 422 вместо записаното 201 | PROVEN | resolved за аванса и плащането (#83 CP-01 `b4a775f`, PROVEN off/enforce: `completed_replay` (`money_input.py:184-213`) преди проверките (`subcontractors.py:660-670, 1150-1157`); повтор след архивиране → 201 със същия id; друго тяло → 409 IDEMPOTENCY_CONFLICT; ключът е изолиран по tenant (B → 404, подправен ред → None)); удръжката → FG-499 |
| FG-482 | medium | #83 CP-01 `a5176b2` | ДДС номер BG+ЕГН на клиент-фирма се показва изцяло на всички роли в `/clients/search/unified` (търсене и по цифрите на ЕГН), `/projects/{id}/client-info`, `/projects/{id}/invoice-context` | PROVEN | partial (#83 CP-01 `b4a775f`, PROVEN: `BG******1111` за всички 6 роли в unified search, client-info, invoice-context, `/companies`, find-by-eik, табло, `/projects`; търсене по цифрите на ЕГН — само Owner/Accountant; `POST /companies/{id}/vat/reveal` Owner/Accountant 200 + AuditEvent `company.vat_egn.revealed` само с маскираното, останалите 403); остатък → FG-496, FG-497, FG-498 |
| FG-483 | low | #83 CP-01 `a5176b2` | ДДС номер BG+ЕГН на контрагент е маскиран за всички, но няма одитирано разкриване — Owner/Accountant никога не го виждат | PROVEN (поведение) / SUSPECTED (канон) | resolved в кода (#83 CP-01 `b4a775f`, PROVEN: `POST /counterparties/{id}/vat/reveal` (`counterparties.py:234-240`) — Owner/Accountant 200, останалите 403, AuditEvent само с `BG******1111`); прочитът на канона — Krum |
| FG-484 | medium | #83 CP-01 `a5176b2` | README §18 и поправката в `gates_r65.txt` сочат `gates_r71.txt` като доказателство за пълния набор — файлът не съществува | PROVEN | resolved (#83 CP-01 `b4a775f`: `gates_r71.txt` съществува от `f91b423`; бройката не се възпроизвежда на натоварената машина — вероятно среда); същият проблем → FG-495 |
| FG-485 | medium | #84 `b0e72cf` (+ #81 в main) | Р69 не е изпълнено: Счетоводителят сам мести окончателно (100%) разпределение на входяща фактура към друг обект; при неплатена — без причина, версия и AuditEvent | PROVEN | open; планирано като отделна задача ALLOC-02 след сливането на #84 (оркестратор, 09.11.2026); не блокира #84. Прочит на текста на Р69 (потвърден от FLOW GUARD): важи за всяко окончателно разпределение — платено или неплатено |
| FG-486 | medium | #84 `b0e72cf` (+ main) | Р70 / D-04: ред на номерирана входяща фактура, свързан със складово приемане, се пренасочва към обект (200) без коригиращо изписване и без 409 | PROVEN (преместването) / SUSPECTED (двойният разход) | open; планирано в ALLOC-02. Прочит на Р70 (потвърден): редакцията на дестинацията сама прави коригиращото изписване след одобрението по Р69; без наличност → 409 |
| FG-435 | high | main `44e8d97` | официалният прогрес по СМР е ръчен субективен процент от всяка роля с M2, без одобрение/измерване/AuditEvent; Accountant задава `qty_executed` направо | PROVEN | open |
| FG-436 | medium | main `44e8d97` | прогресът на всеки обект се чете от не-членове (Viewer), с имената на въвелите | PROVEN | open |
| FG-437 | medium | main `44e8d97` | една крайна дата без baseline/план/прогноза/договорен срок; SiteManager я мести без причина/анекс/версия; фазите без одит и с hard delete | PROVEN | open |
| FG-438 | medium | main `44e8d97` | два различни плана за човекочасове на едно СМР (55.6 ч срещу 40 ч) | PROVEN | open |
| FG-439 | medium | main `44e8d97` | 28 ч на ден по две СМР за един работник се приемат и одобряват само с предупреждение | PROVEN | open |
| FG-440 | medium | main `44e8d97` | графикът по FLOW-027 не е реализиран: няма зависимости/критичен път, готовност, най-късна дата, напомняния, delay events | SUSPECTED | open |
| FG-441 | low | main `44e8d97` | таблото на обекта: „Изминало/Оставащи“ дни са празни (несъвпадащи имена на полета) | SUSPECTED | open |
| FG-450 | low | #84 `f6e0c90` | `dq_issues` с две форми на записа: #81 `type`/`owner_role`/`resolved` + аларма; #84 `kind`/`assignee_role`/`closed`, без аларма | PROVEN | resolved (#84 `b0e72cf`, PROVEN: една схема на `dq_issues` (`invoice_corrections.py:367-440`), стари записи 0) |
| FG-451 | low | #84 `f6e0c90` | обект без поле `status` се третира като изтрит при одобрението (а `projects.py:286` — като Draft); предложение за ред без разпределение се одобрява и осчетоводява разход без обект | PROVEN | open |
| FG-452 | low | #84 `f6e0c90` | значката за одобрение на Собственика не показва причината (приключен обект / друго място) и статуса; при връщане към разпределение — „обект “ без име | PROVEN (код) | open |
| FG-453 | medium | #84 `f6e0c90` | прихващанията погасяват входящи фактури без Р44 `ensure_payable` (след сливането с #81) | SUSPECTED | resolved по Р74 (#84 `b0e72cf`, PROVEN: `routes/invoice_corrections.py:909-926` — проверка при заявката и отново при одобрението в транзакцията; неразпределена 100% → 409 (`ensure_payable`); над тавана по Р47 → 409; одобрява само Owner, авторът не може (`:950`); `claim_invoice` сериализира офсет/сторно/преразпределение) |
| FG-454 | low | #84 `f6e0c90` | 9 mongomock варианта в набора на #81 са червени след сливането (`auth_tx` без резервен път без транзакции); реалният Mongo минава | PROVEN | resolved (#84 `b0e72cf`, решение на оркестратора: номерираните потоци на #81 — само реален Mongo; 129/129, без реален Mongo 60 passed / 69 skipped / 0 failed) |
| FG-455 | low | #83 CP-01 `7750f4e` | фактура с ЕГН само в полето `egn` минава проверката и одита по Р65, но PDF-ът не печата ЕГН (етикет „ЕИК:“); AuditEvent се пише преди PDF-а да е създаден | PROVEN | resolved (#83 CP-01 `a5176b2`, PROVEN: PDF съдържа `ЕГН: 8001011234`; неуспешен PDF не пише одит) |
| FG-456 | low | #83 CP-01 `7750f4e` (+ main) | `/reports/turnover-by-counterparty` и `/api/counterparties` показват стар 10-цифрен ЕИК (ЕГН) изцяло на Admin/Owner/Accountant без одит | PROVEN (поведение) / SUSPECTED (канон) | open |
| FG-457 | medium | #83 CP-01 `7750f4e` | тест на SUB-ADV-01 от main (`test_a_fresh_real_mongo_run_follows_the_rules_in_every_mode`) е червен на #83 (CP-01 иска касов бон, setup-ът не е обновен); evidence `gates_r65.txt` твърди 0 нови провала | PROVEN | partial (#83 CP-01 `a5176b2`: тестът минава (9 passed), промяна само в setup-а; evidence сочи несъществуващ файл → FG-484) |


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

- **Тежест:** medium. **Статус:** resolved (#69 `7300864`, #71 `71f9bbe`; проход 6). **SUSPECTED.** README-то на PR-а го води като дълг SEC-01-D1.
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

- **Тежест:** low. **Статус:** resolved (#69, #70, #71 `71f9bbe`; проход 6). **PROVEN.**
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

- **Тежест:** low. **Статус:** resolved (#55 `f0d86ab`, проход 7). **PROVEN.**
- **Код (#55 `4a3d15c`):** `routes/warehouse_canonical.py:343-360`. Не-член получава 422 с `parent_project_id` в контекста вместо 403. Разкрива се само id на обект, без пари.
- **Решение:** промяна в кода — без родителя в грешката за неупълномощен, или първо проверката на правата.

## FG-56 — Р32: складовият работник не вижда единичните цени

- **Тежест:** medium. **Статус:** resolved по Р32 (#55 `81e412c`, проход 5). **PROVEN.**
- **Канон:** Р32: „складовият работник **може да вижда единичните цени на артикулите** в склада (приемане, наличност, история) и да въвежда единичната цена при приемане“.
- **Код (#55 `4a3d15c`):** `warehouse_canonical_queries.py:173-176` — `warehouse` не е във `FINANCE_VALUE_ROLES` и не е в `UNCHANGED_VALUE_ROLES` → `sees_values=False` и в трите режима. Въведената от него цена при приемане се маха от отговора.
- **Решение:** промяна в кода — добавка E към 5C-C26: единични цени в склада за `warehouse`, без финанси на обекти.

## FG-57 — `record_event` без уникалния индекс тихо разклонява веригата

- **Тежест:** low. **Статус:** resolved (#72 `8ac194a`, проход 6). **PROVEN.**
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

- **Тежест:** high. **Статус:** resolved (#55 `518aab4`, проход 6). **PROVEN** (×3 режима).
- **Канон:**
  - 5C-C26g / Р28: „a project-bound role acts only THROUGH a project“, еднакво в трите режима.
  - FLOW-002: „директен URL да заобикаля правата“.
  - CLAUDE.md §14.
- **Код (#55 `81e412c`):** `backend/app/services/warehouse_movements/legacy_gate.py:51-52` — `_projects_touched` добавя `inp.project_id` от тялото, дори ако никоя локация не е обект; `:80` пропуска проверката, щом списъкът не е празен.
- **Проба:** SiteManager, член на P1, прави QUARANTINE_ENTRY в централния склад `wh_1` с `project_id=P1`. Позволено, записан 1 ред под P1. Без `project_id` → 403 R28_PROJECT_REQUIRED.
- **Решение:** промяна в кода — обектите да се броят само от локациите; `project_id` в тялото без обектова локация → 422.

## FG-60 — неотфилтрирани четения показват количества на чужди обекти

- **Тежест:** medium. **Статус:** resolved (#55 `518aab4`, проход 6). **PROVEN** (×3 режима).
- **Канон:** C26f: „a project-filtered read … needs the in-date project relation“; FLOW-002 обхват по обект.
- **Код (#55 `81e412c`):** `routes/warehouse_canonical_queries.py:168` проверява връзката само когато е посочен обект; `:71-73` в off/shadow връща цялата фирма.
- **Проба:** SiteManager, който не е член, получава 403 на stock/history за P1, но 200 на `balance` и на `history` без филтър, а там има редове от P1. Само количества.
- **Решение:** решение на Крум — може ли SiteManager да вижда количествата на чужди обекти. Ако не — промяна в кода: четенията без филтър да се ограничат до обектите, където е член.

## FG-61 — приемане към обект с различен `project_id`

- **Тежест:** medium. **Статус:** resolved (#55 `518aab4`, проход 6). **PROVEN.**
- **Канон:** принципът от FG-38/FG-53 — обектът се определя от локацията; CLAUDE.md §14.
- **Код (#55 `81e412c`):** `services/warehouse_movements/service.py:1684-1696` връзва само **източника**.
- **Проба:** Owner приема от доставчик към P1 с `project_id=p-other` → позволено. Записът казва p-other, а наличността и разходът са на P1 (P1 = 107, p-other = 0).
- **Решение:** промяна в кода — дестинацията да се връзва по същия начин, различен → 422.

## FG-62 — складовият работник вижда пари на обекти в историята

- **Тежест:** low. **Статус:** resolved по Р34 (#55 `8025871`, проход 9). **SUSPECTED.**
- **Канон:** Р32: вижда единичните цени „в склада (приемане, наличност, история)“, но „не вижда финансите на обекти“.
- **Код (#55 `81e412c`):** историята показва стойности и на CONSUME_TO_SMR по обекти. Отговорът на командата (`routes/warehouse_canonical.py:136`) ползва правилото за склада.
- **Решение:** решение на Крум — стойността на влагане по СМР „единична цена в склада“ ли е или „финанси на обект“.

## FG-63 — Р31: броят на работниците не е за същия период като сумата

- **Тежест:** high. **Статус:** resolved (#71 `71f9bbe`, проход 6). **SUSPECTED** (проследено в кода, не е пуснато).
- **Канон:** Р31 / FLOW-037 §3.4: техническият ръководител вижда сумата по СМР, „без разбивка по човек, ставка …“.
- **Код (#71 `e6ea838`):**
  - `backend/app/permissions/money_write.py:395-417` (`project_labor_workers`) брои работниците за цялата история на обекта;
  - `/expected-actual?date_from&date_to` (`services/expected_actual.py:56-62`) смята `actual_cost` само за периода.
  - Ефект: период, в който е работил само един човек, показва неговото заплащане; изхарчено ÷ часове (часовете се виждат) = ставката му.
- **Решение:** промяна в кода — работниците да се броят в същия прозорец като сумата.

## FG-64 — акордната цена и количеството идват от отчета, който работникът попълва

- **Тежест:** high. **Статус:** resolved (#73 `c422cbd`, проход 6). **SUSPECTED** (проследено в кода).
- **Канон:** FLOW-028: „заработка = **одобрено измерено** количество × **договорена** единична цена труд“; CLAUDE.md §7.
- **Код (#73 `709815d`):**
  - `backend/app/services/report_normalizer.py:23` пренася `pay_type`, `approved_quantity` и `piece_rate` от редовете на отчета;
  - `labor_cost.py:93-99` (`resolve_piece_rate`) взема **първо** `line.piece_rate`, после договорената цена на пакета;
  - `PUT /daily-reports/{id}` (`daily_reports.py:242-264`) приема `day_entries` без валидация.
  - Ефект: всеки с M4 записва в чернова `piece_rate` и `approved_quantity`; след одобрение на отчета LAB-01 плаща точно това.
- **Решение:** промяна в кода — цената само от пакета/договора; одобреното количество само от стъпка за одобрение; полетата да се махат от входа на отчета.

## FG-65 — нищо не задава одобрено количество или акордна цена

- **Тежест:** high (оперативно). **Статус:** resolved по Р33 (LAB-02 `0c85678`, проход 9). **SUSPECTED.**
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

## FG-69 — `/movements` от подобект издава родителя

- **Тежест:** medium. **Статус:** resolved (#55 `f0d86ab`, проход 7). **PROVEN** (×3 режима).
- **Канон:** FLOW-002 (обхват; директен URL не заобикаля правата); решението по FG-55 — „един и същ 403 независимо от опита“.
- **Код (#55 `518aab4`):** `services/warehouse_movements/service.py:711-723` (почистването е само при грешка на свързването), `legacy_gate.py:76`, `routes/warehouse_canonical.py:147` (`_render_error`).
- **Проба:** SiteManager, който не е член, прави WRITE_OFF/CONSUME_TO_SMR от подобект на P2:
  - без `project_id` → 403 със `scope_id: p-c22` (родителят от базата);
  - грешно предположение → голо „permission denied“;
  - вярно → пълното съобщение по Р27/Р28.
- **Решение:** промяна в кода — при източник подобект един фиксиран отказ, който назовава само подадения подобект (както `/project-writeoff`).

## FG-70 — приемане на чужда доставка в свой обект

- **Тежест:** high. **Статус:** resolved (#55 `f0d86ab`, проход 7). **PROVEN** (×3 режима).
- **Канон:**
  - FLOW-009: склад → обект — „количеството се намалява от източника и увеличава в получателя“;
  - Р18: кредит само при приемане от получателя;
  - Р28: релация към всеки засегнат обект.
- **Код (#55 `518aab4`):**
  - `services/warehouse_movements/service.py:1584-1591`, `:1860-1866` — проверката на местоназначението при приемане (`_check_transfer_acceptance`) важи само за `TRANSFER_RULES`, не за DISPATCH_WAREHOUSE_TO_PROJECT;
  - `_projects_touched` не брои обекта на изпращането.
- **Проба:** член на P1 приема в P1 изпращане за P2 → ALLOWED, 1 ред, записът казва P1.
- **Решение:** промяна в кода — приемането влиза само в обекта на изпращането, а той се брои за засегнат. Пренасочване на доставка — отделно действие с одобрение, ако Крум го иска.

## FG-71 — роли, вързани с обект, не виждат централния склад

- **Тежест:** low. **Статус:** resolved по Р35 (#55 `8025871`, проход 9). **SUSPECTED** (вероятно умишлено).
- **Канон:** Р20 позволява количества на не-финансовите роли; FLOW-020 — техническият ръководител заявява материали.
- **Код (#55 `518aab4`):** балансът и историята на `wh_1` → 403 или празно за SiteManager и PM.
- **Решение:** решение на Крум — вижда ли техническият ръководител количествата в централния склад (за заявки).

## FG-72 — два реда с едно id плащат акорда двойно

- **Тежест:** high (скрито, но пари). **Статус:** resolved (#73 `00324ab`, проход 7). **PROVEN.**
- **Канон:**
  - FLOW-028: „заработка = одобрено измерено количество × договорена единична цена“; „един отчетен ред … да бъде платен два пъти“ е забранено;
  - CLAUDE.md §8: Approval сочи към точна версия.
- **Код (#73 `c422cbd`):**
  - `routes/daily_reports.py:253-275` (`_clean_day_entries`) приема два реда с едно id;
  - `services/labor_cost.py:383` намира одобрението по id на реда → и двата реда го ползват;
  - `/reset` не анулира одобренията на количество.
- **Проба:** едно одобрение 24 м² × 5 → платено 240 вместо 120.
- **Решение:** промяна в кода — уникални id на редовете; одобрението вързано към версия/hash на отчета; анулиране при reset.

## FG-73 — всеки редактира чужда чернова на отчет

- **Тежест:** medium. **Статус:** resolved по Р36 (#73 `ca81286`, проход 9). **PROVEN.**
- **Канон:** FLOW-019 (реалният труд — от одобрени отчети на човека); FLOW-002; CLAUDE.md §14 (permission check).
- **Код (#73 `c422cbd`; същото на main):** `routes/daily_reports.py:281-289` `update_daily_report` — само `require_m4` и статус DRAFT/REJECTED, без проверка на собственика.
- **Проба:** Technician сменя черновата на друг служител от 8 ч на 0.5 ч → 200.
- **Решение:** промяна в кода — редактира само собственикът или одобряващ с право за обекта; AuditEvent.

## FG-74 — колега без разход разкрива ставката

- **Тежест:** medium. **Статус:** resolved (#71 `dee0610`, проход 7). **PROVEN.**
- **Канон:** Р31 / FLOW-037 §3.4 — без разбивка по човек и ставка.
- **Код (#71 `71f9bbe`):** правилото „2+ работници“ брои и работници с нулев разход (`permissions/money_write.py:452`, `finance_read.py:428`).
- **Проба:** СМР „Боя“ — wA (8 ч, 120) и wC (8 ч, разход 0, без ставка). SiteManager вижда 120; знае 8-те часа на wA от одобрението → ставка 15.
- **Решение:** промяна в кода — да се броят само работници с разход > 0, или сумата да се крие, когато един човек носи целия разход.

## FG-75 — `PUT /price-modifiers` без AuditEvent

- **Тежест:** medium. **Статус:** resolved (#71 `dee0610`, проход 7). **PROVEN.**
- **Канон:** CLAUDE.md §14: AuditEvent на всеки consequential write; FLOW-040 §4.2 (финансови действия).
- **Код (#71 `71f9bbe`):** `routes/price_modifiers.py:107` — `price_modifiers_config` +1, 0 audit реда.
- **Решение:** промяна в кода — AuditEvent с before/after. Логично е в SEC-01 (#69), където е guard-ът.

## FG-76 — две числа за „изхарчено“

- **Тежест:** medium. **Статус:** resolved (#73 `00324ab`, проход 7). **SUSPECTED.**
- **Канон:** Р31: „изхарчено“ = реален трудов разход от **одобрени** отчети по типа заплащане. LAB-01: „Pay Run и „изхарчено“ дават едно число“.
- **Код:** `/expected-actual` (#71 `71f9bbe`) сумира `work_sessions.labor_cost` (часове × ставка, `daily_reports.py:403`), включително за акорд, и не ползва общата функция на LAB-01 (#73). След merge на двата PR-а се виждат две различни числа.
- **Решение:** промяна в кода — expected-actual през общата функция на LAB-01. Оркестраторът решава дали е в #71 или #73.

## FG-77 — режийни: изтриване и презаписване без версия

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-024 „Правила за разпределение“: „Системата пази: метода; периода; базата; източника на данните; **версията**; разпределената сума; остатъка“;
  - CLAUDE.md §2.9: без hard delete на финансови записи; §7: reversal/correction вместо редакция.
- **Код (main `35ae10b`):**
  - `backend/app/routes/overhead.py:224-232` `DELETE /overhead/costs/{id}` и `:127-135` `/categories/{id}` → `delete_one`, само legacy `log_audit`, без проверка дали записът е разпределен;
  - `:443-462` `POST /overhead/snapshots/{id}/allocate` трие предишните разпределения (`delete_many`) и пише нови — старата версия изчезва, а P&L на обектите се сменя тихо.
- **Решение:** промяна в кода — архивиране/сторно вместо изтриване на използван разход; нова версия на разпределението със запазена предишна и AuditEvent.

## FG-78 — `PUT /technician/draft/{id}` без проверка на собственика

- **Тежест:** high. **Статус:** resolved (#73 `c4ddd33`, проход 8). **PROVEN.**
- **Канон:** FLOW-019 (реалният труд — от одобрени отчети на човека); FLOW-002; CLAUDE.md §14; решението по FG-73 (само собственикът).
- **Код (#73 `00324ab`; същото на main):** `backend/app/routes/technician.py:1379` `update_draft` проверява само логин и статус Draft/Submitted.
- **Проба:** техник сменя черновата на tech2 от 8 ч на 0.5 ч и вида СМР → 200; после подадения му отчет на 12 ч → 200.
- **Решение:** промяна в кода — проверка на собственика, както в `PUT /daily-reports`; анулиране на одобренията.

## FG-79 — `batch-save` пренаписва одобрен отчет

- **Тежест:** high. **Статус:** resolved (#73 `c4ddd33`, проход 8). **PROVEN.**
- **Канон:**
  - CLAUDE.md §8: „Approval винаги сочи към exact version“;
  - FLOW-028 „Корекции“: без тихо редактиране;
  - FLOW-019: „неодобрен отчет да влиза в официалния разход“ е забранено.
- **Код (#73 `00324ab`; същото на main):** `backend/app/routes/daily_reports.py:974-1030` `POST /daily-reports/batch-save` няма проверка на статус или собственик и пише `update_one` върху съществуващия отчет.
- **Проба:** техник сменя ОДОБРЕНИЯ отчет на tech2 от 8 ч на 14 ч → остава `approval_status=APPROVED`, версия 1.
- **Решение:** промяна в кода — одобрен отчет се отказва (или се връща за ново одобрение); записва само собственикът или одобряващ.

## FG-80 — една надплата дава корекция на всеки Pay Run

- **Тежест:** medium. **Статус:** resolved (#73 `ca81286`, проход 9). **PROVEN.**
- **Канон:** FLOW-028: един отчетен ред се плаща/коригира веднъж; Р29 / CLAUDE.md §14: idempotency.
- **Код (#73 `00324ab`):**
  - `backend/app/services/payroll_corrections.py:43` — ключ на корекцията (Pay Run, служител);
  - повторен `POST /pay-runs` със същия Idempotency-Key създава втори run.
- **Проба:** три run-а за един период → три корекции по 600 за една надплата от 600.
- **Решение:** промяна в кода — ключът да е самата надплата (служител, период, плащания); Idempotency-Key да се спазва. Решение на Крум дали чернова на run изобщо създава корекции.

## FG-81 — работник с 0.01 € отключва сумата по СМР

- **Тежест:** low. **Статус:** resolved по Р42 (проход 13). **SUSPECTED.**
- **Код (#71 `dee0610`):** `permissions/money_write.py:536` — „платен“ = `round(v,2) != 0`. Втори работник с 0.01 € прави сумата видима, а тя е почти заплащането на първия.
- **Решение:** решение на Крум за праг, или сумата да се крие, когато един човек носи ≥ X% от нея.

## FG-82 — AuditEvent след бизнес записа, без транзакция

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-040; CLAUDE.md §14 (domain transaction + AuditEvent).
- **Код:** `routes/price_modifiers.py` PUT (#71 `dee0610`) и `services/payroll_corrections.py` `_audit` (#73 `00324ab`) пишат събитието след записа, отделно. Грешка в одита оставя записа без одит.
- **Решение:** промяна в кода — транзакция или outbox.

## FG-83 — повторно разпределение на фактурен ред без версия

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-020: всеки ред има дестинация; разпределението е проследимо;
  - FLOW-006 „Какво НЕ трябва“: „разпределение към обект без проследимост“;
  - CLAUDE.md §7: reversal/correction вместо директна редакция.
- **Код (main `35ae10b`):** `backend/app/routes/invoice_lines.py:549-600` `POST /invoice-lines/{id}/allocate` — „Replaces ALL existing allocations“. Проверява права и количество, но не статуса на фактурата (Sent/Paid) и не пази предишното. След 5C-C26 (#55) Път Б чете тези разпределения, така че разходът на обект за минал период се сменя тихо. Пише само legacy `log_audit`.
- **Решение:** промяна в кода — за фактура извън Draft или вече призната като разход: нова версия на разпределението с причина и AuditEvent, старата с `superseded_by`. Решение на Крум дали изобщо се разрешава след приключен период.

## FG-84 — надплатата се коригира втори път при по-широк период

- **Тежест:** high. **Статус:** resolved (#73 `ca81286`, проход 9). **PROVEN.**
- **Канон:** FLOW-028: един отчетен ред се плаща/коригира веднъж; „платено повече от заработеното/одобреното без корекция/Approval“ е забранено.
- **Код (#73 `c4ddd33`):** `backend/app/services/payroll_corrections.py:43` — ключът е (служител, точно `period_start..period_end`).
- **Проба:** Pay Run за 2 седмици, който покрива вече платената седмица → втора корекция 600; два записа `pending`.
- **Решение:** промяна в кода — ключът да е по платените редове/източника, или проверка за застъпващи се периоди.

## FG-85 — едновременни POST /pay-runs с един ключ

- **Тежест:** high. **Статус:** resolved при merge с #72 (проход 9). **PROVEN.**
- **Канон:** Р29; CLAUDE.md §14 (idempotency key).
- **Код:** на #73 `c4ddd33` (база main) `app/audit/idempotency.py:95-98` е check-then-insert без уникален индекс (docstring-ът на `:24` твърди обратното).
- **Проба:** 6 едновременни POST с ключ „race“ → 4 × 200, 4 run-а, 4 idempotency записа.
- **Поправката вече съществува:** #72 `8ac194a` добавя `ensure_idempotency_index` (`idempotency.py:57`, извиква се от `begin_idempotent` на `:105`).
- **Решение:** процес — #72 да се слее **преди** #69, #70, #73 и OH-01 (или да се влее в тях), и пробата да се пусне отново.

## FG-86 — два snapshot-а за един период → двойни режийни

- **Тежест:** high. **Статус:** resolved (OH-01 `6c5c5cf`, проход 9). **PROVEN.**
- **Канон:** FLOW-024: „Режийните не трябва … да се броят два пъти“.
- **Код (OH-01 `09409f0`):** `backend/app/routes/overhead.py:434`, `:521` — всеки snapshot се разпределя отделно, а версиите са само в рамките на един snapshot.
- **Проба:** два snapshot-а за един и същ период → режийни в P&L 862 = 2 × 431.
- **Решение:** промяна в кода — един активен snapshot на период; новият замества стария (`superseded_by`).

## FG-87 — тиха промяна на използван режиен разход

- **Тежест:** medium. **Статус:** resolved (OH-01 `6c5c5cf`, проход 9). **PROVEN.**
- **Канон:** CLAUDE.md §7 (корекция, не директна редакция); FLOW-024 (пази базата, източника, версията).
- **Код (OH-01 `09409f0`):**
  - `PUT /overhead/costs/{id}` (`overhead.py:307`) сменя сумата на използван разход на 99999 → 200, 0 AuditEvent, без ключ;
  - смяна на датата извън периода + DELETE → архивиран, т.е. обход на 409;
  - PUT на архивирана категория → 200;
  - същото в PUT категория (`:205`) и актив (`:397`).
- **Решение:** промяна в кода — 409 или корекционен поток за използвани и архивирани; ключ и AuditEvent.

## FG-88 — `POST /overhead/snapshots/compute` без ключ

- **Тежест:** medium. **Статус:** resolved (OH-01 `6c5c5cf`, проход 9). **PROVEN.**
- **Канон:** Р29: „запис на пари без `Idempotency-Key` се отказва … и за бъдещите“.
- **Код (OH-01 `09409f0`):** `/overhead/snapshots/compute` не е в списъка на пакета; без ключ → 200.
- **Решение:** промяна в кода — Р29 и тук.

## FG-89 — втори път за режийни без версия

- **Тежест:** high (повишено в проход 10: нетната печалба чете `project_overhead_alloc`, `full_cost.py:345`). **Статус:** resolved (OH-01 `45178ac`, проход 11). **SUSPECTED.**
- **Канон:** FLOW-024 (един метод с версия, без двойно броене); CLAUDE.md §16 (без втори source of truth).
- **Код (main и OH-01):**
  - `backend/app/routes/full_cost.py:185-250` `POST /overhead-allocation/compute/{project_id}` прави upsert в `project_overhead_alloc` (без версия, без AuditEvent, без ключ, само `require_m2` на main);
  - чете се от `revenue_expense.py:522`, `revenue_snapshot.py:146`, `full_cost.py:345`;
  - не стига до `project_pnl`, така че P&L не се удвоява, но има второ число за режийните на обекта.
- **Решение:** решение на Крум/оркестратора кой път е каноничен; другият да чете от него или да отпадне.

## FG-90 — плащане към подизпълнител без таван спрямо актуваното

- **Тежест:** medium. **Статус:** resolved (#69 `ccab244`, проход 10). **SUSPECTED** (четене).
- **Канон:**
  - FLOW-021 „Какво НЕ трябва“: „плащане над измереното без Approval“, „аванс без прихващане/остатък“, „фактура без връзка към пакет/акт“;
  - FLOW-021: „Остатъкът за задължения и плащания се смята от одобреното измерено количество“.
- **Код:** main `0f870c3` `backend/app/routes/subcontractors.py:493-530` и #69 `7300864` (същият handler с money guard). Проверява се само сума > 0 и съществуващ пакет; `act_id` е по избор; няма сравнение с `payable_total`/`certified_total` на пакета. Плащане без акт е неявен аванс без прихващане.
- **Решение:** промяна в кода — плащане ≤ актуваното и неплатено, или изрично „аванс“ с прихващане към следващ акт; надвишаване само с Approval (W0-07; дотогава отказ).

## FG-91 — платен отчет в стар формат се поправя на място

- **Тежест:** high. **Статус:** resolved (#73 `3107ba0`, проход 10). **PROVEN.**
- **Канон:**
  - FLOW-028 „Корекции след плащане“: „Няма тихо редактиране“;
  - Р36: поправка с пълна следа; `report_corrections.py:11-13` обещава 409 за платен отчет.
- **Код (#73 `ca81286`):** `services/payroll_sync.py:106,116,148` маркира отчетите като batched/paid само по `worker_id`/`date`. Отчетите в стар формат (`employee_id`/`report_date`) не получават `payroll_status`, затова заключването в `report_corrections.py:34` не се задейства.
- **Проба:** след mark-paid старият отчет е с `payroll_status=null`; Admin PUT → 200, 8 ч → 0 ч, APPROVED → SUBMITTED. Следващият run вдига вземане 100 (парите не са тихи), но платеният отчет е променен.
- **Решение:** промяна в кода — sync да маркира и стария формат, или заключването да гледа редовете на платените run-ове.

## FG-92 — поправящият одобрява собствената си поправка

- **Тежест:** high. **Статус:** resolved (LAB-02 `ba08ab5`, проход 10). **PROVEN** (и в пълния пробен merge).
- **Канон:** FLOW-002 „Двустепенно одобрение“: „корекция на платен отчет“; „Един човек не може да изпълни и двете стъпки“. CLAUDE.md §8; LAB-01-I.
- **Код (LAB-02 `0c85678`):**
  - `backend/app/routes/labor_quantities.py:239-269` (`/labor-quantities/entry`) не вика `correction_fields`/`reopen_effects` — отчетът остава APPROVED;
  - `:150-160` проверява самоодобрение само срещу `worker_id`, не срещу `self_approval_ids` (поправил/подал).
- **Проба:** SM сменя количеството на 800 и сам го одобрява → 200, заработено 7200. SM, който е подал отчета (`submitted_by`), го одобрява → 200.
- **Решение:** промяна в кода — поправката минава през reopen на LAB-01-I; одобряващият ≠ работник, подал и поправил.

## FG-93 — одобрение и класификация на платен ред

- **Тежест:** high. **Статус:** resolved (LAB-02 `ba08ab5`, проход 10). **PROVEN.**
- **Канон:** FLOW-028 „Корекции след плащане“; CLAUDE.md §7.
- **Код (LAB-02 `0c85678`):** `labor_quantities.py:338-343` (approve) и `:409-414` (classify) нямат проверка `PAYROLL_LOCKED`. Въвеждането (`entry`) правилно връща 409.
- **Проба:** на платен ред approve → 200 (анулира платеното одобрение, количество 10); classify → 200.
- **Решение:** промяна в кода — `PAYROLL_LOCKED` и там; промяната на платено минава като корекция по FLOW-028.

## FG-94 — класификация като престой на чернова

- **Тежест:** low. **Статус:** resolved (LAB-02 `ba08ab5`, проход 10). **PROVEN.**
- **Код (LAB-02 `0c85678`):** `labor_quantities.py:409-414` няма проверка на статуса → 200 на ред в Draft.
- **Решение:** промяна в кода — само подаден/одобрен отчет, както при approve.

## FG-95 — ред на merge: #72 → #73 → LAB-02

- **Тежест:** medium. **Статус:** open (процес). **PROVEN.**
- **Канон:** Р29; Р33 („LAB-01 се качва заедно с LAB-02“); CLAUDE.md §8.
- **Факти:**
  - LAB-02 стъпва на `6763970` и не съдържа `ca81286` (LAB-01-I — без самоодобрение чрез поправка);
  - без #72: 6 паралелни approve с един ключ → **4** одобрения; с #72 → 1;
  - пробен merge #72 + #73 + LAB-02 → 105 passed.
- **Решение:** процес — merge в реда #72 → #73 (с LAB-01-I) → LAB-02, и пробите отново след всеки.

## FG-96 — складовият работник вижда стойността на фира от централния склад

- **Тежест:** medium. **Статус:** resolved по Р37 (#55 `4ed6077`, проход 10). **PROVEN.**
- **Канон:** Р34: складовият работник „**не вижда** стойността на изписаното към обекти **и на фирата** — само количества“.
- **Код (#55 `8025871`):** `_value_visible` в `routes/warehouse_canonical_queries.py` пуска ред, чиято единствена локация е централният склад. Фира от централния склад показва `unit_value 7.0000` на складовия работник; фирата от обект е скрита.
- **Решение:** решение на Крум — „фирата“ в Р34 включва ли и фира в самия склад. Ако да — промяна в кода: без стойност на всеки WRITE_OFF за складовия работник.

## FG-97 — режийните в P&L падат на 0 между изчисление и преразпределение

- **Тежест:** low. **Статус:** resolved по Р38 (OH-01 `6a4ac5b`, проход 10). **PROVEN.**
- **Канон:** FLOW-024 (версия на разпределението; отчетът показва какво е включено).
- **Код (OH-01 `6c5c5cf`):** `overhead.py` `_supersede_previous` маркира старите разпределения като заменени още при новото изчисление. P&L: 431 → 0 → 431 след allocate. `project_financial_results.py:227` тогава минава към приблизителна оценка (SUSPECTED).
- **Решение:** решение на Крум — замяната да е при разпределение на новата версия, или да се показва „чака преразпределение“.

## FG-98 — съществуващите tenant бази без индексите на OH-01

- **Тежест:** low. **Статус:** resolved (OH-01 `6a4ac5b`, проход 10). **SUSPECTED.**
- **Канон:** CLAUDE.md §3: migration runner с per-tenant lock, schema version, idempotency.
- **Код (OH-01 `6c5c5cf`):** индексите се създават при старт само за базата по подразбиране (`server.py`) и при onboarding.
- **Решение:** промяна в кода — стъпка за всички tenant бази (както #72 прави с `ensure_audit_indexes_for_installation`).

## FG-99 — `reset` на отчет заобикаля заключването за платено

- **Тежест:** high. **Статус:** resolved (#73 `4da2ee6`, LAB-02 `ef16a16`; проход 11). **PROVEN** (на `3107ba0` и `ba08ab5`).
- **Канон:** FLOW-028 „Корекции след плащане“: „Няма тихо редактиране“; Р36 (пълна следа); CLAUDE.md §14 (AuditEvent).
- **Код:** `backend/app/routes/daily_reports.py:636-645` (LAB-02 `ba08ab5`; `:625-634` на #73). Проверката гледа само `report.get("date")` (стар формат има `report_date`) и само платени run-ове, не потвърдени. Записът на `:680` е без AuditEvent и без `refuse_if_in_payroll`.
- **Проба:**
  - отчет в стар формат в ПЛАТЕН run → reset 200, SUBMITTED, `approved_by` null, 0 AuditEvent;
  - отчет в нов формат в ПОТВЪРДЕН run → reset 200, одобренията 1 → 0; после run-ът е маркиран като платен с ред в SUBMITTED.
- **Решение:** промяна в кода — `refuse_if_in_payroll` и в reset; AuditEvent за поправката.

## FG-100 — акордната цена се сменя от един човек

- **Тежест:** medium. **Статус:** resolved по Р41 (проход 11; канон → FG-107). **SUSPECTED.**
- **Канон:** FLOW-002 „Двустепенно одобрение“: „промяна на заплата или ставка … Един човек не може да изпълни и двете стъпки“.
- **Код (LAB-02 `ba08ab5`):** `routes/labor_quantities.py:231-272` `PUT /labor-terms` — един финансов потребител сменя акордната цена с една стъпка (версия и AuditEvent има, второ лице няма).
- **Решение:** решение на Крум — акордната цена по СМР „ставка“ ли е по FLOW-002. Ако да — второ одобрение (W0-07; дотогава ясно записан дълг).

## FG-101 — двама одобряващи на една версия

- **Тежест:** low. **Статус:** resolved (LAB-02 `ef16a16`, проход 11). **PROVEN.**
- **Код (LAB-02 `ba08ab5`):** `labor_quantities.py:400-420` — двама различни одобряващи получават 200 на една и съща версия; вторият тихо анулира първия (2 записа, 1 активен; одитът остава).
- **Решение:** промяна в кода — повторно одобрение на същата версия само като изрична корекция; иначе 409.

## FG-102 — няма път за аванс към подизпълнител

- **Тежест:** medium. **Статус:** resolved по Р39 (SUB-ADV-01 `f42da33`, проход 11). **PROVEN.**
- **Канон:** FLOW-021: „аванс без прихващане/остатък“ е забранено — т.е. аванс **с** прихващане е допустим; FLOW-008/006 показват аванси отделно.
- **Код (#69 `ccab244`):** `subcontractors.py:603-625` отказва всяка сума над актуваното (409 при 0 актувано). Плащания без `act_id` минават само в рамките на актуваното и не се връзват с акт.
- **Решение:** решение на Крум — авансите към подизпълнители отлагат ли се (W0-07), или се добавя запис „аванс“ с проследяване на прихващането.

## FG-103 — резервираната платена сума не се освобождава

- **Тежест:** high (повишено в проход 12: фантомен аванс след прекъсната заявка, SUB-ADV-01 `subcontractors.py:956`). **Статус:** resolved (SUB-ADV-01 `542fa2c`, проход 13). **SUSPECTED.**
- **Канон:** FLOW-006 (реверс); CLAUDE.md §7.
- **Код (#69 `ccab244`):** `subcontractors.py:607` — `committed_paid_total` само расте. Подизпълнителските плащания нямат сторно (FG-45 → 409). Прекъсната заявка след резервацията оставя сумата резервирана.
- **Решение:** промяна в кода — бъдещото сторно (INT-70x69) да освобождава резервацията; задача за поправка на висящи резервации.

## FG-104 — таванът е само по пакет

- **Тежест:** low. **Статус:** resolved по Р40 (проход 11). **PROVEN.**
- **Код (#69 `ccab244`):** плащане с `act_id` се ограничава само от общото за пакета; акт без актувана сума приема 10.
- **Решение:** решение на Крум — таван по акт или по пакет.

## FG-105 — `paid_total` до 200 плащания

- **Тежест:** low. **Статус:** resolved (#69 `3fb55f2`, проход 11). **SUSPECTED.**
- **Код (#69 `ccab244`):** `subcontractors.py:~650` преизчислява с `to_list(200)`.
- **Решение:** промяна в кода — агрегирана сума.

## FG-106 — клиентски акт: цена и количество от заявката

- **Тежест:** high (Р3: пари — приходи и фактуриране). **Статус:** open. **SUSPECTED** (четене).
- **Канон:** FLOW-004 „Какво НЕ трябва“:
  - „акт над договорения обхват при крайна цена“;
  - „различна единична цена в акт без анекс“;
  - „едно и също количество да се актува два пъти“;
  - „остатък количество = офертно количество − актувано количество“.
- **Код (main `0f870c3`):**
  - `backend/app/routes/revenue_expense.py:65-100` `POST /client-acts` — `unit_price` и `executed_qty` от тялото, `offer_line_id` по избор, без проверка спрямо офертния ред и вече актуваното;
  - `PUT /client-acts/{id}` (`:139-160`) — същото за Draft.
  - Защитата за остатък има само при подизпълнителските актове (`subcontractors.py:390`).
- **Решение:** промяна в кода — цената от офертния ред (или анекс); остатък по офертен ред; отказ при надвишаване (крайна цена) и при повторно актуване. Режимът „измерено количество“ — когато влезе FLOW-005.

## FG-107 — Р41 срещу FLOW-002 (двама за промяна на ставка)

- **Тежест:** low. **Статус:** resolved (FLOW-043 D-17, проход 12). **SUSPECTED** (решение срещу канон).
- **Канон:** FLOW-002 „Двустепенно одобрение“: „промяна на заплата или ставка … Един човек не може да изпълни и двете стъпки“. CLAUDE.md §18: заключен FLOW се променя само с решение на Крум, **записано в канона**.
- **Решение на Крум:** Р41 (07.11.2026): „акордната цена по СМР се променя от **един човек** от финансите, с версия и следа (AuditEvent); без втори потвърждаващ“. Кодът (LAB-02) е прав по Р41.
- **Защо е разминаване:** Р41 е в RECOVERY_EXECUTION_PROPOSAL, не във FLOW-043. Канонът и решението си противоречат, както беше при Р19 и D-16 (FG-33).
- **Решение:** Крум да запише Р41 като D-решение във FLOW-043 (тясно изключение от FLOW-002 за акордна цена по СМР). Кодът не се пипа.

## FG-108 — партида от фактурен ред се брои двойно (склад + пряко)

- **Тежест:** high. **Статус:** resolved (#55 `d98cead`, проход 12). **PROVEN.**
- **Канон:** FLOW-009 / FLOW-043 D-04: „Една и съща партида не може да стане разход и по двата пътя“; CLAUDE.md §7.
- **Код (#55 `43477d8`):** `backend/app/services/warehouse_movements/service.py:1747-1795` — проверката срещу разпределеното количество сумира само `RECEIVE_FROM_SUPPLIER_TO_PROJECT` (`:1788`), не и свързаните приемания в склада и последващото изпращане към обекта.
- **Проба:** ред L (10 @ 10) към P; 10 приети в склада с връзка → изпратени и приети на P (P = 100); после пряка свързана доставка от 10 на P → приета. P = **200**, без предупреждение.
- **Решение:** промяна в кода — проверката в транзакцията да брои всички свързани приемания на L. Ако Крум допуска надвишаване на доставката — изрично решение и DQ.

## FG-109 — фактурен ред се преразпределя след доставката

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** FLOW-020 (проследимо разпределение); D-04; свързано с FG-83.
- **Код:** `backend/app/routes/invoice_lines.py:550` (main / #55) — allocate не проверява съществуващи доставки и не взема lock-а на реда.
- **Проба:** доставка 10 на P → L преразпределен към Q → доставка 10 на Q → приета. P/Q = 100/100, `PATH_B_LINK_PROJECT_CONFLICT` и на двата.
- **Решение:** промяна в кода — 409 при доставен ред, или същият lock и проверка; заедно с FG-83.

## FG-110 — едновременни reset-и връщат бюджета няколко пъти

- **Тежест:** medium. **Статус:** resolved (#73 `41a43b5`, LAB-02 `f0a0757`; проход 12). **PROVEN.**
- **Канон:** CLAUDE.md §14 (idempotency, domain transaction); FLOW-019.
- **Код:** `routes/daily_reports.py:~668/693` (#73 `4da2ee6`), `:679/704` (LAB-02 `ef16a16`) — смяната на статуса не проверява, че отчетът още е APPROVED; без транзакция.
- **Проба:** 4 паралелни reset → 4 × 200, 4 AuditEvent; `consumed_hours` 40 → 24 (#73) и 40 → 8 (LAB-02), вместо 32.
- **Решение:** промяна в кода — условна смяна на статуса (`approval_status: APPROVED` във филтъра); продължава само при реална промяна.

## FG-111 — `/alarms` показва % на бюджета на всички роли

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** Р20 / Р31 (не-финансовите роли — без пари).
- **Код (#71 `5af530e`):** `routes/alarms.py:52,86,128` без обвивката на SEC-02 и без ред във `FINANCE_READS`; текстът идва от `services/alarm_engine.py:91`.
- **Проба:** Technician, Viewer и SM получават „бюджет 900.0% изхарчен“ и `metric_value` 900.
- **Решение:** промяна в кода — `/alarms` в регистъра на SEC-02.

## FG-112 — reset издава дали отчетът съществува

- **Тежест:** low. **Статус:** resolved (проход 12). **PROVEN.**
- **Канон:** deny by default; без oracle (PM73-01).
- **Код:** `services/report_corrections.py` — проверката за заплати е преди проверката на ролята; различен текст за съществуващ/липсващ отчет.
- **Проба:** SM на друг обект — съществуващ → 403 с един текст; липсващ → 403 с друг; в заплати → 409.
- **Решение:** промяна в кода — първо роля; един и същ 403.

## FG-113 — SUB-ADV-01 не е от head-а на #69

- **Тежест:** medium. **Статус:** resolved (SUB-ADV-01 `17aa55d`, проход 12). **PROVEN.**
- **Канон:** пакетът SUB-ADV-01: „нов клон от неговия head“; Р29; FG-105.
- **Факт:** merge-base е `ccab244`, не `3fb55f2`. Губят се добавка E (`_refresh_package_totals` с `.to_list(1000)` — `subcontractors.py:707` @ `f42da33`) и добавка F (retry на резервацията — пътят на приспадането е без защита).
- **Решение:** rebase върху `3fb55f2`; сума в базата; id на резервацията и при приспадането.

## FG-114 — аванс без горна граница

- **Тежест:** medium. **Статус:** resolved (SUB-ADV-01 `17aa55d`, проход 12). **PROVEN.**
- **Канон:** FLOW-021: „плащане над измереното без Approval“ е забранено; Р39 разрешава аванс, но не определя граница.
- **Код (SUB-ADV-01 `f42da33`):** `subcontractors.py:847` — аванс 1 000 000 по пакет с договор 5 000 → 201, без Approval.
- **Решение:** решение на Крум — таван до остатъка по договора, или Approval над праг.

## FG-115 — авансът влиза в P&L преди изпълнение

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-008: „Авансът не е печалба“ (огледално — даденият аванс не е разход до изпълнение); показва се отделно.
- **Код (SUB-ADV-01 `f42da33`):** `services/project_pnl.py:94`, `project_financial_results.py:88` сумират `subcontractor_payments` без да изключват `kind:"advance"`.
- **Решение:** решение на Крум — P&L без аванси (или само приспаднатата част); авансът отделен ред.

## FG-116 — „преизчислява се“ липсва в новите четения

- **Тежест:** low. **Статус:** resolved (OH-01 `997abdc`, проход 12). **PROVEN.**
- **Канон:** Р38: P&L показва старото разпределение „с етикет „преизчислява се““.
- **Код (OH-01 `45178ac`):** `project-net-profit`, `project-profit` и `profit-by-period` (`full_cost.py:310`, `revenue_expense.py:525`) не връщат флага.
- **Решение:** промяна в кода — `recalculating` и в тези отговори.

## FG-117 — името на tenant базата в грешките на индексите

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-040 §9 (data minimization).
- **Код (#72 `cb5d061`):** `audit/indexes.py:64,279` — `AuditIndexError` съдържа името на базата (`begwork_tenant_{slug или org id}`).
- **Решение:** решение на Крум дали името на базата е допустимо в лог; иначе hash.

## FG-118 — допълнително СМР без „кой плаща“

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене).
- **Канон:** FLOW-007 „Кой плаща“: „клиент / инвеститор, BEG, подизпълнител, доставчик, гаранция, за уточняване. Без определено финансово третиране СМР не може да стане окончателно платимо“; „ново СМР да се изпълни без ясно кой плаща“ е забранено.
- **Код (main `0f870c3`):** `backend/app/routes/extra_works.py:172-250` (чернови) и `:442-550` (допълнителна оферта) — няма поле за платеца/финансовото третиране. Допълнителната оферта може да стане приета и да се актува (FLOW-004) като клиентско СМР, дори когато реално е за сметка на BEG, подизпълнител или гаранция.
- **Решение:** промяна в кода — задължително „кой плаща“ при приемане на допълнителна оферта; само „клиент“ влиза в клиентски акт. Логично е в Wave 1 заедно с ACT-01.

## FG-119 — потвърждаване на клиентски акт от всяка роля

- **Тежест:** high. **Статус:** resolved (ACT-01 `8188689`, проход 13). **PROVEN** (на ACT-01).
- **Канон:**
  - FLOW-004: „стар акт да се редактира тихо след одобрение“ е забранено;
  - Р14/Р20 (парични действия само за финансови роли); Р29; CLAUDE.md §14.
- **Код (ACT-01 `c6c7f1c`, база main):** `backend/app/routes/revenue_expense.py:143-161` — само `require_m2`, без Idempotency-Key, без транзакция, само legacy `log_audit`, без проверка на версията.
- **Проба:**
  - Viewer → 200, актът става Accepted, 0 canonical AuditEvent;
  - чернова на акт по заменена v1 също се потвърждава.
- **Бележка:** #69 (`3fb55f2`) вече слага `require_money_write` на този route (FG-30), но без ключ, AuditEvent и проверка на версията.
- **Решение:** промяна в кода — на потвърждаването същото като при създаване: guard, ключ, транзакция, AuditEvent, проверка на версията. При merge ACT-01 + #69 да не се загуби guard-ът.

## FG-120 — „остатък“ събира два тавана

- **Тежест:** medium. **Статус:** resolved (ACT-01 `8188689`, проход 13). **PROVEN.**
- **Канон:** FLOW-004 „остатък = офертно − актувано“; ACT-01 добавка A: „не сумирай два тавана“; FLOW-003 (новата версия заменя старата).
- **Код (ACT-01 `c6c7f1c`):** `services/client_acts.py:505-526` (`remaining_for_project`) показва v1 с остатък 4 и v2 с остатък 12 за един обхват от 12 → 16 вместо 6.
- **Решение:** промяна в кода — само последната приета версия, или обхватът маркиран „блокиран“, докато няма родословие ред → ред.

## FG-121 — закръгляне на единичната цена губи пари

- **Тежест:** medium. **Статус:** resolved (ACT-01 `8188689`, проход 13). **PROVEN.**
- **Канон:** FLOW-004: „различна единична цена в акт без анекс“ е забранено.
- **Код (ACT-01 `c6c7f1c`):** `services/client_acts.py:117-120` (`offer_unit_price`) закръгля до 2 знака преди умножението. Ред 1000 × 1.234 (1234.00) → акт за цялото количество 1230.00.
- **Решение:** решение на Крум за правилото за закръгляне; промяна в кода — цената на офертата без закръгляне, или общото за цялото количество = сумата на офертния ред.

## FG-122 — цените на актовете се виждат от Viewer

- **Тежест:** medium. **Статус:** resolved (ACT-01 `8188689`, проход 13). **PROVEN.**
- **Канон:** Р20 (не-финансовите роли — без пари).
- **Код (main / ACT-01 `c6c7f1c`):** `routes/revenue_expense.py:85,109` `GET /client-acts` и `/{id}` → 200 с единични цени за Viewer; `/remaining` правилно дава 403.
- **Решение:** промяна в кода — същият финансов guard или скрити цени. Проверете и в SEC-02 (#71).

## FG-123 — акт по v1 в момента на приемане на v2

- **Тежест:** low. **Статус:** resolved (ACT-01 `8188689`, проход 13). **SUSPECTED.**
- **Код (ACT-01 `c6c7f1c`):** проверката на версията е в транзакцията на акта, но приемането на v2 пише извън нея.
- **Решение:** промяна в кода — общ lock/брояч на обхвата при приемане на версия.

## FG-124 — заключването на разпределението се заобикаля през старото поле

- **Тежест:** medium. **Статус:** resolved (#55 `94c0571`, проход 13). **PROVEN.**
- **Канон:** FLOW-020 (проследимо разпределение); FG-109.
- **Код (#55 `d98cead`):** `backend/app/routes/invoice_lines.py:41` — `LOCKED_WHEN_LINKED` не включва `allocation_type` и `allocation_ref_id`, които `effective_allocations` още чете.
- **Проба:** ред само със старото разпределение, доставен със връзка в P → `PUT allocation_ref_id=Q` → 200; редът сочи Q. Сумите остават P/Q 100/0 с `PATH_B_LINK_PROJECT_CONFLICT` — без двойно броене, но заключването не държи.
- **Решение:** промяна в кода — двете полета в списъка за заключване.

## FG-125 — `/alarm-rules` показва прага на всички

- **Тежест:** medium. **Статус:** resolved по Р20 / добавка G (проход 13). **PROVEN.**
- **Канон:** Р20 / Р31.
- **Код (#71 `e90aa5f`):** `routes/alarms.py:203` — без махане на парите. Technician и Viewer виждат `condition.threshold=80`, „Бюджет над 80%“.
- **Решение:** промяна в кода — условието и името скрити за не-финансови роли, или решение на Крум, че правилата не са „пари“.

## FG-126 — един път за грешка в индексите още носи името на базата

- **Тежест:** low. **Статус:** resolved (main `2ec61f3`, проход 16). **PROVEN.**
- **Канон:** FLOW-040 §9; FG-117.
- **Код (#72 `04e0a1b`):** `audit/indexes.py:192` — недублирана грешка на `create_index` се хвърля сурова. Пример: „too many indexes for fg72_acmebuild_xxx.audit_events“ в съобщението и traceback-а; спира старта.
- **Решение:** промяна в кода — обвиване в `AuditIndexError` със `safe_reason`, `raise … from None`.

## FG-127 — P&L и печалбата показват различни режийни

- **Тежест:** medium. **Статус:** resolved (OH-01 `31a9478`, проход 13). **PROVEN.**
- **Канон:** Р38 („нищо не изчезва тихо“); OH-01 добавка 2; CLAUDE.md §2.12 / §16 (един източник).
- **Код (OH-01 `997abdc`):** `services/project_pnl.py:113-115` и `project_financial_results.py:218` четат `current_allocations`, а нетната печалба и печалбата на обекта — `project_overhead_current` (с legacy месеците).
- **Проба:** P&L и financial-results 323.25, нетна печалба и печалба на обекта 823.25 (323.25 + 500 legacy за непокрит месец).
- **Решение:** промяна в кода — един четец навсякъде.

## FG-128 — неприспаднатият аванс не е отделен ред в P&L

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-008: аванси „отделно“ (получен/прихванат/остатък); FLOW-021: остатък на аванса.
- **Код (SUB-ADV-01 `17aa55d`):** P&L няма поле за аванс; само `cash_out` във financial-results го включва.
- **Решение:** решение на Крум — P&L на обекта да показва ли „даден аванс / приспаднат / остатък“.

## FG-129 — стара версия на оферта остава приемаема

- **Тежест:** high (договорна стойност, клиентско приемане). **Статус:** resolved (OFF-01 `2379d07`, проход 15). **SUSPECTED** (четене, ясно от кода).
- **Канон:**
  - FLOW-003 „Какво НЕ трябва“: „стара/заменена версия да бъде одобрена след публикуване на нова“; „общо „ОК“ без exact version да се превърне в Approval Receipt“;
  - FLOW-002 „Magic link“: „невалиден при нова версия, когато е approval link“;
  - FLOW-010 §6.
- **Код (main `d226c49`):**
  - `backend/app/routes/offers.py:398-446` `new-version` само вмъква новата версия (`:440`), старата остава Sent;
  - `/offers/{id}/accept` (`:354-375`) приема всяка Sent;
  - `/offers/review/{token}/respond` (`:1140-1165`, без сесия) приема по токен на старата версия — `resolve_review_token` не гледа версията.
- **Ефект:** клиентът приема по стар линк заменената версия → приета грешна цена/обхват. ACT-01 после смята остатъка по „последната приета“.
- **Решение:** промяна в кода:
  - при нова версия старата → „Заменена“ (Superseded);
  - accept и токенът отказват заменена версия (409);
  - токенът е вързан към exact version/hash.

## FG-130 — изтриване на изпратена оферта

- **Тежест:** medium. **Статус:** resolved (OFF-01 `2379d07`, проход 15). **SUSPECTED.**
- **Канон:** CLAUDE.md §2.9 „Няма hard delete на използвани … или договорни записи“; FLOW-003 („старата версия остава видима“).
- **Код (main `d226c49`):** `offers.py:447-460` — Admin/Owner трие всяка оферта, освен Accepted, с `delete_one` (вкл. Sent и Rejected, които клиентът вече е получил); само legacy `log_audit`.
- **Решение:** промяна в кода — изтриване само на чернова; Sent/Rejected → архив/оттегляне със статус и AuditEvent.

## FG-131 — центове при частични актове

- **Тежест:** low. **Статус:** resolved (ACT-01 `dd11e8e`, проход 14). **PROVEN.**
- **Канон:** правилото към FG-121 („закръгля се само стойността на реда (и сумите) до цент“); FLOW-004 „остатък = офертно − актувано“.
- **Код (ACT-01 `8188689`):** `services/client_acts.py:136` (`money`), `:579-590` (`_remaining_row`).
- **Проба:** три акта 33 + 33 + 34 по ред 100 × 12.345 → 407.39 + 407.39 + 419.73 = **1234.51** срещу 1234.50 на офертата. Изгледът за остатък показва 1234.50 (количество × цена), а не реално фактурираното.
- **Решение:** решение на Крум — последният акт поема цента, или остатъкът по стойност = офертна стойност − сума на актуваните стойности.

## FG-132 — висящ pending аванс държи място под тавана

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Код (SUB-ADV-01 `542fa2c`):** `subcontractors.py:966-990` — след срив pending сумата остава резервирана, докато някой не повтори заявката със същия ключ; няма изтичане или освобождаване.
- **Решение:** решение на Крум дали е приемливо; иначе задача за изтичане с AuditEvent.

## FG-133 — свободно поле `condition` в `/alarm-rules`

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** Р20 (сумите в EUR — само за финансови роли); SEC-02 добавка G.
- **Код (#71 `83f1bf3`):** `routes/alarms.py:211-215` връща `condition` без филтър. В днешните правила няма суми, но Admin може да създаде праг в EUR.
- **Решение:** промяна в кода — полета със суми в `condition` скрити за не-финансови роли.

## FG-134 — отчет без присъствие и със задна дата

- **Тежест:** high (трудът е основа за заплатата — FLOW-028; Р3). **Статус:** open. **SUSPECTED** (четене).
- **Канон:** FLOW-013 „Забрана за отчет без присъствие“:
  - „Техникът не може да създаде отчет за човек, който не е присъстващ на съответния обект“;
  - „Няма нормален сценарий „отчет без присъствие““;
  - „Пропуснат отчет със задна дата може да създаде само Admin/Owner/упълномощен офис админ с причина и AuditEvent“.
  - FLOW-019: „труд без присъствие, СМР и време“ е забранен.
- **Код (main `d226c49`):** `backend/app/routes/daily_reports.py:135-157` проверява присъствието само за конфликт с отсъствие (SickLeave/Leave/Excused/Holiday) и дава **предупреждение**, не отказ. При липсващ запис за присъствие няма проверка. Няма ограничение по дата и роля за минали дни.
- **Връзка:** FG-58 (ръчен труд без отчет) е същият клас. LAB-01/02 смятат заплатата от одобрените отчети, т.е. отчет без присъствие стига до Pay Run след одобрение.
- **Решение:** промяна в кода — отказ без присъствие на същия обект/дата; задна дата само за Admin/Owner/офис с причина и AuditEvent. Ако Крум иска мек режим за преходен период — изрично решение.

## FG-135 — legacy двойка версии: старата още се приема

- **Тежест:** high. **Статус:** resolved (OFF-01 `2379d07`, проход 15). **PROVEN** (×3 режима).
- **Канон:** FLOW-003: „стара/заменена версия да бъде одобрена след публикуване на нова“ е забранено.
- **Код (OFF-01 `bfc41f5`):** `backend/app/routes/offers.py:187-214` (`_family_guard`) отказва само ако друга версия вече е Accepted; не гледа дали има по-нова (`parent_offer_id == offer.id`).
- **Проба:** legacy v1 Sent (1200) + v2 Sent (1500). Клиентът приема v1 по стария линк → 200, Accepted на 1200; v2 после → `OFFER_FAMILY_ALREADY_ACCEPTED`. Вътрешен `/accept` на стара w1 при Sent w2 → 200.
- **Решение:** промяна в кода — отказ на всяка версия, която има по-нова (OFFER_VERSION_SUPERSEDED). Маркирането на старите legacy редове като Superseded е миграция → решение на Крум (D-OFF01-13).

## FG-136 — DELETE в надпревара със send

- **Тежест:** medium. **Статус:** resolved (OFF-01 `2379d07`, проход 15). **PROVEN.**
- **Канон:** CLAUDE.md §2.9 (без hard delete на използвани записи).
- **Код (OFF-01 `bfc41f5`):** `offers.py:769` `delete_one({"id": offer_id})` без условие Draft/`updated_at`; същото в `offer_versions.py:333`.
- **Проба:** ×10 DELETE ∥ send → в 28 от 30 рунда send минава (snapshot и събитие „sent“), после офертата е изтрита; send пада с TypeError на `:520` → 500.
- **Решение:** промяна в кода — DRAFT_FILTER + `updated_at` във филтъра на изтриването, 409 при разминаване; същото за snapshot.

## FG-137 — `signed_pdf` без файл

- **Тежест:** medium. **Статус:** resolved (OFF-01 `2379d07`, проход 15). **PROVEN.**
- **Канон:** FLOW-003 (носител на одобрението = подписан PDF); CLAUDE.md §8 (Approval сочи към доказателство).
- **Код (OFF-01 `bfc41f5`):** `offers.py:546-547` — `approval_method=signed_pdf` без `evidence_file_id` → 200, evidence None (×3 режима).
- **Решение:** промяна в кода — 422 при signed_pdf без файл. Решение на Крум за `verified_email`.

## FG-138 — отменен линк още показва старата оферта

- **Тежест:** medium. **Статус:** resolved по Р43 (OFF-01 `2379d07`, проход 15). **PROVEN.**
- **Канон:** FLOW-002 „Magic link“: „невалиден при нова версия“; „оттеглен или изтекъл grant да продължи да работи“ е забранено; FLOW-010 §4.2/§6.
- **Код (OFF-01 `bfc41f5`):** `offers.py:1397-1449` — GET по отменен токен → 200, общо 1200 и всички редове.
- **Допълнително (SUSPECTED, от main):** редовете показват на клиента `material_unit_cost` и `labor_unit_cost`.
- **Решение:**
  - промяна в кода — отменен линк връща неутрална страница без цени;
  - решение на Крум дали разбивката материал/труд е „вътрешни данни“ по FLOW-010 §6.

## FG-139 — токенът на офертата в явен вид

- **Тежест:** low. **Статус:** open. **PROVEN** (от main, не е въведено от OFF-01).
- **Канон:** FLOW-002 „Magic link“: „token/secret не се пази в audit в четим вид“. В audit го няма (0 срещания), но `offers.review_token` е в явен вид.
- **Решение:** промяна в кода — hash на токена (като AUTH-01 reset токените); запис като дълг.

## FG-140 — изпратена/платена фактура се променя от надпреварваща редакция на ред

- **Тежест:** high. **Статус:** resolved (#55 `ed48595`, проход 15). **PROVEN.**
- **Канон:** FLOW-006: „След плащане няма тихо редактиране“, „тихо редактиране след плащане“ е забранено.
- **Код (#55 `cba5306`):** `backend/app/routes/invoice_lines.py:536-538` — проверката за Draft е извън транзакцията; записът на реда (`:588`) и на заглавието (`:209`) са без условие за статус.
- **Проба:** PUT спрян след проверката за Draft, фактурата сменена на Sent (както `send_invoice`, `finance.py:1018`):
  - Sent: редът 100 → 200, общото 120 → 240, статусът остава Sent;
  - Paid: общото 120 → 240, остатъкът 0 → 120.
- **Допълнително (SUSPECTED):** записът на реда и преизчислението на заглавието са две отделни транзакции.
- **Решение:** промяна в кода — фактурата се чете отново в транзакцията с lock на реда; `status:"Draft"` и в двата записа, иначе 409; една транзакция.

## FG-141 — `/alarm-rules` още показва EUR праг и име

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:** Р20 (без пари за не-финансови роли); SEC-02 добавка G (прагът е настройка, но сумите в EUR се крият).
- **Код (#71 `bfeda82`):** `permissions/finance_read.py:464` пази `threshold` независимо от метриката; `routes/alarms.py:218` не маскира `name`.
- **Проба:** правило `budget_spent_eur`, `threshold 48250`, име „Бюджет над 77777 EUR“ → Technician и Viewer виждат 48250 и името.
- **Решение:** промяна в кода — `threshold` само за метрики в % / часове / дни; за парични — общо име (GENERIC_ALARM_RULE_NAME).

## FG-142 — потвърдената стойност се различава с 1 цент от черновата

- **Тежест:** low. **Статус:** resolved (ACT-01 `2cc1147`, проход 15). **PROVEN.**
- **Канон:** CLAUDE.md §8: „Approval винаги сочи към exact version“.
- **Код (ACT-01 `dd11e8e`):** `services/client_acts.py:972-987` — при две чернови по 33 потвърждаването на втората (показана 407.38) записва 407.39; заявката няма очаквана ревизия/стойност. Одитът пази `subtotal_draft`.
- **Решение:** решение на Крум — потвърждаването да носи очаквана ревизия/сума и 409 при разминаване.

## FG-143 — файловете не минават през File Registry

- **Тежест:** medium (архитектурен дълг, Wave 0). **Статус:** open — дълг W0-06. **SUSPECTED** (четене).
- **Канон:**
  - CLAUDE.md §2.6: „Един File Registry — модулите използват `file_id`, не provider URL/path“;
  - §2.7 и §4: оригиналите — в customer-managed Storage Provider;
  - FLOW-014: „Снимките се избират от единния фото/File Registry; не се качват второ копие“;
  - FLOW-016.
- **Код (main `d226c49`):**
  - `backend/app/routes/projects.py:897-917` пише в `/app/backend/uploads/projects` и пази `url` в `project_photos`;
  - `media.py:95-101` — в `/app/backend/uploads`, колекция `media_files`;
  - дневните отчети и техническият портал пазят списъци с URL (`technician.py:41,51`).
  - Има проверка на tenant при четене.
- **Връзка:** стекът W0-06 (#44, #46, #49, #51) е отворен и стар — не е прегледан от FLOW GUARD (без нов commit).
- **Решение:** промяна в кода в W0-06 — File Registry + adapter към customer-managed storage, миграция на съществуващите файлове. Оркестраторът да го държи като дълг; без ново бизнес решение.

## FG-144 — вътрешен reject презаписва клиентско приемане

- **Тежест:** high. **Статус:** resolved (OFF-01 `acc472f`, проход 16). **PROVEN** (1 от 120 надпревари, режим shadow).
- **Канон:** FLOW-003 (приетата версия остава приета; „приета оферта да се редактира тихо“ е забранено); CLAUDE.md §2.9, §8, §14.
- **Код (OFF-01 `2379d07`, от main):** `backend/app/routes/offers.py:638-655` `reject_offer` чете и пише `update_one({"id": offer_id}, {"$set": {"status": "Rejected"}})` — без условие за статус, без транзакция, без Idempotency-Key и без canonical AuditEvent. Legacy родител (FG-135) също може да се отхвърли вътрешно.
- **Проба:** клиентско приемане ∥ вътрешен reject → и двете 200, крайният статус е Rejected с попълнено `accepted_at`.
- **Решение:** промяна в кода — reject само при Sent и незаменена версия (CAS), в `_in_transaction`, с ключ и AuditEvent; губещият → 409. Оркестраторът решава OFF-01 или отделен пакет.

## FG-145 — сканирани документи по изпратени фактури и изтриване на оригинала

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене, от main).
- **Канон:** CLAUDE.md §2.9 („Няма hard delete …“), §2.7 (оригиналите се пазят); FLOW-006 („След плащане няма тихо редактиране“); FLOW-016.
- **Код (#55 `ed48595`):** `backend/app/routes/scan_docs.py:135,159,194,202,228` — link/unlink пише `scan_doc_id` по Sent/Paid фактура без проверка на статус, CAS и AuditEvent; изтриването на scan doc трие записа и вика `os.remove` на оригиналния файл.
- **Решение:** промяна в кода — правило по статус + корекция/AuditEvent; без `os.remove` на оригинали (архив). Свързано с FG-143 (W0-06).

## FG-146 — редакция на изпратена/частично платена фактура

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене, от main).
- **Канон:** FLOW-006 „Корекции“: „След плащане няма тихо редактиране. Използват се: корекция, реверс, доплащане, удръжка, кредитно / дебитно известие“.
- **Код (#55 `ed48595`, от main):** `backend/app/routes/finance.py:1016,1088` — редакцията на заглавието и на вградените редове забранява само Cancelled и Paid. Sent, Overdue и PartiallyPaid могат да сменят сумата; пази се само snapshot на версията, без Approval и без AuditEvent.
- **Решение:** решение на Крум — след изпращане само кредитно/дебитно известие (FLOW-006), или редакция до първото плащане с Approval.

## FG-147 — авансите към подизпълнители без canonical AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN** (grep).
- **Канон:** CLAUDE.md §2.8: „Един общ append-only AuditEvent envelope“; FLOW-040 §4.2 (плащане, allocation, correction); CLAUDE.md §14.
- **Код (SUB-ADV-01 `c4de7c9`):** `backend/app/routes/subcontractors.py:893,934,1131` — само `log_audit` (legacy `audit_logs`, `app/services/audit.py:24`); `record_event`/`audit_events` — 0 срещания във файла. PAY-01 (#70, main) пише canonical събития за плащанията.
- **Решение:** промяна в кода — canonical AuditEvent в същата стъпка (id от ключа), както PAY-01.

## FG-148 — толерансът при актуване може да блокира последното плащане

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-021 (остатък от одобреното измерено); Р40 (таван по пакет: платено ≤ удостоверено).
- **Код (SUB-ADV-01 `c4de7c9`):** актуването допуска 0.01 количество толеранс на ред (`subcontractors.py:~441-442`), така че `certified_total` може да е малко над `contract_total`. Новата проверка срещу договора (F-76-01, `:683-692`) допуска само половин цент → последното плащане на цялото актувано → `PAYMENT_EXCEEDS_PACKAGE_VALUE`.
- **Решение:** решение на Крум — таванът е актуваното (Р40) или договорът; толерансите да са еднакви.

## FG-149 — отварянето на клиентския линк сменя `updated_at`

- **Тежест:** low. **Статус:** resolved (OFF-01 `653a1a5`, проход 17). **PROVEN.**
- **Поправка (`49fc52f`):** `offers.py:1507-1513` — прегледът прави `$max` на `viewed_at`/`last_viewed_at` и `$inc view_count`; `updated_at` не се пипа. Червен тест `1d89865`, после зелен. FLOW GUARD: `test_off_01_offer_version_accept.py` → 87 passed на MongoDB 7 replica set. Бележка: `viewed_at` вече е последният преглед, не първият (и преди се презаписваше — не е регресия; първият преглед остава в `offer_events` „viewed“).
- **Код (OFF-01 `acc472f`):** `routes/offers.py:1510` — отбелязването на преглед (`viewed_at`/`updated_at`) е безусловно (само id и токен). Не сменя статуса, но вдига `updated_at`, а нова версия ползва `updated_at` за CAS → клиент, който отваря линка, може да предизвика фалшив 409.
- **Решение:** промяна в кода — `viewed_at` без да пипа `updated_at` (или CAS по отделно поле).

## FG-150 — изписването от склада е 0 в P&L, финансовия резултат и централните справки (четат `unit_cost`, а изписването пише `unit_price`)

- **Тежест:** high. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Път А: „обектов разход възниква само при изписване/консумация“.
- **Код (main `2ec61f3`):** `routes/procurement.py:628-637` пише редовете на изписването с `unit_price`/`total_price` (единственият writer на `type:"issue"`). Четат `unit_cost` × `qty_issued` → винаги 0: `services/project_pnl.py:86-89`, `services/project_financial_results.py:84`, `services/centralized_reports.py:324`. Други справки четат `total_price` (`revenue_expense.py:468`, `materials_baseline.py:326`, `material_smr.py:79`) → едно изписване е X в едни справки и 0 в други. В P&L `max(фактури, 0)` (виж FG-17).
- **Решение:** промяна в кода — един общ helper за стойността на изписване, ползван от всички справки. #55 го заменя с каноничния регистър, но на main може да се оправи само в четенето.

## FG-151 — стойността на изписването идва от клиента; обектът не приема (`received_by` е текст)

- **Тежест:** high. **Статус:** resolved (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Прехвърляния: „стойността/партидата се пренасят“; „промяна на историческа … стойност без корекционно движение“; Р17 (разход при приемане).
- **Код (main `2ec61f3`):** `procurement.py:635-636` взема `unit_price` от тялото на заявката; `get_warehouse_stock` (`:549-556`) вади тази стойност. Обектът не приема — `received_by` е свободен текст (`:653`).
- **Решение:** промяна в кода — сървърна оценка (FIFO/средна), отказ на цена от клиента, приемане от обекта (Rule B). Затваря се от #55 (5C-C21/C24).

## FG-152 — `/warehouse-return` и `/project-consumption` без роля и AuditEvent; връщането отива в свободна наличност, без карантина и без стойност

- **Тежест:** high. **Статус:** resolved (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Върнат материал не става автоматично свободна наличност“; Р17 „неизползваното се връща … и тогава разходът намалява“; CLAUDE.md §14 AuditEvent.
- **Код (main `2ec61f3`):** `procurement.py:729-784` `POST /warehouse-return` само с `require_m2` (модул, без роля); връщането е +qty в свободната наличност (`:557-559`); редовете нямат стойност (`:761-767`) → разходът на обекта не намалява. `POST /project-consumption` (`:671-724`) също без роля и без AuditEvent.
- **Решение:** промяна в кода — роля + членство в обекта, canonical AuditEvent, връщане в карантина, сторно по слоя. Аналог на FG-18 в #55.

## FG-153 — втори складов регистър (`warehouse_batches`) до `warehouse_transactions`; `/warehouse/consume` изписва без обект и основание

- **Тежест:** high. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — CLAUDE.md §16 „не създавай втори … source of truth“; FLOW-009 „материал без валидна локация“, „движение без основание“.
- **Код (main `2ec61f3`):** `routes/warehouse_batches.py:103-123` и `services/fifo_service.py:41-87` пазят наличност в `warehouse_batches`, отделно от `warehouse_transactions`. `POST /warehouse/consume` (`warehouse_batches.py:128-147`) изписва без `project_id`/основание, пише в `material_consumption_log`, без AuditEvent. `PUT .../block` (`:154-169`) без причина и одит.
- **Решение:** Крум да реши кой legacy регистър е източник до #55 (другият read-only); консумацията да изисква дестинация и основание.

## FG-154 — P&L не чете `allocations[]` на фактурния ред (само старите `allocation_type`/`allocation_ref_id`), т.е. разделеният ред е 0 или 100%

- **Тежест:** high. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Разпределение на фактурен ред: „40 торби → 10 XOPark, 12 Крум, 8 Делчо, 10 склад“.
- **Код (main `2ec61f3`):** `services/project_pnl.py:74-78` филтрира по `allocation_type`/`allocation_ref_id` и брои целия `line_total_ex_vat`; `POST /invoice-lines/{id}/allocate` (`invoice_lines.py:589-595`) обновява само `allocations[]`. Ред с `allocations[]` е 0 в P&L; стар ред, разделен по-късно, остава 100% за първия обект. Подобно `dashboard.py:688-700`.
- **Решение:** промяна в кода — Път Б: разход = `allocations[].qty × единична цена` за обекта.

## FG-155 — остатъкът от фактурния ред може да остане неразпределен; разпределение „склад“ не създава наличност

- **Тежест:** medium. **Статус:** open (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Остатъкът не изчезва; системата изисква валидна дестинация.“
- **Код (main `2ec61f3`):** `invoice_lines.py:149-152` `require_full_allocation` по подразбиране False; проверките (`:576-582`, `:330-333`) зависят от нея. Разпределение `type:"warehouse"` (`:136-139`) не пише в склада.
- **Решение:** Крум да потвърди, че пълното разпределение е задължително (по канона — да); в кода разпределението към склад да създава приемане.

## FG-156 — директна доставка влиза в склад `main`; приемането по фактура не е атомарно и е без Idempotency-Key

- **Тежест:** medium. **Статус:** resolved (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Видове движения: „покупка → обект / няколко обекта / обекти + склад“; Път Б.
- **Код (main `2ec61f3`):** `procurement.py:441-478` приема всички редове в склад `main`, въпреки `project_id` на реда (`:452`); проверката `posted_to_warehouse` (`:418`) и записът (`:479-489`) не са атомарни, без Idempotency-Key.
- **Решение:** промяна в кода — маршрут по дестинацията на реда, CAS на статуса на фактурата, Idempotency-Key.

## FG-157 — фактура на доставчик се редактира след приемане в склада, без корекционно движение

- **Тежест:** medium. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „промяна на историческа партида/стойност без корекционно движение“.
- **Код (main `2ec61f3`):** `procurement.py:367-403` сменя `lines`/`total`/`status` без проверка на `posted_to_warehouse`; без AuditEvent (ролята — FG-30).
- **Решение:** промяна в кода — след приемане само корекция/сторно с причина и AuditEvent.

## FG-158 — отрицателни количества и надпревара при изписване/FIFO консумация → отрицателна наличност

- **Тежест:** medium. **Статус:** resolved (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „отрицателна наличност без корекция и право“.
- **Код (main `2ec61f3`):** `procurement.py:612-621` проверява само склад `main` (+0.01) и не е атомарно с `insert` (`:661`); отрицателни `qty_issued`/`qty_returned`/`qty_consumed` не се отказват (`:617,751,693`). `fifo_service.py:113-132` чете и записва без условие.
- **Решение:** промяна в кода — qty > 0 и атомарно условно намаляване/транзакция.

## FG-159 — брак/фира не е складово движение: без стойност, без намаляване на наличността

- **Тежест:** medium. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Видове движения „брак / загуба / кражба“; Р10; Р37.
- **Код (main `2ec61f3`):** `services/material_waste.py:57-80` пише `material_waste_entries` без стойност, без източник и без намаляване на наличността; без AuditEvent; P&L не я чете.
- **Решение:** промяна в кода — бракът като складово движение със стойност по слоя. Затваря се от #55.

## FG-160 — `create-sub-project` пренаписва `project_id` на историческите движения и плащания, без Approval

- **Тежест:** medium. **Статус:** open (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Всяко движение е отделен неизтриваем запис“; „промяна на историческа партида … без корекционно движение“.
- **Код (main `2ec61f3`):** `routes/projects.py:1566-1583` (`create-sub-project`) прави `update_many` на `project_id` в `warehouse_transactions`, `invoices`, `subcontractor_payments`, `payroll_payment_allocations` и др. към под-обект А; само legacy `log_audit` (`:1659-1660`), без Approval.
- **Решение:** Крум да реши: историята остава на родителя (под-обектът получава трансфер) или пренасочване с Approval и canonical AuditEvent.

## FG-161 — складовите стойности се виждат от всички роли (Р20/Р34/Р35)

- **Тежест:** medium. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Р20, Р34, Р35 (кой вижда стойности).
- **Код (main `2ec61f3`):** `procurement.py:509-521, 564-571, 897-1007`, `warehouse_batches.py:47-98, 174-187` връщат цени и стойности на всеки с M2/всеки логнат.
- **Решение:** промяна в кода — маскиране по Р20/Р34/Р35 (#71 на main не покрива тези пътища). Аналог на FG-23/FG-56 в #55.

## FG-162 — материалът е свободен текст (`material_name|unit`), не Master артикул; заявката става `fulfilled` без сравнение на количества

- **Тежест:** medium. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Master артикул по FLOW-032“; аларма „незаявен материал“, „доставено повече/по-малко“.
- **Код (main `2ec61f3`):** `procurement.py:544,615,690` — ключ `material_name|unit`; `:492-499` маркира заявката `fulfilled` без сравнение по ред и количество.
- **Решение:** промяна в кода — `master_item_id` (FLOW-032/W0-03), изпълнение по ред, аларма за незаявен материал.

## FG-163 — склад с наличност се деактивира или сменя типа си без проверка и без одит

- **Тежест:** low. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „материал без валидна локация“.
- **Код (main `2ec61f3`):** `routes/warehouses.py:272-278` (TODO за наличност), `:233-259` смяна на type/project_id; без AuditEvent.
- **Решение:** промяна в кода — 409 при наличност/история + AuditEvent.

## FG-164 — липсват движения склад→склад, обект→обект, „в път“, връщане към доставчик, ревизия; наличност само за склад `main`

- **Тежест:** medium. **Статус:** partial (повторен преглед след merge на #55, main `cd03324`, проход 20b). **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Видове движения, Прехвърляния, Ревизия; Р11.
- **Код (main `2ec61f3`):** Няма склад→склад, обект→обект, „в път“, връщане към доставчик, ревизия с DQ/Approval; наличност само за `type:"main"` (`procurement.py:531`); `models/warehouse.py:7` без подобект/машина/транспорт.
- **Решение:** промяна в кода — пакетът е #55; Крум да реши дали legacy пътищата се замразяват read-only до сливането.

## FG-165 — няма регистър на проверени IBAN-и; плащане към нов/различен IBAN не се блокира

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §8.1 „Първи превод към нов IBAN… изпълнението е блокирано до успешна верификация“; §8.2 два източника; §12.
- **Код (main `2ec61f3`):** IBAN се среща само в `routes/projects.py:370-371` (свободен текст); OCR не извлича IBAN (`services/ocr_invoice.py:72-75`); плащане към подизпълнител с `payment_method: bank` без сметка (`routes/subcontractors.py:493-525`).
- **Решение:** промяна в кода — нов пакет: `VerifiedBankAccount` със статуси от §3.3 и два източника; банково плащане изисква проверена сметка (иначе 409 + DQ задача); действие `bank_account.verify`, AuditEvent.

## FG-166 — дублирани контрагенти по ЕИК и по роля в 5 регистъра

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §2 „Ролята не създава втори контрагент“; §12 „две организации със същия ЕИК“.
- **Код (main `2ec61f3`):** `subcontractors.py:58-70` без проверка на ЕИК; `counterparties.py:160-166` и `clients.py:521-526` проверяват само в своята колекция; `counterparties.py:341-395` (auto-link) създава нов `client`. Master Data проверката е само при `MASTER_DATA_MODE=enforce` (по подразбиране `off`, `master_data/deps.py:69-70`).
- **Решение:** промяна в кода — проверка на ЕИК във всички регистри при create/update (409 с препратка) докато Master Data е off/shadow; Крум да реши кога Master Data минава в enforce.

## FG-167 — hard delete на контрагент с история (проверката гледа само `invoices`)

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §12 „изтриване на контрагент с договорна, комуникационна или финансова история“; CLAUDE.md правило 9.
- **Код (main `2ec61f3`):** `routes/counterparties.py:265` брои само `invoices.supplier_counterparty_id`; при 0 и режим off `guarded_identity_delete` връща None (`master_data/legacy_adapter.py:313-315`) → `delete_one` (`counterparties.py:278`) — трие контрагент с `supplier_invoices.supplier_id` (`procurement.py:292,313`) или `warehouse_batches.supplier_id`. `clients.py:288-306` гледа само свързани контрагенти, не `projects.owner_id`/`sales.client_id`.
- **Решение:** промяна в кода — `count_usage` (`legacy_adapter.py:260`) и в off; използван запис → архив, никога hard delete.

## FG-168 — финансовите суми по клиент/контрагент се виждат от всяка роля с модул M5 (#71 не ги покрива)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — Р20; FLOW-010 §3.2.
- **Код (main `2ec61f3`):** `routes/clients.py:753-841` `/clients/{id}/summary` и `routes/counterparties.py:203-223` (`total_invoiced`, `recent_invoices`) — само `require_m5` (модул, `deps/modules.py:108-109`); UI защита (`App.js:285`) не е сървърна.
- **Решение:** промяна в кода — `require_finance_read` (SEC-02) на двата endpoint-а или маскиране на паричните полета.

## FG-169 — профилът смесва приходи и разходи (без `direction`) и брои само 20 фактури

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §9 „Няма двусмислена обща колона „Приходи““.
- **Код (main `2ec61f3`):** `clients.py:779-782, 814-817` — всички фактури по обекта, без `direction`/статус → получени фактури и чернови в `total_revenue`/`balance_due`; `counterparties.py:215-221` `total_invoiced` от `to_list(20)`.
- **Решение:** промяна в кода — read model контрагент → обект → договор → роля с колоните от §9 по `direction` и от FLOW-006 регистъра.

## FG-170 — клиентската карта връща 404 за клиенти фирми/лица на обекта

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §11, §13 (от контрагента към обектите).
- **Код (main `2ec61f3`):** `clients.py:719-747` пише `owner_id` от `companies`/`persons`; `/clients/{id}/summary` търси в `clients` (`:758-760`); UI бутонът (`ProjectInfoPanel.js:160`) подава `owner_id`.
- **Решение:** промяна в кода — един resolver през companies/persons/clients (после Master ID), или Крум да реши кой регистър е „клиент“.

## FG-171 — create/update на контрагенти, клиенти, фирми, лица без право и/или без AuditEvent

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — FLOW-002 критични действия (Master Data, банкова сметка); CLAUDE.md §14.
- **Код (main `2ec61f3`):** Без роля: `PUT /companies/{id}` (`projects.py:810-826`), `PUT /persons/{id}` (`:690-698`), `POST /clients/company` (`clients.py:506`), `/clients/person` (`:566`), `/companies` (`projects.py:757`), `/clients/find-or-create` (`clients.py:312-349`, `require_m5`), `POST /subcontractors` (`subcontractors.py:58`, `require_m2`), `import-client-invoice` (`projects.py:340-400`). С роля, без одит: `PUT /counterparties` (`:226-250`, сменя и ЕИК), `PUT /clients` (`:239-275`), unlink/auto-link (`counterparties.py:322-403`).
- **Решение:** промяна в кода — действия `counterparty.*`/`client.*` в Permission Service, canonical AuditEvent с diff; смяна на ЕИК/име на използван запис през Master Data/Approval.

## FG-172 — ЕГН се връща в явен вид на всеки логнат

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §3.2 (достъп по FLOW-002); `clients.py` сам маскира ЕГН (`:387,470`).
- **Код (main `2ec61f3`):** `GET /persons` (`projects.py:625-636`), `/persons/{id}` (`:680-687`), `/persons/find-by-phone` (`:669`) — целият документ с `egn`, само `get_current_user`.
- **Решение:** промяна в кода — projection без/маскиран `egn`; пълен ЕГН само за правоимащи роли.

## FG-173 — клиентското одобрение по линк не е ApprovalReceipt (свободно име, без контакт, hash, AuditEvent)

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §6 „идентичност на потвърдилия… метод на верификация… контакт… AuditEvent“; §3.2.
- **Код (main `2ec61f3`):** `routes/offers.py:1140-1176` — `client_name` от тялото; без контакт и права, без hash на версията, без AuditEvent; събитието в глобалния `db.offer_events` (`:1171`). OFF-01 (не е на main) пише `verification: "link_token_only"`. FG-129 покрива само версията.
- **Решение:** промяна в кода — ApprovalReceipt с `contact_id` (Contact Role), метод на верификация, hash на версията, AuditEvent; Крум да реши кой метод на идентификация стига за линк.

## FG-174 — ролята на контрагента е едно поле, не множество

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §2 (много роли едновременно).
- **Код (main `2ec61f3`):** `models/finance.py:22`, `counterparties.py:285` — `type` ∈ supplier/client/both/person; подизпълнителите са отделна колекция.
- **Решение:** промяна в кода — `roles: [...]` върху Master организацията; `type` само за четене.

## FG-175 — IBAN-ът във фактурата е свободен текст; няма проверена собствена сметка

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-010, проход 18).
- **Канон:** FLOW-010 — §8.4.
- **Код (main `2ec61f3`):** `projects.py:370-371` копира `invoice_details` IBAN; редактира се в UI (`ProjectInfoPanel.js:180`); собствена сметка във фактурите няма.
- **Решение:** промяна в кода — сметка от VerifiedBankAccount (FG-165), иначе изпращането се блокира.

## FG-176 — handover сменя локацията и затваря custody на предаващия преди ACCEPTED

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Двуфазно „Докато предаването е PENDING_ACCEPTANCE, държател и отговорник остава предаващият… Custody … се сменят само при ACCEPTED“.
- **Код (main `2ec61f3`):** `routes/assets_units.py:272-275, 300-303` — `handover` веднага `location=employee/получател`, `status=in_use`; `assets_custody.py:84-91` затваря custody на предаващия (`_close_active` :47-51) и пише `given`, който се брои за активен (:33) → `/custody/unit/{id}` (:193-196) показва получателя преди приемане. Същото в `give_custody` (:108).
- **Решение:** промяна в кода — handover/give пише само `PENDING_ACCEPTANCE`; unit/custody се сменят в `accept`, в транзакция, с AuditEvent.

## FG-177 — `take` със `to_id` записва ACCEPTED custody на друг потребител; „вземи от него“ само със сканиране

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — CLAUDE.md §16 „не третирай … QR като автоматично приемане или прехвърляне на отговорност“; FLOW-011 „Какво НЕ трябва: отговорността да се смени без ACCEPTED — само със сканиране“; „Служител … приема лично“.
- **Код (main `2ec61f3`):** `assets_units.py:270-271` `to_id = data.to_id or user["id"]`; `assets_custody.py:74-83` → `status: "accepted"` за `target`; право само `get_current_user` (`assets_units.py:256`). UI „Вземи от него“ (`frontend/.../ScanLandingPage.js:126-131`) прехвърля от текущия държател без негово предаване. `give_custody` към себе си — самоприемане (`assets_custody.py:112,115`).
- **Решение:** промяна в кода — `take` само за текущия потребител; вземане от друг = искане → предаване → приемане. Крум да реши дали самоприемане от склад/свободен актив е допустимо (FLOW-012 §9).

## FG-178 — отказът няма причина/доказателство и оставя актива без отговорник

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Двуфазно „Отказ или проблем … с причина и доказателство … отговорността остава при предаващия … Нищо не се прехвърля мълчаливо“.
- **Код (main `2ec61f3`):** `assets_custody.py:143-158` записва само `declined`; custody на предаващия вече е затворен (FG-176); unit остава `employee`/отказалия, `in_use`.
- **Решение:** промяна в кода — `rejection_reason`, `evidence_file_id`, статус „Проблем при приемане“, custody остава/възстановява се на предаващия, AuditEvent.

## FG-179 — `drop` на обект прехвърля без приемане от отговорника на обекта

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Актив само на обект „Актив, оставен ‚на обекта‘ без потвърдил отговорник, не е прехвърлен“.
- **Код (main `2ec61f3`):** `assets_units.py:276-279` — веднага `location=project`, `in_use`; custody не се сменя (`assets_custody.py:95`); свободен актив остава без пазител, само admin аларма `no_custodian` (:211-231).
- **Решение:** промяна в кода — `drop` = предаване към обектовия отговорник (`PENDING_ACCEPTANCE`).

## FG-180 — ГОСТ получател без задължителни данни и DQ блок

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §ГОСТ „задължително … име, телефон, фирма, … срок за връщане“; „при ГОСТ без телефон е блокиран/алармиран“.
- **Код (main `2ec61f3`):** custody само към `users` (`assets_custody.py:105-107`), `handover` винаги `employee` (`assets_units.py:275`); ГОСТ само като QR entity с име (`assets_qr.py:78-81`) и intake `location_type="guest"` със свободен `location_name` (`assets_intake_pending.py:35,74-76,157-158`).
- **Решение:** промяна в кода — ГОСТ получател със задължителни полета и DQ блок; Крум да реши одобрения начин на потвърждение от ГОСТ (подпис, SMS…).

## FG-181 — изтекъл срок за приемане — само pull аларма след 24 ч, без напомняне/ескалация

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Двуфазно „Изтичане на срок … напомняне и ескалация (FLOW-026). За инструменти … срокът е незабавно“.
- **Код (main `2ec61f3`):** `assets_custody.py:34, 199-208` — праг 24 ч, само GET за admin.
- **Решение:** промяна в кода — Action Inbox/аларма при създаване на предаването, ескалация по FLOW-026.

## FG-182 — няма AuditEvent за нито един преход на актив; няма Idempotency-Key

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Двуфазно „Всеки преход … е AuditEvent с предаващ, получател, актив, локации, състояние и доказателства“; CLAUDE.md §14.
- **Код (main `2ec61f3`):** `assets_custody.py`, `assets_units.py` (create/PUT/move), `assets_repairs.py`, `assets_qr.py`, `assets_items.py`, `asset_item_types.py`, intake approve/reject (`assets_intake_pending.py:169-261`) — без AuditEvent; `asset_movements` (`assets_units.py:287-298`) без accept/decline, състояние, доказателства.
- **Решение:** промяна в кода — canonical AuditEvent за всеки преход и промяна; Idempotency-Key на move/give/accept.

## FG-183 — отписване/бракуване през PUT без Approval; `take` връща отписан актив в употреба

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Липсващ актив „Само Крум/Owner/упълномощен админ може да одобрява отписване, бракуване…“; тест „скъп актив не се отписва без изискуемото одобрение“.
- **Код (main `2ec61f3`):** `assets_units.py:203-219` `PUT` задава `status=written_off` и произволни `location_*` само с `require_admin` — без Approval, причина, AuditEvent, движение; `move_unit` (:260-303) не проверява терминален статус.
- **Решение:** промяна в кода — отделно действие за отписване с Approval, причина, AuditEvent; PUT без status/location; `move` блокиран за терминални статуси.

## FG-184 — hard delete на актив с история (режим off)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — „Какво НЕ трябва: тихо изтриване на история“; CLAUDE.md правило 9.
- **Код (main `2ec61f3`):** `assets_units.py:222-234` — hard delete в off/shadow (по подразбиране off, `master_data/deps.py:69-70`), без проверка на `asset_movements`/`asset_custody`/`asset_repairs`.
- **Решение:** промяна в кода — 409/архив при всяка история, независимо от режима.

## FG-185 — AI оценка на цена става `purchase_price`; снимката е base64, не `file_id`

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — CLAUDE.md §10 „AI не измисля … цена“; правило 6 (File Registry).
- **Код (main `2ec61f3`):** `assets_intake_pending.py:135,162` `estimated_price_eur` → `purchase_price`; `purchase_date` = днес (:136,160); снимка като data URI в `photo_url` (:138-141; виж FG-143).
- **Решение:** промяна в кода — `estimated_price` с източник „AI“; `purchase_price` само от фактура/ръчно.

## FG-186 — връщане от ремонт/в склад без приемане; ремонт и движения без проверка на права

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-011, проход 19).
- **Канон:** FLOW-011 — §Ремонти/§Двуфазно „Складовото и сервизното приемане следват същия принцип“.
- **Код (main `2ec61f3`):** `assets_repairs.py:175-178` (`repair_return` → `available`), `assets_units.py:282-285` + `assets_custody.py:93-94` (`return` затваря custody); `repair/send`, `repair/return`, `move`, `give` — всеки логнат (`assets_repairs.py:94,138`; `assets_units.py:256`; `assets_custody.py:99`).
- **Решение:** промяна в кода — приемане от склада/получателя, проверка на права (Permission Service).

## FG-187 — заявка за материал се отменя/„изпълнява“/пренаписва през общ PUT без роля, причина и одит

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-012, проход 20).
- **Канон:** FLOW-012 — §4 „Артикулът отпада от активната опашка само чрез официално `Отменен/отказан` с причина, actor, timestamp и AuditEvent. Историята не се изтрива.“; §12.
- **Код (main `2ec61f3`):** `routes/procurement.py:166-177` `PUT /material-requests/{id}` — само `require_m2` (модул), `data: dict`; позволени `status` и `lines` с произволна стойност и след `submitted`; без проверка на статус, `check_project_writable`, причина, AuditEvent. `cancelled` влияе на сметките (`:796`). `submit` (`:182-195`) също без роля.
- **Решение:** промяна в кода — махни `status`/`lines` от общия PUT; команди `cancel` (задължителна причина) и `revise lines` (само `draft`) с роля по Р12, project-writable guard, Idempotency-Key и canonical AuditEvent.

## FG-188 — мобилният API дава на шофьора модул „Доставки“ без бекенд; моделът на снимката е URL, не `file_id`

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-012, проход 20).
- **Канон:** FLOW-012 — §7.4 „Снимките са `file_id` във FLOW-016 и са свързани с конкретното приемане“; §3 мобилен процес на шофьора.
- **Код (main `2ec61f3`):** `core/mobile_constants.py:28,45-48,110-118`, `models/mobile.py:20,36-39` (`photo_urls`), `routes/mobile.py:165-166` (бутон „updateDelivery“); никой не пише `deliveries` — `media_acl.py:98-110`/`media.py:342-348` връщат „Delivery not found“.
- **Решение:** промяна в кода — скрий `deliveries` от mobile bootstrap/defaults до реализацията на FLOW-012; схемата да е `photo_file_ids` през File Registry (W0-06, FG-143).

## FG-189 — транспортът в анализа на СМР е мълчалив фиксиран процент (10%) върху материала

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-012, проход 20).
- **Канон:** FLOW-012 — FLOW-024:75 „Транспортът не трябва да се приема като постоянен процент“ (отложено от FLOW-024 прегледа към FLOW-012).
- **Код (main `2ec61f3`):** `routes/smr_analysis.py:41` `logistics_pct: float = 10`; `:81,87,116` `mat_raw × (1+logistics_pct/100)`; `SMRAnalysisPage.js:73,100` (`?? 10`).
- **Решение:** Крум да реши дали процентът е приемлив като видимо означена оценка при офертата или се заменя с оценка по курс/разстояние/товар при реализация на FLOW-012; във всички случаи без мълчалив 10% по подразбиране.

## FG-190 — справките за количества (покритие, фира/„overuse“, статистика) не четат каноничния регистър

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (повторен преглед на FLOW-009 след merge на #55, проход 20b).
- **Канон:** FLOW-009 — „Всяко движение е отделен неизтриваем запис с източник, количество, стойност, локации и основание.“
- **Код (main `cd03324`):** `materials_baseline.py:204-221` (`/planned-materials/coverage`), `revenue_snapshot.py:331-339`, `services/material_waste.py:71-98`, `procurement.py:785-806` четат само legacy `type`+`lines`; каноничните редове ги нямат → 0 или замразени стари стойности след първото канонично движение. Само `compute_project_ledger` (`procurement.py:672-693`) е на `canonical_project_trail`.
- **Решение:** промяна в кода — количествата от `canonical_project_trail` / `material_entries`.

## FG-191 — стойността при приемане от доставчик идва от клиента, без сверка с фактурния ред

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (повторен преглед на FLOW-009 след merge на #55, проход 20b).
- **Канон:** FLOW-009 — Път А: „фактурата създава задължение/стойност на наличността“.
- **Код (main `cd03324`):** `services/warehouse_movements/service.py:965` взема `unit_value` от входа; `invoice_line_id` не е задължителен; `_check_invoice_line_total` (`:1832-1890`) проверява само количество и мярка; `BatchesTab.js:85-125` праща `unit_cost` от формата.
- **Решение:** промяна в кода — `unit_value` = `line_total_ex_vat/qty` на свързания ред и задължителен `invoice_line_id`; или Крум да реши дали има приемане без фактура и с какво одобрение.

## FG-192 — проверката срещу Master артикул в каноничния склад е изключена по подразбиране

- **Тежест:** high. **Статус:** open. **SUSPECTED** (повторен преглед на FLOW-009 след merge на #55, проход 20b).
- **Канон:** FLOW-009 — „Един материал има Master артикул по FLOW-032“.
- **Код (main `cd03324`):** `services/warehouse_movements/service.py:653-657` — `WAREHOUSE_STRICT_MASTER_IDENTITY` по подразбиране `"0"`; коментарът на `:651` твърди „default is strict in production“; променливата не се задава никъде в репото (compose/staging скриптове). Всеки низ минава като `item_id`; „pending-mapping само в карантина“ (`:905-911`) не се прилага.
- **Решение:** промяна в кода — strict по подразбиране (fail-closed), тестовете да подават изрично False.

## FG-193 — `create-sub-project` пренаписва `project_id` на каноничните append-only складови редове извън единствения писател

- **Тежест:** high. **Статус:** open. **SUSPECTED** (повторен преглед на FLOW-009 след merge на #55, проход 20b).
- **Канон:** FLOW-009 — „Всяко движение е отделен неизтриваем запис“; „промяна на историческа партида/стойност без корекционно движение“.
- **Код (main `cd03324`):** `routes/projects.py:1566-1583` — `coll.update_many` на `warehouse_transactions` хваща и каноничните редове; статичният скенер не го хваща (`legacy_inventory.py:115-119` изисква `.warehouse_transactions.update_many(`). Проекциите (`material_entries`, `warehouse_batches`, `warehouse_in_transit`) не се пренаписват, обектът се взема от локацията (`projections.py:437-443`) → регистърът и проекциите се разминават.
- **Решение:** промяна в кода — изключи каноничните редове (с `ledger_sequence`) от `update_many` (409 или трансферно движение); скенерът да хваща и `coll.update_many`. Историята — решение на Крум (FG-160).

## FG-194 — сторното на получаване дава на склададжията право да връща към доставчик (каталогът му го отказва); Accountant не може да сторнира

- **Тежест:** medium. **Статус:** open. **PROVEN (тест на PR, реален Mongo)** (проход 21).
- **Канон:** Р28 (права по Р16/Р27); `permissions/catalog.py:194-196` „Not permitted: … return-to-supplier (procurement decision)“; пакет WH-REV-01 т.4 „+ финансова роля за стойности“.
- **Код (WH-REV-01 `ed8f9e7`):** `services/warehouse_movements/actions.py:139` свързва `reverse_supplier_receipt` с правото `warehouse.receive_from_supplier` → ролята `warehouse` сторнира и отключва финансовото разпределение на реда; Accountant (който по Р44 разпределя) не може. Тестът `ROLE_CASES` (Warehousekeeper → 201).
- **Решение:** Крум да реши кой сторнира; предложение: правото на `return_to_supplier` (снабдител, Owner/Admin) или Owner/Admin/Accountant за свързан ред.

## FG-195 — сторно + allocate тихо преразпределя ред от вече платена фактура (FG-83 отново достъпно)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба `probes_whrev/test_probe_whrev.py`)** (проход 21).
- **Канон:** FLOW-006 „Корекции“: „След плащане няма тихо редактиране … кредитно / дебитно известие“.
- **Код (WH-REV-01 `ed8f9e7`):** `routes/invoice_lines.py:628-679` `allocate` не проверява статуса на фактурата; сторното също не го проверява. Проба на FLOW GUARD (реален Mongo, 3 режима): Paid фактура → сторно 201 → allocate P→Q 200, разходът минава от P към Q без версия и без canonical AuditEvent.
- **Допълнение (#81):** и на `5c0faa5` след плащане `/invoice-lines/{id}/allocate` може да намали разпределението без проверка за платена фактура (SUSPECTED).
- **Решение:** промяна в кода — поправката на FG-83 (версия на разпределението с причина и AuditEvent при статус ≠ Draft) преди merge на WH-REV-01, или сторно на ред от не-Draft фактура → DQ задача.

## FG-196 — сторното не създава очакване за кредитно известие — по Р44 фактурата остава платима в пълен размер

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 21).
- **Канон:** FLOW-006 (кредитно известие); Р44.
- **Код (WH-REV-01 `ed8f9e7`):** Свързаният ред остава 100% разпределен → по Р44 платим, въпреки че стоката е върната; при складов път стойността излиза от наличността и не е разход на никой обект.
- **Решение:** Крум да реши: DQ задача към Счетоводителя „очаква кредитно известие или ново получаване“.

## FG-197 — основание от един интервал минава при сторно

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 21).
- **Канон:** FLOW-009 „движение без основание“.
- **Код (WH-REV-01 `ed8f9e7`):** `routes/warehouse_canonical.py:458` — `reason` с `min_length=1`, `" "` се приема.
- **Решение:** промяна в кода — `strip()` и 422 при празно.

## FG-198 — т.3 (FG-191) изисква финансова роля за цена на несвързано получаване — против Р32 (склададжията въвежда единична цена при приемане)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (проход 21).
- **Канон:** Р32 (уточнява Р20 за склада).
- **Код (пакет WH-FIX-01 (`2a52fc4`)):** Пакет `docs/architecture/tasks/WH-FIX-01_POST_55_RESIDUE.md` т.3: „без ред — финансова роля + причина … по Р20“.
- **Решение:** Крум да реши: при несвързано получаване склададжията пише цена по Р32 с DQ задача вместо 403, или Р32 се стеснява.

## FG-199 — header-only разпределена фактура от доставчик се брои в обекта, маха се от „фактури за разпределяне“ и се плаща — против Р45/Р44

- **Тежест:** **blocker**. **Статус:** open. **PROVEN (проба `fg21probe/test_fg21_probe.py`, реален Mongo + mongomock)** (проход 21).
- **Канон:** Р45 (1) „…системата го **записва изрично на всеки ред** с AuditEvent … Флаг само в заглавието не е достатъчен.“; (2) „процент на ниво фактура не е окончателно разпределение“; (4) „Справките **не** показват временно разделение по процент; неразпределената фактура е само в „фактури за разпределяне“ …“; FLOW-008 L142 „неразпределена фактура да влиза в P&L на обекта;“; FLOW-043 D-04.
- **Код (#81 `5c0faa5`/`dae15da`):** `services/invoice_allocation.py:102-107, 126-128` (`ensure_payable` пропуска header-only: „unchanged until the FLOW Guard rules (debt)“), `:219-228` (брои се за разпределена); `routes/dashboard.py:791-803` (един проект в заглавието → целият `total`; суми в заглавието → разделяне). Проба на реален Mongo: заглавие с един проект, ред без разпределение → finance-by-project 1200, P&L на обекта 0, не е в „за разпределяне“, DQ 0, плащане 201; заглавие 700/500 → разделяне, 201; заглавие с проект + ред 100% към склад → 1200 на обекта (двойна класификация). Тестът `test_wh_fix_01_a3_r44_allocation.py:176-187` твърди точно това поведение.
- **Решение:** промяна в кода — премахни header fallback за `Received` фактури: header-only = висяща в „фактури за разпределяне“, плащане 409, докато дестинацията не е записана на всеки ред с AuditEvent (Р45 (1)); процентът само като помощ за точна сума на ред (Р45 (2)); миграция по Р45 (3) като отделна задача; заглавие/`project_id` само за издадени (приходни) фактури.

## FG-200 — фактури от доставчик, създадени от основния UI, пазят редовете вградени → броят се за разпределени и се плащат (Р44 се заобикаля)

- **Тежест:** high. **Статус:** open. **PROVEN (проба P1, реален Mongo на `5c0faa5`; mongomock на `f674eed`)** (проход 21).
- **Канон:** Р44; FLOW-020 L200 „фактурен ред без дестинация да стане окончателен;“; FLOW-009 L84.
- **Код (#81 `5c0faa5`/`dae15da`):** `InvoiceEditorPage.js:306` → `POST /finance/invoices` пази редовете в `invoice.lines` (`routes/finance.py:874-899`), `project_id` на реда се губи, документи в `invoice_lines` не се създават; `invoice_allocation_state` чете само `invoice_lines` (`services/invoice_allocation.py:83`) → ALLOCATED. Проба: quick-pay 1200 → 201, не е в „за разпределяне“, не е в никоя справка по обект.
- **Решение:** промяна в кода — вградени редове без разпределение = висяща фактура (или задължителни `invoice_lines` за `Received`); Крум да реши, защото блокира всички UI фактури от доставчик, докато редовете не се пренесат.

## FG-201 — DQ задачата и ескалацията към Собственика по Р44 се обновяват само при четене на списъка; GET пише без AuditEvent

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (проход 21).
- **Канон:** Р44 „…в срок 3 дни (DQ задача + аларма); след срока — ескалация към Собственика.“; FLOW-026 (аларми със срок); CLAUDE.md §14.
- **Код (#81 `5c0faa5`/`dae15da`):** `services/invoice_allocation.py:151-204` — DQ/аларма се пресмятат при GET `invoices-to-allocate`; няма scheduler → без отваряне няма ескалация; GET-ът пише без AuditEvent. Признато като дълг в PR.
- **Решение:** промяна в кода — scheduler job или проверка на срока в alarm feed-а; записите от DQ с AuditEvent.

## FG-202 — каноничните количества се свързват с планираните/заявените материали по име, не по `item_id`

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 21).
- **Канон:** FLOW-009 „Един материал има Master артикул по FLOW-032“.
- **Код (#81 `5c0faa5`/`dae15da`):** `services/canonical_material_cost.py` `canonical_trail_by_name`; `routes/materials_baseline.py:222-227` — при различно свободно име каноничните количества не се показват.
- **Решение:** промяна в кода — свързване по `item_id`.

## FG-203 — статичният скенер за писатели по каноничния регистър не хваща alias на атрибут и `getattr`

- **Тежест:** low. **Статус:** open. **PROVEN (директно извикване)** (проход 21).
- **Канон:** FLOW-009 „Всяко движение е отделен неизтриваем запис“ (един писател).
- **Код (#81 `5c0faa5`/`dae15da`):** `services/warehouse_movements/legacy_inventory.py:122-181` — `wt = tenant.warehouse_transactions; wt.update_many(...)` и `getattr(tenant, …)` не се хващат (директно извикване на `_indirect_canonical_writes` → []).
- **Решение:** промяна в кода — разшири `_HANDLE_ASSIGN_RE` за `= <x>.warehouse_transactions` и `getattr(…)`.

## FG-204 — парите на таблата (P&L на всички обекти, плащания, прогноза, Pulse) се виждат от всяка роля

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — §Персонални/ролеви табла „Чувствителните маржове, комисионни, заплати и обща печалба не се разкриват чрез Dashboard на потребител без право“; Р20, Р31.
- **Код (main `cd03324`):** `routes/project_pnl.py:68-69` (`/org/pnl-overview`, само `get_current_user`), `:109-112` (`/projects/{id}/pnl/aggregated`, без роля и без `can_access_project`); `routes/dashboard.py:26-27` (`/dashboard/pending-payments`), `:298-300, 460-462, 582, 667, 755, 910` (само `require_m5` = модул, не роля); `routes/cashflow_forecast.py:137-138`, `routes/morning_briefing.py:13-20`; `routes/pulse.py:49-124` (`labor_cost` по работник, без членство). UI: `DashboardPage.js:48` слага SiteManager в `isManager` и показва печалба/марж на всички обекти (`:234-251`), а Accountant е изключен.
- **Решение:** промяна в кода — затваря се от #71 SEC-02 (`permissions/finance_read.py` регистрира тези пътища); отделно в UI `isManager` да се води от правото, не от списък роли.

## FG-205 — cash-flow прогнозата брои задълженията към доставчици като постъпления и започва от 0

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — „Текущо състояние, начислен резултат и прогноза никога не се смесват“; „Какво НЕ трябва: forecast да се представя като текущ факт“.
- **Код (main `cd03324`):** `services/cashflow_forecast.py:18-23` чете `invoices` със статус Sent/PartiallyPaid без филтър по `direction` → неплатените получени фактури влизат в „Incoming“; `:130-153` кумулативът започва от 0, а се нарича `lowest_cash_day`; същото без `direction` в `routes/morning_briefing.py:77-80`.
- **Решение:** промяна в кода — Issued → вход, Received → изход; начало от каса/банка по FLOW-006; етикет „прогноза“.

## FG-206 — формулите на таблото се различават от официалната (`/finance/stats`); Draft/Cancelled влизат; филтрите важат частично

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — „карта да има различна формула от официалния регистър“ е забранено; drill-down по включени/изключени статуси.
- **Код (main `cd03324`):** `routes/dashboard.py:32`, `services/cashflow_forecast.py:20`, `routes/morning_briefing.py:78` — само Sent/PartiallyPaid, `Overdue` изпада (срещу `finance.py:2017-2034` `$nin Draft/Cancelled/Paid`); `dashboard.py:336-340, 352-356, 498-506` без статус; `:532` смесва начислени фактури с каса и нетни заплати в един `net`; филтрите `:491-495` важат само за фактурите; `client_id` (`:468`) се игнорира; `project_id`/`warehouse_id` си презаписват `allocations` (`:493,495`).
- **Решение:** промяна в кода — една обща функция за вземания/задължения; отделни карти „начислено“ и „пари“; филтрите важат за всички източници или картата казва какво е изключено.

## FG-207 — Pulse пази snapshot и го показва като текущ; втори списък аларми без статус; GET пише

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — „Не пази отделни истини… Всяка карта се изчислява от официалните domain регистри“; CLAUDE.md правило 12.
- **Код (main `cd03324`):** `services/pulse_generator.py:160-169` записва `site_pulses` (`total_labor_cost`, `budget_snapshot`, `daily_report_submitted`, `alerts`); `routes/pulse.py:85-90` генерира само ако за деня няма; `:53-59, 105-111` връщат/сумират запазеното; `morning_briefing.py:51-59, 99-103` чете запазеното; `pulse_generator.py:119-132` — паралелни аларми; `POST /pulse/generate*` (`pulse.py:74-98`) за всяка роля; бюджет от `work_sessions.labor_cost` (`:76-86`), не по Р31.
- **Решение:** промяна в кода — Pulse при четене (или snapshot само като исторически архив с `as_of`); алармите само през `alarm_events`.

## FG-208 — алармата няма собственик, срок и действие

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — §Алармен център „Всяка аларма има собственик, срок, статус, засегнат запис и действие/линк.“
- **Код (main `cd03324`):** `services/alarm_engine.py:39-51` — `site_id` и `context.entity_id`, без `owner`/`due_at`/линк; `RuleCreate` (`routes/alarms.py:26-33`) само `notify_roles`.
- **Решение:** промяна в кода — `owner_id` по правило/роля на обекта, `due_at` по тежест, ескалация (сродно с FG-181, FG-201).

## FG-209 — „видяна“ аларма изпада от броячите; „решена“ с едно кликване от всяка роля, без причина и одит

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — „аларма да бъде „решена“ само защото е прочетена“ е забранено; тест „аларма `видяна` остава отворена до реално решение“.
- **Код (main `cd03324`):** `routes/alarms.py:79-81, 89`, `morning_briefing.py:16-21` броят само `status:"active"`; списъкът по подразбиране `active` (`alarms.py:56`, `AlarmsDashboardPage.js:34`); `resolve` (`alarms.py:149-159`) — всяка роля, без причина (UI праща `{}`, `AlarmsDashboardPage.js:65`), без проверка на условието, без AuditEvent. `morning_briefing.py:21` сортира `severity` като низ (critical може да изпадне от top-3).
- **Решение:** промяна в кода — броячите включват `acknowledged`; resolve с право, бележка/доказателство и canonical AuditEvent; сортиране по ранг на тежестта.

## FG-210 — auto-resolve затваря аларми, чието условие още е вярно (заради cooldown)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — същият като FG-209.
- **Код (main `cd03324`):** `services/alarm_engine.py:87-88` пропуска събитие при активен cooldown → `new_events` празно → `:189-197` маркира всички активни на правилото като `resolved`/„Auto-resolved“; следващата оценка ги отваря пак.
- **Решение:** промяна в кода — auto-resolve само за обекта, чието условие е проверено като невярно.

## FG-211 — алармите не се оценяват автоматично — само с бутон

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — алармен център, realtime/дневен преглед (FLOW-015; CLAUDE.md §9).
- **Код (main `cd03324`):** единственият извикващ на `evaluate_all_rules` е `POST /alarms/evaluate` (`routes/alarms.py:162-165`, бутон `AlarmsDashboardPage.js:74`); няма scheduler (`server.py:583` пуска само `reminder_loop`).
- **Решение:** промяна в кода — периодична оценка за всеки tenant през Tenant Guard; или Крум да реши, че v1 е ръчна.

## FG-212 — всеки логнат вижда присъствието и болничните на всички служители

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-015, проход 22).
- **Канон:** FLOW-015 — ролеви табла „техник — неговите обекти…“; FLOW-002.
- **Код (main `cd03324`):** `routes/dashboard.py:71-85, 147-191` `/dashboard/personnel-today` — само `get_current_user`; връща `day_status` (sick/leave/absent), обект и часове за всички.
- **Решение:** промяна в кода — филтър по обхвата на ролята, без причина за отсъствие за не-управленски роли; или решение на Крум за по-широк достъп.

## FG-213 — две конкуриращи се корекции на разпределение след сливане на #81 и #82 (две полета, две хранилища на версии, две AuditEvent действия)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба `fg22probe`, пробно сливане)** (проход 22).
- **Канон:** CLAUDE.md §16 „не създавай втори ledger/registry/source of truth“; FLOW-006 §Корекции.
- **Код (#81 `c86d161` + #82 `1622f62` (пробно сливане)):** #81 изисква `correction_reason` (`routes/invoice_lines.py:761-768`), #82 — `reason` (`:72-95` на #82), и двете дават същия 409. Проба на пробното сливане (3 режима): нищо / само едното → 409; и двете → 200, пишат `invoice_line_allocation_versions` и `invoice_versions` и две AuditEvent (`finance.invoice_line.allocation_corrected`, `invoice_line.allocation_corrected`). Сливането има конфликти в `models/invoice_lines.py`, `routes/invoice_lines.py`, `services/warehouse_movements/service.py`, `tenancy/ownership.py`; капан: `_plan_receipt_reversal` губи `@staticmethod`.
- **Решение:** промяна в кода — едно поле, едно хранилище на версии, едно действие; #82 да се пребазира върху механизма на #81 и да добави контекста `reversed_receipts`.

## FG-214 — две DQ хранилища: „очаква кредитно известие“ не е в DQ/алармите на #81

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (проход 22).
- **Канон:** Р44, Р47 (DQ задача към Счетоводителя); CLAUDE.md §8 (каноничен DQ runtime).
- **Код (#81 `c86d161` + #82 `1622f62` (пробно сливане)):** #81 пише `dq_issues` + `alarm_events`; #82 влага `dq_task` в `expected_credit_notes` (`service.py:1947-2006` на #82).
- **Решение:** промяна в кода — DQ задачата по Р47 през пътя `dq_issues`/sync на #81.

## FG-215 — издадени (приходни) фактури с проект само в заглавието губят прихода по обект

- **Тежест:** medium. **Статус:** open. **PROVEN (проби P6/P10)** (проход 22).
- **Канон:** Р45 е за доставчици; FLOW-008 (приход по обект); Q002 (заглавие/`project_id` само за приходни).
- **Код (#81 `c86d161`):** Издадена фактура с header `allocations`=[prj-1] и вградени редове → няма приход в finance-by-project, отива в „фактури за разпределяне“ + DQ; автоматичното записване на редовете е само за `Received` (`finance.py:1083`, `dashboard.py:830`). На main същата фактура броеше целия приход към обекта.
- **Решение:** Крум да реши: (а) издадените фактури запазват проекта от заглавието, или (б) Р45 важи и за приходите със същото автоматично записване на редовете.

## FG-216 — тестовете на #82 разчитат на мекия Master режим, който #81 премахва

- **Тежест:** low. **Статус:** open. **PROVEN (пробно сливане)** (проход 22).
- **Канон:** FLOW-009 „Master артикул по FLOW-032“ (FG-192).
- **Код (#82 `1622f62`):** След сливане с #81 сторно маршрутът е strict („item_id is not registered“); тестовете на #82 не засяват `md_item`.
- **Решение:** промяна в тестовете — `md_item` в `_prepare` на #82.

## FG-217 — втора чернова на изходяща фактура → 500 (уникален индекс по `invoice_no` хваща null); входяща фактура с наш следващ номер блокира издаването

- **Тежест:** high. **Статус:** open. **PROVEN (проба P1, реален Mongo)** (проход 23).
- **Канон:** Р49 (1) „чернова на фактура се поправя свободно; при получаване на номер фактурата е заключена“; (3) „в общата номерация с фактурите“.
- **Код (#84 `7446d85`):** `server.py:572` създава `invoices (org_id, invoice_no) unique sparse`; черновите пишат `"invoice_no": None` (`routes/finance.py:936`); sparse compound индекс индексира null → втората чернова на tenant-а → 500 DuplicateKeyError. Входяща фактура с номер INV-0001 → нашето издаване 409 `INVOICE_NUMBER_TAKEN` при всеки опит.
- **Решение:** промяна в кода — без поле `invoice_no` в черновите (или `$unset`) и частичен индекс по `issued_number`/посока, чрез миграция.

## FG-218 — номерацията засяда завинаги при сблъсък (ръчен номер в автоматичната поредица)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба P3)** (проход 23).
- **Канон:** Р49 (3) обща номерация.
- **Код (#84 `7446d85`):** Ръчен INV-0002 → автоматично INV-0001 OK → после 409 `INVOICE_NUMBER_TAKEN` ×3: abort връща `$inc` назад и се опитва същият номер (`routes/finance.py:1205-1220`, `services/invoice_corrections.py:167-175`).
- **Решение:** промяна в кода — прескачане на заетите номера в транзакцията или отказ на ръчен номер в автоматичната поредица.

## FG-219 — входящо кредитно известие с разлика 1 стотинка се приема за съвпадение

- **Тежест:** low. **Статус:** open. **PROVEN (проба P5)** (проход 23).
- **Канон:** Р49 (8) „при съвпадение до стотинка лимитът се преизчислява; при разлика лимитът остава + DQ“.
- **Код (#84 `7446d85`):** `services/invoice_corrections.py:74, 521` — `<= 0.01`; очаквано 36.00, известие 35.99 → съвпадение, DQ затворен.
- **Решение:** промяна в кода — `==` след закръгляне до стотинки (или Крум да реши толеранс).

## FG-220 — входящото известие се сравнява със сбора на всички очаквани, а не се свързва от Счетоводителя с конкретния ред

- **Тежест:** medium. **Статус:** open. **PROVEN (проба P6)** (проход 23).
- **Канон:** Р49 (8) „свързва се от Счетоводителя с очакваното“.
- **Код (#84 `7446d85`):** `services/invoice_corrections.py:514-535` — сравнение със сбора на отворените редове; очаквани 20 и 16, известия 20 и 16 → и двете отказани като „разлика“, задължението остава 240.
- **Решение:** промяна в кода — изрично `expected_credit_note_id`, избран от Счетоводителя, сравнение по ред.

## FG-221 — анулиране на официална фактура и смяна на падежа след изпращане — без Approval; падежът и без canonical AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN (тест + проба P11)** (проход 23).
- **Канон:** FLOW-025 §DOC-12 L239 „Към FLOW-034 се изпращат … документи с реален … финансов … ефект:“, L241 „срок“, L244 „прекратяване/анулиране;“; Р49 (2) „анулиране с причина“.
- **Код (#84 `7446d85`):** `routes/finance.py:1340-1407` — анулиране от един финансов потребител само с причина; `due_date` се редактира след изпращане без AuditEvent (проба P11).
- **Решение:** Крум да реши: заменя ли Р49 (2) изискването на FLOW-025 L244, или анулирането иска одобрение от Собственика; за падежа — промяна в кода (AuditEvent; Approval по решение).

## FG-222 — прихващането пази само свободен текст, без правно основание и документ

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 23).
- **Канон:** FLOW-010 §10 L355-357 „изрично договорно/правно основание; точни source obligations“.
- **Код (#84 `7446d85`):** `routes/invoice_corrections.py:375-416` — само `reason`, без основание/референция/`file_id`.
- **Решение:** промяна в кода — задължително `basis` (референция + `file_id`).

## FG-223 — входящо дебитно известие се прилага веднага, без основание и одобрение

- **Тежест:** medium. **Статус:** open. **PROVEN (проба P13)** (проход 23).
- **Канон:** Р49 изисква основание само за дебитно известие **към клиент**; FLOW-025 L239/L242 (промяна на стойност → FLOW-034).
- **Код (#84 `7446d85`):** Проба P13: входящо дебитно известие → задължението 240 → 276 веднага.
- **Решение:** Крум да реши: основание и/или одобрение за входящо дебитно известие (канонът мълчи за посоката).

## FG-224 — `POST material-waste` дава 503 вместо 428 за office ролите; тестът на SEC-01 за PM-01 матрицата е червен

- **Тежест:** medium. **Статус:** open. **PROVEN (тест)** (проход 23).
- **Канон:** CLAUDE.md §14 (idempotency key; правата преди валидацията — Р29 → 428).
- **Код (#81 `d2fe80b`):** `routes/material_waste.py:100-106` — правата първо (`canon.require_project_writeoff`), ключът след това; в PM-01 harness-а каноничната проверка връща 503 преди 428; `test_sec_01_money_write_permissions.py::test_the_pm01_matrix_shows_the_money_write_cells_closed` червен на `d2fe80b`, зелен на main `4bca18a`.
- **Решение:** промяна в кода/теста — harness-ът да подава валиден каноничен контекст, за да стигне 428; или Крум/оркестраторът приема 503/403 преди 428 и тестът се сменя.

## FG-225 — плащане към непроверена/сменена сметка все още стига до FLOW-006 през три пътя

- **Тежест:** high. **Статус:** open. **PROVEN (проби B1, B2, реален Mongo)** (проход 23).
- **Канон:** FLOW-010 §8.1 L250 „…изпълнението е блокирано до успешна верификация.“; FLOW-025 L187 „не може да разреши плащане към непотвърден получател/банкова сметка;“
- **Код (#83 CP-01 `ea51030`):** (a) `POST /finance/payments/{id}/allocate` (`routes/finance.py:1864+`) без проверка — в **enforce**: плащане на cp2 (проверена сметка) + allocate към фактура на cp1 (IBAN несъвпадение) → 201/200, `paid_amount` 100; (b) `/subcontractor-payments` с `payment_method:"cash"` и банкова сметка → 201, банков изходящ поток, проверката пропусната (`subcontractors.py:520-522`, `bank_account_guard.py:125`); (c) `/finance/other-expense` с BankTransfer → 201 без guard.
- **Решение:** промяна в кода — allocate: плащането трябва да е на страната на фактурата и с проверена сметка (иначе 409); методът при подизпълнители по типа на сметката, не по `payment_method`; other-expense с банков метод → guard или забрана.

## FG-226 — пълно ЕГН изтича през invoice-details и списъка с обекти

- **Тежест:** medium. **Статус:** open. **PROVEN (проби B8, B9)** (проход 23).
- **Канон:** Р48 (3) „останалите виждат `******1234` …“
- **Код (#83 CP-01 `ea51030`):** `GET /projects/{id}/invoice-details` (`routes/projects.py:365-371`) не маскира → Viewer/Technician/SiteManager виждат legacy пълно ЕГН; `GET /projects` (`:154`) → Admin вижда пълно ЕГН.
- **Решение:** промяна в кода — `_mask_owner_egn` и в двата reader-а; миграция за маскиране на legacy копията в `invoice_details`.

## FG-227 — търсенето по ЕГН е оракул за всеки логнат; маската в Master Data е различна

- **Тежест:** low. **Статус:** open. **PROVEN (проба B5)** (проход 23).
- **Канон:** Р48 (3).
- **Код (#83 CP-01 `ea51030`):** `/clients/search/unified` (`routes/clients.py:426`) връща съвпадение за пълно ЕГН и 0 за грешно на Viewer/Technician/SiteManager; `master_data/uniqueness.py:73-80` маскира като `12****90`, не `******1234`.
- **Решение:** промяна в кода — търсене по ЕГН само за Owner/Accountant с точно съвпадение; маската `******1234`.

## FG-228 — при смяна на IBAN въвелият и проверилият могат да са двамата одобряващи

- **Тежест:** medium. **Статус:** open. **PROVEN (проба B3)** (проход 23).
- **Канон:** FLOW-025 L146 „независима проверка; двойно одобрение при промяна“; FLOW-034 L62; Р48 (1), (2).
- **Код (#83 CP-01 `ea51030`):** `routes/bank_accounts.py:299-301` проверява само дали същият човек вече е одобрил; проба B3: approvers = [acct-a (въвел), owner-a (проверил)].
- **Решение:** Крум да реши (Q005 D7): одобряващите различни от въвелия/проверилия, или проверил + един друг при малък офис.

## FG-229 — ЕИК на подизпълнител не се проверява за дубликат

- **Тежест:** medium. **Статус:** open. **PROVEN (проба B6)** (проход 23).
- **Канон:** Р48 (6) „ЕИК, който вече е на друг контрагент → отказ“; FLOW-010 §12 L379.
- **Код (#83 CP-01 `ea51030`):** `routes/subcontractors.py:60-71` — дубликат → 201/201; ЕИК като на контрагент cp1 → 201.
- **Решение:** промяна в кода — claim ред + проверка като в `counterparties.py:107-114`; между регистрите — в CP-02 (FG-166).

## FG-230 — клонът е от `cd03324` и конфликтира с main `4bca18a` (SEC-01); `dq_issues` с различна схема от #81

- **Тежест:** high. **Статус:** open. **PROVEN (merge-tree) / SUSPECTED (DQ схема)** (проход 23).
- **Канон:** CLAUDE.md §16 (един registry); FLOW-017 (проверка на реалния diff преди merge).
- **Код (#83 CP-01 `ea51030`):** `git merge-tree 4bca18a ea51030` → CONFLICT в `routes/clients.py`, `routes/projects.py`, `routes/subcontractors.py`, PM-01; CP-01 пише `dq_issues` с `code`/`severity`, #81 с `owner_role`/`status`.
- **Решение:** промяна в кода — rebase върху `4bca18a`, една схема за `dq_issues`, повторно пускане на CP-01, PAY-01, PM-01, SEC-01.

## FG-231 — два доставчика с еднакъв номер на фактура се отказват (уникалност на ниво фирма, не на издател)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба Q1)** (проход 23c).
- **Канон:** FLOW-025 §DOC-05 L125 (входяща фактура, duplicate check); FLOW-010 §2 (контрагентът е отделна организация).
- **Код (#84 `71957db`):** `routes/finance.py:915` (`validate_invoice_no_unique` на ниво org) и новият уникален индекс `(org_id, direction, invoice_no)` (`services/invoice_corrections.py:493`) → два различни доставчика с № `0000000123` → [201, 400].
- **Решение:** Крум да реши; предложение: уникалност на входящите по (org, ЕИК на доставчика, номер), вкл. в индекса.

## FG-232 — PUT на чернова с ръчен номер → 500 (KeyError след поправката на FG-217)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба Q2)** (проход 23c).
- **Канон:** Р49 (1) „чернова на фактура се поправя свободно“.
- **Код (#84 `71957db`):** `routes/finance.py:1079` — `invoice["invoice_no"]` върху чернова без поле; удря ръчната номерация от `InvoiceEditorPage.js:314`.
- **Решение:** промяна в кода — `invoice.get("invoice_no")` + тест.

## FG-233 — грешна входяща фактура се анулира, макар да е свързана със складово приемане само по `invoice_id`

- **Тежест:** medium. **Статус:** open. **PROVEN (на ниво данни, проба Q5) / SUSPECTED (надпревара)** (проход 23c).
- **Канон:** Р51 (3) „анулиране … ако не е платена и не е свързана със складово приемане … иначе корекция/сторно“.
- **Код (#84 `71957db`):** `services/invoice_corrections.py:621-627` (`linked_to_warehouse`) гледа само `warehouse_transactions.invoice_line_id`; каноничното приемане позволява само `invoice_id` (`warehouse_movements/service.py:180, 970`); cancel не взима заключването на реда (`bump_line_lock`).
- **Решение:** промяна в кода — проверка и по `invoice_id` + заключване на редовете в транзакцията за анулиране.

## FG-234 — анулиране предлагат и Admin/Owner; предложение на Owner не може да се одобри при един Owner; висящото не отпада при изпращане

- **Тежест:** low. **Статус:** open. **PROVEN (проба Q4)** (проход 23c).
- **Канон:** Р51 (1) „Счетоводителят предлага с причина, Собственикът одобрява“.
- **Код (#84 `71957db`):** Проба Q4: Admin предлага → 200; Owner предлага → само Owner одобрява → остава висящо; след изпращане предложението остава pending.
- **Решение:** Крум да реши дали Admin/Owner могат да предлагат; промяна в кода — автоматично `superseded` при изпращане/плащане.

## FG-235 — промяна на `notes` на изпратена фактура без canonical AuditEvent; анулиране на грешна входяща фактура и от Admin/Owner

- **Тежест:** low. **Статус:** open. **PROVEN (проби Q5, Q6)** (проход 23c).
- **Канон:** CLAUDE.md §14 (AuditEvent за всеки запис); Р51 (3) „анулиране от Счетоводителя“.
- **Код (#84 `71957db`):** Проба Q6: `notes` → 0 събития; Q5: Admin/Owner също анулират входяща.
- **Решение:** промяна в кода — AuditEvent за `notes`; правото за анулиране на входяща по Р51 (3) (или дълг).

## FG-236 — гаранционната работа отива в отделен обект тип „Warranty“; типът се сменя със задна дата

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-018, проход 24).
- **Канон:** FLOW-018 „гаранционната работа се извършва в оригиналния обект чрез повторно активиране, а не в нов Project“; „разходите по гаранционна работа се виждат отделно“; FLOW-001 L72, L101.
- **Код (main `8c52e92`):** `routes/projects.py:49`, `models/projects.py:8` (`PROJECT_TYPES` с `Warranty`); `create_project` приема `type="Warranty"` без връзка към оригинала (`projects.py:181-182`); UI „Гаранционен“ (`ProjectsListPage.js:297, 492`); `PUT /projects/{id}` сменя `Billable ↔ Warranty` по всяко време (`projects.py:300-301`) → целият натрупан разход се преименува.
- **Решение:** промяна в кода — без `Warranty` за нови обекти, типът неизменим след първия разход, гаранционният разход се маркира на ниво запис в оригиналния обект; Крум да реши съдбата на съществуващите Warranty обекти (мапване при миграцията към FLOW-039).

## FG-237 — приключен обект не може да се отвори отново (няма Completed → Active) — изходът за гаранция е нов обект

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-018, проход 24).
- **Канон:** FLOW-018 (както FG-236); FLOW-001 P-08 „обектът може да се отвори отново към Активен … посочва се причина и се записва AuditEvent“.
- **Код (main `8c52e92`):** `routes/projects.py:286` `"Completed": ["Archived"]`; `services/project_guards.py:9, 33-38` отказва всеки запис в Completed (`work_sessions.py:140`, `attendance.py:399`, `technician.py:861`, `procurement.py:127`, `extra_works.py:178`).
- **Решение:** промяна в кода — преход Completed → Active с причина, AuditEvent и право; „гаранционно отваряне“, което маркира следващите разходи; повторно затваряне.

## FG-238 — снимка на обекта (доказателство) се трие окончателно заедно с оригиналния файл

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-018, проход 24).
- **Канон:** FLOW-018 „НЕ … изтриване на дефектна история“, доказателства „преди/по време/след“; CLAUDE.md правило 9 и §4 (оригиналната снимка се пази).
- **Код (main `8c52e92`):** `DELETE /projects/photos/{photo_id}` (`routes/projects.py:957-978`) — качилият или Admin/Owner: `file_path.unlink()` (`:972`) + `project_photos.delete_one` (`:975`); без проверка за използване, само legacy `log_audit`.
- **Решение:** промяна в кода — soft-retire (статус, причина, AuditEvent) вместо `unlink`/`delete_one`; заедно с File Registry (W0-06, FG-143).

## FG-239 — Admin трие окончателно обект с цялата му история (разходи, плащания, снимки, отчети остават сираци)

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-018, проход 24).
- **Канон:** CLAUDE.md правило 9 „Няма hard delete на използвани, финансови, договорни или одобрени записи“; FLOW-018; FLOW-001 L44 (използвано не се трие).
- **Код (main `8c52e92`):** `DELETE /projects/{project_id}` (`routes/projects.py:321-339`) — единствената защита е броят подобекти (`:328`); после `projects.delete_one` (`:331`) и `delete_many` на `project_team`/`project_phases` (`:337-338`); не проверява статус, разходи, плащания, снимки, отчети.
- **Решение:** промяна в кода — 409 при каквато и да е история; архивиране вместо изтриване; изтриване само на празна чернова.

## FG-240 — „качество/rework“ на подизпълнител — свободна оценка без права, AuditEvent и история; „платеното“ се въвежда ръчно

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-018, проход 24).
- **Канон:** FLOW-018 „дефектът влияе върху рейтинг, плащане, прихващане“; забранени „отделна паралелна база“ и „плащане/прихващане извън Payment ledger“; CLAUDE.md §16 (втори source of truth).
- **Код (main `8c52e92`):** `routes/subcontractor_performance.py:71-98` — POST/PUT без роля (и Viewer), без AuditEvent, без проверка на съществуването; PUT презаписва `quality_score`/`rework_flag`; `quality_score` без валидация (`:34`); `actual_paid_amount` ръчно (`:33, 42`) — втори източник за „платено“ до `finance_payments`.
- **Решение:** промяна в кода — права (Owner/Admin/PM) + AuditEvent + append-only история; „платено“ от `finance_payments`; Крум да реши дали `subcontractor_performance` влиза в миграцията към FLOW-039 или се замразява read-only.

## FG-241 — приход по банка (`/finance/other-income`) се проверява като изходящо плащане → в enforce (production) приход не може да се запише

- **Тежест:** high. **Статус:** open. **PROVEN (проба C4)** (проход 24).
- **Канон:** FLOW-006 (единният регистър приема всяко реално движение; FLOW-025 L164 „…винаги се записва в единния Payment ledger“); FLOW-010 §8 (проверката е за изходящи плащания).
- **Код (#83 CP-01 `7e0b914`):** `routes/finance.py:653, 670-681` (`create_other_income`) — `check_payment_target(direction="Outflow", …)`, копирано от other-expense; приход по банка → 409 `NO_VERIFIED_BANK_ACCOUNT`; приход в брой от контрагент с висящ IBAN → 409 `PAYEE_BLOCKED_PENDING_IBAN`.
- **Решение:** промяна в кода — без guard за прихода (или `direction="Inflow"`) + тест.

## FG-242 — плащане в брой само с име на получателя (без `counterparty_id`) минава без разписка и без блок при висящ IBAN

- **Тежест:** medium. **Статус:** open. **PROVEN (проба C1, shadow и enforce)** (проход 24).
- **Канон:** Р50 (1) „плащане **в брой** към контрагент се допуска само срещу разписка … ако контрагентът има спрян/сменен непроверен IBAN, плащането в брой също е **спряно**“.
- **Код (#83 CP-01 `7e0b914`):** `services/bank_account_guard.py:63-64` (`if not party_id: return None`), `:196-198`; `POST /finance/payments` и `/finance/other-expense` с `counterparty_name:"Доставчик cp1"` → 201 без разписка, докато cp1 има висяща смяна на IBAN.
- **Решение:** промяна в кода — разписка за всяко изходящо плащане в брой с име на получател + блок при съвпадение с контрагент с висящ IBAN; или Крум да реши дали Р50 (1) важи без избран контрагент.

## FG-243 — висяща смяна на IBAN оцелява при архивиране и след връщането се активира без нова проверка

- **Тежест:** medium. **Статус:** open. **PROVEN (проба C3)** (проход 24).
- **Канон:** Р50 (3) „старият IBAN не важи автоматично — проверява се наново“.
- **Код (#83 CP-01 `7e0b914`):** `services/master_records.py:246-248` (`_reverify_bank_accounts` нулира само `status == verified`); проверена смяна с 1 одобрение отпреди архива → след връщането второто одобрение я активира → плащане към `****5678`.
- **Решение:** промяна в кода — нулиране на проверка и одобрения и за висящите сметки при връщане; отказ на verify/approve, докато контрагентът е архивиран.

## FG-244 — подизпълнителите нямат „неактивен“/„архивиран“

- **Тежест:** low. **Статус:** open. **PROVEN (проба C7)** (проход 24).
- **Канон:** Р48 (4) „контрагент никога не се изтрива … само „неактивен“ … или „архивиран“ …“.
- **Код (#83 CP-01 `7e0b914`):** `routes/subcontractors.py` — няма маршрути за деактивиране/архивиране (`POST /subcontractors/sub1/archive` → 404); кодът за тях в `master_records.py:227-229` е мъртъв.
- **Решение:** промяна в кода — маршрути през `mr.lifecycle`.

## FG-245 — пълен IBAN през legacy полета и фактури за Viewer/SiteManager/Admin; `dq_issues` с две семейства след сливане с #81

- **Тежест:** medium. **Статус:** open. **PROVEN (проби C8, C9)** (проход 24).
- **Канон:** Р50 / Q005: пълен IBAN само Owner и Accountant, Admin само с изрично право, останалите `****1234`; CLAUDE.md §16 (един registry).
- **Код (#83 CP-01 `7e0b914`):** `routes/counterparties.py:122-125` (`_public`, поле `iban`), `routes/subcontractors.py:102-116` (`bank_iban`), `GET /projects/{id}/invoice-details` (`invoice_details.iban`), `GET /finance/invoices` (`counterparty_iban`) за Admin; при сливане с #81 `dq_issues` се регистрира два пъти в `tenancy/ownership.py` (TASKS и AUDIT, ред 131).
- **Решение:** промяна в кода — `cr.mask_iban` във всички reader-и при `full_iban_allowed=false`; едно семейство за `dq_issues`.

## FG-246 — издадена фактура с одобрено прихващане се анулира — кредитното салдо на клиента изчезва

- **Тежест:** high. **Статус:** open. **PROVEN (проба R7)** (проход 25).
- **Канон:** Р49 (2) „преди изпращане … (не платена …) → анулиране“; Р49 (6) „кредитно по платена фактура → открито салдо … прихващане с изрично решение“; Р53 (2) „чакащо предложение се отменя автоматично, ако фактурата е изпратена/платена“.
- **Код (#84 `081f35b`):** `routes/finance.py:1426-1438` (`_cancel_blockers`) не гледа `invoice_offsets`; `_supersede_cancellation` не се вика при одобрение на прихващане (`routes/invoice_corrections.py` ~646). Проба: предложено анулиране → одобрено прихващане 36 → Owner одобрява анулирането → 200 Cancelled; прихващането остава `approved`, `credit_balance` на клиента = 0.
- **Решение:** промяна в кода — одобрено или висящо прихващане блокира анулирането; одобрението на прихващане отменя висящото предложение; тест.

## FG-247 — ефектът на входящо кредитно известие върху разхода е грешен и е само в P&L (отрицателен разход; другите справки и ДДС не се променят)

- **Тежест:** medium. **Статус:** open. **PROVEN (проби R1a, R1b)** (проход 25).
- **Канон:** Р52 (1) „Кредитно без сторно … намалява разхода по обекта/СМР на оригиналния ред в периода на известието (Р49.7)“; FG-17/5C-C22 (едно число във всички справки); FLOW-006 L62 (Net/VAT/Gross отделно).
- **Код (#84 `081f35b`):** `services/invoice_corrections.py:719-750` (fallback по `n.project_id`, без период), `services/project_pnl.py:113-114`. Проби: (a) входяща фактура с вградени редове не е в материалния разход (0), но известие 30 прави `material_cost = -30`; (b) Path B ред: P&L 100→50, но `project_material_cost` остава 100 (full_cost, financial_results, budget_progress, revenue_expense, centralized_reports, material_smr, pulse); (c) `input_vat`/`vat_payable` не се променят (20→20, трябва 10).
- **Решение:** промяна в кода — ефектът като лот в `project_material_cost` с период = `issue_date` на известието; без ефект, ако оригиналният разход не е признат; корекция на ДДС.

## FG-248 — преди миграцията същият доставчик с по-рано въведена фактура се дублира

- **Тежест:** medium. **Статус:** open. **PROVEN (проба R4c)** (проход 25).
- **Канон:** Р53 (1) „дубликат само при същия доставчик (ЕИК) + същия номер“.
- **Код (#84 `081f35b`):** `server.py:576-580` строи индекса `inv_cn_02_supplier_invoice_no` преди backfill на `supplier_key`; старите редове са с null → проверката не ги вижда; нова фактура със същия доставчик и номер → 201; планът на миграцията после показва `supplier_conflicts=1` и `apply` отказва.
- **Решение:** промяна в кода — проверката до миграцията пада на (`counterparty_eik`, номер); или Крум/Release Manifest: миграцията преди deploy.

## FG-249 — PUT, който сменя само ЕИК на доставчика и създава дубликат → 500; същият доставчик с ЕИК и само с име не се хваща

- **Тежест:** medium. **Статус:** open. **PROVEN (проби R4, R8)** (проход 25).
- **Канон:** Р53 (1).
- **Код (#84 `081f35b`):** `routes/finance.py:1088` проверява само при смяна на номера; запис на `:1122, 1152` → 500 DuplicateKeyError; `supplier_key` (`services/invoice_corrections.py:189`) — ЕИК срещу само име → 201/201.
- **Решение:** промяна в кода — проверка при всяка промяна на `supplier_key`, DuplicateKeyError → 409; Крум да реши задължителен ли е ЕИК при входяща фактура.

## FG-250 — Owner сам регистрира несъвпадащо входящо известие и сам приема разликата

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 25).
- **Канон:** Р49 (8) „свързва се от Счетоводителя с очакваното“; Р52 (2) „Собственикът може да приеме разликата“.
- **Код (#84 `081f35b`):** Проби R2, R7: Owner регистрира (201) и приема разликата (200).
- **Решение:** Крум да реши: регистрира само Счетоводителят, или регистриращият ≠ приемащият.

## FG-251 — приетата разлика по известие, свързано със сторно, не се осчетоводява никъде

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 25).
- **Канон:** Р52 (1), (2); CLAUDE.md §7 (пълна финансова история).
- **Код (#84 `081f35b`):** `supplier_note_cost_effect` пропуска свързаните известия; сторно 36, известие 30, приета разлика 6 → P&L губи 6 разход, задължението остава с 6 повече.
- **Решение:** Крум да реши къде се осчетоводява приетата разлика (разход/загуба на обекта или фирмен).

## FG-252 — `create-sub-project`, `wrap-in-group` и `add-subproject` създават нови обекти тип Warranty (типът се наследява от родителя)

- **Тежест:** high. **Статус:** open. **PROVEN** (проход 26).
- **Канон:** Р54 (1) „новите гаранционни работи се водят към оригиналния обект … типът на проект не се сменя“; FLOW-001 P-13 „Гаранционната работа не създава отделен Project“.
- **Код (#86 PRJ-01 `0bd77a1`):** `routes/projects.py:1751, 1836, 1885` (`"type": parent.get("type", "Billable")`), `:1954, 1984`, `:2045`; проба: create-sub-project от стар Warranty → 2 нови обекта тип Warranty.
- **Решение:** промяна в кода — подобект на Warranty родител не наследява Warranty (или 409 `WARRANTY_IN_ORIGINAL_PROJECT`); проверката в общ helper.

## FG-253 — свързан стар Warranty обект може да се отвори отново и пак да приема записи

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 26).
- **Канон:** Р54 (1); FLOW-001 P-13, P-08 (отваря се оригиналният обект).
- **Код (#86 PRJ-01 `0bd77a1`):** `reopen_project` не проверява `type`/`warranty_of_project_id`; проба: reopen → 200, `check_project_writable` = true.
- **Решение:** промяна в кода — 409 за обекти с `warranty_of_project_id` или тип Warranty, с насочване към оригинала (или решение на Крум).

## FG-254 — обект с файл, качен през `/api/media/upload` (`context_type`/`context_id`), се изтрива като „празна чернова“

- **Тежест:** high. **Статус:** open. **PROVEN** (проход 26).
- **Канон:** FLOW-001 §Какво НЕ трябва „изтриване на обект, по който има движения, отчети, фактури, снимки, материали или плащания;“; CLAUDE.md правило 9.
- **Код (#86 PRJ-01 `0bd77a1`):** `services/project_lifecycle.py:29` проверява само полета `*_id`; `routes/media.py:118-119` пише `context_type="project"`/`context_id`; DELETE → 200, `media_files` остава сирак; същото за `asset_qr_codes` (`entity_type`/`entity_id`).
- **Решение:** промяна в кода — двойките `(context_type, context_id)` и `(entity_type, entity_id)` в проверката за история.

## FG-255 — изчисленото „платено“ на подизпълнител се вижда от всяка роля

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 26).
- **Канон:** Р20 (финансите само за Owner/Admin/Accountant); Р54 (2).
- **Код (#86 PRJ-01 `0bd77a1`):** `GET /subcontractor-performance` (`routes/subcontractor_performance.py:77-97, 207-218`) — Viewer вижда `actual_paid_amount=150`; `/log` → 200 за Technician; без `require_finance_read`/`strip_money_for_non_finance`.
- **Решение:** промяна в кода — маскиране на паричните полета за роли без финансово право.

## FG-256 — PUT без приети полета създава празна версия; DQ задачата за неопределим оригинал остава отворена след `--map`; „платено“ брои само `subcontractor_payments`

- **Тежест:** low. **Статус:** open. **PROVEN (първите две) / SUSPECTED (третото)** (проход 26).
- **Канон:** CLAUDE.md §14; FLOW-033 (DQ се затваря при решение); FLOW-006 (единен регистър).
- **Код (#86 PRJ-01 `0bd77a1`):** `subcontractor_performance.py:173-200` — PUT с `promised_amount` → 200 и празна версия + AuditEvent; `migration:89-101, 140-155` — `PROJECT_WARRANTY_ORIGINAL_UNKNOWN` остава `open`; `services/subcontractor_performance.py:17-26` — само плащания през `subcontractor_payments`.
- **Решение:** промяна в кода — 422 при празни промени; затваряне на DQ в транзакцията на `--map`; Крум да реши каноничния ключ за плащане към подизпълнител.

## FG-257 — статусът при създаване не минава през таблицата на преходите; чернова без клиент става Активна

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-03 „Обект без клиент може да бъде чернова, но не може да стане активен търговски обект.“; контролна секция „активиране на търговски обект без основен клиент/възложител“; P-04 (10 статуса); P-07 (PM само чернова).
- **Код (main `ec7ddd8`):** `routes/projects.py:179-181` проверява само дали `status` е в списъка (`:48`) и го записва (`:211`) → `POST /projects` със Active/Completed/Archived/Finished/Stopped минава покрай `TRANSITIONS` (`:281-290`); SiteManager създава (`:171`), UI предлага Active (`ProjectsListPage.js:481`); Draft→Active (`:282`) не проверява клиент/адрес/ръководител/дати; `Finished` няма ред в `TRANSITIONS`; `models/projects.py:7` е друг списък.
- **Решение:** промяна в кода — при създаване само Draft; каноничен enum и transition service; Draft→Active само с клиент и данните от P-03 (409 + DQ); Крум да реши картата Finished/Stopped/Overhead → каноничен статус.

## FG-258 — клиентът се маха от Активен обект без AuditEvent

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-03; P-06 „Всички промени се записват в AuditEvent.“; CLAUDE.md §14.
- **Код (main `ec7ddd8`):** `PATCH /projects/{id}/client-link` (`routes/clients.py:696-747`) с `client_id=null` (`:714-719`) нулира `owner_*` при всеки статус; без `log_audit` и без canonical AuditEvent и при свързване (`:739-747`).
- **Решение:** промяна в кода — 409 при отвързване на Billable обект след Draft (смяна с причина); canonical AuditEvent с old/new.

## FG-259 — пауза/възобновяване и приключване са само смяна на поле — без данните на P-04A и проверките на P-10

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-04A „…причина, кой го е поискал, отговорна страна, засегнат scope, дата, условие за възобновяване и `Pause Impact Assessment`…“, „Спирането и възобновяването създават AuditEvent“; P-10 „…само след проверка за незатворени финансови, складови, payroll, подизпълнителски…“.
- **Код (main `ec7ddd8`):** `ProjectUpdate` (`routes/projects.py:80-102`) без полета за пауза; Active↔Paused/Stopped (`:283-285`) само със `status`, legacy `log_audit` (`:318`); два статуса за спиране; Active→Completed и Completed→Archived (`:283, 286`) без проверки (вкл. активни подобекти); няма „Blocked“ за СМР.
- **Решение:** промяна в кода — команди pause/resume/close със задължителни полета, Pause Impact Assessment и canonical AuditEvent; проверки преди приключване; един статус за спиране; Крум да реши кой спира/възобновява освен Owner/Admin (P-07).

## FG-260 — платецът не е отделна страна; получателят на фактурата се попълва от клиента

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-02 „…клиент / възложител, инвеститор, платец и контактни лица. Те могат да са една и съща фирма, но системата не трябва да го приема автоматично.“; Р22.
- **Код (main `ec7ddd8`):** Няма поле за инвеститор/платец като контрагент; `invoice_details` е свободен dict (`routes/projects.py:76, 100`), който SiteManager сменя през PUT (`:268-269`) и `import-client-invoice` (`:357-416`); `GET /projects/{id}/invoice-context` (`:985-1045`) взима получателя от `owner_id`, без `can_access_project`.
- **Решение:** промяна в кода — роли по обект (клиент/инвеститор/платец/контакт) към контрагенти; invoice-context от платеца; запис само от финансовите роли с AuditEvent; Крум да реши дали платецът е финансово поле по Р22.

## FG-261 — wrap-in-group/add-subproject създават директно Активни подобекти — без членство, без AuditEvent, и под приключен обект

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-07; P-03; P-06 „Всички промени се записват в AuditEvent“; P-08/P-13.
- **Код (main `ec7ddd8`):** `routes/projects.py:1736, 1832` (и create-sub-project `:1520`) проверяват само ролята, без `can_manage_project`; новите подобекти са `"status": "Active"` (`:1799, 1860`); кодът не се проверява за уникалност; без `log_audit` (`:1783, 1810, 1871`); add-subproject не гледа статуса на групата; `check_project_writable` не гледа родителя.
- **Решение:** промяна в кода — `can_manage_project`; новият подобект е Draft; 409 под приключен/архивиран/отказан родител; canonical AuditEvent; уникален код.

## FG-262 — архивираните/приключените обекти и подобектите изпадат от финансовите суми на фирмата

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-11 „…не го изключва от финансовите справки. Архивираните обекти участват в обороти, приходи, разходи, печалба/загуба, марж…“; P-12; P-05 „Основният обект обобщава данните от всички свои нива.“; P-16.
- **Код (main `ec7ddd8`):** `/org/pnl-overview` (`routes/project_pnl.py:91-95`) само `status ∈ {Active, Draft, Paused}` и `.to_list(100)` — суми за „Финансов анализ“, таблото и Pulse; `compute_org_profit_attribution` (`services/pnl_aggregator.py:88-91`) само главни обекти, `compute_project_pnl` само собствения; `except Exception: continue` (`:114-115`), лимит 200; ежедневният списък по подразбиране показва и архивираните (`ProjectsListPage.js:117, 125`).
- **Решение:** промяна в кода — фирмените суми върху всички статуси (без Draft/Отказан) и всички нива, без мълчаливо пропускане; оперативните менюта по подразбиране без Archived.

## FG-263 — използвано ниво от структурата се изтрива; промените по нивата са без AuditEvent

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-001, проход 26).
- **Канон:** FLOW-001 P-06 „Празно ниво може да се изтрие. Използвано ниво не може да се изтрие; може да се преименува, обедини или архивира. … Всички промени се записват в AuditEvent.“
- **Код (main `ec7ddd8`):** `DELETE /locations/{id}` (`routes/locations.py:168-208`) проверява само деца, `missing_smr`, `extra_work_drafts` (`:190-201`), не и `material_waste`, `smr_groups`, `employee_daily_reports.location_id`, `smr_analyses.lines.location_id`; в режим off → hard delete (`:207`); create/update на ниво и `delete_phase` (`projects.py:576-588`) без одит; SiteManager трие нива на всеки обект.
- **Решение:** промяна в кода — проверка по всички колекции с `location_id` → 409 + архив/обединяване; canonical AuditEvent; `can_manage_project`.

## FG-264 — уникалният индекс по доставчик се строи само от ръчния migrate скрипт — без него паралелни входящи дубликати минават (и за нови tenant-и)

- **Тежест:** medium. **Статус:** open. **PROVEN (проба S3)** (проход 26).
- **Канон:** Р53 (1) „входяща фактура е дубликат само при същия доставчик (ЕИК) + същия номер“.
- **Код (#84 `2c2e75f`):** `server.py:578`, `services/invoice_corrections.py:614-615` (коментарът „built at startup“ вече не е верен); без скрипта проверката е check-then-write: 6 паралелни POST → [201, 201, 201, 409, 409, 409], 3 записа; после планът показва `supplier_conflicts=2` и `apply` отказва. На `081f35b` индексът се строеше при стартиране.
- **Решение:** промяна в кода — индексът при стартиране/`ensure_indexes` за бази без стари конфликти + стъпка за нови tenant-и.

## FG-265 — приетата разлика по ред, приет в склада (сторно по #82), не се записва никъде

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 26).
- **Канон:** Р55 (3) „приета разлика … остава разход на обекта/СМР на оригиналния ред“.
- **Код (#84 `2c2e75f`):** Проба S6w: разлика 5 нето по складов ред → няма разход в нито един обект, разходът остава само в задължението; вероятно честият случай (`expected_credit_notes` от сторно по #82).
- **Решение:** Крум да реши: складов ред няма обект — загуба по склада/FIFO слоя или фирмен разход.

## FG-266 — пълно ЕГН (въведено, несъвпадащо с лицето) в legacy одита и в отговора при създаване на обект

- **Тежест:** medium. **Статус:** open. **PROVEN (проби D1, D3)** (проход 26).
- **Канон:** Р48 (3) „останалите виждат `******1234` …, вкл. в експорти и AuditEvent“.
- **Код (#83 CP-01 `bc0d1c7`):** `routes/projects.py:275` (`_store_invoice_details` пази пълно несъвпадащо ЕГН), `:388` `log_audit(..., update)` го пише в `audit_logs` (и глобално, видимо през `/audit-logs`), `:248` го връща на Admin при създаване. Регресия спрямо `7e0b914` (CP83-03).
- **Решение:** промяна в кода — `cr.mask_invoice_details` преди `log_audit` и в отговора.

## FG-267 — 10-цифрено ЕГН в `invoice_details.eik` без собственик или с фирма-собственик се показва изцяло на Admin

- **Тежест:** medium. **Статус:** open. **PROVEN (проба D2)** (проход 26).
- **Канон:** Р48 (3) „ЕГН се вижда изцяло само от Собственика и Счетоводителя“.
- **Код (#83 CP-01 `bc0d1c7`):** `services/counterparty_rules.py:131` маскира само при `field == "egn"` или `owner_type == "person"` (преди — всяка 10-цифрена стойност); проба D2: Admin вижда пълното ЕГН в `/projects/{id}`, `/projects`, `/invoice-details`. Регресия спрямо `7e0b914`.
- **Решение:** Крум да реши: 10-цифрена стойност без лице-собственик — маска (ЕГН първо) или видима (чужд VAT); предложение: маска, освен за Owner/Accountant.

## FG-268 — блокът за плащане в брой по Р50 (1) се заобикаля с вариант на името или ЕИК в тялото

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 26).
- **Канон:** Р50 (1) „плащането в брой също е **спряно** до проверката (не се заобикаля защитата)“.
- **Код (#83 CP-01 `bc0d1c7`):** `services/bank_account_guard.py:58-77`; `routes/finance.py:628, 1845` — с разписка и „Доставчик  cp1“ (два интервала), „Доставчик cp1 ООД“, латиница или `counterparty_eik` в тялото → 201, докато cp1 има висящ IBAN.
- **Решение:** промяна в кода — нормализиране на интервали и правна форма, използване на `counterparty_eik` от тялото; или Крум: плащане в брой с име изисква `counterparty_id`.

## FG-269 — директна доставка до обект се третира като „приета в склада“ — приетата разлика става фирмен разход вместо разход на обекта

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 27).
- **Канон:** Р58 „стока, приета **в склада** (не на обект) → фирмен разход“; Р55 (3) „…разход на обекта/СМР на оригиналния ред“.
- **Код (#84 `caea933`):** `services/invoice_corrections.py:933` (`first_linked_movement` хваща всеки ledger ред с `invoice_line_id`, вкл. `receive_from_supplier_to_project`); проба: директна доставка → разликата отива във фирмен разход, обектът не получава разход (контрола без ledger ред: обект 0→105).
- **Решение:** промяна в кода — фирмен разход само при складово приемане (`receive_from_supplier` към склад); директна доставка → разход на обекта по Р55 (3).

## FG-270 — едно складово приемане, вързано само към фактурата, прави всички редове на фактурата фирмен разход

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 27).
- **Канон:** Р58; Р55 (3).
- **Код (#84 `caea933`):** `services/invoice_corrections.py:935-937` — приемане без `invoice_line_id` прави и ред, разпределен към обект, фирмен разход (проба R58I: ред към prj-1 → фирмен, prj-1 без разход).
- **Решение:** промяна в кода — класификация по ред; приемане само по фактура не засяга редовете, разпределени към обект.

## FG-271 — фирменият разход по Р58 не влиза в нито една справка за фирмения резултат

- **Тежест:** medium. **Статус:** open. **PROVEN (код + проба)** (проход 27).
- **Канон:** Р58 „фирмен разход … в периода на приемането“; FLOW-024 L178 „крайна печалба/загуба“, L180; FLOW-015 L155 „Текущ фирмен резултат“ (Q007).
- **Код (#84 `caea933`):** Само отделен endpoint `GET /api/finance/company-costs/accepted-differences` (`routes/invoice_corrections.py:494`), изчислен от `credit_debit_notes` (`services/invoice_corrections.py:965`); няма го в `/org/pnl-overview` (`routes/project_pnl.py:85`), `/finance/stats` и UI; извън разпределението на overhead само защото никой не го чете.
- **Решение:** промяна в кода — ред „Фирмени загуби (не се разпределят)“ в крайния фирмен резултат и в „Текущ фирмен резултат“, с drill-down и етикет; изрично изключване от базата за разпределение на overhead (Q007).

## FG-272 — чернова с ред от входяща фактура, разпределен към нея само чрез `allocations[].ref_id`, се изтрива — редът остава сирак

- **Тежест:** high. **Статус:** open. **PROVEN** (проход 28).
- **Канон:** FLOW-001 §Какво НЕ трябва „изтриване на обект, по който има … фактури …“; CLAUDE.md правило 9; Р56 (2).
- **Код (#86 PRJ-01 `28fb230`):** `services/project_lifecycle.py:29-32, 106` не гледа вложени масиви; `POST /invoice-lines` (`routes/invoice_lines.py:416-418`) пише само `allocations[]` с `allocation_ref_id=None` → DELETE → 200.
- **Решение:** промяна в кода — `{"allocations": {"$elemMatch": {"type": "project", "ref_id": pid}}}` в проверката.

## FG-273 — стар Warranty обект, чийто оригинал е подобект, не може да се свърже — DQ задачата само ескалира; свързването после тихо преименува кода му

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 28).
- **Канон:** Р54 (1); Р56 (4); CLAUDE.md §14; FLOW-001 P-06.
- **Код (#86 PRJ-01 `28fb230`):** `migration:98` отхвърля оригинал с `parent_project_id` (и `--map` → `candidate_invalid`); след връзката `create-sub-project` на оригинала преименува кода на стария обект без AuditEvent (`projects.py:1851-1862`).
- **Решение:** Крум да реши: свързване с корена или второ ниво; промяна в кода — без тихо преименуване, AuditEvent при всяка смяна на кода.

## FG-274 — проверката за история пуска пълно сканиране на всички колекции в една транзакция

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 28).
- **Канон:** CLAUDE.md §14 (domain transaction); FLOW-042 (производителност преди Gate).
- **Код (#86 PRJ-01 `28fb230`):** `business_links` с `$expr/$objectToArray` върху целия документ за всяка колекция в `ORG_KEYED` при DELETE и при смяна на типа.
- **Решение:** промяна в кода — индексирани полета/списък на връзките вместо пълно сканиране.

## FG-275 — пълно ЕГН се показва на Owner/Accountant в обикновени четения без AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN (код + проба E2)** (проход 28).
- **Канон:** Р48 (3) „ЕГН се вижда изцяло само от **Собственика и Счетоводителя**, всяко показване на пълното ЕГН се записва в одита“.
- **Код (#83 CP-01 `9f86d0b`):** `routes/projects.py:168, 250, 267, 399, 436` — GET /projects, /projects/{id}, /invoice-details и отговорите на PUT/POST показват пълно ЕГН на Owner/Accountant без AuditEvent; само reveal маршрутът (`:788-804`) одитира.
- **Решение:** промяна в кода — маска в обикновените четения; пълно ЕГН само през reveal с AuditEvent.

## FG-276 — приета разлика (фирмен разход) няма път за сторно/корекция

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 28).
- **Канон:** CLAUDE.md §7 „Reversal/correction заменя директното редактиране“; §14 (correction/reversal path).
- **Код (#84 `ef7cddd`):** `services/invoice_corrections.py:965-984` (`company_cost_lines`) брои всяко известие с `difference_accepted`; няма маршрут за отмяна.
- **Решение:** промяна в кода — сторно на приетата разлика с причина, одобрение и AuditEvent.

## FG-277 — ред с неопределен вид (`undetermined`) не се осчетоводява никъде; DQ задачата няма изход

- **Тежест:** medium. **Статус:** open. **PROVEN (код)** (проход 29).
- **Канон:** Р55 (3), Р58 „…в периода на приемането“; FLOW-033 (DQ се решава в изходния модул).
- **Код (#84 `e75b558`):** `services/invoice_corrections.py:938, 1006-1012` — отваря DQ `accepted_difference_line_undetermined`, но никой код не я решава и не превръща реда в разход на обект или фирмен разход; разликата остава извън всеки резултат.
- **Решение:** промяна в кода — действие за решаване на DQ (Счетоводителят избира обект/фирма) с AuditEvent, разходът в периода на приемането.

## FG-278 — фирмените загуби са за цялото време, а сумите на обектите — само за активни статуси; крайният резултат смесва обхвати

- **Тежест:** low. **Статус:** open. **SUSPECTED** (проход 29).
- **Канон:** FLOW-015 L37 „Текущо състояние, начислен резултат и прогноза никога не се смесват в една неясна сума.“; FLOW-024 L180 („екранът трябва ясно да показва какво е включено“).
- **Код (#84 `e75b558`):** `services/invoice_corrections.py:1039` (`company_losses_block` без период) + `/org/pnl-overview` (обекти само Active/Draft/Paused, FG-262).
- **Решение:** промяна в кода — общ период и обхват за двете части или етикет какво е включено.

## FG-279 — `PUT /projects/{id}` сменя `parent_project_id` без проверка и без AuditEvent — заобикаля Р60

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 30).
- **Канон:** Р60 „второ ниво подобект се разрешава само за гаранция“; FLOW-001 P-06 „Всички промени се записват в AuditEvent“; CLAUDE.md §14.
- **Код (#86 PRJ-01 `abc6fda`):** `routes/projects.py:119, 289` — обикновен обект става второ ниво под подобект (200); свързан гаранционен обект се мести към корена, а `warranty_of_project_id` остава подобектът (противоречие); полето съществува и в main.
- **Решение:** промяна в кода — `parent_project_id` само през командите за структура, с проверка по Р60 и AuditEvent; в PUT → 409.

## FG-280 — агрегатът на обекта и складът гледат само едно ниво — гаранцията на второ ниво не стига до корена

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (проход 30).
- **Канон:** Р60 „разходите се сумират към подобекта и после към целия обект“; FLOW-001 P-05 „Основният обект обобщава данните от всички свои нива.“
- **Код (#86 PRJ-01 `abc6fda`):** `GET /projects/{id}/aggregate` (`routes/projects.py:2374-2386, 2474-2486`) — само преките деца; `warehouse_movements/price_history.py:38-41` (`_project_buckets`) — само преките деца; `service.py:206-223` дава подобекта, не корена. `/pnl/aggregated` сумира правилно.
- **Решение:** промяна в кода — рекурсивно обобщение по всички нива (само гаранционно второ ниво) в агрегата и в склада.

## FG-281 — преосчетоводяване след сторно на приета разлика без ограничение

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN** (проход 31).
- **Канон:** Р55 (3) „…остава разход на обекта/СМР на оригиналния ред“; Р58 „…приета в склада … → фирмен разход“; Р55 (2) „…винаги двама различни души“.
- **Код (#84 `cdd3dc8`):** `routes/invoice_corrections.py:504-521` — за сторниран ред се приема всяка цел; обектът само се проверява, че съществува (`:510`).
- **Проба:** ред с директна доставка за prj-1 → фирмен разход от Счетоводителя (200); ред, приет в склада → несвързан обект prj-2 (200); към Completed обект (200); един и същ Owner приема, сторнира и преосчетоводява сам.
- **Решение:** промяна в кода — сторниран ред се преосчетоводява само по оригиналната си класификация; всяко отклонение (или неопределен ред извън кандидат-обектите) — с одобрение на Owner от друг човек; отказ за приключени обекти. Крум решава дали Счетоводителят може да прекласифицира след сторно.

## FG-282 — приходът на обекта брои входящи фактури

- **Тежест:** medium. **Статус:** open. **PROVEN** (код и проба); ефект в реални данни — SUSPECTED.
- **Канон:** FLOW-015 L37 / FLOW-024 L180 (краен фирмен резултат); FLOW-006 (приход = издадени фактури).
- **Код (main `3699c3b`, използван от #84 `final_profit`):** `services/project_pnl.py:29-40` — заявката за приход няма филтър по `direction`.
- **Проба:** една `Received` фактура с нето 200 и `project_id` → печалбата на обекта +200 → влиза в `final_profit` на атрибуцията.
- **Решение:** промяна в кода — приход само от `direction: "Issued"`; регресионен тест; отделна задача.

## FG-290 — касовият бон (`file_id`) не се проверява във File Registry

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 31, проби P3/P4/P11).
- **Канон:** Р59 „само с касов бон“; Р50 (1) „(`file_id`)“; CLAUDE.md §2.6 „Един File Registry — модулите използват `file_id`“.
- **Код (#83 CP-01 `1e455e3`):** `services/bank_account_guard.py:68-72` (`_receipt_id`) проверява само формата.
- **Проба:** `"nonexistent-file-xyz"`, `"zzz"`, `"anything"` → 201; tenant-ът няма нито един запис във File Registry.
- **Решение:** промяна в кода — търсене на `file_id` във File Registry на tenant-а (както складът: `warehouse_movements/service.py:334, 745-750`, `file_registry_available()`).

## FG-291 — разход „без получател“ може да назове получателя в свободен текст

- **Тежест:** medium. **Статус:** open — Krum decision. **PROVEN** като поведение, SUSPECTED като разминаване.
- **Канон:** Р59 „в брой към фирма или лице … само с контрагент, избран от списъка“; дребни разходи — само с касов бон.
- **Код (#83 CP-01 `1e455e3`):** `bank_account_guard.py:89-96`; `note`/`reference` се пазят свободно (`finance.py:1858-1860`, `:641-642`); няма категория на разхода и праг на сумата.
- **Проба (всички 201):** note „Платено на Иван Петров за кофраж“; reference „Иван Петров ЕГН 8001011234“ (пълно ЕГН в плащане); име само с интервали.
- **Решение:** Крум определя „малък разход“ (затворен списък категории и праг); после код — задължителна категория, истински бон, маскиране на ЕГН в `note`/`reference`.

## FG-292 — бързо плащане в брой на входяща фактура без контрагент минава като разход без получател

- **Тежест:** low. **Статус:** open. **PROVEN** (проба P16 → 201, `cash_expense_without_payee: true`).
- **Канон:** Р59; FLOW-025 L126 „верифициран получател“.
- **Код (#83 CP-01 `1e455e3`):** `routes/finance.py:1346-1361`.
- **Решение:** промяна в кода — плащането на входяща фактура винаги изисква разрешен контрагент.

## FG-293 — заем/аванс в брой към външно лице по свободен текст заобикаля Р59

- **Тежест:** medium. **Статус:** open — Krum decision. **PROVEN** (проба P20 → 201). Код на main, не в делтата на #83.
- **Канон:** Р59; Р50 (1); FLOW-006 L86.
- **Код (main `3699c3b`, същият в #83):** `routes/hr.py:260-261` приема `guest_name` свободно; `:283-291` записва изходящо плащане в брой във `finance_payments` без контрагент/лице и без бон. Само `MASTER_DATA_MODE=enforce` би го спрял.
- **Решение:** Крум решава покрива ли Р59 авансите и заемите; после код — през `check_payment_target`.

## FG-294 — издадена фактура с ЕГН показва номера изцяло на Admin и на Owner без AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN** (#83, известен дълг D19, повишен в FG).
- **Канон:** Р48 (3) — пълно ЕГН само за Собственик и Счетоводител, иначе `******1234`; всяко разкриване с AuditEvent (FG-275).
- **Код (#83 CP-01 `1e455e3`):** `GET /finance/invoices` и `/finance/invoices/{id}` връщат `counterparty_eik` (10 цифри) без маскиране.
- **Свързано (SUSPECTED, D9):** ЕГН копие без запис в `persons` не може да се види изцяло от никого — Счетоводителят не може да изпълни DQ задачата за създаване на лицето.
- **Решение:** промяна в кода — същото маскиране и разкриване с AuditEvent като в проектите.

## FG-300 — състезание в транзакцията за изтриване на празна чернова

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 31).
- **Канон:** CLAUDE.md §2 правило 9 „Няма hard delete на използвани … записи“; FLOW-001 „Какво НЕ трябва“ — изтриване на обект с движения/отчети/фактури; Р56 (2) „изтрива се само наистина празна чернова“.
- **Код (#86 PRJ-01 `dbb04ba`):** `routes/projects.py:433-452` — повторната проверка чете snapshot; CAS върху `projects` не конфликтира с вмъкване в друга колекция; пишещите проверки (`project_guards.py:21-30`, `money_input.py:91-93`, `finance.py:111-113`) само четат проекта.
- **Проба:** оферта, вмъкната веднага след проверката в транзакцията, оцелява; DELETE → 200; офертата сочи tombstone.
- **Решение:** промяна в кода — пишещите и изтриването пишат в един и същ документ на проекта (конфликт), или reconciler с DQ задача за записи към tombstone.

## FG-301 — пълното сканиране се пуска два пъти при всяко DELETE

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §14; договореният изход за FG-274 (индексирани полета / списък с връзки вместо пълно сканиране).
- **Код (#86 PRJ-01 `dbb04ba`):** `projects.py:437`, `services/project_lifecycle.py:157-164`.
- **Проба:** при 60k фактури DELETE 2.3–2.85 s (преди 1.11 s).
- **Решение:** промяна в кода — в транзакцията само именуваните индексирани пътища + изходът за FG-300; дългосрочно — регистър на връзките.

## FG-302 — tombstone-и в съединенията и масовите пътища; няма възстановяване

- **Тежест:** low. **Статус:** open (частично Krum decision). **SUSPECTED**.
- **Канон:** CLAUDE.md правило 12 и §14 (път за корекция); FLOW-001 P-04 „историята му се пази“.
- **Код (#86 PRJ-01 `dbb04ba`):** `tenancy/data_access.py:346-359` — `TenantData.lookup` връща tombstone с код `~deleted~`; `:103-112` — `update_many`/`delete_many` тихо пропускат tombstone-ите (миграциите по tenant ги пропускат); няма път за преглед/възстановяване.
- **Решение:** промяна в кода (`lookup`, migration runner); Крум решава може ли изтрита празна чернова да се възстанови и кой я вижда.

## FG-303 — wrap-in-group оставя група-сирак при неуспешно прехвърляне

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 31b).
- **Канон:** FLOW-001 P-06 „Всички промени се записват в AuditEvent“; CLAUDE.md §14.
- **Код (#86 PRJ-01 `8e8be48`):** `routes/projects.py:2150` създава групата преди и извън транзакцията на прехвърлянето.
- **Проба:** принудена загуба → 409 `PROJECT_CHANGED`, остава Active група `is_group` с 0 AuditEvent; две паралелни извиквания → [201, 409] и 2 групи.
- **Решение:** промяна в кода — една транзакция (група + прехвърляне + нов подобект) с AuditEvent и Idempotency-Key. Застъпва се с FG-261.

## FG-304 — стари данни със свободно сменен `parent_project_id`

- **Тежест:** medium. **Статус:** open (+ Krum decision). Ефектът — **PROVEN**; наличието в реални данни — **SUSPECTED**.
- **Канон:** FLOW-001 P-05 „Основният обект обобщава данните от всички свои нива“; Р60 (второ ниво само за гаранция); CLAUDE.md §15 (migration/backfill).
- **Код:** main (кодът е от 28.06.2026; налице и в `3699c3b`, и в `ea57121`) — PUT сменя родителя без проверки; #86 затваря пътя занапред, но не проверява наличните данни.
- **Проба:** негаранционен обект на второ ниво с труд 77 липсва от `/aggregate`, `/pnl/aggregated` и `_project_buckets`; DQ задача не се отваря.
- **Решение:** промяна в кода — сканиране (първо dry-run), DQ задачи за второ негаранционно ниво, самородителство и цикли; Крум решава дали такива обекти се вдигат на първо ниво или се обобщават.

## FG-305 — няма команда за преместване/обединяване на нива

- **Тежест:** low. **Статус:** open — Krum decision. **SUSPECTED**.
- **Канон:** FLOW-001 P-06 „преименува, **обедини** или архивира“.
- **Код (#86 PRJ-01 `8e8be48`):** след затварянето на PUT няма път, който поставя съществуващ обект под съществуващ корен/група или обединява две нива.
- **Решение:** ако Крум иска — команда `move-under` за Owner/Admin с причина, проверките по Р60, Idempotency-Key и транзакция с `project.parent_change`.

## FG-310 — сливането на main в #81 запази остарели evidence файлове

- **Тежест:** low (evidence/CI, без код). **Статус:** open. **PROVEN** (проход 31).
- **Канон:** CLAUDE.md §15 „документация и source traceability“; §16 „не обявявай Implementation Gate PASS без тестови доказателства“.
- **Код (#81 `a7166d4`, merge `fdfad135`):** auto-merge `60c6928` и реалното дърво `6f3eaa3` се различават само в 5 evidence файла (PM-01 `run_meta.json`, SEC-01/C01/C02/C03 `results.json`) — взета е версията на #81, без редовете на OH-01 от main (`op.audit_events`, `op.overhead_period_locks`, `op.execution_packages`).
- **Проба:** `test_sec_01_c02_flow_guard_money_writes.py::test_the_committed_evidence_satisfies_the_package` и `test_sec_01_c03_payment_amount_idempotency.py::test_the_committed_evidence_satisfies_the_package` падат на `a7166d4`, минават на main `3699c3b` и на `aa369d8`.
- **Решение:** промяна (без код) — файловете от main или регенериране с техните harness-и на слетия head.

## FG-315 — локалните данни са по tenant, не по потребител; изходът трие всичко без предупреждение

- **Тежест:** medium. **Статус:** open (дълг за PWA-02). **PROVEN** — днес няма загуба (няма опашка).
- **Канон:** Р61 (5) „предупреждение с броя им; записите остават криптирани на телефона и се изпращат само когато **същият** потребител влезе отново; друг потребител на същия телефон не ги вижда“; FLOW-037 §15 — липсата на интернет да не губи запис.
- **Код (PWA-01 `a05167a`):** `frontend/src/lib/pwa/clearLocalData.js:7-8` („everything else, including keys added later, is removed“); маркерът `bw_pwa_tenant` е без потребител, `noteActiveTenant` (`:66-74`) сравнява само tenant; `clearLocalData.test.js:56`; изходът и 401 в `api.js` трият без предупреждение; грешна парола също връща 401 (`backend/app/routes/auth.py:126,139`).
- **Решение:** промяна в кода (PWA-02) — опашката е по потребител, криптирана, изключена от изтриването; предупреждение с броя преди изход. По желание TODO за Р61 (5) в `clearLocalData.js` сега.

## FG-316 — изчистването не покрива IndexedDB, бисквитки и HTTP кеша

- **Тежест:** low. **Статус:** open. **PROVEN**, без ефект днес.
- **Канон:** собственото обещание в `clearLocalData.js:1` „clear what this device holds for a tenant“; CLAUDE.md §3.
- **Код:** `clearLocalData.js:24-60` — само localStorage, sessionStorage и Cache Storage (отговаря на §6 на пакета PWA-01).
- **Решение:** промяна в кода/документацията — да се опише обхватът; PWA-02 покрива IndexedDB с изключението по Р61 (5).

## FG-317 — външни скриптове със запис на сесията в инсталираното приложение

- **Тежест:** medium. **Статус:** open — Krum decision. **PROVEN**; съществуващо (дълг D5 на клона).
- **Канон:** Р48 (3) (маскиране на ЕГН); Р20 (кой вижда пари); CLAUDE.md §16 (без secrets — не е нарушено: `phc_` е публичен ключ).
- **Код (PWA-01 `a05167a`):** `frontend/public/index.html:35,44` (Emergent скриптове); `:180-186` PostHog с `session_recording` към us.i.posthog.com; `index.html` вече е в precache. Бисквитките на PostHog оцеляват при изчистването.
- **Решение:** Крум решава — махане от production или изключен запис и маскирани полета.

## FG-318 — `/api` без `Cache-Control: no-store`

- **Тежест:** low. **Статус:** open. **SUSPECTED** (Chromium не кешира в пробата; iOS Safari не е тестван).
- **Код:** няма `no-store` в `nginx.conf` и backend; e2e mock-ът (`docs/evidence/PWA-01/e2e/server.js:17`) го добавя и не отговаря на production.
- **Решение:** промяна в кода (отделна infra задача) — `no-store` за `/api` и `/uploads`; mock-ът като production.

## FG-319 — презареждане без интернет губи сесията

- **Тежест:** low. **Статус:** open (дълг D1). **PROVEN**.
- **Канон:** FLOW-043 D-12; MFE §5; Р61 (6) (блокирано устройство трие данните при следващо свързване).
- **Код:** `AuthContext.fetchUser` трие токена при всяка грешка, вкл. мрежова.
- **Решение:** промяна в кода (PWA-02) — токенът се трие само при 401, при спазване на Р61 (6).

## FG-320 — версията на service worker-а не е версията на страницата

- **Тежест:** low. **Статус:** open. **PROVEN**, безвредно днес (един bundle).
- **Канон:** CLAUDE.md §6 (точна версия; не е пряко нарушен — отнася се за deployment).
- **Код (PWA-01 `a05167a`):** `service-worker.js:74-79` (`GET_VERSION`), `:65-71` `clients.claim()`; `serviceWorker.js:341-356`.
- **Решение:** промяна в кода (по желание) — BuildIdentity сравнява двете версии.

## FG-321 — сесията на платформения админ оцелява при изход/401/смяна на tenant

- **Тежест:** low. **Статус:** open — Krum decision. **PROVEN**; не е регресия.
- **Канон:** CLAUDE.md §3 (Tenant Guard; споделен телефон).
- **Код (PWA-01 `a05167a`):** `clearLocalData.js:16` — `bw_platform_token`, `bw_platform_user` в списъка „предпочитания на устройството“.
- **Решение:** Крум решава — отделен ясно наименуван списък или изчистване и при изход от tenant.

## FG-325 — AI измисля пазарна цена на труда без данни; цената няма източник и дата, а стига до черновата на офертата

- **Тежест:** high. **Статус:** open. **PROVEN** (проба A и B).
- **Канон:**
  - FLOW-022 L130 „AI да измисля пазарна стойност при липса на данни.“;
  - L123 „цена без дата, единица и източник;“;
  - L106 „AI предлага, но Крум определя продажната цена и коефициентите.“;
  - Implementation Gate L5 „изисква source/date/version на всяка цена“;
  - CLAUDE.md §10 „AI не измисля ID, цена …“, „При липсващ tool AI казва, че не може да провери.“
- **Код (main `3699c3b`):**
  - `services/ai_proposal.py:15-131`: твърди `labor_price` (мазилка 12, боядисване 6 …). За неразпознато СМР `DEFAULT_KNOWLEDGE` дава `labor_price` 15;
  - `:155-213` `rule_based_proposal` връща цена дори при `confidence` 0.3;
  - `:219-242` LLM promptът иска от модела „labor_price_per_unit: число_лв“;
  - `:281,315` при липсващо поле LLM пътят слага 15;
  - `:331-343` без LLM ключ тихо минава към твърдата таблица;
  - отговорът няма източник, дата или версия;
  - стойността отива в `extra_works.py:428` (`ai_labor_price_per_unit`), после в `:489,518` `labor_unit_cost` на офертата, в `smr_analysis.py:415` и в `missing_smr.py:686-698`.
- **Проба:**
  - `rule_based_proposal("Монтаж на нестандартен елемент","pcs",10,"София")` → `labor 17.25`, `confidence 0.3`. В ключовете на отговора няма `source`, `as_of` или `currency`;
  - `POST /extra-works/ai-proposal` (Owner) → `provider rule-based`, „LLM недостъпен…“, `labor 13.8`.
- **Решение:** промяна в кода:
  - AI ценовото предложение чете само записи на FLOW-022 (източник, дата, статус, валута, актуалност);
  - без такъв запис отговорът е „няма проверени данни“, без число;
  - LLM само класифицира, не дава цена;
  - всяко предложение носи `source_ref`/`as_of`/`price_type`.
  - Решение на Крум: остава ли твърдата таблица като изрично означена „демо/ориентир“ (например само в Trial) или се маха.

## FG-326 — AI `ai-suggest` презаписва цената на труда (и материалите) на одобрен анализ — от всяка роля, без потвърждение и без AuditEvent

- **Тежест:** high. **Статус:** open. **PROVEN** (проба C).
- **Канон:**
  - FLOW-022 L125 „автоматична промяна на офертна цена;“;
  - L106 „AI предлага, но Крум определя продажната цена“;
  - CLAUDE.md §10 „Write tools само чрез draft → confirmation → permission → Approval → domain service“;
  - §14 (AuditEvent);
  - Р20.
- **Код (main `3699c3b`):**
  - `routes/smr_analysis.py:378-434` — само `require_m2`; отказ само при `locked` (`:384`). Одобрен (`approved`) анализ се пипа: `:413-422` подменя материалите и `labor_price_per_unit`, а `:427` записва без AuditEvent;
  - същото за материалите: `routes/pricing.py:100-161` `fetch-prices` (`:107` само `locked`, `:158` запис).
- **Проба:** анализ `status=approved` с труд 30.0:
  - `POST /smr-analyses/an1/ai-suggest` като Technician → 200, труд 13.8, материалите заменени (1 → 8 реда), статусът остава `approved`;
  - `audit_events` Δ0, `audit_logs` Δ0;
  - същото като Viewer → 200, труд 13.8.
- **Решение:** промяна в кода:
  - `ai-suggest` / `fetch-prices` връщат предложение, без запис;
  - прилагането е отделна команда с право за писане на цени (Р14/Р20) и само в `draft`;
  - Idempotency-Key, canonical AuditEvent с before/after и отбелязан източник „AI“.

## FG-327 — партидните AI ценови пътища показват цени, часови ставки и вътрешната историческа цена на роли без пари

- **Тежест:** high. **Статус:** open. **PROVEN** (проба B).
- **Канон:**
  - FLOW-022 L129 „Marketplace данни да разкриват вътрешната минимална цена на фирмата;“ (вътрешната цена е затворена);
  - Р20 (FLOW-002/FLOW-010): „Технически ръководител … не вижда … себестойност, марж и цени към клиента … Наблюдател, техник, шофьор … — без пари“;
  - Р43 (разбивката материал/труд е вътрешна).
- **Код (main `3699c3b`):**
  - `routes/extra_works.py:283-290` `ai-proposal` е с `@strip_money_for_non_finance`;
  - без него и само с `require_m2` са `:293` `ai-batch`, `:337` `ai-fast`, `:375` `ai-refine`, `smr_analysis.py:378` `ai-suggest` (връща анализа и предложението) и `missing_smr.py:651` `ai-estimate`.
- **Проба:** за SiteManager, Technician, Viewer и Driver:
  - `ai-proposal` → `labor null`, `hint null` (изрязано);
  - `ai-batch` / `ai-refine` → `labor 13.8`, `hourly_rate 22`, `internal_price_hint {median_labor 7, median_total 12, min 9, max 12}`, `grand_total 471.4`;
  - `ai-fast` → `labor 13.8`, `hourly_rate 22`.
- **Решение:** промяна в кода — `strip_money_for_non_finance` (или `require_finance_read`) за `ai-batch`, `ai-fast`, `ai-refine`, `ai-suggest` и `ai-estimate`; тест за SEC-02 пропуски, който обхожда POST отговорите с пари. Ако Крум иска техникът да въвежда допълнително СМР без цени, решението е изглед само с количества.

## FG-328 — AI цената е в лева, а ставките и офертата са в евро; няма валута и ДДС на предложението

- **Тежест:** high. **Статус:** open. **SUSPECTED** (LLM пътят не може да се пусне локално; кодът е еднозначен). Частично PROVEN: в отговора `hourly_info.currency` е `EUR`, а `pricing` е без валута.
- **Канон:** FLOW-022 L47 „валута и ДДС;“; L55 „нето/ДДС/бруто;“ (нормализиране преди сравнение).
- **Код (main `3699c3b`):**
  - `services/ai_proposal.py:227-228,238` „Цените са в лв (BGN)“;
  - `extra_works.py:150` минимумът е в `"currency": "EUR"` и се смесва със същата цена на единица (`:140-160`);
  - `:67` офертата е `currency: str = "EUR"`, а `:489-523` копира AI труда 1:1;
  - `smr_analysis.py:603` EUR;
  - `historical_offer_rows` няма поле за валута или ДДС (`historical_offers.py:226-249`).
- **Решение:** промяна в кода — всяко предложение и всеки ред в ценовата база носят `currency` и `vat_mode`; превалутиране по фиксирания курс 1.95583 само явно, със следа; LLM промптът и таблиците да са в EUR, без ДДС, или полето да се попълва изрично.

## FG-329 — „вътрешната ценова подсказка“ смесва стари, недатирани и чужди за града данни и труд с труд+материали; продажните цени се показват като вътрешни

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба G).
- **Канон:**
  - FLOW-022 L24 „Цени с различен смисъл не се сравняват директно.“;
  - L124 „смесване на труд с труд+материали;“;
  - L127 „остаряла цена да се представя като текуща;“;
  - L128 „различни условия да се сравняват без нормализация;“;
  - L137 „невалидни/спорни източници не влизат в официалния диапазон;“.
- **Код (main `3699c3b`):**
  - `routes/historical_offers.py:361-402` `get_internal_price_hint`: без филтър по дата, статус или тип цена; при липса на редове за града `:382-383` тихо маха града;
  - `min_total`/`max_total` идват от всички редове, включително с `labor 0` (неразбит общ ред);
  - същото в `/historical/analytics` (`:278-356`);
  - източникът са стари оферти, т.е. цени към клиента, но в AI отговора и в UI се показват като „вътрешна“ (`ai_proposal.py:380-389`, `OfferEditorPage.js:310`, `NovoSMRPage.js:110`).
- **Проба:** редове „Варна, 2015 г., само общо 9.0“ и „Варна, без дата, 5+7=12“. Подсказката за **София** → `available true`, `sample_count 2`, `range 9.0-12.0`, `median_labor 7`, без дата, град или предупреждение.
- **Решение:** промяна в кода — подсказката филтрира по регион, срок на актуалност, тип цена и обхват (само труд / труд+материали); показва дата, източник и брой; ако регионът липсва, го казва, а не замества тихо.

## FG-330 — импортът на исторически цени приема цена без дата, източник, валута и тип; без AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба F).
- **Канон:** FLOW-022 L123 „цена без дата, единица и източник;“; L35-48 (задължителните полета на записа); CLAUDE.md §14.
- **Код (main `3699c3b`):** `routes/historical_offers.py:211-275`:
  - `source_date = data.get("source_date", "")` (`:224`);
  - няма проверка за дата, валута, ДДС, тип цена, Master СМР id или статус;
  - `insert_one` ред по ред (`:250`) без Idempotency-Key и без AuditEvent (`log_audit` е импортиран, но не се вика).
- **Проба:** `POST /historical/import-confirm` (Admin) без дата и файл → 201, `source_date ""`; `audit_events` Δ0, `audit_logs` Δ0.
- **Решение:** промяна в кода — задължителни дата, източник, единица, валута/ДДС, тип цена и „с/без материали“; статус „непроверен“ до преглед; Idempotency-Key; canonical AuditEvent за партидата; връзка към Master СМР (W0-03).

## FG-331 — часовите ставки и одобрените AI коефициенти се презаписват и изтриват без история и AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба D и E).
- **Канон:**
  - FLOW-022 L138 „историята на старите стойности се пази.“;
  - L106 „Крум определя … коефициентите“;
  - CLAUDE.md правило 9 (без hard delete на одобрени записи), §14 (AuditEvent);
  - FLOW-043 D-17 L130 „всички други промени на ставки/цени по FLOW-002 остават с двуличното правило.“
- **Код (main `3699c3b`):**
  - `routes/extra_works.py:659-677` `PUT /ai-config/hourly-rates` — legacy Admin/Owner, `update_one … upsert` върху един ред, без версия и без AuditEvent;
  - `routes/ai_calibration.py:324-369` `approve` — upsert върху същия ключ (`:350`) презаписва стария коефициент;
  - `:372-382` `DELETE` — `delete_one` на одобрен коефициент; без AuditEvent.
- **Проба:**
  - две смени на ставката 22 → 99: един документ, `audit` Δ0, няма колекция с история;
  - Accountant → 403 (финансовата роля е изключена);
  - коефициент 1.2 → 1.5 (един документ), после `DELETE` → 0 документа, `audit` Δ0.
- **Решение:** промяна в кода — версии (append-only) за ставките и коефициентите; отмяна чрез статус `revoked` вместо `delete_one`; canonical AuditEvent с before/after; роли по Permission Service (Р14). Решение на Крум: важи ли за тези ценови ставки правилото за двама души (D-17 L130), или е достатъчен един финансов човек като при акорда (Р41).

## FG-332 — калибрацията смесва труд с труд+материали и тихо пренася коефициента от друг град; UI записва фалшиви „некоригирани“ случаи

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба E, приложеният коефициент) + SUSPECTED (UI).
- **Канон:** FLOW-022 L124 „смесване на труд с труд+материали;“; L56 „труд срещу труд+материали;“; L136 „значими отклонения се преглеждат;“.
- **Код (main `3699c3b`):**
  - `routes/ai_calibration.py:120-123` делтата е само върху общата цена;
  - `services/ai_proposal.py:354-377` прилага един коефициент и към материала, и към труда;
  - `ai_calibration.py:410-423` при липса на град взима коефициента без град;
  - `NovoSMRPage.js:200-205` праща `ai_total == final_total`, т.е. всяко събитие е с делта 0;
  - `ExtraWorkModal.js:272-276` праща `ai_material/labor` равни на финалните.
- **Проба:** коефициент 1.5 за „Мокри процеси/Мазилка, София“. `ai-proposal` → труд 13.8 → 20.7 и материал 9.77 → 14.65 (един и същ ×1.5).
- **Решение:** промяна в кода — отделни делти и коефициенти за труд и материал; правилни AI стойности в събитието (стойността преди редакцията); без тихо пренасяне от друг регион.

## FG-333 — скрити коефициенти по град, малко количество и DEMO часови ставки се прилагат към цената без източник и причина

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба A: `is_demo true`, `hourly_rate 22`, цена ×1.15 за София) + SUSPECTED.
- **Канон:**
  - FLOW-022 L93 „Разликата трябва да има причина, а не да изглежда като грешка.“;
  - L57 „локация;“, L58 „количество и мащаб;“;
  - L127 „остаряла цена да се представя като текуща;“.
- **Код (main `3699c3b`):**
  - `services/ai_proposal.py:137-141` `CITY_PRICE_FACTORS` (`софия 1.15` …) без източник и дата;
  - `:171-178` множители за малко количество;
  - `routes/extra_works.py:95-104` `DEMO_WORKER_RATES`, които `:126-169` прилагат като минимум за труда, когато фирмата няма свои ставки (`is_demo` е само флаг в отговора).
- **Решение:** промяна в кода — коефициентите като записи на FLOW-022 с източник, дата и собственик; DEMO ставките никога не стигат до цена (само в Trial/демо tenant или с ясен отказ). Решение на Крум: кои условия от L80-91 се поддържат като коефициенти и с каква процедура за смяна.

## FG-334 — офертата и анализът не пазят произхода на цената (AI/доставчик, дата, версия на източника)

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-022 Implementation Gate L5 „изисква source/date/version на всяка цена“; L117 „източници и дати;“.
- **Код (main `3699c3b`):**
  - `routes/extra_works.py:507-523` редът на офертата от AI чернова няма `price_source`, `ai_provider`, `price_as_of` или `calibration_id`;
  - `smr_analysis.py:415` задава `labor_price_per_unit` без източник;
  - `offers.py` няма поле за произход на цената.
- **Решение:** промяна в кода — `price_provenance` (тип източник, `source_ref`, `as_of`, версия на ценовия запис/коефициента) на всеки ред, попълнен от предложение; показва се на Крум, не на клиента (Р43).

## FG-335 — `record-edit` приема произволни калибрационни събития от всяка роля, без връзка с реален запис

- **Тежест:** low. **Статус:** open. **SUSPECTED.**
- **Канон:** FLOW-022 L137 „невалидни/спорни източници не влизат в официалния диапазон;“; L135 „нови реални пакети обновяват статистиката;“.
- **Код (main `3699c3b`):** `routes/ai_calibration.py:114-170` — само `require_m2`, `data: dict`. Не проверява дали `draft_id`/`offer_id` съществуват и дали AI стойността е реално върната от сървъра. Броят на събитията задейства известие „готово за калибрация“ (`:23-110`).
- **Решение:** промяна в кода — сървърът сам записва AI стойността при генериране (`proposal_id`), а `record-edit` само я свързва с финалната цена на реален ред; роля с право за цени; калибрацията да се учи и от реално приключени пакети (FLOW-019/021) при реализацията във Wave 3.

## FG-340 — три различни трудови разхода за един обект

- **Тежест:** high. **Статус:** open (+ Krum decision). **PROVEN** (проход 32, реален Mongo, `scratchpad/fg32lab_probe/probe_fg340.py`).
- **Канон:** FLOW-019 „Реалният труд идва само от одобрени дневни отчети“ и забраната „едни и същи часове да се броят два пъти“; Р31 („изхарчено“ = реален трудов разход от одобрени дневни отчети … акорд → одобрено количество × акордна цена); CLAUDE.md §7 „Акордът изисква одобрено количество × единична цена труд“; CLAUDE.md §2.12 (проекциите не са втори source of truth).
- **Код (#73 LAB-01 `7ee87f8`; четящите извън P&L са и на main):** P&L — изчислението на LAB-01 (`services/project_pnl.py:62-70`); `GET /project-profit` (`routes/revenue_expense.py:477-497`) сумира `labor_entries` (синхронизирани + ръчни), а без редове пада към часове × ставка от всички `work_reports`, вкл. Draft, без вид заплащане; `GET /project-net-profit` (`routes/full_cost.py:346-348`) — същата сума; `actual_labor_cost` на пакетите (`routes/labor_smr.py:394-438`) — от `labor_entries`, захранва бюджета, пълната себестойност и материалите.
- **Проба:** P&L 850; `project-profit` преди синхронизация 150 (Draft 10 ч × 15 за акордов работник); след един ръчен акордов ред 40 ч × 15 → 600; net-profit 600; P&L остава 850.
- **Решение:** промяна в кода — всички четящи през `project_labor_cost` (LAB-01), без резервния път през `work_reports`, пакетите от същото изчисление. Крум решава дали ръчен ред (FG-58) изобщо се брои.

## FG-341 — паричните пътища на LAB-02 извън общия слой за права

- **Тежест:** low. **Статус:** open (дълг). **SUSPECTED**.
- **Канон:** CLAUDE.md §14 (permission check), §16 (не заобикаляй Permission); Р16/Р20; FG-28 (общ запис на отказа).
- **Код (#75 LAB-02 `5809367`):** `routes/labor_quantities.py` — твърди списъци `FINANCE_ROLES` (`:44`), `APPROVER_ROLES` (`:205`) за `GET`/`PUT /labor-terms` (`:234`, `:247`), approve/classify и `pending` (`:386`); без `require_m2`; пътищата не са в каталозите на SEC-01/SEC-02. Днес поведението съвпада с ролите по подразбиране в PM-01, но правата от Permission Service се пренебрегват и отказът не оставя общ запис. Idempotency (W0-04), транзакция и AuditEvent са налице.
- **Решение:** промяна в кода — пътищата в каталозите на SEC-01/SEC-02 и общите зависимости пред проверката на ролята; може да се запише като дълг след сливането.

## FG-350 — пишещи пътища на офертата връщат клиентски цени на Технически ръководител

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN** (проход 32, в off/shadow/enforce).
- **Канон:** Р20 „Технически ръководител (site_manager) не вижда печалба, себестойност, марж и цени към клиента“.
- **Код (OFF-01 #79 `f526182`):** `routes/offers.py:739` (`POST /offers/{id}/new-version` — пренаписан от OFF-01 и разширен за Draft без изрязване на парите); `POST /versions/{n}/restore`; `PUT /offers/{id}/lines` (`:488`). На main същото за new-version на Sent и за restore. `POST /offers` позволява ТР (`:345`).
- **Проба:** SiteManager на обекта — `GET /offers/{id}` 0 парични ключа; трите пътя връщат цени на редове, суми, ДДС и тотал. SEC-02-E сканирането не го хваща (seed-ът е Draft).
- **Решение:** промяна в кода — `@strip_money_for_non_finance` на трите пътя; Крум решава дали ТР изобщо пише оферти (Р20).

## FG-351 — отварянето на клиентския линк не записва AuditEvent

- **Тежест:** low. **Статус:** open. **PROVEN**. Налице и на main.
- **Канон:** FLOW-002 „Magic link“ — „отваряне, отказ, одобрение и revoke се записват в AuditEvent.“
- **Код:** `GET /offers/review/{token}` (`routes/offers.py:1541-1572`) пише само ред за първо гледане в глобалния `db.offer_events`; отваряне на затворен линк (410) не се записва.
- **Проба:** audit events 0 → 0 след отваряне.
- **Решение:** промяна в кода — AuditEvent при всяко отваряне (и при 410); или Крум го записва като дълг до D-OFF01-1.

## FG-352 — OFF-01 evidence не покрива сливането с main `ea57121`

- **Тежест:** low (evidence). **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15 „документация и source traceability“; §16.
- **Код:** `docs/evidence/OFF-01/README.md` спира на гейтовете на `5675e17`; сливането `552ffdce` промени harness-а; пуснат е само PM-01. D-OFF01-17 (обединяване на помощника за колекции с ACT-01) вече може да се направи.
- **Решение:** промяна (без код) — гейтовете на слетия head в README.

## FG-355 — анализът на цената се пише, одобрява, заключва и превръща в оферта от всяка роля с M2; отговорите връщат себестойност и надценка; без AuditEvent

- **Тежест:** high. **Статус:** open. **PROVEN** (проби P1 и P2).
- **Канон:**
  - FLOW-023 L9 „AI подготвя анализа и вариантите, но Крум определя и потвърждава продажната цена.“;
  - L150 „AI сам да изпрати/одобри продажна цена;“ (одобрението е човешко и отговорно);
  - Р14 (паричните записи — само Owner/Admin/Accountant);
  - Р20 „Технически ръководител … не вижда печалба, себестойност, марж и цени към клиента … Наблюдател, техник, шофьор … — без пари“;
  - CLAUDE.md §14 (permission check, AuditEvent, idempotency за всеки consequential write).
- **Код (main `ea57121`):** `routes/smr_analysis.py`:
  - само `require_m2` (модулът е в абонамента, роля не се проверява) имат: `:262` `POST lines`, `:298` `PUT lines/{id}`, `:329` `DELETE lines/{id}`, `:437-457` `approve`, `:460-476` `lock`, `:479` `snapshot`, `:547-618` `to-offer`, `:742` `toggle`, `:772-835` `bulk-update`;
  - роля се проверява само при `create` (`:152`) и `import-excel` (`:655`), и там е разрешен и SiteManager, който по Р20 не вижда себестойност и марж;
  - всички пътища връщат целия анализ (`totals.cost_total`, `markup_total`, `final_price_per_unit`) без `strip_money_for_non_finance`;
  - нито един не вика `log_audit`/AuditEvent и не иска Idempotency-Key;
  - `approve` записва `approved_by` = текущия потребител, без Approval.
- **Проба:**
  - Viewer `POST lines` → 200, вижда `final_price_per_unit 17.25` и `totals {cost_total 1500, markup_total 225, grand_total 1725}`;
  - Technician `PUT line` → 200;
  - Viewer `approve` → 200, `status approved`, `approved_by` = Viewer;
  - Viewer `to-offer` от **чернова** (неодобрен) анализ → 200, създадена е оферта `Draft` с `subtotal 1950`;
  - `audit_events` Δ0, `audit_logs` Δ0 за целия P1 и за `to-offer`.
- **Решение:** промяна в кода:
  - запис по редовете на анализа — право за цени по Permission Service (Р14);
  - `approve`/`lock`/`to-offer` — финансова роля (Owner/Admin/Accountant), а потвърждаването на продажна цена — Approval към точната версия (CLAUDE.md §8);
  - `to-offer` само от `approved`;
  - отговорите — `strip_money_for_non_finance` / `require_finance_read` по Р20;
  - Idempotency-Key и canonical AuditEvent с before/after.
  - Решение на Крум: може ли техническият ръководител да създава анализ само с количества (без цени), както сега позволяват `create` и `import-excel`.

## FG-356 — одобреният анализ се променя тихо: редове се редактират, умножават и изтриват, а статусът остава `approved`

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P1).
- **Канон:**
  - FLOW-023 L9 (Крум потвърждава цената);
  - L155 „приета оферта да се променя тихо;“ (по аналогия за потвърдената цена);
  - CLAUDE.md правило 9 („Няма hard delete на … одобрени записи“);
  - §7 „Reversal/correction заменя директното редактиране на официални записи.“
- **Код (main `ea57121`):**
  - `routes/smr_analysis.py:250,268,304,335,748,778` отказват само при `status == "locked"`. `approved` се пипа свободно и статусът не се връща в `draft`;
  - `:338` `DELETE` маха реда от масива (hard delete, без следа);
  - `routes/pricing.py:107` (`fetch-prices`) и `:384` (`ai-suggest`, FG-326) имат същата проверка.
- **Проба:** след `approve`:
  - Driver `PUT line labor 1` → 200, статусът остава `approved`;
  - Technician `bulk-update qty *2` → 200;
  - Viewer `DELETE line` → 200, `lines_left 0`, статусът е още `approved`;
  - `audit` Δ0.
- **Решение:** промяна в кода — одобреният анализ е само за четене. Промяната е нова версия (`snapshot` → `draft`) или изрично „върни за редакция“ с причина и AuditEvent. Редът се изключва със статус (`is_active`/`removed`), не с изтриване.

## FG-357 — офертата от анализа показва на клиента себестойността като единична цена и вътрешната надценка/риск в бележката на реда

- **Тежест:** high. **Статус:** open. **PROVEN** на main (проба P2). **SUSPECTED** за OFF-01 `f526182` (четене на кода).
- **Канон:**
  - Р43 „клиентският изглед на офертата показва само обща единична цена, количество, стойност и ДДС. Разбивката материал/труд … е вътрешна“;
  - FLOW-023 L67 „Комисионната е вътрешен процент, който се разпределя в СМР редовете и не се показва като отделен ред на клиента.“ (вътрешните коефициенти не отиват при клиента);
  - L151 „комисионната да бъде показана като отделен клиентски ред;“;
  - Р20 (себестойността е вътрешна).
- **Код (main `ea57121`):**
  - `routes/smr_analysis.py:575-585` `to-offer`: `material_unit_cost` = материал **без** логистика, надценка и риск, т.е. себестойност; `labor_unit_cost` = труд без надценка; `line_total` = `final_total` (с надценка и риск); `note` = `"Markup {markup_pct}%, Risk {risk_pct}%"`;
  - `routes/offers.py:1097-1150` (клиентският линк) връща `lines` изцяло. `:627-633` PDF показва „Мат./ед“, „Труд/ед“ и бележката;
  - същото е и в `revenue_expense.py:337` `sale_price = mat + lab` (Work Package с продажна цена = себестойност);
  - на OFF-01 `f526182` `client_line` (`offers.py:261-276`) показва `unit_price = material + labor` (= себестойност 15.00) до `line_total` 1950 и пак връща `note`. PDF-ът (`:1081-1084`) пак добавя бележката.
- **Проба:** анализ мат. 5 + труд 10, надценка 25%, риск 4%, 100 м2 → `to-offer` → изпратена:
  - клиентският линк връща `material_unit_cost 5.0`, `labor_unit_cost 10.0`, `line_total 1950.0`, `note "Markup 25.0%, Risk 4.0%"`;
  - единичната цена × количество (1500) не съвпада със стойността (1950).
- **Решение:** промяна в кода:
  - `to-offer` записва продажните компоненти (материал/труд с надценка и риск, или една комбинирана продажна цена/ед) и пази вътрешните себестойност и коефициенти в отделно вътрешно поле на реда (`internal_costing`), невидимо за клиента;
  - бележката не съдържа коефициенти;
  - клиентският изглед и PDF — само по Р43.

## FG-358 — повторен запис на офертата от анализ тихо маха надценката и риска (стойността пада до себестойността)

- **Тежест:** high. **Статус:** open. **PROVEN** (проба P2).
- **Канон:**
  - FLOW-023 L109 „Системата не допуска отстъпка, която скрива загуба без ясно предупреждение.“;
  - L154 „отстъпка да създаде скрита загуба;“;
  - L156 (стойностите не се губят и не се броят различно по пътя).
- **Код (main `ea57121`):**
  - `routes/smr_analysis.py:583` записва `line_total` с надценка, но единичните компоненти са себестойност (FG-357);
  - `routes/offers.py:250-294` `PUT /offers/{id}/lines` минава всеки ред през `compute_offer_line` (`:72-80`): `line_total = qty × (material + labor)`, т.е. надценката и рискът изчезват;
  - няма предупреждение и сравнение със стойността преди записа;
  - същото важи на OFF-01 (`compute_offer_line` е непроменен).
- **Проба:** оферта от анализ `subtotal 1950` → Owner записва редовете **без промяна** → 200, `line_total 1500`, `subtotal 1500` (−450, −23%). Предупреждение няма.
- **Решение:** промяна в кода:
  - редът на офертата има единна продажна цена/ед, от която се смята `line_total`, отделно от вътрешната себестойност;
  - при запис, който сменя стойността на ред/оферта, сървърът показва разликата и иска изрично потвърждение;
  - при цена под себестойността — блокиращо предупреждение (виж FG-359);
  - тест: „запис без промяна = същата стойност“.

## FG-359 — надценката може да е отрицателна: цената пада под себестойността без предупреждение, от всяка роля; няма отстъпка с видим ефект върху печалбата

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P1).
- **Канон:**
  - FLOW-023 L101-107 („даде процентна/фиксирана отстъпка … види приблизителната печалба след промяната … избрани редове или цялата оферта“);
  - L109 „Системата не допуска отстъпка, която скрива загуба без ясно предупреждение.“;
  - L144 „рискови или губещи редове;“;
  - L154.
- **Код (main `ea57121`):**
  - `routes/smr_analysis.py:47-56` `LineUpdate.markup_pct: Optional[float]` без долна граница;
  - `calc_line` (`:76-97`) смята `final_price = cost × (1 + markup) × (1 + risk)` без проверка за загуба;
  - само bulk `-` спира на 0 (`:802`), а директното `PUT` не;
  - няма поле за отстъпка, предупреждение или флаг „губещ ред“ в анализа и офертата (backend и UI: `grep discount|отстъп` → само `procurement.py`).
- **Проба:** Technician `PUT markup_pct -40` → 200, `total_cost_per_unit 15.0`, `final_price_per_unit 9.0` (−40% под себестойността). В отговора няма ключ за предупреждение или загуба.
- **Решение:** промяна в кода:
  - отстъпката/надценката е отделна операция (%/фиксирана, по редове или цялата оферта) с показан ефект върху печалбата;
  - цена под себестойността → видимо предупреждение и изрично потвърждение от финансова роля (Approval при праг);
  - флаг „губещ ред“ в анализа и в изгледа на Крум.
  - Решение на Крум: прагът (загуба / под минималния марж), над който е нужно Approval, а не само предупреждение.

## FG-360 — `ai-breakdown` пише AI (или измислена 60/40) разбивка материал/труд в заключен анализ — от всяка логната роля, без AuditEvent

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P3).
- **Канон:**
  - FLOW-023 L9 (AI подготвя, Крум потвърждава);
  - L150;
  - L82 „използва проверими източници и дата;“;
  - CLAUDE.md §10 „Write tools само чрез draft → confirmation → permission → Approval → domain service“ и „AI не измисля … цена“, „Raw AI content не е official record.“
- **Код (main `ea57121`):** `routes/smr_analysis.py:976-1096`:
  - `Depends(get_current_user)` — без `require_m2` и без роля;
  - няма проверка за `locked`/`approved`;
  - LLM промптът „Базирай се на пазарни цени за България 2026“ е без източник;
  - при всяка грешка (`:1080-1096`) пише `material = 60%`, `труд = 40%` от единичната цена с `ai_uverenost 30`;
  - записва в `smr_analyses.lines` (`:1063`, `:1094`) и в `ai_cache` без AuditEvent;
  - кешът се прилага наново при следващо извикване (`:993-1004`).
- **Проба:** заключен анализ (`status locked`), ред с ед. цена 50 → Driver `POST ai-breakdown` → 200, `source fallback`:
  - в заключения анализ е записано `material_cena_per_unit 30.0`, `trud_cena_per_unit 20.0`, „Приблизителна разбивка 60/40 (AI недостъпен)“;
  - статусът остава `locked`;
  - `audit` Δ0.
- **Решение:** промяна в кода:
  - `ai-breakdown` връща предложение, без запис;
  - прилагането е отделна команда с право за цени, само в `draft`, с AuditEvent (източник „AI“, модел, дата);
  - без AI отговорът е „няма разбивка“, а не 60/40;
  - `require_m2` + `require_finance_read`.

## FG-361 — „агентите“ за пазарни цени на материали симулират магазинни цени (случайно отклонение, измислени URL и увереност) и ги представят като проверени източници с текуща дата; цените са в BGN

- **Тежест:** high. **Статус:** open. **PROVEN** (проба P4).
- **Канон:**
  - FLOW-023 L79-84 („AI може да проверява актуални цени, но: … използва проверими източници и дата; сравнява качество, наличност, доставка и условия; преди приемане офертата използва реалистична пазарна цена“);
  - L157 „цена без валута …“;
  - CLAUDE.md §10 „AI не измисля … цена“, „Всеки важен отговор има source links и timestamp.“, „При липсващ tool AI казва, че не може да провери.“
- **Код (main `ea57121`):** `services/pricing_engine.py`:
  - `:1-5` docstring „Agent 1: BG retail stores (simulated with realistic data)“;
  - `:21-60` твърди таблици `MATERIAL_PRICES_BGN`/`ONLINE_CATALOG`;
  - `:92-103`, `:134-145` `random.choice` на магазин, `random.uniform` отклонение ±3–6%, URL, построен от името на магазина (`https://баумакс.bg/search?q=…`), `confidence` = `random.uniform(0.80, 0.92)`, `fetched_at` = сега;
  - `:104-118`, `:146-160` резервни „Практикер (оценка)“ / „Зора Строй (оценка)“ с ±15–20%;
  - всички са с `currency "BGN"`;
  - медианата влиза в кеша `material_prices` за 7 дни (`:317-336`) и в анализа чрез `pricing.py:100-161` `fetch-prices` (`price_source "live_pricing"`). Анализът и офертата са в EUR (`smr_analysis.py:603`);
  - агент 3 смесва историята с „база знания“ (`_estimate_from_knowledge`, `:234-245` — производна от твърдата цена на СМР × 0.3).
- **Проба:** `get_material_price("грунд", force_refresh=True)` два пъти:
  - 1-во → `Mr.Bricolage 3.53 (https://mrbricolage.bg/search?q=грунд, 0.87)`, `Зора Строй 3.64`, медиана 3.64;
  - 2-ро → `Баумакс 3.76 (https://баумакс.bg/…, 0.85)`, `Зора Строй 3.79`, медиана 3.79;
  - различни „магазини“ и цени при един и същ вход, без реална заявка;
  - „Вътрешна база: база знания“ дава 17.0 (×4.5 спрямо „магазините“).
- **Решение:** промяна в кода:
  - симулираните агенти не са източник на цена. Махат се или връщат „няма проверени данни“;
  - реален адаптер за доставчик/каталог (Wave 3) пази URL, дата на проверката, валута/ДДС, единица и наличност;
  - вътрешната история — само реални покупки (склад/фактури, FLOW-009/020), с дата;
  - в UI ясно „ориентир, не е проверено“, ако Крум реши да остане демо.
  - Решение на Крум: остава ли симулираният каталог за Trial/демо tenant или се маха изцяло. Свързано: FG-326 (`fetch-prices` пише в одобрен анализ), FG-328 (BGN/EUR).

## FG-362 — `POST /pricing/batch` връща цените на материалите на роли без пари

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P4).
- **Канон:**
  - Р20 „Наблюдател, техник, шофьор … — без пари“;
  - Р35 (техникът вижда цените само в централния склад, не пазарни/офертни цени);
  - FLOW-023 L135-146 (пазарната цена и източникът са за Крум).
- **Код (main `ea57121`):**
  - `routes/pricing.py:41-46` `get_batch_prices` — само `require_m2`, без `require_finance_read`;
  - съседните `GET /pricing/material`, `/history` и `/catalog` (`:31-38`, `:61-66`, `:83-86`) имат `require_finance_read`;
  - освен това `batch` при всяко извикване записва в кеша `material_prices` (FG-361).
- **Проба:** Technician `POST /pricing/batch {"materials": ["грунд"]}` → 200, `median_price 3.79`.
- **Решение:** промяна в кода — `require_finance_read("finance.material_price.read", …)` на `/pricing/batch`; тест за SEC-02 пропуски по POST пътищата, които връщат цени (като FG-327).

## FG-363 — Work Packages и планирани материали се генерират от неприета (дори отказана) оферта, от всяка роля с M2

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P5).
- **Канон:**
  - FLOW-023 L125-133 „Само последната одобрена версия: влиза като договорен обхват; създава планирани СМР и бюджети; подготвя материални заявки; подава човекочасове и Work Packages; служи за актуване и контрол.“;
  - FLOW-003 (актуална е една версия);
  - CLAUDE.md §14.
- **Код (main `ea57121`):**
  - `routes/revenue_expense.py:317-376` `execution-packages/from-offer` — само `require_m2`, без проверка на статуса и версията (docstring-ът казва „from accepted offer“);
  - `:337` `sale_price = material + labor` (виж FG-357);
  - `routes/materials_baseline.py:31-…` `planned-materials/from-offer` — същото (docstring „from accepted offer“);
  - защитата от дубликати е само по `source_offer_id`. Затова старата версия и новата версия на офертата могат и двете да генерират пакети;
  - `offer_budget.py:94-131` `PUT /offer-budgets` — без роля и без AuditEvent (SUSPECTED);
  - без AuditEvent.
- **Проба:** оферта `status Rejected` → Technician:
  - `POST /execution-packages/from-offer` → 201 (1 пакет);
  - `POST /planned-materials/from-offer` → 201 (1 ред).
- **Решение:** промяна в кода:
  - генерирането е позволено само от `Accepted` и последната версия (`superseded` → 409);
  - роля с право за планиране (Owner/Admin/SiteManager по FLOW-002);
  - Idempotency-Key и AuditEvent;
  - при нова приета версия — сверка/миграция на пакетите, не втори комплект.
  - Свързано: FG-67 (P&L бюджетът брои чернови).

## FG-364 — анализът на цената няма валута, ДДС режим и дата на цената; мостовете слагат валута по подразбиране различно (EUR/BGN)

- **Тежест:** low. **Статус:** open. **SUSPECTED** (четене). Частично PROVEN: `to-offer` → `currency EUR`, `vat_percent 20.0` независимо от анализа.
- **Канон:** FLOW-023 L157 „цена без валута, ДДС режим, единица и дата;“; FLOW-022 Implementation Gate L5 „source/date/version на всяка цена“.
- **Код (main `ea57121`):**
  - `routes/smr_analysis.py:23-56` (модели) и документът `smr_analyses` нямат `currency`, `vat_mode` или дата на цената по ред/материал;
  - `:591,603-604` `to-offer` записва твърдо `EUR` и 20%;
  - `routes/offers.py:947` `import-confirm` е по подразбиране `BGN` (UI-ят праща EUR, `OffersListPage.js:137`, но API-то без поле — BGN);
  - `:653`, `:723` PDF/xlsx при липса на валута показват „BGN“;
  - материалите идват в BGN (FG-361), трудът от AI — в BGN (FG-328).
- **Решение:** промяна в кода:
  - анализът и всеки материал/цена носят `currency`, `vat_mode` и `price_as_of`;
  - `to-offer` пренася валутата и ДДС от анализа или изисква да се зададат;
  - едно правило по подразбиране (EUR) за API и UI;
  - превалутиране само явно, по фиксирания курс и със следа.

---

## FG-370 — амортизацията на актив се брои преди покупката и след края на полезния живот

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:**
  - FLOW-024 L9: „Режийните не трябва да се крият в произволен коефициент или да се броят два пъти.“;
  - FLOW-024 L65 (компонент „инструменти и амортизация“);
  - FLOW-024 L216 (аларма „разход, разпределен два пъти“);
  - CLAUDE.md §7 (един разход се признава веднъж).
- **Код (main `ea57121`):** `backend/app/routes/overhead.py:525-533`. Compute сумира `purchase_cost / (useful_life_months × 30.4375) × num_days` за всеки `active` актив. `purchase_date` и краят на полезния живот не се проверяват. Актив, купен след периода, и напълно амортизиран актив влизат всеки месец.
- **Проба (P4, `out.json`):**
  - актив с цена 1000 €, покупка 2027-06-01, живот 1 месец;
  - snapshot-ите за 2026-11, 2026-12 и 2027-01 съдържат амортизация 985.63 + 1018.48 + 1018.48 = **3022.59 €**;
  - това е 3 пъти цената на актив, който още не е купен.
- **Решение:** промяна в кода. Амортизацията се брои само за дните между `purchase_date` и `purchase_date + useful_life` в рамките на периода, с таван общата цена. Тест: актив извън периода → 0; сборът по всички периоди ≤ `purchase_cost`.

## FG-371 — фирменият overhead е в няколко регистъра с различни четци (втори source of truth)

- **Тежест:** high. **Статус:** open. **PROVEN.**
- **Канон:**
  - FLOW-024 L9 (режийните не се броят два пъти и не се крият);
  - FLOW-024 L199: „един разход да бъде директен и overhead едновременно“ (не трябва);
  - FLOW-024 L185: „месечен/годишен фирмен overhead“ (Крум го вижда);
  - CLAUDE.md §2.12 / §16: „не създавай втори ledger/registry/source of truth“.
- **Код (main `ea57121`):**
  - (1) `overhead_costs` / `overhead_assets` → `overhead_snapshots` → `project_overhead_allocations` (M9, `overhead.py`). Чете се **само** в P&L на обектите (`project_overhead_current`);
  - (2) `overhead_transactions` (M5, `reports.py:1022-1051`). Чете се **само** във фирмените справки (`dashboard.py:373-378` series, `:523-526` finance-details/summary, `reports.py:625-634`, `:767-772`);
  - (3) `fixed_expenses` (`overhead_realtime.py:229-250`, PUT с презапис, без версия, ключ и AuditEvent). Чете се от `compute_realtime_overhead` → аларма, утринна сводка, `centralized_reports` (труд + overhead/час) и fallback в fully loaded (FG-373);
  - (4) `full_cost.py:112-145` `POST /overhead-snapshots` пише ръчни суми по категория в **същата** колекция `overhead_snapshots`. `:159-204` aggregate ги събира с `overhead_transactions`. UI: `ProjectOperationsPage.js:77`, `:479`.
- **Проба (P1, P3, P6, `out.json`):**
  - разход 1000 € в M9 → проектите получават 800 (плюс 200 неразпределени). `/reports/finance-details/summary` за октомври показва `expenses_overhead: 0`;
  - `overhead_transaction` 300 € в M5 → фирмената сводка показва 300. P&L на обектите остава 800;
  - ръчен `/overhead-snapshots` 777 € → появява се в списъка на OH-01 `GET /overhead/snapshots` като ред без период (`[null, null, 777.0]`);
  - същият наем, въведен и в M9, и в M5, се брои веднъж в обектите и веднъж във фирмата. Ако е въведен само в единия, не се вижда в другия.
- **Решение:** решение на Крум кой е единственият регистър на фирмения overhead. Предложение: `overhead_costs` по FLOW-024. После промяна в кода:
  - фирмените справки четат от него, а другите регистри стават проекции или се мигрират (per-tenant, dry-run, без изтриване);
  - ръчните `/overhead-snapshots` отпадат или се пишат в отделна колекция;
  - плащането остава през FLOW-006 (FG-35).

## FG-372 — неразпределеният overhead и разходът след разпределението изчезват

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:**
  - FLOW-024 L141 (системата пази „остатъка“);
  - FLOW-024 L190 („неразпределени разходи“ — вижда Крум);
  - FLOW-024 L205 „неразпределен разход да изчезне“ (не трябва);
  - FLOW-024 L215 (аларма „неразпределени разходи“);
  - Р38 („нищо не изчезва тихо“, OH-01 добавка 2); Р45 т.4.
- **Код (main `ea57121`):**
  - `overhead.py:732-750`, `:873`: остатъкът се записва само в `overhead_snapshots.current_unallocated_amount` и в отговора на `allocate`. Никой четец не го показва (в `frontend/src` няма `unallocated` за режийни). Не влиза в `pnl_aggregator.py:94-139` и в `dashboard.py`;
  - `overhead.py:315-342`: нов разход с дата в период, който вече е изчислен и разпределен, се приема без предупреждение и без етикет „преизчислява се“;
  - `_cost_usage` (`:66-75`) после го смята за „използван“, макар че snapshot-ът не го е сумирал. Затова не може и да се архивира.
- **Проба (P1, P2, `out.json`):**
  - 1000 € → A 600, B 200, `unallocated 200`. `/org/pnl-attribution` overhead = **800**, фирмената сводка = **0**;
  - нов разход 500 € на 2026-10-15 след разпределението → P&L overhead остава 800, `overhead_recalculating: false`, snapshot 1000;
  - DELETE на същия разход → 409 `OVERHEAD_RECORD_IN_USE`.
- **Решение:** промяна в кода:
  - (а) неразпределеният остатък да се вижда във фирмения резултат и на екрана Режийни, плюс аларма;
  - (б) разход с дата в изчислен период маркира периода като „преизчислява се“ (Р38), а DQ задачата е „преизчисли snapshot-а“;
  - (в) `_cost_usage` да проверява дали разходът е влязъл в сумата (например `computed_at ≥ created_at` или списък на сумираните id в snapshot-а).

## FG-373 — fully loaded показва оценка със скрит 30% коефициент като разпределени режийни

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:**
  - FLOW-024 L9: „Режийните не трябва да се крият в произволен коефициент“;
  - FLOW-024 L203 („фирмен overhead да се скрие“), L207: „forecast да се представя като реален разход“;
  - FLOW-024 L180: „екранът трябва ясно да показва какво е включено“.
- **Код (main `ea57121`):**
  - `services/project_financial_results.py:226-239`: когато обектът няма разпределение, `overhead_allocation` = `compute_realtime_overhead` за **текущия** месец. Месецът не зависи от периода на обекта. Източникът е `fixed_expenses`;
  - `services/overhead_realtime.py:13`, `:86-93`: `SUBCONTRACTOR_OVERHEAD_FACTOR = 0.3` — 30% от подизпълнителските актове се вадят от фирмения overhead;
  - `:243-244`: още два слепи коефициента върху разхода — `subcontractor_burden` 0.3 и `contract_burden` 0.6;
  - `:270-271`: предупреждението „Няма формални overhead allocations“ изчезва точно когато е подменена оценката. Етикетът е `null`.
- **Проба (P7, `out.json`):**
  - обект C без разпределение, `fixed_expenses` 10 000 € за текущия месец, 3 работни дни на C → `overhead_allocation: 1428.57`, `overhead_label: null`, `warnings: []`;
  - след подизпълнителски акт 20 000 € (на друг обект) режийните на C падат на **571.44**.
- **Решение:** промяна в кода. Без разпределение fully loaded показва 0 с изрично „няма разпределение“, а оценката е отделно поле „прогноза“. Ако Крум иска коефициентите 0.3 / 0.6, това е негово решение: те трябва да са видими, версионирани настройки (FLOW-024 L71). Иначе отпадат.

## FG-374 — разход, категория и актив се създават без ключ, без canonical AuditEvent, с отрицателна сума и смесена валута

- **Тежест:** medium. **Статус:** open. **PROVEN.**
- **Канон:**
  - Р29: „запис на пари без `Idempotency-Key` се отказва … и за бъдещите“;
  - CLAUDE.md §14 (consequential write: idempotency key, AuditEvent, validation);
  - FLOW-024 L137-138 (източник и версия на данните).
- **Код (main `ea57121`):**
  - `overhead.py:226-242` (категория), `:315-342` (разход), `:406-432` (актив): без `Idempotency-Key` и без `money_value`. Само legacy `log_audit`. Валутата е свободен текст, а compute сумира `amount` без конверсия (`:523`);
  - `overhead_realtime.py:229-250` PUT `fixed-expenses`: презапис без ключ, версия и AuditEvent;
  - пакетът OH-01 §3 изисква ключ и AuditEvent само за архив и версия, затова това не е регресия на OH-01.
- **Проба (P5, `out.json`):**
  - два еднакви POST-а на разход −5000 BGN без ключ → 200 и 200 (два записа);
  - canonical AuditEvent за `overhead_cost` Δ0 (в `audit_events` има само `snapshot.computed` и `allocation.version_created`);
  - snapshot за 2027-01: `total_costs −10000`, `total_overhead −8981.52`. Отрицателните режийни намаляват разхода на обектите.
- **Решение:** промяна в кода:
  - ключ по Р29 (`KeyedWrite`/`MoneyWrite`) на трите POST-а и на `fixed-expenses`;
  - `money_value` (крайна сума > 0, корекцията е отделен запис);
  - валута от master data или изричен отказ за не-EUR;
  - canonical AuditEvent `overhead.*.created`.

## FG-375 — разпределението няма предварително одобрено правило; фирмен и обектов overhead не се различават

- **Тежест:** low. **Статус:** open. **SUSPECTED** (четене + P1/P5).
- **Канон:**
  - FLOW-024 L121: „Разходът се разпределя чрез предварително одобрено правило“;
  - FLOW-024 L24-37 (обектов overhead), L152: „софтуерът — фирмен overhead“;
  - FLOW-024 L201: „разпределение без метод, период и база“ (не трябва);
  - FLOW-024 L117 / FLOW-019 (реалните часове — от одобрени отчети).
- **Код (main `ea57121`):**
  - `overhead.py:753-826`: методът идва от тялото на всеки `allocate`. Може да е различен от `snapshot.method`. Няма Approval и няма версия на правилото;
  - `:516-523`: всички неархивирани `overhead_costs` се сумират и разпределят по обекти, независимо от `allocation_type` (`CompanyWide`/`PerPerson`/`PerAssetAmortized`) и `frequency`;
  - няма поле за обект или за „остава фирмен“;
  - `:702-705`, `:723-729`: базата „часове“ брои и `Submitted` (неодобрени) отчети.
- **Проба:** P5 — разход с `allocation_type: PerPerson`, `frequency: Monthly` влиза в сумата като еднократен `CompanyWide`.
- **Решение:** решение на Крум:
  - (1) кои категории остават фирмени и не се разпределят;
  - (2) дали разпределението изисква одобрено и версионирано правило (Approval).

  После промяна в кода: обектов overhead с `project_id` (директно към обекта), правило на ниво период, само одобрени часове.

## FG-376 — ръчно `actual_overhead_cost` на пакета дава втори марж

- **Тежест:** low. **Статус:** open. **SUSPECTED** (четене).
- **Канон:**
  - FLOW-024 L186 („overhead по обект и Work Package“), L199;
  - CLAUDE.md §2.12 / §16 (един source of truth), §14 (AuditEvent).
- **Код (main `ea57121`):**
  - `routes/revenue_expense.py:394-420`: `PUT /execution-packages/{id}` е защитен с `require_finance_read` (за четене). Презаписва `actual_overhead_cost` и `actual_total_cost` без ключ и без AuditEvent;
  - `:540-551`: печалбата на обекта показва марж по пакет от това ръчно число;
  - `full_cost.py:243-308` net-financial смята overhead на пакета от дела на OH-01 разпределението. Така един пакет има два различни overhead-а и два марж-а.
- **Решение:** промяна в кода. `actual_overhead_cost` да се чете от разпределението, а не да се въвежда. PUT на парични полета под `require_money_write` с AuditEvent.

---

## FG-415 — праг „Completed“ при новото разнасяне: извън Р63 и неравен

- **Тежест:** low. **Статус:** open — Krum decision (D20; `oracle/Q009_rebooking_project_status.md`). **PROVEN** (проход 36).
- **Канон:** Р63 „Към **същото** място като първоначалното — става веднага. Към **друг обект или фирмен разход** — нужно е одобрение от Собственика“ — без статус на обект. FLOW-001 P-04/P-08/P-10/P-11 — без изрично правило (Q009).
- **Код (#84 `5242cba`):** `routes/invoice_corrections.py:519-542`; `services/invoice_corrections.py:966, 1079-1098`. Проба по всички статуси: отказ — никой; одобрение от Собственика — само `Completed` и само когато заявката подаде project id (пътят „същото място“); веднага — Draft, Active, Paused, Stopped, Cancelled, Overhead, Archived, Finished; `Completed` минава веднага при връщане към разпределение и при неопределен ред; другото място — винаги предложение; при одобрение статусът не се проверява отново (Archived → 200).
- **Решение:** Крум решава (Q009); после промяна в кода — или без праг, или един затворен списък статуси, приложен на всички пътища и при одобрението.

## FG-416 — идемпотентността на одобрението не включва коментара

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р29 / CLAUDE.md §14 (idempotency key); договорът `_once` (`routes/finance.py:64-71`) — същият ключ с различно тяло → конфликт.
- **Код (#84 `5242cba`):** `routes/invoice_corrections.py:615-616` — отпечатъкът е note id + proposal id.
- **Проба:** същият ключ с друг коментар → записаното 200, новият коментар се губи.
- **Решение:** промяна в кода — коментарът в отпечатъка.

## FG-417 — фирменият резултат се реже на 500 обекта без флаг

- **Тежест:** low. **Статус:** open. **SUSPECTED**.
- **Канон:** FLOW-024 L180 (екранът показва какво е включено); FLOW-015 L37.
- **Код (#84 `5242cba`):** `services/pnl_aggregator.py:97-102` — лимит 500; новият обхват включва всички статуси и подобекти.
- **Решение:** промяна в кода — без лимит за сумите или флаг `truncated`, показан на екрана.

## FG-385 — дедупликацията е само cooldown: след 24 ч същият източник получава втора активна аларма

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 34, реален Mongo, P1).
- **Канон:**
  - FLOW-026 L95: „Една и съща причина и източник не трябва да създават десетки еднакви аларми. Алармата пази `source_type`, `source_id`, правило, първа дата, последна дата, брой повторения, отговорник, срок и статус.“;
  - FLOW-026 L121: „дублиране на една и съща аларма за един източник“ (не трябва);
  - FLOW-026 L153: „deduplication key и автоматично затваряне“.
- **Код (main `ea57121`):**
  - `services/alarm_engine.py:23-28` — `_check_cooldown` търси аларма само в прозореца `triggered_at >= now - cooldown_hours`;
  - `:87-88`, `:106-107`, `:129-130`, `:147`, `:163` — извън прозореца се създава ново събитие, дори старото още е `active`/`acknowledged`;
  - `:39-51` — събитието няма `source_type`, първа/последна дата и брой повторения; няма уникален индекс по (правило, източник, отворен статус).
- **Проба (P1, `out.json`):** бюджетна аларма 90% на A и B → 4 събития (две правила). Остарявам събитията на 25 ч и оценявам пак → `new_events: 2`; активни за правилото: A = 2, B = 2. Ключовете на събитието: без `first_at`/`last_at`/`count`/`owner`/`due_at`.
- **Решение:** промяна в кода — ключ (правило, `source_type`, `source_id`); при повторно задействане на отворена аларма се обновяват `last_seen_at` и `occurrences`, без ново събитие; уникален частичен индекс за отворените статуси; cooldown само за известяването.

## FG-386 — rule catalog: правилата се трият твърдо и без одит; приемат се тежести и типове, които никой не оценява

- **Тежест:** medium. **Статус:** open. **PROVEN** (P4).
- **Канон:**
  - FLOW-026 L123: „изтриване на алармата и историята“ (не трябва);
  - FLOW-026 L152: „централен rule catalog“; L155: „audit и reason-required ignore“;
  - CLAUDE.md §2 т.9 (няма hard delete на използвани записи), §14 (AuditEvent за consequential write).
- **Код (main `ea57121`):**
  - `routes/alarms.py:266-272` — `DELETE /alarm-rules/{id}` → `delete_one`, без проверка дали правилото има събития;
  - `:222-237`, `:240-251`, `:254-263` — създаване, промяна (праг на място, без версия) и включване/изключване, без AuditEvent и без ключ;
  - `:37-44` — `RuleCreate` не валидира `type`, `severity`, `cooldown_hours` (`VALID_SEVERITIES`/`VALID_TYPES` на `:33-34` не се ползват);
  - `services/alarm_engine.py:53-170` оценява само `budget`, `overtime`, `attendance`, `overhead`, `deadline`.
- **Проба (P4):** PUT на прага 80 → 999: 200; DELETE: 200, правилото в базата: 0, събития със същия `rule_id`: 4; AuditEvent Δ0 за всички записи на правила (и `audit_logs` за аларми: 0). Правило `type:"pricing"`, `severity:"blocking"`, `cooldown_hours:-5` → 201; след оценка — 0 събития.
- **Решение:** промяна в кода — правилата се архивират (`is_active=false`, `archived_at`), не се трият; всяка промяна прави нова версия и пише canonical AuditEvent; събитието пази версията на правилото; валидиране на тип/тежест/cooldown; отказ на тип, който двигателят не оценява.

## FG-387 — „потвърждаване“ връща решена аларма в работа; преходите на статуса не се проверяват и не се одитират

- **Тежест:** medium. **Статус:** open. **PROVEN** (P3).
- **Канон:**
  - FLOW-026 L97-106 (статуси, вкл. „Игнорирана с причина“, „Затворена автоматично след валидна корекция“);
  - FLOW-026 L119-120: „„видяно“ да означава „решено“; игнориране без причина и AuditEvent“ (не трябва);
  - FLOW-026 L137: Крум вижда „решени, игнорирани и повторно отворени“.
- **Код (main `ea57121`):**
  - `routes/alarms.py:154-167` — `acknowledge` слага `status:"acknowledged"` независимо от текущия статус;
  - `:170-183` — `resolve` презаписва и вече решена аларма;
  - няма история на преходите, нито състояние „повторно отворена“; няма AuditEvent (FG-209).
- **Проба (P3):** Viewer решава аларма → `resolved`, `resolved_by: viewer`. Technician я „потвърждава“ → 200, `status: acknowledged`, `resolved_by: viewer` остава. Решението изчезва без следа. AuditEvent Δ0.
- **Решение:** промяна в кода — машина на състоянията по L97-106 (разрешени преходи, повторно отваряне като отделно действие с причина); история на преходите в събитието; canonical AuditEvent за всеки преход (свързано с FG-209).

## FG-388 — 3 нива вместо 5, няма „Блокиращо“; непозната тежест не влиза в броячите

- **Тежест:** low. **Статус:** open. **PROVEN** (код + P4).
- **Канон:**
  - FLOW-026 L83-89: „Информация / Внимание / Проблем / Критично / Блокиращо“;
  - FLOW-026 L91: „Блокиращата аларма спира само конкретното опасно действие, а не целия обект.“;
  - FLOW-026 L125, L156 (блокираща аларма не се заобикаля; тест за блокираща аларма).
- **Код (main `ea57121`):**
  - `routes/alarms.py:33` — само `info`/`warning`/`critical`, не се налага (FG-386);
  - `:93-96`, `services/morning_briefing.py:25-26` — броят само `critical`/`warning`/`info`; аларма с друга тежест не се брои;
  - няма проверка на отворени блокиращи аларми в нито една domain операция.
- **Проба (P4):** правило с `severity:"blocking"` → 201.
- **Решение:** промяна в кода — петте нива от L83-89 като затворен списък; „Блокиращо“ с явна връзка към действието, което спира (проверка в domain service, не в UI). Ако v1 остава с 3 нива — решение на Крум и съпоставка с петте.

## FG-389 — няма финансова група аларми и централен каталог; 8+ паралелни списъка с предупреждения без статус

- **Тежест:** medium. **Статус:** open. **PROVEN** (код, grep).
- **Канон:**
  - FLOW-026 L13-23 (финанси и кеш: просрочени вземания и задължения, аванс, отрицателна cash позиция, надплатено, плащане без основание, ретенция, неразпределен ред, одобрени неплатени заплати/подизпълнители, прогноза за недостиг);
  - FLOW-026 L36-81 (материали, активи, договори, качество); L152 „централен rule catalog“;
  - Р44: „неразпределеният остатък … (DQ задача + аларма); след срока — ескалация към Собственика“;
  - FLOW-024 L212-222 (9 аларми за режийни).
- **Код (main `ea57121`):**
  - `services/alarm_engine.py:55-170` — само 5 типа: бюджет %, извънреден труд, присъствие, срок на обекта, промяна на режийните;
  - паралелно, при всяко отваряне и без статус/собственик/потвърждаване: `full_cost.py:406-466` (`/financial-alerts`, вкл. „Вземания … просрочени“ `:438`), `full_cost.py:469` (`/project-risk`), `revenue_snapshot.py:319` (`/procurement-alerts`), `labor_smr.py:473`, `material_smr.py:473`, `budget_progress.py:318`, `warehouse_canonical_queries.py:574`, `assets_custody.py:199`, `pulse_generator.py` (FG-207).
- **Ефект:** едно и също условие може да е „предупреждение“ на един екран и да липсва в алармения център; нищо от тях не може да се потвърди, игнорира с причина или ескалира.
- **Решение:** промяна в кода — каталогът в `alarm_engine` (или общ rule catalog) поема условията на паралелните списъци; екраните четат `alarm_events`. Първо финансовата група по L13-23 (източник FLOW-006/005/021/028) и Р44. Редът е по Waves (FLOW-026 е Wave 2) — Крум решава кое влиза първо.

## FG-390 — бюджетната аларма смята „изхарчено“ от работните сесии, не от одобрените дневни отчети (Р31)

- **Тежест:** medium. **Статус:** open. **PROVEN** (код + P6).
- **Канон:**
  - FLOW-026 L9: „Алармата не е втори източник на данни; тя е проекция върху официалните регистри.“; L157 „проверка, че алармите не създават втори финансов/оперативен запис“;
  - Р31: „изхарчено“ = реален трудов разход от одобрени дневни отчети (акорд → одобрено количество × акордна цена);
  - CLAUDE.md §2.12.
- **Код (main `ea57121`):**
  - `services/alarm_engine.py:56-58` — обекти `Active` **и `Draft`**;
  - `:62-63` — бюджет = сума на `activity_budgets.labor_budget`;
  - `:66-69` — изхарчено = `labor_cost` на всички приключени `work_sessions` на обекта, без статус на отчета, без акорд, максимум 5000 сесии, 100 обекта;
  - `:78-81` — прогрес = просто средно на `progress_percent` на пакетите, без тегло.
- **Проба (P6):** 2 приключени сесии по 450 на обект → „бюджет 90.0% изхарчен“ (900/1000). Двигателят изобщо не чете `work_reports`.
- **Сродни:** FG-207 (същият източник в Pulse), FG-340 (три трудови разхода), FG-371 (overhead алармата от `fixed_expenses`).
- **Решение:** промяна в кода — бюджетната аларма чете общото изчисление на трудовия разход по Р31 (същото като P&L); `Draft` обектите — по решение на Крум; прогресът — претеглен по стойност на пакета.

## FG-391 — алармите нямат обхват по обекти: техник и наблюдател виждат всички обекти и извънредния труд на всеки по име

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN** (P5).
- **Канон:**
  - Р20: техническият ръководител вижда бюджета, изхарченото и остатъка „само за своите обекти“; наблюдател, техник, шофьор, складов работник — без пари;
  - FLOW-026 L9: алармите предупреждават „Крум и отговорните хора“; L154 „permission-safe drill-down“.
- **Код (main `ea57121`):**
  - `routes/alarms.py:62-85`, `:88-96`, `:99-140` — филтър само по `org_id` (и `money_alarm_exclusion` за обекти с <2 платени работници); няма филтър по обектите на потребителя;
  - `:154-183` — acknowledge/resolve без проверка на право и обхват (FG-209);
  - `services/alarm_engine.py:108-111` — алармата за извънреден труд съдържа име и часове на работника, тип `overtime` не е в `MONEY_ALARM_TYPES` (`finance_read.py:455-456`), т.е. стига до всички роли.
- **Проба (P5):** SiteManager (без назначение към обект), Technician и Viewer → 200 и еднакви 8 реда: бюджетни аларми за A и B с тежест `critical`/`warning`, срок на A, „technician: 60ч извънреден труд/седмица“, „viewer: 60ч …“. Viewer решава критична бюджетна аларма (P3).
- **Решение:** промяна в кода — `/alarms*` филтрира по обектите в обхвата на ролята (Permission Service scope); acknowledge/resolve с право. **Решение на Крум:** (1) виждат ли наблюдател/техник/шофьор тежестта на бюджетните аларми изобщо (SEC-02 добавка E я позволява при 2+ платени работници); (2) кой вижда алармите за извънреден труд по име.

## FG-392 — `notify_roles` е мъртво поле; алармите не стигат до никого без отваряне на екрана (няма push / Action Inbox / Daily Digest)

- **Тежест:** low. **Статус:** open. **PROVEN** (код, grep).
- **Канон:**
  - FLOW-026 L9: алармите „предупреждават Крум и отговорните хора преди рискът да се превърне в загуба“;
  - CLAUDE.md §9: „Action Inbox; realtime push + Daily Digest“;
  - FLOW-026 L146 (FLOW-030/045 — напомняне).
- **Код (main `ea57121`):**
  - `routes/alarms.py:42, 51, 232` — `notify_roles` се записва; grep в `backend/app` и `server.py`: никой не го чете;
  - `NotificationBell.js:29-30`, `DashboardPage.js:75` — UI анкетира `/alarms/count`; `routes/morning_briefing.py:20, 27` — само GET;
  - няма оценка по график (FG-211), затова няма и известяване.
- **Решение:** промяна в кода — след FG-211 (оценка по график) новите и ескалираните аларми отиват в Action Inbox на отговорника (FG-208) и в Daily Digest; `notify_roles` се ползва или се маха.

## FG-393 — няма причинно-следствени вериги, финансов ефект и разлика „прогноза / факт“

- **Тежест:** low. **Статус:** open. **SUSPECTED** (липса по код; Wave 2/3).
- **Канон:**
  - FLOW-026 L108-114: „Свързаните рискове се обединяват … Системата показва една верига и ефекта, вместо несвързани предупреждения.“;
  - FLOW-026 L124: „прогнозен риск да се представя като настъпил факт“ (не трябва);
  - FLOW-026 L133-134, L156 (финансов ефект и прогнозна загуба; тест за прогнозна аларма).
- **Код (main `ea57121`):** `services/alarm_engine.py:39-51` — събитието няма `parent`/`chain_id`, `financial_effect`, `kind: forecast|fact`; таблото (`alarms.py:99-140`) групира само по тежест, тип и обект.
- **Решение:** промяна в кода, когато се прави каталогът (FG-389): поле `kind` (прогноза/факт) за всяко правило, `chain_id` и оценен ефект; таблото показва веригата. Редът — решение на Крум по Waves.

## FG-400 — документалният контрол по FLOW-025 не е реализиран: няма тип, семейство, Current версия, requirement snapshot, статус на подписване, валидност и checklist

- **Тежест:** high. **Статус:** open. **PROVEN** (по код, grep: 0 модела; проба P6 за последствията).
- **Канон:**
  - FLOW-025 L42: „Само една версия в едно version family може да е `Current`.“;
  - L58-59: „При започване на контролирано действие системата създава snapshot на приложимите изисквания. По-късна промяна на шаблона не променя със задна дата вече извършено действие.“;
  - L99: „`Статус на документа ≠ статус на подписването`.“;
  - L111: „Чернова може да се създаде и при липсващ документ. Блокира се окончателното одобрение, издаване, активиране или плащане — не целият обект.“;
  - L296-298: „`DocumentType`, `DocumentFamily`, `DocumentVersion` и one-Current constraint; `DocumentRequirementTemplate` и immutable `DocumentRequirementSnapshot`; action-specific checklist engine;“;
  - Waves `:180` (FLOW-025 е в Wave 1), `:379` („ApprovalReceipt and Document Control“).
- **Код (main `ea57121`):**
  - grep в `backend/app` за `DocumentType|DocumentFamily|DocumentRequirement|requirement_snapshot|signature_status|is_current|document_version`: 0 съвпадения;
  - единственото версиониране е `offer_versions` (snapshot на офертата, без Current и без подпис);
  - `invoices`, `client_acts`, `scan_docs` и `ocr_invoice_intake` нямат версия, статус на подписване, `valid_from`/`valid_to` и връзка към requirement.
- **Проба:** P6 (виж FG-401..403) — финалните действия минават без нито една документна проверка.
- **Решение:** промяна в кода — отделен Wave 1 пакет (DOC-01). Той съдържа:
  - модели `DocumentType` / `DocumentFamily` / `DocumentVersion` върху `file_id` от FLOW-016;
  - уникален частичен индекс за една Current версия в семейство;
  - `DocumentRequirementTemplate` с версия и immutable `DocumentRequirementSnapshot` при финализиране;
  - checklist engine с трите нива;
  - канонични AuditEvent за всяка промяна.

  Крум да реши реда спрямо FLOW-005 (договорна база) и FLOW-016 (W0-BLOCKER).

## FG-401 — изходяща фактура към клиент се издава без одобрен акт и без договорна база

- **Тежест:** high. **Статус:** open. **PROVEN** (P6, реален Mongo, enforce).
- **Канон:**
  - FLOW-025 L124: „**Издаване на междинна/крайна фактура към клиент** | одобрен акт или друг изрично договорен billing milestone; действаща договорна база; … | финализиране/издаване; чернова е позволена“;
  - L123: авансовата фактура изисква „действаща договорна база с клауза/график за аванс“;
  - L262: „фактура/акт/плащане да се финализира при блокиращ requirement“ (не трябва).
- **Код (main `ea57121`):**
  - `routes/finance.py:842-900` — `POST /finance/invoices` не приема и не проверява акт или основание;
  - `:1108-1144` — `send` проверява само `Draft` и поне един ред.
- **Проба (P6):** Accountant създава изходяща фактура за 50 000 + ДДС на обект A → 201; `send` → 200. В базата: `client_acts` 0, `contracts` 0, `approvals` 0.
- **На PR:** #84 INV-CN-01 проверява одобрения акт само ако е подаден `act_id` (`finance.py`, „Р49.5 / FLOW-025 L124“). Фактура без `act_id` минава както на main, т.е. partial.
- **Решение:** промяна в кода — `send` на изходяща фактура от вид междинна/крайна изисква одобрен акт (или договорен milestone); авансовата изисква договорна база. Крум да реши:
  - какво е достатъчно основание, докато FLOW-005 не съществува (например приета exact-version оферта);
  - дали фактура без акт остава възможна с Approval по FLOW-034 (DOC-08).

## FG-402 — входяща фактура става платима и се плаща изцяло без потвърдено получаване на стоката/услугата

- **Тежест:** high. **Статус:** open. **PROVEN** (P6).
- **Канон:** FLOW-025 L125: „**Признаване на входяща фактура като официално задължение** | валиден счетоводен/данъчен документ; доставка/приемане на стока или услуга; PO/договор/заявка, когато е приложимо; allocation …; duplicate check | документът е Current/официален; получаването е потвърдено; разпределението е завършено или контролирано чакащо | статус `Approved/Payable`; upload/OCR чернова не се блокира“.
- **Код (main `ea57121`):**
  - `routes/finance.py:1108-1144` — входящата фактура минава `Draft → Sent` със същия `send` като изходящата. Няма статус `Approved/Payable` и проверка за получаване;
  - `:1278-1281` — quick pay отказва само `Draft`/`Cancelled`.
- **Проба (P6):** входяща фактура `D-777` за 60 000 → `send` 200 → `POST /invoices/{id}/payments` за 60 000 → 201. В базата: `finance_payments` 1, `warehouse_transactions` 0 (няма приемане), одобрения 0.
- **На PR:** разпределението по Р44 е FG-155 (#81 WH-FIX-01); дубликатът по Р53 е FG-231 (#84). Проверката за получаване/приемане на услуга не е на нито един PR.
- **Решение:** промяна в кода — отделен преход на входящата фактура към `Payable` при потвърдено получаване или приемане на услугата (складово приемане, протокол, подписан акт на подизпълнител) и при пълно разпределение по Р44. Крум да реши кои типове разходи са без получаване (наем, комунални, услуги по договор) и с какво доказателство.

## FG-403 — изходящо плащане без одобрение по лимит: един Счетоводител създава и изпълнява плащане за 60 000

- **Тежест:** high. **Статус:** open. **PROVEN** (P6).
- **Канон:**
  - FLOW-025 L126: „**Иницииране на изходящо плащане** | … Approval по лимит; duplicate/idempotency check | … нужните едно/две одобрения са налични | създаване/изпълнение на Payment instruction“;
  - L145: „**Payment Request / Approval Decision** | версия към конкретно obligation/payment attempt | едно или две човешки одобрения по FLOW-034“;
  - FLOW-034 L62-64: „Две различни упълномощени лица са задължителни при: - реално плащане над зададен лимит“;
  - CLAUDE.md §8 (Approval към exact version).
- **Код (main `ea57121`):**
  - `routes/finance.py:1245-1330` (quick pay) и `:1730` (`POST /finance/payments`) — правото е само `finance_permission` (`:117-119`, Admin/Owner/Accountant) и Idempotency-Key;
  - няма Payment Request, праг, второ лице или връзка към Approval runtime.
- **Проба (P6):** Accountant плаща 60 000 по входяща фактура с една заявка → 201. `approvals` 0, `approval_requests` 0.
- **На PR:** нито един от #81-#84 не добавя одобрение по лимит. #83 добавя само проверката на получателя/IBAN-а.
- **Решение:** промяна в кода — Payment Request с версия (сума, получател, сметка, основание), Approval по FLOW-034 преди изпълнението на плащането; вторият одобряващ е различен от създателя. Крум да реши лимита (сума/валута, по тип плащане) и дали Собственикът одобрява сам под лимита.

## FG-404 — OCR входът на фактури е счупен: качването дава 500, а файлът и медията вече са записани

- **Тежест:** medium. **Статус:** open. **PROVEN** (P1).
- **Канон:**
  - FLOW-025 L125 („upload/OCR чернова не се блокира“), L302 („source-page/reference при AI intake“);
  - CLAUDE.md §4 („Оригиналното аудио и оригиналната снимка се пазят преди AI/OCR обработка“), §14 (domain transaction).
- **Код (main `ea57121`):**
  - `services/ocr_invoice.py:15-16` — `extract_invoice_text(tenant: TenantData, media_id=None, file_path=None)`;
  - `:150` — извиква се като `extract_invoice_text(media_id=media_id)`, без `tenant` (от W0-03E-A2C `1308f20b`);
  - `routes/ocr_invoice.py:69-85` — файлът и `media_files` се записват преди извикването, без транзакция;
  - `/ocr-invoice/from-media` (`:99-116`) минава през същата функция.
- **Проба (P1):** `POST /ocr-invoice/upload` (Accountant, текстова фактура) → 500. Добавени са 1 ред в `media_files` и 1 файл; `ocr_invoice_intake` 0. Директно извикване → `TypeError: extract_invoice_text() missing 1 required positional argument: 'tenant'`.
- **Тест:** `tests/test_ocr_invoice.py` е live тест срещу `frontend/.env` и не върви в CI.
- **Решение:** промяна в кода — `extract_invoice_text(tenant, media_id=…)`; тест с mongomock/реален Mongo за двата входа; медията и intake-ът в една транзакция. При грешка оригиналът остава, но не като сирак (статус „за ръчно въвеждане“).

## FG-405 — OCR intake: всеки потребител пренаписва сумата и отказва вече одобрен intake; паралелните одобрения дават няколко разхода; без AuditEvent и без проверка за дубликат

- **Тежест:** high. **Статус:** open. **PROVEN** (P2).
- **Канон:**
  - FLOW-025 L125 („duplicate check“); CLAUDE.md §10 („Raw AI content не е official record“; запис само чрез draft → confirmation → permission → Approval → domain service);
  - §14 (permission check, idempotency key, AuditEvent);
  - Р53 (1) (дубликат = същият доставчик + номер); FLOW-043 D-08 L46.
- **Код (main `ea57121`):**
  - `routes/ocr_invoice.py:158-176` — `review` без проверка на роля и без AuditEvent;
  - `:181-228` — `approve`: проверката `status != "reviewed"` (`:193`) не е CAS, `insert_one` в `pending_expenses` (`:219`) е преди условен update (`:221`). Няма проверка за доставчик + номер и няма AuditEvent;
  - `:233-247` — `reject`: без роля, без проверка на статуса, причината не е задължителна.
- **Проба (P2):**
  - Наблюдател `PUT /review` с `total_amount: 9999` → 200; Accountant одобрява → pending expense с `amount: 9999`;
  - Наблюдател `PUT /reject` с празна причина на вече одобрения intake → 200, статус `rejected`, разходът остава;
  - AuditEvent Δ0 и `audit_logs` Δ0 за трите действия;
  - втори intake със същия номер `0000012345`, 5 паралелни approve → [200×5], 5 pending expenses (общо 6 с този номер).
- **Решение:** промяна в кода:
  - review/approve/reject само за финансова роля (Р20/Р14), с ключ;
  - approve като CAS `reviewed → approved` в една транзакция с вмъкването;
  - reject само от `processed`/`reviewed`, със задължителна причина;
  - проверка за дубликат по доставчик (ЕИК) + номер (Р53);
  - канонични AuditEvent;
  - пазене на страница/регион на всяко извлечено поле (L302).

## FG-406 — Р20: наблюдателят вижда сумите на OCR intake, суровия текст, сумата на фактурата зад скана и всички чакащи разходи

- **Тежест:** medium. **Статус:** open. **PROVEN** (P2, P3, P4).
- **Канон:**
  - Р20: „Наблюдател, техник, шофьор, складов работник — без пари“;
  - FLOW-025 L299: „permission enforcement от FLOW-002“.
- **Код (main `ea57121`):**
  - `routes/ocr_invoice.py:121-122` — списъкът е с `@strip_money_for_non_finance`, а `:138-144` (детайл) и `:147-153` (raw text) са без него и без роля;
  - `routes/scan_docs.py:98-114` — `GET /scan-docs/{id}` не вика `scan_permission` и връща `linked_invoice.total`;
  - `routes/technician.py:1199-1205` — `GET /pending-expenses` без роля и без маскиране.
- **Проба:**
  - P2: наблюдател — списък без сума (✅), детайл `total_amount: 1500.0`, raw text с „Общо: 1500.00 лв“ (200);
  - P4: наблюдател — `GET /scan-docs` → 403, но `GET /scan-docs/{id}` → 200 с `{"invoice_no": "S-1", "total": 500.0}`;
  - P3: наблюдател — `GET /pending-expenses` → 200 с всички суми (420, 1500 ×5, 9999).
- **Решение:** промяна в кода — `strip_money_for_non_finance` и проверка на ролята за детайла и raw text на OCR, за `GET /scan-docs/{id}` (същото `scan_permission` и без сумата за не-финансови роли) и за `/pending-expenses`. Техническият ръководител вижда по Р20 само бюджетите на своите обекти.

## FG-407 — чакащите разходи (`pending_expenses`): одобрява ги техническият ръководител, „отказан“ става „одобрен“, без одит, а одобреното не стига до никакъв официален запис

- **Тежест:** medium. **Статус:** open. **PROVEN** (P3).
- **Канон:**
  - FLOW-025 L128: „**Служебен аванс / възстановяване на разход** | одобрено искане или expense report; касови/фактурни доказателства според policy; разпределение; проверка на стар неприключен аванс; Approval“;
  - L148: „**Expense Report / Advance Request** | … ръководител/финанси според policy“;
  - Р20 (техническият ръководител не управлява пари извън бюджета на своите обекти);
  - CLAUDE.md §2.5, §7 (едно място за задължението и плащането), §14.
- **Код (main `ea57121`):**
  - `routes/technician.py:1208-1220` — `approve`: роли Admin/Owner/SiteManager, без проверка на статуса, без обхват по обект, без ключ и AuditEvent;
  - `:1223-1235` — `reject`: същото, причината не е задължителна;
  - `expense_id` остава `None`. Grep: никой не превръща одобрения разход в задължение, разход по обект или плащане.
- **Проба (P3):**
  - SiteManager `reject` (празна причина) → 200, после `approve` → 200, статус `approved`, `approved_by: sitemanager`;
  - AuditEvent Δ0, `audit_logs` Δ0;
  - след одобрението `finance_payments`, `invoices`, `expenses` и `project_expenses` са 0.
- **Решение:** Крум да реши:
  - кой одобрява разход/аванс на служител (ръководител на обекта по policy или само финанси) и до каква сума;
  - къде отива одобреното (задължение към служителя → плащане през FLOW-006, или разход по обект).

  След това промяна в кода: CAS по статуса, обхват по обект, ключ, AuditEvent, връзка към задължението.

## FG-408 — сканирани документи: PUT пренасочва скана към несъществуваща фактура и разваля двупосочната връзка; unlink/PUT/delete без AuditEvent; регистърът пази URL, не `file_id`

- **Тежест:** low. **Статус:** open. **PROVEN** (P4).
- **Канон:**
  - FLOW-025 L10: „Той не е второ файлово хранилище.“; L264: „FLOW-025 да създава собствено плащане или паралелен файлов регистър;“ (не трябва);
  - FLOW-043 D-11 L58: „Модулите използват стабилен `file_id`, не provider URL/path.“;
  - CLAUDE.md §14 (AuditEvent).
- **Код (main `ea57121`):**
  - `models/scan_docs.py:7-12` и `routes/scan_docs.py:80` — `file_url` (задължителен), `media_id` по избор, без `file_id`;
  - `routes/scan_docs.py:117-132` — PUT приема `linked_invoice_id` без проверка, че фактурата съществува, и без да обнови `invoices.scan_doc_id`;
  - `:170-199` (unlink) и `:202-233` (delete) — без запис в одита.
- **Проба (P4):**
  - техник създава скан с `file_url: https://provider.example/x.pdf` (201, без `file_id`);
  - PUT `linked_invoice_id: "nonexistent-inv"` → 200, а `inv-paid.scan_doc_id` още сочи към скана;
  - за link + PUT + delete: AuditEvent Δ0, `audit_logs` +1 (само link).
- **Решение:** промяна в кода — сканът е връзка (`relation`) на файл от FLOW-016 (`file_id`) към фактурата, не отделен регистър; връзката се сменя само през link/unlink с проверка на фактурата и статуса (FG-145) и с канонични AuditEvent. Свързано с FG-143.

## FG-409 — стара версия на оферта презаписва приета оферта на място; версия на използвана оферта се трие окончателно

- **Тежест:** high. **Статус:** open (на main); поправено на #79 OFF-01. **PROVEN** (P5).
- **Канон:**
  - FLOW-025 L101: „Подписана или официално одобрена версия е immutable. Промяна се прави с нова версия, анекс, …“;
  - L254: „стара версия да бъде презаписана;“ и L258: „подписан/одобрен документ да се редактира тихо;“ (не трябва);
  - L245, L248 (нов Current и подмяна на подписан документ → FLOW-034);
  - CLAUDE.md §2.9, §8.
- **Код (main `ea57121`):**
  - `routes/offer_versions.py:196-285` — `restore` проверява само ролята (Admin/Owner/SiteManager) и проекта, не статуса. Пише редовете и сумите на снимката в офертата (`:270`), статусът `Accepted` и `accepted_at` остават;
  - `:288-314` — `DELETE` версия → `delete_one` (`:310`) за всяка оферта с повече от една версия;
  - и двете пишат само legacy `log_audit`.
- **Проба (P5):** приета оферта (100 m² → 1200) и v1 (10 m² → 120):
  - Admin `restore v1` → 200, `status: Accepted`, `total: 120`, `qty: 10`, `accepted_at` запазен;
  - Owner `DELETE v1` → 200, v1 в базата: 0;
  - AuditEvent Δ0, `audit_logs` +2.
- **На PR:** #79 OFF-01 (`offer_versions.py:25-33`, `_refuse_if_used`, OFF79-01) — restore и delete само за Draft, която никога не е изпращана; иначе 409 `OFFER_IN_USE`. Ще се затвори при merge на #79; канонични AuditEvent там не са проверени.
- **Решение:** промяна в кода — сливане на OFF-01 (#79) и тест на main, че restore/delete на Sent/Accepted оферта → 409 и нищо не се записва; канонични AuditEvent за restore/delete на чернова.

## FG-420 — финансови справки за труда извън `project_labor_cost`

- **Тежест:** high. **Статус:** open. **PROVEN** (проход 37, `scratchpad/fg37lab_probe/probe_r62.py`).
- **Канон:** Р62 „разходът за труд по обект е **едно число във всички справки** от един канонически източник (project_labor_cost): само **одобрени** отчети … Чернови и неодобрени отчети не влизат никъде.“; CLAUDE.md §2.12.
- **Код (#73 LAB-01 `a97db46`):** `routes/revenue_expense.py:236-306` `GET /labor-cost/by-project` — всички `work_reports` вкл. Draft × ставка (логиката, махната от `/project-profit`); `routes/revenue_snapshot.py:144-197` `GET /profit-by-period` — сурови `labor_entries` вкл. pending; кеширани `actual_total_cost`/`actual_labor_cost` (`revenue_expense.py:379-391, 532-543`).
- **Проба:** при P&L 850 → 1450: `/labor-cost/by-project` 150 / 150 / 150; `/profit-by-period` 0 → 600 (неодобреният ред се брои) → 600; кешираните суми 777 навсякъде.
- **Решение:** промяна в кода — тези четци през `project_labor_cost`; кешът се преизчислява от него или се маха.

## FG-421 — справки, които още четат `work_sessions` или черновите

- **Тежест:** high. **Статус:** open. **PROVEN**.
- **Канон:** Р62 (както FG-420); FLOW-019 „Реалният труд идва само от одобрени дневни отчети“.
- **Код (#73 LAB-01 `a97db46`):** `routes/activity_budgets.py:679-692, 838-848`; `services/project_financial_results.py:51-55, 163-191`; `routes/centralized_reports.py:41-45, 208-210` („Include BOTH draft AND approved costs“); `services/morning_briefing.py:47-59`; `routes/projects.py:1949-1959, 2135-2141`.
- **Проба:** activities-overview / financial-results / Pulse 900; centralized-reports 1000 (с черновите); сутрешният брифинг 90%, а алармата 145% — при P&L 1450.
- **Решение:** промяна в кода — всички през `project_labor_cost`; регресионен тест, който сравнява всеки четец с него.

## FG-422 — бюджетните показатели взимат различна част от труда

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** Р62 (едно число); FLOW-019.
- **Код (#73 LAB-01 `a97db46`):** `routes/activity_budgets.py:351-361` — budget-health, earned-value и burn взимат `by_smr` / `labor_total` (без престоя и без ръчните редове), алармата — `total`.
- **Проба:** един бюджет — 750 / 825 / 850 (след одобрение: 750 / 1425 / 1450).
- **Решение:** промяна в кода — един и същ компонент от `project_labor_cost` (и изрично етикетиран, ако е частичен).

## FG-423 — ръчният ред: часове × ставка и за акорд; двойно броене

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** Р62 „по часова ставка или акорд (одобрено количество × единична цена)“; CLAUDE.md §7 „Акордът изисква одобрено количество × единична цена труд“; FLOW-019 — забрана „едни и същи часове да се броят два пъти“.
- **Код (#73 LAB-01 `a97db46`):** `routes/labor_smr.py:117-120` — часове × `hourly_rate`; няма проверка срещу одобрен отчет за същия работник/ден/СМР.
- **Проба:** акордов работник 40 ч × 15 = 600; ръчен ред 8 ч върху одобрен отчет 8 ч → часовете стават двойни.
- **Решение:** промяна в кода — акордът по одобрено количество × единична цена; отказ или DQ при застъпване с одобрен отчет.

## FG-424 — одобрението на ръчен ред няма отказ, сторно, ключ и точна версия

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN**.
- **Канон:** CLAUDE.md §7 (reversal/correction вместо редакция), §8 „Approval винаги сочи към exact version и evidence“, §14 (idempotency key, domain transaction, AuditEvent, correction/reversal path); Р29.
- **Код (#73 LAB-01 `a97db46`):** `routes/labor_smr.py:142-176` — reject / reverse / DELETE / PUT → 404; Idempotency-Key не се изисква (в AuditEvent `None`); одобрява се id, не версия/стойност; записът и AuditEvent не са в една транзакция; `created_by = approved_by` е позволено.
- **Решение:** промяна в кода — отказ и сторно с причина, Idempotency-Key, одобрение на точна версия, една транзакция. Крум решава дали Собственикът може да одобрява собствения си ред.

## FG-425 — използван касов бон се трие твърдо

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 37).
- **Канон:** CLAUDE.md §2 правило 9 „Няма hard delete на използвани, финансови… записи“; Р50 (1) „в брой само срещу разписка (`file_id`)“.
- **Код (#83 CP-01 `4929451`, същото на main):** `routes/media.py:447-477` — `delete_one`, без проверка дали плащане ползва файла.
- **Проба:** плащане в брой с бон → 201; `DELETE /api/media/{id}` → 200; плащането сочи файла, записът на файла липсва, AuditEvent няма.
- **Решение:** промяна в кода — 409 или архивиране за файл, сочен от плащане; дългосрочно — връзки във File Registry (W0-06, D10).

## FG-426 — всеки файл минава за касов бон; един бон — много разходи

- **Тежест:** low. **Статус:** open — Krum decision. **PROVEN** като поведение, SUSPECTED като разминаване.
- **Канон:** Р59 „Дребни разходи без контрагент (гориво, магазин) — само с касов бон“.
- **Код (#83 CP-01 `4929451`):** `services/bank_account_guard.py:87-91` — проверява само, че файлът съществува и не е изтрит.
- **Проба:** снимка от обекта → 201; видео → 201; един и същ бон три пъти → 201.
- **Решение:** Крум решава какво е касов бон и дали един бон = един разход; после код — вид документ и проверка за уникалност.

## FG-427 — авансът на подизпълнител заобикаля проверката на CP-01

- **Тежест:** high. **Статус:** open. **PROVEN**.
- **Канон:** FLOW-010 §8.1 L250 „изпълнението е блокирано до успешна верификация“; FLOW-025 L187 „не може да разреши плащане към непотвърден получател/банкова сметка“; Р50 (1) „спрян или сменен непроверен IBAN спира и плащането в брой“; Р48 (4) (неактивен/архивиран контрагент не се избира за нови документи); договорът на модула `bank_account_guard.py:5-8` — проверката е на всяко изходящо плащане.
- **Код (#83 CP-01 `4929451`, пътят е от main — SUB-ADV-01):** `routes/subcontractors.py:1110-1203` записва изходящ ред във `finance_payments` (`:1195`) без `check_payment_target` и `require_selectable_party`; без сметка — първата каса (`:1160`).
- **Проба (подизпълнител само с непроверен IBAN):** обикновено плащане → 409 `PAYEE_BLOCKED_PENDING_IBAN`; аванс в брой без бон и получател → **201**; аванс по банка → **201** с `bank_account_id` None; след архивиране: обикновено плащане 422, аванс → **201**.
- **Решение:** промяна в кода (в CP-01) — двете проверки преди `MoneyWrite.begin`, `bank_account_id` в записа, пробата като тест.

## FG-428 — PDF на фактурата печата пълното ЕГН

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN**.
- **Канон:** Р48 (3) „…всяко показване се одитира; останалите виждат `******1234`, вкл. в export“; FLOW-040 §9 L268 „export-ът прилага същата … masking политика като екрана“.
- **Код (#83 CP-01 `4929451`):** `routes/finance.py:2343-2344` (`/finance/invoices/{id}/pdf`).
- **Проба:** Admin, Owner, Accountant → 200, PDF-ът съдържа `ЕИК: 8001011234`; AuditEvent няма.
- **Решение:** промяна в кода — маскиране в PDF, пълно само през одитираното разкриване. Крум решава дали PDF към физическо лице носи ЕГН изобщо.

## FG-429 — ДДС номер `BG` + ЕГН носи ЕГН без маскиране

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** Р48 (3).
- **Код (#83 CP-01 `4929451`):** `validators.py:18-28` приема BG + 10 цифри; `counterparty_rules.py:194` `INVOICE_EGN_KEYS` не включва `counterparty_vat_no`.
- **Проба:** `POST /finance/invoices` с `counterparty_vat_no` `BG8001011234` → 201; Admin/Owner/Accountant виждат пълната стойност в списък, детайл и PDF без AuditEvent (за разлика от 10-цифрен ЕИК, който API отказва).
- **Решение:** промяна в кода — `BG******1234`, запазване на записаната стойност при връщане на маскираната, включване в разкриването.

## FG-430 — таблото на обекта брои разходите без подизпълнителите

- **Тежест:** medium. **Статус:** open (+ Krum decision). **PROVEN** (проход 37, off/shadow/enforce). Налице на main, не е въведено от #81.
- **Канон:** FLOW-043 D-04 / FG-17 (едно число във всички справки); CLAUDE.md §2.12.
- **Код:** `routes/projects.py:1476-1483` на #81 `3028304` (на main `:1453`) — разходите на картата „Баланс“ = заплати + материали.
- **Проба:** аванс 1000, после плащане 1000 и прихванат аванс 1000 по акт 2000 → P&L подизпълнител 2000, оперативен резултат 2000, `/project-profit` 2000; таблото — 0.
- **Решение:** Крум решава — таблото чете общия помощник за признат разход, или картата се етикетира като частичен изглед; после промяна в кода.

## FG-450 — `dq_issues` с две форми на записа

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 38).
- **Канон:** CLAUDE.md §2 (един източник — без втори регистър); Р44/Р47 (DQ задача към Счетоводителя).
- **Код (#84 `f6e0c90`):** #81 — `services/invoice_allocation.py:380-420` (`type`, `owner_role`, `resolved`, аларма); #84 — `services/invoice_corrections.py:305-320` (`kind`, `assignee_role`, `closed`, без аларма). Никой още не чете `dq_issues`.
- **Решение:** промяна в кода — една схема и един писател на DQ задачи (с аларма), преди да се появи четец.

## FG-451 — обект без статус и ред без разпределение при одобрението

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р64 („статусът на обекта се проверява отново в момента на одобрението“); FLOW-008 L142 (разходът трябва да има обект); FLOW-006 L91 (проследимост).
- **Код (#84 `f6e0c90`):** `routes/invoice_corrections.py:613` — липсващ `status` → като изтрит (409, предложението никога не се одобрява), докато `routes/projects.py:286` го третира като Draft; предложение за ред без разрешимо разпределение се одобрява с 200 и записва разход на обект без обект.
- **Решение:** промяна в кода — една интерпретация на липсващ статус; отказ на предложение без дестинация.

## FG-452 — значката за одобрение не показва причината и статуса

- **Тежест:** low. **Статус:** open. **PROVEN** по код.
- **Канон:** CLAUDE.md §8 („Approval винаги сочи към exact version и evidence“); Р64.
- **Код (#84 `f6e0c90`):** `frontend/src/components/InvoiceCorrectionsPanel.js:213-224` — без причина (приключен обект / друго място) и без статуса; при връщане към разпределение — „обект “ без име. Без jest тест.
- **Решение:** промяна в кода — причина, статус и дестинация в значката; тест.

## FG-453 — прихващане погасява входяща фактура без проверката по Р44

- **Тежест:** medium. **Статус:** open (+ Krum decision). **SUSPECTED**.
- **Канон:** Р44 „фактура от доставчик с ред, който не е разпределен 100%, **не може да се плати**…“; Р51 (4) „всяко прихващане иска втори човек“.
- **Код (#84 `f6e0c90`):** `routes/invoice_corrections.py:808-893` — прихващането погасява Received фактура без `ensure_payable` (`finance.py:1933, 2525`); взаимодействието съществува само след сливането с #81.
- **Решение:** Крум решава дали прихващането е плащане по Р44; ако да — `ensure_payable` и в прихващането.

## FG-454 — mongomock вариантите на #81 са червени след сливането

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15/§16 (тестови доказателства).
- **Код (#84 `f6e0c90`):** `auth_tx` няма резервен път без транзакции → 9 mongomock варианта в `test_wh_fix_01_a3_r44_allocation.py` падат; реалните Mongo варианти минават. Разработчикът го води като отворено решение.
- **Решение:** промяна в кода/тестовете — резервен път или изрично маркиране на тези варианти като само за реален Mongo.

## FG-455 — ЕГН само в полето `egn`: проверката минава, PDF-ът не го печата

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 38).
- **Канон:** Р65 „PDF на фактура към физическо лице съдържа **цялото ЕГН** (официален документ)… всяко сваляне записва AuditEvent“.
- **Код (#83 CP-01 `7750f4e`):** `routes/finance.py:2460-2463` — при ЕГН само в `egn` PDF-ът не печата ЕГН, етикетът е „ЕИК:“; AuditEvent се пише преди PDF-ът да е създаден.
- **Решение:** промяна в кода — ЕГН от `egn` в PDF с етикет „ЕГН:“; AuditEvent след успешно създаден PDF (или в същата операция).

## FG-456 — стар 10-цифрен ЕИК (ЕГН) в справки за контрагенти без маскиране

- **Тежест:** low. **Статус:** open. **PROVEN** като поведение, SUSPECTED като разминаване (само стари данни).
- **Канон:** Р48 (3) (пълно ЕГН само Owner/Accountant, всяко показване одитирано; останалите `******1234`).
- **Код (#83 CP-01 `7750f4e`, и main):** `routes/reports.py:247` (`/reports/turnover-by-counterparty`), `/api/counterparties` — пълна стойност за Admin/Owner/Accountant без одит. API вече приема само 9 или 13 цифри.
- **Решение:** промяна в кода — същото маскиране и разкриване; DQ за старите записи.

## FG-457 — тест на SUB-ADV-01 червен на #83; evidence твърди обратното

- **Тежест:** medium (evidence / CI). **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15, §16 „не обявявай Implementation Gate PASS без тестови доказателства“.
- **Код (#83 CP-01 `7750f4e`):** `test_sub_adv_01_subcontractor_advance.py::test_a_fresh_real_mongo_run_follows_the_rules_in_every_mode` — минава на main `1525a1e`, пада на `7750f4e` с 422 `CASH_RECEIPT_REQUIRED` (проверката на CP-01 правилно иска бон; setup-ът на #76 не е обновен както на #81); `docs/evidence/.../gates_r65.txt` — „0 провала, които main няма“.
- **Решение:** промяна само в теста (бон в setup-а) и поправка на evidence.

## FG-465 — „очаква кредитно известие“ не се затваря след кредитното известие (#82 × #84)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (кръстосано между PR; проход 38).
- **Канон:** Р47 „…Дотогава има DQ задача към Счетоводителя („очаква кредитно известие“)“ — задачата трябва да се затвори, когато известието се регистрира; CLAUDE.md §2 (един източник).
- **Код:** #82 `e07320d` — задачата се отваря и затваря само чрез `sync_credit_note_issue` (`services/invoice_allocation.py:607-668`, извиквано от `service.py:2083-2085`). #84 `f6e0c90` — затваря `dq_task.status` в `expected_credit_notes` (`services/invoice_corrections.py:775-777`, `routes/invoice_corrections.py:420`), не вика `sync_credit_note_issue` и пише втора схема `dq_issues` (`id "dq:{org}:{kind}:{entity}"`, `kind`/`assignee_role`, `invoice_corrections.py:304-319`). `git merge-tree e07320d f6e0c90` — конфликти във `finance.py`, `service.py`, `ownership.py`, A1 inventory.
- **Решение:** промяна в кода (в #84 или при сливането) — `sync_credit_note_issue` при изпълнение/сторно на очакване от кредитно известие; без записи в `dq_task.*`; една схема (FG-450).

## FG-470 — токенът на клиентския линк отива в PostHog

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 38, Playwright на production build с posthog-js 1.200.0, `scratchpad/ph38/tokcheck.js`).
- **Канон:** Р68 „Допуска се само анонимна статистика за отворени страници и грешки, без съдържание на полета“; FLOW-002 Magic link (токенът е достъп до офертата с цени и до приемане/отказ); CLAUDE.md §16 (без secrets в logs/frontend).
- **Код (#88 PWA-01 `d59bcca`):** `frontend/src/App.js:229` (`/offers/review/:reviewToken`); `frontend/src/lib/analytics.js:22, 57` пазят пътя на URL.
- **Проба:** `POST /e/` носи `$current_url` и `$pathname` = `/offers/review/rvTOKEN_…`.
- **Решение:** промяна в кода — пътят се заменя с шаблона на маршрута (`/offers/review/:token`) или аналитиката се изключва на `/offers/review/*`; токените, които вече са изпратени, се анулират по преценка на Крум.

## FG-471 — Р67: няма коментар по офертата за техническия ръководител

- **Тежест:** low. **Статус:** open. **PROVEN** (липса).
- **Канон:** Р67 „Техническият ръководител предлага количества чрез коментар по офертата.“
- **Код (OFF-02 `56913a4`):** няма модел и път за коментар по оферта (дълг D-OFF02-2). Нищо не изтича, защото отговор няма.
- **Решение:** промяна в кода — коментар по оферта без цени в отговора, с AuditEvent.

## FG-472 — бюджетът на офертата е отворен за всички M2 роли

- **Тежест:** medium. **Статус:** open. **PROVEN** (реален Mongo, off/shadow/enforce). Отделено от FG-363.
- **Канон:** Р67 „оферти създават и променят **само Собственик, Администратор и Счетоводител** (ролите, които виждат цените)“; Р20 (кой вижда цени/марж); CLAUDE.md §14 (AuditEvent).
- **Код (OFF-02 `56913a4`, същото на main):** `routes/offer_budget.py:23-24, 94-131` — `PUT`/`GET /offer-budgets/{offer_id}` само с M2; извън FINANCE_READS и SEC-02.
- **Проба:** Техник, Наблюдател, ТР и Шофьор пишат единични бюджетни цени и марж % (200, без AuditEvent) и четат продажба, бюджет, `margin_value`, `margin_percent` (200).
- **Решение:** промяна в кода — `require_money_write` за PUT и `require_finance_read` / изрязване за GET; AuditEvent.

## FG-480 — методът на плащане на аванс се разминава между пакета и регистъра

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 39).
- **Канон:** FLOW-006 (единен регистър — една истина за плащането); CLAUDE.md §2.12.
- **Код (#83 CP-01 `a5176b2`):** `routes/subcontractors.py:1195` (и `:719` за плащания) — `payment_method` от заявката, по подразбиране `"bank"`; регистърът го взима от сметката.
- **Решение:** промяна в кода — редът на пакета взима метода от сметката (от регистъра).

## FG-481 — повтор на изпълнен аванс връща грешка

- **Тежест:** low. **Статус:** open (+ Krum decision). **PROVEN**.
- **Канон:** Р29 / CLAUDE.md §14 (idempotency — повторът връща записания резултат).
- **Код (#83 CP-01 `a5176b2`):** `routes/subcontractors.py:1172-1181` (и `:697-706`) — проверките преди replay; `/finance/payments` прави replay първо.
- **Проба:** аванс → 201; архивиране на подизпълнителя; повтор със същия ключ → 422 (парите са излезли, клиентът вижда грешка).
- **Решение:** промяна в кода — replay преди проверките. Крум потвърждава, че повторът винаги връща оригиналния резултат.

## FG-482 — ДДС номер BG+ЕГН на клиент-фирма изцяло във вторични пътища

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** Р71 „ДДС номер във вида **BG+ЕГН се третира като ЕГН** (скрит, показва се само с одит, Р48/Р65)“; Р48 (3).
- **Код (#83 CP-01 `a5176b2`):** `POST /clients/company` приема `vat_number`=BG+ЕГН; пълна стойност за всички роли (вкл. Owner/Accountant без одит) в `routes/clients.py:414` (`/clients/search/unified`; търсене по цифрите на ЕГН — `:397`), `:639` (`/projects/{id}/client-info`), `routes/projects.py:1267` (`/projects/{id}/invoice-context`; също `:478, 1124, 1151`).
- **Решение:** промяна в кода — маскиране и одитирано разкриване и в тези пътища; търсене по ЕГН — по решение на Крум.

## FG-483 — ДДС номер BG+ЕГН на контрагент без одитирано разкриване

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** като поведение, SUSPECTED като разминаване.
- **Канон:** Р71; Р48 (3) (Owner/Accountant виждат пълното с одит).
- **Код (#83 CP-01 `a5176b2`):** номерът е маскиран за всички; `POST /counterparties/{id}/egn/reveal` → 404.
- **Решение:** промяна в кода — одитирано разкриване за Owner/Accountant, както при фактурите.

## FG-484 — evidence на CP-01 сочи несъществуващ файл

- **Тежест:** medium (evidence). **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15, §16 „не обявявай Implementation Gate PASS без тестови доказателства“.
- **Код (#83 CP-01 `a5176b2`):** README §18 и поправката в `gates_r65.txt` цитират `gates_r71.txt` като доказателство, че целият набор е пуснат с реален Mongo на клона и на main; файлът не съществува нито на `a5176b2`, нито в историята.
- **Решение:** промяна (без код) — файлът с реалните резултати или поправка на твърдението.

## FG-490 — отчет от стар вид заобикаля проверката за двойни часове

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проход 39, `scratchpad/fg39lab_probe/probe_39.py`).
- **Канон:** FLOW-019 — забрана „едни и същи часове да се броят два пъти“; Р62.
- **Код (#73 LAB-01 `df4cf51`):** `routes/daily_reports.py:378, 431-443` — отчет от стар вид (`employee_id` + `day_entries`) няма `project_id`, `approve_report_one` пропуска проверката по ден.
- **Проба:** одобрен ръчен ред 8 ч → одобрение на стар отчет 8 ч за същия ден → 200; сумата 1200 → 1360. Обратната посока е пазена (409).
- **Решение:** промяна в кода — проверката по ден и за стария вид (проектът от редовете); Крум решава дали старите отчети още се одобряват или се преобразуват.

## FG-491 — датата на ръчния ред не се валидира

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** FLOW-019 (двойно броене); Р62; CLAUDE.md §14 (validation/DQ).
- **Код (#73 LAB-01 `df4cf51`):** `routes/labor_smr.py:101` — `date` е свободен низ.
- **Проба:** „2026-10-05T00:00:00“, „2026-10-05 “, „05.10.2026“ върху ден с одобрен отчет → 201 и 200; часовете се броят два пъти; четците, които филтрират по дата, изпускат тези редове.
- **Решение:** промяна в кода — ISO дата (`YYYY-MM-DD`) и нормализиране преди проверката по ден; DQ за старите редове с неправилна дата (Крум: ръчна или автоматична поправка).

## FG-492 — корекцията по Р73 без връзка към заменения ред

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED**.
- **Канон:** Р73 „всяко такова действие оставя **следа кой и кога** (AuditEvent)“; CLAUDE.md §14 (correction path).
- **Код (#73 LAB-01 `df4cf51`):** `routes/labor_smr.py:76-169` — новият ред няма поле към заменения; създаването на ръчен ред не пише AuditEvent.
- **Решение:** промяна в кода — `corrects_entry_id` и AuditEvent при създаване; Крум решава дали връзката е задължителна.

## FG-493 — SEC-01 гейтовете падат след LAB73-R1

- **Тежест:** low (evidence / CI). **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15, §16 „не обявявай Implementation Gate PASS без тестови доказателства“.
- **Код (#73 LAB-01 `df4cf51`):** C03 брои `.insert_one(` = 1 срещу `mw.insert_once()` = 0 (LAB73-R1 замени пазача с повторно четене в транзакцията, `labor_smr.py:149-164` — поведението остава идемпотентно); C01, C02 и money_write_permissions — evidence отпреди LAB73-R1 (липсва `op.labor_day_locks`; създаването на индекса `labor_cost.py:493` записано като запис с org `None`).
- **Решение:** промяна (тестове/evidence) — адаптиране на структурната проверка и регенериране; без обявяване на Gate PASS дотогава.

## FG-495 — README на CP-01 цитира несъществуващ гейт файл

- **Тежест:** medium (evidence). **Статус:** open. **PROVEN** (проход 40).
- **Канон:** CLAUDE.md §15, §16 „не обявявай Implementation Gate PASS без тестови доказателства“.
- **Код (#83 CP-01 `b4a775f`):** README §19 цитира `gates_pass39.txt` два пъти като доказателство за целия набор на реален Mongo; файлът не съществува нито на главата, нито в историята; гейт файл за M3/M5 няма.
- **Решение:** промяна (без код) — файлът с реалните резултати или поправка на твърдението (повторение на FG-484).

## FG-496 — ДДС номер BG+ЕГН с разделители заобикаля маскирането при търсене

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р71 „ДДС номер във вида **BG+ЕГН се третира като ЕГН**“; Р48 (3).
- **Код (#83 CP-01 `b4a775f`):** API-то на контрагентите приема `BG-7501011111`, `BG 750101-1111`, `bg.7501011111` (201); списъкът ги маскира, но изключването в търсенето (`routes/counterparties.py:168-169`) хваща само `BG` + 10 цифри — Admin и Viewer намират записа по цифрите на ЕГН или само по „750101“.
- **Решение:** промяна в кода — нормализиране на ДДС номера при запис (или отказ на нестандартен вид) и търсене по нормализираната стойност; Крум избира.

## FG-497 — пълно копие на BG+ЕГН в `projects.invoice_details`

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р48 (3); CP83-03 / FG-226 (без излишни копия на пълно ЕГН).
- **Код (#83 CP-01 `b4a775f`):** `routes/projects.py:478, 504` (`import-client-invoice`) записва `BG7501011111` изцяло, без DQ; четците маскират.
- **Решение:** промяна в кода — без копие (връзка към записа на клиента) или маскирано копие + DQ.

## FG-498 — стари записи на клиенти и master-data планът показват BG+ЕГН

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** като поведение, SUSPECTED като достижимост (само стари данни).
- **Канон:** Р71; Р48 (3).
- **Код (#83 CP-01 `b4a775f`, и main):** стари `clients` с `vat_number`/`vatNumber` — пълна стойност за всички роли в `/clients`, `/clients/{id}`, `/clients/{id}/summary` (`ClientCreate` няма ДДС поле); `legacy_plan.public_view` (`SENSITIVE_KINDS = {"egn"}`) печата `vat:BG7501011111` в `GET /master-data/legacy/plan` и в справката за дубликати.
- **Решение:** промяна в кода — маскиране и в тези пътища; `vat` с BG+10 цифри като чувствителен вид; Крум решава миграция или само маскиране.

## FG-499 — удръжката от аванс без replay преди проверките

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED** (днес няма API път, който изважда акт от `confirmed`).
- **Канон:** Р29 / CLAUDE.md §14 (повторът връща записания резултат).
- **Код (#83 CP-01 `b4a775f`):** `routes/subcontractors.py:1262-1295` — проверките преди идемпотентността, без `completed_replay`; повтор след промяна на акта → 409 PAYMENT_ACT_NOT_CONFIRMED; друго тяло със същия ключ → същото 409, не IDEMPOTENCY_CONFLICT.
- **Решение:** промяна в кода — `completed_replay` преди проверките и тук; Крум потвърждава Р29 за всички парични пътища (вкл. ключ „в процес“ при архивиран получател).

## FG-500 — стари ръчни редове с неправилна дата изпадат от справките по период

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (проход 40, `scratchpad/fg40lab_probe/probe_40.py`).
- **Канон:** Р62 „разходът за труд по обект е **едно число във всички справки**“.
- **Код (#73 LAB-01 `4d1f5a3`):** `services/labor_cost.py:461-463` — `approved_manual_rows` филтрира датата с низово `$gte`/`$lte`.
- **Проба:** два стари одобрени реда по 20 € с неправилна дата: общо 890, за 01–31.10 — 870; еднодневните прозорци 25.10 и 26.10 не връщат нито един. Редовете имат DQ, така че разликата е видима.
- **Решение:** промяна в кода — сравнение по нормализирания ден, или поправка на редовете чрез сторно + нов ред (Крум).

## FG-501 — няма екран за ръчни редове за труд

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED**.
- **Канон:** CLAUDE.md §15 „UI за Крум и operational visibility“; Р62, Р66, Р73.
- **Код (#73 LAB-01 `4d1f5a3`):** никой frontend код не вика `/labor-entries` (създаване, одобрение, отказ, сторно) и не праща `corrects_entry_id`.
- **Решение:** Крум решава дали екранът е нужен преди „Готово“; после промяна в кода.

## FG-502 — отговорите при запис на работна сесия носят пари

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED**.
- **Канон:** Р62 (едно число; неодобреното никъде); Р20.
- **Код (#73 LAB-01 `4d1f5a3`):** `routes/work_sessions.py:216, 256, 462, 548` — start, end, split и PUT връщат `labor_cost` и `hourly_rate_at_date` сурово, вкл. на работника за собствената му сесия.
- **Решение:** промяна в кода — без пари в тези отговори; Крум решава дали „само часове“ важи и тук.

## FG-510 — някои изписвания на BG+ЕГН заобикалят нормализирането и маскирането

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проход 41, `scratchpad/p41cp/test_probe41_cp.py`).
- **Канон:** Р71 „ДДС номер във вида **BG+ЕГН се третира като ЕГН** (скрит, показва се само с одит, Р48/Р65)“; Р48 (3).
- **Код (#83 CP-01 `2415b5f`):** нормализирането (`services/counterparty_rules.py:201`) и изключването в търсенето (`routes/counterparties.py:170`) махат само `\s - . /`.
- **Проба:** `BG_…`, `BG:…`, `BG–…` (en dash), `BG,…`, `BG` + zero-width space и `ВG7501011111` (кирилско „В“ — реалистично от българска клавиатура) → 201 в `POST /counterparties` и `POST /companies`, записани както са въведени, не се третират като ЕГН; пълни в отговора и в списъка за Admin/Viewer; Admin/Viewer/SiteManager ги намират по `7501011111`, `750101`, `0101111` (вкл. unified search).
- **Решение:** промяна в кода — разпознаване на ЕГН по 10-те цифри след произволен префикс/разделители (вкл. кирилица и Unicode тирета/невидими знаци); Крум избира нормализиране до `BG…` или 422.

## FG-511 — replay-ят връща текущия запис, не оригиналния отговор

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** като поведение, SUSPECTED като разминаване.
- **Канон:** Р29 / CLAUDE.md §14 (idempotency — повторът връща записания резултат).
- **Код (#83 CP-01 `2415b5f`):** удръжката, авансът и плащането при replay четат записа наново; пътищата на FLOW-006 пазят първия отговор байт по байт (`routes/finance.py:107`).
- **Проба:** replay на удръжката след анулиране на акта → актът със `status: cancelled`.
- **Решение:** Крум решава дали „оригиналният резултат“ е същото id или същото тяло; при второто — пазене на отговора както във FLOW-006.

## FG-512 — replay първо не е на всички парични пътища

- **Тежест:** low. **Статус:** open (отделна задача). **SUSPECTED** (не е пробвано).
- **Канон:** Р29; техническо решение на оркестратора „replay първо на всички парични пътища“.
- **Код (#83 и main):** дълг D12 в README на CP-01 — `routes/full_cost.py:123`, `routes/labor_smr.py:93, 120, 302`, `routes/reports.py:976, 1042, 1107` четат преди `MoneyWrite.begin` без ранна проверка за replay.
- **Решение:** промяна в кода — отделна задача извън CP-01.

## FG-513 — AuditEvent при търсене по ЕГН без намерените записи

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р48 (3) („всяко показване се одитира“); техническо решение на оркестратора (търсене по ЕГН с AuditEvent).
- **Код (#83 CP-01 `2415b5f`):** `services/master_records.py:344-359` — само маскираната заявка и броят съвпадения.
- **Решение:** Крум решава дали е достатъчно; иначе — id-тата на намерените записи в събитието.

## FG-505 — агрегатът на обекта ползва платения труд за печалбата

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проход 41, `scratchpad/fg41lab_probe/probe_41.py`). Код на main, не е пипан от LAB.
- **Канон:** Р62 „разходът за труд по обект е **едно число във всички справки** от един канонически източник (project_labor_cost)“; CLAUDE.md §2.12.
- **Код (main `1525a1e`, и #73 `d34d41b`):** `routes/projects.py:2211-2217, 2264-2272` — блокът „pnl“ на `/projects/{id}/aggregate` взима платения труд като разход за труд; плочките „Труд“ на подобектите и графиката „Разходи“ в `ProjectDetailPage.js` — същото.
- **Проба:** печалба −1234 от платения труд при одобрен труд 850.
- **Решение:** промяна в кода — `project_labor_cost` и в агрегата; Крум решава дали някъде е нужен касов (платен) изглед — с изричен етикет.

## FG-506 — два източника за „изплатени заплати“

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED**.
- **Канон:** CLAUDE.md §2.12 (без втори source of truth); FLOW-006 (реалното плащане — само в регистъра).
- **Код (main `1525a1e`):** `routes/projects.py:1215-1223, 1477` — картата „Баланс (касов)“ чете старото `payroll_entries` (Paid, `net_pay`); другите изгледи — платените pay runs.
- **Решение:** промяна в кода — един източник (pay runs / регистъра на плащанията); Крум потвърждава.

## FG-507 — коригирано количество в LAB-02 не стига до одобрения ръчен акордов ред

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р62 (акорд = одобрено количество × единична цена); Р33 (количеството от LAB-02); FLOW-019 (без грешно отчетен труд).
- **Код (#75 LAB-02 `4fa4957`):** корекциите в `routes/labor_quantities.py:475-479` и четецът в `services/labor_cost.py` не проверяват свързаното одобрение.
- **Проба:** количеството 20 → 30, каноничното число остава 100 вместо 150, без DQ; отчетът не може да се одобри, нов ред се отказва — поправката е само сторно + нов ред.
- **Решение:** промяна в кода — корекция на количество, ползвано от одобрен ред, или се спира, или създава DQ задача/автоматично изпадане на реда; Крум избира.

## FG-508 — ръчен акордов ред приема самоодобрено количество

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (само стари данни).
- **Канон:** Р66 (двама различни души); Р33.
- **Код (#75 LAB-02 `4fa4957`):** `routes/labor_smr.py:238-245` — приема старо одобрение на количество, направено от самия работник (цена 250); четците на труда пренебрегват такива одобрения. Одобрението на реда от Собственика отчасти покрива риска.
- **Решение:** промяна в кода — отказ на самоодобрено количество; Крум потвърждава дали одобрението на реда е достатъчно.

## FG-515 — CSP в nginx ще блокира PostHog; заглавките зависят от ръчна подмяна

- **Тежест:** low. **Статус:** open. **PROVEN** (проход 42).
- **Канон:** Р75 („добавя се защита на браузъра (CSP…)“); Р68 (PostHog остава с анонимна статистика); CLAUDE.md §6 (Release Manifest / конфигурационна версия).
- **Код (#90 SEC-03 `bc52843`):** nginx CSP `connect-src 'self'` статичен — след #88 с ключ PostHog се блокира; заглавките стигат до production само след ръчна подмяна на живия nginx.conf.
- **Решение:** промяна в кода/release — `connect-src` с PostHog хоста само при конфигуриран ключ; подмяната на nginx.conf в Release Manifest.

## FG-516 — тестовият режим за `JWT_SECRET` е твърде широк

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р75 „без таен ключ сървърът не стартира (без „dev-secret-key“)“; CLAUDE.md §6 (Staging като production среда), §16.
- **Код (#90 SEC-03 `bc52843`):** `ENV=staging` или `ENVIRONMENT=dev` се броят за тестов режим — сървърът стартира, `JWT_SECRET=abc` се приема.
- **Решение:** промяна в кода — тестов режим само при изричен флаг за тестове; staging като production.

## FG-517 — скриването на лични данни преди модела е непълно

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р48 (3), Р71 (ЕГН/IBAN скрити); пакет SEC-03 т. 9 („само нужните полета (без ЕГН/IBAN)“).
- **Код (#90 SEC-03 `bc52843`):** регулярният израз не хваща IBAN с малки букви и ЕГН с интервали/тирета; прекалено скрива телефони, суми, цифри в id; снимките не се минимизират (без изрязване на документи с лични данни).
- **Решение:** промяна в кода — нормализиране преди проверката; списък от полета вместо свободен текст, където е възможно.

## FG-518 — кешът на ai-breakdown работи и при изключен AI

- **Тежест:** medium. **Статус:** open. **PROVEN** по код.
- **Канон:** Р76 „без тях AI е изключен“; CLAUDE.md §10 (AI само чернови → потвърждение).
- **Код (#90 SEC-03 `bc52843`):** `routes/smr_analysis.py:991-1003` — прилага кеширани AI резултати преди проверката `ai_enabled`/ключ на `:1037`.
- **Решение:** промяна в кода — проверката преди кеша; кешираният резултат също само като чернова.

## FG-519 — AI извикванията без canonical AuditEvent и отчет за потребление

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** CLAUDE.md §10 („Всеки важен отговор има source links и timestamp“), §14 (AuditEvent); FLOW-050 / CLAUDE.md §11 (месечен AI бюджет, AI Usage Ledger).
- **Код (#90 SEC-03 `bc52843`):** AI извикванията не пишат canonical AuditEvent, нито запис за потребление; включването на `ai_enabled` — само legacy `log_audit` (`routes/auth.py:640`).
- **Решение:** промяна в кода — canonical AuditEvent и запис в AI Usage Ledger; Крум решава дали включването иска Approval и брои ли се срещу бюджета.

## FG-520 — остатъци от Emergent извън обхвата на пакета

- **Тежест:** low. **Статус:** open (+ Krum за dev сървъра). **PROVEN**.
- **Канон:** Р75 („махат се скриптовете и надписът на Emergent от програмата“); Р76.
- **Код (#90 SEC-03 `bc52843`):** docstring `ai_proposal.py:3`, preview URL в `backend_test.py`; `test_m9_alerts.py` вика напомнянията без ключ и очаква 200; чеклистът в паметта още назовава `EMERGENT_LLM_KEY`; dev сървърът за visual edits вярва на `*.emergent.sh`; `openai` и `litellm` закрепени, но неизползвани.
- **Решение:** промяна в кода — почистване; Крум решава за dev сървъра.

## FG-521 — напомнянията: AuditEvent след изпълнението; `all_tenants` без разрешение

- **Тежест:** low. **Статус:** open. **SUSPECTED**.
- **Канон:** CLAUDE.md §3 („temporary scoped Support/Partner Access Grants“; Tenant Guard на всеки job), §14.
- **Код (#90 SEC-03 `bc52843`):** AuditEvent се пише след изпълнението, не атомарно; човек Platform Admin може да пусне `all_tenants` без Support Access Grant.
- **Решение:** промяна в кода — събитие преди/с изпълнението; `all_tenants` само със служебен ключ или Support Access Grant.

## FG-522 — оригиналната снимка не се пази преди AI

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**. Налице и на main.
- **Канон:** CLAUDE.md §4 „Оригиналното аудио и оригиналната снимка се пазят преди AI/OCR обработка.“; Р72.
- **Код (#90 SEC-03 `bc52843`):** клиентът компресира снимките преди изпращане; пази се само едно смалено base64 копие в Mongo, при подаване и след AI. Признат дълг до W0-06 (File Registry).
- **Решение:** промяна в кода в W0-06; предложение за Крум — `ai_enabled` за никой tenant преди W0-06.

## FG-525 — `POST /subcontractors` не нормализира и не маскира ДДС номера

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (проход 43). Налице и на main.
- **Канон:** Р71; Р48 (3); техническо решение на оркестратора (нормализиране при въвеждане).
- **Код (#83 CP-01 `781d185` (код `c50df5f`)):** `routes/subcontractors.py:122, 135` — пази суровия вход и връща пълното BG+ЕГН в отговора 201 за всяко изписване, вкл. `BG7501011111`.
- **Решение:** промяна в кода — същото нормализиране и маскиране като на другите пътища.

## FG-526 — някои ДДС стойности не се разпознават като ЕГН

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р71 „ДДС номер във вида **BG+ЕГН се третира като ЕГН** (скрит, показва се само с одит)“; Р48 (3).
- **Код (#83 CP-01 `781d185` (код `c50df5f`)):** `services/counterparty_rules.py:209-235`, `routes/clients.py:405-418`.
- **Проба:** гръцко `Β`, комбиниращ знак върху `B`, `VAT BG…`, `ДДС BG…`, `xBG…`, `BG… (физ. лице)`, `BG…x`, `ЕГН 7501011111`, само `7501011111` → 201, записани повредени, пълно ЕГН за всички роли във всички четци; Admin/Viewer/SiteManager ги намират по цифрите в unified search; без одит; разкриване 404; създаване на фактура ги отказва с 400.
- **Решение:** Крум избира — отказ 422 (само BG + 9 или 10 цифри, както при фактурите) или разпознаване по 10-те цифри и маскиране; Крум решава дали 10-цифрена стойност без „BG“ е ЕГН по Р71.

## FG-527 — нормализирането тихо поврежда данни

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §14 („validation/DQ“); Р71.
- **Код (#83 CP-01 `781d185` (код `c50df5f`)):** `services/counterparty_rules.py:224-225`.
- **Проба:** `ДДС BG…` → `CBG…`; `ЕГН …` → `EGH…`; `(физ. лице)` → завършващо `E`; гръцко `Β` губи B; цифри от други писмености изчезват — всичко с 201, без 422 и без DQ.
- **Решение:** промяна в кода — отказ (422) или DQ при стойност, която нормализирането променя извън разделителите.

## FG-528 — кратко търсене по цифри намира BG+ЕГН записи (регресия)

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN**. Регресия спрямо `2415b5f`.
- **Канон:** Р71; Р48 (3); техническо решение на оркестратора (търсене по цифри на ЕГН само Owner/Accountant, с AuditEvent).
- **Код (#83 CP-01 `781d185` (код `c50df5f`)):** `routes/counterparties.py:122-130, 193-197` — под 4 цифри изключването не се прилага.
- **Проба:** Admin/Viewer/SiteManager: `BG750` → 28 записа; `750`, `111` → 32 (при `2415b5f` записите се изключваха винаги) — ЕГН може да се познае по 3 цифри; кратките търсения на Owner/Accountant не се одитират.
- **Решение:** промяна в кода — изключването на BG+ЕГН записи за другите роли независимо от дължината; Крум решава дали кратките търсения на Owner/Accountant се одитират.

## FG-529 — търсене с fullwidth цифри без AuditEvent

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** техническо решение на оркестратора (търсене по ЕГН с AuditEvent); Р48 (3).
- **Код (#83 CP-01 `781d185` (код `c50df5f`)):** `services/counterparty_rules.py:238-241` — `egn_digits_query` пази не-ASCII цифри; `/counterparties` намира всички BG+ЕГН записи без събитие, unified search — нищо.
- **Решение:** промяна в кода — нормализиране на заявката (NFKC) преди проверката за одит.

## FG-530 — агрегатът смесва касов приход с начислени разходи

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED** (по код, проход 44).
- **Канон:** FLOW-008 (печалбата не се смесва с каса/банка); FLOW-015 L37 / FLOW-024 L180 (фирменият резултат показва какво е включено); Р62.
- **Код (#73 LAB-01 `06a309d`, и main):** `routes/projects.py` блок „pnl“ на `/projects/{id}/aggregate` — `revenue` = платени фактури (`own_inv["paid"]`), `expenses` = одобрен труд + материали без ДДС.
- **Решение:** промяна в кода — приход по издадени фактури (както P&L) или изричен етикет за основата; Крум потвърждава.

## FG-531 — последващи корекции не стигат до маркирания ред

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проход 44, `scratchpad/fg44lab_probe/probe_44.py`).
- **Канон:** Р77 „…редът за труд се маркира „изисква корекция“; програмата предлага сторно + нов ред по **новото** количество…“.
- **Код (#75 LAB-02 `b35d0c7`):** `services/labor_cost.py:476` — редовете се търсят само по id-тата на заменените одобрения; `:494` — всяко маркиране презаписва предишното.
- **Проба:** корекция 20 → 30 (маркиран, предложение 30/150); втора корекция 30 → 40 → маркировката остава 30/150 и сочи анулирано одобрение, без AuditEvent и аларма; анулиране след това — нищо не се записва; реалният нов ред е 200.
- **Решение:** промяна в кода — търсене по веригата на одобренията; предложението винаги следва последното одобрено количество; анулиране = предложение само за сторно (Крум потвърждава).

## FG-532 — сторното от създателя сваля деня на 0 преди новия ред

- **Тежест:** medium. **Статус:** open — Krum decision. **PROVEN**.
- **Канон:** Р77 „До одобрението старата сума остава, но с видимо предупреждение.“; Р73 „въвелият ръчен ред … **може** сам да го откаже/коригира/сторнира“; Р66.
- **Код (#75 LAB-02 `b35d0c7`):** `routes/labor_smr.py:501-506` — сторно от създателя сам, веднага, затваря алармата.
- **Проба:** денят 100 → **0** (след сторното) → 200 (след одобрението на новия ред); сторното не се одобрява от втори човек.
- **Решение:** Крум избира: (а) сторно и нов ред се одобряват заедно от втори човек; (б) сторното чака одобрението на новия ред; (в) 0 в междинния период е приемливо. После промяна в кода.

## FG-533 — предупреждението „изисква корекция“ няма UI

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** по код.
- **Канон:** Р77 („видимо предупреждение“); CLAUDE.md §15 (UI за Крум).
- **Код (#75 LAB-02 `b35d0c7`):** `frontend/src` не съдържа `correction_required`, двата нови DQ кода или `dq_warnings`; предупреждението е само в API и като обща аларма; ТР затваря алармата с 200, маркировката и DQ остават.
- **Решение:** промяна в кода — видимо предупреждение за Owner/Accountant; алармата се затваря само с корекцията (Крум).

## FG-534 — корекцията на количество не е атомарна

- **Тежест:** low. **Статус:** open. **SUSPECTED** (не е възпроизведено).
- **Канон:** CLAUDE.md §14 („domain transaction/service“); Р77.
- **Код (#75 LAB-02 `b35d0c7`):** `routes/labor_quantities.py:476-501` — анулирането, вмъкването (`:495`) и маркирането са отделни операции; срив след `:495` оставя немаркиран ред, повторът дава 409 и редът никога не се маркира.
- **Решение:** промяна в кода — една транзакция.

## FG-535 — още нескрити лични данни към модела

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (проход 44).
- **Канон:** Р48 (3), Р71; пакет SEC-03 т. 9 („без ЕГН/IBAN“).
- **Код (#90 SEC-03 `863876b`):** регулярните изрази за скриване.
- **Проба:** минават `Иванов,8001010008` (ЕГН след запетая/точка), `8001010008 12 бр`, ЕГН с точка за разделител, IBAN групиран с NBSP/двойни интервали, ЕГН/IBAN с грешна контролна сума, ЛНЧ.
- **Решение:** промяна в кода — граници на думи вместо разделители; Крум решава дали стойности с грешна контролна сума също се скриват (по-безопасно, с малко излишно скриване).

## FG-536 — отчетът за AI потребление се пише преди одита

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §14 (domain transaction + AuditEvent); FLOW-050 (AI Usage Ledger).
- **Код (#90 SEC-03 `863876b`):** редът в `ai_usage_ledger` се записва преди AuditEvent — при срив на audit store след успешно извикване действието се брои без събитие, отговорът се губи, ai-breakdown пише резервното 60/40.
- **Решение:** промяна в кода — двата записа в една транзакция (или събитието първо).

## FG-537 — AI бюджетът не се прилага

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** CLAUDE.md §11 „Всеки план включва месечен AI бюджет — План+AI: Start 100 / Control 500 / Pro 2000 действия + add-on пакети“; FLOW-050.
- **Код (#90 SEC-03 `863876b`):** никой не чете `ai_usage_ledger`; няма връзка с плана и проверка преди извикването.
- **Проба:** при 2500 действия за месеца (над Pro 2000) следващото извикване минава; поведение при изчерпан бюджет няма; единицата не е определена (разбивка до 30 реда = 1 действие, партидно предложение = 1 на ред).
- **Решение:** Крум решава дали сливането по Р76 иска прилагане на бюджета сега или регистърът стига до W0 Subscription, какво става при изчерпан бюджет и какво е едно действие; после промяна в кода.

## FG-538 — включването на AI не е атомарно и без Approval

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** CLAUDE.md §8 („custom entitlement“ иска Approval), §14 (idempotency key, AuditEvent в транзакцията).
- **Код (#90 SEC-03 `863876b`):** `PUT /api/ai/settings` записва флага преди събитието — при срив на audit store връща 500, но AI остава включен без събитие; без Idempotency-Key, причина и Approval.
- **Решение:** промяна в кода — една транзакция, ключ и причина; Крум решава за Approval.

## FG-539 — SEC-03 конфликтира с текущия main

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15/§16 (тестови доказателства на слетия head); Р68, Р75.
- **Код:** `git merge-tree origin/main(3863610) #90 SEC-03 `863876b`` — конфликт в `frontend/public/index.html` (клонът още има стария inline PostHog с вграден `phc_` ключ, махнат от #88) и в PM-01 `run_meta.json`. Страната на клона пада на теста за аналитиката на #88 и губи PWA таговете; страната на main връща скриптовете на Emergent.
- **Решение:** промяна — сливане на main в #90 с PWA таговете на #88 + CSP на SEC-03, без inline скриптове (работи в локален опит); PM-01 регенериран след сливането.

## FG-540 — `/api/media/avatar/{filename}` сервира всеки качен файл без вход и без tenant

- **Тежест:** high. **Статус:** open. **PROVEN** (P1).
- **Канон:**
  - FLOW-029 L124: „клиентът да вижда вътрешни/чувствителни снимки;“ (забранено);
  - FLOW-029 L146: „permission-safe previews и short-lived links;“;
  - FLOW-043 D-15 L102: „всички входни точки минават през Tenant Guard;“;
  - CLAUDE.md §3: „Всеки request, job, export, file operation, search, AI tool и webhook минава през Tenant Guard.“.
- **Код (main `3863610`):**
  - `routes/media.py:210-221` `serve_avatar` — без `Depends(get_current_user)`, без запис в `media_files`, без ACL. Чете `/app/backend/uploads/{filename}` и го връща като `image/jpeg`;
  - в същата папка пишат и други пътища, общо за всички tenant-и:
    - `media.py:94-101` — снимки от обекта;
    - `technician.py:1159-1162` — фактура от терена;
    - `ocr_invoice.py:73-75` — фактури на доставчици;
    - `procurement.py:59, 356-358`;
  - името на файла е `{media_id}.{ext}`. `media_id` и `url` се връщат в отговорите на upload, в `pending_expenses.media_url` и в `missing_smr.attachments[].url`;
  - единственият клиент е аватарът (`EmployeeDetailPage.js:933-934`).
- **Проба (P1):**
  - Owner качва снимка с контекст обект B → 200;
  - Technician, който не е член на B: `GET /api/media/file/{fn}` → 403;
  - без вход: `GET /api/media/file/{fn}` → 403, а `GET /api/media/avatar/{fn}` → **200**, същите байтове, `image/jpeg`.
- **Решение:** промяна в кода:
  - `/media/avatar` да изисква сесия и да сервира само файл с `context_type="profile"` от `media_files` на tenant-а на сесията (или аватарите — в отделна папка);
  - всички файлове да се сервират само през пътя с ACL;
  - тест: без вход → 401, чужд не-профилен файл → 404, друг tenant → 404.
  - Трайно: File Registry с кратковременни подписани линкове (W0-06, FG-143).

## FG-541 — снимките на обекта (`project_photos`) се качват, четат и свалят от всяка роля за всеки обект

- **Тежест:** medium. **Статус:** open. **PROVEN** (P2).
- **Канон:**
  - FLOW-029 L113: „Проектен мениджър: назначени обекти, избор за отчет/акт/портфолио.“;
  - FLOW-029 L115: „Работник: качване към разрешен обект и кратък коментар; без изтриване на чужди файлове.“;
  - FLOW-029 L139: „AuditEvent история.“;
  - Р20 (видимост само за своите обекти); FLOW-043 D-08.
- **Код (main `3863610`):**
  - `routes/projects.py:1190-1211` (list), `:1214-1260` (upload) и `:1263-1282` (file) — само `get_current_user` и `org_id`, без `can_access_project`, без роля;
  - PM-01 матрицата няма гейт за тези пътища;
  - при качване — само legacy `log_audit` (`:1257`);
  - паралелният път `media_files` с `context_type="project"` проверява членство (`media_acl.py:136-139`). Същата снимка на същия обект има различни права в зависимост от това в коя колекция е.
- **Проба (P2):**
  - в B няма членове (`team_rows_on_B 0`);
  - Viewer `POST /projects/B/photos` → **201**;
  - `audit_events` Δ0, `audit_logs` +1;
  - Technician (не е член на B) — списък → 200 (1 снимка), файл → 200.
- **Решение:** промяна в кода:
  - запис само от член на обекта с роля за качване (Owner/Admin навсякъде; Viewer/Driver — не);
  - четене по Р20 (`can_access_project`);
  - каноничен AuditEvent при качване;
  - positive + forbidden тестове.
  - При W0-06 двата регистъра да станат един (FG-143).

## FG-542 — използвана медия се трие физически (`DELETE /api/media/{id}`), отчетите сочат изтрит файл

- **Тежест:** high. **Статус:** open. **PROVEN** (P3).
- **Канон:**
  - FLOW-029 L80: „Нормалното изтриване означава архивиране. Използван медиен файл не се заличава физически.“;
  - FLOW-029 L122: „използван файл да бъде изтрит физически;“ (забранено);
  - CLAUDE.md §2.9; Р56 (2); Р71.
- **Код (main `3863610`):**
  - `routes/media.py:446-479` — собственикът или Admin/Owner. Прави `file_path.unlink()` (`:472`) и `media_files.delete_one` (`:477`);
  - не проверява `work_reports.photos`, `missing_smr.attachments`, `pending_expenses.media_id`, `finance_payments`;
  - няма AuditEvent;
  - поправката на FG-425 (бон в плащане → 409) е само на #83 CP-01.
- **Проба (P3):**
  - SiteManager качва снимка към A;
  - тя е сложена в **одобрения** отчет `wr-1.photos`. Owner я прикача към `ms-B` → 200;
  - SiteManager `DELETE /api/media/{id}` → **200**;
  - `media_row_left 0`, `file_on_disk false`;
  - `wr-1` (Approved) и `ms-B` още сочат изтрития `media_id`;
  - AuditEvent Δ0.
- **Решение:** промяна в кода:
  - `DELETE /media/{id}` да става архивиране (статус, причина, кой/кога, Idempotency-Key, AuditEvent), както снимката на обекта в PRJ-01;
  - физическо изтриване — никога за медия с връзка (отчет, СМР, плащане, разход, доставка);
  - при използвана медия → 409 с предложение за скриване;
  - възстановяване от Admin;
  - тест за използвана снимка (FLOW-029 L149).
  - Обединява се с поправката на FG-425 от #83.

## FG-543 — прикачените файлове към ново СМР и снимките в отчета приемат всеки `media_id`/URL, за чужд обект, без одит

- **Тежест:** medium. **Статус:** open. **PROVEN** (P4 — missing-SMR) / **SUSPECTED** (`work_reports.photos`, по код).
- **Канон:**
  - FLOW-029 L125: „снимка за друг обект да бъде свързана без проверка;“ (забранено);
  - FLOW-029 L98: „Потребителят избира съществуващи снимки; не ги качва втори път.“;
  - FLOW-029 L104;
  - Р20; FLOW-043 D-08.
- **Код (main `3863610`):**
  - `routes/missing_smr.py:271-294` — `require_m2` и `org_id` на СМР. Не проверява дали `media_id` съществува в `media_files`, дали е на същия обект и дали потребителят е член. `url` и `filename` идват от клиента;
  - `:297-315` (remove) — същото;
  - няма AuditEvent;
  - `technician.py:41, 51` — `photos: List[str]` се записва както е подаден в `work_reports.photos` (`:1025`, презаписва при повторно подаване `:1035`) и в `quick-smr attachments` (`:1095`);
  - URL-ът там е `/api/media/file/{media_id}` без разширение. Той не съвпада със `stored_filename` и не се отваря.
- **Проба (P4):**
  - SiteManager, който не е член на B, прикача снимка от A към `ms-B` → **200**;
  - прикача `media_id "no-such-media"` с `url "https://evil.example/x.jpg"` → **200**;
  - маха прикачен файл от B → 200;
  - AuditEvent Δ0.
- **Решение:** промяна в кода:
  - връзката да се прави само към съществуваща медия на същия tenant и същия обект (или 409 с изрично потвърждение за друг обект);
  - URL да не се приема от клиента — изчислява се от медията (после `file_id`);
  - членство по Р20;
  - AuditEvent за свързване и махане;
  - същата проверка за `work_reports.photos` и `quick-smr`.

## FG-544 — медията има само една връзка; `/media/link` тихо я мести и сменя кой я вижда

- **Тежест:** medium. **Статус:** open. **PROVEN** (P4).
- **Канон:**
  - FLOW-029 L14: „Един `file_id` може да участва в дневен отчет, акт, дефект, задача и портфолио без физически копия.“;
  - FLOW-029 L121: „независими копия в отчет, акт и дефект;“ (забранено);
  - FLOW-043 D-11 (relations във File Registry); D-08.
- **Код (main `3863610`):**
  - `media_files` има едно поле `context_type`/`context_id`;
  - `routes/media.py:135-183` `link_media` проверява собственика (или Admin/Owner) и достъпа до **новия** контекст. После `update_one({"id": …}, {"$set": {"context_type", "context_id", "linked_at"}})` (`:169-176`) — без `org_id` във филтъра, без история на старата връзка, без AuditEvent;
  - ACL-ът (`media_acl.py:182-231`) зависи само от текущия контекст. Затова смяната на връзката сменя и кой вижда файла.
- **Проба (P4):**
  - снимка на SiteManager с контекст обект A;
  - Owner `POST /media/link` → `workReport wr-2` (обект B, автор Viewer) → 200;
  - контекстът става `workReport/wr-2`, връзката с A я няма;
  - Viewer вече чете метаданните → 200;
  - AuditEvent Δ0.
- **Решение:** промяна в кода (в W0-06 / FLOW-016 relations):
  - много връзки за един файл, append-only, с кой/кога/защо;
  - ACL по обединението на връзките според правата за всяка от тях;
  - свързването не премахва предишна връзка, а махането е отделно действие с AuditEvent.
  - До тогава: `/media/link` да отказва (409) медия, която вече има контекст, вместо да я презаписва.

## FG-545 — моделът на фото/видео архива по FLOW-029 не е реализиран

- **Тежест:** medium (Wave 2, зависи от W0-06). **Статус:** open. **PROVEN** (по код и grep; P2 за полетата).
- **Канон:**
  - FLOW-029 L26: „видео;“;
  - L31: „Автоматично се записват обект, дата/час, потребител, устройство, GPS при разрешение, оригинал, compressed и thumbnail.“;
  - L67: „Таговете са Master Data, поддържат алиаси и масово поставяне върху избрани снимки.“;
  - L71-78 (статуси);
  - L84-94 (филтри);
  - L98 („При дневен отчет системата предлага снимките от същия ден/обект.“);
  - L100 („Снимките за актуване се свързват с конкретен СМР ред/измерване.“);
  - L108 (портфолио);
  - L112 („архивиране/възстановяване“);
  - L143-149 (Implementation Gate).
- **Код (main `3863610`):**
  - типовете са само изображения (`media.py:20`, `projects.py:1185`) — видео → 400;
  - `project_photos` пази само `project_id`, `uploaded_by`, `uploaded_at`, името, типа, размера и бележката. Няма устройство, GPS, `thumbnail` и `compressed`;
  - grep: 0 за категории, тагове, статуси (освен `retired`), портфолио, задължителна снимка, видео;
  - няма възстановяване на скрита снимка;
  - няма Idempotency-Key при качване;
  - няма UI за галерия (frontend не вика `/projects/{id}/photos`).
- **Проба:** P2 — `stored_fields` без устройство, GPS, категория, статус.
- **Решение:** промяна в кода, Wave 2 след W0-06:
  - медийни metadata върху `file_id`;
  - категории и тагове от Master Data;
  - статусите по L71-78;
  - галерия с филтри;
  - предлагане на снимки в дневния отчет;
  - връзка към СМР ред за актуване;
  - checklist правило за рискови СМР;
  - портфолио като изглед;
  - възстановяване от Admin;
  - offline опашка (PWA-02, Р61).
  - Без ново бизнес решение — канонът е заключен.

## FG-546 — контекстите `message`/`site` и фактурата от терена заобикалят видимостта по обекти

- **Тежест:** low. **Статус:** open. **SUSPECTED** (по код, не е пробвано).
- **Канон:**
  - FLOW-029 L115: „Работник: качване към разрешен обект и кратък коментар;“;
  - FLOW-029 L124 (вътрешни/чувствителни снимки);
  - Р20.
- **Код (main `3863610`):**
  - `deps/media_acl.py:149-152` — `message`: „TODO … allow any user in the same org“;
  - `:154-162` — `site`: всеки в организацията, щом обектът съществува;
  - `media.py:429-431` прави същото за `message` в списъка (там `site` липсва и не се показва — двата пътя се разминават);
  - `routes/technician.py:1140-1194` `photo-invoice` — `project_id` от формата не се проверява (нито дали съществува, нито членство). Създава се `media_files` с `context_type="project"` и `pending_expenses` за чужд обект.
- **Решение:** промяна в кода:
  - `message` — по подателя/получателите (или забранен до модула за съобщения);
  - `site` — по членство в обекта;
  - `photo-invoice` — проверка на обекта и членството преди записа на файла, с тест.

## FG-555 — MEDIA-SEC-01 и #83 се сблъскват в `delete_media`

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 45).
- **Канон:** Р71 „**използвана касова бележка не се изтрива**“; CLAUDE.md §2 правило 9.
- **Код:** `git merge-tree` на MEDIA-SEC-01 `35df04e` и #83 `ddc6e9a` — конфликт в `backend/app/routes/media.py` (`delete_media`). Само на клона: бон, сочен от `finance_payments.cash_receipt_file_id`, се оттегля с 200, после Счетоводителят получава `/media/file` → 404. След сливане `_INACTIVE_FILE_STATES` на #83 няма `"retired"` — оттеглен файл би се приел за нов бон.
- **Решение:** промяна в кода (при второто сливане) — `receipt_references` на #83 в `_media_usages` и `"retired"` в множеството.

## FG-556 — проверката за използване не вижда всички записи

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** CLAUDE.md §2 правило 9 („Няма hard delete на използвани … записи“); FLOW-001 P-04 (историята се пази); FLOW-037 §12.3.
- **Код (MEDIA-SEC-01 `35df04e`):** `_media_usages` пропуска `work_reports.photos`, `extra_work_drafts.photos`, `pending_expenses.media_id`, `finance_payments`.
- **Проба:** несвързана снимка от одобрен отчет → DELETE → 200 оттеглена; авторът на отчета — `/media/file` 200 преди, 404 след; път за възстановяване няма.
- **Решение:** промяна в кода — всички препратки в проверката; Крум решава дали използван файл винаги е 409 (препоръка: да).

## FG-557 — аватарите се виждат от всички; Admin свързва всеки файл

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р48 (3), Р20; CLAUDE.md §14 (AuditEvent).
- **Код (MEDIA-SEC-01 `35df04e`):** всеки файл с `context_type="profile"` се сервира на всеки потребител на tenant-а; Admin може да свърже всеки несвързан файл (напр. бон на Счетоводителя) с профил → Viewer го получава през `/media/avatar` (200), докато `/media/file` → 403; свързването не се одитира; всеки свързан файл е „използван“ завинаги — стар аватар не може да се оттегли.
- **Решение:** Крум решава видимостта на аватарите и кой задава аватар; после промяна в кода (само изображения, собствени качвания, AuditEvent).

## FG-558 — оттеглен файл: метаданни и липса на възстановяване

- **Тежест:** low. **Статус:** open. **PROVEN** по код.
- **Канон:** CLAUDE.md §14 (correction path); FLOW-029 (възстановяване — застъпва се с FG-545).
- **Код (MEDIA-SEC-01 `35df04e`):** `routes/media.py:217` — `GET /media/{id}` връща метаданните на оттеглен файл на не-админи; Admin няма списък на оттеглените и възстановяване.
- **Решение:** промяна в кода.

## FG-565 — проформата се брои за приход в агрегата и P&L

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (проход 46).
- **Канон:** Р80 „приходът се брои по **издадени фактури** (както в отчета за печалба и загуба)“.
- **Код (#73 `2ca349e`):** `services/project_pnl.py:13-17` (`issued_revenue_net` без филтър по вид), извикан от `routes/projects.py:2516`.
- **Проба:** изпратена проформа (нето 400) влиза в прихода и едновременно в `proforma_future` (480); таблото на обекта я изключва, агрегатът преди Р80 също. Фактура без `subtotal` брои брутото като нето. P&L прилага същото правило — съответствието по Р80 се пази.
- **Решение:** Крум — проформата приход ли е (препоръка: не — само данъчни фактури/известия); после промяна в кода в общата функция.

## FG-566 — агрегатът на обекта показва пари на всяка роля

- **Тежест:** high. **Статус:** open. **PROVEN**.
- **Канон:** Р20 (парите се виждат само от финансови роли; видимост по обекти); FLOW-002/010; SEC-02.
- **Код:** `routes/projects.py:2444-2445` — `GET /projects/{id}/aggregate` само с вход, без запис в каталога на SEC-02 и без проверка на членство. Пропускът е на main; #73 (Р80) добавя още полета.
- **Проба:** Driver, Viewer, Technician, Warehousekeeper и ТР — не членове на обекта — 200 с приход 2270, печалба 1420, труд 850, платени/неплатени фактури.
- **Решение:** промяна в кода — `require_finance_read`/`strip_money_for_non_finance` и Tenant/обектова видимост на маршрута; запис в каталога на SEC-02.

## FG-567 — фалшива „интермитентна“ утечка в теста на пулса

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15 (тестове като доказателство).
- **Код:** `tests/test_sec_02_finance_read.py:504, 523` (`"7777" in resp.text`); `services/pulse_generator.py:14, 151`.
- **Проба:** 6000 пулса за Driver — 3 съвпадения, всички в `generated_at` (`…14.777737`); 6 пълни прогона — 0 утечки към не-финансови роли.
- **Решение:** промяна в теста — проверка на парични полета/стойности, не подниз.

## FG-568 — анулиране на одобрение на труд без транзакция

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** Р77/Р81; CLAUDE.md §14 (domain transaction, AuditEvent).
- **Код (#75 `9e34641`):** `routes/labor_quantities.py:357` (`PUT /labor-quantities/entry`), `routes/daily_reports.py:332, 602, 1216` — `void_labor_approvals` без сесия (само `daily_reports.py:806` подава сесия).
- **Проба:** срив при AuditEvent по Р77 в `PUT /labor-quantities/entry` — одобрението анулирано, версията вдигната, количеството не записано, редът маркиран без AuditEvent и аларма; повторът (200) не ги дописва.
- **Решение:** промяна в кода — същата транзакция като в пътя на одобрението (FG-534) на всички пътища за анулиране.

## FG-569 — ръчните акордни редове не стигат до ведомостта

- **Тежест:** medium. **Статус:** open (+ Krum). **SUSPECTED** (по код).
- **Канон:** Р81 „старата сума остава **в разхода и за заплатата**“; Р62 (един труд); CLAUDE.md §7 („Акордът изисква одобрено количество × единична цена труд“).
- **Код:** `routes/pay_runs.py:314, 501, 602` → `services/report_normalizer.py:33` — четат само дневни отчети, не ръчните редове на труда.
- **Решение:** Крум — ръчните (акордни) редове ред ли са във ведомостта? Ако да — промяна в кода (ведомостта чете `project_labor_cost`/одобрените редове); ако не — Р81 „за заплатата“ се отнася само до дневните отчети.

## FG-580 — суровата AI оценка става приход в P&L

- **Тежест:** high. **Статус:** open. **PROVEN** (проход 46, реален Mongo, `scratchpad/fg46_030/test_probe_030.py` → `out.json`).
- **Канон:** FLOW-030 L98 (забранено „чернова да се представя като официален запис“), L103 („стар чат отговор да се използва като текущ source of truth“), L50; CLAUDE.md §10 („Raw AI content не е official record“).
- **Код (main `3863610`):** `routes/missing_smr.py:651-697` записва `ai_estimated_price` (само проверка на модула, `deps/modules.py:102-103`; без статус и AuditEvent); `services/project_pnl.py:53-57, 152` го сумира в прихода „additional_offered“; `ProjectPnLDashboard.js:127` го показва.
- **Проба:** Viewer пуска оценката → 205 в записа; офертата коригирана на 50 и Rejected → P&L още 205; Technician преизчислява след `offered` (к-во 40) → 820 в P&L при непроменена оферта; нито един AuditEvent/legacy одит.
- **Решение:** промяна в кода — P&L чете текущата версия на офертата/договора, не AI полето; AI оценката е чернова без паричен ефект; без преизчисление след `offered`; права и AuditEvent.

## FG-581 — оферта от AI оценките без права и одит

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** FLOW-030 L96 („измисляне на стойности“); FLOW-043 D-07 („иначе създава само чернова“); CLAUDE.md §10 (draft → confirmation → permission → Approval → domain service).
- **Код:** `routes/missing_smr.py:708-799` (`:742-756`).
- **Проба:** Viewer създава оферта (200, Draft, 246); материал 8.5 + труд 12 → труд 20.5/ед., материал 0; записът става `offered`; без одит.
- **Решение:** промяна в кода — проверка на ролята, отделни материал/труд, AuditEvent, Idempotency-Key.

## FG-582 — измислен процент „доверие“

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** FLOW-030 L50 „Не се използва измислен общ процент „доверие““.
- **Код:** `services/ai_proposal.py:212, 324`; `routes/smr_analysis.py:1063, 1089`; `routes/assets_ai_intake.py:42`; `ExtraWorkModal.js:250, 406`; `routes/extra_works.py:431`. Пробата: 0.85 за пътя по правила.
- **Решение:** промяна в кода — без процент; източник, дата и какво не е включено.

## FG-583 — няма BEG Brain, а 4 отделни AI пътя

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** по код.
- **Канон:** FLOW-030 L9-22 (един Brain, специализирани шапки), L26 (схема на tool отговора), L54-73 (панел, история), L111-114, Gate L118-120; Р76 (ключ и модел не са в кода).
- **Код:** `ai_proposal.py:265`, `assets_batch_intake.py:128`, `smr_analysis.py:1038` — вградени модели; 2 ключа; няма каталог на tools, `as_of`, източници, валута, история, статус на AI.
- **Решение:** Крум — съществуващите AI маршрути стават ли шапки на Brain зад каталог на tools и схема на отговора (Wave 3), или се замразяват/махат дотогава. Вградените модели — по Р76, поправено на #90.

## FG-584 — грешка на AI се показва сурово и записва 60/40

- **Тежест:** low. **Статус:** open. **PROVEN** по код.
- **Канон:** FLOW-030 L81 („при tool грешка казва, че справката не е изпълнена и данните не са променени“), L91; Р76.
- **Код:** `assets_ai_intake.py:70-71, 95`; `assets_batch_intake.py:118-119, 140`; `smr_analysis.py:1078-1095`.
- **Решение:** промяна в кода — „AI не е настроен / проверката не е изпълнена“, без запис и без суровата грешка (#90 връща 503 — важи след сливане).

## FG-585 — фирмени цени и снимки към външния модел без маскиране

- **Тежест:** low. **Статус:** open (+ Krum). **SUSPECTED**.
- **Канон:** FLOW-030 L122 („audit на prompt/tool/result без изтичане на secrets“); Р20; Р48 (3).
- **Код:** `smr_analysis.py:1012-1020, 1034`; `ai_proposal.py:254-259, 341`; снимките на активи като base64.
- **Решение:** Крум — може ли цени и оферти на фирмата да се пращат към външен модел и с какво маскиране; маскирането на ЕГН/IBAN е само на #90 (FG-517, FG-535).

## FG-586 — няма AI флаг, дневник и бюджет на main

- **Тежест:** medium. **Статус:** open (+ Krum, FG-537). **PROVEN** по код.
- **Канон:** CLAUDE.md §11 (Start 100 / Control 500 / Pro 2000 + add-on), §5 (Feature Flag/Entitlement); FLOW-030 L113.
- **Код:** няма `ai_enabled`, entitlement, дневник или проверка на бюджета; `constants.py:24-54` — free/pro/enterprise с лимит на потребители (противоречие с FLOW-050 — за прегледа на FLOW-050).
- **Решение:** промяна в кода след отговорите на FG-537 (единица действие, поведение при изчерпване, сега или с W0 Subscription).

## FG-575 — Наблюдателят още качва снимки по други пътища

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 46, `scratchpad/fg46media/probe/probe.py` → `out.json`, fgmongo2).
- **Канон:** Р83 „Наблюдател (дори член на обекта) не качва снимки — само гледа.“
- **Код (#91 `d634bf4`):** `routes/media.py:55-145` (`/media/upload` без проверка на ролята; контекст project минава за член; без контекст — всеки); `routes/technician.py:1140-1194` (photo-invoice).
- **Проба (Viewer):** `/media/upload` без контекст → 200; с контекст project като член → 200; `/technician/photo-invoice` → 201; само `/projects/{id}/photos` → 403.
- **Решение:** промяна в кода — обща проверка при качване (Viewer → 403 по фирмена или обектова роля) на всички входни точки, преди запис; забранителни тестове.

## FG-576 — използван в одобрен/финансов запис файл се оттегля без Собственика

- **Тежест:** high. **Статус:** open. **PROVEN**.
- **Канон:** Р83 „Файл в одобрен запис … се премахва само с одобрение от Собственика“; Р71 „използвана касова бележка не се изтрива“; CLAUDE.md §8.
- **Код (#91 `d634bf4`):** `routes/media.py:545-563` пропуска `offers.approval.evidence_file_id` (`offers.py:161-176` позволява несвързан файл), `warehouse_transactions.file_ids`, `finance_payments`/`subcontractor_payments.cash_receipt_file_id`, `audit_events.related_file_ids`.
- **Проба:** за всеки от тях — DELETE от качилия (Счетоводител) → 200, оттеглен, без одобрение.
- **Решение:** промяна в кода — един регистър на „държателите на файл“ (общ с `receipt_references` на #83), тест за всеки.

## FG-577 — одобрението на оттегляне не е за точна версия

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §8 „Approval винаги сочи към exact version и evidence.“
- **Код:** `routes/media.py:687-691` (заявката пази само `uses`), `:744-752` (одобрението ги преизчислява без сравнение), `:201-209` (`link_media` не гледа `retire_request_pending`).
- **Проба:** заявка с uses = [work_reports]; докато чака — плащане започва да ползва файла, `/media/link` → 200; одобрение → 200, `retired_uses` = [link, work_reports, finance_payments].
- **Решение:** промяна в кода — снимка на състоянието (контекст, файл, uses, брояч на версия) в заявката; при одобрение различно състояние → 409 `RETIRE_REQUEST_STALE`; записите, които добавят препратка, отказват при чакаща заявка.

## FG-578 — скриптът за аватари маркира свързани (не качени) файлове

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р83 „съществуващ файл не става аватар“; „пуснат само с „да“ от Крум“.
- **Код:** `backend/scripts/media_sec_01_avatar_backfill.py:79-94` (не гледа `linked_at`), `:131-134` (резултатът от `update_one` не се проверява); `approved_by` — свободен текст.
- **Проба:** стар ред с контекст profile и `linked_at` → действие „flag“.
- **Решение:** промяна в кода — пропуск при `linked_at` (`skip:linked_not_uploaded`), проверка на резултата, опция за връщане. По подразбиране скриптът наистина е проба (`:156-161`).

## FG-579 — write skew между оттегляне и нова препратка

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (по код).
- **Канон:** CLAUDE.md §2 правило 9; Р71.
- **Код:** `routes/media.py:613-627` — чете препращащите колекции, пише само `media_files`; нова препратка (напр. `_require_registered_receipt` на #83 + запис на плащане) чете `media_files` и пише другаде — при snapshot isolation и двете минават.
- **Решение:** промяна в кода — всеки, който добавя препратка, прави CAS върху реда в `media_files` (`$inc ref_version`, `status != retired`) в своята транзакция.

## FG-570 — F-82-01 спира физическото връщане при платена фактура

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** за поведението, **SUSPECTED** за канона (проход 46).
- **Канон:** Р47 ограничава само **плащането** до нетото; Р49 (6) — кредит по платена фактура става открито салдо; Р46 — складовият работник прави сторното.
- **Код (#82 `d6de7db`):** `services/…/service.py:2054, 2077-2096` (проверката е в транзакцията на сторното), `credit_note_rule.py:35-38`. Тест: `test_f82_01_an_already_paid_invoice_refuses_the_reversal`. Нищо платено / платено точно нето → сторно минава; платено над нетото → 409 `INVOICE_PAID_ABOVE_NET`.
- **Решение:** Крум — при връщане на стока по вече платена фактура: отказ (днес) или запис на връщането + открито салдо/претенция към доставчика по Р49 (6) (препоръка: второто — физическото движение не бива да чака парите).

## FG-571 — #82 и #84 смятат нетото различно

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (пробното сливане #82 × #84 има конфликти в `finance.py`, `service.py`, `ownership.py`).
- **Канон:** Р47; Р49; CLAUDE.md §2 (един източник на истината за платимата сума).
- **Код:** #82 — суровото `invoice.total` и отворените `expected_credit_notes`; #84 — `adjusted_total` (`invoice_corrections.py:489-497`, `current_open` `:909-921`).
- **Пример:** 120 общо, 72 платено, 48 кредитирано, второ сторно 48 → проверката вижда 72 ≥ 72 и минава, макар платеното > истинското нето; одобрено дебитно известие → фалшив отказ.
- **Решение:** промяна в кода при сливането — една функция за платимото нето (от #84), ползвана и от проверката на #82; тест за кредитно + дебитно известие.

## FG-572 — анулирането и падежът на #84 заобикалят Permission Service

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проба в enforce, отнети роли).
- **Канон:** FLOW-002 (права), SEC-01; CLAUDE.md §14 (permission check за всеки съществен запис).
- **Код (#84 `e8be2b3`):** `routes/finance.py:1650/1665` (анулиране), `:1736/1744` (одобрение), `:1788/1797` (отказ), `:1119/1121, 1186-1243` (падеж след издаване) — само legacy `finance_permission(user)`. `routes/invoice_corrections.py` е изцяло на Permission Service (12 записа, 5 четения, `catalog.py:236-250`).
- **Проба:** четене през corrections → 403 (контрола); Admin предлага анулиране → 200; Accountant сменя падежа → 200; quick-pay 201 и четене 200 — съществуващият пропуск на main.
- **Решение:** промяна в кода — Permission Service на тези маршрути; Крум/оркестратор — сега или с общата миграция на `finance.py`.

## FG-573 — PM-01 `run_meta` на #82 не отговаря на матрицата

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Код:** #82 `d6de7db` `docs/evidence/PM-01/run_meta.json` — 777/18648 срещу 18696 клетки (779 маршрута).
- **Решение:** промяна в доказателствата — регенериране с инструмента на PM-01.

## FG-574 — доказателствата на SEC-02 на OFF-02 не отговарят на кода

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15/§16 (без PASS без тестови доказателства).
- **Код:** OFF-02 `58d0e40` `docs/evidence/SEC-02/results.json` — 176 проби (на main), кодът — 188; `test_the_committed_evidence_satisfies_the_package` пада; файлът на `edd450d` (185) също пада (липсват 3 на PRJ-01).
- **Решение:** промяна в доказателствата — регенериране на SEC-02 harness на слетата глава.

## FG-560 — старите ДДС стойности в странни изписвания не се маскират

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (проход 46, `scratchpad/p45cp/`).
- **Канон:** Р78 („Стойността никога не се променя мълчаливо“); Р79 (търсене по ЕГН само Owner/Accountant, с AuditEvent); Р48 (3).
- **Код (#83 `ddc6e9a`):** `services/counterparty_rules.py:284-290`, `routes/clients.py:414-415`, `services/uniqueness.py:84`; `routes/projects.py:858` (`import-client-invoice`). README §22 на CP-01 твърди, че такива стойности се маскират — не е вярно за тези изписвания.
- **Решение:** Крум — старите стойности: маскиране и изключване от търсенето по 10 цифри, или почистване чрез DQ/миграция, одобрена от него (препоръка: маскиране веднага + DQ задача за почистване).

## FG-561 — ЕГН в полето ЕИК се вижда от всички

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (и на main).
- **Канон:** Р79; Р48 (3).
- **Код:** `services/counterparty_rules.py:360` (`eik` приема всякакъв брой цифри), `routes/counterparties.py:177`.
- **Проба:** 10-цифрено ЕГН в `eik` — пълно и намирано по `750` от Admin/Viewer/ТР.
- **Решение:** Крум — 10-цифрено „ЕИК“ ЕГН ли е (препоръка: да — ЕИК е 9 или 13 цифри); после валидация и маскиране.

## FG-562 — маскирана стойност се записва като ДДС номер

- **Тежест:** low. **Статус:** open. **PROVEN** (и на main).
- **Канон:** Р78; CLAUDE.md §14 (validation/DQ).
- **Код:** `routes/counterparties.py:312-318`, `services/counterparty_rules.py:498`.
- **Решение:** промяна в кода — маскирана стойност → 422 (или „без промяна“, когато съвпада с текущата маска).

## FG-563 — ключ за AI настройките може да остане „в процес“

- **Тежест:** low. **Статус:** open. **SUSPECTED** (по код).
- **Канон:** Р29 (Idempotency-Key, completed_replay).
- **Код (#90 `aaef24f`):** `routes/auth.py:731` (`complete_idempotent` извън транзакцията), `audit/idempotency.py:186` (без срок).
- **Решение:** промяна в кода — завършването на ключа в същата транзакция (или срок/възстановяване на заседнал ключ).

## FG-587 — Viewer на обекта добавя снимки през link

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 47, `scratchpad/fg47media/probe/probe.py` → `out.json`, `out2.json`).
- **Канон:** Р83 „Наблюдател (дори член на обекта) не качва снимки — само гледа.“
- **Код (#91 `1844627`):** `routes/media.py:67` (обектът се взема само при `context_type=="project"`), `:155-231` (`/media/link` без `require_uploader`).
- **Проба:** фирмен ТР с роля Viewer на обекта — качване с контекст project → 403; без контекст → 200; `/media/link` към обекта → 200; снимката се вижда в медията на обекта.
- **Решение:** промяна в кода — `require_uploader` в `link_media` с обекта на целевия контекст; в `upload_media` — обектът за всеки контекст с обект (workReport, missingSMR, site, machine, attendance); забранителни тестове.

## FG-588 — складът: claim извън транзакцията на движението

- **Тежест:** medium. **Статус:** open (+ Krum). **PROVEN** (последователността възпроизведена стъпка по стъпка).
- **Канон:** CLAUDE.md §2 правило 9; Р83; FLOW-009 (данни на движение, доказателства).
- **Код:** `routes/warehouse_canonical.py:248-249` (POST `/warehouse/movements`), `:426-427` (бракуване по обект); `material_waste.py:118`.
- **Проба:** claim → DELETE 200 → движението е записано → файлът е „retired“, но движението го сочи. Може да го направи качилият файла или Admin/Owner. Днес WRITE_OFF/REVISION/RETURN_TO_SUPPLIER отказват без `FILE_REGISTRY_ENABLED` — изложени са само `post_movement` с незадължителни `file_ids`.
- **Решение:** промяна в кода — `claim(session=…)` в транзакцията на `service.execute` (hook в складовата услуга). Крум — може ли заключената складова услуга да се отвори за това; дотогава — повторна проверка или отказ при скорошна промяна на `ref_version`.

## FG-589 — след сливане #83 приема оттеглен файл за бон

- **Тежест:** high. **Статус:** open. **PROVEN** по кода на сляното дърво (`git merge-tree` `1844627` × `ddc6e9a` → `49189be`); без сглобка за проба.
- **Канон:** Р71 „използвана касова бележка не се изтрива“; CLAUDE.md §8.
- **Код (слято):** `services/bank_account_guard.py:103` без `"retired"`; `routes/finance.py`, `routes/subcontractors.py` пишат `cash_receipt_file_id` без `claim`/`claimed_write`.
- **Решение:** промяна в кода при сливането — `"retired"` и чакаща заявка за оттегляне → 422; всяко записване на `cash_receipt_file_id` в `claimed_write`; тестове: оттеглен бон → 422, състезание плащане/оттегляне → едната страна 409.

## FG-590 — липсваща поправка на EmployeesPage и finders по вид

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Код (#91 `1844627`):** (a) `frontend/src/pages/EmployeesPage.js:134` — още контекст `"avatar"` и `/file/` (PR-ът го обявява за поправен, diff-ът не пипа frontend); (b) `services/file_holders.py:124` — `_FINDERS` само при `kinds` None или съдържащ `audit_event`.
- **Решение:** промяна в кода — (a) контекст `profile`; (b) finders независимо от `kinds` или с вид за всеки.

## FG-595 — надживял маркер блокира оттеглянето завинаги

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 48, `scratchpad/fg48media/probe/probe3.py` → `out.json`).
- **Канон:** Р83 „Файл в одобрен запис … се премахва само с одобрение от Собственика, причина и AuditEvent“ — пътят с одобрение трябва да съществува.
- **Код (#91 `cb19aeb`):** `services/file_holders.py:282-322` (`release_stale` отказва при всеки държател, вкл. движението на самия маркер); `routes/media.py:684-686` (заявката отказва при маркер), `:757` (одобрението изисква `NO_PENDING`). Вероятен спусък (SUSPECTED): `middleware/error_handler.py:14` е `BaseHTTPMiddleware` — при прекъсната връзка заявката може да се отмени, а `settle_pending` във `finally` не е защитен.
- **Проба:** редът на движението е записан, маркерът е на 2 ч → освобождаване „referenced“, остава; заявката на Admin → `MEDIA_IN_USE`; Собственикът никога не може да одобри.
- **Решение:** промяна в кода — в `release_stale`, когато единствените препратки са движения с `idempotency_key == marker.ref`, потвърждаване и махане на маркера („confirmed_late“) с AuditEvent; `settle_pending` защитен от отмяна.

## FG-596 — повторът на движение не е идемпотентен при чакаща заявка

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §14 (idempotency key); Р29.
- **Код:** `routes/warehouse_canonical.py:264, 448` — маркерът преди проверката за повтор на услугата.
- **Проба:** 1-ва заявка 200; заявка на Admin 201; повтор със същия ключ → 409 `RETIRE_REQUEST_PENDING`.
- **Решение:** промяна в кода — преди `mark_pending` да се търси завършено движение с този ключ, или `mark_pending` да пропуска файл, държан от движението със същия ключ.

## FG-597 — OCR from-media: claim извън записа

- **Тежест:** low. **Статус:** open. По код (маршрутът днес — 500).
- **Канон:** CLAUDE.md §2 правило 9 (същото като FG-579).
- **Код:** `routes/ocr_invoice.py:109-110`; `services/ocr_invoice.py:142-170`; предварително съществуващата грешка — `ocr_invoice.py:150` без `tenant`.
- **Решение:** промяна в кода — claim в `claimed_write` заедно със записа на intake или `mark_pending`/`settle_pending`, преди поправката на 500.

## FG-598 — освобождаването на маркер: без ключ и одит на отказа

- **Тежест:** low. **Статус:** open. По код.
- **Канон:** CLAUDE.md §14 (idempotency key, AuditEvent).
- **Код:** `routes/media.py:816-828`, `services/file_holders.py:296-306`.
- **Решение:** промяна в кода — задължителен ключ и `keyed_transaction`; отказът → 409 `PENDING_HOLDER_REFERENCED`; по желание — одит на отказа.

## FG-591 — нули вместо скрити редове в агрегата за роли без пари

- **Тежест:** low. **Статус:** open. **PROVEN** по код (проход 48).
- **Канон:** Р20 (няма утечка); CLAUDE.md §15 (UI с оперативна видимост) — заблуждаващи нули.
- **Код (#73 `ed6e88d4`):** `frontend/src/pages/ProjectDetailPage.js:1037-1049, 1063-1065` — `AggRowMulti` форматира липсваща стойност като „0“.
- **Решение:** промяна в кода — паричните редове и графиката се скриват, когато блоковете липсват.

## FG-592 — SEC-02 harness не доказва махането на парите от агрегата

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** CLAUDE.md §15/§16 (доказателства).
- **Код:** `seed_sec02_records` — P1 без подобект; агрегатът връща само `{"has_children": false}`. Махането е доказано само от теста на Р62 и пробата на FLOW GUARD (режим off).
- **Решение:** промяна в теста — подобект в seed-а и проверка на паричните ключове в трите режима.

## FG-603 — един Idempotency-Key може да се приложи два пъти

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** (проход 48, `scratchpad/test_probe48_sec.py`).
- **Канон:** Р29 (един ключ — един резултат); CLAUDE.md §14.
- **Код (#90 `0c04438c`):** `routes/auth.py:762-765`, `audit/idempotency.py:247-256` — завършването филтрира само по `status: STARTED`; при 0 съвпадения транзакцията не се прекъсва.
- **Проба:** A запазва ключа и спира преди транзакцията; резервацията остарява (3 мин); B със същия ключ я поема и записва; A продължава и записва → 2 събития, две 200.
- **Решение:** промяна в кода — завършване с CAS по токена на опита; 0 съвпадения → прекъсване на транзакцията. Крум/оркестратор — дълг или преди сливане (препоръка: преди сливане, малка промяна).

## FG-604 — непоследователно правило за скриване на ЕГН

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN**.
- **Канон:** Р48 (3); FLOW-030 L122.
- **Код (#90 `0c04438c`):** `services/ai_provider.py:102, 150, 154-169`.
- **Решение:** Крум — 6+4 и 2+2+2+4 скриват ли се и без контролна сума (както голите 10 цифри); IBAN с `.`/`_`/`/`; после едно правило в кода.

## FG-599 — кой издава изходящо кредитно известие

- **Тежест:** low. **Статус:** open (+ Krum). **PROVEN** за поведението, канонът е изричен (проход 49).
- **Канон:** Р49 (4) — Счетоводителят издава, Собственикът одобрява; FLOW-034 (двама различни души).
- **Код (#84 `ebcac7f9`):** `routes/invoice_corrections.py:34` — създаването е само с `finance_permission` (Owner, Admin, Accountant).
- **Проба:** Owner създава → 201; при двама Собственици единият създава, другият одобрява, без Счетоводител.
- **Решение:** промяна в кода — канонът е изричен (Р49 (4), L110): издава само Счетоводителят, одобрява само Собственикът, винаги двама различни. Канонът мълчи за tenant без Счетоводител и за Admin вместо Счетоводител — само ако е нужно, Крум.

## FG-600 — опасност при сливането #84 × #82

- **Тежест:** low. **Статус:** open. **PROVEN** (пробно сливане `71a70779`).
- **Код:** `services/…/service.py` — `_plan_receipt_reversal` губи `@staticmethod` при механично сливане; `ownership.py` — `expected_credit_notes` два пъти в ORG_KEYED.
- **Решение:** промяна при сливането — ръчно разрешаване и пълен пакет тестове на #82 (WH-REV-01 120) след него; заедно с FG-571.

## FG-485 — Р69 не е изпълнено: смяна на окончателно разпределение без Собственика

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 39, проба P1, 3 режима).
- **Канон:** Р69 „**Промяна на вече окончателно (100%) разпределение** към друг обект или фирмен разход — както Р63: предлага Счетоводителят, **одобрява Собственикът** (двама различни души), с причина, версия и AuditEvent; за неактивен обект важи Р64.“
- **Код (#84 `b0e72cf`; пътят е от #81 в main):** `routes/finance.py:1307-1395` (причина само при платена фактура, `:1373`); `routes/invoice_lines.py:766-880`.
- **Проба:** преместване на редове от prj-1 към prj-2 от Счетоводителя → 200, 0 версии, без AuditEvent за разпределението.
- **Решение:** промяна в кода — предложение + одобрение от Собственика (≠ предлагащия), причина, версия, AuditEvent и проверка по Р64; за ред без дестинация или частично разпределен Счетоводителят остава сам (Р44/Р45).

## FG-486 — Р70 / D-04: пренасочване на складов ред към обект без коригиращо изписване

- **Тежест:** medium. **Статус:** open. **PROVEN** за преместването, **SUSPECTED** за двойния разход.
- **Канон:** Р70 „…програмата прави **автоматично коригиращо складово движение** (изписване от склада към обекта по FIFO), така че материалният разход се признава само веднъж … при липса на наличност → 409.“; FLOW-009 L70-72; FLOW-043 D-04; oracle Q010 (условие 1 — фактурният ред остава Път А).
- **Код (#84 `b0e72cf`, и main):** `update_invoice_lines` не проверява `linked_to_warehouse` (проверката е само при анулиране, `routes/finance.py:1624`).
- **Проба:** номерирана входяща фактура, свързана със складово приемане — дестинацията на реда се мести към обект → 200, без коригиращо изписване, без 409.
- **Решение:** промяна в кода — до реализацията на Р70: 409 за складови редове; после — коригиращо изписване по FIFO в същата транзакция, по одобрението на Р69/Р64.

## FG-460 — дейностната част на централизираните справки изпуска ръчните редове

- **Тежест:** medium. **Статус:** open. **PROVEN** (проход 38, `scratchpad/fg38lab_probe/probe_r62_38.py`).
- **Канон:** Р62 „разходът за труд по обект е **едно число във всички справки**“.
- **Код (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`)):** `routes/centralized_reports.py:145, 160, 208` — пропуска СМР без бюджет и редове с празно СМР (по подразбиране всеки ръчен ред).
- **Проба:** сборът по дейности 775, а общата сума на същата справка 850…1270.
- **Решение:** промяна в кода — ред „без СМР / без бюджет“ в дейностната част, така че сборът = общото число.

## FG-461 — СМР на ръчния ред е свободен текст

- **Тежест:** low. **Статус:** open. **PROVEN**.
- **Канон:** Р62; FLOW-019 (труд по СМР).
- **Код (#73 LAB-01 `b395f0d`):** `routes/labor_smr.py:101`, `services/labor_cost.py:520` — СМР = `activity_name` (свободен текст), не СМР на пакета.
- **Проба:** одобрен ред вдига пакета до 650, бюджетът „Шпакловка“ остава 775.
- **Решение:** промяна в кода — СМР на ръчния ред от пакета (Master СМР), не свободен текст.

## FG-462 — справките за работни сесии връщат пари от суровите сесии

- **Тежест:** medium. **Статус:** open. **PROVEN**. Налице и на main.
- **Канон:** Р62 „… Чернови и неодобрени отчети не влизат никъде.“; FLOW-019.
- **Код (#73 LAB-01 `b395f0d`):** `routes/work_sessions.py:339-372` (`/work-sessions/summary`), `:447` (`/overtime`), `:302` (`/my-today`).
- **Проба:** 900 при всяка стъпка (каноничното число 850 → 1270).
- **Решение:** промяна в кода — сумите за пари от `project_labor_cost` или махане на парите от тези справки (часовете могат да останат с етикет).

## FG-463 — едни и същи часове още се броят два пъти

- **Тежест:** medium. **Статус:** open. **PROVEN**.
- **Канон:** FLOW-019 — забрана „едни и същи часове да се броят два пъти“; Р62.
- **Код (#73 LAB-01 `b395f0d` (+ #75 `33a3e7b`)):** проверката за дублиране е само ръчен ред срещу вече одобрен отчет (`labor_smr.py:123, 281`); одобрението на отчет не гледа `labor_entries`; няма проверка ръчен срещу ръчен.
- **Проба:** втори ръчен ред за същия работник и ден → 900 → 950; отчет, одобрен след одобрен ръчен ред за същия работник/ден → 1110 → 1270.
- **Решение:** промяна в кода — проверка в двете посоки (и ръчен срещу ръчен) при създаване и при одобрение; DQ при застъпване.

## FG-464 — `PUT /labor-terms` връща текущата, не записаната версия

- **Тежест:** low. **Статус:** open. **PROVEN** (съществуващо от `48ba662`).
- **Канон:** Р29 / CLAUDE.md §14 (idempotency — replay връща записания резултат).
- **Код (#75 LAB-02 `33a3e7b`):** `routes/labor_quantities.py:305-310` — след запис и при replay пакетът се чете наново.
- **Проба:** `test_f75_01_ten_concurrent_piece_rate_changes_get_versions_in_order` пада на ред 582 в 6 от 7 пускания на реален Mongo (на `33a3e7b` и на `48ba662`).
- **Решение:** промяна в кода — връщане на версията, записана от извикването (и при replay).

## FG-435 — официалният прогрес по СМР е ръчен субективен процент: всяка роля с M2 го задава за всеки обект, без одобрение, измерване и AuditEvent; финансова роля задава „изпълнено количество“ направо

- **Тежест:** high. **Статус:** open. **PROVEN** (проба P1, P6).
- **Канон:**
  - FLOW-027 L37: „Реалните данни идват от одобрени дневни отчети и измервания:“;
  - L47: „Субективен процент не се използва, когато има измерима единица.“;
  - L49: „Неодобрените отчети се виждат отделно, но не променят официалния труд и прогрес.“;
  - L149: „неодобрен отчет да променя официалния прогрес;“;
  - L152: „количество да се приема за изпълнено без измерване/одобрение;“;
  - L195: „одобрен labor/progress source;“, L197: „audit на промени по plan и forecast;“;
  - Р16 (Viewer и Driver не въвеждат труд; SiteManager/Technician — само за своите обекти); Р33 (първо екран за одобрено количество);
  - CLAUDE.md §14 (permission, tenant, validation, idempotency key, AuditEvent).
- **Код (main `44e8d97`):**
  - `routes/budget_progress.py:145-185` `POST /progress-updates`: само `require_m2` (модулът е включен — всяка роля), без проверка за членство в обекта, без статус на одобрение, без Idempotency-Key, без AuditEvent; `date` идва от клиента;
  - `:178-183` веднага презаписва `execution_packages.progress_percent` (`progress_source: "manual"`);
  - `routes/revenue_expense.py:394-420` `PUT /execution-packages/{id}`: под `require_finance_read` позволява `progress_percent`, `qty_executed`, `used_hours` и `planned_hours`, без AuditEvent;
  - потребители на ръчното число: `budget_progress.py:455-500` (претеглен прогрес), `:318-370` (предупреждения), `services/alarm_engine.py:77-84` (аларма по прогрес), `routes/activity_budgets.py:605-612` (earned value = BAC × среден прогрес);
  - на main няма друг writer на `progress_percent` и `qty_executed` (grep). Одобрен отчет и измерване не стигат до прогреса;
  - UI: `frontend/src/pages/ProjectProgressPage.js:73-81` (ръчно поле за процент), маршрутът е `AdminRoute` (`App.js:267`), но API-то не проверява роля.
- **Проба:** пакет `pkg-B1` в обект B, `m2`, `qty_executed 0`. В B няма членове и няма одобрени отчети.
  - P1: Viewer `POST /progress-updates {progress_percent_actual: 85, date: "2026-01-01"}` → 201, официален прогрес 85. Същата заявка втори път → 201 (два реда). Technician → 201 със 100. Резултат: официален прогрес 100.0, `qty_executed 0`, `progress_updates` = 3 реда, ред с дата 2026-01-01 (назад във времето). AuditEvent Δ0, `audit_logs` Δ0. Owner вижда `weighted_progress_percent 100.0`;
  - P6: Accountant `PUT /execution-packages/pkg-B1 {progress_percent: 40, qty_executed: 100, planned_hours: 5}` → 200, всичко е записано, ред в историята на прогреса няма, AuditEvent Δ0. SiteManager на същия PUT → 403.
- **Решение:** промяна в кода:
  - официалният прогрес се изчислява само от одобрено измерено количество / одобрени отчети (Р33, Р62): одобрено количество ÷ количество по КСС;
  - ръчният процент е разрешен само за СМР без измерима единица. И тогава е чернова → одобрение от човек с право. Неодобреният се вижда отделно и не влиза в summary, аларми и earned value;
  - въвеждането — само SiteManager/Technician, членове на обекта (Р16), и финансовите роли;
  - Idempotency-Key, AuditEvent преди/след, корекция с нов запис, а не презапис;
  - `progress_percent`, `qty_executed`, `used_hours` и `planned_hours` да излязат от позволените полета на `PUT /execution-packages`;
  - тестове: positive, forbidden (Viewer/Driver/не-член → 403), неодобрено ≠ официално.

## FG-436 — прогресът на всеки обект се чете от роли, които не са членове на обекта (Viewer), заедно с имената на въвелите

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P2).
- **Канон:**
  - Р20: „Технически ръководител … вижда бюджета на обекта … — само за своите обекти. Наблюдател, техник, шофьор, складов работник — без пари“;
  - Р30 („свой обект“ = обект с роля ръководител в екипа);
  - FLOW-002 (достъп по обект);
  - CLAUDE.md §3 (denied-by-default), §14 (permission check).
- **Код (main `44e8d97`):**
  - `routes/budget_progress.py:188-203` (`GET /progress-updates`), `:206-217` (`/latest`), `:220-242` (`/history` с `updated_by_name`), `:245-312` (`/progress-comparison`), `:318-412` (`/progress-warnings`), `:455-523` (`/project-progress-summary`): само `require_m2` + `strip_money_for_non_finance`, без `can_access_project`;
  - паричните полета се махат, но процентите „разход X% от бюджет“ остават в текста на предупрежденията (`:376-383`).
- **Проба:** P2 — Viewer, без ред в `project_team` за B, получава 200 на всичките пет пътя за B. Technician получава историята с имената `["viewer T", "viewer T", "technician T"]`.
- **Решение:** промяна в кода:
  - `can_access_project` (членство за не-финансовите роли; Р30 за ръководителя) преди всяко четене по `project_id`/`pkg_id`;
  - `/progress-updates` без `project_id` да връща само обектите на потребителя;
  - тест forbidden за не-член.

## FG-437 — обектът има една крайна дата, без baseline / текущ план / прогноза / договорен срок; техническият ръководител я мести без причина, анекс и версия; фазите се променят без одит и се трият окончателно

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P3).
- **Канон:**
  - FLOW-027 L31: „За всяко СМР/Work Package се пазят отделно **baseline** (одобрена версия), **текущ план** и **прогноза**. Договорният срок остава отделна дата (FLOW-005).“;
  - L32: „Промяна на baseline създава нова версия с причина и одобрение.“;
  - L147: „ръчно преместване на договорния край без основание/анекс;“;
  - L148: „прогнозна дата да се показва като договорна;“;
  - L154: „изоставането да се скрива чрез промяна на базовия план;“;
  - L193, L197, L199 (baseline/versioning, audit, отделни дати);
  - CLAUDE.md §2.9 (без hard delete), §14 (AuditEvent, correction path).
- **Код (main `44e8d97`):**
  - `routes/projects.py:81-87, 261-319` `PUT /projects/{id}`: `start_date`, `end_date` и `planned_days` се презаписват при `can_manage_project` (Owner/Admin или SiteManager член). Няма причина, анекс, версия и одобрение. Пише се само legacy `log_audit` (`:318`);
  - таблото показва тази единствена дата като „Край (план)“ (`projects.py:1142-1175`, `frontend/src/pages/ProjectDetailPage.js:357`). Няма отделен договорен срок и няма прогноза;
  - `:562-574` `PUT /phases/{id}` — без никакъв одит; `:576-587` `DELETE /phases/{id}` — `delete_one`, без одит;
  - `budget_freezes` (`budget_progress.py:39-116`) е версиониран, но е паричен snapshot без дати, причина и одобрение. Не е baseline на графика.
- **Проба:** P3 — обект A с край 2026-12-31. SiteManager (член) мести края на 2027-03-31, после на 2027-06-30 (`planned_days 272`): 200, 200. Таблото показва 2027-06-30. Полета за причина няма. Старата дата не е запазена в нито една колекция извън `audit_logs`. AuditEvent Δ0, `audit_logs` +2. Фаза: създаване 201, промяна на `planned_end` 200 (`audit_logs` +1 е от създаването, промяната не оставя нищо), изтриване 200 → редът го няма, одит Δ0.
- **Решение:** промяна в кода (Wave 2.1 / FLOW-005):
  - отделни полета: договорен срок (само чрез договор/анекс), baseline (версия с причина + Approval), текущ план и прогноза (изчислена);
  - докато това няма: `end_date` на активен обект се мени само от Owner/Admin с причина и canonical AuditEvent преди/след;
  - фазите — архив вместо `delete_one`, AuditEvent при промяна.

## FG-438 — два различни плана за човекочасове на едно и също СМР (55.6 ч срещу 40 ч)

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P4).
- **Канон:**
  - FLOW-027 L33: „Има един график за СМР — без втори регистър за задачи.“;
  - L86: „план човекодни срещу реални човекодни;“;
  - L159: „втори регистър за задачи, материали, подизпълнители или плащания заради графика.“;
  - CLAUDE.md §2.12, §16 (един source of truth).
- **Код (main `44e8d97`):**
  - `routes/labor_smr.py:332, 347-360`: `execution_packages.planned_hours` = количество × `labor_hours_per_unit`, иначе трудов бюджет / 18 €/ч (`default_rate = 18`);
  - `services/budget_formula.py:13-31` + `services/expected_actual.py:34-53`: `activity_budgets` → трудов бюджет / коефициент / 200 €/ден × 8 (= бюджет / 25 €/ч);
  - самият код го признава (`budget_progress.py:68-70`): „FUTURE TODO: align planned_hours with budget_formula.py … separate model“;
  - `/progress-comparison` и `/progress-warnings` четат първия план, `/projects/{id}/expected-actual` — втория.
- **Проба:** P4 — едно СМР „Мазилка“, трудов бюджет 1000 в пакета и в `activity_budgets`. `POST /execution-packages/recompute-labor/B` → 200, `planned_hours 55.6` (`budget_estimate`), `/progress-comparison` `raw.planned_hours 55.6`. `/projects/B/expected-actual` → `total_planned_hours 40.0`.
- **Решение:** промяна в кода — един източник на планираните човекочасове по СМР. Норма от офертния ред (`labor_hours_per_unit`) или една обща формула с една ставка от настройките на tenant-а. Всички справки го четат. Заедно с Р62 (един трудов разход) реалните човекочасове също да идват от един канонически източник. Ако Крум иска резервна ставка при липса на норма — Крум да реши стойността (18 €/ч или 200 €/ден).

## FG-439 — 28 часа на ден по две СМР за един работник се приемат и одобряват само с предупреждение

- **Тежест:** medium. **Статус:** open. **PROVEN** (проба P5).
- **Канон:**
  - FLOW-027 L151: „човекочасове да се броят по две СМР едновременно;“;
  - L39-40 (реални хора, часове и човекодни от одобрени отчети);
  - CLAUDE.md §14 (validation/DQ преди consequential write).
- **Код (main `44e8d97`):**
  - `routes/daily_reports.py:58-69` `validate_report` проверява само отрицателни часове;
  - `:72-167` `check_employee_hours` дава предупреждение над 8/12 ч и при повече обекти;
  - `:236-238` „Hours check — add warnings to response (non-blocking)“;
  - `approve_daily_report` (`:498-522`) не блокира (`block_overtime_without_override=False`).
- **Проба:** P5 — Owner създава отчет за `technician` на 2026-10-20 с два реда по едно СМР: 14 ч + 14 ч. Резултат: 201, `total_hours 28.0`, предупреждение „общо 28.0 часа за деня“. После submit 200, approve 200, `APPROVED` с 28 ч. AuditEvent Δ0. Бележка за FLOW-014: одобрението на отчет с `day_entries` създаде 0 `work_sessions` (SUSPECTED, не е изследвано).
- **Решение:** промяна в кода — DQ правило с таван на часовете на човек за ден по всички СМР и обекти. Над тавана: блокиране или изрично одобрение с причина и AuditEvent. Таванът е бизнес стойност: Крум да реши дали е 12 ч, 16 ч или друго.

## FG-440 — графикът по FLOW-027 не е реализиран: няма зависимости и критичен път, готовност, най-късна безопасна дата, напомняния, delay events и timeline

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (четене; grep: 0).
- **Канон:**
  - FLOW-027 L11: „FLOW-027 е **централният оперативен гръбнак** на обекта“;
  - L63: „Резултатът е `Готово`, `В риск`, `Блокирано` или `Не е предстоящо` … Неизвестно условие никога не се показва като изпълнено.“;
  - L65, L69, L113, L115, L191-205;
  - Waves L269-278 (Wave 2.1 planned; predecessors W0-03/06/07, read-only W0-05; „Докато те липсват, всеки W2.1 PR остава feature-off“);
  - Gate Matrix L47; Р2 (Pilot BEG); D-10.
- **Код (main `44e8d97`):**
  - няма модел или route за график, dependency, critical path, readiness, latest-safe-date, delay event или удължаване (grep в `backend/app`: 0, освен `budget_formula.planned_man_days` и `subcontractor_performance` delayed);
  - `project_phases` (`projects.py:111-124`) има само имена и дати, без връзка към СМР;
  - реалното плащане като предпоставка (L60) не се чете отникъде;
  - PR #11 не е merge-нат.
- **Проба:** няма (липсваща функция).
- **Решение:** промяна в кода по Wave 2.1 / U1 срез 4.2 (PR #11 като вход). Ред:
  1. canonical schedule по СМР/WorkPackage с baseline, текущ план и прогноза (FG-437);
  2. official progress от одобрено количество (FG-435);
  3. readiness като изчислена проекция с източник за всяко условие и „неизвестно ≠ готово“;
  4. latest-safe-date;
  5. сигнали към FLOW-026/045 (след FG-211/FG-208);
  6. delay events с изчисление на календарния ефект при припокриване.

  Feature-off до predecessors. Крум да реши дали срез 4.2 тръгва като Pilot BEG (Р2) преди W0-06/07.

## FG-441 — таблото на обекта: „Изминало“ и „Оставащи“ дни винаги са празни (имената на полетата не съвпадат)

- **Тежест:** low. **Статус:** open. **SUSPECTED** (четене на API и UI; UI не е рендериран).
- **Канон:**
  - FLOW-027 L121: „изминало договорно време;“;
  - L161-174 (какво трябва да вижда Крум).
- **Код (main `44e8d97`):** `routes/projects.py:1167-1175` връща `days_elapsed` / `days_remaining`. `frontend/src/pages/ProjectDetailPage.js:359` чете `progress.elapsed_days` / `progress.remaining_days`, които не съществуват → „Изминало: дни“, „Оставащи: дни“.
- **Проба:** P3 — `GET /projects/A/dashboard` → 200, картата за прогреса идва с `end_date 2027-06-30`. Ключовете са по кода (`days_elapsed`).
- **Решение:** промяна в кода — UI да чете `days_elapsed` / `days_remaining`. Отделно: етикетът „Край (план)“ да стане договорен / текущ / прогнозен след FG-437.

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

### Проход 6 — 07.11.2026 02:50 UTC (периодичен)

Нови SHA:

- main без промяна (`35ae10b`);
- #55 `518aab4` (C26h);
- #71 `71f9bbe` (SEC-02-E + merge #69 @ `7300864`);
- #72 `8ac194a` (FG-57);
- #73 `c422cbd` (LAB-01-B/C);
- пакети `bfa87f2` (5C-C26 добавки G/H).

Проверки:

- **#72:** FG-37 пробата **без** предварителни индекси → 20/20, true (FG-57 ✅); с индекси → 40/40, true.
- **#55:** C26h 21/21; c1x/c2x 659 passed. Проби ×3 режима: FG-59/60/61 ✅; регресия 150 / 100 / 40 / 7 / 50, FG-38, FG-56 ✅.
- **#71:** 56 passed. FG-63/29/47 ✅; Р29 → 428.
- **#73:** 25 passed. FG-64 ✅; регресия: акорд 600, месечна заплата 300 само по одобрени часове, DOWNTIME 25 отделно, без ставка → 0 + MISSING_RATE.
- **FG-28:** в off 0 audit реда при отказ. В enforce 2 отказа → 1 ред `permission.denied` (един път вероятно не се одитира, не е изолиран).
- **Бавен преглед на main:** FLOW-008 → FG-67, FG-68.

### Проход 7 — 07.11.2026 04:50 UTC (периодичен)

Нови SHA:

- main без промяна (`35ae10b`);
- #55 `f0d86ab` (C26i);
- #71 `dee0610` (SEC-02-F);
- #73 `00324ab` (LAB-01-D, D-C01);
- пакети `ac74fe9` (5C-C26 добавка I).

Проверки (реален Mongo):

- **#55:** c26i 15 passed. FG-70 и FG-69 ✅ ×3 режима; регресия 150 / 100 / 40 / 7 / 50; FG-59/60/61 без промяна.
- **#71:** 18 passed, 3 skipped. FG-74 ✅ (off); FG-75 ✅ ×3.
- **#73:** 30 passed, 10 skipped. FG-72 ✅; FG-73 частично; FG-66 частично; FG-76 ✅.
  - FG-65: няма writer — потвърдено отново.
- **Бавен преглед на main:** FLOW-024 → FG-77.

### Проход 8 — 07.11.2026 06:50 UTC (периодичен)

Нови SHA:

- main без промяна (`35ae10b`);
- #73 `c4ddd33` (LAB-01-E);
- нов клон `claude/oh-01-overhead` `09409f0` (OH-01);
- пакети `ab74e23` (OH-01 — сверен с FLOW-024, без разминаване).

Проверки (реален Mongo):

- **#73:** 248 passed. FG-78/79 ✅; FG-80 частично; регресия FG-72/73 ✅; FG-65 без writer.
- **OH-01:** 57 passed. Проверено ×3 режима:
  - използван разход/категория/актив → 409;
  - неизползван → archived + AuditEvent;
  - 3 преразпределения → версии 1–3 с `superseded_by`;
  - 6 едновременни → 1 × 200 и 5 × 409;
  - не-финансови роли → 403;
  - без ключ → 428.
- **Бавен преглед на main:** FLOW-020 → FG-83.

### Проход 9 — 07.11.2026 08:50 UTC (периодичен)

Нови SHA:

- main `0f870c3` (merge AUTH-01/02 #56 = `3234446`, проверен в проход 2);
- #55 `8025871` (C26j);
- #72 `34ac9f4` (merge main, без нов код);
- #73 `ca81286` (LAB-01 F/G/H/I);
- OH-01 `6c5c5cf`;
- нов клон LAB-02 `0c85678`;
- пакети `a4b5782` (Р33–Р36, LAB-02).

Проверки:

- **Р33–Р36** — сверени. Р36 следва FLOW-028 само ако поправката на платено минава като корекция → FG-91, FG-93.
- **#55:** c26j 55 passed. Р34/Р35 ×3 режима; регресия 150 / 100 / 40 / 7 / 50; FG-59 и FG-70 остават затворени.
- **OH-01:** 102 passed.
- **#73:** 83 + 30 passed. Пробен merge с #72 → 84 passed; LAB-02 → 99 passed; #72 + #73 + LAB-02 → 105 passed.
- **Бавен преглед на main:** FLOW-021 → FG-90.

### Проход 10 — 07.11.2026 10:50 UTC (периодичен)

Нови SHA:

- main без промяна (`0f870c3`);
- #55 `4ed6077`;
- #69 `ccab244`;
- #70 `0713a81`;
- #71 `c0247e8`;
- #72 `90a582b`;
- #73 `3107ba0`;
- OH-01 `6a4ac5b`;
- LAB-02 `ba08ab5`;
- пакети `e911cc6` (Р37, Р38 — сверени с FLOW, без разминаване).

Проверки (реален Mongo):

- **#69 FG-90:** таван 100 → 150 → 409; 6 паралелни → 3 × 201, 3 × 409; ключ replay.
- **#70:** 6 паралелни сторна → 1; прекъснато сторно на трансфер → двата крака [1, 1]; FG-34/45 регресия ✅.
- **#72:** 20 опита × 6 паралелни `begin_idempotent` → 1 победител, вкл. FAILED retake; FG-37 20/20.
- **OH-01:** Р38 431 „преизчислява се“ → 531; FG-98 ✅.
- **#55:** 76 passed (c26/c26j/c26k); Р37 ×3; C26k свързана директна доставка → веднъж.
- **#73:** 90 passed. **LAB-02:** 128 passed; на реален Mongo 47 passed.
- Пробен merge LAB-02 + #72 `90a582b` → 1 × 200 на ключ.
- **Бавен преглед на main:** FLOW-005 → не е започнат в кода (Wave 1); без ново FG.

**Бележка:** в пробния контейнер остана база `test_database` от conftest на клона LAB-02. Контейнерът е локален и временен, пресъздава се на всеки проход; production не е засегнат.

### Проход 11 — 07.11.2026 12:50 UTC (периодичен)

Нови SHA:

- main без промяна (`0f870c3`);
- #55 `43477d8`;
- #69 `3fb55f2`;
- #70 `4b745f1`;
- #71 `5af530e`;
- #72 `cb5d061`;
- #73 `4da2ee6`;
- OH-01 `45178ac`;
- LAB-02 `ef16a16`;
- нов клон SUB-ADV-01 `f42da33`;
- пакети `b0dc717` (Р39–Р41, SUB-ADV-01).

Проверки:

- **Р39/Р40** — сверени с FLOW-021/006, без разминаване. **Р41** → FG-107 (да се запише във FLOW-043).
- **Тестове на реален Mongo:**
  - SUB-ADV 14 passed;
  - #69 6 passed;
  - OH-01 213 passed;
  - #70 108 passed;
  - #72 34 passed;
  - #55 74 + 92 passed;
  - #73 17 passed;
  - LAB-02 41 passed.
- **Проби:**
  - FG-89, FG-99, FG-101 ✅;
  - Р39 роли и изрично приспадане ✅;
  - регресия 150 / 100 / 40 / 7 / 50 и 120 × 5 = 600 ✅;
  - FG-37 20/20.
- **Бавен преглед на main:** FLOW-004 → FG-106.

### Проход 12 — 07.11.2026 14:50 UTC (периодичен)

Нови SHA:

- main без промяна (`0f870c3`);
- #55 `d98cead`;
- #71 `e90aa5f`;
- #72 `04e0a1b`;
- #73 `41a43b5`;
- OH-01 `997abdc`;
- LAB-02 `f0a0757`;
- SUB-ADV-01 `17aa55d`;
- нов клон ACT-01 `c6c7f1c`;
- пакети `796efef` (D-17 за Р41; ACT-01 + добавка A — сверен с FLOW-003/004/005, без разминаване).

Проверки:

- **#55:** 213 passed; FG-108/109 PROVEN.
- **ACT-01:** 80 passed на реален Mongo (префикс fgact_); проби ×3 режима.
- **LAB:** FG-110/112 PROVEN.
- **SUB-ADV:** Р39/Р40; FG-114/115 PROVEN.
- **OH-01:** Р38 етикет навсякъде.
- **Бавен преглед на main:** FLOW-007 → FG-118.

### Проход 13 — 07.11.2026 16:50 UTC (периодичен)

Нови SHA:

- main `d226c49` (merge #72 W0-04-C01 и #70 PAY-01 — проверени в предишните проходи);
- #55 `94c0571`;
- #69 `da47777` (merge main);
- #71 `83f1bf3`;
- #73 `0c0f5f8`;
- OH-01 `31a9478`;
- LAB-02 `c68c942`;
- SUB-ADV-01 `542fa2c`;
- ACT-01 `8188689`;
- пакети `940bd49` (Р42 — затваря FG-81).

Проверки (реален Mongo):

- **main:** FG-37 20/20; PAY-01 сторно + AuditEvent; FG-45 409; Р29 → 428 (8 POST); 359 passed.
- **ACT-01:** 101 passed на клона и на пробен merge с main.
  - FG-119…FG-123 PROVEN.
  - **Условие за merge:** ACT-01 трябва да се слее след #72 (вече в main), за да има уникалния индекс на веригата.
- **#55:** c26* 494 passed.
- **OH-01:** 117 passed.
- **SUB-ADV-01:** 7 passed.
- **#71:** 29 passed.
- **#69 след merge с main:** 344 passed; guard-овете и сторното се запазват.
- **LAB регресия:** 600; FG-99; FG-110.
- **Бавен преглед на main:** FLOW-003 → FG-129, FG-130.
- **Бележка:** пробният Mongo контейнер спря около 16:59 и беше пуснат отново. Една грешка в c26* съвпада с прекъсването и не е потвърдена.

### Проход 14 — 07.11.2026 18:50 UTC (периодичен)

Нови SHA:

- main без промяна (`d226c49`);
- #55 `cba5306`;
- #71 `bfeda82`;
- ACT-01 `dd11e8e` (merge main);
- нов клон OFF-01 `bfc41f5`;
- пакети `1a15df3` (OFF-01 + добавка A — сверен с FLOW-003/005/002, без разминаване; ACT-01 добавка C).

Проверки (реален Mongo):

- **OFF-01:** 210 passed ×3 режима.
- **ACT-01:** 110 passed.
- **#55:** 185 passed; заглавията винаги = сумата на редовете (15 рунда × 6 паралелни).
- **#71:** 25 passed.
- **Бавен преглед на main:** FLOW-013 → FG-134.

### Проход 15 — 07.11.2026 20:50 UTC (периодичен)

Нови SHA:

- main без промяна (`d226c49`);
- #55 `ed48595` (Addendum N + merge main);
- #71 `eb91eec`;
- ACT-01 `2cc1147`;
- OFF-01 `2379d07`;
- пакети `d420096` (Р43 — затваря въпроса за разбивката по FG-138).

Проверки (реален Mongo):

- **OFF-01:** 84 passed; FG-135…138 PROVEN ×3 режима; OFF79-05 ×60 без 500.
- **ACT-01:** 113 passed; FG-142.
- **#55:** 681 passed; PAY-01 на реален Mongo 630 passed; FG-140 PROVEN.
- **#71:** 30 passed.
- **Бавен преглед на main:** FLOW-014 → FG-143.
- **Бележка:** Docker демонът беше спрял; пуснат отново, контейнерът е пресъздаден.

### Проход 16 — 07.11.2026 22:50 UTC (периодичен)

Нови SHA:

- main `2ec61f3` (#78 W0-04-C02 → FG-126 ✅);
- #71 `b1ab349`;
- SUB-ADV-01 `c4de7c9` (merge main + F-76-01/02);
- OFF-01 `acc472f`.

Проверки (реален Mongo):

- **OFF-01:** 231 passed; FG-144 — 120 надпревари × 3 режима; всички записи на статус в `offers.py` вече са условни (`:519,615,675,731,821,862,1608`; `offer_versions.py:268`).
- **#71:** 30 passed.
- **SUB-ADV-01:** 8 passed. F-76-01: аванс + платено + ново ≤ договора (`:683-692`). F-76-02: един audit ред при повторение.
- **Бавен преглед на main:** FLOW-016 → не е започнат (W0-06); покрито от FG-143/145.

### Проход 17 — 08.11.2026 00:50 UTC (периодичен)

Нови SHA:

- #69 `25ffd9b` (SEC-01-C03 G: `log_audit(entry_id=…)` — един audit ред на операция след срив);
- SUB-ADV-01 `b313933` (F-76-02, същото за обикновеното плащане);
- OFF-01 `653a1a5` (FG-149);
- main, #55, #71, #73, OH-01, LAB-02, ACT-01, пакети — без промяна. `claude/audit-log` и `claude/schedule` са само документи на други сесии — не са код.

Проверки (MongoDB 7 replica set, локален контейнер):

- **OFF-01 `653a1a5`:** `test_off_01_offer_version_accept.py` → 87 passed. **FG-149 resolved.**
- **SUB-ADV-01 `b313933`:** `test_sub_adv_01_subcontractor_advance.py` → 8 passed. Одит редът е идемпотентен, но остава legacy `log_audit` → **FG-147 остава open**.
- **#69 `25ffd9b`:** `test_sec_01_c03_payment_amount_idempotency.py` → 6 passed. `utils/audit.py`: при `entry_id` редът е с `_id = entry_id`, `DuplicateKeyError` по `_id` се поглъща — не противоречи на канона (legacy слой; canonical AuditEvent е отделно).
- **Бавен преглед FLOW-009 на main** (`COVERAGE.md`): main няма каноничен складов регистър (два legacy — `warehouse_transactions` и `warehouse_batches`). Нови **FG-150..FG-164** (SUSPECTED). Най-тежки: FG-150 (изписването е 0 в P&L — ключът `unit_cost` никога не се пише; проверено, че `procurement.py` е единственият writer), FG-151..FG-154. Повечето се затварят от #55; FG-150 и FG-154 са само в четенето на справките и могат да се оправят на main и без #55. Още на main: FG-17, FG-29, FG-30, FG-35, FG-83, FG-143, FG-145, FG-146.

### Проход 18 — 08.11.2026 02:50 UTC (периодичен)

- Няма нови SHA (main, всички отворени PR и пакетите — както в проход 17). #55 още не е слят → чакащият повторен преглед на FLOW-009 остава.
- **Бавен преглед FLOW-010 на main** (`COVERAGE.md`): контрагенти, контакти, IBAN, ApprovalReceipt, финансов профил. Нови **FG-165..FG-175** (SUSPECTED). Най-тежки: FG-165 (няма проверка на IBAN), FG-166 (дубли по ЕИК), FG-167 (hard delete на контрагент с история — проверено четене на `counterparties.py:265-278`), FG-173 (клиентско одобрение без ApprovalReceipt). Още на main: FG-1 (`labor_smr.py:32-33`), FG-30, FG-133/FG-141, FG-129/FG-138 (OFF-01 не е слят).

### Проход 19 — 08.11.2026 04:50 UTC (периодичен)

- Няма нови SHA. #55 още не е слят → повторният преглед на FLOW-009 чака.
- **Бавен преглед FLOW-011 на main** (`COVERAGE.md`): инструменти/машини/QR/активи. Нови **FG-176..FG-186** (SUSPECTED). Най-тежки: FG-176 (handover сменя отговорността преди ACCEPTED), FG-177 (`take` със `to_id` = ACCEPTED custody на друг само със сканиране — против CLAUDE.md §16; проверено четене на `assets_units.py:270-275` и `assets_custody.py:74-91`), FG-178, FG-180, FG-182, FG-183. Р1..Р43 не съдържат решение за активи; няма отворен PR за FLOW-011.

### Проход 20 — 08.11.2026 06:50 UTC (периодичен)

- Няма нови SHA. #55 още не е слят → повторният преглед на FLOW-009 чака.
- **Бавен преглед FLOW-012 на main** (`COVERAGE.md`): логистиката на практика не е започната (няма курсове, стопове, Loading List, автомобили, приемане на доставка; `deliveries` без writer). Отбелязано като „липсва“, не като отделни находки. Нови **FG-187..FG-189** (SUSPECTED): FG-187 (общ PUT на заявка — проверено четене на `procurement.py:166-177`), FG-188, FG-189. Плащания извън FLOW-006 в логистиката няма.

### Проход 20b — 08.11.2026 07:20 UTC (по заявка на оркестратора: #55 е слят)

- main `2ec61f3` → `cd03324` (merge #55). Дървото на merge-а съвпада с автоматичния merge на проверения #55 `ed48595` и `2ec61f3` (`git merge-tree` = `0b0b134`) — няма непрегледана промяна.
- Legacy складовите писатели са спрени безусловно с 410 (`legacy_inventory.py:122-146`, без флаг). Не са зад защитата: `/material-waste`, `create-sub-project`, `PUT /warehouses`, `PUT /supplier-invoices`.
- FG-150..FG-164 на новия main (само четене):
  - **resolved:** FG-151, FG-152, FG-156, FG-158;
  - **partial:** FG-150, FG-153 (на изчакване), FG-154, FG-157, FG-159, FG-161, FG-162, FG-163, FG-164;
  - **open:** FG-155 (решение на Крум), FG-160 (по-тежко).
- Нови от самия merge (SUSPECTED): **FG-190**, **FG-191**, **FG-192** (high — Master проверката е изключена по подразбиране; проверено, че `WAREHOUSE_STRICT_MASTER_IDENTITY` не се задава никъде в репото), **FG-193** (high — `create-sub-project` пренаписва каноничните редове; проверено четене на `projects.py:1566-1583` и `legacy_inventory.py:115-119`).

### Проход 21 — 08.11.2026 08:50 UTC (периодичен)

Нови SHA:
- #69 `b2b3ae0` (суми в цели центове);
- OFF-01 #79 `8dc3c45` (F-79-01);
- LAB-01 `ef8661c` (merge на main `2ec61f3`);
- LAB-02 `388b81c` (F-75-01);
- пакети `2a52fc4` (Р44, WH-FIX-01, WH-REV-01), после `27b497d` (Р45);
- нови клонове: WH-FIX-01 #81 `f674eed` → `5c0faa5` → `dae15da` и WH-REV-01 `ed8f9e7`.

Проверки (MongoDB 7 replica set; контейнерът падна два пъти по време на прохода):
- **#69, OFF-01, LAB-01, LAB-02:** прегледан е диффът. Нищо не противоречи на канона (Р43, Р41, FLOW-019/028). Тестовете на OFF-01 и LAB-02 не са пуснати, защото Mongo падна.
- **WH-REV-01 `ed8f9e7`:** 83 passed (тестове на PR) и 48 passed (проби: паралелни сторна, сторно || allocate, платена фактура). Ядрото отговаря на канона: append-only, без hard delete, 409 при изписана партида, Idempotency-Key, AuditEvent в транзакция, плащанията не се пипат. Нови: **FG-194** (PROVEN), **FG-195** (PROVEN), **FG-196**, **FG-197**. Approval за сторно липсва — разширение на FG-22 (W0-07).
- **Пакети:** **FG-198** — WH-FIX-01 т.3 срещу Р32.
- **WH-FIX-01 #81 `5c0faa5`:** 100 passed (тестове на PR). Пробата FLOW GUARD мина 10/10 и показа FG-199/FG-200. Пълният складов suite не завърши заради Mongo: до ~35% е зелен; `test_warehouse_canonical_c13_mongo.py` дава 4 failed и на main `cd03324`, т.е. не е регресия на #81.
  - resolved на #81 (още не е в main): FG-150, FG-159, FG-161, FG-164, FG-192; с уговорка FG-190 (→ FG-202) и FG-193 (→ FG-203);
  - partial: FG-154, FG-155, FG-157, FG-163, FG-191.
  - **Нови:**
    - **FG-199 blocker:** header fallback, против Р45, PROVEN; още е на `dae15da`;
    - **FG-200 high:** вградени редове от UI заобикалят Р44, PROVEN;
    - **FG-201**, **FG-202**, **FG-203**.
- **Оракул:** Q001 → Р44 (точки 2, 4, 9). Q002 е затворен с Р45.
- Бавен преглед: FLOW-015 се отлага за следващия проход (проходът беше зает с #81 и WH-REV-01).

### Проход 21b — 08.11.2026 09:50 UTC (решения на Крум)

- **Р46** (FG-194) и **Р47** (FG-196) са проверени дословно в `RECOVERY_EXECUTION_PROPOSAL` L107–L108 @ `28b5ab6` и се добавят към проверката на #81 и #82 (WH-REV-01).
- **FG-198** е resolved по Р32 (L83); пакетът ще се поправи.
- **FG-200** ще се реши по Р45 в #81.

### Проход 22 — 08.11.2026 10:50 UTC (периодичен)

Нови SHA:
- #81 `d2d0ba2` → `c86d161`;
- #82 WH-REV-01 `e9633aa` → `1622f62`;
- #69 `faa3da0`: merge на main `cd03324` с ръчно разрешени конфликти — разрешението е обединение (правата за пари + складовите права от #55), без промяна на правило;
- пакети `28b5ab6` (Р46, Р47).

Проверки на реален Mongo (контейнерът падаше от „Too many open files“; вече е с `--ulimit nofile=20000`):
- **#81 `c86d161`:**
  - тестове на PR: 215 passed;
  - широк suite: 1747 passed, 4 failed (`c13_mongo`, същите и на main), 81 не са пуснати (искат сървър на :8001);
  - **FG-199 blocker resolved**; resolved: FG-200, FG-202, FG-203, FG-195 (на #81); FG-201 partial;
  - Р45 (1)–(4) PASS.
- **#82 `1622f62`:** 152 passed. Resolved: FG-194 (Р46), FG-195 (на #82), FG-197; FG-196 partial (Р47 — няма регистриране на кредитно известие).
- **Пробно сливане #81 + #82:** конфликти; нови **FG-213** (PROVEN), **FG-214**, **FG-215** (PROVEN, решение на Крум), **FG-216**.
- **Бавен преглед FLOW-015 на main:** FG-204..FG-212.
- **Оракул:** Q003 (контрагенти) и Q004 (кредитни/дебитни известия) — отговорени; чакат решения на Крум.

### Проход 22b — 08.11.2026 11:50 UTC (отговор на оркестратора)

- **FG-215:** проба P6/P10 повторена на #81 `2d60acd` (= `c86d161` + само evidence). Издадената фактура с проект в заглавието пак губи прихода (`total_income` 0) и отваря DQ, т.е. заявеното „издадените запазват поведението на main“ не е изпълнено в кода. Остава open като код, без решение на Крум.
- **FG-201:** записан като дълг. **FG-213, FG-214, FG-216:** записан е редът на сливане. **FG-196:** чака INV-CN-01 (Р49).

### Проход 23 — 08.11.2026 12:50 UTC (периодичен)

Нови SHA:
- main `4bca18a` (merge #69 — дървото съвпада с проверения `faa3da0`);
- #71 SEC-02 `eff56bf` (merge на main, конфликтите разрешени като обединение);
- #81 `d2fe80b`;
- нов #83 CP-01 `5987f7f` → `ea51030` (само evidence);
- нов #84 INV-CN-01 `7446d85`;
- пакети `344c197` (Р48, Р49).

Проверки (реален Mongo):
- **#81 `d2fe80b`:** **FG-215 resolved** (проби 26/26 + кръстосано с main); тестове 252 passed, 1 failed → **FG-224**.
- **#83 CP-01:** 468 passed, 1 failed (същото и на main), 3 skipped.
  - Р48: (1) PASS, (4) PASS; (2), (3), (5), (6) PARTIAL.
  - FG-167 resolved; FG-165, FG-171, FG-172, FG-175 partial.
  - Нови **FG-225** (high), **FG-226**, **FG-227**, **FG-228** (Крум), **FG-229**, **FG-230** (high, merge риск).
- **#84 INV-CN-01:** 148 passed; FG-217..FG-223; D1–D16 класифицирани (Q004).
- **Оракул:** Q005 (D1/D2/D5/D6/D7/D8 на CP-01). Р48/Р49 записани в Q003/Q004.
- **Бавен преглед:** FLOW-017 (процес) — спазен; бележка: Р17–Р49 и пакетите не са в `main` (PR #80).

### Проход 23b — 08.11.2026 13:10 UTC (решения на Крум)

- **Р50** и **Р51** са проверени дословно в `RECOVERY_EXECUTION_PROPOSAL` L111–L112 @ `e1bf2eb`.
- Р50 (2) решава FG-228. Р51 (1) решава FG-221, Р51 (2) — FG-223. Р51 (3) решава D6, Р51 (4) — D3: всяко прихващане иска втори човек, без праг.
- Р50 (1) решава D6 на CP-01: плащане в брой срещу разписка (`file_id`), блокирано при спрян IBAN. Р50 (3) решава D8: архивиран контрагент се връща от Админ/Собственик, IBAN-ът се проверява наново.
- Р50 потвърждава по канона: enforce в production, пълен IBAN само за Owner/Accountant, маска `****1234`.
- Оркестраторът иска от Крум merge на PR #80 (docs). Бележката от FLOW-017 отпада след merge-а.

### Проход 23c — 08.11.2026 14:00 UTC (повторна проверка на #84)

- main `8c52e92` (merge #80, само документи). Р9–Р52 и пакетите вече са в main; бележката от FLOW-017 отпада.
- **#84 `71957db`:** тестове 181 passed; проби 22 passed; пробно сливане с #82 `1622f62` — конфликти, след разрешаване 182 + 101 passed.
  - Resolved: FG-218, FG-219, FG-220, FG-221 (Р51 (1)), FG-222, FG-223 (Р51 (2)), FG-196 (с #82), Р49 (1) стари чернови.
  - FG-217 partial — до миграцията (Release Manifest).
  - Р51 (3) partial → FG-233.
  - Нови: **FG-231** (Крум), **FG-232**, **FG-233**, **FG-234** (Крум), **FG-235**.
- **Р52** (D8/D7/D12) записано в Q004.

### Проход 24 — 08.11.2026 14:50 UTC (периодичен)

Нови SHA:
- #81 `ac66058` — **FG-224 resolved**; проби fg22 26/26 и fg23 10/10;
- #71 `021a078` — парите се скриват при липсваща заявка (fail closed);
- #84 `5cce932` — само тестове и evidence;
- #83 CP-01 `7e0b914`.

Проверки:
- **#83 `7e0b914`** (реален Mongo): CP-01 482 passed / 3 skipped, PAY-01 630, SEC-01 30, PM-01 6, проби 20/20. Merge с main `8c52e92` без конфликти.
  - Р48: (1), (2), (5), (6) PASS; (3), (4) PARTIAL. Р50: (2) PASS; (1), (3) PARTIAL.
  - Resolved: FG-165, FG-171, FG-172, FG-225, FG-226, FG-227, FG-228, FG-229, FG-230. FG-175 partial.
  - Нови: **FG-241** (high), **FG-242**, **FG-243**, **FG-244**, **FG-245**.
- **Бавен преглед FLOW-018 на main:** FG-236..FG-240.

### Проход 24b — 08.11.2026 15:25 UTC

- main `8c52e92` → `0750d75` (merge #71 SEC-02). Дървото съвпада с автоматичния merge на проверения `021a078`. FG-204: backend затворен (partial — остава UI).
- **Р54** (main `ec7ddd8` L115, след merge на PR #85) решава FG-236 и FG-240; пакет PRJ-01 в работа.
- #84 `081f35b` (Р52, Р53, FG-231..FG-235) — проверка тече.

### Проход 25 — 08.11.2026 15:50 UTC (повторна проверка на #84)

- **Поправка на запис:** Р52, Р53 и Р54 са само на клона `claude/happy-meitner-bmcnel` (`0cb7161`, L113–L115), **не са в main**. В main са до Р51. FLOW GUARD по-рано ги приписа на main погрешно (Р54 в проход 24b). Бележката от FLOW-017 се отваря отново: Р52–Р54 трябва да влязат в main.
- **#84 `081f35b`:** 111 + 91 + 72 passed (реален Mongo); проби 32. Сливане с main `0750d75`: конфликт само в `PM-01/run_meta.json`.
  - Р52: (1) partial (FG-247), (2) resolved, (3) resolved. Р53: (1) partial до миграцията, (2) resolved.
  - Resolved: FG-232, FG-234, FG-235. Partial: FG-217, FG-231, FG-233.
  - Нови: **FG-246** (high), **FG-247**, **FG-248**, **FG-249**, **FG-250** (Крум), **FG-251** (Крум).

### Проход 25b — 08.11.2026 15:45 UTC

- main `0750d75` → `ec7ddd8` (merge PR #85, само документи). Р52–Р55 вече са в main (L113–L116); бележката от FLOW-017 отново е затворена.
- **Р55** (проверено дословно) решава FG-249 (1), FG-250 (2) и FG-251 (3). FG-246..FG-248 се поправят в #84.

### Проход 26 — 08.11.2026 16:50 UTC (периодичен)

Нови SHA:
- #81 `5b08e59` (WH81-03; FG-205/FG-169 partial; проби 36/36);
- #84 `8ccbe45` → `2c2e75f`;
- #83 `e36af6e` → `bc0d1c7`;
- ACT-01 `c7df7ca` (merge на main `0750d75`);
- #86 PRJ-01 `0bd77a1`.

Проверки (реален Mongo; контейнерът падна от „too many open files“ при паралелни агенти):
- **#84 `2c2e75f`:** 217 passed. Resolved: FG-246, FG-248, FG-249, FG-250, FG-233; FG-217/FG-231 след миграцията. Partial: FG-247, FG-251. Нови **FG-264**, **FG-265** (Крум).
- **#83 `bc0d1c7`:** CP-01 548, SEC-02 31, SEC-01 30, PM-01 6, PAY-01 630. Resolved: FG-241, FG-243, FG-244. Partial: FG-242, FG-245. Нови **FG-266**, **FG-267** (Крум), **FG-268**. Сливането с main е чисто, без загубени guard-ове на SEC-02.
- **ACT-01 `c7df7ca`:** 113 passed. Всички маршрути на клиентски актове остават само за финансовите роли в 3-те режима, без регресия спрямо `2cc1147`. FG-122 resolved.
- **#86 PRJ-01:** FG-236..FG-240 partial; нови **FG-252..FG-256**.
- **Бавен преглед FLOW-001 на main:** FG-257..FG-263.
- **Оракул:** Q006 (PRJ-01).

### Проход 27 — 08.11.2026 18:40 UTC

- main `ec7ddd8` → `fddb0185` (merge #77 ACT-01) → `1ea98fe2` (merge #74 OH-01).
  - #77: дървото съвпада с автоматичния merge на проверения `c7df7ca`.
  - #74: OH-01 = проверения `31a9478` + merge на main `182ea574`; конфликтите в `routes/overhead.py` и `full_cost.py` са разрешени като обединение (gate-ът на #69 `require_money_write` + keyed write на OH-01; ред „фира“ + полетата по Р38), без загубено правило. Сливането в main съвпада с автоматичния merge.
  - Поправките на ACT-01 и OH-01 вече са в main.
- **#84 `caea933`:** 245 passed (реален Mongo). **FG-264 resolved.** Р58 partial; нови **FG-269**, **FG-270**, **FG-271**. Сливането с main `1ea98fe2` има конфликт само в `PM-01/run_meta.json`.
- **Оракул:** Q007 (къде се вижда фирменият разход по Р58).
- Р56–Р59 са на клона `claude/happy-meitner-bmcnel` (`cc14f1e`), не в main.

### Проход 27b — 08.11.2026 19:05 UTC

- main `1ea98fe2` → `3699c3b` (merge PR #87, само документи — проверено: няма файл извън `docs/`). Р56–Р59 вече са в main.

### Проход 28 — 08.11.2026 18:50 UTC (периодичен)

- main `3699c3b` (merge #87, само документи; Р56–Р59 в main).
- **#86 `28fb230`:** PRJ-01 9, PAY-01 630, SEC-01 30, SEC-02 31, PM-01 6 passed.
  - Р54 и Р56 (1)–(4) resolved.
  - Resolved: FG-236, FG-238, FG-240, FG-252, FG-253, FG-254, FG-255. Partial: FG-237 (D2), FG-239, FG-256.
  - Нови **FG-272** (high), **FG-273** (Крум), **FG-274**.
- **#83 `9f86d0b`:** CP-01 580, PAY-01 626, SEC-01 30, SEC-02 31, PM-01 6 passed (20 падания от рестарт на Mongo, повторно зелени).
  - Resolved: FG-266. Partial: FG-267, FG-268 (Р59 не е изпълнено), FG-242, FG-245.
  - Нов **FG-275**.
- **#84 `ef7cddd`:** 223 + 81 passed. FG-271 partial; FG-269 open (по-тежко); FG-270 open. Нов **FG-276**.
- Бавният преглед на FLOW-022 се отлага.

### Проход 29 — 08.11.2026 19:40 UTC

- **#84 `e75b558`:** 144 + 91 + 299 + 246 passed (25 грешки само в тест, който иска жив сървър). Сливането с main `3699c3b` е чисто.
  - Resolved: FG-269, FG-270. FG-271 partial (UI). FG-276 open.
  - Нови **FG-277**, **FG-278**.
- **Р60** (FG-273) е записано; на клона `2a8e7245`, не в main.

### Проход 30 — 08.11.2026 20:50 UTC

- **#86 `abc6fda`:** 706 passed (реален Mongo); сливането с main `3699c3b` е чисто.
  - Р60 изпълнено; пробив → FG-279.
  - Resolved: FG-239, FG-273. Partial: FG-237 (D2), FG-256, FG-272, FG-274.
  - Нови **FG-279**, **FG-280**.
- **Оракул:** Q008 (offline-first, PWA-02).

### Проход 31 — 08.11.2026 20:50–22:00 UTC (периодичен)

- main без промяна (`3699c3b`).
- Р61 (Q008, offline) записан дословно в `oracle/Q008_offline_first_pwa02.md` (`242d5517`).
- #83 CP-01 `1e455e3`: FG-242, FG-268 (заобикалянето с име/ЕИК), FG-275 → resolved (PROVEN). FG-267 — кодът прилага неодобрено правило, чака Крум. FG-245 — partial. Нови FG-290..294. Тестове: CP-01 реален Mongo 28 passed, PAY-01 21 passed; 43 грешки в широкия набор са от срива на `fgmongo` (среда).
- #86 PRJ-01 `dbb04ba`: FG-274 partial (tombstone, rollback, 409 за използвана чернова — PROVEN); FG-272, FG-279 open; FG-280 → PROVEN; нови FG-300..302. Проход 31b на `8e8be48` (`24ffe07`): FG-279, FG-280 → resolved (PROVEN); tombstone съвместим с FLOW-001 P-03/P-06 и Р56 (2) — 404, скрит от списъци, кодът се освобождава, старият остава в `original_code` и AuditEvent; FG-300/301/302 open; нови FG-303..305. Тестове: PRJ-01 9 passed, свързани 570 passed / 32 грешки среда.
- PWA-01 `a05167a` (нов клон): само app shell, без `/api` кеш, без офлайн опашка, обновяване само с клик — съответства на Р61 (1); нови FG-315..321 (medium/low). Production build + 35/35 Jest + Playwright проба.
- Бавен преглед FLOW-022 на main: нови FG-325..335 (4 high). COVERAGE обновен.
- #84 INV-CN-01 `cdd3dc8`: FG-276, FG-277 → resolved (PROVEN); FG-278, FG-271 partial; FG-247 без промяна; нови FG-281, FG-282. Тестове (частен Mongo): INV-CN-01 147/147, склад 1117 passed / 4 failed (`c13_mongo`, същите на main) / 16 грешки среда; jest 183 passed.
- #81 WH-FIX-01 `a7166d4`: сливането на main (`fdfad135`) пази всички пазачи (права, tenant, пари, AuditEvent, idempotency, 410); F-81-03 (`projects.py:1290-1460`, приход на табло само от платени Issued + `project_payments`; `paid_*` се изрязват за роли без пари) — PASS; нов FG-310 (evidence). Тестове: 1429 passed, 4 failed (`c13_mongo`, същите на main), WH-FIX-01 311/311.
- SUB-ADV-01 `aa369d8`: сливането на main `1ea98fe` (`8780cfbf`) е чисто (всички разлики спрямо auto-merge прегледани — запазени `MONEY_WRITE_ACTIONS`, SEC-02 четения, `strip_money_for_non_finance`); `aa369d8` — fail-closed при липсваща заявка. FG-132, FG-147, FG-148 без промяна. Тестове: 1126 passed, 4 failed (същите на main).
- #81 + #82: `git merge-tree a7166d4 1622f62` — същите 4 кодови конфликта като в проход 22; FG-213 / FG-214 / FG-216 без промяна.
- `fgmongo` падаше (лимит 20000 файла); контейнерът е създаден наново празен ~21:43 UTC; засегнатите тестове са пуснати отново.

### Проход 32 — 08.11.2026 22:50 UTC (периодичен)

- main `3699c3b` → `ea57121` (merge #76 SUB-ADV-01): дървото на сливането е идентично с `git merge-tree 3699c3b aa369d8` (`e6ce7d5`) — точно проверената в проход 31 глава `aa369d8`. FG-132, FG-147, FG-148 вече са в main (open).
- #81 `72e7e87`: само evidence — FG-310 → resolved (PROVEN).
- PWA-01 (PR #88) `7c284fa`: D1 — FG-319 → resolved (PROVEN по код и jest).
- Поправка: FG-304 сочеше `ea57121` като commit на дефекта; това е сегашният main, кодът е от 28.06.2026.
- Бавен преглед FLOW-023 на main `ea57121`: нови FG-355..364 (4 high: FG-355, FG-357, FG-358, FG-361). Krum: FG-355 (анализ само с количества от ТР?), FG-359 (праг на загуба за Approval), FG-361 (симулираният каталог — демо или махане).
- OFF-01 #79 `f526182`: сливането с main `ea57121` (`552ffdce`) — чисто (разлики спрямо auto-merge само в harness, 2 inventory, `run_meta.json`); паричните пазачи на main по офертите запазени; FG-129/130/135/136/137/138/144/149 — още resolved (PROVEN); FG-139 open; FG-173 partial; нови FG-350..352. Тестове: 237 passed.
- LAB-01 #73 `7ee87f8`: сливането с main `ea57121` (`c7d48ed0`, 5 конфликта) — без загубен пазач (запазено сторно-само пресинхронизиране SEC-01-C02/FG-26; `piece_rate`, `labor_formula` в `LABOR_MONEY_FIELDS`); `a0409535` — приемливо. LAB-02 #75 `5809367`: сливането `adc01d42` — чисто. FG-58 ефект PROVEN; FG-66, FG-82, FG-44 без промяна; разрешените LAB записи остават. Нови FG-340 (high), FG-341. Тестове: LAB-01 423/423 (1 flake, минал отделно), LAB-02 473/473.

### Проход 33 — 09.11.2026 00:50 UTC (периодичен)

- main без промяна (`ea57121`).
- OFF-01 #79 `f526182` → `25c9ae8`: само evidence на сливането — FG-352 → resolved.
- LAB-01 #73 `7ee87f8` → `fdcb5ac`: само тестове (складовите c20/c21/c22 насочват и `services/labor_cost`, `services/report_normalizer` към тестовата база) и evidence `tests-LAB-01-R.txt`; без промяна в кода; FG-340 остава open.
- Бавен преглед FLOW-024 повторно (след OH-01) на main `ea57121`: FG-77 → resolved (PROVEN); FG-86/87/88/97 потвърдени на main (PROVEN), FG-89/98/116/127 — по четене; FG-189 open; Р14/Р20 съответстват (ТР/Техник/Наблюдател 403, Счетоводител 200). Нови FG-370..376 (FG-371 high — режийните в 4 регистъра). OH-01 тестове на main (mongomock) 117 passed; реалният Mongo — собствени проби.

### Проход 34 — 09.11.2026 02:50 UTC (периодичен)

- main без промяна (`ea57121`).
- LAB-01 #73 `fdcb5ac` → `5e3a152`: само evidence (`warehouse-suite-LAB-01-R.txt`, склад 1121 = main).
- LAB-02 #75 `5809367` → `48ba662`: сливане на LAB-01 (`fc538d5`) — разлика спрямо auto-merge само в `PM-01/run_meta.json`; останалото — evidence (склад 1121 = main). Без кодова промяна; FG-340, FG-341 остават open.
- Бавен преглед FLOW-026 на main `ea57121`: FG-208/209/210/211 → PROVEN (open); съответства: алармата не променя официални записи, събитията не се трият, SEC-02 маха сумите, tenant изолация (404). Нови FG-385..393. Krum (FG-391): виждат ли Наблюдател/Техник/Шофьор тежестта на бюджетната аларма; кой вижда алармите за извънреден труд с имена.

### Проход 35 — 09.11.2026 04:50 UTC (периодичен)

- main без промяна (`ea57121`); нито една отворена PR глава не е сменена.
- Бавен преглед FLOW-025 на main `ea57121`: документалният контрол (DocumentType, версии, един Current, подписване, валидност, чеклист) не е реализиран. Нови FG-400..409 (6 high: FG-400, 401, 402, 403, 405, 409). FG-145 → PROVEN (open). FG-404 потвърден и по код: `services/ocr_invoice.py:150` вика `extract_invoice_text(media_id=…)` без задължителния `tenant` (`:15`). FG-409 е поправен на #79 OFF-01. Krum (FG-407): кой одобрява разходите на служители и къде отива одобреният разход.

### Проход 36 — 09.11.2026 06:15 UTC (по съобщение от оркестратора)

- main `ea57121` → `44e8d97` (merge #79 OFF-01): дървото = `git merge-tree ea57121 25c9ae8` — точно проверената в проход 33 глава. FG-409 → resolved; FG-139, FG-173 (partial), FG-350, FG-351 вече са в main (open).
- Нови решения на Крум на `claude/happy-meitner-bmcnel` `6f29205`: Р62 (FG-340, FG-58 — едно число за труда) и Р63 (FG-281 — ново разнасяне след сторно).
- Oracle Q009 (D20 на #84): Р63 не назовава статус на обект; канонът не покрива изрично нито един статус за новото разнасяне — `oracle/Q009_rebooking_project_status.md`, 5 въпроса към Крум.
- #84 INV-CN-01 `5242cba` (`808d13be` код; `639b3895` inventory; сливане `5e7ab4a2` на main `44e8d97` — разлика спрямо auto-merge само в 2 документа): FG-281 → resolved по Р63 (PROVEN); FG-278 → partial (числата съвпадат, етикет на екрана липсва); FG-282 open (PROVEN отново); FG-247/271 без промяна; нови FG-415..417. Тестове: INV-CN-01 153 passed.

### Проход 37 — 09.11.2026 06:50 UTC (периодичен)

- main без промяна (`44e8d97`).
- Бавен преглед FLOW-027 на main `44e8d97`: графикът не е изграден (Wave 2.1); съществуващите пътища за прогрес, крайна дата и часове нарушават канона. Нови FG-435..441 (FG-435 high). Krum: FG-438 (резервна ставка труд — 18 €/ч или 200 €/ден), FG-439 (дневен лимит часове на работник), FG-440 (стартира ли графикът като Pilot BEG преди W0-06/07).
- LAB-01 #73 `a97db46` (по-късно `b33058e` — само evidence): сливането `c3d5f8d8` на main `44e8d97` — без загубен пазач; Р62 изпълнено за P&L, `/project-profit`, `/project-net-profit`, пакетите и алармата (PROVEN); FG-340, FG-58 → partial; FG-390 → resolved за алармите; FG-207 → PROVEN; нови FG-420..424 (2 high). Тестове: LAB-01 129 passed (R62 12), PAY-01 91, SEC-01-C01 7, SEC-02 31.
- CP-01 #83 `4929451`: сливането `2f64d708` на main `44e8d97` — чисто (един ред import); FG-290, FG-294 → partial (PROVEN); FG-291, FG-292 — PROVEN отново; FG-293, FG-267 без промяна; FG-245 partial. Нови FG-425..429 (FG-427 high — авансът заобикаля CP-01; препоръка: да не се слива преди поправката). Тестове: CP-01 614 passed, PAY-01 91, SEC-01-C02 9, SUB-ADV-01 8, OFF-01 237, PM-01 6.
- WH-FIX-01 #81 `3028304`: сливането `f31fe92d` на main `44e8d97` — PASS (разлики спрямо auto-merge само в 3 генерирани файла, регенерирани в `61cef415`; SUB-ADV-01 пазачи на място); `0528084b` — PASS (авансът не е приход, без двойна себестойност: 0 → 2000, не 3000; Р20 спазен). Сливане с #82 `1622f62` — същите 4 конфликта; капан: `@staticmethod` над маркера (ред 1924), `_plan_receipt_reversal` на #82 без декоратор. FG-213, FG-216 PROVEN, FG-214 SUSPECTED; FG-147 PROVEN. Нов FG-430 (от main). Тестове: WH-FIX-01 317/317, SUB-ADV-01 9; склад 1112 passed, 4 failed (`c13_mongo` = main), останалите — среда (минали при повторно пускане).

### Проход 38 — 09.11.2026 08:50 UTC (периодичен)

- main `44e8d97` → `1525a1e` (merge #81 WH-FIX-01): дървото = `git merge-tree 44e8d97 3028304` (`d2011a6`) — точно проверената в проход 37 глава. Отворените FG на #81 (FG-150..164 остатък, FG-213/214/216 спрямо #82, FG-430) вече са в main.
- Нови решения на Крум на `claude/happy-meitner-bmcnel` `121ee87`: Р64 (FG-415/Q009), Р65 (FG-428), Р66 (FG-424), Р67 (FG-350), Р68 (FG-317) — записани към съответните FG.
- Нови глави в проверка: #84 `f6e0c90` (Р64, FG-416, FG-282), #83 `7750f4e` (Р65, FG-427), #73 `b395f0d` + #75 `33a3e7b` (Р62 във всички четци, Р66), #82 `e07320d` (сливане с #81 — FG-213/214/216), #88 `d59bcca` (Р68), #86 `49eb546` (сливане), нов клон OFF-02 `56913a4` (Р67).
- #73 LAB-01 `b395f0d` + #75 LAB-02 `33a3e7b`: сливанията `f04a5169` и `33a3e7b0` — чисти (само `run_meta.json`). Р62 — всички четци на общия труд = `project_labor_cost` (PROVEN): FG-340, FG-420, FG-421, FG-422 → resolved; FG-424 → resolved по Р66 с остатъци; FG-58 механика resolved; FG-423, FG-207 partial; FG-341 open. Нови FG-460..464. Krum: (1) одобрява ли Счетоводителят редове на Админ/ТР/друг Счетоводител без Собственик (Р62 срещу Р66); (2) „Управител“ от Р66 = Админ?; (3) може ли създателят да отказва/сторнира собствения си ред; (4) стари ръчни редове без `created_by` — backfill, масово одобрение или без промяна; (5) „одобрено количество“ — ръчният акорд (Owner/Accountant) и LAB-02 (Admin/Owner/ТР) същото ли са. Тестове: R62 21, LAB-01 25, SEC-01-C01 7, LAB-02 49 (+1 FG-464).
- #84 INV-CN-01 `f6e0c90`: сливането `8e2a1f43` на main `1525a1e` — без загубен пазач (различават се само 6 конфликтни файла; `dq_issues` веднъж в TASKS). Редакция само на дестинацията на заключена входяща фактура (`finance.py:1300-1345`) — без промяна на суми/редове (409 `INVOICE_LOCKED`), с AuditEvent и версия при платена (виж oracle Q010). FG-415 → resolved по Р64; FG-416, FG-282 → resolved (PROVEN); FG-278 partial; FG-417 open; FG-214 open. Нови FG-450..454. Krum: (1) `Stopped` = „Временно спрян“?; (2) `Overhead` затворен ли е?; (3) `Draft` като затворен — по буквата на Р64?; (4) Completed/Finished = технически или финансово приключен; Warranty?; (5) статусното правило при първо осчетоводяване на неопределен ред?; (6) прихващането плащане ли е по Р44?; (7) при одобрение на вече приключен обект — отказ или предупреждение? Тестове: INV-CN-01 159 + 9; WH-FIX-01 f81 132, post_55 47, a3_r44 129 (+9 mongomock — FG-454).
- #83 CP-01 `7750f4e`: сливането `4f32e963` на main `1525a1e` — чисто (само 4 документа); пътищата за плащане на #81 са под проверката на CP-01 (quick-pay, allocate). FG-428 → resolved по Р65 за физически лица (PROVEN); FG-245 → resolved (`dq_issues` веднъж); FG-427 (high), FG-429, FG-425, FG-292 — PROVEN отново, open; FG-426/291/293/267 чакат Крум. Нови FG-455..457. Препоръка: да не се слива преди FG-427 и FG-457. Krum: (1) PDF на входяща фактура от физическо лице — също под Р65?; (2) PDF на фирмена фактура — Admin без одит, потвърдено ли?; (3) ДДС номер `BG` + ЕГН = ЕГН по Р65/Р48 (3)? Тестове: CP-01 620, WH-FIX-01 a3_r44 138, f81 132, PAY-01 91, SEC-01-C02 9, SUB-ADV-01 8 (+1 FG-457).
- #82 WH-REV-01 `e07320d`: сливането `9ebdc373` на main `1525a1e` — PASS (7 конфликта, всички прегледани; капанът `@staticmethod` — решен правилно, проверено с AST; една „evil merge“ промяна в `invoice_allocation.py` — адаптацията за FG-214, прегледана). FG-213, FG-214 (на #82), FG-216 → resolved (PROVEN); FG-194/195/197 остават resolved; FG-196 зависи от FG-465. Нов FG-465 (кръстосано с #84). Тестове: 750 passed (WH-REV-01 101, WH-FIX-01 317, c26l k/l/n 288, …), 15 проби.
- #88 PWA-01 `d59bcca`: сливането `bdf5e5a` = merge-tree (чисто). FG-317 → partial по Р68 (PostHog част resolved, PROVEN); FG-315/316/318/320/321 без промяна; нов FG-470. Тестове: jest 232 passed.
- #86 PRJ-01 `49eb546`: сливането `2d6421a` — чисто (`dq_issues` веднъж, генерирани файлове регенерирани); FG-279/280 остават resolved; FG-300..305 без промяна. Тестове: PRJ-01 9, WH-FIX-01 317, PM-01 + SEC-02 37.
- OFF-02 `56913a4` (нов клон): FG-350 → resolved по Р67 (PROVEN); FG-355 partial; FG-357, FG-358 open; нови FG-471, FG-472. Наблюдение за Крум: Счетоводителят вече може вътрешно да приема/отказва/анулира/трие оферти (по Р67 „създават и променят“) — потвърждение за FLOW-003. Тестове: OFF-02 22, OFF-01 90, SEC-01-C01 7, PM-01 6, SEC-02 31, ACT-01 113.
- Бавният преглед (FLOW-029) се отлага за следващия проход заради натоварването на тестовата база.

### Проход 39 — 09.11.2026 10:50 UTC (периодичен)

- main без промяна (`1525a1e`).
- Нови решения на Крум на `claude/happy-meitner-bmcnel` `a11a4c4`: Р71 (FG-427/425/429), Р72 (FG-426), Р73 (FG-424 — създателят може да откаже/коригира/сторнира с AuditEvent), Р74 (FG-453 — офсетът е плащане).
- #88 PWA-01 `131d945`: FG-470 → resolved. OFF-02 `7cfeae5`: FG-472 → resolved (по код и тестовете на PR-а).
- #84 `b0e72cf` + #82 `108afc0`: пробно сливане PASS (5 конфликта, решени по `26908700`); FG-465, FG-450, FG-214, FG-196, FG-453 (Р74), FG-454, INV84-N2 → resolved (PROVEN); `108afc0b` (WHREV82-M1) освобождава ключа за редакция на записа за приемане в доставките (FG-157), не заключването по Р49 — съответства. Нови FG-485 (Р69 не е изпълнено), FG-486 (Р70). Въпроси (1) и (2) се отговарят от самия текст на Р69/Р70 (прочит на оркестратора, потвърден от FLOW GUARD); (3) INDEX_NOT_BUILT → Админ, видимо за Собственика — техническо решение на оркестратора (канонът мълчи; Крум може да го промени); (4) остава за Крум при пакета ALLOC-02. Тестове: INV-CN-01 165+9, WH-REV-01 104, a3_r44 129/138.
- #83 CP-01 `a5176b2`: FG-427, FG-425 → resolved по Р71; FG-455 → resolved (PROVEN); FG-429, FG-426, FG-457 partial; нови FG-480..484. Krum: (1) един бон за един разход/аванс?; (2) BG+ЕГН на фирма/контрагент — кой вижда пълното и през какво одитирано действие; търсене по цифрите на ЕГН само за Owner/Accountant?; (3) 409 и пазене на файла до File Registry достатъчно ли е?; (4) повторът на изпълнен аванс винаги с оригиналния резултат? Тестове: SUB-ADV-01 9, CP-01 647, PAY-01 630, SEC-01 26.
- #73 LAB-01 `df4cf51` (главата се премести от `f1c46c6`; `LAB73-M3` добавя само `labor_day_locks` в `ownership.py`): 17 четеца = `project_labor_cost` (850 → 2860); FG-460, FG-461, FG-424 → resolved; FG-463, FG-462, FG-423 partial; Р73 — PROVEN за отказ и сторно. Нови FG-490..493. #75 `09a2ac7` — само evidence; FG-341, FG-464 open; сливането с `df4cf51` дава малък конфликт в `ownership.py`. Krum: (1) FG-462 — етикетирана оценка в екраните за време или махане; (2) FG-490 — старите отчети още ли се одобряват; (3) FG-491 — стари редове с неправилна дата; (4) Р73 — задължителен `corrects_entry_id`?; (5) от проход 38: „Управител“ = Админ?; стари редове без `created_by` — само Owner достатъчно?; акордното „одобрено количество“ = LAB-02? Тестове: R62 67, LAB-01 25, SEC-01 26 (+4 FG-493), SEC-02 30 (+1 нестабилен), PM-01 6, LAB-02 50.

### Проход 40 — 09.11.2026 12:50 UTC (периодичен)

- main без промяна (`1525a1e`).
- #84 `faaa2d0`: само evidence (гейтове на реален Mongo за FG-465/Р74/INV84-N2).
- #88 PWA-01 `62f898a`: posthog-js се вгражда в bundle-а (без външен loader) — FG-317 остатъкът за PostHog е затворен; `emergent-main.js` остава.
- Нов клон `claude/sec-scan` `5fccc70`: доклад на друга сесия за скрит код и supply chain (само документи). Съвпада с FG-317 (H-1 `emergent-main.js`, H-2 PostHog на main); M-1 (`deps/auth.py:20` — `JWT_SECRET` по подразбиране `dev-secret-key`) е въпрос на сигурността (CLAUDE.md §16), не разминаване с FLOW — само бележка.
- #83 CP-01 `b4a775f`: FG-480, FG-481, FG-483, FG-484 → resolved; FG-482 partial (PROVEN); FG-426 partial; нови FG-495..499. Krum: (1) Р29 на всички парични пътища вкл. удръжката; (2) търсене по цифрите на ЕГН от Owner/Accountant без AuditEvent — приемливо?; (3) ДДС номер — нормализиране или отказ; (4) стари клиенти с ДДС номер — миграция или маскиране; master-data `vat` BG+10 цифри като чувствителен; (5) един бон за много плащания? Тестове: CP-01 666, SUB-ADV-01 9, PAY-01 198 + 91, SEC-01 30, A2C 0 нарушения.
- #73 LAB-01 `4d1f5a3` + #75 LAB-02 `11b55c1`: сливането `415cf711` — приемливо (двете страни запазени в `ownership.py`). FG-490, FG-491, FG-492, FG-462, FG-493, FG-464, FG-463, FG-423 → resolved (PROVEN); 17 четеца = `project_labor_cost` (3820); FG-341 open; FG-207 partial. Нови FG-500..502. Krum: (1) стари ръчни редове с неправилна дата в реалните данни — сторно + нов ред или нормализиране в четците; (2) „само часове“ и за отговорите при запис на сесия; (3) екран за ръчни редове преди „Готово“; (4) от проходи 38/39: „Управител“ = Админ?; стари редове — само Owner?; акордното „одобрено количество“ = LAB-02? Тестове: R62 82, LAB-01 25 + 92, SEC-01 30, SEC-02 31, PM-01 6, A2B/A2C 152, LAB-02 52 × 5.
- Бавният преглед (FLOW-029) — отложен до освобождаване на тестовата база.

### Отговори на отворени въпроси (09.11.2026, по съобщение от оркестратора; проверени от FLOW GUARD)

**От канона:**
- **„Управител“ в Р66 = Owner, не Admin.** Р57: „„Собственик“ … е **ролята Owner = Собственик / Управител** … Няма отделна роля „Управител“.“ Потвърдено дословно.
- **„Одобрено количество“ за акорд в Р62 = количеството, одобрено в LAB-02.** Р33: „…екран за въвеждане и одобрение на изработеното количество (м2 и др.) и акордна цена по СМР; новото смятане на труда (LAB-01, #73) се качва **заедно** с него.“ Потвърдено. Последица: ръчен акордов ред трябва да ползва същото одобрено количество. Отделно одобрение на количество в ръчния ред би било втори източник.

**Тълкувание (канонът мълчи):**
- **Стари ръчни редове без създател → одобрение само от Owner.** Р66 изисква двама различни души. При неизвестен създател разликата не може да се докаже. Само Owner е по-строго от Р66, което позволява и Счетоводителя. Това е разумно тълкувание, не текст. Остава неясно дали Owner, който сам е създал реда, може да го одобри — създателят е неизвестен.

**Технически решения на оркестратора** (не са канон; Крум може да ги промени):
- **FG-500:** нормализиране на датата в четците; DQ задачата остава.
- **FG-502:** отговорите при запис на работна сесия — само часове.
- **FG-501:** екранът за ръчни редове е отделна задача (дълг по Definition of Done), не част от #73.
- **CP-01:**
  - ДДС номерът се нормализира при въвеждане (FG-496);
  - търсенето по цифри на ЕГН от Owner/Accountant пише AuditEvent;
  - replay първо на всички парични пътища вкл. удръжката (FG-499, Р29);
  - старите ДДС номера се маскират при четене (FG-498).

**Остава за Крум:** един касов бон за много плащания (FG-426, заедно с Р72).

### Проход 41 — 09.11.2026 14:50 UTC (периодичен)

- main без промяна (`1525a1e`).
- Нови решения на Крум на `claude/happy-meitner-bmcnel` `7824b51`:
  - **Р75 (SEC-SCAN):** махат се скриптовете/надписът на Emergent; сървърът не стартира без таен ключ; служебният адрес за напомняния се заключва; CSP и без вграждане; почистване на имената при печат.
  - **Р76 (SEC-SCAN M-2):** AI директно с Anthropic, закрепена версия, ключ и модел в настройките; без тях AI е изключен, ръчните процеси продължават.
  - FG-317 (остатък `emergent-main.js`) → решено по Р75, изпълнение в SEC-03.
- Пакет `docs/architecture/tasks/SEC-03_EMERGENT_REMOVAL_AND_HARDENING.md` — проверен срещу канона: не противоречи на FLOW/CLAUDE.md. Т. 8–10 следват CLAUDE.md §10 (AI само чернови → потвърждение → права; AI не е единична точка на отказ; feature flag изключен по подразбиране). Т. 9 (без ЕГН/IBAN към модела) съответства на Р48/Р71. Т. 5 (служебният адрес през Tenant Guard, AuditEvent) — на CLAUDE.md §3/§14.
- #83 CP-01 `2415b5f`: FG-495, FG-497, FG-499 → resolved (PROVEN); FG-496, FG-498 partial; нови FG-510..513. Препоръка: FG-510 и FG-498 (а) — преди сливане. Krum: (1) ДДС с кирилско „В“, `_`, `:`, тире, запетая — нормализиране или 422; (2) `vatNumber` и master-data `vat` BG+10 цифри като чувствителни; (3) Р29 „оригинален резултат“ — id или тяло; (4) AuditEvent при търсене по ЕГН без id-тата — достатъчно ли е; (5) FG-426/Р72. Тестове: CP-01 690, SUB-ADV-01 9, PAY-01 193 (+5 нестабилни, минават отделно) + 91, SEC-01 30.
- #73 LAB-01 `d34d41b` + #75 LAB-02 `4fa4957`: сливанията `af228707` (main `1525a1e`) и `fe743f47` — приемливи (без кодова разлика спрямо auto-merge; F-81-03, WH-FIX-01 и R62 четците запазени). 19 четеца = `project_labor_cost`. FG-500, FG-502 → resolved; акордът само от одобрено количество в LAB-02 (Р62 + Р33) — PROVEN; FG-463/490/491 остават затворени; FG-341 open; FG-207 partial. Нови FG-505..508. Krum: (1) FG-507 — корекция на количество след одобрен ред: спиране, автоматично изпадане или DQ; (2) FG-505 — агрегатът с платен или одобрен труд; (3) FG-506 — касовата карта от pay runs; (4) FG-508 — старо самоодобрено количество при одобрен от Собственика ред. Тестове: R62 84, LAB-01 25 + 92, SEC-01 30, SEC-02 31, PM-01 6, WH-FIX-01 270, A2B/A2C 76 × 2, LAB-02 52 × 3 + 8.
- Бавният преглед (FLOW-029) — отложен (тестовата база: 65 стари бази, сривове).

### Проход 42 — 09.11.2026 16:10 UTC (по съобщение от оркестратора)

- Нов PR #90 SEC-03 `bc52843` (Р75, Р76): съответства на 10-те точки на пакета; пропуски в т. 3, 4, 9, 10 (low/medium). Production build — само собственият bundle; PostHog snippet байт-идентичен с main (по пакета). `JWT_SECRET` fail-closed (с изключение FG-516); напомнянията — служебен ключ / Platform Admin, през данните на tenant-а, AuditEvent; печатът екранира имената; AI адаптер `anthropic==2.3.0`, без ключ/модел в кода, без AI → 503 „AI не е настроен“ / резервен път, без 500; логовете — само вида на грешката; `emergentintegrations`/`EMERGENT_LLM_KEY` махнати. Към модела не отиват структурирани ЕГН, IBAN, имена, клиентски полета, tenant id.
- FG-317 → остатъкът от Emergent решен на клона (след merge/deploy). FG-325..328, 332, 333, 360, 361, 143, 185 — без промяна (при изключен AI фиктивното 60/40 на FG-360 е нормалният път).
- Нови FG-515..522. Krum: (1) FG-519 — Approval и бюджет по FLOW-050 за включване на AI; (2) FG-522 — без `ai_enabled` до W0-06; (3) FG-520 — dev сървърът с `*.emergent.sh`.
- Тестове: SEC-03 45, W0-03E-C02 25, ST-02 3, A2C + две tenant-а 36, jest 9, craco build OK.

### Проход 43 — 09.11.2026 16:30 UTC (по съобщение от оркестратора)

- #83 CP-01 `781d185` (код `c50df5f`): FG-498, FG-511, FG-513 → resolved; FG-510 partial (28 изписвания поправени, PROVEN); нови FG-525..529. Krum: (1) FG-526/527 — 422 или разпознаване по 10 цифри; 10 цифри без „BG“ ЕГН ли е; (2) FG-528 — кратко търсене по цифри за другите роли; одит на кратките търсения на Owner/Accountant; (3) ключовете за идемпотентност са по потребител — друг потребител със същия ключ създава ново плащане, нарочно ли е; (4) FG-525 — нормализиране и маскиране при подизпълнители. Тестове: CP-01 724, SUB-ADV-01 9, PAY-01 198 + 91 (пасът 41 нестабилни — сега 0), SEC-01 30.

### Проход 44 — 09.11.2026 16:50 UTC (периодичен)

- main `1525a1e` → `5e36dc2` (merge #86 PRJ-01 = `49eb546`, проверена в проход 38) → `3863610` (merge #88 PWA-01 `e03315a`); и двете дървета = `git merge-tree` на родителите. Сливането на main в #88 (`89718aa5`) = merge-tree на `62f898a` × `5e36dc2`; след него — само evidence. Отворените FG на #86 (FG-300..305) и на #88 (FG-315, 316, 318, 320, 321) вече са в main.
- #73 LAB-01 `06a309d`: FG-505, FG-506 → resolved (по код); нова бележка FG-530 (смесени основи в агрегата).
- Решение на Крум Р77 (FG-507) на `claude/happy-meitner-bmcnel` `9b9ede8`.
- #75 LAB-02 `b35d0c7`: сливането `b35d0c77` — приемливо (код = merge-tree); FG-508 → resolved; FG-507 partial по Р77; FG-505/506 PROVEN на слетия head; 18 четеца = 1350; FG-341 open; нови FG-531..534. Gate — не PASS. Krum: (1) FG-532 — Р73 или Р77 при сторно от създателя; (2) FG-531 — предложението следва последното количество; анулиране = само сторно?; (3) FG-533 — къде се вижда „изисква корекция“; ТР затваря алармата?; (4) FG-508 — по-строгото правило (Админ одобрил количеството не въвежда реда) желано ли е? Тестове: LAB-02 52 + 14, R62 88, LAB-01 25, SEC-01 C03 6.
- Бавен преглед FLOW-029 (фото/видео архив) на main `3863610`: моделът на архива не е изграден (Wave 2, след W0-06); съществуващите пътища нарушават канона. Нови FG-540..546 (FG-540 high — `GET /api/media/avatar/{filename}` без вход и без проверка на tenant връща всеки файл от общата папка за качване; потвърдено и по код в `media.py:210-221`; FG-542 high — физическо изтриване на използвана снимка). Следващ: FLOW-030.
- #90 SEC-03 `863876b`: FG-516, FG-518, FG-521 → resolved; FG-515, FG-517, FG-519, FG-520 partial; FG-522 временно затворен (AI за снимки изключен с константа); нови FG-535..539. Препоръка: FG-539 (сливане с main) и решение на Крум по FG-537 преди сливане. Krum: (1) бюджет сега или регистърът стига до W0 Subscription; изчерпан бюджет; единица; (2) Approval при включване на AI (§8); (3) скриване и при грешна контролна сума; (4) `*.emergent.sh` в dev сървъра. Тестове: SEC-03 82, W0-03E-C02 25, ST-02 162, A2C 57, jest 12; на локалното сливане + release 81, jest 264/265 (1 — среда).

### Проход 45 — 09.11.2026 18:50 UTC (периодичен)

- main без промяна (`3863610`).
- Нови глави (повечето сливат main `3863610`): #82 `d6de7db` (Р47 F-82-01/02), #73 `4a63a1e` (FG-530 по решение на Крум — приходът в агрегата = издадени фактури), #84 `279403f` (F-84-01 Permission Service на всички пътища за корекции), #83 `ddc6e9a` (FG-525..529 — само каноничен ДДС вход, 422), OFF-02 `58d0e40` (F-89-01 — без линка за преглед в отговорите към роли без пари), #90 `2b70152` (FG-535/536/538, сливане с #88 — FG-539), #75 `bac1d02` (FG-531/533/534).
- Нов клон `claude/media-sec-01` `35df04e` (FG-540/541/542/544) — отделна сесия по решение на оркестратора; FG-543/545/546 — дълг.
- MEDIA-SEC-01 `35df04e`: FG-540 → resolved (PROVEN); FG-541, FG-542, FG-544 partial; FG-543/545/546 без промяна; конфликт с #83 в `media.py` → FG-555; нови FG-555..558. Krum: (1) Viewer на обекта качва ли снимки; (2) файл в одобрен запис — винаги 409 (препоръка); (3) видимост на аватарите и кой ги задава; (4) колко реални аватара не са `context_type="profile"` (само брой на production — четене); (5) ред на сливане #83 / MEDIA-SEC-01. Тестове: MEDIA-SEC-01 18, PRJ-01 9, PM-01 6, jest 5.
- Останалите — в проверка.

### Проход 46 — 13.11.2026 18:40 UTC (периодичен; обединява 47 пропуснати задействания 09.11 20:50 – 13.11 16:50 — работникът спря поради лимит на разходите)

- main без промяна (`3863610`).
- Нови решения на Крум на `claude/happy-meitner-bmcnel` `b0278cb7`: Р78 (FG-525/526/527 — само каноничен ДДС/ЕГН вход, иначе 422), Р79 (FG-528/529 — търсене по ЕГН само Owner/Accountant, винаги AuditEvent), Р80 (FG-530 — приход в агрегата = издадени фактури), Р81 (FG-532 — старата сума остава до одобрението на новия ред; денят не пада на 0), Р82 (PWA-02 — Q011: първи етап присъствие/отчет/снимка без приемане; ден по Europe/Sofia; еднакво отбелязване = съгласувано), Р83 (MEDIA-SEC-01 — FG-541/542/556/557).
- Нови глави: #73 `2ca349e`, #75 `9e34641`, #84 `e8be2b3`, #90 `aaef24f`; без промяна: #82 `d6de7db`, #83 `ddc6e9a`, #89 `58d0e40`. Нов PR #91 (MEDIA-SEC-01, draft) `d634bf4` (код `f3cf9f1`).
- Проверките, спрени от лимита в проход 45, продължават срещу новите глави и Р78..Р83.
- LAB-01 #73 `2ca349e` / LAB-02 #75 `9e34641`: FG-530 (Р80), FG-531, FG-532 (Р81), FG-534 → resolved; FG-533 partial; нови FG-565..569 (FG-566 high — агрегатът на обекта показва пари на всяка роля, на main).
- FLOW-030 (преглед): нови FG-580..586 (FG-580 high — суровата AI оценка влиза в P&L като приход).
- #91 MEDIA-SEC-01 `d634bf4`: FG-557 → resolved по Р83; FG-541/542/544/556/558 partial; FG-555 open; нови FG-575..579 (FG-576 high). Минималният поток за одобрение от Собственика (`media_retire_requests`) — допустим като временен, записан като дълг към W0-07 (DQ/Approval runtime); изпълнява Owner-only, одобряващ ≠ заявител, AuditEvent, CAS (4 паралелни → 1×200), файлът остава; не изпълнява „exact version“ (FG-577). Krum: (1) при един Собственик — собствената му заявка достатъчна ли е, или заявява винаги Admin; (2) възстановяване на оттеглен файл и от кого (FG-558); (3) кога се пуска скриптът — до пускането старите аватари се показват като инициали; (4) ред на сливане #83 / MEDIA-SEC-01 (FG-555); (5) видимост на аватарите в tenant-а. Тестове: MEDIA-SEC-01 29 passed.
- #82 WH-REV `d6de7db`, #84 INV-CN `e8be2b3` (само доказателства над `279403f`), OFF-02 `58d0e40`: сливанията с main носят точно кода на main (merge-tree). F-82-02 → resolved (едно правило в цели центове, `credit_note_rule.py:19-38`, quick-pay и allocate); F-82-01 работи по кода (409 `INVOICE_PAID_ABOVE_NET`) — канонът → FG-570; FG-465 се пази (`service.py:2113`). F-84-01 → resolved за `invoice_corrections.py` (Permission Service, R20-1); останалите маршрути → FG-572; FG-485/486 без промяна. F-89-01 → resolved (`strip_money` маха `review_token`/`review_url`, 0 попадения в 389 GET × 5 роли × 3 режима); FG-139, FG-351 — open; D-OFF02-5 open. Нови FG-570..574. Krum: (1) FG-570; (2) D-OFF02-5 — Warehousekeeper/Driver не член чете ли таблото на обекта; (3) FG-572 — сега или с миграцията на `finance.py`. Тестове: WH-REV-01 120, INV-CN-01 174, fg233 9, OFF-02 34, OFF-01 90+147, PM-01 5/1, SEC-02 27/4 (#82, #84) и 26/1 провален (OFF-02, FG-574).
- CP-01 #83 `ddc6e9a`: 52 изписвания × 10 пътя за запис — Р78 изпълнено за нов вход; Р79 изпълнено в `/counterparties`. FG-525, FG-527, FG-529 → resolved; FG-526, FG-528, FG-510 partial; нови FG-560..562. Сливането `62543b3e` с main — вярно (merge-tree). SEC-03 #90 `aaef24f` (само frontend над `2b70152`, CSP по origin): FG-536, FG-539 → resolved; FG-515, FG-535, FG-538 partial; FG-537 open (Krum); нов FG-563. Krum: (1) Р78 — допустимо ли е мълчаливо махане на интервали/тирета/zero-width и съпоставяне на fullwidth и кирилски В/Г към `BG…`, или и те → 422; (2) FG-560; (3) FG-561; (4) FG-537/538/519 — AI бюджет и Approval за включване; (5) FG-535 — точка и наклонена черта като разделители; (6) FG-515 — кой вписва `nginx.conf` в Release Manifest. Тестове: CP-01 747/15, SUB-ADV-01 8/1, SEC-01 c01/c02/c03 6/8/5, ST-02 159 + 3 грешки (и на main), A2C 21/32/4, jest 253; SEC-03 95, jest 270, PM-01 5/1. Неизпълнени (Mongo паднал): PAY-01 c01, SEC-01 money_write_permissions — дълг за следващ проход.

### Проход 47 — 13.11.2026 19:51 UTC (по искане на оркестратора)

- #91 MEDIA-SEC-01 → `1844627` (код `9ba8980`): тестове MEDIA-SEC-01 42 passed; проба на fgmongo2. FG-576, FG-577, FG-578, FG-544, FG-556 → resolved; FG-575, FG-579, FG-541, FG-542, FG-558 partial; FG-555 open (сливането с #83 още е в конфликт; пътят към решението е описан). Нови FG-587..590 (FG-589 high — след сливане с #83). Потокът за одобрение: заявява само Admin, одобрява само Собственикът, точна версия, 4 паралелни → 1×200, файлът остава; остаряла заявка заключва файла до отказ.
- Остатъчният прозорец (въпрос на оркестратора): складът (FG-588) е достижим и пише доказателство на складово движение → по позицията на FLOW GUARD трябва да се затвори преди сливане или маршрутът да откаже `file_ids` до тогава; OCR from-media днес не е достижим (500 — предварително съществуваща грешка, липсва `tenant`) и създава чернова → допустим като дълг; плащанията на #83 след сливане (FG-589) — трябва да се затворят при сливането.
- FG-588 — вариантът „отказ на `file_ids`“ отпада (`ProjectWriteOffBody.file_ids` min_items=1 — би спрял всяко бракуване). Вариант 4 (траен маркер „чакащ държател“, потвърждаван/освобождаван от маршрута) изпълнява Р83/§2.9 без отваряне на складовата услуга при условия: (1) поставянето — едно условно обновяване (`status != retired`, без чакаща заявка, `$inc ref_version`), иначе 409; (2) DELETE/заявка/одобрение броят маркера за държател и крайният retire има „без маркери“ и `ref_version` в собствения си филтър; (3) потвърждаване/освобождаване — идемпотентно по ид. на маркера; (4) остарял маркер — само след доказателство за липса на препратка (`file_holders`), минимална възраст, без автоматично оттегляне, с AuditEvent; (5) видим за Owner/Admin, без подробности за не-финансови роли; (6) тестове за последователностите. Същото — за OCR from-media преди поправката на 500.
- Krum: (1) ид. на Собственика достатъчно ли е като „да от Крум“ за скрипта; (2) остаряла заявка — изтича ли, или заключва до отказ; (3) възстановяване на оттеглени файлове и видимост на аватарите; (4) може ли складовата услуга да се отвори за hook (FG-588).

### Проход 48 — 13.11.2026 20:15 UTC (по искане на оркестратора и MEDIA-SEC-01)

- #91 MEDIA-SEC-01 → `cb19aeb` (над `56ea33b`): тестове 50 passed; проба на fgmongo2 през истинския маршрут `/api/warehouse/canonical/movements` (заместител на услугата). FG-588 → resolved (всичките 6 условия); FG-587, FG-590, FG-575 → resolved; FG-579 partial (FG-597, FG-589); FG-555 open (`c299a20`). Нови FG-595..598. Реална складова услуга в harness → 503 INDEX_MISSING — пътят за запис проверен по код (`file_ids` на горно ниво, `org_id`).

- LAB-01 #73 `ed6e88d4` / LAB-02 #75 `a665932b` (сливането `b470e752` = merge-tree): FG-566, FG-567, FG-568 → resolved; дългът на теста на FG-530 — затворен; Р62, Р80, Р81 се пазят; нови FG-591, FG-592 (low). Тестове: SEC-02 31, R62 110, R81 16, количества 52, labor_cost 25, FG-568 20.

- SEC-03 #90 `0c04438c` (код `f34b1f25`; merge-tree с main — чисто): FG-563 → resolved за срив след commit; FG-535, FG-515 partial; FG-536, FG-539 без промяна; FG-537, FG-538 (Approval) — чакат Крум; нови FG-603, FG-604. Тестове: SEC-03 111, PM-01 6, A2C 32, jest 30/270.

### Проход 49 — 13.11.2026 20:40 UTC (по искане на оркестратора и MEDIA-SEC-01)

- #91 MEDIA-SEC-01: `a7e0546` — FG-596 resolved, FG-598 partial; правилото за остарял маркер не следваше решението на оркестратора → FG-607, FG-608 (medium), FG-609, FG-610 (low). `35cc099` (само `release_stale` + тестове): решението на оркестратора „остарял маркер се урежда само по собствения ref“ е изпълнено — FG-595, FG-607, FG-608 → resolved; FG-609, FG-610 open (low, код). Позиция на FLOW GUARD: правилото не отваря дупка в Р83/§2.9 — всички други държатели остават видими за оттеглянето; условие — „собствено“ по пълния обхват на ключа (FG-609). Условия 1–6 на FG-588 — без регресия. Тестове: MEDIA-SEC-01 52 passed.

- #84 INV-CN `ebcac7f9` (над `e8be2b3`: `1a3ef757` + `ebcac7f9`): FG-572 → resolved; FG-571 partial (на #84 — да, след сливане с #82 — не; рецепта: `_expect_credit_note` → `payable_until_credit_note`); нови FG-599 (Krum), FG-600. FG-485/486 — към ALLOC-02, не блокират #84 (FG-486 — препоръка за временен 409 за складови редове). Тестове: INV-CN-01 186, fg233 9, SEC-02 31, PM-01 6; WH-REV-01 на ръчно сляното дърво 120.

### Проход 50 — 13.11.2026 20:50 UTC (по искане на MEDIA-SEC-01)

- #91 MEDIA-SEC-01 → `700629f` (над `35cc099`): тестове 53 passed; FG-609 → resolved; без регресия (случаи A–K, правилото по собствения ref (a)–(d), FG-588 условия 1–6, FG-596, FG-598); FG-610 open (low); бележка: `_markers_for` без `actor_id` — по желание.

### Проход 51 — 13.11.2026 20:55 UTC (по искане на оркестратора)

- #91 MEDIA-SEC-01 → `a15b614`: тестове 55 passed; FG-610, FG-598 → resolved; `mark_pending` rollback — поправен; `_markers_for` с actor_id; без регресия (A, D, E, E2, F, H, H2). На #91 не остава открито разминаване от тази линия; за сливането с #83 остават FG-555 и FG-589.

### Проход 52 — 13.11.2026 20:50 UTC (периодичен)

- main без промяна (`3863610`); канон без промяна (`b0278cb7`).
- Нови глави: #73 `3d39a9df`, #82 `cd454eaa`, #83 `5695f974`, #84 `baafdf3a`, #89 `5763bd86`, #90 `38a3bfd4`; без промяна: #75 `a665932b`, #91 `a15b614`.
- #82/#84/#89: FG-573, FG-574, FG-599 → resolved (PROVEN). За сливането #82 × #84 остават FG-571, FG-600.

## Бележки, които не са разминавания

- #67: доказателствата казват „50 passed“, а тестовете вече са 110. 26 реда с локални пътища на scratchpad.
- #67: `schema_version` и `entitlements.snapshot` = null идват от main (W0-08 не е изпълнен). Това е дълг спрямо CLAUDE.md §6, не грешка на PR-а.
- Пакетът R0-04 мълчи за Approval/break-glass и срока на security събитията. Затова FG-7…FG-10 не са грешка на изпълнителя.

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
| FG-58 | medium | main `35ae10b` | ръчен `POST /labor-entries` без присъствие и отчет; възможно двойно броене със sync | SUSPECTED | open |
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
| FG-77 | medium | main `35ae10b` | режийни: изтриване на разходи/категории и презаписване на разпределенията (`delete_many`), без версия | SUSPECTED | partial — OH-01 `6c5c5cf`: FG-86/87/88 ✅; остава FG-89 |
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
| FG-122 | medium | main / ACT-01 | `GET /client-acts` и `/{id}` показват цените на Viewer (Р20) | PROVEN | resolved (ACT-01 `8188689`, PROVEN: без пари за Viewer/Technician/SM) |
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
| FG-145 | medium | #55 `ed48595` (и main) | сканирани документи: link/unlink по изпратена/платена фактура без проверка; изтриването трие оригиналния файл | SUSPECTED | open |
| FG-146 | medium | main / #55 | заглавието и редовете на Sent/Overdue/PartiallyPaid фактура могат да се редактират (само snapshot) | SUSPECTED | open |
| FG-147 | medium | SUB-ADV-01 `c4de7c9` | аванс и приспадане пишат само legacy `log_audit`, без canonical AuditEvent | PROVEN | open |
| FG-148 | low | SUB-ADV-01 `c4de7c9` | толерансът при актуване (0.01) може да вдигне актуваното над договора → последното плащане се отказва | SUSPECTED | open |
| FG-149 | low | OFF-01 `acc472f` | отварянето на клиентския линк сменя `updated_at` → фалшиво 409 при нова версия | PROVEN | resolved (OFF-01 `653a1a5`, PROVEN: 87 passed на реален Mongo) |
| FG-150 | high | main `2ec61f3` | изписването от склада е 0 в P&L, финансовия резултат и централните справки (четат `unit_cost`, а изписването пише `unit_price`) | SUSPECTED | open |
| FG-151 | high | main `2ec61f3` | стойността на изписването идва от клиента; обектът не приема (`received_by` е текст) | SUSPECTED | open |
| FG-152 | high | main `2ec61f3` | `/warehouse-return` и `/project-consumption` без роля и AuditEvent; връщането отива в свободна наличност, без карантина и без стойност | SUSPECTED | open |
| FG-153 | high | main `2ec61f3` | втори складов регистър (`warehouse_batches`) до `warehouse_transactions`; `/warehouse/consume` изписва без обект и основание | SUSPECTED | open |
| FG-154 | high | main `2ec61f3` | P&L не чете `allocations[]` на фактурния ред (само старите `allocation_type`/`allocation_ref_id`), т.е. разделеният ред е 0 или 100% | SUSPECTED | open |
| FG-155 | medium | main `2ec61f3` | остатъкът от фактурния ред може да остане неразпределен; разпределение „склад“ не създава наличност | SUSPECTED | open |
| FG-156 | medium | main `2ec61f3` | директна доставка влиза в склад `main`; приемането по фактура не е атомарно и е без Idempotency-Key | SUSPECTED | open |
| FG-157 | medium | main `2ec61f3` | фактура на доставчик се редактира след приемане в склада, без корекционно движение | SUSPECTED | open |
| FG-158 | medium | main `2ec61f3` | отрицателни количества и надпревара при изписване/FIFO консумация → отрицателна наличност | SUSPECTED | open |
| FG-159 | medium | main `2ec61f3` | брак/фира не е складово движение: без стойност, без намаляване на наличността | SUSPECTED | open |
| FG-160 | medium | main `2ec61f3` | `create-sub-project` пренаписва `project_id` на историческите движения и плащания, без Approval | SUSPECTED | open |
| FG-161 | medium | main `2ec61f3` | складовите стойности се виждат от всички роли (Р20/Р34/Р35) | SUSPECTED | open |
| FG-162 | medium | main `2ec61f3` | материалът е свободен текст (`material_name|unit`), не Master артикул; заявката става `fulfilled` без сравнение на количества | SUSPECTED | open |
| FG-163 | low | main `2ec61f3` | склад с наличност се деактивира или сменя типа си без проверка и без одит | SUSPECTED | open |
| FG-164 | medium | main `2ec61f3` | липсват движения склад→склад, обект→обект, „в път“, връщане към доставчик, ревизия; наличност само за склад `main` | SUSPECTED | open |
| FG-165 | high | main `2ec61f3` | няма регистър на проверени IBAN-и; плащане към нов/различен IBAN не се блокира | SUSPECTED | open |
| FG-166 | high | main `2ec61f3` | дублирани контрагенти по ЕИК и по роля в 5 регистъра | SUSPECTED | open |
| FG-167 | high | main `2ec61f3` | hard delete на контрагент с история (проверката гледа само `invoices`) | SUSPECTED | open |
| FG-168 | medium | main `2ec61f3` | финансовите суми по клиент/контрагент се виждат от всяка роля с модул M5 (#71 не ги покрива) | SUSPECTED | open |
| FG-169 | medium | main `2ec61f3` | профилът смесва приходи и разходи (без `direction`) и брои само 20 фактури | SUSPECTED | open |
| FG-170 | medium | main `2ec61f3` | клиентската карта връща 404 за клиенти фирми/лица на обекта | SUSPECTED | open |
| FG-171 | medium | main `2ec61f3` | create/update на контрагенти, клиенти, фирми, лица без право и/или без AuditEvent | SUSPECTED | open |
| FG-172 | medium | main `2ec61f3` | ЕГН се връща в явен вид на всеки логнат | SUSPECTED | open |
| FG-173 | high | main `2ec61f3` | клиентското одобрение по линк не е ApprovalReceipt (свободно име, без контакт, hash, AuditEvent) | SUSPECTED | open |
| FG-174 | low | main `2ec61f3` | ролята на контрагента е едно поле, не множество | SUSPECTED | open |
| FG-175 | low | main `2ec61f3` | IBAN-ът във фактурата е свободен текст; няма проверена собствена сметка | SUSPECTED | open |
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

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Път А: „обектов разход възниква само при изписване/консумация“.
- **Код (main `2ec61f3`):** `routes/procurement.py:628-637` пише редовете на изписването с `unit_price`/`total_price` (единственият writer на `type:"issue"`). Четат `unit_cost` × `qty_issued` → винаги 0: `services/project_pnl.py:86-89`, `services/project_financial_results.py:84`, `services/centralized_reports.py:324`. Други справки четат `total_price` (`revenue_expense.py:468`, `materials_baseline.py:326`, `material_smr.py:79`) → едно изписване е X в едни справки и 0 в други. В P&L `max(фактури, 0)` (виж FG-17).
- **Решение:** промяна в кода — един общ helper за стойността на изписване, ползван от всички справки. #55 го заменя с каноничния регистър, но на main може да се оправи само в четенето.

## FG-151 — стойността на изписването идва от клиента; обектът не приема (`received_by` е текст)

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Прехвърляния: „стойността/партидата се пренасят“; „промяна на историческа … стойност без корекционно движение“; Р17 (разход при приемане).
- **Код (main `2ec61f3`):** `procurement.py:635-636` взема `unit_price` от тялото на заявката; `get_warehouse_stock` (`:549-556`) вади тази стойност. Обектът не приема — `received_by` е свободен текст (`:653`).
- **Решение:** промяна в кода — сървърна оценка (FIFO/средна), отказ на цена от клиента, приемане от обекта (Rule B). Затваря се от #55 (5C-C21/C24).

## FG-152 — `/warehouse-return` и `/project-consumption` без роля и AuditEvent; връщането отива в свободна наличност, без карантина и без стойност

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Върнат материал не става автоматично свободна наличност“; Р17 „неизползваното се връща … и тогава разходът намалява“; CLAUDE.md §14 AuditEvent.
- **Код (main `2ec61f3`):** `procurement.py:729-784` `POST /warehouse-return` само с `require_m2` (модул, без роля); връщането е +qty в свободната наличност (`:557-559`); редовете нямат стойност (`:761-767`) → разходът на обекта не намалява. `POST /project-consumption` (`:671-724`) също без роля и без AuditEvent.
- **Решение:** промяна в кода — роля + членство в обекта, canonical AuditEvent, връщане в карантина, сторно по слоя. Аналог на FG-18 в #55.

## FG-153 — втори складов регистър (`warehouse_batches`) до `warehouse_transactions`; `/warehouse/consume` изписва без обект и основание

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — CLAUDE.md §16 „не създавай втори … source of truth“; FLOW-009 „материал без валидна локация“, „движение без основание“.
- **Код (main `2ec61f3`):** `routes/warehouse_batches.py:103-123` и `services/fifo_service.py:41-87` пазят наличност в `warehouse_batches`, отделно от `warehouse_transactions`. `POST /warehouse/consume` (`warehouse_batches.py:128-147`) изписва без `project_id`/основание, пише в `material_consumption_log`, без AuditEvent. `PUT .../block` (`:154-169`) без причина и одит.
- **Решение:** Крум да реши кой legacy регистър е източник до #55 (другият read-only); консумацията да изисква дестинация и основание.

## FG-154 — P&L не чете `allocations[]` на фактурния ред (само старите `allocation_type`/`allocation_ref_id`), т.е. разделеният ред е 0 или 100%

- **Тежест:** high. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Разпределение на фактурен ред: „40 торби → 10 XOPark, 12 Крум, 8 Делчо, 10 склад“.
- **Код (main `2ec61f3`):** `services/project_pnl.py:74-78` филтрира по `allocation_type`/`allocation_ref_id` и брои целия `line_total_ex_vat`; `POST /invoice-lines/{id}/allocate` (`invoice_lines.py:589-595`) обновява само `allocations[]`. Ред с `allocations[]` е 0 в P&L; стар ред, разделен по-късно, остава 100% за първия обект. Подобно `dashboard.py:688-700`.
- **Решение:** промяна в кода — Път Б: разход = `allocations[].qty × единична цена` за обекта.

## FG-155 — остатъкът от фактурния ред може да остане неразпределен; разпределение „склад“ не създава наличност

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Остатъкът не изчезва; системата изисква валидна дестинация.“
- **Код (main `2ec61f3`):** `invoice_lines.py:149-152` `require_full_allocation` по подразбиране False; проверките (`:576-582`, `:330-333`) зависят от нея. Разпределение `type:"warehouse"` (`:136-139`) не пише в склада.
- **Решение:** Крум да потвърди, че пълното разпределение е задължително (по канона — да); в кода разпределението към склад да създава приемане.

## FG-156 — директна доставка влиза в склад `main`; приемането по фактура не е атомарно и е без Idempotency-Key

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Видове движения: „покупка → обект / няколко обекта / обекти + склад“; Път Б.
- **Код (main `2ec61f3`):** `procurement.py:441-478` приема всички редове в склад `main`, въпреки `project_id` на реда (`:452`); проверката `posted_to_warehouse` (`:418`) и записът (`:479-489`) не са атомарни, без Idempotency-Key.
- **Решение:** промяна в кода — маршрут по дестинацията на реда, CAS на статуса на фактурата, Idempotency-Key.

## FG-157 — фактура на доставчик се редактира след приемане в склада, без корекционно движение

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „промяна на историческа партида/стойност без корекционно движение“.
- **Код (main `2ec61f3`):** `procurement.py:367-403` сменя `lines`/`total`/`status` без проверка на `posted_to_warehouse`; без AuditEvent (ролята — FG-30).
- **Решение:** промяна в кода — след приемане само корекция/сторно с причина и AuditEvent.

## FG-158 — отрицателни количества и надпревара при изписване/FIFO консумация → отрицателна наличност

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „отрицателна наличност без корекция и право“.
- **Код (main `2ec61f3`):** `procurement.py:612-621` проверява само склад `main` (+0.01) и не е атомарно с `insert` (`:661`); отрицателни `qty_issued`/`qty_returned`/`qty_consumed` не се отказват (`:617,751,693`). `fifo_service.py:113-132` чете и записва без условие.
- **Решение:** промяна в кода — qty > 0 и атомарно условно намаляване/транзакция.

## FG-159 — брак/фира не е складово движение: без стойност, без намаляване на наличността

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Видове движения „брак / загуба / кражба“; Р10; Р37.
- **Код (main `2ec61f3`):** `services/material_waste.py:57-80` пише `material_waste_entries` без стойност, без източник и без намаляване на наличността; без AuditEvent; P&L не я чете.
- **Решение:** промяна в кода — бракът като складово движение със стойност по слоя. Затваря се от #55.

## FG-160 — `create-sub-project` пренаписва `project_id` на историческите движения и плащания, без Approval

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Всяко движение е отделен неизтриваем запис“; „промяна на историческа партида … без корекционно движение“.
- **Код (main `2ec61f3`):** `routes/projects.py:1566-1583` (`create-sub-project`) прави `update_many` на `project_id` в `warehouse_transactions`, `invoices`, `subcontractor_payments`, `payroll_payment_allocations` и др. към под-обект А; само legacy `log_audit` (`:1659-1660`), без Approval.
- **Решение:** Крум да реши: историята остава на родителя (под-обектът получава трансфер) или пренасочване с Approval и canonical AuditEvent.

## FG-161 — складовите стойности се виждат от всички роли (Р20/Р34/Р35)

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — Р20, Р34, Р35 (кой вижда стойности).
- **Код (main `2ec61f3`):** `procurement.py:509-521, 564-571, 897-1007`, `warehouse_batches.py:47-98, 174-187` връщат цени и стойности на всеки с M2/всеки логнат.
- **Решение:** промяна в кода — маскиране по Р20/Р34/Р35 (#71 на main не покрива тези пътища). Аналог на FG-23/FG-56 в #55.

## FG-162 — материалът е свободен текст (`material_name|unit`), не Master артикул; заявката става `fulfilled` без сравнение на количества

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „Master артикул по FLOW-032“; аларма „незаявен материал“, „доставено повече/по-малко“.
- **Код (main `2ec61f3`):** `procurement.py:544,615,690` — ключ `material_name|unit`; `:492-499` маркира заявката `fulfilled` без сравнение по ред и количество.
- **Решение:** промяна в кода — `master_item_id` (FLOW-032/W0-03), изпълнение по ред, аларма за незаявен материал.

## FG-163 — склад с наличност се деактивира или сменя типа си без проверка и без одит

- **Тежест:** low. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
- **Канон:** FLOW-009 — „материал без валидна локация“.
- **Код (main `2ec61f3`):** `routes/warehouses.py:272-278` (TODO за наличност), `:233-259` смяна на type/project_id; без AuditEvent.
- **Решение:** промяна в кода — 409 при наличност/история + AuditEvent.

## FG-164 — липсват движения склад→склад, обект→обект, „в път“, връщане към доставчик, ревизия; наличност само за склад `main`

- **Тежест:** medium. **Статус:** open. **SUSPECTED** (бавен преглед на FLOW-009, проход 17).
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

## Бележки, които не са разминавания

- #67: доказателствата казват „50 passed“, а тестовете вече са 110. 26 реда с локални пътища на scratchpad.
- #67: `schema_version` и `entitlements.snapshot` = null идват от main (W0-08 не е изпълнен). Това е дълг спрямо CLAUDE.md §6, не грешка на PR-а.
- Пакетът R0-04 мълчи за Approval/break-glass и срока на security събитията. Затова FG-7…FG-10 не са грешка на изпълнителя.

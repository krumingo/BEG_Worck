# PLATFORMA

Код: `/tmp/claude-0/wtmain` (main `de720f94`), само четене. Пътищата по-долу са спрямо `backend/app/`, освен ако не е казано друго.
Обхват: tenant/абонаменти/модули, AI (оферти, калибрация, „пазарни цени“), табла/справки/аларми, брифинг/пулс, backup, клиентско одобрение. FLOW-015, 017, 022, 030, 031, 041, 042, 043, 044, 045, 046, 049, 050 + CLAUDE.md §2, §10.

Обща добра новина: никой AI модел няма достъп до базата. Моделът получава само текст и връща JSON, а кодът записва. Разпознаването на активи (снимка → AI → „чака одобрение“ → Admin одобрява) е направено правилно. Не намерих записи, споделени между фирмите: всички четения минават през `TenantData` с `org_id`.

## Карта: информация → всички входове → къде се записва → кой я чете за пари/решения

| Бизнес факт | Входове (endpoint / път) | Къде се записва | Кой го чете за пари/решения |
|---|---|---|---|
| Абонамент / план на фирмата | `POST /billing/signup`, mock checkout, Stripe webhook, seed | `subscriptions.plan_id/status` | `deps/modules.py:63` (пуска или спира модулите M2/M4/M5/M9 на всеки route) |
| Включен модул (M0–M9) | `PUT /feature-flags` (страници „Модули“), signup, checkout, webhook, seed | `feature_flags.enabled` | **никой бекенд не го чете за M1–M9**; само екранът го показва |
| План — копия | seed, platform bootstrap, onboarding | `organizations.subscription_plan/status/expires_at`, `tenant_registry.plan/subscription_status` | никой (мъртви копия) |
| Изтекъл trial | при **четене**: `check_module_access_for_org`, `GET /billing/subscription`, `GET /billing/check-module` (3 копия на една и съща логика) | `subscriptions.status = past_due` | пазачът на модулите |
| AI цена за СМР | `/extra-works/ai-proposal`, `/batch-ai`, `/fast`, `/refine`, `/extra-works/{id}/apply-ai`, `/missing-smr/{id}/ai-estimate`, `/smr-analyses/{id}/ai-suggest`, `/smr-analyses/{id}/ai-breakdown` | `extra_work_drafts.ai_*`, `missing_smr.ai_estimated_price`, `smr_analyses.lines[]` | 3 различни пътя „→ оферта“: `extra-works/create-offer`, `missing-smr/batch-to-offer`, `smr-analyses/{id}/to-offer` |
| „Пазарна“ цена на материал | `/pricing/material`, `/pricing/batch`, `/smr-analyses/{id}/lines/{line}/fetch-prices` | `material_prices` (кеш), `smr_analyses.lines[].materials[].unit_price` | СМР анализ → оферта |
| Корекционен коефициент за AI цените | `POST /ai-calibration/record-edit` (данни от браузъра), `POST /ai-calibration/approve` (коефициент на ръка) | `ai_calibration_events`, `ai_calibrations` | `ai_proposal.get_ai_proposal` умножава всяка AI цена |
| Часова ставка за офериране | `PUT /ai-config/hourly-rates`; DEMO таблица в кода | `settings[WORKER_RATES]` | `apply_hourly_pricing` (минимална цена на поръчка) |
| Допълнително / липсващо СМР | `POST /extra-works/batch-save`; `POST /missing-smr` | `extra_work_drafts` **и** `missing_smr` | две отделни оферти (`/projects/{id}/smr-aggregated` ги смесва само за преглед) |
| Клиентско одобрение | публичен линк `/offers/review/{token}/respond`; **вътрешен бутон** `PUT /missing-smr/{id}/client-approve` | `offers.*`; `missing_smr.client_approval` | `missing-smr/batch-to-offer` |
| Режийни разходи | `/overhead/costs` (екран „Режийни“); `POST /finance/overhead-transactions` (само API, наречени „legacy“); `PUT /fixed-expenses` (месечна сума); фактура с разпределение „режийни“ | `overhead_costs`, `overhead_transactions`, `fixed_expenses`, `invoices.lines.allocations` | OH-01 snapshot ← `overhead_costs`; финансово табло ← `overhead_transactions`; „режийни на човекоден“ и аларма ← `fixed_expenses` |
| Труд по обект (в справките) | (входовете са в областта ТРУД) | `work_sessions`, `labor_entries`, `pay_runs` | P&L ← work_sessions; печалба по месеци ← labor_entries; финансов резултат ← work_sessions + pay_runs; фирмено табло ← платени фишове |
| Кой е на работа днес | присъствие, календар, дневни отчети, работни сесии | `attendance_entries`, `worker_calendar`, `employee_daily_reports`, `site_daily_rosters`, `work_sessions` | `/dashboard/stats` ← attendance_entries; `/dashboard/personnel-today` ← календар + отчети; пулс/аларми/брифинг ← work_sessions |
| Дневен пулс на обекта | `GET/POST /pulse*` (генерира и запомня) | `site_pulses` (запомнени часове, труд, материали, „има отчет“) | `morning_briefing` (рискове, „липсва отчет“) |
| Аларма | `alarm_engine` (правила), `invoice_allocation` (DQ), ръчно „Потвърди/Реши“ | `alarm_events` | табло аларми, брифинг |
| Фирмен приход/разход (табло) | фактури, `POST /finance/cash-transactions`, `POST /finance/bonus-payments`, overhead_transactions, платени фишове | същите колекции | `FinanceSummaryWidget` (Табло), `FinanceDetailsPage` |
| Осигуровки / „пълна цена на час“ | `PUT /resource-model/config` (32,8%), `PUT /employee-cost-config` (% добавка + % режийни), профил на служителя `insurance_pct` | `resource_model_config`, `settings[EMPLOYEE_COST_CONFIG]`, `employee_profiles` | финансов резултат ← resource_model; `/full-cost` ← settings; `insurance_pct` ← никой |
| Backup | нощен `ops/synology/atlas_backup.sh` | един архив с всички фирми | ръчен `atlas_restore.sh --production` |

## Находки

### PLATFORMA-01: AI цените са в лева, а офертите се правят в евро без превод
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-022 „Преди сравнение системата нормализира: … нето/ДДС/бруто …“ и „Всеки запис пази: … валута и ДДС“. FLOW-046 забранява „измисля цена“.
- Доказателство:
  - `services/ai_proposal.py:227-228,238`: подсказката към модела казва „число_лв … Цените са в лв (BGN)“.
  - `services/ai_proposal.py:15-` (`ACTIVITY_KNOWLEDGE`): вградените цени са в лв.
  - `services/pricing_engine.py:20,100,114,142`: `MATERIAL_PRICES_BGN`, `"currency": "BGN"`.
  - Офертите се правят с `"currency": "EUR"`: `routes/smr_analysis.py:607`, `routes/missing_smr.py:784`, `routes/extra_works.py:68,548`.
  - Числото минава 1:1 (`extra_works.py:487-512`, `missing_smr.py:748-763`). Grep за 1.95583 или превод BGN→EUR не намира нищо.
  - `apply_hourly_pricing` (`extra_works.py:136-169`) сравнява тези левови цени с минимална цена на поръчка, записана в EUR.
- Пример: мазилка 100 m² — AI/базата дава 8,50 + 12,00 = 20,50 „лв“/m². Офертата излиза 2 050 € вместо ≈1 048 €. Ако Крум не види разликата, клиентът получава почти двойна цена (или, обратно, цени от EUR източник се сравняват като левове).
- Известно ли е: НОВО
- Достига ли до екран: да — „Допълнителни СМР“, „Липсващи СМР“ (AI оценка → оферта), „СМР анализ“ (PricingPanel → оферта).

### PLATFORMA-02: „Пазарните цени“ на материалите са измислени — симулирани магазини, случайни числа и фалшиви линкове
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - FLOW-022 „Какво НЕ трябва да позволява: цена без дата, единица и източник; … AI да измисля пазарна стойност при липса на данни“.
  - CLAUDE.md §10 „AI не измисля … цена“ и „Всеки важен отговор има source links“.
- Доказателство:
  - `services/pricing_engine.py:3-4`: „Agent 1: BG retail stores (simulated…)“, „Agent 2 … (simulated)“.
  - `:86-160`: произволен магазин (`random.choice`), цена × `random.uniform(-0.03,0.05)`, „увереност“ също `random.uniform`, линк `https://praktiker.bg/search?q=…`, който кодът сам сглобява.
  - При непознат материал се връща „Практикер (оценка)“ / „Зора Строй (оценка)“ с ±15–20% шум.
  - Медианата се пази в `material_prices` (`:332`).
  - `routes/pricing.py:137-141` я записва като `unit_price` на материала в СМР анализа (`price_source: "live_pricing"`), а от там тя отива в офертата (`smr_analysis.py:548-`).
- Пример: „грунд“ — екранът показва „Практикер 3,87 лв., увереност 0,86, линк“. Нито цената, нито линкът са проверени, а при второ натискане числото е друго.
- Известно ли е: НОВО
- Достига ли до екран: да — `components/PricingPanel.js:39,55`, `pages/MaterialCatalogPage.js:47,59`.

### PLATFORMA-03: AI цената влиза в офертата без човешко потвърждение на цената; при празен отговор AI „измисля“ 10/15
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - CLAUDE.md §10 „Write tools само чрез draft → confirmation → permission → Approval → domain service. AI не измисля ID, цена, количество“.
  - FLOW-022 „AI предлага, но Крум определя продажната цена“.
- Доказателство:
  - `services/ai_proposal.py:280-281`: ако моделът не върне цена → материал 10, труд 15.
  - `routes/missing_smr.py:655-700`: `ai-estimate` записва `ai_estimated_price` без проверка на статуса. Липсващото СМР няма поле за човешка цена, затова `batch-to-offer` (`:748-763`) ползва **само** AI цената и я слага цялата в „труд“ (`material_unit_cost: 0`, `line_labor_cost: price`).
  - `routes/extra_works.py:415-440`: `apply-ai` записва AI цените в черновата (без проверка на статуса). `create-offer` ги взима директно (`:487-512`).
  - `routes/smr_analysis.py:379-433`: `ai-suggest` пише AI цена в анализа и при статус `approved` (спира само `locked`). Одобрението не се анулира.
  - Офертата се създава като `Draft`. Това е единствената спирачка.
- Пример: Липсващо СМР „Шпакловка 8 m²“. AI връща празно → 10 + 15 = 25 „лв“/m² → в офертата излиза 200 € само труд, а материал 0. Справката за труда по обект после показва 200 € труд, които не са труд.
- Известно ли е: НОВО (R67 в AUDIT_LOG покрива само кой може да създаде офертата, не откъде идва цената)
- Достига ли до екран: да — `MissingSMRPage`, „Допълнителни СМР“, „СМР анализ“.

### PLATFORMA-04: „Одобрено от клиента“ се натиска от служител, без доказателство и без цена/версия; после AI сменя цената, а одобрението остава
- Тип: НАРУШЕНИЕ НА FLOW (+ ДУБЛИРАН ВХОД на клиентско одобрение)
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - FLOW-046 §8 „Всяка промяна на цена, количество … изисква ново одобрение. Системата създава tamper-evident ApprovalReceipt с: идентичност / ExternalPrincipal; … exact version/hash; одобрения текст, цена“.
  - CLAUDE.md §8 („клиентско одобрение“ минава през Approval).
- Доказателство:
  - `routes/missing_smr.py:600-623`: `PUT /missing-smr/{id}/client-approve` е достъпен за всеки потребител с модул M2. Записва `decided_by = user["id"]` (служителят, не клиентът). Подписът е по желание. Цената и версията не се записват. Няма AuditEvent.
  - `:655-700`: след това `ai-estimate` презаписва `ai_estimated_price` без проверка на статуса.
  - `:748`: офертата взима новата цена.
  - Офертите имат отделен, истински клиентски път (`routes/offers.py:1560,1631`, публичен линк). Значи има два механизма за едно и също „клиентът одобри“.
- Пример: техникът Петър натиска „Клиентът одобри“ за 3 m² хидроизолация при AI оценка 150 €. После някой натиска „AI оценка“ отново → 290 €. Офертата излиза с 290 €, а в системата пише „одобрено от клиента“.
- Известно ли е: НОВО
- Достига ли до екран: да — `pages/MissingSMRPage.js:325,784` (бутон `client-approve-btn`).

### PLATFORMA-05: Финансовото табло на фирмата брои чернови и анулирани фактури като приход и смесва „начислено“ с „платено“
- Тип: ДУБЛИРАН ЗАПИС (двойно броене)
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО (липсващият филтър по статус и смесването); ВЕРОЯТНО (двойното броене на кеш — потвърждава се с реален запис „касов приход“ за платена фактура)
- Правило: FLOW-015 „Текущо състояние, начислен резултат и прогноза никога не се смесват в една неясна сума“ и „Всяка карта се изчислява от официалните domain регистри“.
- Доказателство:
  - `routes/dashboard.py:343-347` (`company-finance-series`), `:545-546` (`finance-details/summary`), `routes/reports.py:584-587` (`company-finance-summary`): издадените фактури се взимат без филтър по `status`. `Draft` и `Cancelled` влизат като приход. За сравнение `project_pnl.py:32` и `revenue_snapshot.py` ги изключват.
  - Към тях се добавят `cash_transactions` (касов приход/разход, само API, `reports.py:962`), `bonus_payments`, `overhead_transactions` и платените фишове (`dashboard.py:351-390`, `reports.py:615-668`). Получава се сбор от „фактурирано“ и „платено“ в едно число „Нето“.
  - При филтър по обект (`dashboard.py:538-541`) кешът, режийните, заплатите и бонусите **не** се филтрират (`:565-575`). Показват се за цялата фирма.
- Пример:
  - Анулирана фактура 10 000 € към „Обект А“ остава в прихода на месеца.
  - Клиент плаща фактура 5 000 € в брой и счетоводителят я записва и като „касов приход“ → приходът става 10 000 €.
  - Филтър „Обект Б“ показва заплатите на цялата фирма.
- Известно ли е: НОВО (WH81-03 / F-81-01 оправиха само посоката и разпределението на получените фактури)
- Достига ли до екран: да — `components/FinanceSummaryWidget.js:110,130,146` на Таблото и `pages/FinanceDetailsPage.js:150,204`.

### PLATFORMA-06: Режийните имат три отделни входа; таблото чете „legacy“ колекция, която екранът не пълни
- Тип: ДУБЛИРАН ВХОД
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило: Р96 / FLOW-015 „Всяка карта се изчислява от официалните domain регистри“.
- Доказателство:
  - Екранът „Режийни“ пише в `overhead_costs` (`pages/OverheadPage.js:215` → `routes/overhead.py:317`). OH-01 snapshot-ът чете тях (`overhead.py:519`).
  - Фирменото табло чете само `overhead_transactions` (`dashboard.py:376,569,946`; `reports.py:630,774`). Тях ги пише само `POST /finance/overhead-transactions` (`reports.py:1028`), без екран. `full_cost.py:179` ги нарича „legacy“.
  - „Режийни на човекоден“ и алармата „Режийни +X%“ четат трети вход, `fixed_expenses` (`services/overhead_realtime.py:36`). Той се презаписва на място, без история и без AuditEvent (`routes/overhead_realtime.py:229-250`).
  - Фактура, разпределена към режийни, влиза като разход още веднъж (`received_result`).
- Пример: наем 2 000 €/мес., въведен в „Режийни“. На Таблото: режийни 0 €. Ако офисът го въведе и в „фиксирани разходи“, „режийни/човекоден“ отразява наема, а фирменото табло — не. Ако има и фактура за наема, разпределена към режийни, наемът се брои веднъж от фактурата плюс веднъж от всеки ръчен запис.
- Известно ли е: НОВО (OH-01 / FG-89 оправи само P&L по обект)
- Достига ли до екран: да — Табло (`FinanceSummaryWidget`), `WorkerCalendarPage`, `DashboardPage:78` (`/overhead/realtime`).

### PLATFORMA-07: Един и същ обект има различен „труд“ в различните справки
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-015 „Dashboard е read-only управленска проекция, а не втори източник“; Р96.
- Доказателство:
  - `routes/revenue_snapshot.py:144-146,192-198`: „Печалба по месеци“ чете труда от `labor_entries`.
  - `services/project_pnl.py:61-68`: P&L чете от `work_sessions`.
  - `services/project_financial_results.py:50-61`: финансовият резултат чете от `work_sessions` + платените `pay_runs`.
  - Фирменото табло чете от платените фишове (`dashboard.py:383`).
  - Бюджетни аларми и брифинг четат от `work_sessions` (`alarm_engine.py:65`, `morning_briefing.py:50`).
- Пример: Иван работи 10 ч × 20 € на „Обект А“ по дневен отчет. P&L показва труд 200 €. „Печалба по месеци“ показва 0 €, докато някой не пусне `sync-from-work-reports`. При ръчен ред в `labor_entries` за същия ден там излизат 400 €.
- Известно ли е: ИЗВЕСТНО отчасти — Р96 (двата входа `work_reports` / `labor_entries`). Това, че справките четат различни източници, е НОВО.
- Достига ли до екран: да — `ProjectOperationsPage` (печалба по месеци), P&L, финансов резултат.

### PLATFORMA-08: Коефициентът, който умножава всички AI цени, се „учи“ от непроверени данни, а одобрението се трие и презаписва без история
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - CLAUDE.md §2.9 „Няма hard delete на … одобрени записи“.
  - FLOW-022 „историята на старите стойности се пази“.
  - CLAUDE.md §14 (AuditEvent при consequential write).
- Доказателство:
  - `routes/ai_calibration.py:114-157`: `record-edit` записва AI цена и „крайна“ цена, подадени от браузъра. Не се сверява с черновата или офертата. Достъпът е само `require_m2` (всеки потребител с модула).
  - `:324-369`: `approve` взима `factor` от заявката, без граници и без изчисление на сървъра. Прави upsert със `$set`, така че предишното одобрение се губи (ново `id`).
  - `:372-381`: `DELETE` е `delete_one` (hard delete). Никъде няма AuditEvent.
  - `services/ai_proposal.py:346-377`: коефициентът умножава материал и труд на всяка AI оферта.
- Пример: Admin одобрява коефициент 1,8 за „Мазилка / София“ (по погрешка вместо 1,08). Всички AI предложения за мазилка поскъпват с 80%. После коефициентът се трие и не остава следа кой, кога и колко е бил.
- Известно ли е: НОВО
- Достига ли до екран: да — екран „AI калибрация“ (overview/approve/revoke) и всички AI оферти.

### PLATFORMA-09: Едно „допълнително СМР“ се въвежда по две логики (две колекции, два AI, два пътя към оферта)
- Тип: ДУБЛИРАН ВХОД
- Тежест: ПАРИ
- Сигурност: ПОТВЪРДЕНО (двата входа); ВЕРОЯТНО (една и съща работа в две оферти — потвърждава се, като се намери обект с ред и в двете колекции)
- Правило: Р96 „една и съща информация се въвежда по ЕДНА логика“.
- Доказателство:
  - `routes/extra_works.py` (`extra_work_drafts`, `/extra-works/create-offer`) и `routes/missing_smr.py` (`missing_smr`, `/missing-smr/batch-to-offer`) — два входа.
  - Трети път е `smr_analyses → to-offer`.
  - `extra_works.py:684-688` (`smr-aggregated`) изрично „Merges from both extra_work_drafts and missing_smr“, т.е. същият факт стои на две места.
  - Между двете колекции няма проверка за дубликат.
- Пример: техникът записва „Шпакловка, ет. 2, стая 5“ като липсващо СМР. Офисът записва същото като допълнително СМР. Двете стават две отделни оферти към клиента.
- Известно ли е: НОВО (може да се припокрие с областта ТЪРГОВИЯ / ОФЕРТИ)
- Достига ли до екран: да — `MissingSMRPage` и „Допълнителни СМР“.

### PLATFORMA-10: Абонаментният модел в кода е обратен на FLOW-050 (лимити на хора/обекти/фактури, без Grace, данните стават невидими)
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ДАННИ (на практика спира и издаването на фактури)
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - FLOW-050 §6 „Всички пакети включват неограничени Full/Field/External Users и неограничен брой обекти“.
  - §11 „Trial: 14 дни Pro“.
  - §10 „ден 0–7: GRACE; ден 8–14: RESTRICTED; след ден 14: SUSPENDED“.
  - §5 „Downgrade не трие данни: изключените модули остават read-only и исторически видими“.
- Доказателство:
  - `deps/modules.py:13-58`: планове `free/pro/enterprise`, 0/49/149 €, лимити users 3/20/100, projects 2/50/500, monthly_invoices 5/500/5000.
  - Лимитите се прилагат: `enforce_limit` в `routes/auth.py:413,459` (потребители), `routes/projects.py:194` (обекти), `routes/finance.py:851` (фактури).
  - Trial = `free` само с M0/M1/M3 (`:29`), т.е. без оферти и финанси.
  - `:86-90`: при `past_due`/`canceled` всеки модул освен M0 връща 403, включително четенето.
  - `routes/billing.py:610-617`: един неуспешен плащане → веднага `past_due`.
  - Промените на статуса от webhook-а пишат само в лога, без AuditEvent.
- Пример: нова фирма на trial не може да направи оферта (M2) и не може да добави 4-ти човек. Картата на клиент с платен план се отказва веднъж → на следващата минута офертите, финансите и заплатите стават невидими.
- Известно ли е: НОВО
- Достига ли до екран: да — `BillingSettingsPage`; 403 на всички M2/M4/M5/M9 екрани.

### PLATFORMA-11: Три механизма за „какво е включено за фирмата“; превключвателят „Модули“ не прави нищо
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: ДАННИ
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-050 §10 „FLOW-050 остава source of truth за Subscription, Plan, … Entitlements и Access State“; §5 „Runtime достъпът изисква едновременно tenant entitlement и user permission“.
- Доказателство:
  - Реалният пазач е `subscriptions.plan_id` (`deps/modules.py:63-93`).
  - `feature_flags.enabled` за M1–M9 се пише от `PUT /feature-flags` (`routes/auth.py:619-647`), signup (`billing.py:184-194`), checkout/webhook (`billing.py:276,556,595`) и seed (`core/seed.py:96`). Никой бекенд код не го чете за достъп (grep `module_code`: четат се само `report_auto_presence` и офлайн флагът).
  - Seed създава план `enterprise`, но флаговете са включени само за M0 (`core/seed.py:96-104`).
  - Още две мъртви копия: `organizations.subscription_plan/status/expires_at` (`core/seed.py:68-70`, `routes/platform.py:283`) и `tenant_registry.plan/subscription_status` (`tenancy/onboarding.py:133`). Нищо не ги чете и не ги обновява.
  - Проверката „trial изтече“ е копирана три пъти (`deps/modules.py:72-84`, `billing.py:787-801`, `billing.py:829-838`). И трите **пишат** `past_due` при обикновено четене (GET), без AuditEvent.
- Пример: Platform Admin изключва „M5 Финанси“ за фирмата. Екранът показва „изключено“, но счетоводителят продължава да издава фактури, защото пазачът гледа плана.
- Известно ли е: ИЗВЕСТНО отчасти — N2 в AUDIT_LOG („PUT /feature-flags toggles only the Platform Admin's own org“). Това, че флагът изобщо не се чете, е НОВО.
- Достига ли до екран: да — `pages/PlatformModulesPage.js`, `pages/ModuleTogglesPage.js`.

### PLATFORMA-12: „Кой е на работа днес“ се смята от три различни източника на едно и също табло
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: ДАННИ
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-015 „Оперативно табло: хора на работа и липсващи“ + „Всеки показател има … формула и линк към източника“; Р96.
- Доказателство:
  - `routes/overhead.py:150-171` (`/dashboard/stats`): „присъстващи днес“ от `attendance_entries`.
  - `routes/dashboard.py:76-130` (`/dashboard/personnel-today`): от `worker_calendar` + `site_daily_rosters` + `employee_daily_reports`.
  - `services/pulse_generator.py:18-23` и `services/alarm_engine.py:113-127`: „няма хора на обекта“ / „без работници > N дни“ от `work_sessions`. Присъствието (`attendance.py`, `technician.py`) не създава `work_sessions` (writers.tsv).
- Пример: 6 души маркират присъствие на „Обект А“. Картата показва 6 присъстващи, „Персонал днес“ показва 4 (двама без календарен запис). Пулсът и алармата пишат „Няма хора на обекта“, защото никой не е пуснал работна сесия.
- Известно ли е: НОВО
- Достига ли до екран: да — `pages/DashboardPage.js` (stats + `PersonnelTodayCard`), `AlarmsDashboardPage`, `MorningBriefingPanel`.

### PLATFORMA-13: Алармите се затварят, без проблемът да е оправен (автоматично „мигане“ и ръчно „Реши“ от всеки)
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ДАННИ
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-015 „Корекцията се прави в изходния модул, не директно в картата“ и „Всяка аларма има собственик, срок, статус“.
- Доказателство:
  - `services/alarm_engine.py:23-28,87-88`: докато има активна аларма, „cooldown“ не създава нова.
  - `:188-197`: правило с `auto_resolve` и без нови събития затваря **всички** активни аларми на правилото, макар условието още да е вярно. На следващото пускане алармата се отваря наново.
  - `routes/alarms.py:169-183`: `PUT /alarms/{id}/resolve` е достъпен за всеки логнат потребител (`get_current_user`), за всякакъв тип аларма. Това включва DQ алармата „фактура без окончателно разпределение“ (`services/invoice_allocation.py:420-428`), която се вдига отново само при следваща промяна на фактурата. DQ issue-то остава отворено, т.е. алармата и DQ си противоречат.
- Пример: „Обект А: бюджет 112% изхарчен“. На второто оценяване алармата е „решена (auto)“, на третото е нова, и така нататък. Работник натиска „Реши“ на „фактура 1234 без разпределение“ и тя изчезва от таблото.
- Известно ли е: НОВО
- Достига ли до екран: да — `AlarmsDashboardPage`, `NotificationBell`, брифинг.

### PLATFORMA-14: Нощният backup се обявява „OK“ без checksum/manifest; restore на production е с `--drop` на цялата база, без Approval
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: ДАННИ
- Сигурност: ПОТВЪРДЕНО
- Правило:
  - FLOW-044 „Какво НЕ … backup да е „успешен“ без checksum/manifest; restore без version compatibility check“.
  - CLAUDE.md §8 (критична миграция/rollback → Approval).
- Доказателство:
  - `ops/synology/atlas_backup.sh:60,73-80`: `mongodump` на цялата база (всички фирми в един архив), проверка само с `gzip -t`, после „BACKUP OK“. Ротацията трие стари архиви с `find … -delete`.
  - `ops/synology/atlas_restore.sh:45-63`: `--production` иска да се напише „RESTORE PRODUCTION“ и пуска `mongorestore --drop` върху цялата база. Няма Approval, AuditEvent, проверка на версия, нито възстановяване само на една фирма.
- Пример: грешка в една фирма изисква restore → презаписват се всички фирми и се губи всичко, въведено от всички след архива.
- Известно ли е: ИЗВЕСТНО отчасти — `ops/dr/README.md` (W0-10B: off-site, per-tenant restore, drill). Липсата на checksum/manifest в нощния архив и restore без Approval: НОВО.
- Достига ли до екран: не (операторски скриптове).

### PLATFORMA-15: Утринният брифинг чете запомнен „пулс“, не източника
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: НИСКО
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-015 „Не пази отделни „истини“ … Всяка карта се изчислява от официалните domain регистри“.
- Доказателство:
  - `services/pulse_generator.py:159-169` записва в `site_pulses` часове, труд, материали и „отчет подаден“.
  - `services/morning_briefing.py:63-71,111-115` чете тези запомнени стойности за „Без работници“ и „Липсва отчет“.
- Пример: пулсът е генериран в 08:00 („няма отчет“). Отчетът е подаден в 12:00, но брифингът продължава да показва „Липсва отчет“, докато някой не регенерира пулса.
- Известно ли е: НОВО
- Достига ли до екран: да — `MorningBriefingPanel`.

### PLATFORMA-16: `ai-breakdown` пише AI цени дори в заключен анализ, достъпен е за всяка роля и прилага стар кеш
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: НИСКО (полетата `material_cena_per_unit` / `trud_cena_per_unit` не се ползват в оферта; няма UI)
- Сигурност: ПОТВЪРДЕНО
- Правило: CLAUDE.md §10 (draft → confirmation); §2.9 (одобрен/заключен запис не се променя).
- Доказателство:
  - `routes/smr_analysis.py:980-1100`: `get_current_user` (без модул/роля), без проверка на статуса.
  - Кешът е по `analysis_id` и се прилага върху вече променени редове (`:994-1008`).
  - При грешка измисля разбивка 60/40 (`:1078-1092`).
- Пример: заключен анализ за 50 000 € получава нови AI полета материал/труд, без никой да ги потвърди.
- Известно ли е: НОВО
- Достига ли до екран: само API.

### PLATFORMA-17: „Пълна цена на час“ и осигуровки — три настройки, които си противоречат
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: НИСКО
- Сигурност: ВЕРОЯТНО (да се потвърди кой екран Крум реално ползва за себестойност)
- Правило: Р96; FLOW-022 „Цени с различен смисъл не се сравняват директно“.
- Доказателство:
  - `services/resource_model.py:33` (32,8% фирмена ставка) се ползва във финансовия резултат (`services/project_financial_results.py:22-23,184`).
  - `routes/full_cost.py:61-69` смята `/full-cost` с отделни `additional_cost_percent` + `overhead_percent_per_hour` (`settings`).
  - Профилът на служителя пази собствени `insurance_pct` / `insurance_amount` (`routes/hr.py:109-110`), които нищо не чете.
- Пример: за Иван е въведено 18% осигуровки в профила, а финансовият резултат ползва 32,8%. `/full-cost` показва трета сума.
- Известно ли е: НОВО
- Достига ли до екран: да — финансов резултат по обект, „пълна цена“ на служител.

### PLATFORMA-18: Stripe webhook-ът не проверява сума, валута и период
- Тип: НАРУШЕНИЕ НА FLOW
- Тежест: НИСКО (цената идва от фиксиран Stripe price ID)
- Сигурност: ПОТВЪРДЕНО
- Правило: FLOW-050 §10 „webhook-ите … проверяват event ID, сума, валута, tenant и billing period“.
- Доказателство: `routes/billing.py:480-515`. Проверяват се event ID (уникален индекс), фирма, клиент и план, но не сума, валута и период.
- Пример: плащане в грешна валута или за друг период активира плана без предупреждение.
- Известно ли е: НОВО (R0-01 в AUDIT_LOG покрива само подпис, фирма и еднократност)
- Достига ли до екран: само API.

### PLATFORMA-19: Ролите се четат от две места (стар `users.role` и новите RoleAssignments)
- Тип: ВТОРИ ИЗТОЧНИК
- Тежест: НИСКО
- Сигурност: ПОТВЪРДЕНО
- Правило: CLAUDE.md §3 (User → TenantMembership → RoleAssignments → Tenant Guard).
- Доказателство:
  - 112 вградени проверки `user["role"] in [...]` в 35 route файла (напр. `ai_calibration.py:328`, `alarms.py:225`, `overhead_realtime.py:232`, `resource_model.py:50`).
  - Паралелно с тях работи `permissions/service.py` (RoleAssignments) в режим off/shadow/enforce.
- Пример: на Мария е отнета ролята Admin в RoleAssignments, но `users.role` още е „Admin“ → тя може да одобри AI калибрация или да изтрие правило за аларма.
- Известно ли е: ИЗВЕСТНО — W0-02 / PM-01 (PERMISSION_SERVICE_MODE, shadow), OH74 бележка „4 OH-01 routes stay on the legacy role check“.
- Достига ли до екран: да (всички Admin/Owner настройки).

## Не е реализирано (до 10 реда)
1. Физически database-per-tenant: всички фирми са в една база с филтър по `org_id` (`tenancy/onboarding.py` docstring, `database_name = op_db.name`).
2. AI бюджет / AI Usage Ledger по план (Start 100 / Control 500 / Pro 2000) и пауза на AI при 100%.
3. BEG Brain, AI Command Center и специализирани агенти с read-only tools и source links (FLOW-030/031/045).
4. Scenario / What-if engine (FLOW-041): няма код.
5. Client Portal с ExternalPrincipal и ApprovalReceipt (FLOW-046). Има само публичен линк за оферта.
6. Marketplace (FLOW-049): няма код.
7. FLOW-022 база с пазарни цени на труда (Master СМР, регион, min/median/max, източник, дата, срок на актуалност).
8. Dunning ден 0/3/7, състояния GRACE/RESTRICTED/SUSPENDED/SUSPENDED_CHARGEBACK, един trial на ЕИК.
9. Активиране на фирма само след свързан customer-managed storage (onboarding записва `storage_status: not_configured` и фирмата работи).
10. Per-tenant restore, off-site immutable копие и периодичен restore drill (W0-10B).

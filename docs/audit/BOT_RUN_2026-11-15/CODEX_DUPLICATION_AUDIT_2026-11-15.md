# Codex audit — повтарящи се колекции и дублирана бизнес логика

Дата: 2026-11-15  
Статус: read-only статичен одит на кода  
Проверен код: commit 749f69288ea9a57d52991706a1ef29d0b298930e  
Production база: не е достъпвана

## Резюме

Потвърдени са и двата вида дублиране:

1. една бизнес реалност се пази в няколко MongoDB колекции или в два формата;
2. една и съща бизнес логика е реализирана независимо на няколко места.

Това не означава автоматично, че всеки производен запис е грешен. Част от копията са умишлени ledger/materialized записи. Опасният случай е, когато два независими входа могат да променят една и съща бизнес реалност по различни правила или когато няма един каноничен writer.

Статичният одит доказва моделите, writer-ите и различаващите се правила. Той не доказва колко случайни дублирани документи вече има в реалната база.

## 1. Потвърдени паралелни модели и колекции

| Област | Потвърдено състояние | Основен риск | Доказателство |
|---|---|---|---|
| Организации | Една организация може да бъде представена в companies, clients, counterparties и subcontractors с различни ID | една фирма се дублира по роли и плащанията/договорите сочат различни идентичности | backend/app/master_data/legacy_sources.py:233; backend/app/master_data/uniqueness.py:253 |
| Хора | users, persons и employee_profiles представят части от една физическа идентичност | дублирани хора, различни права и трудови профили | docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md:60-80 |
| Persons writers | POST /clients/person и POST /persons записват в persons с различни полета и проверки | различна дедупликация по ЕГН, телефон и имейл | backend/app/routes/clients.py:567-624; backend/app/routes/projects.py:973-996 |
| Companies writers | POST /clients/company и POST /companies записват в companies по различни пътища | различна нормализация и audit поведение | backend/app/routes/clients.py:507-544; backend/app/routes/projects.py:1090-1116 |
| Труд | attendance_entries, employee_daily_reports, work_reports, daily_work_logs и work_sessions описват части от факта „човек работи X часа на обект/ден“ | двойно отчитане, различни часове, ставки и статуси | backend/app/routes/daily_reports.py:1-4 и текущите writer-и в attendance.py, technician.py, work_logs.py и work_sessions.py |
| Две схеми в една колекция | employee_daily_reports поддържа worker_id/date/hours и employee_id/report_date/day_entries | уникалност и approval/payroll логика пропускат другия формат | backend/app/routes/daily_reports.py:72-90 |
| Audit | едновременно се пише в audit_logs и audit_events | непълна audit картина според използвания reader | backend/app/utils/audit.py:88; backend/app/audit/store.py:31 |
| Payroll mirror | pay_runs/payment_slips/pay_run_allocations се оглеждат и в payroll_payment_allocations | физическо копие, което изисква безгрешни sync/reversal правила | backend/app/services/payroll_sync.py:32-92 |

## 2. Умишлени производни записи

Следните копия не са автоматично дефект, но трябва да имат source_id, идемпотентност и reversal:

- work_reports се материализира в labor_entries;
- одобрен employee_daily_report може да създаде work_session;
- payroll данните се материализират в allocation/ledger записи.

Тези записи стават опасни, ако производният writer може да се извика два пъти, ако източникът може да бъде редактиран без reversal или ако различни readers избират различен източник на истина.

## 3. Потвърдена дублирана логика

### 3.1 Присъствие — три различни имплементации

- backend/app/routes/attendance.py:118-156 е каноничният helper: валидира статус, превръща Present в Late след срока, използва уникален ключ и затваря reminders.
- backend/app/routes/technician.py:515-564 прави отделен find/upsert, без същото Late/reminder поведение.
- backend/app/routes/technician.py:1120-1140 създава авто-присъствие от дневен отчет по трети път.

Еднакво действие може да даде различен резултат според екрана.

### 3.2 Часова ставка — две конкуриращи се формули

- backend/app/services/resolve_hourly_rate.py:20-69 е обявеният общ resolver;
- backend/app/routes/work_sessions.py:64-82 има локална формула, която не прилага всички същите приоритети и дели дневната ставка твърдо на 8.

Директен таймер и одобрен отчет могат да формират различна labor_cost за един човек.

### 3.3 Извънреден труд — два алгоритъма

- backend/app/routes/work_sessions.py:91-123 разглежда уикенд, работа след 20:00 и общо над 8 часа;
- backend/app/routes/daily_reports.py:315-357 разглежда основно hours > 8 и има различно поведение за коефициента.

Това влияе пряко върху заплата и P&L.

### 3.4 Плащания — поне четири writers

finance_payments се създава независимо от:

- backend/app/routes/hr.py:274-316 — аванси;
- backend/app/routes/pay_runs.py:1344-1379 — заплати;
- backend/app/routes/subcontractors.py:911-948 — подизпълнители;
- backend/app/routes/finance.py:500-640 — ръчни финансови операции.

Всеки път сам изгражда ledger ред и синхронизира втори domain record. Няма единен Payment write service; това е потвърдено и в docs/architecture/IMPLEMENTATION_WAVES.md:133.

### 3.5 „Изразходван труд“ — различни дефиниции

backend/app/routes/activity_budgets.py използва едновременно:

- офертен line_labor_cost;
- daily_work_logs × ставка;
- work_sessions.labor_cost.

Без едно ясно правило офертна оценка и реален труд могат да се съберат два пъти, а различни endpoints могат да покажат различен actual.

## 4. Конкретни последици, видими в кода

### Платен транш без движение на пари

backend/app/routes/hr.py:902-933 маркира транша като paid и обновява contract_payments, но в този път не създава finance_payments. Така UI/domain статусът може да е „платено“, без движение в касата или банката.

### Анулирана фактура остава разход

backend/app/services/canonical_material_cost.py:301-314 избира invoice_lines по allocation, без да филтрира статуса на родителската фактура. Така ред от Cancelled фактура може да продължи да участва в material_cost и input VAT.

## 5. Какво този одит не доказва

Не е доказан броят на реалните дубликати в production. За това е нужна отделна read-only агрегация по:

- ЕИК/VAT за организации;
- ЕГН, нормализиран телефон и имейл за хора;
- employee + date + project + activity за труд;
- source_type + source_id + amount + date + direction за плащания;
- report/source IDs за payroll и labor mirrors.

## 6. Препоръчан ред

1. Един каноничен Payment write service и забрана за директен finance_payments insert извън него.
2. Един каноничен вход за одобрен труд; останалите входове стават adapters към него.
3. Една формула за ставка, извънреден труд и labor_cost.
4. Един canonical organization/person ID с legacy_refs, а не отделна идентичност за всяка роля.
5. Един audit writer и един reader модел.
6. Уникални индекси и idempotency keys след read-only duplicate report върху възстановено копие.

## Заключение

Дублирането е реално и е основна причина за наблюдаваните несъответствия в пари, труд и P&L. Приоритетът не е механично сливане на колекции, а определяне на един source of truth и един writer за всеки бизнес факт, със строго контролирани производни записи.

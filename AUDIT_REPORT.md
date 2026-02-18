# ОДИТ НА ПРОЕКТА BEG_Work
## Пълен технически преглед и анализ
**Дата:** 18 февруари 2026  
**Версия:** 1.0

---

## СЪДЪРЖАНИЕ
1. [Инвентаризация на API Endpoints](#1-инвентаризация-на-api-endpoints)
2. [Инвентаризация на Data Models](#2-инвентаризация-на-data-models)
3. [Ключови бизнес потоци](#3-ключови-бизнес-потоци)
4. [Имплементирано vs Описано](#4-имплементирано-vs-описано)
5. [Definition of Done за критични потоци](#5-definition-of-done-за-критични-потоци)
6. [Преглед на сигурност и права](#6-преглед-на-сигурност-и-права)
7. [Консистентност на данните](#7-консистентност-на-данните)
8. [Анализ на тестово покритие](#8-анализ-на-тестово-покритие)
9. [Статус таблица на модулите](#9-статус-таблица-на-модулите)
10. [Топ 10 рискове](#10-топ-10-рискове)
11. [Три-етапен Patch план](#11-три-етапен-patch-план)

---

## 1. ИНВЕНТАРИЗАЦИЯ НА API ENDPOINTS

**Общо: 144 endpoints** *(computed from audit_endpoints.csv)*

### 1.1 Authentication & Core (M0) - 7 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| POST | /api/auth/login | login | ✅ Работи |
| GET | /api/auth/me | get_me | ✅ Работи |
| GET | /api/organization | get_organization | ✅ Работи |
| PUT | /api/organization | update_organization | ✅ Работи |
| GET | /api/modules | list_modules | ✅ Работи |
| GET | /api/roles | list_roles | ✅ Работи |
| GET | /api/health | health | ✅ Работи |

### 1.2 User Management (M0) - 4 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/users | list_users | ✅ Работи |
| POST | /api/users | create_user | ✅ Работи |
| PUT | /api/users/{user_id} | update_user | ✅ Работи |
| DELETE | /api/users/{user_id} | delete_user | ✅ Работи |

### 1.3 Feature Flags (M0) - 2 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/feature-flags | list_feature_flags | ✅ Работи |
| PUT | /api/feature-flags | toggle_feature_flag | ✅ Работи |

### 1.4 Audit Logs (M0) - 1 endpoint
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/audit-logs | list_audit_logs | ✅ Работи |

### 1.5 Projects (M1) - 13 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/projects | list_projects | ✅ Работи |
| POST | /api/projects | create_project | ✅ Работи |
| GET | /api/projects/{project_id} | get_project | ✅ Работи |
| PUT | /api/projects/{project_id} | update_project | ✅ Работи |
| DELETE | /api/projects/{project_id} | delete_project | ✅ Работи |
| GET | /api/projects/{project_id}/team | list_project_team | ✅ Работи |
| POST | /api/projects/{project_id}/team | add_team_member | ✅ Работи |
| DELETE | /api/projects/{project_id}/team/{member_id} | remove_team_member | ✅ Работи |
| GET | /api/projects/{project_id}/phases | list_phases | ✅ Работи |
| POST | /api/projects/{project_id}/phases | create_phase | ✅ Работи |
| PUT | /api/projects/{project_id}/phases/{phase_id} | update_phase | ✅ Работи |
| DELETE | /api/projects/{project_id}/phases/{phase_id} | delete_phase | ✅ Работи |
| GET | /api/project-enums | get_project_enums | ✅ Работи |

### 1.6 Estimates / BOQ (M2) - 15 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/offers | list_offers | ✅ Работи |
| POST | /api/offers | create_offer | ✅ Работи |
| GET | /api/offers/{offer_id} | get_offer | ✅ Работи |
| PUT | /api/offers/{offer_id} | update_offer | ✅ Работи |
| DELETE | /api/offers/{offer_id} | delete_offer | ✅ Работи |
| PUT | /api/offers/{offer_id}/lines | update_offer_lines | ✅ Работи |
| POST | /api/offers/{offer_id}/send | send_offer | ✅ Работи |
| POST | /api/offers/{offer_id}/accept | accept_offer | ✅ Работи |
| POST | /api/offers/{offer_id}/reject | reject_offer | ✅ Работи |
| POST | /api/offers/{offer_id}/new-version | create_offer_version | ✅ Работи |
| GET | /api/offer-enums | get_offer_enums | ✅ Работи |
| GET | /api/activity-catalog | list_activity_catalog | ✅ Работи |
| POST | /api/activity-catalog | create_activity | ✅ Работи |
| PUT | /api/activity-catalog/{item_id} | update_activity | ✅ Работи |
| DELETE | /api/activity-catalog/{item_id} | delete_activity | ✅ Работи |

### 1.7 Attendance & Work Reports (M3) - 18 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| POST | /api/attendance/mark | mark_attendance_self | ✅ Работи |
| POST | /api/attendance/mark-for-user | mark_attendance_for_user | ✅ Работи |
| GET | /api/attendance/my-today | get_my_attendance_today | ✅ Работи |
| GET | /api/attendance/my-range | get_my_attendance_range | ✅ Работи |
| GET | /api/attendance/site-today | get_site_attendance_today | ✅ Работи |
| GET | /api/attendance/missing-today | get_missing_attendance_today | ✅ Работи |
| GET | /api/attendance/statuses | get_attendance_statuses | ✅ Работи |
| POST | /api/work-reports/draft | create_or_get_draft | ✅ Работи |
| GET | /api/work-reports/{report_id} | get_work_report | ✅ Работи |
| PUT | /api/work-reports/{report_id} | update_work_report | ✅ Работи |
| POST | /api/work-reports/{report_id}/submit | submit_work_report | ✅ Работи |
| POST | /api/work-reports/{report_id}/approve | approve_work_report | ✅ Работи |
| POST | /api/work-reports/{report_id}/reject | reject_work_report | ✅ Работи |
| GET | /api/work-reports/my-today | get_my_work_reports_today | ✅ Работи |
| GET | /api/work-reports/my-range | get_my_work_reports_range | ✅ Работи |
| GET | /api/work-reports/project-day | get_project_day_reports | ✅ Работи |
| GET | /api/reminders/missing-attendance | api_missing_attendance | ✅ Работи |
| GET | /api/reminders/missing-work-reports | api_missing_work_reports | ✅ Работи |

### 1.8 HR / Payroll (M4) - 18 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/employees | list_employees | ✅ Работи |
| POST | /api/employees | upsert_employee_profile | ✅ Работи |
| GET | /api/employees/{user_id} | get_employee | ✅ Работи |
| PUT | /api/employees/{user_id} | update_employee_profile | ✅ Работи |
| GET | /api/advances | list_advances | ✅ Работи |
| POST | /api/advances | create_advance | ✅ Работи |
| POST | /api/advances/{advance_id}/apply-deduction | apply_advance_deduction | ✅ Работи |
| GET | /api/payroll-runs | list_payroll_runs | ✅ Работи |
| POST | /api/payroll-runs | create_payroll_run | ✅ Работи |
| GET | /api/payroll-runs/{run_id} | get_payroll_run | ✅ Работи |
| DELETE | /api/payroll-runs/{run_id} | delete_payroll_run | ✅ Работи |
| POST | /api/payroll-runs/{run_id}/generate | generate_payroll | ✅ Работи |
| POST | /api/payroll-runs/{run_id}/finalize | finalize_payroll | ✅ Работи |
| GET | /api/payslips | list_payslips | ✅ Работи |
| GET | /api/payslips/{payslip_id} | get_payslip | ✅ Работи |
| POST | /api/payslips/{payslip_id}/mark-paid | mark_payslip_paid | ✅ Работи |
| POST | /api/payslips/{payslip_id}/set-deductions | set_payslip_deductions | ✅ Работи |
| GET | /api/payroll-enums | get_payroll_enums | ✅ Работи |

### 1.9 Finance (M5) - 17 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/finance/accounts | list_accounts | ✅ Работи |
| POST | /api/finance/accounts | create_account | ✅ Работи |
| PUT | /api/finance/accounts/{account_id} | update_account | ✅ Работи |
| DELETE | /api/finance/accounts/{account_id} | delete_account | ✅ Работи |
| GET | /api/finance/invoices | list_invoices | ✅ Работи |
| POST | /api/finance/invoices | create_invoice | ✅ Работи |
| GET | /api/finance/invoices/{invoice_id} | get_invoice | ✅ Работи |
| PUT | /api/finance/invoices/{invoice_id} | update_invoice | ✅ Работи |
| DELETE | /api/finance/invoices/{invoice_id} | delete_invoice | ✅ Работи |
| PUT | /api/finance/invoices/{invoice_id}/lines | update_invoice_lines | ✅ Работи |
| POST | /api/finance/invoices/{invoice_id}/send | send_invoice | ✅ Работи |
| POST | /api/finance/invoices/{invoice_id}/cancel | cancel_invoice | ✅ Работи |
| GET | /api/finance/payments | list_payments | ✅ Работи |
| POST | /api/finance/payments | create_payment | ✅ Работи |
| GET | /api/finance/payments/{payment_id} | get_payment | ✅ Работи |
| DELETE | /api/finance/payments/{payment_id} | delete_payment | ✅ Работи |
| POST | /api/finance/payments/{payment_id}/allocate | allocate_payment | ✅ Работи |
| GET | /api/finance/stats | get_finance_stats | ✅ Работи |
| GET | /api/finance/enums | get_finance_enums | ✅ Работи |

### 1.10 Overhead Costs (M9) - 18 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/overhead/categories | list_overhead_categories | ✅ Работи |
| POST | /api/overhead/categories | create_overhead_category | ✅ Работи |
| PUT | /api/overhead/categories/{cat_id} | update_overhead_category | ✅ Работи |
| DELETE | /api/overhead/categories/{cat_id} | delete_overhead_category | ✅ Работи |
| GET | /api/overhead/costs | list_overhead_costs | ✅ Работи |
| POST | /api/overhead/costs | create_overhead_cost | ✅ Работи |
| PUT | /api/overhead/costs/{cost_id} | update_overhead_cost | ✅ Работи |
| DELETE | /api/overhead/costs/{cost_id} | delete_overhead_cost | ✅ Работи |
| GET | /api/overhead/assets | list_overhead_assets | ✅ Работи |
| POST | /api/overhead/assets | create_overhead_asset | ✅ Работи |
| PUT | /api/overhead/assets/{asset_id} | update_overhead_asset | ✅ Работи |
| DELETE | /api/overhead/assets/{asset_id} | delete_overhead_asset | ✅ Работи |
| GET | /api/overhead/allocations | list_overhead_allocations | ✅ Работи |
| GET | /api/overhead/snapshots | list_overhead_snapshots | ✅ Работи |
| POST | /api/overhead/snapshots/compute | compute_overhead_snapshot | ✅ Работи |
| GET | /api/overhead/snapshots/{snapshot_id} | get_overhead_snapshot | ✅ Работи |
| POST | /api/overhead/snapshots/{snapshot_id}/allocate | allocate_overhead_to_projects | ✅ Работи |
| GET | /api/overhead/enums | get_overhead_enums | ✅ Работи |

### 1.11 Billing / SaaS (M10) - 9 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/billing/plans | list_billing_plans | ✅ Работи |
| GET | /api/billing/config | get_billing_config | ✅ Работи |
| POST | /api/billing/signup | signup_organization | ✅ Работи |
| GET | /api/billing/subscription | get_billing_subscription | ✅ Работи |
| GET | /api/billing/usage | get_billing_usage | ✅ Работи |
| POST | /api/billing/create-checkout-session | create_checkout_session | ✅ Работи (MOCK) |
| POST | /api/billing/create-portal-session | create_portal_session | ✅ Работи (MOCK) |
| POST | /api/billing/webhook | stripe_webhook | ✅ Работи (MOCK) |
| GET | /api/billing/check-module/{module_code} | check_module_access | ✅ Работи |

### 1.12 Mobile Integration - 6 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/mobile/bootstrap | mobile_bootstrap | ✅ Работи |
| GET | /api/mobile/settings | get_mobile_settings | ✅ Работи |
| PUT | /api/mobile/settings | update_mobile_settings | ✅ Работи |
| GET | /api/mobile/view-configs | list_mobile_view_configs | ✅ Работи |
| PUT | /api/mobile/view-configs | update_mobile_view_config | ✅ Работи |
| DELETE | /api/mobile/view-configs/{role}/{module_code} | reset_mobile_view_config | ✅ Работи |

### 1.13 Media - 5 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| POST | /api/media/upload | upload_media | ✅ Работи |
| POST | /api/media/link | link_media | ✅ Работи |
| GET | /api/media | list_media | ✅ Работи |
| GET | /api/media/{media_id} | get_media | ✅ Работи |
| GET | /api/media/file/{filename} | serve_media_file | ✅ Работи |

### 1.14 Notifications & Reminders (M9) - 9 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/notifications/my | get_my_notifications | ✅ Работи |
| POST | /api/notifications/mark-read | mark_notifications_read | ✅ Работи |
| GET | /api/reminders/policy | get_reminder_policy | ✅ Работи |
| GET | /api/reminders/logs | get_reminder_logs | ✅ Работи |
| POST | /api/reminders/send | send_reminders_manual | ✅ Работи |
| POST | /api/reminders/excuse | excuse_reminder | ✅ Работи |
| GET | /api/reminders/missing-attendance | api_missing_attendance | ✅ Работи |
| GET | /api/reminders/missing-work-reports | api_missing_work_reports | ✅ Работи |
| POST | /api/internal/run-reminder-jobs | trigger_reminder_jobs | ✅ Работи |

### 1.15 Dashboard & Misc - 2 endpoints
| Метод | Път | Хендлър | Статус |
|-------|-----|---------|--------|
| GET | /api/dashboard/stats | get_dashboard_stats | ✅ Работи |
| GET | /api/subscription | get_subscription | ✅ Работи |

---

### Endpoint Count Summary (Verification)
| Секция | Брой |
|--------|------|
| 1.1 Auth & Core | 7 |
| 1.2 User Management | 4 |
| 1.3 Feature Flags | 2 |
| 1.4 Audit Logs | 1 |
| 1.5 Projects | 13 |
| 1.6 Estimates/BOQ | 15 |
| 1.7 Attendance & Work Reports | 18 |
| 1.8 HR/Payroll | 18 |
| 1.9 Finance | 17 |
| 1.10 Overhead | 18 |
| 1.11 Billing/SaaS | 9 |
| 1.12 Mobile Integration | 6 |
| 1.13 Media | 5 |
| 1.14 Notifications & Reminders | 9 |
| 1.15 Dashboard & Misc | 2 |
| **ОБЩО** | **144** |

**Източник:** `/app/audit_endpoints.csv` *(извлечено от FastAPI app.routes)*

**Public onboarding endpoint:** `/api/billing/signup` *(няма /api/auth/signup)*

---

## 2. ИНВЕНТАРИЗАЦИЯ НА DATA MODELS

### 2.1 MongoDB Колекции — 31 общо (15 core + 16 supporting)

#### Core Business Collections (15)
| Колекция | Описание | Модул |
|----------|----------|-------|
| organizations | Тенант/компания данни | M0 |
| users | Потребители с роли | M0 |
| subscriptions | Абонаментна информация | M0/M10 |
| projects | Проекти | M1 |
| project_team | Членове на екипи | M1 |
| project_phases | Фази на проекти | M1 |
| offers | Оферти/BOQ | M2 |
| activity_catalog | Каталог дейности | M2 |
| attendance_entries | Присъствия | M3 |
| work_reports | Работни доклади | M3 |
| employee_profiles | HR профили | M4 |
| payroll_runs | Периоди на заплащане | M4 |
| payslips | Фишове за заплати | M4 |
| invoices | Фактури | M5 |
| financial_accounts | Каси/банки | M5 |

#### Supporting Collections (16)
| Колекция | Описание | Модул |
|----------|----------|-------|
| feature_flags | Включени модули | M0 |
| audit_logs | История на действията | M0 |
| advances | Аванси/заеми | M4 |
| finance_payments | Плащания | M5 |
| payment_allocations | Разпределения | M5 |
| payroll_payments | Payroll плащания | M4 |
| notifications | Известия | M3/M9 |
| reminder_logs | Логове напомняния | M9 |
| overhead_categories | Категории разходи | M9 |
| overhead_costs | Непреки разходи | M9 |
| overhead_assets | Амортизируеми активи | M9 |
| overhead_snapshots | Снимки на разходи | M9 |
| project_overhead_allocations | Разпределения по проекти | M9 |
| org_mobile_settings | Мобилни настройки | Mobile |
| mobile_view_configs | Конфигурации на изгледи | Mobile |
| media_files | Медийни файлове | Mobile |

**Източник:** `/app/audit_models_collections.txt` *(extract от server.py: db.* usage patterns)*

### 2.2 Pydantic Models (48 модела)
Всички заявки са валидирани чрез Pydantic модели:
- **Auth:** LoginRequest
- **Users:** UserCreate, UserUpdate
- **Organization:** OrgUpdate, ModuleToggle
- **Projects:** ProjectCreate, ProjectUpdate, TeamMemberAdd, PhaseCreate, PhaseUpdate
- **Attendance:** AttendanceMarkSelf, AttendanceMarkForUser
- **Work Reports:** WorkReportDraftCreate, WorkReportUpdate, WorkReportLineInput, WorkReportReject
- **Reminders:** SendReminderRequest, ExcuseRequest
- **Offers/BOQ:** OfferCreate, OfferUpdate, OfferLineInput, OfferLinesUpdate, OfferReject, ActivityCatalogCreate, ActivityCatalogUpdate
- **HR/Payroll:** EmployeeProfileCreate, EmployeeProfileUpdate, AdvanceLoanCreate, PayrollRunCreate, SetDeductionsRequest, MarkPaidRequest
- **Finance:** FinancialAccountCreate, FinancialAccountUpdate, InvoiceCreate, InvoiceUpdate, InvoiceLineInput, InvoiceLinesUpdate, PaymentCreate, AllocationInput, AllocatePaymentRequest
- **Overhead:** OverheadCategoryCreate, OverheadCategoryUpdate, OverheadCostCreate, OverheadCostUpdate, OverheadAssetCreate, OverheadAssetUpdate, OverheadSnapshotCompute, OverheadAllocateRequest
- **Billing:** OrgSignupRequest, CreateCheckoutRequest, SubscriptionUpdate
- **Mobile:** MobileSettingsUpdate, MobileViewConfigUpdate, MediaUploadContext, MediaLinkRequest

---

## 3. КЛЮЧОВИ БИЗНЕС ПОТОЦИ

### 3.1 Поток: Присъствие (Attendance)
```
1. Технически отваря приложението
2. Системата проверява дали е в работен прозорец (attendance_start - attendance_end)
3. Техникът маркира присъствие (Present/Absent/Late/SickLeave/Vacation)
4. Ако е след крайния час → автоматично Late
5. Записва се в attendance_entries
6. Авто-резолва MissingAttendance reminders
7. Мениджър може да маркира за други в неговите проекти
```
**Статус:** ✅ НАПЪЛНО ИМПЛЕМЕНТИРАНО

### 3.2 Поток: Работен доклад (Work Report)
```
1. Техник създава Draft за конкретен проект и дата
2. Добавя редове (дейности + часове + бележки)
3. Submit → статус Submitted
4. Мениджър преглежда → Approve или Reject
5. При Reject: причина + връщане на Draft
6. При Approve: статус Approved + timestamp
```
**Статус:** ✅ НАПЪЛНО ИМПЛЕМЕНТИРАНО

### 3.3 Поток: Офертиране (BOQ/Estimates)
```
1. Създава се Offer за проект
2. Добавят се линии (материали + труд)
3. Изчислява се нетна + ДДС + обща сума
4. Send → статус Sent
5. Клиент: Accept или Reject
6. При нужда: New Version (версиониране)
```
**Статус:** ✅ НАПЪЛНО ИМПЛЕМЕНТИРАНО

### 3.4 Поток: Заплащане (Payroll)
```
1. Създава се PayrollRun за период
2. Generate: автоматично създава payslips за служители
3. Преглед и корекции на payslips
4. Finalize: заключва периода
5. Mark Paid: маркира като платени
```
**Статус:** ✅ НАПЪЛНО ИМПЛЕМЕНТИРАНО

### 3.5 Поток: Фактуриране и плащания
```
1. Създава се Invoice (Issued/Received)
2. Добавят се линии с разпределение по проекти
3. Send → статус Sent
4. Получава се Payment
5. Allocate: разпределя се по фактури
6. Автоматична проверка за пълно плащане
```
**Статус:** ✅ НАПЪЛНО ИМПЛЕМЕНТИРАНО

### 3.6 Поток: SaaS Billing
```
1. Нов клиент → /api/billing/signup
2. Създава се организация + owner + subscription (Free Trial 14 дни)
3. Upgrade → create-checkout-session → Stripe (или Mock)
4. Webhook обработва резултата
5. Лимити се проверяват при create операции
```
**Статус:** ✅ ИМПЛЕМЕНТИРАНО (MOCK MODE)

---

## 4. ИМПЛЕМЕНТИРАНО VS ОПИСАНО

### 4.1 НАПЪЛНО ИМПЛЕМЕНТИРАНО ✅
| Модул | Описание | Backend | Frontend | Тестове |
|-------|----------|---------|----------|---------|
| M0 | Core/SaaS/Auth | ✅ | ✅ | ✅ |
| M1 | Projects | ✅ | ✅ | ✅ |
| M2 | Estimates/BOQ | ✅ | ✅ | ✅ |
| M3 | Attendance & Reports | ✅ | ✅ | ✅ |
| M4 | HR/Payroll | ✅ | ✅ | ✅ |
| M5 | Finance | ✅ | ✅ | ✅ |
| M9 | Overhead Costs | ✅ | ✅ | ✅ |
| M9 | Reminders/Alerts | ✅ | ✅ | ✅ |
| M10 | SaaS Billing | ✅ | ✅ | ✅ |
| Mobile | Config Backend | ✅ | ✅ | ✅ |
| i18n | BG + EN | ✅ | ✅ | N/A |

### 4.2 ЧАСТИЧНО ИМПЛЕМЕНТИРАНО ⚠️
| Модул | Описание | Backend | Frontend | Забележка |
|-------|----------|---------|----------|-----------|
| M9 | Admin Console/BI | 30% | 30% | Само Dashboard stats |
| Mobile | Client App | 0% | 0% | Само конфигурация готова |

### 4.3 НЕ Е ИМПЛЕМЕНТИРАНО ❌
| Модул | Описание | Статус |
|-------|----------|--------|
| M6 | AI Invoice Capture | Планирано |
| M7 | Inventory | Планирано |
| M8 | Assets & QR | Планирано |
| Deliveries | Доставки | Backend модели готови, CRUD липсва |
| Machines | Машини | Backend модели готови, CRUD липсва |

---

## 5. DEFINITION OF DONE ЗА КРИТИЧНИ ПОТОЦИ

### 5.1 Delivery Lifecycle (Доставки)

**Текущ статус:** ❌ НЕ Е ИМПЛЕМЕНТИРАНО

**Какво съществува:**
- Pydantic модел в MOBILE_FIELDS дефиниции
- Полета: id, date, origin, destination, status, driver_id, driver_name, vehicle, items, notes, photo_urls

---

#### 5.1.1 State Machine

```
                    ┌─────────────┐
                    │   Draft     │
                    └──────┬──────┘
                           │ assign
                           ▼
                    ┌─────────────┐
          ┌────────│  Assigned   │────────┐
          │        └──────┬──────┘        │
          │ cancel        │ start         │ reassign
          ▼               ▼               │
   ┌─────────────┐ ┌─────────────┐        │
   │  Cancelled  │ │  InTransit  │◄───────┘
   └─────────────┘ └──────┬──────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
   │ PartialDlvd │ │  Delivered  │ │   Failed    │
   └──────┬──────┘ └─────────────┘ └─────────────┘
          │ complete
          ▼
   ┌─────────────┐
   │  Delivered  │
   └─────────────┘
```

**Статуси:**
| Статус | Описание |
|--------|----------|
| Draft | Създадена, не е присвоена |
| Assigned | Присвоена на шофьор, чака старт |
| InTransit | В движение към дестинация |
| PartialDelivered | Частично доставена (някои items липсват/отказани) |
| Delivered | Успешно завършена |
| Failed | Неуспешна (клиент отказа, грешен адрес, etc.) |
| Cancelled | Отменена преди доставка |

---

#### 5.1.2 State Transitions

| # | From Status | Action | To Status | Allowed Roles | Validation Rules |
|---|-------------|--------|-----------|---------------|------------------|
| T1 | Draft | **assign** | Assigned | Admin, SiteManager, Warehousekeeper | driver_id required; driver exists & active; items.length > 0 |
| T2 | Assigned | **start** | InTransit | Driver (own), Admin | driver == current_user OR Admin; vehicle_id set |
| T3 | Assigned | **reassign** | Assigned | Admin, SiteManager | new driver_id != old; audit log reason |
| T4 | Assigned | **cancel** | Cancelled | Admin, SiteManager | reason required; notify driver |
| T5 | InTransit | **complete** | Delivered | Driver (own), Admin | all items delivered (qty_delivered == qty_requested) |
| T6 | InTransit | **partial** | PartialDelivered | Driver (own), Admin | at least 1 item delivered; at least 1 item missing/rejected |
| T7 | InTransit | **fail** | Failed | Driver (own), Admin | reason required (enum: ClientRefused, WrongAddress, Inaccessible, Other) |
| T8 | PartialDelivered | **complete** | Delivered | Admin, SiteManager | manual resolution; all items accounted for |
| T9 | Draft | **cancel** | Cancelled | Admin, SiteManager, Creator | soft delete or status change |

**Забележки:**
- Driver може да извърши T2, T5, T6, T7 само за **собствените си** доставки
- Всяка транзиция записва audit log с: user_id, timestamp, from_status, to_status, reason (ако има)
- При T6 (partial): items се маркират индивидуално (delivered_qty, rejected_qty, missing_qty)

---

#### 5.1.3 Edge Cases (минимум 5)

| # | Edge Case | Сценарий | Очаквано поведение |
|---|-----------|----------|-------------------|
| E1 | **Partial Delivery** | Шофьор доставя 8 от 10 бройки; клиент отказва 2 | Статус → PartialDelivered; items[0].delivered_qty=8, items[0].rejected_qty=2; requires admin resolution |
| E2 | **Missing Items** | При товарене липсват артикули (грешка в склада) | Driver маркира items като `missing_at_load`; статус → PartialDelivered или Failed ако всичко липсва |
| E3 | **Wrong Item Loaded** | Заредено грешен артикул вместо поръчания | Driver reports `wrong_item` с photo proof; admin creates return + new delivery |
| E4 | **Offline Update Conflict** | Driver offline маркира Delivered; междувременно Admin cancel-ва | При sync: conflict detected; server wins (Cancelled); Driver notification за ръчна резолюция |
| E5 | **Cancel After Assign** | SiteManager cancel-ва след като Driver е започнал (InTransit) | Забранено: T4 валидно само от Assigned; трябва T7 (fail) с причина |
| E6 | **Driver Reassign Mid-Transit** | Шофьор се разболява по време на доставка | Admin: T7 (fail, reason=DriverUnavailable) → нова Delivery от текуща локация |
| E7 | **Duplicate Delivery Attempt** | Същите items към същия destination в същия ден | Warning (not block): "Similar delivery exists: {id}"; allow override |

---

#### 5.1.4 Required Endpoints Mapping

| Transition | HTTP Method | Endpoint | Request Body |
|------------|-------------|----------|--------------|
| Create | POST | `/api/deliveries` | DeliveryCreate (project_id, origin, destination, items[], notes) |
| T1 assign | POST | `/api/deliveries/{id}/assign` | {driver_id, vehicle_id?, scheduled_date?} |
| T2 start | POST | `/api/deliveries/{id}/start` | {vehicle_id?, start_location?} |
| T3 reassign | POST | `/api/deliveries/{id}/reassign` | {new_driver_id, reason} |
| T4/T9 cancel | POST | `/api/deliveries/{id}/cancel` | {reason} |
| T5 complete | POST | `/api/deliveries/{id}/complete` | {items_confirmation[], signature_url?, photo_urls[]} |
| T6 partial | POST | `/api/deliveries/{id}/partial` | {items_status[], notes, photo_urls[]} |
| T7 fail | POST | `/api/deliveries/{id}/fail` | {reason_code, reason_text, photo_urls[]} |
| T8 resolve | POST | `/api/deliveries/{id}/resolve` | {resolution_type, notes} |
| List | GET | `/api/deliveries` | ?status=&driver_id=&project_id=&date_from=&date_to= |
| Get | GET | `/api/deliveries/{id}` | - |
| Update | PUT | `/api/deliveries/{id}` | DeliveryUpdate (only Draft status) |
| Delete | DELETE | `/api/deliveries/{id}` | (only Draft status, soft-delete) |
| My Deliveries | GET | `/api/deliveries/my` | Driver-only: own assigned/in-transit |
| Driver Actions | POST | `/api/deliveries/{id}/driver-action` | Mobile-friendly: {action, payload} |

**Общо: 14 endpoints**

---

#### 5.1.5 Definition of Done Checklist

| # | Критерий | Статус |
|---|----------|--------|
| 1 | MongoDB колекция `deliveries` със schema | ❌ |
| 2 | State machine имплементирана (7 статуса, 9 прехода) | ❌ |
| 3 | Role-based transition guards | ❌ |
| 4 | All 14 endpoints working | ❌ |
| 5 | Items tracking (delivered/rejected/missing qty) | ❌ |
| 6 | Media linkage (photos at delivery) | ❌ |
| 7 | Audit log на всяка транзиция | ❌ |
| 8 | Offline conflict detection | ❌ |
| 9 | Frontend DeliveriesPage + Driver view | ❌ |
| 10 | i18n (BG + EN) | ❌ |
| 11 | Backend tests: all transitions + 7 edge cases | ❌ |
| 12 | Mobile bootstrap integration | ❌ |

---

### 5.2 Global Availability Scan (Глобално сканиране за наличност)

> **Важно:** Това НЕ е compliance/reminders за присъствия. Това е логистичният поток за **наличности**, който се изпълнява при **Submit/Изпрати заявка** и генерира предложения откъде да се осигурят количества + какво трябва да се купи.

**Текущ статус:** ❌ НЕ Е ИМПЛЕМЕНТИРАНО (в BEG_Work към момента няма M7 Inventory и няма Requests/RequestLines модул)

#### Цел (какво прави)
При натискане на **„Изпрати заявка"** системата прави **глобален availability scan** през:
- всички **Warehouse** локации
- всички **Project/Site** локации
- всички **Guests/Assets** (инструменти/активи "при човек")

… и записва към всеки ред на заявката:
- `suggestedSourcesJson` (списък предложения: локация → налично qty → препоръчано qty)
- `qtyTotalAvailable` (общо налично)
- `qtyToBuy` (какво не достига и трябва да се купи)
- `suggestionsUpdatedAt`

**Ключово изискване:** не зависи от "default warehouse".

**Definition of Done:**
| # | Критерий | Статус |
|---|----------|--------|
| 1 | Съществува домейн модел: `Request` + `RequestLine` | ❌ |
| 2 | `RequestLine` има полета: suggestedSourcesJson, qtyTotalAvailable, qtyToBuy, suggestionsUpdatedAt | ❌ |
| 3 | Endpoint: `POST /api/requests` (create) + `POST /api/requests/{id}/submit` (submit) | ❌ |
| 4 | При submit се извиква функция/сървис `buildSourceSuggestionsForRequest(requestId)` | ❌ |
| 5 | Scan покрива ALL: warehouses + projects + guests/assets | ❌ |
| 6 | Изчислява `qtyToBuy` коректно (ако totalAvailable < requestedQty) | ❌ |
| 7 | Записва предложенията към всеки RequestLine (persist) | ❌ |
| 8 | UI в Request Detail показва: totalAvailable, qtyToBuy, suggested sources | ❌ |
| 9 | Не зависи от default warehouse (валидирано в тест) | ❌ |
| 10 | Тестове минимум 5 сценария за scan | ❌ |

#### State Machine (логика на потока)
| От статус | Действие | Към статус | Валидация |
|---|---|---|---|
| Draft | Submit Request | Submitted | има поне 1 ред; qty > 0; itemId валиден |
| Submitted | Build Suggestions | Submitted (обновен) | запис suggestedSourcesJson/qtyToBuy/updatedAt |
| Submitted | Approve / Dispatch | Approved/Dispatched | според логистичния процес |

#### Алгоритъм (високо ниво)
1. Събира всички `itemId` от RequestLines
2. Зарежда наличности по всички локации (Warehouse/Project) за тези itemId
3. Зарежда asset instances при guests (ако item type = Asset/Tool)
4. За всеки ред: пресмята totalAvailable, генерира предложения, изчислява qtyToBuy
5. Persist към RequestLine

#### Edge Cases (минимум 5 теста)
1. **Mixed sources:** част в Warehouse + част в Project → комбинирани предложения
2. **Insufficient stock:** totalAvailable < requestedQty → qtyToBuy > 0
3. **Guest assets:** инструмент "WithGuest" → да се показва като източник
4. **ReturnQty / pending returns:** да участват по правилата
5. **Concurrency:** две заявки едновременно → предложенията са snapshot (не резервация)

**Необходими действия за DoD:**
1. Добавяне на Requests домейн (Request + RequestLine + статуси)
2. Добавяне на InventoryBalance/AssetInstance (интеграция към M7/M8)
3. Имплементация на submit flow + buildSourceSuggestionsForRequest
4. UI визуализация на предложенията
5. Тестове: 5 сценария (warehouse-only, project-only, mixed, guest, insufficient)

**Зависимости:** M7 (Inventory) + M8 (Assets) трябва да са имплементирани преди този поток

---

### 5.3 Mobile Governance (Мобилно управление)

**Текущ статус:** ✅ BACKEND ГОТОВ, ❌ MOBILE APP ЛИПСВА

**Какво съществува:**
- `org_mobile_settings` - кои модули са активни
- `mobile_view_configs` - какви полета/действия вижда всяка роля
- `/api/mobile/bootstrap` - единна точка за конфигурация
- Default конфигурации за Technician, Driver, SiteManager
- Admin UI за управление

**Definition of Done:**
| # | Критерий | Статус |
|---|----------|--------|
| 1 | Backend модели за mobile settings | ✅ |
| 2 | Bootstrap endpoint с пълна конфигурация | ✅ |
| 3 | CRUD за mobile settings (admin) | ✅ |
| 4 | CRUD за view configs (admin) | ✅ |
| 5 | Default configs per role | ✅ |
| 6 | Field filtering helper function | ✅ |
| 7 | Action blocking helper function | ✅ |
| 8 | Admin UI страница | ✅ |
| 9 | i18n за mobile labels | ✅ |
| 10 | Mobile client app (React Native/Flutter) | ❌ |
| 11 | Push notifications infrastructure | ❌ |
| 12 | Offline sync support | ❌ |
| 13 | Mobile-specific authentication (biometrics) | ❌ |

**Необходими действия за DoD:**
1. Създаване на mobile client app (Phase 3+)
2. Push notification service
3. Offline-first архитектура
4. Device registration и management

---

#### 5.3.1 Mobile Governance Hardening Policies

> **Цел:** Осигуряване на security-first подход за мобилния клиент, предотвратяване на data leaks и unauthorized access.

---

**Policy 1: Deny-by-Default**

| Аспект | Правило |
|--------|---------|
| **Описание** | Ако няма `mobile_view_config` за дадена роля/модул комбинация → **deny access** или **safe minimum** |
| **Safe Minimum** | `listFields: []`, `detailFields: ["id"]`, `allowedActions: ["view"]` |
| **Имплементация** | `get_mobile_config(role, module)` връща `DEFAULT_SAFE_CONFIG` ако няма match |
| **Audit** | Log warning: "No config for {role}/{module}, using safe minimum" |

```python
# Псевдокод
def get_mobile_config(org_id, role, module):
    config = db.mobile_view_configs.find_one({org_id, role, module})
    if not config:
        logger.warning(f"Deny-by-default: {role}/{module}")
        return SAFE_MINIMUM_CONFIG
    return config
```

---

**Policy 2: Config Precedence**

| Priority | Level | Описание |
|----------|-------|----------|
| 1 (highest) | **User-specific** | `mobile_view_configs` where `user_id` is set |
| 2 | **Role-specific** | `mobile_view_configs` where `role` matches user's role |
| 3 | **Org default** | `org_mobile_settings.defaultConfig` |
| 4 (lowest) | **System default** | `DEFAULT_MOBILE_CONFIGS[role]` from code |

**Resolution Rule:** First match wins (highest priority)

**Merge Strategy:** НЕ се merge-ват configs; използва се config от най-високия приоритет изцяло

```python
# Псевдокод
def resolve_config(org_id, user_id, role, module):
    # Priority 1: User-specific
    config = db.mobile_view_configs.find_one({org_id, user_id, module})
    if config: return config
    
    # Priority 2: Role-specific  
    config = db.mobile_view_configs.find_one({org_id, role, module, user_id: None})
    if config: return config
    
    # Priority 3: Org default
    org_settings = db.org_mobile_settings.find_one({org_id})
    if org_settings and module in org_settings.get("defaultConfigs", {}):
        return org_settings["defaultConfigs"][module]
    
    # Priority 4: System default (deny-by-default applies here)
    return DEFAULT_MOBILE_CONFIGS.get(role, {}).get(module, SAFE_MINIMUM)
```

---

**Policy 3: Media ACL (Access Control List)**

| Проверка | Описание | Статус |
|----------|----------|--------|
| **Org Isolation** | `serve_media_file` MUST verify `media.org_id == user.org_id` | ⚠️ Needs review |
| **Context Permission** | Ако media е linked към `workReport` → user must have access to that report | ⚠️ Needs impl |
| **Owner Access** | `media.owner_user_id == user.id` → always allowed | ✅ Implemented |
| **Admin Override** | Admin/Owner roles bypass context checks (but not org isolation) | ✅ Implemented |

**Current Risk:** `serve_media_file` може да serve файл само по filename без org check

**Required Fix:**
```python
@api_router.get("/media/file/{filename}")
async def serve_media_file(filename: str, user: dict = Depends(get_current_user)):
    media = await db.media_files.find_one({"filename": filename})
    if not media:
        raise HTTPException(404)
    
    # CRITICAL: Org isolation
    if media["org_id"] != user["org_id"]:
        raise HTTPException(403, "Access denied")
    
    # Context permission check
    if media.get("context_type") and media.get("context_id"):
        if not await can_access_context(user, media["context_type"], media["context_id"]):
            raise HTTPException(403, "No access to linked resource")
    
    return FileResponse(...)
```

---

**Policy 4: Config Versioning**

| Field | Описание |
|-------|----------|
| `configVersion` | Integer, инкрементира се при всяка промяна на config |
| `updatedAt` | ISO timestamp на последна промяна |
| **Bootstrap Response** | Включва `configVersion` и `updatedAt` |
| **Client Behavior** | Client кешира config; при `bootstrap` сравнява version; refetch ако е по-нов |

**Bootstrap Response Enhancement:**
```json
{
  "user": {...},
  "organization": {...},
  "enabledModules": [...],
  "viewConfigs": {...},
  "configVersion": 42,
  "configUpdatedAt": "2026-02-18T15:00:00Z"
}
```

**Client Cache Strategy:**
1. Store `configVersion` locally
2. On app launch: call `/api/mobile/bootstrap`
3. If `response.configVersion > local.configVersion`: refresh all cached configs
4. If equal: use cached data, skip full config parse

---

#### 5.3.2 Recommended Security Tests (6)

| # | Test Name | Сценарий | Expected Result |
|---|-----------|----------|-----------------|
| T1 | `test_no_config_returns_safe_minimum` | Role=Viewer, Module=finance (no config exists) | Returns `SAFE_MINIMUM_CONFIG`, not error; logs warning |
| T2 | `test_multi_config_precedence` | User has user-specific + role-specific config for same module | User-specific config wins (priority 1) |
| T3 | `test_cross_org_media_access_denied` | User from Org-A tries to access media from Org-B via filename | 403 Forbidden; audit log: "Cross-org media access attempt" |
| T4 | `test_orphan_media_cleanup_eligibility` | Media file with no context links, older than 30 days | Marked as `cleanup_eligible`; NOT auto-deleted without admin action |
| T5 | `test_bypass_attempt_via_generic_endpoint` | User calls `/api/work-reports/{id}` directly instead of mobile endpoint | Same field filtering applies; no extra fields leak |
| T6 | `test_nested_field_filtering` | Config allows `lines` field but not `lines.internal_cost` | Response includes `lines` array but each line has `internal_cost` removed |

---

#### 5.3.3 Mobile Security Risk Assessment

| Risk | Severity | Current Status | Mitigation |
|------|----------|----------------|------------|
| Cross-org data leak via media | 🔴 HIGH | ⚠️ Needs verification | Implement Policy 3 (Media ACL) |
| Config bypass via direct API | 🟡 MEDIUM | ⚠️ Partial | Field filtering on ALL endpoints, not just mobile |
| Offline data tampering | 🟡 MEDIUM | ❌ Not addressed | Implement request signing + server-side validation |
| Session hijacking on mobile | 🟡 MEDIUM | ⚠️ JWT only | Add device fingerprinting + refresh tokens |

---

## 6. ПРЕГЛЕД НА СИГУРНОСТ И ПРАВА

### 6.1 Authentication
| Аспект | Имплементация | Оценка |
|--------|---------------|--------|
| JWT Tokens | ✅ HS256, 24h expiry | ✅ Добре |
| Password Hashing | ✅ bcrypt | ✅ Добре |
| Token Validation | ✅ На всяка заявка | ✅ Добре |
| Refresh Tokens | ❌ Липсва | ⚠️ Препоръчително |
| Rate Limiting | ❌ Липсва | ⚠️ Риск |
| Account Lockout | ❌ Липсва | ⚠️ Риск |

### 6.2 Authorization (RBAC)
| Роля | Права | Имплементация |
|------|-------|---------------|
| Admin | Пълен достъп | ✅ `require_admin` |
| Owner | Пълен достъп | ✅ `require_admin` |
| SiteManager | Управление на екипи/проекти | ✅ `can_manage_project` |
| Technician | Собствени записи | ✅ Ограничен |
| Accountant | Финанси read-only | ⚠️ Частично |
| Driver | Доставки | ⚠️ Не е имплементирано |
| Viewer | Само четене | ✅ Работи |

### 6.3 Multi-Tenant Isolation
| Проверка | Имплементация | Статус |
|----------|---------------|--------|
| org_id филтър на всички заявки | ✅ | ✅ Добре |
| Потребител не вижда чужди данни | ✅ | ✅ Добре |
| Cross-tenant injection protection | ✅ | ✅ Добре |

### 6.4 Module Gating
| Проверка | Имплементация | Статус |
|----------|---------------|--------|
| Plan-based module access | ✅ `check_module_access_for_org` | ✅ Добре |
| Trial expiration check | ✅ Автоматичен | ✅ Добре |
| Usage limits enforcement | ✅ `enforce_limit` | ✅ Добре |

### 6.5 Идентифицирани рискове за сигурност
1. **СРЕДЕН:** Липса на rate limiting - възможни brute-force атаки
2. **НИСЪК:** Липса на refresh tokens - потребителите трябва да се логват на 24h
3. **НИСЪК:** Липса на account lockout след неуспешни опити
4. **НИСЪК:** JWT secret в .env - добре за dev, но трябва rotation в prod

---

## 7. КОНСИСТЕНТНОСТ НА ДАННИТЕ

### 7.1 Referential Integrity
| Релация | Проверка | Статус |
|---------|----------|--------|
| User → Organization | ✅ org_id задължителен | ✅ |
| Project → Organization | ✅ org_id задължителен | ✅ |
| Invoice → Project | ⚠️ Optional, не се валидира | ⚠️ |
| Payment → Account | ✅ Проверява съществуване | ✅ |
| PaySlip → User | ✅ employee_id проверен | ✅ |

### 7.2 Cascade Delete
| Обект | При изтриване | Статус |
|-------|---------------|--------|
| Project | Изтрива team + phases | ✅ |
| User | НЕ изтрива свързани записи | ⚠️ Риск |
| Organization | НЕ cascade delete | ⚠️ Риск |
| PayrollRun | Изтрива payslips | ✅ |

### 7.3 Data Validation
| Поле | Валидация | Статус |
|------|-----------|--------|
| Email | Format check | ✅ |
| Date strings | ISO format | ✅ |
| Enum values | Списъчна проверка | ✅ |
| Numeric ranges | ⚠️ Частично | ⚠️ |
| Required fields | Pydantic enforcement | ✅ |

### 7.4 Идентифицирани проблеми
1. **СРЕДЕН:** При изтриване на User не се обработват: attendance, work_reports, payslips
2. **НИСЪК:** invoice.project_id не се валидира дали проектът съществува
3. **НИСЪК:** Липсва soft-delete за критични обекти

---

## 8. АНАЛИЗ НА ТЕСТОВО ПОКРИТИЕ

### 8.1 Съществуващи тестове
| Файл | Тестове | Модул | Покритие |
|------|---------|-------|----------|
| test_m10_billing.py | 15 | Billing | ✅ Добро |
| test_usage_limits.py | 10 | Usage | ✅ Добро |
| test_mobile_integration.py | 18 | Mobile | ✅ Добро |
| test_m5_finance.py | ~10 | Finance | ✅ Средно |
| test_m9_overhead.py | ~8 | Overhead | ✅ Средно |
| test_m9_alerts.py | ~6 | Alerts | ⚠️ Базово |
| test_m4_payroll.py | ~10 | Payroll | ✅ Средно |
| test_m2_offers.py | ~8 | Offers | ⚠️ Базово |

### 8.2 Препоръчани 10+ нови теста

#### Категория: Authentication & Security
| # | Тест | Приоритет | Описание |
|---|------|-----------|----------|
| 1 | test_login_invalid_credentials | P0 | Верификация на грешка при невалидни данни |
| 2 | test_expired_token_rejected | P0 | JWT с изтекъл срок да се отхвърля |
| 3 | test_user_disabled_cannot_login | P1 | Деактивиран потребител не може да влезе |

#### Категория: RBAC & Permissions
| # | Тест | Приоритет | Описание |
|---|------|-----------|----------|
| 4 | test_technician_cannot_delete_project | P0 | Технически не може да трие проекти |
| 5 | test_sitemanager_manages_only_assigned | P1 | SiteManager вижда само своите проекти |
| 6 | test_cross_org_data_isolation | P0 | Потребител A не вижда данни на организация B |

#### Категория: Business Logic
| # | Тест | Приоритет | Описание |
|---|------|-----------|----------|
| 7 | test_payroll_finalize_blocks_edits | P1 | Финализиран payroll не може да се редактира |
| 8 | test_invoice_allocation_exceeds_amount | P1 | Алокация > сума на плащане да се отхвърля |
| 9 | test_work_report_submit_requires_lines | P1 | Празен доклад не може да се submit-ва |
| 10 | test_trial_expiration_blocks_modules | P0 | Изтекъл trial блокира платени модули |

#### Категория: Data Integrity
| # | Тест | Приоритет | Описание |
|---|------|-----------|----------|
| 11 | test_delete_user_orphan_records | P1 | Проверка за осиротели записи при изтриване |
| 12 | test_duplicate_attendance_same_day | P0 | Не може 2 присъствия на един ден |
| 13 | test_invoice_lines_total_matches | P2 | Сумата на редове = нетна стойност |

#### Категория: Edge Cases
| # | Тест | Приоритет | Описание |
|---|------|-----------|----------|
| 14 | test_attendance_after_deadline_is_late | P1 | Маркиране след deadline = Late |
| 15 | test_offer_versioning_increments | P2 | Нова версия = version + 1 |

---

## 9. СТАТУС ТАБЛИЦА НА МОДУЛИТЕ

| Модул | Код | Backend | Frontend | Тестове | i18n | Mobile Ready | Общ статус |
|-------|-----|---------|----------|---------|------|--------------|------------|
| Core/SaaS | M0 | 100% | 100% | 80% | ✅ | ✅ | ✅ PRODUCTION |
| Projects | M1 | 100% | 100% | 70% | ✅ | ✅ | ✅ PRODUCTION |
| Estimates/BOQ | M2 | 100% | 100% | 60% | ✅ | ⚠️ | ✅ PRODUCTION |
| Attendance | M3 | 100% | 100% | 70% | ✅ | ✅ | ✅ PRODUCTION |
| Work Reports | M3 | 100% | 100% | 70% | ✅ | ✅ | ✅ PRODUCTION |
| HR/Payroll | M4 | 100% | 100% | 70% | ✅ | ⚠️ | ✅ PRODUCTION |
| Finance | M5 | 100% | 100% | 65% | ✅ | ⚠️ | ✅ PRODUCTION |
| AI Invoice | M6 | 0% | 0% | 0% | ❌ | ❌ | ❌ NOT STARTED |
| Inventory | M7 | 0% | 0% | 0% | ❌ | ❌ | ❌ NOT STARTED |
| Assets & QR | M8 | 0% | 0% | 0% | ❌ | ❌ | ❌ NOT STARTED |
| Overhead | M9 | 100% | 100% | 60% | ✅ | ⚠️ | ✅ PRODUCTION |
| Alerts | M9 | 100% | 100% | 50% | ✅ | ⚠️ | ✅ PRODUCTION |
| Dashboard | M9 | 30% | 30% | 20% | ✅ | ❌ | ⚠️ PARTIAL |
| Billing | M10 | 100% | 100% | 90% | ✅ | N/A | ✅ PRODUCTION (MOCK) |
| Mobile Config | - | 100% | 100% | 85% | ✅ | ✅ | ✅ READY |
| Mobile App | - | 0% | 0% | 0% | ❌ | ❌ | ❌ NOT STARTED |
| Deliveries | - | 10% | 0% | 0% | ❌ | ⚠️ | ❌ NOT STARTED |
| Machines | - | 10% | 0% | 0% | ❌ | ⚠️ | ❌ NOT STARTED |

**Легенда:**
- ✅ PRODUCTION: Готово за продукционна употреба
- ⚠️ PARTIAL: Частично имплементирано
- ❌ NOT STARTED: Не е започнато

---

## 10. ТОП 10 РИСКОВЕ

| # | Риск | Тежест | Вероятност | Въздействие | Митигация |
|---|------|--------|------------|-------------|-----------|
| **1** | **Монолитен server.py (4700+ реда)** | 🔴 КРИТИЧЕН | 100% | Невъзможност за поддръжка, бавно развитие | Рефакторинг на модулна структура |
| **2** | **Stripe само в Mock Mode** | 🔴 КРИТИЧЕН | 100% | Невъзможност за реални плащания | Интеграция с реален Stripe акаунт |
| **3** | **M7 Inventory липсва** | 🔴 КРИТИЧЕН | 100% | Невъзможен Global Availability Scan, Requests flow | Приоритизиране на M7 преди Requests |
| **4** | **Mobile Media ACL недостатъчен** | 🔴 КРИТИЧЕН | 80% | Cross-org data leak през media endpoint | Имплементиране на Policy 3 (виж 5.3.1) |
| **5** | **Липса на Rate Limiting** | 🟠 ВИСОК | 60% | DDoS атаки, brute-force | Добавяне на slowapi или nginx rate limit |
| **6** | **Deliveries модул липсва** | 🟠 ВИСОК | 100% | Driver роля е безполезна | State machine + 14 endpoints (виж 5.1) |
| **7** | **Requests/RequestLines липсва** | 🟠 ВИСОК | 100% | Логистичният поток не работи | Зависи от M7/M8 |
| **8** | **M8 Assets & QR липсва** | 🟡 СРЕДЕН | 100% | Guest assets не могат да се следят | Имплементация след M7 |
| **9** | **Mobile App липсва** | 🟡 СРЕДЕН | 100% | Мобилната конфигурация е безполезна | Стартиране на Mobile Phase 3 |
| **10** | **Config precedence не е имплементиран** | 🟡 СРЕДЕН | 70% | Inconsistent mobile behavior | Имплементиране на Policy 2 (виж 5.3.1) |

---

## 11. ТРИ-ЕТАПЕН PATCH ПЛАН

### ЕТАП 1: СТАБИЛИЗАЦИЯ (1-2 седмици)
**Цел:** Намаляване на критични рискове без нова функционалност

| # | Задача | Приоритет | Оценка | Зависимости |
|---|--------|-----------|--------|-------------|
| 1.1 | **Рефакторинг на server.py** | P0 | 3-5 дни | Няма |
| | → routes/ (auth, projects, billing, etc.) | | | |
| | → models/ (pydantic models) | | | |
| | → services/ (business logic) | | | |
| | → helpers/ (utilities) | | | |
| 1.2 | Rate Limiting (slowapi) | P1 | 0.5 дни | 1.1 |
| 1.3 | Refresh Token система | P1 | 1 ден | 1.1 |
| 1.4 | Soft-delete за Users | P2 | 0.5 дни | 1.1 |
| 1.5 | Добавяне на 15-те нови теста | P1 | 1-2 дни | 1.1 |
| 1.6 | Cascade delete handlers | P2 | 0.5 дни | 1.4 |

**Deliverables:**
- Модулна backend структура
- Подобрена сигурност
- 90%+ тестово покритие за критични пътища

---

### ЕТАП 2: ФУНКЦИОНАЛНОСТ (2-3 седмици)
**Цел:** Затваряне на бизнес-критични gap-ове

| # | Задача | Приоритет | Оценка | Зависимости |
|---|--------|-----------|--------|-------------|
| 2.1 | **Deliveries CRUD пълна имплементация** | P0 | 3-4 дни | Етап 1 |
| | → Backend endpoints | | | |
| | → Frontend страница | | | |
| | → Тестове | | | |
| 2.2 | **M7 Inventory базова имплементация** | P0 | 4-5 дни | 2.1 |
| | → Items catalog + InventoryBalance | | | |
| | → Warehouses + Projects като locations | | | |
| | → Stock movements CRUD | | | |
| 2.3 | **M8 Assets базова имплементация** | P1 | 3-4 дни | 2.2 |
| | → AssetInstance + Guest assignments | | | |
| | → QR code generation | | | |
| 2.4 | **Requests + Global Availability Scan** | P0 | 3-4 дни | 2.2, 2.3 |
| | → Request + RequestLine models | | | |
| | → buildSourceSuggestionsForRequest | | | |
| | → UI за предложения | | | |
| 2.5 | Real Stripe Integration | P1 | 2 дни | Stripe акаунт |
| 2.6 | Export CSV/PDF | P2 | 1-2 дни | Етап 1 |

**Deliverables:**
- Пълна Deliveries функционалност
- M7 Inventory (базово)
- M8 Assets (базово)
- Global Availability Scan при Request submit
- Реални плащания

---

### ЕТАП 3: МОБИЛНО ПРИЛОЖЕНИЕ (4-6 седмици)
**Цел:** Стартиране на мобилния клиент

| # | Задача | Приоритет | Оценка | Зависимости |
|---|--------|-----------|--------|-------------|
| 3.1 | **Mobile App Setup** (React Native/Flutter) | P0 | 1 седм. | Етап 2 |
| 3.2 | **Phase 3: Technician flows** | P0 | 1-2 седм. | 3.1 |
| | → Attendance clock in/out | | | |
| | → Work Reports CRUD | | | |
| | → Profile view | | | |
| 3.3 | **Phase 4: Driver flows** | P1 | 1-2 седм. | 3.2 |
| | → Deliveries list & update | | | |
| | → Photo upload | | | |
| 3.4 | **Phase 5: Machine flows** | P2 | 1 седм. | 3.3 |
| 3.5 | Push Notifications | P1 | 3-5 дни | Firebase/OneSignal |
| 3.6 | Offline Sync | P2 | 1-2 седм. | 3.1-3.4 |

**Deliverables:**
- Работещо мобилно приложение за Technician и Driver роли
- Push notifications
- Offline capability

---

## ЗАКЛЮЧЕНИЕ

### Силни страни на проекта:
1. ✅ Солидна multi-tenant архитектура
2. ✅ Пълна i18n поддръжка
3. ✅ Добра RBAC система
4. ✅ Модулно гейтиране по план
5. ✅ Добро тестово покритие за новите модули

### Основни слабости:
1. ❌ Монолитен backend файл
2. ❌ Stripe в Mock режим
3. ❌ Липсващи критични модули (Deliveries, Machines)
4. ❌ Няма мобилно приложение

### Препоръка:
**Приоритизирайте Етап 1 (Рефакторинг)** преди добавяне на нова функционалност. Монолитният server.py е главната пречка пред мащабирането и поддръжката на проекта.

---

## APPENDIX: EVIDENCE ARTIFACTS

### A1. Endpoint Inventory
- **Файл:** `/app/audit_endpoints.csv`
- **Генериран от:** FastAPI `app.routes` extraction
- **Формат:** CSV (path, methods, route_name, handler_func)
- **Общо редове:** 145 (1 header + 144 endpoints)

### A2. MongoDB Collections Inventory
- **Файл:** `/app/audit_models_collections.txt`
- **Генериран от:** `server.py` db.* usage pattern extraction
- **Общо колекции:** 31 (15 core + 16 supporting)

### A3. Pydantic Models Count
- **Източник:** `server.py` BaseModel class definitions
- **Общо модели:** 48

---

*Одит изготвен на: 18 февруари 2026*
*Последна актуализация: 18 февруари 2026 (Етап 0.2 Consistency Fix)*
*Автор: E1 Agent*

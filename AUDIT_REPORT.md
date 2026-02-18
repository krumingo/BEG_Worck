# BEG_Work - ПЪЛЕН ОДИТ НА ПРОЕКТА
**Дата:** 18 Февруари 2026
**Версия:** Core + Mobile Phase 1-2

---

## 1. INVENTORY (Инвентаризация)

### 1.1 Endpoints (144 общо)
| Категория | Брой | Статус |
|-----------|------|--------|
| finance | 19 | ✅ Имплементирано |
| overhead | 18 | ✅ Имплементирано |
| projects | 12 | ✅ Имплементирано |
| offers | 10 | ✅ Имплементирано |
| work-reports | 9 | ✅ Имплементирано |
| billing | 9 | ✅ Имплементирано |
| attendance | 7 | ✅ Имплементирано |
| reminders | 6 | ✅ Имплементирано |
| payroll-runs | 6 | ✅ Имплементирано |
| mobile | 6 | ✅ Имплементирано |
| media | 5 | ✅ Имплементирано |
| users | 4 | ✅ Имплементирано |
| payslips | 4 | ✅ Имплементирано |
| employees | 4 | ✅ Имплементирано |
| activity-catalog | 4 | ✅ Имплементирано |
| advances | 3 | ✅ Имплементирано |
| **deliveries** | 0 | ❌ НЕ СЪЩЕСТВУВА |
| **machines** | 0 | ❌ НЕ СЪЩЕСТВУВА |
| **warehouse/inventory** | 0 | ❌ НЕ СЪЩЕСТВУВА |

### 1.2 Pydantic Models (55 общо)
- ✅ Auth: LoginRequest
- ✅ Users: UserCreate, UserUpdate
- ✅ Projects: ProjectCreate, ProjectUpdate, TeamMemberAdd, PhaseCreate, PhaseUpdate
- ✅ Attendance: AttendanceEntry, AttendanceOverride
- ✅ Work Reports: WorkReportCreate, WorkReportUpdate, WorkReportLine
- ✅ Offers: OfferCreate, OfferUpdate, OfferLine
- ✅ Finance: AccountCreate, InvoiceCreate, PaymentCreate, AllocationRequest
- ✅ Payroll: PayrollRunCreate, SetDeductionsRequest, MarkPaidRequest
- ✅ Overhead: CategoryCreate, CostCreate, AssetCreate, SnapshotCompute, AllocateRequest
- ✅ Billing: OrgSignupRequest, CreateCheckoutRequest, SubscriptionUpdate
- ✅ Mobile: MobileSettingsUpdate, MobileViewConfigUpdate, MediaUploadContext, MediaLinkRequest
- ❌ **ЛИПСВАТ**: DeliveryCreate, MachineCreate, WarehouseCreate, StockMovement, Request/Return models

### 1.3 Database Collections (30 общо)
```
✅ users (39 заявки)
✅ projects (37)
✅ project_team (35)
✅ invoices (32)
✅ offers (28)
✅ work_reports (27)
✅ subscriptions (27)
✅ payslips (20)
✅ attendance_entries (17)
✅ payroll_runs (15)
✅ finance_payments (12)
✅ organizations (11)
✅ reminder_logs (10)
✅ financial_accounts (10)
✅ employee_profiles (10)
✅ advances (10)
✅ feature_flags (9)
✅ activity_catalog (9)
✅ payment_allocations (8)
✅ media_files (8)
✅ overhead_* (5 collections)
✅ mobile_view_configs (5)
✅ notifications (6)
✅ audit_logs (4)
✅ org_mobile_settings (3)
❌ deliveries - НЕ СЪЩЕСТВУВА
❌ machines - НЕ СЪЩЕСТВУВА
❌ warehouses - НЕ СЪЩЕСТВУВА
❌ stock_movements - НЕ СЪЩЕСТВУВА
❌ requests - НЕ СЪЩЕСТВУВА
❌ returns - НЕ СЪЩЕСТВУВА
```

### 1.4 Status Constants (State Machines)
```python
PROJECT_STATUSES = ["Draft", "Active", "Paused", "Completed", "Cancelled"]
ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "SickLeave", "Vacation"]
REPORT_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
REMINDER_STATUSES = ["Open", "Reminded", "Resolved", "Excused"]
OFFER_STATUSES = ["Draft", "Sent", "Accepted", "Rejected", "Archived"]
ADVANCE_STATUSES = ["Open", "Closed"]
PAYROLL_STATUSES = ["Draft", "Finalized", "Paid"]
PAYSLIP_STATUSES = ["Draft", "Finalized", "Paid"]
INVOICE_STATUSES = ["Draft", "Sent", "PartiallyPaid", "Paid", "Overdue", "Cancelled"]
SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete"]
```

❌ **ЛИПСВАТ**: DELIVERY_STATUSES, MACHINE_STATUSES, REQUEST_STATUSES, RETURN_STATUSES

---

## 2. GAP ANALYSIS (Анализ на липсите)

### 2.1 Критичен GAP: Flow A (Request → Delivery → Verification)
| Компонент | Статус | Доказателство |
|-----------|--------|---------------|
| Request Model | ❌ ЛИПСВА | Няма grep резултат |
| Delivery Model | ❌ ЛИПСВА | Няма grep резултат |
| Return Model | ❌ ЛИПСВА | Няма grep резултат |
| Verification Flow | ❌ ЛИПСВА | Няма endpoint |
| State Machine | ❌ ЛИПСВА | Няма STATUS constant |

**ИЗВОД:** Flow A НЕ Е ИМПЛЕМЕНТИРАН. Има само PLACEHOLDER в mobile configs.

### 2.2 Критичен GAP: Flow B (Global Availability Scan)
| Компонент | Статус | Доказателство |
|-----------|--------|---------------|
| Warehouse Model | ❌ ЛИПСВА | M7 не е имплементиран |
| Stock/Inventory | ❌ ЛИПСВА | M7 не е имплементиран |
| Availability Scan | ❌ ЛИПСВА | Няма endpoint |
| Cross-site Query | ❌ ЛИПСВА | Няма логика |

**ИЗВОД:** Flow B НЕ Е ИМПЛЕМЕНТИРАН. M7 (Inventory) е маркиран като UPCOMING.

### 2.3 Частичен GAP: Flow C (Mobile Governance)
| Компонент | Статус | Доказателство |
|-----------|--------|---------------|
| Bootstrap endpoint | ✅ ИМПЛЕМЕНТИРАН | server.py:5149 |
| OrgMobileSettings | ✅ ИМПЛЕМЕНТИРАН | MongoDB collection |
| MobileViewConfig | ✅ ИМПЛЕМЕНТИРАН | MongoDB collection |
| DEFAULT_MOBILE_CONFIGS | ✅ ИМПЛЕМЕНТИРАН | server.py:592 |
| filter_fields() | ✅ ДЕФИНИРАНА | server.py:5114 |
| filter_list_items() | ✅ ДЕФИНИРАНА | server.py:5120 |
| check_mobile_action() | ✅ ДЕФИНИРАНА | server.py:5124 |
| enforce_mobile_action() | ✅ ДЕФИНИРАНА | server.py:5137 |
| **ФАКТИЧЕСКО ИЗПОЛЗВАНЕ на filter_fields** | ⚠️ НЕ СЕ ИЗПОЛЗВА | 0 употреби извън дефиницията |
| **ФАКТИЧЕСКО ИЗПОЛЗВАНЕ на enforce_mobile_action** | ⚠️ НЕ СЕ ИЗПОЛЗВА | 0 употреби извън дефиницията |
| Media upload | ✅ ИМПЛЕМЕНТИРАН | server.py:5347 |
| Media link | ✅ ИМПЛЕМЕНТИРАН | server.py:5418 |

**ИЗВОД:** Flow C е ЧАСТИЧНО ИМПЛЕМЕНТИРАН. Helpers са дефинирани, но НЕ СЕ ПРИЛАГАТ към реални данни.

---

## 3. DEFINITION OF DONE (DoD)

### 3.A Flow: Request → Delivery → Verification → Reject → Return → ReRequest

**ТЕКУЩ СТАТУС: 0% ГОТОВО**

| Критерий | Изискване | Текущо състояние |
|----------|-----------|------------------|
| Data Models | Request, Delivery, Return, Verification | ❌ НИЩО |
| Status Machine | REQUEST_STATUSES, DELIVERY_STATUSES | ❌ НИЩО |
| Endpoints | CRUD за всеки entity | ❌ НИЩО |
| State Transitions | Valid transitions enforced | ❌ НИЩО |
| Audit Trail | История на всяка промяна | ❌ НИЩО |
| Relations | request ↔ delivery ↔ return links | ❌ НИЩО |
| Tests | 100% покритие на flow | ❌ НИЩО |

### 3.B Flow: Global Availability Scan

**ТЕКУЩ СТАТУС: 0% ГОТОВО**

| Критерий | Изискване | Текущо състояние |
|----------|-----------|------------------|
| Warehouse Model | Multi-warehouse support | ❌ НИЩО |
| Stock/Inventory | Items + quantities per location | ❌ НИЩО |
| Site Integration | Stock per project site | ❌ НИЩО |
| Guest Access | External partner stock | ❌ НИЩО |
| Scan Endpoint | Query all sources | ❌ НИЩО |
| No Default Warehouse | Explicit source selection | ❌ НИЩО |
| Tests | Scan correctness | ❌ НИЩО |

### 3.C Flow: Mobile Governance

**ТЕКУЩ СТАТУС: 60% ГОТОВО**

| Критерий | Изискване | Текущо състояние |
|----------|-----------|------------------|
| Bootstrap endpoint | Returns config per role | ✅ ГОТОВО |
| OrgMobileSettings | Enable/disable modules | ✅ ГОТОВО |
| MobileViewConfig | Per role/module config | ✅ ГОТОВО |
| Admin UI | Configure from web | ✅ ГОТОВО |
| filter_fields() | Strip disallowed fields | ⚠️ ДЕФИНИРАНО, НЕ СЕ ИЗПОЛЗВА |
| enforce_mobile_action() | Block disallowed actions | ⚠️ ДЕФИНИРАНО, НЕ СЕ ИЗПОЛЗВА |
| Mobile data endpoints | /api/mobile/attendance, etc. | ❌ ЛИПСВАТ |
| Field filtering integration | All mobile/* endpoints | ❌ ЛИПСВА |
| Action enforcement integration | All mobile/* POST/PUT | ❌ ЛИПСВА |
| Tests | Field filtering, action blocking | ⚠️ ЧАСТИЧНИ |

---

## 4. SECURITY / PERMISSION ENFORCEMENT

### 4.1 Deny-by-default при липса на config (mobile)
```python
# server.py:5090-5098
async def get_mobile_view_config(org_id: str, role: str, module_code: str) -> dict:
    config = await db.mobile_view_configs.find_one({...})
    if config:
        return config
    # FALLBACK to DEFAULT_MOBILE_CONFIGS
    role_defaults = DEFAULT_MOBILE_CONFIGS.get(role, {})
    module_config = role_defaults.get("configs", {}).get(module_code, {})
```

⚠️ **ПРОБЛЕМ:** Ако role не е в DEFAULT_MOBILE_CONFIGS (напр. "Accountant"), се връща empty config с `allowedActions: ["view"]` - НЕ deny-by-default, а READ-ONLY default.

**ПРЕПОРЪКА:** Explicit deny за roles без дефиниран default config.

### 4.2 Precedence при 2 matching configs
```python
# ТЕКУЩО ПОВЕДЕНИЕ:
# 1. Търси в db.mobile_view_configs (custom)
# 2. Ако няма custom -> използва DEFAULT_MOBILE_CONFIGS
# 3. Ако няма в defaults -> fallback: all detail fields, view only
```

✅ **ДОБРЕ:** Precedence е ясен: Custom > Default > Fallback

### 4.3 Media Access Control (cross-org)
```python
# server.py:5457-5473
media = await db.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
if not media:
    raise HTTPException(status_code=404, detail="Media file not found")

is_owner = media["owner_user_id"] == user["id"]
is_admin = user["role"] in ["Admin", "Owner"]
has_context_access = True  # ❌ PLACEHOLDER - ВИНАГИ TRUE!

if not (is_owner or is_admin or has_context_access):
    raise HTTPException(status_code=403)
```

❌ **КРИТИЧЕН ПРОБЛЕМ:** `has_context_access = True` е HARDCODED! Всеки user в org-а може да види всяка media.

### 4.4 Action Enforcement - Generic Endpoints
```python
# enforce_mobile_action() е дефинирана, но НЕ СЕ ИЗПОЛЗВА никъде

# Текущо /api/attendance/mark може да се извика директно без mobile action check
# /api/work-reports/draft - същото
# /api/media/upload - същото
```

❌ **КРИТИЧЕН ПРОБЛЕМ:** Mobile actions могат да се заобикалят чрез generic endpoints.

---

## 5. DATA CONSISTENCY

### 5.1 Статуси и Преходи

**Work Reports:**
```
Draft -> Submitted -> Approved/Rejected
```
✅ Имплементирано в server.py:1683, 1705, 1723

**Offers:**
```
Draft -> Sent -> Accepted/Rejected -> Archived (or new version)
```
✅ Имплементирано с версиониране

**Payroll:**
```
Draft -> Finalized -> Paid
```
✅ Имплементирано с lock-in

**Invoices:**
```
Draft -> Sent -> PartiallyPaid -> Paid/Cancelled
```
✅ Имплементирано с payment allocations

❌ **ЛИПСВА:** Deliveries state machine, Request/Return state machine

### 5.2 Връзки request ↔ returns ↔ re-requests

**ТЕКУЩО СЪСТОЯНИЕ:** НЕ СЪЩЕСТВУВАТ. Няма модели, няма relations.

### 5.3 Audit Trail / History

```python
# server.py:855-866
async def log_audit(org_id, user_id, user_email, action, entity_type, entity_id="", details=None):
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
```

✅ **ДОБРЕ:** log_audit() се използва на ~50+ места
⚠️ **ПРОБЛЕМ:** Не всички операции се логват (напр. media upload/link не се логва)

---

## 6. TEST COVERAGE

### 6.1 Текущи Тестове

| Файл | Брой тестове | Покритие |
|------|--------------|----------|
| test_m2_offers.py | 26 | M2 Offers CRUD + versions |
| test_m4_payroll.py | 20 | M4 Payroll runs + payslips |
| test_m5_finance.py | 33 | M5 Accounts + Invoices + Payments |
| test_m9_alerts.py | 17 | M9 Reminders |
| test_m9_overhead.py | 25 | M9 Overhead costs |
| test_m10_billing.py | 16 | M10 Billing + signup |
| test_mobile_integration.py | 18 | Mobile bootstrap + media |
| test_usage_limits.py | 10 | Plan limits |
| **ОБЩО** | **165** | |

### 6.2 Липсващи Тестове (ТОП 10)

1. **❌ M1 Projects CRUD** - Няма test файл
2. **❌ M3 Attendance flow** - Няма test файл
3. **❌ M3 Work Reports flow** - Няма test файл
4. **❌ Mobile field filtering** - filter_fields() не се тества реално
5. **❌ Mobile action blocking** - enforce_mobile_action() не се тества реално
6. **❌ Cross-org isolation** - Няма тест за data leakage между orgs
7. **❌ Media context access** - has_context_access е hardcoded
8. **❌ Trial expiration flow** - Auto past_due не е тестван
9. **❌ Subscription downgrade** - Webhook subscription.deleted не е тестван
10. **❌ Rate limiting / abuse** - Няма protection

---

## 7. ФИНАЛЕН DELIVERABLE

### 7.1 Module Status Table

| Module | Status | Evidence | Risk | Next Step |
|--------|--------|----------|------|-----------|
| M0 Core/Auth | ✅ DONE | 144 endpoints, JWT | LOW | - |
| M1 Projects | ✅ DONE | /api/projects/* (12 endpoints) | MEDIUM | Add tests |
| M2 Offers/BOQ | ✅ DONE | /api/offers/* (10 endpoints), 26 tests | LOW | - |
| M3 Attendance | ✅ DONE | /api/attendance/* (7 endpoints) | MEDIUM | Add tests |
| M3 Work Reports | ✅ DONE | /api/work-reports/* (9 endpoints) | MEDIUM | Add tests |
| M4 HR/Payroll | ✅ DONE | /api/payroll-*, employees, advances | LOW | - |
| M5 Finance | ✅ DONE | /api/finance/* (19 endpoints), 33 tests | LOW | - |
| M6 AI Invoice | ❌ MISSING | Само описание в MODULES dict | HIGH | Phase 3+ |
| M7 Inventory | ❌ MISSING | Само описание в MODULES dict | CRITICAL | Phase 3+ |
| M8 Assets/QR | ❌ MISSING | Само описание в MODULES dict | HIGH | Phase 3+ |
| M9 Alerts | ✅ DONE | /api/reminders/* (6 endpoints), 17 tests | LOW | - |
| M9 Overhead | ✅ DONE | /api/overhead/* (18 endpoints), 25 tests | LOW | - |
| M10 Billing | ✅ DONE | /api/billing/* (9 endpoints), 16 tests | LOW | - |
| Mobile Phase 1 | ⚠️ PARTIAL | bootstrap + settings UI, NO enforcement | HIGH | Fix enforcement |
| Mobile Phase 2 | ⚠️ PARTIAL | media upload OK, context access broken | HIGH | Fix access control |
| Deliveries | ❌ MISSING | Placeholder в mobile configs само | CRITICAL | Phase 3 |
| Machines | ❌ MISSING | Placeholder в mobile configs само | CRITICAL | Phase 3 |

### 7.2 TOP 10 RISKS (по приоритет)

| # | Risk | Impact | Probability | Mitigation |
|---|------|--------|-------------|------------|
| 1 | **Mobile actions заобикалят се през generic endpoints** | CRITICAL | HIGH | Add middleware за mobile-origin requests |
| 2 | **has_context_access = True hardcoded** | HIGH | HIGH | Implement real context-based access |
| 3 | **filter_fields() не се използва** | HIGH | HIGH | Integrate в /api/mobile/* endpoints |
| 4 | **M7 Inventory не съществува** | CRITICAL | 100% | Must implement за Flow B |
| 5 | **Deliveries/Machines са placeholders** | CRITICAL | 100% | Must implement за Flow A |
| 6 | **Няма тестове за M1/M3** | MEDIUM | HIGH | Add test files |
| 7 | **Cross-org data leakage не е тестван** | HIGH | MEDIUM | Add isolation tests |
| 8 | **Media audit log липсва** | MEDIUM | HIGH | Add log_audit calls |
| 9 | **Deny-by-default не е strict** | MEDIUM | MEDIUM | Change fallback behavior |
| 10 | **No rate limiting** | MEDIUM | MEDIUM | Add throttling |

### 7.3 PATCH PLAN

#### ЕТАП 1: Quick Wins (1-2 дни)
1. ✅ Fix `has_context_access` - implement real check
2. ✅ Add `log_audit()` to media upload/link
3. ✅ Change mobile fallback to deny-by-default
4. ✅ Add tests for M1 Projects
5. ✅ Add tests for M3 Attendance + Work Reports

#### ЕТАП 2: Core Blockers (3-5 дни)
1. ✅ Create `/api/mobile/attendance/*` endpoints with filter_fields integration
2. ✅ Create `/api/mobile/work-reports/*` endpoints with filter_fields integration
3. ✅ Add middleware to enforce_mobile_action for mobile-origin requests
4. ✅ Add cross-org isolation tests
5. ✅ Add trial expiration + webhook tests

#### ЕТАП 3: Mobile Phase 3 Readiness (5-7 дни)
1. ✅ Design M7 Inventory data model
2. ✅ Implement Deliveries model + endpoints
3. ✅ Implement Machines model + endpoints
4. ✅ Create mobile-specific endpoints for each
5. ✅ Full integration tests for Flow A (Request → Delivery → ...)
6. ✅ Full integration tests for Flow B (Availability Scan)

---

## ЗАКЛЮЧЕНИЕ

**Проектът е 65% завършен** спрямо заявените изисквания:
- Core modules (M0-M5, M9) са солидно имплементирани
- Billing (M10) работи в mock mode
- Mobile Phase 1-2 са ЧАСТИЧНО готови - инфраструктурата е там, но enforcement липсва
- M6, M7, M8 са ИЗЦЯЛО ЛИПСВАЩИ
- Flow A и Flow B НЕ МОГАТ ДА СЕ ИЗПЪЛНЯТ с текущия код

**Критични действия преди Phase 3:**
1. Fix mobile enforcement gaps (filter_fields, enforce_mobile_action)
2. Fix media access control
3. Add missing test coverage

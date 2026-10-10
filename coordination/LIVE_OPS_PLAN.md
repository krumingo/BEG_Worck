# 🧭 LIVE-OPS — постоянен план за реално използваема BEG_Work

> 🎯 **Цел:** BEG_Work да стане реално използваема по време на разработката.
>
> 🟦 **Status:** `[ ]` NOT STARTED · 🟨 `[~]` IN PROGRESS · 🟩 `[x]` DONE · 🟥 `[!]` BLOCKED
>
> 📍 **Source of truth:** този файл + Issue #52.
>
> 🧱 **FLOW rule:** одобрените FLOW са authoritative. Не препроектираме бизнес логика, освен при CODEX+CLAUDE потвърдена грешка.

> Owner: Krum
> Status model: [ ] NOT STARTED · [~] IN PROGRESS · [x] DONE · [!] BLOCKED
> Source of truth: this file + Issue #52.
> Important: FLOW behavior is NOT rewritten here. Existing approved FLOWs remain authoritative. Only a CODEX+CLAUDE-confirmed logical/technical inconsistency may trigger a proposed FLOW correction, and that requires Krum's decision.

## 🧩 Правила за работа

- Този план стои като постоянен checklist за LIVE-OPS.
- Всяка точка и подточка се отбелязва при доказано изпълнение.
- Преди всяка задача към CODEX или CLAUDE GPT показва кратко „На човешки“:
  1. какво ще се прави;
  2. къде в програмата;
  3. какво ще види/ползва Крум;
  4. какво НЕ се променя.
- Няма ново описание/препроектиране на „Заявки / Склад / Машини / други“ бизнес последователности, когато те вече са описани в FLOW.
- Ако CODEX и CLAUDE независимо намерят логическа/техническа грешка спрямо FLOW, тя се докладва с конкретен пример и се иска решение от Крум.
- Mockup approval ≠ code approval.
- Няма merge/deploy/migration/production activation без отделен owner gate.
- Draft PR никога не отива директно в production.

---

# 🗺️ MASTER PLAN — как BEG_Work ще стане използваема още по време на разработката

## 🧱 1. Разделяме разработката от ежедневната работа
- [x] 1.1 Създаден е отделен LIVE-OPS track
- [x] 1.2 Създаден е Issue #52
- [x] 1.3 Първи визуален mockup е одобрен от Крум
- [x] 1.4 Изпратени са независими review requests към CODEX и CLAUDE
- [x] 1.5 CODEX review получен
- [x] 1.6 CLAUDE review получен
- [x] 1.7 GPT comparison: AGREED / DISAGREED / OWNER DECISION
- [x] 1.8 Потвърдено е, че LIVE-OPS не създава паралелен canonical model

## 🔎 2. Проверяваме какво реално може да се ползва
- [x] 2.1 Inventory на наличния backend
- [x] 2.2 Inventory на наличния frontend
- [x] 2.3 Inventory на наличните tests
- [ ] 2.4 Проверка кое вече работи end-to-end
- [x] 2.5 Проверка кое е частично
- [x] 2.6 Проверка кое липсва технически
- [x] 2.7 Проверка за конфликт с FLOW/Wave
- [x] 2.8 Проверка за migration risk
- [x] 2.9 Проверка за tenant/permission risk
- [x] 2.10 Проверка за data-loss / rollback risk

## 🎨 3. Заключваме UX преди implementation
- [x] 3.1 Mockup v1 — одобрен
- [x] 3.2 Събиране на CODEX UX предложения
- [x] 3.3 Събиране на CLAUDE UX предложения
- [ ] 3.4 Mockup v2 — desktop control screen
- [ ] 3.5 Mockup v2 — Заявки
- [ ] 3.6 Mockup v2 — Склад
- [ ] 3.7 Mockup v2 — Машини / инструменти
- [ ] 3.8 Mockup v2 — phone-first screens
- [ ] 3.9 Крум одобрява UX v2

## 📐 4. Freeze на technical contract
- [ ] 4.1 Reuse map: кои текущи models/routes/screens се използват
- [ ] 4.2 Missing technical links
- [ ] 4.3 Permission matrix
- [ ] 4.4 AuditEvent coverage
- [ ] 4.5 Tenant/project isolation
- [ ] 4.6 Feature flags
- [ ] 4.7 Migration plan
- [ ] 4.8 Rollback plan
- [ ] 4.9 Required acceptance tests
- [ ] 4.10 CODEX independent contract review
- [ ] 4.11 CLAUDE independent contract review
- [ ] 4.12 Krum resolves only true business decisions

## 🛠️ 5. Implementation на малки стабилни части
### 🖥️ LIVE-OPS-A — Control center / read-only
- [ ] 5A.1 Implementation
- [ ] 5A.2 Tests
- [ ] 5A.3 CODEX independent review
- [ ] 5A.4 PASS
- [ ] 5A.5 Staging accepted

### 📋 LIVE-OPS-B — operational slice 2
- [ ] 5B.1 Implementation
- [ ] 5B.2 Tests
- [ ] 5B.3 CODEX independent review
- [ ] 5B.4 PASS
- [ ] 5B.5 Staging accepted

### 🏭 LIVE-OPS-C — operational slice 3
- [ ] 5C.1 Implementation
- [ ] 5C.2 Tests
- [ ] 5C.3 CODEX independent review
- [ ] 5C.4 PASS
- [ ] 5C.5 Staging accepted

### 🧰 LIVE-OPS-D — operational slice 4
- [ ] 5D.1 Implementation
- [ ] 5D.2 Tests
- [ ] 5D.3 CODEX independent review
- [ ] 5D.4 PASS
- [ ] 5D.5 Staging accepted

### 🔗 LIVE-OPS-E — integrated end-to-end gate
- [ ] 5E.1 End-to-end test
- [ ] 5E.2 Real Mongo
- [ ] 5E.3 Permissions / tenant isolation
- [ ] 5E.4 Frontend desktop smoke
- [ ] 5E.5 Frontend phone smoke
- [ ] 5E.6 Backup / restore
- [ ] 5E.7 Rollback proof
- [ ] 5E.8 Independent PASS

> Имената/точният функционален scope на B/C/D ще се заключат след CODEX+CLAUDE audit, за да не пренаписваме вече одобрените FLOW.

## 🧪 6. Staging
- [ ] 6.1 Production-shaped data copy/restore
- [ ] 6.2 Migration dry-run
- [ ] 6.3 Exact-version artifact
- [ ] 6.4 Backend/API smoke
- [ ] 6.5 Frontend smoke
- [ ] 6.6 Permissions
- [ ] 6.7 Tenant isolation
- [ ] 6.8 Backup
- [ ] 6.9 Rollback
- [ ] 6.10 STAGING ACCEPTED

## 🚀 7. Ограничен production pilot
- [ ] 7.1 Owner approval за pilot
- [ ] 7.2 Exact production SHA/release manifest
- [ ] 7.3 Backup преди deploy
- [ ] 7.4 Deploy
- [ ] 7.5 Smoke след deploy
- [ ] 7.6 Ограничени реални потребители/обекти
- [ ] 7.7 Incident/error observation
- [ ] 7.8 Rollback readiness
- [ ] 7.9 Pilot verdict

## ✅ 8. Stable production
- [ ] 8.1 P0 defects = 0
- [ ] 8.2 P1 operational blockers = 0
- [ ] 8.3 Backup/restore доказани
- [ ] 8.4 Daily-use acceptance by Krum
- [ ] 8.5 LIVE-OPS marked STABLE
- [ ] 8.6 Canonical Wave development continues independently

---

# 📌 Винаги видим статус

### 🔴 ТЕКУЩО
**OWNER DECISIONS — DONE; следва Mockup v2**

### ⏭️ СЛЕДВА
**Technical contract freeze**

### 👤 KRUM ACTION
**UX v2 е одобрен; следва technical contract freeze**

### 💻 CODE ACTION
**Няма LIVE-OPS implementation преди owner decisions + Mockup v2 + contract freeze**

Next decision: **няма business decision преди двата review-а**

Current owner action: **none**

Current code action: **none for LIVE-OPS until audit is complete**



## OWNER DECISIONS — APPROVED
- [x] Pilot only after Permission Service + AuditEvent enforcement.
- [x] warehouse_transactions = canonical authoritative movement ledger.
- [x] warehouse_batches = FIFO/batch/cost projection, not second stock source.
- [x] central = canonical warehouse type.
- [x] main = legacy inconsistency to reconcile/migrate with dry-run + rollback proof.

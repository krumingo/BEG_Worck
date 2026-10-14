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

## 🧭 Управляващ принцип

- GPT носи отговорност за последователността на плана.
- FLOW-first е методът за изпълнение на задачите вътре в плана, не заместител на плана.
- Приоритет: правилно работеща програма без повторно пренаписване > скорост на всяка цена.
- Планът може да цели по-бърза употреба, но не може да прескача зависимости, да чупи FLOW логика или да създава паралелни решения.
- Owner testing се поставя там, където функционалният scope е достатъчно цялостен за смислен тест.

**FLOW-FIRST Е МЕТОДЪТ, НЕ ЗАМЕСТИТЕЛ НА ПЛАНА.**

### ⚡ ACCELERATION MODE

- При correction loop CODEX първо пуска само предишните failing Real-Mongo тестове + директно засегнатите тестове.
- Пълен acceptance matrix се пуска само след като bounded failing tests станат зелени.
- Пълен FLOW/v6 reread не се повтаря при всяка микро-корекция; четат се засегнатите clauses, освен при ново противоречие.
- Изолираната Mongo replica-set среда се преизползва между correction cycles, когато е технически възможно.
- Бъдещите implementation tasks се режат на по-малки dependency-safe блокове, целево до 1–2 correction cycles.
- CLAUDE не маркира runtime условие като затворено, ако не е било реално изпълнено.
- PASS остава само след пълен финален gate: 0 failed / 0 errors / 0 skipped / exit 0.


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
- [x] 2.4 Проверка кое вече работи end-to-end
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
- [x] 3.4 Mockup v2 — desktop control screen
- [ ] 3.5 Mockup v2 — Заявки
- [ ] 3.6 Mockup v2 — Склад
- [ ] 3.7 Mockup v2 — Машини / инструменти
- [ ] 3.8 Mockup v2 — phone-first screens
- [x] 3.9 Крум одобрява UX v2

## 📐 4. Freeze на technical contract
- [x] 4.1 Reuse map: кои текущи models/routes/screens се използват
- [x] 4.2 Missing technical links
- [x] 4.3 Permission matrix
- [x] 4.4 AuditEvent coverage
- [x] 4.5 Tenant/project isolation
- [x] 4.6 Feature flags
- [x] 4.7 Migration plan
- [x] 4.8 Rollback plan
- [x] 4.9 Required acceptance tests
- [x] 4.10 CODEX independent contract review
- [x] 4.11 CLAUDE independent contract review
- [x] 4.12 Krum resolves only true business decisions

## 🛠️ 5. FLOW-first implementation на последователни функционални блокове

> Правило: owner staging acceptance не затваря частичен екран. То идва след завършен релевантен FLOW scope.
> Всеки блок започва с пълен прочит на FLOW-овете + реалния код и FLOW↔CODE map.

### 🖥️ LIVE-OPS-A — Control center / read-only
- [x] 5A.1 Implementation
- [x] 5A.2 Tests
- [x] 5A.3 CODEX independent review
- [x] 5A.4 PASS
- [x] 5A.5 Staging accepted

### 📋 LIVE-OPS-B — Material Requests core (FLOW-020 request domain)
- [x] 5B.1 Safe-write request implementation
- [x] 5B.2 Real-Mongo + frontend tests
- [x] 5B.3 CODEX independent review
- [x] 5B.4 PASS_CANDIDATE
- [ ] 5B.5 Final acceptance — отлага се до integrated Materials FLOW gate

### 🏭 LIVE-OPS-C — Canonical Warehouse / Stock core (FLOW-009 + FLOW-032 + FLOW-002 + FLOW-040)
- [x] 5C.1 Full FLOW read + FLOW↔CODE map
- [x] 5C.2 Canonical warehouse movement implementation
- [x] 5C.3 FIFO/value projection + reconciliation
- [x] 5C.4 Return/quarantine/revision/correction
- [x] 5C.5 Permissions + AuditEvent + tenancy
- [ ] 5C.6 Real-Mongo concurrency/idempotency tests
- [ ] 5C.7 CODEX independent review
- [ ] 5C.8 PASS

### 🚚 LIVE-OPS-D — Logistics / Delivery / Acceptance (FLOW-012 + FLOW-020 + FLOW-009)
- [ ] 5D.1 Full FLOW read + FLOW↔CODE map
- [ ] 5D.2 Trip / delivery / loading-unloading implementation
- [ ] 5D.3 Quantity acceptance / technical acceptance
- [ ] 5D.4 Partial/missing/damaged/refused flows
- [ ] 5D.5 Offline/phone-first driver and receiver UX
- [ ] 5D.6 Permissions + AuditEvent + file evidence links
- [ ] 5D.7 Real-Mongo + frontend/E2E tests
- [ ] 5D.8 CODEX independent review
- [ ] 5D.9 PASS

### 🧾 LIVE-OPS-E — Full Materials lifecycle integration (FLOW-020 + dependencies)
- [ ] 5E.1 Full FLOW-020/dependency read + FLOW↔CODE map
- [ ] 5E.2 Request → order/supplier-confirmation facts
- [ ] 5E.3 Invoice-line classification/allocation without double counting
- [ ] 5E.4 Direct delivery vs warehouse path
- [ ] 5E.5 Accepted quantity → project cost rule B
- [ ] 5E.6 Material readiness / shortages / remaining quantities
- [ ] 5E.7 Master aliases / pending mapping integration
- [ ] 5E.8 Material budget / consumption projection
- [ ] 5E.9 End-to-end FLOW-020/012/009 tests
- [ ] 5E.10 CODEX independent review
- [ ] 5E.11 PASS

### 🔗 LIVE-OPS-F — Integrated Materials Gate
- [ ] 5F.1 Request → approval → procurement/delivery → acceptance → stock/site availability → consumption
- [ ] 5F.2 Partial / over / under / damaged / refused scenarios
- [ ] 5F.3 Real Mongo replica-set
- [ ] 5F.4 Permissions / tenant / project isolation
- [ ] 5F.5 Canonical AuditEvent completeness
- [ ] 5F.6 Backup / restore / rollback proof
- [ ] 5F.7 Desktop E2E
- [ ] 5F.8 Phone E2E
- [ ] 5F.9 Independent PASS
- [ ] 5F.10 Owner staging acceptance for Materials flow

### 🧰 LIVE-OPS-G — Machines / tools complete flow
- [ ] 5G.1 Full FLOW-011/dependencies read + FLOW↔CODE map
- [ ] 5G.2 Asset/custody/repair implementation
- [ ] 5G.3 Two-phase handover + QR
- [ ] 5G.4 Permissions / AuditEvent
- [ ] 5G.5 Real-Mongo + phone/desktop E2E
- [ ] 5G.6 CODEX independent review
- [ ] 5G.7 PASS
- [ ] 5G.8 Owner staging acceptance

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
**LIVE-OPS-C implementation HANDOFF готов — CODEX independent review**

### ⏭️ СЛЕДВА
**CODEX independent review на PR #55 + задължителен Real Mongo gate**

### 👤 KRUM ACTION
**Няма owner action; staging acceptance за Materials се мести след integrated FLOW gate**

### 💻 CODE ACTION
**Implementation вече може да започне само по frozen contract и на малки bounded slices**

Next decision: **няма owner decision pending**

Current owner action: **none**

Current code action: **review PR #55 exact head 027be29d... against FLOW + real frozen v6 contract**



## OWNER DECISIONS — APPROVED
- [x] Pilot only after Permission Service + AuditEvent enforcement.
- [x] warehouse_transactions = canonical authoritative movement ledger.
- [x] warehouse_batches = FIFO/batch/cost projection, not second stock source.
- [x] central = canonical warehouse type.
- [x] main = legacy inconsistency to reconcile/migrate with dry-run + rollback proof.


## CONTRACT FREEZE — READY
- [x] Version: v6-contract-freeze
- [x] Final SHA-256: 489525BF36D69182CC0AED49EED2BA22C9883435021C4AF81241A3CB57700C3E
- [x] Baseline: 79af297612f57c055bb7caef3f0c48493800d1b6
- [x] CLAUDE verdict: READY_FOR_FREEZE
- [x] OWNER_DECISION: NONE
- [x] F1–F9, R1–R5, N1 closed
- [x] No runtime PASS claimed

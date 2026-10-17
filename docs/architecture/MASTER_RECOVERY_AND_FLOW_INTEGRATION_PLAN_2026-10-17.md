# BEG_Work — Master Recovery & FLOW Integration Plan

> Date: 2026-10-17
> Owner direction: Krum Radulov
> Status: canonical execution direction for recovery + FLOW integration
> Scope: post-audit recovery, usable-product integration, runtime validation and continued FLOW completion

## 1. Purpose

BEG_Work is not to be treated as a bug-fix-only project.

The program must progress on two coordinated tracks:

1. **Recovery / healing**
   - security;
   - tenant isolation;
   - permissions;
   - auditability;
   - data integrity;
   - financial integrity;
   - warehouse/material integrity;
   - auth/recovery;
   - broken workflows;
   - dead UI.

2. **FLOW integration**
   - missing screens;
   - missing tables;
   - missing fields;
   - incomplete cross-module links;
   - incomplete workflows required by canonical FLOW/decisions.

The goal is to reach a **usable integrated application as early as safely possible**, then validate it through real work, and continue FLOW completion from observed runtime evidence.

## 2. Owner decisions carried forward

- FLOW is the business source of truth.
- Existing implementation must be reused when correct; no duplicate parallel source-of-truth models.
- Every new screen or structural UI change requires:
  current screen -> FLOW gap map -> mockup -> Krum approval -> implementation.
- A feature is not complete because code exists or tests pass.
- Completion requires runtime integration and, where applicable, real-use validation.
- Codex prepares/reviews; Claude implements; GitHub is the evidence/control plane; Krum alone decides merge/deploy/business acceptance.
- No merge or deploy without explicit Krum decision.
- Consequential chat/voice actions require explicit confirmation according to FLOW rules.

## 3. Master execution waves

### R0 — Immediate P0 recovery

Priority:
1. D-045 subscription-plan mutation / production mock billing
2. D-026 tenant isolation override
3. D-025 role/email privilege escalation
4. D-023 Pay Runs includes unselected employees
5. D-043 paid Pay Run reopen/double-pay path
6. D-039 production dev-reset hardening
7. D-009 Stripe webhook fail-open hardening
8. AUTH-01 PR #56 corrections F-01..F-08 + independent re-review

Rules:
- one bounded correction package at a time;
- exact-head independent review;
- no unrelated cleanup;
- declare data-remediation impact;
- no production mutation during verification unless separately approved.

### R1 — Canonical integrity recovery

Repair canonical foundations:
- tenant/permission boundaries;
- canonical audit path;
- one Payment source of truth;
- canonical warehouse/material ledger;
- payroll/advance/payment reconciliation;
- finance/P&L consistency;
- reversal/correction instead of destructive history changes.

Exit condition:
critical business entities have one declared source of truth and cross-module totals reconcile.

### U1 — Usable operational core

Build/integrate the usable core:
- Projects/Object control;
- SMR;
- schedule/readiness;
- materials/procurement;
- warehouse/site availability;
- daily progress.

### U2 — Commercial + financial flow

Integrate:
Change Order -> Analysis -> Offer -> Approval -> Execution -> Act -> Invoice -> Payment -> Profitability.

### U3 — Owner control

Integrate:
- questions;
- blockers;
- reminders;
- escalations;
- readiness warnings;
- owner control center.

### P1 — Real-work pilot

When the integrated core is stable enough:
- use it on selected real workflows/projects;
- log friction and defects;
- distinguish bug vs missing FLOW vs UX issue;
- fix in bounded slices;
- preserve canonical-data gates.

### F1 — Remaining FLOW coverage

Complete the remaining approved FLOW modules and secondary capabilities after the pilot stabilizes.

## 4. Vertical-slice rule

Recovery and FLOW development are not separate sequential projects.

For each business slice use:

CURRENT RUNTIME
-> FLOW GAP MAP
-> MOCKUP
-> KRUM APPROVAL
-> TECH CONTRACT
-> IMPLEMENTATION
-> CODEX INDEPENDENT REVIEW
-> INTEGRATION
-> RUNNABLE APP
-> REAL-USE TEST
-> CORRECTIONS
-> CLOSE

## 5. Required vertical slices

### 5.1 Project / Object Control Center

Object -> location/subobject -> SMR -> schedule -> readiness -> people/materials/issues -> progress -> money.

Must include:
- project overview;
- SMR operational table;
- location granularity;
- responsible person/brigade;
- dependencies/readiness;
- links to materials, questions, documents, daily progress, change orders and finance;
- warnings/blockers.

### 5.2 FLOW-027 schedule backbone

Must include:
- SMR-driven schedule;
- start date + working days;
- drag-to-start;
- dependencies;
- baseline/current/forecast separation;
- Today line;
- readiness prerequisites;
- blocking questions/materials/payments;
- 14-day readiness;
- latest-safe-action alerts.

The schedule is a backbone, not a second task ledger.

### 5.3 Materials / Procurement / Warehouse

Need -> Request -> RFQ -> Supplier Offers -> Selection -> Order -> ETA -> Delivery -> Receipt -> Site Availability -> Consumption -> Balance.

Mandatory distinction:
ORDERED != DELIVERED != RECEIVED ON SITE != CONSUMED.

### 5.4 People / Daily Reports / Payroll

Employee -> Role Assignment -> Brigade -> Object -> Attendance -> Daily Report -> Executed Qty -> Accepted Qty -> Rate -> Accrual -> Advance -> Settlement.

### 5.5 Change Orders / Offers / Acts

Request -> Scope -> Qty -> Analysis -> Offer -> Approval -> Execution -> Act -> Invoice -> Payment -> Standalone Profitability.

Client-public output must not expose internal cost, markup, risk, or internal analytical notes.

### 5.6 Finance

Canonical:
- invoices;
- payments;
- accounts;
- balances;
- project P&L;
- cash flow;
- unpaid/overdue;
- source-record drilldown.

### 5.7 Alerts / Questions / Owner Control

FLOW-045 behavior:
- responsible person;
- deadline;
- priority;
- object/FLOW link;
- blocking impact;
- reminder until resolved;
- escalation;
- explicit follow-up deadline for deferred answers;
- no consequential action without confirmation.

## 6. UI / mockup gate

For every new screen or structural UI change:

1. identify current runtime screen;
2. identify canonical FLOW requirements;
3. produce mockup;
4. obtain Krum approval;
5. only then implement.

Do not invent UI from developer preference.

## 7. Development protocol per bounded slice

1. **Codex task package**
   - Task-ID;
   - exact base SHA;
   - FLOW/decision references;
   - runtime evidence;
   - approved mockup reference;
   - scope / forbidden scope;
   - acceptance criteria;
   - test plan.

2. **Claude implementation**
   - branch;
   - code;
   - tests;
   - commit;
   - push;
   - Draft PR;
   - HANDOFF.

3. **Codex independent review**
   - exact head;
   - positive/negative tests;
   - tenant/permission/data integrity;
   - runtime/UI evidence.

4. Verdict:
   - PASS; or
   - bounded CHANGES_REQUESTED.

5. Integration/staging.
6. Krum runtime/real-use review where applicable.
7. Close only after acceptance.

## 8. Definition of Done for a business FLOW

A FLOW is done only when:
- UI/mockup is approved;
- required fields/actions exist;
- backend rules match FLOW;
- canonical data is stored once;
- downstream modules reflect the change correctly;
- tenant/permissions are correct;
- audit/history exists where required;
- reverse/error paths are defined;
- automated tests pass;
- runtime/staging test passes;
- real-use acceptance is completed where applicable.

## 9. Current starting point

- Full independent application audit completed 2026-10-16/17.
- Recovery begins with R0.
- PR #56 AUTH-01 is CHANGES_REQUESTED and requires bounded F-01..F-08 correction + Codex re-review.
- After R0 is controlled, begin Project/Object Control Center with:
  CURRENT SCREEN -> FLOW GAP MAP -> MOCKUP -> KRUM APPROVAL.

## 10. Canonical direction

**Healing + FLOW integration -> usable application -> real-work testing -> continued FLOW completion.**

This document is the controlling execution plan for that direction. If another implementation document conflicts with this sequencing or UI/mockup gate, stop and reconcile before coding.

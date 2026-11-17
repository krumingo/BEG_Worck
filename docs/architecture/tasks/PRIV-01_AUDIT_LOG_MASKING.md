# PRIV-01: pay and rate values in the legacy `audit_logs`, and the retention of an AI proposal

> Package t51. This applies the canon and adds no new business rule. Findings from FLOW Guard pass 72 on main `3863610`: FG-726 (medium) and FG-725 (low). Branch `claude/priv-01-audit-log-masking`, draft PR. Not merged and not deployed.

## Canon

- **FLOW-040 §9:** "банкови сметки, лични номера, заплати и PII се маскират според ролята"; "before/after използва field-level diff и references"; "export-ът прилага същата permission и masking политика като екрана".
- **FLOW-040 §11:** the Administrator "няма автоматичен достъп до payroll, банково съдържание или лични AI разговори без отделно sensitive-domain право"; Platform support / DR operator: "business content само чрез break-glass, две одобрения и time-bound access".
- **FLOW-040 §6, R4:** "structured metadata, tool calls, показана чернова, human confirmation и official action — наследяват R1/R2/R3 според действието".

## Findings on main `3863610`

| ID | Where | What |
|---|---|---|
| FG-726 | `backend/app/routes/hr.py:164` | `PUT /employees/{id}` wrote `hourly_rate`, `daily_rate`, `monthly_salary`, `insurance_*` and `akord_note` in clear into `audit_logs`. `GET /audit-logs` returned them unmasked to any `is_platform_admin` user, with no payroll right and no break-glass. |
| FG-726 (grep) | `backend/app/routes/work_logs.py:100` | `PATCH /work-types/{id}` logged `default_hourly_rate` in clear. |
| FG-726 (grep) | `backend/app/routes/hr.py:318` | `advance_created` logged the advance `amount`. An advance to a person is deducted from their pay. |
| FG-725 | `backend/app/master_data/pending.py:299` | An AI master-data proposal was recorded as R4. A human proposal of the same record was recorded as R2. |

## What changed

1. **Write** (`app/audit/pay_masking.py`, used by both legacy sinks `app/utils/audit.py` and `app/services/audit.py`):
   - A pay or rate value never reaches `audit_logs` in clear. Every route that logs one is covered, including routes added later.
   - The key stays, so the fact that the value changed is kept. The value becomes the marker `{"masked": true, "kind": "pay_or_rate", "changed": true}`.
   - The marker is not a hash: a salary hash is easy to brute-force.
   - The reference to the real value is the row's own `entity_type` / `entity_id`. The value lives only in its source record (`employee_profiles`, `work_types`, `advances`).
2. **Read** (`GET /audit-logs`, `app/routes/auth.py`):
   - The route still requires a platform admin.
   - On top of that, every row is masked unless the caller holds `finance.pay_run.read`. This covers rows written before PRIV-01 in clear; they stay stored as they are, append-only, not rewritten and not deleted.
   - `finance.pay_run.read` is the payroll read action of the catalog (R20-1, CANON_PAY). Its holders are Owner, Admin and Accountant.
   - In off and shadow, the decision is the legacy role. In enforce, the Permission Service decides at company scope. `is_platform_admin` never grants the right.
   - There is no break-glass or Support Access Grant runtime, so a platform admin without the right is simply masked.
3. **Retention** (`proposal_retention_class` in `app/master_data/pending.py`):
   - An AI proposal now gets the class of the record it proposes for, the pending mapping record (R2). This is the same class as a human proposal.
   - The event carries no raw prompt or response, so R4 does not apply.
   - `tests/test_w0_03b2_pending_mapping.py::test_ai_proposal_is_attributed_to_its_model` used to pin the old R4 value. It now asserts R2.

## Interim decisions and debt (for Krum)

- **D1, the payroll action:** the catalog has no action named "payroll audit". PRIV-01 uses the existing `finance.pay_run.read`. A dedicated `audit.payroll_values.read` would be a new catalog entry, which needs Krum's decision.
- **D2, Admin and §11:** FLOW-040 §11 says the Administrator has no automatic payroll access. The catalog (R20 / SEC-02) gives Admin `finance.pay_run.read` through Admin's full set, and PRIV-01 follows the catalog, so a platform admin with role Admin still sees the values. Whether Admin should lose payroll reads is Krum's decision, and it would change R20 for every payroll screen.
- **D3, the Owner:** FLOW-040 §11 gives the Owner L3 over the whole tenant. `GET /audit-logs` is still platform-admin only, so an Owner without the flag gets 403. That is unchanged by PRIV-01.
- **D4, break-glass (debt):** there is no break-glass or Support Access Grant runtime for audit reads. The only break-glass that exists is the AUTH-02 password recovery CLI. The L5 runtime is FLOW-040 §10 work that has not been built.
- **D5, other money in `audit_logs`:** payment, invoice, overhead and budget amounts (for example `activity_budgets.labor_budget`) are not pay or rate, so PRIV-01 does not mask them. A finance-role masking rule for them would be a separate decision.
- **D6, the retention subject:** if Krum considers the subject of the proposal to be the Master record (R1) rather than the pending record (R2), that is a one-line change in `proposal_retention_class`.
- **D7, legacy rows:** existing clear rows are masked when read, but not rewritten. The audit log is append-only and nothing is migrated. Physically removing the clear values would be a FLOW-040 §7 disposition with Approval and a manifest.
- **D8, `/dashboard/activity`:** this route reads `audit_logs.details`, which `log_audit` never writes. It does not return `changes`, so PRIV-01 leaves it unchanged. `GET /audit-logs` masks `details` as well, if that field is ever present.

## Tests

`backend/tests/test_priv_01_audit_log_masking.py` runs 65 tests: mongomock plus real Mongo, in off, shadow and enforce.

- **Write:** an HR profile update stores no pay value in clear, and the key is kept. Both sinks are covered, including the work-type rate and the advance amount.
- **Positive:** a platform admin who holds the right (Accountant, Admin) sees the values.
- **Forbidden:** a platform admin with role Viewer, SiteManager or Technician gets the values masked. In enforce, `users.role=Admin` with a revoked assignment is also masked.
- **Tenant isolation:** each tenant's platform admin sees only its own rows (A↔B).
- **Retention:** an AI proposal gets R2, the same class as a human proposal.
- **Canon quotes:** the lines quoted from FLOW-040 are present in the canon.
- **Red on main:** 34 failed and 31 passed (`docs/evidence/PRIV-01/red_on_main.txt`).

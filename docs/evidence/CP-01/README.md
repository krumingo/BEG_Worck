# CP-01: counterparties — verified IBAN before payment, never deleted, hidden ЕГН, rights and audit

Package: `docs/architecture/tasks/CP-01_COUNTERPARTY_IBAN_EGN_NO_DELETE.md` (branch `claude/happy-meitner-bmcnel` @ e96cde8). Decision **R48** (Krum, 08.11.2026). Oracle **Q003** (`claude/flow-guard` @ 687786e). FLOW Guard FG-165, FG-167, FG-171, FG-172, FG-175 (partly).

Canon: FLOW-010 §3.3, §8, §12; FLOW-006; FLOW-025 L146, L187; FLOW-032 L46, L99, L105, L109–112; FLOW-040 §9, §11; CLAUDE.md §2, §8, §14, §15.

Branch `claude/cp-01-counterparty-iban` from main `cd03324`. No merge, no deploy, no production access.

## 1. What was wrong on main (proved first)

`backend/tests/test_cp_01_counterparty_iban_egn.py` was run against main `cd03324` on a real MongoDB 7.0 replica set before any fix. Result: **174 failed, 28 passed** (`red_on_main_cd03324_real_mongo.txt`).

| Problem | Red test(s) on main |
|---|---|
| A payment to an unverified or changed IBAN is executed | `test_red_payment_to_an_unverified_account_is_refused`, `…quick_pay_with_an_invoice_iban…`, `…subcontractor_payment…`, `…during_an_iban_change…` |
| DELETE of a counterparty, client, company or person deletes or soft-deletes it | `test_red_delete_never_deletes` (5 × 3 modes) |
| Viewer, SiteManager and Technician create and edit clients, companies, persons and subcontractors, and change the client of a project | `test_red_other_roles_cannot_create_or_edit` (81 of 108 cells red; the 27 green ones are the counterparty and client routes that were already office-only) |
| A Viewer (and every role) reads the full ЕГН | `test_red_no_reader_returns_the_full_egn` (18 red) |

## 2. Source of truth and data model (additive)

| Collection | Owner | Content |
|---|---|---|
| `verified_bank_accounts` (new) | FLOW-010 §3.3 | `party_type` (counterparty / subcontractor), `counterparty_id`, `iban` (normalised, mod-97), `bic`, `bank_name`, `holder`, `currency`, `status`, `is_change`, `replaces_account_id`, `evidence_file_ids`, `entered_by`/`entered_at`, `verification` {verified_by, verified_at, 2 sources {kind, description, source_origin}, counterparty_confirmed_by, evidence_file_ids}, `approvals` [{approval_id, approver_id, role, at, version}], `version`, `replaced_by_account_id` |
| `finance_payments` (FLOW-006, unchanged ledger) | FLOW-006 | Outgoing payments to a counterparty now carry `bank_account_id` and `bank_account_iban_masked`. No second ledger. |
| `counterparties`, `clients`, `companies`, `persons`, `subcontractors` | FLOW-010 / FLOW-032 | new fields: `lifecycle_status` (active / inactive / archived), `archived`, `lifecycle_reason`, `lifecycle_changed_by/at`, `version`, `created_by`, `updated_by`; counterparty `eik_change_request`, `eik_change_history` |
| `dq_issues` (new, minimal) | until W0-07 | DQ rows: `INVOICE_IBAN_MISMATCH` (critical), `BANK_ACCOUNT_CHANGE` (critical), `DUPLICATE_EIK` (critical), `PAYMENT_WITHOUT_VERIFIED_ACCOUNT` (shadow) |
| `counterparty_eik_claims`, `company_eik_claims` (new) | bookkeeping | one row per ЕИК; two concurrent writes of the same ЕИК write the same row in their transactions, so one conflicts and is retried |

Statuses: `pending_verification` „за проверка“, `verified` „проверена“, `replaced` „заменена“, `rejected` „отказана“.

Records written before CP-01 have no `lifecycle_status`; it is derived from the legacy `active`/`is_active` flag (`counterparty_rules.lifecycle_of`). No backfill is needed.

## 3. Rules implemented

### 3.1 Verified bank accounts (FG-165, FG-175, R48.1, R48.2)

| Endpoint | Rule |
|---|---|
| `POST /counterparties/{id}/bank-accounts`, `POST /subcontractors/{id}/bank-accounts` | Owner / Admin / Accountant. IBAN mod-97 → else 422 `IBAN_INVALID`. Evidence is a list of `file_id`s; a URL or path → 422 `EVIDENCE_NOT_FILE_ID`. The same IBAN pending or verified again → 409. Status „за проверка“. If the party already has a verified account, this is a **change**: a critical DQ row is written and the Owner and the Accountant are notified at once (R48.2). |
| `POST /bank-accounts/{id}/verify` | Owner or Accountant only (403). The person who entered it → 409 `SAME_PERSON_VERIFICATION`. Two sources of different kinds → else 422 `TWO_SOURCES_REQUIRED` / `SOURCES_NOT_INDEPENDENT`; both from the invoice (L274) → 422. `counterparty_confirmed_by` is required. The exact `version` is required (CAS). A first IBAN becomes „проверена“ (R48.1: no separate approval). |
| `POST /bank-accounts/{id}/approve-change` | Only for a verified change. Owner or Accountant, two **different** people, each approving the exact `version` → 409 `VERSION_CONFLICT` / `ALREADY_APPROVED`. On the second approval, in the same transaction: the new account → „проверена“, the old → „заменена“, notification to Owner and Accountant. |
| `POST /bank-accounts/{id}/reject` | Owner or Accountant, reason, „отказана“. |
| `GET …/bank-accounts` | Owner / Admin / Accountant. Full IBAN only for Owner / Accountant; Admin sees the mask (D5). |

### 3.2 FLOW-006 blocking (`app/services/bank_account_guard.py`)

Applied to every path that executes an outgoing payment to a counterparty, before anything is written:
- manual payment / advance: `POST /finance/payments` (new optional `counterparty_id`, `bank_account_id`);
- invoice quick-pay: `POST /finance/invoices/{id}/payments` (the counterparty comes from `supplier_counterparty_id`, else from the ЕИК on the invoice);
- subcontractor payment: `POST /subcontractor-payments`.

| Case | Result |
|---|---|
| `bank_account_id` named and not this counterparty's, or not „проверена“ | 409 `BANK_ACCOUNT_NOT_VERIFIED`, nothing written |
| IBAN on the invoice (new field `counterparty_iban`, FG-175) ≠ a verified account of the counterparty | critical DQ `INVOICE_IBAN_MISMATCH` + 409 |
| the counterparty has a verified account | the payment goes to it and is stamped with it; a pending change never gets the money |
| the counterparty has only unverified accounts | 409 |
| legacy: no account named or registered, or no counterparty identified | `BANK_ACCOUNT_GUARD_MODE`: `off` = log only, `shadow` = DQ row + metric, `enforce` = 409. **Default `shadow`** (D1) |
| incoming payment; cash payment without account or IBAN | not checked (D6) |
| inactive or archived counterparty | 422 `COUNTERPARTY_NOT_SELECTABLE` |

Nothing unlocks the block: no flag, role or Approval (FLOW-025 L187). A verified IBAN is not an approval of the payment (L296): every PAY-01 rule (amount, reason, key, locks) still applies.

### 3.3 Never deleted (FG-167, R48.4)

- `DELETE /counterparties/{id}`, `/clients/{id}`, `/persons/{id}`, `/companies/{id}` → **409 `COUNTERPARTY_NO_DELETE`**, nothing written, with the alternatives in the detail. This applies to used and unused records, in every `MASTER_DATA_MODE`.
- `POST …/{id}/deactivate` and `…/reactivate`: Accountant / Admin / Owner. `POST …/{id}/archive`: Admin / Owner. Reactivating an **archived** record: Admin / Owner only (D8). Each needs a reason (400 otherwise) and writes a canonical AuditEvent.
- Archived records are hidden from the lists unless `include_archived=true`, and they are read-only (update → 409 `COUNTERPARTY_ARCHIVED`).
- Inactive or archived records cannot be chosen for a payment, an invoice (by ЕИК or `supplier_counterparty_id`), the client of a project (client-link, project create/update) or a counterparty→client link. Each of those returns 422. History stays readable.
- `PUT` with a changed `active` / `is_active` → 422 `USE_LIFECYCLE_ROUTE`. The same value is accepted.

### 3.4 Rights, audit, idempotency (FG-171, R48.5, R48.6, R22, R29)

- Create and update of counterparties, clients (including find-or-create when it creates), companies, persons and subcontractors, plus the counterparty↔client link: **Owner, Admin, Accountant only**. Everyone else gets 403 before anything is read or written. R22: the client of a project (`PATCH /projects/{id}/client-link`, and owner changes in `PUT /projects/{id}`) is changed only by those three roles.
- Every such write needs an `Idempotency-Key` (428 without one). It runs in **one transaction** (`auth_tx.run_in_transaction`) holding the CAS on `version`, the canonical AuditEvent (`record_event(session=…)`, FLOW-010, R1) and the completion of the key. A replay returns the first result. The same key with another body → 409. The ЕГН and IBAN are masked in every AuditEvent diff.
- ЕИК: a new counterparty or company with an existing ЕИК (normalised) → **409 `EIK_ALREADY_EXISTS`**, plus a critical DQ row written outside the aborted transaction. The first ЕИК of a record is set directly. A **change** of an existing ЕИК needs `eik_change_reason` and is stored as a pending request. `POST /counterparties/{id}/eik-change/approve` (or `/reject`) is done by a **different** Owner / Admin / Accountant, who names the exact `request_id` → otherwise 409 `SAME_PERSON_APPROVAL` / `VERSION_CONFLICT`. The duplicate check runs again on approval. Merge is not here (FG-166 → CP-02).
- Rights were only narrowed. The PM-01 diff (§5) has no cell that newly writes.

### 3.5 ЕГН (FG-172, R48.3)

- Every reader shows **`******1234`**, for every role, Owner and Accountant included: `/persons` list, detail and find-by-phone, `/clients/search/unified`, `/projects/{id}/client-info`, `/projects/{id}/invoice-context`, `GET /projects/{id}` (`invoice_details` copied before CP-01), and the create responses and conflict messages.
- `import-client-invoice` no longer copies a full ЕГН into a project.
- **`POST /persons/{id}/egn/reveal`**: Owner and Accountant only (403 for everyone else). Each reveal commits a canonical AuditEvent `person.egn.revealed` (who, when, whose; the event holds only the mask) **before** the value is returned.
- Test: 6 roles × 7 readers, plus import-client-invoice — no full ЕГН in any response.

## 4. Migration

`backend/scripts/cp_01_migrate_bank_accounts.py --mongo-url … --db …` runs as a dry run by default; `--apply` writes.
- IBANs found in counterparty and subcontractor fields (`iban`, `IBAN`, `bank_iban`, `bank_account`, `bank_account_iban`) become `verified_bank_accounts` rows with status „за проверка“, **never** „проверена“. Rows are per tenant, with deterministic ids and `$setOnInsert`, so the script is idempotent. Invalid IBANs are only reported, masked.
- The report also counts projects that still hold a person's full ЕГН in `invoice_details` (masked on read; nothing is rewritten).
- It never deletes. Tested in `test_migration_dry_run_then_apply_is_pending_and_idempotent` (mongomock + real).

## 5. Tests and gates

All runs: this container, MongoDB 7.0 replica set `rs0` in Docker, `W0_03_REAL_MONGO_URL` set, `PYTHONPATH=. pytest --noconftest -q -p no:cacheprovider`. Raw summaries: `gates.txt`.

| Gate | main cd03324 | branch |
|---|---|---|
| CP-01 (`test_cp_01_counterparty_iban_egn.py`, mongomock + real, off/shadow/enforce) | real: **174 failed**, 28 passed | **401 passed**, 3 skipped (the mongomock copies of the transaction-concurrency test; all 202 real cases pass) |
| R0 (`tests/test_r0_*.py`) | 814 passed | **814 passed** |
| W0 (`tests/test_w0_*.py`) | 15 failed, 1177 passed | **9 failed**, 1165 passed — every one of the 9 is also among main's 15 (see below) |
| PAY-01 (`tests/test_pay_01*.py`) | — | **630 passed, 0 skipped** |
| PM-01 (`test_pm_01_permission_matrix.py`, real, `-rs`) | — | **6 passed, 0 skipped**; matrix regenerated by the harness only |
| A1 guard | 472 units, 0 violations | 482 units, **0 violations** |
| A2C guard | 234 modules, 0 violations | 239 modules, **0 violations** |
| frontend `yarn test` | — | 17 suites, 170 passed |
| full DB-free suite (`tests/`, no real Mongo) | 166 failed, 2337 passed, 996 errors (live-API tests without a server) | 160 failed, 2527 passed, 993 errors — the FAILED/ERROR set is a **strict subset** of main's, nothing new |

**W0, honestly:** the known 15 failures are all in `test_w0_03e_legacy_routes.py`; the `TENANT_NOT_REGISTERED` ones come from the order of modules in the full run. Six of them were the persons/companies cells of the "an unused identity may still be hard-deleted" matrix. R48.4 removes that contract for counterparties, clients, companies and persons, so those four collections moved out of `DELETE_PATHS` into a new test, `test_cp01_counterparty_identities_are_never_deleted` (409, both tenants' rows intact, no AuditEvent, foreign id → 404). That is why the count went from 15 to 9 and not to 15. No test that passed on main fails on the branch.

Test files changed because the contract changed:
- `test_w0_03e_legacy_routes.py`: the 4 collections are covered by the new test. The shadow, adapter-permission, tenant-resolution and invalid-mode tests that used `clients` as their example now use `location_nodes`, which still has the legacy delete.
- `test_w0_03e_a2b_two_tenant_gate.py`: the HTTP helper sends an `Idempotency-Key` (R29). The ownership assertions are unchanged.
- `docs/architecture/W0-03E-A1_INVENTORY.md` was regenerated (377 → 361 accesses, all SAFE or FIXED, none UNSCOPED); `W0-03E-A2B_INVENTORY.md` §1/§3 were regenerated (the 5 new collections are classified in `ownership.py`).

**PM-01:** 767 → 789 routes. 279 existing cells changed, all toward refusal: 403 for the non-office roles, and 428 for the office roles because the harness sends no key. 528 cells belong to the 22 new routes. No cell newly writes. Per route: `pm01_matrix_diff_vs_main.md`.

## 6. Rollback

Revert the commits. What is left behind:
- the new collections (`verified_bank_accounts`, `dq_issues`, the claim rows);
- the new fields on the records (old code ignores them);
- archived or inactive records keep `active` / `is_active = false`, which old code reads as soft-deleted.

Nothing is deleted automatically. Before a revert, list `verified_bank_accounts` and the records with `lifecycle_status`, and Krum decides what happens to them. There is no index change.

## 7. Debts (not done, for the orchestrator / Krum)

| ID | Debt |
|---|---|
| **CP-01-D1** | `BANK_ACCOUNT_GUARD_MODE` defaults to **`shadow`**: a legacy payment that names no account, to a party with no registered IBAN, still passes with a DQ row. `enforce` refuses it. Krum decides when to switch to `enforce` (after the migration and the IBAN entry). |
| **CP-01-D2** | Non-office roles get **403**. A „за мапване“ draft/proposal flow (FLOW-032 L99, R48.5 "само предлагат чернова") is not built. |
| **CP-01-D3** | There is no canonical DQ/Approval runtime (W0-07). DQ rows live in `dq_issues`. The IBAN-change approvals are stored on the bank-account record and the ЕИК approval on the counterparty, each with an `approval_id` in the AuditEvent. They move to W0-07 when it exists. |
| **CP-01-D4** | Evidence `file_id`s are checked for shape only (no URL/path). The File Registry (W0-06 stack) is not on main, so their existence is not checked. |
| **CP-01-D5** | The full IBAN is shown to Owner and Accountant; Admin and everyone else get the mask. FLOW-040 §9 says "by role" without a matrix, so Krum should confirm. |
| **CP-01-D6** | Cash payments (no account, no IBAN) are not checked against the register. Krum should confirm. |
| **CP-01-D7** | The two approvers of an IBAN change must be different people. The person who entered or verified the change may be one of them; otherwise a two-person office could never change an IBAN. Not stated in R48. |
| **CP-01-D8** | An archived record can be reactivated by Admin or Owner (the correction path of CLAUDE.md §14). R48.4 does not say whether archiving is reversible. |
| **CP-01-D9** | Subcontractors are a separate collection from counterparties (FLOW-010 wants one MasterOrganization). The register serves both; unification and de-duplication across counterparties, companies and subcontractors → CP-02 / FG-166. The subcontractor ЕИК is not checked for duplicates. |
| **CP-01-D10** | ЕГН: `/clients/search/unified` still accepts a full ЕГН as the query, so it works as an existence check. The Master Data reports (`md_person` identifiers, `uniqueness.mask_value`) use the old `12****90` mask. An invoice to a person now gets a masked ЕГН from import-client-invoice / invoice-context; issuing one with the full ЕГН needs the reveal (no UI yet). |
| **CP-01-D11** | Frontend: there is no UI yet for the bank-account register, verification and approvals, archive/reactivate, ЕИК-change approval or ЕГН reveal. The old delete buttons on Counterparties and Clients now deactivate with a prompt for the reason, and every changed call sends an `Idempotency-Key`. A UX design is needed from Krum. |
| **CP-01-D12** | `POST /subcontractor-payments` is still open to every M2 role and has no `Idempotency-Key` (payment rights → SEC/PAY-01-C01 part 2). `POST /finance/other-expense` (documentless, no counterparty) is not guarded. |
| **CP-01-D13** | `PUT /projects/{id}` with an owner change now enforces R22 and selectability, but it has no key and no AuditEvent of its own; the client-link route has both. |
| **CP-01-D14** | The rewritten routes write only the canonical AuditEvent, not the legacy `audit_logs` rows (`counterparty_created`, `client_created`, `created person/company`). A reader of `audit_logs` for these events would no longer see them (W0-04 parallel-record debt). |
| **CP-01-D15** | A real standalone mongod (no replica set) now refuses these master-data writes with 503 (auth_tx has no fallback). Production Atlas is a replica set. |
| **CP-01-D16** | ЕИК uniqueness uses claim rows, not a unique DB index, because legacy data may already hold duplicates. An index, after a duplicate report, is a follow-up. |
| **CP-01-D17** | The R48.2 notification is the existing in-app `notifications` collection. There is no e-mail or push. |

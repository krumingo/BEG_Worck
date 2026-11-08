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
| ~~CP-01-D1~~ | **Closed by Addendum A / Q005.** The guard is always `enforce` unless `ENV` is staging, development or test (Р15). Production, an unknown `ENV` or a missing `ENV` → enforce. |
| ~~CP-01-D2~~ | **Closed by Addendum A / R50.** Direct writes stay 403, and the 403 names the existing propose path `POST /api/master-data/pending` (`master_data.pending.propose`). The catalog is not widened: SiteManager may propose, Viewer and Technician may not. Remaining: the pending module accepts only the channels ai, ocr, excel and import, so a typed (human) proposal from a field user has no channel → **CP-01-D18**. |
| **CP-01-D3** | There is no canonical DQ/Approval runtime (W0-07). DQ rows live in `dq_issues`. The IBAN-change approvals are stored on the bank-account record and the ЕИК approval on the counterparty, each with an `approval_id` in the AuditEvent. They move to W0-07 when it exists. |
| **CP-01-D4** | Evidence `file_id`s are checked for shape only (no URL/path). The File Registry (W0-06 stack) is not on main, so their existence is not checked. |
| ~~CP-01-D5~~ | **Closed by Addendum A / Q005.** The full IBAN is shown to the Owner and the Accountant, and to an Admin only when one of that Admin's own active RoleAssignments carries `sensitive.iban.read` (none by default; the catalog is untouched). Everyone else gets `****1234`, and so do the AuditEvent, DQ rows, logs and payment stamps. |
| ~~CP-01-D6~~ | **Closed by R50.1.** A cash payment to a counterparty needs `cash_receipt_file_id` and `cash_recipient_name` (422 `CASH_RECEIPT_REQUIRED`). While the counterparty has an unverified IBAN, cash is refused too: 409 `PAYEE_BLOCKED_PENDING_IBAN`. Cash that names no counterparty is not checked. There is no UI field for the receipt yet (D11). |
| ~~CP-01-D7~~ | **Closed by R50.2.** The entrant can never approve. The verifier may be approver 1. Approver 2 must be a different person (409 `SAME_PERSON_APPROVAL`). |
| ~~CP-01-D8~~ | **Closed by R50.3.** Only an Admin or the Owner can bring a record back from the archive, with a reason and an AuditEvent. In the same transaction every verified IBAN of that counterparty or subcontractor goes back to „за проверка“ (`bank_account.reverification_required`), and payments to it are blocked until a new verification. |
| **CP-01-D9** | Subcontractors are a separate collection from counterparties (FLOW-010 wants one MasterOrganization). The register serves both; unification and de-duplication across counterparties, companies and subcontractors → CP-02 / FG-166. The subcontractor ЕИК is not checked for duplicates. |
| **CP-01-D10** | ЕГН: `/clients/search/unified` still accepts a full ЕГН as the query, so it works as an existence check. The Master Data reports (`md_person` identifiers, `uniqueness.mask_value`) use the old `12****90` mask. An invoice to a person now gets a masked ЕГН from import-client-invoice / invoice-context; issuing one with the full ЕГН needs the reveal (no UI yet). |
| **CP-01-D11** | Frontend: there is no UI yet for the bank-account register, verification and approvals, archive/reactivate, ЕИК-change approval or ЕГН reveal. The old delete buttons on Counterparties and Clients now deactivate with a prompt for the reason, and every changed call sends an `Idempotency-Key`. A UX design is needed from Krum. |
| **CP-01-D12** | After the merge of #69, `POST /subcontractor-payments` has SEC-01's money-write permission and Idempotency-Key; the CP-01 guard runs before the key is reserved. `POST /finance/other-expense` (documentless, no counterparty) is still not guarded. |
| **CP-01-D13** | `PUT /projects/{id}` with an owner change now enforces R22 and selectability, but it has no key and no AuditEvent of its own; the client-link route has both. |
| **CP-01-D14** | The rewritten routes write only the canonical AuditEvent, not the legacy `audit_logs` rows (`counterparty_created`, `client_created`, `created person/company`). A reader of `audit_logs` for these events would no longer see them (W0-04 parallel-record debt). |
| **CP-01-D15** | A real standalone mongod (no replica set) now refuses these master-data writes with 503 (auth_tx has no fallback). Production Atlas is a replica set. |
| **CP-01-D16** | ЕИК uniqueness uses claim rows, not a unique DB index, because legacy data may already hold duplicates. An index, after a duplicate report, is a follow-up. |
| **CP-01-D17** | The R48.2 notification is the existing in-app `notifications` collection. There is no e-mail or push. |
| **CP-01-D18** | A typed (human) proposal from a field user: the existing `master_data.pending.propose` refuses a human channel by design (W0-03). Allowing one is a model decision for W0-03 / Krum. |

## 8. Addendum A (08.11.2026): R50 + Q005, and the merge of #69

Package: Addendum A in `CP-01_COUNTERPARTY_IBAN_EGN_NO_DELETE.md` (branch `claude/happy-meitner-bmcnel` @ d8dc6c2).

| Point | Code | Tests (`test_cp_01_counterparty_iban_egn.py`) |
|---|---|---|
| D1 production = enforce | `counterparty_rules.bank_guard_mode` (`ENV` via `build_info.environment_label`) | `test_a1_production_is_always_enforce` (8 cases), `test_a1_production_refuses_a_legacy_payment_even_with_shadow_set` |
| D2 propose path | `master_records.require_writer`: 403 + `propose` | `test_a2_other_roles_are_pointed_to_the_pending_proposal` |
| D5 IBAN view | `bank_accounts.full_iban_allowed`; `mask_iban` → `****1234` | `test_iban_is_masked_for_roles_that_do_not_verify` (Admin masked, then full with `sensitive.iban.read`) |
| D6 cash | `bank_account_guard._check_cash` on manual, quick-pay and subcontractor payments | `test_a6_cash_to_a_counterparty_needs_a_receipt`; `test_red_payment_to_an_unverified_account_is_refused` (cash blocked) |
| D7 three people | `approve_bank_account_change` | `test_a7_entrant_verifier_approvers_are_three_people`, `test_iban_change_needs_verification_and_double_approval` |
| D8 unarchive | `master_records._reverify_bank_accounts` | `test_a8_unarchive_sends_the_iban_back_to_verification` |

**The merge of origin/main `4bca18a` (#69, SEC-01)** is a merge commit, not a rebase. Both sides of every conflict were kept:
- `PATCH /projects/{id}/client-link` keeps SEC-01's `require_money_write` and adds CP-01's key, R22, CAS and AuditEvent.
- `PUT /projects/{id}` runs SEC-01's `check_money_write` and then CP-01's R22 check and selectability.
- `POST /subcontractor-payments` keeps SEC-01's `MoneyWrite`, cap reservation and ledger-first order. The CP-01 guard runs before `MoneyWrite.begin`, so a refusal reserves no key.
- `ProjectOperationsPage`: SEC-01's money keys stay, and the other writes send a key too.

The A1 and A2B inventories and PM-01 were regenerated with their own tools. One existing fixture changed because R50.1 changed the rule: SEC-01-C02 `body_for("subpay")` now sends a cash receipt and a recipient name. The SEC-01 tests that use it are unchanged.

Gates for this head: `gates_addendum_a.txt`.

**Gates for this head**, against main `4bca18a`:

| Gate | main `4bca18a` | this head |
|---|---|---|
| R0 | 814 | 814 |
| W0 | 15 failed | 9 failed, all among main's 15 |
| PAY-01 | 630 | 630 |
| SEC-01 | 30 | 30 |
| PM-01 (real, `-rs`) | — | 6 passed, 0 skipped |
| CP-01 | — | 439 passed, 3 skipped (mongomock copies of the concurrency test) |
| A1 / A2C guards | 0 / 0 | 0 / 0 |
| full DB-free suite | 166 failed, 993 errors | 160 failed, 993 errors; the branch's failing set is a strict subset of main's |
| frontend | — | 173 passed |

The Addendum A tests fail on the previous head `ea51030`: 23 red (`addendum_a_red_on_ea51030_real_mongo.txt`).

**PM-01 against `4bca18a`:** 264 changed cells, all toward refusal; 528 cells on the 22 new routes; **0 cells that newly write** (`pm01_matrix_diff_vs_main.md`).

**SEC-01 evidence** (`SEC-01/results.json`, `SEC-01-C01/results.json`) was regenerated by its harnesses. The only difference is `op.audit_events` added to the client-link writes: that is CP-01's canonical AuditEvent. No status changed.

Two tests changed because the rules changed:
- `test_sec_01_money_write_permissions.KEY_REQUIRED` now also lists client-link. PM-01 shows 428 there because the harness sends no key.
- `test_w0_03e_a1_collision_matrix.set_mode` sets `ENV=test` and the IBAN guard to `off`. This tenant-isolation fixture has no verified accounts, and the IBAN rule itself is proved in the CP-01 tests.

## 9. FLOW Guard pass 23 / audit of `ea51030`

Every item below has its own test in `test_cp_01_counterparty_iban_egn.py`. Each test runs in off / shadow / enforce, on mongomock and on real Mongo. On the previous head `fe13c43` they are **40 red** on real Mongo (`fg_pass23_red_on_fe13c43_real_mongo.txt`).

| Finding | Fix | Test |
|---|---|---|
| **FG-225 (a)**: allocate had no guard | `bank_account_guard.check_allocation`, called for each invoice before any allocation is written. A payment to another counterparty → 409 `PAYEE_MISMATCH`. A bank payment to an account that is not this counterparty's verified one → 409. An invoice IBAN that differs from that account → critical DQ row + 409. A legacy payment with no account recorded → by mode. Cash without a receipt → 422. | `test_fg225a_allocate_checks_the_payee_and_its_account` |
| **FG-225 (b)**: the method comes from the account | `check_payment_target(account=…)`: a Cash account means cash; any other account means a bank transfer, whatever `method` / `payment_method` says. Manual payment and quick-pay use `_peek_payment_account`, which reads the account the payment will use without creating anything; the subcontractor payment uses its resolved account. | `test_fg225b_the_account_decides_the_method` |
| **FG-225 (c)**: other-expense had no guard | Guarded. It takes an optional `counterparty_id`, `bank_account_id` and cash receipt. Bank with no payee → legacy rule (enforce → 409). | `test_fg225c_other_expense_by_bank_is_guarded` |
| **CP83-01 / FG-228**: the entrant could approve | The entrant ≠ any approver, and approver 2 ≠ approver 1 → 409 `SAME_PERSON_APPROVAL` (already in `fe13c43`). | `test_a7_entrant_verifier_approvers_are_three_people` (probe K1 = the entrant approves → 409) |
| **FG-226**: full ЕГН in invoice-details, `/projects`, `/projects/{id}` | `_mask_invoice_details`: a person owner's `eik`, any 10-digit value, and `egn` / `tax_id` are masked on create/update of a project (**never stored in full**) and in every project reader. The migration masks existing copies (`--apply`); the original stays in `persons`. | `test_red_no_reader_returns_the_full_egn` (6 roles × 10 readers), `test_fg226_a_stored_project_never_holds_a_full_egn`, migration test |
| **FG-227**: mask format and search | One mask, `******1234`, now also in the Master Data reports (`uniqueness.mask_value`; W0-03C assertion updated). `/clients/search/unified` matches on ЕГН only for Owner / Accountant. | `test_fg227_search_by_full_egn_only_for_owner_and_accountant`, `test_fg227_master_data_report_uses_the_one_egn_mask` |
| **FG-229**: subcontractor ЕИК duplicates | `master_records.eik_holder` / `claim_eik`: one ЕИК check across counterparties **and** subcontractors, in both directions, with the shared claim row → 409 `EIK_ALREADY_EXISTS` + DQ. Subcontractor create is office-only, with a key and AuditEvent. | `test_fg229_subcontractor_eik_is_one_per_organisation` |
| **FG-230**: one DQ schema | `dq_issues` rows now use #81's schema: `id, org_id, type, title, entity_type, entity_id, status (open/resolved), owner_role ("accountant"), opened_at, updated_at`, plus the CP-01 fields `code, severity, message, data, occurrences`. **After #81 merges:** a single shared writer (#81's `sync_invoice_issue` and CP-01's `dq_issue`) and the resolve path → CP-01-D21. | `test_fg230_dq_rows_have_the_one_schema_of_81` |
| **FG-175 (FLOW-010 §8.4)**: our own IBAN on outgoing invoices | **Debt CP-01-D20.** Main has no field that carries our own IBAN on an outgoing invoice: not the invoice model, invoice settings, organization profile or PDF. The project's `invoice_details.iban` is the *client's* IBAN. There is nothing to check yet. When one is added, it must be chosen from `verified_bank_accounts` (party_type `own`), and sending must be blocked with a critical DQ row on a mismatch. | — |

**Every outflow path** (FG-225: "list EVERY path"):

| Path | Payee | Guard |
|---|---|---|
| `POST /finance/payments` (manual / advance) | `counterparty_id` | yes |
| `POST /finance/invoices/{id}/payments` (quick-pay) | invoice → counterparty | yes |
| `POST /finance/payments/{id}/allocate` | invoice → counterparty | yes (new) |
| `POST /finance/other-expense` | optional `counterparty_id` | yes (new) |
| `POST /subcontractor-payments` | subcontractor | yes; method from the account (fixed) |
| `POST /finance/transfers`, `/finance/account-funding` | own accounts only | not a counterparty payment |
| pay runs (`pay_runs._write_salary_outflows`), HR advances / loans / repayments | employees (FLOW-028) | not a counterparty; HR guest loans → debt CP-01-D22 |

**New debts:**
- **CP-01-D19:** `invoices.counterparty_eik` of a *person* buyer is a full ЕГН typed into an ЕИК field. Masking it in the invoice JSON would break invoice editing (the masked value fails validation on PUT), so it needs a separate buyer-ЕГН field with a reveal step.
- **CP-01-D20:** FG-175 / §8.4, our own IBAN (above).
- **CP-01-D21:** after #81 merges, one shared DQ writer and resolve path.
- **CP-01-D22:** an HR loan to a guest (`guest_name`) is an outflow to a person who is outside the counterparty register.

## 10. Early audit of `7e0b914`: CP83-02, CP83-03

| Finding | Fix | Test |
|---|---|---|
| **CP83-02 (blocking)**: the outflow guard had also landed in `create_other_income`. The other-expense edit was a `str.replace`, and other-income contains the identical block. | Removed from other-income: income is not a payment to a payee. I checked every other CP-01 insertion for such duplicates; there are none, apart from the intentional `counterparty_iban` on both InvoiceCreate and InvoiceUpdate. | `test_cp83_02_other_income_is_never_blocked`: income to a Bank or Cash account, with and without a counterparty (one of them with a pending IBAN), in off, shadow and enforce → 201. The auditor's probe file `docs/audit/probes/cp01/test_probe_cp01.py` (K1–K3, 84 cases) passes. |
| **CP83-03**: the migration masked `invoice_details` with no AuditEvent and could destroy data | A copy is masked **only** when it belongs to a person owner or is the `egn` field (never a 10-digit company tax id), **and** the canonical `persons` record holds the same full ЕГН. Each masked project gets one AuditEvent `project.invoice_details.egn_copy_masked` (masked values only). Every other copy is kept as it is, readers mask it, and a DQ issue „ЕГН копие без каноничен запис“ (owner_role accountant) is opened. `--apply` refuses to run without the `--plan-token` from the dry run. The project create/update path uses the same rule (`_store_invoice_details`). | `test_migration_dry_run_then_apply_is_pending_and_idempotent`, `test_fg226_a_stored_project_never_holds_a_full_egn` |

On `7e0b914` these tests are **7 red** on real Mongo (`cp83_red_on_7e0b914_real_mongo.txt`). Gates for this head: `gates_cp83.txt`.

## 11. CP83-04 and the merge of main `0750d75` (#71, SEC-02)

**CP83-04 (blocking): the #55 fixture was stale**
- On real Mongo, `test_warehouse_canonical_c26l_n_invoice_status` was 33 red: `edit_racing_send_and_pay` ×30 and `paused_edit_after_payment_is_409` ×3.
- **Cause:** the fixture's received invoice names no supplier. Its bank quick-pay is therefore a legacy payment with no verified account, and in production mode (no `ENV`, so `enforce`) it is correctly refused with 409.
- **Fix:** the guard stays on. The fixture now creates a supplier counterparty and links the invoice to it (`supplier_counterparty_id`). The supplier's IBAN goes through the real register: the Accountant enters it (`register_counterparty_bank_account`), and the Owner, a different person, verifies it from two independent sources with the counterparty's confirmation (`verify_bank_account`).
- **Result:** the file is 72 passed (33 red with the old fixture on the same code). The **whole warehouse suite on real Mongo is 1121 passed**.

**Merge of main `0750d75`**
- Merged with a merge commit (`616a66c`).
- One conflict, the imports in `subcontractors.py`; both sides were kept (CP-01 guard + SEC-02 finance read).
- PM-01 and the SEC-01 / SEC-01-C01 evidence were regenerated by their harnesses. Against main, the SEC-01 evidence differs only by CP-01's added `op.audit_events`.
- The inventories were regenerated and did not change.

**Gates** (against main `0750d75`):

| Gate | Result |
|---|---|
| CP-01 | 488 passed |
| PAY-01 | 630 passed |
| SEC-01 | 30 passed |
| SEC-02 | 31 passed |
| R0 | 814 passed |
| W0 | 10 failed, all among main `0750d75`'s 16 |
| PM-01 | 6 passed, 0 skipped |
| Full DB-free suite | no line only on the branch |

Details in `gates_cp83_04.txt`.

## 12. FLOW Guard pass 24 (on `7e0b914`)

On `e36af6e` these tests are 24 red, 6 passed on real Mongo (`fg_pass24_red_on_e36af6e_real_mongo.txt`). The 6 that pass are the Owner/Accountant "full view" cases.

| Finding | Fix | Test |
|---|---|---|
| **FG-241** | = CP83-02, already fixed in `6449dac` (other-income is never guarded) | `test_cp83_02_other_income_is_never_blocked` |
| **FG-242**: cash to a payee given only by `counterparty_name` / ЕИК passed | `bank_account_guard.resolve_payee`: if no `counterparty_id` is given, the ЕИК, or else an exact (case-insensitive) name matching **one** counterparty, resolves the payee. Every cash outflow **to a payee** (named or resolved) needs a receipt `file_id` + recipient. While the resolved counterparty has an unverified IBAN → 409 `PAYEE_BLOCKED_PENDING_IBAN`. Wired into manual payments, other-expense, quick-pay (invoice name / ЕИК) and allocate. Cash with no payee at all (a withdrawal) is not checked. | `test_fg242_cash_to_a_payee_named_only_by_name_or_eik` |
| **FG-243**: a pending change verified before the archive survived the unarchive | On unarchive (R50.3), **every** live account (verified **and** pending) goes back to „за проверка“ with its verification, approvals and `replaces_account_id` cleared, plus one AuditEvent per account. The pre-archive second approval → 409. | `test_fg243_unarchive_resets_a_pending_change_too` |
| **FG-244**: subcontractors had no lifecycle routes | `POST /subcontractors/{id}/deactivate`, `/reactivate`, `/archive`, with the same rules as counterparties (R48.4, R50.3). The subcontractor list hides archived records (`include_archived`). An inactive or archived subcontractor is not chosen for a new package or payment (422). | `test_fg244_subcontractor_deactivate_archive_reactivate` |
| **FG-245**: full IBAN in legacy fields | `counterparty_rules.mask_iban_fields` + `full_iban_allowed` (Owner / Accountant, Admin only with `sensitive.iban.read`). Applied to: counterparties list / detail / write responses (`iban`), subcontractors list / detail (`bank_iban`), projects list / detail / invoice-details (`invoice_details.iban`), finance invoices list / detail / write responses / quick-pay (`counterparty_iban`), and the turnover drill report. A project form that sends back the masked value never overwrites the stored one (`keep_stored_if_masked`). | `test_fg245_legacy_iban_fields_masked_by_role` (6 roles × 10 readers), `test_fg245_a_masked_form_value_never_overwrites_the_stored_iban` |

**Whichever merges second (#81 or #83):** both PRs add `"dq_issues"` to `ownership.py` (#81 under its own family; #83 under FAMILY_AUDIT). The second one to merge must keep **one** registration; otherwise the A2B classification test sees a duplicate. The row schema is already the same (§9, FG-230).

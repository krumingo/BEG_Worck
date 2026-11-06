# CLAUDE AUDIT — log

> Internal second check by the Claude audit session. **Not Codex**, not an approval.
> Never merges, deploys or pushes to other branches. PROVED = reproduced here by command; SUSPICION = reasoning only.

## Last audited SHA per PR

| PR / branch | Last audited SHA | Result | Date |
|---|---|---|---|
| #56 AUTH-01 | `dae097bb46691a8d7cf5b55c6526b32ba597b03d` | PASS (minor notes) | 2026-11-06 |
| #55 Склад 5C (C24) | `dbda909` | PASS (internal) + decision D-55-PRORATA — Codex still required | 2026-11-06 |
| #67 ST-02 | `e987892` | PASS (ST02-1 fixed) | 2026-11-06 |
| #68 PM-01 | `4e20084` | PASS (report accurate; main-level permission debt surfaced) | 2026-11-06 |
| #69 SEC-01 | `aee3169` | PASS (S1/S2 closed); MEDIUM SEC-R1 (ended membership still writes) | 2026-11-06 |
| #65 RC-01 | `93965b0` | PASS (P1 fixed) | 2026-11-06 |
| #66 ST-01 | `ef69601` | PASS (PST-1 fixed) | 2026-11-06 |

## Environment

- Python 3.13 venv, `backend/requirements.txt` + `requirements-dev.txt`.
- Real Mongo: `docker run -d --rm --name auditmongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all`, `rs.initiate`, `myState=1`.
- Each PR head checked out in its own detached worktree.

---

## 2026-11-06 — PR #56 @ `dae097b` (task R0-04 + CODEX RC-AUTH-01/02/03)

Base `origin/main` @ `c0e34e1` (merged in by `8e435a0`). Focus: the RC delta `8e435a0..dae097b` (only `backend/app/services/password_reset.py` + tests); full backend diff vs main skimmed for §14/§16.

### Commands and counts (PROVED)

```
cd backend; W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27019/?directConnection=true \
PYTHONPATH=. python -m pytest --noconftest -q -p no:cacheprovider \
  tests/test_auth_01_password_recovery.py tests/test_auth_01_c01_corrections.py \
  tests/test_auth_01_r0_04_merge.py tests/test_auth_01_rc_corrections.py tests/test_r0_0*.py
→ 908 passed, 0 failed, 0 skipped (349.8 s)

PYTHONPATH=. python -m pytest --noconftest -q -p no:cacheprovider tests/test_w0_*.py   # no Mongo URL
→ 15 failed / 1085 passed / 50 skipped — the same 15 test_w0_03e_legacy_routes failures as baseline

PYTHONPATH=. python scripts/w0_03e_a2c_tenant_boundary_guard.py → 210 modules, 0 violations
```

### Review of the RC delta

- RC-AUTH-01: `settle_delivery` marks the token `sent` only if `used_at=None AND delivery_status=pending`; otherwise it logs `password_reset_link_sent_but_already_resolved` and supersedes nothing. A token that was already revoked is never reactivated. OK.
- RC-AUTH-03: older tokens are superseded with the key `(requested_at, id)`. Query values are BSON-encoded and so truncated to ms, the same as the stored field. Equality inside one ms is therefore consistent. Both completion orders leave exactly one usable link. OK.
- RC-AUTH-02: `_dev_url_logging_enabled` now fails closed on a missing, unknown, production or contradictory `ENV`/`ENVIRONMENT`. OK.
- F-06 is kept: a failed delivery revokes only the new token.
- The audit write is in the same transaction. No token, hash or password is in the audit row. No hard delete. Tenant access goes through `TenantData`.

### Notes (non-blocking, SUSPICION)

- N-56-1 (low): inside one ms the tiebreak uses the random `uuid4` id. If two requests land in the same ms, the link that survives may be the **earlier** e-mail, not the latest one. Exactly one link stays usable, so security holds. UX only.
- N-56-2 (low): rows written before `requested_at` existed would never be superseded by the `$lt` branch. Every token minted since `8892738` has `requested_at`, so this only matters for hand-made data.

**Verdict: PASS** (internal). Codex re-review is still the gate.

---

## 2026-11-06 — PR #55 @ `2bb81fc` (LIVE-OPS-01 / TASK 5C, C16+C17)

Base `79af297` (PR base, **10 commits behind main**; GitHub `mergeable_state=dirty`). There is no task package in `docs/architecture/tasks/`. Audited against the PR body and the C17 commit message.

### Commands and counts (PROVED)

```
# warehouse suites, real Mongo, as the C17 commit prescribes
cd backend; PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 \
MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true&replicaSet=rs0' DB_NAME=audit_wh \
PYTHONPATH=. python -m pytest --noconftest -q -p no:cacheprovider tests/test_warehouse_canonical_*.py
→ 1 failed, 140 passed, 0 skipped
   FAILED test_warehouse_canonical_c13_mongo.py::test_c13_4_material_entries_rebuild_twice_byte_parity
   (without PERMISSION_SERVICE_MODE=enforce: 4 failed / 137 passed)

# W0 DB-free
PYTHONPATH=. python -m pytest --noconftest -q -p no:cacheprovider tests/test_w0_*.py
→ PR head: 27 failed / 1073 passed / 50 skipped
→ base 79af297 (same command): 15 failed / 1085 passed / 50 skipped
   12 NEW failures: a1_static_guard ×3, a2_static_guard ×2, a2b_static_guard ×4,
   a2c_static_guard ×1, a2b_backfill ×1, legacy_routes::test_warehouse_reset_in_enforce_keeps_used_warehouses

# guards
scripts/w0_03e_a2c_tenant_boundary_guard.py → head: 212 modules, 19 violations   | base: 0
scripts/w0_03e_a1_tenant_access_guard.py   → head: 433 units, 9 violations      | base: 0
```

### Findings

**F-55-1 — BLOCKING, PROVED. C17 does not fix C13.4; the test is still red on real Mongo.**
The implementer did not run C17 on real Mongo (the commit message says so).
- Reproduction: run the first command above with `-k c13_4`. It fails at `tests/test_warehouse_canonical_c13_mongo.py:532` with `canonical material_entries projection empty after rebuild … assert 0 >= 1`.
- Cause: the new assertion `len(first_snapshot) >= 1` expects ACCEPT_PROJECT_DELIVERY to emit a `material_entries` row. `projections.py:116-118` emits `material_entries` only for `CONSUME_TO_SMR` (`_project_consumption`). That matches CLAUDE.md §7: cost is recognised once, at consumption or write-off.
- So the expectation in the test is wrong. Without that assertion the parity check is a vacuous `[] == []`.
- Fix belongs in the test: add a CONSUME_TO_SMR step before the rebuild. Do **not** change the projector.

**F-55-2 — BLOCKING, PROVED. Tenant-boundary guards regress from 0 to 19 (A2C) and 9 (A1) violations.**
All of them are in the new `app/services/warehouse_movements/`:
- `projections.py:202,251,283,317,327,369,404`;
- `service.py:319,342,358,366,384,434,479,1274,1275`;
- `migration_readiness.py:89` (`db.warehouses.find` outside TenantData).

Several may be safe in practice. For example, the idempotency `record_id` is derived from `tenant_id` (SUSPICION, not proved per site). The guard is still the gate, and CLAUDE.md §3/§16 forbid bypassing the Tenant Guard. The PR neither routes these through `TenantData` nor regenerates the inventories. That is why `test_the_committed_inventory_is_the_generated_one` and `test_the_committed_inventory_matches_the_code` fail.

**F-55-3 — HIGH, PROVED. `audit_chain_head` is not registered in the A2B ownership registry.**
`test_w0_03e_a2b_backfill.py::test_execute_backfills_every_ownerless_row_and_touches_nothing_else` fails with `KeyError: 'audit_chain_head'`.
- The new tenant-owned collection is written by `service.py:479`, but the backfill/ownership tables do not know it.

**F-55-4 — MEDIUM, PROVED (behaviour change without test/decision). Dev warehouse reset now refuses with 409 `CANONICAL_LEDGER_PRESENT`.**
- The existing test `test_warehouse_reset_in_enforce_keeps_used_warehouses` expects 200 and now gets 409.
- The new behaviour may be intended (no reset over append-only ledger history, which fits §2.9). Either way, the existing test must be updated deliberately, with the decision referenced. Leaving it red is not acceptable.

**F-55-5 — PROCESS. The branch is 10 commits behind main, and GitHub reports conflicts (`dirty`).**
- Every result above is on the old base. After the merge with main (R0-01…R0-07, R0-03 identity), the guards and suites must be re-run.

**Verdict: FINDINGS (blocking: F-55-1, F-55-2).**

---

## 2026-11-06 12:55 — Process change (R9, relayed by the orchestrator)

This session is now the **primary reviewer** for every task except money/security; those also go to Codex. For each audited head, the suites are still run, and in addition I write adversarial probes in `docs/audit/probes/`: cross-tenant ids, role escalation, retries/duplicates, odd input, concurrency. Only proven failures become findings. Open heads are also checked for conflicts with each other.

Queue: RC-01 (`claude/rc-01-build-identity`), ST-01 (`claude/st-01-staging-fixtures`), 5C-C18 (#55). **None of them has a new head yet** (12:55 UTC).

### Integration check — `git merge-tree --write-tree` (PROVED)

Heads: main `c0e34e1`, #53 `e2a07ee`, #54 `48306ba`, #55 `2bb81fc`, #56 `dae097b`, #64 `3e0db8e`.

| Pair | Conflicting files |
|---|---|
| main × #55 | `backend/app/routes/warehouses.py` |
| #53 × #54 | `frontend/src/components/DashboardLayout.js` |
| #53 × #55 | `frontend/src/App.js` |
| #54 × #55 | `backend/app/permissions/catalog.py`, `backend/app/routes/procurement.py`, `backend/app/tenancy/data_access.py` |
| #54 × #56 | `backend/app/audit/store.py`, `backend/app/tenancy/data_access.py` |
| #54 × #64 | `frontend/src/components/DashboardLayout.js` |
| #55 × #56 | `backend/app/routes/warehouses.py`, `backend/app/tenancy/data_access.py` |
| #55 × #64 | `backend/app/routes/warehouses.py`, `frontend/src/App.js` |

Clean pairs: main×#53, main×#54, main×#56, main×#64, #53×#56, #53×#64, #56×#64.

**Hotspot:** `backend/app/tenancy/data_access.py` is touched by #54, #55 and #56. Whichever merges second must re-resolve it and re-run A2C/A1. Recommendation: merge #56 first, then rebase the work for #55 (C18) and #54 onto it.


---

## 2026-11-06 ~13:50 — #55 @ `639ca80` (5C-C18), #65 RC-01 @ `44c9c3c`, #66 ST-01 @ `9904524`

Note: dockerd died during the first R0 run of RC-01. That run was discarded; Mongo was restarted (`rs.status().myState=1`) and every real-Mongo number below is from a re-run.

### PR #55 @ `639ca80` — 5C-C18 (merge of main `58cc3a9` + corrections)

**Suites (PROVED):**

| Command | Result |
|---|---|
| `PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 MONGO_URL=…replicaSet=rs0 pytest --noconftest tests/test_warehouse_canonical_*.py` | **151 passed / 0 failed / 0 skipped** |
| W0 DB-free | 1085 / 15 / 50, same 15 as main ✔ |
| A2C | 217 modules, 0 violations ✔ |
| A1 | 440 units, 0 violations ✔ |
| R0 on real Mongo | see the addendum below |

F-55-1…F-55-4 from the previous audit are fixed. C13.4 now runs consume 3 of 5 and pins one row: 30. No skip, xfail or mock.

**Adversarial probes:** `docs/audit/probes/pr55/test_probe_pr55_material_cost.py`, real Mongo, through the real `CommandService`. Result: **2 failed / 1 passed**.

**P55-1 — BLOCKING (money), PROVED. Project material cost is counted twice: 80 instead of 30.**
- Flow: receive 5 @10 → dispatch 5 → accept 5 → consume 3, then `POST /material-entries/sync/{project}`.
- Result: canonical `material_entries` with kinds `['accept', 'consume']`, total **80.0**. Expected: 30 = 3×10.
- Cause:
  - `app/routes/material_smr.py` `sync_material_entries` maps `accept_project_delivery → ("accept", +1)` and `consume_to_smr → ("consume", +1)`;
  - the readers `get_material_summary_for_project`, the by-package report and the breakdown all sum `movement_kind ∈ {accept, …, consume}`.
- This contradicts CLAUDE.md §7 (material cost is recognised once) and C18's own decision for C13.4 ("cost only at consumption").
- Before C18 the projector rows lacked `org_id` and were invisible to these readers. The sync rows always had `org_id`, so the defect predates C18 (it comes from C11–C13), but C18 does not close it.
- Reproduction: copy the probe into `backend/tests/` and run the command from its docstring.

**P55-2 — BLOCKING, PROVED. Seven `await [row async for …]` sites in `app/routes/material_smr.py` (lines 287, 292, 356, 405, 408, 458, 521) raise `TypeError: object list can't be used in 'await' expression`.**
- They were introduced by PR #55; main has 0 such sites (`git grep 'await \[row async'`).
- Affected:
  - `get_material_summary_for_project`;
  - `GET /execution-packages/{pkg_id}/financial`;
  - `/execution-packages/financial-breakdown/{project_id}`;
  - `/material-warnings/{project_id}`;
  - the profit integrations `full_cost.py:331` and `revenue_expense.py:480`.
- Every one of them returns 500. The probe `test_p55_2` proves it for the summary function. The other sites are the same pattern (SUSPICION per route, not run).

**P55-3 — PASS.** A `sync_material_entries` call as tenant T2 for the same project id writes nothing and sees nothing from T.

### PR #65 @ `44c9c3c` — RC-01 build identity

**Suites (PROVED):**

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_rc_01_build_identity.py tests/test_r0_0*.py` | **845 passed / 0 failed / 0 skipped** on real Mongo. The implementer had 391 skipped; this covers that gap. |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 204 modules, 0 violations ✔ |
| A1 | 414 units, 0 violations ✔ |
| `pytest ops/release/tests` | 78 passed, 1 skipped, 52 subtests passed |
| `yarn test BuildIdentity.test.js` | 6 / 6 ✔ |

**Probes:** `docs/audit/probes/rc01/`.

**P1 — MEDIUM, PROVED. `write_build_info.py --commit X` stamps a tree that does not contain X.**
- Script: `probe_rc01_write_build_info.sh`. In a repo checked out at commit A, `--commit B` exits 0 and writes `build_sha=B` into `backend/` and `frontend/BUILD_INFO.json`.
- The dirty check (`write_build_info.py` `from_git`) only runs when `HEAD == commit`. Otherwise nothing ties the stamped tree to the commit, so `/api/version` and the UI would show a SHA the build is not.
- Task §1 says the identity is "taken at build from immutable Git objects".
- Fix: refuse when `rev-parse HEAD != commit` (or when `--target` is not an export of that commit). Alternatively, require `--from-bundle` for anything other than a dev stamp.
- P1b PASS: a dirty tree with `--commit main` (resolves to HEAD) is refused, exit 2.

**P2–P5 — PASS.** `probe_rc01_api.py` runs on the real `server.app`, with all middleware.
- `/api/version` without auth → 200.
- A BUILD_INFO.json with extra `secret`/`path` keys still gives exactly the allowlisted keys.
- `ENV` values `" production"`, `"Production"`, `"production\n"`, `"prod"`, `"PRODUCTION"`, `""` → `unknown`.
- `BUILD_SHA` values that are uppercase, 39 or 41 chars, padded or non-hex → `unknown`.

**Note (low, SUSPICION):** `build_time` is the commit time, not the build time. That is acceptable for identity, but the name may mislead.

**Verdict:** FINDINGS, non-blocking. P1 should be fixed before the Synology deploy wiring.

### PR #66 @ `9904524` — ST-01 staging fixtures

**Suites (PROVED):**

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_st_01_*.py` | 29 passed on real Mongo |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 203 modules, 0 violations ✔ |
| A1 | 412 units, 0 violations ✔ |

Scope: only `ops/staging/` and the test file, no business code ✔. Passwords come from env or prompt and are never written ✔.

**Probes:** `docs/audit/probes/st01/probe_st01.py`.

**PST-1 — MEDIUM, PROVED. The runner against a dead backend (`--base-url http://127.0.0.1:9`) exits 0.**
- Summary: pass 0 / fail 0 / blocked 40 steps.
- Exit 0 is documented as "nothing failed". A gate or the Bot that reads the exit code would accept a run with no evidence.
- Fix: exit non-zero (for example 3) when any step is `UNREACHABLE`, or when pass == 0.

**PST-2 — PASS.** The runner refuses URL tricks (`127.0.0.1.evil.com`, `localhost@evil.com`, `#@127.0.0.1`, `[::1].evil.com`, `file://`).

**PST-3 / PST-4 — PASS.** The seed refuses `begwork*` names and `$DB_NAME` even with `--allow-remote`, and refuses `mongodb+srv` without it.

**Verdict:** PASS (internal), with PST-1 recommended. The role mapping (`assumption: true`) is Krum's decision, as the HANDOFF says.

### Addendum — orchestrator request 13:28 (ST-01 targets / secrets / isolation; Bot defect classes)

**ST-01 @ `9904524` — extra checks:**

- **Targets: PROVED, see PST-2/3/4.** Seed refusals:
  - a non-local URL without `--allow-remote`, including `mongodb+srv`;
  - `begwork*` names and `$DB_NAME`/`$BEG_SYSTEM_DB`, even with `--allow-remote`;
  - `--confirm-db` not equal to `--db`;
  - any database holding non-synthetic users, organizations or registry rows.

  Residual risk, by design: with `--allow-remote` and a non-`begwork` name, the seed will write to a remote server. That is the documented staging path.
- **Secrets in Git (PROVED by grep of the PR diff):**
  - no real secret, connection string with credentials, or key;
  - the only literals are example URLs in tests (`user:pw@cluster0.example…`) and the synthetic test password `PASSWORD = "ST01-Synthetic-Pass-2026!"` in `backend/tests/test_st_01_staging_fixtures.py:37`, which is used only against mongomock or a throwaway real Mongo;
  - `ops/staging/` contains no password; the PR's own test asserts this.

  Low note: an operator could reuse that constant as the staging password. The README should say "do not reuse the test constant".
- **Isolation A/B:** `test_st_01_*` (`_end_to_end`) logs in as each owner over real ASGI HTTP and checks:
  - the foreign project id → 404, in both directions;
  - `/material-requests` lists only the caller's own `org_id`;
  - B-side attempts write 0 rows into B.

  The runner adds GET/PUT/submit/DELETE on A's request as B → 404, with A unchanged. Both pass on real Mongo (29/29). The seed puts both tenants in one operational DB, scoped by `org_id`. That matches how `TenantData` resolves today, so the isolation is tested in the same topology the backend uses.

**New checklist items** (from the Bot findings on #55 `639ca80`, which the unit suites missed). For every head that touches persistence:

1. **Startup/indexes:** is every required index created by an app startup or migration path, and not only by test fixtures? (`grep` the callers of `ensure_*indexes` outside `tests/`.)
2. **Pre-existing data:** run the first write on a tenant that already has W0-04 `audit_events`, counters and legacy rows. A new chain or counter must not collide with an existing `(tenant_id, sequence)`.
3. **Legacy unique indexes:** create the legacy indexes from main (for example `warehouse_batches(org_id, batch_number)`), then do two inbound writes. Rows with null fields must not collide.
4. **Driver API on wrappers:** call every `TenantCollection` method with the kwargs the service passes (for example `distinct(..., session=)`).
5. **Identical resend** of every command class (inbound and outbound) must return the original result, not 409.
6. **Error-as-empty UI:** an API 500 must not render as "no alarms" or "no data".

### Addendum — #55 @ `639ca80` R0 on real Mongo (PROVED)

`W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27019/?directConnection=true PYTHONPATH=. pytest --noconftest -q tests/test_r0_0*.py`
→ **814 passed / 0 failed / 0 skipped**. The merge with main keeps R0-01…R0-07 green. This does not change the #55 verdict: P55-1 and P55-2 still block.


---

## 2026-11-06 ~14:30 — PR #55 @ `d8ac3a9` (5C-C19: Bot F-1…F-6 + audit F-7/F-8)

### Suites (PROVED)

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix (`PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`) | **176 passed / 0 failed / 0 skipped** |
| R0 on real Mongo (`W0_03_REAL_MONGO_URL=…`) | **814 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 217 modules, 0 violations ✔ |
| A1 | 440 units, 0 violations ✔ |
| `yarn test` CanonicalWarehouseRoute + CanonicalWarehousePage (+c19) | 30 / 30 ✔ |

### Probes (`docs/audit/probes/pr55/test_probe_pr55_c19.py`, real Mongo, real CommandService)

| Probe | Result |
|---|---|
| C19-1: receive 5@10 → dispatch **in_transit** → accept 5 → consume 3 → return 2 to warehouse | **PASS**. Summary 30 before and after sync; exactly one `consume` row. P55-1 is closed. P55-2 is closed too: the summary no longer raises. |
| C19-2: W0-04 event → canonical → W0-04 → canonical → W0-04 | **PASS**. One chain, sequences 1..n, `verify_chain` OK (Bot F-1 closed). |
| C19-4: legacy unique `warehouse_batches(org_id, batch_number)`, 3 receives + dispatch + accept + rebuild ×2 | **PASS**. No null `batch_number` (Bot F-2 closed). |
| C19-5: identical resend of consume after an unrelated consume | **PASS**. Original `movement_id` returned, 2 ledger rows; same key with a different qty is refused (Bot F-5 closed). |
| C19-6: dispatch → project | **PASS**. Refused (Rule B, F-4); T2 cannot accept T's dispatch; T2 has 0 rows. |
| C19-7: `integrity_warnings` with and without a session | **PASS** (Bot F-3 closed). |

Further checks:
- **Startup:** `server.py` startup now calls `ensure_required_indexes_at_startup(db)` (F-1b). Failure is logged and the service stays fail-closed.
- **UI:** a failed alarms or stock read now renders an error with a code, never "no alarms" (F-3 UI, read in code).
- **Frontend catalog copy:** `warehouseCanonicalAccess.json` is a UI copy of the catalog. It is covered by a parity test against `catalog.py`, so it is not a second source of truth.

The earlier probes `test_probe_pr55_material_cost.py` P55-1/P55-3 now fail only because they dispatch straight to the project, which F-4 refuses by design. They are superseded by C19-1/C19-6 and kept for history.

### Debt on main (NOT a #55 finding), PROVED

**C19-3 / control:** concurrent W0-04 `app.audit.store.record_event` calls lose events with `DuplicateKeyError`.
- The writer reads the tail and inserts sequence+1 with no retry or transaction.
- 6 concurrent W0-04-only writers → 3–4 failures, over 3 of 3 runs. The same happens with canonical writers interleaved (canonical: 0 failures; it retries inside its transaction).
- This is on `main`, unchanged by #55.
- Impact: an AuditEvent can be lost under concurrent permission / master-data / auth writes. It is the caller's exception, so no silent loss in the store itself, but the business action may already be committed (CLAUDE.md §2.8).
- Per §18 this is recorded as debt and not fixed; for Krum to prioritise.

### Integration (merge-tree)

- #55 is now clean against main, #65 and #66.
- It still conflicts with:
  - #53 (`frontend/src/App.js`);
  - #54 (`catalog.py`, `procurement.py`, `data_access.py`);
  - #56 (`data_access.py`, `W0-03E-A2B_INVENTORY.md`);
  - #64 (`App.js`).

**Verdict:** PASS (internal). Money-related, so the Codex review is still required.


---

## 2026-11-06 14:20 — check-in: #65 → `93965b0` (RC-01-C01), #66 → `ef69601` (ST-01-C01); #55 and #56 unchanged

Both deltas touch only `ops/` scripts, their tests and READMEs, with no app or business code. So the full R0/W0 runs were not repeated; the 44c9c3c / 9904524 results still apply.

### #65 RC-01-C01 (PROVED)

- `PYTHONPATH=. pytest --noconftest tests/test_rc_01_build_identity.py` → 36 passed.
- `pytest ops/release/tests` → 78 passed, 1 skipped, 52 subtests.
- Probe P1 (`probe_rc01_write_build_info.sh`): **now PASS**. Tree at A with `--commit B` → exit 2, nothing written.
- New probe `probe_rc01_c01.sh`, bypass attempts, **all PASS**:
  - a plain copy (non-git) of tree A is refused;
  - a linked worktree at A is refused;
  - a non-toplevel subdirectory is refused;
  - `--allow-dirty` does not allow another commit;
  - positive: tree at B with `--commit B` → 0;
  - a refusal leaves no `BUILD_INFO.json` or `.tmp`.
- Remaining low note (pre-existing, SUSPICION): the dirty check uses `--untracked-files=no`, so an untracked file in the build context is not detected.

### #66 ST-01-C01 (PROVED)

- `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_st_01_*.py` → 31 passed on real Mongo.
- Probe PST-1: **now PASS**. A dead backend gives exit **3** (no_evidence), with `outcome.reasons` = BACKEND_UNREACHABLE and NOTHING_PASSED.
- PST-2/3/4 still pass.

### Integration

#65 and #66 still merge cleanly with main and with #55 (checked at 14:05 on the previous heads). The deltas touch only `ops/release/*` and `ops/staging/*`, so there is no new overlap.


---

## 2026-11-06 ~15:05 — PR #55 @ `c0b3b4c` (5C-C20: finance reads canonical, F-9…F-11)

Harness note: dockerd keeps dying between turns. `scratchpad/mongo_up.sh` now brings dockerd and the RS up idempotently inside the same command as each test run.

### Suites (PROVED)

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix (enforce) | **187 / 0 / 0** |
| R0 on real Mongo | **814 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 218 modules, 0 violations ✔ |
| A1 | 442 units, 0 violations ✔ |

### Probes (`docs/audit/probes/pr55/test_probe_pr55_c20_reports.py`, real Mongo, real CommandService, no manual sync or recompute)

Flow: receive 5@10 → dispatch in_transit → accept 5 → consume 3. Canonical cost = **30**.

| Report | C20-A canonical only | C20-B + legacy issue 100 |
|---|---|---|
| `material_smr.get_material_summary_for_project` (project-profit, full_cost) | **30** ✔ | 30 (legacy excluded) |
| `project_pnl.compute_project_pnl` (`/projects/{id}/pnl`, summary, breakdown) | **30** ✔ | 30 (legacy excluded) |
| `project_financial_results.compute_financial_results` → `cash.breakdown.paid_materials` | **0** ✘ | harness error (event loop), not counted |
| `centralized_reports.build_centralized_reports` → `total_materials` (and `total_expense`) | **0** ✘ | **100** ✘ |
| `revenue_snapshot.get_profit_by_period` → monthly `material` | **0** ✘ | **0** ✘ |

**C20-1 — BLOCKING (money), PROVED. Three finance reports still read only legacy rows. For a canonical-only project they show material cost 0, so profit is overstated. With a mixed history they disagree with the P&L (100 against 30).**

| Report | Source |
|---|---|
| `app/services/project_financial_results.py:78-86` | legacy `warehouse_transactions` with `type: "issue"` |
| `app/services/centralized_reports.py:318-326` | the same legacy issue rows |
| `app/routes/revenue_snapshot.py:134` | legacy `material_entries.movement_type ∈ {issue, return}`; canonical rows have no `movement_type` |

- This is the same defect class as F-9, and it breaks "one screen, one number".
- The C20 package lists pnl, package, profit, net-profit and ledger. These three were not listed, but they are project finance reports.
- Same legacy-only pattern, not run (SUSPICION):
  - `services/material_waste.py:69`;
  - `services/pulse_generator.py:62`;
  - `routes/materials_baseline.py:323`;
  - `routes/revenue_snapshot.py:318` (procurement-alerts, quantities);
  - `routes/procurement.py:534` (issue-number listing, not cost).

**C20-2 — DECISION NEEDED (money), PROVED as behaviour. Mixed history drops the legacy cost.**
- `canonical_material_cost.project_warehouse_material_cost`: once a project has any canonical cost row, all legacy issue cost is reported as `legacy_excluded_cost` and **not counted**.
- In C20-B the P&L shows 30. The real total is 100 issued before the cutover plus 30 consumed after it.
- This avoids double counting only if the legacy issues and the canonical consumes describe the same material.
- For a project already running when the canon starts, the pre-cutover cost disappears from P&L (underreport).
- Alternative: count legacy issue rows dated before the first canonical ledger row of the project, plus canonical after it, which is disjoint by time.
- It is documented in the module, but it is a business rule. Krum decides; record it in the canon.

### No manual sync (orchestrator question) — PROVED

Every figure in the C20-A table was produced with no `POST /material-entries/sync` and no `recompute-material` call. The two canonical-aware readers show 30 directly from the consume-transaction projection row.


---

## 2026-11-06 ~15:45 — PR #55 @ `df48d68` (merge of main `07da9ab` incl. #65/#66 + 5C-C21: Р10 фира, Р11 Rule B for W2W)

### Suites (PROVED)

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix (enforce) | **203 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo (now on the branch via main) | **881 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 219 modules, 0 violations ✔ |
| A1 | 444 units, 0 violations ✔ |
| `yarn test` CanonicalWarehousePage* + BuildIdentity | 26 / 26 ✔ |

### Probes (`docs/audit/probes/pr55/test_probe_pr55_c21.py`, real Mongo, real CommandService) — **5 / 5 PASS**

| Probe | Result |
|---|---|
| C21-1: receive 10@10 → project 10 → consume 3 → write-off 2 from the project | summary `(total, waste)` = **(50, 20)** after the projector, after sync, after rebuild ×2, and after re-sync + recompute; exactly **1** `write_off` cost row. Recognised once ✔ |
| C21-2: project write-off of 9 when 5 are there | refused, no ledger row ✔ |
| C21-3: W2W transfer 10 (layers 5@10 + 5@20), accept 6, then 5 | the 5 is refused (over-accept); accept 4 → wh_b holds 10; **0** `material_entries` (a transfer is not project cost) ✔ |
| C21-4: accept a W2W transfer into a project bucket | refused ✔ |
| C21-5: T2 accepts T's W2W transfer | refused; T2 has 0 rows ✔ |

Re-runs of earlier probes:
- C19: 6 / 8. The 2 failures are exactly `c19_3` and its control, the known **W0-04 `record_event` concurrency debt on main**. Not a #55 finding.
- C20 report probe: **unchanged**. `project_financial_results`, `centralized_reports` and `profit_by_period` still show 0, or 100 with a legacy row, against 30. C20-1 stays open. The orchestrator says 5C-C22 ("all finance reports from one source" + the R13 cutover split) addresses it and C20-2.

**Verdict:** C21 scope (Р10/Р11) PASS (internal). #55 as a whole is still FINDINGS until C22 closes C20-1. Money, so the Codex review is still required.


---

## 2026-11-06 ~16:45 — PR #55 @ `a427923` (5C-C22: one helper for every finance report, Р13 cutover) and new PR #67 ST-02 @ `55ef71d`

### #55 @ `a427923`

**Suites (PROVED):**

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix | **213 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 219 modules, 0 violations ✔ |
| A1 | 444 units, 0 violations ✔ |

**Probes** (`docs/audit/probes/pr55/test_probe_pr55_c22.py`, plus the C20 report probe, real Mongo, real CommandService). Each test runs in its own process, because a cached loop in `resource_model` breaks multi-test runs of `financial_results` (a harness artifact).

| Probe | material_smr | pnl | financial_results | centralized | profit_by_period |
|---|---|---|---|---|---|
| C22-1 canonical only | 30 | 30 | **30** | **30** | **30** |
| C22-2 legacy 100 dated before cutover + 30 | 130 | 130 | 130 | 130 | 130 |
| C22-3 legacy 100 dated after cutover + 30 | 30 | 30 | 30 | 30 | 30 |
| C22-4 cutover per tenant (T2 cut 30 days earlier; T's legacy row between the two cutovers) | 130 | 130 | 130 | 130 | 130 |
| C22-5 periods + undated equal the total | — | — | — | — | 130 ✔ |

- **C20-1 is CLOSED.** Every report agrees.
- **C20-2 is CLOSED by Р13**, a disjoint split by the tenant cutover. One tenant's cutover does not leak into another.
- An undated legacy row is counted in the total and shown as `material_undated` in profit-by-period, by design and documented.

C21 probes: 5/5. C19: 6/8; only the known main W0-04 concurrency pair fails.

Note (low, pre-existing): legacy `type: return` rows never carried a price (`origin/main:procurement.py:760-779`), so returned legacy material still counts as issued cost. The figures are unchanged from main and C22 documents this.

**Verdict:** PASS (internal). Money, so the Codex review is required.

### #67 ST-02 @ `55ef71d` (isolated staging stack + rollback rehearsal) — NEW

**Scope (PROVED):**
- `git diff origin/main...pr/67` touches only `ops/staging/*`, `backend/tests/test_st_02_staging_stack.py` and `docs/evidence/ST-02/`.
- `ops/release`, `ops/synology`, `backend/app` and `frontend` are untouched ✔.
- Secret scan of the diff: clean. The only hit is a `"synthetic"` JWT value in a test.

**Tests:**

| Command | Result |
|---|---|
| `pytest --noconftest tests/test_st_02_staging_stack.py` | 50 passed |
| `pytest ops/release/tests` | 78 passed, 1 skipped |
| A2C / A1 | 0 / 0 |

The live rehearsal (docker build/deploy) was not re-run by the audit; the evidence is in `docs/evidence/ST-02/rehearsal-2026-11-06/`. The PR itself says it proves the mechanics on sandbox base images, not production base images.

**Probe:** `docs/audit/probes/st02/probe_st02_isolation.py`. It starts from a passing compose model and applies one hostile mutation at a time.

| Mutation | Caught? |
|---|---|
| mongo publishes 0.0.0.0:27017 | ✔ |
| mongo on an external volume | ✔ |
| backend `network_mode: host` | ✔ |
| backend `MONGO_URL` → external `mongodb+srv` production cluster | ✘ |
| backend `MONGO_URL` → LAN IP of a production mongo | ✘ |
| backend `DB_NAME=begwork` | ✘ |
| backend bind-mount of `/volume1/docker/begwork` | ✘ |
| backend mounts `/var/run/docker.sock` | ✘ |
| backend `privileged: true` | ✘ |

**ST02-1 — MEDIUM, PROVED.** `ops/staging/isolation_check.py` ("ISOLATION PASS") does not check where the backend's database points, nor bind mounts or privileges.
- The `st02` bridge network still has outbound access, so a staging backend with a production `MONGO_URL` would write production data while the gate prints PASS.
- The default path is safe: `staging_up.py:169-170` writes `mongodb://mongo:27017/?replicaSet=rs0` and `DB_NAME=st02_staging`. The risk is a hand-edited or copied `.env`, for example the planned "Later: Synology" run next to the production `.env`.
- Fix (small):
  - assert backend `MONGO_URL` host == `mongo` (the service) and `DB_NAME` not in `production_databases()` / not `begwork*`;
  - reject backend/frontend bind mounts outside the staging root, the docker socket, and `privileged`.
- Recommended before any Synology staging use. Not blocking for the cloud-container scope of ST-02.

**Integration:**
- #67 is clean against main, #53, #54, #55, #56 and #64.
- #55 is clean against main. It still conflicts with #56 (`data_access.py`, A2B inventory), #53/#64 (`App.js`) and #54 (`catalog.py`, `procurement.py`, `data_access.py`).


---

## 2026-11-06 ~17:20 — #67 → `e987892` (ST-02-C01), new #68 PM-01 @ `4e20084`; #55 and #56 unchanged

### #67 ST-02-C01 (PROVED)

- `pytest --noconftest tests/test_st_02_staging_stack.py` → 110 passed.
- Probe `probe_st02_isolation.py`, extended to 18 hostile models, **all refused**. Two kinds of case:
  - the original 9 from ST02-1;
  - 9 new evasion attempts: `mongo.evil.com` prefix trick, a second host in the seed list, a userinfo trick, `BEGWORK` uppercase, `BEG_SYSTEM_DB=begwork_system`, frontend and mongo bind mounts of `/volume1/docker/begwork`, `cap_add SYS_ADMIN`, `pid: host`.
- The probe baseline now uses `DB_NAME=st02_staging` (what `staging_up.py` writes). `begwork_staging` is now correctly refused as `begwork*`.
- **ST02-1 is CLOSED.**

### #68 PM-01 — role × endpoint × PERMISSION_SERVICE_MODE matrix (tests and docs only)

**Scope (PROVED):** only `backend/tests/test_pm_01_permission_matrix.py`, `docs/architecture/PM-01_PERMISSION_MODE_REPORT.md` and `docs/evidence/PM-01/*`. No app code. No secrets: a synthetic password constant and a JWT secret that is random per run.

**Tests (PROVED):**

| Command | Result |
|---|---|
| DB-free | 5 passed, 1 skipped (the real-Mongo cell) |
| With `W0_03_REAL_MONGO_URL` | **6 passed, 0 skipped (232 s)**. A fresh 18,048-call run gives the same status and the same wrote/not-wrote for every cell as the committed `matrix.csv` |

**Independent check of the report against `matrix.csv` (PROVED, own script):**
- 18,048 rows.
- **0** cells where the status differs between off, shadow and enforce. This confirms the headline "the three modes give the same answer".
- 18 cells where "wrote" differs between modes, all on `POST /api/users`, `PUT /api/users/{id}` and `POST /api/assets/intake/{id}/approve`. That matches report §2: AuditEvent on deny in enforce, plus RoleAssignment sync.
- Viewer, Technician and Driver write in `off` on 27 distinct non-GET endpoints. That matches report §5.1 (28, counting `billing/signup` as public).
- Report §5.1 lists them with the money-relevant ones:
  - `POST /api/finance/cash-transactions`, `/bonus-payments`, `/overhead-transactions`;
  - `PUT /api/price-modifiers/project/{id}`;
  - `PATCH /api/projects/{id}/client-link`.
- 66 GET calls write: invoice numbering and pulse caches. Not called out explicitly; low.

**Main-level debt surfaced by PM-01 (NOT a #68 defect).** A Viewer can create cash, bonus and overhead transactions and change price modifiers, and that holds in every mode. This contradicts CLAUDE.md §8/§14 (permission check on every consequential write). The report already leaves the decision to Krum (§8), and per §18 it is debt until Krum confirms it hurts in real data. Flagged as **high-priority for Krum**.

**Verdict:** PASS (internal). The report is accurate and reproducible.

### Integration

#68 is clean against main, #55, #56 and #67; #67 is clean against #55.


---

## 2026-11-06 ~17:45 — PR #55 @ `53dbd28` (5C-C23: F-14 profit-by-period material/фира, F-15 waste card)

### Suites (PROVED)

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix | **223 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 219 modules, 0 violations ✔ |
| A1 | 444 units, 0 violations ✔ |
| `yarn test` MaterialWastePanel | 3 / 3 ✔ |

### Probes

- **New C23-1** (`docs/audit/probes/pr55/test_probe_pr55_c23.py`). Flow: consume 3 + write-off 2 from the project + legacy 100 before cutover. Result: profit-by-period Σ material (+ undated) = **130**, Σ waste (+ undated) = **20**, Σ `material_total` = **150** = material summary total ✔. F-14 holds: фира is not inside "material", and the total is counted once.
- **Re-runs:**
  - C22-1…5: 5/5, one test per process;
  - C21: 5/5;
  - C19: 6/8, with only the known main W0-04 concurrency pair failing.

### F-15 review (read)

- The waste card adds canonical write-offs read through the shared helper, with no write on read and no second register.
- It is a quantity card. Its totals feed no finance figure; the money side is the фира line of the C21/C22 reports.
- Low note (SUSPICION, not a money defect): if a site logs the same loss in the manual register **and** as a warehouse write-off, the card's `wasted` quantity counts it twice. The two sources are shown apart (`manual_wasted_qty` / `written_off_qty`), so it is visible.
- Label nit: write-offs from a **project** are labelled "отписване от склада".

**Verdict:** PASS (internal). Codex review required (money).


---

## 2026-11-06 ~18:15 — new PR #69 SEC-01 @ `e6c0e46` (money writes only for Owner/Admin/Accountant, R14)

**Scope (read):**
- 8 endpoints from PM-01 §5.1 get `require_money_write(action)`: the W0-02 `require_permission` with a legacy role check in off/shadow, the Permission Service in enforce, plus the `require_admin` data-path guard.
- The catalog gains 8 actions, granted to accountant only (owner/admin via the full set).
- Handler bodies unchanged. Rule sources are cited per endpoint in `docs/evidence/SEC-01/README.md`.
- PR #68 is merged in (clean).

### Tests (PROVED)

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_sec_01_money_write_permissions.py tests/test_pm_01_permission_matrix.py` | **13 passed, 0 skipped** (219 s). The PM-01 matrix is re-run: exactly 120 cells changed (8 endpoints × 5 non-finance roles × 3 modes), all now 403 with nothing written |
| R0 on real Mongo | **814 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 205 modules, 0 violations ✔ |
| A1 | 416 units, 0 violations ✔ |

### Probe `docs/audit/probes/sec01/probe_sec01_siblings.py`

Real `server.app`, ST-01 seed, real JWT, all three modes. **Both checks FAIL in off, shadow and enforce.**

| Check | off | shadow | enforce |
|---|---|---|---|
| S1: Admin PUTs project modifiers, then **Viewer** calls `DELETE /api/price-modifiers/project/{id}` | 200, config rows left **0** | same | same |
| S2: a work report exists, then **Viewer** calls `POST /api/labor-entries/sync-from-work-reports` | 200, `labor_entries` +1 | same | same |

**SEC-S1 / SEC-S2 — HIGH (security + money), PROVED. Scope gap, not an implementation defect.**
- The task package limited SEC-01 to the 8 endpoints and forbade touching others, so the PR is correct to its scope.
- But the protection is incomplete at the resource level:
  - `app/routes/price_modifiers.py:126` `DELETE …/project/{id}` has only `require_m2`. A Viewer **hard-deletes** the pricing config that only finance roles may now set. That conflicts with CLAUDE.md §2.9 (no hard delete of financial records) and §14.
  - `app/routes/labor_smr.py:73` `sync-from-work-reports` has only `require_m2`. A Viewer **creates labor cost rows** in the same `labor_entries` collection that `POST /api/labor-entries` now guards.
- PM-01 could not see these. It calls every route with nonexistent ids or empty bodies, so DELETE-by-id and "sync from existing data" routes show 404/400 with no write.
- More of the same class, not run (SUSPICION):
  - `PUT /api/price-modifiers/org` (require_m2; the README says it is "Admin/Owner only" in its body; not verified);
  - `POST /execution-packages/recompute-labor/{project_id}` (writes cached labor actuals);
  - `POST /execution-packages/recompute-material/{project_id}` and `POST /material-entries/sync/{project_id}` on #55 (rebuild projections; deterministic, but any M2 role can run them).
- **Recommendation:** extend SEC-01 (SEC-01-C01) to every write route on the same 8 resources. In the matrix harness, add "existing record" probes (create as Admin, then act as each role) so PM-01 can see DELETE/PUT-by-id and sync routes.

**Other notes:**
- SEC-01-D1 (the PR's own debt): `price-modifiers/project` and `material-waste` do not check that the project belongs to the caller's tenant; the row lands in the caller's tenant. That is recorded by the PR.
- Business impact for Krum: SiteManager and Technician can no longer log material waste or labor entries from site.

**Integration:**
- #69 is clean against main, #56, #67 and #68.
- It **conflicts with #55 in `backend/app/permissions/catalog.py`**: both add catalog actions. Resolve when the second one lands.


---

## 2026-11-06 ~18:30 — SELF-CORRECTION: two P1 defects on #55 @ `53dbd28` that this audit passed and Codex caught

Codex CHANGES_REQUESTED: https://github.com/krumingo/BEG_Worck/pull/55#issuecomment-6691597676. My PASS on `53dbd28` (17:45 entry) was wrong on two counts. Both are now **reproduced by new probes** (`docs/audit/probes/pr55/test_probe_pr55_c24.py`, real Mongo, on `53dbd28`).

| Probe | Result on 53dbd28 |
|---|---|
| **L-1** Two legacy issue rows in the **exact shape of `origin/main` `procurement.issue_to_project`** (no `tenant_id` / `movement_id`), then `ensure_required_indexes_at_startup` | **FAIL**: `E11000 … index wh_movements_unique_movement_id dup key { tenant_id: null, movement_id: null }`. The hook returns `ok: False`, so the service stays fail-closed: every canonical write is refused (INDEX_MISSING) on any real tenant with ≥2 legacy rows |
| **F-1** receive 10000@1 + 20000@2 → dispatch 30000 → accept → consume | **FAIL**: project stock value **50001.0000**, cost **50001.0**, expected 50000 |
| **F-2** the same with partial accepts 10000 + 20000 | **FAIL**: 50001.0 |
| **F-3** W2W transfer of the mixed layers, accept 12345 + 17655 | **FAIL**: target value **50001.0000** |
| F-4 odd prices, 3 @ 0.3333 + 7 @ 0.1429 | pass (2.00) |

**Why my probes missed them (root cause):**
1. Every earlier probe used a single price per flow (5@10, 10@10), and two-layer probes checked quantity, not value. A rounded-average layer can only show up with **mixed prices**.
2. My "pre-existing data" probes inserted legacy rows that I made up myself (one row, or rows that already carried tenant fields), and I created indexes in the fixture on an empty DB. A unique-index collision needs **≥2 rows in main's real shape, present before index creation**.

**Checklist additions (permanent):**
- **Value conservation:** mixed prices (at least two layers, different unit values), large quantities, odd decimals; assert value to the cent after every step (accept, partial accept, transfer, consume, rebuild).
- **Real legacy shapes only:** build fixtures by copying the writer in `origin/main` field by field (cite file:line), insert ≥2 rows **before** index creation and startup hooks, then run the startup path and a canonical write.
- **Startup on a populated DB:** drop the fixture's pre-created indexes before running startup-hook probes.


---

## 2026-11-06 ~19:10 — #55 @ `dbda909` (5C-C24) and #69 @ `aee3169` (SEC-01-C01)

### #55 @ `dbda909` — exact FIFO layers after acceptance + partial movement-id index

**Suites (PROVED):**

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix + `test_codex_c23_independent.py` | **236 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | 1085 / 15 / 50, same 15 ✔ |
| A2C | 219 modules, 0 violations ✔ |
| A1 | 444 units, 0 violations ✔ |

**Probes, real Mongo, one test per process:**

| Probe | 53dbd28 | dbda909 |
|---|---|---|
| L-1: 2 legacy rows in main's `issue_to_project` shape before startup | FAIL (E11000) | **PASS** |
| L-2 (new): 2× each of main's intake / issue / return shapes before startup, startup ×2, canonical write, legacy rows byte-identical, cutover = canonical row | — | **PASS** |
| F-1: 10000@1 + 20000@2 → accept → consume | 50001 | **50000.0000** |
| F-2: partial accepts | 50001 | **50000** |
| F-3: W2W split accept | 50001 | **50000.0000** |
| F-4: odd decimals | pass | pass |
| F-5 (new): 3 prices, dispatch 15000, accept 9000 + 6000, consume 10000, write-off 5000; rebuild ×2 + sync | — | total **27000** stable everywhere; warehouse left **24150.0000** ✔ |
| F-6 (new): prime pro-rata, dispatch 7 = 3@1 + 4@2, accept 3 + 2 + 2, consume 7 | — | layers exactly 3 / 4, cost **11.00** ✔ (no drift) |

Other probes: C22 5/5, C23 1/1, C21 5/5. C19: only the known main W0-04 concurrency pair fails.

**D-55-PRORATA — DECISION for Krum (valuation rule, PROVED behaviour, not a defect).**
- A *partial* acceptance values the accepted part **pro-rata across the dispatched layers**. In the ledger, dispatch 15000 = 7000@1 + 8000@2.5, and accept 9000 = 4200@1 + 4800@2.5. FIFO would give 7000@1 + 2000@2.5.
- The total is conserved: every probe sums exactly.
- What changes is **which layers later consumption and write-off draw from**. In F-5: consumption 17200 and фира **9800** under pro-rata; consumption 14500 and фира **12500** under strict FIFO. Package and period attribution move the same way.
- Pro-rata is defensible, since which physical units arrived is unknown, but it is a valuation rule. It should be written into the FLOW-009 canon.

### #69 @ `aee3169` — SEC-01-C01 (every write on the money resources guarded; R16 for labor and waste)

**Tests (PROVED):**

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_sec_01_c01_all_money_writes.py tests/test_sec_01_money_write_permissions.py tests/test_pm_01_permission_matrix.py` | **20 passed, 0 skipped** (245 s) |
| R0 on real Mongo | **814 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |

**Probes:**
- `probe_sec01_siblings.py`: **now PASS in all three modes.** A Viewer's DELETE on project price modifiers → 403, config kept. A Viewer's labor sync → 403, 0 rows. **SEC-S1 and SEC-S2 are CLOSED.**
- `probe_sec01_c01_r16.py` (new): R16 edge cases on the real app, three modes.

| Check | off | shadow | enforce |
|---|---|---|---|
| R1: Technician added by Admin with `to_date` = **yesterday**; labor entry / material waste on that project | **201 / 201** | **201 / 201** | **201 / 201** |
| R2: non-member SiteManager adds himself to the team | 403 ✔ | 403 ✔ | 403 ✔ |
| R3: member posts a labor entry without `project_id` | 403 ✔ | 403 ✔ | 403 ✔ |

**SEC-R1 — MEDIUM (security), PROVED.** R16 "member projects only" honours `active` but **not the membership period**.
- `app/tenancy/project_team.py:93-107` `membership_filter` adds `active: True` only. `from_date`/`to_date` are stored but never checked, and the enforce RoleAssignment mirror does not cut it off either.
- So a field worker whose assignment ended keeps writing labor cost and waste on that project until someone flips `active`.
- The three modes agree, so this is not a parity bug. The same membership semantics already apply to `can_access_project` on main, so the root cause is pre-existing, and SEC-01-C01 now relies on it for money writes.
- Fix: honour `from_date ≤ today ≤ to_date` in `membership_filter` (or in R16's legacy check plus the RA mirror's `valid_to`).

Other notes:
- DELETE price modifiers now refuses everyone (409 for finance roles: "no archive model"), recorded by the PR as debt C01-D2. Krum may want a correction/archive path.
- `recompute-material` and `material-entries/sync` (#55) are still open to any M2 role, as the PR notes; they are deterministic rebuilds.

**Integration:**
- #69 conflicts with **#55** in `backend/app/permissions/catalog.py`; clean against the rest.
- #55 still conflicts with **#56** (`data_access.py`, A2B inventory) and is clean against #67/#68.

### Addendum — #69 @ `aee3169`: what each role LOSES (orchestrator request), PROVED

**1. PM-01 matrix diff** (`git show pr/68:docs/evidence/PM-01/matrix.csv` against `git show pr/69:…`, 18,048 cells each, same keys)
- Every cell that changed from <400 to 401/403/409 is listed below. **No role gained anything.**
- 15 further changes are 400 → 403 on `sync-from-work-reports`: the refusal now comes before body validation.

| Endpoint | Roles that lose it (all three modes) |
|---|---|
| POST `/api/finance/cash-transactions` | SiteManager, Technician, Warehousekeeper, Driver, Viewer |
| POST `/api/finance/bonus-payments` | same |
| POST `/api/finance/overhead-transactions` | same |
| POST `/api/overhead-snapshots` | same |
| PUT `/api/price-modifiers/project/{id}` | same |
| PATCH `/api/projects/{id}/client-link` | same |
| POST `/api/labor-entries` | same (R16: SiteManager/Technician keep it **on member projects**; the matrix caller is not a member) |
| POST `/api/projects/{id}/material-waste` | same (R16 as above) |
| POST `/api/execution-packages/recompute-labor/{id}` | same (R16) |
| DELETE `/api/price-modifiers/project/{id}` | **everyone, Owner/Admin included** (409 for finance roles, debt C01-D2: no archive model) |

**2. SiteManager on projects** (the implementer's claim), probe `docs/audit/probes/sec01/probe_sec01_c01_sitemanager_loss.py`
- Setup: the SiteManager is a SiteManager member of the project (so `can_manage_project` is true), on main as the baseline and on #69.

| Action | main | #69 (off / shadow / enforce) |
|---|---|---|
| create project without client | 201 | 201 (kept) |
| create project **with** `owner_type/owner_id` | 201 | **403** (lost) |
| PUT project, **change** `owner_id` | 200 | **403** (lost) |
| PUT project, same `owner_id` + new name | 200 | 200 (kept) |
| PUT project, name only | 200 | 200 (kept) |

The implementer's claim is **confirmed and exact**: SiteManager loses only setting or changing the paying client of a project. Project create and edit otherwise stay. This is a business-visible change for Krum.

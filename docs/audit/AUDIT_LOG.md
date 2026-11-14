# CLAUDE AUDIT — log

> Internal second check by the Claude audit session. **Not Codex**, not an approval.
> Never merges, deploys or pushes to other branches. PROVED = reproduced here by command; SUSPICION = reasoning only.

## Last audited SHA per PR

| PR / branch | Last audited SHA | Result | Date |
|---|---|---|---|
| #86 PRJ-01 | `49eb546` | **PASS** (main `1525a1e` merged; SEC-02 / PM-01 regen 0 cells) | 2026-11-09 |
| #84 INV-CN-01 | `38d3244` | **PASS** (F-84-01, FG-571 / 572 / 599; warehouse 44/1121; SEC-02 + PM-01 regen 0 cells; R47 wiring notes for the 2nd merger) | 2026-11-13 |
| #83 CP-01 | `eb8138f` | **PASS** (evidence-only over `5695f97`; FG-562; CP83-M6 + M7 closed; warehouse 44/1121 on `ec346f8`; W0 10 ⊂ main) | 2026-11-13 |
| #90 SEC-03 | `66dd1ae` | **PASS** (delta over `aaef24f`: FG-563 / 603 / 604 / 535 / 515; live TTL check; warehouse 44/1121; N1 deploy JWT_SECRET ≥32) | 2026-11-13 |
| #89 OFF-02 | `5763bd8` | **PASS** (main `3863610` merged; OFF89-M2 closed — SEC-02 188 probes, regen 0 cells; warehouse 44/1121) | 2026-11-13 |
| #73 LAB-01 | `a1859bf` | **PASS — pending Krum decisions FG-565 / FG-569** (FG-566 / 567 / 530; SEC-02 + PM-01 regen 0 cells; warehouse 44/1121) | 2026-11-13 |
| #75 LAB-02 | `c7d8464` | **PASS — pending Krum FG-565 / FG-569** (contains #73 `a1859bf`; FG-568; SEC-02 + PM-01 regen 0 cells; warehouse 44/1121 on `a665932`) | 2026-11-13 |
| #88 PWA-01 | `62f898a` | **PASS** (PWA88-N1 closed; D5 emergent script = Krum) | 2026-11-09 |
| #92 PWA-02 | `4140b02` | **PASS** (code `4dd947c`; PWA92-M1 / M2 / M3 + N1 closed; no delete on attendance / daily reports; warehouse 44/1121; SEC-02 + PM-01 regen 0 cells) | 2026-11-14 |
| #91 MEDIA-SEC-01 | `39a1e27` | **PASS** (code `c41da0b`; R88 restore + review screen; FG-706 keyset paging; FG-707 --approval-ref required for --apply) | 2026-11-14 |
| #82 WH-REV-01 | `558dfdf` | **PASS** (code `642227b`; R84 supplier claim replaces 409 PAID_ABOVE_NET; warehouse 44/1121; PM-01 regen 0; for the record — superseded by FG-690: after #84 merges, the overpaid part becomes an open expected credit in #84 expected_credit_notes) | 2026-11-14 |
| #56 AUTH-01/02 | `3234446` | PASS (AUTH-02 break-glass) | 2026-11-06 |
| #55 LIVE-OPS-01 | `94c0571` | **PASS** (FG-124: deprecated allocation inputs locked; embedded `invoices.lines` is not a bypass) | 2026-11-07 |
| #67 ST-02 | `675faba` | **PASS** (C03 R26); low: ST02-C03-L1 flaky bundle-id collision in test fixture; rehearsal evidence read, not re-run | 2026-11-06 |
| #68 PM-01 | `4e20084` | PASS (report accurate; main-level permission debt surfaced) | 2026-11-06 |
| #70 PAY-01 | `4b745f1` | **PASS** (C01-G fixes PAY70-04; N1–N4 24/24) | 2026-11-07 |
| #69 SEC-01 | `ccab244` | **PASS** (FG-90 atomic certified-total reservation); note FG90-N1 (reservation never released on reversal) | 2026-11-07 |
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
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |

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


---

## 2026-11-06 ~19:40 — four new heads: #55 `3706611` (5C-C25), #56 `3234446` (AUTH-02), #69 `f33b2ba` (SEC-01-C02), #67 `98b18ec` (ST-02-C02)

### #55 @ `3706611` — Р17 cost at acceptance, Р18 every move in transit / returns via quarantine, FG-17, FG-19

**Suites (PROVED):**

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix + `test_codex_c23_independent.py` | **250 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |
| yarn CanonicalWarehousePage* | 23 / 23 ✔ |

**Test-weakening check:**
- In the 11 changed test files, removed asserts number fewer than or equal to added ones, with no new skip or xfail.
- Number changes follow Р17, for example accept 5 + consume 3 → 30 becomes **50**, and the consume row is no longer cost.

**New probes** (`docs/audit/probes/pr55/test_probe_pr55_c25.py`, real Mongo, one per process) — **5 / 5 PASS:**

| Probe | Result |
|---|---|
| C25-1: 10000@1 + 20000@2 accepted (50000); return 15000 via quarantine | project **30000** + quarantine **20000.0000** = 50000; release → free 20000.0000 ✔ |
| C25-2: project→project 12345 of mixed layers, accept 5000 + 7345 | p1 + p2 = **50000** after dispatch, after the partial accept (44050.22 + 5949.78) and after the full accept (35310 + 14690) ✔ |
| C25-3: accept 10@10 → return 4 → release → re-dispatch 4 → re-accept | 100 → 60 → **100** (not 140); consume 3 + write-off 2 add nothing; rebuild ×2 and sync stay at 100 ✔ |
| C25-4: legacy 100 before cutover + accept 5@10 (consume 3) | **150** on summary, pnl, financial_results, centralized and profit_by_period ✔ |
| C25-5: main-shape invoice line (built by main's `compute_line_totals`, ex-VAT 100) allocated to p1 + canonical accept 50 | helper total **150**; main's P&L showed `max(100, 50)` = **100** |

C24 probes L-1, L-2 and F-1…F-6: all pass under C25 (F-5 total 27000, F-6 11.00). C19: the known main pair fails, plus `c19_1`, which uses a direct project→warehouse transfer that Р18 now refuses by design. My C20/C21/C22/C23 probes encode cost at consumption (pre-Р17) and are **superseded** by C25-3 and C25-4.

**D-55-FG17 — DECISION for Krum (money, PROVED behaviour).**
- FG-17 removes main's `max(invoice, warehouse)` and **sums** Path B invoice lines allocated to the project with canonical cost.
- A line is excluded only when a canonical ledger row references its `invoice_line_id`.
- Legacy data (before the canon) never carries that link. If a supplier invoice line allocated to the project **and** a warehouse issue describe the same goods, both are counted. The `max` rule existed to prevent exactly that.
- Also pre-existing, as SUSPICION: selection uses the deprecated `allocation_type/allocation_ref_id`, so a line split over several projects (`allocations[]`) counts its full total on one project.
- Krum confirms whether invoice-allocated lots and warehouse issues are disjoint in real data.

### #56 @ `3234446` — AUTH-02 break-glass CLI (Р19), FG-8…11, FG-16

**Suites (PROVED):**

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_auth_0*.py tests/test_r0_0*.py` | **936 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |

**Probe** `docs/audit/probes/auth02/probe_auth02.py`. The #56 branch has no `ops/staging`, so the probe runs against a scratch repo: main's `ops/staging` plus a symlink to the #56 backend. **All PASS.**

| Check | Result |
|---|---|
| A1: `validate_attribution` with hostile text | refused: blank, whitespace, zero-width only, a U+202E bidi override inside, newline, ESC, bcrypt-looking text, 5000 characters. A normal Cyrillic operator and reason are accepted ✔ |
| A2: admin set-password (FG-11) | 200; the old session's `/auth/me` → **401**; the old password → **401**; the new password → 200; the open reset link is revoked (`admin_password_reset`); 1 canonical AuditEvent ✔ |
| A3: tenant B's Owner sets the password of tenant A's Viewer | **404**, hash unchanged ✔ |

**Verdict:** PASS (internal). Security, so the Codex review is required.

### #69 @ `f33b2ba` — SEC-01-C02 (FG-24/26/27/30/31)

**Tests (PROVED):**

| Command | Result |
|---|---|
| C02 + C01 + SEC-01 + PM-01 on real Mongo | **28 / 0 / 0** |
| R0 | 814 |
| W0 | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |

- `probe_sec01_siblings.py`: still PASS.
- `probe_sec01_c01_r16.py`: R1 still **FAIL** in all three modes (SEC-R1 open).

**Probe** `docs/audit/probes/sec01/probe_sec01_c02_payments.py` (real app, tenant A's Accountant, `POST /api/subcontractor-payments`):

| Check | Result |
|---|---|
| P1: identical POST ×2 | 201, 201 → **2 Outflow rows in `finance_payments`** |
| P2: `amount` = `"nan"` / `"inf"` / `"1e309"` | **500**, but a ledger row is written each time (`{'amount': nan}` found) |
| P2: `amount` = `"-0"` | 400, nothing written ✔ |
| P3: tenant B's `account_id` | 404, nothing written ✔ |
| P4: payment of 5000 against `certified_total` 1000 | 201 (business rule, reported) |

**C02-P2 — BLOCKING (money), PROVED.**
- `subcontractors.py`, `create_subcontractor_payment`: `amount = float(...)`; `if amount <= 0` lets NaN and ±Inf through. The ledger row is inserted, then JSON serialisation fails with 500.
- So the ledger holds a non-finite outflow while the caller sees an error.

**C02-P1 — BLOCKING (money), PROVED.**
- No idempotency on a write into the FLOW-006 ledger (the PR's debt D1). With P2 (500 after commit), an ordinary retry produces a **double payment**. This conflicts with CLAUDE.md §14.

A comment was posted on #69 (CLAUDE AUDIT, internal).

### #67 @ `98b18ec` — ST-02-C02 (staging defaults to shadow, R15; FG-3…6)

- `pytest --noconftest tests/test_st_02_staging_stack.py` → **157 passed**.
- Isolation probe: the baseline gains `PUBLIC_URL=http://127.0.0.1:18080` (now required) and 7 new FG-5 cases (public / lookalike `PUBLIC_URL`, `CORS_ORIGINS=*` or an external origin, external frontend `REACT_APP_BACKEND_URL`, `BOOTSTRAP_*` / `SEED_ADMIN_*` env). **25 / 25 refused** ✔.
- **Verdict:** PASS.

### Integration

| Pair | Status |
|---|---|
| #56 × #55 | conflict (`data_access.py`, A2B inventory) |
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |
| #56 × main / #67 / #68 / #69 | clean |
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |


---

## 2026-11-06 ~20:10 — #55 @ `d8923d7` (5C-C25 Addendum A, Р21), #69 @ `471eaaa` (SEC-01-C02 addendum A, SEC-R1), and the open checks on #56 / #67

### #55 @ `d8923d7` — Р21: a partial accept takes layers oldest-first at their own price (resolves D-55-PRORATA)

**Suites (PROVED):**

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix + `codex_c23_independent` | **252 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |
| Test-weakening check on the 3 changed test files | asserts −2/+3, 0/+14, 0/+2; 0 skip/xfail ✔ |

**Probes (all PASS, one test per process):**

| Probe | Result |
|---|---|
| L-1, L-2 (real legacy shapes) | pass |
| F-1…F-4 (mixed prices, 50000 exactly) | pass |
| **F-5 tightened to strict FIFO** | `(total, фира)` = **(27000, 12500)** after projector, rebuild ×2 and sync; warehouse left 24150 ✔ (was 9800 pro-rata on `dbda909`/`3706611`) |
| F-6 | layers 3 / 4 exactly, cost 11 ✔ |
| C25-1…C25-5 | pass. C25-2's partial step is now exact: 45000 / 5000 (the first 5000 of the oldest layer) |

**Package checklist (`5C-C25_COST_AT_ACCEPT_AND_FLOW_GUARD.md`):**
- **Р17 cost at accept, returns reduce it, SMR consume is allocation only** — PROVED (C25-1, C25-3; consume and write-off add no cost).
- **Р18 transit for every move, returns via quarantine, direct transfer refused** — PROVED (C25-1/2/3; C19-1's direct project→warehouse transfer is refused).
- **Р21** — PROVED (F-5).
- **FG-17: P&L reads only the shared helper, no `max()`** — read in code (`services/project_pnl.py:76,174`) and PROVED numerically (C25-5: 150, main showed 100). **D-55-FG17 stays a decision for Krum.**
- **FG-19 (no phantom "в път")** — fixed, with a test in the C25 file.
- **FG-22 and FG-23** — **justified, not changed**, in HANDOFF 5C-C25, as the package allows. FG-22 needs a threshold from Krum plus the W0-07 Approval runtime. FG-23 depends on FG-13 (SEC-02 rule 4 not yet decided). Both stay open for Krum.

### #69 @ `471eaaa` — SEC-01-C02 addendum A (SEC-R1)

**Tests (PROVED):**

| Command | Result |
|---|---|
| C02 + C01 + SEC-01 + PM-01 on real Mongo | **30 / 0 / 0** |
| R0 | 814 |
| W0 | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |

**`probe_sec01_c01_r16.py`, extended with date boundaries — PASS in off, shadow and enforce:**

| Case | Result |
|---|---|
| Ended membership (`to_date` = yesterday) | labor 403, waste 403 |
| `to_date` = today | 201 (still a member) ✔ |
| `from_date` = tomorrow | 403 ✔ |
| `from_date` = today | 201 ✔ |

**SEC-R1 is CLOSED.** `probe_sec01_siblings.py` still passes.

**`membership_filter` callers** (all now date-aware through `is_member` / `member_row`):

| Caller | Purpose |
|---|---|
| `deps/auth.py:143` `can_access_project` | project read access |
| `deps/auth.py:152` `can_manage_project` | project management |
| `permissions/money_write.py:144` | R16 |
| `routes/attendance.py:144,152,469,575,764` | attendance |
| `routes/work_logs.py:149,168` | work logs |
| `tenancy/data_access.py:429` | data access |
| `routes/projects.py:456` | the "already on team" check |

- Side effect: an expired membership no longer blocks re-adding the same user (a new row is created). That is reasonable for re-assignment.
- Debts noted by the PR: **D5** (`assigned_project_ids`, `managed_project_ids` and `project_rows` ignore dates, so list views may still show expired projects) and **D6** (existing project-scope mirrors get the window only at the next sync or bootstrap).

**Blocking findings C02-P1 / C02-P2 are UNCHANGED** on `471eaaa`. `probe_sec01_c02_payments.py`:

| Check | Result |
|---|---|
| Identical POST ×2 | **2** Outflow rows |
| `amount` = `"nan"` / `"inf"` / `"1e309"` | 500 **after** a ledger row is written |
| tenant B's account | 404 ✔ |

The comment on #69 still applies.

### #56 @ `3234446` — the open items of the orchestrator's AUTH-02 checklist

- **Operator + reason required:** probe A1, plus `tests/test_auth_02_break_glass.py:56-58` (exit usage without them).
- **AuditEvent written:** `test_success_records_operator_reason_r1_and_notifies_every_owner` (`:105`).
- **Owner notified:** same test, plus `test_owner_email_is_sent_after_commit_when_configured` (`:151`).
- **No business-content access:** read in code. `scripts/reset_user_password.py` reads only `users` (the target and the tenant's Owners, `:198`) and writes only the user, reset tokens, audit and notifications. There are no project, finance or document reads.
- **FG-8:** `test_fg8_a_non_owner_target_is_refused` (`:220`) and `…role_change_during_the_run_writes_nothing` (`:233`).
- **FG-11:** probe A2. **FG-16:** read in code (`auth_events._key` fails closed). **FG-10:** TTL 730 days.

**Verdict unchanged:** PASS (internal); security, so the Codex review is required.

### #67 @ `98b18ec` — rehearsal status

- C02 changed only `docs/evidence/ST-02/README.md` (a note) and `tests-ST-02-C02.txt`.
- The README says: *"Репетицията с `shadow` (и с новите `--deployed-by`/`--approved-by`, FG-3 `staging-deployment.json`) **още не е пусната отново**"* (the rehearsal with `shadow`, the new `--deployed-by`/`--approved-by` and FG-3 `staging-deployment.json` has not been re-run yet).
- So **the rehearsal evidence still predates C02** (`actor: "unknown"`, enforce). This stays **OPEN**: the code passes, but there is no live proof of the shadow default and FG-3/FG-4 on a real stack yet.

### Integration (merge-tree)

| Pair | Status |
|---|---|
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |


---

## 2026-11-06 ~20:30 — new PR #70 PAY-01 @ `a0dec8b` (payments reversed, never deleted; R23, FG-34). Base main `07da9ab`; main is now `8e3b190` (PM-01 merged)

**Package:** `PAY-01_PAYMENT_REVERSAL_NO_HARD_DELETE.md`. **HANDOFF:** `docs/evidence/PAY-01/README.md`.

### Suites (PROVED)

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_pay_01_payment_reversal.py` | **91 passed** |
| R0 on real Mongo | **814 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C | 205 modules, 0 violations ✔ |
| A1 | 416 units, 0 violations ✔ |
| `yarn test src/pages/__tests__/` | 26 / 26 ✔ |

**No hard delete (PROVED by grep of the PR head):** no `delete_one`, `delete_many` or `find_one_and_delete` on `finance_payments` or `payment_allocations` anywhere in `backend/app`.

**Readers (read in code):** every reader of both collections outside the write path uses `active_payments` / `active_allocations`:
- account balances, `finance.py:381,385,1735`;
- invoice paid/remaining, `update_invoice_status`;
- invoice detail, invoice payments, cancel-invoice check;
- the payments list (`include_reversed`) and the payment detail allocations;
- allocate, which refuses a reversed payment or a reversal row;
- P&L `other_cost`, `services/project_pnl.py:119`;
- project payments, `projects.py:1273`.
`delete_account` / `delete_invoice` count **all** rows, reversed ones included (used = history) → 409.

### Probe `docs/audit/probes/pay01/probe_pay01.py` (real `server.app`, ST-01 seed, tenant A's Accountant)

| # | Check | Result |
|---|---|---|
| Q1 | 6 concurrent DELETEs of one payment | statuses [200, 409×5]; **1** reversal row; **1** AuditEvent ✔ |
| Q2 | 6 concurrent reversals of 6 different payments | 6 × 200; 6 reversed; 6 reversal rows; 6 AuditEvents ✔. The W0-04 audit race did not fire in this run; it remains main debt |
| Q3 | Idempotency-Key | first 200; replay 200 with an identical body; same key + other reason → **409** ✔ |
| Q4 | inflow 100, then reverse | balance 0 → 100 → **0**; the default list hides both rows; `include_reversed=true` shows the pair ✔ |
| Q5 | own-account transfer of 50, reverse one leg | **both** legs `reversed`; both balances back ✔ |
| Q7 | crash between writes (original `reversed`, no reversal row), then DELETE again | 409, but the pair is completed: exactly **1** reversal row ✔ |
| Q8 | Viewer / SiteManager / Technician DELETE in off / shadow / enforce | **403** each, nothing written, the payment unchanged ✔ |
| Q6 | hostile input | see the findings below |

**Baseline on main `8e3b190`** (same probe, Q1): 6 concurrent DELETEs → 5 × 200 + 1 × 404. The payment is hard-deleted, with no reversal and no audit. That is exactly what PAY-01 fixes.

### Findings

**PAY-N1 — HIGH (money), PROVED, pre-existing on main (NOT a PAY-01 regression).** Non-finite amounts reach the payment ledger.
- `POST /api/finance/payments` (pydantic `float` accepts `"nan"` / `"inf"`), `POST /api/finance/transfers` (`float(...) <= 0`) and `POST /api/finance/payments/{id}/allocate` (amount `"nan"`) each **write** the row, then fail with **500** (JSON serialisation).
- Payment create + transfer give **+3 ledger rows** for NaN and +3 for Inf.
- Identical on main `8e3b190` (`probe_amounts_baseline.py`). The same class as #69 C02-P2.
- Recommendation: put one finite-positive-Decimal validator in the money-input layer and apply it to all of these routes. SEC-01-C03 is already on NaN for #69 and could cover these routes too.

**PAY-N2 — LOW.** The reversal `reason` is unbounded and accepts control characters: a 5000-character reason and `a\x00b\x1b[31m` are both stored. It goes into the AuditEvent and the reversal row's note. An object `{"$ne": 1}` → 400 ✔.

**INT-70x69 — HIGH (money, integration), PROVED on a local merge of #70 `a0dec8b` + #69 `471eaaa`** (scratch commit `be6879e`, not pushed). Probe: `docs/audit/probes/pay01/probe_pay01_x_sec01_c02.py`.
- Steps: a subcontractor payment of 300 (FG-27 writes a `finance_payments` Outflow and a `subcontractor_payments` row), then `DELETE /api/finance/payments/{ledger id}` with a reason.
- Results:
  - the ledger reversal is 200 and the account balance goes back to 0;
  - **but** `subcontractor_payments` stays `status: completed, amount: 300`;
  - the package keeps `paid_total 300 / payable_total 700`.
- So the package shows a payment that the ledger no longer has: two views of the same money disagree (CLAUDE.md §2.5/§7).
- Neither PR alone has the defect. **Whichever of #69 and #70 merges second must handle it.** Either PAY-01 reverses the linked `subcontractor_payment_id` and recomputes the package, or FG-27's package totals are derived from the active ledger rows.

### Integration (merge-tree)

| Pair | Status |
|---|---|
| #70 PAY-01 | `31ed258` | **PASS** (D5-R1/R2 fixed by locks; FG-50 422); IDEM-IDX-1 resolved once #72 is merged (proved on a scratch merge) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |

- On the merged #70 + #55 tree, `services/project_pnl.py` keeps `active_payments` on `other_cost` (semantic check ✔).
- The textually clean #70 × #69 merge is **semantically wrong**: see INT-70x69.

**Verdict:** PAY-01 in its own scope: **PASS (internal)**. Money, so the Codex review is required. PAY-N1 is main debt. INT-70x69 is blocking for the second of #69 / #70 to merge.


---

## 2026-11-06 ~20:45 — #55 @ `25e1bab` (5C-C26: one path per lot between Path A and Path B; resolves D-55-FG17)

### Suites (PROVED)

| Command | Result |
|---|---|
| Warehouse real-Mongo matrix + `codex_c23_independent` | **264 / 0 / 0** |
| R0 + RC-01 + ST-01 on real Mongo | **881 / 0 / 0** |
| W0 DB-free | same 15 ✔ |
| A2C / A1 | 0 / 0 ✔ |

### Probes (`docs/audit/probes/pr55/test_probe_pr55_c26.py`, real Mongo)

Invoice lines are built with **origin/main's own `compute_line_totals` + `compute_allocation_stats`** (real shape). **4 / 4 PASS:**

| Probe | Result |
|---|---|
| C26-1: line 10 @10 split over `allocations[]` p1 5 / p2 5 | p1 **50**, p2 **50** (main's selection would have put 100 on p1) ✔ |
| C26-2: line allocated 10 to p1 + canonical `receive_from_supplier` 10 with `invoice_line_id` → dispatch → accept at p1 | p1 **100** (one lot, not 200) ✔ |
| C26-3: partial link (direct receipt to p1 of 4 with `invoice_line_id`) | p1 **100** = 40 canon + 60 line (not 140) ✔ |
| C26-4: pre-cutover legacy issue (main's `issue_to_project` shape) of the same material + Path B line | sum unchanged (**200**); warning `PATH_B_LEGACY_OVERLAP_UNPROVEN` raised for T; tenant T2 sees **no** warnings ✔ |

**Re-runs:** C24 L-1, L-2, F-1…F-6 and C25-1…5 are **13 / 13 ok** (C25-5: a line with no link is still a separate lot, total 150, as C26 intends).

**Not probed, by design:** an allocation summing to more than the line quantity. `path_b_split` does not cap at the line total, but main's writers refuse it (`invoice_lines.py:326,413,507,568`). Under the real-shapes rule (18:30 entry) I do not probe with invented rows. Low note: if such data was ever imported, Path B would overcount.

**D-55-FG17 is CLOSED** per the canon (FLOW-043 D-04, FLOW-009 Path A/B), as the orchestrator relayed. A lot is counted once when the link is proven; an unproven overlap stays summed but is surfaced as an integrity warning, not silently.

### Integration

| Pair | Status |
|---|---|
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |


---

## 2026-11-06 ~21:00 — #55 @ `71c11da` (5C-C26 Addendum A delta only; full audit at the C26b head)

Scope:
- FG-21 → Р27 write-off rights (`write_off_policy.py`);
- FG-23 → Р20 money only for finance roles (`warehouse_canonical_queries.py`, `_values_for` / `strip_values`);
- Bulgarian labels.

### Read in code

**Р27 policy:**
- owner / admin / accountant on every project; project_manager on their own project scope or as an in-date member; site_manager and technician only as an in-date member (a local `_member_in_date` until #69's dated `membership_filter` lands); everyone else 403.
- Fails closed on an unreadable date.
- The orchestrator says Accountant and member Technician get 201 only in Addendum B, through a dedicated action. Not probed now.

**Р20 value hiding:**
- `strip_values` drops `unit_value`, `total_value`, `movement_value`, `value`, `line_value` and `layer_value`, recursively, for any caller without an active owner/admin/accountant (or procurement, kept unchanged and noted in the HANDOFF) RoleAssignment.
- It is applied **only to `GET /stock/{item}` and `GET /history`**.

### Probe `docs/audit/probes/pr55/probe_pr55_c26a_value_leak.py` (PROVED)

Real `server.app`, ST-01 seed, **enforce**, real JWT. The Admin receives 10 @10 into tenant A's warehouse, then the **Warehousekeeper** (`role_id` `warehouse`, not a finance role) calls every canonical read and one write:

| Call | Status | Money in the response |
|---|---|---|
| GET `/warehouse/canonical/stock/I1` | 200 | none (`values_hidden: true`) ✔ |
| GET `/warehouse/canonical/history` | 200 | none (`values_hidden: true`) ✔ |
| GET `/warehouse/canonical/balance/I1` | 200 | none (quantities only) ✔ |
| GET `/warehouse/canonical/integrity-warnings` | 200 | none in this scenario ✔ |
| **POST `/warehouse/canonical/movements` (dispatch, response)** | 200 | **`envelope.unit_value` and `envelope.layer_allocations[*].unit_value`**: the server's FIFO valuation |

**C26A-1 — MEDIUM (Р20, PROVED).**
- The write response (`MovementCommandResponse.envelope`, `routes/warehouse_canonical.py:233-238`) returns the full envelope, including the FIFO unit values of the layers drawn, to a non-finance role.
- A Warehousekeeper who dispatches, accepts, transfers or consumes learns the stock cost that Р20 hides on the read side.
- Fix: pass the envelope through the same `_values_for(ctx, …)` before returning it, including on a replay.
- Not checked (SUSPICION): Path B integrity warnings with value fields (none fired here). `strip_values` would not drop `counted_value` / `covered_value` if such keys reach that response.

Gates not re-run for this intermediate head. They will run on the C26b head.


---

## 2026-11-06 ~21:20 — #70 @ `61d45d3` (PAY-01-C01 Part 1: finite positive amounts → 422, clean reversal reasons → 400)

### Suites (PROVED)

| Command | Result |
|---|---|
| `W0_03_REAL_MONGO_URL=… pytest --noconftest tests/test_pay_01_payment_reversal.py tests/test_pay_01_c01_amounts_reason.py` | **219 passed** |
| R0 on real Mongo, first run (in parallel with W0 on the same Mongo) | 1 failed / 813 passed |
| R0, two re-runs (`-x` and `-rf`) | **814 / 0 / 0**. The single failure did not reproduce: unreproduced flake, noted, not a finding |
| W0 DB-free | same 15 ✔ |
| A2C | 206 modules, 0 violations ✔ |
| A1 | 418 units, 0 violations ✔ |
| `yarn test src/pages/__tests__/` | 26 / 26 ✔ |

### Probes

`probe_pay01.py` re-run: **all PASS**, including Q6. NaN / Inf / -Inf / 1e309 on payment create and transfer → **422, ledger +0**; on allocate → 422, +0. On `a0dec8b` these were 500 with rows written.

**New `probe_pay01_c01.py`** (real `server.app`, tenant A's Accountant). Hostile amounts `nan`, `inf`, `-inf`, `1e309`, `""`, `-1`, `0`, `true`, `"abc"` on every money route:

| Route | Hostile amounts | Valid 12.5 |
|---|---|---|
| POST `/finance/transfers` | all 4xx, 0 rows ✔ | 201 |
| POST `/finance/account-funding` | all 4xx, 0 rows ✔ | 201 |
| POST `/finance/other-expense` | all 4xx, 0 rows ✔ | 201 |
| POST `/finance/other-income` | all 4xx, 0 rows ✔ | 201 |
| POST `/finance/invoices/{id}/payments` (quick-pay) | all 4xx, 0 rows ✔ | 201 |
| POST `/finance/payments` | all 4xx, 0 rows, **except `true` → 201 (+1 row, amount 1.0)** | 201 |
| POST `/finance/payments/{id}/allocate` | all 4xx, 0 rows, **except `true` → 200 (+1 allocation of 1.0)** | 200 |

Reversal reason:

| Reason | Result |
|---|---|
| 500 characters | 200 ✔ |
| 501 characters | **400** ✔ |
| ZWSP | **400** ✔ |
| RLO | **400** ✔ |
| NUL | **400** ✔ |
| ESC | **400** ✔ |
| soft hyphen U+00AD | 200 |
| tag character U+E0041 | 200 |
| line separator U+2028 | 200 |

**PAY-N1 — CLOSED** for every finance money route. **PAY-N2 — CLOSED** for the length bound and the listed characters.

**PAY-C01-L1 — LOW, PROVED.** JSON `true` is accepted as the amount `1.0` on the two pydantic-typed routes (`PaymentCreate.amount`, `AllocationInput.amount`: `float` coerces `true` to `1.0` **before** `positive_amount` sees it, so its "booleans refused" rule is bypassed). The dict-based routes refuse it. Fix: `StrictFloat` / `Union[StrictFloat, StrictInt, str]`, or a `mode="before"` validator.

**PAY-C01-L2 — LOW, PROVED.** The reason filter refuses category Cc plus a fixed list, but accepts other invisible Cf characters: soft hyphen, the tag block, and U+2028/2029 (Zl/Zp). Suggest refusing categories Cf, Zl and Zp in general.

### UI impact of 400 → 422 (read in code)

- `PaymentsPage.js:274` filters `amount > 0` before allocate, so the stricter allocate (whole request 422 instead of silently skipping ≤ 0 lines) is not hit from the UI.
- The amount error details are plain strings: `alert(detail)` shows them.
- Reason errors are `{error_code, message}`: both reversal dialogs show `detail.message` (`PaymentsPage.js:252-253`, `InvoiceEditorPage.js:404-405`).
- No UI path breaks.

### Integration

- #70 is clean against main, #55, #56, #67 and #69.
- INT-70x69 (subcontractor payment not reversed with its ledger row) waits for Part 2, after #69.


## #69 SEC-01-C03 @ `07faab5` — 2026-11-06 ~20:40 UTC — PASS

Commands, from wt69/backend, real Mongo RS at 127.0.0.1:27019:
- `PERMISSION_SERVICE_MODE=enforce MONGO_URL=...replicaSet=rs0 W0_03_REAL_MONGO_URL=... pytest --noconftest tests/test_sec_01_*.py` → **30 passed**
- `pytest tests/test_r0_0*.py` (real Mongo) → **814 passed**
- `pytest tests/test_w0_*.py` → **1085 passed / 15 failed / 50 skipped**. The FAILED list is identical to `fail_56.txt` (the 15 legacy_routes failures).
- A2C guard 0/206; A1 guard 0/418.
- Frontend yarn tests NOT run: there is no node_modules in the worktree.

Probe `docs/audit/probes/sec01/probe_sec01_c02_payments.py`, extended with P1b/P1c. All results PROVED:

| Probe | Request | Result |
|---|---|---|
| P1b | same Idempotency-Key, sent twice with the same body | 201/201, identical response JSON, ledger +1 |
| P1b | same key, different body | 409 |
| P1c | 6 concurrent requests, same key | [201, 409×5], ledger +1 |
| P2 | nan / inf / -0 / 1e309 | 422, ledger +0 |
| P3 | cross-tenant account | 404, ledger +0 |
| P1 | two POSTs **without** a key | 201/201, 2 Outflow rows |

The P1 result without a key is the documented legacy behaviour (`money_input.py:27`). The frontend now sends a key per payload (`lib/idempotency.js`).
- Residual (NOT blocking): it is Krum's decision whether the money routes should require the key.

Code read: `MoneyWrite` scopes the key as tenant + action + user (`money_input.py:113-118`). Key-derived ids allow resume after a FAILED attempt.

Siblings, r16 (SEC-R1) and sitemanager-loss probes: FAILS none.

Action taken: updated the existing PR comment 6693570924 to mark the blockers resolved. No new comment.


## #55 5C-C26 Addendum B + C26b + C26c @ `64418eb` — 2026-11-06 ~20:50 UTC — FINDINGS (blocking)

Commits since `71c11da`:
- `d2b9633`: dedicated `POST /warehouse/canonical/project-writeoff`, plus P&L input VAT by `allocations[]`.
- `0beeb9d`: no money in command responses for non-finance roles.
- `64418eb`: Р27 applied in off, shadow and enforce.

Gates, from wt55/backend on the real Mongo RS:

| Gate | Result |
|---|---|
| Warehouse canonical + `test_codex_c23_independent.py` | **365 passed** |
| R0 | **814 passed** |
| W0 | 1085 passed / 15 failed / 50 skipped; FAILED list identical to `fail_56.txt` |
| A2C | 0 / 220 |
| A1 | 0 / 446 |

Earlier probes, one test per process:
- c24, c24b, c25 and c26 all pass.
- `probe_pr55_c26a_value_leak.py`: **LEAKS: none**. The dispatch response has no money keys for the Warehousekeeper. **C26A-1 is FIXED (PROVED).**

### C26B-1 (HIGH, blocking) — Р27 bypass through `subproject_id`; фира charged to the wrong project — PROVED

Probe: `docs/audit/probes/pr55/test_probe_pr55_c26b_subproject.py`, real Mongo, production CommandService and Р27 policy.

Setup:
- The Technician is an in-date member of PROJECT only.
- 5 units are accepted into subproject `sp-of-other-project`, which belongs to OTHER_PROJECT.

Request: `POST /project-writeoff` with `{project_id: PROJECT, subproject_id: "sp-of-other-project", qty: 2}`.

Result:
- **201**.
- Stock in OTHER_PROJECT's subproject goes from 5 to 3.
- PROJECT's cost now shows `waste_cost 20` (фира, `pkg-c22`), on material that PROJECT never held. PROJECT's own stock is untouched.
- OTHER_PROJECT keeps accepted cost 50 with no waste line, so its 2 units vanish without a cost line.

Cause:
- `warehouse_canonical.py:371-372` takes the source from `body.subproject_id`, but Р27 is decided on `body.project_id` (`_r27_decide`, and `service.py:668-670`).
- `_bind_write_off_project` (`service.py:1622-1626`) only requires that *some* `project_id` is present for a SUBPROJECT source. It never checks that the subproject's parent is that project.
- `projections._project_of` (`projections.py:441`) then trusts the body's project as the subproject's owner.

Same root cause, pre-existing (suspicion, not separately probed):
- The generic `POST /movements` WRITE_OFF has the same hole.
- An acceptance into a SUBPROJECT target accepts any `project_id` (`service.py:1571-1575`).

Self-correction: the hole was already present at C26A `189e8e5`, which I passed. My probes there covered only PROJECT sources.

Fix direction: resolve the subproject server-side in the tenant (`projects` row with parent == `project_id`, or the subproject bucket's recorded project) and refuse a mismatch before Р27 and before any write.

Not blocking:
- `project_input_vat` falls back to the full VAT when any allocation has `qty=None`. That seems reasonable; no probe.

Merge-tree, `64418eb` against each:

| Against | Result |
|---|---|
| main | clean |
| #67 | clean |
| #70 PAY-01 | `31ed258` | **PASS** (D5-R1/R2 fixed by locks; FG-50 422); IDEM-IDX-1 resolved once #72 is merged (proved on a scratch merge) | 2026-11-07 |
| #71 SEC-02 | `e90aa5f` | **FINDINGS: SEC71-05 BLOCKING** (`evaluate.resolved_events` + an auto_resolve rule → pay 6196.90 / 6200); SEC71-04 closed | 2026-11-07 |
| #56 | conflict: data_access.py, A2B inventory |
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |


## #70 PAY-01-C01 @ `8910939` — 2026-11-06 ~21:05 UTC — PASS

Delta from `61d45d3`:
- `strict_number` on the Pydantic `amount` fields of `PaymentCreate` and `AllocationInput`;
- `positive_amount` accepts only JSON numbers;
- the reason filter refuses the Unicode categories Cc, Cf, Zl, Zp and Cs.

Gates, real Mongo:

| Gate | Result |
|---|---|
| `tests/test_pay_01*.py` | **244 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same FAILED list as `fail_56.txt` |
| A2C | 0/206 |
| A1 | 0/418 |

Probe results (PROVED):
- `probe_pay01.py` Q1–Q8: FAILS none.
- `probe_pay01_c01.py`, amounts:
  - tested on all 7 money routes (payments, transfers, account-funding, other-expense, other-income, invoice quick-pay, allocate);
  - hostile amounts `{nan, inf, -inf, 1e309, "", -1, 0, true, "abc"}` all get 4xx and write 0 rows; a valid 12.5 gets 201/200;
  - **L1 closed:** `true` is now refused on the typed routes.
- `probe_pay01_c01.py`, reasons:
  - 500 characters → 200; 501 → 400;
  - ZWSP, RLO, NUL, ESC → 400;
  - soft hyphen, tag U+E0041 and U+2028 → 400 now. **L2 closed.**

Frontend regression check: strings are now refused, so I checked every frontend caller of these routes. InvoiceEditor, Payments, Invoices and FinancialAccounts all send `parseFloat(...)` or an API number, so nothing breaks.

Info, not a finding: these visually blank characters are still accepted in a reason, which the package does not require:
- U+3164 Hangul filler;
- U+2800 braille blank;
- U+034F combining grapheme joiner;
- U+FE0F variation selector;
- NBSP and U+3000.

INT-70x69: scratch merge of `8910939` with `07faab5`, clean. `probe_pay01_x_sec01_c02.py` gives the same result as before:
- reversing the ledger row returns 200 and the account balance goes to 0;
- but the `subcontractor_payments` row stays `completed`, and the package keeps `paid_total` 300.
- This is still OPEN (HIGH) and planned for PAY-01 Part 2.


## #67 ST-02-C03 @ `675faba` — 2026-11-06 ~21:10 UTC — PASS (1 low finding)

Delta:
- `release_build.py --flag-override` (non-production only) records the staging `PERMISSION_SERVICE_MODE` in the manifest's `feature_flags`.
- The validator rejects a deployment-parameter source in production.
- `staging_deploy.sh` no longer maps the expectation. Its precheck requires that the manifest of the target **and** of the rollback target equals the staging parameter. After the smoke, the backend must equal both the parameter and the manifest.
- New rehearsal step 2b is a negative control.

Gates:

| Gate | Result |
|---|---|
| `ops/release/tests` | **81 passed / 1 skipped** |
| `test_st_02_staging_stack.py` | **162 passed** in 3 of 5 runs; 159 passed + 3 errors in 2 of 5 (see L1) |
| R0 | 814 passed on re-run; first run 1 failed / 813 passed — the same unreproduced flake pattern as on #70 |
| W0 | 1085/15/50, same FAILED list as `fail_56.txt` |
| A2C | 0/204 |
| A1 | 0/414 |
| `probe_st02_isolation.py <wt67>` | MISSED none |

Rehearsal: NOT re-run by me. I read the evidence `docs/evidence/ST-02/rehearsal-2026-11-06-c03/summary.json`:
- result PASS, 45/45 checks;
- the X bundle's `feature_flags` has PERMISSION_SERVICE_MODE `expected: shadow` and `source: deployment parameter (staging): R15 staging default; layout default off`;
- `rehearse.log` shows the R26 precheck lines.

**ST02-C03-L1 (low, test-only) — PROVED flaky.** In the fixture `r26_bundles` (`test_st_02_staging_stack.py:759`), two bundles of the same commit are built in the same second. `release_id` has one-second resolution (`rel-<YYYYMMDDTHHMMSSZ>-<sha12>`), so the second build fails with `bundle directory already exists`.
- The 3 C03 tests then error at setup.
- In production use the build fails closed, so this is benign there. It is a flaky gate, not a defect.

Note (info): the precheck also requires the **rollback target's** manifest to record the staging mode. A staging deployed with a pre-C03 bundle (expected = layout default `off`) running shadow will therefore refuse every deploy until it is re-initialised. This is fine if no real staging exists yet; it is a rollout note for Krum.

Answer to @parent's #55 contract question:
- At #55 `64418eb`, canonical writes are enforce-only: `routes/warehouse_canonical.py` `post_project_writeoff` returns 503 `CANONICAL_WRITES_REQUIRE_ENFORCE` in off/shadow (code read), and `CommandService.execute` refuses without enforce.
- So a shadow staging (R15 default, recorded by R26) can hold **no canonical stock**. Any warehouse rehearsal on staging needs an explicit `--permission-mode enforce`.


## #71 SEC-02 @ `6080165` — 2026-11-06 ~21:35 UTC — FINDINGS (1 blocking for completeness)

Base: stacked on #69 @ `471eaaa`. #69 is now `07faab5`, so the merge-tree conflicts with #69 (full_cost, labor_smr, reports, subcontractors, PM-01 matrix). **A rebase onto C03 is needed.** Conflicts with #55 (catalog, procurement, sales, DashboardLayout). Clean with main, #56, #67 and #70.

Gates, real Mongo:

| Gate | Result |
|---|---|
| `test_sec_02_finance_read.py` (incl. the fresh real-Mongo two-tenant harness) + `test_sec_01_*` + `test_pm_01` | **43 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same FAILED list as `fail_56.txt` |
| A2C | 0/206 |
| A1 | 0/418 |
| sec01 siblings + r16 probes | FAILS none |

The registry (87 routes), with my checks on the points @parent asked for:

- **FG-12 part 1: PROVED it holds.**
  - R20-1/R20-2 are decided at **company** scope (`require_finance_read` = `require_money_write`). `money_values_visible` is also company scope.
  - My decision probes, on top of the PR's own `_decide`:

    | Assignments | Request | Result |
    |---|---|---|
    | Viewer company + project-scope *accountant* on P1 | `project_profit` at company scope | **False** |
    | same | `money_values` | **False** |
    | Technician company + project mirror with explicit `money_values` | `money_values` | False |
    | project_manager / procurement company | money | False |

  - A project-scope accountant or explicit permission on a project returns True only for project-scope evaluation, which the R20 routes do not use.
  - Deny-overrides is open, declared as D5.
- **Expired membership:** a SiteManager mirror with `valid_to` in the past gets budget P1 → **False**. The harness covers expired and future dated memberships on P2.
- **SiteManager R20-2B:**
  - `expected-actual` removes group/location `planned_cost`/`actual_cost`/`variance_cost`/`status` (client-price sums).
  - The summary totals come from activities (`labor_budget` and session labor cost), not from client prices (`services/expected_actual.py:147-150`). OK.
  - Info: activity `planned_cost / planned_hours` gives the project's average hourly rate. This is inherent to the "budget + spent" view Krum chose.
- **Labor (FG-1/FG-15):** `GET`/`POST /labor-entries` strip `hourly_rate`/`labor_cost` for non-finance roles, and the list is limited to current-member projects. OK.

### SEC02-1 (HIGH, blocking for completeness) — money GETs outside the registry, NOT in the declared debt — PROVED

Probe: `docs/audit/probes/sec02/probe_sec02_unregistered_money_gets.py`.
- It reuses the SEC-02 harness seed, then calls every GET route not in the registry as a **non-member Warehousekeeper** and as a member Viewer, in **off and enforce**.
- Raw output: `docs/audit/probes/sec02/scan_6080165.json`.

Undeclared (not in D1/D3/D4); all return 200 with money to the **non-member Warehousekeeper in enforce**:
- `GET /api/work-sessions` — `items[].labor_cost` (each worker's pay, FLOW-037 §3.4 / FLOW-010). The same data SEC-02 strips from `/labor-entries`, so the FG-15 goal is not met.
- `GET /api/work-sessions/summary` (`total_cost`), `GET /api/work-sessions/overtime` (`workers[].total_cost`).
- `GET /api/projects/{id}/site-workers` — `workers[].total_earned`, to a non-member.
- `GET /api/projects/{id}/smr-groups` and `/smr-groups/tree` — `summary.total_cost` and `grand_total.total_cost` (group sums of the analysis lines, i.e. client prices per the PR's own D6 note), plus `labor_price_per_unit`. D1 names `/api/smr-analyses`, not these.
- `GET /api/pulse/today`, `GET /api/sites/{id}/pulse`, `/pulse/range` — `budget_snapshot.total_budget`, to a non-member.
- `GET /api/ocr-invoice` — `items[].reviewed_data.total_amount` (supplier invoice amounts).
- Minor: `GET /api/subscription` `plan_price`. `/api/billing/subscription` is guarded as R20-1, but this sibling is not.

Declared (D1/D3/D4) and seen by the scan: `/api/ai-config/hourly-rates`, `/api/smr-analyses`, `/api/warehouse/batches` (`unit_cost`, D3), and the Viewer-member activity budgets / activities-overview / budget-health (D4).

Noise (not money): `/api/billing/plans` (public plan prices), `/api/organization` `vat_percent`, `/invoice-context` `default_vat_rate`.

Recommendation: add the undeclared routes to Addendum A (D1), or record them as debt with Krum's decision.


## main @ `8e3b190` — 2026-11-06

PR #68 (PM-01) was merged; I had audited `4e20084` as PASS. No action needed.

## #55 5C-C26d @ `103ecdc` — 2026-11-06 ~22:00 UTC — PASS (1 low finding)

Delta:
- `resolve_subproject_parent` reads the tenant's `projects.parent_project_id`.
- `_bind_subproject_parent` runs in `execute` before the gate. A mismatched `project_id` → 422 before the gate and the write. The project-writeoff route checks the same before Р27.
- `_sees_values` uses the legacy role in off/shadow (FG-39).

Gates, real Mongo:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **389 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same FAILED list as `fail_56.txt` |
| A2C | 0/220 |
| A1 | 0/446 |

Probes, one test per process, all pass: c24, c24b, c25, c26, c26b (updated to seed the subproject row) and the new c26d.

**C26B-1: CLOSED, PROVED.** In `test_probe_pr55_c26b_subproject.py`, a member of P1 writing off with `subproject_id` = a subproject of P2 now gets 422 (it was 201 at `64418eb`).

`probe_pr55_c26a_value_leak.py` in enforce, off and shadow: LEAKS none for the Warehousekeeper (FG-39).

New probe `test_probe_pr55_c26d_transfers.py`:

| Case | Result |
|---|---|
| D2: subproject of P1 → subproject of P2 | OK; the gate is asked for project P1 + location S1 + location S2 |
| D3 baseline: P1 → P2 (project) | cost P1 80 / P2 20, sum 100 |
| D4: P1 → subproject of P2, no `project_id` | OK; cost P1 80 / P2 20, sum 100 (value conserved). The transfer row records `project_id = P2` (the target's parent) |
| D1: P1 → subproject of P2 **with `project_id = P1`** | **422** "project_id must be the parent project of the subproject" |

- **C26D-L1 (low): PROVED.** For a project→project transfer, `project_id` is the SOURCE project by convention (`return_to_warehouse` / `transfer_to_project` helpers, D3). When the target is a subproject, the binding uses the target's parent instead. Callers following the convention get 422; omitting `project_id` works, so this is an API inconsistency, not a permission hole.
- In D4 the project scope checked by the gate flips to P2, and P1 is checked only as a location. No widening was observed.
- Also: an acceptance into a subproject still requires the body `project_id` (`service.py:1595` runs before the binding). It must equal the parent.

## #71 SEC-02 Addendum A @ `73b72b5` — 2026-11-06 ~22:00 UTC — FINDINGS (SEC02-1 remainder open)

Delta:
- 36 more registry rows (D1).
- `strip_money_for_non_finance` decorator (R20-5M) on mixed GETs (offers and others).
- The employee file without money for a SiteManager (D9): member-project lines only, no payroll or advances, money keys stripped.

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo with the fresh harness | **44 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |

Re-run of `probe_sec02_unregistered_money_gets.py` (raw output `docs/audit/probes/sec02/scan_73b72b5.json`):
- **Closed:** `/api/ai-config/hourly-rates`, `/api/smr-analyses`.
- **Still open** (SEC02-1; Addendum A was committed 21:04, before my comment at ~21:20):
  - `/work-sessions` (+ `/summary`, `/overtime`) `labor_cost`;
  - `/projects/{id}/site-workers` `total_earned`;
  - `/projects/{id}/smr-groups` (+ `/tree`) `total_cost`;
  - the pulse routes' `total_budget`;
  - `/ocr-invoice` `total_amount`;
  - `/subscription` `plan_price`.
- Declared and still present: D3 `/warehouse/batches`, D4 activity budgets for a Viewer member.

Code read, no finding:
- The decorator preserves the signature (+ `_sec02_request`) and requires a `user` kwarg.
- It encodes with `jsonable_encoder` before stripping.
- Handler HTTPExceptions propagate unchanged.


## #70 PAY-01-C01 Addendum A @ `45768f3` — 2026-11-06 ~22:20 UTC — FINDINGS (1 blocking)

Delta: `payment_state.source_module` identifies the owning module of a `finance_payments` row:
- `subcontractor_payment_id` → subcontractor;
- `pay_run_id`, or category "Заплата" → pay_run;
- `advance_id`, or category "Аванс" / "Заем" / "Връщане заем" → hr_advance.

The refusal is a 409 `SOURCE_MODULE_REVERSAL_REQUIRED`:
- on `DELETE /finance/payments/{id}`;
- on `DELETE /finance/invoices/{id}/payments/{alloc}` when the allocation being cancelled is the last active one.

**Field mapping vs the real writers: PROVED it matches.**
- `hr.py:282` (advance/loan: category = "Заем"/"Аванс").
- `hr.py:373` (repay: "Връщане заем").
- `pay_runs.py:1349` (salary upsert: "Заплата").
- `subcontractors.py:535` (#70 base) and `#69 subcontractors.py:589` (C03): both write `subcontractor_payment_id`.
- `PaymentCreate` has no `category` field, so a manual payment cannot spoof a module.
- No other writer of `finance_payments` outside `finance.py`.

Gates:

| Gate | Result |
|---|---|
| `tests/test_pay_01*.py` | **306 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |
| `probe_pay01.py`, `probe_pay01_c01.py` | FAILS none |

New probe `docs/audit/probes/pay01/probe_pay01_c01a_source_module.py`. Rows come from the real hr routes; pay-run and subcontractor rows are inserted with the exact writer field sets.

| Case | Result |
|---|---|
| M1: DELETE of an Аванс / Заем / Връщане заем / Заплата / subcontractor row | **409 SOURCE_MODULE_REVERSAL_REQUIRED**; finance_payments, allocations and audit_events +0 |
| M2: manual payment | 200 |
| M3: cancel a non-last allocation of a module payment | 200 |
| M3/M4: cancel the last allocation, same Idempotency-Key sent twice | 409 / 409, writes +0 |

INT-70x69: scratch merge of `45768f3` with #69 `07faab5`. The FG-27 ledger reversal now returns **409**, so the ledger and the subcontractor module stay consistent: balance -300, `subcontractor_payments` completed, `paid_total` 300. **Mitigated** until the module has its own reversal.

### C01A-1 (MEDIUM-HIGH, blocking, money) — time-of-check/time-of-use: concurrent cancels of a module payment's allocations reverse the payment — PROVED

M5 in the same probe:
- A "Заплата" row has 2 allocations. Both are cancelled concurrently (2 threads).
- Result: **200 / 200**. The payment status becomes **reversed**, with 1 reversal row and 0 active allocations.
- Reproduced on the first attempt.

Cause:
- The FG-45 pre-check (`finance.py:1368-1374`) counts the *other* active allocations **before** the cancel. Each request sees the other allocation still active.
- After its own cancel, `remaining_allocs == 0` → `_reverse_one(...)` (`finance.py:1396-1398`) runs with **no source-module check**.

Effect: the ledger reverses a salary, advance or subcontractor payment that the module still counts as paid. This is the FLOW-006 divergence FG-45 is meant to prevent; it needs two concurrent finance actions, for example a double submit or two tabs.

Fix direction: guard the post-cancel reversal as well. If `source_module(payment)` is set, do not reverse; leave the payment active and unallocated, or refuse atomically. Alternatively, make "last allocation" an atomic decision.


## #70 PAY-01-C01 Addendum B + C01A-1 fix @ `8aac73d` — 2026-11-06 ~22:25 UTC — PASS (1 low finding, 1 integration note)

Delta:
- `670b5b9` (R29): every money write needs an Idempotency-Key, else 428.
- `8aac73d`:
  - the source-module guard moved into `_reverse_one` (it applies to every caller);
  - for a module-owned payment, the "last allocation?" check and the cancel run under `_payment_lock`: a conditional `allocation_lock` on the payment row; a busy lock → 409 `PAYMENT_BUSY`; a lock older than 30 s is taken over; the release is token-guarded.

Gates:

| Gate | Result |
|---|---|
| `tests/test_pay_01*.py` | **444 passed** |
| R0 | **814** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |

New probe `docs/audit/probes/pay01/probe_pay01_r29_keys.py` (PROVED):
- payments, transfers, account-funding, other-expense, other-income, invoice quick-pay and allocate, without a key → **428 IDEMPOTENCY_KEY_REQUIRED, +0 writes**;
- with a key → 201/200; replaying the same key + same body → identical response, +0; same key + other body → 409;
- payment reversal and allocation cancel without a key → 428, +0.

Frontend: every money POST/DELETE (InvoiceEditor, Payments, Invoices, FinancialAccounts) sends `idempotencyHeaders`.

`probe_pay01_c01a_source_module.py` now adds an automatic key to each write, because R29 refuses keyless writes:

| Case | Result |
|---|---|
| M1–M4 | unchanged, all ok |
| **M5 (the C01A-1 race), 5 attempts** | **[200, 409]**; payment stays active, 0 reversal rows, 1 allocation left. **C01A-1 CLOSED (PROVED)** |
| M6: fresh foreign lock (5 s) | 409 `PAYMENT_BUSY`, writes +0, the foreign lock is untouched |
| M6: stale lock (31 s) | taken over, 200; the lock is released afterwards |
| M7: forced takeover race (`PAYMENT_LOCK_STALE_SECONDS = -5`, every lock counts as stale) | see C01A-L1 |

- **C01A-L1 (low): PROVED** only under the forced condition. In M7 the guard in `_reverse_one` held: the payment was never reversed, with 0 reversal rows. But **both** requests answered 409 `SOURCE_MODULE_REVERSAL_REQUIRED` **after** both allocations were cancelled and audited (0 active allocations left).
  - So in a real takeover (a holder stalled for more than 30 s), the caller sees an error although the cancel was written.
  - Its key is never completed, so a retry with the same key replays to the same 409.
  - The ledger stays correct; the payment ends active with no allocations. This is low because it needs a stall of over 30 s.

INT-70x69:
- On the scratch merge with #69 `07faab5`, the ledger reversal is still refused; with no key it now returns 428 first.
- **Integration note:** the merge now has an **add/add conflict in `frontend/src/lib/idempotency.js`** (and its test).
  - #69 exports `createIdempotencyHolder().keyFor(endpoint, payload)`, which keeps the key per payload.
  - #70 exports `createKeyHolder().get()/settle(err)`, which keeps the key only on a network error.
  - These are two different contracts at one path. One must win at merge, and the callers of the other must be ported.
  - The A1 inventory conflicts as well.


## IDEM-IDX-1 (HIGH, blocking, money, cross-PR: main W0-04 + #69 + #70 + #71) — PROVED

The W0-04 idempotency registry (`app/audit/idempotency.py` `begin_idempotent`) does find-then-insert. Its docstring says the key is "reserved atomically via a unique index". **No application code creates that index:**
- not `server.py` startup (which creates `audit_logs` and `organizations` indexes only);
- not tenant provisioning;
- not ST-02 staging.

Only the manual script `scripts/w0_04_bootstrap_audit_indexes.py --apply` creates it, and nothing in `ops/` calls that script. With database-per-tenant, every new tenant database starts without the index.

Proof, real Mongo RS, one Idempotency-Key, 6 concurrent requests:

| PR | Route | Without the index (as the app leaves it) | With `create_index("id", unique=True)` |
|---|---|---|---|
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |
| #70 PAY-01 | `31ed258` | **PASS** (D5-R1/R2 fixed by locks; FG-50 422); IDEM-IDX-1 resolved once #72 is merged (proved on a scratch merge) | 2026-11-07 |
| #72 W0-04-C01 | `04e0a1b` | **PASS** (FG-117: the DB-name marker is clean on 12 paths; leaks on `cb5d061`) | 2026-11-07 |
| #73 LAB-01 | `4da2ee6` | **PASS** (PM73-01 closed; PM-01 real, not skipped) | 2026-11-07 |
| #75 LAB-02 | `ef16a16` | **PASS** (PM75-01 closed; PM-01 real, not skipped) | 2026-11-07 |
| #76 SUB-ADV-01 | `542fa2c` | **PASS** (Addendum A + B: S1–S9 × 3 modes; cap exact) | 2026-11-07 |
| #77 ACT-01 | `8188689` | **PASS** (ACT77-01 fixed; Addendum B confirm / price / visibility checks pass) | 2026-11-07 |
| #74 OH-01 | `45178ac` | **PASS** (OH74-05 closed: O16 and new O17 pass; FG-89 one source; #69 `3fb55f2` merge R0 6/6 = 814) | 2026-11-07 |

- **Self-correction:** my #69 C03 PASS (P1c "6 concurrent → +1") was a single lucky run. The same probe on `07faab5` gives +3 in 2 of 3 runs. The suspected "merge regression" on #71 was this flake.
- **Not verified:** whether production databases already have the index (someone may have run the script by hand). I have no production access.
- **Fix direction:**
  - the app creates the `audit_idempotency.id` unique index (and the `audit_events` unique indexes) idempotently at startup and when a tenant database is provisioned;
  - add a test that starts from a database with no indexes;
  - the main debt "W0-04 `record_event` concurrency loses AuditEvents" probably has the same root cause (the `(tenant_id, sequence)` unique index is also script-only). That part is a suspicion.

## #70 PAY-01-C01 D5 @ `42bbdfc` — 2026-11-06 ~22:50 UTC — FINDINGS (IDEM-IDX-1; D5-R pre-existing)

Delta (D5):
- every allocate item is validated before the first write (cumulatively per invoice);
- uuid5 allocation ids per (tenant, payment, key, index), written with an upsert;
- the "remaining" amounts are computed from active allocations, excluding this key's own rows.

Gates:

| Gate | Result |
|---|---|
| `tests/test_pay_01*.py` | **462 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |

R0: 814 on `8aac73d`. Not re-run on `42bbdfc`, because the delta is `finance.py` allocate only.

Probes on `42bbdfc`:
- `probe_pay01_c01a_source_module.py`: M1–M7 unchanged. M5 [200, 409], payment active (**C01A-1 still closed**). M7 same as C01A-L1.
- `probe_pay01_r29_keys.py`: FAILS none.

**D5-R1/R2 (HIGH, money, PRE-EXISTING on main `8e3b190`, not a regression): PROVED** with `probe_pay01_d5_race.py`.
- R1: two concurrent allocates with *different* keys on a payment of 100 (80 each) → 200/200, **160 allocated on a 100 payment**, in 5/5 runs.
- R2: two payments of 800 allocated concurrently to one invoice of total 1200 → 200/200, **1600 allocated on a 1200 invoice**, in 5/5 runs.
- main gives the same result.
- Validation reads a snapshot, and nothing serialises allocates on the same payment or invoice. The `_payment_lock` from C01A-1 is used only on the module-owned cancel path.
- Recommendation: put allocate under the payment lock (and an invoice lock), or use conditional `$inc` counters. This is for Krum/orchestrator to decide whether it is in D5 scope.

## #71 SEC-02-B @ `ba29dac` (merges #69 `07faab5`) — 2026-11-06 ~22:50 UTC — PASS (IDEM-IDX-1 inherited)

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **51 passed** on re-run; the first run had 1 failure that did not reproduce, and it was killed by a worker restart before I could read which test |
| R0 | **814** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/207 |
| A1 | 0/420 |

Probes:
- **SEC02-1 CLOSED (PROVED):** `probe_sec02_unregistered_money_gets.py` → `docs/audit/probes/sec02/scan_ba29dac.json`.
  - Only non-money noise is left: `/billing/plans` public prices, `/organization` `vat_percent`, `/invoice-context` `default_vat_rate`.
  - All of these are gone: work-sessions (+ summary/overtime), site-workers, smr-groups (+ tree), the pulse routes, ocr-invoice, subscription, warehouse/batches, activity budgets / budget-health / activities-overview, labor-warnings.
- **FG-15 replay strip (PROVED),** `sec02/probe_sec02_fg15_replay.py`, in off and enforce:
  - a member Technician POSTs `/labor-entries` twice with one key → 201/201, one row;
  - neither the first response nor the replay has `hourly_rate`/`labor_cost`; the stored row keeps both;
  - an Accountant's replay keeps the money.
- **#69 behaviour after the merge:** sec01 siblings, r16 and sitemanager-loss all pass; c02_payments P2 (NaN/Inf → 422) and P3 (404) are unchanged. P1c varies only because of IDEM-IDX-1 (#69 alone shows the same).


## main @ `35ae10b` — 2026-11-06

PR #67 (ST-02) merged. I audited `675faba` as PASS, with the low finding ST02-C03-L1.

## #69 SEC-01-C03 Addendum A (R29) @ `6d43284` — 2026-11-06 ~23:30 UTC — PASS (IDEM-IDX-1 applies)

Delta: `money_input.py` returns 428 when the key is missing.

`probe_sec01_c02_payments.py` (run with `PROBE_CREATE_IDEM_INDEX=1`):
- P1, keyless identical POST twice → **428 / 428, 0 rows**. This is now the intended R29 behaviour; the probe's "P1 duplicate" label is stale.
- P1b: key replay → identical response, +1 row; other body → 409.
- P1c: 6 concurrent requests → +1 row, but only with the index present (IDEM-IDX-1).
- P2: NaN → 422.

Gates:

| Gate | Result |
|---|---|
| `tests/test_sec_01_*` | 30 passed |
| W0 | 1085/15/50 |
| A1 | 0/418 |
| A2C | 0/206 |

## #55 5C-C26e @ `4a3d15c` — 2026-11-06 ~23:20 UTC — FINDINGS (1 blocking)

Delta:
- Р28: canonical warehouse writes work in off and shadow too. The new `legacy_gate.ensure_legacy` maps the legacy role through `LEGACY_ROLE_MAP` to `role_actions`. Project-bound roles need an in-date `project_team` row on every project the command touches. Shadow logs mismatches.
- Р30: a PM's own project = an in-date team row with `role_in_project` "SiteManager".
- C26D-L1: the acceptance binding no longer requires the body `project_id`.

Gates:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **636 passed** (the C26e 243-case matrix is included) |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/221 |
| A1 | 0/448 |
| R0 | 814 on re-run; first run had 1 failure, the same unreproduced flake pattern |

Probes:
- c24, c24b, c25, c26, c26b, c26d: all pass, one test per process.
- **C26D-L1 FIXED:** D1 (P1 → subproject of P2 with `project_id = P1`) is now OK.
- Value leak: LEAKS none in enforce, off and shadow.

**C26E-1 (HIGH, blocking): Р28 decisions differ between modes once the real RoleAssignments are used. PROVED** with `docs/audit/probes/pr55/test_probe_pr55_c26e_real_assignments.py`.
- The product gives a legacy SiteManager a **company-scope** `site_manager` assignment with `permissions: []`. It is created by `sync.py` `grant_company_role`, called from `auth.py:334/380/440/463` and by the W0-02 bootstrap.
- The evaluator reads `role_actions("site_manager")` (accept_delivery, consume_smr, transfer_project_to_*, ...) from it. `_scope_covers("company", …)` covers every project.
- The `project_team` mirror only adds `budget.*`.
- The C26e matrix instead hand-builds **project-scope** SiteManager assignments (`test_warehouse_canonical_c26e_r28_all_modes.py`, ROLES "SiteManager-member/non-member"). Those do not exist in the product.

Result with the real assignment, SiteManager **not** a member of P1:

| Command on P1 | off | enforce |
|---|---|---|
| accept | DENIED (`R28_LEGACY_ROLE_NOT_ALLOWED`) | **ALLOWED** (+2 rows) |
| consume | DENIED | **ALLOWED** (+1 row) |
| return_to_warehouse | DENIED | **ALLOWED** (+1 row) |

- The catalog itself says "project scope is required" for these site_manager actions (`catalog.py:141-142`). So the enforce side is the hole; the legacy gate matches the intent.
- The enforce behaviour predates C26e (TASK 5C), but Р28 ("the same rules in all three modes") is now false, and the test that claims it uses unreal assignments.
- Fix direction:
  - in the enforce gate, require the project relation for project-bound roles, as the legacy gate does; or stop granting company scope for site_manager warehouse actions;
  - rebuild the matrix from assignments produced by the real `grant_company_role` + `sync_project_membership`.
- Info: no legacy role maps to `project_manager` in `LEGACY_ROLE_MAP`, so the Р30 PM path of the legacy gate cannot be reached in off/shadow.

## #71 SEC-02-C @ `f17f7e5` — 2026-11-06 ~23:25 UTC — FINDINGS (1)

Delta:
- R31: SiteManager labor spent per SMR only.
- B-D2: `strip_pulse_for_non_finance` keeps `budget_snapshot`, `smr_summary` and `total_labor_cost` for a member SiteManager on his own site.
- B-D1: Accountant gets `budget.read`.

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **51 passed** |
| R0 | **814** |
| W0 | 1085/15/50 |
| A2C | 0/207 |
| A1 | 0/420 |

Scan `scan_f17f7e5.json`: only the 3 noise routes are left (billing/plans, organization, invoice-context).

**SEC02C-1 (MEDIUM-HIGH): per-worker pay and hourly rate are derivable from the SiteManager pulse budget view. PROVED** with `docs/audit/probes/sec02/probe_sec02_c_pulse_derive.py`.
- Setup: a member SiteManager; one day, two workers on two SMR types.
- `GET /api/sites/{p1}/pulse?date=…` returns:
  - `workers[]` with `worker_id`, `hours` and `smr_types` (money stripped, identity and hours kept);
  - `smr_summary[]` with `total_cost` **and `workers_count`**;
  - `total_labor_cost`.
- Every SMR with `workers_count == 1` gives that worker's pay and rate: worker 1 → 200 / 25 per h, worker 2 → 210 / 35 per h.
- A site with one worker that day also exposes it through `total_labor_cost`.
- This is exactly the FLOW-037 §3.4 / R31 concern @parent asked about.
- Fix direction:
  - drop `workers_count`, or suppress the per-SMR cost where it is fewer than 2 (k-anonymity);
  - or drop `worker_id` + `smr_types` + `hours` from `workers[]` for the budget view;
  - and use multi-day aggregates.


## #72 W0-04-C01 @ `e733c66` — 2026-11-06/07 ~23:50 UTC — PASS

What it does:
- `app/audit/indexes.py` `ensure_audit_indexes` is idempotent and drops or deletes nothing. A conflicting index → `AuditIndexConflict`; existing duplicates → `AuditIndexDuplicates`. It is called by `server.startup` for the operational database plus every database named in the registry, and by `onboard_tenant` before its first write.
- `record_event` retries a `(tenant_id, sequence)` collision from the new head: at most 100 attempts, with jitter.

Probe `docs/audit/probes/w004/probe_w004_c01.py`. Real `server.app` startup (handlers **not** cleared), fresh databases with no indexes. All PROVED:

| Case | Result |
|---|---|
| I1 | startup created the 4 unique indexes in the operational database **and** in the database named in the registry |
| I2 | 6 concurrent `begin_idempotent`, one key → exactly 1 STARTED, 5 duplicate |
| I3 | 50 concurrent `record_event` → 50 stored, sequences 1..50 distinct, `verify_chain` (True, None) |
| I4 | existing non-unique `id_1` → `AuditIndexConflict`, the index is kept |
| I5 | 2 duplicate idempotency rows → `AuditIndexDuplicates`, both rows kept |
| I6 | indexes dropped, then `POST /api/billing/signup` → 200, and onboarding re-created the unique indexes |

**IDEM-IDX-1 is resolved on the merge.**
- On a scratch merge of #70 `31ed258` with #72 `e733c66`, `probe_idem_index_race.py` with `PROBE_RUN_STARTUP_INDEXES=1` (the startup function only, no manual index) gives 6 concurrent `POST /finance/payments` with one key → **+1 row in 4/4 runs**.
- Before #72 the same probe gave up to +6.

**The #56 merge recipe is verified.** Trial merge of `e733c66` with #56 `3234446`, `store.py` resolved as the HANDOFF says (`session` passed through; `if session is not None or not _is_sequence_collision(exc): raise`):
- W0-04 + AUTH-02 + R0-04 tests: 83 passed; R0: 814.
- Probe `w004/probe_w004_x56_tx_race.py`, 3 rounds of 20 transactional (`run_in_transaction`) + 20 plain appends on one tenant: **0 failures**, 120 stored, `verify_chain` True.
- Under transactions the conflict surfaces as a transient write conflict that `with_transaction` retries.

Gates:

| Gate | Result |
|---|---|
| `tests/test_w0_04*` | 47 passed |
| W0 | 1090/15/60, same 15 failures as main (+5 passed, +10 skipped are the new tests) |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |

Merge-tree, `e733c66` against each:

| Against | Result |
|---|---|
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |
| #56 | conflict: `store.py` (recipe above) + the A2B inventory |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |

**Rollout risk (not a code defect; for Krum).** If a production or staging database already has duplicate idempotency rows or `(tenant_id, sequence)` events, which are likely given IDEM-IDX-1 and the `record_event` debt, the **app refuses to start** after deploy, by design. Before deploying, run the dry run `scripts/w0_04_bootstrap_audit_indexes.py` against a copy of the data, as the HANDOFF says.

## #70 PAY-01-C01 Addenda C + D @ `31ed258` — 2026-11-07 ~00:00 UTC — PASS

Delta:
- Addendum C: `_row_lock` (`allocation_lock` field) on the payment and on every invoice, taken in sorted order as a try-lock (409 `PAYMENT_BUSY` / `INVOICE_BUSY`), for allocate and quick-pay.
- Addendum D (FG-50): `_require_tenant_project` on other-expense/income.

Probes:

| Probe | Result |
|---|---|
| `probe_pay01_d5_race.py` R1 | 2 × 80 on a payment of 100 → [200, 409], 80 allocated, in 5/5 runs. **D5-R1 FIXED** |
| `probe_pay01_d5_race.py` R2 | 2 × 800 on an invoice of 1200 → [200, 409], 800 allocated, in 5/5 runs. **D5-R2 FIXED** |
| `probe_pay01_fg50.py` | nonexistent, tenant B's and non-string `project_id` → 422, +0, on both routes; own project → 201. **FG-50 PROVED** |
| `probe_pay01_c01a_source_module.py` | M5 [200, 409] (C01A-1 still closed); FAILS none |
| `probe_pay01_r29_keys.py` | FAILS none |

Gates:

| Gate | Result |
|---|---|
| `tests/test_pay_01*.py` | **510 passed** |
| R0 | 814 |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |

Info:
- `allocation_lock` is a transient field written onto invoice and payment rows. A crash leaves it for up to 30 s (stale takeover).
- List endpoints may show it; it is cosmetic.


## #73 LAB-01 @ `709815d` — 2026-11-07 ~00:20 UTC — PASS (notes + merge risk)

Delta:
- New `app/services/labor_cost.py`: `compute_person_labor` and `project_labor_cost`.
- Consumers moved onto it: Pay Run, the labor sync (Approved work_reports only), expected-actual "spent", activity budgets, P&L, all-reports.

Probe `docs/audit/probes/lab01/probe_lab01.py`. Real `server.app` and `GET /pay-runs/generate`; report rows use the employee_daily_reports fields the normalizer reads. All PROVED:

| Case | Result |
|---|---|
| L1 FG-48 | akord line, approved 120 m² × 5, at 40 h → **600**; the same line at 10 h → **600**. Hours never price akord |
| L3 | Hourly profile with no rate → 0 + `MISSING_RATE` (no default 25) |
| L4 FG-51 | Daily 120: 3 approved days → Pay Run earned **360**; the SUBMITTED day is excluded |
| L5 | a DOWNTIME line on P1 is its own line: labor 180 + downtime 120 |
| L6 | Pay Run earned 360.0 == spent P1 300.0 + P2 60.0. **Pay Run == "spent"** for the same person and period |

Code read:
- Confirmed or paid runs: PATCH is refused (`pay_runs.py:1431`, status must be draft/reopened); the stored fields are frozen.
- A reopened run is recalculated only on an explicit PATCH, with `labor_recalc` history. This is declared.

Gates:

| Gate | Result |
|---|---|
| `tests/test_lab_01*` | 18 passed |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |

**LAB01-N1 (HIGH business impact; declared debt, canon-correct): PROVED.**
- Nothing in the repository writes `approved_quantity`, `piece_rate` or line `pay_type`. The daily_reports writer stores only `hours_worked`, and nothing writes the package fields `labor_pay_type` / `labor_piece_rate` either.
- So **every akord line in production prices to 0** + `AKORD_NO_APPROVED_QUANTITY`. Probe L2: Akord profile, 8 h, no quantity → total 0.0.
- Before LAB-01, akord paid hours × hourly_rate.
- FG-49 (pay type from the SMR line/package) is also effectively always the profile fallback, for the same reason.
- Krum must decide whether LAB-01 may ship before the quantity-approval flow exists.

**LAB01-M1 (merge risk, HIGH): the HANDOFF merge notes are incomplete.** merge-tree of `709815d` against each:

| Against | Result |
|---|---|
| #71 SEC-02 | `dee0610` | **PASS** (FG-74 only paid workers count for R31; FG-75 price-modifier PUT audited) | 2026-11-07 |
| #69 SEC-01 | `7300864` | **PASS** (addendum B: FG-15 replay strip, FG-47 strict numbers, FG-29 project in tenant) | 2026-11-07 |
| #70 `31ed258` | conflict: `project_pnl.py` |
| #55 5C | `f0d86ab` | **PASS** (FG-70 accept lands on the addressed project; FG-69 subproject denial shape) | 2026-11-07 |

- The HANDOFF names `expected_actual` / `activity_budgets` / `project_pnl` / `all_reports` with respect to #71 only.
- It does not mention that `labor_smr.py` `sync-from-work-reports` was rewritten by both #69 and #73:
  - #69 (FG-26) replaced `delete_many` with reversal rows and added the R16 guard + MoneyWrite;
  - #73, branched from main, keeps `delete_many` (`labor_smr.py:126`) and has no SEC guard.
- A merge that takes #73's version would bring back the hard delete of synced labor rows (CLAUDE.md §2.9) and drop the R16 guard.
- The LAB-01 pricing must be ported into #69's reversal-based sync.


## #55 5C-C26f @ `3777d71` — 2026-11-07 ~00:30 UTC — FINDINGS (1)

Delta:
- `ensure_project_relation`: one rule in both modes. When only project-bound roles grant the action, an in-date `project_team` row is needed on every project **touched**. Enforce: `ensure_enforce_project_relation` runs after the scope gate.
- The C26e rule "no warehouse location for project-bound roles" is dropped.
- F-16: the canonical GETs go through `_legacy_read` / `_read_project_relation`.
- R32: `WAREHOUSE_VALUE_ROLES = {"warehouse"}` sees warehouse values.
- FG-53: a move from a project bucket binds `project_id` to the source.
- FG-55: no `parent_project_id` in 422 contexts.

Gates:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **713 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/221 |
| A1 | 0/448 |
| R0 | 814 |

Probes:
- c24, c24b, c25, c26, c26b, c26d: all pass.
- **C26E-1 CLOSED (PROVED),** `test_probe_pr55_c26e_real_assignments.py` with the real company-scope `site_manager` grant: non-member accept / consume / return → **DENIED `R28_PROJECT_RELATION_REQUIRED` in off AND enforce**.
- **R32,** `probe_pr55_c26a_value_leak.py` in enforce and off, as the Warehousekeeper:
  - stock (`total_value`, `layers.unit_value`), history (`rows.unit_value`) and the dispatch response (`unit_value`, `layer_allocations`) now show values. That is intended under R32; the probe's "LEAKS" label now reflects R32, not a defect.
  - **integrity-warnings stay hidden** (`values_hidden=True`).
  - Open question for Krum: history and stock rows of *project* buckets (consumption and фира values) are also visible to the keeper. Is that "project finance" under R32?

**C26F-1 (MEDIUM-HIGH): dropping the location rule opens warehouse-only commands to any SiteManager. PROVED** with `docs/audit/probes/pr55/test_probe_pr55_c26f_warehouse_only.py`.
- Setup: the real company-scope `site_manager` grant, member of **no** project.

| Command | off | enforce |
|---|---|---|
| `quarantine_entry` at the central warehouse (WH free → WH quarantine) | **ALLOWED** (+1 row) | **ALLOWED** (+1 row) |
| accept of a warehouse → warehouse transfer (`accept_delivery` into WH_B) | **ALLOWED** (+1 row) | **ALLOWED** (+1 row) |

- Cause: the `site_manager` catalog holds `warehouse.quarantine_entry` and `warehouse.accept_delivery`. `ensure_project_relation` checks only the projects a command touches. A warehouse-only command touches none, so no relation is required.
- At `4a3d15c` (C26e), off denied these ("location outside the role's project scope"); enforce already allowed them through the company scope.
- So C26f now makes the two modes agree on the **wider** answer: a site role can quarantine central stock and take custody of an inter-warehouse transfer (FLOW-009 / CLAUDE.md §16).
- Fix direction: for project-bound granting roles, require that the command touches at least one project, and the relation on all of them. In other words, keep the C26e location rule, in both modes.


## #71 SEC-02-D @ `e6ea838` (merges #69 `6d43284`) — 2026-11-07 ~00:40 UTC — FINDINGS (1)

Delta: the R31 view strips per-worker identity and hours. Spent is shown only with 2+ workers, per SMR and at project level. FG-52 (428).

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **53 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/207 |
| A1 | 0/420 |
| R0 | **814** |

Scan `scan_e6ea838.json`: only the 3 noise routes.

**SEC02C-1 CLOSED (PROVED).** `probe_sec02_c_pulse_derive.py`:
- two workers on two SMR types → the SiteManager sees `workers` = null and `smr_summary` with hours only, so nothing can be derived;
- `PROBE_SINGLE=1` (one worker) → `total_labor_cost` is hidden.
- With `probe_sec02_d_pulse_generate.py` (B): cumulative `budget_snapshot.total_spent` is hidden on single-worker days (None), so differencing across days gives nothing.
- Residual (info, inherent to R31): a SiteManager who approves the reports knows each worker's hours. Daily project totals with 2+ workers, combined with known hours over several days, form a linear system that can recover rates. This is for Krum, not a code defect.

**SEC02D-1 (HIGH, money/privacy; pre-existing on main `pulse.py:46`, outside my GET-only scanner): PROVED** with `docs/audit/probes/sec02/probe_sec02_d_pulse_generate.py` (A), in off and enforce:
- `POST /api/sites/{id}/pulse/generate` needs only `get_current_user` and has **no money strip**.
- A **non-member Warehousekeeper** and a **Viewer** get 200 with `workers[].labor_cost` [200.0], `total_labor_cost` 200 and `budget_snapshot.total_spent` 200, i.e. each worker's pay.
- It also lets any user write (regenerate) a stored pulse.
- Fix direction: put the generate route behind a role guard (finance or member SiteManager) and the same `strip_pulse_for_non_finance` view; or make it return nothing but an id.
- Suggestion: extend the money scan to POST compute/generate routes. My scanner covers GETs only.


## #55 5C-C26g @ `81e412c` — 2026-11-07 ~00:50 UTC — PASS

Delta: `ensure_project_relation` refuses `R28_PROJECT_REQUIRED` when only project-bound roles grant the action and the command touches no project, in every mode.

Probes, with the real company-scope `site_manager` grant, member of nothing:

| Probe | Result |
|---|---|
| `test_probe_pr55_c26f_warehouse_only.py` | `quarantine_entry` at WH and accept of a W→W transfer → **DENIED `R28_PROJECT_REQUIRED` in off AND enforce**. **C26F-1 CLOSED (PROVED)** |
| `test_probe_pr55_c26e_real_assignments.py` | non-member accept / consume / return → DENIED `R28_PROJECT_RELATION_REQUIRED` in both modes; C26E-1 stays closed |
| c24, c24b, c25, c26, c26b, c26d | all pass, one test per process |

Gates:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **725 passed** (the member SiteManager's legitimate commands in the C26e matrix still pass) |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/221 |
| A1 | 0/448 |
| R0 | 814 |

Still open, for Krum: the R32 question about project-bucket values shown to the keeper. Not a defect.

## #69 SEC-01-C03 Addendum B @ `7300864` — 2026-11-07 ~00:55 UTC — PASS

Delta:
- FG-47: `money_value` = PR #70's `positive_amount`, so only JSON numbers are accepted.
- FG-29: `project_in_tenant` on labor and material waste (422 when missing, 404 for another tenant's project).
- FG-15: `labor_money_visible` strips the labor rate and cost from the response and from a replay.
- The price_modifiers and subcontractors tweaks are small.

Frontend check for FG-47 (numeric strings are now refused): the only callers are `MaterialWastePanel.js` (`qty: parseFloat`) and `ProjectOperationsPage.js` (`amount: Number(...)` / `parseFloat`). Both send numbers, so there is no regression.

Probes:
- `probe_sec01_c02_payments.py` (with the index): P1b key replay → identical response, +1, other body → 409; P1c → +1; P2 NaN → 422; P3 → 404.
- siblings: FAILS none.
- r16: updated to send an Idempotency-Key per write (R29 refuses keyless writes) → FAILS none. Before the update it reported 428s, which were only the stale probe.

Gates:

| Gate | Result |
|---|---|
| `tests/test_sec_01_*` | 30 passed |
| W0 | 1085/15/50 |
| A1 | 0/420 |
| A2C | 0/207 |


## #71 SEC-02-E @ `b37909f` — 2026-11-07 ~01:35 UTC — PASS

Delta:
- `pulse/generate` is guarded and stripped; `generate-all` is finance-only; stored pulses keep budget and status only.
- 18 POST/PUT routes added to the registry, plus the PR's own POST/PUT scan.

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **55 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/207 |
| A1 | 0/420 |
| R0 | **814** |

**SEC02D-1 CLOSED (PROVED).** `probe_sec02_d_pulse_generate.py`, off and enforce:
- the non-member Warehousekeeper and the Viewer get **403** on `POST /sites/{id}/pulse/generate`, with no `labor_cost`;
- the SiteManager's range shows no cumulative `total_spent`.

My own sweep: `probe_sec02_unregistered_money_gets.py` with `PROBE_METHOD=POST` and `PUT` (a new switch). Every unregistered POST/PUT route was called with an empty body as a non-member Warehousekeeper and as a member Viewer, off and enforce → **0 money hits**.
- Limitation: an empty body is refused with 422 by most routes, so this corroborates the PR's own scan but does not prove the absence of a leak.

Note: E-D1 (the keeper enters a unit price) is intended under R32, per @parent.


## #55 5C-C26h @ `518aab4` — 2026-11-07 ~02:00 UTC — PASS

Delta:
- FG-59/61: the projects touched come from DB-resolved locations; a body `project_id` must name one, except for dispatch, reserve and release.
- FG-55: rights are decided before a binding error. A caller who is not allowed gets the same 403, and the denial names only what the caller sent.
- FG-60: member-scoped reads — `_member_scope` / `_within_member_scope`; balance and history are filtered to member projects.

Probes:
- New `test_probe_pr55_c26h_reads.py`, a SiteManager member of P1 only, real company grant:

| Read | off | enforce |
|---|---|---|
| unfiltered history | only P1 rows (`p-c22`) | only P1 rows (`p-c22`) |
| history with `project_id = P2` | **403** | **403** |
| history with `location = WH` | **403** | **403** |
| balance | no P2 locations | no P2 locations |

- c26e_real (DENIED, relation required), c26f_warehouse_only (DENIED, project required), and c24, c24b, c25, c26, c26b, c26d: all pass.

Gates:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **746 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/221 |
| A1 | 0/448 |
| R0 | 814 |

Note (code read, low): history is narrowed **after** `limit` / `cursor`, so a member page can be short or empty while `next_cursor` advances. This is a UX point, not a leak.

## #72 W0-04-C01 FG-57 @ `009ac1d` — 2026-11-07 ~02:05 UTC — PASS (2 notes)

Delta: `record_event` → `_require_chain_index`. If the unique `(tenant_id, sequence)` index is missing, it creates exactly that index; a conflict, duplicates or an error → `AuditChainUnprotected`, and nothing is appended. A positive result is cached per (client, database).

Probe `docs/audit/probes/w004/probe_w004_fg57.py`. All PROVED:

| Case | Result |
|---|---|
| G1 | database with **no** indexes, 30 concurrent `record_event` → index created lazily, 30 stored, sequences 1..30, chain True |
| G2 | non-unique `(tenant_id, sequence)` index → `AuditChainUnprotected`, 0 appended |
| G3 | an existing fork (2 rows with sequence 1) → `AuditChainUnprotected`, both rows kept |

`probe_w004_c01.py` I1–I6 still pass.

Gates:

| Gate | Result |
|---|---|
| `tests/test_w0_04*` | 52 passed |
| W0 | 1092/15/63, same 15 failures |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |

**On the deviation from a pure refusal (asked by @parent):** creating the planned index lazily is acceptable.
- It is the same index startup and onboarding create, and it drops or deletes nothing.
- On a conflict or a fork it still refuses.
- The result is the same safety (no fork) without blocking a database that only missed startup.

Notes, not blocking:
- **(a) No symmetric guard for idempotency.** `begin_idempotent` has no equivalent guard. Probe G4: a database that missed startup and onboarding still gives **6/6 STARTED** for one key. A tenant database that enters the registry after startup without onboarding (migration or backfill provisioning) stays unprotected until the next restart. Suggestion: the same lazy guard for `audit_idempotency` (`id` and `(tenant_id, action, key)`).
- **(b) After the #56 merge:** `record_event(session=...)` will call `_require_chain_index` without the session. If the index is ever missing, `create_index` runs while the caller's transaction is open on the same collection, which may block until the transaction times out. This is rare, because startup creates the index. Run the index check before opening the transaction, or note it in the merge recipe.

## #73 LAB-01-B @ `fa3e23a` — 2026-11-07 ~02:10 UTC — FINDINGS (1, latent)

Delta:
- FG-64: `line.pay_type`, `line.piece_rate` and `line.approved_quantity` are ignored.
  - The pay type and piece rate come only from the package (`execution_packages.labor_pay_type` / `labor_piece_rate`), restricted to the line's own project.
  - The quantity comes only from `labor_quantity_approvals` with status approved, `approved_by` set, and approver ≠ worker.
- FG-66: remaining is never negative; the excess becomes a `FLOW028_CORRECTION` item.

Probes and gates:
- `probe_lab01.py`: L1 updated to package + approval terms → 600 at 40 h and at 10 h. The old L1 relied on line fields, which are now ignored by design. L3, L4, L5 and L6 still pass (Pay Run == spent: 360 == 300 + 60).
- `tests/test_lab_01*`: 22 passed.
- W0: 1085/15/50; A2C 0; A1 0; R0 814.

**LAB01B-1 (MEDIUM-HIGH, latent): the worker still picks the package that prices the line. PROVED** at function level (production `compute_person_labor` and `load_smr_terms` shapes) with `docs/audit/probes/lab01/probe_lab01b_package_pointer.py`.
- `_package()` uses the approval record's `execution_package_id`, **else `line.execution_package_id`**. Only a package of another project is refused.
- `PUT /daily-reports/{id}` stores `day_entries` dicts unvalidated (`daily_reports.py:252-264`; FG-64 itself says so). The normalizer passes `execution_package_id` through, so the worker sets it on a DRAFT, and approval does not reset it.

Results:

| Case | no package | package A (Hourly) | package B (Daily) |
|---|---|---|---|
| P1 time work: profile Monthly 1100/22 = 50 per day, 12 h | **50** | **180** | **120** |

| Case | package C (piece 2) | package D (piece 9) |
|---|---|---|
| P2 akord: approval record with qty 100 but no `execution_package_id` | **200** | **900** |

- Latent: nothing writes `labor_pay_type` / `labor_piece_rate` on packages yet, so it is not exploitable today. It becomes exploitable once packages carry terms (FG-65 / quantity approval).
- Fix direction:
  - take the pricing package only from the approver-written approval record (require `execution_package_id` there);
  - for time work, ignore package pay types not set by the approver, or validate `day_entries` against the SMR assignment;
  - never price from a worker-editable pointer.


## Round @ 2026-11-07 ~02:30 UTC — #71 `71f9bbe`, #72 `8ac194a`, #73 `c422cbd`

### #72 W0-04-C01 @ `8ac194a` — PASS

Delta:
- `begin_idempotent` → `ensure_idempotency_index` (the shared `indexes.require_unique_index`): the lazy unique `id` index, otherwise `IdempotencyUnprotected`.
- Check-only mode inside transactions. This addresses my notes (a) and (b).

Probes:
- `probe_w004_fg57.py`: G1, G2 and G3 unchanged (ok). **G4 (no index, no startup) → STARTED 1 of 6** (it was 6 of 6). Note (a) is CLOSED.
- `probe_w004_c01.py`: FAILS none.

Gates:

| Gate | Result |
|---|---|
| `tests/test_w0_04*` | 56 passed |
| W0 | 1092/15/67 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |

### #73 LAB-01-C @ `c422cbd` — PASS

Delta:
- `_package()` takes the package only from the approver's quantity-approval record.
- `PUT /daily-reports` rebuilds `day_entries` from an allow-list. Pricing fields (`execution_package_id`, `pay_type`, `piece_rate`, `approved_quantity`, `labor_*`, `cost_type`, `activity_type`) → 400.

**LAB01B-1 CLOSED (PROVED).** `probe_lab01b_package_pointer.py`, the same report:

| Case | Result |
|---|---|
| P1 time work | no package / package A Hourly / package B Daily → **50 / 50 / 50** |
| P2 akord, approval with no package | C / D → **50 / 50** (the approval names no package, so no piece rate applies; profile time pay) |

Other probes and gates:
- `probe_lab01.py` (L1 with package + approval terms): FAILS none.
- `tests/test_lab_01*`: 25 passed.
- W0: 1085/15/50; A2C 0; A1 0; R0 **814**.

Still declared debt: akord pays 0 until the FG-65 quantity-approval flow writes `labor_quantity_approvals`.

### #71 SEC-02-E @ `71f9bbe` — PASS

Delta: FG-63 (the workers behind a "spent" figure are counted from the same source, filter and window) and the merge of #69 `7300864`.

Probes:
- `probe_sec02_c_pulse_derive.py`: DERIVED {} (also with `PROBE_SINGLE`).
- `probe_sec02_d_pulse_generate.py`: Warehousekeeper and Viewer → 403.
- `probe_sec02_fg15_replay.py`: the Technician's first response and replay have no money keys; the stored row keeps them.
- GET scan: noise only.
- sec01 probes on the merged tree:
  - `c02_payments`: P1b ok, P1c +1 with the index; "P1 duplicate rows=0" is the stale label for keyless 428.
  - siblings, r16: FAILS none.

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **56 passed** |
| W0 | 1085/15/50 |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | **814** |


### #71 @ `71f9bbe` — FG-63 narrow-window check (requested by @parent) — holds

Probe `docs/audit/probes/sec02/probe_sec02_e_narrow_window.py`: a member SiteManager, work sessions plus approved daily reports, off and enforce.

| Case | Request | Result |
|---|---|---|
| 2 workers on 2 days | one-day window (only worker 1's day) | 200 with `actual_cost` / `clean_labor_cost` **410** — the two-worker all-time total, not worker 1's 200 |
| `PROBE_SINGLE=1` (one worker in the whole project) | either window | only the planned **budget** 5000 (allowed); actual and labor cost hidden |

- Why the one-day window shows 410: for a caller without the finance right the window is deliberately **ignored**. `routes/expected_actual.py:47-50` sets `date_from = date_to = None` (SEC-02-E, anti-differencing).
- So one worker's pay is not exposed by a narrow window. **FG-63 holds.** The probe's "FAILS" lines are false positives: it flagged the planned budget and the two-worker total.
- Residual (info, the same class as noted before; inherent to R31 "spent"): the all-time total grows day by day. A SiteManager who polls once per day can take the difference, which is that day's labor. On a day with a single worker, that is that worker's pay. Mitigation would be coarser publication (for example weekly, k-anonymous deltas); this is Krum's call.


## #55 5C-C26i @ `f0d86ab` — 2026-11-07 ~03:40 UTC — PASS

Delta:
- FG-70: `_check_dispatch_acceptance`. An acceptance of a warehouse→project dispatch must land on the dispatch's `project_id` (a subproject counts by its DB parent); a mismatch is an `InvariantViolationError`, held behind the rights check.
- FG-69: a denial on a command with a subproject names only `scope_type = subproject` / the sent id.

New probe `docs/audit/probes/pr55/test_probe_pr55_c26i_accept.py`. The dispatch is addressed to P2. PROVED; the results are identical in off and enforce:

| Who | Accept into | Result |
|---|---|---|
| member SiteManager | P1 | **422**, +0 |
| member SiteManager | subproject of P1 | **422**, +0 |
| member SiteManager | subproject of P2 | DENIED `R28_PROJECT_RELATION_REQUIRED`, scope subproject `sp-i-of-p2` only (FG-69) |
| member SiteManager | P2 | DENIED, scope project P2 |
| Admin | P1 | **422**, +0 |
| Admin | subproject of P1 | **422**, +0 |
| Admin | subproject of P2 | ALLOWED |
| Admin | P2 | ALLOWED |

Before FG-70, only a transfer's target was enforced.

Other probes: c26e_real, c26f, c26h reads, and c24, c24b, c25, c26, c26b, c26d — all pass.

Gates:

| Gate | Result |
|---|---|
| Warehouse canonical + c23 | **761 passed** on re-run. The first run gave 751 passed + 10 errors in 8:47 (slow, environmental); the re-run in 4:25 had 0 errors |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/221 |
| A1 | 0/448 |
| R0 | 814 |

Info: the 422 tells a SiteManager allowed on P1 that the dispatch is addressed elsewhere (not where). That is acceptable, because the rights check passed first.


## #73 LAB-01-D @ `21d4ed1` — 2026-11-07 ~04:00 UTC — PASS (1 latent low note)

Delta:
- FG-72: approvals are keyed `approval_key(report, entry, version)`. Every content change (owner PUT, batch save, technician draft edit, reject, reset) calls `void_labor_approvals`, which does `report_version += 1` and marks the approvals `void` (kept, never deleted). Duplicate entry ids → 400 on PUT; in pricing a duplicate key is counted once, with DQ `DUPLICATE_REPORT_ENTRY`.
- FG-73: `PUT /daily-reports/{id}` is owner-only, Admin included (pending Krum).
- FG-66: `payroll_corrections` records (pending_approval, AuditEvent, DQ alert, never applied automatically; superseded, never deleted).
- FG-76: `progress-warnings` reads the LAB-01 function.

Writers of report content vs voiding (code read):
- Every `employee_daily_reports` update that changes content voids: `daily_reports.py:309` PUT, `:1024` batch save, `technician.py:1399` draft edit; reject `:529` and reset `:647` void too.
- The approve path (`:500`, status + frozen split) and `payroll_sync` (payroll status only) do not change content and correctly do not void.

New probe `docs/audit/probes/lab01/probe_lab01d_binding.py` (production `compute_person_labor`). Package A Akord, piece 6; approval for (r1, e1, v0), qty 10:

| Case | Result |
|---|---|
| B1 r1/e1/v0 | 60 |
| B2 the same entry twice | **60, not 120** (+ DQ `DUPLICATE_REPORT_ENTRY`) |
| B3 edited, version 1 | **0** (approval void) |
| B4 e2 of the same report | 0 (not priced by e1's approval) |

Other probes:
- `probe_lab01.py`: L1 updated to the new approval key → 600 at 40 h and at 10 h.
- `probe_lab01b_package_pointer.py`: FAILS none.

Gates:

| Gate | Result |
|---|---|
| `tests/test_lab_01*` | **37 passed** |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/206 |
| A1 | 0/418 |
| R0 | 814 |

Notes, not blocking:
- **(a) Latent, low:** in `sync_run_corrections` (`payroll_corrections.py:116-128`) the `else` branch rewrites **any** existing record whose status is not pending-with-the-same-amount back to `pending_approval`, clearing `approval_id`. That includes a record already approved or applied. Today only pending and superseded exist, because there is no approval runtime. Once FG-65 approvals exist, an edited run could silently reopen an approved or applied correction. Guard it: only update pending or superseded; otherwise create a new correction version.
- **(b)** `void_labor_approvals` runs after the content write as a separate operation. A crash between the two leaves the edited content with the old version, so the old approval would still match. This is narrow; a transaction or "bump version first" would close it.


## #71 SEC-02-F @ `dee0610` — 2026-11-07 ~04:30 UTC — PASS

Delta:
- FG-74: `project_labor_workers` counts only workers with **non-zero pay** in the window (per SMR as well) toward the R31 2+ rule.
- FG-75: `audit_money_write` writes a canonical R1 AuditEvent for the price-modifier PUTs, in the same database as the write, with the Idempotency-Key and the endpoint.

Probes (`probe_sec02_e_narrow_window.py` gains `PROBE_ZERO=1`: the second worker has labor cost 0):

| Probe | Result |
|---|---|
| zero-pay second worker, off and enforce | expected-actual shows only the planned budget; actual and labor are hidden; centralized-reports/activities shows no money. **FG-74 holds (PROVED)** |
| `probe_sec02_c_pulse_derive.py` | FAILS none |
| `probe_sec02_d_pulse_generate.py` | FAILS none |
| `probe_sec02_fg15_replay.py` | FAILS none |

Gates:

| Gate | Result |
|---|---|
| SEC-02 + SEC-01 + PM-01, real Mongo | **57 passed** (the FG-75 audit event is covered by the PR's tests; not separately probed) |
| W0 | 1085/15/50, same 15 failures |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | 814 |


## #73 LAB-01-D-C01 @ `00324ab` — 2026-11-07 ~05:10 UTC — PASS

Delta `21d4ed1..00324ab` (fast-forward, 1 commit) addresses both latent notes from the `21d4ed1` round:
- **(a) closed:** `sync_run_corrections` (`payroll_corrections.py:120-136`) re-prices only `pending_approval` or `superseded` records that are not `applied`. A decided record is left untouched; a different amount upserts a `PAYROLL_CORRECTION_CHANGED_AFTER_DECISION` DQ alert. Both the update and the supersede now filter on status/`applied` and skip when `matched_count == 0`.
- **(b) closed:** `void_labor_approvals` (version bump + void) now runs **before** the content/status write at all six call sites: `daily_reports.py` (PUT, reject, reset, batch-save), `attendance.py:670`, `technician.py:1399`. A failure after the void leaves the approvals void, the safe side; the PR's test covers this.
- Residual (theoretical): an approval written between the void and the content write would bind the new version to the old content. Today the app has no route that creates `labor_quantity_approvals` (FG-65 runtime not built), so this is unreachable.

New probe `docs/audit/probes/lab01/probe_lab01e_decided_corrections.py` (production service, real Mongo RS):

| Case | Result |
|---|---|
| E1 rejected record + new amount | untouched, LOCKED DQ raised. **PROVED** |
| E2 approved record, overpayment vanished | stays approved; **no DQ raised** (note) |
| E3 approved, amount 70 then back to the decided 50 | the LOCKED DQ stays `open` with `new_amount` 70 (stale; note) |
| E4 8 concurrent syncs with different amounts on a pending record | 1 doc, pending, but `version` 2 (lost version increments; note) |
| FAILS | none |

Gates on `00324ab`:

| Gate | Result |
|---|---|
| `tests/test_lab_01*`, real Mongo RS | **40 passed** |
| W0 DB-free | 1085/15/50, same 15 as `fail_56.txt` |
| A2C | 0/206 |
| A1 | 0/418 |
| R0, real Mongo | 814 |
| merge-tree vs main | clean |
| merge-tree vs #69 `7300864` | conflict in `labor_smr.py` only (known LAB01-M1) |

Notes, not blocking; all latent until FG-65 approvals exist:
- **E2:** when the overpayment behind a decided correction disappears, nothing flags it. Suggest raising the same LOCKED DQ with `new_amount` 0.
- **E3:** the LOCKED alert is never resolved when the amount returns to the decided value.
- **E4:** concurrent run edits each read version N and write N+1, so the audit trail shows several "updated" events with the same version. Low; pay-run PATCH concurrency.
- **Supersede alert:** the supersede path resolves `dq_alerts` by `(entity_type, entity_id)` with no `code` filter, so it could resolve a LOCKED alert instead of the PENDING one. Unlikely in the current flow.

Environment note: the audit Mongo container was recreated; `mongo_up.sh` now uses host networking on 27019, so that RS discovery works with `replicaSet=rs0`.


## #73 LAB-01-E @ `c4ddd33` — 2026-11-07 ~05:25 UTC — PASS (one merge-order condition)

Delta `00324ab..c4ddd33` (fast-forward, 1 commit), audited at the orchestrator's request:
- **FG-78** `technician.py:1387-1393`: PUT draft returns 403 unless the caller is `submitted_by` or `worker_id`, and 400 unless the status is `Draft`. Submitted reports change only through approve, reject or reset. Read in code; covered by `test_fg78_*`.
- **FG-79** `daily_reports.py:1010-1029`: batch-save first loads every existing (employee, date) report and checks owner (`employee_id`/`created_by`) and status (DRAFT/REJECTED). Any refusal gives 403 (not owner) or 409 (status) before any write. Read in code; the PR test checks that nothing is written. Residual: a check-then-write window (TOCTOU) if the status changes between the two loops. Low.
- **FG-80 corrections:** keyed per overpayment, `overpayment:employee:<id>:period:<s>..<e>:source:paid_pay_runs_of_period`; the uuid5 id is derived from it and runs are collected in `pay_run_ids` (`$addToSet`). Supersede now goes by the same key, only for employees present in this run without an item.
  - An employee removed from a run no longer supersedes their correction. That is consistent with per-overpayment keying, since other runs may still see it.
  - Overlapping periods (a week inside a month) give different keys, so one overpayment could get two records. Suspicion, not probed; correction records are never auto-applied.
- **FG-80 R29** `pay_runs.py:802-847`: no key or blank → 428; key over 200 chars → 400; same key and body → replay of the first run (`idempotent_replay`); other body → 409; in progress → 409; a failed attempt can be retried under the same key.
  - **Note, low:** `_create_pay_run` writes `pay_runs.insert_one`, then `sync_run_corrections`, then `payment_slips.insert_many`, with no transaction. A crash after the insert marks the key failed, so a retry creates a second run. This was not atomic before either.
- **Test-client key hook** (`tests/pay_run_idempotency.py`): adds a fresh key **only** when the request has none. R0-05/R0-06/LAB-01 assertions are unchanged (the diff only adds `event_hooks`). The 428 is still tested without the hook (`test_fg80_no_header_at_all_is_refused`, `test_fg80_r29_*` blank key). **No assertion weakened.**
- Frontend `PayRunsPage.js`: one key per request body via `useRef`, reset after success, reused on retry of the same body.

New probe `docs/audit/probes/lab01/test_probe_lab01e_payrun_r29.py` (real Mongo RS, one test per process):

| Case | Tree | Result |
|---|---|---|
| P1: 8 concurrent POSTs with the **same** key, fresh DB | `c4ddd33` alone | **8 runs**, all 200. `audit_idempotency` has only `_id` (no unique `id` index on main) |
| P1 | trial merge `c4ddd33` + #72 `8ac194a` | **1 run**, 1×200 + 7×409. PROVED fixed by #72's lazy unique-index guard |
| P3: PATCH a draft run to another period | `c4ddd33` | 400 (period change refused), so no orphan correction |

**Condition, PROVED:** R29 on POST /pay-runs is race-safe only once #72 (W0-04-C01 indexes and guards) is in. **#72 must merge before or together with #73.** This is the same class as IDEM-IDX-1 on #69. Not blocking #73 itself.

Gates on `c4ddd33`:

| Gate | Result |
|---|---|
| `tests/test_lab_01*`, real Mongo RS | **47 passed** |
| W0 DB-free | 1085/15/50, same 15 |
| A2C | 0/206 |
| A1 | 0/418 |
| R0, real Mongo | 814 |
| `yarn build` (frontend, same deps as wt70) | **Done**, compiled |
| merge-tree main / #72 | clean / clean |
| merge-tree #69 | `labor_smr.py` (known LAB01-M1) |
| merge-tree #70 | `project_pnl.py` (known) |
| merge-tree #71 | `all_reports.py`, `labor_smr.py`, A2B inventory (known) |

Environment: the dockerd restart was blocked by a stale `/var/run/docker.pid`; it was removed and the RS brought back up.


## #74 OH-01 @ `a3e0b91` — 2026-11-07 ~06:20 UTC — FINDINGS (1 blocking)

Base: main `35ae10b`. Package: `OH-01_OVERHEAD_NO_HARD_DELETE.md` (tasks branch `ab74e23`); FLOW-024, CLAUDE §2.9, FG-77.

Read in code:
- `overhead.py` has **no `delete_one`/`delete_many`** left (grep is empty).
- The DELETE routes (category, cost, asset) do: access check, then `require_key` (428), then a 404 check, then a usage check (409 `OVERHEAD_RECORD_IN_USE`), and only then archive (`status=archived`, who/when/why) plus a FLOW-024 AuditEvent.
- Allocate supersedes the previous batch first, then inserts version N+1.
- Every reader of `project_overhead_allocations` filters `superseded_by: None`: snapshot detail, `/overhead/allocations`, `project_pnl.py:112`, `project_financial_results.py:216`. There are no other readers in `backend/app`.
- Permissions are the unchanged `check_overhead_access` (write = Admin/Owner/Accountant), as the package allows until #69.

Probe `docs/audit/probes/oh01/test_probe_oh01.py` (real Mongo RS, enforce unless noted, one test per process):

| Case | Tree | Result |
|---|---|---|
| **O1** 4 concurrent re-allocations, **different** keys, ×5 rounds | `a3e0b91` | all 200; **4 current batches every round; current total 1600 vs snapshot 400**; versions collide (one version number per round) |
| O1 | trial merge with #72 | **same: 5/5 rounds with >1 current version**. This is not the index issue |
| **O2** 6 concurrent DELETEs of the same unused cost, different keys | `a3e0b91` | **6 × 200, 6 AuditEvents** "archived"; the document is archived once |
| O3 tenant-B Owner DELETEs tenant-A cost and category ids | `a3e0b91` | 404 / 404, A untouched. PASS |
| O4 accountant / sitemanager / technician / viewer, off/shadow/enforce | `a3e0b91` | accountant 200 (finance role); the others 403/403 in all three modes. PASS |
| O5 4 concurrent allocates, **same** key | `a3e0b91` | 4 × 200, **8 rows, total 1600** (no unique `audit_idempotency` index on main) |
| O5 | trial merge with #72 | 1 × 200 + 3 × 409, 2 rows, 400. PASS. Needs #72 (same class as IDEM-IDX-1) |

### OH01-1 — BLOCKING, PROVED: concurrent re-allocations double (×N) the project overhead

`_write_allocation_version` (`overhead.py:~686-735`) runs these steps with no lock and no compare-and-set:
1. read max version;
2. `update_many(superseded_by=None, batch != mine)`;
3. `insert_many`.

Two requests with different keys (two admins, or two tabs) interleave: A supersedes, B supersedes, A inserts, B inserts. The result is two current batches with the same version number. `project_pnl` and `project_financial_results` then sum both.

- Repro: O1 above. P&L overhead is 1600 for a 400 snapshot.
- This contradicts the package ("the sum is not doubled") and HANDOFF D2 ("never double").
- Suggested fix, any one of:
  - a per-snapshot lock or a CAS on the snapshot document (`allocation_version` `$inc` conditioned on the version that was read), like #70's `allocation_lock`;
  - a unique index on `(overhead_snapshot_id, allocation_version)`, inserting before superseding `version < N`.
- Add a concurrency test.

### OH01-2 — MEDIUM, PROVED: concurrent archives all succeed and each writes an AuditEvent

`_archive_record` ignores `update_one(...status != archived)`'s `modified_count`. A loser of the race returns 200 and appends "overhead_cost.archived" again (O2: 6 events for one archive). Suggested fix: when `modified_count == 0`, refuse with 409 `ALREADY_ARCHIVED` (`kw.refuse`).

### Conditions and notes

- **Needs #72 first (PROVED, O5):** same-key double submit creates duplicate rows without the unique idempotency index.
- **Merge order with #69 (PROVED):**
  - `merge-tree` is clean, and PM-01 plus OH-01 on the trial merge pass in off and shadow.
  - But **12 OH-01 enforce cases fail** on the trial merge. #69's `require_money_write` on `/overhead/snapshots/compute` sends enforce through the Tenant Guard / Permission Service, and the OH-01 harness seeds no tenant registry (403 `TENANT_NOT_REGISTERED`; without MONGO_URL it reaches localhost:27017).
  - The HANDOFF says only "re-run PM-01". Whichever PR merges second must also fix the OH-01 harness.
  - After #69, the 4 OH-01 routes stay on the legacy role check while compute uses `require_money_write`. That inconsistency should be a follow-up, as HANDOFF item 3 says.
  - SEC-01 tests on the trial merge: 30 passed.
- **PM-01 regeneration verified:**
  - `tests/test_pm_01_permission_matrix.py` gives 6 passed on `a3e0b91`.
  - The `matrix.csv` diff is exactly 36 cells: 4 routes × owner/admin/accountant × 3 modes, 404 → 428, wrote=no before and after. No non-finance cell changed.
  - 404 → 428 is expected: PM-01 sends no key, and the key check precedes the existence check.
- **Low notes:**
  - A category whose only costs are archived can never be archived (usage counts archived costs). This is conservative.
  - PUT on an archived record is not blocked (HANDOFF D4).
  - Asset usage is approximated by `computed_at` (D1).
- **#70:** `merge-tree` conflicts in `frontend/src/lib/idempotency.js` and its test. #74's copy equals #69's, #70's differs.

Gates on `a3e0b91`:

| Gate | Result |
|---|---|
| OH-01 tests (mongomock + real × 3 modes) | **43 passed** |
| `test_m9_overhead.py` | live-server test (needs `REACT_APP_BACKEND_URL`), not runnable here |
| PM-01, real Mongo | 6 passed |
| W0 DB-free | 1085/15/50, same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| merge-tree main / #69 / #71 / #72 / #73 / #55 | clean |
| merge-tree #70 | `idempotency.js` (+ test) conflict |

R0 and `yarn build` were not re-run by me this round: the delta is backend overhead plus 2 pages, and the PR evidence states R0 814 and the build compiles. Re-run them at the fix round.


## #74 OH-01 @ `09409f0` — 2026-11-07 ~06:50 UTC — PASS (OH01-1 and OH01-2 closed)

Delta `a3e0b91..09409f0` (fast-forward, 1 commit):
- **OH01-1:** `_write_allocation_version` now runs under `snapshot_allocation_lock` (`overhead_lifecycle.py`).
  - One conditional atomic `update_one` on the snapshot row; a busy lock → 409 `ALLOCATION_BUSY`; a lock older than 30 s may be taken over; release goes by the owner's token in `finally`.
  - Plus a CAS on `snapshot.allocation_version` (409 `ALLOCATION_VERSION_CONFLICT`).
  - Plus a unique partial index `(org_id, overhead_snapshot_id, allocation_version, project_id)` where `allocation_version` exists, created idempotently per request.
  - Lock order: `async with kw, lock`, so a lock refusal marks the key FAILED and a retry is allowed.
- **OH01-2:** `_archive_record` checks `modified_count != 1` → 409 `ALREADY_ARCHIVED`, raised before the audit step.
- **Harness:** the OH-01 tests now seed a registered tenant (system db: registry, memberships, role assignments) and patch `money_write.db` when #69's module exists.

Probes `docs/audit/probes/oh01/test_probe_oh01.py` (updated for the new `_Db`/`_seed` signature; new **O6**), real Mongo RS:

| Probe | `09409f0` | + #69 | + #72 |
|---|---|---|---|
| O1: 4 parallel re-allocations, different keys, 5 rounds | **0/5 rounds with >1 current version**; each round 1×200 + 3×409; current total 400 = snapshot; versions 1..5 distinct | 0/5 | 0/5 |
| O2: 6 parallel archives of one cost | **1×200 + 5×409, 1 AuditEvent** | | |
| O3 cross-tenant DELETE | 404/404, untouched | | |
| O4 roles × off/shadow/enforce | accountant 200; sitemanager, technician, viewer 403 | | |
| O5: 4 parallel same-key allocates | 1×200 + 3×409, 2 rows, 400 (now safe **even without #72**: the snapshot lock serializes) | | pass |
| O6: fresh foreign lock | 409 `ALLOCATION_BUSY`, 0 rows, lock intact | | |
| O6: stale (45 s) lock | taken over, 200, lock released, version 1 | | pass |

**OH01-1 closed (PROVED). OH01-2 closed (PROVED).**

Gates on `09409f0`:

| Gate | Result |
|---|---|
| OH-01 tests | **57 passed** (incl. `test_07` concurrency) |
| OH-01 tests on trial merge with #69 | **57 passed** (enforce now green; was 12 failed) |
| SEC-01 tests on trial merge with #69 | 30 passed |
| OH-01 tests on trial merge with #72 | 57 passed |
| W0 DB-free | 1085/15/50, same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0, real Mongo | **814** |
| PM-01, real Mongo | 6 passed |
| `yarn build` | compiled (with warnings, none in changed files per the PR) |
| `idempotency.test.js` | 4 passed |

Residual notes, low:
- `ensure_allocation_indexes` calls `create_index` on every allocate. It is idempotent but costs a round trip; startup would be better.
- The 30 s stale-lock takeover means an allocation running longer than 30 s could be overlapped. The CAS on the version still prevents a duplicate version.
- Legacy rows without `allocation_version` are outside the unique index (as documented).
- #70 still conflicts on `idempotency.js`.


## #73 LAB-01-F @ `25f1d6c` — 2026-11-07 ~07:30 UTC — PASS

Delta `c4ddd33..25f1d6c` (fast-forward, 1 commit), audited at the orchestrator's request:
- **FG-84:** a correction's key is now `overpayment:employee:<id>:source:paid_pay_run_lines:<sorted paid run ids>` (`payroll_corrections.py:_key`). `generate_pay_run` records `previously_paid_sources` (each paid line: run id, number, period, amount) and `considered_pay_run_ids` on the row; both are frozen on create and update.
  - Supersede: a pending correction of the employee whose source runs are all inside this run's considered runs, and which is not the current key, is superseded.
  - This closes the c4ddd33 suspicion about overlapping periods.
- **FG-85:** `create_pay_run` catches #72's `IdempotencyUnprotected` and answers **503** with nothing written (fail closed). The concurrency test is skipped on #73 alone and runs on the merge with #72.

New probe `docs/audit/probes/lab01/test_probe_lab01f_sources.py`, plus P4 added to `test_probe_lab01e_payrun_r29.py`:

| Case | Tree | Result |
|---|---|---|
| F1: week, 3-week and month runs over one 60 overpayment (mongomock + real) | `25f1d6c` | **1 record**, 60, sources `[run-old]`, 3 `pay_run_ids`. PROVED |
| F2: a DRAFT monthly run where later unpaid earnings (120) absorb the 60 (earned 720, paid 660, remaining 60, no item) | `25f1d6c` | the pending correction is **superseded** by the draft; the next weekly run reopens it (pending, v3, still 1 record) |
| P1: 8 concurrent same-key POSTs | merge with #72 `8ac194a` | 1 run, 1×200 + 7×409 |
| P4: `audit_idempotency` with duplicate ids (unique index cannot be built) | merge with #72 | **503** "Idempotency registry is not protected; nothing written", 0 runs. PROVED |

Gates:

| Gate | Result |
|---|---|
| `tests/test_lab_01*` on `25f1d6c` | 51 passed, 1 skipped (`test_fg85`, needs #72) |
| `tests/test_lab_01*` on the merge with #72 | **52 passed** (`test_fg85` green) |
| W0 | 1085/15/50, same 15 |
| A2C | 0/206 |
| A1 | 0/418 |
| R0 | 814 |
| merge-tree main / #72 / #74 | clean |
| merge-tree #69 / #70 / #71 | known conflicts (`labor_smr.py`; `project_pnl.py`; `all_reports.py` + `labor_smr.py` + A2B inventory) |

Note for Krum (business, not blocking), F2: a **draft** run that nets a salary overpayment against later unpaid earnings of the same person supersedes the pending correction. It is recoverable: the next run that sees the overpayment reopens it. But while only the draft exists, the overpayment is not visible as a pending correction. Krum decides whether superseding should happen only on confirm, or whether netting against later salary is acceptable at all (CLAUDE.md §7: no automatic netting of receivables and payables).


## #74 OH-01 FG-86/87/88 @ `240cbcf` — 2026-11-07 ~07:45 UTC — PASS (2 notes)

Delta `09409f0..240cbcf` (fast-forward, 1 commit):
- **FG-86, compute:** compute supersedes every active snapshot of the **same exact period** (and their current allocations), and assigns `snapshot_version`.
  - The active snapshot carries `active_period_key`, protected by a unique sparse index.
  - Compute and allocate share one `period_lock` (conditional upsert on `_id` in `overhead_period_locks`, 30 s stale takeover).
- **FG-86, allocate:** allocating a superseded snapshot → 409 `SNAPSHOT_SUPERSEDED`; a new allocation supersedes every current allocation of the period.
- **FG-87:** `_guarded_update`.
  - Archived record → 409 `RECORD_ARCHIVED`; used record → 409 `OVERHEAD_RECORD_IN_USE`.
  - For a cost, the new date is checked too.
  - The write is conditional on status (a racing archive gives 409); an accepted PUT writes an AuditEvent with before/after of the changed fields.
- **FG-88:** compute requires a key (428) and runs under `KeyedWrite` (replay, 409 on a different body).

Probes `docs/audit/probes/oh01/test_probe_oh01.py` (O6 adapted to `overhead_period_locks`; new O7–O10), real Mongo RS, enforce:

| Probe | Result |
|---|---|
| O1: 4 parallel re-allocations × 5 rounds | 0/5 with >1 current; each round 1×200 + 3×409; total 400 = snapshot |
| O2 parallel archive | 1×200 + 5×409, 1 event |
| O3 cross-tenant | 404/404 |
| O5 same key | 1×200 + 3×409, 2 rows |
| O6 lock edges | fresh → 409 `ALLOCATION_BUSY`, 0 rows, lock intact; stale → taken over, released |
| **O8**: 4 parallel computes of one period × 3 rounds (FG-86) | each round 1×200 + 3×409; **exactly 1 active snapshot**; versions 1, 2, 3. PROVED |
| **O9**: allocate S1, compute S2 (same period) | 0 current allocation rows after S2; allocate S1 → 409 `SNAPSHOT_SUPERSEDED`; allocate S2 → 200, total 400 = snapshot. PROVED |
| **O10** FG-87 | unused cost moved into a computed period → 409; used cost edit → 409; accepted edit → AuditEvent `{"amount": {"before": 50.0, "after": 55.0}}`; DELETE racing 3 PUTs → [200, 409, 409, 409], final archived with the amount unchanged; PUT on archived → 409. PROVED |
| **O7** (D6): month Oct 1–31 **and** half-month Oct 1–15, both allocated | **2 active snapshots, current allocation total 800 for one 400 cost** (double count) |

Gates on `240cbcf`:

| Gate | Result |
|---|---|
| OH-01 tests | **87 passed** |
| W0 | 1085/15/50, same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| `yarn build` | compiled (warnings) |
| R0, real Mongo | **814** |
| PM-01, real Mongo | 6 passed |
| PM-01 matrix diff | exactly 9 cells: compute × owner/admin/accountant × 3 modes, 200/wrote → 428/nothing |
| merge-tree main / #72 / #73 / #55 | clean |
| merge-tree #70 | `idempotency.js` (known) |
| merge-tree #69, #71 | `overhead.py` (compute signature) + `matrix.csv`. #71 carries #69's compute change: same conflict, same resolution |

Trial merge with #69 `7300864`, resolved as the HANDOFF says (keep `_sec01` and `idempotency_key`; matrix taken from one side):
- OH-01: **87 passed**.
- SEC-01: 29 passed, **1 failed**: `test_sec_01_c01_all_money_writes::test_a_fresh_real_mongo_run_on_two_tenants_follows_the_rules_in_every_mode`.
- `test_the_pm01_matrix_shows_the_money_write_cells_closed` passed without regeneration.

**OH01-3, MEDIUM, PROVED: the HANDOFF's diagnosis of that SEC-01 failure is wrong.**
- The HANDOFF says compute "now gets 428". On the merged tree the SEC-01 harness sends a key and compute returns **200** (off, Owner, tenant A).
- The assertion that fails is `written_orgs == ['A']`: the actual value is `['A', 'None']`. The written namespaces are `op.$cmd, op.audit_events, op.audit_logs, op.overhead_period_locks, op.overhead_snapshots`.
- The lock row carries `org_id` (checked directly). The org-less write is the **`createIndexes` command** from `ensure_snapshot_indexes` on the first compute in a fresh database (`$cmd` oplog entry, no `_id`/org).
- So "update the expectation to 428" will not make it pass. The fix is either:
  - create the OH-01 indexes at startup/onboarding (like #72's `ensure_audit_indexes`), not per request (this also closes my earlier low note), or
  - teach the SEC-01 harness to ignore `$cmd` DDL.

**Note for Krum, HIGH business impact, not blocking (pre-existing on main; documented as HANDOFF D6), O7:**
- Snapshots of **overlapping** periods are both active, and both allocations count in P&L: 800 for a 400 cost.
- Recommendation: refuse a compute whose period overlaps an active snapshot of a different period (or supersede it).

Other notes:
- Between "new snapshot computed" and "new snapshot allocated", P&L shows 0 overhead for the period (HANDOFF; behaviour change).
- FG-87 is strict and also blocks non-financial fields on used records (HANDOFF; Krum).
- FG-89: `full_cost.py` is a second overhead path writing into `overhead_snapshots` with no versions or key (HANDOFF debt; needs a decision).


## #73 LAB-01-G @ `d0aa09a` — 2026-11-07 ~08:00 UTC — PASS (F2 closed)

Delta `25f1d6c..d0aa09a` (fast-forward, 1 commit) answers my F2 note under CLAUDE.md §7:
- `allocate_paid_sources` (`pay_runs.py:294`) takes the paid lines in run order and lets each consume the LAB-01 earned amount of **its own days**. "Previously paid" counts a line only up to that; the excess is `overpaid`, a receivable.
- `overpayment_item` builds the item per source.
- `sync_run_corrections` now only **creates** missing records: one per (employee, source pay run), key `overpayment:employee:<id>:source:pay_run:<run>`. It never rewrites, supersedes or applies one. A different recomputed amount opens a DQ alert (`PAYROLL_CORRECTION_RECOMPUTED`, or `…CHANGED_AFTER_DECISION` for a decided record) with the recorded and new amounts.
- In create/update, the run's own window shortfall no longer produces an item.

Probes (`docs/audit/probes/lab01/test_probe_lab01f_sources.py`, updated; new G1 and G3), real Mongo RS:

| Case | Result |
|---|---|
| F1: week, 3-week and month windows over one 60 overpayment (mongomock + real) | 1 record, 60, source `run-old`, 3 `pay_run_ids` |
| **F2**: draft monthly run with later unpaid work worth 120 | earned 720; previously paid **counted 600** (total 660); receivable 60; **remaining 120** (later work paid in full); correction **stays pending**. Next weekly run: still pending, v1, 60, 1 record. **F2 closed (PROVED)** |
| G1: two confirmed runs paid the same week (660 + 600, earned 600) | counted 600, receivable 660, remaining 0. Records: `run-old` 60 and `run-old-2` 600. PROVED |
| G3: paying 700 now against 600 earned in this run | **400 "Overpayment is not allowed"**, no record. There is no path that creates an overpaid line inside a run |

The orchestrator expected "600 remaining" in F2. In my seed the later work is worth 120, so the correct remaining is 120 (later earnings paid in full); the semantics match.

Test edits: `test_lab_01_d/e` replace the supersede/reopen assertions with "record unchanged + DQ alert" assertions, and `previously_paid` 660 → 600 with `previously_paid_total` 660. This is consistent with the design change; nothing is weakened.

Gates:

| Gate | Result |
|---|---|
| `tests/test_lab_01*` on `d0aa09a` | 53 passed, 1 skipped (fg85) |
| `tests/test_lab_01*` on the merge with #72 | **54 passed** |
| W0 | 1085/15/50, same 15 |
| A2C | 0/206 |
| A1 | 0/418 |
| R0 | 814 |
| merge-tree main / #72 / #74 | clean |
| merge-tree #69 / #70 / #71 | known conflicts |

Note, low: a receivable is recorded only when a later run's preview sees the paid line; nothing records it at the moment the source run is paid. G3 shows a run cannot itself pay above its remaining, so the only way to get one is later re-pricing. That is acceptable.


## main @ `0f870c3` — 2026-11-07 ~08:30 UTC — #56 merged (Codex PASS, Krum approved)

- The merge commit `0f870c3` has parents `35ae10b` (old main) and `3234446` (the #56 head I audited, PASS).
- `git merge-tree --write-tree 35ae10b 3234446` gives tree `0d011de9…`, **identical** to `0f870c3^{tree}`. Main is exactly the clean merge of the audited head, with nothing added.

Gates on main `0f870c3`:

| Gate | Result |
|---|---|
| W0 | 1085/15/50, the same 15 as `fail_56.txt` |
| A2C | 0/211 |
| A1 | 0/426 |
| R0, real Mongo | **814** |
| `tests/test_auth_0*.py`, real Mongo | **122 passed** |

The idempotency-race, w004 and #73/#74 probes target trees with #72/#73/#74 and will be re-run when those merge main.

merge-tree of the open PR heads against main `0f870c3`:

| PR | Result |
|---|---|
| #69, #70, #71 | clean |
| #55 `f0d86ab` | `tenancy/data_access.py`, A2B inventory |
| #72 `8ac194a` | `audit/store.py` (the known #56 recipe), A2B inventory |
| #73 `6763970` | `tenancy/ownership.py` |
| #74 `6c5c5cf` | `server.py` (startup index blocks: keep both, trivial) |


## #74 OH-01 @ `6c5c5cf` — 2026-11-07 ~08:35 UTC — PASS (D6 and OH01-3 closed)

Delta `240cbcf..6c5c5cf` (2 commits):
- **D6:** `_refuse_overlap` refuses a compute whose period overlaps an ACTIVE snapshot of a **different** period (409 `PERIOD_OVERLAP`). It runs before the key reservation and again under a new org-wide `overhead_lock(COMPUTE_LOCK)`, taken before the period lock. Allocate takes only the period lock, so there is no ordering conflict, and both locks are non-blocking (409).
- **OH01-3:** `ensure_overhead_indexes` (allocation `version_key` unique sparse, `active_period_key` unique sparse, and the `overhead_period_locks` collection) runs at **startup** (`server.py`) and at **tenant onboarding**, never on a request path. `overhead_period_locks` is classified ORG_KEYED.

Probes (O7 updated; new **O11**), real Mongo RS:

| Probe | Result |
|---|---|
| O1/O2/O5/O6/O8/O9 | unchanged, all pass |
| **O7** month then half-month | **409 `PERIOD_OVERLAP`**, 1 snapshot in the database. **D6 closed (PROVED)** |
| **O11**: Oct 1–31, Oct 1–15 and Oct 10–Nov 10 computed in parallel × 5 rounds | each round 1×200 + 2×409 `ALLOCATION_BUSY`; **exactly 1 active snapshot** every round |
| O10 FG-87 | move-in/used/archived PUT → 409; accepted edit audited. The race was [200, 200, 200, 200] this run: all PUTs landed before the archive (a PUT after archive is conditional → 409); final archived. Consistent |

Trial merge with #69 `7300864`:
- `overhead.py` resolved as the HANDOFF says (`_sec01` + `idempotency_key`); matrix from one side.
- OH-01: 102 passed.
- SEC-01 without the results diff: 29 + 1 failed (expected: committed `results.json` predates OH-01).
- After applying `docs/evidence/OH-01/merge69_sec01_c01_results.diff`: **30/30 passed**.
- Fresh run: compute (off, Owner, A) writes `op.audit_events, op.audit_logs, op.overhead_period_locks, op.overhead_snapshots` with written_orgs **`['A']`**. There is no `$cmd` any more. **OH01-3 closed (PROVED).**

Gates on `6c5c5cf`:

| Gate | Result |
|---|---|
| OH-01 tests | **102 passed** |
| W0 | 1085/15/50, same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |
| PM-01, real Mongo | 6 passed |

Notes, low:
- Startup creates the indexes on the legacy operational `db`, the same pattern as `project_team.ensure_indexes(db)`. New tenants get them at onboarding. Dedicated tenant databases onboarded **before** this change need a one-off bootstrap run, or have no OH-01 unique indexes; the locks and CAS still protect them.
- D6 refuses only; existing overlapping legacy data is not migrated. Switching from monthly to quarterly needs a supersede/retire path (Krum).


## #73 LAB-01-H @ `6763970` — 2026-11-07 ~08:40 UTC — FINDINGS (1 blocking)

Delta `d0aa09a..6763970` (1 commit): R36 (Krum, LAB-01 Addendum A).
- `report_corrections.authorize_report_edit` returns:
  - **CORRECTOR** for Admin/Owner, or for a SiteManager who `can_manage_project` on every project of the report (old and new entries);
  - **AUTHOR** for the worker/creator, only on DRAFT/REJECTED;
  - otherwise 400 or 403.
  - A report with `payroll_status` paid/batched → 409 for everyone.
- Every correction voids the quantity approvals first (FG-72) and writes a FLOW-014 AuditEvent with before/after.
- Applies to PUT `/daily-reports`, PUT `/technician/draft`, POST batch-save.
- Test edits: FG-73 (Admin now allowed, audited) and FG-79 (author on APPROVED: 409 → 400). Consistent with R36.

### LAB01H-1 — HIGH, BLOCKING, PROVED: a corrector can raise the hours of their **own** approved report

Probe `docs/audit/probes/lab01/test_probe_lab01h_r36.py` (the PR's own R36 harness). Report of worker X on project P, APPROVED by `admin`, 8 h. X edits it to 12 h:

| X | Result |
|---|---|
| `sm-p` (SiteManager of P) | **200**, total_hours **12**, status **APPROVED**, `approved_by` still `admin`, `corrected_by` `sm-p` |
| `admin` | 200, the same |

- The report stays APPROVED, so payroll counts the 12 h. Hourly/daily pay is computed from APPROVED lines (LAB-01); only akord quantity approvals are voided.
- Nobody but X approved the 4 extra hours, and `approved_by` names someone who approved 8.
- This is a self-approval path (CLAUDE.md §8/§16: no bypass of Approval; LAB-01 already forbids self-approval of quantities, `labor_cost.py`).
- Fix options, Krum to choose:
  - (a) a corrector may not correct a report where they are the worker/author (`employee_id`/`created_by`/`worker_id`): 403;
  - (b) correcting an APPROVED report returns it to SUBMITTED (or keeps APPROVED only when another approver confirms);
  - (c) at least clear or replace `approved_by` and raise a DQ alert for self-corrections.
- Add a test for each endpoint.

Gates on `6763970`:

| Gate | Result |
|---|---|
| `tests/test_lab_01*` | 78 passed, 1 skipped (fg85, needs #72) |
| W0 | 1085/15/50, same 15 |
| A2C | 0/207 |
| A1 | 0/420 |

R0 was not re-run on `6763970` (last run 814 on `d0aa09a`); re-run at the fix round. merge-tree vs main: conflict in `tenancy/ownership.py`.


## #72 W0-04-C01 @ `34ac9f4` — 2026-11-07 ~09:10 UTC — PASS (main merged; merge-order root)

`e30c567` = merge of `8ac194a` (my last PASS) and main `0f870c3`; `34ac9f4` adds only `docs/evidence/W0-04-C01/tests.txt`. Against `git merge-tree 8ac194a 0f870c3` the merge commit differs in exactly three files:

| File | Change |
|---|---|
| `audit/store.py` | conflict resolved per the recipe (below) |
| `W0-03E-A2B_INVENTORY.md` | conflict, regenerated |
| `services/auth_tx.py` | +5 lines, **not a conflict file**: `run_in_transaction` now calls `ensure_chain_index(db)` **before** `start_session` |

`record_event` (`store.py`):
- `_require_chain_index(db, create=session is None)`: **check-only inside a transaction** (an index build would wait on the transaction's own lock), create allowed outside.
- `_last_event(..., session=session)` and `insert_one(..., session=session)`.
- On `DuplicateKeyError`: `if session is not None or not _is_sequence_collision(exc): raise`. The recipe verified at e733c66; inside a transaction the whole transaction retries.

Probes on `34ac9f4`, real Mongo RS:

| Probe | Result |
|---|---|
| `w004/probe_w004_x56_tx_race.py` × 3 (each 3 rounds of 20 transactional + 20 plain appends on one tenant) | **0 transactional / 0 plain failures**, 120 stored, `verify_chain` (True, None) every run |
| `w004/probe_w004_c01.py` (I1–I6) | **FAILS none** (I6: signup/onboarding → 200, idempotency unique keys `id`, `(tenant_id, action, key)`) |
| `w004/probe_w004_fg57.py` | **FAILS none**. G1: no index, 30 concurrent → 0 errors, linear chain. G2 non-unique index → `AuditChainUnprotected`, 0 appended. G3 existing fork → refused, kept. G4: `begin_idempotent` with no index → 1 of 6 STARTED (the IDEM-IDX guard) |

Gates on `34ac9f4`:

| Gate | Result |
|---|---|
| W0 | **1092/15/67** (#72's own tests add 7 passed and 17 skipped); same 15 failures as `fail_56.txt` |
| A2C | 0/212 |
| A1 | 0/428 |
| `tests/test_auth_0*.py` + `test_w0_04_c01_audit_indexes_and_chain.py`, real Mongo | **146 passed** |
| R0 | **814** |

merge-tree vs `34ac9f4`:
- #69 and #70: clean.
- #71: A2B inventory.
- #55: `data_access.py` + inventory.
- #73: `ownership.py`.
- #74: `server.py`.

These are the same conflicts the PRs have with main (they come from #56). lab01e P1 and oh01 O5 passed on the earlier #72 merges; the idempotency code is unchanged, so they will be re-run when #73/#74 rebase onto #72/main.

**Environment incident (not a PR finding):**
- The audit `mongod` died at 08:33 UTC with a WiredTiger panic: **"Too many open files"** (errno 24) during the #55 warehouse suite. Leftover test databases had exhausted file handles under the 20000 limit.
- The #55 run at that time (775 passed / 38 errors) is therefore **invalid**; it is being re-run on a fresh container.
- New `$S/mongo_clean.sh` drops leftover test databases. It dropped 87 after the auth tests alone. It now runs before and after long suites.


## #73 LAB-01-I @ `ca81286` — 2026-11-07 ~09:35 UTC — LAB01H-1 CLOSED

`6763970..ca81286` (1 commit) chooses fix option (b):
- `correction_fields`: a correction of an APPROVED report sets it back to **SUBMITTED**, clears `approved_by`/`approved_at`, sets `payroll_ready` false and `sessions_created` 0, stores `reopened_by_correction`, and adds the corrector to `correctors`.
- `reopen_effects` flags the report's work sessions void (as reset does), gives back the activity-budget hours, and opens DQ `DAILY_REPORT_CORRECTED_AFTER_APPROVAL`.
- `approve_report_one` refuses `self_approval_ids` (worker/employee/submitted_by/created_by plus correctors): 403 on the single path. The bulk path uses the same function.
- Applied to PUT `/daily-reports`, PUT `/technician/draft`, batch-save.
- The only other `Approved` setter is `work_reports` approve (`attendance.py:701`), which is a different collection, pre-existing and outside R36.

Probe `lab01/test_probe_lab01h_r36.py` (H1/H2 updated; new H5 on the PR's four-eyes harness):

| Case | Result |
|---|---|
| H1/H2: SM or Admin corrects own APPROVED report 8 → 12 h | 200, status **SUBMITTED**, `approved_by` None |
| **H5** end to end (SM `sm` is the worker on P, approved by admin) | earned 80 before; after self-correction status SUBMITTED, **earned 0**; sm approves → **403**; admin approves → APPROVED, earned **120**. **LAB01H-1 closed (PROVED)** |

Gates on `ca81286`:
- `test_lab_01_h_r36` + `test_lab_01_i_four_eyes`: 30 passed.
- W0: 1085/15/50, same 15.
- A2C: 0/207.
- A1: 0/420.

The full real-Mongo lab suite and R0 will be re-run (environment, below). The existing #73 PR comment will be updated to "resolved".


## #75 LAB-02 @ `789bbd9` — 2026-11-07 ~09:40 UTC — review PASS, note LAB02-1

Stacked on #73 (`0c85678` LAB-02, then a merge of LAB-01-I `ca81286`, then `789bbd9` four-eyes on quantity entry/approval).

New `routes/labor_quantities.py`:

| Endpoint | Rules |
|---|---|
| `GET/PUT /labor-terms` | finance only (R31); PUT under R29 (`_idempotent` on the W0-04 registry, 503 when unprotected), `labor_terms_version` + `labor_terms_history`, AuditEvent |
| `PUT /labor-quantities/entry` | R36 author/corrector, void before write, LAB-01-I reopen, audited |
| `POST /labor-quantities/approve` | approver role first; `_require_approver`: never the worker nor any author/corrector; SM via `can_manage_project`; report SUBMITTED/APPROVED; **409 on a stale `report_version`**; package must be on the line's project. The record **snapshots** `labor_pay_type`/`piece_rate`/`labor_terms_version`; a re-approval voids the previous record (kept); AuditEvent |
| `POST /labor-quantities/classify` | LABOR/DOWNTIME/DOWNTIME_UNCLASSIFIED, a reason is required for downtime, same binding, version check and four-eyes |

`labor_cost.py`:
- pay type and piece rate come first from the approval's snapshot, then the package, never the line;
- `_cost_type` comes from the approver's classification;
- `void_labor_approvals` also voids classifications.

No `delete_*` in the new code; replaced records are marked `void`.

Probes `lab01/test_probe_lab02.py`, real Mongo RS:

| Probe | Result |
|---|---|
| **Q1**: 4 concurrent approvals of one line (sm, admin, owner, sm; different keys; quantities 100–130) | all 200, **4 `approved` records**; Pay Run earned 550 (one record; the earliest wins, so never the sum) |
| Q2: rate 5 → approve 120 → finance sets 9 | earned **600 before and after** (snapshot), 2 history rows. PROVED |
| Q3 roles | approve as tech/acct/sm-other/worker → 403, 0 records; GET terms acct 200, sm/tech 403; PUT terms sm 403, admin 200 |
| Q4 cross-tenant | tenant-B admin: approve 404, set terms 404, entry 404; A's rate unchanged, 0 records |

**LAB02-1, MEDIUM (PROVED in part):**
- Concurrent approvals of the same (report, version, entry) leave several active `approved` records.
- Pay is not doubled: `load_smr_terms` takes the earliest.
- But `GET /labor-quantities/pending` builds `by_key` with last-wins, so the approver may be **shown** a different quantity than the one paid (by code reading).
- Suggested fix: a per-line lock or a unique partial index on (org, report_id, entry_id, report_version) where status is approved; or make pending use the same earliest-wins rule.

Gates on `789bbd9`:
- W0: 1085/15/50, same 15.
- A2C: 0/208.
- A1: 0/422.
- `laborQuantities.test.js`: 5 passed.
- `yarn build`: compiled.
- Lab tests: 53/53 on the first real-Mongo run. Later reruns failed because my own `mongo_clean.sh` loop was dropping databases mid-test (self-inflicted, see below). They will be re-run in isolation, with R0 and PM-01.

**Environment (again):**
- `mongod` crashed a second time at 09:09 UTC with "Too many open files", at about 70% of the #55 warehouse suite in one process. That suite alone exhausts the handles.
- The #55 suite is now run **per file** with a cleanup between files.
- Lesson logged: never run another real-Mongo suite while the cleanup loop runs.


## #55 5C-C26j @ `8025871` — 2026-11-07 ~10:00 UTC — PASS

Delta `f0d86ab..8025871` against package addendum J (tasks branch; R34/R35 in `RECOVERY_EXECUTION_PROPOSAL`):
- **R34:** `_value_scope`/`_value_visible`. The keeper sees money only on rows touching nothing but warehouse buckets; never on a row with a project/subproject.
- **R35:** SiteManager/Technician see the **central** warehouse with prices. New `GET /central-stock/{item}` (`CENTRAL_STOCK_READ_ROLES`, every mode); `_within_member_scope` lets central locations through. It is called only from the read-scope helper (`warehouse_canonical_queries.py:259/278`), so **no write path is widened**.
- **Price history:** `GET /price-history?project_id` (finance everywhere; SM/Tech in-date member projects; keeper 403). Purchases come from canonical receipts plus unlinked Path B invoice lines (FG-17 once); flag `SAME_SUPPLIER_DIFFERENT_PRICE`; best price. Tenant-scoped through `TenantData`.
- **Test expectation edits** (c26b, c26d, c26f, c26h): each widens only to central-warehouse prices for SM/Tech, or hides the keeper's project-row money. **Nothing weakened beyond R34/R35.**

Gates on `8025871`:

| Gate | Result |
|---|---|
| warehouse canonical suites, real Mongo RS, run **per file** with a database cleanup between files | **813 passed, 0 failed** (c20 needs c19's index setup in the same session: 36/36 together; a lone-file failure is a chunking artifact) |
| W0 | 1085/15/50, same 15 |
| A2C | 0/222 |
| A1 | 0/450 |
| frontend tests (c26j, c19, lib, components) | 10 suites / 111 passed |

`1b3f182` (after) adds only a test for R37 (warehouse "фира" value visible to the keeper) in `c26j`; it will be run with the next #55 round.

Environment, resolved: `mongod` now runs with `wiredTigerFileHandleCloseIdleTime=15`, `CloseMinimum=200`, `ScanInterval=5`. The per-file run then took c26e 78 s instead of 828 s, and no crash followed. Three earlier crashes ("Too many open files") were caused by the 600 s default idle-handle time under thousands of test databases.


## #72 W0-04-C01 @ `13dd8d7` — 2026-11-07 ~10:05 UTC — PASS (root)

`23d0bc9` (F-69-01): `begin_idempotent` retakes a FAILED key with `update_one({id, status: FAILED}, {$set: STARTED, attempt_token})`; only the caller whose token is in the record afterwards gets STARTED. The others get the new **`IDEMPOTENCY_IN_PROGRESS`** (or a replay if the winner already completed). Callers updated in #72: `RecoverableWrite` → 409, `legacy_migration._begin` and `merge._run` → `MasterDataRefused`.

| Probe / gate | Result |
|---|---|
| new `w004/probe_w004_retake_cas.py`: FAILED key, 6 concurrent retakes × 10 rounds | **exactly 1 started + 5 in_progress every round**, FAILS none |
| x56 tx race | 120 stored, `verify_chain` True |
| w004_c01 | FAILS none |
| fg57 | FAILS none (G4: 1 of 6 STARTED) |
| `test_w0_04_c01` + `test_auth_0*`, real Mongo | **149 passed** |
| W0 | 1093/15/69, same 15 |
| A2C | 0/212 |
| A1 | 0/428 |
| R0 | **814** |

### RETAKE-1 — BLOCKING for the merge of #72@13dd8d7 with #73 and #75 (PROVED)

The new return value breaks callers that only test for DUPLICATE:
- `pay_runs.create_pay_run` (#73/#75, `pay_runs.py:~904-916`)
- `labor_quantities._idempotent` (#75, `:~93-105`)

Both treat any non-DUPLICATE state as "go", so an IN_PROGRESS loser performs the write.

| Probe | Tree | Result |
|---|---|---|
| `lab01/test_probe_lab01e_payrun_r29.py::test_p5_retake_of_failed_key` (key FAILED, then 6 concurrent identical POST /pay-runs) | merge #73 `ca81286` + #72 `13dd8d7` (`ownership.py` resolved: both lists) | codes [200, 200, 200, 409, 409, 409], **3 pay runs** |
| `lab01/test_probe_lab02_retake.py::test_r1` (FAILED approve key, then 6 concurrent identical approves) | merge #75 `70cb594` + #72 `13dd8d7` | codes [200 ×4, 409 ×2], **4 approval records** |

Other callers are safe:
- #70 `finance.py` (both callers proceed only on STARTED, `f71dce2`);
- #69 `MoneyWrite` and #74 `KeyedWrite` (through `RecoverableWrite`, 409);
- `permissions/sync.py` (records a failure only).

Fix options:
- (a) #73/#75 proceed **only on explicit `STARTED`**, the #70 pattern.
- (b) More robust for every future caller: #72 returns the losers as `DUPLICATE` with `prior_status=STARTED`, which every existing caller already maps to 409.


## #70 PAY-01-C01-E @ `f71dce2` — 2026-11-07 ~10:10 UTC — PASS

`cfb9d74` (F-70-01/F-70-02):
- `delete_payment` locks every leg's payment row (sorted), **re-reads under the lock**, then begins the key and reverses.
- Cancel takes the payment lock, then the invoice lock (the order allocate uses).
- `_audit_once` with `store.has_event(action, entity_id)` under the payment lock records the reversal/cancel event exactly once, on the normal path and on recovery (`_repair_pair` now completes the audit).

`8cf0f4a`: both `begin_idempotent` callers in `finance.py` proceed only on explicit STARTED; anything else → 409.

| Probe / gate | Tree | Result |
|---|---|---|
| new `pay01/probe_pay01_e_alloc_vs_reverse.py` (allocate 60 ∥ reverse, 12 rounds, both orders) | merge `f71dce2` + #72 `13dd8d7` | 12× (alloc 409, rev 200); **never a reversed payment with an active allocation; exactly 1 reversal AuditEvent each**; FAILS none |
| `probe_pay01_c01a_source_module` (M1–M7) | same | FAILS none |
| `probe_pay01_d5_race` | same | FAILS none |
| `probe_pay01_fg50` | same | FAILS none |
| `tests/test_pay_01_*.py`, real Mongo | same | **588 passed** |

merge-tree:
- with #72 `13dd8d7`: clean (`store.py` auto-merges; `has_event` sits after #72's functions);
- with main: clean;
- with #69: A1 inventory only.

Interrupt-before/after-audit recovery is covered by the PR's `test_pay_01_c01_e_serialisation` (part of the 588); not separately probed.


## #75 LAB-02 @ `70cb594` (after `789bbd9`) — 2026-11-07 ~10:10 UTC

- `a0d1ca9`/`70cb594` are frontend toasts and Bulgarian texts. The backend diff (5 files) only translates `detail=` messages and drops internal FLOW codes from user texts; there is **no logic change**.
- RETAKE-1 applies (above).
- LAB02-1 stands.
- The real-Mongo LAB-02 suite, R0 and PM-01 for #73/#75 will be run in isolation at the fix round.


## #73 LAB-01-J @ `6ac47d0` and #75 LAB-02-B @ `7156140` — 2026-11-07 ~10:30 UTC

**#73 FG-91:**
- `report_corrections.report_in_payroll` decides "in payroll" from the **Pay Run lines**: `employee_rows.day_cells.report_ids`, `day_cells.reports.report_id` and `selected_report_ids`, matching the report id and `<report>_<entry>` for the old format, on runs that are confirmed/paid/paying/payment_failed/reopened or have a `paid_at`. `payroll_status` is still honoured too.
- `authorize_report_edit(..., tenant=)` refuses with 409 on PUT `/daily-reports`, batch-save, PUT `/technician/draft`, and (on #75) `enter_quantity`.
- The fields exist on frozen runs (`pay_runs.py:541/737/802`).

**#75 FG-93/FG-94:**
- approve/classify call `refuse_if_in_payroll` (409);
- classify on a draft → 409;
- the FG-92 regression tests are added.

Gates:

| Gate | #73 `6ac47d0` | #75 `7156140` |
|---|---|---|
| `tests/test_lab_0*.py`, real Mongo, run in isolation | 87 passed, 1 skipped (fg85, needs #72) | 118 passed, 1 skipped |
| W0 | 1085/15/50, same 15 | same |
| A2C | 0/207 | 0/208 |
| A1 | 0/420 | 0/422 |
| R0 | (covered by #75) | **814** |
| PM-01 | (covered by #75) | 6 passed |

**RETAKE-1 still open on both heads**: `pay_runs.create_pay_run` and `labor_quantities._idempotent` still only test DUPLICATE. LAB02-1 is still open.


## #74 OH-01-B @ `39eafdf` — 2026-11-07 ~10:40 UTC — PASS

`cee2023`:
- **OH74-01:** compute freezes `allocation_basis` (per project, both methods) in the snapshot. Allocate uses ONLY the frozen basis and the snapshot total; `_split_cents` uses largest remainder in whole cents, plus an explicit `unallocated` remainder, and the sum is checked before any write (`ALLOCATION_TOTAL_MISMATCH`). A pre-OH74 snapshot allocates from the current source only if its total is unchanged; otherwise 409 `SNAPSHOT_SOURCE_CHANGED`.
- **OH74-02:** the archive stores `archive_operation_key`, so the same key resumes an interrupted archive and finishes the audit (with `legacy_audit` as its own step).

`39eafdf`:
- **R38:** a recompute marks the old allocations `recalculating` (they keep counting; P&L/financial results show `overhead_recalculating` and the label "преизчислява се") until the new snapshot's allocation supersedes them period-wide.
- **FG-98:** startup indexes every Tenant Registry database.

Probes `oh01/test_probe_oh01.py` (O9 updated for R38; new O12–O14), real Mongo RS:

| Probe | Result |
|---|---|
| O1, O2, O5, O7, O8, O10, O11 | unchanged, pass |
| O9 (R38) | after S2 compute, S1's 2 rows stay current; allocate S1 → 409 `SNAPSHOT_SUPERSEDED`; allocate S2 → total 400 = snapshot |
| **O12** (Codex: +6 person-days and +90 h on project B **after** the snapshot) | PersonDays 200, total 400.00; Hours 200, total 400.00 (unallocated 0). **Never 200 %** |
| **O13** `_split_cents` | 100 over 3 → 33.34/33.33/33.33; 0.05 over 3 of a 4-basis → 0.02/0.01/0.01 + 0.01 unallocated; 1234.57 → 411.11/823.46. Exact sums |
| **O14**: the audit step crashes after the archive write, then the same key is retried | first: crash, status archived; retry → **200, exactly 1 archived event**; another key → 409. PROVED |

Gates on `39eafdf`:

| Gate | Result |
|---|---|
| OH-01 tests | **140 passed** |
| W0 | 1085/15/50, same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | **814** |
| PM-01 | 6 passed |
| `yarn build` | compiled |
| merge-tree #73 | clean |
| merge-tree main / #72 | `server.py` (startup blocks) |
| merge-tree #69 | `overhead.py` + matrix (the known compute-signature resolution) |


## #69 SEC-01-C03-C @ `6af0e98` — 2026-11-07 ~10:45 UTC — PASS

- **F-69-01:** `MoneyWrite.unique(doc)` sets `_id` = the key-derived id and `insert_once()` swallows only a duplicate on `{_id}`. Two attempts of one key (resumed or concurrent) can never both insert, even without the idempotency index. It replaces the racy `needs_insert` read, and is used in labor entry, material waste, full_cost, subcontractors, reports.
- **F-69-02:** R29 (428) on labor sync, package recompute, overhead compute; the computed answer is stored as a `json:` result reference and replayed.

Gates:

| Gate | Result |
|---|---|
| `tests/test_sec_01_*.py`, enforce, real Mongo | **30 passed** |
| `sec01/probe_sec01_c01_r16.py` | FAILS none |
| `sec01/probe_sec01_c02_payments.py` | P2/P3/P4 as before; the "P1" entry is the known stale label (keyless → 428 now) |
| W0 | 1085/15/50, same 15 |
| A2C | 0/207 |
| A1 | 0/420 |
| R0 | **814** |
| PM-01 | 6 passed |

merge-tree:
- main, #72, #71: clean;
- #70: A1 inventory + `idempotency.js`;
- #73: `labor_smr.py` (known LAB01-M1);
- #74: `overhead.py` + matrix (known).

With #72: `MoneyWrite` goes through `RecoverableWrite`, which maps `IDEMPOTENCY_IN_PROGRESS` to 409, so it is safe.


## RETAKE-1 / LAB02-1 closed — #72 @ `3606766`, #73 @ `3107ba0`, #75 @ `ba08ab5` — 2026-11-07 ~11:10 UTC

**#72 `a444095`:** the loser of a FAILED retake now returns `{status: DUPLICATE, prior_status: STARTED, detail: IDEMPOTENCY_IN_PROGRESS}`, which every caller already refuses. The resuming callers check `detail` **first** and refuse, never resume: `RecoverableWrite` → 409; `legacy_migration._begin` and `merge._run` → `MasterDataRefused` (before `merge`'s `resumed = DUPLICATE` logic).

**#73 `3107ba0` / #75 `59fd3a7`:** `create_pay_run` and `labor_quantities._idempotent` write only on an explicit `STARTED` (defence in depth).

**#75 `5c0a9ed`:** unique partial indexes `one_approved_per_line` (`labor_quantity_approvals`, status approved) and `one_active_per_line` (`labor_line_classifications`, status active) on (org, report, entry, version). Created at startup and lazily; a `DuplicateKeyError` on insert → 409.

Trial merges with #72 `3606766` (the `ownership.py`/`server.py` conflicts resolved by keeping both sides):

| Tree | Probe / suite | Result |
|---|---|---|
| #73 `3107ba0` + #72 | `lab01e::test_p5_retake_of_failed_key` × 3 | [200, 409 ×5], **1 pay run** each run |
| | `tests/test_lab_0*.py` | **91 passed** (fg85 runs) |
| #75 `ba08ab5` + #72 | `lab02_retake::test_r1` × 3 | [200, 409 ×5], **1 approval** each run |
| | `tests/test_lab_0*.py` | **129 passed** |
| #74 `26a135a` + #72 | new `oh01::test_o15_retake_of_failed_allocate_key` | [200, 409 ×5], **1 allocation batch** |
| | OH-01 tests | 140 passed |
| #70 `f71dce2` + #72 | `tests/test_pay_01_*.py` | **588 passed** |
| #69 `ccab244` + #72 | `tests/test_sec_01_*.py` | **30 passed** |

#72 `3606766` alone:

| Probe / gate | Result |
|---|---|
| `retake_cas` | 1 started + 5 duplicate × 10 rounds |
| x56 | 120 stored, chain True |
| fg57 | FAILS none |
| W0-04 + auth tests | **150 passed** |
| W0 | 1093/15/70, same 15 |
| A2C | 0/212 |
| A1 | 0/428 |
| R0 | **814** |

#75 `ba08ab5` alone:

| Probe / gate | Result |
|---|---|
| `lab02::test_q1` × 3 (4 concurrent approvals, different keys) | [200, 409 ×3], **1 approved record**, earned 550 |
| Q2 / Q3 / Q4 | pass |
| `test_lab_0*` | 128 passed, 1 skipped |
| W0 | same 15 |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | **814** |
| PM-01 | 6 passed |

**RETAKE-1 closed (PROVED). LAB02-1 closed (PROVED).** PR comments on #73 and #75 are updated to "resolved".


## #71 SEC-02-G @ `c0247e8` — 2026-11-07 ~11:30 UTC — PASS

- **SEC71-01:** `POST /budget-freezes/{project_id}` is now `@strip_for_budget_view`. `finance_read.budget_view_forbidden` drops `BUDGET_VIEW_HIDDEN_FIELDS` (+ `planned_margin`, `total_sale`) **and** any key matching `sale|price|margin|profit|revenue|markup|commission|final_total` at any depth, on every R20-5B answer and the pulse view. The scanners gained `sale|markup|commission`, and the seed has a non-zero sale/margin package.
- **SEC71-02:** `pulse_paid_workers` counts only workers with a non-zero `labor_cost`, and a worker counts toward an SMR only when it is his only SMR that day. `r31_view` hides at **≤ 1** counted worker (was == 1).

| Probe / gate | Result |
|---|---|
| `tests/test_sec_02_finance_read.py`, enforce, real Mongo (includes Codex's freeze and pulse 160+0 scenarios from comment 6704759986, as tests) | **24 passed** |
| `probe_sec02_c_pulse_derive` | FAILS none |
| `probe_sec02_d_pulse_generate` | FAILS none |
| `probe_sec02_fg15_replay` | FAILS none |
| `probe_sec02_e_narrow_window` (`PROBE_ZERO`) | only the known false positive (planned budget, allowed) |
| W0 | same 15 |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | **814** |
| PM-01 | 6 |

merge-tree:
- main and #69: clean;
- #72: A2B inventory;
- #70: A1 inventory + `idempotency.js`;
- #73: `all_reports`/`labor_smr` + inventory;
- #74: `overhead.py` + matrix.


## #74 @ `26a135a` — 2026-11-07 ~11:40 UTC

- `73a5601`/`26a135a` are evidence only (merge with #69); the code is `39eafdf` (audited PASS).
- Codex reviewed `26a135a` (comment 6705531681, CHANGES_REQUESTED): **OH74-03** (R38 window: the old batch is superseded before the new insert, so readers see 0, no label) and **OH74-04** (archive recovery duplicates the canonical event when the crash lands after the event but before the step is recorded). Codex is the independent reviewer; I do not duplicate them here. OH74-03 is the old D2 gap now in conflict with R38. They will be re-checked at the next head.

**HANDOFF OH-01-C 6-step #69 merge procedure — VERIFIED** on a fresh trial merge `26a135a` + #69 **`ccab244`** (newer than the `6af0e98` the HANDOFF used):
1. `overhead.py`: 3 conflicts, signature `data, _sec01, idempotency_key (one Header), user`; body (b)(c) from #74.
2. The unused `MoneyWrite` import removed; compute has one key reservation.
3. Matrix: theirs, then `--harness` regeneration (`run_meta.json` restored).
4. `merge69_sec01_c03_test.diff` applied.
5. `merge69_sec01_c01_results.diff` applied cleanly. **`merge69_sec01_c03_results.diff` does NOT apply on `ccab244`** (addendum D changed that file), so regenerate with `--harness`, as step 5 says. The regenerated diff matches the committed expectation: the compute rows gain `op.overhead_period_locks`; the 201/409 mix of the `f69_01_interrupted_payment_race` retries is timing-dependent, and the committed expected diff has the same kind of swap.
6. On the merged tree: SEC-01 **30 passed**, OH-01 **140 passed**, PM-01 6 passed, A2C 0/208, A1 0/422.


## #69 SEC-01-C03-D @ `ccab244` — 2026-11-07 ~11:45 UTC — PASS

FG-90: a payment naming an act requires a **confirmed** act of the package (404/409). `_reserve_within_certified` is a single conditional `update_one` with `$expr` (committed + amount ≤ certified + 0.005), done as the **first** `mw.step("reserve")` per key; over the cap → 409 `PAYMENT_EXCEEDS_CERTIFIED`. Two different-key payments cannot both pass.

| Gate | Result |
|---|---|
| `tests/test_sec_01_*.py` (incl. the FG-90 tests) | **30 passed** |
| W0 | same 15 |
| A2C | 0/207 |
| A1 | 0/420 |
| R0 | **814** |

**FG90-N1, LOW/MEDIUM (code reading):** `committed_paid_total` is only ever incremented; nothing decrements it. If a subcontractor payment is reversed or cancelled, its reservation is never released, so later legitimate payments up to the certified total get 409. This fails closed, with no money loss. A reservation whose payment never completes (crash, never retried) also stays.


## #55 @ `1b3f182` — PASS

R37 test only: the keeper sees the value on a warehouse "фира" and not on a project one. `c26j` file: **58 passed** (real Mongo).


## #72 @ `90a582b` — PASS

`3606766..90a582b`: `docs/evidence/PM-01/matrix.csv` only, +48 rows:
- `POST /api/auth/forgot-password`: 24 cells, 200, wrote=yes;
- `POST /api/auth/reset-password`: 24 cells, 400, wrote=yes.

Both are unauthenticated #56 routes that record tokens and auth events even on a refusal; plus `run_meta.json`. PM-01 on `90a582b`: **6 passed**.


## #74 OH-01-D @ `6a4ac5b` — 2026-11-07 ~11:55 UTC — FINDINGS (1 blocking)

- **OH74-03 fix:** a new allocation batch is inserted **staged**, then published by one atomic write of the period pointer (`overhead_period_locks.current_allocation_batch_id`, under the period lock). `current_allocations()` is used by project P&L, financial results, snapshot detail and `/overhead/allocations`. Superseding is history only.
- **OH74-04 fix:** `audit_overhead_event_once` / `legacy_audit_once` check for an existing event or row of this operation key before writing. This is safe because only one attempt of a key runs at a time.

Probes, real Mongo RS:

| Probe | Result |
|---|---|
| Codex's own two probes from comment 6705531681 (`oh01/test_codex_oh74_recompute_interruptions.py`, verbatim logic) × off/shadow/enforce | **6/6 pass**: reader during the switch → 300 labelled "преизчислява се"; crash after the canonical event + same-key retry → 200, 1 event |
| my O1, O2, O5, O7, O8, O9, O11, O12, O14, O15 | all pass |
| **O16** `test_o16_reader_interleaved_with_publish`: reader paused **between its row read and its pointer read**, while a real allocate completes | P&L(A) **300 → 0 → 600**. FAIL |

**OH74-05, BLOCKING, PROVED:** `current_allocations()` reads the rows, then the snapshots, then the pointer. An insert plus publish in between leaves the reader with rows lacking the new batch and a pointer naming it, so it keeps nothing and reads 0. That is exactly the invariant OH74-03 claims.
- **Fix:** read the pointer(s) first. The read is then consistent, because old batches are never deleted and the staged insert precedes the publish.
- PR comment 6703213443 updated (blocking).

Low note: rows that carry an `allocation_batch_id` but have no published pointer (allocated by an intermediate draft head) are no longer counted. No production data has them; all #74 heads are unmerged.

Gates on `6a4ac5b`:

| Gate | Result |
|---|---|
| OH-01 tests | **194 passed** |
| W0 | same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | **814** |


## main moved: `0f870c3` (Merge PR #56 AUTH-01/02, approved by Krum 07.11.2026)

Every open head is now behind main. merge-tree against `0f870c3`:

| PR | Conflicts |
|---|---|
| #69, #70, #71 | clean |
| #72 | clean, already based on main |
| #55 | `tenancy/data_access.py` + A2B inventory |
| #73 | `tenancy/ownership.py` |
| #74 | `server.py` |
| #75 | `ownership.py` + `server.py` |


## #55 5C-C26k @ `4ed6077` — 2026-11-07 ~12:30 UTC — PASS

- **Fix:** `ledger_invoice_line_links` also projects the server-bound `project_id`. In `path_b_split._is_to`, a `subproject` destination matches through that `project_id` (FG-38 `_bind_subproject_parent`), a `project` destination through `location_id`, and nothing else.
- **Test** `c26k`: Codex's reproduction (L 10@10 → P; 10@10 into S with `invoice_line_id`=L), plus partial (4 of 10) and unlinked, × subproject/project, on 10 reports, live and after rebuild ×2.

| Gate | Result |
|---|---|
| Warehouse suite per file, enforce, real Mongo RS | **40 files, 822 passed**, 0 failed; c26k **6 passed** |
| W0 | same 15 |
| A2C | 0/222 |
| A1 | 0/450 |
| R0 | **814** |

Low note: a legacy canonical subproject row without `project_id` would not match and could still count twice. There are none, because #55 is unmerged and FG-38 binds `project_id` on every subproject movement.


## #70 PAY-01-C01-F @ `0713a81` — 2026-11-07 ~12:40 UTC — FINDINGS (1 blocking)

The F-70-03 code was reviewed: `delete_payment` takes all original legs (status ≠ reversal) under sorted locks, puts the URL leg first, runs `_reverse_one` or `_repair_pair` per leg, and completes the key after both legs. Codex's leg-2 interruption points (before and after the row, before and after the audit) are covered by the 30 new tests.

**PAY70-04, BLOCKING, PROVED** by `probes/pay01/test_probe_f703_leg2_unmarked.py` (mongomock + real, off/shadow/enforce):

| Case | Result |
|---|---|
| **N1**: interrupt before the 2nd `_reverse_one` (L1 reversed with row and event; L2 never marked), then a **new key** on L1 | **409 "already reversed"**; L1 (`reversed`, 1 row); **L2 (active, 0 rows)**. FAIL 6/6 |
| N2: the same key retried | 200, both legs reversed. pass |
| N3: a new key on L2's URL | 200, both legs reversed. pass |

- **Cause:** the `status == REVERSED and not retry` branch only runs `_repair_pair`, which is a no-op for an unmarked leg, and then refuses.
- **Reachable from the UI:** `PaymentsPage.js:254` creates a fresh key on every click, so the user's second click after a 500 is N1.
- PR comment 6696777161 updated (blocking).

Gates on `0713a81`:

| Gate | Result |
|---|---|
| `test_pay_01_*`, real Mongo | **618 passed** |
| probes `e_alloc_vs_reverse` (12/12 alloc 409 + rev 200), `d5_race`, `c01a_source_module`, `fg50` | FAILS none |
| W0 | same 15 |
| A2C | 0/206 |
| A1 | 0/418 |
| R0 | **814** |
| merge-tree #72 `3606766` / main | clean |


## #73 LAB-01-L @ `b5384cd` and #75 LAB-02-C @ `c34480b` — 2026-11-07 ~11:55 UTC — FINDINGS (1 blocking each)

**#73 FG-99:**
- `reset_daily_report` calls `authorize_report_edit`, which applies:
  - the R36 roles: Admin, Owner, or the SiteManager of every project of the report;
  - the payroll lock decided from pay-run lines (LAB-01-J).
- Reset handles both date formats.
- Reset writes a `daily_report.reset` AuditEvent with before/after.

**#75 FG-101:**
- A second approval of the same version without `replaces_approval_id` naming an active record → 409 `ALREADY_APPROVED`; a stale id → 409.
- The void is a CAS on `modified_count`.
- `pending` exposes `approval.id`, and the UI sends it back.
- Two existing tests now send `replaces_approval_id`. This follows the design change; nothing is weakened.

**PM73-01 / PM75-01, BLOCKING, PROVED:** `test_pm_01_permission_matrix::test_a_fresh_real_mongo_run_reproduces_the_committed_matrix` fails.
- **Reset cells, 18, on both PRs:** `POST /daily-reports/{id}/reset` for requester / technician / accountant / warehousekeeper / driver / viewer: committed 403, fresh **404**. The role check moved after the report lookup. Low side effect: an existence oracle within the tenant.
- **Pay-run cells, 6, #73 only:** `POST /pay-runs` owner/admin, 400 → **428**. Already red at `3107ba0`, verified by running PM-01 there: LAB-01-E made the key mandatory and the matrix was never regenerated. Earlier rounds did not run PM-01 on #73; that was my miss.
- **Fix:** a role pre-check before the lookup (or accept 404), then `--harness` regeneration.
- PR comments 6704503510 (#73) and 6705198745 (#75) updated.

| Gate | #73 `b5384cd` | #75 `c34480b` |
|---|---|---|
| `test_lab_0*`, real Mongo | 99 passed, 1 skipped | 140 passed, 1 skipped |
| probes | `lab01h_r36` 3 pass; `lab01f` 5 pass; `lab01e` needs #72 (P1 8 runs alone, as before) | `lab02` Q1 [200, 409×3], 1 approved; Q2–Q4 pass; `lab02_retake` R1 pass; `lab01h` 3 pass |
| W0 | same 15 | same 15 |
| A2C | 0/207 | 0/208 |
| A1 | 0/420 | 0/422 |
| R0 | 814 | 814 |
| PM-01 | **1 failed (24 cells)** | **1 failed (18 cells)** |
| trial merge + #72 `90a582b` (= main + #72) | `ownership.py` resolved; `test_lab_0*` **100 passed**; lab01e P1 1 run, P3 400, P4 503, P5 1 run | `ownership.py` / `server.py` / `run_meta` resolved; `test_lab_0*` **141 passed**; Q1, R1 pass |

Probe fix: `lab01e` P3 now prints with `.get` (the corrections rows no longer carry `period_start`); the result is 400, as before.

Low notes:
- The reset AuditEvent is written after the status write, with no key, so a crash leaves a reset with no event.
- A SiteManager author can reset their own report (R36-consistent; four-eyes holds at approval).
- An FG-101 correction voids before it inserts, so a crash leaves the line with no active approval until a reload and re-approval (this predates FG-101).


## #70 PAY-01-C01-G @ `4b745f1` — 2026-11-07 ~12:10 UTC — PASS (PAY70-04 closed)

`delete_payment`, in the `REVERSED and not retry` branch:
- every leg that still counts is reversed (with the original reason), unless it has an active allocation, which gives 409 `TRANSFER_LEG_ALLOCATED`;
- then `_repair_pair` runs for every leg;
- then 409 `PAYMENT_ALREADY_REVERSED` with the repaired state (`reversals`, `completed_legs`).

`probes/pay01/test_probe_f703_leg2_unmarked.py`, mongomock + real, off/shadow/enforce: **24/24**.

| Case | Result |
|---|---|
| N1, new key on L1 | 409; both legs `reversed`, 1 row each |
| N2, same key | 200 |
| N3, new key on L2 | 200 |
| **N4**, new: remaining Inflow leg allocated to an Issued invoice, then a new key on L1 | 409 `TRANSFER_LEG_ALLOCATED`, nothing written; cancelling the allocation reverses the leg (1 row, 1 event) |

| Gate | Result |
|---|---|
| `test_pay_01_*`, real Mongo | **630 passed** |
| probes `e_alloc_vs_reverse`, `d5`, `c01a`, `fg50` | FAILS none |
| W0 | same 15 |
| A2C | 0/206 |
| A1 | 0/418 |
| R0 | **814** |
| merge-tree #72 `90a582b` | clean |


## #55 5C-C26l @ `c31c09a` — 2026-11-07 ~12:15 UTC — FINDINGS (1 blocking)

The fix, for Codex F-55-C26-02:
- `_check_invoice_line_delivery` (in the binding phase, held until the rights check): a linked direct delivery must go to a project L is allocated to (422 `INVOICE_LINE_PROJECT_MISMATCH`), and must not exceed L's remaining allocation to that project; a same-key replay is exempt.
- `path_b_split` handles `to_other` / `excess_other`.
- `project_link_conflicts` covers the destination side.
- `PATH_B_LINK_PROJECT_CONFLICT` is raised once per project.

**WH55-C26L-1, BLOCKING, PROVED** by `probes/wh55/test_probe_c26l_link_race.py` (real Mongo RS, enforce, 3 rounds × 2 shapes). L = 10 @10, allocated P 5 and Q 5; 6 concurrent linked deliveries of 5, different keys:

| Shape | Accepted | Linked | Cost P/Q (live = rebuild ×2) |
|---|---|---|---|
| 6 → P | **6/6** | P **30** | **300 / 50** |
| 3 → P + 3 → Q | **6/6** | P 15, Q 15 | **150 / 150** |

The delivered sum is read before the transaction, and nothing serialises deliveries of one line. This is the programmer's recorded debt, now proven to over-link and to cost the line 3–3.5×.
- **Fix:** an atomic per-line reservation (conditional `$inc`, as FG-90) or a line lock inside the movement transaction.
- PR comment 6695125557 updated (blocking).

| Gate | Result |
|---|---|
| c26l | **11 passed** (Codex repro 422; legacy conflict counted once, live and after rebuild ×2; warning on both projects once) |
| other c26* | all pass (c26e 272) |
| W0 | same 15 |
| A2C | 0/222 |
| A1 | 0/450 |

The full warehouse suite and R0 will run with the fix head.


## #76 SUB-ADV-01 @ `f42da33` (on #69 `ccab244`) — 2026-11-07 ~12:35 UTC — PASS

Code reviewed (`subcontractors.py`, `catalog.py`, `finance.py`):
- **Advance:** `POST /subcontractor-packages/{id}/advances` uses `require_money_write(..., roles=Owner/Accountant)` before any read. Admin is taken out of the canonical set for this one action.
- **Writes:** one Outflow `finance_payments` row (FLOW-006), plus a `subcontractor_payments` row with `kind=advance`, plus the `advance_total` step and an audit entry, all under `MoneyWrite` with key-derived ids and `insert_once`.
- **Deduction:** done in the same atomic `$expr` update as FG-90. Three conditions:
  - committed + amount + deducted ≤ certified;
  - deducted ≤ outstanding advance;
  - deducted on the act ≤ the act's certified total.
- **Legacy delete:** `DELETE /finance/payments` on an advance row → 409 `SOURCE_MODULE_REVERSAL_REQUIRED`.

`probes/subadv/probe_subadv01.py`, real Mongo RS, off/shadow/enforce, on `f42da33` alone **and** on the trial merge + #72 `90a582b` (`wtm7672`, only `run_meta.json` conflicted): **FAILS none**.

| Case | Result (each mode) |
|---|---|
| S1: advance 1000, 6 concurrent deductions of 400 on act1, different keys | [201 ×2, 409 ×4]; deducted 800; act = package = 800; 2 entries |
| S2: 6 concurrent payments of 100 + 400 deducted | [201 ×2, 409 ×4]; deducted 800 = sum of rows; committed 1000; paid 200 |
| S3: act1 paid 3000 cash, act2 200 deducted | committed 3200; ordinary 0.01 → 409; a further deduction → 409; advance outstanding 800 stays visible |
| S4: advance interrupted after its steps, same-key retry | 500 → 201; 1 row, 1 ledger row, `advance_total` 1000, 1 audit |
| S5: deduction interrupted, same-key retry | 500 → 201; deducted 300 once, 1 act entry, 1 audit |
| S6: tenant B accountant on A's package | 404, nothing written |
| S7: 6 concurrent requests, one key | [201, 409 ×5]; 1 row, 1 ledger row, total 1000 |

| Gate | `f42da33` | + #72 `90a582b` |
|---|---|---|
| `test_sub_adv_01` + `test_sec_01_*`, real Mongo | 38 passed | 38 passed |
| PM-01 | 6 passed | 6 passed |
| W0 | same 15 (1085/15/50) | same 15 (1093/15/70) |
| A2C | 0/207 | 0/215 |
| A1 | 0/420 | 0/434 |
| R0 | 814 | 814 |

merge-tree:
- main: clean.
- #74: `overhead.py` + matrix (the known #69 × #74 conflicts).
- **#70 `4b745f1`:** `finance.py` (NEW: the advance guard in `delete_payment`, which #70 rewrites), the A1 inventory, and `idempotency.js` with its test (known from #69). #70's `source_module()` already treats `subcontractor_payment_id` as "subcontractor", so take #70's `delete_payment`.

Debts and notes:
- **D1 (reversal after #70):** confirmed open. On #76 alone (base without #70), `DELETE /finance/invoices/{inv}/payments/{alloc}` still hard-deletes a ledger row whose last allocation is removed (`finance.py:1223`). This holds for every module payment, and #70 C01A-1/FG-45 closes it, so #76 should merge after #70.
- **D2:** no cap of the advance against the contract value. Confirmed; it is a business decision.
- **D3:** `project_pnl`, `project_financial_results`, `revenue_snapshot` and `cashflow_forecast` sum `subcontractor_payments` amounts, so the advance is counted once as cash. The ledger row has no category, so `project_pnl`'s "Други" branch does not count it twice. Accrual view: not changed, as stated.
- **Note:** a deduction without cash is allowed for Admin (Owner/Admin/Accountant, R14), as the HANDOFF says. Krum to confirm whether R39 also covers it.
- **Note:** like FG90-N1, a reservation that is never followed by its payment is never released. Retries resume it with the same key.

No blocking finding, so no PR comment, per the one-comment rule.


## #55 5C-C26l-K @ `43477d8` — 2026-11-07 ~12:50 UTC — PASS (WH55-C26L-1 closed)

**The fix:** inside the movement transaction, `_lock_invoice_line` upserts `warehouse_ledger_counters` `_id=invoice_line_lock:<org>:<line>` with `$inc`, then `_check_invoice_line_delivery(session=)` re-decides on the transaction snapshot. Concurrent deliveries of the same line write-conflict, and `with_transaction` re-runs the loser.

`probes/wh55/test_probe_c26l_link_race.py` (now asserts exact outcomes), `ROUNDS=10`, × off/shadow/enforce:

| Case | Result |
|---|---|
| 6 → P | 1 accepted, P 5 linked, cost 50/50 live and after rebuild ×2 |
| 3P + 3Q | 1 + 1 accepted, 50/50 |
| **Total** | **60/60 pass** |
| new `test_crash_after_lock_leaves_nothing` | the crash surfaces as `AuditChainWriteError`, with 0 lock documents and 0 linked rows; the next delivery is OK (1 row, lock `tenant_id` = org), cost 50 |

**Hot spot:** one document per line, contended only by deliveries of the same line. A WriteConflict aborts and retries, never waits, so it cannot deadlock. The lock value is never read as data, and `rebuild_from_ledger` / cost readers never touch it. It is in the per-tenant database via TenantData.

| Gate | Result |
|---|---|
| warehouse suite per file, enforce, real RS | **42 files, 896 passed**, 0 failed; includes c26l with Codex's repro |
| W0 | same 15 |
| A2C | 0/222 |
| A1 | 0/450 |
| R0 | **814** |

Process note: the #72 sentinel probe (its own throwaway databases) ran once while this suite was in progress. Nothing failed.


## #72 W0-04-C01 F-72-01 @ `cb5d061` — 2026-11-07 ~12:55 UTC — PASS

**The fix:**
- `AuditIndexError` and its subclasses carry `code` + `ref` and name only the database, collection and index (field names).
- `AuditIndexDuplicates` is raised `from None`, with a report that has no `keyValue` or `errmsg`.
- The lazy guard uses `safe_reason()` with fixed sentences.
- `IdempotencyConflict(action)` carries no key.
- `AuditChainContention` carries no tenant.
- The three `MasterDataRefused` messages are key-free, also `from None`.

**New probe `probes/w004/probe_f7201_sentinels.py`:** sentinels are planted as key, tenant and reservation id, and every path is driven for real on RS:

| Path | `cb5d061` | `90a582b` (control) |
|---|---|---|
| L1 startup duplicates | clean | **LEAK** |
| L2 lazy guard (create) | clean | **LEAK** |
| L3 lazy guard (no create) | clean | clean |
| L4 conflict | clean | **LEAK** |
| L5 contention | clean | **LEAK** |
| L7 fail-closed without index | clean | **LEAK** |
| L6 real `ErrorHandlerMiddleware` /dup | clean | **LEAK** |
| L6 /lazy | clean | **LEAK** |
| L6 /conflict | clean | **LEAK** |
| whole log | clean | **LEAK** |

The probe catches the leaks on the control and finds none on the fix. Fail-closed holds: without an index → `IdempotencyUnprotected`.

| Gate | Result |
|---|---|
| retake CAS × 10 rounds | 1 started + 5 duplicate each |
| W0-04 + auth + W0-03 master data, real Mongo | **296 passed, 0 skipped** |
| W0 (DB-free) | 1093/15/76, same 15; the +6 skips are the new real-only F-72-01 tests, which ran above |
| A2C | 0/212 |
| A1 | 0/428 |
| R0 | **814** |
| PM-01, real | 6 passed |

merge-tree with #69 `3fb55f2`, #70 `4b745f1`, #73 `4da2ee6`, #74 `45178ac`, #75 `ef16a16`, #55 `43477d8`, #76 `f42da33`: only the known `ownership.py` / `server.py` / `data_access.py` / A2B / `run_meta` conflicts. #70: clean.

Low observation: the successful startup INFO line names each tenant database (operator config, not data). Not an F-72-01 class leak.


## #73 @ `4da2ee6` / #75 @ `ef16a16` — 2026-11-07 ~13:05 UTC — PASS (PM73-01 / PM75-01 closed)

`reset_daily_report`:
- a role outside `RESET_ROLES` (Admin/Owner/SiteManager) → 403 before the lookup;
- a SiteManager on a missing report → 403.

Matrix: #73 regenerated by the harness (6 pay-runs cells, 400 → 428); #75 changed 0 cells.

| Gate | #73 `4da2ee6` | #75 `ef16a16` |
|---|---|---|
| PM-01 with `W0_03_REAL_MONGO_URL`, `-rs` | **6 passed, 0 skipped** | **6 passed, 0 skipped** |
| reset row | 6 roles 403 × 3 modes; owner/admin 404 | same |
| `test_lab_0*` | 107 passed, 1 skipped | 148 passed, 1 skipped |
| W0 | same 15 | same 15 |
| A2C | 0/207 | 0/208 |
| A1 | 0/420 | 0/422 |
| R0 | 814 | 814 |
| + #72 `cb5d061`: lab | 108 passed | 149 passed |
| + #72 `cb5d061`: probes | lab01e P1 1 run, P3 400, P4 503, P5 1 run | Q1 1 approved, R1 1 approval |
| + #72 `cb5d061`: PM-01 | 6 | 6 |

**PM-01 cross-check (orchestrator's ask):** every PM-01 run I did today passed `W0_03_REAL_MONGO_URL` explicitly. Each took about 145 s, which is the real fresh-run test, and none reported skipped. The #73 `b5384cd` failure itself came from that real test.


## #74 OH-01-E @ `45178ac` — 2026-11-07 ~13:40 UTC — PASS (OH74-05 closed)

- **`612d026`:** `_read_current_pointers()` reads all published pointers first, then the rows. The no-pointer legacy rule no longer reads `superseded_by`; main never wrote that field.
- **`8524f7d` (FG-89):** every profit view reads `project_overhead_current()`. `/overhead-allocation/compute` is a read-only projection. Nothing reads or writes `project_overhead_alloc` / `overhead_actual_allocated` (grep over the backend and the frontend).

Probes, real RS (`probes/oh01`):

| Probe | Result |
|---|---|
| O16 | **300 → 300 → 600** (was 0) |
| **O17** (new: reader frozen right after the pointer read, full allocate publishes) | 300 → 300 → 600 in off/shadow/enforce |
| Codex probes + O1–O15 | pass, **27 passed** in total |

| Gate (alone) | Result |
|---|---|
| OH-01 | 213 |
| W0 | same 15 |
| A2C | 0/205 |
| A1 | 0/416 |
| R0 | 814 |
| PM-01 | 6 (real) |

**Trial merge with #69 `3fb55f2` (current head; `c14fcda` is its ancestor), 7-step OH-01-E procedure:**
- `overhead.py`: 3 conflicts → #69 signature, #74 bodies.
- Unused `MoneyWrite` import removed.
- `merge69_sec01_tests.diff` applies cleanly.
- `--harness` regeneration of PM-01 / C01 / C02 / C03: **C01 and C02 equal the committed expected diffs line for line**. C03 differs only in key-derived ids and the timing-dependent 201/409 race mix, because #69 addendum F changed C03 after the expectation was cut.

| Gate (merged) | Result |
|---|---|
| SEC-01 | 30 |
| OH-01 | 213 |
| PM-01 | 6 |
| W0 | same 15 |
| A2C | 0/208 |
| A1 | 0/422 |
| **R0 × 6** (cleaned DB, after SEC-01 → OH-01 → PM-01, the reported order) | **814 each** |

The programmer's one-off 813 did not reproduce, and no test id was ever captured. There is no evidence of a real failure, and the order dependence is unproven.

Note for Krum: legacy `project_overhead_alloc` rows silently drop out of reports (no backfill), as the HANDOFF says.


## #71 SEC-02-G @ `5af530e` — 2026-11-07 ~13:45 UTC — FINDINGS (1 blocking)

SEC71-03 fixed:
- `money_free_alert` replaces every money alert type with one generic `budget_attention` alert for non-finance callers, the same for > 80 % and > 100 %.
- Any other text holding a number plus % or a currency is replaced.
- It is applied in `strip_money` (labor / material / progress warnings; `/material-warnings` newly decorated), the budget view and the pulse view.
- `test_sec_02_finance_read.py`, real: **25 passed**. The fresh harness covers Codex's stored / generated / on-demand > 80 % and > 100 % × 3 modes: TM generic, finance full.

| Gate | Result |
|---|---|
| W0 | same 15 |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | 814 |
| PM-01 | 6 |

**SEC71-04 (= the programmer's SEC-02-G-D1), BLOCKING, PROVED** by `probes/sec02/probe_sec71_d1_band_bisect.py` (PR fixture: P1, one paid technician; the requester is a SiteManager team member):
- The TM upserts `activity_budgets.labor_budget` (`can_manage_project`) and calls `POST /sites/{P1}/pulse/generate`.
- `budget_snapshot.status` (`on_track` / `warning` / `over_budget` against the **cumulative** labor cost) drives a bisection.
- Result: **6196.90 vs actual 6200.00 in 21 steps, in off, shadow and enforce.** The gap is `burn_pct` rounding.
- That is the single worker's total pay, which R31 hides and SEC-02-E removed from this view. It is not a coarse band.
- **Fix:** drop `status` under the R31 rule (fewer than 2 paid workers), or drop it from the TM pulse view entirely.
- PR comment 6695992847 updated (blocking).

Low: a bare number with no % or currency, in an alert type outside `MONEY_ALERT_TYPES`, passes the regex safety net.


## Round 3 (FLOW Guard pass 11 addenda) — started 2026-11-07 ~14:00 UTC

The orchestrator said FG-108..117 addenda would replace every head, and asked to audit only the next HANDOFF head. The round-2 results at `43477d8`, `cb5d061`, `4da2ee6`, `ef16a16`, `45178ac` and `5af530e` are therefore superseded, and their probes are re-run below.

### #72 @ `04e0a1b` (FG-117) — PASS

- **The change:** `database_ref()` (sha256-12 of the name) replaces the database name in every index error, report and startup log line (`describe_report`). Only the dry-run operator script prints names.
- **Probe:** `probes/w004/probe_f7201_sentinels.py` now also plants a **database-name marker**, and checks the startup INFO line as L8.

| Head | Result |
|---|---|
| `04e0a1b` | all 12 paths clean |
| `cb5d061` (control) | the database-name marker leaks on 8 paths (L1/L2/L3/L7/L8/L6 dup and lazy/log) |

| Gate | Result |
|---|---|
| fail-closed | holds |
| retake × 10 | 1 started each |
| W0-04 + auth + MDM, real | **300 passed, 0 skipped** |
| W0 | same 15 |
| A2C | 0/212 |
| A1 | 0/428 |
| R0 | 814 |
| merge-tree vs every open head | only `run_meta` / `server.py` / `data_access` / A2B (known) |

Low note: an unsalted sha256 of a guessable database name can be matched by trying candidate names; an HMAC with a server secret would avoid that.

### #55 @ `e4d131e` (Addendum L: FG-108 / FG-109) — PASS, 1 MEDIUM

- **FG-108:** every linked supplier receipt (warehouse or direct) bumps the line lock in the transaction. `_check_invoice_line_total` refuses beyond the line quantity with 422 `INVOICE_LINE_QTY_EXCEEDED`. Legacy over-link is counted once, with a warning.
- **FG-109:** `write_unless_linked` decides allocation/qty/unit/price edits and deletes in one transaction on the same lock document, giving 409 `INVOICE_LINE_ALLOCATION_LOCKED`. There is a session-less fallback for deployments without transactions.
- **Static guard:** the anchor moved to the new write, with the same mutation (not weakened).

`probes/wh55/test_probe_c26l_L.py`, real RS:

| Case | Result |
|---|---|
| **M1**: 6 concurrent full receipts (3 warehouse + 3 direct), × 5 | exactly 1 accepted each round (3 × warehouse, 2 × direct); P 100 live and after rebuild ×2 |
| **U1** (WH55-L-1, MEDIUM, PROVED): L fully received as 10 bag (warehouse → P), then a linked direct delivery of 10 **pcs** | **accepted**; P = **200** live and after rebuild ×2, only `PATH_B_LINK_QTY_UNVERIFIED` |

U1 is not blocking: it is flagged and needs a unit mismatch. **Fix:** once the comparable linked quantity equals the line quantity, refuse any further linked receipt.

| Gate | Result |
|---|---|
| warehouse suite per file | **43 files, 968 passed** |
| W0 | same 15 |
| A2C | 0/223 |
| A1 | 0/452 |
| R0 | 814 |
| PM-01 | not on this branch's base (pre-#68) |

PR comment 6695125557 updated (note, no blocker).


### main moved: `7b6da64` (Merge PR #72, Codex PASS, Krum "да")

From now on, trial merges are against main `7b6da64` instead of main + #72.

### #55 @ `d98cead` (WH55-L-1 fix) — PASS, no open findings

- **Fix:** once the comparable linked quantity reaches the line quantity, any further linked receipt in any unit gets 409 `INVOICE_LINE_FULLY_LINKED`. Another unit gets 422 `INVOICE_LINE_UNIT_MISMATCH` up front.
- **U1** (bag/pcs): refused, P **100** live and after rebuild ×2.
- **M1** × 5 × 3 modes: exactly 1 accepted. The C26l-K race shapes pass.
- **Crash probe:** updated, because the lock document is now pre-created outside the transaction by design. It now asserts that the in-transaction bump and the link roll back, and they do.
- **Edited tests:** c26 bypasses only the legacy write; its read assertions (`PATH_B_LINK_QTY_UNVERIFIED`, counted once) are kept. c26j changes only the line unit. Neither is weakened.

| Gate | Result |
|---|---|
| warehouse suite | **43 files, 974 passed** |
| W0 | same 15 |
| A2C | 0/223 |
| A1 | 0/452 |
| R0 | 814 |
| merge-tree main `7b6da64` | `data_access` + A2B (known) |

PR comment 6695125557 updated (resolved).

### #77 ACT-01 @ `c6c7f1c` — PASS, 1 MEDIUM

Code reviewed (`services/client_acts.py`, `permissions/client_act_write.py`, `routes/revenue_expense.py`):
- **Offer line:** resolved on the server (tenant, same project, `Accepted`).
- **Price:** material + labor unit cost. That is the offer model's only price; there is no markup field. A different price → 422.
- **Contracted quantity:** from the offer.
- **Reservation:** a conditional `$inc` per offer line (`client_act_line_totals`) inside the act's transaction. Pre-ACT-01 acts are counted on first touch.
- **Act number:** an `org_counters` counter in the same transaction, plus a partial unique index.
- **R29:** through `RecoverableWrite`.
- **Versions:** Addendum A, with 409 `SUPERSEDED` / `LINEAGE_UNKNOWN`.
- **Rights:** narrowed from "any M2 role" to finance roles. PM-01: non-finance 404 → 403, finance 404 → 428. Nothing widened.

`probes/act01/probe_act01.py`, real RS, off/shadow/enforce, PR seed:

| Case | Result |
|---|---|
| A3: PUT on a Draft 4 → 7 → 2 | acted 7, then 2; a new act of 8 → 201; 0.01 more → 409; totals 10.0000 |
| A4: tenant B line / another project / draft offer | 422, nothing written |
| A5: R29 | 428 / 201 / identical replay / 409; 1 act; **1** `client_act.created` event |
| A1 (collections exist, documents absent): 6 concurrent acts of 4 on L1 (qty 10), × 10 | **2 × 201 + 4 × 409** every round, acted 8 |
| **ACT77-01, MEDIUM, PROVED** — A1 on a **fresh tenant** (`client_act_line_totals` / `org_counters` absent) | **1 × 201 + 5 × 500** every round, × 3 modes |
| ACT77-01 — A2 (fresh `org_counters`), 6 concurrent creates | 2 × 500 |

ACT77-01 detail:
- **Cause:** the transaction implicitly creates the collection, and the concurrent creator gets `OperationFailure: Collection namespace … is already in use` (`TransientTransactionError`), which surfaces as **500** instead of being retried.
- **Integrity holds:** no over-acting, unique numbers.
- **Fix:** create both collections (and their indexes) outside the transaction (cf. #55 `ensure_line_lock`), or retry on the transient label.

| Gate | Result |
|---|---|
| `test_act_01`, real | **80 passed**, 0 skipped |
| W0 | same 15 |
| A2C | 0/213 |
| A1 | 0/430 |
| R0 | 814 |
| PM-01 | 6, real, not skipped |

merge-tree:
- main `7b6da64`: `run_meta` only.
- **#69 `3fb55f2`:** `revenue_expense.py` + PM-01 test.
- **#71 `e90aa5f`:** `revenue_expense.py` + PM-01 test + matrix.

All three guard the client-act routes, so a merge order is needed.

No blocking finding, so no PR comment.


### #71 @ `e90aa5f` (SEC71-04 fix, on `02a1441` FG-111) — FINDINGS (1 blocking)

Addendum F:
- For sites whose cumulative labor cost comes from fewer than 2 paid workers (`single_paid_sites`), the TM pulse view drops `budget_snapshot.status` and the budget alerts.
- `money_alarm_exclusion` hides those sites' money alarms from list, `?severity=`, count, dashboard (and trend), one event, ack and resolve.
- `evaluate` filters `events` / `new_events`.
- `_drop_actual` also drops band keys.

`probes/sec02/probe_sec71_d1_band_bisect.py`, real RS, PR fixture (P1 with one paid technician), requester = SiteManager team member:

| Case | Result |
|---|---|
| pulse bisection | status absent; derives 0.02 vs 6200, off/shadow/enforce. **SEC71-04 closed** |
| `/alarms` list bisection | derives 0.02. Closed |
| 404 oracle: hidden alarm id vs nonexistent id, on GET / acknowledge / resolve | identical 404, same status and body |
| **SEC71-05, BLOCKING, PROVED**: Admin rule `budget > 100 %`, `auto_resolve: true`; TM loops set budget B → `evaluate` → budget 10⁹ → `evaluate`, reading `resolved_events` | **6196.90 vs 6200.00 in 21 steps**. `resolved_events` counts the hidden sites' auto-resolved events |
| known-pay variant (MEDIUM, Krum): 2 paid workers (the TM's own session 500 + the technician) | band shown, as R31 2+ designs; other worker's pay **6196.63 vs 6200**. Inherent to R31: the 2+ totals already allow subtracting one's own known pay |

**SEC71-05 fix:** filter `resolved_events` the same way (or drop it) for non-finance callers. Consider restricting `evaluate`.

| Gate | Result |
|---|---|
| `test_sec_02`, real | **28 passed** (finance roles keep everything) |
| W0 | same 15 |
| A2C | 0/208 |
| A1 | 0/422 |
| R0 | 814 |
| PM-01 | 6, real |

PR comment 6695992847 updated (blocking).

- **#71 known-pay variant:** decided by Krum as **R42** (recorded @ `940bd49`). The R31 threshold stays at 2 paid workers, and the known-pay derivation is accepted. It is **not a finding**.
- **SEC71-05:** dispatched to SEC-02 as Addendum H. It will be re-checked on the next #71 head.


### #78 W0-04-C02 @ `48e28da` (FG-126) — PASS (real W0-04 run pending in batch b5)

- **The change:** a non-duplicate `create_index` failure in `ensure_audit_indexes` now raises `AuditIndexError` (`database_ref` + `safe_reason`, raised `from None`) instead of re-raising the driver error, whose errmsg names `<db>.<collection>`.
- **New L9** in `probes/w004/probe_f7201_sentinels.py`: a database proxy whose `create_index` raises `OperationFailure` (code 67, errmsg with the database name).

| Head | L9 result |
|---|---|
| `48e28da` | `AuditIndexError`, fail-closed; all 13 paths clean |
| `7b6da64` (control) | raw `OperationFailure` leaks the database-name marker |

| Gate | Result |
|---|---|
| W0 | 1094/15/83, same 15 |
| A2C | 0/212 |
| A1 | 0/428 |
| merge-tree vs main `d226c49` | clean |


### #55 @ `94c0571` (Addendum M, FG-124 = Codex F-55-C26-03) — PASS, no open findings

- **The fix:** `LOCKED_WHEN_LINKED` += `allocation_type`, `allocation_ref_id`. The deprecated single allocation is still read when `allocations[]` is empty.
- **Embedded `invoices.lines` (finance.py), checked for a bypass:**
  - all Path B / allocation readers and the lock read `tenant.invoice_lines` only;
  - `effective_allocations` reads only that document's own fields, with no fallback to the parent invoice;
  - all `invoice_lines` writers are in `routes/invoice_lines.py` and are locked, or are inserts.
  - **Not a bypass.**

| Check | Result |
|---|---|
| FG-124 tests (Codex HTTP repro × 3 modes; PUT-vs-delivery race × 10 × 3 modes) | **36 passed** |
| My probes (M1, U1, race shapes, crash) × off/shadow/enforce | 13 passed each |
| warehouse suite | **43 files, 1010 passed** |
| W0 | same 15 |
| A2C | 0/223 |
| A1 | 0/452 |
| R0 | 814 |
| merge-tree main `d226c49` | `data_access` + A2B + A1 inventory |

PR comment updated (resolved).

### #73 @ `41a43b5` / #75 @ `f0a0757` (FG-110 / FG-112, LAB-01-O) — alone PASS; the merge with main conflicts

| Check | #73 | #75 |
|---|---|---|
| lab tests | 116 passed, 1 skipped | 157 passed, 1 skipped |
| reset file (6×10 concurrent resets → budget once; crash in the audit write → full rollback; crash after commit → 1 event; no transactions → 503) | 26 passed | 26 passed |
| W0 | same 15 | same 15 |
| A2C / A1 | 0 / 0 | 0 / 0 |
| PM-01 | 6, real | 6, real |
| R0 | 814 | the run printed an error line (billing webhook test) instead of a summary; re-run queued |

- **Merge with main `d226c49`:** a conflict in `services/project_pnl.py`, an import line where both sides are kept. The programmer must merge main into both. The merged re-runs are queued.
- **The 48 auth cells** in PM-01 `matrix.csv` are byte-identical on #73 `41a43b5`, #75 `f0a0757` and #72 `04e0a1b` (now on main), so there is no content conflict.


### main `d226c49` (#72 + #70) — sanity PASS

| Check | Result |
|---|---|
| PAY | **630** |
| probes `e_alloc_vs_reverse`, `d5_race`, `fg50` | FAILS none |
| f703 transfer probe | **24/24** |
| W0 | same 15 |
| A2C | 0/214 |
| A1 | 0/432 |
| R0 | 814 |
| PM-01 | 6 |

### #74 @ `31a9478` (FG-127, on FG-116 + addendum 2) — alone PASS

- The code is `e76f485`; `31a9478` adds evidence only.
- `test_27` / `test_31` drop their P&L special case, so P&L must equal every other reader. That is stronger, not weaker.
- `test_32` checks one amount and one label across all 7 readers through legacy → mixed → recompute → allocate.
- No double count in P&L: the legacy figure is the company-overhead share, and no other P&L line includes company overhead.

| Gate | Result |
|---|---|
| OH-01 | 231 |
| probes (O16 / O17 + Codex) | 27 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The #74 + #69 `3fb55f2` + main R0×5 run is **invalid**: #69 `3fb55f2` conflicts with main and the auto-resolution left markers, so the 11 SEC-01 / 8 R0 failures are artifacts. It will be redone on #69 `da47777` (which contains main).

### #76 @ `542fa2c` (Addendum A FG-114/115 + B FG-103/128) — PASS

`probes/subadv/probe_subadv01.py` with `PROBE_FG114=1`, off/shadow/enforce: **FAILS none**.

| Case | Result |
|---|---|
| S1 / S2 concurrent deductions | 2 pass, deducted 800, counters = rows |
| S3 cap | committed 3200 |
| S4 / S5 interrupted advance / deduction, same-key retry | one of everything |
| S6 tenant B | 404 |
| S7 same key ×6 | 1 row |
| **S8** cap boundary: 6 concurrent advances of 999.99, contract 5000 | **5 × 201 + 1 × 409**, total 4999.95 |
| **S9** committed counts against the cap | 1800 → 201, then 0.01 → 409 `ADVANCE_EXCEEDS_PACKAGE_VALUE` |

| Gate | Result |
|---|---|
| sub_adv + sec_01 | 38 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

D4 note: a pending reservation that is never retried holds headroom. By construction it only blocks (pending is never deductible, cost or paid). It needs a release path: owner-approved reconciliation or expiry, as debt.

### #77 @ `8188689` (Addendum B FG-119..123 + ACT77-01) — PASS

`probes/act01/probe_act01.py` with `PROBE_ACT_B=1`, × 3 modes: **FAILS none**.

| Case | Result |
|---|---|
| **A1** fresh tenant × 10 | **2 × 201 + 4 × 409** every round (ACT77-01 fixed: collections ensured outside the transaction, bounded transient retry) |
| A2 | 6 unique numbers |
| A3 PUT delta | exact |
| A4 cross-tenant / project / draft | 422, nothing written |
| A5 R29 | holds, 1 event |
| **A7** confirm | Viewer 403, no key 428 |
| **A8** crash in the confirm audit | act stays Draft with 0 events; same-key retry → Accepted with 1 event |
| **A9** price | 12.345 × 100 = **1234.50**; 12.35 given → 422 |
| **A10** technician GET | no money keys |

| Gate | Result |
|---|---|
| act01 tests | **101** |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 + merge with main | running |

### Others

- **#78 `48e28da`:** W0-04 + auth on real Mongo **196 passed** → full PASS.
- **#75 R0 re-run:** 814. The billing line was the expected `SECURITY_EVENT` log of `test_17_F04`, not a failure.
- **#73 / #75 + main** (my resolved trees, now superseded by the PRs' own merges `0c0f5f8` / `c68c942`):

| Check | #73 + main | #75 + main |
|---|---|---|
| lab | 117 | 158 |
| probes | lab01e P1 / P4 / P5 pass | lab02 / retake pass |
| PM-01 | 6 | 6 |
| PAY | 630 | — |

- **#69 `3fb55f2`:** SEC-01 30, W0 same 15, R0 814, PM-01 6. Superseded by `da47777`, which is queued.

### #77 + main — PASS

The only conflict is `docs/evidence/PM-01/run_meta.json` (evidence), with 0 markers.

| Check | Result |
|---|---|
| act01 | 101 |
| PAY | 630 |
| PM-01 | 6 |

### #71 @ `bde1728` — SEC71-05 resolved

Ran `probes/sec02/probe_sec71_d1_band_bisect.py` × 3 modes.

| Check | Result |
|---|---|
| pulse bisection | first answer 201 / 200 with `total_budget` only; derived spent 0.02 vs actual 6200 |
| /alarms | 0 steps |
| 404 oracle (GET, acknowledge, resolve) | same response for hidden and missing |
| **auto_resolve oracle** | rule 201, **0 steps**; derived 50000 vs 6200 (nothing learned) |
| band-varies (expected-actual, morning-briefing, compact) | False |
| known-pay variant | 6196.63 / 6200; this is R42, accepted by Krum, not a finding |

| Gate | Result |
|---|---|
| sec02 | 28 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main touches the A1 / A2B inventories, PM-01 `run_meta`, `idempotency.js` and its test.

I updated PR comment 6695992847 to "resolved".

- `83f1bf3` is docs-only (R42 note).
- `bfeda82` (FG-133) adds `safe_alarm_rule`: an allowlist of condition keys (metric / operator / threshold / secondary_*) for non-finance callers on GET /alarm-rules. Its test checks both roles.
  - Observation, not a finding: the rule `name` is free admin text and is still returned as-is.
  - Runtime is queued: `b71c` on the second RS.

### #55 @ `cba5306` (Codex F-55-C26-04 + header recalc) — probes PASS, gates running

**Static review**
- A metadata-only PUT does a `$set` of only the fields sent plus `updated_at`.
- Any derived input (`LOCKED_WHEN_LINKED` + `vat_percent`) is read, validated, computed and written in one transaction under the per-line lock. 409 applies only to the costing inputs.
- /allocate reads `qty` inside the transaction. DELETE writes nothing derived.
- The header recalculation is one `with_transaction`. A concurrent recalculation write-conflicts and retries, so the header equals Σ of the committed lines.

**A2C anchor: not weakened.** It moved with the code and keeps the same rule, and the test machinery is unchanged. My own mutations of the new statements are all caught:

| Mutated statement | Guard rule |
|---|---|
| header `update_one` | IDENTITY |
| lines `find` | READ |
| in-transaction `find_one` | READ |
| metadata `update_one` | WRITE |

**Probe** `probes/wh55/test_probe_f55_c26_04.py`: **42/42** on real Mongo (second RS on 27029, so it doesn't collide with b5–b7), × 3 modes.

| Case | Result |
|---|---|
| F1 paused vat PUT, then price 20, then linked delivery 5 @ 20, then resume | line 20 / 200 / VAT 18, P = 200 ×3 |
| F2 paused allocations-10 PUT while qty → 5 | 400, nothing written |
| F3 paused qty-12 PUT while /allocate sets P 4 | 4 / 8 / 120 |
| F4 ×10: 4 concurrent derived PUTs on 2 lines | no lost update; header Σ 410 / 60 / 470 |
| F5 notes PUT on a linked line | derived fields byte-equal; P = 100 |

Baseline at `94c0571`: F4 fails 10/10 (lost VAT, IL2 at 300 instead of 210) and F5 fails (derived values written on a linked line). F1–F3 can't be compared there: their pause hook isn't on the old path.

The gates (`b55c`) are running.

### #77 @ `611d17e` (merge main `611435e` + Addendum C FG-131) — **BLOCKING ACT77-02**

- **Byte check CLEAN:** `611435e` equals `git merge-tree` of origin/main `d226c49` + `8188689`, except `docs/evidence/PM-01/run_meta.json`.
- **Earlier checks still pass:** `probe_act01.py` with `PROBE_ACT_B=1` × 3 modes (A1 2/4 ×10, A2–A10).
- **FG-131 randomized probe** (`PROBE_ACT_C=1`: new / split / PUT / burst of 8 / confirm, × 25 steps × 3 rounds × 3 modes): the invariant Σ line_total == round(acted × 12.345) and the `acted_value` counter hold at **every step**. They break at the **move-off** step: a PUT that takes LD off a Draft act. When LD is then full it ends at 1234.49 or **1234.51**.
- **Minimal repro** (`PROBE_ACT_C2=1`), × 3 modes:

| Steps | LD after the move | LD when full |
|---|---|---|
| acts 0.3 (3.70) + 0.3 (3.71), then PUT the first act → L1 | 3.71 (exact 3.70) | **1234.51 > 1234.50** |
| the same with 33 + 33 | 407.38 (exact 407.39) | 1234.49 |

- **Cause:** in `update_act`, when `mine` is empty `new_value = 0`. That drops the act's own historical value, not the cumulative change `value_at(u − d) − value_at(u)`, and the leftover cent has no line to sit on.
- PR comment posted (blocking).
- `acted_value` is a float `$inc`, so it carries float noise (1234.4899999999998). Informational only.

### #79 OFF-01 @ `ea9df81` (FG-129 / FG-130) — **BLOCKING OFF79-01**

**Static review.** The new-version, accept, public respond and cancel routes each make one conditional write (`superseded_by: None`, status, version) inside a transaction together with the canonical AuditEvent, and each requires R29 through PAY-01's `_require_key` / `_once`. Revoking a review link keeps the token. DELETE is allowed only for a never-sent Draft.

**Probe** `probes/off01/test_probe_off01.py` (PR harness, third RS on 27039) × 3 modes: **9 failed / 45 passed**. All 9 failures are O1.

| Case | Result |
|---|---|
| **O1** restore on Sent | **200, total 1200 → 12**; the client approves by link → **Accepted at 12**, with version 1 and the same token |
| **O1** restore on Accepted | price rewritten (1200 → 12) |
| **O1** restore on Superseded | price rewritten (1200 → 12) |
| O2 public 409 | no leak |
| O3 same token in A and B | 404, both untouched |
| O4 4-way race ×10 | exactly 1 winner every time, state matches, 1 event |
| O5 key reused on another offer | 409 `IDEMPOTENCY_KEY_REUSED`; replay gives the same answer, 1 event |
| O6 DELETE matrix | 409 / 409 / 409 / 200 |
| O7 accept with a non-existent `evidence_file_id` | 200 (observation OFF79-02) |

- **OFF79-01:** D-OFF01-7 is a live FG-129 bypass. Fix: restore only for a never-sent Draft, and no hard delete of snapshots. PR comment posted (blocking).

**Debt review**

| Debt | Verdict |
|---|---|
| D-OFF01-7 | **blocking** (= OFF79-01) |
| D-OFF01-2 | **high, needs a decision before ACT-01 and OFF-01 are both on main**. v1 stays Accepted after a new version, so an accepted v2 means two accepted versions, and ACT-01 caps per offer line (new line ids) → the contract value can be acted twice |
| D-OFF01-1 (link has no expiry or identity check) | real FLOW-003 gap, pre-existing; OK as tracked debt |
| D-OFF01-5 (internal accept doesn't require a carrier) / OFF79-02 | OK as debt |
| D-OFF01-3, -4, -6, -8, -9, -10, -11 | OK as debt |

Gates: `b79` (running).

### #69 @ `da47777` (SEC-01, contains main) — PASS

`probes/sec01/probe_f6903.py` × 3 modes: **FAILS none**.

| Case | Result |
|---|---|
| F1 crash after the cap reservation, then same-key retry | 1 ledger row; committed 60 = paid 60 = Σ rows |
| F2 6 concurrent same-key retries | 1 × 201 + 5 × 409; one of everything |
| F3 phantom (abandoned key holds 60) | a new 50 → 409, a new 40 → 201 (committed 100, paid 40) |

| Gate | Result |
|---|---|
| sec01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

### #73 @ `0c0f5f8` / #75 @ `c68c942` (both already merged with main) — PASS

| Check | #73 | #75 |
|---|---|---|
| lab | 117 | 158 |
| reset | 26 | 26 |
| PAY | 630 | 630 |
| probes | lab01e P1 / P4 / P5 | lab02 4 + retake 1 |
| billing `test_17_F04` | — | 6 |
| W0 | same 15 | same 15 |
| A2C / A1 | 0 / 0 | 0 / 0 |
| R0 | 814 | 814 |
| PM-01 | 6 | 6 |

The merge commits were already byte-checked CLEAN.

### #79 @ `ea9df81` gates

| Gate | Result |
|---|---|
| off01 | 42 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 matrix diff vs main is **only** `+offers,POST,/api/offers/{offer_id}/cancel`. Merge with main: clean. OFF79-01 remains blocking; Addendum A is pending.

### #77 @ `dd11e8e` (ACT77-02 fix: re-tile drafts, freeze confirmed) — **ACT77-02 resolved**

`probe_act01.py` with `PROBE_ACT_B=1`, `PROBE_ACT_C=1` and `PROBE_ACT_C2=1` × 3 modes: **FAILS none**.

| Case | Result |
|---|---|
| **C2** 0.3 + 0.3, then move the first act off LD | LD 3.70 (exact), then 1234.50 when full |
| **C2** 33 + 33, then move the first act off LD | LD 407.39 (exact), then 1234.50 when full |
| **C** randomized (25 steps × 3 rounds) | invariant holds at every step; `acted_value` exact (no float noise); **confirmed acts never change** (3–5 tracked per round); full = 1234.50, +0.0001 → 409 |
| **C3** confirm ∥ 2 draft edits on the same line × 10 | 200 / 200 / 200; confirmed act unchanged; full = 1234.50 |
| A1–A10 | still pass |

I updated PR comment 6710704911 to "resolved". Gates: `b77d` (running).

### #77 @ `dd11e8e` gates — **full PASS**

| Gate | Result |
|---|---|
| act01 | 110 |
| PAY + W0-04 | 700 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main is clean.

### #79 @ `449c1f4` (Addendum A) — **OFF79-01 resolved**

`probes/off01/test_probe_off01.py` (O1–O9) × 3 modes.

| Case | Result |
|---|---|
| O9 restore and version-delete on Sent / Accepted | 409 / 409; total stays 1200; snapshot kept |
| O9 new-version of an Accepted offer | 409 `OFFER_ACCEPTED_USE_ANNEX` |
| O9 evidence file of tenant B / linked to another project / missing | 422 ×3; the offer stays Sent |
| O2–O6 | unchanged pass |
| **O8** restore ∥ send on a Draft ×15 | **45/45 end Sent at 12 while the send snapshot says 1200** |

- **OFF79-03 (medium, non-blocking):** O8 is a check-then-unconditional-write race. The same pattern already exists on main in `PUT /offers/{id}/lines` ∥ send. Fix: put the Draft / `sent_at` condition in the write filters.

**Cross-PR trial merge** of #77 `dd11e8e` × #79 `449c1f4` (only the `run_meta` conflict). `probe_act01.py` with `PROBE_X=1` × 3 modes: **FAILS none**.

| Case | Result |
|---|---|
| X1 accepted offer with acts | new-version → 409 ANNEX; acting continues |
| X2 v1 Sent | act → 422; new-version → send v2 → accept v2 → full act on v2 201; act on v1 → 422; old link → 409; acted on v1 = 0 |
| X3 act ∥ new-version × 10 | (201, 409) every time |
| X4 legacy chain (OV1 Accepted + OV2 Sent from before OFF-01) | accept OV2 → **200**, so two versions are Accepted; ACT-01 then refuses both (SUPERSEDED / LINEAGE_UNKNOWN), so no double billing. Observation: `/accept` should refuse when another version of the family is already Accepted |

I updated PR comment 6710829710 to "resolved". Gates: `b79a` (#79) and `bx` (merged tree) are running.

### #79 @ `449c1f4` gates — PASS (OFF79-03 medium stays open as non-blocking)

| Gate | Result |
|---|---|
| off01 + audit_probe | 108 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 diff vs main is only `+POST /api/offers/{offer_id}/cancel`. The merge with main is clean.

Merged tree #77 × #79: act01 110, off01 108, R0 814, PM-01 6, W0 same 15 — **PASS**.

### #79 @ `e0dce63` (OFF79-03 compare-and-swap writes + legacy family guard) — **OFF79-03 resolved; OFF79-04 medium**

Probe O1–O10 × 3 modes.

| Case | Result |
|---|---|
| **O8** restore ∥ send ×15 | either send 200 + restore 409 (Sent at 1200 = snapshot) or send 409 + restore 200 (Draft); **never** a mismatch |
| O9 | unchanged pass |
| **O10** `PUT /offers/{id} {"vat_percent":9}` ∥ send ×15 | **10/45 end Sent with VAT 9 and total 1200** (should be 1090), and the PUT still answers **200**; the send snapshot carries the same inconsistent pair |

- **OFF79-04 (medium, non-blocking):** the VAT PUT writes `vat_percent`, then the totals in an unchecked second write. A send in between wins the compare-and-swap, the second write matches nothing, and the result is ignored. Fix: compute the totals first and write them together in one compare-and-swap.
- I updated PR comment 6710829710.

### #74 `31a9478` + #69 `da47777` — proper trial merge (`3764e41`)

The merge conflicts in 5 files. Resolution:

| File | Resolution |
|---|---|
| `overhead.py` signature | #69's SEC-01 `require_money_write` gate + #74's docstring |
| `overhead.py` step 6 and the write block | #74's versioned `KeyedWrite` (#69's comment says "#74's version wins") |
| `server.py` | both sides (OH-01 indexes + AUTH-01 indexes) |
| `idempotency.js` and its test | #69's version |
| PM-01 matrix | regenerated by `--harness`: route set equals #69 `da47777`'s; vs #74 only `+auth forgot/reset-password` (from main) |

`overhead.py` keeps #69's only overhead money gate (1/1). Gates `b7469` (SEC-01, OH-01, PAY, f6903 probe, PM-01, W0, R0 ×5) are running.

### #74 `31a9478` + #69 `da47777` trial merge (`3764e41`) — gates

| Gate | Result |
|---|---|
| OH-01 | 231 |
| PAY | 630 |
| f6903 probe | FAILS none |
| PM-01 | 6 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| **R0 ×5** | **814 ×5** |
| **SEC-01** | **3 failed / 27** |

The 3 SEC-01 failures are merge-time expectation updates, not a regression. Each is a "fresh real-Mongo run" test that compares fixed collection-write sets (c01, c02, c03), and #74 intentionally changed two routes:

| Route | What changed | Effect on SEC-01 |
|---|---|---|
| `/overhead/snapshots/compute` (ohcompute) | #74's versioned snapshot also writes `audit_events` + `overhead_period_locks` | expected set is `audit_logs` + `overhead_snapshots` only |
| `/overhead-allocation/compute/{project}` (oh_alloc) | FG-89: now a read-only projection of the OH-01 allocation, writes nothing | expects a write to `project_overhead_alloc` |

The permission gates are intact: `require_money_write` count is 2/2 in `full_cost.py` and 1/1 in `overhead.py`, and PM-01 passes.

**Action for whichever of #69 / #74 merges second:** update the SEC-01 c01 / c02 / c03 expected write sets for ohcompute (+`audit_events`, +`overhead_period_locks`) and oh_alloc (no write; or drop it from the money-write list, since it is read-only now).

### #79 @ `ed68cb9` (OFF79-04 compare-and-swap sweep) — provisional PASS on probes

`probes/off01` O1–O12 × 3 modes: **207 passed**.

| Case | Result |
|---|---|
| O10 VAT PUT ∥ send ×15 | always consistent; Sent equals its snapshot (1090 at VAT 9, or 1200 at VAT 20) |
| O8 restore ∥ send | never a mismatch |
| O11 lines PUT ∥ new-version of a Draft ×10 | the new version copies the final lines (or 409) |
| O12 reject ∥ new-version ×10 | consistent (Rejected, or Rejected then Superseded) |

- **OFF79-04 resolved.** The header PUT, lines PUT and new-version now each make one compare-and-swap with `updated_at`.
- Observation: a public GET of the review page writes `updated_at` on a Sent offer, so a new-version that read the offer before the client viewed it gets 409 `OFFER_STATE_CHANGED`. This is benign; the user retries.
- Gates: `b79b` (running). Pending addenda FG-135..139.

### #71 @ `30a8c22` (FG-141) — static review

`is_money_metric()` is a **name heuristic that fails open**. It treats a metric as money only when it matches eur / amount / cost / price / spent / budget / … and not pct / hours / days / count.

| Classified as money (threshold hidden) | Classified as NOT money (**threshold shown to non-finance**) |
|---|---|
| `labor_cost`, `amount_eur`, `spend_eur` | `total_spend`, `expenses`, `overhead_total`, `paid_total`, `outstanding`, `debt`, `cash`, `fee`, `receivables`, `deficit`, `overspend` |

The metric is free admin text, and `alarm_engine` dispatches on the rule type, not the metric name.

- **SEC71-06 (medium):** fail closed instead. Show the threshold only for an allowlist of metrics `alarm_engine` actually reads as % / hours / days / count (e.g. `burn_pct`, `progress_pct`, overtime hours, days left), or decide by rule `type`. Hide it for everything else.
- Runtime: `b71d` (bisect probe, sec02, gates; starts after `b55c`).

#79 @ `ed68cb9` gates — PASS (provisional; FG-135..139 addenda pending):

| Gate | Result |
|---|---|
| off01 + audit_probe | 210 |
| W0 | **same 15** (the programmer's one-off 75 was a local mongod crash; not reproduced here) |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 diff vs main is only `+cancel`. The merge with main is clean.

### Environment incident (audit side, not a PR finding)

The extra audit replica sets crashed with mongod **fassert 50853** (`wiredtiger_util.cpp:772`, file-handle exhaustion from many test databases). They had been started without the main RS's WiredTiger handle-close settings.

| RS | Crashed at | Impact |
|---|---|---|
| `auditmongo2` (27029) | 17:21 UTC | #55 `cba5306`'s 43-file warehouse loop (`b55c`) ran against a dead mongod until it hit its time limit: **those warehouse results are void** |
| `auditmongo3` (27039) | 19:20 | interrupted the #79 probe re-runs ("connection closed" / "connection refused" are environment errors) |

The `b55c` lines written before 17:21 are valid: c26l_l 153, A2C static guard 32, old probes 13 ×3. Both RSs were recreated with the handle-close settings. Re-runs: `b55e` (#55, all 43 files + W0 + R0 + merge), `b71e` (#71 `30a8c22`), #79 `b03b806` probes on rs0.

This is likely the same class as the programmer's "75 W0 failures from a local mongod crash".

### #79 @ `b03b806` (Addendum B FG-135..138) — probes O13–O15 pass

| Case | Result × 3 modes |
|---|---|
| **O13** legacy pair (v1 Sent + child v2 Sent, v1 never superseded) | GET v1 link **410** (no prices or ids); approve / reject → 409; `/accept` → 409; new-version → 409; v1 unchanged |
| **O14** DELETE ∥ send ×10 | never 5xx; never both 200; a sent offer is never deleted |
| **O15** `signed_pdf` without a file | 422 `EVIDENCE_FILE_REQUIRED` |
| **O15** `verified_email` | 422 `VERIFIED_EMAIL_NOT_SUPPORTED` |
| **O15** cancelled link | GET 410, no leak |

- **Open check:** one O12 run (reject ∥ new-version, fresh database) raised `OperationFailure: Collection namespace '…audit_logs' is already in use` from the new-version transaction. That is the fresh-tenant implicit-collection-creation class, like ACT77-01. It ran shortly before the 19:20 crash, so it is being re-run on rs0 (×3) to confirm or discard.
- FG-138 part 2 (unit costs in the client view) is held for Krum.
- FG-139 (plaintext token) is debt D-OFF01-15. Sensible: it needs a re-issue flow.

### #79 @ `b03b806` — probe re-run on the stable rs0

Full probe O1–O15: **243 passed**.

**OFF79-05 (medium, non-blocking): fresh-tenant first-write race.** O11 / O12 run alone on an idle rs0, ×3: in **1–4 of 60 rounds** the new-version transaction fails with `pymongo OperationFailure: Collection namespace '…audit_logs' is already in use`, and it reaches the client as an error.

- Cause: on a tenant whose `audit_logs` collection does not exist yet, a concurrent non-transactional `log_audit` (the reject) and the transactional `log_audit(..., session)` (new-version) both create it implicitly.
- Same class as ACT77-01. Nothing is corrupted: the transaction aborts and a retry works. Only the first offer actions of a brand-new tenant are affected.
- Fix: as in ACT77-01, make sure `audit_logs` / `offer_events` / `audit_events` exist before the transaction opens. `run_in_transaction` already does this for the chain index.

The other O11 / O12 failures seen earlier were collisions with my own concurrent #77 probe on rs0 (`mongo_clean` dropped its database), not findings. Gates: `b79c` (running).

### #77 @ `2cc1147` (Addendum D, FG-142 expected values on confirm) — PASS on probes

`probe_act01.py` with `PROBE_ACT_B`, `C`, `C2`, `D` × 3 modes. The probe now confirms with the values seen, and on 409 re-confirms with the shown values (as the UI does).

| Case | Result |
|---|---|
| **D** confirm with no key | 428 |
| **D** confirm with no body | 422 `EXPECTED_VALUES_REQUIRED` |
| **D** confirm with the draft's 407.38 (the second act on LD) | **409 `ACT_VALUE_CHANGED`**; act stays Draft, 0 events |
| **D** same key with the corrected body | 409 (key reused) |
| **D** new key with the corrected values | **200**, Accepted at **407.39** (total 488.87); AuditEvent `confirmed_total_seen` = 488.87 |
| C randomized | invariant holds at every step; full = 1234.50 |
| C2 | unchanged pass |
| C3 confirm ∥ 2 draft edits ×10 | (409, 200, 200); then re-confirmed with the shown values → Accepted; full = 1234.50 (re-run ×2: 60/60) |
| A1–A10 | still pass |

- Note: after `ACT_VALUE_CHANGED`, the **same** Idempotency-Key cannot be reused, because the body is in the fingerprint. The frontend sends a new key (verified in `ProjectOperationsPage.js`), so this is fine.
- The one C3 failure in the first run (acts vanished) was my own `mongo_clean` colliding on rs0, and does not reproduce.
- Gates are queued after `b79c`.

### #71 @ `eb91eec` (SEC71-06 fix: fail closed by rule type) — static PASS

`safe_alarm_rule` shows `threshold` only for the types `alarm_engine` evaluates as a non-money unit. Verified against the engine's branches:

| Type | Unit |
|---|---|
| budget | burn % |
| overhead | % change of overhead per person-day |
| overtime | hours |
| attendance | days |
| deadline | days left |

`secondary_threshold` is shown only for (budget, progress_pct).

My matrix of 16 metric names × 10 types (incl. custom, pricing, procurement, None, wrong case), 160 cases: **0 mismatches**. `threshold_eur` and the other keys are always dropped.

- **SEC71-06 resolved.**
- Runtime: `b71f` (bisect probe, sec02, W0, R0, PM-01, merge) on rs2 (running).

### #71 @ `eb91eec` — **full PASS** (SEC71-06 resolved)

Bisect probe × 3 modes: every oracle closed.

| Oracle | Result |
|---|---|
| pulse | derived 0.02 of 6200 |
| /alarms | 0 steps |
| 404 (GET, acknowledge, resolve) | same response for hidden and missing |
| auto_resolve | 0 steps |
| band-varies (3 readers) | False |
| known-pay variant | the only FAILS line; R42, accepted |

| Gate | Result |
|---|---|
| sec02 | 30 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main touches the inventories, PM-01 `run_meta` and the `idempotency.js` pair (same as #69 / #74).

### #79 @ `5d17063` (Addendum B complete + R43) — probes PASS

Probe O1–O16 × 3 modes: **246 passed**.

| Case | Result |
|---|---|
| **O16 R43** review GET line keys | only `activity_name`, `id`, `line_total`, `note`, `qty`, `sort_order`, `unit`, `unit_price` (= 100.0); no split keys and no split figures (40 / 60 / 400 / 600 / 1.5) in the body |
| **O16 R43** generated PDF (text extracted with pypdf) | no "Мат" / "Труд" columns and no split figures; unit price 100.00 present |
| **O16 R43** respond | `{ok, status}` only |
| O13–O15 | pass |

The only public routes are `GET /offers/review/{token}` and `POST …/respond`. The PDF and XLSX are staff routes (`require_m2`).

- **OFF79-05 confirmed again** on this head (O11 / O12 ×3 on idle rs0: 1, 5 and 0 failures of 60, all `audit_logs` namespace in use). Medium, non-blocking.

**Debt verdicts**

| Debt | Verdict |
|---|---|
| **D-OFF01-16 XLSX** | **confirmed internal-only.** `GET /offers/{id}/xlsx` requires an authenticated M2 user; the only UI caller is the staff `OfferEditorPage` export button; no token / public route serves it. It still contains the split, which is fine for staff. Sending that file to a client by hand is a process matter. |
| **D-OFF01-15 plaintext `review_token`** | **acceptable as debt, not blocking.** It was already plaintext on main; the token is 96-bit random, scoped to one offer, and can only approve / reject / request revision of the current Sent version (409 / 410 after a new version, cancel or revoke). Main also already returns `review_token` to internal users in the project financial view (`projects.py` extra_offers projection). Condition: pair it with D-OFF01-1 (no expiry, no identity check) **before** a magic-link approval is treated as contractual evidence; until then the approval records `verification: link_token_only`. Cheap hardening worth doing early: drop `review_token` from list projections for roles that cannot send offers. |

Gates: `b79d`, then #77 `b77e` (running).

### #55 @ `cba5306` (Codex F-55-C26-04 + header recalc) — **full PASS**

Re-run after the mongod crash, on the recreated rs1.

| Gate | Result |
|---|---|
| warehouse canonical | **all 43 files, 1049 passed**, 0 bad (1010 at `94c0571`; +39 new) |
| c26l_l | 153 |
| A2C static guard | 32 (anchor not weakened; my own mutations caught) |
| earlier wh55 probes × 3 modes | 13 |
| **new F-55-C26-04 probe** | **42/42** × 3 modes |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |

The merge with main conflicts in the same 3 files as before: `data_access.py`, A1 / A2B inventories. FG-140 (invoice edit ∥ send / pay) is pending as the next head.

### #79 @ `5d17063` gates — PASS (with OFF79-06 low)

| Gate | Result |
|---|---|
| off01 + audit_probe | 225 + **3 failed** → **228** once `pdfplumber` was installed |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 diff is only `+cancel`; the merge with main is clean.

- **OFF79-06 (low):** `test_23_the_client_sees_only_the_combined_unit_price` imports `pdfplumber`, which is **not in `backend/requirements.txt`**. In a clean environment (CI / Codex) the R43 PDF test fails with `ModuleNotFoundError` in all 3 modes. Fix: add `pdfplumber` (pinned) to the requirements, not an importorskip. A skip would hide the R43 PDF check.
- Open: OFF79-05 (medium, fresh-tenant `audit_logs` race).

### #77 @ `2cc1147` gates — **full PASS**

| Gate | Result |
|---|---|
| act01 | 113 |
| PAY + W0-04 | 700 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main is clean.

### Environment: machine restart at ~20:21 UTC

All containers stopped. Scratchpad, worktrees and repo are intact. The RSs were restarted (`mongo_up.sh` + `docker start auditmongo2/3`), and the probe run that was in flight was redone.

### #79 @ `2379d07` (OFF79-05 + OFF79-06 fixes) — probes PASS

| Check | Result |
|---|---|
| O11 / O12 fresh-tenant race (idle rs0) | **60/60 ×3, 0 failures** → **OFF79-05 resolved** |
| full probe O1–O16 | 246 passed |
| clean venv from `backend/requirements.txt` (`pip install -r`) | `pip check`: no broken requirements |
| pins | `pdfplumber` 0.11.7 (requires `pdfminer.six`, Pillow, `pypdfium2`), Pillow 12.1.0 unchanged, `pdfminer.six` 20250506, `pypdfium2` 4.30.0 |

- Observation on the OFF79-05 fix: `ensure_offer_collections(db)` runs on the default `db`. That is where `audit_logs` and `audit_events` are written (the raced collection). `offers` / `offer_events` live in the tenant DB and are ensured at onboarding; the new bounded `TransientTransactionError` retry covers anything left over. Not a gap.
- The OFF-01 suite and R43 `test_23` run in the clean venv (`b79e`, running), then W0 / R0 / PM-01 / merge.

### #55 @ `ed48595` (merge of f1c3394 FG-140 + main d226c49) — static review

**Byte check.** The merge commit equals `git merge-tree` (4 conflicts) plus resolutions, plus extra changes made inside the merge commit:

| Extra change | What it is |
|---|---|
| warehouse routes (`warehouse_canonical`, queries, migration) | `catalog_legacy_check` on the route-level `require_permission` |
| `_finite_decimal_str` validators | non-numeric or non-finite quantity / value → **422** (was 500) |
| `invoice_state`, `legacy_gate`, PM-01 report and test, c26l_n test | as above |

**`finance.py` vs main d226c49.** #70's payment and reversal code is unchanged apart from:
- `update_invoice_status(…, *, session=None)`, plus a `status ≠ Cancelled` filter on its write;
- `PAYMENT_LOCK_STALE_SECONDS` / `ROW_LOCK_FIELD` imported from `invoice_state` (same values: 30 s, `allocation_lock`);
- two imports.

FG-140 claim / CAS is present in `update_invoice`, `update_invoice_lines`, send, cancel and delete.

**`claim_invoice` honours #70's row lock.** Its filter is `allocation_lock` absent OR `.at` older than 30 s, otherwise 409 `INVOICE_BUSY`. #70 releases its lock with `$unset`, so the states match.

**Invoice-line writers.** The metadata PUT, derived PUT, create, bulk create and delete all `claim_invoice(allowed=Draft)` in their transaction. `/allocate` does not claim; it only moves cost allocations, not invoice money (observation).

**`catalog_legacy_check` does not widen enforce.** `require_permission` reads `legacy_check` only in the off / shadow branches. In the committed PM-01 matrix (767 routes, 18 408 cells), **0** (route, role) keys differ between off / shadow / enforce, including all 256 warehouse keys.

**`TenantData.transaction_client`** is the motor client of the tenant's own DB. `run_transaction` only opens a session with it; every read and write stays `TenantData`-scoped. It adds no cross-tenant capability (the same client is already `app.db.client`).

Runtime `b55n` (rs1) is running: c26l_n FG-140 races, wh55 probes ×3, PAY, 43 warehouse files, W0, R0, PM-01.

### #79 @ `2379d07` gates — **full PASS**

Clean venv `pip install -r requirements.txt -r requirements-dev.txt` (as the repo instructs); `pip check` is clean.

| Gate | Result |
|---|---|
| OFF-01 suite + audit_probe in the clean venv | **231 passed, 0 skipped** |
| R43 `test_23` | 3 passed (runs, does not skip) |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main is clean.

- With `requirements.txt` alone, 15 mongomock-backend tests fail with `ModuleNotFoundError: mongomock_motor`. That is expected: it lives in `requirements-dev.txt`, documented as required for tests. Not a defect.
- OFF79-01 / 03 / 04 / 05 / 06 are all resolved. Remaining debts (D-OFF01-1, -15 etc.) are as judged earlier.

### #55 @ `ed48595` (FG-140 + main d226c49) — **full PASS**

| Gate | Result |
|---|---|
| c26l_n FG-140 suite | **72 passed** (edit ∥ send ×10 and edit ∥ send→pay ×10 × 3 modes: a Paid invoice stays at its paid total with remaining 0, header = Σ lines live and after rebuild; paused edits after send / payment → 409; conditional send / delete; claim honours the PAY-01 lock with `INVOICE_BUSY`) |
| wh55 probes (c26l L, link race, F-55-C26-04) | 55 × 3 modes |
| PAY (#70 suites on the merged finance) | 630 |
| warehouse canonical | **44 files, 1121 passed**, 0 bad |
| W0 | same 15 |
| A2C / A1 (against the regenerated inventories) | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 (767 routes / 18 408 cells; modes identical) |

Static review is in the entry above. Ready for Codex.

### #71 @ `b1ab349` (FG-141 explicit (type, metric) allowlist) — static PASS

My 16-name × 10-type matrix (160 cases): **0 mismatches**. The threshold is shown only for (budget, `burn_pct`) in that set; `threshold_eur` is always dropped.

| Case | Result |
|---|---|
| FLOW Guard case: budget / `amount_eur` / 48250 | `{metric, operator}`, **threshold hidden** |
| all **11** allowlisted (type, metric) pairs | threshold shown |
| budget rule with no metric | threshold hidden |

- Observation (usability, not security): `alarm_engine` branches on the type only, so a budget rule with an unlisted metric name is still a % rule. Non-finance users won't see its threshold. Fails closed by design.
- No UI or seed sets metric names (API only).
- Runtime `b71g` (bisect probe, sec02, W0, R0, PM-01, merge) was re-started after a second machine restart (~21:19 UTC).

#71 @ `b1ab349` runtime — **full PASS**.

| Check | Result |
|---|---|
| bisect probe × 3 modes | pulse 0.02 / 6200; 404 oracles same; auto_resolve 0 steps; band-varies False; only FAILS line = the known-pay variant (R42, accepted) |
| sec02 | 30 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main touches inventories, `run_meta` and the `idempotency.js` pair.

### main → `2ec61f3` (#72 + #70 + #78)

Codex results:

| PR | Result |
|---|---|
| #74 | PASS |
| #78 | PASS, merged |
| #76 | **CHANGES_REQUESTED** |

The #76 findings:

- **F-76-01:** an ordinary payment can exceed the contract cap when an advance exists.
- **F-76-02:** the audit record is duplicated after a crash.

**Audit miss (#76 @ `542fa2c`, which I passed).**

- My `subadv` probe tested advances against the cap (S8 / S9: concurrent advances; committed counts toward the cap), but **not an ordinary payment after an advance**.
- The crash probes S4 / S5 checked "one of everything" on business rows, but **not the AuditEvent count after the crash-and-retry**.

For the #76 fix head, add:

- (a) advance A, then ordinary payments up to and past `cap − A`, including concurrently, with exact 201 / 409 boundaries;
- (b) a crash at each step, then same-key retry → exactly 1 AuditEvent per business action.

Trial merges now use main `2ec61f3`.

### #79 @ `acc472f` (FG-144 reject CAS + status-transition sweep) — **full PASS**

Probe O1–O18 × 3 modes: **606 passed**.

| Case | Result |
|---|---|
| **O17** public approve ∥ internal reject **×100 per mode** | always exactly 1 winner (200 / 409); Accepted ⇒ `accepted_at` and no `rejected_at`, Rejected ⇒ the reverse; exactly 1 decision AuditEvent |
| **O18** send ∥ send ×20 | one 200 + one 409, `offers.offer.sent` 1, snapshot 1, `offer_events` 'sent' 1 |
| O18 reject without key | **428** |

| Gate | Result |
|---|---|
| OFF-01 suite in the clean venv (req + dev) | 231 passed, 0 skipped |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 diff vs main is only `+cancel`. The merge with main d226c49 is clean, and so is the merge with the **new main `2ec61f3`**.

- **400 → 409:** no frontend change needed. `OfferEditorPage` (accept / reject / new-version) and `OfferReviewPage` (respond) render errors through `apiErrorText`. The new reject call sends a per-click Idempotency-Key.
- **D-OFF01-18 (send has no key): acceptable as debt.** `/send` sends **no email**; it writes the status, a snapshot, `offer_events` 'sent' and `offers.offer.sent` in one transaction behind a compare-and-swap. A double send gives exactly one of each and the loser gets 409. A key would only turn the loser's 409 into a replay of the first answer.

### Periodic pass 22:25 UTC — new PR #80 @ `d420096` (docs: task packages, addenda, decisions) — PASS (docs-only)

**Docs-only:** 56 files, all under `docs/`; no code, tests or config. Secret scan of the diff: none.

**Canon changes (FLOW-043, FLOW-040).** FLOW-043 gains **D-16** and **D-17**; FLOW-040 gains a pointer to D-16.

| Decision | What it allows | Bounds | Source |
|---|---|---|---|
| **D-16** | Owner emergency recovery from the server: a narrow exception to FLOW-040 L5 | name + reason + canonical AuditEvent (R1) + Owner notification; no business-content access; the rest of L5 unchanged | Р19 + Р24 (Krum, 06.11.2026) |
| **D-17** | the piece rate changed by one finance person: a narrow exception to FLOW-002 two-person | new version + reason + AuditEvent; already approved quantities keep their price; all other rate changes stay two-person | Р41 (Krum, 07.11.2026, FG-100 / FG-107) |

- **Traceability verified:** Р19 (line 57), Р24 (line 67) and Р41 (line 101) are in `docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md`, and D-16 / D-17 reproduce them faithfully. This meets CLAUDE.md §18: a locked FLOW changes only with Krum's explicit decision recorded in the canon.
- No other PR head changed since the last audit: 55 ed48595, 69 da47777, 71 b1ab349, 74 31a9478, 76 542fa2c, 77 2cc1147, 79 acc472f. Main is `2ec61f3`.

### #76 @ `c4de7c9` (merge 9ba9ec7 main d226c49 + Codex F-76-01 / F-76-02) — static review

**Merge byte check (`9ba9ec7`):** = `git merge-tree` (542fa2c × d226c49, 5 conflicts) + resolutions.

| File | Resolution |
|---|---|
| `finance.py` | #76's own `subcontractor_advance` refusal in `delete_payment` removed in favour of #70's generic `_source_module_refusal`, which classifies a row with `subcontractor_payment_id` as the subcontractor module's (FG-45 kept). The test was updated to check exactly that, plus no `finance_payments.delete_one` anywhere. |
| `idempotency.js` + its test | the union of #69 / #70 (`createIdempotencyHolder` + `createKeyHolder` + `apiErrorText`). Compared with #69 `da47777`'s union: **only function order and comments differ; the code is identical.** Merging #69 and #76 will conflict textually, not semantically. |
| A1 inventory, `run_meta` | regenerated |

**F-76-01.** A single `_TAKEN` expression (advance incl. pending − deducted − deduction pending + `committed_paid_total`) now gates both:
- the ordinary payment reservation (`_within_contract(amount)` in the same atomic update as the certified cap → 409 `PAYMENT_EXCEEDS_PACKAGE_VALUE`);
- the advance reservation.

A package without `contract_total` keeps the certified cap only (FG-114 already refuses advances there).

**F-76-02.** `log_audit(entry_id=…)`: the key-derived id is also `_id`, and a duplicate `_id` means "already written". `MoneyWrite.new_id` = uuid5(org_id, action, user:key, name), so it is tenant-unique and two tenants reusing a key string cannot collide in the shared `audit_logs`.

- **To verify at runtime:** the advance and deduction audits use `entry_id`, but the **ordinary payment's** `subcontractor_payment_created` audit (step `"audit"`) does **not**. A crash right after that insert may still duplicate it. The probe S11 covers it.

**Probe additions** (`probes/subadv/probe_subadv01.py`, `PROBE_F76=1`):

| Case | What it checks |
|---|---|
| S10a | advance 2000 → pay 2999.99 (201) → +0.01 (201, taken = 5000) → +0.01 (**409 `PAYMENT_EXCEEDS_PACKAGE_VALUE`**) |
| S10b | advance 2000 + 6 concurrent payments of 600 → exactly 5 |
| S10c | 3 advances of 1000 ∥ 3 payments of 1000 → exactly 5, taken ≤ 5000 |
| S11 | advance / deduction / payment × crash after `log_audit` / `_confirm_advance` / `_confirm_deduction` / `_refresh_package_totals`, then 2 same-key retries → `audit_logs` and `audit_events` deltas equal a clean run |

Runtime `b76c` (rs0; the machine restarted again ~22:34) is running.

#76 @ `c4de7c9` runtime — **BLOCKING SUBADV76-01**

`probe_subadv01.py` with `PROBE_FG114=1 PROBE_F76=1` × 3 modes.

| Case | Result |
|---|---|
| **S10a** | advance 2000 → 2999.99 201 → +0.01 201 (taken 5000.00) → +0.01 **409 `PAYMENT_EXCEEDS_PACKAGE_VALUE`** |
| **S10b** | 6 concurrent payments of 600 after an advance of 2000 → 5 × 201 + 1 × 409, taken 5000 |
| **S10c** | 3 advances ∥ 3 payments of 1000 → exactly 5 × 201, taken 5000 |
| **S11** advance / deduction × crash after `log_audit` / `_confirm_advance` / `_confirm_deduction` / `_refresh_package_totals` + 2 retries | `audit_logs` delta = clean (+1) every time |
| **S11 payment, crash after `log_audit`** + 2 retries | **`audit_logs` +2 (clean +1)** |

- **F-76-01 resolved.**
- **F-76-02: incomplete (SUBADV76-01).** The ordinary payment audit step has no `entry_id`. This code is inherited from #69 SEC-01-C03, so **#69 `da47777` has the same defect** (`subcontractors.py` `mw.step("audit", log_audit(…"subcontractor_payment_created"…))`). `overhead.py`'s `mw.step` audit is the same class, but #74 replaces that block.
- PR comment posted on #76 (blocking). #69 is flagged to @parent.

| Gate | Result |
|---|---|
| subadv + sec01 | 38 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

- The merge with main `2ec61f3` is clean. The merge with #69 `da47777` touches `run_meta` and the `idempotency.js` pair (text only).
- Clean runs write only legacy `audit_logs` (no canonical AuditEvent). This is declared debt in SUB-ADV-01 README:88, same as #69.

### #76 @ `b313933` (F-76-02 follow-up: payment audit `entry_id`) — **full PASS, SUBADV76-01 resolved**

Probe with `PROBE_FG114=1 PROBE_F76=1` × 3 modes: **FAILS none**.

| Case | Result |
|---|---|
| **S11** advance / deduction / **payment** × crash after `log_audit` / `_confirm_advance` / `_confirm_deduction` / `_refresh_package_totals` + 2 same-key retries | `audit_logs` **+1** every time (= clean) |
| S10a–c (F-76-01) | still exact: 5000.00 boundary → 409; concurrent → exactly 5 |
| S1–S9 | pass |

| Gate | Result |
|---|---|
| subadv + sec01 | 38 |
| PAY | 630 |
| W0 (incl. the A2B writer guard on `audit.py`) | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main `2ec61f3` is clean. I updated PR comment 6714054560 to "resolved".

- **Pending:** the same fix on #69 (its programmer is applying it). Re-run the S11 payment case on the new #69 head.

### #79 @ `653a1a5` (FG-149: a client view is not an edit) — **full PASS**

- **Static review.** The public view writes only `$max {viewed_at, last_viewed_at}` + `$inc view_count` and never `updated_at`. No CAS filter reads `viewed_at` / `view_count` (they occur only in that write). The review response does not include them.

| Check | Result |
|---|---|
| probe O1–O19 × 3 modes | **666 passed** |
| **O19** client view ∥ new-version ×20 per mode | new-version **200 every time**; o1 Superseded; `view_count` 1; no leak of `view_count` / `last_viewed_at` / `updated_at` |
| OFF-01 suite in the clean venv | 234 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |

The merge with main `2ec61f3` is clean.

- Process note: the first `b79g` probe run was void. It was killed by a machine restart (Docker down → every test failed to connect), and the re-run found the probe file missing. The probe was then run alone.

### #69 @ `25ffd9b` (addendum G: audit `entry_id`, the SUBADV76-01 class)

- `audit.py` is **byte-identical** to #76 `b313933` (`cmp`). The subcontractor payment audit and the overhead snapshot audit use `entry_id=mw.new_id(…)`.

**sec01 probe G** (crash right after the payment's audit insert, then 2 same-key retries) × 3 modes:

| Head | 3 modes | `audit_logs` rows |
|---|---|---|
| **`25ffd9b`** | 500 → 201 → 201 | **+1**, ledger 1 |
| baseline `da47777` | 500 → 201 → 201 | **+2** (the probe detects the defect; the fix closes it) |

F1–F4 still pass (FAILS none).

| Gate | Result |
|---|---|
| sec01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The merge with main `2ec61f3` is clean → **full PASS**.

**Other `log_audit` steps in #69.** Both `mw.step` audits (`overhead.py`, `subcontractors.py`) now carry `entry_id`. The two `wf.step("legacy_audit", log_audit(…))` calls in `auth.py` have no `entry_id`, but they are **main's** AUTH code (2 on `2ec61f3`), not #69's change. That is the same class pre-existing on main; noted as an observation (debt), not a #69 finding.

**Trial merge #69 × #76 `b313933`.** One code conflict, in `subcontractors.py` at the payment audit call. #76's side is a superset (adds `advance_deducted` and the deduction call). Both use `entry_id=mw.new_id("audit_payment")`, so the id is identical whichever merges first. The other conflicts are text only (`run_meta`, the `idempotency.js` pair, which is code-identical).

### main → `cd03324` (#72 + #70 + #78 + **#55**)

Codex results:

| Result | PRs |
|---|---|
| PASS | #55, #71, #73, #77, #74, #78 |
| CHANGES_REQUESTED | **#69 F-69-04**, **#75 F-75-01**, #76 (now fixed at `b313933`) |

The new findings:

- **F-69-04:** sub-cent amounts bypass the cap.
- **F-75-01:** a concurrent piece-rate change gets the same version.

**Audit misses (#69, #75; I had passed both).**

- **#69:** my probes tested the cap with whole and decimal amounts (60 / 50 / 40, 999.99 ×6 on #76), but **not amounts below one cent** (e.g. 0.001 or 0.004 repeatedly) against the cent-tolerance (`_CENT = 0.005`) comparisons.
- **#75:** I checked the LAB-02 retake / FG flows, but **not concurrent piece-rate (akord) changes** racing for the same version number (D-17 territory).

For the fix heads, add:

- (a) N × sub-cent payments and advances (0.001 / 0.004 / 0.0049) against a cap that is otherwise exactly full, sequential and concurrent, plus mixed with a 0.01 boundary. Expect refusal or rounding by the money rule (finite > 0 with 2 decimals?), never cumulative overshoot.
- (b) M concurrent piece-rate changes → distinct, gap-free versions, each with its own AuditEvent; the latest wins.

Main sanity run `bmain2` (PAY, 43 warehouse files, W0, R0, PM-01) is running.

main `cd03324` sanity — **PASS**.

| Gate | Result |
|---|---|
| PAY | 630 |
| warehouse canonical | **44 files / 1121 passed**, 0 bad |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

Identical to #55 `ed48595`'s gates, so the merge introduced nothing.

## 2026-11-08 08:40 UTC: #75 `388b81c` (F-75-01 fix) and #73 `ef8661c`, against main `cd03324`: PASS

**#75 F-75-01:** `set_labor_terms` now runs in one transaction: read → CAS on `labor_terms_version` → history insert (unique `one_terms_version_per_package`, a duplicate gives 409) → audit in the same session.

Probe `docs/audit/probes/lab02/test_probe_f75_01.py` (real Mongo, 3 modes): **51 passed**.

| Case | Result |
|---|---|
| L1: 10 concurrent PUT /labor-terms (×10 per mode) | all 200; versions 1..10 gap-free; AuditEvent chain 1..10; package v10 |
| L2: same key ×6 | 200, then 409 ×5; one version, one event |
| L3: starting from v3 | v1..v9 contiguous |
| L4: rate change ∥ quantity approval | the approval's (rate, version) = (5.0, 1); history {1: 5.0, 2: 9.0}; consistent |

Gates:

| Tree | lab | PAY | W0 | A2C / A1 | R0 | PM-01 |
|---|---|---|---|---|---|---|
| #75 head | 167 (real) | – | – | – | – | – |
| #75 + main (`52f0289`) | 167 | 630 | same 15 | 0 / 0 | 814 | 6 |
| #73 head | lab_01 117 | – | – | – | – | – |
| #73 + main (`2670a53`) | lab_01 117 | 630 | same 15 | 0 / 0 | 814 | 6 |

#73 has no `test_lab_02*`. The batch's combined lab_01 + lab_02 glob made pytest refuse the whole command line, so lab_01 was re-run on its own.

## 2026-11-08 08:55 UTC: #79 `8dc3c45` (Codex F-79-01 + deterministic test_16): PASS

**F-79-01 fix:** the client unit price is now computed exactly, as Decimal material + Decimal labour. The payload carries `unit_price_text` (at least 2 decimals, trailing zeros trimmed), and the PDF uses `unit_price_text` / `qty_text`.

New probe O20 (`docs/audit/probes/off01/test_probe_off01.py`), 3 modes:

| Case | GET review | PDF text |
|---|---|---|
| 5 + 7.345, ×100 | `unit_price_text` "12.345", `line_total` 1234.5 | contains "12.345" and "1234.50" |
| 0.1 + 0.2, ×3 | "0.30" (no float noise) | contains it |
| 19.999 + 0.001, ×7 | "20.00" / 140.0 | contains it |

In all cases there is no split key in the payload, no split figure in the PDF, and no float noise (`0000000` / `9999999`). R43 still holds: O16 keys = activity_name, id, line_total, note, qty, sort_order, unit, unit_price, unit_price_text.

My own first O20 had a false positive ("0.00" is a substring of "20.00"); the probe filter is fixed.

**test_16 is strengthened, not weakened.** Every old assertion is kept. New: deterministic `send_first` / `rival_first` orderings through pause hooks, plus assertions on the winner per ordering (send_first → 200 / 409 OFFER_IN_USE; rival_first → 200 / 409 OFFER_CHANGED), and `orderings == {send_first: 2R, rival_first: 2R}`.

Gates:

| Gate | Result |
|---|---|
| Probe O1–O20 | **675 passed** |
| OFF-01 (clean venv) | 237 |
| Trial merge with main `cd03324` (`a6c7e99`): OFF-01 | 237 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

**Merge with main conflicts only in generated files:** `docs/architecture/W0-03E-A1_INVENTORY.md`, `W0-03E-A2B_INVENTORY.md` and `docs/evidence/PM-01/run_meta.json`. In the trial tree the two inventories were regenerated with their scripts (`w0_03e_a1_inventory.py`, `w0_03e_a2b_inventory.py`), and the static guard plus W0 pass. At merge time: regenerate those, and PM-01 `--harness`.

## 2026-11-08 09:00 UTC: #81 `de0698d` WH-FIX-01 (new PR, periodic pass): 2 BLOCKING

Package: WH-FIX-01 (`claude/happy-meitner-bmcnel` @ `2a52fc4`, which also adds decision R44; #80 docs-only). Diff read for all 11 items. Probe: `docs/audit/probes/whfix01/test_probe_whfix01.py`.

**WHFIX81-01 (blocking): the FG-157 lock is check-then-act.** `_supplier_invoice_link()` runs outside `run_in_transaction`, and the write only CASes the invoice's own `updated_at`. X1a, deterministic (a linked receipt commits between the check and the write): **PUT 200, linked receipts 1, line unit_price 10 → 7.** The free race X1b ×10 was always ordered PUT first (audit seq put 1 < receipt 2, a legal order), so the window is narrow but real.
- Fix: a shared lock document written by both the PUT and the linked receipt, the same pattern as #55's per-line lock (Addendum K). Moving the check into the transaction alone does not help under snapshot isolation.

**WHFIX81-02 (blocking): the waste UI regresses.** `MaterialWastePanel.js:63` posts `{material_name, qty, unit, waste_type, notes}`. The new canonical waste route answers **422 MASTER_IDENTITY_MISSING** (X4), so no waste can be recorded from the UI. A frontend change is missing.

Non-blocking:
- D-WHFIX-03: FG-191 stores an unquantized line price: `unit_value '33.33333333333333333333333333'` for 100 / 3. The `material_entries` value is 100.0000 and total_cost is 100.0.
- #81 × #82: `service.py` conflicts. Semantically, `_supplier_invoice_link` does not skip reversed receipts, so after a WH-REV-01 reversal the supplier invoice stays locked. Whichever merges second must handle both.
- FG-192: the conftest lowers `STRICT_MASTER_IDENTITY_DEFAULT` only for the old fixtures (before the PR the default was env "0" everywhere, so this is not a weakening). The production `_service()` passes strict=True.
- FG-193: create-sub-project no longer rewrites the ledger; the scanner catches indirect handles (PR tests).
- FG-161: the masking reuses the canonical value rules from the session role in every mode. `project_remainders` on the dashboard is quantity only.

PR comment 6719287307. Gates batch `b81` is running on rs0.

#82 `ed8f9e7` WH-REV-01 (new, assigned): probe `whrev01` R1–R7 **111 passed** (details with the gates). #82's own suite: 76. Warehouse gates batch `b82` running on rs3.

## 2026-11-08 09:05 UTC: #69 `b2b3ae0` (addendum H, Codex F-69-04): PASS on the head; rebase onto main needed

**Fix:** `money_value(..., places=2)` refuses more than 2 decimals with 422 before any write; never a silent round. Quantities (`hours`, `qty`) pass `places=None`. The `dated_window` fixture now uses the UTC date. #76's `subcontractors.py` calls the same `money_value` (payments, advances, deductions), so the #69 × #76 merge keeps the rule.

New probe `PROBE_H=1` in `docs/audit/probes/sec01/probe_f6903.py`, 3 modes: **FAILS: none.**

| Case | Result |
|---|---|
| H1: cap 0.05, 20 × 0.0049 sequential | all 422; committed / paid / ledger delta 0 / 0 / 0 |
| H2: cap 0.05, 12 × 0.01 concurrent | exactly 5 × 201 (7 × 409); committed = paid = Σ rows = 0.05; ledger +5 |
| H3: 0.30000000000000004, 1e-3, 5e-324, 123.456789, 99.999 | 422 |
| H3: 10.10, 100, 1e2, 0.01, 12345.67 | 201 |
| H3: `vat_amount` 0.005 | 422 |
| G (audit crash) and F1–F4 together | still pass |

Gates on the head:

| Gate | Result |
|---|---|
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

**Merge with main `cd03324` conflicts** in `permissions/catalog.py`, `routes/procurement.py`, `routes/sales.py`, `tests/test_pm_01_permission_matrix.py` and PM-01 `matrix.csv` / `run_meta.json`. These come from #55's merge; the same files already conflicted at `25ffd9b`. #69 needs a rebase onto `cd03324` before merge. The trial-merge gates must be re-run then.

**Main observation (not #69, debt D-MAIN-PAY-SUBCENT):** finance quick-pay / `create_payment` / `allocate` call `positive_amount` without `places`. Sub-cent amounts are stored as-is; the overpay is bounded by the fixed `remaining + 0.01` tolerance, because after one overshoot the remaining is negative.

## 2026-11-08 09:20 UTC: #82 `ed8f9e7` WH-REV-01 (supplier receipt reversal): PASS, with 1 minor note

Read: the route `POST /warehouse/canonical/receipts/{id}/reverse`, `reversal.py`, `_plan_receipt_reversal` (decided inside the movement transaction), the readers that skip reversed receipts (line lock, covered quantity, Path B links, price history, project conflicts), the `receipt_reversal` cost row, and the actions / envelope.

Checks:
- No hard delete; the receipt row stays.
- `reverses_movement_id` is in the idempotency fingerprint, so reusing a key on another receipt is a 409 conflict.
- Rights: the receipt's own right, in every mode.
- The `distinct("invoice_line_id")` callers in `canonical_material_cost.py` only gather candidates; the rows themselves are filtered by `ledger_invoice_line_links`, which applies `without_reversed`.
- PM-01: the matrix diff only adds rows (24, all for the reverse route).

Probe `docs/audit/probes/whrev01/test_probe_whrev01.py`, real Mongo, 3 modes: **111 passed.**

| Probe | Result |
|---|---|
| R1 ×10: reversal ∥ reversal | 1 × 201 + 409 RECEIPT_ALREADY_REVERSED; one row; WH free 0, live + rebuild ×2 |
| R2 ×10: reversal ∥ new linked delivery | live linked qty ≤ 10 always; P cost = 100 × live deliveries (29 refused, 1 ordered after the reversal) |
| R3 ×10: reversal ∥ reallocation P→Q | reallocation only after the reversal; costs consistent ×3 |
| R4: key K on receipt A, then K on identical receipt B | 409 IDEMPOTENCY_CONFLICT; B untouched (WH free 10) |
| R5: 3 @ 3.3333, 7 @ 0.0001, 1.5 @ 12.345, 0.001 @ 99999.9999 | Σ material_entries exactly 0.0000, live + rebuild ×2 |
| R7: lot moved whole (dispatch + accept) | 409 RECEIPT_ALREADY_ISSUED naming both |

Gates (rs3; PR based on current main, so the merge is trivial):

| Gate | Result |
|---|---|
| wh_rev_01 | 76 |
| warehouse canonical | **44 files / 1121**, 0 bad |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

Minor (D-WHREV-01): R6, `reason` = "   " (blank) is accepted and stored, because `min_length=1` does not strip whitespace.

Interaction with #81 (see WHFIX81): `service.py` conflicts, and #81's `_supplier_invoice_link` must skip reversed receipts.

Audit hygiene: one #81 probe run overlapped the b82 batch on rs3, against my own rule. b82 shows no failed file, so no re-run was needed.

### #81 `de0698d` gates: 2 more BLOCKING (WHFIX81-03, WHFIX81-04)

| Gate | Result |
|---|---|
| wh_fix_01 | 35 |
| warehouse canonical | 44 files / 1121, 0 bad |
| PAY | 630 |
| **W0** | **23 failed** (main's same 15 + 8 new) |
| A2C / A1 guards | 0 / 0 |

**WHFIX81-03 (FG-154): header-allocated invoices that have lines silently leave finance-by-project.** In `dashboard._finance_by_project_rows`, `with_lines.add(inv_id)` runs for every invoice that has any line, before the line's own allocations are checked. A header allocation is then never used, and the invoice is not reported in `unsplit_invoices` either. New W0 failures:
- `test_w0_03e_a1_collision_matrix::test_a1_collision_matrix_over_http[off|shadow|enforce]`: A's `pr-x` is missing.
- `test_w0_03e_r1_exports::test_finance_detail_drilldowns_name_only_tenant_a_records[×3]` and `::test_finance_drilldowns_keep_same_tenant_names_when_b_has_none`.

**WHFIX81-04: stale A1 inventory.** `test_the_committed_inventory_is_the_generated_one` fails: generated 376 / FIXED 130, committed 377 / 131. The README references a `03_gates.txt` that is not committed.

PR comment 6719287307 updated. R0 814. **PM-01: 1 failed (WHFIX81-05).**

**WHFIX81-05 (blocking): the committed PM-01 matrix is not regenerated.** `test_a_fresh_real_mongo_run_reproduces_the_committed_matrix` has 24 cells differing: `POST /api/projects/{project_id}/material-waste` for every role in off/shadow/enforce. The committed matrix has (201, yes, op.material_waste_entries); the real run gives (422, no, -). Regenerate with `--harness` after fixing WHFIX81-02.

Correction: commit 0df7c09 wrote "PM-01 6" by mistake; the real result is 1 failed / 5 passed.

## 2026-11-08 10:45 UTC: #69 `20bd36c` (main `cd03324` merged in with a merge commit): PASS

Merge resolution reviewed with `git show --remerge-diff`:
- `catalog.py`: both action sets kept. Accountant gets #55's warehouse reads / write-off **and** `*MONEY_WRITE_ACTIONS`.
- `procurement.py`: both imports.
- `sales.py`: `POST /sales/commit` keeps #69's `require_money_write` as the first dependency, then #55's fail-closed 410. Non-finance roles get 403; finance gets 410.
- `test_pm_01`: union of the extra writes.
- The `test_sec_01_c02` expectation for `sales_commit` follows #55 (finance → 410, nothing written). That follows main's behaviour and is not a weakening.
- PM-01 matrix and the A1 inventory were regenerated by their tools. `pm01_cells_vs_main_cd03324.csv` shows 455 cells = #69's changes.

Gates on `20bd36c` (rs0, after the machine restart):

| Gate | Result |
|---|---|
| Probe sec01 G + H + F1–F4, 3 modes | **FAILS: none**. G: audit +1. H2: 12 × 0.01 against cap 0.05 → exactly 5 × 201; committed = paid = Σ = 0.05 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| warehouse canonical | **44 files / 1121**, 0 bad |

#82 `e9633aa` (blank reason → 422): the run was void (machine restart; docker down). Diff reviewed and correct. The orchestrator asked for the audit after the FG-195 head.

## 2026-11-08 11:05 UTC: #81 `d2d0ba2` WH-FIX-01 (code = `78c249d`; `d2d0ba2` changes only `03_gates.txt`): PASS, with non-blocking notes

WHFIX81-01..05 re-checked:

| Finding | Status | Evidence |
|---|---|---|
| WHFIX81-01 | **fixed** | A per-supplier-invoice lock (`warehouse_ledger_counters`, `supplier_invoice_lock:<org>:<id>`) is bumped by the PUT and by every linking receipt, inside the transaction. Probe X1a: **PUT 409, price stays 10.** X1b ×10: legal order only. |
| WHFIX81-02 | **fixed** | `MaterialWastePanel` picks a Master item from the project ledger, uploads evidence (`/media/upload` → `file_ids`) and sends an `Idempotency-Key` (createKeyHolder) |
| WHFIX81-03 | **fixed (by Р45)** | No invoice disappears: a header-only allocation goes to `to_allocate`. The three W0 test expectation changes (collision matrix, r1_exports, real_mongo) are authorized by Р45 / A4 #13, with citations. |
| WHFIX81-04 | **fixed** | A1 inventory regenerated; `03_gates.txt` committed |
| WHFIX81-05 | **fixed** | PM-01 regenerated, real run 6 / 0 skipped |

Р44 / Р45 checks:
- Р44 409 on every payment path is covered by the PR tests (`test_wh_fix_01_a3_r44_allocation.py`).
- X7: `GET /invoice-lines/invoices-to-allocate` ×2 changes **no collection**, 3 modes, mongomock and real; the partly allocated invoice is listed.
- The migration script defaults to a dry run (`--apply` writes), is idempotent, has a finance actor, writes an AuditEvent per line and never deletes.

Gates on `78c249d` (rs1):

| Gate | Result |
|---|---|
| wh_fix_01 + a3_r44 | 134 |
| warehouse canonical | 44 files / 1121, 0 bad |
| PAY | 630 |
| W0 | **same 15** |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

Non-blocking:
- **WHFIX81-06 (decision for Krum):** Р44 blocks payment until 100% allocated, but the allocation of a **Paid** supplier invoice can still be reduced afterwards (X5: 100% → 60%, 200, invoice stays Paid, AuditEvent written, DQ reopens). The race payment ∥ reallocation (X6, `ensure_payable` runs without the transaction's session) reaches the same state. Whether a paid invoice's allocation may be reduced, or only corrected through a versioned correction like FG-195 in #82, is for Krum.
- D-WHFIX-03b: the FG-191 quantize stores unit 33.3333, so the `material_entries` value is 99.9999 against an invoice line of 100.00 (0.0001 residue; total_cost rounds to 100.0). Storing the lot value, not only the unit, would be exact.
- The W0 isolation coverage is thinner: with the Р45 expectations, the colliding project id `pr-x` no longer shows A's name anywhere, so "colliding id → A's name, not B's" is no longer asserted for finance-by-project. Suggestion: add an A line allocated to `pr-x` in the fixture.
- #82 interaction: `_supplier_invoice_link` still does not skip reversed receipts. This is recorded as debt in the code; whichever PR merges second carries it.

## 2026-11-08 10:30 UTC: periodic pass

- #69 `faa3da0` = `20bd36c` plus one evidence file (`docs/evidence/SEC-01-MAIN-MERGE/README.md`, +16, docs only). The `20bd36c` PASS applies; no code changed.
- All other heads are unchanged since their last audit: 71 b1ab349, 73 ef8661c, 74 31a9478, 75 388b81c, 76 b313933, 77 2cc1147, 79 8dc3c45, 80 28b5ab6, 81 d2d0ba2, 82 e9633aa (waiting for the FG-195 head). main `cd03324`.

## 2026-11-08 11:50 UTC: #82 `1622f62` WH-REV-01 Addendum A (FG-195, Р46, Р47; FG-197 blank reason from `e9633aa`): PASS

Read:
- **FG-195:** `_correction_after_reversal` runs in the write's transaction. On a line with reversed linked receipts, a change of allocation / qty / unit / price needs a reason (else 409 ALLOCATION_CORRECTION_REQUIRED) and writes an `invoice_versions` snapshot plus an AuditEvent.
- **Р46:** a new action `warehouse.reverse_supplier_receipt[_to_project]` at the route and in the service, for Warehousekeeper / Accountant / Owner / Admin. Procurement can no longer reverse.
- **Р47:** an `expected_credit_notes` row per reversed linked receipt (deterministic id, so a replay adds no second row). The invoice CAS respects the PAY-01 row lock (INVOICE_BUSY). Quick-pay and `allocate_payment` refuse more than the net payable with 409 INVOICE_AWAITS_CREDIT_NOTE. These are the only two paths that write `payment_allocations`.
- FG-195's AuditEvent is written with `record_event(db, …)`. `_tenant()` wraps the same `db`, so this is equivalent under the current layout, and the A2C / A1 guards are 0.

Probe whrev01, now R1–R9 (3 modes, real Mongo): **144 passed.**

| Probe | Result |
|---|---|
| R6: blank reason | 422 |
| R8 ×10: reversal of 4 (credit 48) ∥ quick-pay 120 | exactly one winner every time: reversal 409 INVOICE_BUSY + payment 201 (11/30), or reversal 201 + payment 409 INVOICE_AWAITS_CREDIT_NOTE (19/30); never both |
| R9: reversal while the payment holds the row lock (deterministic) | 409 INVOICE_BUSY; payment ok; no ECN |
| R1–R5, R7 | as before |

Gates (rs3; after the second machine restart of the day):

| Gate | Result |
|---|---|
| wh_rev_01 | 101 |
| warehouse canonical | 44 files / 1121, 0 bad |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The PM-01 delta (36 cells) is Р46: SiteManager → 403, Accountant → passes the route.

## 2026-11-08 12:00 UTC: #81 `2d60acd` (delta from `d2d0ba2`: WHFIX81-06, exact line price, W0 name check restored): PASS

- **WHFIX81-06, fixed.**
  - `allocate_invoice_line` claims the invoice in its transaction, a CAS that honours the PAY-01 row lock.
  - On a Paid / PartiallyPaid invoice, a change without `correction_reason` → 409 ALLOCATION_CORRECTION_REQUIRED. With a reason: an append-only `invoice_line_allocation_versions` row, `allocation_version + 1`, and an AuditEvent.
  - `PUT /finance/invoices/{id}/lines` applies the same rule to embedded lines (`invoice_versions` snapshot + AuditEvent).
  - Probe X5: pay, then reallocate to 60 → **409**, line stays 100. X6: a reallocation during the payment → **409**, payment 201, line 100. X7: the GET still writes nothing.
- **Exact price:** a line's own `unit_price` is used exactly. Only a derived `total / qty` is quantized to 4 decimals (recorded debt, ≤ 0.0001 × qty).
- **W0:** the shared-project name check is restored in `test_w0_03e_a1_collision_matrix`, `test_w0_03e_r1_exports` and `test_w0_03e_real_mongo`: A's line on the shared invoice id, allocated to `pr-x`, gives `A-OWN-PROJECT`.

Gates (rs1):

| Gate | Result |
|---|---|
| wh_fix_01 + a3_r44 | 177 |
| warehouse canonical | 44 files / 1121, 0 bad |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

Still open for whichever of #81 / #82 merges second: the `service.py` conflict, and `_supplier_invoice_link` must skip reversed receipts.

## 2026-11-08 12:10 UTC: main moved to `4bca18a` (Merge PR #69, Krum's approval relayed by the orchestrator)

Verified:
- The tree of `4bca18a` = the tree of `faa3da0` = `590847be…` (byte-identical).
- Parents: `cd03324` + `faa3da0`.
- `faa3da0` = `20bd36c` + one docs file, and `20bd36c` passed the full merged gates (sec01 probe G/H/F, SEC-01 30, PAY 630, W0 same 15, A2C / A1 0 / 0, R0 814, PM-01 6, warehouse 1121).

So the main sanity of `4bca18a` is covered by that run; no re-run is needed.

Merge queue (orchestrator): #71 (merging main) → #77 → #74 → #76 → #73 + #75 → #79 → #81 → #82. Each must be re-audited on its merge with the new main (conflict resolution and gates).

## 2026-11-08 12:55 UTC: #81 `7d887fd` (delta from `2d60acd`: FG-215, Р44 / Р45 for supplier invoices only): PASS

- **The change:** `under_r45(inv)` = `direction == "Received"`. It gates stamping, the final state (an Issued invoice counts as ALLOCATED), `apply_header_destination`, the DQ refresh and the migration query. `_finance_by_project_rows` keeps main's header counting for Issued invoices that have no line-level project allocation.
- **The three W0 test edits** move back toward main's expectations (`pr-only-b` counted again because its invoice is Issued) and keep the restored shared-project name check. Not a weakening.

| Gate | Result |
|---|---|
| Probe `_r44` X5–X7 | 18 passed |
| wh_fix_01 + a3_r44 | 185 |
| warehouse canonical | 44 files / 1121, 0 bad |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

#80 `344c197`: docs only (decisions Р48 / Р49, packages CP-01 and INV-CN-01).

## 2026-11-08 13:05 UTC: #71 `eff56bf` (merge `c6e3e06` of main `4bca18a`): BLOCKING, SEC71-M1

| Check | Result |
|---|---|
| Byte check | the tree of `c6e3e06` vs `merge-tree(4bca18a, b1ab349)` differs only in the three conflict resolutions (catalog.py, test_pm_01, DashboardLayout.js) and generated / evidence files (A2B inventory, PM-01 matrix / run_meta, SEC-02 results / scans, SEC-02-MAIN-MERGE). `eff56bf` adds only `test_summary.txt`. |
| No weakening | for every canonical role, the merged action set = the **exact union** of `b1ab349` and `4bca18a`. ACTIONS: 0 missing, 0 extra. |
| PM-01 delta | merged vs main = **1614 cells / 120 routes** = #71's own delta (merge-base `7300864` → `b1ab349`); 0 cells in one set but not the other |
| Gates | sec01 probe G/H none; sec02 bisect only the known-pay variant (R42); SEC-02 + SEC-01 60; PAY 630; W0 same 15; A2C / A1 0 / 0; R0 814; PM-01 6 |
| **Warehouse canonical** | **44 files, 1084 passed, 37 FAILED** (main `4bca18a` alone: 1121) |

**SEC71-M1 (blocking).** #71's `strip_money_for_non_finance` wrapper pops a keyword-only `_sec02_request` that FastAPI injects. #55's warehouse report tests call the decorated handlers directly (`project_pnl.get_project_pnl(PROJECT, user=u)` and others), so they get `KeyError: '_sec02_request'` (`money_write.py:309`).
- Failing files: c19 ×2, c20 ×1, c22 ×8, c23 ×1, c24 ×2, c25 ×7, c26 ×10, c26k ×6.
- Production over HTTP is unaffected, but the merge turns main's warehouse gate red. The merge evidence did not run the warehouse suite.
- Fix: pass a Request in those direct calls, or make the wrapper fail closed (strip) when no request is present, never "visible". Then re-run warehouse.

PR comment 6695992847 updated.

## 2026-11-08 13:20 UTC: #81 `d2fe80b` (merge of main `4bca18a`): BLOCKING, WHFIX81-M1

- **Byte check:** the tree equals `merge-tree(7d887fd, 4bca18a)` plus the resolutions:
  - material_waste.py: SEC-01 gate + qty + project-in-tenant, then the R27 / FG-159 canonical write-off;
  - MaterialWastePanel.js;
  - the WHFIX81-01 lock moved onto `supplier_invoices.link_lock_seq`;
  - plus SEC-01 / WH-FIX-01 test and evidence edits.
- **Test edits:** all of them are `waste_create` → 422 (FG-159, no Master item in the harness body). The rights asserts are kept (Viewer → 403). SEC-01's waste idempotency probe is skipped; that coverage moves to `test_fg159_*`.
- **Probes:** X1a 409 (the price stays 10); X5–X7 18.
- **wh_fix_01 + a3_r44:** 185.
- **WHFIX81-M1 (blocking): SEC-01 29 / 30.** `test_the_pm01_matrix_shows_the_money_write_cells_closed` fails: PM-01 has POST material-waste at **503** for Owner / Admin / Accountant in every mode; main has **428**. The key check now runs after `require_project_writeoff` / `_r27_first`, which do DB and index work (the canonical 503). Fix: key (428) before the R27 resolution; regenerate PM-01; SEC-01 must be 30.
- PR comment 6719287307 updated. Rest of the gates on the merge: W0 same 15, A2C / A1 0 / 0, R0 814, PM-01 6, PAY 630, warehouse 1121. Only SEC-01 is red (WHFIX81-M1).

## 2026-11-08 13:20 UTC: #83 `ea51030` CP-01 (counterparties, Р48): BLOCKING, CP83-01

- **CP83-01 (blocking):** `approve-change` does not exclude the entrant or the verifier. Probe `cp01/test_probe_cp01.py` K1, 3 modes × (mongomock, real): acct-a enters, the Owner verifies, acct-a approves 200, the Owner approves 200. The new IBAN is **verified**, the old one replaced, and the payment goes to the new IBAN, with **2 distinct people**. Fix: entrant ≠ approver; recommended: verifier ≠ approver.
- **K2 ×10, activation ∥ payment:** the payment always goes to the old or the new **verified** account. OK.
- **Payment guard:** a named unverified account, an invoice-IBAN mismatch or a pending-only counterparty → 409 in every mode. The legacy case with no account and no counterparty follows `BANK_ACCOUNT_GUARD_MODE`; the default shadow lets the payment through with a DQ row (debt D1, for Krum).
- **W0 test edit** (4 collections → `test_cp01_counterparty_identities_are_never_deleted`): stricter, not a weakening; the generic delete paths are still covered via `location_nodes`.
- PR comment 6721864098.
- Gates (rs2): cp_01 401 (+3 mongomock skips of the real-only concurrency tests); PAY 630; **W0 9 failed, all within main's 15 (NEW_FAILS=0)**; A2C / A1 0 / 0; R0 814; PM-01 6; warehouse 44 files / 1121. SEC-01 not present on its base cd03324.
- Rebase needed: merging with main conflicts in clients.py, projects.py, subcontractors.py, ProjectOperationsPage.js plus generated files. #69's money-write guards meet CP-01's rewrites there, so re-audit the merge (SEC-01 30).

## 2026-11-08 13:30 UTC: main → `8c52e92` (Merge PR #80, docs only)

Verified:
- The tree of `8c52e92` = `merge-tree(4bca18a, e1bf2eb)`.
- Parents: `4bca18a` + `e1bf2eb`.
- 0 files changed outside `docs/` vs `4bca18a`.

So gates run on heads containing `4bca18a` stay valid. New canon: Р51 (invoice cancellation approval, incoming debit note, wrong incoming invoice, every offset two people) plus INV-CN-01 addendum A. #84 must follow it on its next head.

## 2026-11-08 13:45 UTC: #84 `7446d85` INV-CN-01 (credit / debit notes, Р49): BLOCKING, INV84-01 (red gate; behaviour correct)

Probe `invcn01` V1–V5 (99 passed on the head and on the trial merge with `4bca18a`, `3cca911`):

| Probe | Result |
|---|---|
| V1 lock matrix | every InvoiceUpdate field + `/lines` + DELETE → 409 on issued and sent. `total` / `subtotal` are not model fields (ignored); my first V1 flagged them falsely. |
| V2 ×10, cancel ∥ send | never both |
| V3 ×10, cancel ∥ payment | never cancelled with a payment |
| V4 ×10, refund ∥ offset approval (balance 36) | exactly one wins |
| V5, 6 × the same incoming number | 1 row |

Other checks:
- The 2 PAY-01 asserts are canon tightenings (Р49.2; §2.9 numbered draft), and the positive path is kept.
- Approve claims the invoice and re-runs the credit cap; the act cap claims the act; numbering is an atomic `$inc` in the transaction.
- Same-person approval → 409; exact version.

| Gate | Head | Trial merge |
|---|---|---|
| inv_cn_01 | 57 | 57 |
| PAY | 630 | 630 |
| W0 | same 15 | same 15 |
| A2C / A1 | 0 / 0 | 0 / 0 |
| R0 | 814 | 814 |
| PM-01 | 6 | 6 |
| SEC-01 | n/a (no SEC-01 on the base) | **30** |
| **warehouse** | **1118 / 1121** | **1118 / 1121** |

**INV84-01:** `test_warehouse_canonical_c26l_n_invoice_status.py::test_fg140_claim_honours_the_pay01_invoice_lock[×3]`. #55's test cancels under the PAY-01 lock without a reason, and Р49.2 now refuses with 400 REASON_REQUIRED first. Re-run with a reason: locked → 409 INVOICE_BUSY, released → Cancelled (3 modes). Behaviour OK; the test needs the reason; the gate is red until then.

Main `8c52e92` added Р51 (affects INV-CN-01). PR comment posted.

## 2026-11-08 14:20 UTC: #81 `625ece1` (WHFIX81-M1 / FG-224 fix): PASS

- **Delta from `d2fe80b`:** the material-waste key check (428) now runs right after the SEC-01 gate and its input checks, **before** `require_project_writeoff` / `_r27_first`. Refused roles still get 403 from the SEC-01 dependency first.
- PM-01 sends no key for this route (as on main), so the cells test the permission: allowed → 428, refused → 403. The matrix was regenerated by the harness.
- The first gate run was void (machine restart); re-run from scratch.

| Gate | Result |
|---|---|
| **SEC-01** | **30 / 30** |
| Probe X1a | PUT 409, price stays 10 |
| Probe X5–X7 | 18 |
| wh_fix_01 + a3_r44 | 185 |
| warehouse canonical | **44 files / 1121** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

The X4 probe failure is my probe's `request=None` limitation (known), not the code.

## 2026-11-08 14:30 UTC: #84 `71957db` (merge of main `8c52e92` + Addendum A / Р51): INV84-01 STILL OPEN (6 red; behaviour correct)

- **Merge `8cbd15a` byte check:** the tree equals `merge-tree(3893b9f, 8c52e92)` plus the 2 generated conflicts only.
- **Probe `invcn01`, updated for Р51** (cancel = proposal + Owner approval; offset needs legal_basis + file_id + source_credit_note_id): 99 passed. A stale cancellation proposal approved after a payment → 409 USE_CREDIT_NOTE; V4 exactly one wins.
- **Migration:** the dry run is read-only; idempotent; no document deleted; AuditEvent per migrated invoice. Minor: it drops the legacy unique index before building the new one.

| Gate | Result |
|---|---|
| inv_cn_01 | 90 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1115 / 1121** |

**INV84-01 (6 red, all in `c26l_n_invoice_status`):**
- the lock test needs the Р49 reason (verified: locked → INVOICE_BUSY, released → Cancelled);
- `send_and_delete_are_conditional` must accept INVOICE_NUMBERED for the delete (verified: then it passes, nothing written).

PR comment 6722039745 updated with the exact test fixes.

## 2026-11-08 15:00 UTC: #84 `5cce932` (INV84-01 fix): PASS

- **Diff vs `71957db`:** tests and evidence only. The lock test now cancels as the Accountant with a reason on a Received invoice; the send/delete stale snapshot is an unnumbered draft. No production code changed and no assertion weakened.
- **Probe `invcn01`:** 99 passed.

| Gate | Result |
|---|---|
| inv_cn_01 | 90 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

INV84-01 resolved. Remaining minor note (non-blocking): the migration drops the legacy unique index before creating the new one.

## 2026-11-08 15:05 UTC: #71 `6fe8594` (= `021a078` + evidence; SEC71-M1 fix): PASS

- **Wrapper:** `_request_of` returns None on a direct call, and the decorators then strip money (fail closed, no crash).
- **#55 tests:** they pass `_sec02_request`; 6 calls changed, 0 assertions changed.
- **Enforce fixture:** it gives only `u-<tenant>` an Owner assignment; everyone else goes through the real loader, so no rights are widened.

| Gate | Result |
|---|---|
| sec01 probe G/H | none |
| bisect probe | only the known-pay variant (R42, accepted) |
| SEC-02 + SEC-01 | 61 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

SEC71-M1 resolved. No blocking finding remains.

## 2026-11-08 14:56 UTC: main `0750d75` (merge of #71): verified

- **Parents:** `8c52e92` + `021a078` (the audited head).
- **Byte check:** the tree `74c823f` equals `git merge-tree --write-tree 8c52e92 021a078`.
- **Next:** #81, #83 and #84 must merge main `0750d75` before their own merge; each such merge gets a full re-audit.

## 2026-11-08 15:20 UTC: #83 `7e0b914` (FG-225..230 on top of `fe13c43`; merge `63b6635` unchanged): FAIL, 2 blocking

- **Merge `63b6635`:** the byte check and the resolutions from the `fe13c43` round still hold; `7e0b914` is one commit with no new merge.
- **K1:** entrant + verifier → 409 SAME_PERSON_APPROVAL (66 passed with K2).
- **ЕГН:** one mask `******1234`; readers mask `invoice_details`; ЕГН search only for roles that may see it.
- **FG-229:** the ЕИК check spans counterparties and subcontractors, under one claim row.

**CP83-02 (BLOCKING), probe K3:**
- **Cause:** FG-225 (c) pasted the Outflow guard into `create_other_income`.
- **Enforce:** income into a Bank account → 409 NO_VERIFIED_BANK_ACCOUNT. The UI sends `method: "Cash"` with a bank `account_id`, and the account decides the method.
- **All modes:** cash income with a counterparty → 422 CASH_RECEIPT_REQUIRED.
- **K3:** 5 of the 9 mongomock cases fail.

**CP83-04 (BLOCKING): warehouse canonical 1088 / 1121.**
- **Where:** all 33 failures are in `c26l_n_invoice_status` (`edit_racing_send_and_pay` ×30, `paused_edit_after_payment_is_409` ×3).
- **Cause:** the quick payment of the Received fixture invoice (BankTransfer, no verified IBAN) → 409 BANK_ACCOUNT_NOT_VERIFIED in enforce. The same file had 72 passed at `ea51030`.
- **Behaviour:** correct (Addendum A D1: enforce outside staging, development and test).
- **Fix:** the test fixture seeds a verified supplier bank account (preferred) or sets ENV=test with the guard off; list it in the HANDOFF.

**CP83-03 (minor):**
- The migration masks `invoice_details` with no AuditEvent per project.
- This is irreversible for a typed value with no matching `persons` record.
- A 10-digit `tax_id` is masked for companies too.

| Gate | Result |
|---|---|
| probe K1/K2 | 66 |
| cp_01 | 482 (+3 mongomock-only skips) |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | 9 failed, all also on main (NEW_FAILS 0) |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1088 / 1121** |

## 2026-11-08 15:30 UTC: #81 `20b1663` (Codex F-81-01 / F-81-02): gates PASS; WH81-03 open (orchestrator / Krum decision)

- **F-81-01:** supplier invoices reach these readers only by their lines' allocation (`received_result`):
  - finance-details/summary;
  - company-finance-series;
  - reports company-finance-summary, month totals and export;
  - the project-profit fallback.
- **F-81-02:** Issued invoices stay on the header total in every reader.
- **Not a result under Р45 (not a finding):** by-counterparty turnover and the transactions list show the full Received document total; that is document turnover.

**WH81-03 (pre-existing on main), probe X8:** four project readers query invoices by `{org_id, project_id}` with no `direction` filter, so a Received invoice with a header project is counted as project REVENUE.
- **Where:** `project_pnl.compute_project_pnl` L29, `compute_pnl_trend` L223, `centralized_reports` L324, `project_financial_results` L31.
- **X8:** a 1000 + VAT supplier invoice, unallocated or allocated to another project → prj-1 P&L revenue 1000, invoiced 1200, trend 1000, centralized revenue 1000. Expected 0.
- Sent to the orchestrator: blocking or follow-up.

| Gate | Result |
|---|---|
| probe X5–X7 | 18 |
| probe X1–X4 | 12 + X4 (the probe's known `request=None` limitation) |
| SEC-01 | 30 |
| wh_fix_01 (incl. f81_readers) | 287 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

## 2026-11-08 15:50 UTC: #84 `081f35b` (Addenda B+C: Р52 D7/D8/D12, Р53 FG-231..235): PASS, no blocking finding

- **D8, on my own trial merge of `081f35b` + #82 `1622f62`:**
  - conflicts resolved as in the evidence: `finance.py` keeps both the Р51(2) and the Р47 checks; `ownership.py` keeps one entry;
  - inv_cn_01 + wh_rev_01 + the trial D8 test: **215 passed** on real Mongo;
  - a credit linked to a #82 reversal has no second cost effect; a defect credit lowers the project material cost once (10.00).
- **accept-difference:** Owner only (`APPROVER_ROLES = ("Owner",)`, Accountant → 403 tested). Reason, key, conditional write and an AuditEvent, all in one transaction.
- **FG-231 migration:**
  - `plan` only reads;
  - `apply` refuses (nothing changed) while supplier+number conflicts exist;
  - the `supplier_key` backfill is conditional on direction.

**Non-blocking notes:**
- **FG-233 residual:** a ledger movement linked only by `invoice_id` writes no shared lock document. The receipt command also never reads the invoice's status, so even sequentially it can name a cancelled supplier invoice. The effect is data quality (a stale reference; the goods and the cost are real; nothing is payable on a cancelled invoice); no money moves. Recommendation: debt. A receipt with `invoice_id` should bump a per-invoice lock or check the status in its transaction.
- **INV84-02:** the Р52(1) note effect is applied only in `project_pnl.compute_project_pnl`. The other project cost readers (centralized_reports, project-profit, financial-results) do not apply it, so readers disagree after a defect credit.
- **Indexes:** the migration still drops the legacy index before creating the new ones. `server.py` creates both indexes in one `try`, so if the first fails the second is skipped.

| Gate | Result |
|---|---|
| probe invcn01 V1–V5 | 99 |
| inv_cn_01 | 111 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

## 2026-11-08 16:00 UTC: #81 `5b08e59` (WH81-03 fix on top of `20b1663`): PASS, no blocking finding

- **Delta vs `20b1663`:** `"direction": "Issued"` added to 7 revenue / incoming queries (project_pnl pnl + trend, centralized_reports, project_financial_results, client summary, project aggregate `count_invoices`, cashflow incoming), plus tests. Turnover views are untouched (correct: document turnover). F-81-01 / F-81-02 unchanged from `20b1663` (verified there).
- **Probe X8:** 12 passed (was red at `20b1663`).

| Gate | Result |
|---|---|
| probe X5–X7 | 18 |
| probe X1–X4 | 12 + X4 (the probe's known `request=None` limitation) |
| probe X8 | 12 |
| SEC-01 | 30 |
| wh_fix_01 (incl. f81_readers) | 299 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

#81 still has to take in main `0750d75` before its merge; that merge gets a full re-audit.

## 2026-11-08 16:35 UTC: periodic pass. main `ec7ddd8` verified; #77 / #83 / #86 under audit

- **main `ec7ddd8`** (merge of #85, canon R52–R55 + task packages): docs only (3 files under `docs/`). Tree `9365caa` equals `merge-tree(0750d75, ea9ef8e)`.
- **#77 `c7df7ca` (merge `5d75736` of main `0750d75`):**
  - Not a plain merge: it ports ACT-01's own permission code onto main's mechanisms. `client_act_write.py` is removed; create/confirm use #69 `require_money_write`; PUT, from-offer and remaining use #71 `require_finance_read` (R20-2 for PUT and from-offer, as on main; R20-1 for remaining).
  - **Role-union:** every role equals the union of both parents except `finance.client_act_money.read`, which is dropped from owner/admin/accountant. It narrows rights, nothing references it any more, and the act GETs are R20-1 (finance only).
  - **PM-01 delta:** all 120 of #77's own cells keep the PR's value on the merge (0 differ). 45 of them already had that value on main. No extra cells.
- **#83 `e36af6e`** (`6449dac` CP83-02/03 fixes, merge `616a66c` of `0750d75`, CP83-04 fixture):
  - **Merge:** only the 4 conflict files differ from `merge-tree`. `subcontractors.py` takes the union of the imports (`require_money_write` + `require_finance_read` + `strip_money_for_non_finance`). The guard stays before `MoneyWrite.begin`.
  - **CP83-02:** the guard is removed from other-income.
  - **CP83-03:** a stored copy is masked only when `persons` holds the same ЕГН; otherwise it is kept with a DQ issue. The migration writes an AuditEvent per masked project and `--apply` needs the dry run's `--plan-token`; a 10-digit company `tax_id` is no longer masked.
    - Minor: the DQ `entity_id` is the owner id in the route but the project id in the migration.
  - **CP83-04:** the fixture gets a verified supplier account through the real register (Accountant enters, Owner verifies from 2 sources); the guard stays on; no assertion changed.
- **#86 `4bf5eae`** (PRJ-01, new): first review only. Delete is allowed only for an empty Draft (409 PROJECT_HAS_HISTORY / PROJECT_NOT_DRAFT); it needs a key and writes an AuditEvent in one transaction. Archive/cancel are conditional status changes with a reason. Photos are retired, not deleted.
- **Machine restart at ~16:26 UTC:** the first gate runs (b77f/b83d/b86a) were voided and re-run from scratch.

## 2026-11-08 17:15 UTC: #77 `c7df7ca` (ACT-01 + merge `5d75736` of main `0750d75`): PASS, no blocking finding

- **Merge checks:** see the 16:35 entry (role-union only narrows: `finance.client_act_money.read` dropped; PM-01 120/120 cells, 0 extra).
- **Guards on the merged head:**
  - create and confirm use `require_money_write` (#69);
  - list, detail, PUT, from-offer and remaining use `require_finance_read` (#71);
  - every act read is R20-1, so a non-finance caller gets 403 and never sees money;
  - FG-142 expected values must be whole cents (`money_value`).
- **C02 test:** fixture and confirm body only; the assertions are unchanged.

| Gate (serial re-run after the restart / disk crash) | Result |
|---|---|
| act01 | 113 |
| probe act01 | FAILS none (enforce: 428 without a key, 201, replay 201, 409; 1 act, 1 event) |
| SEC-01 + SEC-02 | 61 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

- **#84 `2c2e75f`, merge checks done ahead of its run:**
  - merge `5692247` tree = `merge-tree(d32a33f, ec7ddd8)`;
  - role-union: 0 differences;
  - PM-01 delta: 360 cells = the PR's own, 0 extra.
- **Disk:** the space allowance hit 0 at ~16:36 and all 3 mongod crashed. I removed my old worktrees and an old venv; `docker volume prune` (~20 GB of dangling scratch volumes) was refused by the permission check and is asked of Krum. Runs are serial until then.

## 2026-11-08 17:50 UTC: #83 `bc0d1c7` (CP83-02/03/04 + merge `616a66c` of main `0750d75` + FG-241..245): PASS, no blocking finding

- **Merge and CP83 fixes:** see the 16:35 entry. CP83-02, CP83-03 and CP83-04 are resolved.
- **FG-242..245 (`bc0d1c7`):**
  - payee name / ЕИК are passed to the guard;
  - `full_iban_allowed` moved into `counterparty_rules`;
  - counterparty and invoice responses mask IBAN fields for roles without the full right.
  - A masked `****1234` sent back is rejected by `_invoice_iban` (422) and never overwrites the stored IBAN; project `invoice_details` use `keep_stored_if_masked`.

| Gate | Result |
|---|---|
| probe K1–K3 | 84 |
| cp_01 | 548 (+3 mongomock-only skips) |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | 9 failed, all also on main (NEW_FAILS 0) |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

Minor (non-blocking): the DQ `entity_id` for an ЕГН copy is the owner id in the route but the project id in the migration.

## 2026-11-08 18:25 UTC: #86 `0bd77a1` (PRJ-01, R54; new PR): PASS, no blocking finding

- **PRJ86-01 (red at `4bf5eae`):** `test_the_committed_evidence_is_a_run_of_this_harness` failed because `docs/evidence/PRJ-01/results.json` was not committed. Resolved at `0bd77a1` (evidence-only commit; no code change).
- **Delete (FG-239):** only an empty Draft. Any business link → 409 PROJECT_HAS_HISTORY with the links; a non-Draft → 409 PROJECT_NOT_DRAFT. It needs a key (428), is Owner/Admin only, and writes the AuditEvent in the same transaction. Archive/cancel: reason + key + a conditional status change + an AuditEvent.
- **Photos (FG-238):** retired (status, reason, who, when); the row and the file are never deleted.
- **Reopen (FG-237):** reason (400), key (428), Owner/Admin only (others 403, cross-tenant 404), one open cycle, AuditEvent `project.reopen` (FLOW-001); covered by the PR test incl. enforce.
- **Warranty migration (FG-236):** dry run by default; `--apply` needs `--approved-by` and the current plan SHA; no deletes; an AuditEvent per link.
- **Score (FG-240, R54):**
  - writers: Owner/Admin anywhere; a SiteManager only on a project they manage;
  - every change is a new version (the previous one stays in `subcontractor_performance_versions`) plus an AuditEvent, in one transaction;
  - "paid" is computed from `finance_payments` Outflow rows of subcontractor payments (`active_payments`, reversals excluded); a typed value → 422 ACTUAL_PAID_IS_COMPUTED.
  - Minor: `quality_score` has no range check.

| Gate | Result |
|---|---|
| prj_01 | 9 |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

## 2026-11-08 18:30 UTC: main `fddb018` (merge of #77): verified

- **Parents:** `ec7ddd8` + `c7df7ca` (the audited head; PASS at 17:15).
- **Byte check:** the tree `faeb3b8` equals `merge-tree(ec7ddd8, c7df7ca)`.
- **Next:** #84 (`2c2e75f`, running against main `ec7ddd8`), #81, #83 and #86 must take in `fddb018` before their own merge; each such merge gets a full re-audit.

## 2026-11-08 18:01 UTC: check-in. New heads #74 `4c8b313`, #84 `b99c0eb`, #86 `19d77cf`; serial queue restarted

- **Correction:** the two previous entries are stamped 18:25 and 18:30, but the real times were about 17:55 and 17:58. From now on entries are stamped from `date -u`.
- **#74 `4c8b313`** (merge `182ea574` of main `fddb018` + evidence):
  - Conflicts: `full_cost.py`, `overhead.py`, `server.py`, frontend `idempotency.js`/test, and generated files.
  - `overhead.py`: the snapshot route keeps #69's `require_money_write("finance.overhead_snapshot_compute.execute")` gate before any read or write; the one key path is OH-01's `KeyedWrite` (main's `MoneyWrite` block intentionally dropped, as its own comment foresaw).
  - `full_cost.py`: OH-01's costs line plus main's waste split.
  - **Role-union:** 0 differences.
  - **PM-01:** 45 own cells, all keep the PR's value on the head (9 already equal on main); 0 extra.
- **#84 `b99c0eb`** (FG-264 on top of `2c2e75f`, code): the run on `2c2e75f` was stopped (stale) and re-queued on the new head.
- **#86 `19d77cf`** (PRJ-01 rounds 2–3: FG-252..256, R56, "paid" from all ledger payments and advances): queued.
- **Serial order:** #74 → #84 → #86.

## 2026-11-08 18:25 UTC: #74 `4c8b313` (OH-01 + merge `182ea574` of main `fddb018`): PASS, no blocking finding

- **Merge checks:** see the previous entry (resolutions; the #69 gate is kept on the snapshot route; role-union 0; PM-01 45/45, 0 extra).

| Gate | Result |
|---|---|
| oh01 | 231 |
| probes oh01 + Codex OH74 interruptions | 27 |
| probe f6903 | FAILS none |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

**#84 `d5d3089`** (FG-264 + Р58/FG-265 + merge `142d2720` of main `fddb018`): merge checks done ahead of its run.
- **Byte check:** the merge differs from `merge-tree(158ae878, fddb018)` only in the generated `run_meta.json`.
- **Role-union:** 0 differences.
- **PM-01:** 360/360, 0 extra.
- **Р58 reader** `GET /finance/company-costs/accepted-differences`: finance roles only, read-only, derived from the accepted notes.
  - Observation (non-blocking): the company-cost part is not in the company finance summaries.
- **#86:** skipped at the orchestrator's request until its final head (it will merge `fddb018`).

## 2026-11-08 18:26 UTC: periodic pass. #86 `e0fd1e2` (merge of main `fddb018`) merge checks; queued after #84

- **Byte check:** the merge `e0fd1e2` differs from `merge-tree(30a92ae, fddb018)` only in the generated `PM-01/run_meta.json` and `SEC-02/results.json`.
- **Role-union:** 0 differences.
- **PM-01:** 168 own cells, all keep the PR's value on the head; 0 extra.
- **Gates:** queued after #84 `d5d3089` (serial).

## 2026-11-08 18:26 UTC: main `1ea98fe` (merge of #74): verified

- **Parents:** `fddb018` + `4c8b313` (the audited head, PASS).
- **Byte check:** the tree `bde4153` equals `merge-tree(fddb018, 4c8b313)`.
- **Next:** #76 is merging main. #83, #84 and #86 need `1ea98fe` before their own merge.

## 2026-11-08 18:50 UTC: #84 `d5d3089` interim gates (head superseded; #84 paused until its final head)

| Gate | Result |
|---|---|
| probe invcn01 | 99 |
| inv_cn_01 | 132 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | **2 failed** |
| **warehouse** | **1121 (44 files, 0 bad)** |

- **PM-01:** the committed matrix at `d5d3089` lacks the 24 cells of the new Р58 route `GET /finance/company-costs/accepted-differences`. `caea933` (evidence only) adds them: finance roles 200, the 5 other roles 403, nothing written, 3 modes. My PM-01 re-run on `caea933` was stopped because the head moves again.
- **Moving heads:** `ef7cddd` (Q007: company_losses in `/org/pnl-attribution`), then FG-269..271 + the merge of main `1ea98fe`. A full re-audit follows on the final head.
- **#86 `28fb230`** (= `e0fd1e2` + evidence, no code change): gates running.

## 2026-11-08 19:10 UTC: #86 `28fb230` (PRJ-01 rounds 2–3 + merge `e0fd1e2` of main `fddb018` + evidence): PASS, no blocking finding

- **Merge checks:** see the `e0fd1e2` entry (only generated files differ from merge-tree; role-union 0; PM-01 168/168, 0 extra). `28fb230` adds evidence only.

| Gate | Result |
|---|---|
| prj_01 | 9 |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 (with the regenerated matrix) |

- Minor (carried over): `quality_score` has no range check.
- **Next:** #84's final head. #83, #84 and #86 need main `1ea98fe` before their own merge.

## 2026-11-08 19:16 UTC: check-in. main `3699c3b` verified; #84 `2ceb2a9` and #86 `6479cf1` merge checks; gates queued

- **main `3699c3b`** (merge of #87, canon R56–R59): docs only. Tree = `merge-tree(1ea98fe, 1303686)`.
- **#84 `2ceb2a9`** (Q007 `ef7cddd` + FG-269..271 `9630ff0e` + merge of main `1ea98fe`): only `run_meta.json` differs from merge-tree; role-union 0; PM-01 384/384, 0 extra.
- **#86 `6479cf1`** (merge `0fe133db` of main `3699c3b` + `quality_score` 1–5 on POST and PUT): only `run_meta.json` differs from merge-tree; role-union 0; PM-01 168/168, 0 extra. The minor `quality_score` note is addressed (probes follow in the gates).
- **#83 `9f86d0b`** (FG-266..268): no merge of main yet; waiting for its next head.
- **Gates:** serial, #84 then #86 (disk at about 1.9 GB free).

## 2026-11-08 19:41 UTC: #84 `e75b558` (final; = `2ceb2a9` + evidence): PASS, no blocking finding

- **`e75b558` vs `2ceb2a9`:** README, `gates.txt`, `warehouse_suite.txt` and PM-01 `run_meta.json` only. No code change and the matrix is unchanged, so the gates on `2ceb2a9` apply.
- **Merge `2ceb2a9` of main `1ea98fe`:** see the 19:16 entry (only `run_meta` differs from merge-tree; role-union 0; PM-01 384/384). Main `3699c3b` adds only docs to `1ea98fe`.
- **New code since `081f35b`:**
  - FG-246..251, FG-233, FG-264 (one supplier + number under one lock; index at startup);
  - Р58/FG-265 (the accepted difference on a warehouse line is a company cost; FIFO untouched; read-only reader, finance roles only);
  - Q007 (company_losses line in `/org/pnl-attribution`; answers my Р58 observation);
  - FG-269..271.

| Gate (run on `2ceb2a9`) | Result |
|---|---|
| probe invcn01 | 99 |
| inv_cn_01 | 135 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

Carried non-blocking notes: the FG-233 receipt linked only by `invoice_id` (debt) and INV84-02 (other project cost readers) — re-check whether FG-246..271 changed them is left to Codex.

## 2026-11-08 20:01 UTC: #86 `6479cf1` (merge `0fe133db` of main `3699c3b` + `quality_score` 1–5): PASS, no blocking finding

- **Merge checks:** see the 19:16 entry (only `run_meta` differs from merge-tree; role-union 0; PM-01 168/168).
- **`quality_score`:** 1–5 is enforced on POST and PUT (0, 6, 99, -3, 2.5, "x", "4", true → 422); my minor note is resolved.

| Gate | Result |
|---|---|
| prj_01 | 9 |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

**#76 `aa369d8`** (SUB-ADV-01 + merge `8780cfb` of main `1ea98fe` + direct-call fix): merge checks done ahead of its run.
- **Byte check:** only the conflict files (`catalog`, `revenue_expense`, `subcontractors`, PM-01 test, frontend idempotency, generated files) differ from merge-tree.
- **Role-union:** 0 differences.
- **PM-01:** 503 own cells all keep the PR's value (main already had most via #69/#71; merge delta 48); 0 extra.
- **`aa369d8` fix:** the Request param defaults to None on 5 finance-only reads, and `advance_visible` returns False with no request in enforce (fail closed; off/shadow by role). The money decorators already strip with no request.
- **SEC-02 flake:** `row["leaks_7777"] = "7777" in resp.text` (main's `test_sec_02_finance_read.py` L496) is a raw substring match, so an id or timestamp containing "7777" gives a false positive. It never hides a leak. Debt: match `\b7777(\.0)?\b` or check parsed values.

## 2026-11-08 20:27 UTC: periodic pass. New heads #81 `a7166d4`, #83 `464ce36`, #84 `6730fc2`, #86 `dbb04ba` (all include main `3699c3b`)

- **Process failure:** the waiters for #76 / #86 (`while pgrep -f b86c.sh`) matched their own command line and never fired; #76's run started only at 20:26 (about 30 minutes lost). The chain now waits on the PID.
- **Merge checks:**

| PR | Merge | Merge vs merge-tree | Role-union | PM-01 own / extra |
|---|---|---|---|---|
| #81 `a7166d4` | `fdfad135` (`066c991` + `3699c3b`) | only generated evidence | 0 | 48/48, 0 |
| #83 `464ce36` | `3143ade5` (`5ee1f23` + `3699c3b`) | identical | 0 | 864/864, 0 |
| #84 `6730fc2` | `6730fc2b` (`569407c` + `3699c3b`) | identical | 0 | 384/384, 0 |
| #86 `dbb04ba` | `0fe133db` (`28fb230` + `3699c3b`) | only `run_meta` | 0 | 168/168, 0 |

- **#81 `a7166d4`:** its own test changes add the request / fixtures for SEC-02 only; 0 assertion lines changed. F-81-03: a payment to a supplier is never project income.
- **#86 `dbb04ba`:** D14 closed. History is re-checked inside the transaction, and an empty Draft is tombstoned, never `delete_one`.
- **Gates queue (serial):** #76 `aa369d8` (running) → #81 → #84 → #86 → #83.

## 2026-11-08 20:49 UTC: #88 `a05167a` (PWA-01, frontend only; base main `3699c3b`): code review done, jest / build / Playwright re-run PENDING (disk)

- **Backend diff:** empty.
- **Service worker** (`frontend/src/service-worker.js`):
  - precaches only the InjectManifest build list + public icons/manifest + `index.html`;
  - `fetch` returns early (no `respondWith`) for non-GET, other origins and `/api`, `/uploads`, `/ws` (`isNeverCachedPath`);
  - navigations are network-first with a fallback to the cached `index.html`, and navigation responses are never stored;
  - no runtime caching of anything else;
  - old `bw-shell-*` caches are dropped on activate.
- **Registration:** only when `NODE_ENV === "production"`.
- **Update:** no `skipWaiting` on install; it waits for `SKIP_WAITING` from the "Обнови" bar, so there is no silent reload.
- **Logout / 401 / tenant change:** `clearTenantLocalData` deletes every non-shell cache, clears sessionStorage, and empties localStorage except an allow-list of device prefs + the separate platform-admin session; an event resets the in-memory active project. A tenant change is detected at login and `fetchUser` (`noteActiveTenant`). The frontend has no other tenant-switch path.
- **Secrets / CSP:** no new secrets or env values beyond `REACT_APP_BUILD_SHA`. `index.html` has no CSP before or after (not weakened; there is none). The pre-existing `assets.emergent.sh` script is unchanged.
- **D1 (offline reload drops the session):** PRE-EXISTING on main `3699c3b` (`AuthContext.fetchUser` `catch {}` removes `bw_token`/`bw_user` on any error, incl. network).
  - Minimal fix: `catch (err)` and clear only on `err.response?.status === 401` (and 403 from `/auth/me`). On a network error or 5xx keep the token and, to stay usable offline, restore `user` from the cached `bw_user`. The API 401 interceptor still ends a really expired session.
- **Minor:** `logout()` does not await `clearTenantLocalData()`; cache deletion continues in the background, and an immediate unload could leave non-shell caches (normally none exist).
- **Pending:** the jest / `yarn build` / Playwright re-run needs a frontend `node_modules` (~1 GB); about 1.2 GB is free while the Mongo gates run.

## 2026-11-08 20:56 UTC: #76 `aa369d8` (SUB-ADV-01 + merge `8780cfb` of main `1ea98fe` + direct-call fix): PASS, no blocking finding

- **Merge checks / fix:** see the 20:0x entry (only the conflict files differ; role-union 0; PM-01 503/503, 0 extra; fail-closed `advance_visible` with no request).

| Gate | Result |
|---|---|
| sub_adv | 9 |
| probe subadv (FG114, F76) | FAILS none |
| SEC-02 ×3 | 31 / 31 / 31 (the 7777 flake did not occur) |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

- **Next (chain6, serial):** #81 `72e7e87` → #84 `cdd3dc8` → #86 `dbb04ba` → #83 `1e455e3`. All four are evidence-only on top of the merge-checked heads.

## 2026-11-08 21:08 UTC: #88 `7c284fa` (code `e571b06`): D1 fix reviewed

- **`sessionRejected(err)`:** true only for 401, or 403 on `/auth/me` (`err.config.url` ends with `/auth/me`). Otherwise (network error, 5xx) the token stays and `user` is restored from the cached `bw_user`; org stays unknown, and nothing from `/api` is cached.
- **`logout()`:** async, and awaits `clearTenantLocalData()` (my minor note is resolved).
- **The axios 401 interceptor** still clears and redirects on a real 401.
- **Assessment:** correct and minimal.
- **Pending:** the jest (24/221) / build / Playwright (35/35) re-run, after the Mongo queue.
- **#86:** `dbb04ba` skipped in the queue (FG-279/280 coming).

## 2026-11-08 21:19 UTC: #81 `72e7e87` (F-81-03 + merge `fdfad13` of main `3699c3b` + evidence): PASS, no blocking finding

- **Merge checks:** see the 20:27 entry (only generated evidence differs from merge-tree; role-union 0; PM-01 48/48, 0 extra). Its own test changes add the request / fixtures for SEC-02 only (0 assertion lines changed). `72e7e87` adds evidence only.
- **F-81-03:** a payment to a supplier is never project income.

| Gate | Result |
|---|---|
| probe X5–X7 | 18 |
| probe X1–X4 | 12 + X4 (the probe's known `request=None` limitation) |
| probe X8 | 12 |
| SEC-01 | 30 |
| wh_fix_01 | 311 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

## 2026-11-08 21:45 UTC: #84 `cdd3dc8` (FG-276..278 cost journal + FG-271 UI + merge `6730fc2` of main `3699c3b` + evidence): PASS, no blocking finding

- **Merge checks:** see the 20:27 entry (merge identical to merge-tree; role-union 0; PM-01 384/384, 0 extra). `cdd3dc8` adds evidence only on top of `6730fc2`.

| Gate | Result |
|---|---|
| probe invcn01 | 99 |
| inv_cn_01 | 138 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

- **Disk:** at 597 MB free during this run. I freed ~0.5 GB (worktrees, idle test DBs, pip/uv caches). `docker volume prune` and truncating the audit mongod json logs (~5.3 GB) were refused by the permission check; Krum is asked to approve either directly.

## 2026-11-08 21:46 UTC: check-in. main `ea57121` (merge of #76) verified; #79 `f526182` merge checks; queue

- **main `ea57121`:** parents `3699c3b` + `aa369d8` (the audited head, PASS). Tree = `merge-tree(3699c3b, aa369d8)`.
- **#79 `f526182`** (merge `552ffdce` of main `ea57121` + PM-01 harness):
  - conflicts only in the generated A1/A2B inventories and `run_meta`;
  - the one extra merge diff is a test-harness binding of the `money_write` / `finance_read` modules to the scratch db for #71's guard (no assertion change);
  - role-union 0; PM-01 24/24, 0 extra.
  - Gates queued after #83.
- **#86 `03b86cd`** (round 6: FG-279/280; not yet merged with `ea57121`): waiting for its final head.

## 2026-11-08 22:09 UTC: #83 `1e455e3` (R59 + FG-266..268 + FG-275/267 + merge `3143ade` of main `3699c3b` + evidence): PASS, no blocking finding

- **Merge checks:** see the 20:27 entry (merge identical to merge-tree; role-union 0; PM-01 864/864, 0 extra). `1e455e3` adds evidence only on top of `464ce36`.

| Gate | Result |
|---|---|
| probe K1–K3 | 84 |
| cp_01 | 602 (+3 mongomock-only skips) |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | 9 failed, all also on main (NEW_FAILS 0) |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |
| **warehouse** | **1121 (44 files, 0 bad)** |

- **Note:** `1e455e3` is merged with main `3699c3b`, not yet `ea57121` (#76). It needs that merge and a re-audit before its own merge.

## 2026-11-08 22:26 UTC: periodic pass. #73 `e802e6f` and #75 `adc01d4` merge checks (gates not run: disk)

- **#73 `e802e6f`** (merge `c7d48ed0` of main `ea57121` + LAB-01 adaptation + PM-01 regenerated):
  - Resolutions: `labor_smr.py` keeps main's SEC-01-C02 no-delete re-sync (reversal rows, no `delete_many`) and adds LAB-01's pricing basis (cost_type, pay_type, approved_quantity, piece_rate) to the row fingerprint; `all_reports.py` takes the import union.
  - Role-union: 0.
  - PM-01: 6/6, 0 extra.
- **#75 `adc01d4`** (merge of LAB-01 `a040953` into LAB-02):
  - Role-union: 0.
  - The committed **PM-01 matrix is NOT regenerated**: 2708 cells differ from the merged base `a040953` (stale pre-main values, e.g. `PATCH /api/projects/{id}/client-link` driver/enforce 200 + write where main has 403 audit_only; `overhead/realtime/trend` technician 200 where main has 403; warehouse canonical rows missing). The catalog is intact (role-union 0), so this looks like stale evidence, not lost guards — but PM-01 will fail until the matrix is regenerated by the harness.
- **Disk:** ~0.9 GB free; the gates for #73/#75 (and #86, #88) wait for the cleanup approval.

## 2026-11-08 22:36 UTC: #79 `f526182` (OFF-01 + merge `552ffdce` of main `ea57121` + PM-01 harness): PASS, no blocking finding

- **Merge checks:** see the 21:46 entry (only generated inventories/run_meta + a test-harness binding for #71's guard; role-union 0; PM-01 24/24, 0 extra).

| Gate | Result |
|---|---|
| off01 | 237 |
| probe off01 | 675 |
| SEC-01 | 30 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

## 2026-11-08 22:46 UTC: #86 `8e8be48` run STOPPED (disk). Audit paused

- **Partial results:** prj_01 9, SEC-01 30. The warehouse suite was stopped at `c26l_l`: free disk fell from 889 to 454 MB at ~1 MB/s (the audit mongod json logs grow; auditmongo2's log is 3.4 GB), and a full disk would crash Mongo and void the run.
- **After the stop and dropping the test DBs:** ~0.7 GB free.
- **Blocked until Krum approves a cleanup directly in this session (or by a Bash permission rule):**
  - #86 `8e8be48` gates;
  - #73 `e802e6f` gates;
  - #75 (needs a regenerated PM-01 matrix first);
  - #88 frontend checks.
- **The two cleanups the permission check refused:**
  1. `docker volume prune -f` (~20 GB of dangling audit volumes);
  2. `truncate -s 0` of the audit containers' json logs (~5.7 GB of log text).

## 2026-11-08 23:02 UTC: check-in. #73 `7ee87f8` / #75 `5809367` (evidence-only heads)

- **#73 `7ee87f8`** = `e802e6f` + PM-01 `run_meta` stamp (matrix unchanged). The merge checks from the 22:27 entry apply.
- **#75 `5809367`:** the PM-01 matrix is regenerated by the harness on the merge.
  - PM-01 delta vs the merged base LAB-01 `a040953`: 150 cells. All 144 of LAB-02's own cells keep the PR's value (0 differ).
  - The 6 remaining cells are `POST /api/pay-runs` Owner/Admin × 3 modes: 428 (key required) instead of LAB-01's 400. LAB-02's own base already had 428, so this is LAB-02's R29 key rule kept by the merge. Stricter, not weaker.
  - Role-union 0 (22:27 entry). The stale-matrix note is RESOLVED.
- **Gates for #73 / #75 / #86 `8e8be48` / #88:** still blocked by the disk (~0.9 GB free; a warehouse suite needs more), pending Krum's cleanup approval.

## 2026-11-09 00:26 UTC: periodic pass. #73 `fdcb5ac`, #79 `25c9ae8` (no code changes)

- **#79 `25c9ae8`** = `f526182` (PASS 22:59) + OFF-01 merge evidence only. The verdict stands.
- **#73 `fdcb5ac`** = `7ee87f8` + test-harness bindings in 3 warehouse canonical tests (c20, c21, c22): the `app.services.labor_cost` / `report_normalizer` modules are bound to the test db, as LAB-01 now reads through them. Fixture only, 0 assertion lines changed. Plus evidence.
- **Gates for #73 / #75 / #86 `8e8be48` / #88:** still blocked by the disk (~0.9 GB free).

## 2026-11-09 02:22 UTC: #73 `5e3a152` / #75 `48ba662` final heads: merge checks OK; gates blocked by disk

- **#73 `5e3a152`** = `fdcb5ac` + warehouse-suite evidence only (no code change, PM-01 matrix unchanged). The earlier merge checks apply.
- **#75 `48ba662`:** merge `fc538d5d` of LAB-01 `5e3a152` into LAB-02 `5809367`.
  - Only `run_meta.json` differs from merge-tree.
  - Its code change is LAB-01's c20/c21/c22 fixture bindings (0 assertions changed).
  - Role-union 0; PM-01 matrix unchanged vs `5809367`.
- **FLOW Guard FG-340 (high) is open on #73:** one project shows three different labor costs. It waits for Krum's decision, so #73/#75 merges wait. Not re-judged here.
- **Gates:** #86 `8e8be48` → #73 → #75 → #88. Still blocked (~0.9 GB free; cleanup approval pending).

## 2026-11-09 06:14 UTC: main `44e8d97` (merge of #79) verified; #84 `5242cba` merge checks (gates blocked by disk)

- **main `44e8d97`:** parents `ea57121` + `25c9ae8` (= `f526182` + evidence; PASS). Tree = merge-tree.
- **#84 `5242cba`** (FG-278 one project-status scope for company-result readers; R63/FG-281 re-booking after a reversal; merge `5e7ab4a2` of main `44e8d97`):
  - Only the generated A1 inventory and `run_meta` differ from merge-tree.
  - Role-union 0.
  - PM-01: 432/432 own cells, all keep the PR's value. The 48 "extra" cells are the PR's own new R63 routes `POST /finance/credit-notes/{id}/difference-proposals/{pid}/approve|reject`:
    - approve: Owner only (Owner 428 = key required; all others 403);
    - reject: Owner / Admin / Accountant 428, the rest 403;
    - nothing written, 3 modes.
- **Queue (after disk cleanup):** #86 `8e8be48` → #84 `5242cba` → #73/#75 → #88. Still ~0.9 GB free.

## 2026-11-09 06:26 UTC: periodic pass. #73 `8a02819`, #81 `61cef41`, #83 `a35417f`, NEW #89 `1b13d11` (all on main `44e8d97`); gates blocked by disk

| PR | Merge | vs merge-tree | Role-union | PM-01 |
|---|---|---|---|---|
| #73 `8a02819` | `c3d5f8d8` (`5e3a152` + `44e8d97`) | **matrix.csv edited (6 rows)** + `run_meta` | 0 | **6 own cells differ** |
| #81 `61cef41` | `f31fe92d` (`72e7e87` + `44e8d97`) | generated A1/SEC-02/`run_meta` | 0 | 48/48, 0 extra |
| #83 `a35417f` | `2f64d708` (`dbadbf1` + `44e8d97`) | `subcontractors.py` import union (+ `Request`; `typing` kept) + generated files | 0 | 864/864, 0 extra |

- **LAB73-M1 (blocking until fixed, evidence):** the merge hand-resolved `docs/evidence/PM-01/matrix.csv` and set `POST /api/pay-runs` Owner/Admin × 3 modes to main's **400**. LAB-01's code at the head still answers **428** (no Idempotency-Key, R29), and the committed matrix at `5e3a152` said 428. The committed evidence no longer matches the code, so PM-01 will fail. Fix: regenerate the matrix with the harness on the merge, never by hand.
- **#73 R62** (`8a02819`: one labor cost per project in every reader; FG-340/FG-58/FG-390): 21 files, +2762/-340. Needs a full code review + gates; not done yet.
- **#81** F-81-03 extended to SUB-ADV-01 advances. **#83** FG-290 (receipt must be a tenant file), FG-294 (invoice ЕГН masked + audited).
- **NEW #89 `1b13d11`** (OFF-02, FG-350: offer write responses strip money for non-finance like the offer read): not reviewed yet.
- **Gates for all of the above + #86 `8e8be48`, #84 `5242cba`, #75 `48ba662`, #88:** blocked by the disk (~0.9 GB free).

## 2026-11-09 07:04 UTC: #81 `3028304` (= `61cef41` + evidence; merge `f31fe92d` of main `44e8d97`): PASS, no blocking finding

- **Merge checks:** see the 06:27 entry (generated files only; role-union 0; PM-01 48/48, 0 extra). F-81-03 now also covers SUB-ADV-01 advances.
- **Disk handling:** the audit mongods are set to quiet logging (connection logs off, slowms 600000). A watchdog stopped the first run at 242 MB: rs0 had been recreated by the 06:34 restart, and its fresh journal plus drop-pending files grew. The warehouse suite was finished on rs3 (steady size; dropping DBs + `fsync` frees space). Each warehouse file runs on its own clean DB, so 28 files on rs0 + 16 on rs3 = the whole suite.

| Gate | Result |
|---|---|
| probe X5–X7 | 18 |
| probe X1–X4 | 12 + X4 (the probe's known `request=None` limitation) |
| probe X8 | 12 |
| SEC-01 | 30 |
| wh_fix_01 | 317 |
| **warehouse** | **1121 (44 files, 0 bad)** |
| PAY | 630 |
| W0 | same 15 |
| A2C / A1 | 0 / 0 |
| R0 | 814 |
| PM-01 | 6 |

- **#83:** final head `4929451` = `a35417f` + regenerated evidence (no code change).

## 2026-11-09 07:14 UTC: #86 `8e8be48` run stopped again (disk); audit PAUSED

- **Partial #86 `8e8be48` results:** prj_01 9, SEC-01 30. Warehouse files 1–23 of 44 all passed (650 cases; c26l_* etc. not reached). The watchdog stopped the run at 119 MB free.
- **Measurement:** even with quiet logging, a warehouse suite grows a replica set's `/data/db` by ~400–450 MB (journal + drop-pending idents; rs3 → 942 MB). That space is only slowly returned after `dropDatabase` + `fsync` (rs3 857 MB a few minutes later). With ~0.3–0.6 GB free, one whole warehouse suite does not fit reliably.
- **Status:**
  - **PASS:** #81 `3028304`.
  - **Blocked:** #86 `8e8be48`, #84 `5242cba`, #83 `4929451`, #89 `1b13d11`, #73/#75 (also LAB73-M1), #88 frontend.
- **To continue:** Krum must approve `docker volume prune -f` (~20 GB) or truncating the audit containers' json logs (~5.7 GB), directly in this session or by a Bash permission rule.

## 2026-11-09 07:24 UTC: relayed cleanup approval not acted on; handoff to a fresh audit session recommended

- **The relay:** the orchestrator relayed Krum's answer from its own session ("Изчисти ги ти, ти знаеш какво не трябва") approving `docker volume prune -f`.
- **Why I did not act on it:** a cross-session message is not an instruction from the user in this session, and the permission check had already refused this exact deletion twice. So I did not retry it.
- **Recommendation:** a fresh audit session on an empty disk. The handoff state was sent to the orchestrator: queue, partial results, LAB73-M1, probes, and lessons (replica-set disk headroom, quiet mongod, drop + `fsync`, PID-based waiters).
- **Krum's decision noted for LAB-01 (#73):** the Owner may not approve a manual labor row they entered; a second person must.

## 2026-11-09 07:25 UTC: handover to AUDIT-2 (session_01UghxKZb6nGrVuwnvXzQ5P3)

- At the orchestrator's request, this session stops running Mongo gates. AUDIT-2 runs the queue on a fresh disk from the 07:24 handoff and the entries above.
- No batch or Mongo test is running here. This log is pushed (`claude/audit-log`).
## 2026-11-09 07:30 UTC: AUDIT-2 takes over (fresh session, empty disk)

- **Handover:** from session `session_01UghxKZiQ4VfsNzfoAGs1Ek` (disk full). Method, probes and gates unchanged.
- **Environment:** three local `mongo:7.0` single-node replica sets (`rs0`), each on its own docker volume created by this session, `--quiet --slowms 600000 --logpath /tmp/mongod.log` (no json log driver). Every gate drops its test DBs and `fsync`s; each warehouse file runs on a clean DB; a watchdog stops a run below 500 MB free. ~26 GB free.
- **Role-union tool:** `catalog.PERMISSION_MATRIX` of the merge vs the union of both parents (per role, removed and added actions); constants that differ from both parents are listed.

## 2026-11-09 07:33 UTC: main `1525a1e` (merge of #81) verified

- Parents `44e8d97` + `3028304` (the audited head, PASS). Tree `d2011a67` = `merge-tree(44e8d97, 3028304)`, byte-identical.
- Role-union 0.
- **Baseline on real Mongo:** W0 = 16 failed / 1176 passed (the 15 `test_w0_03e_legacy_routes` + the order-dependent `test_w0_03e_real_mongo::test_r1_…`); A2C 0/242; A1 0/488.

## 2026-11-09 07:50 UTC: #88 PWA-01 `7c284fa` (code `e571b06`): PASS, no blocking finding

- **Backend diff:** empty. Code review: see the 20:49 / 21:08 entries (D1 fix correct and minimal).
- **On the head:** `yarn install --frozen-lockfile`; jest **24 suites / 221**; `yarn build` OK (CRA warnings only); Playwright with the pre-installed Chromium, prod build served by `e2e/server.js`: **35 / 35**.
- **Cache Storage (my run's `cache-check.json`):** only `bw-shell-7c284fab3d89-*`; **0** `/api`, `/uploads`, `/ws` entries; offline `fetch('/api/payments')` = network error; logout and tenant switch leave only the shell cache.
- **Onto main `1525a1e`:** merges cleanly. On the trial merge (backend byte-identical to main): jest **25 / 224** (main's extra suite), build OK, Playwright **35 / 35**.
- **Mongo gates:** not applicable (no backend change; merged backend = main).

## 2026-11-09 08:00 UTC: #86 PRJ-01 `8e8be48` (base main `3699c3b`): PASS on the head, no blocking finding in code

- **Merge check:** last merge `0fe133d` (`28fb230` + main `3699c3b`) = merge-tree except PM-01 `run_meta`. Role-union 0. PM-01 `--harness` regenerated on the head = committed matrix (18528 rows, 0 cells differ).

| Gate | Result |
|---|---|
| prj_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6 passed / 0 skipped |
| PAY | 630 |
| R0 | 814 |
| W0 | 16 failed = main's 16 (0 new) |
| A2C / A1 | 0/240, 0/484 |
| **warehouse** | **44 files / 1121, 0 bad** |

- **Onto main `1525a1e`:** not clean. Conflicts only in generated files (A2B inventory, PM-01 `run_meta`, SEC-02 `results.json`); code auto-merges (`routes/finance.py`, `routes/projects.py`, `tenancy/ownership.py`, `ProjectDetailPage.js`); role-union of the trial merge 0.
- **Env note:** the first warehouse pass had 30 files with `ImportError: pytest_asyncio`. That package is missing from `requirements*.txt`, but `pyproject.toml` (`asyncio_mode = "auto"`) and `warehouse_canonical_conftest.py` need it. Installed; the whole suite was re-run.
- **Superseded by `2d6421a`** (merge of main `1525a1e`): see the next #86 entry.

## 2026-11-09 08:25 UTC: #83 CP-01 `4ef7dfe` (contains main `1525a1e`): FAIL, 1 blocking (evidence)

- **Merge check:** merge `4f32e96` (`4c77b72` + `1525a1e`) = merge-tree except generated A1 / A2B / `run_meta` and `SEC-01-C01/results.json` (below). `3b57b46` drops CP-01's own `dq_issues` registration and keeps #81's (FAMILY_TASKS): correct, one registration. Role-union 0. PM-01 `--harness` = committed (19176 rows, 0 cells differ).
- **CP83-M1 (blocking, evidence):** SEC-01 **1 failed / 29**.
  - Test: `tests/test_sec_01_c01_all_money_writes.py:599` `test_a_fresh_real_mongo_run_on_two_tenants_follows_the_rules_in_every_mode`. Deterministic (re-run alone).
  - Every `PATCH /api/projects/{id}/client-link` 200 cell (Owner / Admin, tenants A / B, P1 / P2, 3 modes) now writes `op.audit_events` + `op.projects`. The committed `docs/evidence/SEC-01-C01/results.json` says `op.projects` only.
  - Cause: the merge took main's file (last written by #81 `72e7e87`) instead of the auto-merged content. Both merge-tree(`4c77b72`, `1525a1e`) and CP-01's own `4c77b72` have `op.audit_events` on those rows: CP-01 audits the client-link write.
  - README §17 says SEC-01-C01 was "regenerated by their tools"; it was not. §17 also cites `gates_r65.txt`, which is not in the tree.
  - Fix: regenerate SEC-01-C01 with its harness on the merge, and commit the gates file.

| Gate | Result |
|---|---|
| probe K1–K3 | 84 |
| cp_01 | 620 (+3 mongomock-only skips) |
| **SEC-01** | **29 / 1 failed (CP83-M1)** |
| SEC-02 | 31 |
| PM-01 | 6 passed / 0 skipped |
| PAY | 630 |
| R0 | 814 |
| W0 | 10 failed, all within main's 16 (0 new) |
| A2C / A1 | 0/247, 0/498 |
| **warehouse** | **44 files / 1121, 0 bad** |

## 2026-11-09 08:30 UTC: #89 OFF-02 `1b13d11`: code review; OFF89-N1 (closed by R67 in `0d8984d`)

- **FG-350 review:**
  - The decorators keep the signature (`functools.wraps`) and fail closed without a request.
  - No handler is called directly by other code.
  - None of the decorated routes returns a `Response` object.
  - `strip_money` covers the offer keys (`material_unit_cost`, `labor_unit_cost`, `line_total`, `subtotal`, `vat_amount`, `total`, and import `material_price` / `labor_price`).
- **OFF89-N1 (PROVED, probe `off02/test_probe_off02.py`, real Mongo, 3 modes):**
  - Steps: a SiteManager GETs his draft (the lines come stripped), then PUTs those lines back with only a qty change.
  - Result: 200, and `material_unit_cost` / `labor_unit_cost` / `total` became **0** (8 / 12 / 240 → 0 / 0 / 0).
  - Pre-existing (`update_offer_lines` is unchanged by #89). The UI blocks it (`OfferEditorPage` `canManage` = Admin / Owner), but the API did not.
  - Krum's **R67** answers it: only Owner / Admin / Accountant write offers. Implemented in `6ccb873` (head `0d8984d`); gates follow.
- **Gates on `1b13d11`** (superseded, partial): off_02 12, SEC-01 30, SEC-02 31, PM-01 6, PAY 630, R0 814, W0 = main's 16, A2C / A1 0 / 0; the off01 probe's 9 O20 failures were my venv missing `pypdf` (installed).

## 2026-11-09 09:05 UTC: #84 INV-CN-01 `8d2a48e` (merge `8e2a1f4` of main `1525a1e` + R64 / FG-416): FAIL, 2 blocking (both fixed in later heads)

- **Merge `8e2a1f4`:** real code conflicts, resolved correctly.
  - `routes/finance.py`: create / update keep INV-CN-01's FG-264 (supplier, number) lock and #81's Р45 stamping + DQ in **one** transaction (`_insert_supplier_invoice(..., after_insert=...)`).
  - `invoice_line_lock.py`, `warehouse_movements/service.py`, `ownership.py`: union of both sides; `dq_issues` registered once.
  - Role-union 0.
- **INV84-R64-1 (blocking, PROVED, probe `invcn01/test_probe_invcn01_r64.py`, real Mongo, 3 modes):**
  - Scenario: an accepted difference whose project is then Archived, reversed, and re-booked "back to the line's own allocation".
  - The legacy single-allocation shape (`allocation_type` / `allocation_ref_id`) and `allocations[].refId` were **booked at once without the Owner**: 6 / 6. Only `allocations[].ref_id` gave the `closed_project` proposal (3 / 3).
  - Cause: `services/invoice_corrections.rebooking_projects` read only `allocations[].ref_id`; the cost reader `effective_allocations` reads all three shapes.
  - **Fixed in `f6e0c90`:** probe 9 / 9.
- **INV84-M1 (blocking, evidence):** SEC-02 failed.
  - The harness regen differs in 36 cells: `GET /api/project-material-summary/{id}` for Owner / Admin / Accountant has the new money key `supplier_note_cost`, which the committed file (main's) lacks.
  - Non-finance roles do not get the key: no leak.
  - **Fixed in `6871bc0`** (SEC-02 regenerated by its harness).
- **Other gates on `8d2a48e`:**

| Gate | Result |
|---|---|
| probe invcn01 | 99 |
| inv_cn_01 | 144 |
| fg233 race | 9 (needs `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`, else 9 skips) |
| SEC-01 | 30 |
| PM-01 | 6; regen = committed |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0 / 0 |
| **warehouse** | **44 / 1121** |

## 2026-11-09 09:20 UTC: #86 PRJ-01 `49eb546` (merge `2d6421a` of main `1525a1e` + regenerated evidence): PASS, no blocking finding

- **Merge `2d6421a`:** = merge-tree except generated files, plus dropping PRJ-01's duplicate `dq_issues` registration (it keeps #81's, correct). Role-union 0.
  - On `2d6421a` itself, SEC-02 was stale: 54 finance-only cells lacked main's `paid_issued` / `paid_received` (dashboard) and `advance` (subcontractor packages).
  - `49eb546` regenerates it; harness regen = committed (0 cells).
- **`49eb546` vs `2d6421a`:** docs / evidence only.
- **SEC-02:** failed once on the known `leaks_7777` raw-substring flake; then 2 / 2 passed. Every `leaks_7777 = True` row in my regen is Owner / Admin / Accountant.

| Gate | Result |
|---|---|
| prj_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 (see the flake above) |
| PM-01 | 6; regen = committed |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/243, 0/490 |
| **warehouse** | **44 / 1121** |

## 2026-11-09 09:20 UTC: #83 CP-01 `7750f4e`: PASS, no blocking finding

- **CP83-M1 fixed:** SEC-01 30 / 30. SEC-01-C01 is regenerated (the client-link rows carry `op.audit_events`), and `gates_r65.txt` is present.
- **`7750f4e` vs `4ef7dfe`:** tests + evidence only, 0 bytes in `backend/app`.
- **Re-run on this head:** SEC-01 30, PAY 630, wh_fix_01 a3_r44 138 + f81_readers 132. The rest from `4ef7dfe` stands.

## 2026-11-09 09:30 UTC: #89 OFF-02 `56913a4` (merge `01e8e8c` of main `1525a1e` + R67): PASS, no blocking finding

- **Merge `01e8e8c`:** = merge-tree except SEC-02 (generated, regenerated). Role-union 0.
- **R67 (`6ccb873`):** 18 `offers.*` write actions (`OFFER_WRITE_ACTIONS`) for Owner / Admin / Accountant. `require_money_write` is the first dependency on every offer mutation, including the missing-smr / smr-analysis to-offer routes, which had no role check before.
- **OFF89-N1 closed:** a SiteManager `POST /api/offers` → 403 in all 3 modes (probe off02 stops at its precondition).

| Gate | Result |
|---|---|
| off_02 | 22 |
| off_01 | 90 |
| off_01 audit probe | 147 |
| probe off01 | 675 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6 (on `56913a4`); regen = committed |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/242, 0/488 |
| **warehouse** | **44 / 1121** |

## 2026-11-09 09:30 UTC: #82 WH-REV-01 `e07320d` (merge `9ebdc37` of main `1525a1e`): WHREV82-M1 (blocking, PROVED); gates running

- **WHREV82-M1:** the #81 / #82 merge condition from the 2026-11-08 audits is **not met**.
  - `routes/procurement.py:535` `_supplier_invoice_link` still counts a reversed receipt (its docstring still calls this debt for "whichever PR merges second", and #82 is second).
  - Probe `whrev01/test_probe_whrev01_silock.py` (real Mongo, 3 / 3 modes): a reviewed procurement supplier invoice whose line is named by a receipt → PUT lines 409 `SUPPLIER_INVOICE_LINKED` (correct). After the receipt reversal (201), PUT lines is **still 409**, so the invoice stays locked forever.
- **Merge resolution otherwise reviewed:**
  - the reversal takes / bumps #81's supplier-invoice lock by line;
  - Р47's DQ issue moves into #81's `dq_issues` (`sync_credit_note_issue`);
  - `reason` → `correction_reason` (no frontend user).

## 2026-11-09 10:15 UTC: #84 INV-CN-01 `6871bc0`: PASS, no blocking finding

- **INV84-R64-1 fixed (`f6e0c90`):** `rebooking_projects` reads `effective_allocations` and fails closed. Probe R64 9 / 9.
- **INV84-M1 fixed (`ec5e085`):** SEC-02 regenerated; my harness regen = committed (0 cells).
- **`6871bc0`:** three #81 tests take a real-Mongo-only fixture; 0 assertion lines changed.
- **`052e845` review:** a locked supplier invoice may change only its lines' destination. The stored line is kept as is except `project_id`, and money equality is re-checked inside the claim transaction. Correct.
- **INV84-N2 (non-blocking, SUSPICION):** `ensure_indexes` now swallows a failed build of every planned index (credit notes, offsets, counters), with only a log warning. Suggest a DQ / health flag.

| Gate | Result |
|---|---|
| probe R64 | 9 |
| probe invcn01 | 99 |
| inv_cn_01 | 159 |
| fg233 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/245, 0/494 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | a3_r44 129, post_55 47, f81 132 |

- Contains main `1525a1e`.

## 2026-11-09 10:35 UTC: #82 WH-REV-01 `108afc0`: PASS, no blocking finding

- **WHREV82-M1 fixed:** `_supplier_invoice_link` drops reversed receipts and reversal rows (`without_reversed`) in the lock transaction. Probe silock 3 / 3.
- **Gates:** the full suite on `e07320d`, plus everything `108afc0` touches (`procurement.py` only).

| Gate | Result |
|---|---|
| probe whrev01 | 144 |
| probe silock | 3 |
| wh_rev_01 | 104 |
| wh_fix_01 | post_55 47, a3_r44 138, f81 132 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/243, 0/490 |
| **warehouse** | **44 / 1121** (`e07320d`) |

- Contains main `1525a1e`.

## 2026-11-09 10:50 UTC: #73 LAB-01-T `b766f34` (R62 FG-460..463, R66, R73): FAIL, 2 blocking (warehouse still running)

- **LAB73-M2 (blocking, gate):** SEC-01 **4 failed / 26**.
  - Failing: the "fresh real Mongo" tests of `money_write_permissions`, `c01`, `c02` and `c03`.
  - `POST /api/labor-entries` → 422 (expected 201; C03's no-key probe expected 428). FG-461 (`ad557c7`) made `execution_package_id` mandatory, and the SEC-01 harness bodies were not adapted. The PR's gate file is from `1efa8cf`.
- **LAB73-R1 (blocking, PROVED, probe `lab01/test_probe_lab01t_fg463_race.py`, real Mongo):** FG-463 is not atomic.
  - **T1:** concurrent Owner / Accountant approvals of two overlapping pending rows → 10 / 10 both approved.
  - **T2:** two concurrent creates for the same worker / project / day → 7 / 10 two live rows.
  - Nothing serialises (tenant, project, worker, day).
- **Green so far:**

| Gate | Result |
|---|---|
| lab_01* | 154 |
| probe lab01e | 4 |
| probe lab01f | 5 |
| probe lab01h | 3 (needs `MONGO_URL`) |
| SEC-02 | 31 |
| PM-01 | 6 |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0 / 0 |

- **Earlier heads:**
  - `b395f0d`: all gates green, warehouse 44 / 1121; PM-01 regen 0 cells.
  - `102e0fd`: SEC-02 54 cells stale (work-session `cost_*` keys, finance roles only); fixed in `fc97a2c`.
- **R62 / R66 / R73 review:**
  - Creator ≠ approver; a row with no creator is approved by the Owner only.
  - Each decision is bound to the row's version and value, takes an Idempotency-Key, does a CAS on the row and writes the AuditEvent, all in one transaction.
  - R73: the creator may reject or reverse only with `labor.entry.create` on the row's project.
- **LAB73-N1 (non-blocking):** a reversal drops the original from every period instead of booking a negative in the reversal's own period. Design question.

## 2026-11-09 11:20 UTC: #73 LAB-01-T `f1c46c6` (LAB73-R1 fix): FAIL (fixed in `8b72647`, under audit)

- **LAB73-R1 fixed:** probe T1 + T2 20 / 20. One lock document per (tenant, project, worker, day), bumped and re-read inside create / approve / report-approve.
- **LAB73-M3 (blocking):** the new `labor_day_locks` is not classified in `tenancy/ownership.py`.
  - The A2B backfill inventory marks a non-empty unclassified collection `BLOCKED_UNCLASSIFIED_COLLECTION` (`legacy_backfill.py:364`), and execute is refused (`:641`).
  - A2C = 2 violations (`labor_cost.py:496` dynamic getattr; `:499` unclassified).
  - W0: 2 new failures (`a2b_static_guard::test_every_collection_the_application_names_is_classified`, `a2c_static_guard::test_the_whole_active_backend_is_clean`).
- **SEC-01: 4 failed.**
  - `written_orgs` has `None`: the unclassified lock collection.
  - C03 static rule: an `insert_one` outside `mw.insert_once()`.
  - C01 evidence stale.
- **SEC-02: 1 failed.** Stale evidence: the PM-01 seed gives P2 an SMR package.
- **My scan of every collection the app names:** no unclassified collection on main, #84, #83 or #89.

## 2026-11-09 11:40 UTC: #84 INV-CN-01 `faaa2d0`: PASS, no blocking finding

- **`faaa2d0`** = `b0e72cf` + evidence.
- **New code:**
  - FG-465: one `dq_issues` schema with #81 / #82.
  - R74: offsets follow the payment rules.
  - INV84-N2: number / note decisions are serialised by lock documents in `org_counters`; a failed index build becomes a DQ issue + alarm. INV84-N2 closed.

| Gate | Result |
|---|---|
| probe R64 | 9 |
| probe invcn01 | 99 |
| inv_cn_01 | 165 |
| fg233 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/245, 0/494 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | 47 / 129 / 132 |

## 2026-11-09 11:40 UTC: #83 CP-01 `a5176b2` (R71): FAIL, 1 blocking

- **CP83-M2 (blocking):** main's own `tests/test_wh_fix_01_f81_readers.py::test_f81_03_subcontractor_advance_is_not_project_income[real-off|shadow|enforce]` → 3 failed / 129.
  - `POST /api/subcontractor-packages/pkg-f81/advances` → 422 `COUNTERPARTY_NOT_FOUND` (expected 201).
  - R71 sends the advance through the payment guards, and #81's fixture has no counterparty. Fix: setup only.
- **Rest green:**

| Gate | Result |
|---|---|
| probe K1–K3 | 84 |
| cp_01 | 647 (+6 skips) |
| sub_adv_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6 |
| PAY | 630 |
| R0 | 814 |
| W0 | within main's 16 |
| A2C / A1 | 0/247, 0/498 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 a3_r44 | 138 |

## 2026-11-09 11:50 UTC: #89 OFF-02 `7cfeae5` (FG-472): PASS, no blocking finding

- **FG-472:** `PUT /offer-budgets` requires the R67 finance write first and writes the rows + one AuditEvent in one transaction. `GET` has an explicit non-finance allow-list view. The router is not mounted in `server.py`.

| Gate | Result |
|---|---|
| off_02 | 28 |
| off_01 | 90 |
| off_01 audit probe | 147 |
| probe off01 | 675 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/242, 0/488 |
| **warehouse** | **44 / 1121** |

## 2026-11-09 12:00 UTC: #73 LAB-01-T `8b72647` / `55d23f6`: FAIL, LAB73-M4 (evidence)

- **Fixed:**
  - LAB73-M3: `labor_day_locks` is classified; A2C 0, A1 0; W0 = main's 16.
  - LAB73-M2 (b): the lock-tx insert goes through `mw.insert_once()`.
- **LAB73-M4 (blocking, evidence / harness):**
  - SEC-01 C01 / C02 `test_the_committed_evidence_satisfies_the_package` fail: `written_orgs ['A','None']`. On `8b72647` the fresh-run tests failed too.
  - The committed `SEC-01-C01` / `-C02` results each have one such row: off / A / owner / P1 / `labor_create`, the first labor create of the run.
  - Cause: the DDL (create collection + unique index of `labor_day_locks`) is logged in the oplog with no org. Reproduced in my own C01 harness run: 1 of 48 rows.
  - `55d23f6` creates the index at startup, so the fresh runs pass, but the committed C01 / C02 evidence was not regenerated: 2 failed / 28.
- **Green (`8b72647`):**

| Gate | Result |
|---|---|
| lab_01* | 189 |
| race probe | 20 |
| SEC-02 | 31 |
| PM-01 | 6 |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0 / 0 |

## 2026-11-09 12:00 UTC: #83 CP-01 `f91b423`: PASS, no blocking finding

- **CP83-M2 fixed:** f81_readers 132 / 132. The setup now registers and verifies the subcontractor; 0 assertion lines changed; 0 bytes in `backend/app` vs `a5176b2`.
- **Re-run on this head:** a3_r44 138, post_55 47, PAY 630, SEC-01 30, sub_adv_01 9, cp_01 647 (+6). The rest from `a5176b2` stands.

## 2026-11-09 12:00 UTC: #88 PWA-01 `131d945` (merge `bdf5e5a` of main `1525a1e` = merge-tree; R68 PostHog; FG-470): PASS, no blocking finding

- **Backend:** byte-identical to main.

| Check | Result |
|---|---|
| jest | 26 / 246 |
| build | OK |
| Playwright | 35 / 35 (Cache Storage: only `bw-shell-*`, 0 `/api` / `/uploads` / `/ws`) |
| analytics-check, no key | 2 / 2 |
| analytics-check, test key + posthog-js 1.200.0 served locally | 15 / 15 |

- **PWA88-N1 (non-blocking, security):** the PostHog CDN loader is injected at runtime with no SRI or pinned version, into the origin that holds `bw_token` in localStorage. Prefer a lockfile-pinned npm build or a CSP.
- **Note:** a short `REACT_APP_BUILD_SHA` gives build identity `unknown` (`build-info.js` needs 40 hex). That was my invocation, not a defect.

## 2026-11-09 12:50 UTC: #83 CP-01 `4c8e922` (FLOW Guard pass 39): FAIL, 3 blocking

- **CP83-M3:** main's `test_sub_adv_01::test_the_routes_check_the_role_before_any_read_and_take_the_key` (`:892`) fails. FG-481 puts the replay read before amount validation.
- **CP83-M4:** PM-01 2 failed. The new `POST /companies/{id}/vat/reveal` and `/counterparties/{id}/vat/reveal` are not in the matrix (not regenerated).
- **CP83-M5:** A2C 1 violation: `money_input.py:198`, a raw `db[audit_idempotency].find_one` with no literal tenant filter. W0 has 1 new failure (`a2c_static_guard`).
- **Green:** probe 84, cp_01 662, SEC-01 30, SEC-02 31.
- **`6709453`:** fixes CP83-M3 (validation → replay → guards; same key + another body → 409). Re-audit running.

## 2026-11-09 12:50 UTC: #73 LAB-01-T `7c24452`: PASS, no blocking finding

- **Closed:** LAB73-M2, M3, M4 and R1.
- **`7c24452`:** `205c7d6` + regenerated SEC-01 / -C01 / -C02 / -C03 / SEC-02.

| Gate | Result |
|---|---|
| lab_01* | 199 |
| race probe | 20 |
| probes lab01e / lab01f / lab01h | 4 / 5 / 3 |
| SEC-01 | 30 |
| SEC-02 | 31; regen 0 cells |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/244, 0/492 |
| **warehouse** | **44 / 1121** |

- **Base:** still main `44e8d97`. Onto `1525a1e` it conflicts only in generated files (A2B, PM-01 `run_meta`, SEC-01-C01 / C02 / C03, SEC-02); role-union 0. It needs a merge of main and regeneration.
- `tests/test_work_sessions.py` is a live-server test, not run here.

## 2026-11-09 12:50 UTC: #88 PWA-01 `62f898a`: PASS, no blocking finding

- **PWA88-N1 closed:** `posthog-js` 1.200.0 is pinned and bundled (the `module.no-external` build, as a lazy chunk); `/decide` and remote config are off.

| Check | Result |
|---|---|
| jest | 26 / 249 |
| build | OK |
| Playwright | 35 / 35 |
| analytics-check, no key | 4 / 4 |
| analytics-check, test key | 18 / 18 |

- **Pre-existing D5:** `assets.emergent.sh` script in `index.html`. Krum's decision.

## 2026-11-09 13:30 UTC: #83 CP-01 `a30a059`: PASS, no blocking finding

- **Closed:**
  - CP83-M3 (`6709453`): validation → replay → guards; same key + another body → 409.
  - CP83-M5 (`b4a775f`): literal `tenant_id` in the replay lookup; A2C 0.
  - CP83-M4 (`a30a059`): PM-01 regenerated. Both `vat/reveal` routes are Owner / Accountant only (others 403, nothing written, 3 modes).

| Gate | Result |
|---|---|
| probe | 84 |
| cp_01 | 666 (+12) |
| sub_adv_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | within main's 16 |
| A2C / A1 | 0/247, 0/498 |
| **warehouse** | **44 / 1121** (run spanned `6709453` → `a30a059`; one-line diff outside the warehouse path) |
| wh_fix_01 | 138 / 132 / 47 |

- Contains main `1525a1e`.

## 2026-11-09 13:35 UTC: #75 LAB-02 `11b55c1` (merge `415cf71` of #73 `4d1f5a3` + FG-464): PASS on base `44e8d97`

- **Merge `415cf71`:** = merge-tree except `ownership.py` (correct union) and `run_meta`. Role-union 0.
- **FG-464:** the answer and the replay come from the history row of the written version.

| Gate | Result |
|---|---|
| lab_0* | 251 |
| probes lab02 / retake / f75_01 / race | 4 / 1 / 51 / 20 |
| SEC-01 | 30 |
| SEC-02 | 31; regen 0 cells |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/245, 0/494 |
| **warehouse** | **44 / 1121** |

- **Next:** it must re-merge #73 `af22870` (which contains main `1525a1e`) and regenerate the generated files.

## 2026-11-09 14:50 UTC: #73 LAB-01 `af22870` → `749ccd6` → `d34d41b`: PASS, no blocking finding

- **`af22870`:** merge of main `1525a1e`. = merge-tree except generated evidence; role-union 0. All gates green, warehouse 44 / 1121.
- **`749ccd6` (pass 40):**
  - FG-502: session writes answer with hours only.
  - FG-500: manual-row dates normalised on read.
  - A manual akord row is refused without a LAB-02 approved quantity. The code after that `raise` in `_manual_row_pricing` is dead (minor).
- **`d34d41b`:** `749ccd6` + regenerated evidence.

| Gate | Result |
|---|---|
| lab_01* | 201 |
| probes lab01h / race / lab01e / lab01f | 3 / 20 / 4 / 5 |
| SEC-01 | 30 |
| SEC-02 | 31; regen 0 cells |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/245, 0/494 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | 138 / 132 / 47 |

- Contains main.

## 2026-11-09 14:50 UTC: #83 CP-01 `83cc386` / `2415b5f` (pass 40): gates green

| Gate | Result |
|---|---|
| probe | 84 |
| cp_01 | 690 (+12) |
| sub_adv_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | within main's 16 |
| A2C / A1 | 0/247, 0/498 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | 138 / 132 / 47 |

- **`2415b5f`:** evidence only; SEC-01 / PM-01 re-check running.

## 2026-11-09 15:45 UTC: #75 LAB-02 `4fa4957` (merge `fe743f4` of #73 `d34d41b` + R62 / R33 akord): PASS, no blocking finding

- **Merge `fe743f4`:** = merge-tree except generated evidence. Role-union 0. No unclassified collection. Contains main `1525a1e`.
- **R62 / R33:** a manual akord row is priced only from a LAB-02 approved quantity of the same worker / package / project / day.
  - Second quantity → 422.
  - One approval backs one live row → 409.
  - A voided approval → 409 at approve.
  - The pre-tx "in use" check is serialised by the FG-463 day lock.

| Gate | Result |
|---|---|
| lab_0* | 261 |
| probes lab02 / retake / f75_01 / race | 4 / 1 / 51 / 20 |
| SEC-01 | 30 |
| SEC-02 | 31; regen 0 cells |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/246, 0/496 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | 138 / 132 / 47 |

## 2026-11-09 15:45 UTC: queue status (main still `1525a1e`)

- **PASS on the latest heads, each containing main `1525a1e`:**
  - #86 `49eb546`
  - #84 `faaa2d0`
  - #83 `2415b5f`
  - #89 `7cfeae5`
  - #73 `d34d41b`
  - #75 `4fa4957`
  - #88 `62f898a`
  - #82 `108afc0`
- **Each was audited against main only, not against the others.** After the first merge, the rest must re-merge main and be re-audited. Shared hotspots: `routes/finance.py`, `tenancy/ownership.py`, `dq_issues`, and the PM-01 / SEC-01 / SEC-02 evidence.
- **Open non-blocking items:**
  - LAB73-N1: reversal period (design).
  - SEC-02 `leaks_7777` substring flake (debt).
  - #88 D5: `assets.emergent.sh` script in `index.html` (Krum).
- **Environment:** three or more audit mongods on volumes `audit2_db*` (created by this session), quiet logs; ~20 GB free. `pytest-asyncio` and `pypdf` are needed by the suites but are missing from `requirements*.txt` (debt).

## 2026-11-09 16:30 UTC: follow-ups on the orchestrator's queued requests

- **#83 `2415b5f`, fixtures in #81 / #55 tests (vs main):** 0 assertion lines removed; 3 added. No guard is patched off. Accounts are registered and verified through the real register.
- **#89 R67 test changes:** exactly R67.
  - The Accountant moves to the allowed side.
  - Tech and the project manager move to the forbidden side.
  - In enforce, "nothing written" compares only the business collections. PM-01 still checks every denial cell.
- **#89 FG-472:** `offer_budget`'s router is not mounted (confirmed).
- **#88 `62f898a` dependencies:** `--frozen-lockfile` verified the sha512 of every tarball against `yarn.lock`.
  - posthog-js 1.200.0, preact 10.29.8, core-js 3.51.0, fflate 0.4.9 (`^0.4.8`), web-vitals 4.2.4.
  - All are more than 2 weeks old.
- **#82 `tests/test_procurement.py`:** not runnable here. Its credentials and project id are not created by any repo seed (an external preview environment), and it calls the retired `post-to-warehouse`.
- **Trial merge #84 `faaa2d0` × #82 `108afc0`:**
  - `merge-tree` conflicts in code: `routes/finance.py`, `warehouse_movements/service.py`, `ownership.py` (add / add), plus the A1 inventory and `run_meta`.
  - Resolved as a union (second `@staticmethod`, one `expected_credit_notes`); A1 inventory regenerated.
  - Result:

| Suite | Result |
|---|---|
| probe whrev01 | 144 |
| silock | 3 |
| wh_rev_01 | 104 |
| fg233 | 9 |
| wh_fix_01 | 47 / 129 / 132 |
| probe R64 | 9 |
| probe invcn01 | 99 |
| inv_cn_01 | 165 |
| SEC-01 | 30 |
| PAY | 630 |
| A2C / A1 | 0 / 0 |
| **warehouse** | **44 / 1121** |

  - The second of #82 / #84 to merge must carry this union resolution.
- **Environment:** `audit2mongo` (27020) exited once (code 14) during the trial. It was restarted on its volume and the affected suites were re-run. Earlier verdicts come from completed runs.

## 2026-11-09 18:00 UTC: #90 SEC-03 `bc52843` (Emergent removal + hardening, R75 / R76): PASS, no blocking finding

- **No external script:** the built `index.html` = the app bundle + main's legacy PostHog inline snippet (H-2 debt). The CSP blocks that snippet (hash verified).
- **The CSP does not break the app.** My e2e:
  - Setup: production build + the repo's `nginx.conf` (nginx:1.27-alpine) + uvicorn on real Mongo + the PR's `e2e_bot.js`. Result: BOT PASSED.
  - Login and 7 screens render; framing is blocked; every script comes from the app origin.
  - CSP / XFO / nosniff / Referrer are on every response.
  - The 2 violations are the legacy snippet. The 403s are the same as on main.
- **AI:** `anthropic==2.3.0` is genuine. Its new pins (httpx2 / httpcore2 from pydantic, etc.) are its declared dependencies. Key and model come from env only; `ai_enabled` is off by default; only the error type is logged; ЕГН / IBAN are redacted in the text part.
- **JWT_SECRET:** fail-closed and correct.
- **Reminder trigger:** an internal key (≥ 32, `compare_digest`) or a Platform Admin, with an explicit scope and an AuditEvent per tenant. The `attendance.py` change is a pure move.
- **Print XSS:** escaped.

| Gate | Result |
|---|---|
| sec_03 | 45 |
| w0_03e_c02 | 25 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/243, 0/490 |
| **warehouse** | **44 / 1121** |
| ops/release | 81 (+1 skip) |
| ST-02 | 162 |
| jest | 22 / 191 |
| build | OK |

- **Non-blocking notes:**
  - N1: production must have `JWT_SECRET` ≥ 32 bytes before deploy; the live `nginx.conf` must be replaced.
  - N2: `PUT /feature-flags` toggles only the Platform Admin's own org; there is no per-tenant path for `ai_enabled`.
  - N3: redaction covers only upper-case IBAN and plain 10-digit ЕГН in text; images are not redacted.
  - N4: stale docstring in `ai_proposal.py`.
- **Merge note:** #88 × #90 conflict in `frontend/public/index.html` only. After both land, nginx `connect-src` needs the PostHog host when a key is set.

## 2026-11-09 18:00 UTC: #83 CP-01 `781d185` (pass 41: FG-510 / 498 / 511 / 513): PASS, no blocking finding

| Gate | Result |
|---|---|
| probe | 84 |
| cp_01 | 724 (+15) |
| sub_adv_01 | 9 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | within main's 16 |
| A2C / A1 | 0 / 0 |
| **warehouse** | **44 / 1121** |
| wh_fix_01 | 138 / 132 / 47 |

## 2026-11-09 17:30 UTC: post-merge confirmations: main `5e36dc2` (#86) and main `3863610` (#88)

- **main `5e36dc2`:** parents `1525a1e` + `49eb546` (#86, audited PASS). Tree `affedab0` = `merge-tree(1525a1e, 49eb546)` = the `49eb546` tree. Role-union 0.
- **main `3863610`:** parents `5e36dc2` + `e03315a` (#88). Tree `035f0ff2` = `merge-tree(5e36dc2, e03315a)`. Role-union 0.
  - `e03315a` = `merge-tree(5e36dc2, 62f898a)` (the audited PASS head) + 2 evidence files under `docs/evidence/PWA-01/main-merge-5e36dc2/` only.
  - #88 brings 0 backend bytes (`5e36dc2..3863610 -- backend` empty).
- **Open heads onto `3863610`:**
  - #83 `781d185` conflicts in code (`routes/projects.py`, `tenancy/ownership.py`) + `run_meta`.
  - #90 `bc52843` conflicts in `frontend/public/index.html` + `run_meta`.
  - Both need a re-merge of main and a re-audit.

## 2026-11-13 18:50 UTC: #90 SEC-03 `aaef24f` (merge `bbb98cfe` of main `3863610` + passes 42 / 44 + SEC90-N5): PASS, no blocking finding

- **Merge `bbb98cfe`:** = merge-tree except the resolved `index.html` + `run_meta`. Role-union 0. Clean onto main.
- **`index.html`:** #88's PWA tags kept; 0 inline script; 0 `phc_`. The nginx header carries only directives that do not depend on configuration; `connect-src` comes from the build-templated meta CSP.
- **SEC90-N5 (found on `2b70152`, PROVED):** a host with a path, e.g. `REACT_APP_POSTHOG_HOST=http://localhost:4177/__posthog`, put that path into `connect-src`, so `/__posthog/e/` was blocked (28 / 30). Fixed in `aaef24f`: the CSP gets `new URL(x).origin`.
- **e2e (production build + nginx + uvicorn + real Mongo):**

| Build | Result |
|---|---|
| no key | 30 / 30, 0 CSP violations |
| key + path host | 30 / 30, 0 violations, 9 analytics requests allowed |

- **Pass 42 / 44 review:**
  - Owner-only `PUT /api/ai/settings`: Idempotency-Key + reason + AuditEvent in one transaction. Closes N2.
  - Broadened redaction: any case, NBSP / dash separators, any digit run of 10 or more. Closes N3 for text.
  - Photo AI refused until W0-06.
  - `ai_usage_ledger` classified.
  - The removed unused pins: nothing imports them; a clean venv from exactly these requirements imports `server`.
- **Gates:**

| Gate | Result |
|---|---|
| sec_03 | 95 |
| w0_03e_c02 | 25 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| PAY | 630 |
| R0 | 814 |
| W0 | main's 16 |
| A2C / A1 | 0/244, 0/492 |
| **warehouse** | **44 / 1121** |
| ops/release | 81 |
| ST-02 | 162 |
| jest | 30 / 270 |

- **N1 (Release Manifest):** production needs `JWT_SECRET` ≥ 32 bytes before deploy; replace the live `nginx.conf`; then update `LIVE_NGINX_BLOB`.
- **Environment:** the container restarted three times (2026-11-09 17:55, 19:04 and 2026-11-10 06:01). Docker was recovered each time, and runs cut by a restart were repeated. No verdict uses an interrupted result.

## 2026-11-13 — #82 WH-REV-01 `d6de7db4` — PASS

- **Merge check:**
  - `d6de7db4` contains main `3863610`;
  - the merge equals `git merge-tree --write-tree` except PM-01 `run_meta`;
  - role-union 0;
  - it still merges cleanly onto main `3863610`.
- **Gates** (real Mongo 7.0 rs; warehouse in `PERMISSION_SERVICE_MODE=enforce`):

| Gate | Result |
|---|---|
| R0 | 814 |
| W0 | 16 = main's 16 (identical set) |
| A2C / A1 | 0/245, 0/494 |
| PAY | 630 |
| SEC-01 | 30 |
| SEC-02 | 31; committed `results.json` 176 probes = code 176 |
| PM-01 | 6 / 0 skipped; harness regen 0 differing cells |
| **warehouse** | **44 files / 1121** |
| WH-REV-01 own + probes | `wh_rev_01` 120, `probe_whrev01` 144, `silock` 3, `wh_fix_01` post_55 47 / a3_r44 138 / f81 132 |

- **Environment:** root cause of today's mongod exit-14 aborts: WiredTiger `Too many open files` (dockerd nofile 20000; WT keeps dropped/idle table handles ~28h by default).
  - Fix: runtime `file_manager=(close_idle_time=20)` on the audit mongods, plus DB drops after every file.
  - No verdict uses an interrupted run.

## 2026-11-13 — #82 WH-REV-01 `cd454eaa` — PASS (delta)

- **Delta over `d6de7db4`** (PASS above): one commit, FG-573, changing only `docs/evidence/PM-01/run_meta.json`; no code or test change.
- The new `run_meta` equals the meta written by my independent PM-01 harness regeneration on `d6de7db4`, except `seconds` (timing). 779 routes, 18696 cells, same roles / role_ids / modes.
- Still merges cleanly onto main `3863610`; d6de7db4's gates stand.

## 2026-11-13 — SEC-02 pulse "7777" (P1 from orchestrator) — closed as a probe false positive

- **Mechanism:**
  - `GET /api/sites/{id}/pulse` regenerates today's pulse with a new `uuid4` `id` (`pulse_generator.py:168`) and a microsecond `generated_at` (`:14`).
  - For non-finance roles `strip_pulse_for_non_finance` keeps those, correctly: they are not money.
  - The probe tested `"7777" in resp.text`.
- **Deterministic repro (local only):**
  - uuid4 was forced to `…000000007777` for pulse_generator only.
  - Result: 99 non-finance responses flagged, and all 129 "7777" occurrences are inside `"id"`. hidden_budget_keys / money_keys were `[]`.
- **Scope:** main `3863610` has the same flake.
  - Fix: FG-567 (field-aware probe) on #73 `b1f7e902`.

## 2026-11-13 — #89 OFF-02 `5763bd86` — PASS

### OFF89-M2 (raised on `58d0e402`, closed)

- **Finding:** the main-merge commit `58d0e402` resolved `docs/evidence/SEC-02/results.json` by taking main's copy.
  - That copy is blob `58b559ee`, 176 probes.
  - The PR's own regenerated copy (`edd450d7`, 185 probes) was dropped.
- **Effect:** the merged code has 188 probes, so SEC-02 failed 2 tests on real Mongo, at `:1868` and `:2039`.
- **Fix:** `5f64a60a` / `5763bd86` regenerated the evidence by the harnesses. Since `58d0e402` only `docs/evidence/` changed; there is no code change.

### Merge check

- `5763bd86` contains main `3863610`.
- The merge equals merge-tree except PM-01 `run_meta` and SEC-02 evidence (regenerated).
- Role-union 0; clean onto main.

### Gates

Real Mongo; code is identical to `58d0e402`, where W0 ran.

| Gate | Result |
|---|---|
| R0 | 814 |
| W0 | 16 = main's 16 |
| A2C / A1 | 0/243, 0/490 |
| PAY | 630 |
| SEC-02 | 31; committed 188 probes = code 188; **independent harness regen: 0 differing cells** |
| PM-01 | 6 / 0 skipped; regen 0 cells |
| **warehouse** | **44 / 1121** (enforce) |

- **Run on `58d0e402`** (same code as `5763bd86`): SEC-01 30; own suites `off_02_offer_money_strip` 34, `off_01_offer_version_accept` 90, `off_01_audit_probe` 147; probe off01 675.

## 2026-11-13 — #73 LAB-01 `ed6e88d4` — PASS (pending Krum: FG-565 proforma, FG-569 akord→payroll)

- **Heads:**
  - `ed6e88d4` = `b1f7e902` (FG-566 aggregate access, FG-567 field-aware SEC-02 probe, FG-530 isolation) + `docs/evidence` only;
  - `b1f7e902` contains main `3863610` via `4a63a1e`.
- **Merge check:**
  - `4a63a1e` = merge-tree(`cf6fd3d4`, `3863610`) except the conflict files.
  - The one code conflict, `projects.py` `count_invoices(subtree_ids)` + `issued_net`, is resolved correctly. The rest is PM-01 / SEC-02 evidence.
  - Role-union 0 (merge and head); clean onto main; no unclassified collections.
- **FG-566 (static):**
  - non-finance callers need current `project_team` membership (else 403);
  - `_aggregate_without_money` drops invoices / pnl / paid_labor / materials / labor_cost, top level and per child;
  - plus `strip_money_for_non_finance(keep=("total",))`;
  - registered R20-5M.
- **Gates** (real Mongo; code gates on `b1f7e902`, evidence gates on `ed6e88d4`):

| Gate | Result |
|---|---|
| R0 | 814 |
| W0 | 16 = main's 16 |
| A2C / A1 | 0/246, 0/496 |
| PAY | 630 |
| SEC-01 | 30 |
| SEC-02 (`ed6e88d4`) | 31; 177 probes; **independent harness regen on `b1f7e902` = committed: 0 differing cells**; every 7777 row in the regen is a finance role |
| PM-01 (`ed6e88d4`) | 6 / 0 skipped; **regen = committed: 0 cells** (includes the 15 `/aggregate` cells) |
| **warehouse** | **44 / 1121** (enforce) |
| LAB-01 suites | 227 |
| probes | lab01e_payrun_r29 4, lab01f_sources 5, lab01h_r36 3, lab01t_fg463_race 20 |

- **Note:** on the stale `b1f7e902` evidence, SEC-02 and PM-01 failed (176 vs 177 probes; 15 `/aggregate` cells), as expected before the regen. `ed6e88d4` closes that.

## 2026-11-13 — #75 LAB-02 `a665932b` — PASS (pending Krum: FG-565, FG-569)

- **Merge check:**
  - `b470e752` = merge-tree(`8ef6b442`, #73 `ed6e88d4`) except `docs/evidence`;
  - contains #73 `ed6e88d4` and main `3863610`;
  - role-union 0; clean onto main; no unclassified collections.
- **FG-568 (static):** `void_labor_approvals` runs the bump, voids, R77 flags (+ the repair of never-flagged rows) and the DOWNTIME classification voids in ONE body. The body runs in the caller's session or in its own transaction.
- **Gates** (real Mongo, warehouse in enforce):

| Gate | Result |
|---|---|
| R0 | 814 |
| W0 | 16 = main's 16 |
| A2C / A1 | 0/247, 0/498 |
| PAY | 630 |
| SEC-01 | 30 |
| SEC-02 | 31; **harness regen 0 differing cells** |
| PM-01 | 6 / 0 skipped; regen 0 cells |
| **warehouse** | **44 / 1121** |
| LAB-01 + LAB-02 suites | 314 + 1 env-only (`test_lab01c_put_daily_report_refuses_pricing_fields_in_day_entries` needs `MONGO_URL`; with it `test_lab_01_labor_cost.py` 25/25) |
| probes | lab02 4, lab02_retake 1, f75_01 51, lab01t_fg463_race 20 |

- **Note:** #73 has since moved to `3d39a9df` (FG-591/592). #75 must re-merge it before merge.

## 2026-11-13 — #83 CP-01 `5695f974` — PASS

### Findings on `ec346f86` (FG-562), both closed

**CP83-M6** — the invoice VAT number could no longer be cleared.
- Repro: `PUT /api/finance/invoices/{id} {"counterparty_vat_no": ""}` returned 200 but kept the stored value.
- Cause: `vat_update("")` → ("set", None) → the field was dropped by `if v is not None`.
- Probe: `docs/audit/probes/cp01/test_probe_cp83_vatclear.py`. It passes on `ddc6e9ad`, fails 3/3 on `ec346f86`, and passes on `5695f974`.
- Fixed by `38ee979e`.

**CP83-M7** — the W0 A1 static guard went red.
- The committed A1 inventory had 380 accesses; the generated one has 381. The missing row is FG-562's `companies.get` in `update_company`.
- Fixed by `5695f974`: A1 inventory regenerated (381 / FIXED 124), plus the A2C / A2 project_team inventories.

### Merge check

- Contains main `3863610`; clean onto main; role-union 0.
- Since `ec346f86` the code delta is `finance.py` `update_invoice` only (an explicit "" clears).

### Gates on real Mongo

| Gate | `ec346f86` | `5695f974` |
|---|---|---|
| probe cp01 | 84 | — |
| CP-01 suite | 753 / 15 skipped | 759 / 15 skipped (+ probe) |
| SUB-ADV / PRJ-01 | 9 / 9 | — |
| SEC-01 | 30 | 30 |
| SEC-02 | 31 | — |
| PM-01 | 6; regen 0 cells | 6 |
| PAY | 630 | 630 |
| A2C / A1 | 0/248, 0/500 | 0/248, 0/500 |
| R0 | 814 | — |
| W0 | 11 (M7) | **10 = `ddc6e9ad`'s set** (strict subset of main's 16; CP-01 R48.4 never-delete) |
| **warehouse** | **44 / 1121** | — |
| wh_fix_01 | 138 / 132 / 47 | — |

- **Open, for whichever of #83 / #91 merges second:** FG-555 / FG-589.

## 2026-11-13 — #90 SEC-03 `66dd1ae6` (code `38a3bfd4`) — PASS (delta over `aaef24f4`)

- **Commits:** FG-563 (`b95ee4ea`, `0716f8e9`, `f34b1f25`) and FG-603 / FG-604 (`38a3bfd4`).

### Merge check

- Contains main `3863610`; clean onto main; role-union 0.

### `complete_idempotent` / `begin` / `release` stay additive

- `session` is passed only when given.
- `attempt_token` filters only when passed. `begin` writes a token on every record, which is additive.
- A FAILED-key retake is a CAS that writes a new token.
- A pre-deploy STARTED key with no token still matches the `{attempt_token: None}` release filter.
- Only `put_ai_settings` passes `expires_at`. The 10 other `begin_idempotent` callers and the warehouse service's own registry records never write it.

### TTL — live on real Mongo, on `0c04438c` and again on `38a3bfd4`

- A key with a past `expires_at` was removed after about 40 s.
- Keys without `expires_at`, or with `expires_at` 7 days ahead, remain.
- Index: `expires_at` with `expireAfterSeconds` 0.

### Lost attempt

- `test_real_mongo_fg603_…` ran on real Mongo (not skipped):
  - the stale attempt A resumes after B's takeover;
  - A's CAS raises `IdempotencyAttemptLost` inside the transaction, so A rolls back;
  - exactly one `ai.settings.changed` event exists;
  - A answers with B's result.

### A2C registry-write fix

- Both registry updates (stale-CAS release and failure release) filter on `tenant_id`.
- A2C 0.

### Gates (`66dd1ae6`)

| Gate | Result |
|---|---|
| SEC-03 | 148 (4 real-Mongo) |
| w0_03e_c02 | 25 |
| A2C / A1 | 0/244, 0/492 |
| SEC-01 | 30 |
| PAY | 630 |
| W0 | 16 = main's 16 |
| SEC-02 | 31 |
| PM-01 | 6 |
| **warehouse** | **44 / 1121** |

- **On `0c04438c`:** R0 814.
- **N1 (deploy) stands:** `JWT_SECRET` ≥ 32 bytes; replace the live `nginx.conf`; then update `LIVE_NGINX_BLOB`.

## 2026-11-13 — #84 INV-CN-01 `38d3244b` — PASS

- **Head:** `38d3244b` = `baafdf3a` (FG-599) + `docs/evidence` only.

### Merge check

- Contains main `3863610`; clean onto main; role-union 0.
- The earlier main-merge `9874601` equals merge-tree except PM-01 `run_meta` and SEC-02 evidence.

### Static review

- **F-84-01:** all 17 `invoice_corrections` routes take a Permission Service action first.
  - Codex's revoked / expired / missing × off / shadow / enforce matrix is `test_f84_01_…` in the own suite.
- **FG-572:** `require_money_write` comes first on PUT invoice, cancel, cancel/approve and cancel/reject.
  - The four new actions are granted to owner / admin / accountant.
  - The Owner-only Р51 approval stays in the service.
- **FG-571:**
  - `payable_net` → `current_open` → `payable_until_credit_note`;
  - `_check_offset` is equivalent to before.
- **FG-599:**
  - outgoing note: legacy role must be Accountant, else 403 `ISSUER_ROLE_REQUIRED`;
  - the UI issue button is shown only to the Accountant.
  - The 2 changed old tests relax nothing: the same-person guard is still asserted, and `f84_01` off / shadow is tightened from 201 to 403.

### Gates (real Mongo)

| Gate | `ebcac7f9` | `baafdf3a` (= `38d3244b` code) |
|---|---|---|
| R0 | 814 | — |
| W0 | 16 = main's 16 | — |
| A2C / A1 | 0/246, 0/496 | — |
| PAY | 630 | — |
| SEC-01 | 30 | 30 |
| SEC-02 | 31; regen 0 cells | 31 |
| PM-01 | 6; regen 0 cells | 6; regen 0 cells |
| inv_cn_01 | 186 | 189 |
| probes | R64 9 / invcn01 99 | invcn01 99 |
| **warehouse** | **44 / 1121** | — |
| fg233 / wh_fix_01 | 9 / 47 / 129 / 132 | — |

- **Not re-run on `baafdf3a`:** the warehouse suite. FG-599 touches only the `create_note` route and the UI.

### For whichever of #82 / #84 merges second (union trial `671de2be` + `4dd01e88`, all green)

- Merge-file union.
- Restore `@staticmethod` before `_plan_receipt_reversal`.
- Keep one `"expected_credit_notes"` ownership entry.
- Regenerate the A1 inventory by redirecting the script's stdout into the doc.
- R47 wiring: `ic.payable_until_credit_note` fits #82's call sites.
  - **Units trap:** `ic.cents` is a 0.01 Decimal; `credit_note_rule.cents` is integer cents.
  - #82's reversal guard should use `ic.payable_net`.

## 2026-11-13 — #83 CP-01 `eb8138fc` — PASS (evidence-only delta over `5695f974`)

- **Diff:** `5695f974..eb8138fc` changes only `docs/` (regenerated evidence, SEC-02 and SUB-ADV-01 included).
- **Merge check:** clean onto main `3863610`.
- **On `eb8138fc`, real Mongo:**
  - SEC-02 31, so the committed `results.json` matches the code;
  - PM-01 6 / 0 skipped.
- **Other gates:** the `5695f974` PASS gates stand.
- **Environment:** the container restarted at 21:53 (Docker recovered, mongods back with the fd setting re-applied). The interrupted runs were discarded and re-run.

## 2026-11-13 — #91 MEDIA-SEC-01 `582eb9d3` (code `fdd3ec7f`) — PASS

- **Head:**
  - `582eb9d3` = `fdd3ec7f` + evidence (`206262a0` PM-01 regen, `582eb9d3` gates);
  - `fdd3ec7f` is a one-line change over `a15b6145`.
- **MEDIA91-M1 (raised on `a15b6145`, closed):**
  - `backend/app/services/file_holders.py:334` read `warehouse_transactions` with `.to_list(50)`, a capped canonical read.
  - It broke warehouse `test_c12_10_static_scan_zero_offenders_overall` and `test_c13_6_scanner_zero_offenders_on_clean_tree` (1 scanner hit).
  - Fixed: `.to_list(None)`.
- **Merge check:** head tree = merge-tree(main `3863610`, head); role-union 0; no unclassified collections.
- **Gates** (real Mongo, warehouse in enforce):

| Gate | `582eb9d3` | `a15b6145` (code = `fdd3ec7` except that one line) |
|---|---|---|
| MEDIA-SEC-01 own suite | 55 | 55 |
| PM-01 | 6 / 0 skipped; **regen 0 cells** | — |
| SEC-02 | 31; **harness regen 0 differing cells** | 31 |
| **warehouse** | **44 / 1121** | — |
| frontend jest | 28 suites / 259 tests | — |
| SEC-01 | — | 30 |
| PAY | — | 630 |
| A2C / A1 | — | 0/247, 0/498 |
| R0 | — | 814 |
| W0 | — | 16 = main's 16 |

- **FLOW Guard:** pass 50 found nothing medium or above (orchestrator).
- **Open for whichever of #83 / #91 merges second:** FG-555 / FG-589.

## 2026-11-13 — #73 `a1859bf4` / #75 `c7d8464b` — PASS (delta; pending Krum FG-565 / FG-569)

### #73 `a1859bf4`

- `a1859bf4` = `3d39a9df` (FG-591 UI: no 0 € for absent money; FG-592 SEC-02 child seed) + regenerated evidence (FG-618).
- Clean onto main; role-union 0.
- Real Mongo:
  - SEC-02 31;
  - **independent SEC-02 regen = committed: 0 differing cells**. The only 7777 rows are Owner / Admin / Accountant, and 0 non-finance `/aggregate` rows carry money keys.
  - PM-01 6 / 0 skipped.
- Earlier on `3d39a9df`: PM-01 6, A2C / A1 0/246, 0/496; `ProjectDetailPage.aggregate.test.js` 2 / 2.
- The `ed6e88d4` gates stand.

### #75 `c7d8464b`

- Merge check:
  - `d8f59c31` = merge-tree(`a665932b`, #73 `a1859bf4`) except `docs/evidence`;
  - the code delta over `a665932b` is #73's (SEC-02 test seed + frontend);
  - clean onto main; role-union 0.
- Real Mongo:
  - SEC-02 31; **regen 0 cells** (same role picture as #73);
  - PM-01 6 / 0 skipped;
  - LAB-01 + 02: 314 + the 1 env-only test (`MONGO_URL`, passes with it as before);
  - A2C / A1 0/247, 0/498.
- jest `ProjectDetailPage.aggregate` 2 / 2.
- The `a665932b` gates stand (warehouse 44 / 1121 etc.).
- **Environment:** the container restarted again at about 23:00; recovered. No verdict uses an interrupted run.

## 2026-11-13 — #92 PWA-02 `614510e8` — FAIL (PWA92-M1); FLOW Guard pending

### Merge check

- Contains main `3863610`; clean; role-union 0.
- New collections are classified (`sync_*`).

### Gates (real Mongo)

| Gate | Result |
|---|---|
| PWA-02 suites | 43 |
| SEC-01 | 30 |
| SEC-02 | 31; harness regen 0 cells |
| PM-01 | 6 / 0 skipped; regen 0 cells |
| PAY | 630 |
| A2C / A1 | 0/246, 0/496 |
| R0 | 814 |
| W0 | 16 = main's 16 |
| **warehouse** | **44 / 1121** |
| jest | 29 / 276 |

### PWA92-M1 (blocking) — a crash-retry writes the daily report twice

- **Where:** `offline_sync_handlers._daily_report`.
  - `submit_daily_report` inserts the drafts.
  - Only afterwards does `update_many` tag them with `sync_local_id`.
  - The retake guard (`mine`) looks for that tag, and the write and the tag are not atomic.
- **Probe:** `docs/audit/probes/pwa02/test_probe_pwa02.py`.
  1. Attendance is synced first.
  2. The first item crashes after submit, before the tag. The batch answers 500 and the receipt stays "processing".
  3. After `PROCESSING_STALE` (2 min) the same item is resent and the takeover re-runs the handler.
- **Result:** **2 rows, 1 tagged**, while the receipt says synced.
- **Fix:** tag inside the insert, or use one transaction, or add a unique partial index on `sync_local_id`.

### Non-blocking

- **PWA92-N1:** a generic Exception from a handler escapes `process_item`. The whole batch answers 500 and the receipt is left "processing".
- **PWA92-N2:** `attendance.mark` (online on main too) accepts a foreign tenant's `project_id`; `check_project_writable` returns on "not found". Debt.
- **Minor debt:** a crash mid-decision leaves the item "deciding" with no takeover.

### Passed in the probe

- Daily report into a foreign project: 404, nothing written.
- Foreign device: 409.
- Cross-tenant revoke: 404, and the console is isolated.
- Same key in parallel: 1 row, 1 receipt.

## 2026-11-14 — #92 PWA-02 `4140b027` (code `4dd947c6`) — PASS

- **Head:** `4140b027` = `4dd947c6` + `docs/evidence/PWA-02` only (README, gates, e2e results, screenshots).
- **Merge check:** clean onto main `3863610`; role-union 0; no unclassified collections. `ops_alarms` is classified TECHNICAL.

### Findings — all closed

- **PWA92-M1** (crash-retry duplicate daily report):
  - Closed by `5d115d2d`: the drafts are inserted already tagged, in one transaction, with a unique partial index.
  - Probe on `4dd947c6`:
    - post-write crash: 1 tagged row;
    - **S7 (same local_id under 2 keys, in parallel): 1 row (old head: 2)**.
- **PWA92-N1** (a generic exception made the batch 500): closed. The item answers `retry` / `SERVER_ERROR_RETRY`.
- **PWA92-M2** (A2C 1 violation, `getattr(database, …)`): closed by `41ef3848`. A2C 0/247.
- **PWA92-M3** (W0 18: `ops_alarms` unclassified + stale A2B inventory): closed by `4dd947c6`. W0 16 = main's set.

### Debt, not blocking

- **PWA92-N2:** a foreign `project_id` on attendance is accepted, as on main (`check_project_writable` returns on not-found).
- **Observation:** `attendance_void.py:147` / `:248` use `._raw.update_one` with a literal `org_id`, to reach voided (hidden) rows.

### No-delete check

- No `delete_one` / `delete_many` / `find_one_and_delete` on `attendance_entries` or `employee_daily_reports` in `app/` or `scripts/`, directly, via `tenant.collection(…)` or via variables.
- Main had 4 (`technician.py:504` / `1334` / `1340` / `1414`); all are replaced by void.

### Isolation (probe)

- Daily report into a foreign project: 404, nothing written.
- Foreign device: 409.
- Cross-tenant revoke: 404, and the console is isolated.
- Same key in parallel: 1 row, 1 receipt.

### Gates on `4dd947c6` (real Mongo, warehouse in enforce)

| Gate | Result |
|---|---|
| PWA-02 suites | 72 |
| SEC-01 | 30 |
| SEC-02 | 31; **harness regen 0 cells** |
| PM-01 | 6 / 0 skipped; **regen 0 cells** |
| PAY | 630 |
| A2C / A1 | 0/247, 0/498 |
| R0 | 814 |
| W0 | 16 = main's 16 |
| **warehouse** | **44 / 1121** |
| jest (on `4140b027`) | 33 / 288 |

- **Not counted:** on `db8a7e33`, a SEC-02 run hit the known pulse "7777" uuid flake (main's probe; FG-567 lives on #73). The re-run passed 31/31.

### Deploy note

- `pwa02_attendance_day_unique` / `pwa02_daily_report_sync_unique` are skipped with an ALARM (`ops_alarms`) if duplicates exist.
- Run `scripts/pwa02_unique_index_dryrun.py` (read-only) per tenant before deploy.

## 2026-11-14 — #91 MEDIA-SEC-01 `2de0f859` (code `900dc9c3`) — PASS (delta over `582eb9d3`)

- **Head:** `2de0f859` = `900dc9c3` + `docs/evidence` only.
- **Code delta over `582eb9d3`:**
  - R88 restore (`POST /api/media/{id}/restore`) and the retired list (`GET /api/media-retired`);
  - the "Файлове за преглед" screen;
  - FG-693 paging (`/media-retire-requests` is now `{items, total, skip, limit, next_skip}`; the only caller is the new `mediaReview.js`).
- **Merge check:** clean onto main `3863610`; role-union 0.

### R88 restore (static)

- **Gating:** Owner only (`RESTORE_ROLES`) → otherwise 403; Idempotency-Key → 428; reason → 422 / 400.
- **One keyed transaction:**
  - CAS on "still retired" + `ref_version` → otherwise 409 `MEDIA_CHANGED`;
  - `ref_version` +1;
  - the retire fields move into `retire_history` (append, nothing lost);
  - AuditEvent `media.file.restored`.
- **Retired list:** Owner / Admin, paged, with a per-row `can_restore`.

### PM-01 regen

- Restore: owner → 428 (needs the key), every other role → 403, in off / shadow / enforce.
- Regen = committed: 0 cells (48 rows for restore / retired list).

### Frontend gating

- `mediaReviewAccess.js`: REVIEW Owner / Admin, DECIDE Owner, RESTORE Owner. It mirrors `media_policy` (`RETIRED_LIST_ROLES`, `RESTORE_ROLES`).
- `MediaReviewRoute` has its own guard; it is not AdminRoute, which also admits SiteManager / Accountant.

### Gates on `900dc9c3` (real Mongo)

| Gate | Result |
|---|---|
| MEDIA-SEC-01 | 60 |
| PM-01 | 6; regen 0 cells |
| SEC-01 | 30 |
| SEC-02 | 31; regen 0 cells |
| A2C / A1 | 0/247, 0/498 |
| W0 | 16 = main's 16 |
| PAY | 630 |
| R0 | 814 |
| **warehouse** | **44 / 1121** |
| jest | 29 / 283 |

## 2026-11-14 — #82 WH-REV-01 `558dfdff` (code `642227b9`) — PASS (delta over `cd454eaa`)

- **R84** (Krum 14.11.2026, FG-570): a return on an already-paid supplier invoice is recorded. `INVOICE_PAID_ABOVE_NET` is removed. The overpaid part opens one `supplier_claims` record per reversal:
  - deterministic id `claim_<movement>`, so a replay adds nothing;
  - written in the movement's transaction;
  - AuditEvent `finance.supplier_claim.opened` on first insert only.
  - It is never netted: payments are untouched. Refund / offset are t26 / #84 debt.
- **Static check:**
  - `overpaid_cents` / `claimed` / `cents(amount)` are all integer cents;
  - claim = min(this return, overpaid − already-open claims);
  - `supplier_claims` is classified (FAMILY finance).
- **Merge check:** clean onto main `3863610`; role-union 0.
- **Probe** `whrev01/test_probe_whrev01_r84_two.py` (new):
  - two successive returns (2 + 2 of 10) on an invoice paid 120 → claims **24 + 24**; the second claims only the increment;
  - the replay adds nothing; 2 AuditEvents;
  - off / shadow / enforce.
- **Gates** (real Mongo, warehouse in enforce):

| Gate | Result |
|---|---|
| wh_rev_01 | 123 |
| probe_whrev01 | 144 |
| silock | 3 |
| wh_fix_01 | 47 / 138 / 132 |
| A2C / A1 | 0/245, 0/494 |
| W0 | 16 = main's 16 |
| PAY | 630 |
| SEC-01 | 30 |
| SEC-02 | 31 |
| PM-01 | 6; regen 0 cells |
| R0 | 814 |
| **warehouse** | **44 / 1121** |

- **Pending:** FLOW Guard's single-source question (`supplier_claims` vs the #84 ledgers).
- **Note:** a claim no longer `open` (settled later) is not subtracted by a later return's `claimed`. Correct as long as settling also changes `paid` / credit. Check when t26 lands.

- **2026-11-14 update:** FG-690 decision — #82 will drop `supplier_claims` after #84 merges; the overpaid part becomes an open expected supplier credit in #84's `expected_credit_notes`. The `558dfdff` PASS stands for the record only; the union trial with `supplier_claims` was skipped on the orchestrator's instruction.

## 2026-11-14 — #91 MEDIA-SEC-01 `39a1e277` (code `c41da0ba`) — PASS (delta over `2de0f859`)

- **Head:** `39a1e277` = `c41da0ba` + `docs/evidence` only. Clean onto main; role-union 0.

### FG-706 keyset paging

- Covers `/media-retire-requests` and `/media-retired`. The response is `{items, total, limit, next_cursor}`, and the cursor encodes (sort key, id).
- `_after` gives the rows strictly after the cursor in the (field desc, id asc) order.
- The null / missing sort key has its own branch, since null sorts last in descending order.
- A bad cursor → 400 `BAD_CURSOR`; limit 1..200.
- The only caller (`mediaReview.js`) is updated.

### FG-707

- `migrate(apply=True)` without `--approval-ref` raises `NotApproved` before any read. The dry run needs none.

### Gates on `c41da0ba` (real Mongo)

| Gate | Result |
|---|---|
| MEDIA-SEC-01 | 62 |
| PM-01 | 6; **regen 0 cells** |
| SEC-01 | 30 |
| SEC-02 | 31 |
| A2C / A1 | 0/247, 0/498 |
| W0 | 16 = main's 16 |
| jest | 29 / 283 |

- **Not re-run:** warehouse / PAY / R0. The delta touches only `media.py` list routes, the backfill script and the frontend; the `900dc9c3` runs stand (44 / 1121, 630, 814).

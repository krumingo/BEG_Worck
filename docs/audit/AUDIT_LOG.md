# CLAUDE AUDIT — log

> Internal second check by the Claude audit session. **Not Codex**, not an approval.
> Never merges, deploys or pushes to other branches. PROVED = reproduced here by command; SUSPICION = reasoning only.

## Last audited SHA per PR

| PR / branch | Last audited SHA | Result | Date |
|---|---|---|---|
| #56 AUTH-01 | `dae097bb46691a8d7cf5b55c6526b32ba597b03d` | PASS (minor notes) | 2026-11-06 |
| #55 Склад 5C (C18) | `639ca80e89db3d603d17cdded769b01aa4c92bd9` | FINDINGS (blocking: P55-1, P55-2) | 2026-11-06 |
| #65 RC-01 | `44c9c3cfa668cf9a601f65960680eac11ef70ec7` | FINDINGS (non-blocking, P1 medium) | 2026-11-06 |
| #66 ST-01 | `9904524caba59038b3251d3cd468defbe6205d96` | PASS with 1 medium finding (PST-1) | 2026-11-06 |

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

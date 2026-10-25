# CODEX independent re-review — AUTH C01 / warehouse C16

## PR #56 — 10ed6b5181bc5d95defb347868f1507899632854

Real MongoDB 7.0.43 replica set: **99 passed / 1 failed / 0 skipped / exit 1**, 129.76 seconds. Scope: password_recovery, c01_corrections, r0_04_merge, rc_corrections and independent test_codex_auth_settlement_contract.py.

The original ordering and environment failures are corrected for the exercised cases. Remaining failure: `test_same_millisecond_requests_still_leave_one_delivered_link` (independent test, line 49). Two requests minted with the same timestamp and delivered sequentially leave **2** unused sent links, expected 1. MongoDB BSON dates have millisecond precision; timestamp-only strict `<` does not provide a total ordering for real requests within the same millisecond.

CHANGES_REQUESTED RC-AUTH-03: preserve supersession and use a stable ordering/tie-break contract compatible with persisted precision and concurrent transactions. Do not simply change the assertion to allow two links or remove same-timestamp coverage. Prove both settlement orders, equal persisted timestamps, failed delivery, late settlement after password reset and actual concurrent settlement. No reactivation of revoked tokens. Independent reproduction source is in PR #64 under docs/evidence/INTEGRATED-RC-2026-10-25/test_codex_auth_settlement_contract.py.

## PR #55 — a2892a49be72ce232b9fe9e9a2659471fd4b2a48

Accelerated gate: **9 passed / 0 failed / 0 skipped / 19 deselected / exit 0**. This is the same nine selected tests as the previous 8-pass/1-fail run; expected count is nine, not eight.

Then full five-file real-Mongo matrix ran once: **28 passed / 1 failed / 0 skipped / exit 1**, 13.04 seconds. Files: c13_mongo, concurrency, mongo, mongo_c10, mongo_full. `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`, `PERMISSION_SERVICE_MODE=enforce`.

Failure: `test_c13_4_material_entries_rebuild_twice_byte_parity`, test_c13_mongo.py lines 507/513. `_snapshot()` executes `list(AsyncIOMotorCursor)` and raises TypeError before parity assertions. This is a test-harness defect, not evidence that parity passed or failed.

CHANGES_REQUESTED C17: make this snapshot helper await the Motor cursor (e.g. async helper + to_list), preserve both rebuild comparisons and legacy-row preservation assertions. No skip/xfail/mock substitution. Re-run focused gate, then full real-Mongo matrix after the corrected head. C16 Rule B focused failure is fixed in the independent real-Mongo run.

## Synology status

Owner completed DSM login. BEG_Work backend/frontend are running, created September 12 and up since September 16. Existing Krum execution cannot read Docker socket or protected backup; a disabled manual diagnostic task was prepared and executed once, recording only metadata. Docker image IDs/backup verification via this task failed with permission denied. Explicit owner approval has been requested for running the same bounded read-only task as root. No service restarts, deploy, data changes or credential changes.

НА РЕД Е: Claude bounded RC-AUTH-03 and C17 fixes, then exact SHA HANDOFF. #54 mockup and build identity remain assigned. Codex continues operational evidence and independent review. No merge/deploy approval.

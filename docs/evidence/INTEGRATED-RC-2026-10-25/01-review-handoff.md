# CODEX independent exact-head review — INTEGRATED-RC-2026-10-25

## Verdict: CHANGES_REQUESTED — #56 and #55

Synthetic test data only. MongoDB 7.0.43, fresh local single-node replica set `rc20261025`, `127.0.0.1:27165`. No production writes. No merge or deploy.

## PR #56 — 8e435a0e8823ff49d11dfe2803968b27701c688e

Independent runs (`--noconftest -q -p no:cacheprovider`, `W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27165/?replicaSet=rc20261025`):
- `test_auth_01_password_recovery.py` + `test_auth_01_c01_corrections.py`: 59 passed, 0 failed/skipped, exit 0.
- `test_auth_01_r0_04_merge.py`: 8 passed, 0 failed/skipped, exit 0.
- Two additional CODEX probes: 0 passed, 2 failed, 0 skipped, exit 1.

### RC-AUTH-01 — successfully delivered overlapping links revoke each other

`backend/app/services/password_reset.py::settle_delivery` marks the selected token sent only if unused, but then unconditionally revokes EVERY other unused token. Reproduction through the real transaction path:
1. `first = await request_reset(db, synthetic_owner, ip)`.
2. `second = await request_reset(db, synthetic_owner, ip)` before either SMTP completion.
3. `settle_delivery(db, first, DELIVERY_SENT, ip)`.
4. `settle_delivery(db, second, DELIVERY_SENT, ip)`.
5. Count unused sent tokens for that user: **0**, expected at least one.

First completion revokes pending second token; second completion cannot activate its already-revoked token but revokes the first. Both deliveries can succeed while neither link is usable. Correct ordering/settlement atomically; test both completion orders, SMTP failure and a reset occurring while another delivery is in flight. Do not reactivate a token invalidated by successful recovery. Preserve F-01 atomicity and F-06 preservation of older usable links on failed delivery.

### RC-AUTH-02 — inconsistent production environment guard permits reset URL logging

`_dev_url_logging_enabled()` checks only `ENV`. With `ENV` unset, `ENVIRONMENT=production`, and `PASSWORD_RESET_DEV_LOG_URL=1`, it returns **True**. No real token was logged by this probe. The application already uses ENVIRONMENT for production controls; align this guard with the canonical fail-closed environment policy, including conflicting/missing settings. Add explicit tests; production must never enable plaintext reset-link logging.

### Assignment to Claude

Same PR #56; bounded correction of RC-AUTH-01/02 only. Re-run 67 existing tests plus new real-Mongo regression probes. Publish exact SHA, commands/counts and HANDOFF. Do not self-declare independent PASS.

## PR #55 — 1dc557da5026246cc515ca3b2a3ac331546da4d9

Required accelerated gate: **8 passed / 1 failed / 0 skipped / 19 deselected / exit 1**. Deselected tests are outside the documented focused gate. `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`, `PERMISSION_SERVICE_MODE=enforce`.

Selected: C13 cross-item ten concurrent writes, sentinel audit rollback, Rule B 10→3→4→3, C13 consume_fifo fail-closed, established cross-item chain integrity, named reconciled sales test, three C13 sales regression checks.

Failure: `test_c13_2_rule_b_10_3_4_3_zero_unresolved_at_close`, line 400. After all ten units are accepted, `warehouse_in_transit.unresolved_discrepancies` still contains two entries (layer quantities 3 and 4). Expected `{}`. C15 now reaches real business behavior; its former raw-collection harness failures are no longer the failure.

**Full real-Mongo matrix NOT STARTED**, as required by C15 protocol.

### Assignment to Claude — C16 after AUTH correction handoff

Same PR #55. Fix the Rule B cumulative discrepancy closure in command/projection logic without weakening the test. Preserve canonical append-only stock ledger, tenant scope, permission enforcement and atomic audit. Prove 10→3→4→3 and 10→8→2, correct resolution facts, zero active unresolved state at completion, no early cost recognition, layer/value conservation and two identical rebuilds. Accelerated gate first; only if green run full real-Mongo matrix once. No skip/xfail/mock replacement or weakened assertions.

## #53 / #54 and current runtime

#53 has historical PASS and owner acceptance, not a fresh cumulative runtime PASS. Current main's changes since its base do not touch its nine changed files (source compatibility evidence only).

#54 still needs Krum's explicit feedback from comment 6109248800: least-privilege requester/approver/denied identities, navigation aligned with permissions, direct-URL denial, compact 390×844 list/create/detail/approve-reject screens. Structural UI changes require mockup review before implementation. Prepare this package after the bounded security/stock corrections.

Synology SMB marker freshly read: `0b53bcd5b977ee27de8d4cee363fed41dd897482`, deployed 2026-09-12; HTTP serves `main.01758b62.js`. Current container image identity still needs Docker/SSH evidence. Backup file `begwork_atlas_2026-10-25_0310.archive.gz` exists (800989 bytes); restore is NOT yet verified in this cycle. SSH documented user denied; SMB read works.

ГОТОВО: exact-head independent gates and reproducible failures above.
ОСТАВА: bounded fixes, re-review, integration candidate, full workflow/runtime acceptance and backup/rollback proof.
НА РЕД Е: CLAUDE #56 bounded corrections, then #55 C16; CODEX maintains integration matrix and release evidence.
БЛОКЕР: the three reproduced defects; authenticated Docker/SSH access for runtime identity and rollback validation.

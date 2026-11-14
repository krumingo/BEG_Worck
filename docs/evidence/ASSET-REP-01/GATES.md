# ASSET-REP-01 — gate counts (WIP, paused 2026-11-14)

main = origin/main 3863610; branch = claude/asset-rep-01.

| Gate | main | branch |
|---|---|---|
| R0 (6 files) | 814 passed | 814 passed |
| W0 | 16 failed / 1176 passed | 16 failed / 1176 passed (same failure set) |
| PAY-01 | 630 passed | 630 passed |
| SEC-01 | 30 passed | 30 passed |
| SEC-02 | 31 passed | 31 passed |
| PM-01 | 6 passed (pre-change) | 6 passed (matrix regenerated, FG-727) |
| A1 / A2B | unchanged | unchanged |
| A2C | 2197 accesses | 2209 accesses, 0 violations |
| ASSET-REP-01 suite | — | 110 passed (mongomock + real Mongo rs0) |
| Warehouse (real-Mongo env) | NOT DONE | NOT DONE |

Warehouse gate: not completed. The local Mongo rs0 died with EMFILE twice
(dropped-DB files accumulate); the last clean sequential run was stopped by
the pause. To finish: run Mongo with
`--setParameter minSnapshotHistoryWindowInSeconds=0`, then run
`tests/test_warehouse_*.py` with WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 on
main and the branch, one after the other, and compare the failure sets.
Also not done: updating the gates section of PR #94.

# CODEX — cumulative merged R0 regression gate

Application source: main `c0e34e1f3037010311d352683d519c3c9d7dcbfa` + exact PR #53 `e2a07ee66d5d6d59a95f6b17bb90996917790193`, matching RC integration commit `8768c82`.

**814 passed / 0 failed / 0 skipped / exit 0**, 172.83 seconds. JUnit breakdown: **391 real MongoDB cases, 391 mongomock cases, 32 other/unparameterized cases**. Six deprecation warnings; no skipped database gates.

| Suite | Passed |
|---|---:|
| R0-01 billing signature/idempotency/tenant checks | 83 |
| R0-02 items tenant filter | 69 |
| R0-03 roles/email authorization | 388 |
| R0-05 selected employees in payroll | 145 |
| R0-06 paid payroll locks/idempotency | 56 |
| R0-07 development reset guards | 73 |

Command: `python -m pytest tests/test_r0_01_billing_p0.py tests/test_r0_02_items_tenant_filter.py tests/test_r0_03_roles_email.py tests/test_r0_05_pay_run_selected_only.py tests/test_r0_06_paid_pay_run.py tests/test_r0_07_dev_reset.py --noconftest -q -p no:cacheprovider --junitxml=../../main-r0-results.xml`.

`W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27165/?replicaSet=rc20261025`, disposable MongoDB 7.0.43, synthetic data. No production data or credentials used. Log and JUnit are retained locally in `coordination/integrated-rc-2026-10-25/`.

Scope: confirms the six merged R0 fixes coexist with main and #53. Does not include the pending #56/#55/#54 corrections, browser end-to-end acceptance, current Synology container images, backup restoration or rollback. These remain open release gates.

ГОТОВО: cumulative R0 gate and #53 integration.
ОСТАВА: pending corrections, visible build identity, cumulative workflows and operational proof.
НА РЕД Е: Claude bounded corrections; Codex exact-head re-review when handed off.
БЛОКЕР: previously reproduced AUTH/warehouse findings and authenticated Synology command access.

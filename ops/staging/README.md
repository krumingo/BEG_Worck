# ST-01 — synthetic staging fixtures and scenario runner

Package: `docs/architecture/tasks/ST-01_STAGING_FIXTURES_SCENARIOS.md`. Source of the
scenarios: PR #64 `docs/evidence/INTEGRATED-RC-2026-10-25/02-release-gates.md`, steps 6–7
and the table "Krum's acceptance scenarios". FLOW-002, FLOW-040, FLOW-042, FLOW-050.

**Synthetic data only.** No production, no Synology production database, no real
person/company/email, no secrets in Git. Nothing here changes business code or
`ops/release/`.

| File | What it is |
|---|---|
| `st01_fixture.json` | tenants A and B, the 10 release-gate roles and their mapping to `users.role` / FLOW-002 `role_id` |
| `seed_synthetic.py` | idempotent seed of A and B into an explicitly named local/staging database |
| `scenarios/acceptance_scenarios.json` | the 12 scenarios of Krum's table: id, roles, FLOW, steps, expected result, `blocked` + reason where the function/screen is missing |
| `run_scenarios.py` | runs the API part against a running backend, writes `result.json` |

## Roles (per tenant)

`owner`, `admin`, `requester`, `approver`, `denied`, `warehousekeeper`, `technician`,
`accountant`, `viewer`, `driver`. Email: `st01.<role>@tenant-a.st01.test` /
`st01.<role>@tenant-b.st01.test` (reserved `.test` domain — nothing can be delivered).
All users of one run share the password you give the seed.

`requester` → SiteManager, `approver` → Admin and `denied` → Viewer are **staging
assumptions** (`"assumption": true` in the fixture): main has no own role for them and no
material-request approval. Krum confirms or changes the mapping.

## 1. Disposable local MongoDB

```bash
docker run -d --rm --name st01mongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all
docker exec st01mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
# Docker daemon down?  (nohup dockerd >/tmp/dockerd.log 2>&1 &)
```

## 2. Seed tenants A and B

```bash
cd backend
export ST01_SEED_PASSWORD='<choose one, ≥12 characters; never commit it>'   # or omit: a hidden prompt asks
PYTHONPATH=. python ../ops/staging/seed_synthetic.py \
    --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true' \
    --db st01_staging --system-db st01_staging_system --confirm-db st01_staging \
    --out /tmp/st01_seed_report.json
```

Run it again: the report shows `created` and `updated` all 0 and the database is unchanged.

Refusals (exit 2, nothing written): no URL; `--db`/`--system-db` is a production name
(`begwork*`, `$DB_NAME`, `$BEG_SYSTEM_DB` of this shell) — **even with `--allow-remote`**;
`--confirm-db` does not repeat `--db`; a non-local server without `--allow-remote`; a
database that already holds a non-synthetic user, organization or tenant; no password.

`--allow-remote` is only for an isolated staging server with its own database and storage
(release gate step 6). Never against production.

## 3. Start the backend on the staging databases

```bash
cd backend
MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' DB_NAME=st01_staging \
BEG_SYSTEM_DB=st01_staging_system JWT_SECRET='<local random value>' \
PYTHONPATH=. uvicorn server:app --host 127.0.0.1 --port 8001
```

No production credentials, no external email/billing keys in this shell.

## 4. Run the API scenarios

```bash
cd backend
ST01_SEED_PASSWORD='<same as the seed>' PYTHONPATH=. python ../ops/staging/run_scenarios.py \
    --base-url http://127.0.0.1:8001 --out /tmp/st01_result.json
```

Exit 0 = `result.json` written, no step failed, the backend answered and at least one step
passed; 1 = a step failed; 2 = refused (non-local `--base-url` without `--allow-remote`, or no
password); 3 = no evidence — the backend did not answer (any `UNREACHABLE` step) or no step
passed (ST-01-C01). `result.json` → `outcome` holds the same `exit_code`, a `status`
(`ok` / `failed` / `no_evidence`) and `reasons` (`STEP_FAILED`, `BACKEND_UNREACHABLE`,
`NOTHING_PASSED`). The runner **writes** synthetic
material requests into tenant A (tagged `ST-01 runner` in `notes`); rerunning adds more.

`result.json`: per scenario and per step `pass` / `fail` / `blocked`, with `reason_code`
and `reason`. A scenario is `pass` only if every step passed.

* `NO_CANONICAL_FUNCTION`, `NO_SCREEN` — missing on this build: the scenario cannot pass.
* `NO_RUNNER_CHECK` — no API check yet (e.g. payroll needs fixtures ST-01 does not create).
* `UI_NOT_RUN_BY_API_RUNNER` — browser step; the Bot session runs it from the same list.
* `UNREACHABLE` — the backend did not answer.

**Restart persistence** (S12): stop and start the backend, then run step 4 again — the
`request.create_persists_relogin` and isolation checks must still pass and the requests
of the first run must still be listed.

## 5. Tests

```bash
cd backend
PYTHONPATH=. pytest tests/test_st_01_staging_fixtures.py -v --noconftest
# with the real MongoDB of step 1:
W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
PYTHONPATH=. pytest tests/test_st_01_staging_fixtures.py -v --noconftest
```

## Clean-up

Drop the two databases (`st01_staging`, `st01_staging_system`) or stop the container
(`docker stop st01mongo`, started with `--rm`). Synthetic records carry
`synthetic_fixture: "st-01"`.

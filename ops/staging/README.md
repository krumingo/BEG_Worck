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

---

# ST-02 — isolated staging stack from a release bundle + deploy/rollback rehearsal

Package: `docs/architecture/tasks/ST-02_ISOLATED_STAGING_STACK.md` (approved by Krum, R9,
06.11.2026). Source: PR #64 `02-release-gates.md` steps 5–6 and "Exercise W0-09A deploy →
smoke → exact-image rollback in isolated staging". Evidence: `docs/evidence/ST-02/`.

**Never Synology production, never `/volume1/docker/begwork`, never production data or
secrets.** `ops/release/` and `ops/synology/` are not changed; production `layout.json` and
flags are not touched.

| File | What it is |
|---|---|
| `staging_up.py` | orchestrator: `up`, `deploy`, `rehearse`, `down` |
| `staging_deploy.sh` | release_deploy.sh logic on the isolated project; sources the release's own `tools/synology/lib.sh` |
| `deploy/docker-compose.staging.yml` | overlay on the **unchanged** production compose: own container names, port, network, MongoDB replica set, `ENV=staging`, flag parameter |
| `isolation_check.py` | proves from `docker compose config` that the merged model is isolated (runs in the verifier image, `--network none`) |
| `sandbox-base/prepare_sandbox_base_images.sh` | **cloud container only** — local base images so the production Dockerfiles build there (see below) |

## How it works

1. `release_build.py --environment staging --deployment-id staging-begwork` builds a bundle
   from the **exact commit** (Git objects; `--reachable-from origin/main` by default) and
   `release_verify.py bundle` verifies it.
2. The staging layout root (`--base`, any directory outside the Git work tree) gets:
   `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend` **byte-identical from the
   release artifact** (the verifier checks their sha256 against the manifest), the overlay, a
   synthetic `.env` (random `JWT_SECRET`, `st02_staging` databases, no SMTP/Stripe/LLM keys,
   mode 600), `staging.env` (project/port/flag — not secret) and `.st02-seed.env` (random ST-01
   password, mode 600). None of these leave the layout root.
3. Compose always runs as
   `docker compose -p begwork-staging -f docker-compose.yml -f docker-compose.staging.yml`.
   Containers `begwork-staging-{backend,frontend,mongo}`, network `begwork-staging_net`,
   volume `begwork-staging_mongo_data`, only `127.0.0.1:<port>` → frontend:80 published
   (MongoDB is not published). `staging_deploy.sh` refuses (exit 3) unless `isolation_check.py`
   passes on the merged model; `staging_up.py` runs the same check before it starts the
   staging MongoDB (and before every `deploy`), so a refusal starts nothing. Needs Docker
   Compose ≥ 2.24 (`ports: !override`).

   ST-02-C01 (audit ST02-1) — the check also refuses production targets:
   * backend `MONGO_URL` (required) and every other `mongodb…` value: only `mongodb://` to
     `mongo` / `<project>-mongo`:27017 — never `mongodb+srv`, an IP/LAN address, `localhost`,
     `host.docker.internal` or any other host (ST-02-C02 / FG-6: the former
     `ST02_ALLOWED_MONGO_HOSTS` allow-list is removed — a set value is refused — until Krum
     decides whether staging may use a MongoDB outside its own stack);
   * `DB_NAME` (required) / `BEG_SYSTEM_DB` = `begwork`, `begwork_beg`, `begwork_system` or any
     `begwork*` name;
   * any bind mount outside the staging root, under `/volume1/docker/begwork`, of `/` or of a
     Docker socket; a named volume that is external or not `<project>_*`;
   * `privileged`, `cap_add`, `devices`, an `unconfined`/disabled `security_opt`, host
     pid/ipc/uts/userns/cgroup, `network_mode` or a `host` network driver;
   * `ST02_HTTP_PORT` 80, 443, 8001, 8080, 27017 or below 1024.

   ST-02-C02 (FG-5) — and the URLs/keys the stack is reached and bootstrapped with:
   * backend `PUBLIC_URL` (required), every `CORS_ORIGINS` entry, the frontend build arg
     `REACT_APP_BACKEND_URL` (required when the frontend is built) and a frontend
     `REACT_APP_BACKEND_URL` environment value: only `http://127.0.0.1:<ST02_HTTP_PORT>` or
     `http://localhost:<ST02_HTTP_PORT>` — never a production, LAN or other URL, never `*`;
   * any `*BOOTSTRAP*` / `SEED_ADMIN*` environment key on any service
     (`PLATFORM_BOOTSTRAP_TOKEN`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`).
   Reasons name the key, never its value.
4. `staging_deploy.sh` = precheck (bundle verify with `--base`, isolation, recorded current,
   live tree, running images = recorded runtime, endpoints, gzip mongodump backup) → stage +
   tree identity → RC-01 `write_build_info.py --from-bundle` (the two `BUILD_INFO.json` are the
   only allowed extra files of the tree) → swap → `compose up --no-deps --build` → smoke →
   record. On a smoke failure: automatic rollback to the recorded tree **and the exact image IDs**
   (re-tag + `--no-build --force-recreate`, proved by `docker inspect .Image`) + post-rollback
   smoke → record `ROLLED_BACK` / `EXACT_IMAGE`, exit 1. MongoDB is not part of a release and is
   never recreated by deploy or rollback.
5. Staging differences from production, all explicit in the log and record:
   * container names / smoke URL / flag expectation of the manifest describe production; they
     are mapped to the staging project and to `--permission-mode` — **default `shadow` (R15,
     ST-02-C02)**; `enforce` or `off` only when passed explicitly (logged as
     `EXPLICIT --permission-mode`). The production expectation `off` stays in the immutable
     manifest; the flag is set by the overlay (`${ST02_PERMISSION_SERVICE_MODE:-shadow}`), not `.env`;
     `staging_deploy.sh` also falls back to `shadow` when `staging.env` has no mode;
   * FG-3: after the smoke `staging_deploy.sh` reads `PERMISSION_SERVICE_MODE` from the running
     backend; it must equal the staging parameter (unset or different = initial failure /
     automatic rollback). `staging-deployment.json` next to `record.json` keeps
     `manifest_expected` (production layout), `staging_parameter` (+ source: R15 default or
     explicit) and `observed_in_backend` side by side. Where a staging flag overlay should live in
     the Release Manifest itself is a decision for Krum (the manifest is not changed by ST-02);
   * FG-4: `--deployed-by` and `--approved-by` are **required** (plain identifiers, never
     `unknown`/`none`/`root`; refused before anything is built). The deployer is the manifest's
     `created_by` and the record's `actor`; the approver is a manifest approval
     `deploy:approved_by=<name>`; both are in `staging-deployment.json`. `staging_deploy.sh`
     refuses without `ST02_DEPLOYED_BY` / `ST02_APPROVED_BY`;
   * every service is rebuilt (each image carries its own `BUILD_INFO.json`), the manifest's
     `services_to_rebuild` is logged;
   * `--force-smoke-fail` adds `GET /api/st02-forced-smoke-failure` (404) to the deploy smoke —
     the controlled failure of the rehearsal. The post-rollback smoke never has it.
6. Seed and scenarios run **inside the deployed backend image** on `begwork-staging_net`
   (`seed_synthetic.py --allow-remote` against `mongo:27017`, `run_scenarios.py --base-url
   http://frontend --allow-remote`) — no Python dependencies on the host.

## Commands (cloud container)

```bash
# Docker daemon down?   (nohup dockerd >/tmp/dockerd.log 2>&1 &)
# Cloud container only: Docker Hub 429 + TLS re-termination + no Debian mirror -> local base images
bash ops/staging/sandbox-base/prepare_sandbox_base_images.sh --sandbox --ca /root/.ccr/ca-bundle.crt \
     --report /tmp/st02/sandbox-base.txt

# one exact commit: bundle, verify, deploy, /api/version == bundle, seed A/B, scenarios
python3 ops/staging/staging_up.py up --base /tmp/st02/base --commit origin/main \
     --port 18080 --deployed-by <who> --approved-by <who> \
     --verify-image mirror.gcr.io/library/python:3.11-slim        # shadow (R15 default)
# enforce/off only explicitly:  ... --permission-mode enforce

# next release on the running stack (optionally with the controlled smoke failure)
python3 ops/staging/staging_up.py deploy --base /tmp/st02/base --commit <ref> [--force-smoke-fail] \
     --deployed-by <who> --approved-by <who> --verify-image mirror.gcr.io/library/python:3.11-slim

# full rehearsal X -> X+1 (forced failure, exact-image rollback) -> X+1, evidence + summary.json
python3 ops/staging/staging_up.py rehearse --base /tmp/st02/run --from <X> --to <X+1> \
     --evidence /tmp/st02/evidence --deployed-by <who> --approved-by <who> --verify-image mirror.gcr.io/library/python:3.11-slim \
     --sandbox-base-report /tmp/st02/sandbox-base.txt

python3 ops/staging/staging_up.py down --base /tmp/st02/base [--volumes]
```

`--port` must be free on 127.0.0.1 and is never 8080. `--project` must start with
`begwork-staging`. Exit codes: `up`/`rehearse` 0 = all checks passed, 1 = a check failed,
2 = refused; `deploy` returns `staging_deploy.sh`'s code (0 deployed, 1 rolled back, 2 precheck,
3 isolation/usage, 4 rollback failed).

### Why the sandbox base images (cloud container only)

In the Claude Code cloud container Docker Hub answers 429, outbound TLS is re-terminated by
the session proxy (pip/yarn inside a build do not trust it) and Debian apt mirrors are not
reachable, so `apt-get install build-essential curl` in `Dockerfile.backend` cannot run.
`prepare_sandbox_base_images.sh` tags local images under the names the Dockerfiles use:
`python:3.11-slim` = official `python:3.11` (full image, toolchain and curl already installed)
+ session CA + `PIP_CERT` + a local `build-essential` metapackage that only depends on that
toolchain; `node:20-alpine` = official + session CA; `nginx:alpine` = official. The Dockerfiles
and compose stay byte-identical; the IDs and parents are in the evidence. **These are not the
images a Synology build uses** — the rehearsal proves deploy/smoke/exact-image-rollback
mechanics and build identity, not the production base images. The script refuses without
`--sandbox` and wherever `/volume1` exists.

## Later: Synology on a separate port (needs Krum's separate "да")

Not done by ST-02. Requirements before it may run on the NAS:

* own layout root, e.g. `/volume1/docker/begwork-staging` (never `/volume1/docker/begwork`);
  own `--port` (free on the NAS), own project/containers/network/volume — the isolation check
  refuses anything else;
* official base images (no sandbox script; it refuses on `/volume1`), `VERIFY_IMAGE` resolved
  locally as in §7.1 of `ops/release/README.md`;
* Docker Compose ≥ 2.24 invoked as `docker compose` (Synology's legacy `docker-compose` 1.x
  cannot merge `!override`);
* `staging_up.py` needs Python 3 on the machine that runs it (or run it from the release PC
  against a copied layout root); the NAS's thermal state checked before a heavy build;
* production containers, images, `.env` and `layout.json` read before and after, unchanged.

```bash
python3 ops/staging/staging_up.py up --base /volume1/docker/begwork-staging --commit <exact sha> --port <free port> \
     --deployed-by <who> --approved-by <who>
```

## Tests

```bash
cd backend
PYTHONPATH=. pytest tests/test_st_02_staging_stack.py -v --noconftest
```

Isolation rules (good model + 18 violations; ST-02-C01: 40 production-target cases, production
ports, the allow-list, the nine audit-probe mutations, the default `staging_up` root passing the
real `compose config`, and a hand-edited `.env`/overlay refused before anything starts), staging_up guards (production base, Git work tree,
project name, port 8080 / busy port, synthetic private `.env`, reuse refusal, secret scan),
overlay content, production layout/flags unchanged, the real `docker compose config` of
production compose + overlay passes and production compose alone is refused, staging_deploy.sh
refusals before any Docker call, sandbox script refusal, `ops/release`/`ops/synology` unchanged
versus `07da9ab`. ST-02-C02: default mode `shadow` (CLI, `prepare_base`, isolation check,
overlay, real `compose config`, `staging_deploy.sh` without a mode), `enforce` only explicit,
FG-3 observed-flag check/record, FG-4 deployer/approver refusals and `actor`, FG-5 URL and
bootstrap-key refusals, FG-6 allow-list refused.

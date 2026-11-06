# ST-02 — доказателства: изолиран staging stack + репетиция на deploy/rollback

> Пакет: `docs/architecture/tasks/ST-02_ISOLATED_STAGING_STACK.md` (одобрен, Крум, Р9, 06.11.2026)
> Изпълнено: 06.11.2026, в облачния контейнер на Claude Code. **Synology и production не са пипани.**
> Инструменти: `ops/staging/staging_up.py`, `ops/staging/staging_deploy.sh`, `ops/staging/deploy/docker-compose.staging.yml`,
> `ops/staging/isolation_check.py` (команди: `ops/staging/README.md`, раздел ST-02).
> Статус: доказателство за **механиката** на release → staging → rollback. Не е Implementation Gate PASS и не е production готовност.

## Резултат: `rehearsal PASS — 29/29 проверки` (`rehearsal-2026-11-06/summary.json`)

| | Commit | Release | release_sha256 |
|---|---|---|---|
| X (RC-01) | `1c01f6721170176553dd7c71c833fa54a9d89278` | `rel-20261106T152121Z-1c01f6721170` | `8d089441ecb85df863cb28c5c615899e08270b3185a10ea56732ae56374517d1` |
| X+1 (main, ST-01) | `07da9aba0711c0b0784bee8e58c5669ce81a93c1` | `rel-20261106T152231Z-07da9aba0711` | `0ff1f998636c828278fb2ebc313f68f2229a5b697c439d67b7b1a4a0c16cf498` |

Двата bundle-а са направени с `release_build.py --environment staging` от точния commit и проверени с
`release_verify.py bundle` (`bundle/release_verify.txt`). `manifest.json`, `SHA256SUMS`, `build_info.json`
в evidence са **байт-идентични** (`cmp`) с bundle-ите, а `sha256sum -c SHA256SUMS` минава за всички 19 файла.

### Последователност

```text
1. X:   bundle → verify → изолиран project begwork-staging → build → smoke → DEPLOYED
        /api/version = 1c01f672… = bundle; environment_label = staging; UI bundle-ът съдържа същия SHA
        ST-01 seed A/B → ST-01 сценарии (запис на синтетични заявки в фирма A)
2. X+1 с контролиран провал на smoke (GET /api/st02-forced-smoke-failure → 404):
        X+1 реално е build-нат и пуснат, /api/version по време на провала = 07da9aba… (X+1)
        → АВТОМАТИЧЕН ROLLBACK: точните image ID-та на X (re-tag + --no-build --force-recreate)
        → post-rollback smoke OK → record ROLLED_BACK / runtime_rollback EXACT_IMAGE, exit 1
        /api/version = X; бройките във всички колекции = същите; MongoDB контейнерът не е пресъздаден
3. X+1 без провал: DEPLOYED, /api/version = 07da9aba…, rollback target = X с неговите image ID-та,
        данните от X са налице, ST-01 сценариите минават отново
```

### Image ID-та (`summary.json` → `runtime_images`)

| Етап | backend | frontend |
|---|---|---|
| X | `sha256:ce7310d4752d…` | `sha256:cbdcb70a94e7…` |
| X+1, провален опит (върнат) | `sha256:cbf5e1a450d0…` | `sha256:d9ca9ae26c2b…` |
| след rollback | `sha256:ce7310d4752d…` (= X) | `sha256:cbdcb70a94e7…` (= X) |
| X+1, успешен deploy | `sha256:c606392a1719…` | `sha256:16a455b23483…` |

Пълните ID-та са в `summary.json` и в `record.json` на всяка операция. Наблюдение: провалилият се и
успешният X+1 са от **един и същи commit**, но с различни image ID-та (rebuild дава нов image) —
точно затова rollback-ът пуска записаните ID-та, а не прави rebuild.

### Build identity в UI (скрийншот)

`3-X+1-deploy/ui-login-desktop.png`, `3-X+1-deploy/ui-login-phone-390x844.png`: на входа пише
`v 07da9aba0711 STAGING`, `data-build-status="match"` (UI = API).

### ST-01 сценарии (честен резултат)

И при X, и при X+1: **12 сценария: 0 pass / 0 fail / 12 blocked; стъпки: 10 pass / 0 fail / 30 blocked**,
`outcome.exit_code = 0`. „blocked“ ≠ „pass“: липсваща канонична функция/екран, browser-стъпки (Бот сесия)
или стъпки без API проверка — виж `scenarios.json` (reason_code за всяка стъпка). Нито един сценарий не е
обявен за минал.

## Изолация (проверявана преди всяко compose действие, `isolation_check.py`)

* project `begwork-staging`; контейнери `begwork-staging-{backend,frontend,mongo}`;
* production `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend` — **байт-идентични** (verifier-ът
  сверява sha256 с manifest-а); разликите са само в overlay-а;
* публикуван е само `127.0.0.1:18080 → frontend:80` (никога 8080); MongoDB не е публикуван;
* собствена мрежа `begwork-staging_net`, собствен MongoDB replica set `rs0` на собствен volume;
* `ENV=staging`, `PERMISSION_SERVICE_MODE=enforce` (параметър; production очакването `off` в layout.json е непроменено);
* `.env` е синтетичен (случаен JWT secret, бази `st02_staging*`), без SMTP/Stripe/LLM ключове;
  secret scan на evidence: 0 съвпадения (JWT secret и seed парола).

## Отклонения / ограничения — прочети преди решение

1. **Base images в облачния контейнер не са официалните.** Docker Hub връща 429, TLS се прекриптира от proxy-то
   на сесията, а Debian apt огледалата са недостъпни — `apt-get install build-essential curl` от
   `Dockerfile.backend` не може да тръгне. `ops/staging/sandbox-base/prepare_sandbox_base_images.sh` прави
   локални `python:3.11-slim` (= официален `python:3.11` + CA на сесията + `build-essential` метапакет, който
   зависи само от вече инсталирания toolchain), `node:20-alpine` (+ CA), `nginx:alpine` (официален).
   ID-тата и родителите: `rehearsal-2026-11-06/sandbox-base-images.txt`. Dockerfile-ите и compose са същите.
   **Това доказва механиката deploy/smoke/rollback и build identity, не production base images.** На Synology
   скриптът отказва (`/volume1`) и се ползват официалните image-и.
2. Verifier-ът е официалният `python:3.11-slim` (от mirror.gcr.io), по image ID, `--network none`.
3. Staging rebuild-ва backend и frontend при всеки release (всеки image носи свой `BUILD_INFO.json`);
   manifest-ът на X+1 казва `services_to_rebuild = [backend]` — записано в лога.
4. Pre-deploy backup = `mongodump --gzip` на staging базата (не production backup/restore доказателство).
5. `ops/release/` и `ops/synology/` **не са променени** (тест срещу `07da9ab`). Synology deploy още не пише
   `BUILD_INFO.json` (известно от RC-01) — в staging това се прави в `staging_deploy.sh`.
6. Демо подсказката `admin@begwork.com / admin123` на входния екран е съществуващ продуктов текст (не е от ST-02)
   — в staging базата такъв потребител няма.

## Тестове — `tests-cbb8bdb.txt`

| Проверка | Резултат |
|---|---|
| A2C guard | 204 модула, 0 нарушения |
| A1 guard | 414 units, 0 нарушения |
| `tests/test_r0_0*.py` (с реален локален MongoDB) | 814 passed |
| W0 DB-free `tests/test_w0_*.py --noconftest` | 1085 passed / 15 failed / 50 skipped — същите 15 `test_w0_03e_legacy_routes` |
| `tests/test_st_02_staging_stack.py` (нов) | 50 passed |
| `tests/test_st_01_staging_fixtures.py` (+ реален MongoDB) | 31 passed |
| `ops/release/tests` (`test_artifact`, `test_deploy_tools`, `test_isolated_runner`) | 79 OK (1 skipped) |

## Какво следва (не е направено, изисква отделно „да“)

* Synology staging на отделен порт/директория (`ops/staging/README.md` → „Later: Synology“).
* Browser частта на сценариите (Бот сесия) срещу staging URL-а.
* Решение на Крум за mapping-а requester/approver/denied (ST-01 предположение) и за `PERMISSION_SERVICE_MODE` в production.

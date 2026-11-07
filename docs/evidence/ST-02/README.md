# ST-02 — доказателства: изолиран staging stack + репетиция на deploy/rollback

> Пакет: `docs/architecture/tasks/ST-02_ISOLATED_STAGING_STACK.md` (одобрен, Крум, Р9, 06.11.2026)
> Изпълнено: 06.11.2026, в облачния контейнер на Claude Code. **Synology и production не са пипани.**
> Инструменти: `ops/staging/staging_up.py`, `ops/staging/staging_deploy.sh`, `ops/staging/deploy/docker-compose.staging.yml`,
> `ops/staging/isolation_check.py` (команди: `ops/staging/README.md`, раздел ST-02).
> Статус: доказателство за **механиката** на release → staging → rollback. Не е Implementation Gate PASS и не е production готовност.

## ТЕКУЩА репетиция (ST-02-C03, Р25/Р26): `rehearsal PASS — 45/45 проверки` (`rehearsal-2026-11-06-c03/summary.json`)

> Пакет `docs/architecture/tasks/ST-02-C03_MANIFEST_FLAG_REHEARSAL.md` (Р15, Р25, Р26). Само в облачния контейнер,
> локален Docker; **Synology и production не са пипани.** `PERMISSION_SERVICE_MODE=shadow` (Р15 подразбиране),
> deployer `claude-st02-c03`, approver `krum` (`--deployed-by` / `--approved-by`; `actor` във всеки `record.json`).
> Тази репетиция **заменя** старата `rehearsal-2026-11-06/` (`enforce`, `actor: "unknown"`), която остава по-долу
> само като история — не се трие.

| | Commit | Release | release_sha256 | manifest `PERMISSION_SERVICE_MODE` |
|---|---|---|---|---|
| X (main, ST-01) | `07da9aba0711c0b0784bee8e58c5669ce81a93c1` | `rel-20261106T203417Z-07da9aba0711` | `c3fb6f37321b4296197434b8841d13a4a25d9b3f68c81b8ed12c352f123fe0a3` | `shadow` |
| X+1 (main, PM-01) | `8e3b1901938dd4f96b792cd9234b8763f6feefc5` | `rel-20261106T203722Z-8e3b1901938d` | `edda0055ba9528261669e18833ce65621522934822b74d221d3f33b78b044bff` | `shadow` |

**Р26 — режимът и Feature Flags snapshot са в Release Manifest-а на deployment-а.** Двата bundle-а са направени с
`release_build.py --environment staging --flag-override PERMISSION_SERVICE_MODE=shadow --flag-override-reason
"R15 staging default"`. В `manifest.json` → `release.feature_flags.PERMISSION_SERVICE_MODE`:
`expected: "shadow"`, `source: "deployment parameter (staging): R15 staging default; layout default off; set by the
deployment overlay, not .env"`. Схемата остава `beg.release-manifest/v1` (съществуващото поле `feature_flags`; без
override manifest-ите и `configuration.version` са същите; за production override-ът се отказва, а validator-ът
отхвърля такъв `source` в production manifest). `release_verify.py bundle` с инструментите **от самия commit**
(main, без Р26 промяната) приема manifest-ите → обратна съвместимост, доказана на живо.
`manifest.json`, `SHA256SUMS`, `build_info.json` в evidence са байт-идентични (`cmp`) с bundle-ите; `sha256sum -c` минава.

Сравнение **manifest ↔ staging ↔ работещ backend** (`staging-deployment.json` до всеки `record.json`:
`live_release_id`, `live_release_sha256`, `live_manifest_feature_flags`, `manifest_expected`, `staging_parameter`,
`observed_in_backend`, `observed_equals_parameter` / `observed_equals_manifest` / `manifest_equals_parameter`):

```text
1.  X:   manifest shadow = staging shadow (precheck) → build → smoke → backend shadow → DEPLOYED
         /api/version = 07da9aba…; ST-01 seed A/B; сценарии exit 0
2.  X+1 с контролиран провал на smoke → АВТОМАТИЧЕН ROLLBACK към точните image ID-та на X (EXACT_IMAGE)
         precheck: manifest на X+1 и на rollback target X = shadow; след rollback backend shadow = manifest на X
         данните (бройки по колекции) същите; MongoDB контейнерът не е пресъздаден
2b. Р26 отрицателна проба: bundle на X+1 с manifest enforce ≠ staging shadow
         → PRECHECK_FAILED, exit 2, „Release Manifest records PERMISSION_SERVICE_MODE=enforce, staging parameter is shadow“
         → нищо не е променено (current state и работещите image ID-та същите)
3.  X+1 без провал: DEPLOYED, /api/version = 8e3b1901…, backend shadow = manifest = parameter,
         rollback target = X с неговите image ID-та, данните от X налице, сценариите минават отново
```

Разминаване след smoke (backend ≠ manifest или ≠ параметъра) → `auto_rollback` (при initial — `INITIAL_FAILED`);
разминаване manifest ≠ параметъра → отказ в precheck преди каквато и да е промяна (тестове в
`backend/tests/test_st_02_staging_stack.py`, `test_c03_*`).

| Етап | backend | frontend |
|---|---|---|
| X | `sha256:4bc881d7d559…` | `sha256:831a8debb497…` |
| X+1, провален опит (върнат) | `sha256:9d4b4ee738c6…` | `sha256:4990d2f0edda…` |
| след rollback | `sha256:4bc881d7d559…` (= X) | `sha256:831a8debb497…` (= X) |
| X+1, успешен deploy | `sha256:34fa907cfdd8…` | `sha256:9fe29efb61e3…` |

ST-01 сценарии (X и X+1): 12 сценария 0 pass / 0 fail / 12 blocked; стъпки 10 pass / 0 fail / 30 blocked — както преди.
Base images: пак sandbox образите на облачния контейнер (`rehearsal-2026-11-06-c03/sandbox-base-images.txt`) —
доказва механиката, не production base images. Secret scan на evidence: 0 съвпадения.

**Р25:** staging ползва само собствения си MongoDB; `ST02_ALLOWED_MONGO_HOSTS` остава премахнат (зададена стойност → отказ;
FG-6 тестовете + `test_c03_r25_no_external_mongo_option_in_the_tools`).

**Известен козметичен дълг (не е поправян):** `staging_parameter_source` в `staging-deployment.json` пише
`explicit staging parameter`, защото `staging_up.py` винаги записва режима в `staging.env`; самият manifest носи
правилния източник `R15 staging default`.

Тестове на ST-02-C03: `tests-ST-02-C03.txt`.

---

# ИСТОРИЯ — първата репетиция (ST-02, заменена от ST-02-C03 по-горе; не се трие)

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
  **ST-02-C02 (Р15):** тази репетиция е пусната с тогавашното подразбиране `enforce`. От ST-02-C02
  подразбирането е `shadow`; `enforce` само с изричен `--permission-mode enforce`. Репетицията с `shadow`
  (и с новите `--deployed-by`/`--approved-by`, FG-3 `staging-deployment.json`) **още не е пусната отново** —
  `actor: "unknown"` в `record.json` по-долу е от старата версия (FG-4).
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
5. `ops/release/` и `ops/synology/` **не са променени** от ST-02 (тест срещу `07da9ab`; от ST-02-C03 — само Р26 файловете на `ops/release`, без deploy/rollback инструментите). Synology deploy още не пише
   `BUILD_INFO.json` (известно от RC-01) — в staging това се прави в `staging_deploy.sh`.
6. Демо подсказката `admin@begwork.com / admin123` на входния екран е съществуващ продуктов текст (не е от ST-02)
   — в staging базата такъв потребител няма.

## Тестове на първата репетиция — `tests-cbb8bdb.txt` (текущите: `tests-ST-02-C03.txt`)

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

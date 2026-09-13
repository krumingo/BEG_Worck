# W0-09A — Release foundation (exact-version release, deploy, rollback)

Статус: **foundation, не е пускан в production.** Първото използване на Synology изисква
отделно одобрение (виж §9 и §11).

Заменя ad-hoc процеса от W0-02 (`git archive` + ръчен `w0_02_deploy.sh` + ръчно копиран
`nginx.conf` + rollback по ръчно написан SHA).

## 1. Какво решава

| Проблем от W0-02 | Решение |
|---|---|
| `git archive` на release PC-то прилага `core.autocrlf=true` (system gitconfig) → 702 от 1043 файла на `0b53bcd5` не са байт-идентични | артефактът се пише директно от Git обекти (`ls-tree` + `cat-file --batch`), идентичността се доказва независимо: Git tree hash се преизчислява от самия архив и от разпънатата директория |
| `nginx.conf` е скрит build вход (не е в Git, копира се на ръка) | tracked в корена на репото, байт-идентичен с live копието (blob `b87dfcda80a6fbcfd0fa18bd36a220b77a425607`); build-ът пада при всеки нетракнат `COPY` вход |
| версията в production не е записана никъде | `release-state/current.env`, `DEPLOYED_COMMIT`, `DEPLOYED_VERSION.txt` извън `repo/` + manifest + deployment record |
| rollback по ръчно написан SHA | `release_rollback.sh` връща **записания** rollback target след проверка на неговото дърво |
| rollback с rebuild от mutable base image tag-ове дава друг runtime | при deploy се записват immutable image ID-тата на контейнерите; rollback пуска точно тях отново (re-tag + recreate без build) и го доказва по image ID |
| ръчни проверки, без доказателства | evidence директория за всяка операция в `release-state/history/` |

## 2. Компоненти

| Файл | Роля |
|---|---|
| `release_build.py` | прави bundle от commit (на release PC-то) |
| `release_verify.py` | проверява bundle, дърво, manifest, record; редактира secrets от логове. Stdlib only |
| `beg_release/gitobj.py` | артефакт от Git обекти, tree hash, безопасно разпъване, mode probe |
| `beg_release/inputs.py` | inventory на build входовете, compose drift, `services_to_rebuild` |
| `beg_release/manifest.py` | `beg.release-manifest/v1`, `beg.deployment-record/v1`, validator, shell-safe plan |
| `release_manifest.schema.json` | JSON Schema (parity-тест срещу validator-а) |
| `synology/layout.json` | декларация на текущия Synology layout (services, containers, env key names, flags, smoke) |
| `synology/release_adopt.sh` | еднократно: записва работещия production като current release (без container действия) |
| `synology/release_deploy.sh` | precheck → stage → swap → rebuild само нужното → smoke → auto-rollback → record |
| `synology/release_rollback.sh` | самостоятелен rollback към записания target (dry run по подразбиране) |
| `synology/release_retention.sh` | почистване на стари дървета и (с `--images`) стари release image tag-ове (dry run по подразбиране) |
| `synology/lib.sh` | общи функции |
| `tests/` | unit тестове + изолиран Synology runner (виж §12); не влизат в bundle-а |

## 3. Release Manifest `beg.release-manifest/v1`

`manifest.json` = `{schema, release, release_sha256}`. Обектът `release` е immutable след build;
`release_sha256` = sha256 на canonical JSON (sorted keys, compact). Всяка редакция без нов
build се хваща (`manifest was modified`). Validator-ът отхвърля непознати/липсващи ключове,
грешни формати и secret-подобни стойности/ключове.

| Поле | Съдържание |
|---|---|
| `release_id` | `rel-<UTC build time>-<първите 12 hex на commit>` |
| `app` | `repository`, `commit` (40 hex), `tree` (40 hex), `commit_time`, `reachable_from` (ref, от който production commit-ът трябва да е достижим; `null` само извън production) |
| `artifact` | `format=tar-pax-git-objects-v1`, `sha256`, `size_bytes`, `file_count`, `tree_verified=true`, `legacy_extras` (само за baseline/adoption) |
| `environment` | development / test / staging / production |
| `deployment` | `id` (`synology-begwork`), `layout`, `tenant_scope` (`deployment-wide` днес) |
| `schema_version` | `app_schema_version` (null — няма app schema version още), `migrations`: `declared`, `policy=NOT_RUN_BY_DEFAULT`, `approval_ref` (задължителен при declared) |
| `configuration` | `version` (sha256 на layout файлове + env key names + flags + build args + smoke), `layout_source_commit`, `layout_files` (sha256), `required_env_keys` (само имена), `build_args` |
| `feature_flags` | очаквани стойности (`PERMISSION_SERVICE_MODE: off`) — никога стойности от `.env` |
| `entitlements` | `NOT_IMPLEMENTED` (W0-08), без snapshot |
| `build` | tool версия, python, git, per-service inventory (`base_images`, `copy_sources`, `input_file_count`, `fingerprint`), `unpinned_base_images`, `rebuild_reason`, `tools_source_commit`, `tools` (sha256 на всеки tool файл в bundle-а) |
| `services_to_rebuild` | само services с променен input fingerprint (всички, ако няма previous) |
| `previous`, `rollback_target` | `{release_id, commit, tree, release_sha256}` на текущия release; rollback target = previous |
| `approvals` | `[{type: merge/review/deploy/validation, ref}]`; production изисква `deploy` |
| `smoke` | base URL, health path, HTTP paths, containers, timeouts, log service |
| `created_at`, `created_by` | UTC време и actor |

Какво се е случило при deploy/rollback не е в manifest-а, а в **deployment record**
(`beg.deployment-record/v1`, `history/<stamp>-<action>-<pid>/record.json`): action, status
(`ADOPTED/DEPLOYED/PRECHECK_FAILED/ROLLED_BACK/ROLLBACK_DONE/ROLLBACK_FAILED`), release,
`release_sha256`, commit, tree, environment, started/finished, actor, previous и rollback
target, `services_rebuilt`, `runtime_images` (service → immutable image ID), `runtime_rollback`
(`NOT_APPLICABLE` / `EXACT_IMAGE` / `SOURCE_REBUILD` / `FAILED`), `verifier_image` (image ID на
verifier-а), `migrations=NOT_RUN`, verification, smoke, failure (санитизиран), evidence dir.

## 4. Идентичност на артефакта

1. `git ls-tree -r -z --full-tree <commit>` → път, mode, blob. Symlink/submodule → отказ.
2. `git cat-file --batch` → суровите байтове; всеки blob се проверява срещу своя id.
3. Детерминистичен PAX tar: сортирани пътища, `mtime=commit_time`, uid/gid 0, mode 0644/0755.
4. Архивът се чете обратно и Git tree hash-ът се изчислява от него → трябва да е `app.tree`.
5. На NAS-а: разпъване в нова `repo.staging-<release>` директория и повторно изчисляване на tree hash-а от диска.

Exec битове: проверяват се от диска, когато файловата система ги пази (chmod probe в evidence
директорията). Където не ги пази (NTFS на Windows тестове, ACL-mapped share), пътищата и
байтовете се проверяват пак изцяло, а exec битовете се вземат от артефакта на същия release —
и това се пише изрично в detail реда.

## 4a. Runtime images — точен runtime rollback

Source дървото е точно, но image-ът, който реално върви, зависи и от mutable base image tag-ове
(`python:3.11-slim`, `node:20-alpine`, `nginx:alpine`) и от `apt`/`pip`/`yarn` по време на build.
Rebuild на същия commit може да даде различен image, затова rollback **не прави rebuild**, когато
може да пусне записания image:

1. Adoption и всеки успешен deploy записват за всеки service `docker inspect .Image` (immutable
   `sha256:` ID) и `.Config.Image` (compose image ref) в `current.env` (`RUNTIME_IMAGES`,
   `RUNTIME_REFS`), в record-а и в `DEPLOYED_VERSION.txt`.
2. Тези image-и се tag-ват `beg-release/<service>:<release_id>`, за да не ги изчисти
   dangling-image prune, докато са rollback target.
3. Precheck на deploy/rollback: работещите image ID-та трябва да са точно записаните (иначе
   `runtime drift`, exit 2, нищо не е променено).
4. Rollback (auto и standalone): записаният image се re-tag-ва като compose ref-а и контейнерът се
   пресъздава с `up -d --no-deps --no-build --force-recreate <service>`; след това
   `docker inspect .Image` трябва да е точно записаното ID → `runtime_rollback=EXACT_IMAGE`.
5. Ако записаният image липсва локално: auto-rollback (услугата е паднала) прави rebuild от вече
   провереното дърво и записва `SOURCE_REBUILD` („source-exact, NOT runtime-exact“);
   standalone rollback **отказва** (exit 2), освен с изрично `--allow-source-rebuild`.
6. Services извън rebuild-а трябва да продължат да въртят записания си image (проверява се в smoke).

Всички `compose up` са с `--no-deps` — deploy/rollback на един service не пресъздава и не
rebuild-ва неговите зависимости.

Verifier-ът: `VERIFY_IMAGE` (по подразбиране `python:3.11-slim`) се резолвира веднъж до image ID и
всички `docker run` на операцията са по това ID (никога pull); ID-то е в record-а. По желание
`VERIFY_IMAGE_ID=sha256:…` го pin-ва (при разлика — exit 3).

Mounts на verifier контейнера: `--network none --pull never --read-only --security-opt
no-new-privileges`; bundle, `$BASE` и hint bundle са **read-only**; писане има само в
evidence директорията на операцията (`/evid`) и, по време на deploy, в staging директорията
(`/stage`). Staged дървото е `repo.staging-<release>/tree` и се мести като `repo`.

## 5. Build входове

- Layout файловете (`docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`) идват от
  `ops/synology/deploy/` в Git и трябва да са байт-идентични с тези в `/volume1/docker/begwork`.
- Compose се сравнява с `layout.json` (services, container names, context, dockerfile, build args) → drift = отказ.
- Всеки `COPY`/`ADD` източник трябва да е в release дървото → иначе `missing build input`.
  Wildcard, JSON-form и remote източници → отказ (fail closed).
- Versioned `.env` файл → отказ.
- `nginx.conf` е tracked в корена (`COPY nginx.conf` във `Dockerfile.frontend`), същите байтове
  като ръчното копие → frontend fingerprint-ът не се променя → **няма frontend rebuild и няма
  промяна в nginx поведението** (доказано с тест, §12).

## 6. Bundle

```
<release_id>/
  artifact.tar      exact Git tree
  manifest.json
  SHA256SUMS        artifact.tar, manifest.json, tools/**
  tools/            release_verify.py, beg_release/, synology/*.sh, layout.json (от tools commit-а)
```

## 7. Runbook

### 7.1 Build (release PC, Windows или Linux)

```bash
git fetch origin
python ops/release/release_build.py --commit origin/main --environment production \
  --deployment-id synology-begwork --previous-manifest <manifest.json на текущия release> \
  --approval deploy:<BEG_Work_AI Issue #1 comment> --out <dir>
python ops/release/release_verify.py bundle --bundle <dir>/<release_id>
```

Build-ът пада (exit 2), ако commit-ът не е достижим от `origin/main`, previous не е предшественик,
има нетракнат вход, compose drift или manifest-ът е невалиден. `core.autocrlf` няма значение.

Копирай целия bundle в `\\bekr\docker\begwork\releases\<release_id>\` (извън `repo/`).
Bundle-ите на current и previous release **не се трият** — те са mode hint и доказателство.

Предусловие на NAS-а: verifier-ът върви в `python:3.11-slim` с `--pull never --network none`
(image-ът вече е там, защото backend се билдва от него): `sudo docker image inspect python:3.11-slim`.

### 7.2 Еднократно adoption на работещия production

Live production е `0b53bcd5` + ръчно копиран `nginx.conf`. Baseline manifest (tools от W0-09A commit-а):

```bash
python ops/release/release_build.py --commit 0b53bcd5b977ee27de8d4cee363fed41dd897482 \
  --environment production --deployment-id synology-begwork --no-previous --baseline \
  --legacy-extra nginx.conf=b87dfcda80a6fbcfd0fa18bd36a220b77a425607 \
  --tools-ref <W0-09A merge commit> --approval deploy:<ref> --out <dir>
```

По желание и предишният anchor като rollback target (`repo_before_48e4a108a3a3e2821798e0a5ad1b40b5615e8fb0`):
baseline за `48e4a108…` със същия `--legacy-extra`. Дали anchor-ът е точно това дърво
(включително exec битове) **не е проверено** — adoption го проверява и отказва, ако не е.

```bash
sudo bash /volume1/docker/begwork/releases/<baseline>/tools/synology/release_adopt.sh \
  [--previous-bundle /volume1/docker/begwork/releases/<baseline-48e4a108> \
   --previous-tree-dir repo_before_48e4a108a3a3e2821798e0a5ad1b40b5615e8fb0]
```

Adoption проверява bundle-а, layout файловете, имената на `.env` ключовете, flag-а и че `repo/`
е точно baseline дървото + `nginx.conf`; контейнерите трябва да вървят, за да се запишат image
ID-тата им. Пише `release-state/`, `DEPLOYED_COMMIT`, `DEPLOYED_VERSION.txt` (презаписва маркерите
от W0-02 със същия commit) и tag-ва текущите image-и `beg-release/<service>:<baseline release>`.
Без container действия. Runtime image-ите на adopt-нат previous release са неизвестни → rollback
към него е възможен само с `--allow-source-rebuild` (не е runtime-exact).

### 7.3 Deploy

```bash
sudo bash /volume1/docker/begwork/releases/<release_id>/tools/synology/release_deploy.sh
```

| Фаза | Какво | При провал |
|---|---|---|
| A PRECHECK (read-only) | SHA256SUMS; manifest; tools; artifact sha256 + tree identity; без `.env` в артефакта; **без declared migrations**; layout файлове; `.env` съществува и има нужните имена; flag липсва или е равен на очакването; deployment/environment; target ≠ current; **manifest.previous = записания current** (иначе version mismatch); live `repo/` = записаното дърво; свободни имена за anchor/staging; контейнерите вървят; **работещите image ID-та = записания runtime**; endpoint-ите отговарят 2xx/3xx; валиден backup (`gzip -t`) | exit 2, нищо не е променено, record `PRECHECK_FAILED` |
| B DEPLOY | stage extract + tree identity; tag на текущите runtime image-и; base image ID-та в evidence; `repo` → `repo.rollback-<current>`; staging → `repo`; tree identity на новото `repo`; `docker-compose up -d --no-deps --build <само services_to_rebuild>` | auto-rollback |
| C SMOKE | health 200 в срок; всички контейнери running; rebuilt контейнерите са пресъздадени след началото на deploy-а (иначе version mismatch); останалите въртят записания си image; restart count не расте за `restart_sample_sec`; HTTP paths 2xx/3xx (5xx = провал); backend лог без startup/config грешки (само брой, без съдържание); flag в контейнера липсва или е равен | auto-rollback |
| D RECORD | нови runtime image ID-та (+ tag `beg-release/<service>:<release>`); стар rollback tree → `release-state/retired/`; `previous.env` = стария current (с неговия runtime); `current.env` = новия; manifests; маркери; record `DEPLOYED` | — |

Auto-rollback: провалилото се дърво → `repo.failed-<release>-<UTC>`, anchor обратно в `repo`,
tree identity, **записаните image-и отново (без build, проверено по image ID)** за засегнатите
services, post-rollback smoke, state остава непроменен, record `ROLLED_BACK` с
`runtime_rollback=EXACT_IMAGE` (или `SOURCE_REBUILD`, ако image-ът липсва), exit 1. Ако и rollback-ът се провали: exit 4, record `ROLLBACK_FAILED`,
двете дървета остават.

Когато няма променени service входове (напр. docs-only), дървото се сменя без rebuild/restart.

### 7.4 Rollback

```bash
sudo bash <bundle>/tools/synology/release_rollback.sh                               # dry run: план
sudo bash <bundle>/tools/synology/release_rollback.sh --yes                         # изпълнение
sudo bash <bundle>/tools/synology/release_rollback.sh --yes --allow-source-rebuild  # само ако image-ът липсва
```

Target-ът е `release-state/previous.env` (никога ръчен SHA). Преди каквото и да е движение
дървото на target-а и live `repo/` се проверяват срещу записаните tree hash-ове (tampered/missing
→ exit 2, нищо не е променено), работещите image-и = записания runtime. За всеки service,
чийто записан image се различава, се пуска image-ът на target-а (без build, проверено по ID);
smoke; `current.env` = target; `previous.env` се консумира (в evidence); record `ROLLBACK_DONE`
с `runtime_rollback`.
При провал: exit 4 и отпечатани ръчни стъпки за roll-forward.

### 7.5 Retention

```bash
sudo bash <bundle>/tools/synology/release_retention.sh [--keep N] [--images]          # dry run
sudo bash <bundle>/tools/synology/release_retention.sh --keep 1 --images --apply
```

Политика:
- **никога** не се трие: `repo`, current `TREE_DIR`, записаният rollback target (`previous.env` `TREE_DIR`), bundles, `release-state/manifests`, `release-state/history` (evidence);
- кандидати: `repo.rollback-*`, `repo.failed-*`, `repo.rolledback-*`, `repo_before_*`, `repo.staging-*` (само без активен lock), `release-state/retired/*`;
- пазят се най-новите N кандидата (по подразбиране 1); останалите се трият само с `--apply`;
- `--images`: tag-овете `beg-release/<service>:<release>` на други releases се махат с `docker rmi <tag>` (без `-f`, без prune); tag-овете на current и previous се пазят винаги. Без `--images` Docker не се пипа.

Exit кодове на скриптовете: 0 OK, 1 rolled back, 2 отказ/precheck (без промяна), 3 usage/lock/layout, 4 rollback провал.

## 8. State и evidence на NAS-а

```
/volume1/docker/begwork/
  repo/                      активното дърво (build context)
  repo.rollback-<release>/   rollback anchor
  DEPLOYED_COMMIT            commit (извън repo/)
  DEPLOYED_VERSION.txt       deployed, release_id, release_sha256, previous, rollback_dir, runtime_images, state, at
  releases/<release_id>/     bundles
  release-state/
    DEPLOYMENT  current.env  previous.env  current.json  previous.json
    manifests/<release_id>.json
    history/<UTC>-<action>-<pid>/   <action>.log, verify.json, stage.json, plan.env, base-images.txt, compose-*.log, record.json
    retired/  lock/
```

`current.env`/`previous.env`/`plan.env` се четат със строг `KEY=VALUE` parser (без `source`/`eval`).

## 9. Secrets

- `.env` не се копира, не се чете в изхода и не влиза в bundle/manifest/record.
- Verifier-ът чете `.env` само в памет: имена на ключове, сравнение на flag стойност, редакция.
- Изходът на `docker-compose` се пише в evidence само след редакция срещу стойностите от `.env`.
- Лог сканирането отчита само брой съвпадения. Flag стойности се сравняват, не се печатат.
- Тестовете слагат sentinel secrets в `.env`, compose изхода и контейнерния лог и проверяват, че не се появяват в stdout, state, evidence и маркери.

## 10. Migrations

Никога не се пускат от W0-09A. Manifest с declared migrations не минава deploy precheck;
migration е отделна одобрена стъпка (Approval + backup + restore proof — W0-10A).

## 11. Съвместимост с текущия Synology deployment

- Същият compose layout (`./repo` като build context, `../Dockerfile.*`), същите container names и порт 8080. Layout файловете в Git са байт-идентични с тези на share-а.
- Rollback е rename в същата файлова система — като W0-02 anchor-а.
- `nginx.conf` на корена на layout-а остава неизползван (както и досега); frontend-ът чете `repo/nginx.conf`.
- `PERMISSION_SERVICE_MODE` не се пипа; очакването е `off` (липсващ ключ = app default off).
- Нощният backup се пуска от `repo/ops/synology/atlas_backup.sh` и пише в `/volume1/docker/begwork/backups` (извън `repo/`). След swap се изпълнява копието от новия release; release, който променя този скрипт, променя backup-а — това не е build вход и трябва да се вижда в review-то.
- Първият W0-09A deploy след adoption на `0b53bcd5` е с `services_to_rebuild = []` (доказано на реалното репо) → смяна на дървото без restart на контейнери.
- Разделът „Обновяване на кода после“ в `ops/synology/deploy/INSTRUKCII.md` (`git pull`) не е валиден — `repo/` не е git checkout.

Изолираната Synology проверка (§12) пуска инструментите на самия NAS, без да пипа production; резултатите ѝ са в HANDOFF-а за съответния SHA, не в този файл.

## 12. Тестове

```bash
cd ops/release/tests
python -m unittest -v test_artifact test_deploy_tools
```

`test_artifact` (Python): байт-идентичност на реалния HEAD; CRLF регресия (синтетично репо с
`core.autocrlf=true`, `git archive` negative control, реалният `0b53bcd5`: `git archive` дава
несъвпадащи файлове, builder-ът дава tree `4c3e8855…`); exec битове; възпроизводимост;
липсващ вход / нетракнат `nginx.conf` / compose drift / versioned `.env`; грешен/недостижим
commit, previous не е предшественик, друга среда; tree mismatch; tampered checksum, resealed
артефакт, manifest без rehash, липсващ ред в SHA256SUMS, tampered tool, опасни tar членове;
manifest/record validation; schema parity; shell-safe plan; без secrets.

`test_deploy_tools` (bash + `tests/fakes/`: docker с image/tag store, compose с build и
`--no-build`, curl; истински verifier): adoption с runtime image-и; успешен deploy (само backend,
маркери, record, tag-ове, редактиран compose изход); docs-only без rebuild; docker verifier режим
(image ID, read-only base, писане само в `/evid`/`/stage`); липсващ/непин-нат verifier image;
precheck провали без мутация (вкл. runtime drift); 8 auto-rollback тригера, всеки с проверка, че
върви записаният image без втори build; auto-rollback без image → `SOURCE_REBUILD`; standalone
rollback (dry run, exact image, tampered target, липсващ target, runtime drift, липсващ image →
отказ / `--allow-source-rebuild`); втори deploy; retention на дървета и image tag-ове.

`test_isolated_runner`: сглобява пакета за Synology от working tree-то и пуска
`run_isolated.sh` в `sim` режим (без Docker) — проверява самия runner.

### Изолирана Synology проверка

```bash
python ops/release/tests/synology/make_package.py --out <dir>        # от commit-нат, чист tree
# копирай <dir>/w009a-isolated-<sha12> в \\bekr\docker\w009a-isolated\
sudo bash /volume1/docker/w009a-isolated/w009a-isolated-<sha12>/runner/run_isolated.sh
```

Phase 1: всеки сценарий има временна `BEGWORK_BASE` в `runs/<stamp>/`, истинските инструменти от
bundle-ите, фалшиви docker/compose/curl за контейнери/image-и/HTTP и **истинския verifier** в
`python:3.11-slim` (по image ID, read-only mounts) върху файловата система на NAS-а: mode probe,
adoption, deploy, precheck без мутация, всички auto-rollback тригери, standalone rollback,
retention, secret-leak scan. Phase 2: истински Docker + docker-compose върху мини layout със
собствени container имена (`w009a-rt-*`) — deploy, standalone rollback и auto-rollback на
crash-ващ release, с доказателство по image ID. Production (`/volume1/docker/begwork`, неговите
контейнери, image-и, `.env` metadata) се чете преди и след и трябва да е непроменен. Phase 2 махa
само собствените си контейнери (`compose down`); image-ите остават (без `rmi`/prune).

## 13. Известни ограничения / рискове

- Няма криптографски подпис на bundle-а — SHA256SUMS е integrity, не authenticity.
- Base images не са pinned (`python:3.11-slim`, `node:20-alpine`, `nginx:alpine`) → **нов** build на същия commit може да даде различен image. Rollback не зависи от това, докато записаният image съществува (`EXACT_IMAGE`); `SOURCE_REBUILD` е изрично отбелязан като не runtime-exact. Base image ID-тата преди всеки build са в `base-images.txt`.
- Image tag-овете `beg-release/*` задържат стари image-и до `release_retention.sh --images --apply`.
- Compose няма `healthcheck`; restart loop се хваща чрез sample на restart count.
- Backup-ът се проверява само с `gzip -t`; restore никога не е доказан (W0-10A).
- Rollback връща кода, не данните.
- Entitlements snapshot липсва (W0-08); tenant scope е deployment-wide.

# ST-02 — изолиран staging stack от release bundle + репетиция на deploy/rollback

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Без merge/deploy без „да“. **Не пипа Synology/production.**
> Изпълнител: Claude Code · Одит · Бот · Codex: не (инфраструктура/тестова среда)
> Източник: PR #64 `02-release-gates.md`, стъпки 5–6 и „Exercise W0-09A deploy → smoke → exact-image rollback in isolated staging“.
> База: `main` @ `07da9ab` (вече има RC-01 build identity и ST-01 тестови данни) · Клон `claude/st-02-staging-stack` → Draft PR
> Нови файлове основно в `ops/staging/`; `ops/release/` само ако е нужна малка, обоснована промяна (с тест).

## Обхват
1. `ops/staging/staging_up.sh` (или `.py`):
   - прави bundle с `ops/release/release_build.py` от **точен commit** (по подразбиране текущия `main`), проверява го с `release_verify.py`;
   - пуска **същите** `ops/synology/deploy/Dockerfile.*` и compose в отделен compose project (`begwork-staging`), отделна мрежа, отделни портове (проверка, че са свободни), собствен MongoDB **replica set** и празен volume; без production credentials, без реален SMTP/Stripe;
   - `ENV=staging`, `PERMISSION_SERVICE_MODE` като параметър (по подразбиране `enforce` за staging; production не се пипа);
   - сийдва ST-01 тестовите фирми A/B и пуска `ops/staging/run_scenarios.py`;
   - записва manifest, SHA256SUMS, image ID-та и `/api/version` (трябва да е същият SHA като bundle-а).
2. **Репетиция на rollback:** deploy на commit X → smoke → deploy на X+1 с **принудително провален smoke** → автоматичен rollback към **точните image ID-та** на X; синтетичните записи от X остават. Записва старите/новите image ID и резултата. Ползва логиката на `synology/release_deploy.sh`/`release_rollback.sh`, адаптирана за изолирания project, без да се променя production поведението им.
3. `ops/staging/README.md` с точните команди за пускане в облачния контейнер и (по-късно) на Synology на отделен порт.

## Забранено
Synology, production, реални данни/тайни, промяна на production `layout.json`/флагове, merge, deploy.

## Тестове и доказателства
- Скриптът минава в този контейнер (docker е наличен; при спрян daemon: `(nohup dockerd >/tmp/dockerd.log 2>&1 &)`).
- `docs/evidence/ST-02/`: изход от staging_up (SHA в API = bundle), резултат от сценариите, rollback репетиция с image ID-та.
- Всички `tests/test_r0_0*.py`, W0 DB-free 1085/15/50, A2C/A1 0, `ops/release` тестове зелени.

## Предаване
Draft PR `ST-02 — isolated staging stack and rollback rehearsal`, `HANDOFF ST-02`, съобщение `ST-02 DONE pr=<n> head=<sha> tests=<summary>`.

# ST-02-C01 — staging изолацията трябва да отказва production цели

> Статус: **ОДОБРЕНА** (Крум, 06.11.2026, Р9). Без merge/deploy, без Synology.
> PR: #67, клон `claude/st-02-staging-stack`, head `55ef71d` · Одит: `docs/audit/AUDIT_LOG.md` @ `claude/audit-log` 320da34
## Находка ST02-1 (medium, доказана)
`isolation_check` пуска staging backend, ако `MONGO_URL` сочи production cluster или LAN IP, `DB_NAME=begwork`, bind на `/volume1/docker/begwork`, `docker.sock` или `privileged`. Пътят по подразбиране (`staging_up`) е безопасен, но проверката трябва да спира всичко това.
## Поправка
`isolation_check` отказва (ненулев код, ясна причина, нищо не се стартира) при: нелокален/LAN/`mongodb+srv` MONGO_URL (освен изрично разрешен staging host от конфигурация), DB_NAME = production име или `begwork*`, bind към production пътища, `docker.sock`, `privileged`, host network, production портове. Тест за всеки случай + тест, че пътят по подразбиране минава.
## Проверки
ST-02 тестове, `ops/release` тестове, R0 тестове, W0 1085/15/50, A2C/A1 0. Коментар `HANDOFF ST-02-C01` в PR #67; съобщение `ST-02-C01 DONE head=<sha> tests=<summary>`.

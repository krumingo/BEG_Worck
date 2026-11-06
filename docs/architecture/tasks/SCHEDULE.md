# График за изпълнение — живо копие

> Поддържа: Claude Scheduler сесия (клон `claude/schedule`). Оркестраторът: Claude (основна сесия). Решения: само Крум.
> Правила (Р9, 06.11.2026): една задача = един PR. Merge и deploy **само** с изрично „да“ от Крум. Claude програмира (до 3 паралелни сесии по отделни области), Claude Audit одитира, Claude Bot тества в браузър. **Codex само за пари и сигурност.**
> Ред на изпълнение (от PR #64, `02-release-gates.md`):

| # | Задача | PR / клон | Отговорен | Статус | Блокира |
|---|---|---|---|---|---|
| 1 | AUTH-01: RC-AUTH-01/02/03 | #56 @ `dae097b` | Codex (re-review) | чака Codex | — |
| 2 | Склад 5C: C16/C17 | #55 @ `2bb81fc` | Codex (re-review) | чака Codex | — |
| 3 | RC-01 Build identity | `claude/rc-01-build-identity` | Claude Code → Audit → Bot | **в работа** | — |
| 3a | 5C-C18 склад: tenant guard + C13.4 + merge на main | #55 | Claude Code → Audit → Codex (пари/сигурност) | **в работа** | — |
| 3b | ST-01 staging тестови данни + сценарии | `claude/st-01-staging-fixtures` | Claude Code → Audit → Bot | **в работа** | — |
| 4 | #53 Control Center: свързване с текущия main + тест на ролите | #53 / #64 | Codex | чака | — |
| 5 | #54 Заявки: mockup → права → телефон 390×844 | #54 | Крум (бележки), после Claude | чака Крум | бележки на Крум |
| 6 | Staging артефакт (W0-09A) + `PERMISSION_SERVICE_MODE` решение | — | Claude + Codex | не е започнато | 1–4 |
| 7 | Изолиран staging + сценариите на Крум | — | Codex / Bot | не е започнато | 6, достъп до NAS |
| 8 | Backup restore proof + rollback на точния image | — | Codex | блокирано | root/Docker достъп на Synology (одобрение от Крум) |
| 9 | Решение на Крум за deploy | — | Крум | — | 1–8 |

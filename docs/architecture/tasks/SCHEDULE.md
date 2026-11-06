# График за изпълнение — живо копие

> Поддържа: Claude Scheduler сесия (клон `claude/schedule`). Оркестраторът: Claude (основна сесия). Решения: само Крум.
> Правила: една задача = един PR. Merge и deploy **само** с изрично „да“ от Крум. Codex е независимият review.
> Ред на изпълнение (от PR #64, `02-release-gates.md`):

| # | Задача | PR / клон | Отговорен | Статус | Блокира |
|---|---|---|---|---|---|
| 1 | AUTH-01: RC-AUTH-01/02/03 | #56 @ `dae097b` | Codex (re-review) | чака Codex | — |
| 2 | Склад 5C: C16/C17 | #55 @ `2bb81fc` | Codex (re-review) | чака Codex | — |
| 3 | RC-01 Build identity | `claude/rc-01-build-identity` | Claude Code | **в работа** | — |
| 4 | #53 Control Center: свързване с текущия main + тест на ролите | #53 / #64 | Codex | чака | — |
| 5 | #54 Заявки: mockup → права → телефон 390×844 | #54 | Крум (бележки), после Claude | чака Крум | бележки на Крум |
| 6 | Staging артефакт (W0-09A) + `PERMISSION_SERVICE_MODE` решение | — | Claude + Codex | не е започнато | 1–4 |
| 7 | Изолиран staging + сценариите на Крум | — | Codex / Bot | не е започнато | 6, достъп до NAS |
| 8 | Backup restore proof + rollback на точния image | — | Codex | блокирано | root/Docker достъп на Synology (одобрение от Крум) |
| 9 | Решение на Крум за deploy | — | Крум | — | 1–8 |

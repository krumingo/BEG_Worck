# FLOW GUARD — покритие на main по FLOW

Бавен преглед: по един FLOW на проход. Легенда:

- ✅ — изпълнено;
- ⚠️ — частично;
- ❌ — противоречи на канона;
- ⏳ — още не е изпълнено (не е разминаване, ако вълната не е стигнала дотам).

## Проход 1 — FLOW-002 (Потребители / роли / права / достъп)

- main @ `07da9ab`, 06.11.2026.
- Прочетени: `backend/app/permissions/*`, `backend/app/routes/labor_smr.py`, `backend/app/deps/modules.py`.
- Проба: `probes/fg1_labor_entries_probe.py`.

| Правило в FLOW-002 | Състояние | Къде / бележка |
|---|---|---|
| RoleAssignment с person/role/scope/module/permissions/valid_from/valid_to/status/created_by/approved_by | ✅ | `permissions/sync.py:196-205`, `:265-272`; `max_amount` покрива „сума“ |
| Обхват: фирма/обект/модул/сума/статус/период | ⚠️ | Има scope, module, max_amount и validity (`permissions/service.py:102-138`). Няма ограничение по подобект, тип документ, конкретен запис/версия и статус |
| „По-ограниченото право има предимство“ | ❌ SUSPECTED | `permissions/service.py:160-176` използва правилото на обединението: позволява, ако **кое да е** назначение позволява. Няма запис-ограничение (deny), който да бие по-широко назначение → **FG-12** |
| Основни роли (канонични) | ⚠️ | `permissions/catalog.py:90-125`: 11 канонични роли. Technician/Viewer остават като LEGACY без канонично съответствие. Няма „Подизпълнителски контакт“ и „Клиент“ — правилно, те са външни (ExternalPrincipal) |
| Permission Service е авторитетен | ⚠️ | По подразбиране `PERMISSION_SERVICE_MODE=off` (`permissions/deps.py:51`). Решават legacy проверките. Р15: staging = `shadow` |
| Критични действия: изрични права + AuditEvent | ⚠️ | Промените на права се одитират (`permissions/audit_hooks.py:59-68`). Трудът (основа за заплата) няма право и AuditEvent → **FG-1** |
| Директен URL не заобикаля правата | ❌ PROVEN | `POST/GET /api/labor-entries`: само модулен gate M2, без роля и без членство → **FG-1** |
| Двустепенно одобрение (двама различни) | ⏳ | Няма общ механизъм в `permissions/`. Зависи от W0-07 Approval runtime |
| ExternalPrincipal / AccessGrant / magic link | ⏳ | Не е изпълнено. Няма и клиентски портал в кода, така че условието „преди FLOW-046“ не е нарушено |
| AI вижда ≤ потребителя | ✅ (каталог) | `catalog.py:123`: `ai_service` без действия. AI tool проверките не са прегледани в този проход |
| Крум вижда роли/временни/рискови права | ⏳ | Не е прегледан UI |
| Промяна на права без AuditEvent е забранена | ✅ | `audit_hooks.py:59` `permission.role_assignment.*`. R0-03 (main) — смяна на роля с AuditEvent |

Следващ FLOW в бавния преглед: **FLOW-006** (плащания).

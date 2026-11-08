# ACT-01 — сливане на main `0750d75` в #77

Клон `claude/act-01-client-act-from-offer` (#77) @ `2cc1147` + `origin/main` @ `0750d75` („Merge PR #71“; преди това #80 и #69). Сливането е с merge commit **`5d75736`** (родители `2cc1147`, `0750d75`), без rebase и без force-push. Регенерираните доказателства са в следващия commit. Merge в main няма — той чака „да“ от Крум.

## Принцип

И трите страни остават:
* **#69 (SEC-01)** — правата за запис на пари (`require_money_write`, Р14), Idempotency-Key (Р29), суми в цели центове (F-69-04);
* **#71 (SEC-02)** — четенията по Р20: не-финансовите роли не виждат пари в четците на актове (Р20-1 → 403);
* **#77 (ACT-01)** — правилата на акта: цена и договорено к-во от офертата, остатък, без двойно актуване, версии, кумулативно закръгляне, `expected_total`.

**Една зависимост за права на route** — тази на main (иначе в enforce отказът се одитира два пъти); тялото на handler-а — от ACT-01.

## Конфликти и как са решени

| Файл | Какво се сблъска | Решение |
|---|---|---|
| `backend/app/routes/revenue_expense.py` (6 места) | import-ите и dependency-тата на `GET /client-acts`, `GET /client-acts/{id}`, `PUT /client-acts/{id}`, `POST /client-acts/{id}/confirm`, `POST /client-acts/from-offer/{offer_id}`. От main: `require_finance_read` (#71) и `require_money_write` (#69) върху стария handler. От #77: собствената `require_client_act_right` върху новия handler (услугата `app/services/client_acts.py`) | **Правата от main, тялото от ACT-01.** confirm → `require_money_write("revenue.client_act_confirm.execute")` (#69); list / detail / PUT / from-offer → `require_finance_read(...)` със същите action имена (#71). Двата нови маршрута на ACT-01 минават на същите механизми: `POST /client-acts` → `require_money_write("revenue.client_act.create")`, `GET /client-acts/remaining/{project_id}` → `require_finance_read("finance.client_act_remaining.read")` (Р20-1). Изрязването на пари (FG-122) ползва `money_values_visible` на #71. `app/permissions/client_act_write.py` на ACT-01 е премахнат (дълг D9 затворен). |
| `backend/tests/test_pm_01_permission_matrix.py` | `ENFORCE_EXTRA_WRITES` | **Списъкът на main** (SEC-01, SEC-02, TASK 5C) **+ `POST /api/client-acts`** — единственият ACT-01 ред, който main няма (confirm / PUT / from-offer вече са там). |
| `docs/evidence/PM-01/matrix.csv`, `run_meta.json` | генерирани файлове | **Регенерирани само с harness-а на PM-01** (`tests/test_pm_01_permission_matrix.py --harness`, реален Mongo rs0) върху сливането: 768 route-а, 18 432 клетки, 3 режима, 0 пропуснати. |

## Последици от сливането (без текстов конфликт, но нужни, за да важат правилата и на трите)

| Къде | Какво и защо |
|---|---|
| `backend/app/permissions/catalog.py` | `revenue.client_act.create` е вписан в `ACTIONS` и в `MONEY_WRITE_ACTIONS` на SEC-01 (Accountant го получава оттам; Owner/Admin — с пълния набор). Страничният блок `CLIENT_ACT_ACTIONS` на ACT-01 е махнат: confirm е в `MONEY_WRITE_ACTIONS_C02` (#69), PUT / from-offer / remaining — във `FINANCE_READ_ACTIONS` от регистъра на #71. Тестът на SEC-01 (`test_the_catalog_r16_and_money_grants`) иска точно това. |
| `backend/app/permissions/finance_read.py` | регистърът на SEC-02 (`FINANCE_READS`): + `GET /api/client-acts/remaining/{project_id}` (Р20-1, клиентски цени). Тестът на SEC-02 иска всеки route с `require_finance_read` да е в регистъра. |
| `backend/tests/test_sec_01_c01_all_money_writes.py` | `GUARDED_ROUTES` + `("POST", "/api/client-acts"): "revenue.client_act.create"` — новият money write е проверен от същия тест (покритие разширено, нищо не е отслабено). |
| `backend/tests/test_sec_01_c02_flow_guard_money_writes.py` | Пробата `client_act_confirm` на #69 беше върху акт със свободен ред без офертен ред и без тяло. По ACT-01 такъв акт не се потвърждава (422 `OFFER_LINE_REQUIRED`, 422 `EXPECTED_VALUES_REQUIRED`). **Фикстурата е заменена с акт, какъвто ACT-01 създава** (приета оферта на обекта, ред с офертната цена 10.00, ДДС 20 %) и тялото носи видените стойности (FG-142); колекциите на акта са създадени предварително (както пробата прави за останалите). **Нито едно assertion не е променено**: финанси 200 + запис, не-финанси 403 без запис, чужд tenant 404 без запис, еднакво в трите режима. Доказателството `docs/evidence/SEC-01-C02/results.json` е регенерирано с harness-а му. |
| `backend/app/services/client_acts.py` | Правилото на #69 за цели центове (`money_value(..., places=2)`) върху `expected_total` / `expected_line_values` на потвърждението — 422 при по-фина сума, без тихо закръгляне. |
| `backend/tests/test_act_01_client_act_from_offer.py` | Четците: при #71 не-финансовите роли получават **403** на `GET /client-acts[/{id}]` (по-строго от „само количества“ на ACT-01) — тестът проверява 403, никакви пари в тялото и нищо записано; финансите — пълните суми. |
| `docs/evidence/SEC-02/results.json`, `docs/evidence/ACT-01/results.json` | регенерирани с harness-ите си върху сливането. |

Без конфликт, проверени:
* `docs/architecture/W0-03E-A1_INVENTORY.md` — изходът на `backend/scripts/w0_03e_a1_inventory.py` е изцяло в документа (без промяна).
* `docs/architecture/W0-03E-A2B_INVENTORY.md` — `backend/scripts/w0_03e_a2b_inventory.py` дава байтово същия файл (без промяна).
* `frontend/src/pages/ProjectOperationsPage.js` — сля се автоматично; двете страни са налице (ключовете на #69 за `/subcontractor-payments`, `/overhead-snapshots` и ключът + потвърждението с видени стойности на ACT-01); компилира се (esbuild JSX). `yarn test` не е пуснат — в тази среда няма `node_modules`.

## PM-01 спрямо main `0750d75`

Само маршрутите на клиентския акт:

| Route | Клетки | Какво |
|---|---|---|
| `GET /api/client-acts/remaining/{project_id}` | 24 нови | финанси 200, другите 403 (Р20-1) |
| `POST /api/client-acts` | 24 | не-финанси 404 → **403** (в enforce с denial AuditEvent), финанси 404 → **428** без ключ; нищо не е записано |
| `PUT /api/client-acts/{act_id}`, `POST /api/client-acts/from-offer/{offer_id}`, `POST /api/client-acts/{act_id}/confirm` | по 9 | финанси 404 → **428** без ключ (не-финансовите вече бяха 403 от #69 / #71) |

## Gates

Виж `test_summary.txt` в тази папка.

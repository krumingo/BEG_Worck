# OFF-01 — Заменена версия на оферта не може да се приеме; изпратена оферта не се изтрива

> Дата: 07.11.2026 · Източник: FLOW Guard pass 13, FG-129 (high, SUSPECTED), FG-130 (medium, SUSPECTED) · Wave 1 Commercial Core
> Канон: FLOW-003 (BUSINESS LOCK) „Версии“, „Одобрение“, „Какво НЕ трябва да позволява“ (стара/заменена версия да бъде одобрена след публикуване на нова; invalidation на approval при нова версия); FLOW-002 (клиентски линк / magic link); CLAUDE.md §2.9 (без hard delete), §8 (клиентско одобрение = Approval към exact version), §14.
> Клон: нов от main `d226c49`, `claude/off-01-offer-version-accept`. Draft PR към main. Без merge/deploy.

## Проблеми (main @ d226c49) — първо ДОКАЖИ с тест на реален Mongo
1. **FG-129:** `POST /offers/{id}/new-version` (offers.py:~440) само вмъква новата версия; старата Sent версия остава приемлива през `/accept` (~:354) И през публичния `/offers/review/{token}/respond` (~:1140). `resolve_review_token` игнорира версията → клиент приема заменена цена/обхват по стар линк.
2. **FG-130:** `DELETE /offers/{id}` (~:447–460) hard-delete-ва Sent/Rejected оферти, които вече са изпратени на клиента.

## Какво да се направи
1. При нова версия старата се маркира `superseded` (със `superseded_by`, кой, кога) в същата транзакция като вмъкването на новата; всички отворени review токени на старата версия се анулират (не се трият — статус revoked + причина). Конкурентно: две нови версии от една → само една печели (CAS по версия/статус).
2. `/accept` и публичният `/respond` приемат само ДЕЙСТВАЩАТА версия; токенът е обвързан с exact offer id + version; заменена → 409 `OFFER_VERSION_SUPERSEDED` (публичният отговор — неутрален текст на български, без вътрешни данни). Проверката е в същата транзакция като приемането.
3. Приемането пише canonical AuditEvent с exact version и evidence (метод на одобрение по FLOW-003: подписан PDF / верифициран email / magic link).
4. `DELETE /offers/{id}`: само Draft, който никога не е изпращан, може да се изтрие (или архивира); Sent/Accepted/Rejected/Superseded → 409 `OFFER_IN_USE` → вместо това „анулиране“ (status cancelled + причина + AuditEvent). Без hard delete на използвани записи.
5. Права: без разширяване; провери PM-01 матрицата; регенерирай само с harness, с `W0_03_REAL_MONGO_URL` (0 skipped).
6. Idempotency-Key на new-version / accept / respond / cancel (Р29, където има пари или договорно действие).

## Тестове (real Mongo, off/shadow/enforce)
- Червени на main: приемане на стара версия през /accept и през публичния линк; delete на Sent оферта.
- Позитивни: приемане на действащата версия; анулиране на Sent.
- Конкурентни: new-version ∥ accept на старата ×10 → никога двете; две new-version ×10 → една.
- Gates: R0 814; W0 същите 15; A2C/A1 0; PM-01 реален.

## Предаване
HANDOFF в PR, доказателства в `docs/evidence/OFF-01/`, дългове. Съобщение: `OFF-01 DONE pr=… head=… tests=…`.

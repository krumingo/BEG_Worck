# SEC-03 — Премахване на остатъците от Emergent и затваряне на слабите места от SEC-SCAN

> Дата: 09.11.2026 · Одобрено от Крум (Р75, Р76) · Източник: `docs/security/SEC_SCAN_2026-11-09.md` (клон claude/sec-scan)
> Канон: CLAUDE.md §2, §3, §10 (AI правила), §14, §16 (без secrets в Git/frontend/logs). Клон от актуалния main: `claude/sec-03-emergent-removal`. Draft PR. Без merge/deploy.

## A. Frontend (H-1, M-4)
1. `frontend/public/index.html`: махни `emergent-main.js`, блока с `debug-monitor.js` и Tailwind CDN за iframe, бадж „Made with Emergent“, meta description „A product of emergent.sh“; заглавие `BEG_Work`. Никакъв външен `<script>` освен собствения bundle. (PostHog вече е вграден от #88 — ако #88 още не е в main, не пипай PostHog тук.)
2. Ако нещо в `frontend/src` зависи от тези скриптове (visual edits), премахни зависимостта без да чупиш build.
3. CSP + `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` в nginx конфигурацията за production (`ops/synology/deploy/...`) **и** като `<meta http-equiv>` където е приложимо. CSP: `default-src 'self'`; script-src само `'self'`; style/font за Google Fonts ако се ползват; connect-src `'self'` + PostHog хоста само ако ключ е конфигуриран. Тествай, че приложението работи (Playwright 35/35).

## B. Backend
4. **M-1:** `backend/app/deps/auth.py` — без fallback `dev-secret-key`. Ако `JWT_SECRET` липсва или е < 32 байта → приложението отказва да стартира (fail-closed), освен в изричен тестов режим. Тест.
5. **M-3:** `POST /api/internal/run-reminder-jobs` (attendance.py:897) — изисква служебен ключ от env (constant-time сравнение) или Platform Admin; иначе 401/403. Работи per-tenant през Tenant Guard, не cross-tenant без изрично разрешение. AuditEvent. Тест forbidden/positive.
6. **M-5:** `PayRunPrintView.js`, `UnitQrBlock.js` — без `document.write` с непочистени стойности; escape на всички имена/текстове (или DOM API/React рендер). Тест с име `<img src=x onerror=…>`.

## C. AI директно към Anthropic (Р76, M-2)
7. Махни `emergentintegrations` и `EMERGENT_LLM_KEY` от кода (5 файла: ai_proposal.py, smr_analysis.py, assets_batch_intake.py, assets_ai_intake.py + тестовете).
8. Един адаптер `app/services/ai_provider.py` над официалния `anthropic` Python SDK, **закрепена версия** в requirements.txt. Ключ само от env/secret store (`ANTHROPIC_API_KEY`), моделът от конфигурация (`ANTHROPIC_MODEL`) — **без вграден ключ или модел в кода**; без ключ/модел → AI функциите връщат ясно „AI не е настроен“ и ръчните процеси продължават (CLAUDE.md §10: AI не е single point of failure).
9. Запази правилата от §10: AI не записва директно, само чернови → потвърждение → права; никакви ключове/лични данни в логове; изпращай към модела само нужните полета (без ЕГН/IBAN). Снимки — оригиналът се пази преди обработка (§4).
10. Feature flag `ai_enabled` per tenant, по подразбиране изключен до тест на живо от Крум.

## Тестове и gates
Positive + forbidden за всяка точка; Playwright без външни скриптове (запис на всички заявки — нито една към emergent.sh); стартиране без JWT_SECRET → отказ; AI без ключ → „не е настроен“, без 500. Gates на реална Mongo: R0 814, W0 (същите legacy), PAY 630, SEC-01 30, SEC-02 31, PM-01 6/0 (regen с harness), A2C/A1 0, warehouse 1121, frontend jest + build + Playwright.

## Предаване
HANDOFF в PR, `docs/evidence/SEC-03/`. Съобщение: `SEC-03 DONE pr=… head=… tests=…`. Без merge.

# PWA-01 — Инсталируема PWA обвивка (стъпка 1 от Modern Field Experience)

> Дата: 08.11.2026 · Одобрено от Крум (стъпка 1 сега, стъпка 2 = PWA-02 offline queue отделно) · Канон: docs/architecture/MODERN_FIELD_EXPERIENCE_2026-08-04.md §5, §14, §15; CLAUDE.md §2, §3, §9, §16 (без secrets във frontend). Wave 2 ядро, но само обвивка — без бизнес промени.
> Клон: нов от актуалния main, `claude/pwa-01-installable-shell`. Draft PR към main. Без merge/deploy.

## Цел
BEG_Work се инсталира на телефон/компютър от браузъра (Android Chrome, iOS Safari „Add to Home Screen“, desktop Chrome/Edge), отваря се на цял екран с икона, отваря обвивката и без интернет, показва ясно „Без връзка“ и „Има нова версия“. Един общ codebase, без native app.

## Обхват
1. **Web App Manifest** (`frontend/public/manifest.webmanifest`): name „BEG_Work“, short_name, start_url `/`, scope `/`, display `standalone`, theme/background цветове от текущата тема, lang `bg`, икони 192/512 + maskable + apple-touch-icon (генерирай от текущото лого — каската; без нови бранд решения), shortcuts по желание (Табло, Заявки) само ако маршрутите съществуват. Свържи в `public/index.html` (+ apple meta тагове за iOS).
2. **Service worker** (Workbox чрез CRA/craco или ръчно; без нова тежка зависимост, ако може):
   - precache само статичните build файлове (app shell: html/js/css/шрифтове/икони);
   - navigation fallback към index.html, за да се отваря офлайн;
   - **API (`/api/*`) НИКОГА не се кешира** (NetworkOnly) — пари, лични данни, чужди tenant-и не се пазят на устройството (CLAUDE.md §3, Р20, Р48);
   - качени файлове/снимки от API — също не се кешират в тази стъпка;
   - версия на SW = build идентичност (RC-01 build info), за да се вижда коя версия е кеширана.
3. **Регистрация и обновяване:** регистрирай SW само в production build; при нова версия — лента „Има нова версия — Обнови“ (skipWaiting след потвърждение), без тихо презареждане по време на въвеждане.
4. **Офлайн индикатор:** глобална лента „Без връзка — промените няма да се запишат“ при `navigator.onLine=false` / неуспешен fetch; формите показват ясна грешка вместо да висят. (Опашка за офлайн запис е PWA-02 — тук НЕ.)
5. **Инсталиране:** бутон „Инсталирай приложението“ в профил/меню, когато браузърът предлага `beforeinstallprompt`; за iOS — кратка инструкция „Сподели → Добави към началния екран“.
6. **Изход/смяна на tenant:** при logout и при смяна на активния tenant — изчисти всички Cache Storage кешове, свързани с API (ако има), sessionStorage/localStorage с данни на tenant-а; SW не пази токени.
7. **Сигурност:** без secrets във frontend; SW scope само `/`; CSP/headers не се отслабват; SW не прихваща чужд origin.

## Извън обхвата (PWA-02)
Офлайн запис и синхронизация (присъствие, отчети, снимки, задачи), криптирано локално хранилище, idempotent sync, конфликти по D-12, push известия, background sync.

## Тестове
- Jest/unit: регистрацията е само в production; update лентата; offline лентата; изчистване при logout/смяна на tenant.
- Playwright (Chromium, без инсталиране на нов браузър): manifest валиден и свързан; SW активен; офлайн (context.setOffline) → обвивката се отваря, лента „Без връзка“; `/api/*` отговорите НЕ са в Cache Storage (проверка на всички кешове); след logout кешовете с данни са празни.
- Lighthouse PWA проверка (installable) ако е налична офлайн; иначе ръчен списък в evidence.
- Gates: frontend тестове + build; backend gates непроменени (R0 814, SEC-01 30, PM-01 6 без промени в матрицата — няма backend промяна).

## Предаване
HANDOFF в PR, `docs/evidence/PWA-01/` (скрийншоти телефон/десктоп, Lighthouse/ръчен списък), дългове D1…. Съобщение: `PWA-01 DONE pr=… head=… tests=…`. Без merge.

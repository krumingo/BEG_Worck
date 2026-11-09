# PWA-01 — Инсталируема PWA обвивка: доказателства

Задача: `docs/architecture/tasks/PWA-01_INSTALLABLE_SHELL.md` (клон `claude/happy-meitner-bmcnel`).
Канон: MODERN_FIELD_EXPERIENCE_2026-08-04 §5, §14, §15; CLAUDE.md §2, §3, §9, §16.
Засегнати FLOW-ове: няма бизнес FLOW промяна — само frontend обвивка. Няма backend промяна.

## Как е получено
- Production build (`craco build`) с `REACT_APP_BACKEND_URL=` (API на същия origin, както при nginx) и
  `REACT_APP_BUILD_SHA` = commit-а на кода (виж `cache-check.json` → `service_worker.version`).
- `e2e/server.js` сервира build-а като `nginx.conf` (SPA fallback; `/api`, `/uploads` → mock backend).
- `e2e/run.js` — Playwright с предварително инсталирания Chromium (без `playwright install`).
  Резултат: **35 PASS / 0 FAIL** (след D1 fix), пълни данни в `cache-check.json`.
- Скрийншоти: deviceScaleFactor 2; телефон 390×844 (Android UA и iOS Safari UA), десктоп 1366×820.

```
node docs/evidence/PWA-01/e2e/server.js frontend/build 4173 &
node docs/evidence/PWA-01/e2e/run.js http://localhost:4173 docs/evidence/PWA-01
```

## Скрийншоти
| Файл | Какво показва |
|---|---|
| `desktop-login.png` | вход, десктоп |
| `desktop-dashboard.png` | бутон „Инсталирай приложението“ в страничното меню |
| `desktop-offline.png` | офлайн презареждане → обвивката се отваря от кеша + лента „Без връзка“ |
| `desktop-update-available.png` | „Има нова версия — По-късно / Обнови“ (без тихо презареждане) |
| `phone-login.png`, `phone-dashboard.png` | телефон |
| `phone-menu-install.png` | бутон „Инсталирай приложението“ в мобилното меню |
| `phone-offline.png` | телефон офлайн + лента „Без връзка“ |
| `phone-ios-install-steps.png` | iOS: „Сподели → Добави към началния екран“ |

## Проверка на кешовете (`cache-check.json`)
- След вход и заявки към `/api/payments`, `/api/auth/me`, `/uploads/...`: единственият кеш е
  `bw-shell-<sha12>-<hash>` и съдържа само `index.html`, `static/js|css`, manifest и икони.
  **0 записа за `/api`, `/uploads`, `/ws`.**
- Офлайн `fetch('/api/payments')` → network error (не се отговаря от кеш).
- Logout: localStorage остава само `lang` (allow-list); sessionStorage празен; изкуствено
  поставеният `bw-legacy-api` кеш е изтрит; остава само shell кешът.
- Смяна на tenant (сесия на org-b върху устройство, държало org-a): чернова/sessionStorage/кеш на
  org-a изтрити, входът на org-b запазен, маркер `bw_pwa_tenant = org-b`.
- Chromium `Page.getInstallabilityErrors` → `[]` (инсталируемо).

## Ръчен списък (вместо Lighthouse — няма офлайн Lighthouse в средата)
- [x] manifest: name, short_name, start_url `/`, scope `/`, display `standalone`, lang `bg`, theme/background
- [x] икони 192/512 `any` + 192/512 `maskable` + apple-touch-icon 180 (от текущото лого — каската)
- [x] SW регистриран само в production build, scope `/`
- [x] SW версия = RC-01 build SHA (съобщение `GET_VERSION`)
- [x] офлайн навигация (вкл. deep link `/tech/tools`) → index.html от кеша
- [x] `/api/*`, `/uploads/*`, `/ws`, не-GET и чужд origin — не се прихващат и не се пазят
- [x] update лента; activate само след „Обнови“
- [x] офлайн лента при `navigator.onLine=false` и при network-level грешка на API
- [x] install бутон (`beforeinstallprompt`) + iOS инструкция
- [x] изчистване при logout, при 401 и при смяна на tenant
- [ ] **Реално устройство** (Android Chrome „Инсталирай“, iOS Safari „Добави към началния екран“) — за Крум

## Дългове (не са поправени — изискват решение на Крум)
- **D1 — ПОПРАВЕН (одобрено от Крум, commit `e571b06`).** Преди: `AuthContext.fetchUser` триеше
  `bw_token` при всяка грешка → офлайн презареждане изхвърляше потребителя. Сега сесията се прекратява
  само при 401 (и 403 от `/auth/me`); при мрежова грешка/5xx токенът остава, потребителят се възстановява
  от `bw_user` (без кеширане на `/api`), показва се лентата „Без връзка“. `logout()` изчаква изчистването
  на кешовете. Доказателство red → green в `d1/`:
  `jest-red-a05167a.log` (5 ✕), `playwright-red-a05167a.log` (3 FAIL) → `jest-green.log`,
  `playwright-green.log` (35/35). Остатък: `PlatformAuthProvider` (платформен админ) има същия catch-all —
  извън обхвата, не е пипан.
- **D2 — няма UI за смяна на tenant.** Смяната се засича по `organization.id` при вход/зареждане на
  сесия (маркер `bw_pwa_tenant`). Бъдещият превключвател трябва да вика `noteActiveTenant` /
  `clearTenantLocalData` от `src/lib/pwa/clearLocalData.js`.
- **D3 — формите.** Глобалната лента „Без връзка“ се показва при неуспешна заявка; съобщенията на
  отделните форми не са пипани, а axios няма timeout — при „полу-връзка“ заявката още чака.
  Предложение: общ timeout/съобщение в PWA-02.
- **D4 — shortcut „Заявки“ не е добавен:** етикетът сочи към различни маршрути според ролята
  (`/my-day` за терен, `/review-reports` за офис). Добавен е само „Табло“ (`/`).
- **D5 — външни скриптове в `index.html`** (Emergent badge/debug, PostHog, Google Fonts) — не се
  кешират и офлайн просто не се зареждат. Не са пипани (извън обхвата); за решение по privacy/CSP.
- **D6 — `nginx.conf`:** препоръчително `Cache-Control: no-cache` за `/service-worker.js` и
  `/manifest.webmanifest` при deploy. Не е променяно (без infra/deploy промяна в PWA-01).
- **D7 — `<title>`** е сменен от „Emergent | Fullstack App“ на „BEG_Work“ (името на продукта, нужно за
  прозореца на инсталираното приложение). Цветовете са от текущата тъмна тема (`#070b13`, амбър лого).

## R68 — PostHog без запис на екрана (Крум, 09.11.2026, FG-317)
Промяна (commit `01f9029`):
- Inline PostHog snippet-ът е махнат от `index.html`. Той съдържаше твърдо вписан ключ и включен
  `session_recording`.
- `src/lib/analytics.js` се зарежда само ако при build има `REACT_APP_POSTHOG_KEY`; иначе не се
  зарежда нищо.
- Настройки на клиента:
  - `disable_session_recording: true`, а в `loaded` се вика и `stopSessionRecording()`;
  - изключени са autocapture, heatmaps, rageclick, dead clicks и exception capture;
  - `mask_all_text` и `mask_all_element_attributes` са включени.
- `before_send` пропуска само `$pageview` и `app_error`:
  - от свойствата остават само тези в allow-list;
  - URL-ът е без query и hash;
  - грешката носи само типа си (`TypeError`…), никога съобщението.

Проверки (`e2e/analytics-check.js`, Playwright):
| | Резултат |
|---|---|
| red: build на `7c284fa`/`e571b06`, без ключ | 0/2: PostHog се зарежда с вписания ключ (`r68/red-7c284fa.*`) |
| green: build без ключ | 2/2: няма `window.posthog`, няма заявка към PostHog (`r68/green-off.json`) |
| green: build с тестов ключ + истинският posthog-js 1.200.0, сервиран локално | 10/10 (`r68/green-on.json`) |

Подробности за green с тестов ключ:
- `/decide` *иска* session recording, но записът не стартира.
- Няма заявка за запис или snapshot (`/s/`, recorder).
- Изпращат се само `$pageview` и `app_error`.
- Нито едно въведено ЕГН, IBAN, сума, име или парола не е в заявките. Проверката декодира всяко тяло.

Повторение на проверката с ключ:

```
npm pack posthog-js@1.200.0 && tar xzf posthog-js-1.200.0.tgz
REACT_APP_POSTHOG_KEY=phc_test REACT_APP_POSTHOG_HOST=http://localhost:4174/__posthog yarn build
PH_ARRAY_JS=package/dist/array.js node e2e/server.js frontend/build 4174 &
node e2e/analytics-check.js http://localhost:4174 out.json on
```

В тестовата среда posthog-js приема headless Chromium за бот и не изпраща нищо. Затова само скриптът
за проверка скрива `navigator.webdriver` и марката „HeadlessChrome“. Продуктовият код не е променян
за това.

**Отворена точка за Крум:** вписаният ключ е махнат. За да продължи анонимната статистика, при
production build трябва да се подаде `REACT_APP_POSTHOG_KEY` (и по желание `REACT_APP_POSTHOG_HOST`).
Без него статистиката е изключена.

## FG-470 — токенът на клиентския линк за оферта изтичаше към PostHog (поправено)
Находка (FLOW Guard, PROVEN): всеки `$pageview` пращаше `$current_url` и `$pathname` =
`/offers/review/<token>`. Този токен е bearer достъп до оферта с цени и с приемане или отказ.
Това нарушава R68.

Промяна (commit `349622a`):
- На маршрути с токен (`/offers/review/*`, `/reset-password`) аналитиката **не се зарежда**.
  Събитие от такъв път се изхвърля в `before_send`, включително след SPA навигация.
- `$current_url` и `$pathname` стават **шаблон на маршрута** (`/projects/:projectId`);
  непознат път става `/:unknown`.
  - `$referrer`, `$initial_*` и всяко друго URL свойство остават извън allow-list-а.
  - jest тест следи всеки `<Route path>` в `App.js` да има шаблон, за да не изтече нов маршрут
    с id или токен.
- При logout `clearTenantLocalData` изтрива и бисквитките `ph_*`.

| | Резултат |
|---|---|
| jest на кода от `d59bcca` | 15 ✕ (`fg470/jest-red-d59bcca.log`) |
| jest на `349622a` | 26 suites / 246 tests pass (`fg470/jest-green.log`) |
| Playwright, тестов ключ, build на `d59bcca` | 9 PASS / **6 FAIL** — токенът и id на обекта са в заявките (`fg470/red-d59bcca.*`) |
| Playwright, тестов ключ, build на `349622a` | **15/15** (`fg470/green-on.*`) |
| Playwright, без ключ | 2/2 · `run.js` 35/35 |

Сценарии в зелената проверка:
- Клиентът отваря линка за преглед на офертата → няма PostHog.
- Отваря се линк за смяна на парола → няма PostHog.
- Влизане в приложението с referrer от линка → токенът не е в нито една заявка.
- SPA преход към линка или към `/projects/<id>` → изпращат се само шаблони.

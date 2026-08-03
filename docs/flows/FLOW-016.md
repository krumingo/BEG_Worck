# FLOW-016 — Единен File Registry / файлове и документи

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 03.08.2026  
> **Implementation Gate:** W0-BLOCKER; отделна техническа проверка по FLOW-042  
> **Архитектурно правило:** BEG_Work не хоства клиентските оригинални файлове

## Цел

FLOW-016 е единната логическа и техническа основа за файловете в BEG_Work. Един физически файл има един стабилен `file_id`, а различните модули го използват чрез връзки, без независими копия.

## Канонично разделение на отговорностите

### Отговорност на клиента

Всеки tenant задължително свързва собствен Storage Provider още при onboarding:

- Google Drive / Shared Drive;
- Synology / NAS;
- S3-compatible storage;
- собствен on-premise server;
- друг provider чрез одобрен adapter.

Без успешно свързан и проверен Primary Storage Provider tenant-ът не се активира.

Оригиналните клиентски файлове физически се съхраняват при клиента, на негова сметка и договорна отговорност. Клиентът отговаря за капацитета, лиценза/абонамента към storage доставчика, основното съхранение и достъпността на оригиналите.

### Отговорност на BEG_Work

BEG_Work пази:

- File Registry;
- metadata и business relations;
- document families и версии;
- provider/account/object identifiers;
- checksums и последна проверка;
- AuditEvent история;
- thumbnails, previews, OCR и друг ограничен технически кеш;
- собствената приложна база данни.

BEG_Work не продава клиентски GB, не определя архивния срок на оригиналите в клиентското хранилище и не изтрива клиентски оригинали поради достигане на SaaS лимит.

Опционален бъдещ продукт `BEG Hosted Storage` може да се проектира отделно само при доказано търсене. Той не е част от текущия продукт и текущите пакети.

## Разделение между FLOW-ове

- **FLOW-016** — `file_id`, File Registry, provider adapters, metadata, версии, checksums, availability и relations.
- **FLOW-025** — договорен документален контрол, подписи, валидност и checklist.
- **FLOW-029** — фото/видео категории, тагове, галерия и медийна логика.
- **FLOW-044** — backup/restore на BEG_Work базата, File Registry, AuditEvent и техническия кеш; не поема автоматично backup на клиентския Primary Storage.
- Останалите модули сочат към съществуващ `file_id`.

## Един File Registry

Всеки файл пази поне:

- `file_id` и `tenant_id`;
- `original_name` и `display_name`;
- `mime_type` и `size`;
- checksum/hash;
- category/status;
- document family/current version;
- uploaded_by/uploaded_at;
- чувствителност и права;
- storage provider/account/location/object ID;
- availability state и `last_verified_at`;
- relations към business records.

## Един файл, много връзки

Един `file_id` може да е свързан едновременно с:

- обект/подобект;
- СМР;
- дневен отчет;
- оферта/договор/анекс;
- акт/фактура;
- доставка;
- задача;
- дефект/гаранция;
- подизпълнител;
- актив/ремонт.

Показването в няколко екрана не създава физически копия.

## Storage Provider Abstraction

Всички модули използват `file_id`, а не физически път или постоянен provider URL.

Каноничният модел съдържа:

- задължителен Primary Storage Provider на tenant-а;
- optional Backup Provider, когато клиентът го е конфигурирал;
- provider adapter;
- encrypted tenant-specific credentials/secrets;
- provider account, bucket/share, path/object key и provider file ID;
- checksum, sync/availability status и `last_verified_at`.

Browser-ът не получава постоянни storage credentials. Достъпът е чрез краткотрайни защитени upload/preview/download операции и FLOW-002 permission проверки.

## Onboarding gate

Tenant activation изисква:

1. избран provider adapter;
2. валидни credentials;
3. проверен read/write тест в tenant-specific root;
4. записан Primary Storage в Tenant Registry;
5. checksum round-trip тест с временен test object;
6. AuditEvent за свързване и проверка;
7. показано и прието договорно разграничение: оригиналите са отговорност на клиента, File Registry е отговорност на BEG_Work.

При прекъсната връзка tenant-ът не се деактивира автоматично, но upload/download действията се ограничават според риска и се създава критична аларма.

## Периодична проверка на наличността и целостта

BEG_Work извършва периодични проверки според риск, тип документ и последна проверка:

- provider object съществува ли;
- размерът съвпада ли;
- checksum съвпада ли;
- версията/ID-то съвпадат ли;
- provider permission позволява ли необходимия достъп;
- preview/cache може ли да бъде възстановен от оригинала.

При липсващ или променен файл системата създава Data Quality/Alarm запис и AuditEvent с:

- `file_id`;
- provider и location;
- очакван и установен checksum/status;
- дата/час на проверката;
- всички засегнати business records;
- severity според връзките;
- отговорник и действие за възстановяване.

Засегнатите записи се показват изрично, например:

- акт или протокол;
- дефект/гаранционен запис;
- дневен отчет;
- фактура;
- договор/анекс;
- доставка;
- актив/ремонт.

Липсващ оригинал не се замества мълчаливо с thumbnail или preview. Техническият кеш може да помага за преглед и диагностика, но не става нов каноничен оригинал.

## Версиониране

Документите не се презаписват тихо.

- Всички версии са в едно document family.
- Само една версия е Current.
- Старите версии са видими и read-only.
- Одобрена/подписана версия не може да бъде заменена в File Registry без нова версия.
- Нова версия пази кой, кога, причина и предходна версия.
- Повторно качване със същия checksum предлага дубликат.
- Промяна на provider object извън BEG_Work се открива от checksum проверката и се третира като integrity problem, не като автоматична нова версия.

## Снимки и технически производни

- original е в клиентския storage;
- thumbnail, compressed preview, OCR text и PDF preview са технически производни;
- техническите производни могат да бъдат кеширани от BEG_Work;
- производните не са отделни бизнес версии;
- всички сочат към оригиналния `file_id`;
- кешът има техническа retention политика и може да бъде регенериран при наличен оригинал.

## Логическа структура

Стандартни категории:

- Договори и анекси;
- Оферти;
- Актове и протоколи;
- Фактури и финансови документи;
- Чертежи и проекти;
- Дневни отчети;
- Снимки и видео;
- Доставки и стокови документи;
- Дефекти и гаранции;
- Безопасност и сертификати;
- Други.

Физическата папка не е бизнес истината — категорията, версията и relations са.

## Премахване на връзка и изтриване

Премахването от един екран изтрива само relation-а. Файлът остава към останалите записи. Действието се записва в AuditEvent.

BEG_Work не трябва да представя изтриването на запис от File Registry като гарантирано физическо изтриване при клиента. Физическото изтриване в клиентския provider изисква отделно ясно действие, право, provider response и AuditEvent.

Използван, подписан, одобрен или финансов документ не може да бъде премахнат от нормалния интерфейс без документалните и audit правила.

## Права и сигурност

Прилагат се едновременно:

1. достъпът до tenant-а;
2. достъпът до обекта/подобекта;
3. достъпът до модула;
4. чувствителността на категорията;
5. provider capability и наличност.

По-ограниченото право има предимство. Достъп до обект не дава автоматично достъп до payroll, банкови, лични, комисионни или вътрешни финансови файлове.

Задължително:

- tenant-specific credentials;
- encrypted secrets;
- краткотрайни защитени links;
- няма публичен постоянен URL като право за достъп;
- upload/open/download/share/unlink/version/provider-change/check actions се записват в AuditEvent;
- provider credentials и object identifiers не изтичат към друг tenant.

## Health Dashboard

Admin вижда:

- Primary Provider и optional Backup Provider;
- provider connection status;
- брой регистрирани файлове;
- последна успешна availability/checksum проверка;
- липсващи файлове;
- checksum mismatches;
- permission errors;
- засегнати актове, дефекти, отчети и други записи;
- кеш/preview грешки;
- provider migration status.

BEG_Work не показва и не продава собствен клиентски storage quota. Капацитетът на клиентския provider може да се показва само информативно, когато provider API го предоставя.

## Какво НЕ трябва да позволява

- активиране на tenant без проверен Primary Storage Provider;
- качване на клиентски оригинали в неописано BEG_Work хранилище;
- продажба на `+GB` като част от текущите пакети;
- независими копия на един документ по модули;
- provider path/URL да е бизнес ID;
- стар документ да се презаписва без версия;
- външно променен файл да се приеме без integrity alarm;
- липсващ файл да остане без списък на засегнатите записи;
- migration да счупи `file_id` и relations;
- един tenant да вижда файлове или credentials на друг;
- директен URL да заобикаля FLOW-002;
- preview cache да се представя като каноничен оригинал.

## Минимални тестове преди Implementation Gate

- tenant activation е блокирана без проверен Primary Storage Provider;
- onboarding read/write/checksum round-trip е успешен;
- един `file_id` е видим в отчет, акт и дефект без копие;
- нова версия не презаписва старата;
- външно променен provider object създава checksum mismatch;
- липсващ файл създава аларма, AuditEvent и списък на засегнатите записи;
- provider permission failure се различава от физически липсващ файл;
- unlink премахва само една relation;
- provider migration запазва `file_id`;
- потребител без module/sensitivity право не отваря файла;
- tenant isolation пази credentials, metadata, previews и originals;
- preview cache не замества липсващ оригинал.

## Връзки

- FLOW-002 — права;
- FLOW-014/029 — отчети и медии;
- FLOW-025 — документален контрол;
- FLOW-033/034 — проблеми, аларми и решения;
- FLOW-040 — AuditEvent;
- FLOW-042 — integration/isolation tests;
- FLOW-044 — backup/disaster recovery на BEG_Work-managed data;
- FLOW-045/046 — AI и клиентски достъп;
- FLOW-050 — mandatory customer-managed storage и абонаментни entitlements.

## Източници / сесии

- Каноничен архив: `BEG_Work_ALL_FLOWS_001-043_CANONICAL_FULL_2026-07-15.docx`.
- Архитектурна рамка и cross-FLOW решения: FLOW-043.
- Recovery и корекционен проход: Draft PR #2, 20.07.2026.
- Изрично решение на Крум от 03.08.2026: BEG_Work не хоства клиентски оригинални файлове; задължителен customer-managed Storage Provider при onboarding; BEG_Work пази File Registry, checksums, previews/cache и DB.

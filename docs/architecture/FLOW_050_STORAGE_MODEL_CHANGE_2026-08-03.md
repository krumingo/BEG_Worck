# FLOW-050 Storage Model Change — 03.08.2026

> **Статус:** APPROVED BUSINESS DECISION / authoritative addendum to FLOW-050  
> **Засегнати FLOW:** 016, 042, 044, 050  
> **Засегнати решения:** D-11 / F-02  
> **PR:** Draft PR #2 — не се слива автоматично

## Решение

BEG_Work **не хоства клиентските оригинални файлове** в текущия SaaS модел.

Всеки tenant задължително свързва собствен Storage Provider още при onboarding. Без успешно свързан и проверен Primary Storage Provider tenant-ът не се активира.

Поддържани provider типове чрез adapters:

- Google Drive / Shared Drive;
- Synology / NAS;
- S3-compatible storage;
- собствен on-premise server;
- бъдещи providers по общия adapter contract.

## Разделение на отговорностите

### Клиентът отговаря за

- физическото съхранение на оригиналните файлове;
- provider абонамента/лиценза и капацитета;
- основната provider наличност;
- собствената storage/backup политика извън изрично договорените BEG_Work услуги;
- запазването на originals според неговите договорни и законови изисквания.

### BEG_Work отговаря за

- File Registry;
- metadata и връзките към business records;
- версии и document families;
- checksums и availability status;
- provider identifiers и adapter orchestration;
- thumbnails, preview и OCR кеш;
- приложната база данни;
- alarms, Data Quality records и AuditEvent при липса/промяна.

Договорното правило е:

> **Оригиналното съхранение е отговорност на клиента; целостта и проследимостта на File Registry са отговорност на BEG_Work.**

## Onboarding activation gate

Tenant activation изисква:

1. избран provider adapter;
2. валидни tenant-specific credentials;
3. проверена read/write операция;
4. checksum round-trip test;
5. записан Primary Storage в Tenant Registry;
6. AuditEvent за свързване и проверка;
7. прието договорно разграничение на отговорностите.

## Периодичен integrity и availability контрол

FLOW-016 изпълнява периодични проверки:

- съществува ли provider object;
- размерът и checksum-ът съвпадат ли;
- provider permission валиден ли е;
- може ли original-ът да бъде прочетен;
- може ли preview кешът да бъде регенериран.

При липсващ или променен файл системата задължително създава:

- Alarm/Data Quality issue;
- AuditEvent;
- severity;
- отговорник и срок;
- списък на всички засегнати записи: акт, дефект, дневен отчет, фактура, договор, доставка, актив и други relations.

Preview или thumbnail не се превръща автоматично в каноничен оригинал.

## Промяна в пакетите и лимитите

Отпадат от FLOW-050:

- колоната `Файлово пространство`;
- SaaS лимити в GB за клиентски originals;
- архивни срокове за original файловете като част от пакетите;
- add-on `+50 GB`;
- автоматично изтриване/ограничаване на originals поради BEG_Work quota.

Usage limits остават само за:

- AI fair-use прагове;
- свързани имейл акаунти;
- външни интеграции;
- test/staging/Tenant Acceptance environments.

Основната оперативна и финансова работа не се блокира при изчерпан AI fair-use лимит.

## Бъдещ опционален продукт

`BEG Hosted Storage` може да бъде проектиран като отделен платен add-on само при доказано клиентско търсене.

Той не е част от Launch Pricing v1, не се програмира сега и не променя текущия customer-managed storage инвариант.

## Implementation Gate последствия

Wave 0 трябва да включи:

- provider-neutral File Registry;
- mandatory storage onboarding gate;
- tenant-specific encrypted credentials;
- provider adapter contract;
- availability/checksum scheduler;
- alarms + affected-record resolver;
- AuditEvent coverage;
- tenant isolation tests за credentials, metadata, previews и originals;
- backup/restore разграничение между BEG_Work-managed data и customer-managed originals.

## Приемателни тестове

- tenant не се активира без Primary Storage Provider;
- read/write/checksum onboarding test е задължителен;
- липсващ provider object се различава от permission error;
- checksum mismatch създава integrity alarm;
- алармата показва всички засегнати business records;
- един tenant не вижда credentials/files/metadata на друг;
- preview cache не се представя като original;
- пакетите и billing моделът не съдържат storage GB;
- `BEG Hosted Storage` е disabled/not_entitled във всички Launch Pricing v1 планове.

## Канонично предимство

При конфликт между по-ранен текст във FLOW-050 и това решение, **този документ от 03.08.2026 има предимство**, докато FLOW-050 бъде консолидиран при финалния business-close pass.

## Източник

Изрично решение на Крум Радулов от 03.08.2026.

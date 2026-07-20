# FLOW-044 — Disaster Recovery / Backup / Резервна система

> **Статус:** 100% — BUSINESS LOCK  
> **Последна проверка:** 20.07.2026  
> **Implementation Gate:** изисква инфраструктурен дизайн и доказан restore тест

## Цел

BEG_Work трябва да може да бъде възстановен при повреда на сървър, човешка грешка, ransomware, компрометиран акаунт, изтриване/корупция на база, повреден deployment, пожар, кражба или отпадане на storage/cloud услуга.

## Какво се защитава

- MongoDB и всички бизнес данни;
- File Registry и физическите файлове;
- снимки, видеа, договори, фактури и документи;
- приложен код, release tags и Docker images;
- deployment/configuration manifests;
- database migrations и schema version;
- encrypted secrets/credentials чрез защитен механизъм;
- FLOW документация, Decision Register и restore инструкции;
- AuditEvent историята.

## Защитни слоеве

### 1. Production

Основна application, database и storage среда.

### 2. Standby

Готов резервен application instance и съвместима database/storage конфигурация. Standby намалява времето за възстановяване, но не е backup.

### 3. Replication / Point-in-Time Recovery

За висока наличност и възстановяване до близък момент. Репликацията не защитава сама от логическо изтриване или компрометирани данни.

### 4. Historical backups

Дневни/седмични/месечни копия според настройката на tenant-а.

### 5. Off-site immutable / offline copy

Поне едно криптирано копие е извън production доверителната зона, с отделни credentials и защита от изтриване/презаписване.

## Начална целева архитектура за BEG

- Primary application server;
- standby application server;
- MongoDB replica и/или PITR;
- Synology snapshots;
- отделно off-site immutable копие;
- backup на файлове, база, код и конфигурация;
- пълен disaster-recovery тест на всеки 3 месеца.

## RPO и RTO

RPO и RTO са конфигурируеми бизнес цели по tenant и критичност. Те не се представят като гарантирани, докато не бъдат доказани с реален тест.

Примерна цел за критични модули:

```text
RPO: до 15 минути
RTO: до 1 час
```

## Процес при инцидент

```text
аларма
→ изолиране на засегнатата среда
→ спиране на опасна репликация/sync
→ определяне на чиста restore точка
→ restore в изолирана среда
→ проверка на база, файлове и версии
→ човешко разрешение за активиране
→ превключване на трафика
→ смяна на компрометирани credentials
→ post-incident audit
```

При подозирана кибератака не се допуска сляп автоматичен failover към потенциално компрометирано копие.

## Версионна съвместимост

Всеки backup/restore пакет пази:

- `application_version`;
- `database_schema_version`;
- `migration_version`;
- `FLOW_archive_version`;
- `created_at`;
- checksum/manifest.

Не се стартира несъвместима application версия върху възстановена база без миграционна проверка.

## Restore тестове

- периодичен автоматичен restore в изолирана среда;
- пълен ръчен DR тест на всеки 3 месеца;
- допълнителен тест след голяма инфраструктурна промяна;
- health checks, контролни справки и проверка на файлове;
- записан реален RPO/RTO и резултат.

## Backup Dashboard

Крум/Администратор виждат:

- production и standby статус;
- последен database/file/off-site/immutable backup;
- последен успешен restore тест;
- текущ replication lag;
- свободно backup пространство;
- несинхронизирани файлове;
- версия на production и standby;
- аларми за остарял, непълен или непроверен backup.

## Какво НЕ трябва да позволява

- единственият backup да е на production сървъра;
- production и backup да използват един администраторски акаунт;
- standby да се представя като backup;
- backup да е „успешен“ без checksum/manifest;
- restore без version compatibility check;
- изтриване на immutable/off-site копие от обикновен production admin;
- архив на базата без файловете или обратно;
- backup стратегия без доказан restore тест;
- автоматичен failover при подозирана компрометация.

## Връзки

- FLOW-016 — storage providers и file backup;
- FLOW-017 — GitHub/releases;
- FLOW-040 — AuditEvent;
- FLOW-042 — QA, rollback и release acceptance;
- FLOW-043 — D-13.

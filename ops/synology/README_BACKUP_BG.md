# BEG_Work — нощен backup Atlas → Synology

**Защо:** безплатният Atlas M0 клъстер НЯМА автоматични backup-и. Кодът в
GitHub винаги е възстановим; данните — само ако ги пазим сами. Този пакет
пази всяка нощ пълен архив на базата върху твоя Synology.

**Канон:** подготовка за W0-10 Disaster Recovery (backups, restore proof).
Скриптовете са read-only спрямо работната база — mongodump само чете.

## Файлове

```
ops/synology/atlas_backup.sh    — нощният backup (dump + проверка + ротация 14 дни)
ops/synology/atlas_restore.sh   — възстановяване (тест режим по подразбиране)
ops/synology/README_BACKUP_BG.md — този файл
```

Паролата за Atlas НЕ е в скриптовете — чете се от съществуващия
`/volume1/docker/begwork/.env` (MONGO_URL).

## Еднократна настройка (5 минути)

1. Качи файловете в GitHub (клон → PR → merge, както винаги), после обнови
   `repo/` на Synology с командите от резюмето.

2. Ръчен тест по SSH:

```bash
ssh -o Ciphers=aes256-cbc krum@192.168.1.112
sudo bash /volume1/docker/begwork/repo/ops/synology/atlas_backup.sh
```

Очакван край на изхода: `BACKUP OK: begwork_atlas_<дата>.archive.gz`
Архивите отиват в `/volume1/docker/begwork/backups/`.

3. Направи го нощен: **DSM → Control Panel → Task Scheduler → Create →
   Scheduled Task → User-defined script**
   - General: име `BEG Atlas Backup`, user **root**
   - Schedule: **Daily, 03:10**
   - Task Settings → Run command:

```bash
bash /volume1/docker/begwork/repo/ops/synology/atlas_backup.sh
```

   - (по желание) Task Settings → Send run details by email → твоя имейл,
     „only when the script terminates abnormally" — така разбираш само при провал.

4. Провери на сутринта: в `backups/` има нов файл, а последният ред на
   `backups/backup.log` е `BACKUP OK`.

## Проверка, че backup-ът наистина работи (веднъж месечно, препоръчително)

Backup, който никога не е възстановяван, не е backup. Тестът е безопасен —
възстановява в ОТДЕЛНА база `begwork_beg_restore_test`, работната не се пипа:

```bash
sudo bash /volume1/docker/begwork/repo/ops/synology/atlas_restore.sh \
     /volume1/docker/begwork/backups/begwork_atlas_<най-новият>.archive.gz
```

Накрая печата броя записи по колекции — сравни с очакваното (напр. 17
проекта, 15 потребители). После изтрий тестовата база с командата, която
скриптът показва.

## При истинско бедствие

```bash
sudo bash atlas_restore.sh <архив> --production
```

Пита за потвърждение и изисква да напишеш точно `RESTORE PRODUCTION`.
Връща базата към момента на архива — всичко след него се губи, затова
първо говорим, ако ситуацията не е ясна.

## Детайли

- Ротация: пази последните 14 дни (промяна: `RETENTION_DAYS=30` пред командата).
- Всеки архив минава `gzip -t` — офлайн проверка, че е цял и не е повреден.
  Пълната възстановимост се доказва с месечния restore-тест по-горе.
- Празен/малък архив = грешка, не тиха „успешна" нула.
- Скриптът ползва официалния `mongo:7` Docker образ (сваля се веднъж,
  автоматично, при първото пускане).
- Логът е в `backups/backup.log`; при провал последният ред е `BACKUP FAILED`.

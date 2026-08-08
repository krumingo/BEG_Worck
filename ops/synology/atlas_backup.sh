#!/bin/bash
# =============================================================================
# BEG_Work — нощен backup на MongoDB Atlas към Synology
#
# Какво прави:
#   1. чете MONGO_URL от .env на инсталацията (никакви пароли в този файл);
#   2. прави mongodump на цялата база (gzip архив) чрез контейнер mongo:7;
#   3. проверява, че архивът е цял и четим (gzip -t) и не е празен;
#   4. трие архиви, по-стари от RETENTION_DAYS (по подразбиране 14);
#   5. пише всичко в лог; при провал последният ред е "BACKUP FAILED".
#
# Какво НЕ прави:
#   - никога не пише в базата (mongodump е read-only; dryRun не възстановява);
#   - не пипа приложението и контейнерите му.
#
# Настройка (еднократно, DSM Task Scheduler):
#   Control Panel -> Task Scheduler -> Create -> Scheduled Task ->
#   User-defined script; User: root; Schedule: Daily 03:10;
#   Run command:
#     bash /volume1/docker/begwork/repo/ops/synology/atlas_backup.sh
#
# Ръчен тест:  sudo bash atlas_backup.sh
# =============================================================================
set -u -o pipefail

BEG_DIR="${BEG_DIR:-/volume1/docker/begwork}"
ENV_FILE="${ENV_FILE:-$BEG_DIR/.env}"
BACKUP_DIR="${BACKUP_DIR:-$BEG_DIR/backups}"
LOG_FILE="${LOG_FILE:-$BACKUP_DIR/backup.log}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
MONGO_IMAGE="${MONGO_IMAGE:-mongo:7}"
# Минимален размер на смислен архив (байтове). 2113 записа са далеч над това.
MIN_BYTES="${MIN_BYTES:-100000}"

mkdir -p "$BACKUP_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

fail() {
    log "ERROR: $*"
    log "BACKUP FAILED"
    exit 1
}

log "=== BEG_Work Atlas backup start ==="

# --- 1. MONGO_URL от .env (файлът остава единственото място с паролата) ---
[ -f "$ENV_FILE" ] || fail ".env не е намерен: $ENV_FILE"
MONGO_URL="$(grep -E '^MONGO_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
[ -n "$MONGO_URL" ] || fail "MONGO_URL липсва в $ENV_FILE"

STAMP="$(date '+%Y-%m-%d_%H%M')"
ARCHIVE_NAME="begwork_atlas_${STAMP}.archive.gz"

# --- 2. Dump (read-only) ---
log "mongodump започва -> $ARCHIVE_NAME"
docker run --rm \
    -v "$BACKUP_DIR":/backup \
    "$MONGO_IMAGE" \
    mongodump --uri="$MONGO_URL" --gzip --archive="/backup/$ARCHIVE_NAME" \
    >>"$LOG_FILE" 2>&1 \
    || fail "mongodump завърши с грешка (виж $LOG_FILE)"

ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"
[ -f "$ARCHIVE_PATH" ] || fail "архивът не е създаден"

SIZE_BYTES=$(stat -c%s "$ARCHIVE_PATH" 2>/dev/null || stat -f%z "$ARCHIVE_PATH")
[ "$SIZE_BYTES" -ge "$MIN_BYTES" ] || fail "архивът е подозрително малък: $SIZE_BYTES байта"
log "архив: $SIZE_BYTES байта"

# --- 3. Проверка за цялост (офлайн, не изисква връзка към база) ---
# gzip -t чете целия архив и потвърждава, че не е повреден/отрязан.
# Пълната възстановимост се доказва с месечния restore-тест (README).
gzip -t "$ARCHIVE_PATH" >>"$LOG_FILE" 2>&1 \
    || fail "архивът е повреден или отрязан (gzip тест)"
log "gzip проверка: OK — архивът е цял и четим"

# --- 4. Ротация ---
DELETED=$(find "$BACKUP_DIR" -name 'begwork_atlas_*.archive.gz' -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
log "ротация: изтрити $DELETED архива по-стари от $RETENTION_DAYS дни"

TOTAL=$(find "$BACKUP_DIR" -name 'begwork_atlas_*.archive.gz' | wc -l)
log "налични архиви: $TOTAL"
log "BACKUP OK: $ARCHIVE_NAME"
log "=== BEG_Work Atlas backup end ==="

#!/bin/bash
# =============================================================================
# BEG_Work — възстановяване от Atlas backup архив
#
# ДВА РЕЖИМА:
#
#   1. ТЕСТ (по подразбиране, безопасен):
#      възстановява архива в ОТДЕЛНА база begwork_beg_restore_test в Atlas,
#      без да докосва работната begwork_beg. Така доказваме, че backup-ът
#      наистина може да бъде възстановен (W0-10: restore proof).
#
#        sudo bash atlas_restore.sh backups/begwork_atlas_2026-08-08_0310.archive.gz
#
#   2. ИСТИНСКО ВЪЗСТАНОВЯВАНЕ (само при бедствие, изисква изрично писване):
#      връща архива върху работната база. Пита за потвърждение и изисква
#      да напишеш точно: RESTORE PRODUCTION
#
#        sudo bash atlas_restore.sh <архив> --production
#
# Забележка: --drop замества колекциите в ЦЕЛЕВАТА база с тези от архива.
# В тест режим целевата база е тестовата; работната не се пипа изобщо.
# =============================================================================
set -u -o pipefail

BEG_DIR="${BEG_DIR:-/volume1/docker/begwork}"
ENV_FILE="${ENV_FILE:-$BEG_DIR/.env}"
MONGO_IMAGE="${MONGO_IMAGE:-mongo:7}"
SOURCE_DB="${SOURCE_DB:-begwork_beg}"
TEST_DB="${TEST_DB:-begwork_beg_restore_test}"

usage() { echo "Употреба: $0 <път-до-архив> [--production]"; exit 1; }

ARCHIVE="${1:-}"
[ -n "$ARCHIVE" ] || usage
[ -f "$ARCHIVE" ] || { echo "Архивът не е намерен: $ARCHIVE"; exit 1; }
MODE="${2:-test}"

[ -f "$ENV_FILE" ] || { echo ".env не е намерен: $ENV_FILE"; exit 1; }
MONGO_URL="$(grep -E '^MONGO_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
[ -n "$MONGO_URL" ] || { echo "MONGO_URL липсва в $ENV_FILE"; exit 1; }

ARCHIVE_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"
ARCHIVE_FILE="$(basename "$ARCHIVE")"

if [ "$MODE" = "--production" ]; then
    echo "!!! ВНИМАНИЕ: ще презапишеш работната база '$SOURCE_DB' с архива:"
    echo "!!!   $ARCHIVE_FILE"
    echo "!!! Всичко въведено СЛЕД момента на архива ще бъде ИЗГУБЕНО."
    printf "За потвърждение напиши точно RESTORE PRODUCTION: "
    read -r CONFIRM
    [ "$CONFIRM" = "RESTORE PRODUCTION" ] || { echo "Отказано."; exit 1; }
    TARGET_DB="$SOURCE_DB"
else
    TARGET_DB="$TEST_DB"
    echo "ТЕСТ режим: възстановявам в '$TARGET_DB'. Работната '$SOURCE_DB' не се пипа."
fi

docker run --rm \
    -v "$ARCHIVE_DIR":/backup \
    "$MONGO_IMAGE" \
    mongorestore --uri="$MONGO_URL" --gzip --archive="/backup/$ARCHIVE_FILE" \
    --nsFrom="${SOURCE_DB}.*" --nsTo="${TARGET_DB}.*" --drop \
    || { echo "RESTORE FAILED"; exit 1; }

echo
echo "Възстановено в '$TARGET_DB'. Проверка на броя записи по колекции:"
docker run --rm "$MONGO_IMAGE" mongosh "$MONGO_URL" --quiet --eval "
  const db2 = db.getSiblingDB('$TARGET_DB');
  let total = 0;
  db2.getCollectionNames().sort().forEach(c => {
    const n = db2.getCollection(c).countDocuments();
    total += n;
    print(c + ': ' + n);
  });
  print('--- ОБЩО: ' + total + ' записа');
"

if [ "$TARGET_DB" = "$TEST_DB" ]; then
    echo
    echo "Ако числата изглеждат правилно, тестовата база може да се изтрие:"
    echo "  docker run --rm $MONGO_IMAGE mongosh \"\$MONGO_URL\" --eval 'db.getSiblingDB(\"$TEST_DB\").dropDatabase()'"
fi
echo "RESTORE OK"

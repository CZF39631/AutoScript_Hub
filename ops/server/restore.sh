#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"

BACKUP_DIR=${1:?Usage: restore.sh /absolute/path/to/backup}
if compose ps --status running -q server | grep -q .; then
  echo "Server is running; stop it before restore" >&2
  exit 3
fi

case "$BACKUP_DIR" in
  /data/*) CONTAINER_BACKUP=$BACKUP_DIR ;;
  "$DATA_DIR"/*) CONTAINER_BACKUP=/data/${BACKUP_DIR#"$DATA_DIR"/} ;;
  *) echo "Backup must be under $DATA_DIR or /data" >&2; exit 2 ;;
esac

compose run --rm --no-deps --entrypoint python server \
  /app/ops/backup_sqlite.py verify --backup "$CONTAINER_BACKUP"
compose run --rm --no-deps --entrypoint python server \
  /app/ops/backup_sqlite.py restore --backup "$CONTAINER_BACKUP" --data-dir /data

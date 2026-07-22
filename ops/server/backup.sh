#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"

VERSION=${AUTOSCRIPT_BACKUP_VERSION:-0.9.0}
compose exec -T server python /app/ops/backup_sqlite.py backup --data-dir /data --version "$VERSION"

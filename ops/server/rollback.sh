#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"

TARGET_REFERENCE=${1:?Usage: rollback.sh VERSION_OR_IMAGE BACKUP_DIR}
BACKUP_DIR=${2:?Usage: rollback.sh VERSION_OR_IMAGE BACKUP_DIR}
TARGET_IMAGE=$(resolve_server_image "$TARGET_REFERENCE")
export AUTOSCRIPT_SERVER_IMAGE=$TARGET_IMAGE
pull_server
compose stop server
sh "$SCRIPT_DIR/restore.sh" "$BACKUP_DIR"
compose up -d --force-recreate server
wait_ready 30
echo "Rollback to $TARGET_IMAGE is ready"

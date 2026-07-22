#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"

TARGET_VERSION=${1:?Usage: upgrade.sh VERSION}
TARGET_IMAGE=$(resolve_server_image "$TARGET_VERSION")
OLD_IMAGE=$(current_server_image_id)
OLD_VERSION=$(current_server_version)
BACKUP_DIR=$(AUTOSCRIPT_BACKUP_VERSION="$OLD_VERSION" sh "$SCRIPT_DIR/backup.sh")
export AUTOSCRIPT_SERVER_IMAGE=$TARGET_IMAGE
pull_server
compose up -d --force-recreate server
if ! wait_ready 30; then
  echo "Upgrade readiness failed; starting rollback" >&2
  sh "$SCRIPT_DIR/rollback.sh" "$OLD_IMAGE" "$BACKUP_DIR"
  exit 4
fi
echo "Upgrade to $TARGET_VERSION is ready"

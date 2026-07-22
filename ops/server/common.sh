#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE=${AUTOSCRIPT_COMPOSE_FILE:-$REPO_DIR/deploy/compose.yaml}
DATA_DIR=${AUTOSCRIPT_DATA_DIR:-/opt/autoscript-hub/data}
PORT=${AUTOSCRIPT_PORT:-8000}
PROJECT_NAME=${AUTOSCRIPT_PROJECT_NAME:-}
DEFAULT_IMAGE_REPOSITORY=ghcr.io/czf39631/autoscript-hub-server

case "$DATA_DIR" in
  /*) ;;
  *) echo "AUTOSCRIPT_DATA_DIR must be an absolute path" >&2; exit 2 ;;
esac
if [ "$DATA_DIR" = "/" ]; then
  echo "Refusing to operate on /" >&2
  exit 2
fi

compose() {
  if [ -n "$PROJECT_NAME" ]; then
    docker compose --project-name "$PROJECT_NAME" --env-file "$REPO_DIR/deploy/.env" -f "$COMPOSE_FILE" "$@"
  else
    docker compose --env-file "$REPO_DIR/deploy/.env" -f "$COMPOSE_FILE" "$@"
  fi
}

resolve_server_image() {
  value=${1:?image version or reference is required}
  case "$value" in
    sha256:*|*@sha256:*|*/*) printf '%s\n' "$value" ;;
    *) printf '%s:%s\n' "${AUTOSCRIPT_IMAGE_REPOSITORY:-$DEFAULT_IMAGE_REPOSITORY}" "$value" ;;
  esac
}

current_server_image_id() {
  container_id=$(compose ps -q server)
  if [ -z "$container_id" ]; then
    echo "Server container is not running" >&2
    return 1
  fi
  docker inspect --format '{{.Image}}' "$container_id"
}

current_server_version() {
  compose exec -T server python -c 'from shared.version import get_version; print(get_version())'
}

pull_server() {
  case "${AUTOSCRIPT_SERVER_IMAGE:-}" in
    sha256:*)
      docker image inspect "$AUTOSCRIPT_SERVER_IMAGE" >/dev/null
      echo "Using immutable local server image $AUTOSCRIPT_SERVER_IMAGE"
      return 0
      ;;
  esac
  if [ "${AUTOSCRIPT_SKIP_PULL:-0}" = "1" ]; then
    echo "Using preloaded server image (AUTOSCRIPT_SKIP_PULL=1)"
    return 0
  fi
  compose pull server
}

wait_ready() {
  attempts=${1:-30}
  required_successes=${2:-3}
  consecutive=0
  while [ "$attempts" -gt 0 ]; do
    if curl --fail --silent --show-error "http://127.0.0.1:$PORT/api/health/ready" >/dev/null; then
      consecutive=$((consecutive + 1))
      if [ "$consecutive" -ge "$required_successes" ]; then
        return 0
      fi
    else
      consecutive=0
    fi
    attempts=$((attempts - 1))
    if [ "$attempts" -gt 0 ]; then
      sleep 2
    fi
  done
  return 1
}

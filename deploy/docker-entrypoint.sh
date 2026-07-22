#!/bin/sh
set -eu

python -c "from app.config import DATABASE_URL; from app.migrations import upgrade_database; upgrade_database(DATABASE_URL)"
exec python -m uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT:-8000}" --proxy-headers

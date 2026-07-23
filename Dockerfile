ARG BASE_REGISTRY=docker.io/library
FROM ${BASE_REGISTRY}/node:20-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm test && npm run build

FROM ${BASE_REGISTRY}/python:3.11-slim-bookworm AS server
ARG AUTOSCRIPT_VERSION=0.9.1-dev
ARG AUTOSCRIPT_CHANNEL=beta
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/autoscript.db \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    AUTOSCRIPT_VERSION=${AUTOSCRIPT_VERSION} \
    AUTOSCRIPT_CHANNEL=${AUTOSCRIPT_CHANNEL}

WORKDIR /app
RUN addgroup --system autoscript && adduser --system --ingroup autoscript autoscript
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY alembic.ini /app/alembic.ini
COPY backend/ /app/backend/
COPY shared/ /app/shared/
COPY ops/server/backup_sqlite.py /app/ops/backup_sqlite.py
COPY deploy/docker-entrypoint.sh /app/docker-entrypoint.sh
COPY --from=frontend-build /build/frontend/dist /app/backend/static
RUN printf '{"version":"%s","channel":"%s"}\n' "$AUTOSCRIPT_VERSION" "$AUTOSCRIPT_CHANNEL" > /app/autoscript-build.json
RUN mkdir -p /data /app/backend/static \
    && chown -R autoscript:autoscript /data /app \
    && chmod 0755 /app/docker-entrypoint.sh

USER autoscript
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).read()"
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# syntax=docker/dockerfile:1

FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN useradd --uid 1000 --create-home --home-dir /home/app app \
    && mkdir -p /data /app/static \
    && chown -R app:app /data /app

WORKDIR /app
COPY pyproject.toml ./
COPY apps/api ./apps/api
COPY packages/mmex-domain ./packages/mmex-domain
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY --from=web /web/dist /app/static
RUN chown -R app:app /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MMEX_DATA_DIR=/data \
    MMEX_DB_PATH=/data/data.mmb \
    STATIC_DIR=/app/static

USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

CMD ["python", "-m", "uvicorn", "mmex_web_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

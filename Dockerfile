# Production image for Fly.io. Built remotely by `fly deploy` (no local Docker needed).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Editable install so app/config.py's paths (data/, migrations/) resolve inside /app.
COPY pyproject.toml ./
COPY app ./app
RUN pip install -e .

COPY alembic.ini ./
COPY migrations ./migrations
COPY data/shelf_life.json data/aliases_extra.json ./data/

EXPOSE 8080

# On start the app migrates and seeds the database on the /data volume (both idempotent).
# --proxy-headers: trust Fly's proxy for the original https scheme and client address.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

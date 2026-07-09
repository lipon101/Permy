# ---- Permy API image (production) ----
FROM python:3.9-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for geoalchemy2 / asyncpg / pyproj build. libpq-dev stays for
# asyncpg at runtime; build-essential+gcc are build-only (kept for slim simplicity).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY permy ./permy
COPY tests ./tests

# Runtime deps ONLY (no [dev] test tooling in the prod image).
RUN pip install --upgrade pip && pip install .

# Non-root user for the running process
RUN useradd -r -u 1001 -g users permy && chown -R permy:users /app
USER permy

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "permy.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]

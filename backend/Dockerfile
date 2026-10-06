# ==============================================================================
# Backend Dockerfile — multi-stage build
# Stages: base -> development | production
# Build a specific stage with: docker build --target development ./backend
# ==============================================================================

# ---------- Stage: base ----------
# Shared system dependencies and Python package manifest.
# psycopg/asyncpg need libpq at build time; build-essential covers any
# packages (e.g. cryptography) that compile native extensions.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# ---------- Stage: development ----------
# Installs dev dependencies (pytest, ruff, black, mypy) and runs uvicorn
# with --reload against a bind-mounted source tree (see docker-compose.override.yml).
# Never used in production — reload watches the filesystem, which is wasted
# overhead and unnecessary surface area outside local dev.
FROM base AS development

RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- Stage: production ----------
# Installs only runtime dependencies (no pytest/ruff/mypy), copies source
# in as a fixed layer (no bind mount), and runs uvicorn without --reload,
# as a non-root user.
FROM base AS production

RUN pip install --upgrade pip && pip install -e .

COPY . .

RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

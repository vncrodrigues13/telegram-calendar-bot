# --- builder: resolve deps from uv.lock into /app/.venv ---------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer survives source edits.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- runtime ------------------------------------------------------------------
FROM python:3.13-slim-bookworm

# tzdata: extract.py resolves ZoneInfo(settings.timezone); slim ships without
# the zoneinfo database and every extraction would fail.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# UID 1000 matches the k8s securityContext and the default Ubuntu VM user.
RUN groupadd --gid 1000 bot && useradd --uid 1000 --gid 1000 --no-create-home bot

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/bot.db \
    TOKEN_PATH=/data/token.json \
    CREDENTIALS_PATH=/data/credentials.json

WORKDIR /data
USER 1000:1000

# Exec form so PID 1 gets SIGTERM; PTB shuts down gracefully on it.
CMD ["python", "-m", "event_bot.main"]

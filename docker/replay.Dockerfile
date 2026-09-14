# syntax=docker/dockerfile:1.7
# xpm replay publisher: the deterministic MQTT dataset streamer.
# Entrypoint is `python -m xpm.replay` (backend.md §1).

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim-bookworm AS builder
# `tdigest` pulls in accumulation-tree, which is sdist-only and needs a C
# compiler. It is confined to this stage; the runtime image has no toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so a source edit does not re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable
COPY backend/ ./backend/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
# The publisher reads the committed processed parquet and never scores, but it
# shares one image recipe with the API so the two environments cannot drift.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Mount points for the read-only config and data trees, created up front so
# they are owned by app, not root.
RUN mkdir -p /app/config /app/data && chown -R app:app /app
USER app
CMD ["python", "-m", "xpm.replay"]

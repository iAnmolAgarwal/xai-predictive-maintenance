# syntax=docker/dockerfile:1.7
# xpm API: FastAPI + WebSocket hub + the live scoring pipeline.
# Entrypoint is `python -m xpm.api` (backend.md §1).

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim-bookworm AS builder
# No compiler is installed here on purpose: every locked runtime dependency
# publishes a cp312 manylinux wheel for both amd64 and arm64, so `uv sync`
# never builds from source. The `build-essential` layer this stage used to
# carry existed only for `tdigest` -> accumulation-tree, which R22 dropped from
# pyproject. Adding a dependency without linux wheels means adding it back.
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
# libgomp1 is LightGBM's OpenMP runtime; it is absent from the slim base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Mount points for the read-only config/data/model trees and the writable
# database volume, created up front so they are owned by app, not root.
RUN mkdir -p /app/config /app/data /app/models /app/var && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["python", "-m", "xpm.api"]

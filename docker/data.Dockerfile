# syntax=docker/dockerfile:1.7
# Data-tooling image for `make data` / `make data-ims` run in a container.
# It is the only image that carries the archive extractors the NASA IMS
# download needs (backend.md §2.1, §3.2): `unar` for the nested RAR members
# and `p7zip-full` for the outer archive.
#
# It is deliberately not a docker-compose service: data acquisition is a human
# action, not part of `make dev`, which needs no download at all (R2).

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
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable
COPY backend/ ./backend/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 unar p7zip-full \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app scripts/ /app/scripts/
RUN mkdir -p /app/config /app/data && chown -R app:app /app
USER app
CMD ["python", "scripts/fetch_data.py", "--help"]

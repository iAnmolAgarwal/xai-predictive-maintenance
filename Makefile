# Public interface of this repository. Every target works from a fresh clone
# once `make setup` has run. The target list is fixed by docs/plan/backend.md
# §2.2; the scripts they invoke are owned by the task named beside them.

SHELL := /bin/sh
.DEFAULT_GOAL := help

# make dev PULL=1 pulls the GHCR images CI publishes from main instead of
# building locally (R1).
PULL ?=

# Tag of the data-tooling image (docker/data.Dockerfile), which carries the
# `unar`/`7z` extractors the IMS archive needs.
XPM_DATA_IMAGE ?= xpm-data:local

.PHONY: help setup data data-image data-ims contracts contracts-check train \
        evaluate lint typecheck test e2e dev down check media

help:  ## List the available targets
	@grep -hE '^[a-z][a-z0-9-]*:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Install Python, Node and git-hook tooling
	uv sync --all-extras
	pnpm -C web install
	uv run pre-commit install

data:  ## Fetch and process the AI4I 2020 dataset (T-DATA)
	uv run python scripts/fetch_data.py --plant ai4i

data-image:  ## Build the data-tooling image that carries the IMS archive extractors
	docker build -f docker/data.Dockerfile -t $(XPM_DATA_IMAGE) .

data-ims:  ## Fetch and process the NASA IMS dataset (1.0 GB download) (T-DATA)
	@if command -v unar >/dev/null 2>&1; then \
		echo "unar found on PATH: extracting on the host"; \
		uv run python scripts/fetch_data.py --plant ims; \
	else \
		echo "unar not on PATH: extracting inside $(XPM_DATA_IMAGE)"; \
		$(MAKE) data-image; \
		mkdir -p "$(CURDIR)/data" "$(CURDIR)/config"; \
		docker run --rm \
			--user "$$(id -u):$$(id -g)" \
			--security-opt no-new-privileges:true \
			-e HOME=/tmp \
			-v "$(CURDIR)/config:/app/config:ro" \
			-v "$(CURDIR)/data:/app/data" \
			$(XPM_DATA_IMAGE) python scripts/fetch_data.py --plant ims; \
	fi

contracts:  ## Regenerate contracts/*.json and the frontend's TypeScript types (T-CONTRACTS)
	uv run python scripts/export_openapi.py
	pnpm -C web exec openapi-typescript ../contracts/openapi.json -o src/contracts/api.ts
	uv run python scripts/export_ws_schema.py
	pnpm -C web exec json2ts -i ../contracts/ws-schema.json -o src/contracts/ws.ts --additionalProperties false

contracts-check:  ## Fail if the committed contract artefacts have drifted
	@tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	uv run python scripts/export_openapi.py --out "$$tmp/openapi.json"; \
	uv run python scripts/export_ws_schema.py --out "$$tmp/ws-schema.json"; \
	diff -u contracts/openapi.json "$$tmp/openapi.json"; \
	diff -u contracts/ws-schema.json "$$tmp/ws-schema.json"; \
	echo "contracts are current"

train:  ## Train LightGBM + RandomForest for both plants (T-MODEL)
	uv run python scripts/train.py --plant all

evaluate:  ## Regenerate docs/EVALUATION.md and reports/metrics.json (T-MODEL)
	uv run python scripts/evaluate.py

lint:  ## ruff check + ruff format --check + eslint
	uv run ruff check .
	uv run ruff format --check .
	pnpm -C web lint

typecheck:  ## mypy --strict on the backend, tsc --noEmit on the frontend
	uv run mypy --strict backend
	pnpm -C web exec tsc --noEmit

test:  ## Backend pytest with the 85% coverage gate, then the frontend unit tests
	uv run pytest --cov=backend/xpm --cov-branch --cov-fail-under=85
	pnpm -C web test

e2e:  ## Bring up the non-looping stack and run the Playwright suite against it
	docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build
	sh scripts/wait_for_port.sh 127.0.0.1 8000 120
	sh scripts/wait_for_port.sh 127.0.0.1 5173 120
	pnpm -C web exec playwright test

dev:  ## Run the whole stack (PULL=1 pulls prebuilt GHCR images instead of building)
ifeq ($(PULL),1)
	docker compose pull
	docker compose up
else
	docker compose up --build
endif

down:  ## Stop the stack and delete its volumes
	docker compose down -v

check:  ## Everything CI enforces, in one command
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) contracts-check

media:  ## Capture the README screenshots and GIF from a running stack (T-DOCS)
	pnpm -C web exec tsx ../scripts/capture_media.ts

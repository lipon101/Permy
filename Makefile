.PHONY: help install dev test lint format run worker ingest clean docker-up docker-down

help:
	@echo "Permy — permit & construction-intelligence API"
	@echo "  make install     install runtime deps"
	@echo "  make dev         install dev deps"
	@echo "  make test        run unit tests (no live upstream calls)"
	@echo "  make test-live   include live upstream calls (network)"
	@echo "  make lint        ruff check"
	@echo "  make format      ruff format + isort"
	@echo "  make run         uvicorn API"
	@echo "  make worker      ingestion + webhook worker"
	@echo "  make docker-up   docker compose stack (pg+redis+api+worker)"
	@echo "  make ingest      run daily ingestion for configured cities"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest -m "not live"

test-live:
	pytest

lint:
	ruff check permy tests

format:
	ruff format permy tests || true
	ruff check --fix permy tests || true

run:
	uvicorn permy.api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	python -m permy.ingest.worker

ingest:
	python -m permy.ingest.cli

docker-up:
	docker compose -f deploy/docker-compose.yml up --build

docker-down:
	docker compose -f deploy/docker-compose.yml down

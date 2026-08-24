# NEYOGI — common operations.
# Requires GNU make. On Windows use Git Bash or WSL.

SHELL := /bin/bash
PY    ?= python
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

.PHONY: install
install: ## Install Python and Node dependencies locally
	$(PY) -m pip install -r backend/requirements.txt
	$(PY) -m pip install -r ml_pipeline/requirements.txt
	cd frontend && npm install

.PHONY: env
env: ## Create .env from the template if it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env — fill it in before starting.")

# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

.PHONY: test
test: ## Run the full Python test suite
	$(PY) -m pytest ml_pipeline/tests backend/tests -q

.PHONY: test-indices
test-indices: ## Verify the 11 vegetation indices against hand-computed matrices
	$(PY) -m pytest ml_pipeline/tests/test_feature_engineering.py -v

.PHONY: lint
lint: ## Lint the frontend
	cd frontend && npm run lint

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply the PostGIS schema (idempotent)
	$(PY) -c "from ml_pipeline import db; db.apply_schema()"

.PHONY: psql
psql: ## Open a psql shell in the postgis container
	$(COMPOSE) exec postgis psql -U $${POSTGRES_USER:-neyogi} -d $${POSTGRES_DB:-neyogi}

# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

.PHONY: districts
districts: ## Resolve district names against the live FAO/GAUL collection
	$(PY) -m ml_pipeline.gee_districts --list-available

.PHONY: seed
seed: ## Backfill 60 days of Sentinel-2 composites (cold-start seed)
	$(PY) -m ml_pipeline.gee_ingestion --seed

.PHONY: ingest
ingest: ## Ingest the most recent composite window
	$(PY) -m ml_pipeline.gee_ingestion

.PHONY: train
train: ## Train the Random Forest crop classifier
	$(PY) -m ml_pipeline.train_classifier

.PHONY: yields
yields: ## Report yield-baseline verification coverage
	$(PY) -m ml_pipeline.supply_estimation --coverage

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

.PHONY: api
api: ## Run the API locally with reload
	uvicorn backend.main:app --reload --port 8000

.PHONY: web
web: ## Run the Vite dev server
	cd frontend && npm run dev

.PHONY: worker
worker: ## Run a Celery worker locally
	celery -A backend.workers.celery_app.celery_app worker --loglevel=info

.PHONY: up
up: env ## Build and start the whole stack
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail all service logs
	$(COMPOSE) logs -f

.PHONY: officer
officer: ## Generate a bcrypt hash for OFFICER_ACCOUNTS (make officer PASS=secret)
	@test -n "$(PASS)" || (echo "usage: make officer PASS=<password>" && exit 1)
	@$(PY) -m backend.security hash "$(PASS)"

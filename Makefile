.DEFAULT_GOAL := help
VENV ?= .venv
PY := $(VENV)/bin/python
PORT ?= 8000

.PHONY: help venv install ui-install ui-build ui-dev ui-test dev test lint fmt eval eval-ablation chat site docker-up docker-down clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the local virtualenv
	test -d $(VENV) || python3 -m venv $(VENV)

install: venv ## Install the backend with dev extras
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"

ui-install: ## Install UI dependencies
	cd ui && npm ci

ui-build: ## Build the chat UI into ui/dist (served by the API at /)
	cd ui && npm run build

ui-dev: ## Vite dev server on :5173 (proxies /api to :$(PORT))
	cd ui && npm run dev

ui-test: ## UI lint, typecheck and vitest
	cd ui && npm run lint && npm run typecheck && npm test

dev: ## Run the API with auto-reload on :$(PORT)
	$(VENV)/bin/uvicorn support_agent.api.main:app --reload --port $(PORT)

test: ## Backend test suite
	$(PY) -m pytest

lint: ## Ruff lint + format check
	$(VENV)/bin/ruff check support_agent tests
	$(VENV)/bin/ruff format --check support_agent tests

fmt: ## Auto-format and fix lint
	$(VENV)/bin/ruff format support_agent tests
	$(VENV)/bin/ruff check --fix support_agent tests

eval: ## Run the scenario suite (agent-eval)
	$(VENV)/bin/agent-eval run

eval-ablation: ## Same suite with the soft guardrails switched off
	$(VENV)/bin/agent-eval run --disable input_injection --disable tool_output || true

chat: ## Chat in the terminal as a demo customer (CUSTOMER=C001)
	$(VENV)/bin/support-agent chat --memory --customer $(or $(CUSTOMER),C001)

site: ## Build the GitHub Pages site (replay UI + API reference) into _site/
	PATH="$(abspath $(VENV))/bin:$$PATH" bash scripts/build_site.sh _site

docker-up: ## Build and start the container
	docker compose up --build -d

docker-down: ## Stop the container
	docker compose down

clean: ## Remove caches and build output
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage _site ui/dist data/shop.db*
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

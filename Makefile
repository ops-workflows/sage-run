PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST := $(PYTHON) -m pytest
PYTEST_FLAGS ?= $(if $(CI),-q,-vv -ra)
PYTEST_TIMEOUT_FLAGS ?=

PGUSER ?= sage_run
PGPASSWORD ?= localdev-postgres-password
TEST_DB_NAME ?= sage_run_test
TEST_PG_PORT ?= 55432
TEST_DATABASE_URL ?= postgresql+asyncpg://$(PGUSER):$(PGPASSWORD)@localhost:$(TEST_PG_PORT)/$(TEST_DB_NAME)
RUNTIME_IMAGE ?= sage-run-agent-runtime:latest
MCP_IMAGE ?= sage-run-mcp:latest
RUNTIME_BUILD ?= docker build
SANDBOX_MODE ?= macos
COMPOSE_PROJECT_NAME ?= sage-run-test
TEST_DOCKER_NETWORK ?= $(COMPOSE_PROJECT_NAME)-network
TEST_COMPOSE ?= PGUSER=$(PGUSER) PGPASSWORD=$(PGPASSWORD) PG_PORT=$(TEST_PG_PORT) DOCKER_NETWORK=$(TEST_DOCKER_NETWORK) docker compose --project-name $(COMPOSE_PROJECT_NAME) -f tests/compose.yaml

.PHONY: help unit-tests service-tests runtime-tests tests \
	ensure-test-db runtime-build mcp-build clean-test-containers \
	init create-github-app lint format

init: ## Install Python dependencies
	uv sync --extra dev --extra server --extra kubernetes

create-github-app: ## Register an organization GitHub App and save its credentials privately
	$(PYTHON) scripts/create_github_app.py $(GITHUB_APP_ARGS)

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "%-28s %s\n", $$1, $$2}'

runtime-build: ## Build the runtime container image
	$(RUNTIME_BUILD) -t $(RUNTIME_IMAGE) -f runtime/Dockerfile .

mcp-build: ## Build the shared MCP server container image used by runtime smoke tests
	docker build -t $(MCP_IMAGE) -f mcps/Dockerfile .

ensure-test-db: ## Create the dedicated Postgres test database if needed
	$(TEST_COMPOSE) up -d --wait postgres
	@$(TEST_COMPOSE) exec -T postgres psql -U $(PGUSER) -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$(TEST_DB_NAME)'" | grep -q 1 || \
		$(TEST_COMPOSE) exec -T postgres psql -U $(PGUSER) -d postgres -c "CREATE DATABASE $(TEST_DB_NAME)"

unit-tests: ## Run unit tests (no infra required)
	$(PYTEST) tests/unit $(PYTEST_FLAGS)

service-tests: ensure-test-db ## Run service/Postgres tests
	TEST_DATABASE_URL='$(TEST_DATABASE_URL)' $(PYTEST) tests/service $(PYTEST_FLAGS)

runtime-tests: ensure-test-db runtime-build mcp-build ## Run runtime scenario tests (Postgres + Docker required)
	TEST_DATABASE_URL='$(TEST_DATABASE_URL)' TEST_RUNTIME_ENABLED=1 SANDBOX_MODE=$(SANDBOX_MODE) DOCKER_NETWORK=$(TEST_DOCKER_NETWORK) \
		COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) MCP_TEST_IMAGE=$(MCP_IMAGE) \
		$(PYTEST) tests/runtime $(PYTEST_TIMEOUT_FLAGS) $(PYTEST_FLAGS)

tests: ensure-test-db runtime-build mcp-build ## Run all tests, including unit, service, and runtime scenarios
	TEST_DATABASE_URL='$(TEST_DATABASE_URL)' TEST_RUNTIME_ENABLED=1 SANDBOX_MODE=$(SANDBOX_MODE) DOCKER_NETWORK=$(TEST_DOCKER_NETWORK) \
		COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) MCP_TEST_IMAGE=$(MCP_IMAGE) \
		$(PYTEST) tests $(PYTEST_FLAGS)

clean-test-containers: ## Remove dangling test session containers
	-@docker ps -a --filter "label=sage_run.type=agent-session" --format "{{.ID}}" | xargs -r docker rm -f

format: ## Format code (ruff check + fix)
	uv run ruff check . --fix && uv run ruff format . && npm --prefix control-plane-ui run format

lint: ## Lint (ruff check + format check)
	uv run ruff check . && uv run ruff format --check . && npm --prefix control-plane-ui run lint && npm --prefix control-plane-ui run format:check
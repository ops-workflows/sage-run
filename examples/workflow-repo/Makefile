UV ?= uv
ENV ?=
TARGET ?=
REF ?= main
INSTANCE ?=
CONTEXT ?=
SANDBOX ?=
IDENTITY ?=
IMAGE_TAG ?=
NO_BUILD ?=
PURGE ?=
NAME ?=
CONNECTION ?=
VALUE_FILE ?=
SAGE_RUN_SOURCE ?=
DEV_SOURCE ?= $(if $(SAGE_RUN_SOURCE),$(SAGE_RUN_SOURCE),../sage-run)

UV_RUN = $(UV) run $(if $(SAGE_RUN_SOURCE),--with-editable "$(SAGE_RUN_SOURCE)",--frozen)
CODE_DIRS := $(wildcard connectors mcps tests)
LOCAL_FLAGS = $(if $(INSTANCE),--instance "$(INSTANCE)") $(if $(CONTEXT),--context "$(CONTEXT)")
UP_FLAGS = $(LOCAL_FLAGS) \
	$(if $(SAGE_RUN_SOURCE),--source "$(SAGE_RUN_SOURCE)") \
	$(if $(IMAGE_TAG),--image-tag "$(IMAGE_TAG)") \
	$(if $(NO_BUILD),--no-build) \
	$(if $(IDENTITY),--identity "$(IDENTITY)") \
	$(if $(SANDBOX),--sandbox "$(SANDBOX)") \
	$(if $(ENV),--env "$(ENV)")
DEPLOY_FLAGS = --host "$(TARGET)" \
	--env "$(or $(ENV),prod)" \
	--ref "$(REF)" \
	$(if $(INSTANCE),--instance "$(INSTANCE)") \
	$(if $(IMAGE_TAG),--image-tag "$(IMAGE_TAG)")

.PHONY: help validate lint format test ci up dev down status plan deploy secret-set

help:
	@echo "Targets:"
	@echo "  make validate                                Validate workflows, config overlays, and sage-run pin/lock"
	@echo "  make lint                                    Run ruff check, ruff format --check, and sage-run validate"
	@echo "  make format                                  Auto-fix ruff lint/formatting and validate"
	@echo "  make test                                    Run workflow and MCP unit tests with pytest"
	@echo "  make ci                                      Run shared CI entry point (sage-run ci)"
	@echo "  make up [INSTANCE=...] [ENV=...]             Create/update local Kubernetes instance from working tree"
	@echo "  make dev [SAGE_RUN_SOURCE=../sage-run]       Run local instance built from a local sage-run checkout"
	@echo "  make down [INSTANCE=...] [PURGE=1]           Remove local Kubernetes instance workloads"
	@echo "  make status [INSTANCE=...]                   Show local Kubernetes instance status"
	@echo "  make plan [TARGET=host] [ENV=prod] [REF=main] Preview local validation or remote SSH deployment plan"
	@echo "  make deploy [TARGET=host] [ENV=prod] [REF=main] Apply local working tree (dev) or deploy REF over SSH"
	@echo "  make secret-set NAME=VAR [ENV=dev|prod] [CONNECTION=...] [VALUE_FILE=...] Encrypt a secret value"

validate:
	$(UV_RUN) sage-run validate .

lint:
	@if [ -n "$(strip $(CODE_DIRS))" ]; then \
		$(UV_RUN) ruff check $(CODE_DIRS); \
		$(UV_RUN) ruff format --check $(CODE_DIRS); \
	fi
	$(UV_RUN) sage-run validate .

format:
	@if [ -n "$(strip $(CODE_DIRS))" ]; then \
		$(UV_RUN) ruff check --fix $(CODE_DIRS); \
		$(UV_RUN) ruff format $(CODE_DIRS); \
	fi
	$(UV_RUN) sage-run validate .

test:
	$(UV_RUN) pytest tests -q

ci:
	@if $(UV_RUN) sage-run --help 2>/dev/null | grep -q '\bci\b'; then \
		$(UV_RUN) sage-run ci .; \
	else \
		$(MAKE) lint && $(MAKE) test; \
	fi

up:
	$(UV_RUN) sage-run up . $(UP_FLAGS)

dev:
	$(MAKE) up SAGE_RUN_SOURCE="$(DEV_SOURCE)"

down:
	$(UV_RUN) sage-run down . $(LOCAL_FLAGS) $(if $(PURGE),--purge)

status:
	$(UV_RUN) sage-run status . $(LOCAL_FLAGS)

plan:
	@if [ -n "$(TARGET)" ]; then \
		$(UV_RUN) sage-run deploy . $(DEPLOY_FLAGS) --plan; \
	else \
		$(UV_RUN) sage-run validate . && \
		echo "Local plan valid (env=$(or $(ENV),dev), context=$(or $(CONTEXT),rancher-desktop), instance=$(or $(INSTANCE),$(notdir $(CURDIR))-dev))"; \
	fi

deploy:
	@if [ -n "$(TARGET)" ]; then \
		$(UV_RUN) sage-run deploy . $(DEPLOY_FLAGS); \
	elif [ -z "$(ENV)" ] || [ "$(ENV)" = "dev" ]; then \
		$(MAKE) up; \
	else \
		echo "error: TARGET=<ssh-host> is required when deploying ENV=$(ENV)" >&2; \
		exit 1; \
	fi

secret-set:
	@if [ -z "$(NAME)" ]; then \
		echo "error: NAME=<secret_name> is required (optional: ENV=dev|prod CONNECTION=<name> VALUE_FILE=<path>)" >&2; \
		exit 1; \
	fi
	$(UV_RUN) sage-run secret set . --env "$(or $(ENV),dev)" --name "$(NAME)" \
		$(if $(CONNECTION),--connection "$(CONNECTION)") \
		$(if $(VALUE_FILE),--value-file "$(VALUE_FILE)")

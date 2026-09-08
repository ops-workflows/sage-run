SAGE_RUN_DIR ?= ../sage-run
PYTHON := $(SAGE_RUN_DIR)/.venv/bin/python
RUFF := $(SAGE_RUN_DIR)/.venv/bin/ruff
PYTHON_PATHS := $(strip $(wildcard connectors mcps))

.PHONY: lint format check-venv validate

lint: check-venv
	@if [ -n "$(PYTHON_PATHS)" ]; then $(RUFF) check $(PYTHON_PATHS); fi
	@if [ -n "$(PYTHON_PATHS)" ]; then $(RUFF) format --check $(PYTHON_PATHS); fi
	@$(MAKE) --no-print-directory validate

format: check-venv
	@if [ -n "$(PYTHON_PATHS)" ]; then $(RUFF) check --fix $(PYTHON_PATHS); fi
	@if [ -n "$(PYTHON_PATHS)" ]; then $(RUFF) format $(PYTHON_PATHS); fi
	@$(MAKE) --no-print-directory validate

check-venv:
	@test -x "$(PYTHON)" -a -x "$(RUFF)" || { \
		echo "Missing sage-run virtual environment at $(SAGE_RUN_DIR)/.venv" >&2; \
		exit 1; \
	}

validate:
	$(PYTHON) $(SAGE_RUN_DIR)/scripts/validate_workflow_repo.py .

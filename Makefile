VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
BOOTSTRAP_PYTHON ?= python3.12

.PHONY: check-python install-dev test lint format-check typecheck verify run

$(PYTHON):
	@command -v $(BOOTSTRAP_PYTHON) >/dev/null || { \
		echo "$(BOOTSTRAP_PYTHON) is required to create $(VENV_DIR)"; \
		exit 1; \
	}
	@$(BOOTSTRAP_PYTHON) -c 'import sys; expected = (3, 12); actual = sys.version_info[:2]; sys.exit(f"expected Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]}") if actual != expected else sys.exit(0)'
	$(BOOTSTRAP_PYTHON) -m venv $(VENV_DIR)

check-python:
	@test -x $(PYTHON) || { \
		echo "$(VENV_DIR) is missing; run 'make install-dev' first"; \
		exit 1; \
	}
	@$(PYTHON) -c 'import sys; expected = (3, 12); actual = sys.version_info[:2]; sys.exit(f"$(VENV_DIR) must use Python {expected[0]}.{expected[1]}, got {actual[0]}.{actual[1]}") if actual != expected else sys.exit(0)'

install-dev: $(PYTHON)
	@$(MAKE) check-python
	$(PYTHON) -m pip install -e '.[dev]'

test: check-python
	$(PYTHON) -m pytest

lint: check-python
	$(PYTHON) -m ruff check .

format-check: check-python
	$(PYTHON) -m ruff format --check .

typecheck: check-python
	$(PYTHON) -m mypy

verify: lint format-check typecheck test

run: check-python
	$(PYTHON) -m strategy_runtime.bootstrap.main

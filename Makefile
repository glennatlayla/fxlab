# FXLab Development Makefile
# Run `make help` to see available targets.

PYTHON      := .venv/bin/python
PIP         := .venv/bin/pip
PYTEST      := .venv/bin/python -m pytest
RUFF        := .venv/bin/ruff
MYPY        := .venv/bin/mypy
COVERAGE    := .venv/bin/coverage
PRECOMMIT   := .venv/bin/pre-commit

.PHONY: help install-dev hooks format format-check lint type-check \
        test test-unit test-integration test-acceptance \
        coverage quality ci clean

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install-dev:  ## Install all dependencies (prod + dev)
	$(PIP) install -r requirements.txt

hooks:  ## Install pre-commit hooks (run once after clone)
	$(PRECOMMIT) install

format:  ## Auto-format code with ruff
	$(RUFF) format .

format-check:  ## Check formatting without modifying files
	$(RUFF) format --check .

lint:  ## Run ruff linter
	$(RUFF) check .

type-check:  ## Run mypy type checker
	$(MYPY) services/ libs/ --ignore-missing-imports --no-strict-optional

test:  ## Run full test suite with coverage
	$(PYTEST) --tb=short -q --cov=services --cov=libs --cov-report=term-missing

test-unit:  ## Run unit tests only
	$(PYTEST) tests/unit/ --tb=short -q

test-integration:  ## Run integration tests only
	$(PYTEST) tests/integration/ --tb=short -q

test-acceptance:  ## Run acceptance tests only
	$(PYTEST) tests/acceptance/ --tb=short -q

coverage:  ## Run tests and enforce ≥80% coverage gate
	$(PYTEST) --tb=short -q --cov=services --cov=libs --cov-fail-under=80

quality: format-check lint  ## Run all code quality checks (format + lint)

ci: quality test  ## Simulate full CI pipeline locally

clean:  ## Remove build artefacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache

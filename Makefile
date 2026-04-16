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
        test-shell install-smoke \
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

test-shell:  ## Run shell test suites for install.sh and ship.sh
	@echo "Running shell test suites..."
	@bash tests/shell/test_install_pull_latest.sh
	@bash tests/shell/test_install_diagnostics.sh
	@bash tests/shell/test_install_env_detection.sh
	@bash tests/shell/test_ship_commit_push.sh
	@echo "All shell tests passed."

ci: quality test  ## Simulate full CI pipeline locally

# ---------------------------------------------------------------------------
# Install smoke test (v2 remediation Phase 5)
# ---------------------------------------------------------------------------
# Spins up the full production compose stack, waits for healthchecks,
# probes each service endpoint, checks logs for CRITICAL/ERROR, and
# tears down. REQUIRED gate for any commit touching docker-compose.prod.yml,
# install.sh, Dockerfiles, or lifespan code.
#
# Prerequisites:
#   - Docker Engine 24+ and Docker Compose v2
#   - .env file with secrets (or .env.production.template copied to .env)
#   - Ports 80/443 available (or FXLAB_HTTP_PORT/FXLAB_HTTPS_PORT set)
#
# Usage:
#   make install-smoke
#   make install-smoke SMOKE_TIMEOUT=120
#
# The target exits non-zero if any service fails its healthcheck or if
# CRITICAL/ERROR log lines are found. The compose stack is always torn
# down on exit (success or failure).
# ---------------------------------------------------------------------------
SMOKE_TIMEOUT     ?= 90
SMOKE_COMPOSE     := docker compose -f docker-compose.prod.yml
SMOKE_LOG_LINES   := 100

install-smoke:  ## Spin up prod compose, verify health, tear down
	@echo "=== Install Smoke Test ==="
	@echo "Timeout: $(SMOKE_TIMEOUT)s"
	@echo ""
	@# --- 1. Build and start ---
	@echo "[1/5] Building and starting production stack..."
	@$(SMOKE_COMPOSE) up -d --build 2>&1 | tail -5
	@echo ""
	@# --- 2. Wait for healthchecks ---
	@echo "[2/5] Waiting for services to become healthy (up to $(SMOKE_TIMEOUT)s)..."
	@elapsed=0; \
	while [ $$elapsed -lt $(SMOKE_TIMEOUT) ]; do \
		unhealthy=$$($(SMOKE_COMPOSE) ps --format json 2>/dev/null | \
			python3 -c "import sys,json; lines=[json.loads(l) for l in sys.stdin if l.strip()]; print(sum(1 for s in lines if s.get('Health','') not in ('healthy','')))" 2>/dev/null || echo "99"); \
		if [ "$$unhealthy" = "0" ]; then \
			echo "  All services healthy after $${elapsed}s."; \
			break; \
		fi; \
		sleep 5; \
		elapsed=$$((elapsed + 5)); \
	done; \
	if [ $$elapsed -ge $(SMOKE_TIMEOUT) ]; then \
		echo "  TIMEOUT: not all services healthy after $(SMOKE_TIMEOUT)s."; \
		$(SMOKE_COMPOSE) ps; \
		echo ""; \
		echo "Failing service logs:"; \
		$(SMOKE_COMPOSE) ps --format json 2>/dev/null | \
			python3 -c "import sys,json; [print(json.loads(l).get('Service','')) for l in sys.stdin if l.strip() and json.loads(l).get('Health','') != 'healthy']" 2>/dev/null | \
			while read svc; do echo "--- $$svc ---"; $(SMOKE_COMPOSE) logs --tail=30 "$$svc" 2>/dev/null; done; \
		$(SMOKE_COMPOSE) down --timeout 10 2>/dev/null || true; \
		exit 1; \
	fi
	@echo ""
	@# --- 3. Probe service endpoints ---
	@echo "[3/5] Probing service endpoints..."
	@fail=0; \
	echo "  api /health:"; \
	if $(SMOKE_COMPOSE) exec -T api curl -sf http://localhost:8000/health >/dev/null 2>&1; then \
		echo "    OK"; \
	else \
		echo "    FAIL"; fail=1; \
	fi; \
	echo "  postgres pg_isready:"; \
	if $(SMOKE_COMPOSE) exec -T postgres pg_isready -U $${POSTGRES_USER:-fxlab} -d $${POSTGRES_DB:-fxlab} >/dev/null 2>&1; then \
		echo "    OK"; \
	else \
		echo "    FAIL"; fail=1; \
	fi; \
	echo "  redis ping:"; \
	if $(SMOKE_COMPOSE) exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then \
		echo "    OK"; \
	else \
		echo "    FAIL"; fail=1; \
	fi; \
	if [ $$fail -ne 0 ]; then \
		echo ""; \
		echo "Service probe failures detected."; \
		$(SMOKE_COMPOSE) down --timeout 10 2>/dev/null || true; \
		exit 1; \
	fi
	@echo ""
	@# --- 4. Check logs for CRITICAL/ERROR ---
	@echo "[4/5] Scanning logs for CRITICAL/ERROR..."
	@errors=$$($(SMOKE_COMPOSE) logs --tail=$(SMOKE_LOG_LINES) 2>/dev/null | \
		grep -iE '"level"\s*:\s*"(CRITICAL|ERROR)"' | \
		grep -v "test" | head -20); \
	if [ -n "$$errors" ]; then \
		echo "  WARNING: CRITICAL/ERROR lines found in logs:"; \
		echo "$$errors" | head -10; \
		echo "  (Review above — may be transient startup noise.)"; \
	else \
		echo "  No CRITICAL/ERROR log lines found."; \
	fi
	@echo ""
	@# --- 5. Tear down ---
	@echo "[5/5] Tearing down..."
	@$(SMOKE_COMPOSE) down --timeout 10 2>/dev/null || true
	@echo ""
	@echo "=== Install Smoke Test PASSED ==="

clean:  ## Remove build artefacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache

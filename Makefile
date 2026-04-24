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
        test-shell compose-check install-smoke \
        coverage quality ci clean \
        verify minitux-ps minitux-logs minitux-diag

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install-dev:  ## Install all dependencies (prod + dev)
	@# requirements-dev.txt has `-r requirements.txt` at the top, so
	@# installing it pulls in both sets in one invocation. Previously
	@# this target only installed requirements.txt, which meant PyYAML
	@# (needed by compose-check and several CI/CD test suites) was
	@# silently missing from the .venv.
	$(PIP) install -r requirements-dev.txt

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
	@bash tests/shell/test_install_sudo_delegation.sh
	@bash tests/shell/test_compose_env_substitution.sh
	@bash tests/shell/test_install_smoke_preflight.sh
	@bash tests/shell/test_install_mode_selection.sh
	@bash tests/shell/test_entrypoint_seed_admin.sh
	@bash tests/shell/test_ship_commit_push.sh
	@echo "All shell tests passed."

# ---------------------------------------------------------------------------
# compose-check — lightweight structural verification of docker-compose.prod.yml
# ---------------------------------------------------------------------------
# Runs the PyYAML-based test suite that pins the ENVIRONMENT / sslmode
# substitution contract in the api service block. Requires no Docker
# daemon — complements `make install-smoke`, which needs a live daemon.
#
# Use this on any machine (Mac laptop, CI sandbox, minitux) to verify the
# 2026-04-16 compose remediation is still intact before attempting a real
# deploy. This target is the recommended pre-flight check whenever a
# commit touches docker-compose.prod.yml.
# ---------------------------------------------------------------------------
compose-check:  ## Verify docker-compose.prod.yml substitution (no daemon needed)
	@bash tests/shell/test_compose_env_substitution.sh

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
	@# --- 0. Preflight: fail fast on environmental prerequisites ---
	@# The 2026-04-16 local run showed install-smoke silently declaring
	@# "All services healthy after 0s" when the daemon was down and no
	@# services had started. These two preflight checks stop the run at
	@# the earliest point where the fault is diagnosable, before the
	@# health-check loop has any chance to misinterpret an empty stack.
	@echo "[0/5] Preflight..."
	@if ! docker info >/dev/null 2>&1; then \
		echo "  FAIL: docker daemon is not reachable."; \
		echo "    Start Docker Desktop (macOS) or 'sudo systemctl start docker' (Linux)"; \
		echo "    and re-run 'make install-smoke'."; \
		exit 1; \
	fi
	@if [ ! -f .env ]; then \
		echo "  FAIL: .env is missing at $$(pwd)/.env"; \
		echo "    install-smoke simulates the post-install environment; it needs"; \
		echo "    the secrets install.sh would have written. Either run install.sh"; \
		echo "    first or seed a smoke .env:"; \
		echo "      cp .env.production.template .env"; \
		echo "      # then set POSTGRES_PASSWORD, JWT_SECRET_KEY, CORS_ALLOWED_ORIGINS"; \
		exit 1; \
	fi
	@for req in POSTGRES_PASSWORD JWT_SECRET_KEY CORS_ALLOWED_ORIGINS; do \
		val=$$(grep -E "^$${req}=" .env | head -1 | cut -d= -f2-); \
		if [ -z "$$val" ] || [ "$$val" = "CHANGE_ME" ]; then \
			echo "  FAIL: .env is missing required value: $$req"; \
			echo "    Edit $$(pwd)/.env and set $$req to a real value."; \
			exit 1; \
		fi; \
	done
	@echo "  OK: docker daemon reachable and .env has required values."
	@echo ""
	@# --- 1. Build and start ---
	@echo "[1/5] Building and starting production stack..."
	@$(SMOKE_COMPOSE) up -d --build 2>&1 | tail -5
	@echo ""
	@# --- 2. Wait for healthchecks ---
	@echo "[2/5] Waiting for services to become healthy (up to $(SMOKE_TIMEOUT)s)..."
	@# Drives the poll loop via scripts/smoke_health_eval.py (extracted
	@# 2026-04-20). The evaluator's exit codes are:
	@#   0 — all services healthy; break and proceed to probes.
	@#   1 — at least one service is in a terminal failure state
	@#       (restart-looping, exhausted, unhealthy, blocked, dead,
	@#       unexpected clean exit). Abort polling immediately — no
	@#       amount of waiting will recover.
	@#   2 — no terminal failures yet, but some services are still
	@#       starting. Sleep and retry.
	@# This replaces the previous Health-only one-liner which silently
	@# passed through State=restarting containers (the 2026-04-20
	@# cAdvisor crashloop bug). See tests/unit/test_smoke_health_eval.py
	@# for the contract.
	@elapsed=0; \
	while [ $$elapsed -lt $(SMOKE_TIMEOUT) ]; do \
		set +e; \
		$(SMOKE_COMPOSE) ps --all --format json 2>/dev/null | \
			python3 scripts/smoke_health_eval.py poll \
				--compose-file docker-compose.prod.yml; \
		verdict=$$?; \
		set -e; \
		if [ $$verdict -eq 0 ]; then \
			echo "  All services healthy after $${elapsed}s."; \
			break; \
		fi; \
		if [ $$verdict -eq 1 ]; then \
			echo ""; \
			echo "  FAIL: terminal failure detected after $${elapsed}s — further waiting will not recover."; \
			$(SMOKE_COMPOSE) ps; \
			echo ""; \
			echo "Failing service logs (with flag-parse scan):"; \
			$(SMOKE_COMPOSE) ps --format json 2>/dev/null | \
				python3 -c "import sys,json; [print(json.loads(l).get('Service','')) for l in sys.stdin if l.strip() and json.loads(l).get('State','').lower() != 'running']" 2>/dev/null | \
				while read svc; do \
					echo "--- $$svc ---"; \
					logs=$$($(SMOKE_COMPOSE) logs --tail=60 "$$svc" 2>/dev/null); \
					echo "$$logs" | tail -60; \
					echo ""; \
					echo "  [smoke-eval] scanning $$svc logs for flag-parse failure..."; \
					echo "$$logs" | python3 scripts/smoke_health_eval.py scan-logs || true; \
				done; \
			$(SMOKE_COMPOSE) down --timeout 10 2>/dev/null || true; \
			exit 1; \
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

# ---------------------------------------------------------------------------
# Claude operational envelope (Tranche G — 2026-04-24)
# ---------------------------------------------------------------------------
# The targets below are the ONLY operations Claude (running in the
# Cowork sandbox on the dev Mac) is permitted to invoke autonomously
# against remote state. They are strictly read-only: `ssh` is used
# only to fetch diagnostic output, never to mutate. The shell tests
# in tests/shell/test_make_minitux_safety.sh lock this envelope and
# FAIL if any of these recipes is modified to include a mutating
# command (sudo, docker rm/stop/kill/restart, systemctl, etc.).
#
# See CLAUDE.md §17 for the full capability contract.
# ---------------------------------------------------------------------------

# verify — fast local pre-commit gate. Safe for Claude to run after
# every code change without operator approval. Chains the same checks
# the pre-commit hook enforces so regressions are caught before they
# reach a branch push.
verify: format-check lint test-unit compose-check  ## Run local pre-commit gate (safe for Claude to invoke autonomously)

# ---------------------------------------------------------------------------
# minitux read-only diagnostics
# ---------------------------------------------------------------------------
# Prerequisites: the operator must have an SSH alias for the minitux
# host configured in ~/.ssh/config. Default alias is "minitux".
# Override with MINITUX_SSH_ALIAS=... on the make command line.
#
#   Host minitux
#       HostName 192.168.1.5
#       User gjohnson
#       IdentityFile ~/.ssh/id_ed25519
#
# Connection is read-only — these targets never invoke sudo, and the
# remote docker commands are strictly ps / logs (no write subcommands).
MINITUX_SSH_ALIAS      ?= minitux
# install.sh deploys the full fxlab tree to /opt/fxlab on the target
# host (FXLAB_HOME default). Both the compose file and scripts/ live
# underneath this root. Override with
#   make minitux-ps MINITUX_INSTALL_DIR=/some/other/path
# if the operator ran install.sh with a non-default FXLAB_HOME.
MINITUX_INSTALL_DIR    ?= /opt/fxlab
MINITUX_COMPOSE_FILE   ?= $(MINITUX_INSTALL_DIR)/docker-compose.prod.yml
MINITUX_SMOKE_EVAL     ?= $(MINITUX_INSTALL_DIR)/scripts/smoke_health_eval.py
MINITUX_LOG_TAIL       ?= 100

# Allowed SERVICE values — docker-compose service-name convention:
# lowercase letters, digits, dashes, underscores. Rejects shell
# metachars (;, |, &, `, $, etc.) that could enable remote shell
# injection through the SERVICE= make variable.
_VALID_SERVICE_NAME_RE := ^[a-z][a-z0-9_-]*$$

minitux-ps:  ## Read-only ssh: docker compose ps on minitux (Claude-safe)
	@ssh $(MINITUX_SSH_ALIAS) "docker compose -f $(MINITUX_COMPOSE_FILE) ps --format json"

minitux-logs:  ## Read-only ssh: docker compose logs --tail=N SERVICE (requires SERVICE=)
	@if [ -z "$(SERVICE)" ]; then \
		echo "usage: make minitux-logs SERVICE=<service-name> [MINITUX_LOG_TAIL=N]"; \
		echo ""; \
		echo "SERVICE must be one of the services declared in docker-compose.prod.yml"; \
		echo "(e.g. api, postgres, redis, nginx, web, prometheus, alertmanager,"; \
		echo " node-exporter, cadvisor, postgres-exporter, redis-exporter)."; \
		exit 2; \
	fi
	@echo "$(SERVICE)" | grep -qE '$(_VALID_SERVICE_NAME_RE)' || { \
		echo "error: SERVICE='$(SERVICE)' is not a valid docker-compose service name."; \
		echo "Allowed: lowercase letters, digits, dashes, underscores (must start with letter)."; \
		echo "Shell metacharacters rejected to prevent remote injection."; \
		exit 2; \
	}
	@ssh $(MINITUX_SSH_ALIAS) "docker compose -f $(MINITUX_COMPOSE_FILE) logs --tail=$(MINITUX_LOG_TAIL) $(SERVICE)"

minitux-diag:  ## Read-only ssh: diagnostic bundle (ps + every service's tail) (Claude-safe)
	@echo "=== minitux diagnostic bundle ==="
	@echo ""
	@echo "--- docker compose ps ---"
	@ssh $(MINITUX_SSH_ALIAS) "docker compose -f $(MINITUX_COMPOSE_FILE) ps"
	@echo ""
	@echo "--- smoke-eval verdict ---"
	@ssh $(MINITUX_SSH_ALIAS) "docker compose -f $(MINITUX_COMPOSE_FILE) ps --all --format json | python3 $(MINITUX_SMOKE_EVAL) poll --compose-file $(MINITUX_COMPOSE_FILE) || true"

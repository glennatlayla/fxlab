#!/usr/bin/env bash
# =============================================================================
# Shell tests: entrypoint.sh seed_admin integration
#
# Validates that entrypoint.sh invokes the seed_admin CLI tool after
# migrations and before starting the API server. These are static
# analysis tests — they parse the entrypoint script without running it.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENTRYPOINT="$REPO_ROOT/services/api/entrypoint.sh"

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== entrypoint.sh seed_admin integration tests ==="

# ---------------------------------------------------------------
# 1. Entrypoint calls seed_admin
# ---------------------------------------------------------------
if grep -q 'python -m services.api.cli.seed_admin' "$ENTRYPOINT"; then
    pass "entrypoint.sh invokes seed_admin CLI module"
else
    fail "entrypoint.sh does not invoke seed_admin CLI module"
fi

# ---------------------------------------------------------------
# 2. seed_admin runs AFTER migrations
# ---------------------------------------------------------------
migration_line=$(grep -n 'alembic upgrade head' "$ENTRYPOINT" | head -1 | cut -d: -f1)
seed_line=$(grep -n 'python -m services.api.cli.seed_admin' "$ENTRYPOINT" | head -1 | cut -d: -f1)

if [[ -n "$migration_line" && -n "$seed_line" ]]; then
    if (( seed_line > migration_line )); then
        pass "seed_admin runs after alembic migrations (line $seed_line > $migration_line)"
    else
        fail "seed_admin runs BEFORE alembic migrations (line $seed_line < $migration_line)"
    fi
else
    fail "could not find migration and/or seed_admin lines in entrypoint.sh"
fi

# ---------------------------------------------------------------
# 3. seed_admin runs BEFORE the API server starts
# ---------------------------------------------------------------
start_line=$(grep -n 'exec "\$@"' "$ENTRYPOINT" | head -1 | cut -d: -f1)

if [[ -n "$seed_line" && -n "$start_line" ]]; then
    if (( seed_line < start_line )); then
        pass "seed_admin runs before API server start (line $seed_line < $start_line)"
    else
        fail "seed_admin runs AFTER API server start (line $seed_line > $start_line)"
    fi
else
    fail "could not find seed_admin and/or exec lines in entrypoint.sh"
fi

# ---------------------------------------------------------------
# 4. seed_admin failure is non-fatal (does not exit 1)
# ---------------------------------------------------------------
# The seed_admin block should use an if-not pattern, not set -e abort.
# We check that the python command is inside an if block.
if grep -A1 'python -m services.api.cli.seed_admin' "$ENTRYPOINT" | grep -q 'then\|WARNING'; then
    pass "seed_admin failure is handled gracefully (non-fatal)"
else
    fail "seed_admin failure would abort the entrypoint (missing error handling)"
fi

# ---------------------------------------------------------------
# 5. Operator retry instructions printed on failure
# ---------------------------------------------------------------
if grep -q 'docker compose exec.*seed_admin' "$ENTRYPOINT"; then
    pass "entrypoint provides manual retry instructions on seed failure"
else
    fail "entrypoint does not provide retry instructions on seed failure"
fi

# ---------------------------------------------------------------
# 6. seed_admin.py exists as a runnable module
# ---------------------------------------------------------------
SEED_MODULE="$REPO_ROOT/services/api/cli/seed_admin.py"
if [[ -f "$SEED_MODULE" ]]; then
    pass "services/api/cli/seed_admin.py exists"
else
    fail "services/api/cli/seed_admin.py is missing"
fi

# ---------------------------------------------------------------
# 7. seed_admin.py has __main__ guard
# ---------------------------------------------------------------
if grep -q 'if __name__.*__main__' "$SEED_MODULE" 2>/dev/null; then
    pass "seed_admin.py has __main__ guard"
else
    fail "seed_admin.py is missing __main__ guard"
fi

# ---------------------------------------------------------------
# 8. install.sh print_summary extracts admin creds from container logs
# ---------------------------------------------------------------
INSTALL_SCRIPT="$REPO_ROOT/install.sh"
if grep -q 'FXLAB INITIAL ADMIN CREDENTIALS' "$INSTALL_SCRIPT"; then
    pass "install.sh print_summary extracts admin credentials from API logs"
else
    fail "install.sh print_summary does not extract admin credentials"
fi

# ---------------------------------------------------------------
# 9. install.sh shows manual seed command when creds not found
# ---------------------------------------------------------------
if grep -q 'python -m services.api.cli.seed_admin' "$INSTALL_SCRIPT"; then
    pass "install.sh provides manual seed_admin command in summary"
else
    fail "install.sh does not provide manual seed_admin fallback"
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed (total $((PASS + FAIL)))"

if (( FAIL > 0 )); then
    exit 1
fi
exit 0

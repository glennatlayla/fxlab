#!/usr/bin/env bash
# ===========================================================================
# Tests for docker-compose.prod.yml environment-variable substitution
# ===========================================================================
#
# Purpose:
#     Verify that docker-compose.prod.yml defers ENVIRONMENT-sensitive
#     values to .env (via ${VAR:-default} substitution) rather than
#     hardcoding them literally in the `api` service block.
#
# Why this matters:
#     The 2026-04-15 minitux CORS failure and the 2026-04-16 sslmode
#     failure share a root cause: docker-compose.prod.yml literally
#     embedded `ENVIRONMENT=production` and `?sslmode=prefer` in the
#     api service's `environment:` block. Those literals overrode the
#     values install.sh wrote into /opt/fxlab/.env — the api container
#     booted with ENVIRONMENT=production even when .env said
#     ENVIRONMENT=development. That defeated the Phase 3 LAN-detection
#     remediation entirely (the log line was truthful; the container
#     environment was not).
#
#     This test pins the compose file's substitution contract so the
#     regression cannot recur silently.
#
# Why parse YAML, not `docker compose config`:
#     docker is not universally available in the CI sandbox. We
#     validate the static compose file structure directly using PyYAML
#     (always available in the project's dev env per requirements.txt).
#     The `docker compose config` round-trip is exercised by
#     `make install-smoke`, which is a separate, heavier gate.
#
# Run:
#     bash tests/shell/test_compose_env_substitution.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
#     2 — setup error (compose file missing).
# ===========================================================================

set -uo pipefail

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · ${name}"
    if ( "$@" ); then
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$name")
    fi
}

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"

# ---------------------------------------------------------------------------
# Python resolver
#
# PyYAML is declared in requirements-dev.txt (not the system package set).
# On a macOS dev box the system `python3` typically does NOT have PyYAML
# and `pip install` against it is blocked by PEP 668. The project's
# `.venv/bin/python` is the canonical interpreter — it is where
# `make install-dev` lands every dependency. We prefer the venv
# interpreter if it exists and has PyYAML; fall back to `python3` only
# if it can import yaml; otherwise fail fast with actionable guidance.
# ---------------------------------------------------------------------------

resolve_python() {
    local venv_py="${REPO_ROOT}/.venv/bin/python"
    if [[ -x "$venv_py" ]] && "$venv_py" -c "import yaml" 2>/dev/null; then
        echo "$venv_py"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" 2>/dev/null; then
        echo "python3"
        return 0
    fi
    return 1
}

PYTHON="$(resolve_python || true)"

# ---------------------------------------------------------------------------
# Python YAML query helper
#
# We shell out to Python so each test is independent and self-explanatory.
# All helpers return exit code 0 on match, 1 on mismatch — suitable for
# direct use in `if ...; then`.
# ---------------------------------------------------------------------------

api_environment_entries() {
    # Print each entry of the api service's `environment:` list, one per line.
    "$PYTHON" - "$COMPOSE_FILE" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
api = data["services"]["api"]
env = api.get("environment", [])
# Compose accepts both list-of-strings and mapping. Normalise to list.
if isinstance(env, dict):
    for k, v in env.items():
        print(f"{k}={v}")
else:
    for item in env:
        print(item)
PY
}

api_build_args() {
    # Print each build arg as KEY=VALUE.
    "$PYTHON" - "$COMPOSE_FILE" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
api = data["services"]["api"]
build = api.get("build", {})
args = build.get("args", {}) if isinstance(build, dict) else {}
if isinstance(args, dict):
    for k, v in args.items():
        print(f"{k}={v}")
else:
    for item in args:
        print(item)
PY
}

# ---------------------------------------------------------------------------
# Tests — api service ENVIRONMENT propagation
# ---------------------------------------------------------------------------

test_api_environment_is_substituted_not_literal() {
    # The api service's environment block must use ${ENVIRONMENT:-...}
    # substitution, not a bare literal like `ENVIRONMENT=production`.
    local entries
    entries="$(api_environment_entries)"
    local env_line
    env_line="$(echo "$entries" | grep -E '^ENVIRONMENT=' || true)"

    if [[ -z "$env_line" ]]; then
        echo "    FAIL: api service has no ENVIRONMENT entry"
        echo "    entries seen:"
        echo "$entries" | sed 's/^/      /'
        return 1
    fi

    if [[ "$env_line" != *'${ENVIRONMENT'* ]]; then
        echo "    FAIL: api ENVIRONMENT is a literal, not a substitution"
        echo "      got:     ${env_line}"
        echo "      want:    ENVIRONMENT=\${ENVIRONMENT:-production}"
        return 1
    fi
}

test_api_environment_default_is_production() {
    # Substitution must supply a safe default — fail-safe production
    # if .env is missing or empty.
    local entries env_line
    entries="$(api_environment_entries)"
    env_line="$(echo "$entries" | grep -E '^ENVIRONMENT=' || true)"

    if [[ "$env_line" != *':-production}'* ]]; then
        echo "    FAIL: api ENVIRONMENT substitution missing ':-production' default"
        echo "      got: ${env_line}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Tests — api service DATABASE_URL sslmode propagation
# ---------------------------------------------------------------------------

test_api_database_url_sslmode_is_substituted() {
    # The DATABASE_URL sslmode parameter must be read from
    # ${POSTGRES_SSLMODE:-...}, not hardcoded.
    local entries db_line
    entries="$(api_environment_entries)"
    db_line="$(echo "$entries" | grep -E '^DATABASE_URL=' || true)"

    if [[ -z "$db_line" ]]; then
        echo "    FAIL: api service has no DATABASE_URL entry"
        return 1
    fi

    if [[ "$db_line" != *'sslmode=${POSTGRES_SSLMODE'* ]]; then
        echo "    FAIL: DATABASE_URL sslmode is hardcoded (should be \${POSTGRES_SSLMODE:-require})"
        echo "      got: ${db_line}"
        return 1
    fi
}

test_api_database_url_sslmode_default_is_strict() {
    # The sslmode substitution default MUST be a strict value
    # (require / verify-ca / verify-full) so a production deploy that
    # forgets to set POSTGRES_SSLMODE fails closed, not open.
    local entries db_line
    entries="$(api_environment_entries)"
    db_line="$(echo "$entries" | grep -E '^DATABASE_URL=' || true)"

    local ok=0
    for strict in "require" "verify-ca" "verify-full"; do
        if [[ "$db_line" == *":-${strict}}"* ]]; then
            ok=1
            break
        fi
    done
    if [[ $ok -ne 1 ]]; then
        echo "    FAIL: DATABASE_URL sslmode default is not strict (require/verify-ca/verify-full)"
        echo "      got: ${db_line}"
        return 1
    fi
}

test_api_database_url_does_not_contain_prefer_literal() {
    # Regression guard: the 2026-04-16 failure was sslmode=prefer
    # hardcoded in the DSN. Prove it is not back.
    local entries db_line
    entries="$(api_environment_entries)"
    db_line="$(echo "$entries" | grep -E '^DATABASE_URL=' || true)"

    if [[ "$db_line" == *"sslmode=prefer"* ]] \
       || [[ "$db_line" == *"sslmode=allow"* ]] \
       || [[ "$db_line" == *"sslmode=disable"* ]]; then
        echo "    FAIL: DATABASE_URL contains a literal weak sslmode"
        echo "      got: ${db_line}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Tests — api service build-arg ENVIRONMENT propagation
# ---------------------------------------------------------------------------

test_api_build_arg_environment_is_substituted() {
    # The Dockerfile uses ARG ENVIRONMENT=production / ENV ENVIRONMENT=$ENVIRONMENT
    # to bake the environment into the image for uvicorn --reload gating.
    # The build arg value must also come from .env, not a literal.
    local args env_arg
    args="$(api_build_args)"
    env_arg="$(echo "$args" | grep -E '^ENVIRONMENT=' || true)"

    if [[ -z "$env_arg" ]]; then
        # Absent is acceptable — the Dockerfile has `ARG ENVIRONMENT=production`
        # as its own default, which is safe. This test is informational in
        # that case; we do not fail.
        return 0
    fi

    if [[ "$env_arg" != *'${ENVIRONMENT'* ]]; then
        echo "    FAIL: api build-arg ENVIRONMENT is a literal, not a substitution"
        echo "      got:  ${env_arg}"
        echo "      want: ENVIRONMENT=\${ENVIRONMENT:-production}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Structural guards — whole-file scan for forbidden literals inside api block
# ---------------------------------------------------------------------------

test_compose_file_has_no_bare_environment_production_in_api() {
    # Walk the api service block only and assert no list entry is a
    # literal "ENVIRONMENT=production" (without any ${...} token).
    "$PYTHON" - "$COMPOSE_FILE" <<'PY' || exit 1
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
api_env = data["services"]["api"].get("environment", [])
if isinstance(api_env, dict):
    items = [f"{k}={v}" for k, v in api_env.items()]
else:
    items = list(api_env)
offenders = [
    item for item in items
    if item.startswith("ENVIRONMENT=") and "${" not in item
]
if offenders:
    print("    FAIL: found literal ENVIRONMENT entries in api service:")
    for o in offenders:
        print(f"      {o}")
    sys.exit(1)
sys.exit(0)
PY
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        echo "ERROR: docker-compose.prod.yml not found at ${COMPOSE_FILE}"
        exit 2
    fi
    if [[ -z "${PYTHON}" ]]; then
        echo "ERROR: No Python interpreter with PyYAML was found."
        echo ""
        echo "  The project venv is the canonical place for PyYAML. Install dev deps:"
        echo "    .venv/bin/pip install -r requirements-dev.txt"
        echo ""
        echo "  Or, if you want to use system python instead:"
        echo "    python3 -m pip install 'PyYAML>=6.0.0' --break-system-packages"
        echo ""
        echo "  Resolution order tried:"
        echo "    1. ${REPO_ROOT}/.venv/bin/python (preferred)"
        echo "    2. python3 on \$PATH (fallback)"
        exit 2
    fi
    echo "Using Python: ${PYTHON}"

    echo "docker-compose.prod.yml substitution test suite"
    echo "------------------------------------------------"

    run_test "api env: ENVIRONMENT uses \${...} substitution"         test_api_environment_is_substituted_not_literal
    run_test "api env: ENVIRONMENT default is 'production'"           test_api_environment_default_is_production
    run_test "api env: DATABASE_URL sslmode is substituted"           test_api_database_url_sslmode_is_substituted
    run_test "api env: DATABASE_URL sslmode default is strict"        test_api_database_url_sslmode_default_is_strict
    run_test "api env: DATABASE_URL has no literal weak sslmode"      test_api_database_url_does_not_contain_prefer_literal
    run_test "api build: ENVIRONMENT arg is substitution or absent"   test_api_build_arg_environment_is_substituted
    run_test "structural: no literal ENVIRONMENT= in api env list"    test_compose_file_has_no_bare_environment_production_in_api

    echo
    echo "------------------------------------------------"
    echo "Ran:    ${TESTS_RUN}"
    echo "Passed: ${TESTS_PASSED}"
    echo "Failed: ${TESTS_FAILED}"
    if [[ ${TESTS_FAILED} -gt 0 ]]; then
        echo
        echo "Failed tests:"
        for name in "${FAILED_TESTS[@]}"; do
            echo "  - ${name}"
        done
        exit 1
    fi
    exit 0
}

main "$@"

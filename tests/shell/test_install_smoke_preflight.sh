#!/usr/bin/env bash
# ===========================================================================
# Tests for `make install-smoke` preflight and health-check correctness
# ===========================================================================
#
# Purpose:
#     Pin two correctness properties of the install-smoke Makefile target
#     that were violated by the 2026-04-16 local run:
#
#       1. Preflight: if the docker daemon is unreachable or the .env file
#          is missing, install-smoke must fail fast with a clear diagnostic
#          — never proceed silently.
#
#       2. Health-check loop: if `docker compose ps --format json` returns
#          zero lines (daemon down, stack never started), the loop must NOT
#          classify that as "all services healthy". It must detect the
#          zero-services case and fail.
#
# Why this matters:
#     The 2026-04-16 output from the author's Mac showed:
#
#         unable to get image 'redis:7-alpine': Cannot connect to the
#         Docker daemon at unix:///...
#         [2/5] Waiting for services to become healthy (up to 90s)...
#           All services healthy after 0s.
#         [3/5] Probing service endpoints...
#           api /health: FAIL
#           postgres pg_isready: FAIL
#           redis ping: FAIL
#
#     "All services healthy after 0s" is a lie produced by the Python
#     sum-counter treating zero lines as zero unhealthy services. This
#     false-positive defeats the purpose of the smoke test.
#
# Why shell-native (no bats):
#     Matches the existing pattern in tests/shell/*.sh. We do not
#     actually invoke `make install-smoke` (it needs a docker daemon);
#     instead we assert the Makefile recipe contains the required
#     preflight and detection structure.
#
# Run:
#     bash tests/shell/test_install_smoke_preflight.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
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
MAKEFILE="${REPO_ROOT}/Makefile"

# Extract the install-smoke recipe body so each test grep'd region is scoped.
install_smoke_recipe() {
    # Awk extracts lines from 'install-smoke:' through the next rule or EOF.
    awk '
        /^install-smoke:/ { capturing = 1; print; next }
        capturing && /^[a-zA-Z_-]+:.*##/ { capturing = 0 }
        capturing && /^[a-zA-Z_-]+:[ \t]*$/ { capturing = 0 }
        capturing { print }
    ' "$MAKEFILE"
}

# ---------------------------------------------------------------------------
# Preflight tests
# ---------------------------------------------------------------------------

test_install_smoke_has_daemon_preflight() {
    # Must probe `docker info` (or equivalent) and exit non-zero with a
    # human-readable message if the daemon is unreachable.
    local recipe
    recipe="$(install_smoke_recipe)"

    if ! echo "$recipe" | grep -qE 'docker[[:space:]]+info'; then
        echo "    FAIL: install-smoke recipe does not probe 'docker info' to verify daemon reachability"
        return 1
    fi
}

test_install_smoke_has_env_file_preflight() {
    # Must check for .env and fail fast with a helpful message if absent.
    # The probe should be explicit — not rely on docker compose warnings.
    # Accepts both positive ([ -f .env ]) and negated ([ ! -f .env ]) forms,
    # as well as `test -f .env` / `test ! -f .env`.
    local recipe
    recipe="$(install_smoke_recipe)"

    if ! echo "$recipe" | grep -qE '(\[|test)[[:space:]]+(!?[[:space:]]*)?-[fsr][[:space:]]+\.env'; then
        echo "    FAIL: install-smoke recipe does not check for .env presence via [ -f .env ] / [ ! -f .env ] / test -f .env"
        return 1
    fi
}

test_install_smoke_daemon_check_is_early() {
    # The daemon probe must happen BEFORE `compose up` — otherwise the
    # up failure surfaces first and the false-positive loop runs on the
    # aftermath.
    local recipe
    recipe="$(install_smoke_recipe)"

    local info_line up_line
    info_line="$(echo "$recipe" | grep -nE 'docker[[:space:]]+info' | head -1 | cut -d: -f1)"
    up_line="$(echo "$recipe" | grep -nE '\$\(SMOKE_COMPOSE\)[[:space:]]+up' | head -1 | cut -d: -f1)"

    if [[ -z "$info_line" ]] || [[ -z "$up_line" ]]; then
        echo "    FAIL: could not locate both docker info and compose up lines"
        return 1
    fi

    if [[ "$info_line" -ge "$up_line" ]]; then
        echo "    FAIL: 'docker info' preflight runs at or after 'compose up' (info=$info_line up=$up_line)"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Health-check loop correctness
# ---------------------------------------------------------------------------

test_install_smoke_detects_zero_services() {
    # The loop must fail if compose reports zero services — not declare
    # "all healthy" based on a zero count of unhealthy entries.
    local recipe
    recipe="$(install_smoke_recipe)"

    # Evidence the recipe computes both a total count and unhealthy count.
    # We accept either a Python expression that emits two numbers, or an
    # explicit "len(lines)" / "total" variable comparison.
    if ! echo "$recipe" | grep -qE 'len\(lines\)|total[[:space:]]*=|services_seen'; then
        echo "    FAIL: health-check loop does not count total services (only counts unhealthy)"
        echo "    This leads to the 'healthy after 0s' false-positive when the daemon is down."
        return 1
    fi
}

test_install_smoke_total_zero_is_not_healthy() {
    # Specifically: a branch that treats total=0 as an error, not success.
    local recipe
    recipe="$(install_smoke_recipe)"

    if ! echo "$recipe" | grep -qE 'total.*=[[:space:]]*"?0"?|no[[:space:]]+services[[:space:]]+(running|found|started)'; then
        echo "    FAIL: no explicit branch detecting the zero-services case"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# compose-check target (new — lightweight substitution verification)
# ---------------------------------------------------------------------------

test_compose_check_target_exists() {
    # A new Make target must exist to let operators verify the compose
    # substitution contract without bringing up the full stack.
    if ! grep -qE '^compose-check:' "$MAKEFILE"; then
        echo "    FAIL: no 'compose-check' target in Makefile"
        return 1
    fi
}

test_compose_check_runs_substitution_test() {
    # The target must invoke the structural substitution test we already
    # ship — that is the authoritative verification that does not require
    # docker daemon or CLI.
    local start_line end_line body
    start_line="$(grep -nE '^compose-check:' "$MAKEFILE" | head -1 | cut -d: -f1)"
    if [[ -z "$start_line" ]]; then
        return 1   # Handled by test_compose_check_target_exists
    fi
    # Extract up to the next rule or EOF.
    body="$(awk -v s="$start_line" 'NR >= s {
        if (NR > s && /^[a-zA-Z_-]+:/) exit
        print
    }' "$MAKEFILE")"

    if ! echo "$body" | grep -qE 'test_compose_env_substitution\.sh'; then
        echo "    FAIL: compose-check target does not run test_compose_env_substitution.sh"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$MAKEFILE" ]]; then
        echo "ERROR: Makefile not found at ${MAKEFILE}"
        exit 2
    fi

    echo "install-smoke preflight & correctness test suite"
    echo "--------------------------------------------------"

    run_test "preflight: docker info daemon probe"                  test_install_smoke_has_daemon_preflight
    run_test "preflight: .env file existence check"                 test_install_smoke_has_env_file_preflight
    run_test "preflight: daemon check runs before compose up"       test_install_smoke_daemon_check_is_early
    run_test "health loop: counts total services, not just unhealthy" test_install_smoke_detects_zero_services
    run_test "health loop: zero-services branch fails explicitly"   test_install_smoke_total_zero_is_not_healthy
    run_test "compose-check: Make target exists"                    test_compose_check_target_exists
    run_test "compose-check: runs the substitution test suite"      test_compose_check_runs_substitution_test

    echo
    echo "--------------------------------------------------"
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

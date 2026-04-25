#!/usr/bin/env bash
# ===========================================================================
# Tests for the Makefile's local-host diagnostic targets (Tranche J —
# 2026-04-24).
# ===========================================================================
#
# Purpose:
#     Tranche G shipped `minitux-ps`, `minitux-logs`, and `minitux-diag` —
#     all of which ssh to a remote host. The 2026-04-24 evening session
#     showed the missing complement: when an operator is ALREADY on the
#     deploy host (e.g., ssh'd into minitux), running the minitux-* targets
#     fails because they try to ssh root@minitux from minitux itself.
#
#     Tranche J adds `logs SERVICE=<name>`, `ps`, and `diag` — local-only
#     targets that operate against the docker compose stack on the current
#     host. They share the same safety envelope as the minitux-* targets
#     (no sudo, no mutating docker ops, validated SERVICE=).
#
# Run:
#     bash tests/shell/test_make_local_diagnostics.sh
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

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected substring: ${needle}"
    echo "      actual (first 400) : ${haystack:0:400}"
    return 1
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" != *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      unwanted substring: ${needle}"
    echo "      actual (first 400): ${haystack:0:400}"
    return 1
}

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

#: Same forbidden-patterns list used by the other operator-safety tests.
FORBIDDEN_PATTERNS=(
    "sudo"
    "docker rm "
    "docker stop"
    "docker kill"
    "docker restart"
    "docker rmi"
    "docker volume rm"
    "docker system prune"
    "systemctl"
    "rm -"
    "rm /"
)

_expand_recipe() {
    local target="$1"
    shift
    ( cd "$PROJECT_ROOT" && make -n "$target" "$@" 2>&1 )
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_local_ps_uses_no_ssh() {
    local out
    out="$(_expand_recipe ps)"
    assert_contains "$out" "docker compose" "must invoke docker compose" || return 1
    assert_contains "$out" " ps" "must run the ps subcommand" || return 1
    assert_not_contains "$out" "ssh " "local ps must NEVER ssh" || return 1
    for bad in "${FORBIDDEN_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "local ps must not contain '${bad}'" || return 1
    done
}

test_local_logs_requires_service() {
    local out rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make logs 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: 'make logs' without SERVICE= should exit non-zero."
        echo "    output: ${out:0:400}"
        return 1
    fi
    assert_contains "$out" "SERVICE" \
        "usage error must name SERVICE= as required" || return 1
}

test_local_logs_uses_no_ssh() {
    local out
    out="$(_expand_recipe logs SERVICE=prometheus)"
    assert_contains "$out" "docker compose" "must invoke docker compose" || return 1
    assert_contains "$out" "logs" "must run the logs subcommand" || return 1
    assert_contains "$out" "--tail" "must cap log volume with --tail" || return 1
    assert_contains "$out" "prometheus" "must pass SERVICE through" || return 1
    assert_not_contains "$out" "ssh " "local logs must NEVER ssh" || return 1
    for bad in "${FORBIDDEN_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "local logs must not contain '${bad}'" || return 1
    done
}

test_local_logs_rejects_shell_injection_in_service_name() {
    local out rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make logs 'SERVICE=api; rm -rf /' 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: local 'make logs' should reject SERVICE with metachars."
        echo "    output: ${out:0:400}"
        return 1
    fi
    assert_contains "$out" "SERVICE" \
        "rejection message must reference SERVICE" || return 1
}

test_local_diag_uses_no_ssh_and_runs_smoke_eval() {
    local out
    out="$(_expand_recipe diag)"
    assert_contains "$out" "docker compose" "must invoke docker compose" || return 1
    assert_contains "$out" "smoke_health_eval.py" \
        "must invoke the smoke_health_eval evaluator" || return 1
    assert_contains "$out" "poll" "must use the poll subcommand" || return 1
    assert_not_contains "$out" "ssh " "local diag must NEVER ssh" || return 1
    for bad in "${FORBIDDEN_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "local diag must not contain '${bad}'" || return 1
    done
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "${PROJECT_ROOT}/Makefile" ]]; then
        echo "ERROR: Makefile not found at ${PROJECT_ROOT}/Makefile"
        exit 2
    fi

    echo "Makefile local-diagnostics test suite (Tranche J)"
    echo "-------------------------------------------------"

    run_test "local 'ps' invokes docker compose ps without ssh"             test_local_ps_uses_no_ssh
    run_test "local 'logs' fails loudly without SERVICE="                    test_local_logs_requires_service
    run_test "local 'logs SERVICE=X' invokes docker compose logs without ssh" test_local_logs_uses_no_ssh
    run_test "local 'logs' rejects SERVICE with shell metachars"             test_local_logs_rejects_shell_injection_in_service_name
    run_test "local 'diag' chains ps + smoke_health_eval without ssh"        test_local_diag_uses_no_ssh_and_runs_smoke_eval

    echo
    echo "-------------------------------------------------"
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

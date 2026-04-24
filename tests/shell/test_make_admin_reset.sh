#!/usr/bin/env bash
# ===========================================================================
# Tests for the Makefile's admin-reset helper (Tranche I — 2026-04-24).
# ===========================================================================
#
# Purpose:
#     The 2026-04-24 install-refresh run did not surface admin credentials
#     (by design: refresh preserves the existing admin, doesn't re-create).
#     An operator who has lost the admin password needs a single, approved
#     entrypoint to reset it — not a manual `docker compose exec …` rune.
#
#     Tranche I adds the `make admin-reset EMAIL=<address> [HOST=local|
#     minitux]` target. It wraps services/api/cli/reset_password so the
#     operator command is stable, validated, and documented in CLAUDE.md
#     §17 as requiring operator approval (it mutates user state).
#
#     The target MUST:
#       1. Fail loudly with a usage message when EMAIL= is missing — not
#          fall through to an ambiguous default.
#       2. Reject EMAIL values containing shell metachars (prevents
#          injection through `EMAIL='a@b.com; rm -rf /'`).
#       3. Construct the correct CLI invocation:
#             python -m services.api.cli.reset_password --email <EMAIL>
#          inside the api container.
#       4. Not contain sudo, nor mutating docker commands (rm/stop/kill/
#          restart), nor systemctl — matches the forbidden-patterns list
#          tested in test_make_minitux_safety.sh.
#       5. Honour HOST=minitux by routing the call through ssh to the
#          minitux deploy (read-only in every other way; only the api
#          CLI writes).
#
# Run:
#     bash tests/shell/test_make_admin_reset.sh
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

# Same forbidden-patterns list as test_make_minitux_safety.sh — keep the
# safety envelope consistent across all approved operator targets.
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

test_admin_reset_requires_email() {
    local out rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make admin-reset 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: admin-reset without EMAIL= should exit non-zero."
        echo "    output: ${out:0:400}"
        return 1
    fi
    assert_contains "$out" "EMAIL" \
        "usage error must name EMAIL= as required" || return 1
    assert_contains "$out" "admin-reset" \
        "usage message must name the target" || return 1
}

test_admin_reset_rejects_invalid_email_format() {
    # An EMAIL that doesn't look like an RFC-shape email (no @ or no TLD)
    # must be rejected BEFORE any docker/ssh is invoked.
    local out rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make admin-reset EMAIL=not-an-email 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: admin-reset should reject EMAIL without @ and TLD."
        echo "    output: ${out:0:400}"
        return 1
    fi
    assert_contains "$out" "EMAIL" \
        "rejection must reference EMAIL" || return 1
}

test_admin_reset_rejects_shell_injection_in_email() {
    # Shell metacharacters in EMAIL must be rejected before reaching
    # docker/ssh — protects against remote command injection via `EMAIL='a@b; rm -rf /'`.
    local out rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make admin-reset 'EMAIL=a@b.com; rm -rf /' 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: admin-reset should reject EMAIL containing shell metachars."
        echo "    output: ${out:0:400}"
        return 1
    fi
}

test_admin_reset_local_constructs_correct_cli_invocation() {
    local out
    out="$(_expand_recipe admin-reset EMAIL=admin@fxlab.io)"
    # Must use docker compose exec against the api service, invoking the
    # reset_password CLI with --email <EMAIL>. No other shape is
    # acceptable — the CLI is the single source of truth for password
    # reset policy (bcrypt cost, audit log entry, session invalidation).
    assert_contains "$out" "docker compose" \
        "local admin-reset must use docker compose" || return 1
    assert_contains "$out" "exec" \
        "must use exec subcommand (against running api container)" || return 1
    assert_contains "$out" " api " \
        "must target the api service by name" || return 1
    assert_contains "$out" "services.api.cli.reset_password" \
        "must call the documented reset_password CLI module" || return 1
    assert_contains "$out" "--email admin@fxlab.io" \
        "must pass EMAIL through as --email" || return 1
    assert_contains "$out" "-T" \
        "must use docker exec -T (no TTY) for non-interactive invocation" || return 1
}

test_admin_reset_minitux_routes_through_ssh() {
    local out
    out="$(_expand_recipe admin-reset EMAIL=admin@fxlab.io HOST=minitux)"
    assert_contains "$out" "ssh " \
        "HOST=minitux must invoke ssh" || return 1
    assert_contains "$out" "docker compose" \
        "must still use docker compose on the remote" || return 1
    assert_contains "$out" "services.api.cli.reset_password" \
        "must call the reset_password CLI on the remote" || return 1
    assert_contains "$out" "--email admin@fxlab.io" \
        "must pass EMAIL through to the remote invocation" || return 1
}

test_admin_reset_recipe_is_free_of_forbidden_patterns() {
    local out
    out="$(_expand_recipe admin-reset EMAIL=admin@fxlab.io)"
    for bad in "${FORBIDDEN_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "admin-reset must not contain '${bad}' (safety envelope)" || return 1
    done
}

test_admin_reset_minitux_recipe_is_free_of_forbidden_patterns() {
    local out
    out="$(_expand_recipe admin-reset EMAIL=admin@fxlab.io HOST=minitux)"
    for bad in "${FORBIDDEN_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "admin-reset HOST=minitux must not contain '${bad}'" || return 1
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

    echo "Makefile admin-reset test suite (Tranche I)"
    echo "-------------------------------------------"

    run_test "admin-reset fails loudly without EMAIL="                               test_admin_reset_requires_email
    run_test "admin-reset rejects EMAIL without @ and TLD"                           test_admin_reset_rejects_invalid_email_format
    run_test "admin-reset rejects EMAIL with shell metacharacters"                   test_admin_reset_rejects_shell_injection_in_email
    run_test "admin-reset local constructs correct reset_password CLI invocation"   test_admin_reset_local_constructs_correct_cli_invocation
    run_test "admin-reset HOST=minitux routes through ssh"                            test_admin_reset_minitux_routes_through_ssh
    run_test "admin-reset local recipe is free of forbidden patterns"                test_admin_reset_recipe_is_free_of_forbidden_patterns
    run_test "admin-reset minitux recipe is free of forbidden patterns"              test_admin_reset_minitux_recipe_is_free_of_forbidden_patterns

    echo
    echo "-------------------------------------------"
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

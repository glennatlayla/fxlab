#!/usr/bin/env bash
# ===========================================================================
# Tests for the Makefile's minitux-* and verify helper targets (Tranche G
# — 2026-04-24 operational-envelope hardening).
# ===========================================================================
#
# Purpose:
#     Tranche G adds Makefile helpers so Claude (running in the Cowork
#     sandbox on the dev Mac) can fetch diagnostics from minitux and
#     run the full local verification pipeline without manual round-
#     trips through the operator. The helpers are strictly READ-ONLY
#     against minitux — no sudo, no mutating docker commands, no shell
#     escapes.
#
#     This test suite locks that safety envelope by expanding each
#     recipe with `make -n` (dry-run) and asserting:
#
#       1. `make verify` chains the local pre-commit gate (format-check,
#          lint, test-unit, compose-check) and nothing else. An operator
#          reading this target must be able to trust that running it
#          never mutates remote state.
#
#       2. `make minitux-ps` produces an ssh invocation that runs
#          exactly `docker compose ... ps --format json` on the remote
#          — no write subcommands, no sudo.
#
#       3. `make minitux-logs SERVICE=<name>` produces an ssh invocation
#          that runs exactly `docker compose ... logs --tail=N <svc>` —
#          no write subcommands, no sudo, no shell injection (SERVICE
#          value is validated).
#
#       4. `make minitux-logs` without SERVICE= fails loudly with a
#          usage message — does NOT fall through to a dangerous default.
#
#       5. No minitux-* target contains any of: `sudo`, `rm `, `kill`,
#          `systemctl`, `docker rm`, `docker stop`, `docker kill`,
#          `docker restart`, `docker rmi`, `docker volume rm`,
#          `docker system prune`, `docker exec`. The allowlist is
#          tight and documented in CLAUDE.md §17.
#
# Why shell-native:
#     `make -n` is the natural way to capture an expanded recipe
#     without running it. The test is a pure string-matching exercise
#     on that output — no subprocess, no docker, no ssh.
#
# Run:
#     bash tests/shell/test_make_minitux_safety.sh
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

#: Patterns that must NEVER appear in any minitux-* recipe expansion.
#: Any match means the target could mutate remote state. The test
#: fails loudly with the specific pattern so the reviewer sees which
#: rule was violated.
FORBIDDEN_REMOTE_PATTERNS=(
    "sudo"
    "docker rm "
    "docker stop"
    "docker kill"
    "docker restart"
    "docker rmi"
    "docker volume rm"
    "docker system prune"
    "docker exec"
    "systemctl"
    "rm -"
    "rm /"
)

_expand_recipe() {
    # Run the Makefile target with -n (dry-run, don't execute).
    # Also silence stderr to avoid make's "no rule" noise cluttering
    # test output when the target doesn't exist yet (red phase).
    local target="$1"
    shift
    ( cd "$PROJECT_ROOT" && make -n "$target" "$@" 2>&1 )
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_verify_target_chains_local_gate() {
    local out
    out="$(_expand_recipe verify)"
    # verify must invoke each local gate — match on the actual
    # recipe commands that `make -n` emits (make -n expands targets
    # to their recipes, not to target names).
    assert_contains "$out" "ruff format --check" \
        "verify must run format-check (ruff format --check)" || return 1
    assert_contains "$out" "ruff check" \
        "verify must run lint (ruff check)" || return 1
    assert_contains "$out" "pytest tests/unit" \
        "verify must run test-unit (pytest tests/unit)" || return 1
    assert_contains "$out" "test_compose_env_substitution.sh" \
        "verify must run compose-check (compose-env-substitution shell test)" || return 1
    # verify must NOT touch remote state or push anything.
    for bad in "${FORBIDDEN_REMOTE_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "verify must not contain '${bad}' (local-only target)" || return 1
    done
    assert_not_contains "$out" "git push" "verify must never push" || return 1
    assert_not_contains "$out" "ssh " "verify must never ssh anywhere" || return 1
}

test_minitux_ps_uses_read_only_ssh() {
    local out
    out="$(_expand_recipe minitux-ps)"
    # Must invoke ssh against MINITUX_SSH_ALIAS (or the default alias).
    assert_contains "$out" "ssh"       "minitux-ps must invoke ssh" || return 1
    # Must run docker compose ps on the remote — nothing else.
    assert_contains "$out" "docker compose" "must invoke docker compose" || return 1
    assert_contains "$out" " ps"       "must run the ps subcommand" || return 1
    # No mutating commands or sudo.
    for bad in "${FORBIDDEN_REMOTE_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "minitux-ps must not contain '${bad}'" || return 1
    done
}

test_minitux_logs_requires_service_arg() {
    # Without SERVICE=, the target must emit a usage message and exit
    # non-zero. Falling through to `docker compose logs` with no filter
    # would dump every service's logs and could accidentally leak
    # secrets; fail fast with a clear message instead.
    local out
    local rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make minitux-logs 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: minitux-logs without SERVICE= should exit non-zero."
        echo "    output: ${out:0:400}"
        return 1
    fi
    assert_contains "$out" "SERVICE" \
        "usage error must name SERVICE= as required" || return 1
}

test_minitux_logs_uses_read_only_ssh() {
    local out
    out="$(_expand_recipe minitux-logs SERVICE=api)"
    assert_contains "$out" "ssh"       "minitux-logs must invoke ssh" || return 1
    assert_contains "$out" "docker compose" "must invoke docker compose" || return 1
    assert_contains "$out" "logs"      "must run the logs subcommand" || return 1
    assert_contains "$out" "--tail"    "must cap log volume with --tail" || return 1
    assert_contains "$out" "api"       "must pass SERVICE through to the remote command" || return 1
    for bad in "${FORBIDDEN_REMOTE_PATTERNS[@]}"; do
        assert_not_contains "$out" "$bad" \
            "minitux-logs must not contain '${bad}'" || return 1
    done
}

test_minitux_logs_rejects_shell_injection_in_service_name() {
    # A SERVICE= value containing shell metachars must be rejected
    # BEFORE it reaches ssh, otherwise remote shell injection is
    # possible. The Makefile target should validate the value.
    local out
    local rc
    set +e
    out="$( cd "$PROJECT_ROOT" && make minitux-logs 'SERVICE=api; rm -rf /' 2>&1 )"
    rc=$?
    set -e
    if (( rc == 0 )); then
        echo "    FAIL: minitux-logs should reject SERVICE with shell metachars."
        echo "    output: ${out:0:400}"
        return 1
    fi
    # The rejection must mention the invalid character / service name
    # so the operator knows why the command failed.
    assert_contains "$out" "SERVICE" \
        "rejection message must reference SERVICE" || return 1
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "${PROJECT_ROOT}/Makefile" ]]; then
        echo "ERROR: Makefile not found at ${PROJECT_ROOT}/Makefile"
        exit 2
    fi

    echo "Makefile minitux-safety test suite (Tranche G)"
    echo "----------------------------------------------"

    run_test "verify target chains the local pre-commit gate"               test_verify_target_chains_local_gate
    run_test "minitux-ps uses read-only ssh + docker compose ps"            test_minitux_ps_uses_read_only_ssh
    run_test "minitux-logs fails loudly without SERVICE="                    test_minitux_logs_requires_service_arg
    run_test "minitux-logs uses read-only ssh + docker compose logs"        test_minitux_logs_uses_read_only_ssh
    run_test "minitux-logs rejects shell metachars in SERVICE="             test_minitux_logs_rejects_shell_injection_in_service_name

    echo
    echo "----------------------------------------------"
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

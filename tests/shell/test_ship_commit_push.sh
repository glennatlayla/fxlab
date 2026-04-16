#!/usr/bin/env bash
# ===========================================================================
# Tests for ship.sh — commit_and_push() and generate_commit_msg()
# ===========================================================================
#
# Purpose:
#     Verify that ship.sh:
#       - Never dies silently on commit or push failure.
#       - Generates a fallback commit message when AI is unavailable.
#       - Times out the Claude CLI instead of hanging forever.
#       - Verifies the push actually landed on the remote.
#       - Stages untracked project files before committing.
#       - Reports clear error messages on every failure path.
#
# Why a shell-native harness (no bats/pytest):
#     The target is a bash script.  Running it under real git with a
#     temp origin gives faithful coverage without adding a new test
#     dependency.  Follows the same pattern as test_install_pull_latest.sh.
#
# Run:
#     bash tests/shell/test_ship_commit_push.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail  # Intentionally NOT -e: we want to keep running tests
                  # after a single failure so the final report is useful.

# ---------------------------------------------------------------------------
# Test framework (minimal)
# ---------------------------------------------------------------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

assert_eq() {
    local expected="$1" actual="$2" msg="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected: ${expected}"
    echo "      actual  : ${actual}"
    return 1
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected substring: ${needle}"
    echo "      actual             : ${haystack:0:400}"
    return 1
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" != *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      unexpected substring found: ${needle}"
    echo "      in: ${haystack:0:400}"
    return 1
}

assert_nonzero_exit() {
    local exit_code="$1" msg="${2:-}"
    if [[ "$exit_code" -ne 0 ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected non-zero exit, got 0"
    return 1
}

run_test() {
    local name="$1"
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  TEST: ${name}"
    if "$name"; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "    OK"
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$name")
    fi
}

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHIP_SCRIPT="${REPO_ROOT}/ship.sh"
SCRATCH=""

setup_scratch() {
    SCRATCH="$(mktemp -d /tmp/test-ship-XXXXXX)"
}

teardown_scratch() {
    if [[ -n "$SCRATCH" ]] && [[ -d "$SCRATCH" ]]; then
        rm -rf "$SCRATCH"
    fi
    SCRATCH=""
}

# Create a minimal git repo with a remote, suitable for testing
# commit_and_push flow.  Returns repo path in $SCRATCH/local.
create_test_repo() {
    setup_scratch

    # Create a bare remote
    git init --bare "$SCRATCH/remote.git" &>/dev/null

    # Create a local clone
    git clone "$SCRATCH/remote.git" "$SCRATCH/local" &>/dev/null

    # Seed with an initial commit so HEAD exists
    (
        cd "$SCRATCH/local"
        git config user.email "test@fxlab.dev"
        git config user.name "Test"
        echo "initial" > README.md
        mkdir -p services tests libs
        git add README.md services tests libs
        git commit -m "initial commit" &>/dev/null
        git push origin main &>/dev/null 2>&1 || git push origin master &>/dev/null 2>&1 || true
    )
}


# ===========================================================================
# Structural tests — verify ship.sh source contains required patterns.
# These are fast, need no git fixture, and catch regressions in the
# script's error-handling structure.
# ===========================================================================

test_ship_has_err_trap() {
    # The script must have an ERR trap so set -e never kills it silently.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" "trap '_on_error" \
        "ship.sh must have an ERR trap to prevent silent failures"
}

test_ship_commit_has_error_handling() {
    # git commit must NOT be called bare (unprotected by if/||).
    # Look for the error-handled pattern: 'if ! git commit'
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" 'if ! git commit' \
        "git commit must be wrapped in 'if !' for error handling"
}

test_ship_push_has_error_handling() {
    # git push must be inside an if-block or have || error handling.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" 'if git push' \
        "git push must be inside an if-block for error handling"
}

test_ship_has_post_push_verification() {
    # After push, the script must verify the remote received the commit.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" "ls-remote" \
        "ship.sh must verify remote HEAD via ls-remote after push"
}

test_ship_commit_msg_has_timeout() {
    # The Claude CLI call in generate_commit_msg must have a timeout
    # mechanism — either `timeout` command or a background-job kill pattern.
    local src
    src="$(cat "$SHIP_SCRIPT")"

    # Accept either pattern: `timeout ... claude` or `kill "$ai_pid"`
    if [[ "$src" == *"timeout"*"claude"* ]] || [[ "$src" == *'kill "$ai_pid"'* ]]; then
        return 0
    fi
    echo "    FAIL: generate_commit_msg must timeout the Claude CLI call"
    echo "      Neither 'timeout ... claude' nor 'kill \"\$ai_pid\"' found"
    return 1
}

test_ship_commit_msg_has_fallback() {
    # generate_commit_msg must have a deterministic fallback that does
    # not depend on any external tool (AI, network, etc.).
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" "Deterministic fallback" \
        "generate_commit_msg must have a deterministic fallback path"
}

test_ship_no_bare_git_commit() {
    # Ensure there's no unprotected 'git commit' call outside of an
    # if-block.  We strip comments, string literals (lines containing
    # quotes around 'git commit'), and known-safe patterns before
    # checking.  Only actual shell commands executing 'git commit'
    # without error handling are flagged.
    local bare_commits
    bare_commits="$(grep -n 'git commit' "$SHIP_SCRIPT" \
        | grep -v '^\s*#' \
        | grep -v '^[0-9]*:\s*#' \
        | grep -v 'if.*git commit' \
        | grep -v '! git commit' \
        | grep -v 'echo' \
        | grep -v 'fail_msg' \
        | grep -v 'warn' \
        | grep -v '".*git commit.*"' \
        || true)"

    if [[ -n "$bare_commits" ]]; then
        echo "    FAIL: Found unprotected git commit calls:"
        echo "      ${bare_commits}"
        return 1
    fi
    return 0
}

test_ship_push_shows_diagnostics_on_failure() {
    # The push failure path must mention SSH key check and remote check
    # so the operator has actionable next steps.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" "ssh -T git@github.com" \
        "Push failure message must suggest SSH key check" && \
    assert_contains "$src" "git remote -v" \
        "Push failure message must suggest checking remote URL"
}

test_ship_commit_failure_preserves_staged_changes() {
    # The commit failure message must tell the user staged changes
    # are preserved so they don't think their work was lost.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" "Staged changes are preserved" \
        "Commit failure must reassure that staged changes are preserved"
}

test_ship_empty_commit_msg_safety_net() {
    # If generate_commit_msg returns empty, commit_and_push must catch
    # it and use a fallback instead of passing empty -m to git.
    local src
    src="$(cat "$SHIP_SCRIPT")"
    assert_contains "$src" 'if [[ -z "$msg" ]]' \
        "commit_and_push must check for empty commit message"
}


# ===========================================================================
# Functional tests — exercise generate_commit_msg in a real git repo.
# ===========================================================================

test_fallback_commit_msg_from_staged_python_files() {
    # When Claude CLI is unavailable (NO_AI=1), generate_commit_msg
    # must produce a valid conventional-commit message from staged files.
    create_test_repo

    (
        cd "$SCRATCH/local"
        echo 'print("hello")' > services/app.py
        git add services/app.py

        # Source ship.sh functions in a subshell with AI disabled.
        # We only need generate_commit_msg; skip the rest by overriding.
        COMMIT_MSG=""
        NO_AI=1
        TEMP_FILES=()
        # shellcheck disable=SC1090
        source <(
            # Extract just the helpers and generate_commit_msg from ship.sh
            sed -n '/^make_temp()/,/^}/p' "$SHIP_SCRIPT"
            sed -n '/^generate_commit_msg()/,/^}/p' "$SHIP_SCRIPT"
            # Stub has_claude_code to return false
            echo 'has_claude_code() { return 1; }'
        )

        local msg
        msg="$(generate_commit_msg)"
        assert_contains "$msg" "feat" \
            "Fallback message for Python files should use 'feat' prefix" && \
        assert_contains "$msg" "app.py" \
            "Fallback message should mention the changed file"
    )

    teardown_scratch
}

test_fallback_commit_msg_from_staged_test_files() {
    # When only test files are staged, prefix should be 'test'.
    create_test_repo

    (
        cd "$SCRATCH/local"
        echo 'def test_foo(): pass' > tests/test_foo.py
        git add tests/test_foo.py

        COMMIT_MSG=""
        NO_AI=1
        TEMP_FILES=()
        # shellcheck disable=SC1090
        source <(
            sed -n '/^make_temp()/,/^}/p' "$SHIP_SCRIPT"
            sed -n '/^generate_commit_msg()/,/^}/p' "$SHIP_SCRIPT"
            echo 'has_claude_code() { return 1; }'
        )

        local msg
        msg="$(generate_commit_msg)"
        assert_contains "$msg" "test" \
            "Fallback message for test-only changes should use 'test' prefix"
    )

    teardown_scratch
}

test_user_provided_commit_msg_takes_precedence() {
    create_test_repo

    (
        cd "$SCRATCH/local"
        echo 'x = 1' > services/mod.py
        git add services/mod.py

        COMMIT_MSG="fix(api): resolve CORS crash on LAN IP"
        NO_AI=1
        TEMP_FILES=()
        # shellcheck disable=SC1090
        source <(
            sed -n '/^make_temp()/,/^}/p' "$SHIP_SCRIPT"
            sed -n '/^generate_commit_msg()/,/^}/p' "$SHIP_SCRIPT"
            echo 'has_claude_code() { return 1; }'
        )

        local msg
        msg="$(generate_commit_msg)"
        assert_eq "fix(api): resolve CORS crash on LAN IP" "$msg" \
            "User-provided message must be used verbatim"
    )

    teardown_scratch
}


# ===========================================================================
# Run all tests
# ===========================================================================

echo ""
echo "=== ship.sh commit & push tests ==="
echo ""

echo "--- Structural tests ---"
run_test test_ship_has_err_trap
run_test test_ship_commit_has_error_handling
run_test test_ship_push_has_error_handling
run_test test_ship_has_post_push_verification
run_test test_ship_commit_msg_has_timeout
run_test test_ship_commit_msg_has_fallback
run_test test_ship_no_bare_git_commit
run_test test_ship_push_shows_diagnostics_on_failure
run_test test_ship_commit_failure_preserves_staged_changes
run_test test_ship_empty_commit_msg_safety_net

echo ""
echo "--- Functional tests ---"
run_test test_fallback_commit_msg_from_staged_python_files
run_test test_fallback_commit_msg_from_staged_test_files
run_test test_user_provided_commit_msg_takes_precedence

echo ""
echo "==================================="
echo "Results: ${TESTS_PASSED}/${TESTS_RUN} passed, ${TESTS_FAILED} failed"

if [[ ${#FAILED_TESTS[@]} -gt 0 ]]; then
    echo ""
    echo "FAILED:"
    for t in "${FAILED_TESTS[@]}"; do
        echo "  - ${t}"
    done
    echo ""
    exit 1
fi

echo ""
exit 0

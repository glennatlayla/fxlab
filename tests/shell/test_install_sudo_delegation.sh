#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh privilege-delegation helpers
# ===========================================================================
#
# Purpose:
#     Verify that the 2026-04-16 SSH/sudo remediation correctly
#     delegates git and ssh operations to $SUDO_USER when install.sh
#     is invoked via sudo. These tests cover the two helpers added
#     to install.sh (_as_operator and _ensure_operator_owned) and
#     their integration into pull_latest(), clone_repo(), and
#     check_github_access().
#
#     Why the integration matters:
#
#       fxlab-reinstall.sh clones the repo as the operator (who owns
#       the GitHub SSH key), then invokes `sudo bash install.sh`.
#       Under sudo, the effective user is root with /root/.ssh empty.
#       Bare `git fetch` against an SSH remote therefore fails with
#       "Permission denied (publickey)" and aborts the installer.
#       _as_operator drops privileges to $SUDO_USER so the fetch
#       authenticates with the operator's key.
#
# Why a shell-native harness (no bats):
#     Same pattern as test_install_pull_latest.sh. The target is a
#     bash function; shadowing `sudo` with a shell function lets us
#     assert on the exact command line the installer would execute,
#     without requiring real sudo or real SSH.
#
# Run:
#     bash tests/shell/test_install_sudo_delegation.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# Test framework (minimal) — same pattern as sibling shell tests.
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
    echo "      unwanted substring found: ${needle}"
    echo "      in: ${haystack:0:400}"
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

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

INSTALL_SH="$(cd "$(dirname "$0")/../.." && pwd)/install.sh"

setup_scratch() {
    SCRATCH_ROOT="$(mktemp -d)"
    export FXLAB_HOME="${SCRATCH_ROOT}/work"
    export LOG_FILE="${SCRATCH_ROOT}/install.log"
    touch "$LOG_FILE"
    mkdir -p "$FXLAB_HOME"
}

teardown_scratch() {
    [[ -n "${SCRATCH_ROOT:-}" ]] && [[ -d "${SCRATCH_ROOT:-}" ]] && rm -rf "$SCRATCH_ROOT"
    SCRATCH_ROOT=""
}

source_install_sh() {
    # shellcheck disable=SC1090
    source "$INSTALL_SH"
}

# Build a sudo() shell function that echoes the command line instead
# of actually executing. Writes each invocation to $SCRATCH_ROOT/sudo.log
# so assertions can inspect the exact argv passed.
install_sudo_spy() {
    # shellcheck disable=SC2317  # used after shadowing
    sudo() {
        echo "SUDO_CALL: $*" >> "${SCRATCH_ROOT}/sudo.log"
        # Strip the `-u <user> -H env HOME=<home>` prefix and execute
        # the residual command directly so _as_operator's return
        # value behaves the same as real sudo. We accept both the
        # `-u USER -H env HOME=...` layout used by _as_operator and
        # bare `-u USER cmd...` as a simpler fallback.
        local args=("$@")
        local i=0
        # Skip `-u USER`
        if [[ "${args[$i]:-}" == "-u" ]]; then
            i=$((i + 2))
        fi
        # Skip `-H`
        if [[ "${args[$i]:-}" == "-H" ]]; then
            i=$((i + 1))
        fi
        # Skip `env HOME=<home>`
        if [[ "${args[$i]:-}" == "env" ]]; then
            i=$((i + 1))
            # Skip any VAR=VALUE pairs
            while [[ "${args[$i]:-}" == *"="* ]]; do
                i=$((i + 1))
            done
        fi
        # Execute residual argv
        "${args[@]:$i}"
    }
    # `command -v` must report the function so _as_operator's guard
    # passes. Defining the function achieves this automatically.
    export -f sudo 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# _as_operator — core delegation behaviour
# ---------------------------------------------------------------------------

test_as_operator_passthrough_when_sudo_user_unset() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    unset SUDO_USER 2>/dev/null || true
    source_install_sh
    install_sudo_spy

    # With SUDO_USER unset, _as_operator must NOT invoke sudo — it
    # should call the command directly so plain-user installs keep
    # working exactly as before.
    local out
    out="$(_as_operator echo hello-plain 2>&1)"
    assert_eq "hello-plain" "$out" "direct execution when SUDO_USER unset" || return 1

    # sudo.log must not exist or be empty.
    if [[ -s "${SCRATCH_ROOT}/sudo.log" ]]; then
        echo "    FAIL: sudo was invoked but SUDO_USER was unset"
        echo "      sudo.log: $(cat "${SCRATCH_ROOT}/sudo.log")"
        return 1
    fi
    return 0
}

test_as_operator_passthrough_when_sudo_user_is_root() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    export SUDO_USER="root"
    source_install_sh
    install_sudo_spy

    # SUDO_USER=root is semantically the same as no delegation
    # (root already has full privileges and no key to delegate to).
    local out
    out="$(_as_operator echo hello-root 2>&1)"
    assert_eq "hello-root" "$out" "direct execution when SUDO_USER=root" || return 1

    if [[ -s "${SCRATCH_ROOT}/sudo.log" ]]; then
        echo "    FAIL: sudo was invoked but SUDO_USER=root"
        return 1
    fi
    return 0
}

test_as_operator_delegates_when_sudo_user_set() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    # Pick a user whose home directory actually exists in the sandbox.
    # Using the current user is the most reliable cross-env choice.
    local real_user real_home
    real_user="$(id -un)"
    real_home="$(getent passwd "$real_user" | cut -d: -f6)"
    [[ -n "$real_home" && -d "$real_home" ]] || {
        echo "    SKIP: cannot resolve home for ${real_user}"
        return 0
    }

    export SUDO_USER="$real_user"
    source_install_sh
    install_sudo_spy

    local out
    out="$(_as_operator echo delegated-ok 2>&1)"
    assert_eq "delegated-ok" "$out" "delegated command must still produce output" || return 1

    local sudo_log
    sudo_log="$(cat "${SCRATCH_ROOT}/sudo.log" 2>/dev/null || echo "")"
    assert_contains "$sudo_log" "-u ${real_user}" \
        "sudo must be invoked with -u \$SUDO_USER" || return 1
    assert_contains "$sudo_log" "HOME=${real_home}" \
        "sudo must preserve operator HOME for SSH key discovery" || return 1
    assert_contains "$sudo_log" "echo delegated-ok" \
        "sudo argv must end with the delegated command" || return 1
    return 0
}

test_as_operator_propagates_exit_code() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    unset SUDO_USER 2>/dev/null || true
    source_install_sh

    # Direct (non-sudo) path must return the command's exit code.
    _as_operator bash -c 'exit 42'
    local rc=$?
    assert_eq 42 "$rc" "non-sudo path must propagate exit code" || return 1

    # Delegated path must too.
    local real_user
    real_user="$(id -un)"
    export SUDO_USER="$real_user"
    install_sudo_spy

    _as_operator bash -c 'exit 17'
    rc=$?
    assert_eq 17 "$rc" "delegated path must propagate exit code" || return 1
    return 0
}

test_operator_home_resolves_current_user() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    local real_user real_home
    real_user="$(id -un)"
    real_home="$(getent passwd "$real_user" | cut -d: -f6)"

    export SUDO_USER="$real_user"
    source_install_sh

    local resolved
    resolved="$(_operator_home)"
    assert_eq "$real_home" "$resolved" "_operator_home should resolve current user's home" || return 1
    return 0
}

test_operator_home_empty_when_sudo_user_unset() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    unset SUDO_USER 2>/dev/null || true
    source_install_sh

    local resolved
    resolved="$(_operator_home)"
    assert_eq "" "$resolved" "_operator_home should be empty when SUDO_USER unset" || return 1
    return 0
}

test_operator_home_empty_for_unknown_user() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    export SUDO_USER="fxlab-test-nonexistent-user-${RANDOM}"
    source_install_sh

    local resolved
    resolved="$(_operator_home)"
    assert_eq "" "$resolved" "_operator_home must be empty for unknown user" || return 1
    return 0
}

# ---------------------------------------------------------------------------
# _ensure_operator_owned — ownership-sync behaviour
# ---------------------------------------------------------------------------

test_ensure_operator_owned_noop_when_sudo_user_unset() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    unset SUDO_USER 2>/dev/null || true
    source_install_sh

    # Shadow chown so we can detect any invocation.
    local chown_log="${SCRATCH_ROOT}/chown.log"
    chown() {
        echo "CHOWN: $*" >> "$chown_log"
        command chown "$@"
    }

    _ensure_operator_owned
    if [[ -s "$chown_log" ]]; then
        echo "    FAIL: chown was called but SUDO_USER is unset"
        return 1
    fi
    return 0
}

test_ensure_operator_owned_noop_when_already_correct() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    local real_user real_uid
    real_user="$(id -un)"
    real_uid="$(id -u)"

    export SUDO_USER="$real_user"
    # Ensure the tree is owned by $real_user (it is — we just created it).
    mkdir -p "${FXLAB_HOME}/.git"

    source_install_sh

    local chown_log="${SCRATCH_ROOT}/chown.log"
    chown() {
        echo "CHOWN: $*" >> "$chown_log"
        command chown "$@"
    }

    _ensure_operator_owned
    if [[ -s "$chown_log" ]]; then
        echo "    FAIL: chown fired despite tree already being operator-owned"
        echo "      chown.log: $(cat "$chown_log")"
        return 1
    fi
    return 0
}

test_ensure_operator_owned_noop_when_tree_missing() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    # Remove the tree we created in setup_scratch so the helper's
    # "directory does not exist" fast-path fires.
    rm -rf "$FXLAB_HOME"

    export SUDO_USER="$(id -un)"
    source_install_sh

    local chown_log="${SCRATCH_ROOT}/chown.log"
    chown() {
        echo "CHOWN: $*" >> "$chown_log"
        command chown "$@"
    }

    _ensure_operator_owned
    if [[ -s "$chown_log" ]]; then
        echo "    FAIL: chown fired against a nonexistent tree"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Structural tests — verify install.sh wires the helpers into the
# critical git/ssh operations. Defence-in-depth: if someone reverts
# the remediation these break loudly.
# ---------------------------------------------------------------------------

test_source_pull_latest_uses_as_operator_for_fetch() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    # Extract pull_latest's body.
    local section
    section="$(awk '/^pull_latest\(\)/,/^}/' "$INSTALL_SH")"

    assert_contains "$section" "_as_operator git -C" \
        "pull_latest must call git via _as_operator (SSH/sudo remediation)" || return 1
    assert_contains "$section" "_as_operator git -C \"\$FXLAB_HOME\" fetch origin" \
        "pull_latest must delegate the fetch to the operator" || return 1
    assert_contains "$section" "_ensure_operator_owned" \
        "pull_latest must sync ownership before git ops" || return 1

    # Regression guard: no bare `git <cmd>` remaining in pull_latest
    # for the network/write operations that must be delegated. We
    # anchor the pattern to the start of the line (optionally via
    # `if` / `if !`) so we skip matches inside log/fail string
    # literals like `fail "git fetch ... FAILED"`.
    local bare_git
    bare_git="$(printf '%s\n' "$section" \
        | grep -Ev '^\s*#' \
        | grep -E '^\s*(if (! )?)?git (fetch|reset|stash|rev-parse|diff|log|config) ' \
        | grep -v '_as_operator' \
        || true)"
    if [[ -n "$bare_git" ]]; then
        echo "    FAIL: pull_latest has bare git invocations (must go via _as_operator):"
        echo "      $bare_git"
        return 1
    fi
    return 0
}

test_source_check_github_access_uses_as_operator_for_ssh() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    local section
    section="$(awk '/^check_github_access\(\)/,/^}/' "$INSTALL_SH")"

    assert_contains "$section" "_as_operator ssh" \
        "check_github_access must delegate the SSH probe via _as_operator" || return 1
    # No bare `ssh -T git@github.com` remaining.
    local bare_ssh
    bare_ssh="$(printf '%s\n' "$section" | grep -E '^\s*[^#]*(^|[^_a-zA-Z0-9])ssh ' | grep -v '_as_operator' | grep -v 'ssh-keygen' | grep -v 'ssh-add' | grep -v 'sudo -u' || true)"
    if [[ -n "$bare_ssh" ]]; then
        echo "    FAIL: check_github_access has bare ssh invocations:"
        echo "      $bare_ssh"
        return 1
    fi
    return 0
}

test_source_clone_repo_uses_as_operator_under_sudo() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    local section
    section="$(awk '/^clone_repo\(\)/,/^}/' "$INSTALL_SH")"

    assert_contains "$section" "_as_operator git clone" \
        "clone_repo must delegate the clone to the operator when under sudo" || return 1
    assert_contains "$section" "SUDO_USER" \
        "clone_repo must branch on SUDO_USER for pre-clone chown" || return 1
    return 0
}

test_source_fail_message_names_sudo_user_hint() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    # The redesigned failure message should no longer tell operators
    # to copy private keys to /root/.ssh — that was the anti-pattern
    # the remediation replaces.
    local section
    section="$(awk '/^pull_latest\(\)/,/^}/' "$INSTALL_SH")"

    assert_not_contains "$section" "cp -r /home/\$SUDO_USER/.ssh /root" \
        "pull_latest must not recommend copying keys to /root (anti-pattern)" || return 1
    assert_contains "$section" "ssh -T git@github.com" \
        "pull_latest failure should guide user to validate their own SSH key" || return 1
    return 0
}

# ---------------------------------------------------------------------------
# End-to-end test against a local git fixture.
# Confirms pull_latest works when SUDO_USER points at the invoking user —
# mirroring the minitux scenario where `sudo bash install.sh` delegates
# to the operator who owns the repo.
# ---------------------------------------------------------------------------

test_pull_latest_end_to_end_with_sudo_user() {
    setup_scratch
    trap 'teardown_scratch' RETURN

    # Build a real origin + work fixture (same pattern as
    # test_install_pull_latest.sh::make_fixture).
    git init --bare --initial-branch=main "${SCRATCH_ROOT}/origin.git" >/dev/null 2>&1
    git init --initial-branch=main "${SCRATCH_ROOT}/seed" >/dev/null 2>&1
    (
        cd "${SCRATCH_ROOT}/seed"
        git config user.email "test@example.com"
        git config user.name "Test"
        echo "v1" > README.md
        git add README.md
        git commit -m "initial" >/dev/null 2>&1
        git remote add origin "${SCRATCH_ROOT}/origin.git"
        git push -u origin main >/dev/null 2>&1
    )
    rm -rf "$FXLAB_HOME"
    git clone "${SCRATCH_ROOT}/origin.git" "$FXLAB_HOME" >/dev/null 2>&1
    (
        cd "$FXLAB_HOME"
        git config user.email "test@example.com"
        git config user.name "Test"
    )

    # Advance origin so pull_latest has a new SHA to fetch.
    (
        cd "${SCRATCH_ROOT}/seed"
        echo "v2" >> README.md
        git add README.md
        git commit -m "advance" >/dev/null 2>&1
        git push origin main >/dev/null 2>&1
    )

    export FXLAB_BRANCH="main"
    export SUDO_USER="$(id -un)"
    source_install_sh
    install_sudo_spy

    local output rc
    output="$(pull_latest 2>&1)"
    rc=$?

    local after_sha origin_sha
    after_sha="$(git -C "$FXLAB_HOME" rev-parse HEAD)"
    origin_sha="$(git -C "${SCRATCH_ROOT}/origin.git" rev-parse main)"

    assert_eq 0 "$rc" "pull_latest must succeed under simulated sudo delegation" || return 1
    assert_eq "$origin_sha" "$after_sha" "work HEAD must equal origin after delegated pull" || return 1

    # Confirm sudo was exercised (not bypassed).
    local sudo_log
    sudo_log="$(cat "${SCRATCH_ROOT}/sudo.log" 2>/dev/null || echo "")"
    assert_contains "$sudo_log" "git" \
        "delegated pull must have exercised the sudo wrapper" || return 1
    return 0
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi

    echo "install.sh sudo-delegation test suite"
    echo "-------------------------------------"

    run_test "_as_operator passthrough when SUDO_USER unset"        test_as_operator_passthrough_when_sudo_user_unset
    run_test "_as_operator passthrough when SUDO_USER=root"         test_as_operator_passthrough_when_sudo_user_is_root
    run_test "_as_operator delegates when SUDO_USER set"            test_as_operator_delegates_when_sudo_user_set
    run_test "_as_operator propagates exit codes"                   test_as_operator_propagates_exit_code
    run_test "_operator_home resolves current user"                 test_operator_home_resolves_current_user
    run_test "_operator_home empty when SUDO_USER unset"            test_operator_home_empty_when_sudo_user_unset
    run_test "_operator_home empty for unknown user"                test_operator_home_empty_for_unknown_user
    run_test "_ensure_operator_owned noop when SUDO_USER unset"     test_ensure_operator_owned_noop_when_sudo_user_unset
    run_test "_ensure_operator_owned noop when already correct"     test_ensure_operator_owned_noop_when_already_correct
    run_test "_ensure_operator_owned noop when tree missing"        test_ensure_operator_owned_noop_when_tree_missing
    run_test "source: pull_latest uses _as_operator for fetch"      test_source_pull_latest_uses_as_operator_for_fetch
    run_test "source: check_github_access uses _as_operator for ssh" test_source_check_github_access_uses_as_operator_for_ssh
    run_test "source: clone_repo uses _as_operator under sudo"      test_source_clone_repo_uses_as_operator_under_sudo
    run_test "source: fail message drops root-key anti-pattern"     test_source_fail_message_names_sudo_user_hint
    run_test "E2E: pull_latest with simulated sudo delegation"      test_pull_latest_end_to_end_with_sudo_user

    echo
    echo "-------------------------------------"
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

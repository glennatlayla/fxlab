#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh::pull_latest()
# ===========================================================================
#
# Purpose:
#     Verify that the hardened pull_latest() in install.sh:
#       - Refuses to silently deploy stale code when `git fetch` fails.
#       - Accepts FXLAB_ALLOW_STALE_CODE=1 as an explicit opt-in escape.
#       - Verifies the post-reset HEAD matches the fetched SHA.
#       - Logs the transition between SHAs.
#       - Preserves operator stashes across the update.
#
# Why a shell-native harness (no bats/pytest):
#     The target is a bash function. Running it under real git with a
#     temp origin gives faithful coverage without adding a new test
#     dependency to the repo. `bats` is not installed in the
#     production environment and we do not want to add it as a hard
#     prereq for running the installer's test suite.
#
# Run:
#     bash tests/shell/test_install_pull_latest.sh
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
    echo "      unwanted substring: ${needle}"
    echo "      actual            : ${haystack:0:400}"
    return 1
}

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · ${name}"
    # Each test runs in a subshell so that env changes, function
    # shadows, and `cd` calls don't leak between tests.
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

#: Directory containing install.sh — resolved relative to this test file
#: so it works no matter where the test runner invokes it from.
INSTALL_SH="$(cd "$(dirname "$0")/../.." && pwd)/install.sh"

make_fixture() {
    # Build a fresh origin+work git fixture and echo its root path.
    #   <root>/origin.git   — bare repo that `work` points to as origin
    #   <root>/work         — working clone that pull_latest() operates on
    #   <root>/install.log  — writable LOG_FILE for the installer's logger
    local root
    root="$(mktemp -d)"

    git init --bare --initial-branch=main "${root}/origin.git" >/dev/null 2>&1
    git init --initial-branch=main "${root}/seed" >/dev/null 2>&1
    (
        cd "${root}/seed"
        git config user.email "test@example.com"
        git config user.name "Test"
        echo "v1" > README.md
        git add README.md
        git commit -m "initial" >/dev/null 2>&1
        git remote add origin "${root}/origin.git"
        git push -u origin main >/dev/null 2>&1
    )

    git clone "${root}/origin.git" "${root}/work" >/dev/null 2>&1
    (
        cd "${root}/work"
        git config user.email "test@example.com"
        git config user.name "Test"
    )

    touch "${root}/install.log"
    echo "${root}"
}

push_new_commit_to_origin() {
    # Advance origin/main by one commit so a subsequent pull_latest()
    # has something to fetch.
    local root="$1"
    (
        cd "${root}/seed"
        echo "v2" >> README.md
        git add README.md
        git commit -m "advance" >/dev/null 2>&1
        git push origin main >/dev/null 2>&1
    )
}

cleanup_fixture() {
    local root="$1"
    [[ -n "$root" && -d "$root" ]] && rm -rf "$root"
}

prime_env() {
    # Set only the vars install.sh's module-level code cares about,
    # leaving the rest unset so the sourced script doesn't trip over
    # missing dependencies (docker, systemctl, etc. aren't called).
    local root="$1"
    export FXLAB_HOME="${root}/work"
    export FXLAB_BRANCH="main"
    export LOG_FILE="${root}/install.log"
}

source_install_sh() {
    # Source install.sh. The BASH_SOURCE guard at the bottom of
    # install.sh prevents main() from running when sourced.
    # shellcheck disable=SC1090
    source "$INSTALL_SH"
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_happy_path_pulls_new_commit() {
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    push_new_commit_to_origin "$root"
    prime_env "$root"
    source_install_sh

    local before_sha
    before_sha="$(git -C "${root}/work" rev-parse HEAD)"

    # Run pull_latest; capture stdout/stderr and exit code.
    local output rc
    output="$(pull_latest 2>&1)"
    rc=$?

    local after_sha
    after_sha="$(git -C "${root}/work" rev-parse HEAD)"
    local origin_sha
    origin_sha="$(git -C "${root}/origin.git" rev-parse main)"

    assert_eq 0 "$rc" "pull_latest should succeed on happy path" || return 1
    assert_eq "$origin_sha" "$after_sha" "work HEAD must equal origin HEAD after pull" || return 1
    [[ "$before_sha" != "$after_sha" ]] || { echo "    FAIL: HEAD should have moved"; return 1; }
    assert_contains "$output" "Updated:" "should log an Updated: line" || return 1
}

test_already_at_latest_is_noop() {
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    prime_env "$root"
    source_install_sh

    local before_sha
    before_sha="$(git -C "${root}/work" rev-parse HEAD)"

    local output rc
    output="$(pull_latest 2>&1)"
    rc=$?

    local after_sha
    after_sha="$(git -C "${root}/work" rev-parse HEAD)"

    assert_eq 0 "$rc" "pull_latest should succeed when up-to-date" || return 1
    assert_eq "$before_sha" "$after_sha" "HEAD must not move when already at latest" || return 1
    assert_contains "$output" "Already at latest commit" "should log the 'already at latest' line" || return 1
}

test_fetch_failure_without_escape_is_fatal() {
    # Point origin at a file path that does not exist → fetch will fail.
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    git -C "${root}/work" remote set-url origin "${root}/does-not-exist.git"

    prime_env "$root"
    unset FXLAB_ALLOW_STALE_CODE 2>/dev/null || true
    source_install_sh

    local output rc
    # pull_latest -> fail -> exit 1 — must be caught inside the subshell
    # wrapper so we can assert on it.
    output="$( (pull_latest) 2>&1 )"
    rc=$?

    [[ "$rc" -ne 0 ]] || { echo "    FAIL: expected non-zero exit, got 0"; return 1; }
    assert_contains "$output" "git fetch origin main FAILED" "should fail loudly with the exact FAILED marker" || return 1
    assert_contains "$output" "FXLAB_ALLOW_STALE_CODE=1" "should mention the escape hatch" || return 1
    assert_not_contains "$output" "Proceeding with existing code" "must NOT silently proceed (legacy regression)" || return 1
}

test_fetch_failure_with_allow_stale_is_soft_warning() {
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    git -C "${root}/work" remote set-url origin "${root}/does-not-exist.git"

    prime_env "$root"
    export FXLAB_ALLOW_STALE_CODE=1
    source_install_sh

    local output rc
    output="$(pull_latest 2>&1)"
    rc=$?

    assert_eq 0 "$rc" "pull_latest should return 0 with escape hatch" || return 1
    assert_contains "$output" "FXLAB_ALLOW_STALE_CODE=1 — proceeding" "should mention escape hatch activation" || return 1
    assert_contains "$output" "MAY BE OUT OF DATE" "should clearly warn about stale code risk" || return 1
}

test_missing_remote_branch_after_fetch_is_fatal() {
    # Simulate a successful fetch that leaves no origin/$BRANCH ref
    # (e.g. upstream branch was deleted). We shadow `git` with a
    # function that lets every subcommand through EXCEPT 'rev-parse
    # origin/main', which we force to fail.
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    prime_env "$root"
    source_install_sh

    # Function shadow takes precedence over $PATH for unqualified `git`.
    git() {
        # "rev-parse origin/main" → empty ref
        if [[ "$1" == "rev-parse" && "$2" == "origin/main" ]]; then
            return 1
        fi
        command git "$@"
    }

    local output rc
    output="$( (pull_latest) 2>&1 )"
    rc=$?

    [[ "$rc" -ne 0 ]] || { echo "    FAIL: expected fatal exit on missing remote branch"; return 1; }
    assert_contains "$output" "origin/main does not exist" "should name the missing ref" || return 1
}

test_post_reset_verification_catches_mismatch() {
    # Simulate a pathological reset that succeeds-but-doesn't-land.
    # We shadow git so every `rev-parse HEAD` returns a fabricated SHA,
    # while all other subcommands pass through to real git. Because
    # current_sha and new_sha both come from `rev-parse HEAD` they
    # both equal the fake; remote_sha comes from `rev-parse
    # origin/main` (real). The final check (new_sha != remote_sha)
    # therefore fires, which is exactly the defence-in-depth path we
    # want to exercise. Counting invocations inside the function would
    # be useless because each $(git ...) runs in its own subshell.
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    push_new_commit_to_origin "$root"
    prime_env "$root"
    source_install_sh

    git() {
        if [[ "$1" == "rev-parse" && "$2" == "HEAD" ]]; then
            echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
            return 0
        fi
        command git "$@"
    }

    local output rc
    output="$( (pull_latest) 2>&1 )"
    rc=$?

    [[ "$rc" -ne 0 ]] || { echo "    FAIL: expected fatal exit on post-reset mismatch"; return 1; }
    assert_contains "$output" "Post-reset verification failed" "should name the post-reset check" || return 1
}

test_operator_stash_is_preserved_across_pull() {
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    # Operator edits a file that upstream does NOT touch — so the
    # stash pop won't conflict with the pulled changes. (If both
    # sides touched the same file, `git stash pop` would produce a
    # merge conflict and leave the stash intact — a legitimate
    # outcome that the WARN branch handles, but not what this test
    # is asserting about.)
    echo "operator: custom port" > "${root}/work/operator-notes.txt"
    git -C "${root}/work" add operator-notes.txt

    push_new_commit_to_origin "$root"
    prime_env "$root"
    source_install_sh

    local output rc
    output="$(pull_latest 2>&1)"
    rc=$?

    assert_eq 0 "$rc" "pull_latest should succeed with a dirty tree" || return 1
    assert_contains "$output" "Stashing local changes" "should announce stash" || return 1
    assert_contains "$output" "Re-applied local changes" "should re-apply stash" || return 1
    # The operator's edit must be back in the working tree.
    grep -q "operator: custom port" "${root}/work/operator-notes.txt" \
        || { echo "    FAIL: operator edit was lost"; return 1; }
}

test_corrupt_repo_detection() {
    local root
    root="$(make_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    # Break the clone: remove .git so git rev-parse HEAD fails.
    rm -rf "${root}/work/.git"
    mkdir -p "${root}/work/.git"  # keep the directory so `cd` still works

    prime_env "$root"
    source_install_sh

    local output rc
    output="$( (pull_latest) 2>&1 )"
    rc=$?

    [[ "$rc" -ne 0 ]] || { echo "    FAIL: expected fatal exit on corrupt repo"; return 1; }
    assert_contains "$output" "Cannot read current git HEAD" "should surface corrupt-repo message" || return 1
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi

    echo "install.sh pull_latest test suite"
    echo "---------------------------------"

    run_test "happy path — pulls new commit from origin"           test_happy_path_pulls_new_commit
    run_test "already at latest — no-op"                           test_already_at_latest_is_noop
    run_test "fetch failure is fatal (no silent fallback)"         test_fetch_failure_without_escape_is_fatal
    run_test "fetch failure + FXLAB_ALLOW_STALE_CODE=1 → warn"     test_fetch_failure_with_allow_stale_is_soft_warning
    run_test "missing origin/BRANCH after fetch is fatal"          test_missing_remote_branch_after_fetch_is_fatal
    run_test "post-reset HEAD mismatch is fatal"                   test_post_reset_verification_catches_mismatch
    run_test "operator stash is preserved across pull"             test_operator_stash_is_preserved_across_pull
    run_test "corrupt repo is detected early"                      test_corrupt_repo_detection

    echo
    echo "---------------------------------"
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

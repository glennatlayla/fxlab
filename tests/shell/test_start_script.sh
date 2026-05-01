#!/usr/bin/env bash
# ===========================================================================
# Tests for scripts/start.sh
# ===========================================================================
#
# Verifies the session-start helper:
#   - Refuses outside a git working tree
#   - Refuses on dirty working tree (preserves WIP)
#   - Refuses on detached HEAD
#   - Refuses on branch without tracking upstream
#   - On clean up-to-date repo: runs bootstrap, exits 0, says "up to date"
#   - On clean repo with FF available: pulls and runs bootstrap
#   - --no-pull skips the git step but still runs bootstrap
#   - --no-bootstrap skips bootstrap but still pulls
#   - --help exits 0 and documents both flags
#   - Pass-through arguments reach scripts/bootstrap.sh
#
# Run:
#     bash tests/shell/test_start_script.sh
# ===========================================================================

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
START_SCRIPT_SRC="$PROJECT_ROOT/scripts/start.sh"
LIB_SRC="$PROJECT_ROOT/scripts/_lib.sh"

# ---------------------------------------------------------------------------
# Minimal harness (mirrors style of sibling shell tests in this directory)
# ---------------------------------------------------------------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

assert_eq() {
    local expected="$1" actual="$2" msg="${3:-}"
    [[ "$expected" == "$actual" ]] && return 0
    echo "    FAIL: $msg"
    echo "      expected: $expected"
    echo "      actual:   $actual"
    return 1
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    [[ "$haystack" == *"$needle"* ]] && return 0
    echo "    FAIL: $msg"
    echo "      expected substring: $needle"
    echo "      actual:             ${haystack:0:400}"
    return 1
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    [[ "$haystack" != *"$needle"* ]] && return 0
    echo "    FAIL: $msg"
    echo "      unwanted substring: $needle"
    echo "      actual:             ${haystack:0:400}"
    return 1
}

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · $name"
    if ( "$@" ); then
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$name")
    fi
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
#
# make_repo: build a self-contained temp repo with:
#   - bare upstream at <root>/upstream.git
#   - working clone at <root>/work, branch 'main', tracking origin/main
#   - scripts/_lib.sh           (real, copied from project)
#   - scripts/bootstrap.sh      (stub: prints "BOOTSTRAP-STUB args=...")
#   - scripts/start.sh          (the script under test)
# Echoes the working-clone path on stdout.
#
make_repo() (
    set -e
    local root work
    root="$(mktemp -d)"
    work="$root/work"
    git init --bare -q -b main "$root/upstream.git"
    git init -q -b main "$work"
    cd "$work"
    git config user.email "test@example.com"
    git config user.name "Test"
    git remote add origin "$root/upstream.git"
    mkdir -p scripts
    cp "$LIB_SRC" scripts/_lib.sh
    cat > scripts/bootstrap.sh <<'EOF'
#!/usr/bin/env bash
echo "BOOTSTRAP-STUB args=$*"
exit 0
EOF
    chmod +x scripts/bootstrap.sh
    cp "$START_SCRIPT_SRC" scripts/start.sh
    chmod +x scripts/start.sh
    echo "v1" > README.md
    git add -A
    git commit -q -m "init"
    git push -q -u origin main
    echo "$work"
)

# advance_upstream <work-clone-path>: simulate a teammate pushing one commit
# to the bare upstream sibling so that the work clone is one commit behind.
advance_upstream() (
    set -e
    local work="$1"
    local upstream tmp
    upstream="$(cd "$work" && git config --get remote.origin.url)"
    tmp="$(mktemp -d)"
    git clone -q "$upstream" "$tmp/clone"
    cd "$tmp/clone"
    git config user.email "test@example.com"
    git config user.name "Test"
    echo "v2" > LATEST.md
    git add LATEST.md
    git commit -q -m "feat: upstream advance"
    git push -q origin main
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_help_prints_usage() {
    output="$(bash "$START_SCRIPT_SRC" --help 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0 for --help" || return 1
    assert_contains "$output" "start.sh"     "help should mention start.sh"     || return 1
    assert_contains "$output" "--no-pull"    "help should document --no-pull"    || return 1
    assert_contains "$output" "--no-bootstrap" "help should document --no-bootstrap" || return 1
}

test_outside_git_repo_fails() {
    local d
    d="$(mktemp -d)"
    cd "$d"
    output="$(bash "$START_SCRIPT_SRC" 2>&1)"
    rc=$?
    assert_eq 1 "$rc" "expected exit 1 outside git repo" || return 1
    assert_contains "$output" "git" "expected error mentioning git" || return 1
}

test_dirty_tree_refused() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    echo "uncommitted" > dirty.txt
    output="$(bash scripts/start.sh 2>&1)"
    rc=$?
    assert_eq 1 "$rc" "expected exit 1 on dirty tree" || return 1
    assert_contains "$output" "uncommitted" "expected uncommitted-changes message" || return 1
    assert_not_contains "$output" "BOOTSTRAP-STUB" "bootstrap must NOT run on dirty tree" || return 1
}

test_detached_head_refused() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    git checkout -q --detach HEAD
    output="$(bash scripts/start.sh 2>&1)"
    rc=$?
    [[ "$rc" -ne 0 ]] || { echo "      expected non-zero rc, got 0"; return 1; }
    assert_contains "$output" "etached" "expected detached-HEAD complaint" || return 1
}

test_no_upstream_refused() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    git checkout -q -b feature
    output="$(bash scripts/start.sh 2>&1)"
    rc=$?
    [[ "$rc" -ne 0 ]] || { echo "      expected non-zero rc, got 0"; return 1; }
    assert_contains "$output" "upstream" "expected upstream complaint" || return 1
}

test_clean_uptodate_runs_bootstrap() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    output="$(bash scripts/start.sh 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0 on clean up-to-date" || return 1
    assert_contains "$output" "up to date"      "expected 'up to date' message" || return 1
    assert_contains "$output" "BOOTSTRAP-STUB"  "bootstrap.sh should be invoked" || return 1
}

test_pulls_when_upstream_advances() {
    local repo
    repo="$(make_repo)" || return 1
    advance_upstream "$repo" || return 1
    cd "$repo"
    output="$(bash scripts/start.sh 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0 on FF pull" || return 1
    assert_contains "$output" "feat: upstream advance" "expected pulled-commit subject in output" || return 1
    assert_contains "$output" "BOOTSTRAP-STUB"         "bootstrap.sh should be invoked"          || return 1
}

test_no_pull_skips_git() {
    local repo
    repo="$(make_repo)" || return 1
    advance_upstream "$repo" || return 1
    cd "$repo"
    output="$(bash scripts/start.sh --no-pull 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0 with --no-pull" || return 1
    assert_contains "$output"     "skip"           "expected skip message"      || return 1
    assert_contains "$output"     "BOOTSTRAP-STUB" "bootstrap should still run" || return 1
    head_msg="$(git log -1 --format=%s)"
    assert_eq "init" "$head_msg" "HEAD should be unchanged with --no-pull" || return 1
}

test_no_bootstrap_skips_install() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    output="$(bash scripts/start.sh --no-bootstrap 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0 with --no-bootstrap" || return 1
    assert_not_contains "$output" "BOOTSTRAP-STUB" "bootstrap must not run with --no-bootstrap" || return 1
}

test_passthru_args_forwarded_to_bootstrap() {
    local repo
    repo="$(make_repo)" || return 1
    cd "$repo"
    output="$(bash scripts/start.sh --skip-tests --no-docker 2>&1)"
    rc=$?
    assert_eq 0 "$rc" "expected exit 0" || return 1
    assert_contains "$output" "BOOTSTRAP-STUB args=--skip-tests --no-docker" \
        "expected pass-through flags forwarded to stub" || return 1
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

echo "Tests for scripts/start.sh"
echo

run_test "--help prints usage"                   test_help_prints_usage
run_test "outside git repo fails"                test_outside_git_repo_fails
run_test "dirty working tree is refused"         test_dirty_tree_refused
run_test "detached HEAD is refused"              test_detached_head_refused
run_test "branch without upstream is refused"    test_no_upstream_refused
run_test "clean up-to-date runs bootstrap"       test_clean_uptodate_runs_bootstrap
run_test "fast-forward pull runs bootstrap"      test_pulls_when_upstream_advances
run_test "--no-pull skips git, runs bootstrap"   test_no_pull_skips_git
run_test "--no-bootstrap skips install"          test_no_bootstrap_skips_install
run_test "passthru flags reach bootstrap.sh"     test_passthru_args_forwarded_to_bootstrap

echo
echo "ran=$TESTS_RUN passed=$TESTS_PASSED failed=$TESTS_FAILED"
if (( TESTS_FAILED > 0 )); then
    echo "Failed tests:"
    for t in "${FAILED_TESTS[@]}"; do echo "  - $t"; done
    exit 1
fi
echo "All scripts/start.sh tests passed."
exit 0

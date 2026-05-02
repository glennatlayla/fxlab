#!/usr/bin/env bash
# ===========================================================================
# Tests for the run-lifecycle helpers in scripts/_lib.sh (2026-05-02).
# ===========================================================================
#
# Pins the contract that prevents the "two pytests running in parallel"
# scenario the operator hit on 2026-05-02:
#
#   1. run_acquire_lock refuses when another live PID owns the lock.
#   2. run_acquire_lock claims a stale lock (PID no longer alive).
#   3. _run_kill_descendants kills every descendant on EXIT/INT/TERM.
#   4. run_register_cleanup chains onto an existing EXIT trap rather
#      than overwriting it, so bootstrap's compose-override cleanup
#      and our descendant-killer both run.
#   5. start.sh and bootstrap.sh actually call run_acquire_lock and
#      run_register_cleanup.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
export REPO_ROOT
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/_lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# ---------------------------------------------------------------------------
# 1. run_acquire_lock refuses on a live owner.
# ---------------------------------------------------------------------------

LOCK_NAME="__test_lifecycle_$$"
LOCK_PATH="$REPO_ROOT/.git/${LOCK_NAME}.lock"
trap 'rm -f "$LOCK_PATH"' EXIT

# Plant a lock owned by a sleep we can control.
sleep 60 &
SLEEPER_PID=$!
printf '%s\n%s\n' "$SLEEPER_PID" "$(date -u +%FT%TZ)" > "$LOCK_PATH"

# Try to acquire — must exit 1 with the conflict diagnostic.
output="$(bash -c "
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    run_acquire_lock '$LOCK_NAME'
" 2>&1 || true)"
if ! grep -q "Another '$LOCK_NAME' run is already in progress" <<< "$output"; then
    kill "$SLEEPER_PID" 2>/dev/null || true
    echo "$output"
    fail "run_acquire_lock did not refuse when a live PID owned the lock"
fi
if ! grep -q "PID    : $SLEEPER_PID" <<< "$output"; then
    kill "$SLEEPER_PID" 2>/dev/null || true
    echo "$output"
    fail "run_acquire_lock conflict diagnostic missing live owner PID"
fi
pass "run_acquire_lock refuses when another live PID owns the lock"

# Lock file must NOT have been overwritten by the failed attempt.
saved_owner="$(sed -n 1p "$LOCK_PATH")"
[[ "$saved_owner" == "$SLEEPER_PID" ]] \
    || fail "lock file was overwritten by a refused acquire (now: $saved_owner)"
pass "refused run_acquire_lock leaves the existing lockfile intact"

kill "$SLEEPER_PID" 2>/dev/null || true
wait "$SLEEPER_PID" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. run_acquire_lock claims a stale lock (PID dead).
# ---------------------------------------------------------------------------

# Reuse the lockfile, now pointing at the dead sleeper PID.
[[ -f "$LOCK_PATH" ]] || fail "stale lockfile missing for second test"
output="$(bash -c "
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    run_acquire_lock '$LOCK_NAME'
    echo OK
" 2>&1)"
if ! grep -q '^OK$' <<< "$output"; then
    echo "$output"
    fail "run_acquire_lock did not claim a stale lock"
fi
if ! grep -q "Stale .* lock from PID" <<< "$output"; then
    echo "$output"
    fail "run_acquire_lock did not log the stale-claim warning"
fi
pass "run_acquire_lock claims a stale lock and warns"

# ---------------------------------------------------------------------------
# 3. _run_kill_descendants reaps children on EXIT.
# ---------------------------------------------------------------------------

# Spawn a script that registers the cleanup trap and forks a sleep
# child, then kill that script and verify the sleep is also gone.
PARENT_OUT="$(mktemp)"
trap 'rm -f "$LOCK_PATH" "$PARENT_OUT"' EXIT

bash -c "
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    run_register_cleanup
    sleep 30 &
    echo \$! > '$PARENT_OUT'
    sleep 30
" &
PARENT_PID=$!

# Wait briefly for the child sleep to be spawned and recorded.
i=0
while (( i < 20 )); do
    if [[ -s "$PARENT_OUT" ]]; then break; fi
    sleep 0.1
    i=$((i + 1))
done
CHILD_PID="$(cat "$PARENT_OUT" 2>/dev/null)"
[[ -n "$CHILD_PID" ]] || fail "child sleep PID was not recorded"

kill -0 "$CHILD_PID" 2>/dev/null \
    || fail "child sleep ($CHILD_PID) is not running pre-kill"
pass "child process is alive before parent is killed"

# Kill the parent — its EXIT trap should reap the child.
kill -TERM "$PARENT_PID" 2>/dev/null || true
wait "$PARENT_PID" 2>/dev/null || true

# Give the trap a moment to run and KILL the child.
i=0
while (( i < 30 )); do
    kill -0 "$CHILD_PID" 2>/dev/null || break
    sleep 0.2
    i=$((i + 1))
done

if kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -KILL "$CHILD_PID" 2>/dev/null || true
    fail "child sleep ($CHILD_PID) was NOT reaped when parent's EXIT trap fired"
fi
pass "_run_kill_descendants reaps children when parent's EXIT trap fires"

# ---------------------------------------------------------------------------
# 4. run_register_cleanup chains onto an existing EXIT trap.
# ---------------------------------------------------------------------------

CHAIN_OUT="$(mktemp)"
trap 'rm -f "$LOCK_PATH" "$PARENT_OUT" "$CHAIN_OUT"' EXIT

bash -c "
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    legacy_trap() { echo legacy >> '$CHAIN_OUT'; }
    trap legacy_trap EXIT
    run_register_cleanup
    exit 0
"
grep -q '^legacy$' "$CHAIN_OUT" \
    || fail "run_register_cleanup did not preserve the existing EXIT trap"
pass "run_register_cleanup chains onto existing EXIT trap (compose cleanup safe)"

# ---------------------------------------------------------------------------
# 5. start.sh and bootstrap.sh actually call the helpers.
# ---------------------------------------------------------------------------

START="$REPO_ROOT/scripts/start.sh"
BOOT="$REPO_ROOT/scripts/bootstrap.sh"
grep -q 'run_acquire_lock fxlab-start' "$START" \
    || fail "start.sh does not call run_acquire_lock fxlab-start"
grep -q 'run_register_cleanup' "$START" \
    || fail "start.sh does not call run_register_cleanup"
grep -q 'run_acquire_lock fxlab-bootstrap' "$BOOT" \
    || fail "bootstrap.sh does not call run_acquire_lock fxlab-bootstrap"
grep -q 'run_register_cleanup' "$BOOT" \
    || fail "bootstrap.sh does not call run_register_cleanup"
pass "start.sh + bootstrap.sh both wire run_acquire_lock + run_register_cleanup"

# 6. The orphan pre-flight is in start.sh.
grep -q 'run_preflight_orphan_check' "$START" \
    || fail "start.sh does not call run_preflight_orphan_check"
pass "start.sh wires the orphan pre-flight check"

# 7. run_preflight_orphan_check must survive `set -euo pipefail`. The
#    function calls pgrep, which exits 1 when there are no children;
#    without `|| true` on that pipe, command substitution under
#    pipefail+errexit would silently exit the calling script. This is
#    the regression test for the user-observed `./scripts/start.sh`
#    that just exited with no output and no error.
output="$(bash -c "
    set -euo pipefail
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    run_preflight_orphan_check 'no-such-pattern-that-cannot-match-anything'
    echo SURVIVED
" 2>&1)"
grep -q '^SURVIVED$' <<< "$output" \
    || { echo "$output"; fail "run_preflight_orphan_check exited under set -euo pipefail (pgrep no-children returns 1)"; }
pass "run_preflight_orphan_check survives set -euo pipefail when pgrep finds no children"

# 8. The orphan check must NOT flag its own awk/grep/ps pipeline
#    as an orphan (the pattern is in the awk -v pat=... arg).
output="$(bash -c "
    set -euo pipefail
    export REPO_ROOT='$REPO_ROOT'
    source '$REPO_ROOT/scripts/_lib.sh'
    run_preflight_orphan_check 'scripts/(start|bootstrap)\\.sh|fxlab_pytest|\\.venv/bin/python -m pytest'
    echo END
" 2>&1)"
if grep -q 'awk -v exempt' <<< "$output"; then
    echo "$output"
    fail "run_preflight_orphan_check matched its own awk command line (false positive)"
fi
pass "run_preflight_orphan_check does not match its own awk pipeline"

echo "all run-lifecycle tests passed"

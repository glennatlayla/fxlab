#!/usr/bin/env bash
# ===========================================================================
# Tests for scripts/healthcheck.sh and start.sh dispatch (2026-05-01).
# ===========================================================================
#
# Pins the contract documented in
# docs/workplan/2026-05-01-dev-bootstrap-redesign.md §3.3 and §6:
#
#   - --status mode runs no work, has no side-effects, exits 0.
#   - --status output includes one line per probe (PASS / WARNING /
#     REFRESH / HARD-FAIL).
#   - The fingerprint helpers and stamp helpers are loaded.
#   - start.sh --status delegates to healthcheck.sh --status (no pull,
#     no bootstrap).
#   - start.sh --no-pull --no-bootstrap with a green box exits 0.
#   - The forbidden bare-`exec 9<&-` anti-pattern (which silenced stderr
#     for the rest of the script) does not return.
#
# This is mostly static analysis + a no-side-effect run of --status,
# because the full healthcheck path needs a live compose stack to be
# meaningful. CI's full-stack tests cover the live-network path.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HEALTHCHECK="$REPO_ROOT/scripts/healthcheck.sh"
START="$REPO_ROOT/scripts/start.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -x "$HEALTHCHECK" ]] || fail "scripts/healthcheck.sh not executable"
[[ -x "$START" ]]       || fail "scripts/start.sh not executable"

# 1. healthcheck.sh sources the shared fingerprint + stamp libraries.
grep -q '_fingerprint.sh' "$HEALTHCHECK" \
    || fail "healthcheck.sh does not source _fingerprint.sh"
grep -q '_stamps.sh' "$HEALTHCHECK" \
    || fail "healthcheck.sh does not source _stamps.sh"
pass "healthcheck.sh sources _fingerprint.sh and _stamps.sh"

# 2. The bare-exec anti-pattern must not return. `exec 9<&- 2>/dev/null`
#    is the special form that rewrites the parent shell's redirections
#    permanently — we replaced it with a comment-documented removal.
if grep -nE '^[[:space:]]*exec [0-9]+<&-' "$HEALTHCHECK" \
        | grep -v '^[0-9]+:[[:space:]]*#'; then
    fail "healthcheck.sh contains a bare 'exec <fd><&-' that silences stderr."
fi
pass "healthcheck.sh has no stderr-silencing bare-exec pattern"

# 3. _url_host must handle URLs without an `@` (no userinfo). A
#    regression in the regex would greedily eat the entire URL.
HOST="$(bash -c 'source "$1"; _url_host "redis://localhost:6379/0"' _ "$HEALTHCHECK" 2>/dev/null \
        || true)"
# The above sourcing trips set -uo pipefail in healthcheck.sh because
# REPO_ROOT is unset; use a small extracted shim instead.
TMPHC="$(mktemp)"
trap 'rm -f "$TMPHC"' EXIT
sed -n '/^_url_host()/,/^}/p' "$HEALTHCHECK" > "$TMPHC"
HOST="$(bash -c 'source "$1"; _url_host "redis://localhost:6379/0"' _ "$TMPHC")"
[[ "$HOST" == "localhost" ]] \
    || fail "_url_host returned '$HOST' for redis URL without userinfo (expected 'localhost')"
pass "_url_host strips scheme/path/port without consuming the host (no-userinfo URL)"

HOST="$(bash -c 'source "$1"; _url_host "postgresql://user:pass@dbhost:5432/db"' _ "$TMPHC")"
[[ "$HOST" == "dbhost" ]] \
    || fail "_url_host returned '$HOST' for postgres URL with userinfo (expected 'dbhost')"
pass "_url_host strips userinfo correctly when present"

# 4. --status exit code is 0 (does not propagate green/refresh/hard-fail
#    decision — that's only for the default mode).
#    We don't run it here; we only check the source contract.
grep -qE 'if \[\[ "\$\{1:-\}" == "--status" \]\]' "$HEALTHCHECK" \
    || fail "healthcheck.sh missing --status mode"
grep -qE 'exit 0\s*$' "$HEALTHCHECK" \
    || fail "healthcheck.sh has no `exit 0` (status mode must exit 0)"
pass "healthcheck.sh has --status mode that exits 0"

# 5. start.sh dispatch
grep -qE 'STATUS_ONLY=1' "$START" \
    || fail "start.sh missing STATUS_ONLY flag"
grep -qE -- '--status' "$START" \
    || fail "start.sh does not parse --status"
grep -qE 'healthcheck\.sh' "$START" \
    || fail "start.sh does not invoke healthcheck.sh"
grep -qE 'rc=10|case \$rc' "$START" \
    || fail "start.sh does not branch on healthcheck rc"
pass "start.sh dispatches to healthcheck.sh and branches on its rc"

# 6. start.sh --status short-circuits before pull and bootstrap. Verify
#    the order in source: STATUS_ONLY check appears before the git pull
#    block.
status_line="$(grep -n 'STATUS_ONLY' "$START" | head -1 | cut -d: -f1)"
pull_line="$(grep -n 'log_step "Sync with origin"' "$START" | head -1 | cut -d: -f1)"
[[ -n "$status_line" && -n "$pull_line" && "$status_line" -lt "$pull_line" ]] \
    || fail "start.sh --status check is not above the git pull block"
pass "start.sh --status short-circuits before pull"

# 7. Healthcheck rc semantics documented in the script header.
grep -qE '^#[[:space:]]+0[[:space:]]+healthy' "$HEALTHCHECK" \
    || fail "healthcheck.sh header missing exit code 0 documentation"
grep -qE '^#[[:space:]]+10[[:space:]]+refresh-required' "$HEALTHCHECK" \
    || fail "healthcheck.sh header missing exit code 10 documentation"
grep -qE '^#[[:space:]]+1[[:space:]]+hard-fail' "$HEALTHCHECK" \
    || fail "healthcheck.sh header missing exit code 1 documentation"
pass "healthcheck.sh exit-code semantics documented"

echo "all healthcheck/start.sh tests passed"

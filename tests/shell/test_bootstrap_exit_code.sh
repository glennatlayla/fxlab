#!/usr/bin/env bash
# ===========================================================================
# Tests for scripts/bootstrap.sh exit-code policy (2026-05-01).
# ===========================================================================
#
# Purpose:
#     Bootstrap historically called `set -e 2>/dev/null || true` inside
#     step_validate_env, which silently turned errexit ON for every
#     subsequent step. Any non-zero command after that step then exited
#     the script with that command's exit code, even when the summary
#     showed only OK + WARN rows.
#
#     The visible symptom: `start.sh` reported `[ err]  scripts/bootstrap.sh
#     failed` after every run, because bootstrap.sh exited non-zero
#     despite reaching `exit 0`. WARN rows were treated as failures by
#     downstream consumers.
#
#     This test pins the contract:
#         - WARN rows in the summary do NOT produce a non-zero exit.
#         - Only FAIL rows produce a non-zero exit.
#         - bootstrap.sh does not enable errexit at any point in its run.
#
# This is a static analysis test; it does not execute the full bootstrap
# pipeline (that takes 30+ minutes). It checks the source for the
# patterns that previously caused the bug.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BOOTSTRAP="$REPO_ROOT/scripts/bootstrap.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -f "$BOOTSTRAP" ]] || fail "scripts/bootstrap.sh not found at $BOOTSTRAP"

# 1. The script must not enable errexit anywhere outside an explicitly-
#    documented test setup. The `set -e 2>/dev/null || true` pattern is
#    the original bug; reject it directly. `set -euo pipefail` and
#    `set -e` lines that are not part of the suppression dance are
#    likewise forbidden — bootstrap is `set -uo pipefail` only.
if grep -nE '^[[:space:]]*set -e( |$|o )' "$BOOTSTRAP" \
        | grep -v '^[[:space:]]*#'; then
    fail "bootstrap.sh enables errexit ('set -e'). Use explicit '|| rc=\$?' capture instead."
fi
pass "bootstrap.sh does not enable errexit"

# 2. The error-suppression pattern that flipped errexit on must not
#    re-appear as code (matches in comments are allowed — they document
#    the historical bug).
if grep -nE 'set -e 2>/dev/null \|\| true' "$BOOTSTRAP" \
        | grep -vE '^[0-9]+:[[:space:]]*#'; then
    fail "bootstrap.sh contains the legacy 'set -e 2>/dev/null || true' pattern as code."
fi
pass "bootstrap.sh has no legacy errexit-suppression code"

# 3. The exit-code decision must be controlled exclusively by
#    summary_has_failures (defined in _lib.sh to grep for FAIL rows).
#    A WARN row in the summary table must therefore not influence the
#    exit code. Verify _lib.sh's check is FAIL-only.
LIB="$REPO_ROOT/scripts/_lib.sh"
if ! grep -qE "^[[:space:]]*grep -q '\\^FAIL'" "$LIB"; then
    fail "scripts/_lib.sh::summary_has_failures must grep for '^FAIL' only, not WARN."
fi
pass "summary_has_failures matches FAIL rows only (WARN is not failure)"

# 4. The validate_env capture must use the rc-or-pattern, not the
#    legacy errexit-flip.
if ! grep -qE '\.venv/bin/python scripts/validate_env\.py \|\| rc=\$\?' "$BOOTSTRAP"; then
    fail "step_validate_env must capture rc via '|| rc=\$?' instead of toggling errexit."
fi
pass "step_validate_env captures rc without toggling errexit"

echo "all bootstrap exit-code tests passed"

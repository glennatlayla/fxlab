#!/usr/bin/env bash
# ===========================================================================
# Tests for the per-step stamp + fingerprint helpers (2026-05-01).
# ===========================================================================
#
# Purpose:
#     Bootstrap relies on per-step stamps under .git/fxlab-refresh-*.stamp
#     so that a re-run does not pay the cost of unchanged steps. The
#     contract these tests pin:
#
#       - fingerprint_workspace is stable across calls when the working
#         tree is unchanged, and changes when any tracked file is edited.
#
#       - fingerprint_files captures absent vs present and changes when
#         file content changes.
#
#       - stamp_record / stamp_matches round-trip correctly: writing a
#         fingerprint and then comparing the same fingerprint matches.
#
#       - stamp_clear "all" removes every refresh stamp.
#
#       - stamp_migrate_legacy moves an old stamp into the new naming
#         convention exactly once (idempotent).
#
# These are unit tests for the helper libraries; they do NOT run the
# full bootstrap pipeline.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
export REPO_ROOT
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/_fingerprint.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/_stamps.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# ---------------------------------------------------------------------------
# fingerprint_workspace stability
# ---------------------------------------------------------------------------

fp1="$(fingerprint_workspace)"
fp2="$(fingerprint_workspace)"
[[ "$fp1" == "$fp2" ]] || fail "fingerprint_workspace not stable: $fp1 vs $fp2"
pass "fingerprint_workspace stable across consecutive calls"

[[ ${#fp1} -eq 64 ]] || fail "fingerprint_workspace digest length unexpected (${#fp1})"
pass "fingerprint_workspace returns 64-char sha256"

# Edit a tracked file, ensure fingerprint changes, then revert.
README="$REPO_ROOT/README.md"
[[ -f "$README" ]] || fail "README.md missing — adapt this test"
echo "# fingerprint test marker $$" >> "$README"
fp_dirty="$(fingerprint_workspace)"
[[ "$fp_dirty" != "$fp1" ]] || fail "fingerprint_workspace did not change after editing README.md"
git -C "$REPO_ROOT" checkout -- README.md
fp_clean="$(fingerprint_workspace)"
[[ "$fp_clean" == "$fp1" ]] || fail "fingerprint_workspace did not restore after revert"
pass "fingerprint_workspace tracks tracked-file edits + revert"

# ---------------------------------------------------------------------------
# fingerprint_files: present vs absent vs content change
# ---------------------------------------------------------------------------

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
echo "alpha" > "$TMPDIR/a.txt"
echo "beta"  > "$TMPDIR/b.txt"
fp_ab="$(fingerprint_files "$TMPDIR/a.txt" "$TMPDIR/b.txt")"
fp_ab2="$(fingerprint_files "$TMPDIR/a.txt" "$TMPDIR/b.txt")"
[[ "$fp_ab" == "$fp_ab2" ]] || fail "fingerprint_files not stable"
pass "fingerprint_files stable across consecutive calls"

echo "alpha-modified" > "$TMPDIR/a.txt"
fp_ab_changed="$(fingerprint_files "$TMPDIR/a.txt" "$TMPDIR/b.txt")"
[[ "$fp_ab_changed" != "$fp_ab" ]] || fail "fingerprint_files did not change after editing a.txt"
pass "fingerprint_files changes when file content changes"

rm -f "$TMPDIR/b.txt"
fp_a_only="$(fingerprint_files "$TMPDIR/a.txt" "$TMPDIR/b.txt")"
[[ "$fp_a_only" != "$fp_ab_changed" ]] || fail "fingerprint_files did not change after deleting b.txt"
pass "fingerprint_files changes when a file is deleted"

# ---------------------------------------------------------------------------
# stamp_record / stamp_matches / stamp_clear round trip
# ---------------------------------------------------------------------------

# Use a unique stamp name so this test cannot interfere with real stamps.
STAMP_NAME="__test_stamps_$$"
trap 'rm -rf "$TMPDIR"; stamp_clear "$STAMP_NAME"' EXIT

STAMP_PATH="$(stamp_path "$STAMP_NAME")"
[[ "$STAMP_PATH" == "$REPO_ROOT/.git/fxlab-refresh-${STAMP_NAME}.stamp" ]] \
    || fail "stamp_path returns unexpected path: $STAMP_PATH"
pass "stamp_path returns canonical .git/fxlab-refresh-<name>.stamp"

# Initially absent → no match.
stamp_clear "$STAMP_NAME"
if stamp_matches "$STAMP_NAME" "any-fingerprint"; then
    fail "stamp_matches returned true for an absent stamp"
fi
pass "stamp_matches returns false when stamp absent"

# Record a fingerprint, then a matching probe should succeed.
stamp_record "$STAMP_NAME" "abc123"
if ! stamp_matches "$STAMP_NAME" "abc123"; then
    fail "stamp_matches failed for matching fingerprint immediately after stamp_record"
fi
pass "stamp_matches returns true for matching fingerprint"

# A different fingerprint must not match.
if stamp_matches "$STAMP_NAME" "different-fingerprint"; then
    fail "stamp_matches returned true for a non-matching fingerprint"
fi
pass "stamp_matches returns false for non-matching fingerprint"

# Empty current fingerprint must not match.
if stamp_matches "$STAMP_NAME" ""; then
    fail "stamp_matches returned true for an empty fingerprint argument"
fi
pass "stamp_matches refuses empty current fingerprint"

stamp_clear "$STAMP_NAME"
[[ ! -f "$STAMP_PATH" ]] || fail "stamp_clear did not remove $STAMP_PATH"
pass "stamp_clear removes the named stamp"

# ---------------------------------------------------------------------------
# stamp_migrate_legacy
# ---------------------------------------------------------------------------

LEGACY="$REPO_ROOT/.git/fxlab-test-legacy-$$.stamp"
NEW_NAME="__test_legacy_$$"
NEW_PATH="$(stamp_path "$NEW_NAME")"

# Setup: legacy file exists, new path does not.
echo "legacy-content" > "$LEGACY"
rm -f "$NEW_PATH"

stamp_migrate_legacy "$LEGACY" "$NEW_NAME"
[[ ! -f "$LEGACY" ]] || fail "stamp_migrate_legacy did not remove legacy file"
[[ -f "$NEW_PATH" ]]  || fail "stamp_migrate_legacy did not create new file"
[[ "$(cat "$NEW_PATH")" == "legacy-content" ]] \
    || fail "stamp_migrate_legacy did not preserve content"
pass "stamp_migrate_legacy moves legacy stamp to new path"

# Idempotence: running again with no legacy file is a no-op.
stamp_migrate_legacy "$LEGACY" "$NEW_NAME"
[[ -f "$NEW_PATH" ]] || fail "stamp_migrate_legacy clobbered new stamp on second call"
pass "stamp_migrate_legacy is idempotent when legacy is absent"

# If both exist, do NOT overwrite the new stamp.
echo "legacy-content-2" > "$LEGACY"
echo "new-content"      > "$NEW_PATH"
stamp_migrate_legacy "$LEGACY" "$NEW_NAME"
[[ "$(cat "$NEW_PATH")" == "new-content" ]] \
    || fail "stamp_migrate_legacy clobbered an existing new stamp"
pass "stamp_migrate_legacy never overwrites an existing new stamp"

rm -f "$LEGACY" "$NEW_PATH"

echo "all stamp + fingerprint tests passed"

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

# Edit a tracked file, ensure fingerprint changes, then revert. Note
# we use cp-based save/restore (not git checkout) so this test does
# not destroy unrelated unstaged changes in the operator's tree.
README="$REPO_ROOT/README.md"
[[ -f "$README" ]] || fail "README.md missing — adapt this test"
TMPDIR="$(mktemp -d)"
README_BACKUP="$TMPDIR/README.bak.$$"
cp -- "$README" "$README_BACKUP"
echo "# fingerprint test marker $$" >> "$README"
fp_dirty="$(fingerprint_workspace)"
[[ "$fp_dirty" != "$fp1" ]] || { cp -- "$README_BACKUP" "$README"; fail "fingerprint_workspace did not change after editing README.md"; }
cp -- "$README_BACKUP" "$README"
rm -f "$README_BACKUP"
fp_clean="$(fingerprint_workspace)"
[[ "$fp_clean" == "$fp1" ]] || fail "fingerprint_workspace did not restore after revert"
pass "fingerprint_workspace tracks tracked-file edits + revert"

# ---------------------------------------------------------------------------
# fingerprint_test_inputs is scoped — tooling/doc edits MUST NOT
# invalidate it, but Python source / test / deps changes MUST.
# This is the contract the user identified as a real bug: every
# bootstrap.sh edit forced a 20-minute pytest re-run.
# ---------------------------------------------------------------------------

ti1="$(fingerprint_test_inputs)"
ti2="$(fingerprint_test_inputs)"
[[ "$ti1" == "$ti2" ]] || fail "fingerprint_test_inputs not stable: $ti1 vs $ti2"
pass "fingerprint_test_inputs stable across consecutive calls"

# Helper: save and restore a file's content via `cp`. NEVER use
# `git checkout -- <path>` here — that destroys the operator's
# unstaged edits to the SAME file (caught the hard way: the
# bootstrap.sh case below was nuking concurrent lifecycle work in
# the working tree).
_save_and_edit() {
    local path="$1" marker="$2"
    local backup="$TMPDIR/$(basename "$path").$$.bak"
    cp -- "$path" "$backup"
    echo "$marker" >> "$path"
    printf '%s' "$backup"
}
_restore() {
    local path="$1" backup="$2"
    cp -- "$backup" "$path"
    rm -f "$backup"
}

# Editing scripts/bootstrap.sh — a tooling-only file — must NOT
# invalidate the test fingerprint. This is the regression test for
# the user-identified bug.
BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
backup="$(_save_and_edit "$BOOTSTRAP_SH" "# tooling-only marker $$")"
ti_after_tooling="$(fingerprint_test_inputs)"
_restore "$BOOTSTRAP_SH" "$backup"
[[ "$ti_after_tooling" == "$ti1" ]] \
    || fail "fingerprint_test_inputs changed when scripts/bootstrap.sh was edited (must not — tooling-only)"
pass "fingerprint_test_inputs is NOT invalidated by scripts/ edits (tooling-only)"

# Editing README.md (docs) — must NOT invalidate.
README_MD="$REPO_ROOT/README.md"
backup="$(_save_and_edit "$README_MD" "# docs marker $$")"
ti_after_docs="$(fingerprint_test_inputs)"
_restore "$README_MD" "$backup"
[[ "$ti_after_docs" == "$ti1" ]] \
    || fail "fingerprint_test_inputs changed when README.md was edited (must not — docs)"
pass "fingerprint_test_inputs is NOT invalidated by docs edits"

# Editing a Python file under libs/ MUST invalidate. Pick the first
# .py file we find under libs/ to keep this resilient to refactors.
# Avoid `git ls-files | head -1` because head closing stdin SIGPIPEs
# git, which under pipefail+errexit silently exits this test.
LIBS_FILES="$(git -C "$REPO_ROOT" ls-files 'libs/*.py' 2>/dev/null || true)"
LIBS_PY="${LIBS_FILES%%$'\n'*}"
if [[ -n "$LIBS_PY" ]]; then
    LIBS_PATH="$REPO_ROOT/$LIBS_PY"
    backup="$(_save_and_edit "$LIBS_PATH" "# python source marker $$")"
    ti_after_libs="$(fingerprint_test_inputs)"
    _restore "$LIBS_PATH" "$backup"
    [[ "$ti_after_libs" != "$ti1" ]] \
        || fail "fingerprint_test_inputs did NOT change when libs/ Python source was edited"
    pass "fingerprint_test_inputs IS invalidated by libs/*.py edits"
fi

# Editing requirements.txt MUST invalidate (tests can break when
# pinned versions move).
REQ="$REPO_ROOT/requirements.txt"
if [[ -f "$REQ" ]]; then
    backup="$(_save_and_edit "$REQ" "# req marker $$")"
    ti_after_req="$(fingerprint_test_inputs)"
    _restore "$REQ" "$backup"
    [[ "$ti_after_req" != "$ti1" ]] \
        || fail "fingerprint_test_inputs did NOT change when requirements.txt was edited"
    pass "fingerprint_test_inputs IS invalidated by requirements.txt edits"
fi

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

# ---------------------------------------------------------------------------
# Writer / reader fingerprint agreement.
#
# step_backend_tests in scripts/bootstrap.sh writes the `tests` stamp.
# scripts/healthcheck.sh reads it. They MUST compute the same digest
# from the same workspace state — otherwise the stamp can never match
# and pytest re-runs on every invocation regardless of what changed.
#
# This is the regression test for the bug landed in f218c2d, where the
# bootstrap.sh diff was nuked by a destructive `git checkout` in the
# test before it was committed: the commit message claimed the writer
# had been switched to fingerprint_test_inputs, but only the reader
# (healthcheck.sh) actually got the change. End result: tests stamp
# permanently stale.
# ---------------------------------------------------------------------------

writer_fp_call="$(grep -E '^[[:space:]]*fp="\$\(fingerprint_' "$REPO_ROOT/scripts/bootstrap.sh" \
    | grep -i tests -B0 -A0 || true)"
# Locate the tests fingerprint specifically (it is the one assigned in
# step_backend_tests, between the function start and the first
# stamp_matches tests / stamp_record tests call).
writer_tests_fp="$(awk '
    /^step_backend_tests\(\) \{/      {in_fn=1; next}
    in_fn && /^}/                     {in_fn=0}
    in_fn && /fp="\$\(fingerprint_/   {print; exit}
' "$REPO_ROOT/scripts/bootstrap.sh")"
reader_tests_fp="$(awk '
    /^# tests stamp/                  {capture=1; next}
    capture && /fp="\$\(fingerprint_/ {print; exit}
' "$REPO_ROOT/scripts/healthcheck.sh")"
[[ -n "$writer_tests_fp" ]] || fail "could not locate tests fingerprint in bootstrap.sh::step_backend_tests"
[[ -n "$reader_tests_fp" ]] || fail "could not locate tests fingerprint in healthcheck.sh"

# Strip whitespace differences and compare the function names used.
writer_fn="$(sed -E 's/.*fingerprint_([a-z_]+).*/fingerprint_\1/' <<< "$writer_tests_fp")"
reader_fn="$(sed -E 's/.*fingerprint_([a-z_]+).*/fingerprint_\1/' <<< "$reader_tests_fp")"
[[ "$writer_fn" == "$reader_fn" ]] \
    || fail "tests fingerprint mismatch: writer uses '$writer_fn', reader uses '$reader_fn' — stamp can never match"
pass "tests stamp writer (bootstrap.sh) and reader (healthcheck.sh) use the same fingerprint function ($writer_fn)"

echo "all stamp + fingerprint tests passed"

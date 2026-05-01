# scripts/_stamps.sh
# Per-step stamp helpers for the dev-bootstrap pipeline.
# Sourced — not executed. Callers control their own shell options.
#
# A "stamp" is a small file under .git/ that records the fingerprint of
# the workspace state at the last successful run of one pipeline step.
# When the next run computes the same fingerprint, the step can skip.
#
# Stamps live inside .git/ so they are per-clone and never committed.
# A failed step does NOT update its stamp — leaving any prior stamp
# stale forces the next run to re-try.
#
# Public API:
#
#   stamp_path <name>
#       Print the absolute path of stamp `<name>`.
#
#   stamp_matches <name> <fingerprint>
#       Returns 0 (true) if the stamp file exists AND its content equals
#       <fingerprint>. Returns 1 otherwise. Use with `if`.
#
#   stamp_record <name> <fingerprint>
#       Atomically write <fingerprint> as the content of stamp <name>.
#       Returns 0 even if write fails (best-effort — stamp is a cache).
#
#   stamp_clear <name|all>
#       Remove the named stamp, or all stamps when `<name>` is "all".
#
#   stamp_age_seconds <name>
#       Echo the age of the stamp file in seconds, or "absent" if not
#       present. Useful for time-decay policies.
#
#   stamp_migrate_legacy <legacy_path> <new_name>
#       One-shot migration helper: if `<legacy_path>` exists and the new
#       stamp does not, move legacy -> new. Used when renaming stamps
#       between releases so operators do not pay a one-time refresh cost.
#
# Caller must export REPO_ROOT.

# Stamp directory and naming convention. Stamps land at
# $REPO_ROOT/.git/fxlab-refresh-<name>.stamp.
_STAMP_DIR_REL=".git"
_STAMP_PREFIX="fxlab-refresh"

stamp_path() {
    printf '%s/%s/%s-%s.stamp' "$REPO_ROOT" "$_STAMP_DIR_REL" "$_STAMP_PREFIX" "$1"
}

stamp_matches() {
    local name="$1" current="$2"
    local path
    path="$(stamp_path "$name")"
    [[ -f "$path" ]] || return 1
    [[ -n "$current" ]] || return 1
    local saved
    saved="$(cat "$path" 2>/dev/null || true)"
    [[ "$current" == "$saved" ]]
}

stamp_record() {
    local name="$1" current="$2"
    local path
    path="$(stamp_path "$name")"
    # Best-effort; never error out if the .git dir is unwritable for
    # some reason — the stamp is just a cache.
    printf '%s' "$current" > "$path" 2>/dev/null || true
}

stamp_clear() {
    local name="$1"
    if [[ "$name" == "all" ]]; then
        rm -f "$REPO_ROOT/$_STAMP_DIR_REL/$_STAMP_PREFIX-"*.stamp 2>/dev/null || true
    else
        rm -f "$(stamp_path "$name")" 2>/dev/null || true
    fi
}

stamp_age_seconds() {
    local name="$1"
    local path
    path="$(stamp_path "$name")"
    if [[ ! -f "$path" ]]; then
        printf 'absent'
        return 0
    fi
    local now mtime
    now="$(date +%s)"
    # macOS stat differs from GNU stat; try GNU first.
    mtime="$(stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null || echo 0)"
    printf '%s' "$(( now - mtime ))"
}

stamp_migrate_legacy() {
    local legacy_path="$1" new_name="$2"
    local new_path
    new_path="$(stamp_path "$new_name")"
    if [[ -f "$legacy_path" && ! -f "$new_path" ]]; then
        mv "$legacy_path" "$new_path" 2>/dev/null || true
    fi
}

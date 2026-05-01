# scripts/_fingerprint.sh
# Workspace + file fingerprint helpers for the dev-bootstrap pipeline.
# Sourced — not executed. Callers control their own shell options.
#
# Two flavours:
#
#   fingerprint_workspace
#       Hash of the entire dev workspace. Captures HEAD SHA, every diff
#       vs HEAD (staged + unstaged), and the content of every untracked,
#       non-ignored file. Used by the pytest gate so any source change
#       invalidates the stamp.
#
#   fingerprint_files <path>...
#       Hash of a specific list of files. Missing files contribute via
#       an "absent" sentinel so deletions also invalidate. Used by
#       per-step stamps (e.g. python-deps fingerprints
#       requirements.txt + pyproject.toml).
#
# Both helpers print the hex sha256 digest to stdout and emit nothing on
# stderr. They tolerate missing tools (sha256sum / shasum / git) by
# emitting a unique-per-call sentinel that forces the caller's stamp
# comparison to mismatch — never silently passing.

# Cross-platform sha256 wrapper. Reads from stdin, prints hex digest.
# Prefers sha256sum (Linux); falls back to `shasum -a 256` (macOS).
_sha256_stdin() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | awk '{print $1}'
    else
        printf 'no-sha256-%s' "$(date +%s%N 2>/dev/null || date +%s)"
    fi
}

# Hash the entire workspace state: HEAD SHA + diff vs HEAD + every
# untracked non-ignored file's content. Captures every signal that could
# affect a unit-test outcome.
#
# Caller must export REPO_ROOT (absolute path to git working tree).
fingerprint_workspace() {
    {
        printf 'head=%s\n' "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo no-head)"
        # Format strings starting with `--` are parsed by bash builtin
        # printf as end-of-options, so use `%s\n` indirection for these.
        printf '%s\n' '---diff---'
        git -C "$REPO_ROOT" diff HEAD --no-color 2>/dev/null || true
        printf '%s\n' '---untracked---'
        # Stream NUL-delimited list directly into xargs so embedded NULs
        # are not stripped (which $(git ls-files ... -z) would do).
        git -C "$REPO_ROOT" ls-files --others --exclude-standard -z 2>/dev/null \
            | xargs -0 -I{} sh -c 'printf "%s:" "$1"; cat -- "$1" 2>/dev/null || true; printf "\n"' _ {}
    } | _sha256_stdin
}

# Hash a list of file paths. Missing files contribute an "absent"
# sentinel + filename so deletions invalidate the digest.
#
# Args: one or more file paths (may be relative to current directory).
fingerprint_files() {
    local f
    {
        for f in "$@"; do
            printf '%s:' "$f"
            if [[ -e "$f" ]]; then
                printf 'present\n'
                cat -- "$f" 2>/dev/null || true
            else
                printf 'absent\n'
            fi
            printf '\n---file-end---\n'
        done
    } | _sha256_stdin
}

# Hash a list of file globs. Like fingerprint_files but the input is
# bash globs (e.g. 'alembic/versions/*.py') that get expanded and
# fingerprinted in sorted order. Missing globs (no matches) contribute
# an "empty" sentinel so adding a first file also invalidates.
fingerprint_globs() {
    local glob
    local matches=()
    for glob in "$@"; do
        # Use a subshell + nullglob so unmatched globs disappear instead
        # of becoming literal strings.
        local expanded
        # shellcheck disable=SC2207  # nullglob expansion intentional
        expanded=( $(shopt -s nullglob; echo $glob) )
        if (( ${#expanded[@]} == 0 )); then
            matches+=("__no-match__:$glob")
        else
            local sorted
            # shellcheck disable=SC2207
            sorted=( $(printf '%s\n' "${expanded[@]}" | sort) )
            matches+=("${sorted[@]}")
        fi
    done
    fingerprint_files "${matches[@]}"
}

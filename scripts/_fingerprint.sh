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

# Hash everything that can affect unit-test outcomes — and nothing else.
#
# This deliberately does NOT call fingerprint_workspace (which hashes
# HEAD + every diff + every untracked file). The whole-workspace hash
# is too broad: a commit that only touches scripts/, docs/, or
# .archive/ would invalidate the tests stamp even though the unit
# tests themselves are byte-identical and would produce the same
# result. That made every tooling change pay a 20-minute pytest cost
# for no value.
#
# Inputs the unit-test outcome actually depends on:
#   - Python source under libs/ and services/ (tests import these).
#   - Test code itself (tests/unit/, tests/conftest.py, fixtures).
#   - Dep lockfiles (requirements*.txt, pyproject.toml).
#   - Pytest config (pytest.ini, .coveragerc).
#   - Alembic migrations (ORM models / schema state).
#   - Untracked .py files in libs/services/tests (newly added but not
#     yet committed test files must invalidate so the developer can
#     verify them).
#
# Anything else — scripts/, docs/, frontend/, .archive/, README — is
# excluded by design. If a future change in one of those paths COULD
# affect tests (e.g. a CI script that bakes in a constant), add it
# here explicitly.
fingerprint_test_inputs() {
    {
        fingerprint_globs \
            'libs/**/*.py' 'services/**/*.py' \
            'tests/unit/**/*.py' 'tests/conftest.py' \
            'tests/fixtures/**/*.py' 'tests/factories/**/*.py'
        fingerprint_files \
            requirements.txt requirements-dev.txt pyproject.toml \
            pytest.ini .coveragerc
        fingerprint_globs 'alembic/versions/*.py'
        # Untracked .py files inside the test-relevant trees only.
        # Avoids invalidating on operator scratch files like c.sh at
        # the repo root.
        git -C "$REPO_ROOT" ls-files --others --exclude-standard -z -- \
                libs/ services/ tests/ 2>/dev/null \
            | xargs -0 -I{} sh -c '
                case "$1" in
                    *.py)
                        printf "%s:" "$1"
                        cat -- "$1" 2>/dev/null || true
                        printf "\n"
                        ;;
                esac' _ {}
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
        # Use a subshell + nullglob so unmatched globs disappear
        # instead of becoming literal strings, and globstar so `**`
        # actually recurses (without it, bash silently treats `**` as
        # `*` which matches only one directory level — that bug
        # silently made fingerprint_test_inputs miss every libs/sub/
        # and services/sub/ Python file).
        local expanded
        # shellcheck disable=SC2207  # null/globstar expansion intentional
        expanded=( $(shopt -s nullglob globstar; echo $glob) )
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

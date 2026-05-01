#!/usr/bin/env bash
#
# FXLab — resume a dev session.
#
# Brings the local clone in sync with origin (fast-forward only) and then
# re-runs scripts/bootstrap.sh so .venv, Python deps, npm deps, frontend
# build, and Alembic migrations are all current. Idempotent — safe to
# invoke at the start of every session.
#
# Pre-flight refusals (exit 1 with a message) — designed to never clobber
# an operator's in-progress work:
#   - not inside a git working tree
#   - working tree has uncommitted (staged or unstaged) changes
#   - HEAD is detached
#   - current branch has no tracking upstream
#   - upstream has diverged from local (non-fast-forward)
#
# See `scripts/start.sh --help` for flags and exit codes.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
    echo "[err] start.sh must be run inside a git working tree" >&2
    exit 1
fi
# shellcheck source=./_lib.sh
source "$REPO_ROOT/scripts/_lib.sh"

DO_PULL=1
DO_BOOTSTRAP=1
BOOTSTRAP_PASSTHRU=()

print_help() {
    cat <<'EOF'
Usage: scripts/start.sh [--no-pull] [--no-bootstrap] [bootstrap-args...]

Resume a dev session: pull from origin (fast-forward only), then run
scripts/bootstrap.sh to refresh .venv / Python deps / npm deps / migrations.

Options:
  --no-pull          Skip the git fetch + pull (just refresh deps).
  --no-bootstrap     Skip scripts/bootstrap.sh (just sync git).
  -h, --help         Show this help and exit.

Any other flags are forwarded to scripts/bootstrap.sh, e.g.
    scripts/start.sh --skip-tests --no-docker

Exit codes:
  0  success
  1  pre-flight check failed (dirty tree, detached HEAD, no upstream, ...)
  2  scripts/bootstrap.sh failed
EOF
}

while (( $# )); do
    case "$1" in
        --no-pull)         DO_PULL=0 ;;
        --no-bootstrap)    DO_BOOTSTRAP=0 ;;
        -h|--help)         print_help; exit 0 ;;
        *)                 BOOTSTRAP_PASSTHRU+=("$1") ;;
    esac
    shift
done

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Step 1 — git sync (fast-forward only)
# ---------------------------------------------------------------------------
if (( DO_PULL )); then
    log_step "Sync with origin"

    # Refuse on staged or unstaged TRACKED-file modifications — preserves
    # operator WIP. Untracked files are allowed: `git pull --ff-only` will
    # itself refuse if a new upstream file would clobber an untracked one,
    # and otherwise untracked files survive a pull intact. Forcing a stash
    # for every gitignored scratch file (test SQLite, log, etc.) is friction
    # without safety value.
    if ! git diff --quiet || ! git diff --cached --quiet; then
        log_err "Working tree has uncommitted tracked-file changes."
        log_err "Stash or commit them first:"
        log_err "    git stash push -m 'before start.sh'"
        exit 1
    fi
    UNTRACKED="$(git ls-files --others --exclude-standard)"
    if [[ -n "$UNTRACKED" ]]; then
        log_warn "Untracked files present (proceeding — pull will preserve them):"
        printf '%s\n' "$UNTRACKED" | sed 's/^/    /'
    fi

    BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
    if [[ -z "$BRANCH" ]]; then
        log_err "HEAD is detached. Checkout a branch before running start.sh."
        exit 1
    fi

    UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || true)"
    if [[ -z "$UPSTREAM" ]]; then
        log_err "Branch '$BRANCH' has no tracking upstream."
        log_err "Set one with:  git branch --set-upstream-to=origin/$BRANCH"
        exit 1
    fi

    REMOTE="${UPSTREAM%%/*}"
    PREV_HEAD="$(git rev-parse HEAD)"

    log_info "branch=$BRANCH  upstream=$UPSTREAM  head=${PREV_HEAD:0:12}"
    if ! git fetch "$REMOTE"; then
        log_err "git fetch $REMOTE failed"
        exit 1
    fi

    # --ff-only refuses to merge or rebase; aborts on divergent history.
    # Operator must resolve manually rather than have start.sh guess.
    if ! git pull --ff-only "$REMOTE" "$BRANCH"; then
        log_err "Pull failed — '$BRANCH' has diverged from $UPSTREAM."
        log_err "Resolve manually:  git status; git log --oneline ..@{u}"
        exit 1
    fi

    NEW_HEAD="$(git rev-parse HEAD)"
    if [[ "$PREV_HEAD" == "$NEW_HEAD" ]]; then
        log_ok "Already up to date (${NEW_HEAD:0:12})"
    else
        N_COMMITS="$(git rev-list --count "$PREV_HEAD..$NEW_HEAD")"
        log_ok "Pulled $N_COMMITS commit(s): ${PREV_HEAD:0:12} -> ${NEW_HEAD:0:12}"
        git --no-pager log --oneline "$PREV_HEAD..$NEW_HEAD" | sed 's/^/    /'
    fi
else
    log_skip "git sync (--no-pull)"
fi

# ---------------------------------------------------------------------------
# Step 2 — bootstrap (idempotent: deps + .venv + migrations + frontend)
# ---------------------------------------------------------------------------
if (( DO_BOOTSTRAP )); then
    log_step "Refresh install"
    BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
    if [[ ! -x "$BOOTSTRAP_SH" ]]; then
        log_err "scripts/bootstrap.sh missing or not executable: $BOOTSTRAP_SH"
        exit 2
    fi
    log_info "Running: $BOOTSTRAP_SH ${BOOTSTRAP_PASSTHRU[*]:-}"
    if ! "$BOOTSTRAP_SH" ${BOOTSTRAP_PASSTHRU[@]+"${BOOTSTRAP_PASSTHRU[@]}"}; then
        log_err "scripts/bootstrap.sh failed"
        exit 2
    fi
else
    log_skip "bootstrap (--no-bootstrap)"
fi

log_ok "start.sh complete"

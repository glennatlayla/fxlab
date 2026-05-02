#!/usr/bin/env bash
#
# FXLab — single entry point for resuming a dev session.
#
# Default behaviour: pulls origin (fast-forward only), then runs a fast
# healthcheck. If the healthcheck reports the environment is green, exit
# in seconds. If any per-step stamp is stale, auto-escalate into the
# refresh pipeline (scripts/bootstrap.sh) — which will skip any step
# whose fingerprint already matches the last green stamp.
#
# Pre-flight refusals (exit 1 with a message) — designed to never
# clobber an operator's in-progress work:
#   - not inside a git working tree
#   - working tree has uncommitted (staged or unstaged) changes
#   - HEAD is detached
#   - current branch has no tracking upstream
#   - upstream has diverged from local (non-fast-forward)
#
# Flags:
#   --no-pull         Skip the git fetch + pull.
#   --refresh         Force refresh mode (skip the fast healthcheck).
#   --force           Force refresh AND override every per-step stamp
#                     (full reinstall + alembic + frontend rebuild +
#                     pytest gate, regardless of fingerprint match).
#                     Implies --refresh.
#   --status          Print the current healthcheck/stamp status and
#                     exit. No work, no side-effects.
#   --skip-tests      In refresh mode, skip the pytest gate entirely.
#   --force-tests     In refresh mode, re-run pytest even if stamp
#                     matches.
#   --force-deps      In refresh mode, re-run make bootstrap even if
#                     deps stamp matches.
#   --force-alembic   In refresh mode, re-run alembic upgrade.
#   --force-frontend-build
#                     In refresh mode, re-run the frontend build.
#   --no-bootstrap    Skip the bootstrap pipeline entirely (just sync
#                     git, run healthcheck, report).
#   --no-app          Skip launching the API + frontend dev servers
#                     (still does pull/healthcheck/refresh — useful
#                     for CI or when running them under a debugger).
#   --down            Stop the API + frontend dev servers (sends TERM
#                     to recorded PIDs in .git/fxlab-app-*.pid, then
#                     KILL after 5s if still alive). No pull or
#                     refresh; clean shutdown only.
#   --app-status      Print whether the API + frontend are running
#                     and on which ports. No pull, no refresh.
#   -h, --help        Show this help and exit.
#
# Any flag not recognised by start.sh is forwarded to bootstrap.sh.
#
# Exit codes:
#   0  healthy or refresh completed green
#   1  pre-flight failed (dirty tree, detached HEAD, no upstream, …)
#      OR healthcheck found a hard failure (compose down, .env missing)
#      OR refresh pipeline reported a FAIL row.

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
DO_APP_UP=1
FORCE_REFRESH=0
STATUS_ONLY=0
DOWN_MODE=0
APP_STATUS_MODE=0
BOOTSTRAP_PASSTHRU=()

print_help() {
    awk 'NR==1 {next} /^[^#]/ {exit} {print}' "$0"
}

while (( $# )); do
    case "$1" in
        --no-pull)          DO_PULL=0 ;;
        --no-bootstrap)     DO_BOOTSTRAP=0 ;;
        --no-app)           DO_APP_UP=0 ;;
        --down)             DOWN_MODE=1 ;;
        --app-status)       APP_STATUS_MODE=1 ;;
        --refresh)          FORCE_REFRESH=1 ;;
        --force)            FORCE_REFRESH=1; BOOTSTRAP_PASSTHRU+=("--force") ;;
        --status)           STATUS_ONLY=1 ;;
        -h|--help)          print_help; exit 0 ;;
        *)                  BOOTSTRAP_PASSTHRU+=("$1") ;;
    esac
    shift
done

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Status mode — short-circuit to healthcheck --status, no pull, no work,
# no lock acquisition (it's a read-only probe).
# ---------------------------------------------------------------------------
if (( STATUS_ONLY )); then
    exec "$REPO_ROOT/scripts/healthcheck.sh" --status
fi

# ---------------------------------------------------------------------------
# App status — print whether API + frontend are running, exit. No pull,
# no refresh, no lock.
# ---------------------------------------------------------------------------
if (( APP_STATUS_MODE )); then
    log_step "Application services"
    app_status api:8000 frontend:5173
    exit 0
fi

# ---------------------------------------------------------------------------
# Down mode — stop API + frontend cleanly, then exit. No pull, no
# refresh; only the shutdown side of the lifecycle.
# ---------------------------------------------------------------------------
if (( DOWN_MODE )); then
    log_step "Stopping application services"
    app_stop frontend
    app_stop api
    exit 0
fi

# ---------------------------------------------------------------------------
# Lifecycle: refuse concurrent runs, install descendant-cleanup trap,
# and warn about any orphan pytest/bootstrap.sh from a prior session.
# This is the structural fix for "I left two pytests running" —
# without it, an interrupted run would orphan its children and a
# second start.sh would race the first on stamp files.
# ---------------------------------------------------------------------------
run_preflight_orphan_check 'scripts/(start|bootstrap)\.sh|fxlab_pytest|\.venv/bin/python -m pytest'
run_acquire_lock fxlab-start
# Lock-release-only: start.sh intentionally launches long-running app
# services (uvicorn API + vite dev server) that MUST outlive this
# process. The descendant-killing variant (run_register_cleanup)
# would tear down the very services we just brought up. bootstrap.sh
# still uses run_register_cleanup because its descendants are
# pytest/npm/alembic — meant to be reaped on Ctrl-C.
run_register_lock_release_only

# ---------------------------------------------------------------------------
# Step 1 — git sync (fast-forward only).
# ---------------------------------------------------------------------------
if (( DO_PULL )); then
    log_step "Sync with origin"

    # Refuse on tracked-file modifications — preserves operator WIP.
    # Untracked files are allowed: git pull --ff-only refuses to clobber
    # untracked files itself, and forcing a stash for every gitignored
    # scratch file is friction without safety value.
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
# Step 2 — fast healthcheck. Decides whether refresh is needed.
# ---------------------------------------------------------------------------
if (( ! DO_BOOTSTRAP )); then
    log_skip "bootstrap (--no-bootstrap) — running healthcheck only"
fi

NEED_REFRESH=0
if (( FORCE_REFRESH )); then
    log_info "Refresh forced via --refresh / --force"
    NEED_REFRESH=1
else
    HEALTHCHECK="$REPO_ROOT/scripts/healthcheck.sh"
    if [[ ! -x "$HEALTHCHECK" ]]; then
        log_err "scripts/healthcheck.sh missing — falling back to refresh"
        NEED_REFRESH=1
    else
        # Run healthcheck inline (not exec) so we can act on its exit
        # code. set +e around it because set -e is on at the top of
        # this script.
        set +e
        "$HEALTHCHECK"
        rc=$?
        set -e
        case $rc in
            0)  log_ok "Environment is ready — no refresh needed."
                # Fall through to the app-launch step (DO_APP_UP).
                # Previously had `exit 0` here, which meant start.sh
                # never started the API + frontend on a green-stamps
                # box — the operator saw "ready" but localhost:5173
                # was empty. Letting flow continue brings the app up.
                NEED_REFRESH=0 ;;
            10) log_info "Healthcheck reports stamps stale — escalating to refresh."
                NEED_REFRESH=1 ;;
            1)  log_err "Healthcheck reported hard failures (see above)."
                exit 1 ;;
            *)  log_err "Healthcheck exited with unexpected rc=$rc; escalating to refresh."
                NEED_REFRESH=1 ;;
        esac
    fi
fi

# ---------------------------------------------------------------------------
# Step 3 — refresh (only when needed). Per-step stamps inside bootstrap.sh
# skip work that has not changed.
# ---------------------------------------------------------------------------
if (( DO_BOOTSTRAP )) && (( NEED_REFRESH )); then
    log_step "Refresh"
    BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
    if [[ ! -x "$BOOTSTRAP_SH" ]]; then
        log_err "scripts/bootstrap.sh missing or not executable: $BOOTSTRAP_SH"
        exit 1
    fi
    log_info "Running: $BOOTSTRAP_SH ${BOOTSTRAP_PASSTHRU[*]:-}"
    if ! "$BOOTSTRAP_SH" ${BOOTSTRAP_PASSTHRU[@]+"${BOOTSTRAP_PASSTHRU[@]}"}; then
        log_err "scripts/bootstrap.sh reported failures"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 4 — bring up application services so the operator can actually
# log in and use the app at http://localhost:5173.
# ---------------------------------------------------------------------------
if (( DO_APP_UP )); then
    log_step "Application services"
    # Source .env so JWT_SECRET_KEY, DATABASE_URL, KEYCLOAK_*, etc. reach
    # the uvicorn child process. services/api/main.py validates these on
    # startup and refuses to come up otherwise.
    if [[ -f .env ]]; then
        set -a
        # shellcheck disable=SC1091
        source .env 2>/dev/null || true
        set +a
    fi
    api_ok=1
    frontend_ok=1
    app_launch api 8000 \
        "$REPO_ROOT/.venv/bin/python" -m uvicorn services.api.main:app \
            --host 127.0.0.1 --port 8000 \
        || api_ok=0
    # Frontend dev server: vite picks up vite.config + .env automatically
    # but needs CWD=frontend AND npm on PATH. The repo's nodeenv installs
    # node + npm under .venv/bin, but the bare bash subshell inherits a
    # minimal PATH. Inject the venv's bin directory explicitly, with a
    # fallback to system node if .venv has no node.
    NODE_PATH_DIR=""
    if [[ -x "$REPO_ROOT/.venv/bin/node" ]]; then
        NODE_PATH_DIR="$REPO_ROOT/.venv/bin"
    elif command -v node >/dev/null 2>&1; then
        NODE_PATH_DIR="$(dirname "$(command -v node)")"
    fi
    # Build the frontend launch command as a heredoc-quoted bash -c
    # script so quoting stays sane: outer "..." interpolates the repo
    # path, escaped \$PATH is expanded inside the spawned shell.
    app_launch frontend 5173 \
        bash -c "
            export PATH=\"$NODE_PATH_DIR:\$PATH\"
            cd \"$REPO_ROOT/frontend\"
            exec npm run dev -- --host 127.0.0.1
        " \
        || frontend_ok=0

    if (( api_ok )) && (( frontend_ok )); then
        log_ok ""
        log_ok "FXLab is ready."
        log_ok "  → UI:        http://localhost:5173"
        log_ok "  → API docs:  http://localhost:8000/docs"
        if [[ -n "${FXLAB_ADMIN_EMAIL:-}" ]]; then
            log_ok "  → Login as:  $FXLAB_ADMIN_EMAIL  (Keycloak realm: ${KEYCLOAK_REALM:-fxlab})"
        fi
        log_ok "  → Stop with: ./scripts/start.sh --down"
        log_ok "  → Status:    ./scripts/start.sh --app-status"
    else
        log_err "One or more application services failed to come up — see logs above."
        log_err "  API log:      /tmp/fxlab-app-api.log"
        log_err "  Frontend log: /tmp/fxlab-app-frontend.log"
        exit 1
    fi
fi

log_ok "start.sh complete"

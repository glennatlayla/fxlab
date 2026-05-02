# scripts/_lib.sh
# Shared shell helpers for FXLab developer-facing scripts.
# Sourced — not executed. Callers control their own shell options.

# ----------------------------- styling ---------------------------------------

if [[ -t 1 ]]; then
    _CLR_RED=$'\033[31m'
    _CLR_GREEN=$'\033[32m'
    _CLR_YELLOW=$'\033[33m'
    _CLR_BLUE=$'\033[34m'
    _CLR_GREY=$'\033[90m'
    _CLR_BOLD=$'\033[1m'
    _CLR_RESET=$'\033[0m'
else
    _CLR_RED= _CLR_GREEN= _CLR_YELLOW= _CLR_BLUE= _CLR_GREY= _CLR_BOLD= _CLR_RESET=
fi

log_info()  { printf '%s[info]%s  %s\n'  "$_CLR_BLUE"   "$_CLR_RESET" "$*"; }
log_ok()    { printf '%s[ ok ]%s  %s\n'  "$_CLR_GREEN"  "$_CLR_RESET" "$*"; }
log_warn()  { printf '%s[warn]%s  %s\n'  "$_CLR_YELLOW" "$_CLR_RESET" "$*"; }
log_err()   { printf '%s[ err]%s  %s\n'  "$_CLR_RED"    "$_CLR_RESET" "$*" >&2; }
log_step()  { printf '\n%s==>%s %s%s%s\n' "$_CLR_BOLD"  "$_CLR_RESET" "$_CLR_BOLD" "$*" "$_CLR_RESET"; }
log_skip()  { printf '%s[skip]%s  %s\n'  "$_CLR_GREY"   "$_CLR_RESET" "$*"; }

die() {
    log_err "$*"
    exit 1
}

# ----------------------------- detection -------------------------------------

have_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo linux ;;
        Darwin*) echo darwin ;;
        *)       echo unknown ;;
    esac
}

# Compare two semver-ish version strings.
# Returns 0 if $1 >= $2, 1 otherwise.
version_ge() {
    [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

# ----------------------------- summary table ---------------------------------

SUMMARY_FILE="${SUMMARY_FILE:-/tmp/fxlab_bootstrap_summary.tsv}"

summary_init() {
    : >"$SUMMARY_FILE"
}

summary_row() {
    local status="$1" component="$2" detail="$3"
    printf '%s\t%s\t%s\n' "$status" "$component" "$detail" >>"$SUMMARY_FILE"
}

summary_print() {
    [[ -s "$SUMMARY_FILE" ]] || return 0
    log_step "Summary"
    awk -F'\t' '{
        st=$1; comp=$2; detail=$3;
        printf "  %-6s  %-22s  %s\n", st, comp, detail
    }' "$SUMMARY_FILE"
}

summary_has_failures() {
    grep -q '^FAIL' "$SUMMARY_FILE" 2>/dev/null
}

# ----------------------------- run lifecycle ---------------------------------
#
# Single-instance enforcement and child-process cleanup for start.sh and
# bootstrap.sh. These two scripts launch heavy background work (pytest,
# npm run build, alembic, uvicorn smoke). Without explicit lifecycle
# management, an interrupted run leaves orphans that race the next run
# on the stamp files and waste CPU.
#
# Public API:
#
#   run_acquire_lock <name>
#       Refuse to start if another instance with the same lock name is
#       running. Stale locks (PID no longer alive) are claimed
#       automatically. Echoes a clear PID + start-time + cmd diagnostic
#       on conflict so the operator can decide. Lockfile lives at
#       $REPO_ROOT/.git/<name>.lock — per-clone, never committed.
#
#   run_register_cleanup
#       Install an EXIT/INT/TERM trap that:
#         (a) kills every descendant process of $$, with two passes
#             (TERM, then KILL after a brief grace period), so a
#             Ctrl-C against bootstrap.sh actually stops pytest /
#             npm / alembic in flight.
#         (b) releases any lock acquired via run_acquire_lock.
#       Idempotent — safe to call once at the top of a script.
#       Compose-stack cleanup (the legacy `_cleanup_compose_override`
#       trap) must be added BEFORE this so it runs first.
#
#   run_preflight_orphan_check <pattern>
#       Scan for processes matching <pattern> that aren't the current
#       process tree. Prints a warning listing PIDs/cmds. Does not
#       fail — informational only. Combined with run_acquire_lock,
#       this catches stragglers that might have been missed by lock
#       cleanup (e.g. a `pytest` whose parent shell died ungracefully).

_RUN_LOCK_PATH=""

run_acquire_lock() {
    local name="$1"
    [[ -n "${REPO_ROOT:-}" ]] || die "run_acquire_lock: REPO_ROOT not set"
    local lock="$REPO_ROOT/.git/${name}.lock"
    _RUN_LOCK_PATH="$lock"
    if [[ -f "$lock" ]]; then
        local lock_pid lock_started lock_cmd
        lock_pid="$(sed -n 1p "$lock" 2>/dev/null)"
        lock_started="$(sed -n 2p "$lock" 2>/dev/null)"
        if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
            lock_cmd="$(ps -p "$lock_pid" -o args= 2>/dev/null | head -c 200)"
            log_err "Another '${name}' run is already in progress:"
            log_err "  PID    : $lock_pid"
            log_err "  Since  : ${lock_started:-unknown}"
            log_err "  CMD    : ${lock_cmd:-unknown}"
            log_err "Wait for it to finish, or stop it explicitly:"
            log_err "    kill $lock_pid"
            log_err "(do not just delete .git/${name}.lock — that orphans the running script)"
            exit 1
        fi
        if [[ -n "$lock_pid" ]]; then
            log_warn "Stale ${name} lock from PID $lock_pid (no longer running) — claiming"
        fi
    fi
    printf '%s\n%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$lock" 2>/dev/null \
        || die "could not write lockfile $lock"
}

# Internal: kills all descendant processes of $$ in two passes (TERM,
# then KILL after a brief grace). Recursion via pgrep -P; the loop
# bounds attempts to avoid pathological cases.
_run_kill_descendants() {
    local children pass
    for pass in 1 2; do
        children="$(pgrep -P $$ 2>/dev/null | tr '\n' ' ')"
        [[ -z "${children// }" ]] && return 0
        if [[ $pass -eq 1 ]]; then
            # shellcheck disable=SC2086  # space-delimited PID list
            kill -TERM $children 2>/dev/null || true
            # Brief grace for clean shutdown.
            local i=0
            while (( i < 10 )); do
                children="$(pgrep -P $$ 2>/dev/null | tr '\n' ' ')"
                [[ -z "${children// }" ]] && return 0
                sleep 0.2
                i=$((i + 1))
            done
        else
            # shellcheck disable=SC2086
            kill -KILL $children 2>/dev/null || true
        fi
    done
}

_run_release_lock() {
    [[ -n "$_RUN_LOCK_PATH" && -f "$_RUN_LOCK_PATH" ]] || return 0
    # Only remove the lock if WE own it (in case the file got replaced
    # by another instance somehow).
    local owner
    owner="$(sed -n 1p "$_RUN_LOCK_PATH" 2>/dev/null)"
    if [[ "$owner" == "$$" ]]; then
        rm -f "$_RUN_LOCK_PATH" 2>/dev/null || true
    fi
}

_RUN_CLEANUP_REGISTERED=0
run_register_cleanup() {
    [[ $_RUN_CLEANUP_REGISTERED -eq 1 ]] && return 0
    _RUN_CLEANUP_REGISTERED=1
    # Chain after any pre-existing EXIT trap (e.g. bootstrap's
    # _cleanup_compose_override). Use printf to capture the existing
    # trap body and prepend ours.
    local existing
    existing="$(trap -p EXIT 2>/dev/null | sed -E "s/^trap -- '(.*)' EXIT$/\\1/")"
    if [[ -n "$existing" ]]; then
        # shellcheck disable=SC2064  # intentional eager expansion
        trap "_run_kill_descendants; _run_release_lock; $existing" EXIT
    else
        trap '_run_kill_descendants; _run_release_lock' EXIT
    fi
    trap '_run_kill_descendants; _run_release_lock; exit 130' INT
    trap '_run_kill_descendants; _run_release_lock; exit 143' TERM
}

run_preflight_orphan_check() {
    local pattern="$1"
    # Skip self ($$) and our parent tree. -ww gives full cmd; awk
    # filters out anything in the current process group.
    local current_pgid
    current_pgid="$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')"
    local orphans
    orphans="$(ps -eo pid,pgid,etime,args -ww 2>/dev/null \
        | awk -v me="$$" -v pgid="$current_pgid" \
            -v pat="$pattern" '
            NR==1 {next}
            $1==me {next}
            $2==pgid {next}
            $0 ~ pat {print}
        ' || true)"
    if [[ -n "$orphans" ]]; then
        log_warn "Detected possible orphan processes matching: $pattern"
        echo "$orphans" | sed 's/^/    /'
        log_warn "If these are unexpected, stop them before continuing:"
        log_warn "    pkill -f '$pattern'   # or kill <PID>"
    fi
}

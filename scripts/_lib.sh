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

# Lock-release-only variant: install an EXIT/INT/TERM trap that
# releases the held lock but does NOT kill descendant processes.
# Used by start.sh, which intentionally launches long-running
# services (the API, the frontend dev server) that must outlive
# the start.sh process. Killing them on start.sh exit would
# terminate the very services start.sh just brought up.
#
# bootstrap.sh continues to use run_register_cleanup (the
# descendant-killing variant) because its descendants are
# pytest / npm / alembic — meant to be reaped on abnormal exit.
run_register_lock_release_only() {
    [[ $_RUN_CLEANUP_REGISTERED -eq 1 ]] && return 0
    _RUN_CLEANUP_REGISTERED=1
    local existing
    existing="$(trap -p EXIT 2>/dev/null | sed -E "s/^trap -- '(.*)' EXIT$/\\1/")"
    if [[ -n "$existing" ]]; then
        # shellcheck disable=SC2064  # intentional eager expansion
        trap "_run_release_lock; $existing" EXIT
    else
        trap '_run_release_lock' EXIT
    fi
    trap '_run_release_lock; exit 130' INT
    trap '_run_release_lock; exit 143' TERM
}

# ----------------------------- application services --------------------------
#
# Launch and tear down the FXLab application services (FastAPI on 8000,
# Vite dev server on 5173) so `./scripts/start.sh` actually leaves the
# operator with a usable app at http://localhost:5173, not just a
# prepared environment.
#
# Each service has a PID file at .git/fxlab-app-<name>.pid (per-clone,
# never committed) and a log file at /tmp/fxlab-app-<name>.log.

app_pid_path() { printf '%s/.git/fxlab-app-%s.pid' "$REPO_ROOT" "$1"; }
app_log_path() { printf '/tmp/fxlab-app-%s.log' "$1"; }

# Returns 0 if a process is listening on the given port.
app_port_up() {
    local port="$1"
    timeout 1 bash -c "exec 9<>/dev/tcp/127.0.0.1/$port" 2>/dev/null
}

# Returns 0 if the recorded PID for <name> is still alive.
app_pid_alive() {
    local name="$1"
    local pid_file
    pid_file="$(app_pid_path "$name")"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# Launch a long-running command in the background as a detached process,
# write its PID to .git/fxlab-app-<name>.pid, redirect its stdout+stderr
# to /tmp/fxlab-app-<name>.log, and wait for the given port to start
# responding (30s budget). Returns 0 if the service comes up.
#
# Args: name, port, command...
app_launch() {
    local name="$1" port="$2"; shift 2
    local pid_file log_file
    pid_file="$(app_pid_path "$name")"
    log_file="$(app_log_path "$name")"

    if app_port_up "$port"; then
        log_ok "$name already up on http://localhost:$port"
        return 0
    fi

    # Stale PID file? Remove it.
    if [[ -f "$pid_file" ]]; then
        local old_pid
        old_pid="$(cat "$pid_file" 2>/dev/null || true)"
        if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
            log_warn "$name PID $old_pid is alive but port $port not responding"
            log_warn "  log tail: $log_file"
            tail -10 "$log_file" 2>/dev/null | sed 's/^/    /'
            return 1
        fi
        rm -f "$pid_file"
    fi

    log_step "Starting $name (background)"
    log_info "  cmd: $*"
    log_info "  log: $log_file"

    # setsid puts the child in its own session/pgid so it survives this
    # shell exiting (start.sh exits while the API keeps serving).
    # nohup makes the redirects survive too.
    setsid nohup "$@" >"$log_file" 2>&1 < /dev/null &
    local pid=$!
    disown "$pid" 2>/dev/null || true
    echo "$pid" >"$pid_file"

    local i=0 budget=30
    while (( i < budget )); do
        if app_port_up "$port"; then
            log_ok "$name up on http://localhost:$port (PID $pid)"
            return 0
        fi
        # If the process died mid-startup, fail fast.
        if ! kill -0 "$pid" 2>/dev/null; then
            log_err "$name (PID $pid) exited before port $port became reachable"
            log_err "  log tail:"
            tail -20 "$log_file" 2>/dev/null | sed 's/^/    /'
            rm -f "$pid_file"
            return 1
        fi
        sleep 1
        i=$((i + 1))
    done
    log_err "$name did not come up on port $port within ${budget}s"
    log_err "  log tail:"
    tail -20 "$log_file" 2>/dev/null | sed 's/^/    /'
    return 1
}

# Send TERM to the recorded PID, then KILL after 5s if still alive.
# Removes the PID file. Returns 0 either way (idempotent).
app_stop() {
    local name="$1"
    local pid_file
    pid_file="$(app_pid_path "$name")"
    [[ -f "$pid_file" ]] || { log_skip "$name not running (no PID file)"; return 0; }
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        log_skip "$name PID was stale — cleared"
        return 0
    fi
    log_step "Stopping $name (PID $pid)"
    # Kill the entire process group (setsid put us in our own group)
    # so child npm/node/uvicorn workers die too.
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    local i=0
    while (( i < 10 )); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
        i=$((i + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    log_ok "$name stopped"
}

# Print one line per known app service: name, status, PID, port.
app_status() {
    local services=("$@")
    local svc
    for svc in "${services[@]}"; do
        local name="${svc%%:*}" port="${svc##*:}"
        if app_port_up "$port"; then
            local pid
            pid="$(cat "$(app_pid_path "$name")" 2>/dev/null || echo "?")"
            log_ok "$name up on http://localhost:$port (PID $pid)"
        else
            log_info "$name DOWN (port $port not responding)"
        fi
    done
}

run_preflight_orphan_check() {
    local pattern="$1"
    # Build the set of PIDs we must NOT flag: ourselves, every
    # ancestor of ourselves up to PID 1, and every descendant of
    # ourselves. Same-pgid filtering is unreliable because bash
    # invoked as `bash <script>` (or via the Claude harness wrapper)
    # creates a new process group, so the parent harness shell ends
    # up in a different pgid even though it is a legitimate ancestor
    # we should not flag as an orphan.
    local exempt_pids=" $$ "
    local p="$$"
    local depth=0
    while (( depth < 50 )); do
        local pp
        pp="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
        [[ -z "$pp" || "$pp" == "0" || "$pp" == "1" ]] && break
        exempt_pids+="$pp "
        p="$pp"
        depth=$((depth + 1))
    done
    # Descendants (transitive): expand via pgrep -P repeatedly.
    # `|| true` is required on the pgrep — pgrep returns exit 1 when
    # there are no matching children, which under start.sh's
    # `set -euo pipefail` would propagate through the command
    # substitution and silently exit the entire script.
    local frontier="$$"
    depth=0
    while (( depth < 50 )) && [[ -n "$frontier" ]]; do
        local next=""
        local pid
        for pid in $frontier; do
            local kids
            kids="$(pgrep -P "$pid" 2>/dev/null | tr '\n' ' ' || true)"
            for k in $kids; do
                exempt_pids+="$k "
                next+="$k "
            done
        done
        frontier="$next"
        depth=$((depth + 1))
    done

    # Filter logic:
    #   - Skip the header row.
    #   - Skip exempt PIDs (self + ancestors + descendants).
    #   - Skip our own pipeline tools (awk/grep/ps) — without this,
    #     the awk we are running here matches its own command line
    #     because the pattern ("\.venv/bin/python -m pytest") appears
    #     literally in its `-v pat=...` arg.
    #   - Match the pattern only against the COMMAND portion of the
    #     line ($4 onward), not the whole line.
    #   - CRITICAL for shared-host correctness: only flag a process
    #     as an FXLab orphan if its working directory is inside
    #     $REPO_ROOT. Other applications on this box may use
    #     `.venv/bin/python -m pytest` too — we must never report or
    #     touch those. We do this in a second pass below because awk
    #     cannot read /proc/<pid>/cwd portably.
    local candidate_pids
    candidate_pids="$(ps -eo pid,pgid,etime,args -ww 2>/dev/null \
        | awk -v exempt=" $exempt_pids " \
              -v pat="$pattern" '
            NR==1 {next}
            { tok=" " $1 " " }
            index(exempt, tok) > 0 {next}
            $4 == "awk" || $4 == "grep" || $4 == "ps" {next}
            {
                cmd = ""
                for (i = 4; i <= NF; i++) cmd = cmd " " $i
                if (cmd ~ pat) print $1
            }
        ' || true)"

    # Per-candidate CWD scoping. Linux: /proc/<pid>/cwd is a symlink
    # to the process's current directory. Skip processes whose CWD is
    # not inside REPO_ROOT — those belong to a different application
    # sharing this host.
    local orphans=""
    local cpid
    for cpid in $candidate_pids; do
        local pid_cwd
        pid_cwd="$(readlink "/proc/$cpid/cwd" 2>/dev/null || true)"
        if [[ -z "$pid_cwd" ]]; then
            # Cannot read CWD (process gone, or non-Linux fallback).
            # On non-Linux we conservatively skip — if we can't prove
            # it belongs to this repo, we don't report it.
            continue
        fi
        if [[ "$pid_cwd" != "$REPO_ROOT" && "$pid_cwd" != "$REPO_ROOT"/* ]]; then
            continue
        fi
        local row
        row="$(ps -p "$cpid" -o pid,pgid,etime,args -ww 2>/dev/null | tail -n +2 || true)"
        [[ -n "$row" ]] && orphans+="$row"$'\n'
    done
    if [[ -n "$orphans" ]]; then
        log_warn "Detected possible orphan processes matching: $pattern"
        echo "$orphans" | sed 's/^/    /'
        log_warn "If these are unexpected, stop them before continuing:"
        log_warn "    pkill -f '$pattern'   # or kill <PID>"
    fi
}

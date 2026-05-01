#!/usr/bin/env bash
# scripts/healthcheck.sh
#
# Fast health probe for the FXLab dev environment.
#
# This is the default mode of `./scripts/start.sh`. It is NOT a
# user-facing script — operators only ever invoke `./scripts/start.sh`.
# The healthcheck answers two questions, in this order, and never both:
#
#   1. Is the box healthy enough to start working?
#         (compose services up, .env complete, .venv present, etc.)
#         If any probe fails irrecoverably, exit 1 and the operator
#         must act (start docker, fix .env, etc.).
#
#   2. Are all per-step stamps current vs the working tree?
#         If any stamp is stale (someone added a migration, edited a
#         frontend file, bumped requirements.txt), exit 10 and start.sh
#         auto-escalates into the refresh pipeline. The refresh will
#         skip the steps whose stamps already match.
#
# Exit codes:
#   0   healthy — no work needed
#   10  refresh-required — at least one stamp stale or one artefact
#       missing (.venv, frontend/node_modules, frontend/dist).
#   1   hard-fail — at least one external service unreachable or the
#       .env file is missing or incomplete. Refreshing will not fix it.
#
# Total budget: ~10 seconds. Probes that need network use a 2-second
# per-probe timeout.

set -uo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/_lib.sh"
# shellcheck source=scripts/_fingerprint.sh
source "$SCRIPT_DIR/_fingerprint.sh"
# shellcheck source=scripts/_stamps.sh
source "$SCRIPT_DIR/_stamps.sh"

cd "$REPO_ROOT" || die "cannot cd to repo root: $REPO_ROOT"

# Result accumulators. We collect everything before deciding the exit
# code so the output shows the full picture even when there's an early
# hard-fail.
NEEDS_REFRESH=()
HARD_FAILS=()
WARNINGS=()
PASSES=()

mark_pass()         { PASSES+=("$1"); }
mark_warn()         { WARNINGS+=("$1"); }
mark_refresh()      { NEEDS_REFRESH+=("$1"); }
mark_hard_fail()    { HARD_FAILS+=("$1"); }

# ---------------------------------------------------------------------------
# Load .env into the process environment (DATABASE_URL, REDIS_URL,
# KEYCLOAK_*, etc.). If .env is absent that's a hard-fail — refresh
# cannot create a working .env without operator confirmation.
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    mark_hard_fail ".env"
else
    set -a
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    set +a
    mark_pass ".env loaded"
fi

# ---------------------------------------------------------------------------
# Compare .env keys against .env.example. Missing keys → hard-fail; the
# refresh pipeline does not fill in production secrets.
# ---------------------------------------------------------------------------
_env_keys_complete() {
    [[ -f .env && -f .env.example ]] || return 1
    local example_keys env_keys missing
    example_keys="$(grep -E '^[A-Z_][A-Z0-9_]*=' .env.example 2>/dev/null \
                        | sed -E 's/=.*$//' | sort -u)"
    env_keys="$(grep -E '^[A-Z_][A-Z0-9_]*=' .env 2>/dev/null \
                        | sed -E 's/=.*$//' | sort -u)"
    missing="$(comm -23 <(echo "$example_keys") <(echo "$env_keys"))"
    [[ -z "$missing" ]]
}
if [[ -f .env ]]; then
    if _env_keys_complete; then
        mark_pass ".env keys complete"
    else
        mark_hard_fail ".env keys (missing keys vs .env.example)"
    fi
fi

# ---------------------------------------------------------------------------
# Artefact presence — these are produced by `make bootstrap` and the
# frontend build. Missing → refresh-required (refresh will recreate).
# ---------------------------------------------------------------------------
[[ -d .venv && -x .venv/bin/python ]] \
    && mark_pass ".venv" \
    || mark_refresh ".venv missing or non-functional"

[[ -d frontend/node_modules ]] \
    && mark_pass "frontend/node_modules" \
    || mark_refresh "frontend/node_modules missing"

[[ -d frontend/dist ]] \
    && mark_pass "frontend/dist (last build present)" \
    || mark_refresh "frontend/dist missing (no prior build)"

# ---------------------------------------------------------------------------
# TCP reachability — bash's /dev/tcp pseudo-device gives us a 2s probe
# without depending on pg_isready / redis-cli being installed. We only
# verify the port accepts a connection; protocol-level health is
# already covered by step_compose_up's docker compose ps probe at
# refresh time.
# ---------------------------------------------------------------------------
_probe_tcp() {
    local host="$1" port="$2" budget="${3:-2}"
    # The /dev/tcp open happens inside the `timeout` subshell, so its
    # fd is auto-closed when that subshell exits. Do NOT use a bare
    # `exec 9<&- 2>/dev/null` here — that's the special form of exec
    # that permanently rewrites the parent shell's redirections, which
    # silences every subsequent stderr write (including set -x trace
    # and any error log) for the rest of the script.
    timeout "$budget" bash -c "exec 9<>/dev/tcp/$host/$port" 2>/dev/null
}

# Parse host:port out of a libpq-style URL or a plain host:port.
_url_host() {
    local url="$1"
    # postgres://user:pass@host:port/db -> host
    # redis://host:port/db -> host
    # http://host:port/... -> host
    # The `([^@]+@)?` group is optional userinfo. Without this, the
    # earlier `[^@]*@?` form greedily ate the entire host:port/path
    # whenever there was no `@` in the URL.
    echo "$url" | sed -E 's|^[a-z]+://([^@]+@)?||; s|[/?].*$||; s|:[0-9]+$||'
}
_url_port() {
    local url="$1" default_port="$2"
    local p
    p="$(echo "$url" | sed -E 's|^[a-z]+://([^@]+@)?||; s|[/?].*$||' | grep -oE ':[0-9]+$' | tr -d ':')"
    echo "${p:-$default_port}"
}

# Postgres
if [[ -n "${DATABASE_URL:-}" ]]; then
    pg_host="$(_url_host "$DATABASE_URL")"
    pg_port="$(_url_port "$DATABASE_URL" 5432)"
    if _probe_tcp "$pg_host" "$pg_port"; then
        mark_pass "postgres ($pg_host:$pg_port)"
    else
        mark_hard_fail "postgres ($pg_host:$pg_port) unreachable"
    fi
else
    mark_warn "DATABASE_URL not set — skipping postgres probe"
fi

# Redis — accept either REDIS_URL (libpq-style) or REDIS_HOST/REDIS_PORT.
redis_host=""; redis_port=""
if [[ -n "${REDIS_URL:-}" ]]; then
    redis_host="$(_url_host "$REDIS_URL")"
    redis_port="$(_url_port "$REDIS_URL" 6379)"
elif [[ -n "${REDIS_HOST:-}" ]]; then
    redis_host="${REDIS_HOST}"
    redis_port="${REDIS_PORT:-6379}"
fi
if [[ -n "$redis_host" ]]; then
    if _probe_tcp "$redis_host" "$redis_port"; then
        mark_pass "redis ($redis_host:$redis_port)"
    else
        mark_hard_fail "redis ($redis_host:$redis_port) unreachable"
    fi
else
    mark_warn "redis env vars not set — skipping redis probe"
fi

# Keycloak — accept KEYCLOAK_URL (preferred), KEYCLOAK_INTERNAL_URL,
# KEYCLOAK_PUBLIC_URL, or KEYCLOAK_HOST.
kc_url=""
if [[ -n "${KEYCLOAK_URL:-}" ]]; then
    kc_url="${KEYCLOAK_URL}"
elif [[ -n "${KEYCLOAK_INTERNAL_URL:-}" ]]; then
    kc_url="${KEYCLOAK_INTERNAL_URL}"
elif [[ -n "${KEYCLOAK_PUBLIC_URL:-}" ]]; then
    kc_url="${KEYCLOAK_PUBLIC_URL}"
elif [[ -n "${KEYCLOAK_HOST:-}" ]]; then
    kc_url="http://${KEYCLOAK_HOST}:8080"
fi
if [[ -n "$kc_url" ]]; then
    kc_host="$(_url_host "$kc_url")"
    kc_port="$(_url_port "$kc_url" 8080)"
    if _probe_tcp "$kc_host" "$kc_port"; then
        mark_pass "keycloak ($kc_host:$kc_port)"
    else
        mark_hard_fail "keycloak ($kc_host:$kc_port) unreachable"
    fi
fi

# ---------------------------------------------------------------------------
# Per-step stamps. Each one mirrors the fingerprint computation used by
# the corresponding step in scripts/bootstrap.sh, so a stamp matches iff
# the next refresh would skip that step. If any stamp is stale → at
# least one step needs to run → exit 10 (refresh-required).
# ---------------------------------------------------------------------------

# Migrate the legacy pytest stamp the first time we see it (parallels
# the migration that step_backend_tests does).
stamp_migrate_legacy "$REPO_ROOT/.git/fxlab-bootstrap-tests.stamp" "tests"

# tests stamp — workspace fingerprint
fp="$(fingerprint_workspace)"
if stamp_matches tests "$fp"; then
    mark_pass "tests stamp current"
else
    mark_refresh "tests stamp stale (source changes since last green pytest run)"
fi

# deps stamp — make bootstrap inputs
fp="$(fingerprint_files \
        requirements.txt requirements-dev.txt pyproject.toml \
        frontend/package.json frontend/package-lock.json \
        Makefile)"
fp="$({ printf '%s\n' "$fp"; \
        printf 'venv-exists=%s\n' "$([[ -d .venv ]] && echo y || echo n)"; \
        printf 'node-modules-exists=%s\n' "$([[ -d frontend/node_modules ]] && echo y || echo n)"; \
      } | _sha256_stdin)"
if stamp_matches deps "$fp"; then
    mark_pass "deps stamp current"
else
    mark_refresh "deps stamp stale (requirements/package files changed)"
fi

# alembic stamp — migration set + DATABASE_URL
if [[ -n "${DATABASE_URL:-}" ]]; then
    fp="$({ fingerprint_globs 'alembic/versions/*.py'; printf 'db_url=%s\n' "$DATABASE_URL"; } | _sha256_stdin)"
    if stamp_matches alembic "$fp"; then
        mark_pass "alembic stamp current"
    else
        mark_refresh "alembic stamp stale (new migration or DATABASE_URL changed)"
    fi
fi

# frontend-build stamp — sources + config
fp="$({ fingerprint_globs \
            'frontend/src/**/*.ts' 'frontend/src/**/*.tsx' \
            'frontend/src/**/*.js' 'frontend/src/**/*.jsx' \
            'frontend/src/**/*.css' 'frontend/src/**/*.html'; \
        fingerprint_files \
            frontend/package.json frontend/package-lock.json \
            frontend/vite.config.ts frontend/vite.config.js \
            frontend/tsconfig.json frontend/tsconfig.node.json \
            frontend/index.html; \
        printf 'dist-exists=%s\n' "$([[ -d frontend/dist ]] && echo y || echo n)"; \
      } | _sha256_stdin)"
if stamp_matches frontend-build "$fp"; then
    mark_pass "frontend-build stamp current"
else
    mark_refresh "frontend-build stamp stale (frontend sources or config changed)"
fi

# ---------------------------------------------------------------------------
# Status mode — print and exit without deciding green/refresh/hard-fail.
# Used by `start.sh --status`.
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--status" ]]; then
    log_step "Healthcheck status"
    for p in "${PASSES[@]}";        do log_ok   "$p"; done
    for p in "${WARNINGS[@]}";      do log_warn "$p"; done
    for p in "${NEEDS_REFRESH[@]}"; do log_info "REFRESH: $p"; done
    for p in "${HARD_FAILS[@]}";    do log_err  "HARD-FAIL: $p"; done
    exit 0
fi

# ---------------------------------------------------------------------------
# Decide and report.
# ---------------------------------------------------------------------------
log_step "Healthcheck"
for p in "${PASSES[@]}";        do log_ok   "$p"; done
for p in "${WARNINGS[@]}";      do log_warn "$p"; done

if (( ${#HARD_FAILS[@]} > 0 )); then
    for p in "${HARD_FAILS[@]}"; do log_err "$p"; done
    log_err "Healthcheck found hard failures — operator action required."
    log_err "Fix the issues above (start docker compose, restore .env, etc.) then retry."
    exit 1
fi

if (( ${#NEEDS_REFRESH[@]} > 0 )); then
    for p in "${NEEDS_REFRESH[@]}"; do log_info "stale: $p"; done
    log_info "Refresh required (one or more stamps stale)."
    exit 10
fi

log_ok "All probes green — environment is ready."
exit 0

#!/usr/bin/env bash
#
# FXLab — developer-onboarding bootstrap.
#
# Single command for a fresh dev clone:
#
#   git clone git@github.com:glennatlayla/fxlab.git && cd fxlab && ./scripts/bootstrap.sh
#
# This is the *developer* bootstrap. For a production server install, use
# the Docker-based installer instead:
#
#   git clone git@github.com:glennatlayla/fxlab.git /opt/fxlab && sudo bash /opt/fxlab/install.sh
#
# What it does (idempotent — safe to re-run on a partially-bootstrapped clone):
#
#   1. Detects the OS package manager (apt / dnf / yum / pacman / brew) and
#      installs missing system prerequisites (python3, python3-venv matching
#      the system python version, build toolchain, curl, git) via sudo.
#   2. Verifies python3 + venv module after install.
#   3. Delegates .venv + Python deps + nodeenv + frontend npm install + git
#      pre-commit hooks to `make bootstrap`.
#   4. Optionally installs Docker via https://get.docker.com when
#      --install-docker is passed and docker is missing.
#   5. Detects Docker + Compose; brings up postgres + redis when present.
#   6. Creates .env from .env.example if missing, generating a fresh
#      JWT_SECRET_KEY via `secrets.token_hex(32)`.
#   7. Runs `alembic upgrade head` when DATABASE_URL is set.
#   8. Runs the credential validator (scripts/validate_env.py) and prints
#      a summary table of every external service it could reach.
#
# Flags:
#   --no-docker      Skip the docker compose + alembic steps (default if
#                    docker is unavailable; reports as such in the summary).
#   --no-sudo        Do not invoke sudo to install missing system packages;
#                    fail with an apt/dnf hint instead.
#   --install-docker Install Docker via https://get.docker.com if missing
#                    (off by default — Docker is an invasive system change).
#   --reset-env      Regenerate .env from .env.example with fresh secrets,
#                    archiving the existing .env to .archive/<UTC>/.env first.
#   --skip-tests     Skip the pytest gate (useful on slow machines or CI shards).
#   --skip-frontend-build  Skip the frontend `npm run build` smoke test.
#   --skip-backend-smoke   Skip the uvicorn /health smoke test.
#   --validate-only  Run only the credential validator (assumes a healthy venv).
#   -h, --help       Show this help and exit.
#
# Exit codes:
#   0 — every probed component passed
#   1 — a hard precondition (python3, make bootstrap) failed
#   2 — bootstrap finished but at least one component reported FAIL
#
set -uo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/_lib.sh"

# --------------------------- option parsing ----------------------------------

DO_DOCKER=1
DO_TESTS=1
DO_FRONTEND_BUILD=1
DO_BACKEND_SMOKE=1
VALIDATE_ONLY=0
USE_SUDO=1
INSTALL_DOCKER=0
RESET_ENV=0

usage() {
    sed -n '2,46p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-docker)            DO_DOCKER=0 ;;
        --no-sudo)              USE_SUDO=0 ;;
        --install-docker)       INSTALL_DOCKER=1 ;;
        --reset-env)            RESET_ENV=1 ;;
        --skip-tests)           DO_TESTS=0 ;;
        --skip-frontend-build)  DO_FRONTEND_BUILD=0 ;;
        --skip-backend-smoke)   DO_BACKEND_SMOKE=0 ;;
        --validate-only)        VALIDATE_ONLY=1 ;;
        -h|--help)              usage; exit 0 ;;
        *) log_err "unknown flag: $1"; usage; exit 1 ;;
    esac
    shift
done

cd "$REPO_ROOT" || die "cannot cd to repo root: $REPO_ROOT"
summary_init

readonly OS="$(detect_os)"
log_info "host: os=$OS"

# --------------------------- system package detection ------------------------

# Detect the host's package manager. Echoes one of: apt, dnf, yum, pacman,
# brew, or empty if none is found.
detect_pkg_manager() {
    if   have_cmd apt-get; then echo apt
    elif have_cmd dnf;     then echo dnf
    elif have_cmd yum;     then echo yum
    elif have_cmd pacman;  then echo pacman
    elif have_cmd brew;    then echo brew
    else echo ""
    fi
}

# Run a command with sudo if needed and allowed. Falls back to direct
# invocation when already root (EUID 0). Returns the wrapped command's
# exit code.
sudo_run() {
    if [[ $EUID -eq 0 ]]; then
        "$@"
        return $?
    fi
    if [[ $USE_SUDO -eq 0 ]]; then
        log_err "sudo required for: $* — but --no-sudo was passed"
        return 1
    fi
    if ! have_cmd sudo; then
        log_err "sudo not installed — cannot escalate for: $*"
        return 1
    fi
    sudo "$@"
}

# Compute the matching python3-venv apt package name from the system
# python3 version (e.g. 3.12 → python3.12-venv). Falls back to the
# generic python3-venv when the precise version package isn't available.
apt_python_venv_pkg() {
    local v
    if have_cmd python3; then
        v="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    fi
    if [[ -n "${v:-}" ]] && apt-cache show "python${v}-venv" >/dev/null 2>&1; then
        echo "python${v}-venv"
    else
        echo "python3-venv"
    fi
}

# --------------------------- step: system prereqs ----------------------------

# Install the OS-level packages bootstrap needs. Idempotent — `apt-get install`
# / `dnf install` no-op when packages are already present.
step_system_prereqs() {
    log_step "System prerequisites"
    local pm
    pm="$(detect_pkg_manager)"

    case "$pm" in
        apt)
            local venv_pkg
            venv_pkg="$(apt_python_venv_pkg)"
            local pkgs=(python3 "$venv_pkg" python3-pip build-essential curl git ca-certificates)
            log_info "apt: ensuring ${pkgs[*]}"
            sudo_run apt-get update -qq 2>&1 | tail -3 || true
            if sudo_run apt-get install -y --no-install-recommends "${pkgs[@]}" 2>&1 | tail -3; then
                log_ok "apt prerequisites installed/up-to-date"
                summary_row OK system-prereqs "apt: ${venv_pkg} + build tools"
            else
                log_err "apt-get install failed"
                summary_row FAIL system-prereqs "apt-get install failed"
                return 1
            fi
            ;;
        dnf|yum)
            local pkgs=(python3 python3-virtualenv python3-pip @"Development Tools" curl git ca-certificates)
            log_info "$pm: ensuring ${pkgs[*]}"
            if sudo_run "$pm" install -y "${pkgs[@]}" 2>&1 | tail -3; then
                log_ok "$pm prerequisites installed/up-to-date"
                summary_row OK system-prereqs "$pm: python3 + dev tools"
            else
                log_err "$pm install failed"
                summary_row FAIL system-prereqs "$pm install failed"
                return 1
            fi
            ;;
        pacman)
            local pkgs=(python python-pip base-devel curl git ca-certificates)
            log_info "pacman: ensuring ${pkgs[*]}"
            if sudo_run pacman -S --needed --noconfirm "${pkgs[@]}" 2>&1 | tail -3; then
                log_ok "pacman prerequisites installed/up-to-date"
                summary_row OK system-prereqs "pacman: python + base-devel"
            else
                log_err "pacman -S failed"
                summary_row FAIL system-prereqs "pacman -S failed"
                return 1
            fi
            ;;
        brew)
            local pkgs=(python@3.12 git curl)
            log_info "brew: ensuring ${pkgs[*]}"
            if brew install "${pkgs[@]}" 2>&1 | tail -3; then
                log_ok "brew prerequisites installed/up-to-date"
                summary_row OK system-prereqs "brew: python@3.12 + git + curl"
            else
                log_warn "brew install reported issues — continuing"
                summary_row WARN system-prereqs "brew install issues"
            fi
            ;;
        "")
            log_warn "no supported package manager detected (apt/dnf/yum/pacman/brew)"
            log_warn "manual prereqs: python3 + venv module + build toolchain + curl + git"
            summary_row WARN system-prereqs "no package manager"
            ;;
        *)
            log_warn "unknown package manager: $pm"
            summary_row WARN system-prereqs "unknown pkg mgr"
            ;;
    esac
}

# --------------------------- step: python ------------------------------------

step_python() {
    log_step "Python prerequisites"
    if ! have_cmd python3; then
        log_err "python3 still missing after system prereqs step"
        summary_row FAIL python3 "not installed"
        return 1
    fi
    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
        log_err "python3 venv/ensurepip module still unavailable after system prereqs step"
        log_err "  matching package: $(apt_python_venv_pkg)"
        summary_row FAIL python-venv "venv/ensurepip missing"
        return 1
    fi
    log_ok "python3 $(python3 --version 2>&1 | awk '{print $2}') with venv module"
    summary_row OK python3 "$(python3 --version 2>&1)"
}

# --------------------------- step: docker install ----------------------------

# Optional — runs only when --install-docker is passed and docker is missing.
# Uses the official convenience script from get.docker.com.
step_install_docker() {
    [[ $INSTALL_DOCKER -eq 1 ]] || return 0
    have_cmd docker && return 0
    log_step "Installing Docker via https://get.docker.com"
    if ! have_cmd curl; then
        log_err "curl required to fetch Docker installer"
        summary_row FAIL docker-install "curl missing"
        return 0
    fi
    local script_path
    script_path="$(mktemp)"
    if curl -fsSL https://get.docker.com -o "$script_path" && sudo_run sh "$script_path"; then
        log_ok "Docker installed"
        summary_row OK docker-install "via get.docker.com"
        # Add the invoking user to the docker group so subsequent runs don't need sudo.
        if [[ $EUID -ne 0 ]] && have_cmd sudo; then
            sudo_run usermod -aG docker "$USER" || true
            log_warn "added $USER to docker group — log out + back in to take effect"
        fi
    else
        log_err "Docker install failed"
        summary_row FAIL docker-install "get.docker.com script failed"
    fi
    rm -f "$script_path"
}

# --------------------------- step: make bootstrap ----------------------------

step_make_bootstrap() {
    log_step "make bootstrap (.venv + Python deps + nodeenv + frontend deps + hooks)"
    if make bootstrap; then
        log_ok "make bootstrap complete"
        summary_row OK make-bootstrap "venv + Python + node + frontend"
    else
        log_err "make bootstrap failed — see output above"
        summary_row FAIL make-bootstrap "non-zero exit"
        return 1
    fi
}

# --------------------------- step: docker ------------------------------------

# Returns 0 if a TCP port is in use on localhost, 1 otherwise.
# Tries `ss` first (most modern Linux), falls back to `nc`, then `lsof`.
_port_in_use() {
    local port="$1"
    if have_cmd ss;   then ss -ltn "( sport = :$port )" 2>/dev/null | grep -q ":$port "; return $?; fi
    if have_cmd nc;   then nc -z localhost "$port" >/dev/null 2>&1; return $?; fi
    if have_cmd lsof; then lsof -i ":$port" -sTCP:LISTEN >/dev/null 2>&1; return $?; fi
    # No probe available — be conservative and report "not in use" so
    # we don't block the bootstrap on a missing tool.
    return 1
}

step_docker() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "docker (--no-docker)"; summary_row SKIP docker "--no-docker"; return 0; }
    log_step "Docker + Compose detection"
    if ! have_cmd docker; then
        log_warn "docker not on PATH (compose stack will be skipped)"
        log_warn "  Install: https://docs.docker.com/engine/install/"
        log_warn "  Or run bootstrap with --install-docker to install via get.docker.com"
        summary_row WARN docker "not installed"
        DO_DOCKER=0
        return 0
    fi
    if ! docker info >/dev/null 2>&1; then
        # Distinguish "daemon down" from "user not in docker group" — the
        # latter is by far the most common dev-machine failure mode.
        if [[ $EUID -ne 0 ]] && ! groups 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
            log_warn "docker daemon unreachable AND $USER is not in the 'docker' group"
            log_warn "  Fix: sudo usermod -aG docker $USER"
            log_warn "  Then log out + back in (or: newgrp docker) and re-run bootstrap"
            summary_row WARN docker "user not in docker group"
        else
            log_warn "docker daemon not reachable (try: sudo systemctl start docker)"
            summary_row WARN docker "daemon down"
        fi
        DO_DOCKER=0
        return 0
    fi
    if docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    elif have_cmd docker-compose; then
        DOCKER_COMPOSE="docker-compose"
    else
        log_warn "docker compose plugin not installed"
        summary_row WARN docker "no compose plugin"
        DO_DOCKER=0
        return 0
    fi
    log_ok "$($DOCKER_COMPOSE version | head -n1)"
    summary_row OK docker "$($DOCKER_COMPOSE version | head -n1)"
}

# --------------------------- step: dotenv ------------------------------------

# Upsert a KEY=VALUE pair into the file at .env.
# - If the key exists (commented or uncommented), replace its line.
# - Otherwise append `KEY=VALUE` to the file.
_upsert_env() {
    local key="$1" value="$2"
    local esc_value
    # Escape sed metacharacters in the value: backslash, ampersand, |.
    esc_value="$(printf '%s' "$value" | sed -e 's/[\&|]/\\&/g')"
    if grep -qE "^[[:space:]]*#?[[:space:]]*${key}=" .env 2>/dev/null; then
        sed -i.bak -E "s|^[[:space:]]*#?[[:space:]]*${key}=.*|${key}=${esc_value}|" .env
        rm -f .env.bak
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

# Required keys for the dev stack to start AND for the validator to PASS.
# step_dotenv detects when .env is missing any of these and prompts the
# operator to re-run with --reset-env (instead of silently leaving them
# unset). Keep this list in sync with what step_dotenv populates below.
readonly REQUIRED_DOTENV_KEYS=(
    JWT_SECRET_KEY
    POSTGRES_PASSWORD
    KEYCLOAK_ADMIN_PASSWORD
    POSTGRES_HOST
    POSTGRES_PORT
    POSTGRES_DB
    POSTGRES_USER
    DATABASE_URL
    REDIS_HOST
    REDIS_PORT
    REDIS_URL
    CELERY_BROKER_URL
)

# Returns the count of REQUIRED_DOTENV_KEYS that are present and uncommented
# in .env. Used to detect a half-populated .env left over from an older
# bootstrap run.
_count_required_keys_present() {
    local key count=0
    [[ -f .env ]] || { echo 0; return; }
    for key in "${REQUIRED_DOTENV_KEYS[@]}"; do
        if grep -qE "^[[:space:]]*${key}=[^[:space:]]" .env 2>/dev/null; then
            count=$((count + 1))
        fi
    done
    echo "$count"
}

step_dotenv() {
    log_step ".env"

    # --reset-env: archive the existing .env and regenerate.
    if [[ $RESET_ENV -eq 1 && -f .env ]]; then
        local stamp archive_dir
        stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
        archive_dir=".archive/${stamp%T*}"
        mkdir -p "$archive_dir"
        cp .env "$archive_dir/${stamp}_dotenv"
        rm .env
        log_warn "--reset-env: archived previous .env to $archive_dir/${stamp}_dotenv"
    fi

    if [[ -f .env ]]; then
        local present
        present="$(_count_required_keys_present)"
        local total=${#REQUIRED_DOTENV_KEYS[@]}
        if [[ $present -lt $total ]]; then
            log_warn ".env is half-populated ($present / $total required keys present)"
            log_warn "  Re-run with --reset-env to regenerate (existing .env will be archived)"
            log_warn "  Or edit .env manually — required keys: ${REQUIRED_DOTENV_KEYS[*]}"
            summary_row WARN dotenv "half-populated ($present/$total)"
        else
            log_ok ".env exists with all required keys (left untouched)"
            summary_row OK dotenv "exists ($present/$total keys)"
        fi
        # Tighten permissions even on existing files — defensive.
        chmod 600 .env 2>/dev/null || true
        return 0
    fi

    if [[ ! -f .env.example ]]; then
        log_warn ".env.example missing — skipping .env creation"
        summary_row WARN dotenv ".env.example missing"
        return 0
    fi
    cp .env.example .env
    chmod 600 .env

    # All three secrets need to be populated for the docker-compose stack
    # to start at all (POSTGRES_PASSWORD and KEYCLOAK_ADMIN_PASSWORD are
    # `:?required` in docker-compose.yml — without them, `docker compose up`
    # fails before any container starts). JWT_SECRET_KEY is required by the
    # API container's lifespan startup.
    local jwt_secret pg_password kc_admin_password
    jwt_secret="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)"
    pg_password="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || true)"
    kc_admin_password="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(16))' 2>/dev/null || true)"

    if [[ -z "$jwt_secret" || -z "$pg_password" || -z "$kc_admin_password" ]]; then
        log_warn "could not generate secrets (.venv/bin/python failed?)"
        summary_row WARN dotenv "created (secrets not generated)"
        return 0
    fi

    # Required secrets — without these, compose-up fails outright.
    _upsert_env JWT_SECRET_KEY              "$jwt_secret"
    _upsert_env POSTGRES_PASSWORD           "$pg_password"
    _upsert_env KEYCLOAK_ADMIN_PASSWORD     "$kc_admin_password"

    # Localhost connection strings — point at the dev compose stack.
    # The validator probes these next; with the stack up, they PASS.
    _upsert_env POSTGRES_HOST               "localhost"
    _upsert_env POSTGRES_PORT               "5432"
    _upsert_env POSTGRES_DB                 "fxlab"
    _upsert_env POSTGRES_USER               "fxlab"
    _upsert_env DATABASE_URL                "postgresql://fxlab:${pg_password}@localhost:5432/fxlab"
    _upsert_env REDIS_HOST                  "localhost"
    _upsert_env REDIS_PORT                  "6379"
    _upsert_env REDIS_URL                   "redis://localhost:6379/0"
    _upsert_env CELERY_BROKER_URL           "redis://localhost:6379/0"

    # Keycloak / S3 are kept commented in dev — Keycloak realm setup is a
    # heavier bring-up (requires the keycloak service plus realm import
    # which can take 60+s on first boot) and MinIO is not in the dev
    # docker-compose stack at all. Operators uncomment when needed.

    chmod 600 .env
    log_ok ".env created (chmod 600) with generated secrets + localhost service URLs"
    summary_row OK dotenv "created (secrets + dev URLs populated)"
}

# --------------------------- step: compose up --------------------------------

# Per-service "did compose bring this up?" flags. Read by step_alembic and
# step_dotenv to decide whether to run/probe against that service vs. SKIP
# cleanly. Set by step_compose_up below.
COMPOSE_PG_UP=0
COMPOSE_REDIS_UP=0

# Helper: bring up a single compose service, polling for healthy. Sets
# the named flag variable to 1 on success. Returns 0 always (the caller
# decides whether a missed service is fatal).
_compose_up_one() {
    local svc="$1" flag_var="$2" port="$3"
    local existing
    existing="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -x "fxlab-${svc}" || true)"
    if [[ -z "$existing" ]] && _port_in_use "$port"; then
        log_warn "$svc: port $port in use by host service — skipping compose ${svc}"
        log_warn "  Stop host service: sudo systemctl stop ${svc} (or postgresql / redis-server)"
        summary_row WARN "compose-${svc}" "port $port in use on host"
        return 0
    fi
    if $DOCKER_COMPOSE up -d --wait "$svc" >/dev/null 2>&1; then
        log_ok "compose ${svc} up + healthy"
        summary_row OK "compose-${svc}" "up + healthy"
        eval "$flag_var=1"
        return 0
    fi
    # Older compose plugins don't support --wait. Fall back to detached
    # up + healthcheck poll loop (60s budget, 3s cadence).
    if ! $DOCKER_COMPOSE up -d "$svc" 2>&1 | tail -3; then
        log_err "compose up ${svc} failed"
        summary_row FAIL "compose-${svc}" "up failed"
        return 0
    fi
    local budget=60 elapsed=0 cid status
    log_info "$svc: polling healthcheck (budget ${budget}s)"
    while (( elapsed < budget )); do
        cid="$($DOCKER_COMPOSE ps -q "$svc" 2>/dev/null | head -1)"
        if [[ -n "$cid" ]]; then
            status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo unknown)"
            if [[ "$status" == "healthy" ]]; then
                log_ok "compose ${svc} healthy after ${elapsed}s (polled)"
                summary_row OK "compose-${svc}" "up + healthy (polled)"
                eval "$flag_var=1"
                return 0
            fi
        fi
        sleep 3; elapsed=$((elapsed + 3))
    done
    log_warn "compose ${svc} not healthy after ${budget}s"
    summary_row WARN "compose-${svc}" "health unconfirmed after ${budget}s"
}

step_compose_up() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "compose up (docker unavailable)"; return 0; }
    log_step "Compose stack — postgres + redis"
    # Bring up each service independently — a port conflict on one must
    # NOT prevent the other from coming up. Downstream steps (alembic,
    # validator, dotenv) consult COMPOSE_PG_UP / COMPOSE_REDIS_UP to
    # decide whether to use that service or SKIP cleanly.
    _compose_up_one postgres COMPOSE_PG_UP    5432
    _compose_up_one redis    COMPOSE_REDIS_UP 6379
}

# Comment out a key in .env so the validator SKIPs that probe instead of
# trying to connect with our generated creds against an unrelated host
# service. Idempotent — already-commented lines stay commented.
_comment_out_env_key() {
    local key="$1"
    [[ -f .env ]] || return 0
    if grep -qE "^[[:space:]]*${key}=" .env 2>/dev/null; then
        sed -i.bak -E "s|^([[:space:]]*)${key}=|\\1# ${key}=|" .env
        rm -f .env.bak
    fi
}

# After step_compose_up determines which services actually came up,
# reconcile .env so the validator only probes services we control.
# When postgres-compose didn't come up (port conflict, daemon down,
# etc.), comment out POSTGRES_*/DATABASE_URL so the validator SKIPs
# the postgres probe rather than FAILing against an unrelated host
# service. Same for redis. The operator can uncomment + adjust when
# they want to point at host services manually.
step_reconcile_env_with_compose() {
    [[ -f .env ]] || return 0
    log_step "Reconciling .env with compose state"
    local changed=0
    if [[ $COMPOSE_PG_UP -ne 1 ]]; then
        for key in POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL; do
            _comment_out_env_key "$key"
        done
        log_warn "compose postgres unavailable — POSTGRES_*/DATABASE_URL commented in .env"
        changed=1
    fi
    if [[ $COMPOSE_REDIS_UP -ne 1 ]]; then
        for key in REDIS_HOST REDIS_PORT REDIS_URL CELERY_BROKER_URL; do
            _comment_out_env_key "$key"
        done
        log_warn "compose redis unavailable — REDIS_*/CELERY_BROKER_URL commented in .env"
        changed=1
    fi
    if (( changed == 0 )); then
        log_ok ".env already aligned with compose state"
        summary_row OK reconcile-env "all compose services up"
    else
        summary_row WARN reconcile-env "commented out keys for unavailable services"
    fi
}

# --------------------------- step: alembic -----------------------------------

step_alembic() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "alembic (docker disabled)"; return 0; }
    if [[ $COMPOSE_PG_UP -ne 1 ]]; then
        log_skip "alembic — compose postgres did not come up (port conflict or failure)"
        summary_row SKIP alembic "compose postgres unavailable"
        return 0
    fi

    log_step "alembic upgrade head"
    # Extract DATABASE_URL from .env. Bash subprocesses (alembic) do NOT
    # inherit env vars set inside an inline `python -c` block, so we
    # must export it into the bash environment explicitly. Without this
    # alembic falls back to alembic.ini's `driver://` placeholder and
    # fails with NoSuchModuleError.
    local db_url
    db_url="$(grep -E '^[[:space:]]*DATABASE_URL=' .env 2>/dev/null | head -1 | sed -E 's|^[[:space:]]*DATABASE_URL=||')"
    if [[ -z "$db_url" ]]; then
        log_skip "alembic — DATABASE_URL not set in .env"
        summary_row SKIP alembic "DATABASE_URL unset"
        return 0
    fi

    local attempt=1 max=3 delay=2
    while (( attempt <= max )); do
        if DATABASE_URL="$db_url" .venv/bin/alembic upgrade head 2>&1 | tail -5; then
            log_ok "migrations applied (attempt $attempt)"
            summary_row OK alembic "head (attempt $attempt)"
            return 0
        fi
        log_warn "alembic upgrade failed (attempt $attempt/$max) — retrying in ${delay}s"
        sleep "$delay"
        delay=$((delay * 2))
        attempt=$((attempt + 1))
    done
    log_err "alembic upgrade failed after $max attempts"
    summary_row FAIL alembic "upgrade failed (3 attempts)"
}

# --------------------------- step: validate env ------------------------------

step_validate_env() {
    log_step "Credential validation"
    if [[ ! -f scripts/validate_env.py ]]; then
        log_skip "scripts/validate_env.py not found"
        return 0
    fi
    set +e
    .venv/bin/python scripts/validate_env.py
    local rc=$?
    set -e 2>/dev/null || true
    case $rc in
        0) summary_row OK   validate-env "all checked services reachable" ;;
        2) summary_row WARN validate-env "some checks skipped (env vars unset)" ;;
        *) summary_row FAIL validate-env "rc=$rc" ;;
    esac
}

# --------------------------- step: pytest ------------------------------------

step_backend_tests() {
    [[ $DO_TESTS -eq 1 ]] || { log_skip "backend pytest (--skip-tests)"; return 0; }
    log_step "Backend tests (pytest)"
    # The docker-compose integration test and the npm-build test both
    # depend on environments outside the container — deselect them so
    # bootstrap pytest passes on hosts where docker or npm isn't ready.
    # Real CI re-runs the full suite without these guards.
    local pytest_args=(
        -q --no-cov
        --ignore=tests/integration/test_docker_compose_startup.py
        --deselect=tests/unit/test_m0_frontend_structure.py::test_ac8_npm_build_succeeds
    )
    if .venv/bin/python -m pytest "${pytest_args[@]}" 2>&1 | tail -3 | tee /tmp/fxlab_pytest.out | grep -qE '^=+ [0-9]+ passed'; then
        log_ok "$(tail -1 /tmp/fxlab_pytest.out)"
        summary_row OK pytest "$(tail -1 /tmp/fxlab_pytest.out | tr -s ' ')"
    else
        log_err "pytest reported failures"
        summary_row FAIL pytest "see /tmp/fxlab_pytest.out"
    fi
}

# --------------------------- step: frontend build smoke ----------------------

step_frontend_build() {
    [[ $DO_FRONTEND_BUILD -eq 1 ]] || { log_skip "frontend build (--skip-frontend-build)"; return 0; }
    if [[ ! -f frontend/package.json ]]; then
        log_skip "frontend/package.json missing"
        return 0
    fi
    log_step "Frontend build smoke (typecheck + build)"
    local node_bin
    if [[ -x .venv/bin/node ]]; then
        node_bin="$REPO_ROOT/.venv/bin"
    elif have_cmd node; then
        node_bin="$(dirname "$(command -v node)")"
    else
        log_warn "no node binary available — skipping frontend build smoke"
        summary_row WARN frontend-build "no node binary"
        return 0
    fi
    # Run typecheck and build separately so we know which one tripped.
    if (cd frontend && PATH="$node_bin:$PATH" npm run --silent typecheck 2>&1 | tail -8); then
        log_ok "tsc --noEmit clean"
    else
        log_warn "tsc --noEmit reported errors (continuing)"
        summary_row WARN frontend-build "tsc errors"
        return 0
    fi
    if (cd frontend && PATH="$node_bin:$PATH" npm run --silent build 2>&1 | tail -8); then
        log_ok "vite build succeeded"
        summary_row OK frontend-build "tsc + vite build green"
    else
        log_err "vite build failed"
        summary_row FAIL frontend-build "vite build failed"
    fi
}

# --------------------------- step: backend smoke -----------------------------

step_backend_smoke() {
    [[ $DO_BACKEND_SMOKE -eq 1 ]] || { log_skip "backend smoke (--skip-backend-smoke)"; return 0; }
    [[ -x .venv/bin/uvicorn ]] || .venv/bin/python -m pip install --quiet uvicorn 2>&1 | tail -3 || true
    if ! .venv/bin/python -c 'import uvicorn' 2>/dev/null; then
        log_skip "uvicorn not installed — skipping backend smoke"
        return 0
    fi
    if ! have_cmd curl; then
        log_skip "curl not installed — skipping backend smoke"
        return 0
    fi
    log_step "Backend smoke (uvicorn /health)"
    local pidfile log
    pidfile="$(mktemp)"
    log="$(mktemp)"
    # Boot uvicorn in background; allow it 10s to come up; curl /health.
    (
        cd "$REPO_ROOT"
        nohup .venv/bin/python -m uvicorn services.api.main:app --host 127.0.0.1 --port 18000 \
            >"$log" 2>&1 &
        echo $! >"$pidfile"
    )
    local pid budget=10 elapsed=0 ok=0
    pid="$(cat "$pidfile")"
    while (( elapsed < budget )); do
        if curl -fsS --max-time 2 http://127.0.0.1:18000/health >/dev/null 2>&1; then
            ok=1; break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$pidfile" "$log"
    if (( ok == 1 )); then
        log_ok "uvicorn /health returned 200 within ${elapsed}s"
        summary_row OK backend-smoke "uvicorn /health 200 in ${elapsed}s"
    else
        log_warn "uvicorn /health did not return 200 within ${budget}s"
        summary_row WARN backend-smoke "no /health 200 in ${budget}s"
    fi
}

# --------------------------- main flow ---------------------------------------

if [[ $VALIDATE_ONLY -eq 1 ]]; then
    [[ -x .venv/bin/python ]] || die "no .venv — run bootstrap first"
    step_validate_env
    summary_print
    summary_has_failures && exit 2 || exit 0
fi

step_system_prereqs || die "system prerequisites step failed"
step_python         || die "python prerequisites missing after install"
step_make_bootstrap || die "make bootstrap failed"
step_install_docker
step_docker
step_dotenv
step_compose_up
step_reconcile_env_with_compose
step_alembic
step_validate_env
step_backend_tests
step_frontend_build
step_backend_smoke

summary_print
if summary_has_failures; then
    log_err "bootstrap finished with failures (see summary above)"
    exit 2
fi
log_ok "bootstrap complete"

cat <<'NEXT'

What's next:
  • API:        http://localhost:8000  (docs: /docs)
  • Frontend:   cd frontend && npm run dev   → http://localhost:5173
  • Verify:     make verify
  • Re-validate creds:  make validate-env
  • Re-run bootstrap:   ./scripts/bootstrap.sh        (idempotent)
  • Reset .env:         ./scripts/bootstrap.sh --reset-env

Production install path is unchanged:
  sudo bash install.sh    (full Docker/systemd/Keycloak/nginx stack)
NEXT
exit 0

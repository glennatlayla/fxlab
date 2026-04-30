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
#   --skip-tests     Skip the pytest gate (useful on slow machines or CI shards).
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
VALIDATE_ONLY=0
USE_SUDO=1
INSTALL_DOCKER=0

usage() {
    sed -n '2,38p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-docker)      DO_DOCKER=0 ;;
        --no-sudo)        USE_SUDO=0 ;;
        --install-docker) INSTALL_DOCKER=1 ;;
        --skip-tests)     DO_TESTS=0 ;;
        --validate-only)  VALIDATE_ONLY=1 ;;
        -h|--help)        usage; exit 0 ;;
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

step_docker() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "docker (--no-docker)"; summary_row SKIP docker "--no-docker"; return 0; }
    log_step "Docker + Compose detection"
    if ! have_cmd docker; then
        log_warn "docker not on PATH (compose stack will be skipped)"
        log_warn "  Install: https://docs.docker.com/engine/install/"
        summary_row WARN docker "not installed"
        DO_DOCKER=0
        return 0
    fi
    if ! docker info >/dev/null 2>&1; then
        log_warn "docker daemon not reachable (try: sudo systemctl start docker)"
        summary_row WARN docker "daemon down"
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

step_dotenv() {
    log_step ".env"
    if [[ -f .env ]]; then
        log_ok ".env exists (left untouched — re-runs preserve operator-set values)"
        summary_row OK dotenv "exists"
        return 0
    fi
    if [[ ! -f .env.example ]]; then
        log_warn ".env.example missing — skipping .env creation"
        summary_row WARN dotenv ".env.example missing"
        return 0
    fi
    cp .env.example .env

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

    log_ok ".env created with generated secrets + localhost service URLs"
    summary_row OK dotenv "created (secrets + dev URLs populated)"
}

# --------------------------- step: compose up --------------------------------

step_compose_up() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "compose up (docker unavailable)"; return 0; }
    log_step "Compose stack — postgres + redis"
    local services="postgres redis"
    # `--wait` blocks until healthchecks pass (postgres pg_isready, redis PING).
    # Falls back gracefully if --wait isn't supported (older compose plugins).
    if $DOCKER_COMPOSE up -d --wait $services 2>&1 | tail -8; then
        log_ok "compose up -d --wait $services succeeded (services healthy)"
        summary_row OK compose "$services up + healthy"
    elif $DOCKER_COMPOSE up -d $services 2>&1 | tail -8; then
        log_warn "compose up succeeded without --wait — services may still be starting"
        summary_row WARN compose "$services up (health unconfirmed)"
        # Brief settle to let healthchecks fire before the validator probes.
        sleep 5
    else
        log_warn "compose up failed (the dev stack may need attention)"
        summary_row FAIL compose "up failed"
    fi
}

# --------------------------- step: alembic -----------------------------------

step_alembic() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "alembic (compose stack unavailable)"; return 0; }
    log_step "alembic upgrade head"
    if .venv/bin/python -c "
import os, sys
from pathlib import Path
env = Path('.env')
if env.exists():
    for line in env.read_text().splitlines():
        s = line.strip()
        if s.startswith('DATABASE_URL=') and not s.startswith('#'):
            os.environ['DATABASE_URL'] = s.split('=', 1)[1].strip()
            break
sys.exit(0 if os.environ.get('DATABASE_URL') else 1)
" 2>/dev/null; then
        if .venv/bin/alembic upgrade head 2>&1 | tail -5; then
            log_ok "migrations applied"
            summary_row OK alembic "head"
        else
            log_warn "alembic upgrade failed"
            summary_row WARN alembic "upgrade failed"
        fi
    else
        log_skip "alembic — DATABASE_URL not set in .env"
        summary_row SKIP alembic "DATABASE_URL unset"
    fi
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
    if .venv/bin/python -m pytest -q --no-cov 2>&1 | tail -3 | tee /tmp/fxlab_pytest.out | grep -qE '^=+ [0-9]+ passed'; then
        log_ok "$(tail -1 /tmp/fxlab_pytest.out)"
        summary_row OK pytest "$(tail -1 /tmp/fxlab_pytest.out | tr -s ' ')"
    else
        log_err "pytest reported failures"
        summary_row FAIL pytest "see /tmp/fxlab_pytest.out"
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
step_alembic
step_validate_env
step_backend_tests

summary_print
if summary_has_failures; then
    log_err "bootstrap finished with failures (see summary above)"
    exit 2
fi
log_ok "bootstrap complete"
exit 0

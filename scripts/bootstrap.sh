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
#   1. Verifies python3 + python3-venv are present (apt hint on miss).
#   2. Delegates Python venv + nodeenv + frontend npm install to `make bootstrap`.
#   3. Detects Docker + Compose; brings up postgres + redis if requested.
#   4. Creates .env from .env.example if missing, generating a fresh
#      JWT_SECRET_KEY via `secrets.token_hex(32)`.
#   5. Runs `alembic upgrade head` when DATABASE_URL is set.
#   6. Runs the credential validator (scripts/validate_env.py) and prints
#      a summary table of every external service it could reach.
#
# Flags:
#   --no-docker      Skip the docker compose + alembic steps (default if
#                    docker is unavailable; reports as such in the summary).
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

usage() {
    sed -n '2,32p' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-docker)     DO_DOCKER=0 ;;
        --skip-tests)    DO_TESTS=0 ;;
        --validate-only) VALIDATE_ONLY=1 ;;
        -h|--help)       usage; exit 0 ;;
        *) log_err "unknown flag: $1"; usage; exit 1 ;;
    esac
    shift
done

cd "$REPO_ROOT" || die "cannot cd to repo root: $REPO_ROOT"
summary_init

readonly OS="$(detect_os)"
log_info "host: os=$OS"

# --------------------------- step: python --------------------------------------

step_python() {
    log_step "Python prerequisites"
    if ! have_cmd python3; then
        log_err "python3 not on PATH"
        log_err "  Debian/Ubuntu: sudo apt install python3 python3-venv"
        log_err "  Fedora/RHEL:   sudo dnf install python3"
        log_err "  macOS:         brew install python@3.12  (or use python.org installer)"
        summary_row FAIL python3 "not installed"
        return 1
    fi
    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
        log_err "python3 venv module is unavailable"
        log_err "  Debian/Ubuntu: sudo apt install python3.12-venv"
        log_err "  Fedora/RHEL:   sudo dnf install python3-venv"
        summary_row FAIL python-venv "venv/ensurepip missing"
        return 1
    fi
    log_ok "python3 $(python3 --version 2>&1 | awk '{print $2}') with venv module"
    summary_row OK python3 "$(python3 --version 2>&1)"
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

step_dotenv() {
    log_step ".env"
    if [[ -f .env ]]; then
        log_ok ".env exists (left untouched)"
        summary_row OK dotenv "exists"
        return 0
    fi
    if [[ ! -f .env.example ]]; then
        log_warn ".env.example missing — skipping .env creation"
        summary_row WARN dotenv ".env.example missing"
        return 0
    fi
    cp .env.example .env
    local jwt_secret
    jwt_secret="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)"
    if [[ -z "$jwt_secret" ]]; then
        log_warn "could not generate JWT_SECRET_KEY (.venv/bin/python failed?)"
        summary_row WARN dotenv "created (JWT_SECRET_KEY not set)"
        return 0
    fi
    if grep -q '^# JWT_SECRET_KEY=' .env; then
        sed -i.bak "s|^# JWT_SECRET_KEY=.*$|JWT_SECRET_KEY=${jwt_secret}|" .env && rm -f .env.bak
    else
        printf '\nJWT_SECRET_KEY=%s\n' "$jwt_secret" >> .env
    fi
    log_ok ".env created from .env.example (JWT_SECRET_KEY generated)"
    summary_row OK dotenv "created"
}

# --------------------------- step: compose up --------------------------------

step_compose_up() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "compose up (docker unavailable)"; return 0; }
    log_step "Compose stack — postgres + redis"
    local services="postgres redis"
    if $DOCKER_COMPOSE up -d $services 2>&1 | tail -8; then
        log_ok "compose up -d $services succeeded"
        summary_row OK compose "$services up"
    else
        log_warn "compose up failed (the dev stack may need attention)"
        summary_row WARN compose "up failed"
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

step_python         || die "python prerequisites missing"
step_make_bootstrap || die "make bootstrap failed"
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

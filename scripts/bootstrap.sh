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
#   --evict-conflicts
#                    When a Docker container from another project is bound
#                    to a port we need (5432, 6379), stop and remove it.
#                    PRESERVES that container's image and named volumes —
#                    only the container instance is destroyed. Bring it
#                    back later with `docker compose up` from its own
#                    project directory. OFF by default; opt-in only.
#   --reset-env      Regenerate .env from .env.example with fresh secrets,
#                    archiving the existing .env to .archive/<UTC>/.env first.
#   --skip-tests     Skip the pytest gate (hard skip — useful on slow
#                    machines or CI shards). Compare with --force-tests.
#   --force-tests    Force the pytest gate even when the workspace
#                    fingerprint matches the last green run. By default
#                    every heavy step (make bootstrap, alembic, frontend
#                    build, pytest) is gated on a per-step fingerprint
#                    and skipped when nothing has changed since the last
#                    passing run. Use these flags to override individual
#                    steps; pass --force to override every gate.
#   --force-deps     Re-run `make bootstrap` (pip + npm install) even if
#                    the deps fingerprint matches.
#   --force-alembic  Re-run `alembic upgrade head` even if the migration
#                    set is unchanged.
#   --force-frontend-build  Re-run the frontend `npm run build` smoke
#                    even if the frontend source fingerprint matches.
#   --force          Equivalent to passing every --force-* flag at once.
#   --skip-frontend-build  Skip the frontend `npm run build` smoke test.
#   --skip-backend-smoke   Skip the uvicorn /health smoke test.
#   --no-keycloak    Skip the keycloak compose service + realm init step.
#                    Use when working on a slice that does not need the IdP
#                    (saves ~3 minutes on first bootstrap; the api container
#                    falls back to HS256 self-rolled tokens).
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
# shellcheck source=scripts/_fingerprint.sh
source "$SCRIPT_DIR/_fingerprint.sh"
# shellcheck source=scripts/_stamps.sh
source "$SCRIPT_DIR/_stamps.sh"

# --------------------------- option parsing ----------------------------------

DO_DOCKER=1
DO_TESTS=1
FORCE_TESTS=0
FORCE_DEPS=0
FORCE_ALEMBIC=0
FORCE_FRONTEND_BUILD=0
DO_FRONTEND_BUILD=1
DO_BACKEND_SMOKE=1
DO_KEYCLOAK=1
VALIDATE_ONLY=0
USE_SUDO=1
INSTALL_DOCKER=0
RESET_ENV=0
EVICT_CONFLICTS=0

usage() {
    # Print every leading-comment block (lines 2..first non-comment),
    # so help stays in sync with the documented flag list as the header
    # grows. Avoids the previous hard-coded `sed -n '2,60p'` which
    # silently truncated newly-added flags.
    awk 'NR==1 {next} /^[^#]/ {exit} {print}' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-docker)            DO_DOCKER=0 ;;
        --no-sudo)               USE_SUDO=0 ;;
        --install-docker)       INSTALL_DOCKER=1 ;;
        --evict-conflicts)      EVICT_CONFLICTS=1 ;;
        --reset-env)            RESET_ENV=1 ;;
        --skip-tests)           DO_TESTS=0 ;;
        --force-tests)          FORCE_TESTS=1 ;;
        --force-deps)           FORCE_DEPS=1 ;;
        --force-alembic)        FORCE_ALEMBIC=1 ;;
        --force-frontend-build) FORCE_FRONTEND_BUILD=1 ;;
        --force)                FORCE_TESTS=1; FORCE_DEPS=1
                                FORCE_ALEMBIC=1; FORCE_FRONTEND_BUILD=1 ;;
        --skip-frontend-build)  DO_FRONTEND_BUILD=0 ;;
        --skip-backend-smoke)   DO_BACKEND_SMOKE=0 ;;
        --no-keycloak)          DO_KEYCLOAK=0 ;;
        --validate-only)        VALIDATE_ONLY=1 ;;
        -h|--help)              usage; exit 0 ;;
        *) log_err "unknown flag: $1"; usage; exit 1 ;;
    esac
    shift
done

cd "$REPO_ROOT" || die "cannot cd to repo root: $REPO_ROOT"
summary_init

# Refuse concurrent bootstrap runs immediately. The cleanup-trap
# registration is deferred to AFTER the existing compose-override
# trap is set so we chain onto it rather than overwriting it.
# start.sh acquires its own outer lock; this inner lock catches
# direct `./scripts/bootstrap.sh` invocations.
run_acquire_lock fxlab-bootstrap

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
    # Fingerprint the inputs that drive `make bootstrap`: Python deps
    # files, frontend package manifests, the Makefile itself, and the
    # presence of the .venv / node_modules outputs. If all match the
    # last green run, skip the (expensive) reinstall.
    local fp
    fp="$(fingerprint_files \
        requirements.txt requirements-dev.txt pyproject.toml \
        frontend/package.json frontend/package-lock.json \
        Makefile)"
    # Existence of the produced artefacts is part of the fingerprint —
    # if the operator nuked .venv or frontend/node_modules, force a
    # reinstall by mixing those into the digest.
    fp="$({ printf '%s\n' "$fp"; \
            printf 'venv-exists=%s\n' "$([[ -d .venv ]] && echo y || echo n)"; \
            printf 'node-modules-exists=%s\n' "$([[ -d frontend/node_modules ]] && echo y || echo n)"; \
          } | _sha256_stdin)"
    if [[ $FORCE_DEPS -eq 0 ]] && stamp_matches deps "$fp"; then
        log_skip "make bootstrap (deps fingerprint matches last green run; --force-deps to override)"
        summary_row OK make-bootstrap "skipped — Python/npm deps unchanged"
        return 0
    fi
    log_step "make bootstrap (.venv + Python deps + nodeenv + frontend deps + hooks)"
    if make bootstrap; then
        log_ok "make bootstrap complete"
        summary_row OK make-bootstrap "venv + Python + node + frontend"
        stamp_record deps "$fp"
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
    KEYCLOAK_ADMIN_CLIENT_SECRET
    POSTGRES_HOST
    POSTGRES_PORT
    POSTGRES_DB
    POSTGRES_USER
    DATABASE_URL
    REDIS_HOST
    REDIS_PORT
    REDIS_URL
    CELERY_BROKER_URL
    KEYCLOAK_URL
    KEYCLOAK_REALM
    KEYCLOAK_CLIENT_ID
    KEYCLOAK_ADMIN
    FXLAB_ADMIN_EMAIL
    FXLAB_ADMIN_PASSWORD
)

# Returns 0 when the given KEY is present and uncommented in .env, 1 otherwise.
# Used by step_dotenv to decide whether to upsert a missing key vs leaving an
# operator-set value alone.
_key_present_in_env() {
    local key="$1"
    [[ -f .env ]] || return 1
    grep -qE "^[[:space:]]*${key}=[^[:space:]]" .env 2>/dev/null
}

# Echo the value of KEY from .env (first match, uncommented). Echoes empty
# string when the key is absent or commented.
_read_env_value() {
    local key="$1"
    [[ -f .env ]] || return 0
    grep -E "^[[:space:]]*${key}=" .env 2>/dev/null | head -1 | sed -E "s|^[[:space:]]*${key}=||"
}

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

    # --reset-env: archive the existing .env and regenerate from scratch.
    if [[ $RESET_ENV -eq 1 && -f .env ]]; then
        local stamp archive_dir
        stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
        archive_dir=".archive/${stamp%T*}"
        mkdir -p "$archive_dir"
        cp .env "$archive_dir/${stamp}_dotenv"
        rm .env
        log_warn "--reset-env: archived previous .env to $archive_dir/${stamp}_dotenv"
    fi

    # Bootstrap a fresh .env from .env.example when missing.
    if [[ ! -f .env ]]; then
        if [[ ! -f .env.example ]]; then
            log_warn ".env.example missing — skipping .env creation"
            summary_row WARN dotenv ".env.example missing"
            return 0
        fi
        cp .env.example .env
        chmod 600 .env
        log_info ".env created from .env.example (secrets will be generated next)"
    fi
    chmod 600 .env 2>/dev/null || true

    # Upsert-if-missing pass: for every required key, if it is absent or
    # commented in .env, supply a value. Existing operator-set values are
    # preserved verbatim. This makes step_dotenv idempotent across:
    #   - fresh installs (.env created from .env.example, then secrets added)
    #   - upgrades (new required keys added without rotating existing creds)
    #   - half-populated state (prior bootstrap aborted mid-write)
    #
    # Secrets (JWT, postgres password, Keycloak admin password, Keycloak
    # service-account client secret) are generated only when their key is
    # missing — never regenerated when a value already exists, since that
    # would invalidate live tokens / desynchronise from a running Keycloak.

    local secret_jwt secret_pg secret_kc_admin secret_kc_api

    if ! _key_present_in_env JWT_SECRET_KEY; then
        secret_jwt="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)"
        if [[ -n "${secret_jwt:-}" ]]; then
            _upsert_env JWT_SECRET_KEY "$secret_jwt"
        else
            log_warn "could not generate JWT_SECRET_KEY (.venv/bin/python failed?)"
        fi
    fi

    if ! _key_present_in_env POSTGRES_PASSWORD; then
        secret_pg="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || true)"
        if [[ -n "${secret_pg:-}" ]]; then
            _upsert_env POSTGRES_PASSWORD "$secret_pg"
        else
            log_warn "could not generate POSTGRES_PASSWORD"
        fi
    fi

    if ! _key_present_in_env KEYCLOAK_ADMIN_PASSWORD; then
        secret_kc_admin="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(16))' 2>/dev/null || true)"
        if [[ -n "${secret_kc_admin:-}" ]]; then
            _upsert_env KEYCLOAK_ADMIN_PASSWORD "$secret_kc_admin"
        else
            log_warn "could not generate KEYCLOAK_ADMIN_PASSWORD"
        fi
    fi

    if ! _key_present_in_env KEYCLOAK_ADMIN_CLIENT_SECRET; then
        secret_kc_api="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || true)"
        if [[ -n "${secret_kc_api:-}" ]]; then
            _upsert_env KEYCLOAK_ADMIN_CLIENT_SECRET "$secret_kc_api"
        else
            log_warn "could not generate KEYCLOAK_ADMIN_CLIENT_SECRET"
        fi
    fi

    # FXLab realm admin user. setup-realm.sh provisions this user in Keycloak
    # with the password set TEMPORARY (forces change on first login). We
    # default the email to the operator's git identity when available — that
    # gets a real address into the realm rather than admin@fxlab.local.
    if ! _key_present_in_env FXLAB_ADMIN_EMAIL; then
        local default_email
        default_email="$(git config user.email 2>/dev/null || true)"
        [[ -n "$default_email" ]] || default_email="admin@fxlab.local"
        _upsert_env FXLAB_ADMIN_EMAIL "$default_email"
    fi
    if ! _key_present_in_env FXLAB_ADMIN_PASSWORD; then
        local secret_admin_pwd
        secret_admin_pwd="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(18))' 2>/dev/null || true)"
        if [[ -n "${secret_admin_pwd:-}" ]]; then
            _upsert_env FXLAB_ADMIN_PASSWORD "$secret_admin_pwd"
        else
            log_warn "could not generate FXLAB_ADMIN_PASSWORD"
        fi
    fi

    # Non-secret defaults — connection strings + Keycloak realm configuration
    # pointing at the local compose stack. Upsert only when missing so an
    # operator who pointed POSTGRES_HOST at a host-side database (or
    # KEYCLOAK_URL at a remote IdP) stays pointed there.
    _key_present_in_env POSTGRES_HOST       || _upsert_env POSTGRES_HOST       "localhost"
    _key_present_in_env POSTGRES_PORT       || _upsert_env POSTGRES_PORT       "5432"
    _key_present_in_env POSTGRES_DB         || _upsert_env POSTGRES_DB         "fxlab"
    _key_present_in_env POSTGRES_USER       || _upsert_env POSTGRES_USER       "fxlab"
    _key_present_in_env REDIS_HOST          || _upsert_env REDIS_HOST          "localhost"
    _key_present_in_env REDIS_PORT          || _upsert_env REDIS_PORT          "6379"
    _key_present_in_env REDIS_URL           || _upsert_env REDIS_URL           "redis://localhost:6379/0"
    _key_present_in_env CELERY_BROKER_URL   || _upsert_env CELERY_BROKER_URL   "redis://localhost:6379/0"
    _key_present_in_env KEYCLOAK_URL        || _upsert_env KEYCLOAK_URL        "http://localhost:8080"
    _key_present_in_env KEYCLOAK_REALM      || _upsert_env KEYCLOAK_REALM      "fxlab"
    _key_present_in_env KEYCLOAK_CLIENT_ID  || _upsert_env KEYCLOAK_CLIENT_ID  "fxlab-api"
    _key_present_in_env KEYCLOAK_ADMIN      || _upsert_env KEYCLOAK_ADMIN      "admin"

    # DATABASE_URL is composed from POSTGRES_PASSWORD, so it must be upserted
    # AFTER the password upsert above. Read whatever password ended up in .env
    # (newly generated or operator-set) and weave it into the URL.
    if ! _key_present_in_env DATABASE_URL; then
        local pg_pwd
        pg_pwd="$(_read_env_value POSTGRES_PASSWORD)"
        if [[ -n "$pg_pwd" ]]; then
            _upsert_env DATABASE_URL "postgresql://fxlab:${pg_pwd}@localhost:5432/fxlab"
        else
            log_warn "DATABASE_URL not set and POSTGRES_PASSWORD missing — skipping"
        fi
    fi

    chmod 600 .env

    # Reconcile coverage. With the upsert-if-missing pass above, a complete
    # state is the norm; warn loudly if anything still slipped through (e.g.
    # python unavailable, .env.example structurally broken).
    local present total
    present="$(_count_required_keys_present)"
    total=${#REQUIRED_DOTENV_KEYS[@]}
    if [[ $present -lt $total ]]; then
        log_warn ".env partially populated ($present / $total required keys present)"
        log_warn "  Re-run with --reset-env to regenerate cleanly"
        summary_row WARN dotenv "partial ($present/$total)"
    else
        log_ok ".env has all $total required keys (chmod 600)"
        summary_row OK dotenv "complete ($present/$total)"
    fi
}

# --------------------------- step: compose up --------------------------------

# Per-service "did compose bring this up?" flags. Read by step_alembic and
# step_dotenv to decide whether to run/probe against that service vs. SKIP
# cleanly. Set by step_compose_up below.
COMPOSE_PG_UP=0
COMPOSE_REDIS_UP=0
COMPOSE_KC_UP=0

# Temporary docker-compose override file. Generated lazily when a port
# remap is needed to coexist with another stack on this host. Cleaned up
# via the EXIT trap below.
COMPOSE_OVERRIDE_FILE=""

_cleanup_compose_override() {
    [[ -n "$COMPOSE_OVERRIDE_FILE" && -f "$COMPOSE_OVERRIDE_FILE" ]] && rm -f "$COMPOSE_OVERRIDE_FILE"
}
trap _cleanup_compose_override EXIT
# Now that the compose trap is set, register the descendant-killer +
# lock-releaser. run_register_cleanup chains onto the existing EXIT
# trap, so on exit we run (in order): kill descendants, release the
# fxlab-bootstrap lock, clean up the compose override file. Critical
# for preventing orphan pytest / npm / alembic when the operator
# Ctrl-Cs bootstrap mid-run.
run_register_cleanup

# Find an available TCP port starting at $1, incrementing up to $2
# (default 100) attempts. Echoes the port; returns 1 if none free.
_pick_free_port() {
    local p="$1" tries="${2:-100}" attempt=0
    while (( attempt < tries )); do
        if ! _port_in_use "$p"; then echo "$p"; return 0; fi
        p=$((p + 1))
        attempt=$((attempt + 1))
    done
    return 1
}

# Lazily create the compose override file with the standard YAML header.
_ensure_override_file() {
    if [[ -z "$COMPOSE_OVERRIDE_FILE" ]]; then
        COMPOSE_OVERRIDE_FILE="$(mktemp -t fxlab-compose-override.XXXXXX.yml)"
        printf 'services:\n' >"$COMPOSE_OVERRIDE_FILE"
    fi
}

# Append a single ports remap (host:container) to the override file.
_add_port_override() {
    local svc="$1" external="$2" internal="$3"
    _ensure_override_file
    cat >>"$COMPOSE_OVERRIDE_FILE" <<EOF
  ${svc}:
    ports:
      - "${external}:${internal}"
EOF
    log_info "compose override: ${svc} → ${external}:${internal}  (file: $COMPOSE_OVERRIDE_FILE)"
}

# Run docker compose with the override file chained in when it exists.
# The DOCKER_COMPOSE variable holds either "docker compose" or "docker-compose".
_compose() {
    if [[ -n "$COMPOSE_OVERRIDE_FILE" && -f "$COMPOSE_OVERRIDE_FILE" ]]; then
        $DOCKER_COMPOSE -f docker-compose.yml -f "$COMPOSE_OVERRIDE_FILE" "$@"
    else
        $DOCKER_COMPOSE "$@"
    fi
}

# Update .env's postgres-related connection vars to use a non-default port.
_remap_dotenv_postgres_port() {
    local new_port="$1"
    [[ -f .env ]] || return 0
    # POSTGRES_PORT and the port segment inside DATABASE_URL.
    sed -i.bak -E "s|^([[:space:]]*)POSTGRES_PORT=.*|\\1POSTGRES_PORT=${new_port}|" .env
    sed -i.bak -E "s|^([[:space:]]*DATABASE_URL=postgresql://[^:]+:[^@]+@[^:]+):[0-9]+(/.*)|\\1:${new_port}\\2|" .env
    rm -f .env.bak
}

_remap_dotenv_redis_port() {
    local new_port="$1"
    [[ -f .env ]] || return 0
    sed -i.bak -E "s|^([[:space:]]*)REDIS_PORT=.*|\\1REDIS_PORT=${new_port}|" .env
    sed -i.bak -E "s|^([[:space:]]*REDIS_URL=redis://[^:]+):[0-9]+(/.*)|\\1:${new_port}\\2|" .env
    sed -i.bak -E "s|^([[:space:]]*CELERY_BROKER_URL=redis://[^:]+):[0-9]+(/.*)|\\1:${new_port}\\2|" .env
    rm -f .env.bak
}

# Identify what's holding a TCP port: another Docker container (return its
# name), a SystemD-managed daemon (return its unit name), or just a PID +
# binary name. Echoes a single human-readable string; never errors.
_identify_port_holder() {
    local port="$1"

    # 1. Docker — fastest signal because we already have the daemon up.
    if have_cmd docker; then
        local cname
        cname="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
                  | awk -F'\t' -v port=":$port->" '$2 ~ port { print $1; exit }')"
        if [[ -n "$cname" ]]; then
            echo "docker container: $cname"
            return 0
        fi
    fi

    # 2. ss → PID + comm. Requires elevated privs to see foreign PIDs but
    #    works for the same-user case which is the common dev scenario.
    if have_cmd ss; then
        local proc
        proc="$(ss -ltnp "( sport = :$port )" 2>/dev/null \
                | awk 'NR>1 { print $NF; exit }')"
        if [[ -n "$proc" && "$proc" != "-" ]]; then
            # Format is users:(("comm",pid=N,fd=N))
            echo "process: $proc"
            return 0
        fi
    fi

    # 3. lsof — slower but more permissive on macOS.
    if have_cmd lsof; then
        local cmd_pid
        cmd_pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null \
                   | awk 'NR>1 { printf "%s (pid %s)", $1, $2; exit }')"
        if [[ -n "$cmd_pid" ]]; then
            echo "$cmd_pid"
            return 0
        fi
    fi

    echo "(holder unidentified)"
}

# Print actionable instructions for releasing a port held by either a
# Docker container or a host process.
_suggest_port_fix() {
    local svc="$1" port="$2" holder="$3"
    case "$holder" in
        "docker container: "*)
            local cname="${holder#docker container: }"
            log_warn "  Stop the container: docker stop $cname"
            log_warn "  Or remap our compose service to a different port (override docker-compose.yml)"
            ;;
        "process: "*)
            log_warn "  Inspect: $holder"
            log_warn "  If it's a SystemD daemon: sudo systemctl stop ${svc} (or postgresql / redis-server)"
            ;;
        *)
            log_warn "  Identify with: sudo ss -ltnp '( sport = :$port )'"
            log_warn "  Or: docker ps  (something else is bound to $port)"
            ;;
    esac
}

# If the holder is a foreign Docker container, stop + remove it. PRESERVES
# its image and any named/anonymous volumes. Returns 0 if a container was
# successfully evicted, 1 if the holder isn't a container or removal failed.
_evict_container_holder() {
    local holder="$1"
    if [[ "$holder" != "docker container: "* ]]; then
        log_warn "  --evict-conflicts only handles Docker containers; this holder is: $holder"
        return 1
    fi
    local cname="${holder#docker container: }"
    if [[ "$cname" == "fxlab-"* ]]; then
        # Defensive — never evict our own containers; they're stale state
        # the regular compose lifecycle should manage.
        log_warn "  refusing to evict our own container ($cname)"
        return 1
    fi
    log_warn "  --evict-conflicts: stopping + removing container '$cname' (image + volumes preserved)"
    if docker stop "$cname" >/dev/null 2>&1 && docker rm "$cname" >/dev/null 2>&1; then
        log_ok "  evicted $cname — port released"
        summary_row WARN "evict-conflict" "removed foreign container $cname"
        return 0
    fi
    log_err "  eviction of $cname failed — try manually: docker stop $cname && docker rm $cname"
    return 1
}

# Helper: bring up a single compose service, polling for healthy. Sets
# the named flag variable to 1 on success. Returns 0 always (the caller
# decides whether a missed service is fatal).
_compose_up_one() {
    local svc="$1" flag_var="$2" port="$3" remap_dotenv_fn="${4:-}" health_budget="${5:-60}"
    local existing
    existing="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -x "fxlab-${svc}" || true)"
    local effective_port="$port"

    if [[ -z "$existing" ]] && _port_in_use "$port"; then
        local holder
        holder="$(_identify_port_holder "$port")"
        log_warn "$svc: port $port in use by ${holder}"

        if [[ $EVICT_CONFLICTS -eq 1 ]] && _evict_container_holder "$holder"; then
            # Eviction succeeded — keep canonical port.
            :
        else
            # Coexistence path: pick a free alternate host port and add
            # a compose override so our service is published there
            # instead. Container-internal port stays 5432/6379, which is
            # what the rest of our stack (api -> postgres on the
            # docker network) uses, so api/keycloak don't need changes.
            local alt
            alt="$(_pick_free_port $((port + 1)))" || {
                log_err "  no free port found near $port — cannot remap"
                _suggest_port_fix "$svc" "$port" "$holder"
                summary_row FAIL "compose-${svc}" "no free alt port near $port"
                return 0
            }
            log_warn "  remapping host port: ${port} -> ${alt}  (foreign container preserved)"
            log_warn "  rerun with --evict-conflicts to stop the conflicting container instead"
            _add_port_override "$svc" "$alt" "$port"
            effective_port="$alt"
            # Update .env so DATABASE_URL / REDIS_URL / CELERY_BROKER_URL
            # use the alt port from the host-side caller's perspective.
            if [[ -n "$remap_dotenv_fn" ]] && declare -F "$remap_dotenv_fn" >/dev/null; then
                "$remap_dotenv_fn" "$alt"
                log_info "  updated .env: ${svc} URLs now use port ${alt}"
            fi
        fi
    fi

    if _compose up -d --wait --wait-timeout="$health_budget" "$svc" >/dev/null 2>&1; then
        log_ok "compose ${svc} up + healthy on host port ${effective_port}"
        summary_row OK "compose-${svc}" "up + healthy (host port ${effective_port})"
        eval "$flag_var=1"
        return 0
    fi
    # Older compose plugins don't support --wait. Fall back to detached
    # up + healthcheck poll loop (60s budget, 3s cadence).
    if ! _compose up -d "$svc" 2>&1 | tail -3; then
        log_err "compose up ${svc} failed"
        summary_row FAIL "compose-${svc}" "up failed"
        return 0
    fi
    local elapsed=0 cid status
    log_info "$svc: polling healthcheck (budget ${health_budget}s)"
    while (( elapsed < health_budget )); do
        cid="$(_compose ps -q "$svc" 2>/dev/null | head -1)"
        if [[ -n "$cid" ]]; then
            status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo unknown)"
            if [[ "$status" == "healthy" ]]; then
                log_ok "compose ${svc} healthy after ${elapsed}s on host port ${effective_port} (polled)"
                summary_row OK "compose-${svc}" "up + healthy (polled, host port ${effective_port})"
                eval "$flag_var=1"
                return 0
            fi
        fi
        sleep 3; elapsed=$((elapsed + 3))
    done
    log_warn "compose ${svc} not healthy after ${health_budget}s"
    summary_row WARN "compose-${svc}" "health unconfirmed after ${health_budget}s"
}

# Update KEYCLOAK_URL's port segment when compose remaps keycloak from 8080
# to a free alternate. The validator + setup-realm.sh both probe via
# KEYCLOAK_URL on the host, so the port change must propagate.
_remap_dotenv_keycloak_url() {
    local new_port="$1"
    [[ -f .env ]] || return 0
    sed -i.bak -E "s|^([[:space:]]*KEYCLOAK_URL=https?://[^:]+):[0-9]+|\\1:${new_port}|" .env
    rm -f .env.bak
}

step_compose_up() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "compose up (docker unavailable)"; return 0; }
    log_step "Compose stack — postgres + redis + keycloak"
    # Bring up each service independently — a port conflict on one must
    # NOT prevent the other from coming up. Downstream steps (alembic,
    # validator, dotenv) consult COMPOSE_PG_UP / COMPOSE_REDIS_UP /
    # COMPOSE_KC_UP to decide whether to use that service or SKIP cleanly.
    _compose_up_one postgres COMPOSE_PG_UP    5432  _remap_dotenv_postgres_port
    _compose_up_one redis    COMPOSE_REDIS_UP 6379  _remap_dotenv_redis_port
    if (( DO_KEYCLOAK )); then
        # Keycloak's healthcheck (15s × 10 retries + 60s start_period) plus
        # realm import on first boot can take ~210s — give a 240s budget.
        # When postgres failed to come up, skip — keycloak depends on it.
        if [[ $COMPOSE_PG_UP -ne 1 ]]; then
            log_skip "keycloak — depends on postgres which did not come up"
            summary_row SKIP compose-keycloak "postgres unavailable"
        else
            _compose_up_one keycloak COMPOSE_KC_UP 8080 _remap_dotenv_keycloak_url 240
        fi
    else
        log_skip "keycloak (--no-keycloak)"
        summary_row SKIP compose-keycloak "--no-keycloak"
    fi
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
    # Keycloak only matters when --keycloak is requested (default). When the
    # service didn't come up, comment out the URL so the host-side validator
    # SKIPs cleanly. KEYCLOAK_ADMIN_PASSWORD stays uncommented because compose
    # still requires it (the keycloak container declares it as :?required and
    # docker-compose evaluates that even when the container isn't started).
    if (( DO_KEYCLOAK )) && [[ $COMPOSE_KC_UP -ne 1 ]]; then
        for key in KEYCLOAK_URL KEYCLOAK_REALM KEYCLOAK_CLIENT_ID KEYCLOAK_ADMIN KEYCLOAK_ADMIN_CLIENT_SECRET; do
            _comment_out_env_key "$key"
        done
        log_warn "compose keycloak unavailable — KEYCLOAK_* commented in .env"
        changed=1
    fi
    if (( changed == 0 )); then
        log_ok ".env already aligned with compose state"
        summary_row OK reconcile-env "all compose services up"
    else
        summary_row WARN reconcile-env "commented out keys for unavailable services"
    fi
}

# --------------------------- step: keycloak realm init ------------------------
#
# Synchronise the fxlab-api Keycloak client's secret with the value in .env.
# Without this step, the client secret embedded in the realm-import JSON does
# not match KEYCLOAK_ADMIN_CLIENT_SECRET, the api container fails to obtain
# tokens, and the host-side validator's keycloak probe also fails.
#
# Idempotent: setup-realm.sh updates the existing client secret rather than
# duplicating, so re-running bootstrap is safe.

step_keycloak_realm_init() {
    [[ $DO_DOCKER -eq 1 ]] || { log_skip "keycloak-realm (docker disabled)"; return 0; }
    (( DO_KEYCLOAK ))      || { log_skip "keycloak-realm (--no-keycloak)"; return 0; }
    if [[ $COMPOSE_KC_UP -ne 1 ]]; then
        log_skip "keycloak-realm — compose keycloak did not come up"
        summary_row SKIP keycloak-realm "compose keycloak unavailable"
        return 0
    fi
    if [[ ! -f config/keycloak/setup-realm.sh ]]; then
        log_warn "keycloak-realm — config/keycloak/setup-realm.sh not found"
        summary_row WARN keycloak-realm "setup-realm.sh missing"
        return 0
    fi

    log_step "Keycloak realm setup (fxlab-api client secret + admin user)"

    local kc_url kc_admin kc_admin_pwd kc_api_secret fxlab_admin_email fxlab_admin_pwd
    kc_url="$(_read_env_value KEYCLOAK_URL)"
    kc_admin="$(_read_env_value KEYCLOAK_ADMIN)"
    kc_admin_pwd="$(_read_env_value KEYCLOAK_ADMIN_PASSWORD)"
    kc_api_secret="$(_read_env_value KEYCLOAK_ADMIN_CLIENT_SECRET)"
    fxlab_admin_email="$(_read_env_value FXLAB_ADMIN_EMAIL)"
    fxlab_admin_pwd="$(_read_env_value FXLAB_ADMIN_PASSWORD)"

    if [[ -z "$kc_url" || -z "$kc_admin" || -z "$kc_admin_pwd" || -z "$kc_api_secret" ]]; then
        log_warn "keycloak-realm: KEYCLOAK_URL/ADMIN/ADMIN_PASSWORD/ADMIN_CLIENT_SECRET missing in .env"
        summary_row WARN keycloak-realm "missing env keys"
        return 0
    fi

    # Wait for the master-realm token endpoint to grant an admin-cli token.
    # The container's healthcheck only proves /health/ready is up; the realm
    # import (start-dev --import-realm) can take additional seconds beyond
    # health-ready before admin-cli works. Poll up to 120s.
    local budget=120 elapsed=0
    log_info "polling ${kc_url}/realms/master admin endpoint (budget ${budget}s)..."
    while (( elapsed < budget )); do
        if curl -sf -o /dev/null -X POST \
            "${kc_url}/realms/master/protocol/openid-connect/token" \
            -d "grant_type=password" -d "client_id=admin-cli" \
            -d "username=${kc_admin}" -d "password=${kc_admin_pwd}" 2>/dev/null; then
            break
        fi
        sleep 3; elapsed=$((elapsed + 3))
    done
    if (( elapsed >= budget )); then
        log_err "keycloak admin endpoint did not respond after ${budget}s"
        summary_row FAIL keycloak-realm "admin endpoint timeout"
        return 0
    fi
    log_ok "keycloak admin endpoint reachable after ${elapsed}s"

    # Run setup-realm.sh; it sets the fxlab-api client secret AND provisions
    # the FXLab realm admin user (with the password marked temporary so the
    # operator must change it on first login). Capture stdout to /tmp so we
    # can detect whether the admin user was newly created vs. already
    # present, and print the credentials accordingly.
    local realm_out
    realm_out="$(mktemp)"
    if KEYCLOAK_URL="$kc_url" \
       KEYCLOAK_ADMIN="$kc_admin" \
       KEYCLOAK_ADMIN_PASSWORD="$kc_admin_pwd" \
       KEYCLOAK_API_CLIENT_SECRET="$kc_api_secret" \
       FXLAB_ADMIN_EMAIL="$fxlab_admin_email" \
       FXLAB_ADMIN_PASSWORD="$fxlab_admin_pwd" \
       bash config/keycloak/setup-realm.sh 2>&1 | tee "$realm_out" | sed 's/^/    /'; then
        log_ok "keycloak realm setup complete (fxlab-api client secret synced)"

        # Surface admin-user state so the operator knows what creds to use.
        # setup-realm.sh prints "Admin user created" on first run and
        # "already exists, skipping" on subsequent runs.
        if grep -q "Admin user created" "$realm_out" 2>/dev/null; then
            cat <<EOF

  ${_CLR_BOLD}╭───────────────────────────────────────────────────────────────╮${_CLR_RESET}
  ${_CLR_BOLD}│  FXLab admin user — first-login credentials                   │${_CLR_RESET}
  ${_CLR_BOLD}│                                                               │${_CLR_RESET}
  ${_CLR_BOLD}│    Email:    ${_CLR_RESET}${fxlab_admin_email}
  ${_CLR_BOLD}│    Password: ${_CLR_RESET}${fxlab_admin_pwd}
  ${_CLR_BOLD}│                                                               │${_CLR_RESET}
  ${_CLR_BOLD}│  Password is TEMPORARY — Keycloak forces a change on first    │${_CLR_RESET}
  ${_CLR_BOLD}│  login. Both values live in .env (chmod 600, gitignored).     │${_CLR_RESET}
  ${_CLR_BOLD}╰───────────────────────────────────────────────────────────────╯${_CLR_RESET}

EOF
            summary_row OK keycloak-realm "client secret synced + admin user created"
        elif grep -q "already exists, skipping" "$realm_out" 2>/dev/null; then
            log_info "admin user '${fxlab_admin_email}' already exists in Keycloak (use existing password)"
            summary_row OK keycloak-realm "client secret synced; admin user already exists"
        else
            summary_row OK keycloak-realm "client secret synced"
        fi
        rm -f "$realm_out"
    else
        log_err "keycloak realm setup failed"
        summary_row FAIL keycloak-realm "setup-realm.sh exited non-zero"
        rm -f "$realm_out"
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

    # Fingerprint the migration files. If the set of migrations and the
    # DATABASE_URL haven't changed since the last green run, skip the
    # alembic command — it's idempotent but the network round-trip and
    # subprocess startup add seconds we don't need.
    local fp
    fp="$({ fingerprint_globs 'alembic/versions/*.py'; printf 'db_url=%s\n' "$db_url"; } | _sha256_stdin)"
    if [[ $FORCE_ALEMBIC -eq 0 ]] && stamp_matches alembic "$fp"; then
        log_skip "alembic (migration set + DATABASE_URL match last green run; --force-alembic to override)"
        summary_row OK alembic "skipped — no migration changes"
        return 0
    fi

    local attempt=1 max=3 delay=2
    while (( attempt <= max )); do
        # Stream alembic output live and use PIPESTATUS so the if-test
        # reflects alembic's actual exit code, not tail's.
        DATABASE_URL="$db_url" .venv/bin/alembic upgrade head 2>&1 | tee /tmp/fxlab_alembic.out
        local alembic_rc=${PIPESTATUS[0]}
        if [[ $alembic_rc -eq 0 ]]; then
            log_ok "migrations applied (attempt $attempt)"
            summary_row OK alembic "head (attempt $attempt)"
            stamp_record alembic "$fp"
            return 0
        fi
        log_warn "alembic upgrade failed (attempt $attempt/$max) — retrying in ${delay}s"
        sleep "$delay"
        delay=$((delay * 2))
        attempt=$((attempt + 1))
    done
    log_err "alembic upgrade failed after $max attempts (see /tmp/fxlab_alembic.out)"
    summary_row FAIL alembic "upgrade failed (3 attempts)"
}

# --------------------------- step: validate env ------------------------------

step_validate_env() {
    log_step "Credential validation"
    if [[ ! -f scripts/validate_env.py ]]; then
        log_skip "scripts/validate_env.py not found"
        return 0
    fi
    # Capture the validator's exit code without enabling errexit; this
    # script runs under `set -uo pipefail` only and the previous
    # `set -e 2>/dev/null || true` pattern silently turned errexit ON
    # for every step that followed, which caused bootstrap.sh to exit
    # non-zero from any subsequent failed-but-non-fatal command (and
    # therefore start.sh to report `scripts/bootstrap.sh failed`).
    local rc=0
    .venv/bin/python scripts/validate_env.py || rc=$?
    case $rc in
        0) summary_row OK   validate-env "all checked services reachable" ;;
        2) summary_row WARN validate-env "some checks skipped (env vars unset)" ;;
        *) summary_row FAIL validate-env "rc=$rc" ;;
    esac
}

# --------------------------- step: pytest ------------------------------------

step_backend_tests() {
    [[ $DO_TESTS -eq 1 ]] || { log_skip "backend pytest (--skip-tests)"; return 0; }
    # One-shot migration of the legacy stamp path from commit 15a54cb so
    # operators with a pre-existing green stamp do not pay another full
    # pytest run after pulling this refactor.
    stamp_migrate_legacy "$REPO_ROOT/.git/fxlab-bootstrap-tests.stamp" "tests"
    local fp
    # Use fingerprint_test_inputs (the scoped fingerprint added in
    # f218c2d) so a tooling-only edit to scripts/ or docs/ does NOT
    # invalidate the tests stamp. CRITICAL: this MUST match the
    # fingerprint healthcheck.sh uses to read the stamp — if the
    # writer and reader compute different digests, the stamp can
    # never match and we re-run pytest on every invocation.
    fp="$(fingerprint_test_inputs)"
    if [[ $FORCE_TESTS -eq 0 ]] && stamp_matches tests "$fp"; then
        log_skip "backend pytest (workspace fingerprint matches last green run; --force-tests to override)"
        summary_row OK pytest "skipped — no source changes since last green run"
        return 0
    fi
    log_step "Backend tests (pytest — unit only)"
    # Bootstrap's pytest gate is a smoke check: "do unit tests pass after
    # this dev install?" — NOT a full CI run. Scope to tests/unit/ so that
    # integration / acceptance / load suites (which depend on host clock,
    # disk speed, real services beyond the dev compose stack, perf budgets,
    # etc.) do not block dev-onboarding. CI runs `make test` for the full
    # suite. The npm-build unit test is deselected because it shells out
    # to the frontend build, which step_frontend_build already covers.
    # No `-q`: with quiet mode pytest emits a single line of dots that
    # buffers heavily through `tee`, which is why the operator saw 20
    # minutes of dead-air. Default mode prints one progress line per
    # test file with a percentage — readable and continuous. PYTHONUNBUFFERED
    # forces line-buffered stdout from the python interpreter so the
    # output reaches `tee` (and the terminal) without 4 KiB-block delay.
    # Per-test timeout: bootstrap's pytest gate is a smoke check, not a
    # CI run. Apply a hard 60-second per-test timeout via pytest-timeout
    # (added to requirements-dev.txt 2026-05-02) so a single deadlocked
    # test cannot dead-air the whole gate for hours. If the plugin is
    # not yet installed (operator on a clone with stale deps), the
    # --timeout flag is silently ignored by pytest with a warning.
    local pytest_timeout_args=()
    if .venv/bin/python -c "import pytest_timeout" 2>/dev/null; then
        pytest_timeout_args=(--timeout=60 --timeout-method=thread)
    else
        log_warn "pytest-timeout not installed — bootstrap pytest gate has no per-test deadline"
        log_warn "  install with: .venv/bin/pip install pytest-timeout"
    fi
    local pytest_args=(
        --no-cov
        --color=yes
        --tb=short
        "${pytest_timeout_args[@]}"
        tests/unit/
        --deselect=tests/unit/test_m0_frontend_structure.py::test_ac8_npm_build_succeeds
        # Mismarked as @pytest.mark.unit but actually drives the full
        # backtest CLI end-to-end against two IRs and re-runs it for a
        # determinism assertion — minutes per IR, no timeout, prone to
        # asyncio deadlocks. Belongs in tests/integration/. CI's
        # `make test` continues to exercise it; bootstrap's smoke gate
        # skips it so dev-onboarding is not gated on a flaky 10-minute
        # integration test.
        --deselect=tests/unit/services/cli/test_backtest_all_strategies.py::test_smoke_against_two_irs_produces_deterministic_report
    )
    # Stream pytest's output live to the terminal AND tee it to
    # /tmp/fxlab_pytest.out for post-mortem analysis. Capture the
    # actual pytest exit code via PIPESTATUS — the previous
    # `pytest | tee | tail -3 | grep -qE` chain swallowed the exit
    # code and silenced all live output, so the operator could not
    # tell the difference between "running" and "hung".
    log_info "pytest streaming live; full log at /tmp/fxlab_pytest.out"
    PYTHONUNBUFFERED=1 .venv/bin/python -m pytest "${pytest_args[@]}" 2>&1 | tee /tmp/fxlab_pytest.out
    local pytest_rc=${PIPESTATUS[0]}
    if [[ $pytest_rc -eq 0 ]]; then
        log_ok "$(tail -1 /tmp/fxlab_pytest.out)"
        summary_row OK pytest "$(tail -1 /tmp/fxlab_pytest.out | tr -s ' ')"
        # Record the test-inputs fingerprint so the next bootstrap can
        # skip the gate when nothing has changed. Only on green — a
        # failed run leaves any previous stamp stale, so the next run
        # re-tries.
        stamp_record tests "$fp"
    else
        log_err "pytest reported failures (full log: /tmp/fxlab_pytest.out)"
        # Show the failure summary section so the operator sees what broke
        # without having to open the file.
        grep -E '^FAILED |^=.*failed.*passed' /tmp/fxlab_pytest.out 2>/dev/null | head -20 | sed 's/^/    /'
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
    # Fingerprint the frontend source tree + build config. If unchanged
    # since the last green run AND the dist/ output is still present,
    # skip the rebuild — it costs ~50s every invocation.
    local fp
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
    if [[ $FORCE_FRONTEND_BUILD -eq 0 ]] && stamp_matches frontend-build "$fp"; then
        log_skip "frontend build (sources + config match last green run; --force-frontend-build to override)"
        summary_row OK frontend-build "skipped — frontend sources unchanged"
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
    # Stream live (no `tail -8` swallowing progress) and capture the
    # tool's exit code via PIPESTATUS so the if-test reflects truth
    # rather than tail's exit. tee writes a per-step log so a failure
    # is fully diagnosable after the run.
    log_info "tsc --noEmit streaming; full log at /tmp/fxlab_typecheck.out"
    (cd frontend && PATH="$node_bin:$PATH" npm run typecheck 2>&1) | tee /tmp/fxlab_typecheck.out
    local tsc_rc=${PIPESTATUS[0]}
    if [[ $tsc_rc -eq 0 ]]; then
        log_ok "tsc --noEmit clean"
    else
        log_warn "tsc --noEmit reported errors (continuing)"
        summary_row WARN frontend-build "tsc errors (see /tmp/fxlab_typecheck.out)"
        return 0
    fi
    log_info "vite build streaming; full log at /tmp/fxlab_vite.out"
    (cd frontend && PATH="$node_bin:$PATH" npm run build 2>&1) | tee /tmp/fxlab_vite.out
    local vite_rc=${PIPESTATUS[0]}
    if [[ $vite_rc -eq 0 ]]; then
        log_ok "vite build succeeded"
        summary_row OK frontend-build "tsc + vite build green"
        stamp_record frontend-build "$fp"
    else
        log_err "vite build failed (see /tmp/fxlab_vite.out)"
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
    # Boot uvicorn in background and poll /health. 30s budget covers
    # cold Python imports, SQLAlchemy engine init, real-Postgres connect
    # pool warmup, and the Keycloak-configured lifespan path. Earlier
    # 10s budget was tight when the only DB was SQLite-in-tempfile;
    # with real services in the loop, 30s is the realistic floor. If
    # /health doesn't come up by then, the uvicorn log usually shows
    # exactly why — we now print its tail on the warn path instead of
    # silently deleting it.
    (
        cd "$REPO_ROOT"
        # Load .env so the uvicorn child process sees JWT_SECRET_KEY,
        # DATABASE_URL, etc. The validate-env step parses .env directly,
        # but the smoke must export those vars into the uvicorn process
        # environment because services/api/main.py:_validate_startup_secrets
        # reads from os.environ.
        if [[ -f .env ]]; then
            set -a
            # shellcheck disable=SC1091
            source .env
            set +a
        fi
        nohup .venv/bin/python -m uvicorn services.api.main:app --host 127.0.0.1 --port 18000 \
            >"$log" 2>&1 &
        echo $! >"$pidfile"
    )
    local pid budget=30 elapsed=0 ok=0
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
    if (( ok == 1 )); then
        log_ok "uvicorn /health returned 200 within ${elapsed}s"
        summary_row OK backend-smoke "uvicorn /health 200 in ${elapsed}s"
        rm -f "$pidfile" "$log"
    else
        log_warn "uvicorn /health did not return 200 within ${budget}s"
        log_warn "uvicorn log tail:"
        tail -25 "$log" 2>/dev/null | sed 's/^/    /'
        summary_row WARN backend-smoke "no /health 200 in ${budget}s"
        rm -f "$pidfile" "$log"
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
step_keycloak_realm_init
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
  • Resume session:     ./scripts/start.sh
                        (pulls origin, runs bootstrap; per-step stamps
                         skip work that has not changed)
  • Force a full refresh:  ./scripts/start.sh --force

Production install path is unchanged:
  sudo bash install.sh    (full Docker/systemd/Keycloak/nginx stack)
NEXT
exit 0

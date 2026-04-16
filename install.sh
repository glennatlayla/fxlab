#!/usr/bin/env bash
# ===========================================================================
# FXLab Platform — Git-Based Production Installer
# ===========================================================================
#
# Single-command installer that clones (or updates) FXLab from GitHub and
# deploys the Docker Compose production stack. Supports both fresh installs
# and in-place upgrades — every run pulls the latest code.
#
# FRESH INSTALL (single command — uses your SSH key for private repo):
#   git clone git@github.com:glennatlayla/fxlab.git /opt/fxlab && sudo bash /opt/fxlab/install.sh
#
# If /opt requires root to write:
#   sudo mkdir -p /opt/fxlab && sudo chown $USER /opt/fxlab && git clone git@github.com:glennatlayla/fxlab.git /opt/fxlab && sudo bash /opt/fxlab/install.sh
#
# UPDATE (on an existing installation):
#   sudo bash /opt/fxlab/install.sh
#
# What it does:
#   1. Validates the host environment (OS, Docker, git, disk, memory).
#   2. Clones the repo (fresh) or pulls latest changes (update).
#   3. Preserves .env across updates — never overwrites secrets.
#   4. Builds and starts the Docker Compose production stack.
#   5. Runs database migrations (via API container entrypoint).
#   6. Installs systemd service for boot persistence.
#   7. Runs post-deploy health verification.
#
# Environment variables (optional overrides):
#   FXLAB_HOME         — Installation directory (default: /opt/fxlab)
#   FXLAB_REPO         — Git repo URL (default: git@github.com:glennatlayla/fxlab.git)
#   FXLAB_BRANCH       — Git branch to deploy (default: main)
#   FXLAB_HTTP_PORT    — HTTP port (default: 80)
#   FXLAB_HTTPS_PORT   — HTTPS port (default: 443)
#   SKIP_SYSTEMD       — Set to "1" to skip systemd installation
#   FXLAB_ALLOW_STALE_CODE
#                      — Set to "1" to permit deployment with the current
#                        checkout when `git fetch` fails (offline / air-
#                        gapped deploys). DEFAULT IS UNSET: a fetch
#                        failure is fatal. This exists because a prior
#                        version silently fell back to stale code on
#                        fetch failure and operators deployed outdated
#                        builds without noticing.
#
# Requirements:
#   - Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+, or compatible)
#   - Docker Engine 24+ with Compose v2
#   - Git 2.25+
#   - 4 GB RAM minimum (8 GB recommended)
#   - 10 GB free disk space
#   - Ports 80 and 443 available (configurable)
#   - Root or sudo access
#   - SSH key or HTTPS credentials for GitHub access (private repo)
#
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FXLAB_HOME="${FXLAB_HOME:-/opt/fxlab}"
FXLAB_REPO="${FXLAB_REPO:-git@github.com:glennatlayla/fxlab.git}"
FXLAB_BRANCH="${FXLAB_BRANCH:-main}"
FXLAB_HTTP_PORT="${FXLAB_HTTP_PORT:-80}"
FXLAB_HTTPS_PORT="${FXLAB_HTTPS_PORT:-443}"
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"

# LOG_FILE is overridable so tests (and operators with custom log dirs)
# can redirect install.sh output without editing this file.
LOG_FILE="${LOG_FILE:-/var/log/fxlab/install-$(date +%Y%m%d-%H%M%S).log}"

# FXLAB_LOG_DIR is the directory into which per-service failure logs are
# written when `wait_for_healthy` reports a service as unhealthy. Each
# failing service gets its own `failed-<service>-<ts>.log` file so the
# operator can grep, diff, or attach it to a support ticket without
# re-running the install. Overridable for tests that cannot write to
# system directories. See _report_install_failure() for the full flow.
FXLAB_LOG_DIR="${FXLAB_LOG_DIR:-/var/log/fxlab}"

# INSTALL_ALL_LOGS=1 switches the diagnostic output from the default
# per-service-file mode to a stdout dump of every failing service's full
# log. Useful when the install is being streamed over ssh to a terminal
# that will be archived, or when the operator wants to pipe the output
# into a pager. Settable via env var OR the `--all-logs` CLI arg.
INSTALL_ALL_LOGS="${INSTALL_ALL_LOGS:-0}"

# Minimum requirements
MIN_DOCKER_VERSION="24"
MIN_GIT_VERSION="2"
MIN_RAM_MB=3072
MIN_DISK_GB=10

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"

    case "$level" in
        INFO)   echo -e "${GREEN}[OK]${NC} $msg" ;;
        WARN)   echo -e "${YELLOW}[WARN]${NC} $msg" ;;
        ERROR)  echo -e "${RED}[ERROR]${NC} $msg" ;;
        STEP)   echo -e "\n${BLUE}${BOLD}==>${NC} ${BOLD}$msg${NC}" ;;
        *)      echo "$msg" ;;
    esac
}

fail() {
    log ERROR "$1"
    echo -e "\n${RED}Installation failed.${NC} See log: $LOG_FILE"
    exit 1
}

# ---------------------------------------------------------------------------
# Detect install mode
# ---------------------------------------------------------------------------

detect_mode() {
    # Determine install mode by examining three sources of truth:
    #
    #   1. CLI flags (--fresh / --refresh) — if set, override everything.
    #   2. Docker state — existing FXLab containers or named volumes.
    #   3. .env existence — indicates a prior completed install.
    #
    # The 2026-04-16 minitux reinstall failure exposed a critical gap:
    # the user had deleted /opt/fxlab (so no .env existed, making this
    # "fresh") but old Docker containers were still running and holding
    # port 80. detect_mode classified it as "fresh", check_ports() ran
    # before any teardown, and the install died with "port 80 in use"
    # instead of tearing down the old stack first.
    #
    # Now: when existing Docker artifacts are detected, the user is
    # prompted to choose "fresh" (full teardown) or "refresh" (preserve
    # data, rebuild). Non-interactive invocations must pass --fresh or
    # --refresh explicitly.

    # --- Priority 1: CLI flag overrides ---
    if [[ "$INSTALL_MODE_FLAG" == "fresh" ]]; then
        INSTALL_MODE="fresh"
        log INFO "Install mode forced by --fresh flag."
        return
    fi
    if [[ "$INSTALL_MODE_FLAG" == "refresh" ]]; then
        INSTALL_MODE="update"
        log INFO "Install mode forced by --refresh flag."
        return
    fi

    # --- Priority 2: detect existing Docker artifacts ---
    local has_env=false
    local has_docker=false

    [[ -f "${FXLAB_HOME}/.env" ]] && has_env=true

    # Check for FXLab containers (via compose if the file exists,
    # otherwise via direct docker ps filter) and named volumes.
    if [[ -f "${FXLAB_HOME}/docker-compose.prod.yml" ]] && \
       docker compose -f "${FXLAB_HOME}/docker-compose.prod.yml" ps -q 2>/dev/null | grep -q .; then
        has_docker=true
    fi
    if [[ "$has_docker" == "false" ]]; then
        # Compose file may be gone (deleted /opt/fxlab) — check volumes.
        if docker volume ls --format '{{.Name}}' 2>/dev/null | grep -q '^fxlab-'; then
            has_docker=true
        fi
    fi

    # --- Decision matrix ---
    if [[ "$has_docker" == "true" ]]; then
        # Existing Docker artifacts found — always prompt (or require flag).
        _prompt_install_mode "$has_env"
    elif [[ "$has_env" == "true" ]]; then
        # .env exists but no Docker artifacts — treat as refresh.
        INSTALL_MODE="update"
    else
        # Nothing exists at all — truly fresh install.
        INSTALL_MODE="fresh"
    fi
}

_prompt_install_mode() {
    # Present the user with a choice between fresh install (full
    # teardown) and refresh (code update + restart). Called only when
    # existing FXLab Docker artifacts are detected.
    #
    # Args:
    #   $1 — "true" if .env exists (shown in prompt for context).
    #
    # Non-interactive safety:
    #   If stdin is not a terminal, the script cannot prompt. The user
    #   must pass --fresh or --refresh on the command line. This prevents
    #   install.sh from hanging in a CI pipeline or when invoked via
    #   `echo "y" | sudo bash install.sh`.
    local has_env="$1"

    if [[ ! -t 0 ]]; then
        fail "Existing FXLab Docker artifacts detected, but stdin is not a terminal.
    Cannot prompt interactively. Re-run with --fresh or --refresh:

      sudo bash install.sh --fresh     # Tear down everything, start clean
      sudo bash install.sh --refresh   # Pull latest code, rebuild, restart"
    fi

    echo ""
    echo -e "${BOLD}Existing FXLab installation detected.${NC}"
    if [[ "$has_env" == "true" ]]; then
        echo "  (.env and Docker containers/volumes found)"
    else
        echo "  (Docker containers/volumes found, but .env is missing)"
    fi
    echo ""
    echo "  1) Fresh install — stop all services, remove containers/images/volumes,"
    echo "     and start completely clean. Database data will be DELETED."
    echo ""
    echo "  2) Refresh — pull latest code, rebuild images, and restart services."
    echo "     Preserves database, .env configuration, and service data."
    echo ""

    local choice
    read -rp "  Select [1/2]: " choice

    case "$choice" in
        1)
            INSTALL_MODE="fresh"
            log INFO "User selected: fresh install (full teardown)."
            ;;
        2)
            INSTALL_MODE="update"
            log INFO "User selected: refresh (code update + restart)."
            ;;
        *)
            fail "Invalid selection '$choice'. Run install.sh again and choose 1 or 2, or pass --fresh / --refresh."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

check_root() {
    if [[ $EUID -ne 0 ]]; then
        fail "This script must be run as root (or with sudo)."
    fi
}

check_os() {
    log STEP "Checking operating system..."
    if [[ ! -f /etc/os-release ]]; then
        fail "Cannot detect OS. /etc/os-release not found."
    fi
    source /etc/os-release
    log INFO "Detected OS: $PRETTY_NAME"

    case "$ID" in
        ubuntu|debian|rhel|centos|rocky|almalinux|fedora|amzn)
            log INFO "Supported distribution: $ID"
            ;;
        *)
            log WARN "Untested distribution: $ID — proceeding with caution."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Package manager helpers
# ---------------------------------------------------------------------------

detect_pkg_manager() {
    # Sets PKG_MANAGER and PKG_UPDATE globals
    if command -v apt-get &>/dev/null; then
        PKG_MANAGER="apt-get"
        PKG_UPDATE="apt-get update -qq"
    elif command -v dnf &>/dev/null; then
        PKG_MANAGER="dnf"
        PKG_UPDATE="dnf check-update || true"
    elif command -v yum &>/dev/null; then
        PKG_MANAGER="yum"
        PKG_UPDATE="yum check-update || true"
    else
        PKG_MANAGER=""
        PKG_UPDATE=""
    fi
}

pkg_install() {
    # Install one or more packages using the detected package manager.
    # Usage: pkg_install git curl
    local packages=("$@")
    if [[ -z "$PKG_MANAGER" ]]; then
        fail "No supported package manager found (apt-get, dnf, yum). Install manually: ${packages[*]}"
    fi
    log INFO "Installing: ${packages[*]} via ${PKG_MANAGER}..."
    if [[ "$PKG_MANAGER" == "apt-get" ]]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}" 2>>"$LOG_FILE" \
            || fail "Failed to install ${packages[*]} via apt-get."
    else
        $PKG_MANAGER install -y "${packages[@]}" 2>>"$LOG_FILE" \
            || fail "Failed to install ${packages[*]} via ${PKG_MANAGER}."
    fi
}

install_docker() {
    # Install Docker Engine + Compose v2 using the official convenience script.
    log INFO "Installing Docker Engine..."

    if ! command -v curl &>/dev/null; then
        pkg_install curl
    fi

    # Docker's official install script — widely tested on Ubuntu, Debian, RHEL, Fedora, etc.
    if ! curl -fsSL https://get.docker.com 2>>"$LOG_FILE" | bash 2>>"$LOG_FILE"; then
        fail "Docker installation failed. Install manually: https://docs.docker.com/engine/install/"
    fi

    # Enable and start the Docker daemon
    if command -v systemctl &>/dev/null; then
        systemctl enable docker 2>>"$LOG_FILE" || true
        systemctl start docker 2>>"$LOG_FILE" || true
    fi

    # Verify
    if ! command -v docker &>/dev/null; then
        fail "Docker binary not found after installation. Check the log: $LOG_FILE"
    fi
    log INFO "Docker installed successfully."
}

# ---------------------------------------------------------------------------
# Pre-flight checks (with auto-install)
# ---------------------------------------------------------------------------

check_git() {
    log STEP "Checking Git installation..."

    if ! command -v git &>/dev/null; then
        log WARN "Git is not installed — installing..."
        pkg_install git
    fi

    local git_version
    git_version="$(git --version | awk '{print $3}')"
    local git_major
    git_major="$(echo "$git_version" | cut -d. -f1)"

    if [[ "$git_major" -lt "$MIN_GIT_VERSION" ]]; then
        fail "Git $git_version is too old. Minimum required: ${MIN_GIT_VERSION}.x"
    fi
    log INFO "Git version: $git_version"
}

check_docker() {
    log STEP "Checking Docker installation..."

    if ! command -v docker &>/dev/null; then
        log WARN "Docker is not installed — installing..."
        install_docker
    fi

    local docker_version
    docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0")"
    local docker_major
    docker_major="$(echo "$docker_version" | cut -d. -f1)"

    if [[ "$docker_major" -lt "$MIN_DOCKER_VERSION" ]]; then
        log WARN "Docker $docker_version is below minimum (${MIN_DOCKER_VERSION}). Attempting upgrade..."
        install_docker
        docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0")"
        docker_major="$(echo "$docker_version" | cut -d. -f1)"
        if [[ "$docker_major" -lt "$MIN_DOCKER_VERSION" ]]; then
            fail "Docker $docker_version is still below minimum after upgrade. Install manually: https://docs.docker.com/engine/install/"
        fi
    fi
    log INFO "Docker version: $docker_version"

    if ! docker info &>/dev/null; then
        log WARN "Docker daemon is not running — starting..."
        if command -v systemctl &>/dev/null; then
            systemctl start docker 2>>"$LOG_FILE" || fail "Failed to start Docker daemon."
        else
            fail "Docker daemon is not running and systemctl not available. Start Docker manually."
        fi
    fi
    log INFO "Docker daemon is running."

    if ! docker compose version &>/dev/null; then
        # Docker Compose v2 ships with Docker Engine via get.docker.com.
        # If missing, try installing the plugin package.
        log WARN "Docker Compose v2 not found — installing plugin..."
        pkg_install docker-compose-plugin 2>/dev/null || true
        if ! docker compose version &>/dev/null; then
            fail "Docker Compose v2 not found after install. Install manually: https://docs.docker.com/compose/install/"
        fi
    fi
    local compose_version
    compose_version="$(docker compose version --short 2>/dev/null || echo "unknown")"
    log INFO "Docker Compose version: $compose_version"
}

check_resources() {
    log STEP "Checking system resources..."

    # RAM
    local total_ram_kb
    total_ram_kb="$(grep MemTotal /proc/meminfo | awk '{print $2}')"
    local total_ram_mb=$((total_ram_kb / 1024))

    if [[ "$total_ram_mb" -lt "$MIN_RAM_MB" ]]; then
        fail "Insufficient RAM: ${total_ram_mb} MB. Minimum required: ${MIN_RAM_MB} MB."
    fi
    log INFO "RAM: ${total_ram_mb} MB (minimum: ${MIN_RAM_MB} MB)"

    # Disk space on the partition where FXLAB_HOME will live
    local target_dir="${FXLAB_HOME%/*}"
    [[ -d "$target_dir" ]] || target_dir="/"
    local free_disk_gb
    free_disk_gb="$(df -BG "$target_dir" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')"

    if [[ "$free_disk_gb" -lt "$MIN_DISK_GB" ]]; then
        fail "Insufficient disk space: ${free_disk_gb} GB. Minimum required: ${MIN_DISK_GB} GB."
    fi
    log INFO "Free disk: ${free_disk_gb} GB (minimum: ${MIN_DISK_GB} GB)"
}

check_ports() {
    log STEP "Checking port availability..."

    # On updates, our own containers may be holding the ports — that's fine
    if [[ "$INSTALL_MODE" == "update" ]]; then
        log INFO "Update mode — skipping port check (existing services may hold ports)."
        return 0
    fi

    local ports=("$FXLAB_HTTP_PORT" "$FXLAB_HTTPS_PORT")
    local port_names=("HTTP" "HTTPS")

    for i in "${!ports[@]}"; do
        local port="${ports[$i]}"
        local name="${port_names[$i]}"

        if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
           netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
            local pid_info
            pid_info="$(ss -tlnp 2>/dev/null | grep ":${port} " | awk '{print $NF}' || echo "unknown")"
            fail "Port ${port} ($name) is already in use by: $pid_info. Free the port or set FXLAB_${name}_PORT to a different value."
        fi
        log INFO "Port ${port} ($name) is available."
    done
}

check_github_access() {
    log STEP "Verifying GitHub access..."

    # Determine if SSH or HTTPS repo URL
    if [[ "$FXLAB_REPO" == git@* ]]; then
        # SSH — verify ssh connectivity to github.com.
        #
        # When invoked via sudo, delegate the SSH probe to the operator
        # so their ~/.ssh keys are loaded. Running as root would fail
        # even when the operator has valid keys, because /root/.ssh is
        # empty — exactly the failure mode the 2026-04-16 remediation
        # was introduced to fix.
        local ssh_out
        ssh_out="$(_as_operator ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -T git@github.com 2>&1 || true)"
        if ! echo "$ssh_out" | grep -qi "successfully authenticated"; then
            local who_hint=""
            if [[ -n "${SUDO_USER:-}" ]] && [[ "$SUDO_USER" != "root" ]]; then
                who_hint="install.sh ran the SSH probe as ${SUDO_USER} (the operator who invoked sudo). "
            fi
            fail "SSH authentication to GitHub failed.
${who_hint}Ensure the SSH key is configured for the operator account:
  ssh-keygen -t ed25519
  ssh-add ~/.ssh/id_ed25519
  Add the public key to https://github.com/settings/keys

Or switch to HTTPS:
  FXLAB_REPO=https://github.com/glennatlayla/fxlab.git sudo -E bash install.sh"
        fi
        log INFO "GitHub SSH authentication verified."
    else
        # HTTPS — verify the repo is reachable (may prompt for credentials)
        if ! git ls-remote "$FXLAB_REPO" HEAD &>/dev/null; then
            fail "Cannot reach ${FXLAB_REPO}. Check your credentials or network."
        fi
        log INFO "GitHub HTTPS access verified."
    fi
}

# ---------------------------------------------------------------------------
# Privilege delegation helpers (2026-04-16 v2 remediation — SSH/sudo fix)
# ---------------------------------------------------------------------------
#
# Why these exist:
#
#   fxlab-reinstall.sh clones the repository as the operator (who owns
#   the GitHub SSH keys), then invokes `sudo bash install.sh`. Under
#   sudo, the effective user is root — which has no SSH key in
#   /root/.ssh. Every subsequent `git fetch` against an SSH remote
#   failed with "Permission denied (publickey)" and aborted the
#   install at pull_latest().
#
#   The prior installer worked around this by asking operators to
#   copy their SSH keys to /root/.ssh manually. That is not
#   production-grade: it leaks private keys to root and leaves a
#   manual prerequisite that people forget.
#
#   The correct fix is to drop privileges to the invoking user for
#   commands that depend on the user's SSH / git configuration.
#
# What these helpers do:
#
#   _operator_home
#       Resolve $SUDO_USER's home directory (needed so SSH finds keys
#       in ~/.ssh). Returns empty string when SUDO_USER is unset or
#       the home directory cannot be resolved.
#
#   _as_operator <cmd> [args...]
#       Run an arbitrary command as $SUDO_USER with HOME set to their
#       home directory. Falls back to direct execution when not
#       invoked via sudo, when $SUDO_USER is "root", or when the
#       operator home cannot be resolved.
#
#   _ensure_operator_owned
#       Idempotently chown $FXLAB_HOME to $SUDO_USER:$SUDO_USER's
#       primary group. Needed because earlier runs of install.sh
#       may have created root-owned .git objects; if we now run git
#       as the operator, those would fail to write. Fast-path: skip
#       the chown when the probe file already has the correct uid.
#
# Testability:
#
#   All three helpers respect $SUDO_USER as the delegation signal.
#   Tests simulate sudo mode by exporting SUDO_USER and shadowing
#   the `sudo` command with a shell function — which `command -v`
#   also finds, so the helpers behave as if real sudo were present.
# ---------------------------------------------------------------------------

_operator_home() {
    if [[ -z "${SUDO_USER:-}" ]]; then
        return 0
    fi
    local home=""
    if command -v getent >/dev/null 2>&1; then
        home="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6 || true)"
    fi
    if [[ -z "$home" ]] && [[ -r /etc/passwd ]]; then
        home="$(awk -F: -v u="$SUDO_USER" '$1==u{print $6}' /etc/passwd 2>/dev/null || true)"
    fi
    if [[ -n "$home" ]] && [[ -d "$home" ]]; then
        printf '%s' "$home"
    fi
}

_as_operator() {
    # Delegate to $SUDO_USER when the installer is invoked via sudo,
    # preserving HOME so SSH (and other tools that probe $HOME) find
    # the operator's configuration. Fall through to direct execution
    # in every other case.
    if [[ -n "${SUDO_USER:-}" ]] \
       && [[ "$SUDO_USER" != "root" ]] \
       && command -v sudo >/dev/null 2>&1; then
        local user_home
        user_home="$(_operator_home)"
        if [[ -n "$user_home" ]]; then
            sudo -u "$SUDO_USER" -H env HOME="$user_home" "$@"
            return $?
        fi
    fi
    "$@"
}

_ensure_operator_owned() {
    # Sync $FXLAB_HOME ownership to $SUDO_USER so the delegated git
    # operations can read and write every file in the working tree.
    # No-op when not running under sudo, when the tree does not yet
    # exist, or when ownership is already correct.
    if [[ -z "${SUDO_USER:-}" ]] || [[ "$SUDO_USER" == "root" ]]; then
        return 0
    fi
    if [[ ! -d "$FXLAB_HOME" ]]; then
        return 0
    fi

    local operator_uid
    operator_uid="$(id -u "$SUDO_USER" 2>/dev/null || echo "")"
    if [[ -z "$operator_uid" ]]; then
        return 0
    fi

    # Fast-path probe: .git if present, else FXLAB_HOME itself.
    local probe="$FXLAB_HOME"
    if [[ -d "$FXLAB_HOME/.git" ]]; then
        probe="$FXLAB_HOME/.git"
    fi
    local current_uid
    current_uid="$(stat -c '%u' "$probe" 2>/dev/null || echo "")"
    if [[ "$current_uid" == "$operator_uid" ]]; then
        return 0
    fi

    local operator_group
    operator_group="$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")"
    log INFO "Syncing ${FXLAB_HOME} ownership to ${SUDO_USER}:${operator_group} (prior root-run artefacts detected)."
    if ! chown -R "$SUDO_USER:$operator_group" "$FXLAB_HOME" 2>>"$LOG_FILE"; then
        log WARN "Could not chown ${FXLAB_HOME} to ${SUDO_USER}. SSH-based git operations may fail."
    fi
}

# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

clone_repo() {
    log STEP "Cloning FXLab repository..."

    mkdir -p "$(dirname "$FXLAB_HOME")"

    # When invoked via sudo, clone as the operator so (a) their SSH
    # keys authenticate with GitHub and (b) the resulting tree is
    # operator-owned, keeping subsequent user-initiated git commands
    # working. `sudo -u` requires the parent directory to be writable
    # by the operator; when it is not (e.g. /opt owned by root), we
    # pre-create FXLAB_HOME with the right ownership first.
    if [[ -n "${SUDO_USER:-}" ]] && [[ "$SUDO_USER" != "root" ]]; then
        local operator_group
        operator_group="$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")"
        mkdir -p "$FXLAB_HOME"
        chown "$SUDO_USER:$operator_group" "$FXLAB_HOME" 2>>"$LOG_FILE" || true
        # Clone into the now-operator-owned directory. git clone into
        # an existing empty dir is supported.
        if ! _as_operator git clone --branch "$FXLAB_BRANCH" --depth 1 "$FXLAB_REPO" "$FXLAB_HOME" 2>>"$LOG_FILE"; then
            fail "git clone failed. Check access permissions and network connectivity. Log: $LOG_FILE"
        fi
    else
        if ! git clone --branch "$FXLAB_BRANCH" --depth 1 "$FXLAB_REPO" "$FXLAB_HOME" 2>>"$LOG_FILE"; then
            fail "git clone failed. Check access permissions and network connectivity. Log: $LOG_FILE"
        fi
    fi

    log INFO "Cloned ${FXLAB_REPO} (branch: ${FXLAB_BRANCH}) to ${FXLAB_HOME}"
}

pull_latest() {
    # Fetch the latest commit for $FXLAB_BRANCH from origin and hard-reset
    # the working tree to it. Every step is verified:
    #
    #   1. A `git fetch` failure is FATAL unless FXLAB_ALLOW_STALE_CODE=1
    #      is explicitly set by the operator. A prior version silently
    #      warned and continued, which shipped stale code without the
    #      operator noticing — that regression must not recur.
    #   2. After fetch, origin/$FXLAB_BRANCH must resolve — if upstream
    #      was deleted we fail loudly instead of resetting to nothing.
    #   3. After reset, HEAD must equal the remote SHA — if the reset
    #      did not land we refuse to proceed.
    #
    # Local changes (operator edits to docker-compose, .env, etc.) are
    # stashed before the reset and restored afterwards. A failing stash
    # is fatal: quietly discarding operator changes is worse than a
    # visible halt.
    #
    # Privilege model (2026-04-16 v2 remediation — SSH/sudo fix):
    #   - When run via sudo, ownership of ${FXLAB_HOME} is synchronised
    #     to $SUDO_USER by _ensure_operator_owned() at function entry.
    #   - Every git invocation uses _as_operator, which delegates to
    #     $SUDO_USER when present so GitHub SSH keys (in the operator's
    #     ~/.ssh, not /root/.ssh) are used to authenticate.
    #   - When run as a plain user (no sudo), _as_operator passes
    #     through and git runs as the current user. Same end result.
    log STEP "Pulling latest changes..."

    # Repair ownership drift before touching git. Safe no-op when the
    # tree is already operator-owned or when we're not running as sudo.
    _ensure_operator_owned

    cd "$FXLAB_HOME"

    local current_sha
    current_sha="$(_as_operator git -C "$FXLAB_HOME" rev-parse HEAD 2>/dev/null || echo "")"
    if [[ -z "$current_sha" ]]; then
        fail "Cannot read current git HEAD in ${FXLAB_HOME}. Repository appears corrupt."
    fi
    local current_short="${current_sha:0:12}"

    # Stash any local changes (e.g. operator tweaks to docker-compose).
    # A failing stash is fatal so we never silently drop operator edits.
    local stash_needed=0
    if ! _as_operator git -C "$FXLAB_HOME" diff --quiet 2>/dev/null \
       || ! _as_operator git -C "$FXLAB_HOME" diff --cached --quiet 2>/dev/null; then
        log INFO "Stashing local changes..."
        if ! _as_operator git -C "$FXLAB_HOME" stash push -m "fxlab-install-$(date +%Y%m%d-%H%M%S)" 2>>"$LOG_FILE"; then
            fail "git stash failed. Refusing to proceed with a dirty tree."
        fi
        stash_needed=1
    fi

    # Fetch from origin. Delegated to $SUDO_USER so their SSH keys
    # authenticate with GitHub — running as root (which has no keys)
    # is the exact failure mode this remediation addresses.
    # Full fetch (no --depth 1) so the post-reset changelog log works
    # when the installer runs repeatedly on the same checkout.
    if ! _as_operator git -C "$FXLAB_HOME" fetch origin "$FXLAB_BRANCH" 2>>"$LOG_FILE"; then
        if [[ "${FXLAB_ALLOW_STALE_CODE:-0}" == "1" ]]; then
            log WARN "git fetch failed; FXLAB_ALLOW_STALE_CODE=1 — proceeding with current checkout ${current_short}."
            log WARN "You are deploying code that MAY BE OUT OF DATE. This is intended for offline/air-gapped deploys only."
            if [[ "$stash_needed" -eq 1 ]]; then
                if _as_operator git -C "$FXLAB_HOME" stash pop 2>>"$LOG_FILE"; then
                    log INFO "Re-applied local changes from stash."
                else
                    log WARN "Could not re-apply stashed changes. They are saved in: git stash list"
                fi
            fi
            return 0
        fi

        local remote_url
        remote_url="$(_as_operator git -C "$FXLAB_HOME" config --get remote.origin.url 2>/dev/null || echo unknown)"
        local sudo_hint=""
        if [[ -n "${SUDO_USER:-}" ]] && [[ "$SUDO_USER" != "root" ]]; then
            sudo_hint="Running under sudo as $(id -un) (invoked by ${SUDO_USER}). "
            sudo_hint+="install.sh delegates git to ${SUDO_USER}; verify their SSH key is configured:"$'\n'
            sudo_hint+="       sudo -u ${SUDO_USER} -H ssh -T git@github.com"
        fi
        fail "git fetch origin ${FXLAB_BRANCH} FAILED.

This is fatal. A prior version of this installer silently fell back to
the existing checkout on fetch failure, which caused operators to deploy
stale code without noticing. That silent fallback has been removed.

Current HEAD : ${current_short}
Branch       : ${FXLAB_BRANCH}
Remote       : ${remote_url}
Log          : ${LOG_FILE}

${sudo_hint}

To resolve:
  1. Ensure the operator can authenticate to GitHub via SSH:
       ssh -T git@github.com        # as the operator, not root
     If the key is missing, generate and register it:
       ssh-keygen -t ed25519
       cat ~/.ssh/id_ed25519.pub     # paste into https://github.com/settings/keys
  2. Or switch to HTTPS for the repo URL:
       FXLAB_REPO=https://github.com/glennatlayla/fxlab.git sudo -E bash install.sh
  3. Or, to INTENTIONALLY deploy the current (possibly stale) checkout
     (offline or air-gapped deploys only):
       FXLAB_ALLOW_STALE_CODE=1 sudo -E bash install.sh"
    fi

    # Verify origin/BRANCH exists after the fetch — catches the case
    # where upstream deleted or renamed the branch.
    local remote_sha
    remote_sha="$(_as_operator git -C "$FXLAB_HOME" rev-parse "origin/${FXLAB_BRANCH}" 2>/dev/null || echo "")"
    if [[ -z "$remote_sha" ]]; then
        fail "git fetch succeeded but origin/${FXLAB_BRANCH} does not exist. Was the branch deleted upstream?"
    fi
    local remote_short="${remote_sha:0:12}"

    if ! _as_operator git -C "$FXLAB_HOME" reset --hard "origin/${FXLAB_BRANCH}" 2>>"$LOG_FILE"; then
        fail "git reset --hard origin/${FXLAB_BRANCH} failed. The repository may be in a broken state."
    fi

    # Defence-in-depth: confirm the reset actually landed on the
    # fetched SHA. If this ever fails we want a visible halt rather
    # than a silent divergence.
    local new_sha
    new_sha="$(_as_operator git -C "$FXLAB_HOME" rev-parse HEAD 2>/dev/null || echo "")"
    if [[ "$new_sha" != "$remote_sha" ]]; then
        fail "Post-reset verification failed: HEAD=${new_sha:0:12} but origin/${FXLAB_BRANCH}=${remote_short}."
    fi

    if [[ "$current_sha" == "$remote_sha" ]]; then
        log INFO "Already at latest commit on origin/${FXLAB_BRANCH}: ${remote_short}"
    else
        log INFO "Updated: ${current_short} → ${remote_short}"
        # Record the changelog between old and new HEAD in the install log.
        _as_operator git -C "$FXLAB_HOME" log --oneline "${current_sha}..${remote_sha}" 2>/dev/null | head -20 >> "$LOG_FILE" || true
    fi

    # Re-apply stashed changes if any
    if [[ "$stash_needed" -eq 1 ]]; then
        if _as_operator git -C "$FXLAB_HOME" stash pop 2>>"$LOG_FILE"; then
            log INFO "Re-applied local changes from stash."
        else
            log WARN "Could not re-apply stashed changes. They are saved in: git stash list"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Environment & secrets
# ---------------------------------------------------------------------------

_is_private_ip() {
    # Classify an IPv4 address as private (RFC 1918) or not.
    #
    # Returns 0 (true) if the address falls within:
    #   10.0.0.0/8        — Class A private
    #   172.16.0.0/12     — Class B private (172.16.0.0 – 172.31.255.255)
    #   192.168.0.0/16    — Class C private
    #   127.0.0.0/8       — Loopback
    #   169.254.0.0/16    — Link-local (RFC 3927)
    #
    # Returns 1 (false) for any other address, including "localhost" or
    # non-IP strings (which default to private=false so the caller falls
    # through to the production path — fail-safe behaviour).
    #
    # Used by setup_env() to auto-detect LAN-only installs and set
    # ENVIRONMENT=development. See v2 remediation Phase 3.
    local ip="${1:-}"
    if [[ "$ip" =~ ^10\. ]]; then
        return 0
    elif [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]]; then
        return 0
    elif [[ "$ip" =~ ^192\.168\. ]]; then
        return 0
    elif [[ "$ip" =~ ^127\. ]]; then
        return 0
    elif [[ "$ip" =~ ^169\.254\. ]]; then
        return 0
    fi
    return 1
}

setup_env() {
    log STEP "Configuring environment..."

    local env_file="${FXLAB_HOME}/.env"

    if [[ -f "$env_file" ]]; then
        log INFO "Existing .env found — preserving current configuration."
    else
        log INFO "Creating .env from production template..."
        if [[ -f "${FXLAB_HOME}/.env.production.template" ]]; then
            cp "${FXLAB_HOME}/.env.production.template" "$env_file"
        else
            fail ".env.production.template not found in ${FXLAB_HOME}. Repository may be incomplete."
        fi
    fi

    # Source current env to check values (tolerant of unset vars)
    set +u
    source "$env_file" 2>/dev/null || true
    set -u

    # -----------------------------------------------------------------------
    # Environment designation — LAN vs public IP detection (v2 remediation).
    # -----------------------------------------------------------------------
    # The project's environment policy designates LAN hosts (minitux) as
    # "development" and public-IP hosts (Azure cluster) as "production".
    # If the operator has NOT explicitly set ENVIRONMENT before running the
    # installer, auto-detect based on the server's primary IP address:
    #
    #   - RFC 1918 private (10/8, 172.16/12, 192.168/16) → development
    #   - Any other routable IP → leave .env.production.template default
    #
    # An explicit ENVIRONMENT= in the operator's shell environment takes
    # precedence — the detection only fires when the env var is unset or
    # still at the template default "production" without the operator
    # having explicitly chosen it.
    #
    # Why this matters: the C2 CORS validator rejects plaintext HTTP
    # origins on private IPs in production. install.sh auto-detects CORS
    # origins as http://<LAN_IP> — the combination is a guaranteed crash
    # at startup. Setting ENVIRONMENT=development on LAN hosts sidesteps
    # the policy (C2 skips validation in non-production) without weakening
    # the production security posture.
    #
    # See: docs/remediation/2026-04-15-remediation-plan-v2.md, Phase 3.
    # Tests: tests/shell/test_install_env_detection.sh
    # -----------------------------------------------------------------------
    local server_ip
    server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || server_ip="localhost"

    # Resolved environment for this install run. Computed from the override
    # or IP classification below, then used to derive POSTGRES_SSLMODE.
    local resolved_env=""

    # Only auto-detect if the operator did NOT set ENVIRONMENT explicitly
    # in the shell environment before invoking the installer.
    if [[ -z "${FXLAB_ENVIRONMENT_OVERRIDE:-}" ]]; then
        if _is_private_ip "$server_ip"; then
            if grep -q "^ENVIRONMENT=production" "$env_file"; then
                sed -i "s|^ENVIRONMENT=production|ENVIRONMENT=development|" "$env_file"
                log INFO "Detected private/LAN IP (${server_ip}) — set ENVIRONMENT=development."
                log INFO "Override: FXLAB_ENVIRONMENT_OVERRIDE=production sudo -E bash install.sh"
            fi
            resolved_env="development"
        else
            log INFO "Detected public IP (${server_ip}) — ENVIRONMENT=production."
            resolved_env="production"
        fi
    else
        local override_env="${FXLAB_ENVIRONMENT_OVERRIDE}"
        if grep -q "^ENVIRONMENT=" "$env_file"; then
            sed -i "s|^ENVIRONMENT=.*|ENVIRONMENT=${override_env}|" "$env_file"
        else
            echo "ENVIRONMENT=${override_env}" >> "$env_file"
        fi
        log INFO "FXLAB_ENVIRONMENT_OVERRIDE=${override_env} — set ENVIRONMENT=${override_env}."
        resolved_env="$override_env"
    fi

    # -----------------------------------------------------------------------
    # POSTGRES_SSLMODE — coupled to ENVIRONMENT (v2 remediation 2026-04-16).
    # -----------------------------------------------------------------------
    # docker-compose.prod.yml resolves the api service's DATABASE_URL
    # sslmode from ${POSTGRES_SSLMODE:-require}. The default 'require' is
    # the fail-safe strict posture — if .env is missing this variable the
    # container refuses to boot without SSL. setup_env writes an explicit
    # value into .env so the pairing with ENVIRONMENT is deterministic:
    #
    #   ENVIRONMENT=production    → POSTGRES_SSLMODE=require
    #     (strict SSL required by _enforce_postgres_sslmode production gate)
    #
    #   ENVIRONMENT=<anything-else> → POSTGRES_SSLMODE=disable
    #     (postgres:15-alpine ships no SSL certs; 'disable' is explicit
    #     plaintext intent — 'prefer' would attempt an SSL handshake,
    #     silently fall back to plaintext, and trigger the production
    #     gate's rejection if the image were ever promoted to prod.)
    #
    # This guarantees that (a) the container's DATABASE_URL has a sslmode
    # that _enforce_postgres_sslmode accepts for the resolved environment,
    # and (b) a mismatched promotion (dev image with dev sslmode into a
    # prod cluster) fails loudly at startup instead of silently
    # transmitting credentials in plaintext.
    #
    # Sentinel rationale for FXLAB_ENVIRONMENT_OVERRIDE=production on a
    # LAN host: the operator explicitly requested production. We must
    # honour that and write require — if the postgres container in the
    # compose stack has no SSL, the api container will fail at startup
    # with a clear connection error rather than a silent plaintext DSN.
    # -----------------------------------------------------------------------
    local resolved_sslmode
    if [[ "$resolved_env" == "production" ]]; then
        resolved_sslmode="require"
    else
        resolved_sslmode="disable"
    fi
    if grep -q "^POSTGRES_SSLMODE=" "$env_file"; then
        sed -i "s|^POSTGRES_SSLMODE=.*|POSTGRES_SSLMODE=${resolved_sslmode}|" "$env_file"
    else
        echo "POSTGRES_SSLMODE=${resolved_sslmode}" >> "$env_file"
    fi
    log INFO "Set POSTGRES_SSLMODE=${resolved_sslmode} (paired with ENVIRONMENT=${resolved_env})."

    # Re-source after environment adjustment so downstream setup_env logic
    # (CORS detection, secret generation) sees the updated value.
    set +u
    source "$env_file" 2>/dev/null || true
    set -u

    # Generate secrets if missing or still at placeholder values
    local changed=0

    if [[ -z "${JWT_SECRET_KEY:-}" || "${JWT_SECRET_KEY:-}" == "CHANGE_ME" ]]; then
        local jwt_key
        jwt_key="$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -base64 48)"
        if grep -q "^JWT_SECRET_KEY=" "$env_file"; then
            sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${jwt_key}|" "$env_file"
        else
            echo "JWT_SECRET_KEY=${jwt_key}" >> "$env_file"
        fi
        log INFO "Generated JWT_SECRET_KEY (48-byte random)."
        changed=1
    fi

    if [[ -z "${POSTGRES_PASSWORD:-}" || "${POSTGRES_PASSWORD:-}" == "CHANGE_ME" ]]; then
        local pg_pass
        pg_pass="$(python3 -c "import secrets; print(secrets.token_urlsafe(24))" 2>/dev/null || openssl rand -base64 24)"
        if grep -q "^POSTGRES_PASSWORD=" "$env_file"; then
            sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pg_pass}|" "$env_file"
        else
            echo "POSTGRES_PASSWORD=${pg_pass}" >> "$env_file"
        fi
        log INFO "Generated POSTGRES_PASSWORD (24-byte random)."
        changed=1
    fi

    # Auto-detect CORS origins if still at placeholder
    if [[ -z "${CORS_ALLOWED_ORIGINS:-}" || "${CORS_ALLOWED_ORIGINS:-}" == "CHANGE_ME" ]]; then
        # Detect the primary IP address of this server so the frontend can
        # reach the API via CORS.  The edge nginx serves both on the same
        # origin, but CORS headers are still required for XHR from the
        # browser when accessing via IP or hostname.
        local server_ip
        server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || server_ip="localhost"
        local cors_origins="http://${server_ip},http://${server_ip}:${FXLAB_HTTP_PORT},http://localhost"
        if grep -q "^CORS_ALLOWED_ORIGINS=" "$env_file"; then
            sed -i "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=${cors_origins}|" "$env_file"
        else
            echo "CORS_ALLOWED_ORIGINS=${cors_origins}" >> "$env_file"
        fi
        log INFO "Auto-detected CORS origins: ${cors_origins}"
        log INFO "Edit ${env_file} to add HTTPS or custom domain origins."
        changed=1
    fi

    # Set port configuration
    for var_name in FXLAB_HTTP_PORT FXLAB_HTTPS_PORT; do
        local var_val="${!var_name}"
        if grep -q "^${var_name}=" "$env_file"; then
            sed -i "s|^${var_name}=.*|${var_name}=${var_val}|" "$env_file"
        else
            echo "${var_name}=${var_val}" >> "$env_file"
        fi
    done

    # Secure the env file
    chmod 600 "$env_file"
    log INFO "Environment configured. Secrets stored in ${env_file} (mode 600)."

    if [[ "$changed" -eq 1 ]]; then
        log WARN "Auto-generated secrets. Back up ${env_file} — it contains your production keys."
    fi
}

# ---------------------------------------------------------------------------
# Host kernel tuning
# ---------------------------------------------------------------------------

tune_host_kernel() {
    # Tune host kernel parameters required by containerised services.
    # Each setting is checked before writing so we only modify what is needed,
    # and we persist changes across reboots via /etc/sysctl.d/.
    log STEP "Tuning host kernel parameters..."

    local changed=0

    # --- vm.overcommit_memory = 1 ---
    # Redis requires this for reliable background persistence (RDB/AOF).
    # Without it Redis logs: "WARNING Memory overcommit must be enabled!"
    # and background saves may fail under memory pressure.
    local current_overcommit
    current_overcommit="$(sysctl -n vm.overcommit_memory 2>/dev/null)" || current_overcommit=""
    if [[ "$current_overcommit" != "1" ]]; then
        log INFO "Setting vm.overcommit_memory=1 (required by Redis for background saves)."
        sysctl -w vm.overcommit_memory=1 >>"$LOG_FILE" 2>&1

        # Persist across reboots
        local sysctl_conf="/etc/sysctl.d/99-fxlab.conf"
        if [[ -f "$sysctl_conf" ]] && grep -q "vm.overcommit_memory" "$sysctl_conf"; then
            sed -i 's/^vm.overcommit_memory.*/vm.overcommit_memory=1/' "$sysctl_conf"
        else
            echo "# FXLab — Redis requires overcommit for background persistence" >> "$sysctl_conf"
            echo "vm.overcommit_memory=1" >> "$sysctl_conf"
        fi
        changed=1
    else
        log INFO "vm.overcommit_memory already set to 1."
    fi

    # --- net.core.somaxconn ---
    # Redis and Nginx benefit from a higher listen backlog.  The default
    # of 128 (or 4096 on some distros) is usually fine, but if the current
    # value is below 512 we bump it.  This prevents connection drops under
    # burst traffic.
    local current_somaxconn
    current_somaxconn="$(sysctl -n net.core.somaxconn 2>/dev/null)" || current_somaxconn="128"
    if [[ "$current_somaxconn" -lt 512 ]]; then
        log INFO "Raising net.core.somaxconn from ${current_somaxconn} to 512."
        sysctl -w net.core.somaxconn=512 >>"$LOG_FILE" 2>&1

        local sysctl_conf="/etc/sysctl.d/99-fxlab.conf"
        if [[ -f "$sysctl_conf" ]] && grep -q "net.core.somaxconn" "$sysctl_conf"; then
            sed -i 's/^net.core.somaxconn.*/net.core.somaxconn=512/' "$sysctl_conf"
        else
            echo "# FXLab — higher listen backlog for Redis and Nginx" >> "$sysctl_conf"
            echo "net.core.somaxconn=512" >> "$sysctl_conf"
        fi
        changed=1
    else
        log INFO "net.core.somaxconn already ${current_somaxconn} (≥512)."
    fi

    if [[ "$changed" -eq 1 ]]; then
        log INFO "Kernel parameters tuned and persisted to /etc/sysctl.d/99-fxlab.conf."
    else
        log INFO "All kernel parameters already at required values."
    fi
}

# ---------------------------------------------------------------------------
# Teardown existing installation (fresh install only)
# ---------------------------------------------------------------------------
#
# Called BEFORE check_ports() in a fresh install when existing Docker
# artifacts (containers, volumes) are detected. This is the fix for the
# 2026-04-16 minitux reinstall failure: the old docker-proxy was holding
# port 80, check_ports() ran first and killed the script, and the
# stale-state cleanup in build_and_start() never got a chance to run.
#
# Teardown sequence:
#   1. Stop containers + remove volumes via `docker compose down --volumes`
#      if the compose file is available. This is the most reliable path
#      because it targets only the FXLab project's resources.
#   2. If no compose file (user deleted /opt/fxlab before cloning), fall
#      back to direct docker commands: stop/remove containers by label/name,
#      remove named volumes by prefix.
#   3. Remove locally-built FXLab images (--rmi local) so the fresh build
#      starts from a clean layer cache. Third-party base images (postgres,
#      redis, nginx) are kept to avoid unnecessary re-downloads.
#   4. Remove .env if it exists, so setup_env() generates fresh secrets.
#      (A stale .env with the old POSTGRES_PASSWORD against a wiped volume
#      produces the same auth-failure root cause we fixed in build_and_start.)
#
# This function is a safe no-op if no artifacts exist.

teardown_existing() {
    log STEP "Tearing down existing FXLab installation..."

    # --- Compose-managed teardown (preferred path) ---
    if [[ -f "${FXLAB_HOME}/docker-compose.prod.yml" ]]; then
        log INFO "Stopping containers, removing volumes and locally-built images..."
        docker compose -f "${FXLAB_HOME}/docker-compose.prod.yml" down \
            --volumes --remove-orphans --rmi local --timeout 30 \
            2>>"$LOG_FILE" || true
    else
        # --- Fallback: direct docker commands (compose file is gone) ---
        log INFO "No compose file found — using direct docker commands for teardown."

        # Stop and remove containers whose names start with the fxlab project prefix.
        # docker compose names them as <project>-<service>-<index>.
        local fxlab_containers
        fxlab_containers="$(docker ps -aq --filter 'name=fxlab' 2>/dev/null || true)"
        if [[ -n "$fxlab_containers" ]]; then
            log INFO "Removing FXLab containers..."
            echo "$fxlab_containers" | xargs docker rm -f 2>>"$LOG_FILE" || true
        fi

        # Remove named volumes with the fxlab- prefix.
        local fxlab_volumes
        fxlab_volumes="$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep '^fxlab-' || true)"
        if [[ -n "$fxlab_volumes" ]]; then
            log INFO "Removing FXLab volumes..."
            echo "$fxlab_volumes" | xargs docker volume rm -f 2>>"$LOG_FILE" || true
        fi
    fi

    # --- Remove dangling FXLab images not caught by compose down ---
    local fxlab_images
    fxlab_images="$(docker images --filter 'reference=*fxlab*' -q 2>/dev/null || true)"
    if [[ -n "$fxlab_images" ]]; then
        log INFO "Removing FXLab Docker images..."
        echo "$fxlab_images" | xargs docker rmi -f 2>>"$LOG_FILE" || true
    fi

    # --- Remove .env so setup_env() generates fresh secrets ---
    if [[ -f "${FXLAB_HOME}/.env" ]]; then
        log INFO "Removing old .env (fresh secrets will be generated)."
        rm -f "${FXLAB_HOME}/.env"
    fi

    log INFO "Teardown complete — ports and volumes are free."
}

# ---------------------------------------------------------------------------
# Build & deploy
# ---------------------------------------------------------------------------

build_and_start() {
    log STEP "Building and starting FXLab services..."

    cd "$FXLAB_HOME"

    # On update: stop existing services gracefully before rebuild
    if [[ "$INSTALL_MODE" == "update" ]]; then
        log INFO "Stopping existing services..."
        docker compose -f docker-compose.prod.yml down --timeout 30 2>>"$LOG_FILE" || true
    fi

    # ---- Stale Docker state cleanup (fresh install only) ----
    # A fresh install means no .env existed, so there is no operator data to
    # preserve.  But Docker artifacts from a PREVIOUS failed install can
    # survive independently of the application directory:
    #
    #   - Named volumes (postgres-data, redis-data, prometheus-data, etc.)
    #     PostgreSQL only runs initdb on an empty data dir.  If the volume
    #     survives, PG keeps the OLD password while install.sh just generated
    #     a NEW one → auth failure.
    #   - Containers in exited/restarting state from a prior compose project
    #   - Networks that conflict with the new compose stack
    #   - Orphan services from a compose file that changed between installs
    #
    # One command handles ALL of these: `docker compose down --volumes`
    # removes containers, networks, AND named volumes declared in the
    # compose file.  --remove-orphans catches services that existed in a
    # previous compose file version but no longer appear in the current one.
    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        # Check if any fxlab Docker artifacts exist from a previous attempt
        local has_stale_state=false
        if docker compose -f docker-compose.prod.yml ps -q 2>/dev/null | grep -q .; then
            has_stale_state=true
        fi
        for vol in fxlab-postgres-data fxlab-redis-data fxlab-prometheus-data fxlab-alertmanager-data fxlab-nginx-certs; do
            if docker volume inspect "$vol" &>/dev/null; then
                has_stale_state=true
                break
            fi
        done

        if [[ "$has_stale_state" == "true" ]]; then
            log WARN "Stale Docker artifacts detected from a previous install."
            log WARN "Removing all FXLab containers, networks, and volumes..."
            docker compose -f docker-compose.prod.yml down --volumes --remove-orphans --timeout 15 2>>"$LOG_FILE" || true
            log INFO "Stale Docker state cleaned up."
        fi
    fi

    # Build application images
    log INFO "Building application images (this may take 3-5 minutes on first run)..."
    if ! docker compose -f docker-compose.prod.yml build 2>>"$LOG_FILE"; then
        fail "Docker image build failed. Check the log: $LOG_FILE"
    fi
    log INFO "Images built successfully."

    # Start services
    log INFO "Starting services..."
    if ! docker compose -f docker-compose.prod.yml up -d --remove-orphans 2>>"$LOG_FILE"; then
        log ERROR "Service startup failed. Dumping container logs:"
        docker compose -f docker-compose.prod.yml logs --tail 80 2>/dev/null || true
        fail "Failed to start services. Full log: $LOG_FILE"
    fi
    log INFO "Services started."

    # Prune old dangling images from previous builds to save disk
    docker image prune -f 2>>"$LOG_FILE" || true
}

wait_for_healthy() {
    log STEP "Waiting for services to become healthy..."

    # Core services MUST be healthy for the install to succeed.
    # Monitoring services are checked and warned, but do not block the install.
    # Rationale: a broken cadvisor or prometheus should not prevent the trading
    # platform from deploying — these are observability, not the product.
    # Core services: postgres, redis, api, web, nginx (hardcoded in Python below)

    local max_wait=180
    local elapsed=0
    local interval=5

    while [[ "$elapsed" -lt "$max_wait" ]]; do
        # Parse all service statuses into a temp file so we only call compose once
        local status_json
        status_json="$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null)" || status_json=""

        # Count core healthy / core total(running)
        local core_healthy core_total all_healthy all_total
        read -r core_healthy core_total all_healthy all_total < <(echo "$status_json" | \
            python3 -c "
import sys, json
core = {'postgres','redis','api','web','nginx'}
data = [json.loads(l) for l in sys.stdin if l.strip()]
ch = sum(1 for s in data if s.get('Service','') in core and s.get('Health','') == 'healthy')
ct = sum(1 for s in data if s.get('Service','') in core and s.get('State','') == 'running')
ah = sum(1 for s in data if s.get('Health','') == 'healthy')
at = sum(1 for s in data if s.get('State','') == 'running')
print(ch, ct, ah, at)
" 2>/dev/null) || { core_healthy=0; core_total=0; all_healthy=0; all_total=0; }

        # Best case: everything healthy
        if [[ "$all_total" -gt 0 ]] && [[ "$all_healthy" -eq "$all_total" ]]; then
            log INFO "All ${all_healthy}/${all_total} services are healthy."
            return 0
        fi

        # Core services healthy — don't keep waiting for monitoring
        if [[ "$core_total" -ge 5 ]] && [[ "$core_healthy" -eq "$core_total" ]]; then
            local mon_unhealthy=$((all_total - all_healthy))
            if [[ "$mon_unhealthy" -gt 0 ]]; then
                log WARN "Core services healthy (${core_healthy}/${core_total}). ${mon_unhealthy} monitoring service(s) still starting or unhealthy."
                # Give monitoring services a brief grace period (30s) before declaring success
                if [[ "$elapsed" -ge 30 ]]; then
                    log WARN "Proceeding — monitoring services may still be settling."
                    _report_unhealthy_services
                    return 0
                fi
            fi
        fi

        log INFO "Healthy: ${all_healthy}/${all_total} (core: ${core_healthy}/${core_total}) — waiting... (${elapsed}s / ${max_wait}s)"
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    # Timeout — check if at least core services are healthy
    local final_json
    final_json="$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null)" || final_json=""

    local final_core_healthy final_core_total
    read -r final_core_healthy final_core_total < <(echo "$final_json" | \
        python3 -c "
import sys, json
core = {'postgres','redis','api','web','nginx'}
data = [json.loads(l) for l in sys.stdin if l.strip()]
ch = sum(1 for s in data if s.get('Service','') in core and s.get('Health','') == 'healthy')
ct = sum(1 for s in data if s.get('Service','') in core and s.get('State','') == 'running')
print(ch, ct)
" 2>/dev/null) || { final_core_healthy=0; final_core_total=0; }

    if [[ "$final_core_total" -ge 5 ]] && [[ "$final_core_healthy" -eq "$final_core_total" ]]; then
        log WARN "Core services healthy (${final_core_healthy}/${final_core_total}) but monitoring services did not become healthy within ${max_wait}s."
        _report_unhealthy_services
        return 0
    fi

    log ERROR "Core services NOT healthy after ${max_wait}s."
    # D4: emit the structured failure banner FIRST so the failing
    # service names are visible in the first ~20 lines of stderr/stdout
    # without the operator having to scroll. The banner also writes
    # per-service log files under $FXLAB_LOG_DIR and prints their paths.
    _report_install_failure | tee -a "$LOG_FILE"
    fail "Core services did not become healthy within ${max_wait}s. Full log: $LOG_FILE"
}

_report_unhealthy_services() {
    # Legacy helper used by the WARN branch of wait_for_healthy (core is
    # healthy but monitoring services are still settling). For the hard
    # failure path — where the operator needs the root-cause service
    # named prominently — use _report_install_failure() below, which
    # emits the D4 diagnostic banner plus per-service log files.
    docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | \
        python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    svc = json.loads(line)
    if svc.get('Health', '') != 'healthy' or svc.get('State', '') != 'running':
        print(svc.get('Service', svc.get('Name', 'unknown')))
" 2>/dev/null | while read -r svc_name; do
        echo "=== $svc_name ==="
        docker compose -f docker-compose.prod.yml logs --tail 40 "$svc_name" 2>/dev/null || true
        echo ""
    done
}

# ---------------------------------------------------------------------------
# D4 (2026-04-15 remediation) — structured install-failure diagnostics
# ---------------------------------------------------------------------------
#
# During the 2026-04-15 minitux install failure the installer printed the
# interleaved logs of every container, burying api's Redis EINVAL
# crashloop under cadvisor and node-exporter noise. The operator had to
# grep through ~400 lines to find the root cause.
#
# The three functions below fix that by:
#
#   _identify_unhealthy_services — classifies each service so the banner
#       can distinguish "restart budget exhausted" (B3/D1 on-failure:3
#       cap reached) from "still starting" / "unhealthy" / "blocked on
#       deps". The exit code is preserved so the operator can correlate
#       with the D1 exit(3) = ConfigError convention.
#
#   _write_per_service_log — materialises one `failed-<svc>-<ts>.log`
#       file per failing service so operators can attach them to
#       tickets, grep across them, or copy them off the minitux host
#       with a single `scp` command.
#
#   _report_install_failure — orchestrator that emits the banner (failed
#       service names guaranteed within the first 20 lines of output),
#       the `docker compose ps` overview, the per-service log paths,
#       and a short inline tail per failing service. Respects
#       INSTALL_ALL_LOGS=1 to dump full logs to stdout instead.
#
# All three are sourced by tests/shell/test_install_diagnostics.sh —
# the BASH_SOURCE guard at the bottom of this file prevents main() from
# running when the test harness sources install.sh.

_identify_unhealthy_services() {
    # Read `docker compose ps --format json` output on stdin (one JSON
    # object per line). Emit one TSV line per unhealthy service:
    #
    #     <service>\t<classification>\t<exit_code>
    #
    # Classifications (short keys — the banner maps them to human labels):
    #     exhausted   — State=exited, ExitCode != 0. Under B3/D1
    #                   on-failure:3 compose will NOT restart further.
    #     starting    — State=running, Health=starting. Still within
    #                   the healthcheck start_period window.
    #     unhealthy   — State=running, Health=unhealthy. The container
    #                   is alive but its healthcheck is failing.
    #     restarting  — State=restarting. Budget may still have room.
    #     blocked     — State in {created, paused}. Blocked on a
    #                   depends_on upstream, never actually booted.
    #     unknown:<s> — any other state we didn't enumerate.
    #
    # Healthy services (State=running AND Health in {healthy, ""} where
    # the empty Health means "no healthcheck declared → implicitly OK")
    # and exit-zero completions (State=exited, ExitCode=0) are elided
    # from the output so the banner lists ONLY things the operator
    # needs to care about.
    python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        svc = json.loads(line)
    except Exception:
        continue
    name = svc.get('Service') or svc.get('Name') or 'unknown'
    state = svc.get('State', '')
    health = svc.get('Health', '')
    exit_code = svc.get('ExitCode', 0)
    if state == 'exited' and exit_code != 0:
        cls = 'exhausted'
    elif state == 'exited' and exit_code == 0:
        continue  # completed cleanly — not an unhealthy state
    elif state == 'restarting':
        cls = 'restarting'
    elif state == 'running' and health == 'healthy':
        continue
    elif state == 'running' and health == 'starting':
        cls = 'starting'
    elif state == 'running' and health == 'unhealthy':
        cls = 'unhealthy'
    elif state == 'running' and not health:
        continue  # running without healthcheck → implicit OK
    elif state in ('created', 'paused'):
        cls = 'blocked'
    else:
        cls = f'unknown:{state}'
    print(f'{name}\t{cls}\t{exit_code}')
" 2>/dev/null || true
}

_write_per_service_log() {
    # Write the full compose log for one service to a dedicated file
    # under FXLAB_LOG_DIR. Echo the file path so callers can surface it
    # in the banner. Stderr is merged into the file so the operator
    # gets the complete picture (compose sometimes emits warnings via
    # stderr).
    #
    # Arguments:
    #   $1 — service name (e.g. "api")
    #   $2 — timestamp string (already formatted by caller so all the
    #        files from one install attempt share a suffix)
    local svc="$1" ts="$2"
    local dest="${FXLAB_LOG_DIR}/failed-${svc}-${ts}.log"
    mkdir -p "$FXLAB_LOG_DIR"
    docker compose -f docker-compose.prod.yml logs "$svc" >"$dest" 2>&1 || true
    echo "$dest"
}

_human_classification_label() {
    # Map the short classification key (from _identify_unhealthy_services)
    # to a human-readable label for the banner. Keeping this as a
    # separate pure function makes the banner text changeable without
    # touching the classification logic.
    local cls="$1" exit_code="${2:-0}"
    case "$cls" in
        exhausted)   echo "restart budget exhausted (exit code ${exit_code})" ;;
        starting)    echo "still starting (healthcheck has not yet passed)" ;;
        unhealthy)   echo "unhealthy (container running, healthcheck failing)" ;;
        restarting)  echo "restarting (budget may still have room)" ;;
        blocked)     echo "blocked on deps (never started)" ;;
        unknown:*)   echo "unexpected state: ${cls#unknown:}" ;;
        *)           echo "$cls" ;;
    esac
}

_report_install_failure() {
    # Produce the D4 diagnostic banner for a failed install.
    #
    # Output structure (first 20 lines always carry the failed service
    # names so the root cause is visible without scrolling):
    #
    #   <banner separator>
    #     FAILED SERVICES: <name1> (<human-label1>), <name2> ...
    #   <banner separator>
    #
    #   <docker compose ps overview — short table>
    #
    #   --- <svc1> — <human-label1> ---
    #     full log: <path-to-per-service-file>
    #     last 40 lines:
    #       <tail of svc1>
    #   (repeat for each failing svc)
    #
    # If INSTALL_ALL_LOGS=1 (either env var or --all-logs CLI flag),
    # the per-service files are skipped and full logs dump to stdout.
    #
    # Callable on a healthy stack — returns silently without a banner
    # (tested by test_all_healthy_produces_no_banner).

    local ts
    ts="$(date +%Y%m%d%H%M%S)"

    local ps_json
    ps_json="$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null)" || ps_json=""

    local tsv
    tsv="$(printf '%s\n' "$ps_json" | _identify_unhealthy_services)"

    if [[ -z "$tsv" ]]; then
        # Nothing to report — caller was defensive (e.g. wait_for_healthy
        # timed out but the stack actually came up). No banner.
        return 0
    fi

    # --- Build the banner (single-line service list) ---
    local names_list=""
    local svc class exit_code label
    while IFS=$'\t' read -r svc class exit_code; do
        [[ -z "$svc" ]] && continue
        label="$(_human_classification_label "$class" "$exit_code")"
        if [[ -n "$names_list" ]]; then
            names_list="${names_list}, "
        fi
        names_list="${names_list}${svc} (${label})"
    done <<< "$tsv"

    echo
    echo "=========================================================="
    echo "  FAILED SERVICES: ${names_list}"
    echo "=========================================================="
    echo

    # --- Compose state overview (one line per service) ---
    echo "Compose state:"
    docker compose -f docker-compose.prod.yml ps 2>&1 | sed 's/^/  /' || true
    echo

    # --- Per-service detail ---
    if [[ "${INSTALL_ALL_LOGS}" == "1" ]]; then
        echo "[INSTALL_ALL_LOGS=1] — full logs follow for each failing service."
        echo "  (Per-service log files are NOT written in this mode.)"
        echo
        while IFS=$'\t' read -r svc class exit_code; do
            [[ -z "$svc" ]] && continue
            label="$(_human_classification_label "$class" "$exit_code")"
            echo "--- ${svc} — ${label} ---"
            docker compose -f docker-compose.prod.yml logs "$svc" 2>&1 || true
            echo
        done <<< "$tsv"
        return 0
    fi

    # Default mode: per-service log files + short inline tails.
    while IFS=$'\t' read -r svc class exit_code; do
        [[ -z "$svc" ]] && continue
        label="$(_human_classification_label "$class" "$exit_code")"
        echo "--- ${svc} — ${label} ---"
        local log_path
        log_path="$(_write_per_service_log "$svc" "$ts")"
        echo "  full log: ${log_path}"
        echo "  last 40 lines:"
        docker compose -f docker-compose.prod.yml logs --tail 40 "$svc" 2>&1 \
            | sed 's/^/    /' || true
        echo
    done <<< "$tsv"

    echo "(Re-run with INSTALL_ALL_LOGS=1 bash install.sh — or pass --all-logs —"
    echo "to dump every failing service's full log to stdout in one stream.)"
}

# ---------------------------------------------------------------------------
# systemd
# ---------------------------------------------------------------------------

install_systemd() {
    if [[ "$SKIP_SYSTEMD" == "1" ]]; then
        log INFO "Skipping systemd installation (SKIP_SYSTEMD=1)."
        return 0
    fi

    log STEP "Installing systemd service..."

    if ! command -v systemctl &>/dev/null; then
        log WARN "systemctl not found — skipping. Start manually: cd ${FXLAB_HOME} && docker compose -f docker-compose.prod.yml up -d"
        return 0
    fi

    local service_file="${FXLAB_HOME}/deploy/systemd/fxlab.service"
    if [[ -f "$service_file" ]]; then
        # Patch paths to match actual install location
        sed -i "s|WorkingDirectory=.*|WorkingDirectory=${FXLAB_HOME}|" "$service_file"
        sed -i "s|EnvironmentFile=.*|EnvironmentFile=${FXLAB_HOME}/.env|" "$service_file"
        sed -i "s|file:///opt/fxlab|file://${FXLAB_HOME}|" "$service_file"

        cp "$service_file" /etc/systemd/system/fxlab.service
        systemctl daemon-reload
        systemctl enable fxlab

        log INFO "systemd service installed and enabled."
    else
        log WARN "Service file not found at $service_file — skipping."
    fi

    # Install backup timer if present
    local timer_dir="${FXLAB_HOME}/deploy/systemd"
    if [[ -f "${timer_dir}/fxlab-backup-db.timer" ]] && [[ -f "${timer_dir}/fxlab-backup-db.service" ]]; then
        cp "${timer_dir}/fxlab-backup-db.service" /etc/systemd/system/
        cp "${timer_dir}/fxlab-backup-db.timer" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable --now fxlab-backup-db.timer 2>/dev/null || true
        log INFO "Database backup timer installed (daily 2 AM UTC)."
    fi
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

verify_installation() {
    log STEP "Verifying deployment..."

    cd "$FXLAB_HOME"

    # API health
    local api_healthy=0
    for attempt in 1 2 3; do
        if docker compose -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/health &>/dev/null; then
            api_healthy=1
            break
        fi
        sleep 2
    done
    [[ "$api_healthy" -eq 1 ]] && log INFO "API health check passed." || log WARN "API health check failed — may still be starting."

    # Frontend
    local web_healthy=0
    for attempt in 1 2 3; do
        if docker compose -f docker-compose.prod.yml exec -T web curl -sf http://localhost:3000 &>/dev/null; then
            web_healthy=1
            break
        fi
        sleep 2
    done
    [[ "$web_healthy" -eq 1 ]] && log INFO "Frontend health check passed." || log WARN "Frontend health check failed — may still be starting."

    # Edge proxy (check from host via Docker exec on nginx container)
    if docker compose -f docker-compose.prod.yml exec -T nginx curl -sf http://localhost/health &>/dev/null; then
        log INFO "Nginx edge proxy health check passed."
    else
        log WARN "Nginx not responding on port ${FXLAB_HTTP_PORT}."
    fi

    # Database
    if docker compose -f docker-compose.prod.yml exec -T postgres pg_isready -U fxlab &>/dev/null; then
        log INFO "PostgreSQL is ready."
    else
        log WARN "PostgreSQL not responding."
    fi

    # Redis
    if docker compose -f docker-compose.prod.yml exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
        log INFO "Redis is ready."
    else
        log WARN "Redis not responding."
    fi

    # Prometheus
    if docker compose -f docker-compose.prod.yml exec -T prometheus wget --spider -q http://localhost:9090/-/healthy 2>/dev/null; then
        log INFO "Prometheus is ready."
    else
        log WARN "Prometheus not responding."
    fi

    # Alertmanager
    if docker compose -f docker-compose.prod.yml exec -T alertmanager wget --spider -q http://localhost:9093/-/healthy 2>/dev/null; then
        log INFO "Alertmanager is ready."
    else
        log WARN "Alertmanager not responding."
    fi

    # Node Exporter
    if docker compose -f docker-compose.prod.yml exec -T node-exporter wget --spider -q http://localhost:9100/metrics 2>/dev/null; then
        log INFO "Node Exporter is ready."
    else
        log WARN "Node Exporter not responding."
    fi

    # cAdvisor
    if docker compose -f docker-compose.prod.yml exec -T cadvisor wget --spider -q http://localhost:8080/healthz 2>/dev/null; then
        log INFO "cAdvisor is ready."
    else
        log WARN "cAdvisor not responding."
    fi

    # Print deployed version
    local deployed_sha
    deployed_sha="$(git -C "$FXLAB_HOME" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
    local deployed_date
    deployed_date="$(git -C "$FXLAB_HOME" log -1 --format='%ci' 2>/dev/null || echo "unknown")"
    log INFO "Deployed version: ${deployed_sha} (${deployed_date})"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print_summary() {
    local hostname
    hostname="$(hostname -I 2>/dev/null | awk '{print $1}' || hostname)"
    local sha
    sha="$(git -C "$FXLAB_HOME" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
    local branch
    branch="$(git -C "$FXLAB_HOME" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

    echo ""
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    if [[ "$INSTALL_MODE" == "update" ]]; then
        echo -e "${GREEN}${BOLD}  FXLab Update Complete${NC}"
    else
        echo -e "${GREEN}${BOLD}  FXLab Installation Complete${NC}"
    fi
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    echo ""
    echo -e "  ${BOLD}Version:${NC}          ${sha} (${branch})"
    echo -e "  ${BOLD}Web Application:${NC}  http://${hostname}:${FXLAB_HTTP_PORT}"
    echo -e "  ${BOLD}API Endpoint:${NC}     http://${hostname}:${FXLAB_HTTP_PORT}/api/"
    echo -e "  ${BOLD}API Health:${NC}       http://${hostname}:${FXLAB_HTTP_PORT}/api/health"
    echo ""
    echo -e "  ${BOLD}Installation:${NC}     ${FXLAB_HOME}"
    echo -e "  ${BOLD}Configuration:${NC}    ${FXLAB_HOME}/.env"
    echo -e "  ${BOLD}Install log:${NC}      ${LOG_FILE}"
    echo ""
    echo -e "  ${BOLD}Manage:${NC}"
    echo "    sudo systemctl status fxlab           # Check status"
    echo "    sudo systemctl restart fxlab          # Restart"
    echo "    sudo bash /opt/fxlab/install.sh            # Update to latest"
    echo "    cd ${FXLAB_HOME} && docker compose -f docker-compose.prod.yml logs -f"
    echo ""
    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        # Extract admin credentials from the API container logs.
        # The seed_admin tool prints a bordered block containing the email
        # and auto-generated password. We capture it here so the operator
        # sees it in the install summary — not buried in container logs.
        local admin_creds
        admin_creds="$(
            docker compose -f docker-compose.prod.yml logs api 2>/dev/null \
                | grep -A6 'FXLAB INITIAL ADMIN CREDENTIALS' \
                | grep -E '(Email|Password):' \
                | sed 's/^.*Email:/    Email:/' \
                | sed 's/^.*Password:/    Password:/'
        )" || true

        echo -e "  ${BOLD}Credentials:${NC}"
        if [[ -n "$admin_creds" ]]; then
            echo -e "${GREEN}${BOLD}"
            echo "$admin_creds"
            echo -e "${NC}"
            echo -e "  ${YELLOW}>>> Save these credentials now — they will NOT be shown again. <<<${NC}"
            echo -e "  ${YELLOW}>>> Change the password immediately after first login.         <<<${NC}"
        else
            echo "    Admin user may already exist (seed was skipped)."
            echo "    To create a new admin manually:"
            echo "      cd ${FXLAB_HOME} && docker compose -f docker-compose.prod.yml exec api python -m services.api.cli.seed_admin"
        fi
        echo ""
        echo -e "  ${BOLD}Infrastructure secrets:${NC}"
        echo "    See ${FXLAB_HOME}/.env for database, JWT, and service secrets."
        echo ""
        echo -e "${YELLOW}  IMPORTANT: Back up your .env file — it contains production secrets.${NC}"
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_parse_install_args() {
    # CLI parser. Unknown args fail loudly rather than being silently
    # ignored (the most common installer mistake is a misspelled flag
    # that looks like it worked).
    #
    # INSTALL_MODE_FLAG — if set by --fresh or --refresh, it overrides
    # the interactive prompt in detect_mode(). Required for
    # non-interactive (piped/scripted) invocations.
    INSTALL_MODE_FLAG=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --fresh)
                INSTALL_MODE_FLAG="fresh"
                shift
                ;;
            --refresh)
                INSTALL_MODE_FLAG="refresh"
                shift
                ;;
            --all-logs)
                INSTALL_ALL_LOGS=1
                shift
                ;;
            -h|--help)
                cat <<EOF
FXLab Platform Installer

Usage:
  sudo bash install.sh [--fresh | --refresh] [--all-logs]

Options:
  --fresh       Force a fresh install: tear down all existing FXLab
                containers, volumes, and images before rebuilding.
                Use when you want a completely clean start.
  --refresh     Force a refresh: pull latest code, rebuild images,
                restart services. Preserves database data, .env
                configuration, and service state. Equivalent to an
                in-place code update.
  --all-logs    On diagnostic failure, dump every failing service's
                full log to stdout instead of writing them to
                per-service files under \$FXLAB_LOG_DIR
                (default: ${FXLAB_LOG_DIR}).
                Equivalent to setting INSTALL_ALL_LOGS=1.
  -h, --help    Show this help and exit.

If neither --fresh nor --refresh is specified and an existing FXLab
installation is detected, install.sh will prompt interactively.
Non-interactive invocations (piped stdin) MUST pass one of the two
flags, or the script will fail with a clear error.

Environment variables (see top of install.sh for the full list):
  FXLAB_HOME, FXLAB_REPO, FXLAB_BRANCH, FXLAB_LOG_DIR,
  INSTALL_ALL_LOGS, SKIP_SYSTEMD, FXLAB_ALLOW_STALE_CODE
EOF
                exit 0
                ;;
            *)
                fail "Unknown install.sh argument: '$1' (try --help)"
                ;;
        esac
    done
}

main() {
    _parse_install_args "$@"

    # Ensure log directory exists
    mkdir -p /var/log/fxlab
    mkdir -p "${FXLAB_LOG_DIR}"

    echo -e "\n${BOLD}FXLab Platform Installer${NC}"
    echo -e "Installation log: $LOG_FILE\n"

    check_root
    detect_pkg_manager

    # Update package index early so auto-installs succeed
    if [[ -n "$PKG_UPDATE" ]]; then
        log INFO "Updating package index..."
        $PKG_UPDATE 2>>"$LOG_FILE" || true
    fi

    # Pre-flight: OS, Git, Docker must be working BEFORE detect_mode(),
    # which probes Docker state to find existing containers/volumes.
    check_os
    check_git
    check_docker

    # detect_mode() examines .env, Docker containers, and Docker volumes
    # to determine the install mode. If existing artifacts are found it
    # prompts the user (or reads --fresh / --refresh from the CLI).
    detect_mode

    if [[ "$INSTALL_MODE" == "update" ]]; then
        log INFO "Refresh mode — existing installation detected at ${FXLAB_HOME}"
    else
        log INFO "Fresh install mode — tearing down any existing artifacts."
    fi

    # Fresh install: tear down existing containers, volumes, and images
    # BEFORE the port check. This is the critical ordering fix for the
    # 2026-04-16 minitux reinstall failure — old docker-proxy was holding
    # port 80, and check_ports() killed the script before build_and_start()'s
    # stale-state cleanup ever got a chance to run.
    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        teardown_existing
    fi

    check_resources
    check_ports

    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        if [[ -d "${FXLAB_HOME}/.git" ]]; then
            # Repo was already cloned by the user (recommended install path).
            # Skip clone and GitHub access check — the code is already here.
            # IMPORTANT (2026-04-15 v2 remediation): always pull_latest()
            # even in fresh mode when .git exists. A prior version logged
            # "skipping clone" and built from whatever stale commit was on
            # disk. That caused the 2026-04-15 minitux install to deploy
            # pre-fix code, masking every compose/config remediation that
            # had been committed upstream. pull_latest() fetches the branch
            # tip and hard-resets to it, with full SHA verification.
            log INFO "Repository already cloned at ${FXLAB_HOME} — pulling latest from ${FXLAB_BRANCH}."
            pull_latest
        else
            check_github_access
            clone_repo
        fi
    elif [[ "$INSTALL_MODE" == "update" ]]; then
        pull_latest
    fi

    setup_env
    tune_host_kernel
    build_and_start
    wait_for_healthy
    install_systemd
    verify_installation
    print_summary
}

# Only execute main() when this file is run directly (not sourced by tests).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi

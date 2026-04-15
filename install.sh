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

LOG_FILE="/var/log/fxlab/install-$(date +%Y%m%d-%H%M%S).log"

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
    if [[ -d "${FXLAB_HOME}/.git" ]]; then
        INSTALL_MODE="update"
    else
        INSTALL_MODE="fresh"
    fi
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
        # SSH — verify ssh connectivity to github.com
        if ! ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -T git@github.com 2>&1 | grep -qi "successfully authenticated"; then
            fail "SSH authentication to GitHub failed. Ensure your SSH key is configured:\n  ssh-keygen -t ed25519\n  ssh-add ~/.ssh/id_ed25519\n  Add the public key to https://github.com/settings/keys\n\nOr switch to HTTPS:\n  FXLAB_REPO=https://github.com/glennatlayla/fxlab.git sudo bash install.sh"
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
# Git operations
# ---------------------------------------------------------------------------

clone_repo() {
    log STEP "Cloning FXLab repository..."

    mkdir -p "$(dirname "$FXLAB_HOME")"

    if ! git clone --branch "$FXLAB_BRANCH" --depth 1 "$FXLAB_REPO" "$FXLAB_HOME" 2>>"$LOG_FILE"; then
        fail "git clone failed. Check access permissions and network connectivity."
    fi

    log INFO "Cloned ${FXLAB_REPO} (branch: ${FXLAB_BRANCH}) to ${FXLAB_HOME}"
}

pull_latest() {
    log STEP "Pulling latest changes..."

    cd "$FXLAB_HOME"

    # Stash any local changes (e.g. operator tweaks to docker-compose)
    local stash_needed=0
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        log INFO "Stashing local changes..."
        git stash push -m "fxlab-install-$(date +%Y%m%d-%H%M%S)" 2>>"$LOG_FILE" || true
        stash_needed=1
    fi

    # Fetch and reset to the latest remote branch
    # Using fetch + reset instead of pull to handle force-pushes and diverged history
    local current_sha
    current_sha="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"

    if ! git fetch origin "$FXLAB_BRANCH" --depth 1 2>>"$LOG_FILE"; then
        log WARN "git fetch failed (root may lack SSH keys for private repo)."
        log WARN "Proceeding with existing code at $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')."
        log WARN "To update code: run 'cd ${FXLAB_HOME} && git pull' as a user with GitHub SSH access, then re-run this script."
        return 0
    fi

    if ! git reset --hard "origin/${FXLAB_BRANCH}" 2>>"$LOG_FILE"; then
        fail "git reset failed. The repository may be in a broken state."
    fi

    local new_sha
    new_sha="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"

    if [[ "$current_sha" == "$new_sha" ]]; then
        log INFO "Already at latest commit: ${new_sha}"
    else
        log INFO "Updated: ${current_sha} → ${new_sha}"
        # Show what changed (abbreviated)
        git log --oneline "${current_sha}..${new_sha}" 2>/dev/null | head -10 >> "$LOG_FILE" || true
    fi

    # Re-apply stashed changes if any
    if [[ "$stash_needed" -eq 1 ]]; then
        if git stash pop 2>>"$LOG_FILE"; then
            log INFO "Re-applied local changes from stash."
        else
            log WARN "Could not re-apply stashed changes. They are saved in: git stash list"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Environment & secrets
# ---------------------------------------------------------------------------

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

    # Build application images
    log INFO "Building application images (this may take 3-5 minutes on first run)..."
    if ! docker compose -f docker-compose.prod.yml build 2>>"$LOG_FILE"; then
        fail "Docker image build failed. Check the log: $LOG_FILE"
    fi
    log INFO "Images built successfully."

    # Start services
    log INFO "Starting services..."
    if ! docker compose -f docker-compose.prod.yml up -d --remove-orphans 2>>"$LOG_FILE"; then
        fail "Failed to start services. Check: docker compose -f docker-compose.prod.yml logs"
    fi
    log INFO "Services started."

    # Prune old dangling images from previous builds to save disk
    docker image prune -f 2>>"$LOG_FILE" || true
}

wait_for_healthy() {
    log STEP "Waiting for services to become healthy..."

    local max_wait=120
    local elapsed=0
    local interval=5

    while [[ "$elapsed" -lt "$max_wait" ]]; do
        local healthy_count
        healthy_count="$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | \
            python3 -c "import sys,json; data=[json.loads(l) for l in sys.stdin]; print(sum(1 for s in data if s.get('Health','') == 'healthy'))" 2>/dev/null || echo "0")"

        local total_count
        total_count="$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | \
            python3 -c "import sys,json; data=[json.loads(l) for l in sys.stdin]; print(len(data))" 2>/dev/null || echo "0")"

        if [[ "$healthy_count" -ge 5 ]] && [[ "$total_count" -ge 5 ]]; then
            log INFO "All ${healthy_count}/${total_count} services are healthy."
            return 0
        fi

        log INFO "Healthy: ${healthy_count}/${total_count} — waiting... (${elapsed}s / ${max_wait}s)"
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    log WARN "Not all services healthy after ${max_wait}s. Checking status..."
    docker compose -f docker-compose.prod.yml ps 2>>"$LOG_FILE"
    fail "Services did not become healthy within ${max_wait}s. Check: docker compose -f docker-compose.prod.yml logs"
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
        if docker compose -f docker-compose.prod.yml exec -T web wget -qO- http://localhost:3000 &>/dev/null; then
            web_healthy=1
            break
        fi
        sleep 2
    done
    [[ "$web_healthy" -eq 1 ]] && log INFO "Frontend health check passed." || log WARN "Frontend health check failed — may still be starting."

    # Edge proxy
    if curl -sf "http://localhost:${FXLAB_HTTP_PORT}/health" &>/dev/null; then
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
        echo -e "  ${BOLD}Credentials:${NC}"
        echo "    See ${FXLAB_HOME}/.env for generated secrets."
        echo ""
        echo -e "${YELLOW}  IMPORTANT: Back up your .env file — it contains production secrets.${NC}"
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    # Ensure log directory exists
    mkdir -p /var/log/fxlab

    echo -e "\n${BOLD}FXLab Platform Installer${NC}"
    echo -e "Installation log: $LOG_FILE\n"

    check_root
    detect_pkg_manager

    # Update package index early so auto-installs succeed
    if [[ -n "$PKG_UPDATE" ]]; then
        log INFO "Updating package index..."
        $PKG_UPDATE 2>>"$LOG_FILE" || true
    fi

    detect_mode

    if [[ "$INSTALL_MODE" == "update" ]]; then
        log INFO "Update mode — existing installation detected at ${FXLAB_HOME}"
    else
        log INFO "Fresh install mode — no existing installation at ${FXLAB_HOME}"
    fi

    check_os
    check_git
    check_docker
    check_resources
    check_ports

    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        check_github_access
        clone_repo
    elif [[ "$INSTALL_MODE" == "update" ]]; then
        pull_latest
    fi

    setup_env
    build_and_start
    wait_for_healthy
    install_systemd
    verify_installation
    print_summary
}

main "$@"

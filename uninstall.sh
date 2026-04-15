#!/usr/bin/env bash
# ===========================================================================
# FXLab Platform — Uninstall Script
# ===========================================================================
#
# Removes the FXLab platform from the host:
#   1. Stops and removes all Docker containers and images.
#   2. Removes Docker volumes (database, redis) if confirmed.
#   3. Removes systemd service unit.
#   4. Optionally removes the installation directory.
#
# Usage:
#   sudo ./uninstall.sh
#   sudo ./uninstall.sh --purge   # Also removes /opt/fxlab
#
# ===========================================================================

set -euo pipefail

FXLAB_HOME="${FXLAB_HOME:-/opt/fxlab}"
PURGE=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

if [[ "${1:-}" == "--purge" ]]; then
    PURGE=1
fi

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}This script must be run as root (or with sudo).${NC}"
    exit 1
fi

echo -e "${BOLD}FXLab Uninstaller${NC}"
echo ""

# Stop services
echo -e "${YELLOW}Stopping FXLab services...${NC}"
if command -v systemctl &>/dev/null && systemctl is-active fxlab &>/dev/null; then
    systemctl stop fxlab
    echo -e "${GREEN}[OK]${NC} systemd service stopped."
fi

if [[ -f "${FXLAB_HOME}/docker-compose.prod.yml" ]]; then
    cd "$FXLAB_HOME"
    docker compose -f docker-compose.prod.yml down --timeout 30 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC} Docker containers stopped and removed."
fi

# Remove volumes
echo ""
read -rp "Remove Docker volumes (database and Redis data)? This DELETES ALL DATA. [y/N] " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    docker volume rm fxlab-postgres-data fxlab-redis-data fxlab-nginx-certs 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC} Docker volumes removed."
else
    echo -e "${YELLOW}[SKIP]${NC} Volumes preserved."
fi

# Remove Docker images
echo ""
read -rp "Remove Docker images (fxlab-api, fxlab-web)? [y/N] " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    docker rmi "$(docker images --filter 'reference=*fxlab*' -q)" 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC} Docker images removed."
else
    echo -e "${YELLOW}[SKIP]${NC} Images preserved."
fi

# Remove systemd service
if [[ -f /etc/systemd/system/fxlab.service ]]; then
    systemctl disable fxlab 2>/dev/null || true
    rm -f /etc/systemd/system/fxlab.service
    systemctl daemon-reload
    echo -e "${GREEN}[OK]${NC} systemd service removed."
fi

# Remove installation directory
if [[ "$PURGE" -eq 1 ]]; then
    echo ""
    echo -e "${RED}WARNING: About to delete ${FXLAB_HOME} and all its contents.${NC}"
    read -rp "Are you sure? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "$FXLAB_HOME"
        echo -e "${GREEN}[OK]${NC} ${FXLAB_HOME} removed."
    else
        echo -e "${YELLOW}[SKIP]${NC} Installation directory preserved."
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}FXLab has been uninstalled.${NC}"

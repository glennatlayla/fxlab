#!/usr/bin/env bash
# ===========================================================================
# FXLab — Build Release Package
# ===========================================================================
#
# Creates a self-contained .zip archive for deploying FXLab to a Linux host.
# The archive contains everything needed to install and run the platform.
#
# Output:
#   fxlab-<version>-<date>.zip
#
# Contents:
#   - Application source (services/, libs/, frontend/, migrations/)
#   - Docker build files (Dockerfiles, docker-compose.prod.yml)
#   - Installation script (install.sh)
#   - Nginx configuration (deploy/nginx/)
#   - systemd service unit (deploy/systemd/)
#   - Environment template (.env.production.template)
#   - Documentation (README-INSTALL.md)
#
# Usage:
#   chmod +x build-release.sh
#   ./build-release.sh
#   # => fxlab-1.0.0-20260413.zip
#
# ===========================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Version from git tag or fallback
VERSION="${FXLAB_VERSION:-$(git describe --tags --abbrev=0 2>/dev/null || echo "1.0.0")}"
DATE="$(date +%Y%m%d)"
RELEASE_NAME="fxlab-${VERSION}-${DATE}"
BUILD_DIR="/tmp/${RELEASE_NAME}"
OUTPUT_FILE="${SCRIPT_DIR}/${RELEASE_NAME}.zip"

echo "Building release: ${RELEASE_NAME}"
echo "Output: ${OUTPUT_FILE}"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# ---------------------------------------------------------------------------
# Copy application files
# ---------------------------------------------------------------------------

echo "Copying application files..."

# Core application — use rsync to exclude large/transient directories
if command -v rsync &>/dev/null; then
    rsync -a --exclude='node_modules' --exclude='dist' --exclude='coverage' \
          --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
          --exclude='.mypy_cache' --exclude='.git' --exclude='.archive' \
          services/ "$BUILD_DIR/services/"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.archive' \
          libs/ "$BUILD_DIR/libs/"
    rsync -a --exclude='node_modules' --exclude='dist' --exclude='coverage' \
          --exclude='.git' --exclude='.archive' \
          frontend/ "$BUILD_DIR/frontend/"
    rsync -a migrations/ "$BUILD_DIR/migrations/"
    rsync -a config/ "$BUILD_DIR/config/" 2>/dev/null || true
else
    cp -a services/ "$BUILD_DIR/services/"
    cp -a libs/ "$BUILD_DIR/libs/"
    # For frontend: copy selectively to avoid node_modules
    mkdir -p "$BUILD_DIR/frontend"
    for item in frontend/*; do
        basename_item="$(basename "$item")"
        case "$basename_item" in
            node_modules|dist|coverage) continue ;;
            *) cp -a "$item" "$BUILD_DIR/frontend/" ;;
        esac
    done
    cp -a migrations/ "$BUILD_DIR/migrations/"
    cp -a config/ "$BUILD_DIR/config/" 2>/dev/null || true
fi

# Build and deployment
cp -a deploy/ "$BUILD_DIR/deploy/"
cp docker-compose.prod.yml "$BUILD_DIR/"
cp docker-compose.yml "$BUILD_DIR/"
cp requirements.txt "$BUILD_DIR/"
cp alembic.ini "$BUILD_DIR/"

# Installation and utility scripts
cp install.sh "$BUILD_DIR/"
cp uninstall.sh "$BUILD_DIR/"
cp build-release.sh "$BUILD_DIR/"
chmod +x "$BUILD_DIR/install.sh" "$BUILD_DIR/uninstall.sh" "$BUILD_DIR/build-release.sh"

# Configuration templates
cp .env.production.template "$BUILD_DIR/"
cp .env.example "$BUILD_DIR/"

# Documentation
cp README-INSTALL.md "$BUILD_DIR/"
cp CLAUDE.md "$BUILD_DIR/" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Clean up build artifacts
# ---------------------------------------------------------------------------

echo "Cleaning build artifacts..."

find "$BUILD_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name 'node_modules' -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name '.pytest_cache' -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name '.mypy_cache' -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -name '*.pyc' -delete 2>/dev/null || true
find "$BUILD_DIR" -name '.env' -delete 2>/dev/null || true
find "$BUILD_DIR" -name '.git' -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf "$BUILD_DIR/frontend/dist" 2>/dev/null || true
rm -rf "$BUILD_DIR/frontend/coverage" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------

echo "Creating zip archive..."

cd /tmp
if command -v zip &>/dev/null; then
    zip -rq "$OUTPUT_FILE" "$RELEASE_NAME/"
else
    # Fallback to tar+gzip if zip not available
    OUTPUT_FILE="${SCRIPT_DIR}/${RELEASE_NAME}.tar.gz"
    tar -czf "$OUTPUT_FILE" "$RELEASE_NAME/"
    echo "Note: 'zip' not installed — created .tar.gz instead."
fi

# Cleanup
rm -rf "$BUILD_DIR"

# Summary
FILE_SIZE="$(du -h "$OUTPUT_FILE" | cut -f1)"
echo ""
echo "Release built successfully:"
echo "  File: ${OUTPUT_FILE}"
echo "  Size: ${FILE_SIZE}"
echo ""
echo "To deploy:"
echo "  1. Copy ${OUTPUT_FILE} to the target machine"
echo "  2. unzip ${RELEASE_NAME}.zip  (or: tar -xzf ${RELEASE_NAME}.tar.gz)"
echo "  3. cd ${RELEASE_NAME}"
echo "  4. sudo ./install.sh"

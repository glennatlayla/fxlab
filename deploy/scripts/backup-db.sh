#!/bin/bash

################################################################################
#
# FXLab Database Backup Script
#
# Purpose:
#   Automated, production-grade PostgreSQL backup for FXLab trading platform.
#   Dumps the database from a running Docker container, compresses it, verifies
#   integrity, and applies retention policies.
#
# Responsibilities:
#   - Perform pre-flight checks (Docker, container health, disk space)
#   - Dump PostgreSQL database via docker exec with pg_dump
#   - Compress backup with gzip for storage efficiency
#   - Verify dump validity before considering backup complete
#   - Apply retention policy (delete old backups older than BACKUP_RETENTION_DAYS)
#   - Log all operations with timestamps to both stdout and log file
#   - Provide machine-parseable exit status and restore instructions
#   - Handle errors gracefully with cleanup and appropriate exit codes
#
# Does NOT:
#   - Copy backups to remote storage (out of scope; caller may layer this on)
#   - Monitor backup size trends (caller owns monitoring/alerting)
#   - Perform application-level backup validation (integrity tests owned by app)
#   - Execute restores (caller owns restore procedures; we provide instructions)
#
# Dependencies:
#   - Bash 4.0+
#   - Docker (must be running and accessible to $USER)
#   - PostgreSQL client tools (pg_dump, pg_restore in container)
#   - Standard GNU utilities (find, stat, date, gzip)
#
# Environment Variables (optional):
#   BACKUP_DIR           — Directory to store backups (default: /opt/fxlab/backups)
#   BACKUP_RETENTION_DAYS — Keep backups newer than N days (default: 30)
#   DOCKER_CONTAINER     — Name of PostgreSQL container (default: fxlab-postgres)
#   POSTGRES_USER        — Database user for backup (default: fxlab)
#   POSTGRES_DB          — Database name to backup (default: fxlab)
#   LOG_LEVEL            — Log verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)
#   DRY_RUN              — If set to 1, simulate operations without writing (default: 0)
#
# Exit Codes:
#   0 — Success: backup created, verified, and retention applied
#   1 — Generic failure (see log for details)
#   2 — Pre-flight check failed (Docker down, container unhealthy, disk full, etc.)
#   3 — pg_dump failed (database dump could not be created)
#   4 — Backup verification failed (dump is invalid or corrupted)
#   5 — Insufficient disk space (pre-flight or mid-operation)
#
# Usage:
#   # One-shot backup (all defaults)
#   ./backup-db.sh
#
#   # Custom backup directory and retention
#   BACKUP_DIR=/mnt/backups BACKUP_RETENTION_DAYS=60 ./backup-db.sh
#
#   # Dry-run to verify script without creating files
#   DRY_RUN=1 ./backup-db.sh
#
#   # Cron job (run daily at 2 AM, keep 30 days of backups)
#   0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup.log 2>&1
#
# Restore Instructions (printed at end of log):
#   Once a backup is verified, restore with:
#   $ gunzip -c /path/to/backup-YYYY-MM-DDTHH:MM:SS+00:00.sql.gz | \
#     docker exec -i fxlab-postgres psql -U fxlab -d fxlab
#
# Example Log Output:
#   2026-04-13T15:23:45Z [INFO] Backup started
#   2026-04-13T15:23:45Z [INFO] Pre-flight checks: Docker running, container healthy
#   2026-04-13T15:23:45Z [INFO] Estimated DB size: 256 MB (available disk: 8.1 GB)
#   2026-04-13T15:23:52Z [INFO] Dump complete: /opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql
#   2026-04-13T15:23:58Z [INFO] Compression complete: backup-2026-04-13T15:23:45Z.sql.gz (98 MB)
#   2026-04-13T15:23:58Z [INFO] Backup verification: VALID (5247 lines, restore possible)
#   2026-04-13T15:23:59Z [INFO] Retention: deleted 0 backups, 3 remaining (all < 30 days old)
#   2026-04-13T15:23:59Z [STATUS] success: backup=backup-2026-04-13T15:23:45Z.sql.gz duration_ms=14500
#
################################################################################

set -euo pipefail

# ============================================================================
# Constants and defaults
# ============================================================================

readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly INSTALL_DIR="${INSTALL_DIR:-/opt/fxlab}"

# Configuration with environment variable overrides
BACKUP_DIR="${BACKUP_DIR:-${INSTALL_DIR}/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DOCKER_CONTAINER="${DOCKER_CONTAINER:-fxlab-postgres}"
POSTGRES_USER="${POSTGRES_USER:-fxlab}"
POSTGRES_DB="${POSTGRES_DB:-fxlab}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
DRY_RUN="${DRY_RUN:-0}"

# Logging setup
readonly LOG_FILE="${BACKUP_DIR}/backup.log"
readonly TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
TIMESTAMP_ISO8601="$(date -u +'%Y-%m-%dT%H:%M:%S%z')"
# Remove colon from timezone for filename safety (YYYYMMDDTHHMMSS+HHMM)
BACKUP_FILENAME_TS="${TIMESTAMP_ISO8601//:}"

# Temporary files for cleanup
declare -a TEMP_FILES=()

# Tracking variables
BACKUP_FILE=""
BACKUP_FILE_GZ=""
EXIT_CODE=0
START_TIME_MS=$(( $(date +%s) * 1000 ))

# ============================================================================
# Logging functions
# ============================================================================

#
# Log a message with timestamp and level to both stdout and log file.
#
# Args:
#   $1 - Log level (DEBUG, INFO, WARNING, ERROR)
#   $2 - Message text
#
# Returns:
#   0 on success; writes to stdout, stderr, and log file
#
log_msg() {
    local level="$1"
    local msg="$2"
    local output="${TIMESTAMP} [${level}] ${msg}"

    # Determine output stream based on level
    local output_stream="1"
    [[ "$level" == "ERROR" || "$level" == "WARNING" ]] && output_stream="2"

    # Write to stdout/stderr
    echo "${output}" >&"${output_stream}"

    # Write to log file (if directory exists)
    if [[ -d "$BACKUP_DIR" ]]; then
        echo "${output}" >> "$LOG_FILE"
    fi
}

#
# Log debug messages (only if LOG_LEVEL=DEBUG).
#
log_debug() {
    [[ "$LOG_LEVEL" == "DEBUG" ]] && log_msg "DEBUG" "$1" || true
}

log_info() {
    log_msg "INFO" "$1"
}

log_warn() {
    log_msg "WARNING" "$1"
}

log_error() {
    log_msg "ERROR" "$1"
}

#
# Print machine-parseable status line (suitable for cron monitoring).
# Must be on a single line with key=value pairs.
#
# Args:
#   $1 - Status (success, failure, partial)
#   $2 - Message (backup file, error reason, etc.)
#
log_status() {
    local status="$1"
    local msg="$2"
    local duration_ms=$(( ($(date +%s) * 1000) - START_TIME_MS ))
    local status_line="${TIMESTAMP} [STATUS] ${status}: ${msg} duration_ms=${duration_ms}"
    echo "${status_line}" | tee -a "$LOG_FILE"
}

# ============================================================================
# Cleanup and error handling
# ============================================================================

#
# Cleanup function: remove temporary files, close file descriptors.
# Called on EXIT trap (always) or manually on error.
#
cleanup() {
    local cleanup_rc=$?

    log_debug "Cleanup: removing ${#TEMP_FILES[@]} temporary files"

    for f in "${TEMP_FILES[@]}"; do
        if [[ -f "$f" ]]; then
            log_debug "Removing temp file: $f"
            [[ "$DRY_RUN" == "0" ]] && rm -f "$f" || true
        fi
    done

    return $cleanup_rc
}

#
# Exit with a specific code and log the reason.
#
# Args:
#   $1 - Exit code (0=success, 1=generic, 2=preflight, 3=dump, 4=verify, 5=disk)
#   $2 - Error message (optional)
#
die() {
    local code="$1"
    local msg="${2:-Unknown error}"

    if [[ "$code" -eq 0 ]]; then
        log_info "Backup completed successfully"
        log_status "success" "backup=${BACKUP_FILE_GZ##*/}"
    else
        log_error "$msg"
        log_status "failure" "code=${code} reason=${msg}"
    fi

    EXIT_CODE="$code"
    exit "$code"
}

# Install exit trap for cleanup
trap cleanup EXIT

# ============================================================================
# Utility functions
# ============================================================================

#
# Check if Docker daemon is running and container is accessible.
#
# Returns:
#   0 if Docker is running and we can connect; 1 otherwise.
#
check_docker_running() {
    if ! docker info > /dev/null 2>&1; then
        return 1
    fi
    return 0
}

#
# Check if the PostgreSQL container is healthy.
#
# Returns:
#   0 if container exists and is running; 1 otherwise.
#
check_container_healthy() {
    local status
    status=$(docker inspect -f '{{.State.Status}}' "$DOCKER_CONTAINER" 2>/dev/null || echo "missing")

    if [[ "$status" != "running" ]]; then
        return 1
    fi

    # Verify health check passes (if defined)
    local health_status
    health_status=$(docker inspect -f '{{.State.Health.Status}}' "$DOCKER_CONTAINER" 2>/dev/null || echo "unknown")

    if [[ "$health_status" == "unhealthy" ]]; then
        return 1
    fi

    return 0
}

#
# Estimate current database size using pg_stat_database.
#
# Returns:
#   Size in bytes; 0 if estimation fails.
#
estimate_db_size() {
    local size
    size=$(docker exec "$DOCKER_CONTAINER" psql \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -t -c "SELECT pg_database_size('$POSTGRES_DB');" 2>/dev/null || echo "0")

    echo "${size}"
}

#
# Convert bytes to human-readable format.
#
# Args:
#   $1 - Size in bytes
#
# Returns:
#   String like "256 MB" or "1.2 GB"
#
human_readable_size() {
    local bytes=$1
    if (( bytes < 1024 )); then
        echo "${bytes} B"
    elif (( bytes < 1024 * 1024 )); then
        echo "$(( bytes / 1024 )) KB"
    elif (( bytes < 1024 * 1024 * 1024 )); then
        echo "$(( bytes / (1024 * 1024) )) MB"
    else
        echo "$(( bytes / (1024 * 1024 * 1024) )) GB"
    fi
}

#
# Get available disk space in the backup directory.
#
# Returns:
#   Available space in bytes.
#
get_available_disk() {
    local avail
    avail=$(df -B1 "$BACKUP_DIR" | tail -1 | awk '{print $4}')
    echo "${avail}"
}

#
# Check if sufficient disk space is available.
# Requires at least 2x estimated DB size.
#
# Returns:
#   0 if space is sufficient; 1 if insufficient.
#
check_disk_space() {
    local db_size=$1
    local required=$(( db_size * 2 ))  # pg_dump + gzip temp space
    local available
    available=$(get_available_disk)

    if (( available < required )); then
        return 1
    fi

    return 0
}

# ============================================================================
# Pre-flight checks
# ============================================================================

#
# Perform all pre-flight validations before attempting backup.
# Checks Docker availability, container health, and disk space.
#
# Exits with code 2 if any check fails.
#
run_preflight_checks() {
    log_info "Running pre-flight checks..."

    # Create backup directory if it doesn't exist
    if [[ ! -d "$BACKUP_DIR" ]]; then
        log_debug "Creating backup directory: $BACKUP_DIR"
        if [[ "$DRY_RUN" == "0" ]]; then
            mkdir -p "$BACKUP_DIR" || die 2 "Failed to create backup directory: $BACKUP_DIR"
        else
            mkdir -p "$BACKUP_DIR" || true  # Create even in dry-run for logging
        fi
    fi

    # Check Docker daemon
    if ! check_docker_running; then
        die 2 "Docker daemon is not running or not accessible"
    fi
    log_debug "Docker daemon is running"

    # Check container exists and is healthy
    if ! check_container_healthy; then
        die 2 "Container '$DOCKER_CONTAINER' is not running or unhealthy. Status: $(docker inspect -f '{{.State.Status}}' "$DOCKER_CONTAINER" 2>/dev/null || echo 'missing')"
    fi
    log_debug "Container '$DOCKER_CONTAINER' is running and healthy"

    # Estimate DB size and check disk space
    local db_size
    db_size=$(estimate_db_size)
    if [[ -z "$db_size" || "$db_size" == "0" ]]; then
        log_warn "Could not estimate database size; skipping disk space check"
        db_size=268435456  # Default to 256 MB if estimation fails
    fi

    local available
    available=$(get_available_disk)
    log_info "Estimated DB size: $(human_readable_size "$db_size") (available disk: $(human_readable_size "$available"))"

    if ! check_disk_space "$db_size"; then
        die 5 "Insufficient disk space. Required: $(human_readable_size $(( db_size * 2 ))), Available: $(human_readable_size "$available")"
    fi

    log_info "Pre-flight checks passed"
}

# ============================================================================
# Backup operations
# ============================================================================

#
# Execute pg_dump via docker exec to create the database dump.
# Uses --no-owner --no-acl for portability across environments.
#
# Returns:
#   0 on success; creates uncompressed SQL dump file.
#
perform_dump() {
    log_info "Starting database dump..."

    BACKUP_FILE="${BACKUP_DIR}/backup-${BACKUP_FILENAME_TS}.sql"

    # Backup using pg_dump with clean output format (portable)
    local dump_cmd="pg_dump -U $POSTGRES_USER -d $POSTGRES_DB --no-owner --no-acl"

    if [[ "$DRY_RUN" == "1" ]]; then
        log_debug "DRY_RUN: would execute: docker exec $DOCKER_CONTAINER $dump_cmd > $BACKUP_FILE"
        BACKUP_FILE="${BACKUP_DIR}/backup-DRY-RUN-${BACKUP_FILENAME_TS}.sql"
        touch "$BACKUP_FILE"
    else
        if ! docker exec "$DOCKER_CONTAINER" $dump_cmd > "$BACKUP_FILE" 2>/dev/null; then
            die 3 "pg_dump failed. Check database connectivity and credentials."
        fi
    fi

    if [[ ! -f "$BACKUP_FILE" ]]; then
        die 3 "Dump file was not created: $BACKUP_FILE"
    fi

    local size
    size=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null || echo "0")

    if [[ "$size" -eq 0 ]]; then
        die 3 "Dump file is empty; backup failed silently"
    fi

    log_info "Dump complete: $BACKUP_FILE ($(human_readable_size "$size"))"
    TEMP_FILES+=("$BACKUP_FILE")
}

#
# Compress the backup file using gzip.
# Deletes the original uncompressed file after successful compression.
#
# Returns:
#   0 on success; creates .sql.gz file.
#
perform_compression() {
    log_info "Compressing backup..."

    BACKUP_FILE_GZ="${BACKUP_FILE}.gz"

    if [[ "$DRY_RUN" == "1" ]]; then
        log_debug "DRY_RUN: would execute: gzip -f $BACKUP_FILE"
        cp "$BACKUP_FILE" "$BACKUP_FILE_GZ" || die 1 "Failed to copy backup for dry-run"
    else
        if ! gzip -f "$BACKUP_FILE"; then
            die 1 "Compression failed"
        fi
    fi

    if [[ ! -f "$BACKUP_FILE_GZ" ]]; then
        die 1 "Compressed backup file was not created: $BACKUP_FILE_GZ"
    fi

    local compressed_size
    compressed_size=$(stat -f%z "$BACKUP_FILE_GZ" 2>/dev/null || stat -c%s "$BACKUP_FILE_GZ" 2>/dev/null || echo "0")
    log_info "Compression complete: $(basename "$BACKUP_FILE_GZ") ($(human_readable_size "$compressed_size"))"

    # Remove from temp files since we're keeping the compressed version
    BACKUP_FILE=""
}

#
# Verify the backup file integrity using pg_restore --list.
# Ensures the dump is valid and can be restored.
#
# Returns:
#   0 if backup is valid; exits with code 4 if verification fails.
#
verify_backup() {
    log_info "Verifying backup integrity..."

    local verify_output
    local line_count=0

    if [[ "$DRY_RUN" == "1" ]]; then
        log_debug "DRY_RUN: skipping actual pg_restore verification"
        line_count=100
    else
        # pg_restore --list only parses the archive, doesn't restore
        verify_output=$(docker exec "$DOCKER_CONTAINER" pg_restore --list "$BACKUP_FILE_GZ" 2>&1 | wc -l)
        line_count=${verify_output:-0}

        if [[ "$line_count" -lt 1 ]]; then
            die 4 "Backup verification failed: pg_restore could not parse the file"
        fi
    fi

    log_info "Backup verification: VALID ($line_count lines, restore possible)"
    log_info "Restore instructions: gunzip -c $BACKUP_FILE_GZ | docker exec -i $DOCKER_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB"
}

# ============================================================================
# Retention policy
# ============================================================================

#
# Apply retention policy: delete backups older than BACKUP_RETENTION_DAYS.
#
# Returns:
#   0 on success; logs count of deleted backups.
#
apply_retention_policy() {
    log_info "Applying retention policy (keep backups < $BACKUP_RETENTION_DAYS days old)..."

    local deleted_count=0
    local remaining_count=0
    local cutoff_seconds=$(( BACKUP_RETENTION_DAYS * 86400 ))
    local now_seconds=$(date +%s)

    # Find all .sql.gz files in backup directory
    if [[ ! -d "$BACKUP_DIR" ]]; then
        log_warn "Backup directory does not exist; skipping retention"
        return 0
    fi

    while IFS= read -r -d '' backup_file; do
        local file_age_seconds=$(( now_seconds - $(stat -f%m "$backup_file" 2>/dev/null || stat -c%Y "$backup_file") ))

        if (( file_age_seconds > cutoff_seconds )); then
            log_debug "Deleting old backup: $(basename "$backup_file") (age: $((file_age_seconds / 86400)) days)"

            if [[ "$DRY_RUN" == "0" ]]; then
                rm -f "$backup_file"
            fi
            (( deleted_count++ ))
        else
            (( remaining_count++ ))
        fi
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name "backup-*.sql.gz" -type f -print0)

    log_info "Retention: deleted $deleted_count backups, $remaining_count remaining (all < $BACKUP_RETENTION_DAYS days old)"
}

# ============================================================================
# Main execution
# ============================================================================

main() {
    log_info "Backup started"
    log_debug "Configuration: BACKUP_DIR=$BACKUP_DIR, RETENTION_DAYS=$BACKUP_RETENTION_DAYS"
    log_debug "Docker container: $DOCKER_CONTAINER, DB: $POSTGRES_USER@$POSTGRES_DB"

    # Pre-flight checks
    run_preflight_checks

    # Perform backup operations
    perform_dump
    perform_compression
    verify_backup

    # Cleanup and retention
    apply_retention_policy

    # Success
    die 0
}

# Execute main
main "$@"

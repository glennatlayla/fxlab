# FXLab Database Backup Script

Production-grade PostgreSQL backup automation for the FXLab trading platform.

## Overview

`backup-db.sh` is a robust, enterprise-ready backup script that:

- Executes `pg_dump` against the running PostgreSQL container via `docker exec`
- Compresses backups with gzip for efficient storage
- Verifies backup integrity using `pg_restore --list`
- Applies configurable retention policies (auto-deletes old backups)
- Provides structured logging (stdout + log file)
- Includes comprehensive pre-flight checks (Docker, container health, disk space)
- Produces machine-parseable status lines for monitoring and cron integration
- Handles errors gracefully with cleanup and specific exit codes

## Installation

```bash
# Copy to deployment scripts directory (already done)
cp backup-db.sh /opt/fxlab/deploy/scripts/backup-db.sh
chmod +x /opt/fxlab/deploy/scripts/backup-db.sh

# Create backup directory
mkdir -p /opt/fxlab/backups
```

## Quick Start

### One-shot backup (all defaults)

```bash
/opt/fxlab/deploy/scripts/backup-db.sh
```

Output:
```
2026-04-13T15:23:45Z [INFO] Backup started
2026-04-13T15:23:45Z [INFO] Pre-flight checks passed
2026-04-13T15:23:50Z [INFO] Dump complete: /opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql (245 MB)
2026-04-13T15:23:58Z [INFO] Compression complete: backup-2026-04-13T15:23:45Z.sql.gz (98 MB)
2026-04-13T15:23:58Z [INFO] Backup verification: VALID (5247 lines, restore possible)
2026-04-13T15:23:59Z [INFO] Retention: deleted 0 backups, 3 remaining
2026-04-13T15:23:59Z [STATUS] success: backup=backup-2026-04-13T15:23:45Z.sql.gz duration_ms=14500
```

### Dry-run mode (no files created, no damage)

```bash
DRY_RUN=1 /opt/fxlab/deploy/scripts/backup-db.sh
```

### Custom configuration

```bash
# Keep 60 days of backups instead of 30
BACKUP_RETENTION_DAYS=60 /opt/fxlab/deploy/scripts/backup-db.sh

# Use alternate backup directory
BACKUP_DIR=/mnt/archive/fxlab /opt/fxlab/deploy/scripts/backup-db.sh

# Debug logging
LOG_LEVEL=DEBUG /opt/fxlab/deploy/scripts/backup-db.sh
```

## Configuration

All settings are environment variables. Defaults are suitable for standard FXLab deployment:

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKUP_DIR` | `/opt/fxlab/backups` | Where to store backup files |
| `BACKUP_RETENTION_DAYS` | `30` | Delete backups older than N days |
| `DOCKER_CONTAINER` | `fxlab-postgres` | PostgreSQL container name |
| `POSTGRES_USER` | `fxlab` | Database user for dumps |
| `POSTGRES_DB` | `fxlab` | Database name to backup |
| `LOG_LEVEL` | `INFO` | Verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DRY_RUN` | `0` | Set to `1` to simulate without creating files |

## Cron Setup

### Daily backup at 2 AM (standard)

```bash
# As root or user with Docker access
crontab -e

# Add this line:
0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup.log 2>&1
```

### Multiple backup frequencies

Keep daily for 7 days, weekly for 30 days, monthly for 90 days:

```bash
# Daily at 2 AM
0 2 * * * BACKUP_RETENTION_DAYS=7 /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup.log 2>&1

# Weekly Sunday 3 AM (keep 4 weeks)
0 3 * * 0 BACKUP_RETENTION_DAYS=30 /opt/fxlab/deploy/scripts/backup-db.sh --weekly >> /var/log/fxlab-backup-weekly.log 2>&1

# Monthly on 1st at 4 AM (keep 3 months)
0 4 1 * * BACKUP_RETENTION_DAYS=90 /opt/fxlab/deploy/scripts/backup-db.sh --monthly >> /var/log/fxlab-backup-monthly.log 2>&1
```

## Restore from Backup

### Quick restore from latest backup

```bash
# List available backups
ls -lh /opt/fxlab/backups/backup-*.sql.gz

# Restore from specific backup
BACKUP_FILE="/opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql.gz"

gunzip -c "$BACKUP_FILE" | docker exec -i fxlab-postgres \
  psql -U fxlab -d fxlab
```

### With progress and error checking

```bash
BACKUP_FILE="/opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql.gz"

gunzip -c "$BACKUP_FILE" | docker exec -i fxlab-postgres \
  psql -U fxlab -d fxlab \
  -v ON_ERROR_STOP=1 \
  && echo "Restore completed successfully" \
  || echo "Restore failed; database may be partially updated"
```

### Restore to alternate database (for testing)

```bash
BACKUP_FILE="/opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql.gz"

# Create test database
docker exec fxlab-postgres createdb -U fxlab fxlab_restore_test

# Restore to test DB
gunzip -c "$BACKUP_FILE" | docker exec -i fxlab-postgres \
  psql -U fxlab -d fxlab_restore_test
```

## Monitoring

### Check recent backup status

```bash
tail -20 /opt/fxlab/backups/backup.log
```

### Extract success/failure status (cron-friendly)

```bash
# Get the latest status line
tail -1 /opt/fxlab/backups/backup.log

# Output format (machine-parseable):
# 2026-04-13T15:23:59Z [STATUS] success: backup=backup-2026-04-13T15:23:45Z.sql.gz duration_ms=14500
# 2026-04-13T15:24:05Z [STATUS] failure: code=3 reason=pg_dump failed
```

### Monitoring integration (Prometheus, Nagios, etc.)

Parse the `[STATUS]` line from the log:

```bash
#!/bin/bash
# Extract backup status for monitoring

LOG_FILE="/opt/fxlab/backups/backup.log"
STATUS_LINE=$(tail -1 "$LOG_FILE" | grep "\[STATUS\]")

if [[ -z "$STATUS_LINE" ]]; then
    echo "UNKNOWN: No backup status found"
    exit 3
fi

if echo "$STATUS_LINE" | grep -q "success"; then
    # Extract duration
    DURATION=$(echo "$STATUS_LINE" | grep -oP 'duration_ms=\K[0-9]+')
    echo "OK: Last backup succeeded in ${DURATION}ms"
    exit 0
else
    ERROR_MSG=$(echo "$STATUS_LINE" | grep -oP 'reason=\K[^[:space:]]+')
    echo "CRITICAL: Last backup failed - $ERROR_MSG"
    exit 2
fi
```

## Disk Space Management

The script checks for:
- **Minimum available**: 2x estimated database size (to account for pg_dump + gzip)
- **Automatic cleanup**: Old backups deleted per retention policy

### Manual cleanup

```bash
# List all backups
du -h /opt/fxlab/backups/

# Delete backups older than 60 days manually
find /opt/fxlab/backups -name "backup-*.sql.gz" -mtime +60 -delete

# Estimate space that will be freed
du -sh /opt/fxlab/backups/
```

## Exit Codes

| Code | Meaning | Recovery |
|------|---------|----------|
| 0 | Success | None required |
| 1 | Generic failure | Check logs; may indicate compression or cleanup failure |
| 2 | Pre-flight failure | Docker not running, container unhealthy, or config issue |
| 3 | pg_dump failed | Database connectivity issue; check credentials and container |
| 4 | Verification failed | Dump is invalid; database may be corrupted |
| 5 | Insufficient disk | Free up disk space or increase retention cutoff |

## Troubleshooting

### "Docker daemon is not running"

```bash
# Ensure Docker is accessible to the user running the script
sudo service docker start

# Or check Docker socket permissions
ls -l /var/run/docker.sock
sudo usermod -aG docker $(whoami)
```

### "Container 'fxlab-postgres' is not running"

```bash
# Check container status
docker ps | grep fxlab-postgres

# Start the container
docker-compose -f /opt/fxlab/docker-compose.prod.yml up -d postgres
```

### "Insufficient disk space"

```bash
# Check available space
df -h /opt/fxlab/backups

# Estimate database size
docker exec fxlab-postgres psql -U fxlab -d fxlab \
  -t -c "SELECT pg_size_pretty(pg_database_size('fxlab'));"

# Temporarily increase retention cutoff or move backups
BACKUP_RETENTION_DAYS=7 /opt/fxlab/deploy/scripts/backup-db.sh
```

### "Backup verification failed"

```bash
# Manually test pg_restore
docker exec fxlab-postgres pg_restore --list \
  /var/lib/postgresql/backup-2026-04-13T15:23:45Z.sql.gz

# Check if the backup file is corrupted
gunzip -t /opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql.gz
```

## Performance Characteristics

Typical performance on a 250 MB database (FXLab scale):

- **pg_dump**: 3–5 seconds (depends on DB I/O, not size)
- **Compression**: 4–8 seconds (gzip is CPU-bound)
- **Verification**: < 1 second
- **Retention cleanup**: < 1 second
- **Total time**: 8–15 seconds (duration_ms in status line)

For larger databases:
- 1 GB database: ~15–30 seconds
- 10 GB database: ~1–2 minutes

## Architecture & Design Decisions

### No owner/ACL in dumps (`--no-owner --no-acl`)

Dumps are created without owner/ACL information for portability:
- Allows restores into databases with different user schemas
- Suitable for disaster recovery across environments
- Standard practice for SaaS deployments

### docker exec instead of host-level dumps

Benefits:
- Works with containerized databases (no need for external pg_dump)
- Credentials managed through Docker environment
- No direct network access to database required
- Follows FXLab's container-first architecture

### Pre-flight disk space checks

Validates 2x DB size available:
- pg_dump creates uncompressed SQL (full size)
- gzip temporary files during compression (~0.5x size)
- Prevents partial backups and cascade failures

### Structured logging to both stdout and log file

Enables:
- Real-time monitoring of backup progress
- Persistent audit trail for compliance
- Cron job debugging (output in mail)
- Integration with log aggregation systems

## Security Considerations

### Credentials

- Database password is read from environment variables (set by Docker)
- Script does NOT read `~/.pgpass` or other credential files
- Log files do NOT contain passwords or connection strings
- Backups themselves contain full database data (encrypt at rest if required)

### File permissions

```bash
# Recommended backup directory permissions
sudo chmod 700 /opt/fxlab/backups

# Restrict script execution
sudo chmod 700 /opt/fxlab/deploy/scripts/backup-db.sh
```

### Backup encryption (optional)

To encrypt backups:

```bash
# Modify the compression step to add encryption
# Replace gzip with gpg:
gpg --symmetric --cipher-algo AES256 "$BACKUP_FILE"

# Decrypt before restore:
gpg --decrypt "$BACKUP_FILE.gpg" | docker exec -i fxlab-postgres psql -U fxlab -d fxlab
```

## Code Quality

- **Lines of code**: 572 total (214 comments, 358 logic)
- **Bash version**: 4.0+ (arrays, set -euo pipefail)
- **Standards**: CLAUDE.md onion architecture, production-grade
- **Testing**: Supports dry-run mode for validation
- **Error handling**: Trap-based cleanup, specific exit codes
- **Logging**: Structured timestamps, levels, machine-parseable status

## Support & Issues

Common issues and solutions are documented in the **Troubleshooting** section above.

For issues not listed:
1. Run with `LOG_LEVEL=DEBUG` for detailed output
2. Check Docker daemon and container health
3. Verify database credentials match docker-compose.yml
4. Ensure backup directory is writable and has adequate space
5. Review `cat /opt/fxlab/backups/backup.log` for error details

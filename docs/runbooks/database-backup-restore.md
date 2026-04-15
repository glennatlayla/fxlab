# Database Backup and Restore Procedures

## Overview

This runbook covers PostgreSQL backup and restore procedures for the FXLab
production database. It documents scheduled backup configuration, manual backup
procedures, and full restore steps.

The FXLab database contains execution state (orders, fills, positions),
governance records (overrides, approvals, audit events), risk events, and
configuration data. Data loss can result in incorrect position tracking,
missed risk limits, and regulatory audit gaps. Backups are critical.

## Prerequisites

- PostgreSQL 15+ client tools installed (`pg_basebackup`, `pg_dump`, `pg_restore`).
- Network access to the production PostgreSQL instance.
- Credentials stored in a secure password file (`~/.pgpass`) or provided via
  `PGPASSWORD` environment variable.
- Sufficient disk space for base backups (estimate: 2x current database size).
- WAL archiving target accessible (S3 bucket, NFS share, or local directory).

## 1. Backup Strategy

### 1.1 Scheduled Backups

FXLab uses a two-tier backup strategy:

| Tier | Method | Frequency | Retention | Purpose |
|------|--------|-----------|-----------|---------|
| Base backup | `pg_basebackup` | Daily at 02:00 UTC | 30 days | Full cluster snapshot |
| WAL archiving | Continuous | Real-time | 30 days | Point-in-time recovery |
| Logical backup | `pg_dump` | Weekly (Sunday 03:00 UTC) | 90 days | Schema portability |

### 1.2 WAL Archiving Configuration

Add to `postgresql.conf`:

```
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://fxlab-wal-archive/%f --sse AES256'
archive_timeout = 300
```

Verify WAL archiving is active:

```sql
SELECT * FROM pg_stat_archiver;
```

Expected: `archived_count` should be incrementing. If `last_failed_time` is
recent, check `archive_command` and S3 permissions.

### 1.3 Base Backup Script

Create `/opt/fxlab/scripts/backup-base.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/fxlab/base"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/fxlab_base_${TIMESTAMP}"

echo "[$(date -Iseconds)] Starting base backup to ${BACKUP_PATH}"

pg_basebackup \
  --host="${PGHOST}" \
  --port="${PGPORT:-5432}" \
  --username="${PGUSER}" \
  --pgdata="${BACKUP_PATH}" \
  --format=tar \
  --gzip \
  --checkpoint=fast \
  --progress \
  --verbose

echo "[$(date -Iseconds)] Base backup complete: $(du -sh "${BACKUP_PATH}" | cut -f1)"

# Upload to S3 for off-site storage
aws s3 sync "${BACKUP_PATH}" \
  "s3://fxlab-backups/base/${TIMESTAMP}/" \
  --sse AES256

# Prune local backups older than retention period
find "${BACKUP_DIR}" -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} +

echo "[$(date -Iseconds)] Cleanup complete. Backups older than ${RETENTION_DAYS} days removed."
```

Schedule via cron:

```
0 2 * * * /opt/fxlab/scripts/backup-base.sh >> /var/log/fxlab/backup-base.log 2>&1
```

### 1.4 Logical Backup Script

Create `/opt/fxlab/scripts/backup-logical.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/fxlab/logical"
RETENTION_DAYS=90
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="${BACKUP_DIR}/fxlab_dump_${TIMESTAMP}.sql.gz"

echo "[$(date -Iseconds)] Starting logical backup"

pg_dump \
  --host="${PGHOST}" \
  --port="${PGPORT:-5432}" \
  --username="${PGUSER}" \
  --dbname=fxlab \
  --format=custom \
  --compress=9 \
  --verbose \
  --file="${DUMP_FILE}"

echo "[$(date -Iseconds)] Logical backup complete: $(du -sh "${DUMP_FILE}" | cut -f1)"

aws s3 cp "${DUMP_FILE}" \
  "s3://fxlab-backups/logical/${TIMESTAMP}.sql.gz" \
  --sse AES256

find "${BACKUP_DIR}" -maxdepth 1 -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date -Iseconds)] Cleanup complete."
```

Schedule via cron:

```
0 3 * * 0 /opt/fxlab/scripts/backup-logical.sh >> /var/log/fxlab/backup-logical.log 2>&1
```

## 2. Backup Verification

Backups that are not tested are not backups. Verify monthly.

### 2.1 Verify Base Backup Integrity

```bash
# List available base backups
aws s3 ls s3://fxlab-backups/base/ --recursive | tail -5

# Download the latest backup
LATEST=$(aws s3 ls s3://fxlab-backups/base/ | sort | tail -1 | awk '{print $NF}')
aws s3 sync "s3://fxlab-backups/base/${LATEST}" /tmp/fxlab-restore-test/

# Start a temporary PostgreSQL instance
pg_ctl -D /tmp/fxlab-restore-test init
pg_ctl -D /tmp/fxlab-restore-test -l /tmp/fxlab-restore-test.log start -o "-p 5555"

# Verify tables exist and row counts match production
psql -p 5555 -d fxlab -c "SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY tablename;"

# Clean up
pg_ctl -D /tmp/fxlab-restore-test stop
rm -rf /tmp/fxlab-restore-test
```

### 2.2 Verify Logical Backup

```bash
DUMP_FILE="/tmp/fxlab_verify.sql.gz"
aws s3 cp "s3://fxlab-backups/logical/$(aws s3 ls s3://fxlab-backups/logical/ | sort | tail -1 | awk '{print $NF}')" "${DUMP_FILE}"

createdb -p 5555 fxlab_verify
pg_restore --dbname=fxlab_verify --port=5555 --verbose "${DUMP_FILE}"

psql -p 5555 -d fxlab_verify -c "SELECT count(*) FROM orders;"
psql -p 5555 -d fxlab_verify -c "SELECT count(*) FROM positions;"

dropdb -p 5555 fxlab_verify
rm "${DUMP_FILE}"
```

## 3. Full Restore Procedure

Use this when the database is unrecoverable and must be rebuilt from a base
backup plus WAL replay.

### 3.1 Pre-Restore Checklist

1. Confirm the database is truly unrecoverable (not just a connection issue).
2. Notify the team via the incident channel.
3. Scale FXLab API to 0 replicas: `kubectl scale deployment/fxlab-api -n fxlab --replicas=0`
4. Activate kill switch if any live trading deployments are active.
5. Identify the target recovery point (latest backup or specific timestamp for PITR).
6. Ensure sufficient disk space on the restore target (2x backup size).

### 3.2 Restore Steps

```bash
# 1. Stop PostgreSQL
sudo systemctl stop postgresql

# 2. Move corrupted data directory aside (do NOT delete yet)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
sudo mv /var/lib/postgresql/15/main /var/lib/postgresql/15/main_corrupted_${TIMESTAMP}

# 3. Download the target base backup
BACKUP_TIMESTAMP="20260410_020000"  # Adjust to desired backup
aws s3 sync "s3://fxlab-backups/base/${BACKUP_TIMESTAMP}/" /var/lib/postgresql/15/main/

# 4. Set correct ownership
sudo chown -R postgres:postgres /var/lib/postgresql/15/main

# 5. Download WAL files for replay
aws s3 sync s3://fxlab-wal-archive/ /var/lib/postgresql/15/wal_restore/

# 6. Configure recovery
cat > /var/lib/postgresql/15/main/postgresql.auto.conf << 'EOF'
restore_command = 'cp /var/lib/postgresql/15/wal_restore/%f %p'
recovery_target = 'immediate'
EOF

# 7. Create recovery signal file
touch /var/lib/postgresql/15/main/recovery.signal

# 8. Start PostgreSQL — it will replay WAL files
sudo systemctl start postgresql

# 9. Monitor recovery progress
sudo journalctl -u postgresql -f
# Look for: "database system is ready to accept connections"
```

### 3.3 Post-Restore Verification

```sql
-- Verify table counts match expected values
SELECT schemaname, tablename, n_live_tup
FROM pg_stat_user_tables
ORDER BY tablename;

-- Verify most recent data timestamp
SELECT max(created_at) FROM orders;
SELECT max(created_at) FROM positions;
SELECT max(created_at) FROM audit_events;

-- Verify no corruption
SELECT datname, checksum_failures FROM pg_stat_database WHERE datname = 'fxlab';
```

### 3.4 Resume Service

```bash
# 1. Run pending migrations (if any)
alembic upgrade head

# 2. Scale API back up
kubectl scale deployment/fxlab-api -n fxlab --replicas=2

# 3. Verify health
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/health
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/ready

# 4. Verify data integrity via reconciliation
# Trigger a manual reconciliation run for each active deployment.

# 5. Notify team that service is restored
```

## 4. Monitoring and Alerts

Configure alerts for backup failures:

| Alert | Condition | Severity |
|-------|-----------|----------|
| Backup missed | No base backup in last 26 hours | Critical |
| WAL archiving stalled | `last_archived_time` > 10 minutes ago | Warning |
| Backup verification failed | Monthly verification script exit code != 0 | Critical |
| Disk space low | Backup volume < 20% free | Warning |

## 5. Escalation

| Situation | Action |
|-----------|--------|
| Backup script fails | Check logs, fix, re-run manually. If persistent, escalate to DBA. |
| WAL archiving fails | Check S3 permissions, disk space, `archive_command`. Escalate if unresolved in 30 min. |
| Restore fails | Do NOT retry blindly. Escalate to DBA with error logs. |
| Data corruption detected | Activate kill switch. Escalate immediately. Use PITR (see point-in-time-recovery.md). |

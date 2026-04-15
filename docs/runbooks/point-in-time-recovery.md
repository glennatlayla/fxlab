# Point-in-Time Recovery (PITR) Procedure

## Overview

Point-in-time recovery restores the PostgreSQL database to a specific moment,
discarding all changes after that timestamp. Use PITR when you need to recover
from data corruption, accidental deletions, or bad migrations — situations
where a full restore to the latest state would re-introduce the problem.

PITR requires both a base backup and continuous WAL archiving to be configured.
See `database-backup-restore.md` for backup infrastructure setup.

## When to Use PITR vs Full Restore

| Scenario | Recommended approach |
|----------|---------------------|
| Hardware failure, database unreachable | Full restore (latest backup + all WALs) |
| Accidental `DELETE` or `DROP TABLE` | PITR to moment before the destructive operation |
| Bad migration corrupted data | PITR to moment before migration ran |
| Data corruption discovered hours later | PITR to last known-good timestamp |
| Complete database loss (disk gone) | Full restore (latest backup + all WALs) |

The key distinction: full restore replays ALL available WAL to reach the latest
state. PITR replays WAL only up to a specific timestamp, then stops.

## Prerequisites

1. A base backup older than the target recovery timestamp exists.
2. All WAL segments between the base backup and target timestamp are archived.
3. PostgreSQL is stopped (or the target is a separate instance).
4. FXLab API is scaled to 0 replicas (no active connections).
5. Kill switch is activated for any live trading deployments.
6. Team is notified via incident channel.

## Procedure

### Step 1: Identify the Recovery Target Timestamp

Determine the exact timestamp to recover to. This should be the moment
immediately before the destructive event. Use UTC.

```bash
# Example: bad migration ran at 2026-04-10 14:32:15 UTC
# Recover to 1 minute before: 2026-04-10 14:31:00 UTC
RECOVERY_TARGET="2026-04-10 14:31:00+00"
```

If unsure of the exact timestamp, check:

```sql
-- Check recent migration history (if DB is still accessible)
SELECT * FROM alembic_version;

-- Check audit events around the suspected time
SELECT id, event_type, created_at
FROM audit_events
WHERE created_at BETWEEN '2026-04-10 14:00:00' AND '2026-04-10 15:00:00'
ORDER BY created_at DESC;
```

### Step 2: Scale Down the Application

```bash
# Scale API to zero — no new requests
kubectl scale deployment/fxlab-api -n fxlab --replicas=0

# Verify no active connections
psql -h ${PGHOST} -U ${PGUSER} -d fxlab -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname = 'fxlab' AND state != 'idle';"
# Must be 0 (or only your connection)

# Terminate remaining connections
psql -h ${PGHOST} -U ${PGUSER} -d fxlab -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'fxlab' AND pid != pg_backend_pid();"
```

### Step 3: Stop PostgreSQL

```bash
sudo systemctl stop postgresql
```

### Step 4: Preserve the Current Data Directory

Never delete the current data directory until recovery is verified.

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
sudo mv /var/lib/postgresql/15/main /var/lib/postgresql/15/main_pre_pitr_${TIMESTAMP}
```

### Step 5: Restore the Base Backup

Choose a base backup that is older than the target recovery timestamp.

```bash
# List available backups
aws s3 ls s3://fxlab-backups/base/

# Download the appropriate backup (must be OLDER than RECOVERY_TARGET)
BACKUP_DATE="20260410_020000"
aws s3 sync "s3://fxlab-backups/base/${BACKUP_DATE}/" /var/lib/postgresql/15/main/

# If the backup is tar.gz format:
mkdir -p /var/lib/postgresql/15/main
tar xzf /tmp/backup/base.tar.gz -C /var/lib/postgresql/15/main/

sudo chown -R postgres:postgres /var/lib/postgresql/15/main
```

### Step 6: Download WAL Files

Download all WAL segments from the base backup timestamp to the recovery target.

```bash
mkdir -p /var/lib/postgresql/15/wal_restore
aws s3 sync s3://fxlab-wal-archive/ /var/lib/postgresql/15/wal_restore/
sudo chown -R postgres:postgres /var/lib/postgresql/15/wal_restore
```

### Step 7: Configure recovery_target_time

```bash
cat > /var/lib/postgresql/15/main/postgresql.auto.conf << EOF
restore_command = 'cp /var/lib/postgresql/15/wal_restore/%f %p'
recovery_target_time = '${RECOVERY_TARGET}'
recovery_target_action = 'pause'
EOF

# Create recovery signal file
touch /var/lib/postgresql/15/main/recovery.signal
sudo chown postgres:postgres /var/lib/postgresql/15/main/recovery.signal
```

`recovery_target_action = 'pause'` causes PostgreSQL to pause at the recovery
target so you can verify the data before accepting. This is safer than
`'promote'` which immediately makes the server read-write.

### Step 8: Start PostgreSQL and Monitor Recovery

```bash
sudo systemctl start postgresql

# Monitor WAL replay progress
sudo journalctl -u postgresql -f
# Look for:
#   "recovery stopping before commit of transaction ..."
#   "recovery has paused"
#   "database system is ready to accept read-only connections"
```

### Step 9: Verify Recovery State

While the server is paused in recovery (read-only), verify the data:

```sql
-- Connect (read-only queries only)
psql -h localhost -U ${PGUSER} -d fxlab

-- Check: is the data at the expected state?
SELECT max(created_at) FROM orders;
SELECT max(created_at) FROM audit_events;
SELECT count(*) FROM orders;
SELECT count(*) FROM positions;

-- Check: is the problematic data absent?
-- (e.g., verify the bad migration's changes are not present)
SELECT * FROM alembic_version;
```

### Step 10: Accept or Reject Recovery

If the data looks correct, promote the server to accept writes:

```sql
SELECT pg_wal_replay_resume();
```

If the data does NOT look correct, stop PostgreSQL, adjust the
`recovery_target_time`, and try again from Step 7.

### Step 11: Post-Recovery Actions

```bash
# 1. Run any migrations needed to bring schema up to date
#    (only if you recovered to a state BEFORE a good migration)
alembic upgrade head

# 2. Scale the API back up
kubectl scale deployment/fxlab-api -n fxlab --replicas=2

# 3. Verify health endpoints
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/health
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/ready

# 4. Take a fresh base backup (the old backup chain is now stale)
/opt/fxlab/scripts/backup-base.sh

# 5. Notify team of recovery completion with:
#    - Recovery target timestamp
#    - Data verification results
#    - Any data loss window (time between recovery target and incident)
```

## Data Loss Assessment

After PITR, calculate the data loss window:

```
Data loss window = (incident timestamp) - (recovery target timestamp)
```

Any orders, fills, positions, or audit events created in this window are lost.
Document this in the incident report and determine if any manual corrections
are needed (e.g., reconcile position state with broker).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "could not find WAL segment" | Missing WAL file. Check S3 archive. Recovery cannot proceed past the gap. Choose a later base backup or an earlier recovery target. |
| "recovery target time is before end of backup" | The recovery target is too early for this base backup. Use an older base backup. |
| Server promoted but data is wrong | You accepted too early. Stop PostgreSQL, restore from backup, and repeat PITR with corrected timestamp. This is why we preserve the pre-PITR data directory. |
| Paused but can't query | Some queries may fail during paused recovery. Use only simple SELECTs. |

## Escalation

| Situation | Action |
|-----------|--------|
| Cannot determine correct recovery timestamp | Escalate to team lead. Review audit logs, application logs, and broker records. |
| WAL gap prevents reaching target timestamp | Escalate to DBA. May need to accept data loss or use logical backup. |
| Recovery succeeds but data is inconsistent | Trigger full reconciliation. Compare positions with broker. Escalate if discrepancies found. |

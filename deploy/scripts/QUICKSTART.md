# FXLab Database Backup — Quick Start (5 minutes)

Get automated daily PostgreSQL backups running in 5 minutes.

## TL;DR (Copy-paste ready)

```bash
# 1. Create backup directory
sudo mkdir -p /opt/fxlab/backups
sudo chmod 700 /opt/fxlab/backups

# 2. Install cron job (daily at 2 AM)
(sudo crontab -l 2>/dev/null; echo "0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup.log 2>&1") | \
  sudo crontab -

# 3. Verify
sudo crontab -l | grep backup-db

# 4. Test (optional, but recommended)
sudo /opt/fxlab/deploy/scripts/backup-db.sh

# 5. Check results
ls -lh /opt/fxlab/backups/
tail -20 /opt/fxlab/backups/backup.log
```

Done. Backups run automatically every day at 2 AM.

---

## What Just Happened?

The script `backup-db.sh` has been installed with **automatic daily backups**:

- **When**: Every day at 2:00 AM (UTC)
- **What**: Full PostgreSQL database dump (compressed with gzip)
- **Where**: `/opt/fxlab/backups/backup-YYYYMMDDTHHMMSS.sql.gz`
- **How long**: Keep 30 days of backups (auto-delete older ones)
- **Restore**: One-liner command provided in log file

---

## Check Your Backup

### View latest backup

```bash
ls -lh /opt/fxlab/backups/
```

Expected output:
```
-rw-r--r-- 1 root root 98M Apr 14 02:00 backup-2026-04-14T02:00:00Z.sql.gz
```

### View backup log

```bash
tail /opt/fxlab/backups/backup.log
```

Expected output:
```
2026-04-14T02:00:01Z [INFO] Backup started
2026-04-14T02:00:01Z [INFO] Pre-flight checks passed
2026-04-14T02:00:05Z [INFO] Dump complete: 245 MB
2026-04-14T02:00:13Z [INFO] Compression complete: 98 MB
2026-04-14T02:00:13Z [INFO] Backup verification: VALID
2026-04-14T02:00:13Z [STATUS] success: backup=backup-2026-04-14T02:00:00Z.sql.gz duration_ms=12345
```

---

## Restore Your Database

If you need to restore from backup:

```bash
# Find the backup file
BACKUP="/opt/fxlab/backups/backup-2026-04-14T02:00:00Z.sql.gz"

# Restore (one-liner)
gunzip -c "$BACKUP" | docker exec -i fxlab-postgres psql -U fxlab -d fxlab
```

That's it. The database is restored.

---

## Common Tasks

### Change backup time (e.g., 3 AM instead of 2 AM)

```bash
sudo crontab -e
# Change: 0 2 * * * ...
# To:     0 3 * * * ...
```

### Change retention (keep 60 days instead of 30)

```bash
sudo crontab -e
# Change: 0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh
# To:     0 2 * * * BACKUP_RETENTION_DAYS=60 /opt/fxlab/deploy/scripts/backup-db.sh
```

### Backup to different location

```bash
sudo crontab -e
# Change: 0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh
# To:     0 2 * * * BACKUP_DIR=/mnt/archive /opt/fxlab/deploy/scripts/backup-db.sh
```

### Run backup manually (anytime)

```bash
sudo /opt/fxlab/deploy/scripts/backup-db.sh
```

### Test backup without creating files (dry-run)

```bash
DRY_RUN=1 /opt/fxlab/deploy/scripts/backup-db.sh
```

---

## Monitoring (Optional)

### Email on backup failure

```bash
sudo crontab -e
# Add this line before the backup job:
MAILTO=your-email@example.com
```

### Check if today's backup succeeded

```bash
tail -1 /opt/fxlab/backups/backup.log | grep success && echo "OK" || echo "FAILED"
```

### Get backup completion time

```bash
tail -1 /opt/fxlab/backups/backup.log | grep -oP 'duration_ms=\K[0-9]+' | awk '{print $1 " ms"}'
```

---

## Troubleshooting

### Backup not running

Check if cron job is installed:
```bash
sudo crontab -l | grep backup-db
```

If empty, re-run the TL;DR installation above.

### Backup failed

Check the log:
```bash
tail -50 /opt/fxlab/backups/backup.log
```

Most common issues:
- **Docker not running**: `sudo systemctl start docker`
- **Disk full**: `df -h /opt/fxlab/backups`
- **Container unhealthy**: `docker ps | grep fxlab-postgres`

### Can't restore

Make sure the backup file exists and is readable:
```bash
ls -lh /opt/fxlab/backups/backup-*.sql.gz
```

---

## Advanced Setup (Optional)

For more control, see:
- **Complete configuration**: `INSTALLATION.md`
- **Detailed backup operations**: `README-backup.md`
- **More cron examples**: `crontab-examples.txt`
- **systemd timer** (instead of cron): `../systemd/fxlab-backup-db.timer`

---

## One More Thing

**Test your restore path now, while the database is healthy:**

```bash
# Pick a backup file
BACKUP="/opt/fxlab/backups/backup-2026-04-14T02:00:00Z.sql.gz"

# Verify it's restorable (lists contents, doesn't restore)
gunzip -c "$BACKUP" | docker exec -i fxlab-postgres pg_restore --list - | head -10
```

If this works, you can confidently restore from this backup anytime. ✓

---

**You're done.** Backups are running. Go check the logs tomorrow morning.

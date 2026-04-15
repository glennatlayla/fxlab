# FXLab Backup Script Installation Guide

Complete setup instructions for deploying the `backup-db.sh` production backup system.

## Prerequisites

- FXLab platform running with PostgreSQL 15 in Docker
- Bash 4.0 or later
- Docker CLI with access to `fxlab-postgres` container
- Disk space for backups (recommend 2–3x current database size)
- User account with Docker access or sudo privileges

## Installation Steps

### 1. Copy backup script

```bash
# If not already present:
cp /path/to/backup-db.sh /opt/fxlab/deploy/scripts/

# Make executable
chmod +x /opt/fxlab/deploy/scripts/backup-db.sh
```

### 2. Create backup directory

```bash
# Create with appropriate permissions
sudo mkdir -p /opt/fxlab/backups
sudo chown root:root /opt/fxlab/backups
sudo chmod 700 /opt/fxlab/backups

# Verify
ls -ld /opt/fxlab/backups
```

### 3. Test the script

```bash
# Dry-run test (no files created)
DRY_RUN=1 /opt/fxlab/deploy/scripts/backup-db.sh

# Expected output:
# 2026-04-14T03:04:53Z [INFO] Backup started
# 2026-04-14T03:04:53Z [INFO] Running pre-flight checks...
# ... (may fail if Docker not running, which is ok)
```

### 4. Verify with running Docker

If you have Docker running:

```bash
# Full test (creates actual backup)
/opt/fxlab/deploy/scripts/backup-db.sh

# Check output
ls -lh /opt/fxlab/backups/
```

## Deployment Options

Choose ONE of the following scheduling methods.

### Option A: Cron (traditional, widely supported)

#### Install via crontab

```bash
# Edit crontab for the user/root running backups
sudo crontab -e

# Add this line for daily 2 AM backup:
0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup.log 2>&1
```

#### Verify cron installation

```bash
# Check if job is scheduled
sudo crontab -l | grep backup-db

# Monitor cron log (system-dependent)
tail -f /var/log/syslog | grep backup-db
# or
tail -f /var/log/cron
```

#### Customize backup frequency

Edit `/var/spool/cron/crontabs/root` or use `crontab -e`:

```bash
# Multiple frequencies for comprehensive backup
# Daily (keep 7 days) at 2 AM
0 2 * * * BACKUP_RETENTION_DAYS=7 /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup-daily.log 2>&1

# Weekly (keep 30 days) on Sunday at 3 AM
0 3 * * 0 BACKUP_RETENTION_DAYS=30 /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup-weekly.log 2>&1

# Monthly (keep 90 days) on 1st of month at 4 AM
0 4 1 * * BACKUP_RETENTION_DAYS=90 /opt/fxlab/deploy/scripts/backup-db.sh >> /var/log/fxlab-backup-monthly.log 2>&1
```

#### Send cron email notifications

By default, cron mails output to the system user. Configure:

```bash
# Set MAILTO for cron job notifications
MAILTO=ops@example.com
0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh
```

---

### Option B: systemd Timer (modern, recommended for systemd systems)

#### Install service and timer units

```bash
# Copy systemd unit files
sudo cp /opt/fxlab/deploy/systemd/fxlab-backup-db.service \
         /etc/systemd/system/

sudo cp /opt/fxlab/deploy/systemd/fxlab-backup-db.timer \
         /etc/systemd/system/

# Reload systemd configuration
sudo systemctl daemon-reload
```

#### Enable and start timer

```bash
# Enable timer to start on boot
sudo systemctl enable fxlab-backup-db.timer

# Start the timer immediately
sudo systemctl start fxlab-backup-db.timer

# Verify timer is active
sudo systemctl status fxlab-backup-db.timer
```

#### Monitor timer and service

```bash
# Check next scheduled run
sudo systemctl list-timers fxlab-backup-db.timer

# View recent runs
sudo systemctl list-unit-files --all | grep fxlab-backup

# Check service logs
sudo journalctl -u fxlab-backup-db.service -n 50
# or for follow mode:
sudo journalctl -u fxlab-backup-db.service -f
```

#### Customize timer schedule

Edit `/etc/systemd/system/fxlab-backup-db.timer`:

```ini
[Timer]
# Monday-Friday at 2 AM
OnCalendar=Mon-Fri *-*-* 02:00:00

# Multiple times per day
OnCalendar=*-*-* 02:00:00
OnCalendar=*-*-* 14:00:00

# Restart systemd after editing
sudo systemctl daemon-reload
sudo systemctl restart fxlab-backup-db.timer
```

#### Common timer schedules

```ini
# Daily at 2 AM
OnCalendar=*-*-* 02:00:00

# Every 6 hours
OnCalendar=*-*-* 00,06,12,18:00:00

# Twice daily (2 AM and 2 PM)
OnCalendar=*-*-* 02:00:00
OnCalendar=*-*-* 14:00:00

# Weekly on Monday at 3 AM
OnCalendar=Mon *-*-* 03:00:00

# Monthly on 1st at 4 AM
OnCalendar=*-*-01 04:00:00

# Every minute (for testing)
OnCalendar=*-*-* *:*:00
```

#### Manual backup with systemd

```bash
# Run backup immediately (outside of schedule)
sudo systemctl start fxlab-backup-db.service

# Check if it's running
sudo systemctl is-active fxlab-backup-db.service

# View output
sudo journalctl -u fxlab-backup-db.service
```

---

### Option C: Manual Execution (for ad-hoc backups)

```bash
# Single backup
/opt/fxlab/deploy/scripts/backup-db.sh

# With custom settings
BACKUP_DIR=/mnt/archive BACKUP_RETENTION_DAYS=60 \
  /opt/fxlab/deploy/scripts/backup-db.sh
```

---

## Post-Installation Verification

### 1. Verify script execution

```bash
# Check that backup directory has recent backups
ls -lh /opt/fxlab/backups/

# Should show files like:
# -rw-r--r-- 1 root root 98M Apr 14 02:00 backup-2026-04-14T02:00:00Z.sql.gz
```

### 2. Check backup logs

```bash
# View backup log
tail -20 /opt/fxlab/backups/backup.log

# Should end with [STATUS] line:
# 2026-04-14T02:00:15Z [STATUS] success: backup=backup-2026-04-14T02:00:00Z.sql.gz duration_ms=12345
```

### 3. Test restore capability

```bash
# List available backups
ls /opt/fxlab/backups/backup-*.sql.gz

# Verify backup integrity (lists contents, doesn't restore)
BACKUP="/opt/fxlab/backups/backup-2026-04-14T02:00:00Z.sql.gz"
gunzip -c "$BACKUP" | docker exec -i fxlab-postgres pg_restore --list - | head -5

# Should show SQL object list, not errors
```

### 4. Configure monitoring/alerting

Add to your monitoring system:

```bash
#!/bin/bash
# Check if last backup succeeded

LOG_FILE="/opt/fxlab/backups/backup.log"
LAST_STATUS=$(tail -1 "$LOG_FILE")

if echo "$LAST_STATUS" | grep -q "success"; then
    echo "OK: Backup successful"
    exit 0
else
    echo "CRITICAL: Backup failed"
    exit 2
fi
```

## Troubleshooting Installation

### Backup directory permission denied

```bash
# Ensure directory is writable
sudo ls -ld /opt/fxlab/backups

# Fix permissions
sudo chmod 700 /opt/fxlab/backups
sudo chown root:root /opt/fxlab/backups
```

### Docker socket permission denied

```bash
# Add user to docker group (if using non-root cron)
sudo usermod -aG docker $USER

# Or run cron as root (more secure):
sudo crontab -e
```

### systemd timer not running

```bash
# Reload systemd
sudo systemctl daemon-reload

# Check for errors
sudo systemctl status fxlab-backup-db.timer

# Check timer definition
sudo systemctl cat fxlab-backup-db.timer
```

### Backup file not created

```bash
# Test script directly
sudo /opt/fxlab/deploy/scripts/backup-db.sh

# Check for errors
LOG_LEVEL=DEBUG sudo /opt/fxlab/deploy/scripts/backup-db.sh
```

## Security Configuration

### Restrict backup directory

```bash
# Backups contain full database data
sudo chmod 700 /opt/fxlab/backups
sudo chown root:root /opt/fxlab/backups

# Only owner can read
sudo chmod 600 /opt/fxlab/backups/backup-*.sql.gz
```

### Encrypt backups (optional)

Add GPG encryption to the backup script:

```bash
# Generate encryption key (one-time)
gpg --batch --gen-key <<EOF
%echo Generating FXLab backup encryption key
Key-Type: RSA
Key-Length: 4096
Name-Real: FXLab Backups
Name-Email: backups@example.com
%no-ask-passphrase
%pubring /etc/fxlab/backup-public.gpg
%secring /etc/fxlab/backup-secret.gpg
EOF

# Modify backup script to encrypt (see backup-db.sh for details)
```

### Audit backup access

```bash
# Monitor who accesses backups
sudo auditctl -w /opt/fxlab/backups -p wa -k fxlab_backup_access

# View audit logs
sudo ausearch -k fxlab_backup_access
```

## Maintenance

### Monthly verification

```bash
# Check backup file sizes
du -h /opt/fxlab/backups/

# Verify oldest backups are within retention
find /opt/fxlab/backups -name "*.sql.gz" -printf '%T@ %p\n' | \
  sort -k1 -n | tail -5
```

### Update retention policy

Edit crontab or systemd timer:

```bash
# Keep 60 days instead of 30
sudo crontab -e
# Change BACKUP_RETENTION_DAYS=30 to BACKUP_RETENTION_DAYS=60
```

### Archive old backups

Before rotating out of retention:

```bash
# Copy to archive storage
BACKUP_DIR=/opt/fxlab/backups
ARCHIVE_DIR=/mnt/archive/fxlab-backups

find "$BACKUP_DIR" -name "backup-*.sql.gz" -mtime +30 \
  -exec cp {} "$ARCHIVE_DIR" \;
```

## Support & Monitoring

### Cron monitoring

```bash
# Ensure cron sends mail on failure
MAILTO=ops@example.com
0 2 * * * /opt/fxlab/deploy/scripts/backup-db.sh
```

### systemd monitoring

```bash
# View recent executions
sudo systemctl list-unit-files --all | grep fxlab-backup

# Set up log notification
sudo journalctl -u fxlab-backup-db.service --follow
```

### External monitoring

Send status to monitoring system:

```bash
#!/bin/bash
# Push backup status to Prometheus/Datadog/etc.

STATUS_LINE=$(tail -1 /opt/fxlab/backups/backup.log)

if echo "$STATUS_LINE" | grep -q "success"; then
    DURATION=$(echo "$STATUS_LINE" | grep -oP 'duration_ms=\K[0-9]+')
    # Send metric
    curl -X POST http://monitoring:9091/metrics/job/fxlab_backup \
      -d "fxlab_backup_duration_ms $DURATION"
fi
```

## Rollback / Uninstallation

To disable backups:

### Cron

```bash
# Remove from crontab
sudo crontab -e
# Delete the backup-db.sh line
```

### systemd

```bash
# Disable timer
sudo systemctl disable fxlab-backup-db.timer
sudo systemctl stop fxlab-backup-db.timer

# Remove units
sudo rm /etc/systemd/system/fxlab-backup-db.*
sudo systemctl daemon-reload
```

To preserve backups:

```bash
# Archive backups before cleanup
tar czf /mnt/archive/fxlab-backups-$(date +%Y%m%d).tar.gz \
  /opt/fxlab/backups/

# Then remove
rm -rf /opt/fxlab/backups/*
```

## Next Steps

1. **Install** following Option A (cron) or Option B (systemd)
2. **Verify** installation with post-installation checks
3. **Test restore** to ensure backups are usable
4. **Monitor** first backup cycle in logs
5. **Document** local configuration in runbook
6. **Archive** old backups regularly per compliance requirements

For detailed backup management and restore procedures, see `README-backup.md`.

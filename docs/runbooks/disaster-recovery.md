# Disaster Recovery Runbook

**Owner:** FXLab Platform Operations Team
**Last Updated:** 2026-04-13
**Classification:** Internal Use Only (High Sensitivity)

---

## TABLE OF CONTENTS

- [Emergency Contacts](#emergency-contacts)
- [Escalation Matrix](#escalation-matrix)
- [Communication Templates](#communication-templates)
- [Scenario 1: PostgreSQL Failure](#scenario-1-postgresql-failure)
- [Scenario 2: Redis Failure](#scenario-2-redis-failure)
- [Scenario 3: Broker API Outage](#scenario-3-broker-api-outage)
- [Scenario 4: Full Host Failure](#scenario-4-full-host-failure)
- [Scenario 5: Kill Switch State Corruption](#scenario-5-kill-switch-state-corruption)
- [Scenario 6: Data Breach / Unauthorized Access](#scenario-6-data-breach--unauthorized-access)

---

## EMERGENCY CONTACTS

**CRITICAL: Update these names, numbers, and Slack handles in your ops runbook.**

| Role | Name | Phone | Slack | On-Call Rotation |
|------|------|-------|-------|------------------|
| **On-Call Engineer** | TBD | +1 (XXX) XXX-XXXX | @on-call | PagerDuty |
| **Infrastructure Lead** | TBD | +1 (XXX) XXX-XXXX | @infra-lead | PagerDuty |
| **Trading Operations** | TBD | +1 (XXX) XXX-XXXX | @trading-ops | Business hours |
| **CTO / Emergency Escalation** | TBD | +1 (XXX) XXX-XXXX | @cto | On-demand |

**Escalation Bell Ringer (if Slack down):** Conference bridge: TBD, Passcode: TBD

---

## ESCALATION MATRIX

| Severity | Scenario | Response Time | Activation | Escalate To |
|----------|----------|----------------|------------|------------|
| **P1 — Critical** | Any service total loss during market hours | Immediate (page) | All hands on deck | CTO + Trading Ops (call) |
| **P1 — Critical** | Data breach / credential exposure detected | Immediate (page) | Security incident workflow | CTO + CISO (if exists) |
| **P2 — Major** | Single service down, workaround exists | 15 minutes | Page on-call | Team lead (Slack) |
| **P3 — Minor** | Partial degradation, market closed | 1 hour | Ticket + Slack thread | Team lead (Slack) |

**Decision rule:** If ANY live orders cannot be submitted or cancelled during market hours, treat as P1.

---

## COMMUNICATION TEMPLATES

### Template 1: Incident Open

```
[INCIDENT] Status: OPEN | Severity: {P1|P2|P3} | Component: {component}

Description:
  - What happened: ...
  - Impact: {live orders|paper orders|rate limiting|other}
  - Detected at: {timestamp}
  - Estimated time to recovery: {estimate}

Current status:
  - [x] Kill switch activated (if applicable)
  - [ ] Root cause identified
  - [ ] Remediation in progress
  - [ ] Testing / verification

On-call: {name}
Next update: every 15 minutes

#fxlab-incidents
```

### Template 2: Incident Update

```
[INCIDENT] Update | {component} | {timestamp} UTC

Progress:
  - Root cause: {brief description or TBD}
  - Remediation: {action taken}
  - ETA to resolution: {new estimate}

Next: {what happens next}

#fxlab-incidents
```

### Template 3: Incident Resolved

```
[INCIDENT] RESOLVED | {component} | {resolution time} UTC

Root cause: ...

Timeline:
  - Detected: {time}
  - Severity called (P1/P2/P3): {time}
  - Remediation began: {time}
  - Service restored: {time}
  - Total duration: {HH:MM}

Next: Post-incident review scheduled for {date/time}.

#fxlab-incidents
```

---

# SCENARIO 1: PostgreSQL FAILURE

**Impact:** All API writes blocked. Order persistence broken. Kill switch state unavailable. Live orders cannot be tracked or cancelled.

**RTO:** < 5 minutes (container restart) | < 30 minutes (backup restore)

---

## 1.1 Detection

### Health Check Failure
```bash
# Docker health check failed (visible in `docker ps`)
docker ps | grep fxlab-postgres
# Expected: "healthy"; if "unhealthy", proceed to Scenario 1.2

# Container logs show database errors
docker logs fxlab-postgres | tail -50
# Look for: "FATAL: could not open file", "terminating connection", "disk full"
```

### Manual Connectivity Test
```bash
# Test database connectivity from host
docker exec fxlab-api curl -f http://localhost:8000/health
# If status is degraded or "database": "error", PostgreSQL is down

# Detailed test with psql
docker exec fxlab-postgres pg_isready -U fxlab -d fxlab -h localhost
# Expected: "accepting connections"; if "rejecting", proceed to recovery
```

### Check API Logs for Database Errors
```bash
docker logs fxlab-api | grep -i "psycopg\|database\|connection" | tail -20
# Look for: "connection refused", "lost synchronization", "too many clients"
```

---

## 1.2 Impact Assessment

**BEFORE attempting recovery, check:**

1. **Can orders be submitted?**
   ```bash
   curl -X POST http://localhost:8000/live/submit \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"strategy_id": "test", "symbol": "AAPL", ...}'
   ```
   If 503 or 500 with "database error", PostgreSQL is the blocker.

2. **Are live orders at risk?**
   - Immediately activate global kill switch (Scenario 5 or Scenario 6 procedures).
   - DO NOT proceed with recovery while trading is active unless kill switch is already enabled.

3. **Check available backups:**
   ```bash
   ls -lh /opt/fxlab/backups/backup-*.sql.gz | tail -5
   # If no backups exist, recovery will require point-in-time restore
   ```

---

## 1.3 Recovery: Container Restart (< 5 min)

**Fastest path for transient failures (corrupted memory, temporary lock).**

```bash
# 1. Stop the PostgreSQL container
docker stop fxlab-postgres
# Wait 5 seconds for graceful shutdown
sleep 5

# 2. Verify it's stopped
docker ps | grep fxlab-postgres
# Should show no running container

# 3. Start it again
docker start fxlab-postgres

# 4. Wait for health check to pass (10–30 seconds)
docker exec fxlab-postgres pg_isready -U fxlab -d fxlab -h localhost
# Poll every 2 seconds until "accepting connections"
for i in {1..30}; do
  if docker exec fxlab-postgres pg_isready -U fxlab -d fxlab -h localhost | grep -q "accepting"; then
    echo "PostgreSQL is ready (attempt $i)"
    break
  fi
  sleep 2
done

# 5. Restart the API to clear any stale connection pooling
docker restart fxlab-api
docker exec fxlab-api pg_isready -U fxlab -d fxlab -h postgres
```

**If restart succeeds:** Jump to Scenario 1.5 Verification.

**If restart fails:** Proceed to Scenario 1.4 Backup Restore.

---

## 1.4 Recovery: Backup Restore (< 30 min)

**Used when container restart fails or persistent data corruption is detected.**

### 1.4.1 Identify the Backup

```bash
# List recent backups sorted by date (newest first)
ls -lht /opt/fxlab/backups/backup-*.sql.gz | head -5

# If no backups, attempt emergency snapshot recovery (see section 1.4.5)
# Otherwise, pick the most recent backup BEFORE the failure was detected
BACKUP_FILE="/opt/fxlab/backups/backup-2026-04-13T15:23:45Z.sql.gz"
```

### 1.4.2 Verify Backup Integrity

```bash
# Check that the file is readable and has content
ls -lh "$BACKUP_FILE"
# Expected: size > 1 MB (adjust for your database size)

# Test that gzip can decompress it (without writing to disk)
gunzip -t "$BACKUP_FILE" 2>&1
# If successful, output is empty; if corrupted, you'll see "unexpected end of file"
```

### 1.4.3 Stop the API (Prevent Concurrent Writes)

```bash
# The API must not write to the database while restore is in progress
docker stop fxlab-api
docker stop fxlab-keycloak  # Keycloak also shares the database
sleep 5
```

### 1.4.4 Perform the Restore

```bash
# Create a new database and restore from backup
# Step 1: Drop existing database (destructive—this is the recovery action)
docker exec -i fxlab-postgres dropdb -U fxlab --force fxlab 2>&1 || true

# Step 2: Create empty database
docker exec -i fxlab-postgres createdb -U fxlab fxlab

# Step 3: Restore from backup (this can take 5–15 minutes depending on size)
echo "Starting restore from $BACKUP_FILE..."
RESTORE_START_TIME=$(date +%s)

gunzip -c "$BACKUP_FILE" | docker exec -i fxlab-postgres psql -U fxlab -d fxlab \
  2>&1 | tee /tmp/restore.log

RESTORE_END_TIME=$(date +%s)
RESTORE_DURATION=$((RESTORE_END_TIME - RESTORE_START_TIME))
echo "Restore completed in ${RESTORE_DURATION} seconds"

# Check for errors in restore output
if grep -i "error\|fatal" /tmp/restore.log | grep -v "did not find" > /dev/null; then
  echo "WARNING: Restore had errors (see /tmp/restore.log). Inspect manually."
fi
```

### 1.4.5 Emergency Snapshot Recovery (If No Backups)

**Only if the backup file is missing or corrupted.**

```bash
# Check if Docker volume snapshot is available (depends on your storage layer)
# For AWS EBS: create snapshot, restore to new volume
# For local storage: check if filesystem-level backups exist

# This step requires cloud/infrastructure knowledge. If uncertain, escalate to infrastructure team.
# Do NOT proceed with data recovery unless you are confident in the snapshot integrity.
```

---

## 1.5 Post-Restore Verification

```bash
# 1. Verify database is accessible
docker exec fxlab-postgres psql -U fxlab -d fxlab -c "SELECT count(*) FROM pg_tables WHERE schemaname='public';"
# Should return a number > 0 (number of tables)

# 2. Check that critical tables have data
docker exec fxlab-postgres psql -U fxlab -d fxlab -c "SELECT count(*) FROM deployments;"
# Should match pre-failure count (verify against ops dashboard if available)

# 3. Restart API and Keycloak
docker start fxlab-keycloak
sleep 10  # Wait for Keycloak to initialize

docker start fxlab-api

# 4. Wait for health check
for i in {1..30}; do
  if curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "API is healthy (attempt $i)"
    break
  fi
  sleep 2
done

# 5. Verify connectivity from API
docker exec fxlab-api psql -U fxlab -d fxlab -h postgres -c "SELECT version();"
# Should return PostgreSQL version info
```

---

## 1.6 Verification: Full Health Check

```bash
# Run the API health endpoint
curl -X GET http://localhost:8000/health \
  -H "Content-Type: application/json" \
  -w "\nHTTP Status: %{http_code}\n"

# Expected response:
# {
#   "status": "ok",
#   "service": "fxlab-api",
#   "version": "0.1.0-bootstrap",
#   "components": {
#     "database": "ok"
#   }
# }

# Run the full readiness check
curl -X GET http://localhost:8000/ready \
  -H "Content-Type: application/json" \
  -w "\nHTTP Status: %{http_code}\n"

# Expected: "status": "ready" with all checks green
```

---

## 1.7 Post-Recovery Actions

1. **Reconciliation:** Run a full reconciliation to detect any order/position drift.
   ```bash
   # Get deployment ID
   DEPLOYMENT_ID="your-deployment-id"
   curl -X POST http://localhost:8000/reconciliation/${DEPLOYMENT_ID}/run \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"trigger": "manual", "reason": "post-postgresql-recovery"}'
   ```

2. **Audit the recovery:**
   ```bash
   # Check when the database came back online
   docker logs fxlab-postgres | grep -i "accepting\|ready" | tail -2

   # Check if the API missed any orders during downtime
   curl -X GET "http://localhost:8000/audit?start_time=<failure-time>&end_time=<recovery-time>" \
     -H "Authorization: Bearer $TOKEN"
   ```

3. **Update the backup:**
   ```bash
   # Take a fresh backup after recovery to establish a new baseline
   /opt/fxlab/deploy/scripts/backup-db.sh
   # Verify it succeeded (exit code 0)
   ```

4. **Notify stakeholders:**
   Use Template 3 (Incident Resolved) in [Communication Templates](#communication-templates).

---

# SCENARIO 2: REDIS FAILURE

**Impact:** Rate limiting degraded (requests may exceed limits). Session cache lost. Job queue unavailable (if applicable).
**Note:** Database is authoritative; Redis loss does NOT cause data loss, only performance degradation.

**RTO:** < 3 minutes (container restart) | < 10 minutes (AOF replay)

---

## 2.1 Detection

### Health Check Failure
```bash
# Check Redis health
docker ps | grep fxlab-redis

# Detailed health command
docker exec fxlab-redis redis-cli ping
# Expected: "PONG"; if "NOAUTH" or "Connection refused", Redis is down
```

### Check API Logs for Redis Errors
```bash
docker logs fxlab-api | grep -i "redis\|connection" | tail -20
# Look for: "Connection refused", "failed to connect", "timeout"

# Check if rate limiting is failing
docker logs fxlab-api | grep -i "rate.limit\|429" | head -5
```

### Check Redis Logs
```bash
docker logs fxlab-redis | tail -50
# Look for: "FATAL", "SLAVEOF", "master_link_down", "AOF fsync error"
```

---

## 2.2 Impact Assessment

**Check if rate limiting is still functional:**

```bash
# Test with a rapid request burst (should be rate-limited if Redis works)
for i in {1..100}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Authorization: Bearer $TOKEN" \
    http://localhost:8000/health
done | sort | uniq -c
# If you see 429 (Too Many Requests), rate limiting is working
# If all 200s, Redis may be down and rate limiting is degraded
```

**Impact on trading:**
- If rate limiting is down, malicious or misbehaving clients can overwhelm the API.
- Orders themselves will NOT be lost (they're in PostgreSQL), but submission may be slow.
- **Recommendation:** Activate kill switch on affected deployments until Redis is restored.

---

## 2.3 Recovery: Container Restart (< 3 min)

**Fastest path; AOF persistence will replay on restart.**

```bash
# 1. Stop Redis
docker stop fxlab-redis
sleep 3

# 2. Start Redis (AOF will replay automatically)
docker start fxlab-redis

# 3. Wait for it to be ready (AOF replay can take 10–30 seconds for large datasets)
for i in {1..60}; do
  if docker exec fxlab-redis redis-cli ping | grep -q "PONG"; then
    echo "Redis is ready (attempt $i)"
    break
  fi
  sleep 1
done

# 4. Verify memory usage and no errors
docker exec fxlab-redis redis-cli INFO memory | grep "used_memory_human"
# Should show memory usage; if it's very small, AOF may not have replayed correctly

# 5. Check AOF file size to confirm replay
docker exec fxlab-redis redis-cli LASTSAVE
# Should show a recent timestamp
```

---

## 2.4 Recovery: Manual AOF Replay (If Restart Fails)

**Use if Redis container starts but is empty (AOF replay failed).**

```bash
# 1. Locate the AOF file
docker exec fxlab-redis ls -lh /data/appendonly.aof

# 2. Check if the AOF file is corrupted
docker exec fxlab-redis redis-check-aof /data/appendonly.aof
# If it says "AOF file is valid", the file is OK but may not have replayed

# 3. If corrupted, attempt repair
docker exec fxlab-redis redis-check-aof --fix /data/appendonly.aof
# This will fix corruption by truncating the file at the last valid command

# 4. Restart Redis to replay the repaired AOF
docker restart fxlab-redis

# 5. Verify replay
docker exec fxlab-redis redis-cli DBSIZE
# Should be > 0
```

---

## 2.5 Fallback: Disable Redis (Memory-Only Rate Limiting)

**Emergency fallback if Redis cannot be recovered quickly (only for temporary use).**

```bash
# If Redis will not recover, the API can fall back to in-memory rate limiting
# (Note: this provides NO rate limiting across multiple API instances)

# 1. Check the API's login_tracker backend setting
docker exec fxlab-api env | grep LOGIN_TRACKER

# 2. If it's set to "redis", manually disable rate limiting (TEMPORARY ONLY):
# Edit .env (local) or restart with new environment variable:
docker stop fxlab-api
docker run -d --name fxlab-api-temp \
  -e LOGIN_TRACKER_BACKEND=memory \
  -e DATABASE_URL=postgresql://... \
  ... (other environment variables)
  fxlab:latest

# WARNING: This is NOT production-safe. Use only for < 30 minutes while recovering Redis.
# Clients can exceed rate limits by hitting different API instances.
```

---

## 2.6 Verification

```bash
# 1. Verify Redis is responding
docker exec fxlab-redis redis-cli ping
# Expected: "PONG"

# 2. Check memory is populated
docker exec fxlab-redis redis-cli DBSIZE
# Should be > 0

# 3. Check that API can connect
docker exec fxlab-api python -c "
import redis
r = redis.Redis(host='redis', port=6379, db=0)
print('Redis connection OK:', r.ping())
"

# 4. Test rate limiting
# (See section 2.2 for test procedure)
```

---

## 2.7 Post-Recovery Actions

1. **Restore normal configuration:**
   ```bash
   # If you used the memory-only fallback, restart API with original Redis config
   docker restart fxlab-api
   ```

2. **Verify AOF persistence:**
   ```bash
   # Check that AOF is enabled and syncing
   docker exec fxlab-redis redis-cli CONFIG GET appendonly
   # Expected: "appendonly" "yes"

   # Check AOF rewrite status (optional, but recommended for performance)
   docker exec fxlab-redis redis-cli BGREWRITEAOF
   echo "AOF rewrite scheduled (runs in background)"
   ```

3. **Monitor for data loss:**
   ```bash
   # Redis rate-limiting data is ephemeral; no action needed if lost.
   # However, check if any sessions were disrupted:
   docker logs fxlab-api | grep -i "session.*error\|auth.*fail" | wc -l
   # If count is high, users may need to re-authenticate
   ```

---

# SCENARIO 3: BROKER API OUTAGE

**Impact:** Live order submission fails. Existing orders cannot be monitored or cancelled. Paper/shadow orders succeed (they don't depend on broker).

**RTO:** Depends on broker recovery (typically 5–60 minutes).

**Special:** DO NOT automatically cancel existing orders—the broker may still be processing them.

---

## 3.1 Detection

### Broker Health Check Failure
```bash
# Check the API's broker health endpoint
curl -X GET http://localhost:8000/health \
  -H "Content-Type: application/json" | jq '.components'

# Look for broker adapter status in the response
# If broker shows "error" or is missing, proceed to 3.2

# Alternative: check per-broker status
curl -X GET http://localhost:8000/ready \
  -H "Content-Type: application/json" | jq '.checks'
# Should list each broker (alpaca, schwab, etc.) with OK/error status
```

### Order Submission Failure
```bash
# Try to submit a test order
curl -X POST http://localhost:8000/live/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": "test-deployment",
    "strategy_id": "test",
    "symbol": "SPY",
    "side": "BUY",
    "quantity": 1,
    "order_type": "LIMIT",
    "limit_price": 400.00
  }'

# If error message mentions "broker", "timeout", or "503", broker is unreachable
# Check the response for the specific broker adapter name
```

### Check Broker Status Page
```bash
# Alpaca status (if you use Alpaca)
# Visit: https://status.alpaca.markets/ (in your browser)

# Schwab/TD Ameritrade status
# Visit: https://www.schwab.com/system-status (in your browser)

# Log the status and timestamp for the incident report
```

### Check Broker API Logs in FXLab
```bash
docker logs fxlab-api | grep -i "alpaca\|schwab\|broker" | tail -30
# Look for: "connection timeout", "503", "401 unauthorized", "request rejected"

# Search for specific error codes
docker logs fxlab-api | grep -E "400|401|403|429|500|502|503" | tail -20
```

---

## 3.2 Impact Assessment

**Immediately determine scope:**

```bash
# 1. Are live deployments affected?
curl -X GET http://localhost:8000/deployments \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.mode == "live") | .id'

# 2. For each live deployment, check open orders
DEPLOYMENT_ID="your-live-deployment"
curl -X GET http://localhost:8000/live/${DEPLOYMENT_ID}/open-orders \
  -H "Authorization: Bearer $TOKEN"

# If this returns "broker unavailable", you cannot monitor live orders

# 3. Check paper/shadow deployments (these should still work)
curl -X GET http://localhost:8000/paper \
  -H "Authorization: Bearer $TOKEN" | jq '.mode'
# Should return "paper" (not affected by broker outage)
```

**Decision: Activate kill switch?**

```bash
# YES, activate if:
# - Live orders are open and you cannot cancel them
# - The broker outage is ongoing (broker status page shows "degraded" or "down")
# - You cannot reconcile live positions

# NO, if:
# - Only paper/shadow orders are running
# - You can still query and cancel live orders (broker is partially up)
# - Broker status page says outage is resolved in < 5 minutes
```

---

## 3.3 Activation: Kill Switch (MANDATORY If Live Orders At Risk)

```bash
# Activate the kill switch via API
curl -X POST http://localhost:8000/kill-switch/global \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Broker API outage - cannot submit or monitor live orders",
    "activated_by": "on-call-engineer",
    "audit_metadata": {
      "incident_type": "broker_outage",
      "broker_status": "see broker status page",
      "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
    }
  }'

# Expected response:
# {
#   "scope": "global",
#   "target_id": "GLOBAL",
#   "active": true,
#   "halt_event_id": "...",
#   "orders_cancelled": <N>,
#   "mtth_ms": <milliseconds>,
#   "activated_at": "2026-04-13T..."
# }

# Verify the response
echo "Kill switch activated. Orders cancelled: <N>"
echo "MTTH: <milliseconds> ms (should be < 200 ms)"
```

---

## 3.4 Monitoring Broker Recovery

**Set up a recurring check (manually or via monitoring script):**

```bash
# Check broker status every 30 seconds
for i in {1..60}; do
  echo "Check $i: $(date +%H:%M:%S)"

  # Test broker connectivity
  if curl -s http://localhost:8000/live/health | grep -q '"broker":"ok"'; then
    echo "✓ Broker is back online"
    break
  else
    echo "✗ Broker still down"
  fi

  sleep 30
done

# When broker comes back online:
# 1. Log the recovery timestamp
# 2. Proceed to Scenario 3.5 (Deactivation)
```

---

## 3.5 Deactivation: Kill Switch

**Only after broker status page shows "operational" AND you can submit test orders.**

```bash
# 1. Verify broker is truly recovered
# - Check broker status page (should show all green)
# - Test a small paper order submission (should succeed)

curl -X POST http://localhost:8000/paper/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SPY", "side": "BUY", "quantity": 1, ...}'

# If that succeeds, broker is working. Proceed to step 2.

# 2. Run reconciliation to check for missed fills or phantom orders
DEPLOYMENT_ID="your-live-deployment"
curl -X POST http://localhost:8000/reconciliation/${DEPLOYMENT_ID}/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"trigger": "manual", "reason": "post-broker-recovery"}'

# Wait for reconciliation to complete (check status endpoint)
curl -X GET http://localhost:8000/reconciliation/${DEPLOYMENT_ID}/latest-report \
  -H "Authorization: Bearer $TOKEN" | jq '.status'

# If status is "PASSED" (no discrepancies), proceed to step 3.

# 3. Deactivate the kill switch
curl -X DELETE http://localhost:8000/kill-switch/global \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Broker recovered. Reconciliation passed.",
    "deactivated_by": "on-call-engineer"
  }'

# Expected response:
# {
#   "scope": "global",
#   "active": false,
#   "halt_event_id": "...",
#   "deactivated_at": "2026-04-13T..."
# }
```

---

## 3.6 Post-Outage Actions

1. **Check for orphaned orders:**
   ```bash
   # Orders submitted BEFORE the outage may have been filled without FXLab knowing
   # Reconciliation should catch these, but manually verify for high-value orders

   curl -X GET "http://localhost:8000/execution-analysis?start_time=<outage-start>&end_time=<outage-end>" \
     -H "Authorization: Bearer $TOKEN" | jq '.orders[] | select(.status == "PENDING")'

   # For each PENDING order, check the broker dashboard to see if it actually filled
   ```

2. **Review the incident timeline:**
   ```bash
   # Get all events related to the broker outage
   curl -X GET "http://localhost:8000/audit?start_time=<outage-start>&end_time=<outage-end>&component=broker" \
     -H "Authorization: Bearer $TOKEN" | jq '.events'
   ```

3. **Take a backup post-recovery:**
   ```bash
   /opt/fxlab/deploy/scripts/backup-db.sh
   ```

---

# SCENARIO 4: FULL HOST FAILURE

**Impact:** Entire platform offline. All services unreachable.

**RTO:** 15–45 minutes (host provisioning + restore).

---

## 4.1 Detection

### Host is Unreachable
```bash
# From a remote machine:
ping <host-ip>
# No response

ssh -v ubuntu@<host-ip>
# Connection refused or timeout

# Check in your cloud provider's console (AWS, GCP, etc.)
# Instance state: "stopped" or "shutting down"
```

### Monitoring Agent Silence
```bash
# If you have Prometheus, Datadog, New Relic, etc.:
# - No metrics received in last 5 minutes
# - Status page shows "DOWN"

# Check your alert rules (should have triggered already)
# Look for: "Host unreachable", "No heartbeat"
```

---

## 4.2 Assessment: Hardware vs Software Failure

**Before provisioning a new host, determine if recovery is possible on the same hardware:**

```bash
# Check cloud provider console for:
# - System logs (might show BSOD, kernel panic, OOM kill)
# - Instance state (running, stopped, terminated, error)

# If state is "error" or "terminated", provision a new host (step 4.3)
# If state is "stopped", try hard reboot first (step 4.2.1)
```

### 4.2.1 Hard Reboot (If Instance Is Stopped)

```bash
# AWS EC2 example:
aws ec2 reboot-instances --instance-ids i-1234567890abcdef0

# GCP Compute Engine example:
gcloud compute instances reset fxlab-host-1

# Azure example:
az vm restart --resource-group fxlab-rg --name fxlab-host-1

# Wait 3–5 minutes
sleep 300

# Check if host is reachable
ssh ubuntu@<host-ip> echo "Host is up"

# If reachable, skip to 4.4 (Verify Services)
# If still unreachable, proceed to 4.3 (New Host Provisioning)
```

---

## 4.3 New Host Provisioning

**Provision an identical host in the same region/zone.**

```bash
# AWS EC2 example
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.xlarge \
  --subnet-id subnet-12345678 \
  --security-group-ids sg-12345678 \
  --key-name fxlab-ssh-key \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=fxlab-host-recovered}]' \
  --monitoring Enabled=true

# Wait for instance to reach "running" state (~2 minutes)
aws ec2 wait instance-running --instance-ids i-newinstance123

# Get the public IP
aws ec2 describe-instances --instance-ids i-newinstance123 \
  | jq '.Reservations[0].Instances[0].PublicIpAddress'
# Note: replace i-newinstance123 with actual instance ID

NEW_HOST_IP="<public-ip-from-above>"
```

**GCP Compute Engine example:**

```bash
gcloud compute instances create fxlab-host-recovered \
  --image-family ubuntu-2004-lts \
  --image-project ubuntu-os-cloud \
  --machine-type n1-highmem-4 \
  --zone us-central1-a \
  --scopes cloud-platform \
  --metadata-from-file startup-script=/tmp/startup.sh

# Get the IP
gcloud compute instances describe fxlab-host-recovered --zone us-central1-a \
  | grep networkIP
```

---

## 4.4 Install FXLab on New Host

```bash
# 1. SSH into the new host
ssh -i ~/.ssh/fxlab-key.pem ubuntu@${NEW_HOST_IP}

# 2. Clone or copy the FXLab repository
# Option A: Clone from repo (if public or you have SSH credentials set up)
git clone https://github.com/your-org/fxlab.git /tmp/fxlab

# Option B: Copy from a backup or artifact repo
# (Depends on your deployment strategy)

# 3. Run the installation script
cd /tmp/fxlab
sudo ./install.sh

# The script will:
# - Validate the host environment
# - Create /opt/fxlab
# - Generate secrets in .env (or use provided .env)
# - Start Docker Compose
# - Run database migrations
# - Enable systemd service

# Wait for installation to complete (~5 minutes)
# You should see:
# [OK] All health checks passed
# [OK] systemd service 'fxlab' enabled
```

**If installation fails:**

```bash
# Check the installation log
cat /tmp/fxlab-install-*.log | tail -100

# Common issues:
# - "Docker daemon is not running" → systemctl restart docker
# - "Port 80 already in use" → check what's running (netstat -tlnp | grep :80)
# - "Insufficient disk space" → check df -h
```

---

## 4.5 Restore Backup

```bash
# 1. Copy the most recent backup from the old host (if available)
# OR from your backup storage (S3, GCS, etc.)

# If backup is in AWS S3:
aws s3 cp s3://fxlab-backups/backup-2026-04-13T15:23:45Z.sql.gz \
  /opt/fxlab/backups/backup-restore.sql.gz

# If backup is on a mounted volume / NFS:
# scp user@backup-server:/backups/backup-2026-04-13T15:23:45Z.sql.gz \
#   /opt/fxlab/backups/backup-restore.sql.gz

# 2. Verify backup integrity
gunzip -t /opt/fxlab/backups/backup-restore.sql.gz
echo "Backup integrity: OK"

# 3. Stop API and Keycloak (prevent writes during restore)
sudo systemctl stop fxlab

# 4. Restore the database (see Scenario 1.4.4 for detailed procedure)
gunzip -c /opt/fxlab/backups/backup-restore.sql.gz | \
  docker exec -i fxlab-postgres psql -U fxlab -d fxlab \
  2>&1 | tee /tmp/restore.log

# Check for errors
if grep -i "error\|fatal" /tmp/restore.log | grep -v "did not find" > /dev/null; then
  echo "WARNING: Restore had errors"
  cat /tmp/restore.log | tail -50
fi

# 5. Start services
sudo systemctl start fxlab

# 6. Wait for healthy status
for i in {1..60}; do
  if curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "✓ API is healthy"
    break
  fi
  echo "Attempt $i: waiting for API..."
  sleep 2
done
```

---

## 4.6 Update DNS / Load Balancer

**If you're using a load balancer or DNS, update it to point to the new host:**

```bash
# AWS Route 53 example:
aws route53 change-resource-record-sets \
  --hosted-zone-id Z12345ABCDE \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "api.fxlab.example.com",
          "Type": "A",
          "TTL": 300,
          "ResourceRecords": [{"Value": "'${NEW_HOST_IP}'"}]
        }
      }
    ]
  }'

# GCP Cloud DNS example:
gcloud dns record-sets update api.fxlab.example.com \
  --rrdatas=${NEW_HOST_IP} \
  --ttl=300 \
  --zone=fxlab-zone

# Verify DNS propagation
nslookup api.fxlab.example.com
# Should resolve to ${NEW_HOST_IP}

# Wait for DNS TTL to expire (5–10 minutes) to ensure all clients see the new IP
```

---

## 4.7 Full Verification

```bash
# 1. Health check (should pass immediately)
curl -X GET http://localhost:8000/health

# 2. Readiness check (all components should be green)
curl -X GET http://localhost:8000/ready

# 3. Verify database data
curl -X GET http://localhost:8000/deployments \
  -H "Authorization: Bearer $TOKEN" | jq 'length'
# Should return the number of deployments (not 0)

# 4. Verify kill switch state was preserved
curl -X GET http://localhost:8000/kill-switch/status \
  -H "Authorization: Bearer $TOKEN" | jq '.[]'

# 5. Run a full reconciliation across all deployments
curl -X POST http://localhost:8000/reconciliation/all/run \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"trigger": "post-host-recovery", "reason": "full platform recovery"}'

# Wait for reconciliation to complete
sleep 30
curl -X GET http://localhost:8000/reconciliation/all/latest-reports \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.status != "PASSED")'
# Should return empty (all PASSED)
```

---

## 4.8 Post-Recovery Actions

1. **Decommission the old host** (if it's still running in cloud):
   ```bash
   # AWS: terminate the instance
   aws ec2 terminate-instances --instance-ids i-oldinstance123

   # GCP: delete the instance
   gcloud compute instances delete fxlab-host-original --zone us-central1-a
   ```

2. **Update your infrastructure documentation:**
   ```bash
   # Update CMDB or Infrastructure tracking
   # - New host IP, instance ID
   - New machine image version
   - Restore timestamp
   ```

3. **Update monitoring/alerting:**
   ```bash
   # Ensure the monitoring agent is running and connected
   sudo systemctl status datadog-agent  # (or your monitoring tool)

   # Test an alert notification
   # (depends on your monitoring tool)
   ```

4. **Take a fresh backup:**
   ```bash
   /opt/fxlab/deploy/scripts/backup-db.sh
   ```

---

# SCENARIO 5: KILL SWITCH STATE CORRUPTION

**Impact:** Risk controls bypass. Kill switch may show as active when it's not (or vice versa).

**RTO:** < 5 minutes (manual recovery).

---

## 5.1 Detection

### Kill Switch Query Returns Unexpected State

```bash
# Check the current kill switch status
curl -X GET http://localhost:8000/kill-switch/status \
  -H "Authorization: Bearer $TOKEN"

# Expected response should be consistent with recent operations
# If you deactivated the kill switch 5 minutes ago, it should show:
# "active": false

# If you just activated it, it should show:
# "active": true, "halt_event_id": "...", "orders_cancelled": <N>
```

### Audit Log Gaps

```bash
# Check the kill switch event log for gaps or inconsistencies
curl -X GET "http://localhost:8000/kill-switch/events?limit=50" \
  -H "Authorization: Bearer $TOKEN" | jq '.events'

# Look for:
# - Missing events (timestamps jump more than expected)
# - Events with null/empty fields
# - Duplicate events

# Example of suspicious audit log:
# Event 1: ACTIVATED at 15:23:00
# Event 2: DEACTIVATED at 15:23:30
# Event 3: [MISSING EVENTS — timestamp jumps to 15:50:00]
# Event 4: ACTIVATED at 15:50:00
```

### Database Verification

```bash
# Query the kill_switch table directly
docker exec fxlab-postgres psql -U fxlab -d fxlab -c "
SELECT id, scope, target_id, is_active, activated_at, deactivated_at, reason
FROM kill_switch_events
ORDER BY activated_at DESC
LIMIT 20;
"

# Check for:
# - Rows with is_active = true and no deactivated_at
# - Rows with is_active = false but deactivated_at is NULL
# - Timestamp inconsistencies
```

---

## 5.2 Root Cause Assessment

### Was There a Recent API Restart?

```bash
# Check when the API container was last restarted
docker inspect fxlab-api | jq '.State.StartedAt'

# If it restarted in the last 10 minutes, the in-memory kill switch state may have been lost
# (The state should be reloaded from the database, but a bug might have caused a mismatch)
```

### Was There a Database Issue?

```bash
# Check PostgreSQL logs for transaction errors
docker logs fxlab-postgres | grep -i "transaction\|error\|conflict" | tail -20

# If you see "serialization failure" or "deadlock", the database may have rolled back
# the kill switch state update
```

### Was the Kill Switch Service Updated?

```bash
# Check the service version
curl -X GET http://localhost:8000/version \
  -H "Authorization: Bearer $TOKEN" | jq '.kill_switch_service_version'

# If it changed recently, a bug may have been introduced
```

---

## 5.3 Emergency: Activate Global Kill Switch Manually

**Safest option: force activate the kill switch immediately.**

```bash
# 1. Activate the kill switch via API
curl -X POST http://localhost:8000/kill-switch/global \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Kill switch state corruption detected. Entering emergency posture.",
    "activated_by": "on-call-emergency-override",
    "audit_metadata": {
      "reason_code": "STATE_CORRUPTION",
      "detection_method": "manual_audit",
      "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
    }
  }'

# 2. Verify the kill switch is actually active
for i in {1..5}; do
  STATUS=$(curl -s http://localhost:8000/kill-switch/status \
    -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.scope == "GLOBAL") | .active')

  if [[ "$STATUS" == "true" ]]; then
    echo "✓ Kill switch is ACTIVE"
    break
  else
    echo "✗ Kill switch is NOT active (attempt $i)"
  fi
  sleep 1
done
```

---

## 5.4 Investigation: Query the Database

```bash
# 1. Check the kill_switch_events table for recent events
docker exec fxlab-postgres psql -U fxlab -d fxlab << 'EOF'
SELECT
  id,
  scope,
  target_id,
  is_active,
  activated_at,
  deactivated_at,
  reason,
  created_at
FROM kill_switch_events
WHERE created_at > now() - interval '2 hours'
ORDER BY created_at DESC;
EOF

# 2. Check the deployments table to see if kill switch state is consistent across all deployments
docker exec fxlab-postgres psql -U fxlab -d fxlab << 'EOF'
SELECT
  deployment_id,
  is_kill_switch_active,
  kill_switch_activated_at
FROM deployments
WHERE created_at > now() - interval '2 hours'
ORDER BY created_at DESC;
EOF

# 3. Look for any database errors in the logs during the time of the corruption
docker logs fxlab-postgres | grep -E "2026-04-13T1[5-6]" | grep -i "error\|fatal"
```

---

## 5.5 Recovery: Clear Corrupted State

```bash
# 1. Lock the kill switch service (prevent concurrent updates)
# (This is a logical lock; no actual lock mechanism in the API)

# 2. Query the current state
CURRENT_STATE=$(curl -s http://localhost:8000/kill-switch/status \
  -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.scope == "GLOBAL")')

echo "Current kill switch state: $CURRENT_STATE"

# 3. If the state is inconsistent, manually correct it in the database
# WARNING: Only do this if you understand the schema completely.

# Example: The API says the kill switch is ACTIVE, but the database says INACTIVE
# Fix: Manually set the database to match the API state

docker exec -i fxlab-postgres psql -U fxlab -d fxlab << 'EOF'
BEGIN TRANSACTION;

-- Lock the kill_switch_events table to prevent concurrent updates
LOCK TABLE kill_switch_events IN EXCLUSIVE MODE;

-- Example: Ensure all rows with is_active=true have no deactivated_at
UPDATE kill_switch_events
SET deactivated_at = NULL
WHERE is_active = TRUE AND deactivated_at IS NOT NULL;

-- Example: Ensure all rows with is_active=false have a deactivated_at (if missing)
UPDATE kill_switch_events
SET deactivated_at = activated_at + interval '1 second'
WHERE is_active = FALSE AND deactivated_at IS NULL;

-- Verify the fix
SELECT id, scope, is_active, activated_at, deactivated_at FROM kill_switch_events LIMIT 10;

COMMIT TRANSACTION;
EOF

# 4. Restart the API to reload state from the database
docker restart fxlab-api

# 5. Verify the state is now consistent
for i in {1..10}; do
  if curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "✓ API restarted successfully"
    break
  fi
  sleep 1
done

# 6. Re-check the kill switch status
curl -X GET http://localhost:8000/kill-switch/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## 5.6 Post-Recovery Actions

1. **Verify data consistency across all deployments:**
   ```bash
   curl -X GET http://localhost:8000/deployments \
     -H "Authorization: Bearer $TOKEN" | jq '.[] | {id, is_kill_switch_active, mode}'
   ```

2. **Test the kill switch (in paper mode first):**
   ```bash
   # Activate and deactivate a kill switch on a paper deployment
   DEPLOYMENT_ID="paper-test"

   curl -X POST http://localhost:8000/kill-switch/strategy/${DEPLOYMENT_ID} \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"reason": "Post-corruption verification test"}'

   sleep 5

   # Verify it activated
   curl -X GET http://localhost:8000/kill-switch/status \
     -H "Authorization: Bearer $TOKEN" | jq '.[] | select(.target_id == "'${DEPLOYMENT_ID}'")'

   # Deactivate
   curl -X DELETE http://localhost:8000/kill-switch/strategy/${DEPLOYMENT_ID} \
     -H "Authorization: Bearer $TOKEN"
   ```

3. **Review the service code for the corruption bug:**
   ```bash
   # If this is a known bug, create a ticket to fix it
   # Check the kill switch service for:
   # - Race conditions during concurrent activations/deactivations
   # - Database transaction isolation issues
   # - State deserialization bugs
   ```

4. **Take a fresh backup:**
   ```bash
   /opt/fxlab/deploy/scripts/backup-db.sh
   ```

---

# SCENARIO 6: DATA BREACH / UNAUTHORIZED ACCESS

**Impact:** Potential credential exposure. Unauthorized trades may have been executed. Broker accounts compromised.

**RTO:** Immediate (this is a security incident).

---

## 6.1 Detection

### Unusual API Access Patterns

```bash
# Check for suspicious authentication activity
docker logs fxlab-api | grep -i "unauthorized\|forbidden\|auth.*fail" | tail -30

# Check for unusual source IPs
docker logs fxlab-api | grep "Authorization: Bearer" | awk '{print $(NF-1)}' | sort | uniq -c | sort -rn | head -10

# If you see a sudden spike in requests from a new IP, investigate
```

### Audit Log Anomalies

```bash
# Check for unusual activities in the audit trail
curl -X GET "http://localhost:8000/audit?start_time=$(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)&end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -H "Authorization: Bearer $TOKEN" | jq '.events[] | select(.action != "READ")'

# Look for:
# - Orders submitted from unexpected source IPs
# - Credential changes
# - Kill switch activations by unknown users
# - Data exports by unauthorized users
```

### Monitoring Alert: Failed Authentication Spike

```bash
# If your monitoring (Prometheus, DataDog, etc.) alerts on:
# - HTTP 401 Unauthorized spike
# - JWT validation failures spike
# - Rate limiting blocks from specific IPs

# Correlation: Check if same IP also had successful requests
docker logs fxlab-api | grep "192.168.1.100" | grep -E "200|201" | wc -l
docker logs fxlab-api | grep "192.168.1.100" | grep -E "401|403" | wc -l
```

### Broker Account Verification

```bash
# Check the broker dashboard manually for unusual trades
# Alpaca: https://app.alpaca.markets/ → History → All Orders
# Schwab: https://client.schwab.com/ → Account Details → Orders

# Look for:
# - Orders from unexpected times (e.g., after-hours market-close)
# - Symbols not in your strategy (e.g., your strategy only trades SPY, but BTC was bought)
# - Sizes that don't match your risk limits
# - Orders with slippage far exceeding normal (sign of rushed/panic selling)
```

---

## 6.2 Immediate Actions: Containment

### 1. Activate Global Kill Switch

```bash
# This prevents any further unauthorized orders
curl -X POST http://localhost:8000/kill-switch/global \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "SECURITY INCIDENT: Unauthorized access detected. Activating kill switch for containment.",
    "activated_by": "on-call-security-incident",
    "audit_metadata": {
      "incident_type": "unauthorized_access",
      "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
      "severity": "CRITICAL"
    }
  }'

echo "✓ Kill switch activated. No further orders will be submitted."
```

### 2. Revoke All Active JWT Tokens

```bash
# All users must re-authenticate
# This invalidates all existing sessions

curl -X POST http://localhost:8000/auth/revoke-all-tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "SECURITY: Session revocation due to suspected breach",
    "revoke_all": true
  }'

echo "✓ All JWT tokens revoked. Users must re-authenticate."
```

### 3. Stop All Order Execution Services

```bash
# Prevent any background job from submitting orders
docker stop fxlab-api  # This stops all API services

# Verify no containers are running
docker ps | grep fxlab
# Should show only postgres, redis, keycloak

echo "✓ API services stopped. No orders can be submitted or executed."
```

---

## 6.3 Investigation

### Step 1: Preserve Evidence

```bash
# 1. Back up logs and audit trails before any cleanup
docker logs fxlab-api > /tmp/api-logs-breach.txt 2>&1
docker logs fxlab-postgres > /tmp/postgres-logs-breach.txt 2>&1

# 2. Export the audit table
docker exec fxlab-postgres pg_dump -U fxlab -d fxlab --table audit_events > /tmp/audit-events-breach.sql

# 3. Create a backup of the entire database
/opt/fxlab/deploy/scripts/backup-db.sh
echo "✓ Backup created: $(ls -lt /opt/fxlab/backups/backup-*.sql.gz | head -1 | awk '{print $NF}')"

# Store all evidence in a secure location (not on the host)
# e.g., S3 with encryption, or a separate secure server
```

### Step 2: Determine the Attack Surface

```bash
# 1. Check if the JWT secret was compromised (look for suspicious token patterns)
curl -X POST http://localhost:8000/auth/validate-token \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  2>&1 | jq '.valid'

# If attackers can forge valid JWTs, the JWT_SECRET_KEY is compromised

# 2. Check if broker API credentials were exposed
grep -r "ALPACA_API_KEY\|TD_AMERITRADE_API_KEY" /opt/fxlab/.env \
  /opt/fxlab/config \
  /opt/fxlab/deploy
# If found, credentials may have been exposed

# 3. Check for suspicious environment variable changes
docker inspect fxlab-api | jq '.Config.Env' | grep -i "key\|secret\|password"
```

### Step 3: Determine Scope of Unauthorized Access

```bash
# 1. Get the list of all orders submitted in the last 2 hours
curl -X GET "http://localhost:8000/audit?start_time=$(date -u -d '120 minutes ago' +%Y-%m-%dT%H:%M:%SZ)&action=ORDER_SUBMIT" \
  -H "Authorization: Bearer $TOKEN" | jq '.events'

# Save to a file for analysis
curl -X GET "http://localhost:8000/audit?start_time=$(date -u -d '120 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  -H "Authorization: Bearer $TOKEN" > /tmp/audit-events-breach.json

# 2. Cross-check with broker account orders
# (Manually verify orders in the broker dashboard)
```

---

## 6.4 Credential Rotation

### Rotate All Secrets

```bash
# 1. Generate new JWT secret
NEW_JWT_SECRET=$(openssl rand -base64 32)
echo "New JWT_SECRET_KEY: $NEW_JWT_SECRET"

# 2. Generate new Keycloak admin password
NEW_KEYCLOAK_PASSWORD=$(openssl rand -base64 16)
echo "New KEYCLOAK_ADMIN_PASSWORD: $NEW_KEYCLOAK_PASSWORD"

# 3. Update .env file
# WARNING: Do this carefully; ensure you have a backup first
cp /opt/fxlab/.env /opt/fxlab/.env.breach-backup
sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$NEW_JWT_SECRET/" /opt/fxlab/.env
sed -i "s/KEYCLOAK_ADMIN_PASSWORD=.*/KEYCLOAK_ADMIN_PASSWORD=$NEW_KEYCLOAK_PASSWORD/" /opt/fxlab/.env

# 4. Rotate broker API credentials
# (Done via broker dashboard or API)
# Alpaca: https://app.alpaca.markets/ → API Keys → Regenerate
# Schwab: https://client.schwab.com/ → API Access → Regenerate Key

# NOTE: This may interrupt live trading. Plan this carefully.
echo "TODO: Rotate broker API credentials manually via broker dashboard"

# 5. Update secrets in .env for brokers
# After rotating in broker dashboard, update .env with new credentials
sed -i "s/ALPACA_API_KEY=.*/ALPACA_API_KEY=<NEW_KEY>/" /opt/fxlab/.env
sed -i "s/ALPACA_SECRET_KEY=.*/ALPACA_SECRET_KEY=<NEW_KEY>/" /opt/fxlab/.env
# Repeat for other brokers

# 6. Store the new secrets securely (not in git!)
# Use: HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, or similar
```

### Restart Services with New Credentials

```bash
# 1. Restart Keycloak with new admin password
docker stop fxlab-keycloak
docker start fxlab-keycloak
sleep 30  # Wait for Keycloak to initialize

# 2. Restart API with new JWT secret
docker stop fxlab-api
docker start fxlab-api

# 3. Wait for services to be healthy
for i in {1..60}; do
  if curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "✓ API is healthy"
    break
  fi
  sleep 2
done

# 4. Test authentication with new credentials
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'
```

---

## 6.5 Forensic Analysis

```bash
# 1. Determine when the breach occurred
docker logs fxlab-api | grep -i "invalid.*token\|forged\|unauthorized" | head -5

# First instance of suspicious activity
BREACH_START=$(docker logs fxlab-api | grep -i "unauthorized" | head -1 | awk '{print $1}')

# 2. Determine what data was accessed
# Query the audit trail for all actions between breach start and detection
START_TIME=$(echo "$BREACH_START" | cut -d'T' -f1,2)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)

curl -X GET "http://localhost:8000/audit?start_time=${START_TIME}Z&end_time=${END_TIME}Z" \
  -H "Authorization: Bearer $TOKEN" | jq '.events | group_by(.action) | map({action: .[0].action, count: length})'

# 3. Identify all user accounts that were accessed
curl -X GET "http://localhost:8000/audit?start_time=${START_TIME}Z&end_time=${END_TIME}Z" \
  -H "Authorization: Bearer $TOKEN" | jq '.events[].user_id' | sort | uniq

# 4. Check if any new users were created during the breach window
curl -X GET "http://localhost:8000/audit?start_time=${START_TIME}Z&end_time=${END_TIME}Z&action=USER_CREATE" \
  -H "Authorization: Bearer $TOKEN" | jq '.events'
```

---

## 6.6 Post-Incident Recovery

### 1. Restore a Clean Backup

**Only if you determine the database itself was compromised (e.g., customer data exfiltrated).**

```bash
# Use the latest backup from BEFORE the breach start time
CLEAN_BACKUP="/opt/fxlab/backups/backup-2026-04-13T14:00:00Z.sql.gz"

# Follow Scenario 1.4 (Backup Restore) to restore from this backup
# This will revert any unauthorized orders or account changes
```

### 2. Reinstate Safe Services

```bash
# 1. Restart all services with new credentials
docker restart fxlab-keycloak fxlab-api fxlab-postgres fxlab-redis

# 2. Verify all are healthy
curl -X GET http://localhost:8000/health
curl -X GET http://localhost:8000/ready

# 3. Run full reconciliation with broker
DEPLOYMENT_ID="your-live-deployment"
curl -X POST http://localhost:8000/reconciliation/${DEPLOYMENT_ID}/run \
  -H "Authorization: Bearer $NEW_TOKEN" \
  -d '{"trigger": "post-security-incident", "reason": "Verify broker accounts not compromised"}'
```

### 3. Notify Users and Stakeholders

Use a security incident communication template (customize as needed):

```
SECURITY INCIDENT NOTIFICATION

Date: 2026-04-13T16:30:00 UTC
Severity: CRITICAL
Classification: Unauthorized Access Detected and Contained

Details:
  - Unauthorized access to FXLab platform detected on 2026-04-13 at ~16:00 UTC
  - Global kill switch activated; no unauthorized orders were submitted
  - All JWT tokens revoked; users must re-authenticate
  - All secrets rotated; new credentials in place
  - Broker accounts verified; no unauthorized trades detected
  - System restored from clean backup at 14:00 UTC

Action Items:
  1. All users: log in again (you will be prompted)
  2. Traders: verify all open positions and orders in the broker dashboard
  3. Operations: monitor for any unusual activity in the next 24 hours
  4. Security: review attached forensic report

Next Update: 2026-04-13T18:00:00 UTC

#fxlab-security #fxlab-incidents
```

### 4. Schedule Post-Incident Review

```bash
# Within 24–48 hours, conduct a blameless post-mortem:
# 1. Timeline of breach detection and response
# 2. Root cause analysis (how was access obtained?)
# 3. Impact assessment (what was accessed/changed?)
# 4. Recovery validation (how did we verify the fix?)
# 5. Preventive measures (how do we prevent this again?)
```

---

## APPENDIX: Testing and Validation

### Health Check Commands

```bash
# API health check (all components)
curl -X GET http://localhost:8000/health -w "\nHTTP: %{http_code}\n"

# API readiness check (all dependencies)
curl -X GET http://localhost:8000/ready -w "\nHTTP: %{http_code}\n"

# Kill switch status
curl -X GET http://localhost:8000/kill-switch/status \
  -H "Authorization: Bearer $TOKEN" | jq '.'

# Database connectivity
docker exec fxlab-postgres pg_isready -U fxlab -d fxlab -h localhost

# Redis connectivity
docker exec fxlab-redis redis-cli ping
```

### Quick Recovery Checklist

```
[ ] Identified the scenario (1–6)
[ ] Assessed impact and RTO/RPO
[ ] Activated kill switch (if applicable)
[ ] Followed recovery steps for the scenario
[ ] Verified recovery with health checks
[ ] Ran reconciliation
[ ] Took a fresh backup
[ ] Notified stakeholders
[ ] Scheduled post-incident review
[ ] Updated runbooks based on lessons learned
```

---

**Last Tested:** TBD
**Next Review:** Quarterly (or after each incident)
**Owner:** FXLab Operations Team
**Escalation:** See [Escalation Matrix](#escalation-matrix)

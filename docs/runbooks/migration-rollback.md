# Migration Rollback Procedure

## Overview

This runbook covers rolling back Alembic database migrations for the FXLab
application. Migrations alter the database schema (tables, columns, indexes,
constraints) and occasionally transform data. A failed or harmful migration
must be rolled back quickly to restore service.

FXLab uses Alembic for schema migrations with the migration files stored in
`infra/migrations/versions/`. Each migration has an `upgrade()` function
(apply) and a `downgrade()` function (rollback).

## When to Use Migration Rollback

| Scenario | Action |
|----------|--------|
| Migration fails mid-execution | Rollback with `alembic downgrade -1` |
| Migration succeeds but causes application errors | Rollback with `alembic downgrade -1` |
| Migration succeeds but causes data corruption | Use PITR instead (see point-in-time-recovery.md) |
| Migration succeeds, app works, but performance degrades | Evaluate: rollback if critical, otherwise fix forward |

The decision between rollback and PITR depends on whether the migration's
`downgrade()` function can cleanly reverse the changes. If the migration
included destructive data transformations (column drops, data deletes), PITR
is safer. If the migration only added columns, indexes, or tables, rollback
is appropriate.

## Prerequisites

1. Know which migration caused the problem (check `alembic_version` table).
2. FXLab API is either still running (if the migration didn't break it) or
   scaled to 0 replicas.
3. A database backup exists from before the migration ran.
4. You have the Alembic CLI available and configured.

## Pre-Rollback Checklist

Before rolling back any migration:

- [ ] Take a backup NOW, even if one exists from before the migration.
      This preserves the current state in case rollback makes things worse.
- [ ] Identify the current migration revision.
- [ ] Verify the target revision's `downgrade()` function exists and looks correct.
- [ ] Notify the team that a rollback is in progress.
- [ ] If live trading is active, activate the kill switch first.

## Procedure

### Step 1: Identify Current Migration State

```bash
# Check current revision
alembic current

# Example output:
# 20260411_0011_add_risk_events_table (head)

# View migration history
alembic history --verbose | head -20
```

### Step 2: Take a Pre-Rollback Backup

```bash
pg_dump \
  --host="${PGHOST}" \
  --port="${PGPORT:-5432}" \
  --username="${PGUSER}" \
  --dbname=fxlab \
  --format=custom \
  --compress=9 \
  --file="/tmp/fxlab_pre_rollback_$(date +%Y%m%d_%H%M%S).sql.gz"
```

### Step 3: Scale Down API (If Running)

```bash
# Scale to zero — prevents new requests during schema change
kubectl scale deployment/fxlab-api -n fxlab --replicas=0

# Wait for pods to terminate
kubectl wait --for=delete pod -l app=fxlab-api -n fxlab --timeout=60s
```

### Step 4: Review the Downgrade Function

Before running the rollback, read the migration file to understand what
the downgrade will do:

```bash
# Find the migration file
ls infra/migrations/versions/ | grep "$(alembic current 2>&1 | head -1 | awk '{print $1}')"

# Read the downgrade function
# Verify it reverses the upgrade cleanly
# Watch for: DROP COLUMN (data loss), DROP TABLE (data loss), data transforms
```

If the `downgrade()` function drops columns or tables that contain important
data, consider PITR instead of rollback.

### Step 5: Execute Rollback

```bash
# Roll back one migration
alembic downgrade -1

# Verify the new current revision
alembic current
```

For rolling back multiple migrations:

```bash
# Roll back to a specific revision
alembic downgrade <target_revision>

# Roll back N steps
alembic downgrade -N
```

### Step 6: Verify Schema State

```sql
-- Connect and verify tables/columns match expected state
psql -h ${PGHOST} -U ${PGUSER} -d fxlab

-- Check the alembic version matches expected
SELECT * FROM alembic_version;

-- Verify specific tables affected by the rolled-back migration
-- Example: if the migration added a 'risk_events' table
SELECT EXISTS (
  SELECT FROM information_schema.tables
  WHERE table_name = 'risk_events'
);
-- Should be 'f' (false) if the table was added by the rolled-back migration
```

### Step 7: Restart the Application

```bash
# Scale API back up
kubectl scale deployment/fxlab-api -n fxlab --replicas=2

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=fxlab-api -n fxlab --timeout=120s

# Verify health
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/health
kubectl exec -n fxlab deploy/fxlab-api -- curl -s http://localhost:8000/ready
```

### Step 8: Verify Application Behaviour

```bash
# Check API logs for errors
kubectl logs -n fxlab deploy/fxlab-api --tail=50

# Run a quick smoke test
curl -s https://fxlab.example.com/health | jq .
curl -s https://fxlab.example.com/ready | jq .
```

## Rolling Back in Kubernetes (Entrypoint Migration)

If migrations run as part of the container entrypoint (`entrypoint.sh` runs
`alembic upgrade head` before starting uvicorn), a rollback requires:

1. Scale deployment to 0 replicas.
2. Run a one-off pod with the rollback command:

```bash
kubectl run fxlab-rollback \
  -n fxlab \
  --image=fxlab-api:latest \
  --restart=Never \
  --env="DATABASE_URL=${DATABASE_URL}" \
  --command -- alembic downgrade -1

# Wait for completion
kubectl wait --for=condition=complete pod/fxlab-rollback -n fxlab --timeout=120s

# Check logs
kubectl logs -n fxlab fxlab-rollback

# Clean up
kubectl delete pod fxlab-rollback -n fxlab
```

3. Deploy the previous application version (whose code matches the rolled-back
   schema) or fix forward with a corrective migration.

## Common Pitfalls

| Pitfall | Prevention |
|---------|------------|
| Rolling back a migration that dropped a column | Data in that column is lost. Use PITR instead. Always backup before migration. |
| Rolling back but deploying the same code version | The code expects the new schema. Deploy the previous version or add a corrective migration. |
| Rolling back in production without testing | Always test the downgrade in staging first. |
| Multiple migrations need rollback but you only roll back one | Check `alembic history` and roll back to the correct target revision. |
| Rollback fails with "relation does not exist" | The downgrade function references objects that don't exist. Manual SQL intervention needed. Escalate to DBA. |

## When to Escalate vs Rollback

| Signal | Action |
|--------|--------|
| Migration failed with clear error, no data changes | Rollback. Fix migration. Re-apply. |
| Migration succeeded, app throws ORM errors | Rollback. The schema and code are mismatched. |
| Migration dropped a column with data | PITR to pre-migration timestamp. Do NOT rollback (data is already gone). |
| Rollback command itself fails | STOP. Do not retry. Escalate to DBA with full error output. |
| Unsure whether rollback is safe | Take backup. Test rollback in staging. If staging succeeds, proceed in production. |

## Escalation Contacts

| Role | When to contact |
|------|-----------------|
| On-call engineer | First responder. Can execute rollback procedure. |
| DBA | Rollback fails, data corruption, PITR needed. |
| Team lead | Data loss confirmed, extended outage (>30 min), live trading impact. |

# Secret Rotation Runbook — FXLab

**Last updated:** 2026-04-11
**Owner:** Platform Engineering
**Severity:** HIGH — secrets govern authentication, database access, and broker connectivity.

---

## Overview

FXLab uses the **_NEW suffix rotation convention** for zero-downtime secret rotation.
The `EnvSecretProvider` reads secrets from environment variables and supports runtime
rotation without service restarts. Both old and new values remain valid during a
configurable rotation window, ensuring no in-flight requests fail during the swap.

### How the _NEW Suffix Convention Works

1. Operator sets `KEY_NEW=<new-value>` in the environment (via K8s secret, .env, or CI/CD).
2. The `SecretRotationJob` (or manual API call) detects `KEY_NEW` and calls `rotate_secret()`.
3. The provider swaps: `KEY` (current) → `KEY_OLD` (preserved), `KEY_NEW` → `KEY` (active).
4. Both `KEY` and `KEY_OLD` are valid during the rotation window.
5. On next deploy, the operator removes `KEY_NEW` and `KEY_OLD` from the environment.

### Automated Rotation

The `SecretRotationJob` runs as a background daemon thread, scanning every 5 minutes
(configurable via `check_interval_seconds`). It automatically detects and processes
`_NEW` suffixed environment variables for all known secret keys.

---

## Procedure 1: JWT Secret Key Rotation

**When:** Every 90 days, or immediately if compromise is suspected.

**Impact:** Active JWT tokens signed with the old key remain valid during the rotation
window. New tokens are signed with the new key.

### Steps

1. **Generate a new JWT secret** (minimum 32 bytes):
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. **Set the new key in the environment:**

   For Kubernetes:
   ```bash
   # Update the K8s secret (base64-encoded)
   kubectl -n fxlab create secret generic fxlab-api-secrets \
     --from-literal=JWT_SECRET_KEY=<CURRENT_VALUE> \
     --from-literal=JWT_SECRET_KEY_NEW=<NEW_VALUE> \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

   For local development (.env):
   ```
   JWT_SECRET_KEY=<current-key>
   JWT_SECRET_KEY_NEW=<new-key>
   ```

3. **Trigger rotation** (choose one):
   - **Automatic:** Wait for the next `SecretRotationJob` cycle (up to 5 minutes).
   - **Manual via API:** `POST /admin/rotate-secrets` (admin auth required).
   - **Manual via code:**
     ```python
     from services.api.infrastructure.env_secret_provider import EnvSecretProvider
     from services.api.infrastructure.secret_rotation_job import SecretRotationJob
     provider = EnvSecretProvider()
     job = SecretRotationJob(provider=provider)
     rotated = job.check_and_rotate()
     print(f"Rotated: {rotated}")
     ```

4. **Verify rotation succeeded:**
   ```bash
   # Check structured logs for rotation event
   kubectl -n fxlab logs deployment/fxlab-api | grep "secret.rotated"

   # Verify new tokens work
   curl -s http://localhost:8000/health -H "Authorization: Bearer $(python3 -c '...')"

   # Verify old tokens still work (rotation window)
   curl -s http://localhost:8000/health -H "Authorization: Bearer <old-token>"
   ```

5. **Clean up** (after rotation window expires, typically 24 hours):
   ```bash
   # Remove _NEW and _OLD from K8s secret
   kubectl -n fxlab create secret generic fxlab-api-secrets \
     --from-literal=JWT_SECRET_KEY=<NEW_VALUE> \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

### Rollback

If the new key causes issues:
- The old key is preserved as `JWT_SECRET_KEY_OLD` in memory.
- Revert the K8s secret to the original value and restart pods.
- All tokens signed with the old key remain valid immediately.

---

## Procedure 2: Database Credential Rotation

**When:** Every 90 days, or immediately if compromise is suspected.

**Impact:** Connection pool drains existing connections and establishes new ones.
Brief latency spike expected during reconnection (typically < 2 seconds).

### Pre-Rotation Checklist

- [ ] New credentials created in PostgreSQL (user still has old credentials active).
- [ ] Verified new credentials can connect: `psql "postgresql://fxlab:<new-pw>@host:5432/fxlab"`.
- [ ] No active migrations running (`SELECT * FROM alembic_version`).
- [ ] Off-peak traffic window selected.

### Steps

1. **Create new database credentials in PostgreSQL:**
   ```sql
   -- Connect as superuser
   ALTER USER fxlab WITH PASSWORD '<new-password>';
   -- Both old and new passwords work until pg_hba.conf changes
   ```

2. **Set the new DATABASE_URL:**
   ```bash
   kubectl -n fxlab create secret generic fxlab-api-secrets \
     --from-literal=DATABASE_URL="postgresql://fxlab:<old-pw>@postgres:5432/fxlab" \
     --from-literal=DATABASE_URL_NEW="postgresql://fxlab:<new-pw>@postgres:5432/fxlab" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **Trigger rotation** (same methods as JWT rotation above).

4. **Verify:**
   ```bash
   # Check readiness probe (includes database check)
   curl -s http://localhost:8000/ready | jq .

   # Check for connection errors in logs
   kubectl -n fxlab logs deployment/fxlab-api | grep -i "database\|connection" | tail -20

   # Verify queries execute
   curl -s http://localhost:8000/deployments/ -H "Authorization: Bearer <token>"
   ```

5. **Clean up:** Remove `DATABASE_URL_NEW` from K8s secret on next deploy.

### Rollback

- Revert K8s secret to the old DATABASE_URL and trigger a rolling restart:
  ```bash
  kubectl -n fxlab rollout restart deployment/fxlab-api
  ```
- Old database credentials remain valid as long as PostgreSQL hasn't been reconfigured.

---

## Procedure 3: Broker API Key Rotation

**When:** Every 90 days, per broker security policy, or on suspected compromise.

**Impact:** In-flight orders may receive transient 401 errors during the brief
rotation window. The circuit breaker will handle retries.

### Pre-Rotation Checklist

- [ ] New API key generated in the broker portal (Alpaca, TD Ameritrade, etc.).
- [ ] Verified new key works: test API call to broker health endpoint.
- [ ] Kill switch is available in case of issues.
- [ ] No active deployments with open orders (or: orders are in paper mode only).

### Steps

1. **Generate new API key** in the broker's developer portal.

2. **Set the new key:**
   ```bash
   # Example for Alpaca broker adapter
   kubectl -n fxlab create secret generic fxlab-api-secrets \
     --from-literal=ALPACA_API_KEY=<old-key> \
     --from-literal=ALPACA_API_KEY_NEW=<new-key> \
     --from-literal=ALPACA_SECRET_KEY=<old-secret> \
     --from-literal=ALPACA_SECRET_KEY_NEW=<new-secret> \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **Trigger rotation.**

4. **Verify:**
   ```bash
   # Check broker connectivity
   curl -s http://localhost:8000/ready | jq '.checks.brokers'

   # Submit a test paper order
   curl -s -X POST http://localhost:8000/paper/orders \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"deployment_id": "rotation-test", "symbol": "AAPL", "side": "buy", "quantity": "1", "order_type": "market"}'

   # Check circuit breaker state
   curl -s http://localhost:8000/metrics | grep circuit_breaker_state
   ```

5. **Deactivate old key** in the broker portal after confirming new key works.

6. **Clean up:** Remove `_NEW` suffixed env vars on next deploy.

### Rollback

- If the new key fails, the circuit breaker prevents cascading failures.
- Revert to old key: update K8s secret and trigger rolling restart.
- If orders are stuck, activate the kill switch: `POST /kill-switch/activate`.

---

## Procedure 4: Redis Password Rotation

**When:** Every 90 days or on suspected compromise.

**Impact:** Minimal — Redis connections are lightweight and reconnect quickly.

### Steps

1. **Update Redis ACL:**
   ```bash
   redis-cli ACL SETUSER default on ><new-password>
   ```

2. **Set new REDIS_URL:**
   ```bash
   kubectl -n fxlab create secret generic fxlab-api-secrets \
     --from-literal=REDIS_URL="redis://:<old-pw>@redis:6379/0" \
     --from-literal=REDIS_URL_NEW="redis://:<new-pw>@redis:6379/0" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **Trigger rotation.**

4. **Verify:** `curl -s http://localhost:8000/ready | jq '.checks.redis'`

5. **Remove old password from Redis ACL** after confirming connectivity.

---

## Monitoring and Alerts

### Key Metrics

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| `secret.rotated` log events | Expected during rotation | Verify success |
| `secret.rotation.failed` log events | Any occurrence | Investigate immediately |
| `/ready` probe failures | After rotation | Check connectivity |
| `circuit_breaker_state` | OPEN after rotation | Broker key issue |

### Log Queries

```bash
# All rotation events in the last hour
kubectl -n fxlab logs deployment/fxlab-api --since=1h | grep "secret.rotation"

# Failed rotations
kubectl -n fxlab logs deployment/fxlab-api | grep "secret.rotation.failed"

# Expiring secrets (from list_expiring)
kubectl -n fxlab logs deployment/fxlab-api | grep "secret.expiring"
```

---

## Escalation Matrix

| Situation | Action | Contact |
|-----------|--------|---------|
| Rotation fails with KeyError | Verify _NEW env var is set correctly | On-call engineer |
| Rotation succeeds but service errors | Check logs, consider rollback | On-call engineer |
| Suspected credential compromise | Rotate immediately, activate kill switch if broker keys | Security team + on-call |
| Database connection failures after rotation | Rollback DATABASE_URL, restart pods | DBA + on-call |
| Broker 401 errors after rotation | Rollback broker key, check circuit breaker | On-call + broker support |

---

## Rotation Schedule

| Secret | Rotation Interval | Last Rotated | Next Due |
|--------|-------------------|-------------|----------|
| JWT_SECRET_KEY | 90 days | — | — |
| DATABASE_URL | 90 days | — | — |
| REDIS_URL | 90 days | — | — |
| ALPACA_API_KEY | 90 days | — | — |
| ALPACA_SECRET_KEY | 90 days | — | — |
| KEYCLOAK_ADMIN_CLIENT_SECRET | 90 days | — | — |

> **Note:** Use `provider.list_expiring(threshold_days=90)` to programmatically
> check which secrets are approaching their rotation deadline.

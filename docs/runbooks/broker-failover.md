# Broker Failover Runbook

**Owner:** FXLab Operations Team
**Last Updated:** 2026-04-11

---

## 1. Adapter Reconnection

### Detecting Disconnection

The system detects adapter disconnection via:
- `get_diagnostics()` returning `connection_status: disconnected`.
- Failed API calls returning `ExternalServiceError` with `TransientError`.
- Reconciliation finding discrepancies after a reconnection event.

### Automatic Recovery

The adapter retry policy handles transient failures:
- Exponential backoff with jitter: 1s, 2s, 4s, 8s, 16s.
- Maximum 5 retries per operation.
- Retries on: network timeouts, 429 rate limits, 5xx server errors.
- No retry on: 400, 401, 403, 404 (permanent failures).

### Manual Reconnection Procedure

If automatic recovery fails:

1. **Check adapter diagnostics:**
   ```
   GET /paper/{deployment_id}/account
   ```
   If this returns 500/503, the adapter is disconnected.

2. **Verify broker API status.** Check the broker's status page (e.g., Alpaca status.alpaca.markets).

3. **If broker API is down:** Freeze the deployment and wait.
   ```
   POST /deployments/{deployment_id}/freeze
   ```

4. **If broker API is up but adapter is stuck:**
   - Deregister the adapter: `DELETE /paper/{deployment_id}`
   - Re-register: `POST /paper/{deployment_id}/register`
   - Run reconciliation: `POST /reconciliation/{deployment_id}/run`

5. **Verify recovery:**
   - Check account accessibility: `GET /paper/{deployment_id}/account`
   - Check position state: `GET /paper/{deployment_id}/positions`
   - Verify reconciliation report is clean.
   - Run reconnect drill: `POST /drills/{deployment_id}/execute {"drill_type": "reconnect"}`

---

## 2. Manual Position Import

When positions exist at the broker but are not tracked internally (e.g., after a system restart, database recovery, or manual broker activity):

### Assessment

1. **Get broker positions:** Use the broker's API directly or:
   ```
   GET /paper/{deployment_id}/positions
   ```

2. **Get internal position state:** Check the reconciliation report:
   ```
   POST /reconciliation/{deployment_id}/run {"trigger": "manual"}
   ```

3. **Identify gaps:** Look for `extra_position` discrepancies in the report.

### Import Procedure

For paper/shadow deployments:
1. The adapter tracks positions based on submitted orders. To sync, submit offsetting orders that bring internal state in line with broker state.
2. Use market orders for immediate synchronization.
3. Run reconciliation after each adjustment to verify convergence.

For live deployments:
1. **Freeze the deployment first.**
2. Document each position to be imported.
3. Submit adjustment orders through the standard API path (so risk gates validate them).
4. Run reconciliation to verify.
5. Unfreeze only after the reconciliation report is clean.

---

## 3. Broker Migration

When switching from one broker adapter to another:

1. **Freeze all affected deployments.**
2. **Export current state:**
   - All open orders: `GET /paper/{deployment_id}/all-orders`
   - All positions: `GET /paper/{deployment_id}/positions`
   - Account state: `GET /paper/{deployment_id}/account`
3. **Deregister old adapter:** `DELETE /paper/{deployment_id}`
4. **Register new adapter:** `POST /paper/{deployment_id}/register`
5. **Reconcile:**
   - Verify positions are visible via new adapter.
   - Run reconciliation to check for discrepancies.
6. **Run all 4 drills** against the new adapter:
   ```
   POST /drills/{deployment_id}/execute {"drill_type": "kill_switch"}
   POST /drills/{deployment_id}/execute {"drill_type": "rollback"}
   POST /drills/{deployment_id}/execute {"drill_type": "reconnect"}
   POST /drills/{deployment_id}/execute {"drill_type": "failover"}
   ```
7. **Verify eligibility:** `GET /drills/{deployment_id}/eligibility`
8. **Unfreeze** only after all drills pass and reconciliation is clean.

---

## 4. Emergency Broker Contact

| Broker | Support | Hours | Emergency |
|--------|---------|-------|-----------|
| Alpaca | support@alpaca.markets | 24/7 | api-status@alpaca.markets |
| TD Ameritrade / Schwab | developer.tdameritrade.com | Market hours | Phone: 800-669-3900 |

Always include in broker support requests:
- Account ID (never include API keys).
- Affected order IDs or position symbols.
- Timestamp range of the issue (UTC).
- Description of expected vs actual behavior.

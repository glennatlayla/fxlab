# Deployment Operations Runbook

**Owner:** FXLab Operations Team
**Last Updated:** 2026-04-11

---

## 1. Deployment Lifecycle

Deployments follow a strict state machine. Every transition is recorded in an audit trail.

```
draft → submitted → approved → activating → active → deactivating → deactivated
                                              ↕
                                           frozen
```

All transitions except `activating → active` and `deactivating → deactivated` require an explicit API call.

---

## 2. Creating a New Deployment

### Paper Deployment

```
POST /deployments/paper
{
    "strategy_id": "<ULID>",
    "config": { ... },
    "risk_limits": {
        "max_position_size": "10000",
        "max_daily_loss": "5000",
        "max_order_value": "50000",
        "max_concentration_pct": "25.0",
        "max_open_orders": 20
    },
    "emergency_posture": "flatten_all"
}
```

### Live-Limited Deployment

```
POST /deployments/live-limited
{
    "strategy_id": "<ULID>",
    "config": { ... },
    "risk_limits": { ... },
    "emergency_posture": "flatten_all",
    "live_limits": {
        "max_capital": "100000",
        "allowed_symbols": ["AAPL", "MSFT", "GOOGL"]
    }
}
```

**Prerequisite for live:** All 4 drill types must pass. Check via `GET /drills/{deployment_id}/eligibility`.

---

## 3. Submitting for Approval

```
POST /deployments/{deployment_id}/submit-for-approval
```

This transitions the deployment from `draft` to `submitted`. The deployment is now visible to approvers.

---

## 4. Approving a Deployment

```
POST /deployments/{deployment_id}/approve
```

Requires `deployments:approve` scope. Transitions `submitted → approved`.

**Pre-approval checklist:**
- [ ] Strategy has passing backtest results.
- [ ] Risk limits are configured and reviewed.
- [ ] Emergency posture is set (not `hold` for live deployments).
- [ ] For live: all 4 drill types pass (`GET /drills/{id}/eligibility`).

---

## 5. Activating a Deployment

```
POST /deployments/{deployment_id}/activate
```

Transitions `approved → activating → active`. The system enforces:
- Emergency posture must be configured (spec rule 6).
- For live deployments: all drill types must have passing results.

**Post-activation steps:**
1. Register the adapter: `POST /paper/{deployment_id}/register` (or shadow equivalent).
2. Configure risk limits: `PUT /risk/deployments/{deployment_id}/risk-limits`.
3. Run initial reconciliation: `POST /reconciliation/{deployment_id}/run`.
4. Monitor first 15 minutes for anomalies.

---

## 6. Freezing a Deployment

```
POST /deployments/{deployment_id}/freeze
```

Transitions `active → frozen`. No new orders are accepted. Existing positions remain open.

**When to freeze:**
- Scheduled maintenance window.
- Investigating unusual behavior that doesn't warrant a full kill switch.
- End of trading day before market close procedures.

**Unfreezing:**
```
POST /deployments/{deployment_id}/unfreeze
```

Transitions `frozen → active`. Run reconciliation immediately after unfreezing.

---

## 7. Deactivating a Deployment

```
POST /deployments/{deployment_id}/deactivate
```

Transitions `active|frozen → deactivating → deactivated`.

**Pre-deactivation checklist:**
- [ ] All open orders cancelled (or kill switch activated).
- [ ] All positions closed (or documented as intentionally held).
- [ ] Final reconciliation run and report saved.
- [ ] Deregister adapter: `DELETE /paper/{deployment_id}` (or shadow equivalent).

---

## 8. Rolling Back a Deployment

```
POST /deployments/{deployment_id}/rollback
```

Available from `active`, `frozen`, or `deactivating` states. Returns deployment to `approved` state for re-review.

**When to rollback:**
- Post-deployment issues discovered that require config changes.
- Strategy performance significantly below expectations.
- After a failed drill reveals operational gaps.

**Post-rollback steps:**
1. All open orders are automatically cancelled.
2. Review and update deployment config.
3. Re-run drills before reactivation.
4. Re-submit for approval.

---

## 9. Health Monitoring

```
GET /deployments/{deployment_id}           # Deployment details + state
GET /deployments/{deployment_id}/health    # Health metrics
```

Monitor these metrics continuously for active deployments:
- Adapter connection status (from `GET /paper/{id}/account`).
- Open order count (from `GET /paper/{id}/open-orders`).
- Position count and P&L (from `GET /paper/{id}/positions`).
- Last reconciliation status and time.
- Risk event count (from `GET /risk/risk-events?deployment_id={id}`).

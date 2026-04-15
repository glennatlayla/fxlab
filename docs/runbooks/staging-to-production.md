# Staging-to-Production Promotion Criteria

**Owner:** FXLab Operations Team
**Last Updated:** 2026-04-12

---

## 1. Promotion Gate Checklist

A deployment may be promoted from staging (paper/shadow) to production (live) only when ALL of the following criteria are met. No exceptions.

### Gate 1: Strategy Validation

- [ ] Strategy has completed at least 1 full backtest run with `status: completed`.
- [ ] Backtest results show positive risk-adjusted returns (Sharpe > 1.0 recommended).
- [ ] Strategy has been reviewed and approved (`deployments:approve` scope holder signed off).

### Gate 2: Paper/Shadow Track Record

- [ ] Deployment has been active in paper or shadow mode for at least 5 trading days.
- [ ] No S1 or S2 incidents during the observation period.
- [ ] Execution drift analysis shows max severity ≤ MINOR for the observation period.
- [ ] Shadow P&L within 5% of backtest expectations.

### Gate 3: Risk Configuration

- [ ] Risk limits explicitly configured via `PUT /risk/deployments/{id}/risk-limits`.
- [ ] `max_daily_loss` set to an acceptable value (not 0 / unlimited).
- [ ] `max_position_size` set to an acceptable value.
- [ ] `max_order_value` set to an acceptable value.
- [ ] `max_concentration_pct` ≤ 25% (or documented exception).
- [ ] `max_open_orders` set to a reasonable ceiling.

### Gate 4: Operational Readiness (Drills)

- [ ] Kill switch drill passed: `POST /drills/{id}/execute {"drill_type": "kill_switch"}`
- [ ] Rollback drill passed: `POST /drills/{id}/execute {"drill_type": "rollback"}`
- [ ] Reconnect drill passed: `POST /drills/{id}/execute {"drill_type": "reconnect"}`
- [ ] Failover drill passed: `POST /drills/{id}/execute {"drill_type": "failover"}`
- [ ] Live eligibility confirmed: `GET /drills/{id}/eligibility` returns `{"eligible": true}`
- [ ] Kill switch MTTH < 500 ms (paper) or < 200 ms (live).

### Gate 5: Reconciliation

- [ ] Last reconciliation report is `clean` or `resolved` (no unresolved discrepancies).
- [ ] At least 3 consecutive scheduled reconciliation runs with no unresolved discrepancies.

### Gate 6: Emergency Posture

- [ ] Emergency posture is configured (not `hold` for live deployments).
- [ ] Emergency posture execution drill completed successfully.
- [ ] Operator understands the configured posture and its implications.

### Gate 7: Monitoring & Alerting

- [ ] Deployment health endpoint returns healthy: `GET /deployments/{id}/health`.
- [ ] Prometheus metrics scrape endpoint operational: `GET /metrics`.
- [ ] Alert rules configured for: kill switch activation, risk gate rejection, reconciliation discrepancy, adapter disconnection.

### Gate 8: Documentation & Approval

- [ ] Operator has read and signed off on all runbooks (incident-response, deployment-operations, reconciliation-procedures, broker-failover).
- [ ] Promotion request submitted and approved via governance workflow.
- [ ] At least 2 team members have reviewed the deployment configuration.

---

## 2. Promotion Procedure

1. **Verify all gates.** Run through the checklist above. Every item must be checked.
2. **Submit promotion request:**
   ```
   POST /promotions
   {
       "candidate_id": "<deployment_id>",
       "requester_id": "<operator_ulid>",
       "target_environment": "live",
       "rationale": "<business justification>",
       "evidence_link": "<link to drill results / reconciliation reports>"
   }
   ```
3. **Approval.** A different operator (separation of duties) must approve.
4. **Activate live deployment.** Follow the deployment-operations runbook.
5. **First-hour monitoring.** Operator must be on-call and actively monitoring for the first 60 minutes of live trading.

---

## 3. Rollback Criteria

Immediately rollback a live deployment if any of the following occur within the first 5 trading days:

- Daily loss exceeds 50% of the configured `max_daily_loss`.
- Kill switch activated for any reason.
- Reconciliation shows 2+ unresolved discrepancies.
- Drift analysis shows CRITICAL severity on any metric.
- Broker reports an issue with the account or API key.

---

## 4. Gradual Ramp-Up

For new strategies promoted to live:

| Day | Capital Allocation | Position Limit | Notes |
|-----|-------------------|----------------|-------|
| 1-2 | 10% of target | 1 position max | Close monitoring, manual review of every fill |
| 3-5 | 25% of target | 3 positions max | Automated monitoring, daily reconciliation review |
| 6-10 | 50% of target | 5 positions max | Standard monitoring |
| 11+ | 100% of target | Full limits | Normal operations |

Adjust risk limits at each stage via `PUT /risk/deployments/{id}/risk-limits`.

---

## 5. Infrastructure Deployment: Staging → Production

This section covers promoting a new application build (Docker image) from the staging Kubernetes environment to production. This is distinct from strategy promotion (sections 1-4 above), which promotes a trading strategy from paper/shadow to live mode.

### 5.1 Prerequisites

Before beginning an infrastructure promotion:

- The Docker image is built, tagged, and pushed to the container registry.
- The staging environment is running the candidate image.
- All staging acceptance tests have passed in CI.
- The staging environment has been running the candidate for at least 1 hour without errors.

### 5.2 Artifact Storage (MinIO) Verification

Since M6, artifact storage uses MinIO in both staging and production. Before promotion:

- Verify staging MinIO is accessible: `kubectl -n fxlab-staging exec deploy/fxlab-api -- curl -sf http://minio.fxlab-staging.svc.cluster.local:9000/minio/health/live`
- Verify artifact upload/download works: `curl -sf https://staging.fxlab.internal/artifacts?limit=1`
- Verify production MinIO is accessible: `kubectl -n fxlab exec deploy/minio -- mc admin info local`
- Confirm MINIO_ACCESS_KEY and MINIO_SECRET_KEY are set in `api-secrets-production`.

### 5.3 Automated Promotion Pipeline

The `DeploymentPipeline` class in `services/api/infrastructure/deployment_pipeline.py` automates the promotion flow:

```python
from services.api.infrastructure.deployment_pipeline import DeploymentPipeline

pipeline = DeploymentPipeline(
    staging_url="https://staging.fxlab.internal",
    production_namespace="fxlab",
    kubectl_context="prod-cluster",
)

# Step 1: Validate staging health
result = pipeline.validate_staging(correlation_id="deploy-20260412-001")
assert result.all_passed, f"Staging validation failed: {[g.name for g in result.gates if g.status.value == 'failed']}"

# Step 2: Promote (requires manual approval before calling)
record = pipeline.promote_to_production(
    image_tag="v1.2.3",
    correlation_id="deploy-20260412-001",
    approved_by="glenn@fxlab.com",
    validation=result,
)
print(f"Deployment {record.deployment_id} status: {record.status.value}")
```

### 5.4 Manual Promotion Procedure

If the automated pipeline is unavailable:

1. **Validate staging:**
   ```bash
   curl -sf https://staging.fxlab.internal/health
   curl -sf https://staging.fxlab.internal/ready
   ```

2. **Update production image:**
   ```bash
   kubectl --context prod-cluster -n fxlab \
     set image deployment/fxlab-api fxlab-api=fxlab-api:v1.2.3
   ```

3. **Monitor rollout:**
   ```bash
   kubectl --context prod-cluster -n fxlab \
     rollout status deployment/fxlab-api --timeout=300s
   ```

4. **Verify health:**
   ```bash
   kubectl --context prod-cluster -n fxlab \
     get deployment fxlab-api -o jsonpath='{.status.readyReplicas}'
   ```

5. **Smoke test production:**
   ```bash
   curl -sf https://api.fxlab.internal/health
   curl -sf https://api.fxlab.internal/artifacts?limit=1
   ```

### 5.5 Rollback SOP

If health checks fail after deployment:

1. **Automatic rollback** (via pipeline): Triggered automatically if post-deploy health checks fail.

2. **Manual rollback:**
   ```bash
   kubectl --context prod-cluster -n fxlab \
     rollout undo deployment/fxlab-api
   kubectl --context prod-cluster -n fxlab \
     rollout status deployment/fxlab-api --timeout=300s
   ```

3. **Verify rollback succeeded:**
   ```bash
   kubectl --context prod-cluster -n fxlab \
     get deployment fxlab-api -o jsonpath='{.spec.template.spec.containers[0].image}'
   curl -sf https://api.fxlab.internal/health
   ```

4. **Post-mortem:** File an incident report and investigate the failure before reattempting promotion.

### 5.6 Canary Deployment (Future)

For high-risk changes, a canary deployment strategy is recommended:

1. Deploy the new image to a single pod using a separate Deployment resource.
2. Route a small percentage (5-10%) of traffic via weighted Service or Istio VirtualService.
3. Monitor error rates, latency, and resource consumption for 30 minutes.
4. If metrics are within SLO thresholds, proceed with full rollout.
5. If metrics degrade, remove the canary pod and investigate.

This procedure will be automated in a future milestone.

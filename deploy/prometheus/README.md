# FXLab Prometheus Alert Rules

## Overview

This directory contains Prometheus alerting rules for the FXLab quantitative trading platform.

**File**: `alerts.yml` (44 KB, 26 total alerts across 5 alert groups)

## Alert Groups

### 1. Trading Safety Alerts (7 CRITICAL alerts)

Immediate page-on-call alerts protecting financial integrity and risk management:

- **KillSwitchActivationSlow** - Kill switch p99 latency > 500ms (hard safety limit)
- **KillSwitchStateLost** - Kill switch state inconsistency detected
- **OrderSubmissionSlow** - Order submission p95 > 2s
- **OrderErrorRateHigh** - Order rejection rate > 5% for 5m
- **BrokerDisconnected** - Broker adapter health check failing
- **ReconciliationDiscrepancy** - Unresolved reconciliation discrepancies > 0
- **OrphanedOrdersDetected** - Orders in broker but missing in FXLab DB

### 2. API Health Alerts (4 WARNING alerts)

Platform observability and user experience:

- **APIHighLatency** - p95 > 1s for 5m
- **APIErrorRate** - 5xx rate > 1% for 5m
- **APIHighConcurrency** - Connections > 80% of limit
- **RateLimitExhaustion** - Rate limit rejections > 100/min

### 3. Database Alerts (5 alerts: 2 CRITICAL, 3 WARNING)

PostgreSQL availability and stability:

- **PostgresDown** - Database unreachable (CRITICAL, 30s)
- **PostgresHighConnections** - Connections > 80% max (WARNING, 5m)
- **PostgresReplicationLag** - Standby lag > 30s (CRITICAL, 2m)
- **PostgresDiskUsageWarning** - Disk > 80% (WARNING, 5m)
- **PostgresDiskUsageCritical** - Disk > 90% (CRITICAL, 2m)

### 4. Redis Alerts (3 alerts: 1 CRITICAL, 2 WARNING)

Rate limiting and caching availability:

- **RedisDown** - Redis unreachable (CRITICAL, 30s)
- **RedisMemoryHigh** - Memory > 80% of maxmemory (WARNING, 5m)
- **RedisEvictions** - Eviction rate > 100/s (WARNING, 5m)

### 5. Host Alerts (7 alerts: 4 CRITICAL, 3 WARNING)

Infrastructure resource management:

- **HighCPU** - CPU > 80% for 5m (WARNING)
- **HighCPUCritical** - CPU > 95% for 2m (CRITICAL)
- **HighMemory** - Memory > 80% for 5m (WARNING)
- **HighMemoryCritical** - Memory > 95% for 2m (CRITICAL)
- **DiskUsageWarning** - Disk > 85% (WARNING, 5m)
- **DiskUsageCritical** - Disk > 95% (CRITICAL, 2m)
- **ContainerRestarting** - Container > 3 restarts in 15m (WARNING)

## Integration

### Prometheus Configuration

Add to `prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/rules/alerts.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - localhost:9093  # Alertmanager host
```

### Alertmanager Routes

Example routing configuration (in `alertmanager.yml`):

```yaml
routes:
  - match:
      severity: critical
    receiver: trading_oncall
    group_wait: 10s
    group_interval: 10s
    repeat_interval: 1h

  - match:
      severity: warning
    receiver: platform_team
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
```

## Metrics Dependencies

### FXLab Custom Metrics
All defined in `services/api/metrics.py`:
- `orders_submitted_total`, `orders_filled_total`, `orders_rejected_total`
- `kill_switch_mtth_seconds`, `kill_switch_activations_total`
- `order_latency_seconds`, `broker_request_duration_seconds`
- `reconciliation_discrepancies_total`, `circuit_breaker_state`

### Standard Exporters Required
- **Node Exporter**: CPU, memory, disk metrics (`node_*`)
- **PostgreSQL Exporter**: Database metrics (`pg_*`)
- **Redis Exporter**: Cache metrics (`redis_*`)
- **kube-state-metrics**: Kubernetes metrics (`kube_pod_*`)

### Custom Metrics (Must be Instrumented)
Alerts reference these metrics that must be added to the platform:
- `api_http_active_connections` - FastAPI middleware instrumentation
- `api_http_max_connections` - Configuration metric
- `api_http_request_duration_seconds` - HTTP request histogram
- `api_http_requests_total` - HTTP request counter by status code
- `broker_adapter_health_status` - Broker adapter health check (0 or 1)
- `kill_switch_state_inconsistencies_detected` - Audit metric
- `orphaned_orders_detected` - Order reconciliation metric
- `reconciliation_discrepancies_unresolved` - Audit metric

## Severity Levels

| Severity | SLA | Action | Example |
|----------|-----|--------|---------|
| **critical** | 5 min | Page on-call immediately | Kill switch failure, order error rate, broker disconnect |
| **warning** | 30 min | Create ticket, notify team | High API latency, database connection pressure |
| **info** | N/A | Log event | Not used in this ruleset |

## Thresholds & Tuning

Thresholds are calibrated for FXLab's trading requirements:

- **Kill switch latency**: 500ms p99 (hard safety limit to halt all positions)
- **Order submission**: 2s p95 (acceptable latency for order execution)
- **Order error rate**: 5% (indicates systematic rejection issue)
- **API latency**: 1s p95 (dashboard responsiveness)
- **Database replication**: 30s lag (acceptable standby sync)
- **Resource utilization**: 80% warning, 95% critical

**To adjust thresholds**:
1. Edit the `expr` field in the alert
2. Validate YAML: `python3 -c "import yaml; yaml.safe_load(open('alerts.yml'))"`
3. Reload Prometheus: `curl -X POST http://localhost:9090/-/reload`

## Runbook URLs

All alerts reference runbooks at:
```
https://docs.internal.fxlab.ai/runbooks/{component}/{alert_name}/
```

Example: `KillSwitchActivationSlow` → `https://docs.internal.fxlab.ai/runbooks/kill_switch/activation_slow/`

These runbooks must be created separately with:
- Root cause analysis for the alert condition
- Step-by-step mitigation procedures
- How to verify resolution
- Links to related logs, dashboards, and metrics

## Alert Testing

### Validate YAML Syntax
```bash
python3 -c "import yaml; yaml.safe_load(open('alerts.yml')); print('✓ Valid YAML')"
```

### Simulate Alert in Prometheus
```bash
# Test alert expression in Prometheus UI
# http://localhost:9090/graph
# Paste expression: histogram_quantile(0.99, rate(kill_switch_mtth_seconds_bucket[5m])) > 0.5
```

### Dry-run Alertmanager
```bash
amtool config routes --alertmanager-url=http://localhost:9093
amtool alert query --alertmanager-url=http://localhost:9093 severity=critical
```

## Maintenance

### Quarterly Review Checklist

- [ ] Review production baseline metrics (Prometheus dashboards)
- [ ] Verify all thresholds still match observed performance
- [ ] Check alert SLA compliance (% paged within 5 min, % resolved within SLA)
- [ ] Audit false positive rate per alert (should be < 2%)
- [ ] Confirm runbook URLs are accessible and up-to-date
- [ ] Validate all metric collectors are healthy (node exporter, pg exporter, etc)
- [ ] Review on-call feedback for missed alerts or notification fatigue

### Adding New Alerts

1. Identify the alert condition and metric
2. Determine severity and SLA (critical vs warning)
3. Choose appropriate `for` duration (30s-5m typical)
4. Write PromQL expression with labels
5. Add to appropriate alert group
6. Test in Prometheus UI before deploying
7. Create runbook in `docs/runbooks/{component}/{alert_name}/`
8. Validate YAML and commit

### Removing Alerts

If an alert becomes obsolete:
1. Disable it by commenting out (don't delete)
2. Archive to `.archive/alerts_<date>.yml` with a note
3. Document why it's no longer needed
4. Confirm no runbooks or dashboards reference it

## Related Files

- `services/api/metrics.py` - Prometheus metrics definitions
- `.archive/` - Previous alert rule versions (date-stamped)
- `docs/runbooks/` - Alert response procedures (must be created)
- `infra/k8s/prometheus-configmap.yaml` - Prometheus config (if using K8s)

## Support

For questions or issues with alerts:
1. Check Prometheus UI: http://localhost:9090/alerts
2. Review alert expression in Graph tab
3. Check metrics are being scraped: Status → Targets
4. Verify exporters are running: Status → Targets → search by job
5. Consult CLAUDE.md for architecture guidance

---

**Last updated**: April 2026
**Alert count**: 26 total (14 critical, 12 warning)
**File size**: 44 KB

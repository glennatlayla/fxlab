# FXLab Prometheus Metrics Instrumentation Checklist

This file tracks which metrics must be instrumented in the codebase to support
the alert rules defined in `alerts.yml`.

## Status: PARTIAL ✓⚠

**Already defined in services/api/metrics.py**: 23 metrics (100% ✓)
**Custom metrics needed**: 8 metrics (0% — pending implementation)
**External exporters required**: 15+ standard metrics

---

## Section 1: Trading Safety Metrics (Priority: CRITICAL)

These metrics are essential for all kill switch, order, and reconciliation alerts.

### ✓ Already Implemented

- `kill_switch_mtth_seconds` (Histogram) — Mean Time To Halt for kill switch
- `kill_switch_activations_total` (Counter) — Kill switch activations by scope
- `orders_submitted_total` (Counter) — Orders submitted by execution_mode, symbol, side
- `orders_filled_total` (Counter) — Filled orders by execution_mode, symbol
- `orders_rejected_total` (Counter) — Rejected orders by execution_mode, reason
- `order_latency_seconds` (Histogram) — Order submission latency by mode, type
- `reconciliation_runs_total` (Counter) — Reconciliation runs by trigger, status
- `reconciliation_discrepancies_total` (Counter) — Discrepancies by type
- `risk_gate_checks_total` (Counter) — Risk gate evals by check_name, result

### ⚠ Custom Metrics Required

**1. kill_switch_state_inconsistencies_detected** (Gauge)
- **Purpose**: Count unresolved state inconsistencies between FXLab and broker
- **Labels**: None (single-value gauge)
- **Where to instrument**: Kill switch audit/health check service
- **When to update**: After health check runs (increment when inconsistency found)
- **Alert**: `KillSwitchStateLost` (CRITICAL)
- **Runbook**: Add audit method to kill switch service that verifies state consistency

**2. broker_adapter_health_status** (Gauge)
- **Purpose**: Health status of broker adapters (0=down, 1=up)
- **Labels**: `adapter` (string: "alpaca", "schwab", etc)
- **Where to instrument**: Broker adapter health check endpoint
- **When to update**: After every health check call
- **Alert**: `BrokerDisconnected` (CRITICAL)
- **Runbook**: Add /health endpoint to each broker adapter class

**3. orphaned_orders_detected** (Gauge)
- **Purpose**: Count of currently detected orphaned orders
- **Labels**: None (single-value gauge)
- **Where to instrument**: Order reconciliation/audit service
- **When to update**: During reconciliation runs
- **Alert**: `OrphanedOrdersDetected` (CRITICAL)
- **Runbook**: Implement order audit logic to detect mismatches between DB and broker

**4. reconciliation_discrepancies_unresolved** (Gauge)
- **Purpose**: Count of unresolved discrepancies (distinct from total count)
- **Labels**: None (single-value gauge)
- **Where to instrument**: Reconciliation service state
- **When to update**: When discrepancies are found/resolved
- **Alert**: `ReconciliationDiscrepancy` (CRITICAL)
- **Runbook**: Add state field to reconciliation records (status: pending, resolved, escalated)

---

## Section 2: API Health Metrics (Priority: HIGH)

These metrics enable monitoring of API request patterns and performance.

### ✓ Already Implemented

- None (API metrics are infrastructure-level)

### ⚠ Custom Metrics Required

**5. api_http_request_duration_seconds** (Histogram)
- **Purpose**: HTTP request latency distribution (p50, p95, p99)
- **Labels**: `endpoint` (string), `method` (GET, POST, etc), `status` (200, 500, etc)
- **Buckets**: 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0 (seconds)
- **Where to instrument**: FastAPI middleware
- **When to update**: After every request completes
- **Alert**: `APIHighLatency` (WARNING)
- **Implementation**: Use `prometheus_client.Histogram` with middleware decorator
- **Code location**: `services/api/middleware.py` (create if doesn't exist)

**6. api_http_requests_total** (Counter)
- **Purpose**: Total HTTP requests by status code and endpoint
- **Labels**: `endpoint` (string), `method` (GET, POST, etc), `status` (200, 500, etc)
- **Where to instrument**: FastAPI middleware (same as #5)
- **When to update**: After every request completes
- **Alert**: `APIErrorRate` (WARNING)
- **Implementation**: Use `prometheus_client.Counter` with middleware decorator

**7. api_http_active_connections** (Gauge)
- **Purpose**: Current active HTTP connections
- **Labels**: None (single-value gauge)
- **Where to instrument**: FastAPI middleware
- **When to update**: Increment on request start, decrement on request end
- **Alert**: `APIHighConcurrency` (WARNING)
- **Implementation**: Track connection count in middleware

**8. api_http_max_connections** (Gauge)
- **Purpose**: Configured max connections (configuration metric)
- **Labels**: None (single-value gauge)
- **Where to instrument**: API startup/config initialization
- **When to update**: Once on startup
- **Alert**: `APIHighConcurrency` (WARNING, used as denominator)
- **Implementation**: Set from environment variable or config file

---

## Section 3: Standard Exporter Metrics (External Dependencies)

These metrics are provided by standard Prometheus exporters. Ensure these are deployed
and configured to scrape the respective services.

### Node Exporter Metrics
Required for: CPU, memory, disk, network host monitoring

```
node_cpu_seconds_total
node_memory_MemAvailable_bytes
node_memory_MemTotal_bytes
node_filesystem_avail_bytes
node_filesystem_size_bytes
```

**Installation**: https://github.com/prometheus/node_exporter
**Scrape job in prometheus.yml**:
```yaml
- job_name: 'node'
  static_configs:
    - targets: ['localhost:9100']
```

### PostgreSQL Exporter Metrics
Required for: Database availability, connections, replication lag

```
pg_up
pg_stat_activity_count
pg_settings_max_connections
pg_replication_lag_seconds
pg_disk_usage_bytes
pg_disk_capacity_bytes
```

**Installation**: https://github.com/prometheus-community/postgres_exporter
**Scrape job in prometheus.yml**:
```yaml
- job_name: 'postgres'
  static_configs:
    - targets: ['localhost:9187']
```

### Redis Exporter Metrics
Required for: Cache availability, memory, evictions

```
redis_up
redis_memory_used_bytes
redis_maxmemory
redis_evicted_keys_total
redis_keys_total
```

**Installation**: https://github.com/oliver006/redis_exporter
**Scrape job in prometheus.yml**:
```yaml
- job_name: 'redis'
  static_configs:
    - targets: ['localhost:9121']
```

### kube-state-metrics (Kubernetes only)
Required for: Pod/container restart counts, node metrics

```
kube_pod_container_status_restarts_total
```

**Installation**: https://github.com/kubernetes/kube-state-metrics
**Scrape job in prometheus.yml**:
```yaml
- job_name: 'kube-state-metrics'
  static_configs:
    - targets: ['kube-state-metrics:8080']
```

---

## Implementation Plan

### Phase 1: Critical Trading Metrics (Week 1)
- [ ] Implement kill switch state audit (metric #1)
- [ ] Implement broker health check (metric #2)
- [ ] Implement order reconciliation audit (metrics #3, #4)
- [ ] Test with kill switch alerts disabled initially

### Phase 2: API Metrics (Week 2)
- [ ] Implement HTTP middleware for request tracking (metrics #5, #6, #7, #8)
- [ ] Add to FastAPI app startup
- [ ] Test with API latency alerts
- [ ] Verify p95/p99 calculations in Prometheus

### Phase 3: Deploy Exporters (Week 2)
- [ ] Deploy node-exporter to all nodes
- [ ] Deploy postgres-exporter to database server
- [ ] Deploy redis-exporter to Redis instance
- [ ] Verify metrics appear in Prometheus UI

### Phase 4: Alert Enablement (Week 3)
- [ ] Review alert thresholds against production baselines
- [ ] Enable warnings first (low false-positive risk)
- [ ] Monitor for 1 week, tune thresholds
- [ ] Enable critical alerts with escalation to on-call
- [ ] Create and publish runbooks for each alert

### Phase 5: Continuous Improvement
- [ ] Monitor false positive rate per alert
- [ ] Collect on-call feedback
- [ ] Quarterly threshold review
- [ ] Add new alerts as new features ship

---

## Metric Implementation Details

### API Metrics Middleware Example

```python
# services/api/middleware.py
from prometheus_client import Counter, Histogram, Gauge
import time

http_request_duration = Histogram(
    'api_http_request_duration_seconds',
    'HTTP request latency',
    labelnames=['endpoint', 'method', 'status'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

http_requests_total = Counter(
    'api_http_requests_total',
    'Total HTTP requests',
    labelnames=['endpoint', 'method', 'status']
)

http_active_connections = Gauge(
    'api_http_active_connections',
    'Active HTTP connections'
)

http_max_connections = Gauge(
    'api_http_max_connections',
    'Configured max connections'
)

@app.middleware("http")
async def track_metrics(request, call_next):
    http_active_connections.inc()
    start = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start
    endpoint = request.url.path
    method = request.method
    status = response.status_code
    
    http_request_duration.labels(
        endpoint=endpoint,
        method=method,
        status=status
    ).observe(duration)
    
    http_requests_total.labels(
        endpoint=endpoint,
        method=method,
        status=status
    ).inc()
    
    http_active_connections.dec()
    return response

# On startup
http_max_connections.set(int(os.getenv('API_MAX_CONNECTIONS', 100)))
```

### Kill Switch Audit Example

```python
# services/kill_switch/health.py
from prometheus_client import Gauge

kill_switch_state_inconsistencies = Gauge(
    'kill_switch_state_inconsistencies_detected',
    'Count of unresolved state inconsistencies'
)

async def audit_kill_switch_state():
    """Verify kill switch state matches broker reality."""
    inconsistencies = 0
    
    # Check each adapter for state mismatches
    for adapter in self.adapters:
        fxlab_halted = self.storage.is_halted(adapter.id)
        broker_positions = adapter.get_positions()
        
        if fxlab_halted and len(broker_positions) > 0:
            # State inconsistency: marked halted but positions still open
            inconsistencies += 1
            self.logger.error(f"State inconsistency on {adapter.id}")
    
    kill_switch_state_inconsistencies.set(inconsistencies)
```

---

## Verification Checklist

Before enabling alerts in production:

- [ ] All 4 custom metrics (#5-8) implemented in API middleware
- [ ] All 4 trading metrics (#1-4) implemented in their respective services
- [ ] All standard exporters deployed and scraping (node, postgres, redis)
- [ ] Prometheus scrape config includes all jobs
- [ ] `prometheus reload` successful, no config errors
- [ ] Prometheus UI shows all metrics under Status > Targets
- [ ] Prometheus Graph tab can query each metric name
- [ ] Alert expressions can be tested in Graph tab
- [ ] Alertmanager configured with routing to on-call channels
- [ ] Runbooks created and accessible at configured URLs
- [ ] On-call team trained on alert escalation procedures

---

**Next steps**: Start with Phase 1 critical metrics implementation
**Target**: All metrics instrumented and alerts enabled by end of Q2 2026


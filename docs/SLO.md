# FXLab Service Level Objectives (SLOs)

**Version:** 1.0
**Last Updated:** 2026-04-13
**Audience:** Engineering, Operations, Product Management
**Review Cycle:** Quarterly with monthly progress checks

---

## Executive Summary

This document defines measurable Service Level Objectives (SLOs) for the FXLab quantitative trading platform. SLOs establish targets for reliability, performance, and safety — they are internal operational targets, not external SLAs. Breaching an SLO triggers investigation and remediation, not contractual penalties.

FXLab's SLO strategy prioritizes **safety above all else**, followed by **availability** and **latency**. These SLOs are achievable for a single-host Docker deployment with PostgreSQL 15 and Redis 7 backing, and scale to multi-zone deployment with minimal changes to alerting thresholds.

---

## 1. SLO Summary Table

| # | Service | SLI | Target | Window | Alert @ | Consequence |
|---|---------|-----|--------|--------|---------|-------------|
| 1 | Kill Switch | Activation latency P99 | < 500ms | Per activation | 1s | Incident review; assess control-plane latency |
| 2 | Kill Switch | Monthly availability | 99.99% | 30d | 99.98% | Escalation; emergency hardening sprint |
| 3 | Order Submission | Latency P95 | < 2s | 5m | 3s | Investigation; trace broker adapter RTT |
| 4 | Order Submission | Latency P99 | < 5s | 5m | 7s | Page on-call; assess network / broker API degradation |
| 5 | Order State | Reconciliation match rate | 99.9% | 1h | 99.5% | Investigation; audit broker / internal state mismatch |
| 6 | Position Tracking | Accuracy (live mode) | 100% | Per-trade | Any drift | Halt trading; manual audit required |
| 7 | API | Availability | 99.9% | 30d | 99.8% | Incident review; assess downtime budget |
| 8 | API | Latency P50 | < 200ms | 5m | 300ms | Investigation; profile CPU, DB query paths |
| 9 | API | Latency P95 | < 1s | 5m | 2s | Escalation; resource allocation review |
| 10 | API | Latency P99 | < 3s | 5m | 5s | Page on-call; assess systemic bottleneck |
| 11 | API | Error rate (5xx) | < 0.1% | 5m | 0.05% | Incident investigation; fix and deploy hotfix |
| 12 | Authentication | Latency P99 | < 500ms | 5m | 750ms | Investigation; JWT processing or OIDC latency |
| 13 | Database | Availability | 99.95% | 30d | 99.9% | Escalation; failover or recovery sprint |
| 14 | Database | Query latency P95 | < 100ms | 5m | 150ms | Investigation; query plan review, indexing assessment |
| 15 | Redis | Availability | 99.9% | 30d | 99.8% | Incident review; assess cache / rate-limit impact |
| 16 | Backup | Success rate | 100% | 30d | Any failure | Immediate investigation; data integrity audit |
| 17 | Backup | RTO | < 30min | Per-restore | First restore validation | Runbook update, capacity planning review |

---

## 2. Trading Safety SLOs (Highest Priority)

### SLO-1: Kill Switch Activation Latency

**Definition:**
Time from kill switch API request arrival to database state change confirmation (all orders marked CANCELLED, internal state frozen).

**SLI Measurement:**
- **What:** End-to-end wall-clock time from HTTP POST `/api/trading/kill-switch/activate` to successful UPDATE of `trading_orders.status = 'CANCELLED'` for all open orders, plus verification that `trading_session.is_active = false` is persisted.
- **How:** Prometheus histogram `fxlab_kill_switch_activation_latency_seconds` emitted by `KillSwitchService.activate()` after the final DB write succeeds. Buckets: [50ms, 100ms, 200ms, 500ms, 1s, 2s, 5s, 10s].
- **Window:** Per activation (no aggregation; each activation is independent).

**Target:** P99 < 500 ms
**Error Budget:** 0.01% of activations may exceed 500ms in a 30-day window (i.e., 1 out of 10,000 activations).

**Prometheus Query:**
```promql
histogram_quantile(0.99, rate(fxlab_kill_switch_activation_latency_seconds_bucket[5m]))
```

**Alert Rules:**
- **Warning:** If any single activation exceeds 1,000ms (assessed within the activation handler, logged as WARNING).
- **Critical:** If P99 exceeds 500ms over a 5-minute window → page on-call.
- **Postmortem Required:** Any activation exceeding 2,000ms.

**Consequence of Breach:**
- **< 500ms maintained:** No action; system is healthy.
- **500ms–1,000ms:** Review recent code changes; assess database connection pool / lock contention.
- **> 1,000ms:** Incident declared; stop trading, audit system state, assess database or message broker delay.

**Rationale:**
The kill switch is the primary safety mechanism. Traders expect orders to be halted within *one human reaction time* (~500ms). A P99 of 500ms allows for:
- HTTP request parsing and route dispatch: ~10ms
- Authentication / correlation ID setup: ~20ms
- Service logic (fetch open orders): ~50ms
- Database transaction (mark orders as cancelled): ~200ms
- Broker adapter cancellation requests (concurrent, ~3 orders): ~150ms
- Total: ~430ms, leaving 70ms buffer for GC/scheduling.

---

### SLO-2: Kill Switch Monthly Availability

**Definition:**
Percentage of 5-minute intervals in a calendar month during which kill switch activation succeeds (returns HTTP 200 and persists state).

**SLI Measurement:**
- **What:** Binary: activation succeeds (HTTP 200, state persisted) or fails (HTTP 5xx, state not persisted).
- **How:** Prometheus counter `fxlab_kill_switch_activations_total{status="success"}` and `{status="failure"}` incremented in HTTP middleware after response committed.
- **Window:** 30 calendar days.

**Target:** 99.99% (i.e., 4.32 minutes of downtime allowed per month)
**Error Budget:** 10 failed activations per month (assuming 100 activations/month in normal ops; may be higher in high-stress scenarios).

**Prometheus Query:**
```promql
sum(rate(fxlab_kill_switch_activations_total{status="success"}[30d]))
/
sum(rate(fxlab_kill_switch_activations_total[30d]))
```

**Alert Rules:**
- **Warning:** If availability < 99.98% over 7 days.
- **Critical:** If availability < 99.95% over 24 hours → escalate to senior on-call; declare P1 incident.

**Consequence of Breach:**
- **99.99% maintained:** No action.
- **99.95–99.98%:** Schedule post-mortem; increase test coverage for failure scenarios.
- **< 99.95%:** Halt trading; await manual remediation; consider failover to secondary control plane (if deployed).

**Rationale:**
Kill switch is *always critical* — any unavailability threatens the entire position. 99.99% availability allows for rare failures (network blips, brief DB downtime) without impacting trader confidence. Combined with SLO-1 (latency), this ensures both *responsiveness* and *reliability*.

---

### SLO-3: Order Submission Latency (Live Mode)

**Definition:**
Time from order submission API request arrival to broker acknowledgement (HTTP 200 response from broker, order assigned a broker order ID).

**SLI Measurement:**
- **What:** Wall-clock time from `POST /api/trading/orders` request arrival to the broker adapter returning a broker-assigned order ID (e.g., from Alpaca: `order.id`; from Schwab: `order_id`).
- **How:** Prometheus histogram `fxlab_order_submission_latency_seconds{mode="live"}` emitted by `LiveExecutionService.submit_order()` after broker acknowledgement.
- **Buckets:** [10ms, 50ms, 100ms, 500ms, 1s, 2s, 5s, 10s, 30s].
- **Window:** 5-minute aggregation.

**Targets:**
| Percentile | Target | Rationale |
|-----------|--------|-----------|
| P50 | < 500ms | Median order must be fast; includes API overhead + risk gate + broker RPC |
| P95 | < 2s | 95% of orders complete within 2s; allows for transient broker latency |
| P99 | < 5s | 99% of orders complete within 5s; accounts for broker retry (429/5xx + exponential backoff) |

**Error Budget:**
- P50 > 500ms: 0.5% of orders (5 per 1,000)
- P95 > 2s: 5% of orders (50 per 1,000)
- P99 > 5s: 1% of orders (10 per 1,000)

**Prometheus Queries:**
```promql
# P50
histogram_quantile(0.50, rate(fxlab_order_submission_latency_seconds_bucket{mode="live"}[5m]))

# P95
histogram_quantile(0.95, rate(fxlab_order_submission_latency_seconds_bucket{mode="live"}[5m]))

# P99
histogram_quantile(0.99, rate(fxlab_order_submission_latency_seconds_bucket{mode="live"}[5m]))
```

**Alert Rules:**
- **Warning:** P99 > 3s over 5m → investigate broker adapter RTT, network latency.
- **Critical:** P99 > 5s over 5m → page on-call; may indicate broker API degradation or connection pool exhaustion.
- **Critical:** Any single order submission > 10s → log at ERROR; correlate with broker response times.

**Consequence of Breach:**
- **P99 < 5s maintained:** System nominal.
- **5s–10s:** Trace broker request/response times; assess retry backoff policy; consider increasing connection pool.
- **> 10s:** Halt submission; escalate to infrastructure; check broker API status page.

**Rationale:**
Live order submission involves:
1. HTTP parsing + auth: ~20ms
2. Order validation + risk gate evaluation: ~30ms
3. Broker adapter RPC (Alpaca REST): ~100–300ms typical (99th: ~500ms)
4. Order state persistence: ~50ms
5. Retry overhead (on transient failure): ~1s worst-case (2 retries with backoff)

A P99 of 5s budgets 5 seconds, accounting for:
- Network latency spikes (e.g., 50–100ms extra)
- Broker API queuing (peak load)
- 2–3 transient retries on 429/5xx

---

### SLO-4: Order State Reconciliation Match Rate

**Definition:**
Percentage of reconciliation runs (daily, hourly, or manual) that find zero discrepancies between internal order state and broker state.

**SLI Measurement:**
- **What:** For each reconciliation run, compare internal `trading_orders.status` and `trading_orders.filled_qty` against broker's authoritative order state (via `BrokerAdapter.get_orders()`). Count runs with zero mismatches.
- **How:** Prometheus counter `fxlab_reconciliation_runs_total` and `fxlab_reconciliation_discrepancies_total{type="status|filled_qty"}`. Ratio: (total_runs - runs_with_discrepancies) / total_runs.
- **Window:** 1 hour.

**Target:** 99.9% (≤ 1 discrepancy per 1,000 runs)
**Error Budget:** 1 run with discrepancies per 1,000 runs.

**Prometheus Query:**
```promql
(
  sum(rate(fxlab_reconciliation_runs_total[1h]))
  -
  sum(rate(fxlab_reconciliation_runs_total{has_discrepancies="true"}[1h]))
)
/
sum(rate(fxlab_reconciliation_runs_total[1h]))
```

**Alert Rules:**
- **Warning:** Match rate < 99.5% over 1h → investigate broker API latency, stale caches, clock drift.
- **Critical:** Match rate < 99% over 1h → page on-call; audit order state in database vs. broker; prepare manual reconciliation runbook.

**Consequence of Breach:**
- **99.9% maintained:** No action.
- **99.5–99.9%:** Review broker logs; assess whether discrepancies are transient (fills in-flight) or persistent (state corruption).
- **< 99.5%:** Declare incident; stop new orders; audit position accuracy; consider full state resync.

**Rationale:**
Order state must be consistent between internal DB and broker. Discrepancies arise from:
- Network timeouts (order submitted, ACK lost → internal thinks PENDING, broker has FILLED)
- Clock skew (broker time != FXLab time)
- Broker API bugs (rare; reported to Alpaca/Schwab)
- Internal bug (order status updated but not persisted)

99.9% allows 1 discrepancy per 1,000 runs. If reconciliation runs hourly, that's ~1 discrepancy per 41 days, acceptable for investigation.

---

### SLO-5: Position Tracking Accuracy (Live Mode)

**Definition:**
In live trading mode, internal position state (quantity, average cost, P&L) must exactly match broker state. Zero tolerance.

**SLI Measurement:**
- **What:** At every fill event, verify: `internal_position.qty == broker_position.qty` and `internal_position.cost_basis == broker_cost_basis`. Flag any mismatch.
- **How:** Prometheus gauge `fxlab_position_accuracy{symbol,status="match|mismatch"}` updated at every fill; counter `fxlab_position_drift_total` incremented on mismatch.
- **Window:** Per trade.

**Target:** 100% match (zero tolerance for drift in live mode)
**Error Budget:** 0 (any mismatch is a data integrity bug).

**Prometheus Query:**
```promql
# Positions in sync
fxlab_position_accuracy{status="match"}

# Positions with drift
fxlab_position_accuracy{status="mismatch"}
```

**Alert Rules:**
- **Critical (immediate):** Any mismatch → page on-call; declare P0 incident; halt trading.
- **Escalation:** If drift > 0.01% of position size or > 0.001% in notional value → escalate to principal engineer.

**Consequence of Breach:**
- **100% match maintained:** No action; system nominal.
- **Any mismatch:**
  1. Halt all orders immediately (kill switch activation).
  2. Capture current state from broker and database.
  3. Audit transaction logs to identify when divergence began.
  4. Determine root cause (broker API inconsistency, clock skew, internal update bug).
  5. Manual reconciliation to correct state (may require broker support intervention).
  6. Post-mortem required before resuming trading.

**Rationale:**
In live trading, position accuracy is a fundamental invariant. A 0.01% drift on a $1M position = $100 unaccounted-for loss. This SLO enforces that internal state is the *authoritative mirror* of broker state, with zero tolerance for divergence. Unlike order reconciliation (which can tolerate transient discrepancies), position tracking is the *output* of trading — it must be exact.

---

## 3. API Performance SLOs

### SLO-6: API Availability

**Definition:**
Percentage of HTTP requests to any `/api/*` endpoint that return HTTP 2xx or 3xx status (successful response).

**SLI Measurement:**
- **What:** HTTP requests to `/api/*` that complete (receive response header) without timing out. Counted as success if status in {200..399}, failure if status in {500..599} or timeout (> 30s).
- **How:** Prometheus counter `fxlab_http_requests_total{path,status}` incremented in FastAPI middleware after response is sent. Histogram `fxlab_http_request_duration_seconds` for latency.
- **Window:** 30 calendar days.

**Target:** 99.9% (≤ 43.2 minutes downtime per month)
**Error Budget:** 0.1% of requests may fail; i.e., 1 in 1,000 requests.

**Prometheus Queries:**
```promql
# Success rate
sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"2..|3.."}[30d]))
/
sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[30d]))

# 5xx error rate
sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"5.."}[30d]))
/
sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[30d]))
```

**Alert Rules:**
- **Warning:** Availability < 99.95% over 1h → investigate error logs for systematic failures.
- **Critical:** Availability < 99.9% over 4h → page on-call; declare incident.
- **Critical:** Error rate (5xx) > 1% over 5m → immediate investigation; may indicate database overload or uncaught exception.

**Consequence of Breach:**
- **99.9% maintained:** No action.
- **99.5–99.9%:** Post-mortem; identify failure cause; update error handling or resource allocation.
- **< 99.5%:** Incident declared; assess whether to halt trading pending infrastructure fix.

**Rationale:**
99.9% is a standard SLA for cloud services. For a single-host Docker deployment, this is achievable with:
- Health checks every 10s (Kubernetes or load balancer)
- Database connection pooling (prevent conn exhaustion)
- Request rate limiting (prevent thundering herd)
- Graceful shutdown (drain in-flight requests on restart)

---

### SLO-7: API Latency — P50 (Median)

**Definition:**
50th percentile (median) response time for all `/api/*` requests.

**SLI Measurement:**
- **What:** Wall-clock time from HTTP request arrival to response body transmitted.
- **How:** Prometheus histogram `fxlab_http_request_duration_seconds{path,method}` with buckets [10ms, 50ms, 100ms, 200ms, 500ms, 1s, 2s, 5s, 10s].
- **Window:** 5-minute aggregation.

**Target:** < 200 ms
**Error Budget:** 50% of requests may exceed 200ms (i.e., P50 is exactly 200ms); implies 25th percentile must be < 100ms.

**Prometheus Query:**
```promql
histogram_quantile(0.50, rate(fxlab_http_request_duration_seconds_bucket{path=~"/api/.*"}[5m]))
```

**Alert Rules:**
- **Warning:** P50 > 300ms over 5m → investigate CPU usage, database query times; consider caching.
- **Critical:** P50 > 500ms over 5m → page on-call; assess scaling.

**Consequence of Breach:**
- **< 200ms maintained:** No action.
- **200ms–500ms:** Profile request paths; identify slow endpoints; add caching or query optimization.
- **> 500ms:** Incident; assess database connection pool, CPU throttling, GC pauses.

**Rationale:**
P50 latency reflects the *typical* user experience. < 200ms is imperceptible (human perception threshold is ~250ms). This budget allows for:
- API parsing + dispatch: ~10ms
- Service logic (in-memory): ~30ms
- Database query (simple index lookup): ~50ms
- Broker API call (cached): ~50ms
- Response serialization: ~10ms

---

### SLO-8: API Latency — P95 (95th Percentile)

**Definition:**
95th percentile response time for all `/api/*` requests.

**Target:** < 1 second (1,000 ms)
**Error Budget:** 5% of requests may exceed 1s.

**Prometheus Query:**
```promql
histogram_quantile(0.95, rate(fxlab_http_request_duration_seconds_bucket{path=~"/api/.*"}[5m]))
```

**Alert Rules:**
- **Warning:** P95 > 1.5s over 5m.
- **Critical:** P95 > 2s over 5m → page on-call.

**Rationale:**
P95 captures slower-than-average requests (heavier computations, network I/O). 1s is tolerable for latency-sensitive APIs; accounts for broker API calls under load (100–300ms) + retries.

---

### SLO-9: API Latency — P99 (99th Percentile)

**Definition:**
99th percentile response time for all `/api/*` requests.

**Target:** < 3 seconds (3,000 ms)
**Error Budget:** 1% of requests may exceed 3s.

**Prometheus Query:**
```promql
histogram_quantile(0.99, rate(fxlab_http_request_duration_seconds_bucket{path=~"/api/.*"}[5m]))
```

**Alert Rules:**
- **Warning:** P99 > 4s over 5m.
- **Critical:** P99 > 5s over 5m → page on-call.

**Rationale:**
P99 captures worst-case scenarios: broker API retry loops (1–2s), database lock contention, GC pauses. 3s is acceptable for a trading platform; any exceeding indicates systemic issue (database deadlock, broker down, network flap).

---

### SLO-10: API Error Rate (5xx Responses)

**Definition:**
Percentage of HTTP requests returning 5xx status (server error).

**SLI Measurement:**
- **What:** Requests with status in {500, 502, 503, 504, 5xx}.
- **How:** Prometheus counter `fxlab_http_requests_total{status=~"5.."}` from FastAPI middleware.
- **Window:** 5-minute rolling window.

**Target:** < 0.1% (1 error per 1,000 requests)
**Error Budget:** 1 error per 1,000 requests.

**Prometheus Query:**
```promql
sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"5.."}[5m]))
/
sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[5m]))
```

**Alert Rules:**
- **Warning:** Error rate > 0.05% over 5m.
- **Critical:** Error rate > 0.1% over 5m → page on-call; declare SEV-2 incident.
- **Critical (immediate):** Any unhandled exception (status 500) → log at ERROR with full stack trace.

**Consequence of Breach:**
- **< 0.1% maintained:** No action.
- **0.05–0.1%:** Review recent deployments; audit error logs for patterns (e.g., "database connection timeout" repeating).
- **> 0.1%:** Incident; consider rollback; assess database, Redis, or broker API status.

**Rationale:**
5xx errors indicate bugs or infrastructure failures. < 0.1% allows for rare transient failures (database restart, broker API flake) without impacting user experience. Combined with SLO-6 (availability), this ensures a high-quality API.

---

### SLO-11: Authentication Latency

**Definition:**
Time for JWT validation (HS256) or OIDC token exchange (Phase 3+).

**SLI Measurement:**
- **What:** Wall-clock time in `authentication.validate_token()` to verify JWT signature and extract claims.
- **How:** Prometheus histogram `fxlab_auth_latency_seconds{method="jwt|oidc"}` (currently JWT only).
- **Window:** 5-minute aggregation.

**Target (JWT):** P99 < 500 ms
**Target (OIDC, Phase 3):** P99 < 2s (includes token exchange + validation)

**Prometheus Queries:**
```promql
# JWT (current)
histogram_quantile(0.99, rate(fxlab_auth_latency_seconds_bucket{method="jwt"}[5m]))

# OIDC (future)
histogram_quantile(0.99, rate(fxlab_auth_latency_seconds_bucket{method="oidc"}[5m]))
```

**Alert Rules:**
- **Warning:** JWT P99 > 500ms over 5m (indicates GC pressure or high CPU).
- **Warning:** OIDC P99 > 2s over 5m (broker outage or network latency).
- **Critical:** OIDC P99 > 5s over 5m → page on-call; assess OIDC provider status.

**Rationale:**
JWT validation is in the critical path for every API request. It must be < 500ms to not dominate P50 latency. OIDC adds external I/O (token fetch/validate with provider); 2s is reasonable for a distributed system.

---

## 4. Data Infrastructure SLOs

### SLO-12: Database Availability

**Definition:**
Percentage of database connectivity checks that succeed (can execute a trivial query within timeout).

**SLI Measurement:**
- **What:** Every 10s, the health check endpoint executes `SELECT 1` against PostgreSQL. Success = query completes within 5s; failure = timeout or connection refused.
- **How:** Prometheus counter `fxlab_database_health_checks_total{status="success|failure"}` from `/health/db` endpoint.
- **Window:** 30 calendar days.

**Target:** 99.95% (≤ 21.6 seconds downtime per month)
**Error Budget:** 1 database outage per month lasting < 30 seconds, OR 3 outages per month lasting < 10 seconds each.

**Prometheus Query:**
```promql
sum(rate(fxlab_database_health_checks_total{status="success"}[30d]))
/
sum(rate(fxlab_database_health_checks_total[30d]))
```

**Alert Rules:**
- **Warning:** 3 consecutive failed health checks (30s downtime) → investigate database logs.
- **Critical:** 6 consecutive failed health checks (60s downtime) → page on-call; declare SEV-1 incident.
- **Critical (immediate):** Connection pool exhausted (all 20 connections in use for > 5s) → log at ERROR; assess query timeouts or slow queries.

**Consequence of Breach:**
- **99.95% maintained:** No action.
- **99.9–99.95%:** Post-mortem; assess whether to scale up replica or optimize connection pool.
- **< 99.9%:** Incident declared; evaluate failover to standby PostgreSQL or RTO/RPO trade-off.

**Rationale:**
PostgreSQL 15 with async replication can achieve 99.95% uptime on a single host (planned maintenance ~1–2x/month, 15 min each = ~30–60 min/month). This SLO accounts for:
- Planned maintenance: 1–2 instances/month, 15 min each
- Transient connection errors: ~10 per month, ~1–5s each
- Rare hardware failure: 1x per 2+ years

---

### SLO-13: Database Query Latency

**Definition:**
95th percentile response time for database queries (SELECT, INSERT, UPDATE, DELETE).

**SLI Measurement:**
- **What:** Time from query submission to result returned, measured in database client library (SQLAlchemy).
- **How:** Prometheus histogram `fxlab_db_query_duration_seconds{operation="select|insert|update|delete"}` from database repository layer.
- **Buckets:** [5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 5s].
- **Window:** 5-minute aggregation.

**Target:** P95 < 100 ms
**Error Budget:** 5% of queries may exceed 100ms (typically SELECT * on large tables, multi-table joins).

**Prometheus Queries:**
```promql
# Overall P95
histogram_quantile(0.95, rate(fxlab_db_query_duration_seconds_bucket[5m]))

# By operation
histogram_quantile(0.95, rate(fxlab_db_query_duration_seconds_bucket{operation="select"}[5m]))
histogram_quantile(0.95, rate(fxlab_db_query_duration_seconds_bucket{operation="insert"}[5m]))
```

**Alert Rules:**
- **Warning:** P95 > 150ms over 5m → investigate slow query log; check for missing indexes.
- **Critical:** P95 > 250ms over 5m → page on-call; assess table scans, lock contention.

**Consequence of Breach:**
- **< 100ms maintained:** No action.
- **100–250ms:** Review query plans; add indexes on frequently-filtered columns; consider query rewrite.
- **> 250ms:** Incident; halt trading pending database optimization or failover.

**Rationale:**
Database queries dominate API latency (e.g., fetching orders, updating positions). 100ms P95 is aggressive for a single PostgreSQL instance but achievable with:
- Proper indexing (B-tree on order_id, symbol, created_at, status)
- Connection pooling (PgBouncer if needed)
- Query optimization (avoid N+1 problems, use JOIN instead of subqueries)
- Table partitioning (if tables grow > 100M rows)

---

### SLO-14: Redis Availability

**Definition:**
Percentage of Redis operations (SET, GET, INCR, LPUSH) that complete within timeout.

**SLI Measurement:**
- **What:** Every operation to Redis (rate limiting, session cache, broker response cache) must complete or timeout within 2s. Measured at client library level (redis-py).
- **How:** Prometheus counter `fxlab_redis_operations_total{operation="get|set|incr|lpush", status="success|timeout"}`.
- **Window:** 30 calendar days.

**Target:** 99.9% (≤ 43.2 minutes downtime per month)
**Error Budget:** 1 per 1,000 operations may timeout.

**Prometheus Query:**
```promql
sum(rate(fxlab_redis_operations_total{status="success"}[30d]))
/
sum(rate(fxlab_redis_operations_total[30d]))
```

**Alert Rules:**
- **Warning:** Success rate < 99.9% over 1h → investigate Redis memory usage, eviction policy.
- **Critical:** Success rate < 99.5% over 10m → page on-call; assess Redis CPU, network.

**Consequence of Breach:**
- **99.9% maintained:** No action.
- **99.5–99.9%:** Review Redis logs; assess memory pressure (INFO memory); tune maxmemory-policy (e.g., allkeys-lru).
- **< 99.5%:** Incident; may need to scale Redis or defer non-critical cache operations.

**Rationale:**
Redis is used for rate limiting and response caching. Availability of 99.9% is reasonable; cache misses are non-fatal (can fallback to database). However, rate limiting failures should not be tolerated (would allow abuse). Alert specifically on rate limiting timeouts (higher priority).

---

### SLO-15: Backup Success Rate

**Definition:**
Percentage of scheduled daily backups that complete successfully (exported to durable storage, integrity verified).

**SLI Measurement:**
- **What:** Every 24h at 02:00 UTC, automated backup script (`infra/backup/backup.sh`) runs. Success = files written to S3 (or NFS), MD5 checksum verified, log entry written.
- **How:** Prometheus counter `fxlab_backup_success_total` and `fxlab_backup_failure_total` from backup script exit status.
- **Window:** 30 calendar days (e.g., 30 backup attempts).

**Target:** 100% (zero tolerance; every backup must succeed)
**Error Budget:** 0 (any missed backup is a data integrity risk).

**Prometheus Queries:**
```promql
sum(rate(fxlab_backup_success_total[30d]))
/
(sum(rate(fxlab_backup_success_total[30d])) + sum(rate(fxlab_backup_failure_total[30d])))
```

**Alert Rules:**
- **Critical (immediate):** Any backup failure → page on-call; assess disk space, S3 credentials, network connectivity.
- **Critical (escalate):** If 2 consecutive backups fail → declare P0 incident; stop trading pending backup verification.

**Consequence of Breach:**
- **100% maintained:** No action; verify retention policy (keep 7-day rolling backup).
- **Any failure:**
  1. Investigate immediately; assess whether data loss risk exists.
  2. Manual backup override (if automated backup broken).
  3. Post-mortem; update backup monitoring, alert thresholds.

**Rationale:**
Backups are the last line of defense. If backups fail, data loss becomes possible (e.g., ransomware, hardware failure). 100% success rate is non-negotiable. Monitoring must be bulletproof: heartbeat + verification (e.g., can we restore?).

---

### SLO-16: Backup RTO (Recovery Time Objective)

**Definition:**
Time to restore database from backup to a usable state, measured via monthly restore test.

**SLI Measurement:**
- **What:** Last Friday of each month, restore latest backup to staging PostgreSQL. Measure time from restore-start to first SELECT query succeeding.
- **How:** Manual test; record duration in runbook `docs/runbooks/database-backup-restore.md`. Prometheus gauge `fxlab_backup_rto_seconds` updated monthly.
- **Window:** Monthly (1 data point per month).

**Target:** < 30 minutes (1,800 seconds)
**Error Budget:** RTO may be up to 45 minutes for a 50GB+ backup (rare; acceptable if < 1x per quarter).

**Prometheus Query:**
```promql
fxlab_backup_rto_seconds
```

**Alert Rules:**
- **Warning:** If RTO > 30min during monthly test → investigate restore procedure; assess disk I/O, network latency.
- **Critical:** If RTO > 60min → escalate; backup process may be misconfigured.

**Consequence of Breach:**
- **< 30min maintained:** No action; RTO is acceptable.
- **30–45min:** Review restore procedure; identify bottlenecks (e.g., disk I/O, index rebuild); optimize if possible.
- **> 60min:** Incident; update RTO target or backup strategy (e.g., incremental backups, parallel restore).

**Rationale:**
RTO is how long it takes to recover from catastrophic data loss. 30 minutes is a reasonable target for a fintech platform; aligns with "market open" (9:30 AM ET) to "10:00 AM ET" recovery window for US equities trading. Monthly restore drills are mandatory to ensure RTO is not theoretical.

---

## 5. Error Budget Policy

### Monthly Error Budget Allocation

Each SLO has a monthly error budget — the amount of failure tolerated without triggering a breach. Error budgets are *consumed* when SLIs fall below targets.

**Example: API Availability (SLO-6)**
- Target: 99.9% uptime
- Error budget: 0.1% of time = 43.2 minutes per month
- If API experiences 30 minutes of downtime: budget consumed = 30/43.2 = 69%
- Remaining budget: 13.2 minutes

**Example: Order Submission P99 Latency (SLO-3)**
- Target: P99 < 5s
- Error budget: 1% of orders exceeding 5s
- If 1,000 orders submitted and 50 exceed 5s: breach rate = 5% > 1% budget → **SLO BREACHED**

### Burn Rate Alerts

**Burn rate** = (consumption speed of error budget) / (budgeted consumption speed).

If error budget is consumed uniformly over the month:
- Expected daily consumption: 43.2 minutes / 30 days = 1.44 minutes/day (burn rate = 1.0x)

If the SLO breaches *faster* than expected:
- **2x burn rate:** SLO consumed in 15 days instead of 30 → alert **tomorrow** if 2x continues.
- **5x burn rate:** SLO consumed in 6 days → alert **today** (within 1 hour).
- **10x burn rate:** SLO consumed in 3 days → alert **immediately** (P1 incident).

**Prometheus Alert Rules:**

```yaml
# 2x burn rate for API availability over 5 minutes
- alert: APIAvailability2xBurnRate
  expr: |
    (1 - sum(rate(fxlab_http_requests_total{status=~"2..|3.."}[5m]))
         / sum(rate(fxlab_http_requests_total[5m]))) > 0.002
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "API availability burn rate 2x ({{ $value | humanizePercentage }})"
    runbook: "docs/runbooks/incident-response.md"

# 10x burn rate (immediate escalation)
- alert: APIAvailability10xBurnRate
  expr: |
    (1 - sum(rate(fxlab_http_requests_total{status=~"2..|3.."}[1m]))
         / sum(rate(fxlab_http_requests_total[1m]))) > 0.01
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "API availability burn rate 10x — P1 incident ({{ $value | humanizePercentage }})"
    runbook: "docs/runbooks/incident-response.md"
    pagerduty_routing_key: "YOUR_PAGERDUTY_KEY"
```

### What Happens When Budget Is Exhausted

**Before exhaustion (budget remaining):**
- Continue normal operations.
- Investigate and fix issues, but non-critical fixes can be deferred to the next sprint.

**Budget exhausted (0% remaining):**
- **Feature freeze:** Stop adding new features. All engineers shift to reliability improvements.
- **Reliability sprint:** Dedicate 100% of team capacity to understanding and fixing root causes of SLO breaches.
- **Code review intensity:** All commits require 2 reviewers (including a senior engineer) until SLO recovers.
- **Monitoring review:** Audit alerting thresholds; lower alert thresholds if budget was consumed before alerts fired.

**Recovery (budget replenished for next month):**
- Post-mortem on which SLOs were breached; assess whether targets are realistic.
- Plan 1–2 week "hardening sprint" in next month to prevent recurrence.
- Update runbooks and monitoring based on lessons learned.

### Monthly Review Process

**Every 1st of the month (within 24 hours):**

1. **Download SLO metrics for previous month** (script in `infra/monitoring/slo-report.sh`):
   ```bash
   ./infra/monitoring/slo-report.sh 2026-03 > /tmp/slo-march.json
   ```

2. **Populate SLO tracking spreadsheet** (`docs/workplan-tracking/slo-progress.csv`):
   ```
   SLO,Target,Measured,Met?,Budget Used,Remaining,Root Cause
   SLO-1 (Kill Switch Latency),P99<500ms,P99=320ms,YES,0%,100%,—
   SLO-3 (Order Submission),P99<5s,P99=2.5s,YES,0%,100%,—
   SLO-6 (API Availability),99.9%,99.92%,YES,0%,100%,—
   ```

3. **Identify any breaches** (if SLI < target):
   - Root cause analysis: Was it infrastructure (DB down), code bug, or capacity?
   - Fix tracking: Create ticket for each root cause; assign to engineer.
   - Escalation: If multiple SLOs breached, declare reliability incident.

4. **Assess error budget consumption**:
   - If budget > 80% consumed: schedule hardening sprint for next month.
   - If budget < 20% remaining: can accept new features, but with increased testing.

5. **Sign off**: Engineering lead reviews and approves SLO report; shares with product/stakeholders.

**Template:**
```markdown
# SLO Review — March 2026

**Date:** 2026-04-01 10:00 UTC
**Reviewed by:** [Engineering Lead Name]
**Status:** ✅ All SLOs met | ⚠️ 1 SLO at-risk | 🔴 1 SLO breached

## Metric Summary
| SLO | Target | Measured | Status |
|-----|--------|----------|--------|
| Kill Switch Latency (SLO-1) | P99 < 500ms | P99 = 320ms | ✅ |
| Kill Switch Availability (SLO-2) | 99.99% | 99.993% | ✅ |
| Order Submission (SLO-3) | P99 < 5s | P99 = 2.5s | ✅ |
| Reconciliation Match (SLO-4) | 99.9% | 99.88% | 🔴 BREACHED |
| ...

## Notable Findings
- SLO-4 (Reconciliation) breached at 99.88% on March 14–15. Root cause: Alpaca API returned stale fill data (race condition in their system). Reported to Alpaca; issue resolved on March 16.
- SLO-3 (Order Submission) remained healthy; avg P99 latency 2.5s, well within 5s target.
- No P1 incidents related to SLO breaches.

## Actions for Next Month
- Monitor Alpaca fill data freshness; implement client-side validation (reconciliation timeout if fill > 60s old).
- Reduce reconciliation window from 1h to 30m for faster breach detection.

## Decisions
- ✅ Feature development continues (no freeze).
- ⚠️ 1 hardening task: validate fill-time freshness (assign to [Name], due April 15).
```

---

## 6. Measurement & Reporting

### Prometheus Instrumentation

All SLOs are measured via Prometheus metrics emitted by the FXLab backend. Metric definitions are in `src/infrastructure/metrics.py`:

```python
from prometheus_client import Counter, Histogram, Gauge

# Kill switch latency (SLO-1)
kill_switch_activation_latency = Histogram(
    'fxlab_kill_switch_activation_latency_seconds',
    'Time from activation request to DB state change confirmation',
    buckets=[0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10],
)

# Order submission latency (SLO-3)
order_submission_latency = Histogram(
    'fxlab_order_submission_latency_seconds',
    'Time from order submission request to broker acknowledgement',
    labelnames=['mode'],  # live, paper, shadow
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30],
)

# API request metrics (SLO-6 to SLO-11)
http_requests_total = Counter(
    'fxlab_http_requests_total',
    'Total HTTP requests',
    labelnames=['path', 'method', 'status'],
)

http_request_duration_seconds = Histogram(
    'fxlab_http_request_duration_seconds',
    'HTTP request duration',
    labelnames=['path', 'method'],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10],
)

# Database metrics (SLO-12, SLO-13)
db_query_duration_seconds = Histogram(
    'fxlab_db_query_duration_seconds',
    'Database query duration',
    labelnames=['operation'],  # select, insert, update, delete
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 5],
)

# Backup metrics (SLO-15, SLO-16)
backup_success_total = Counter(
    'fxlab_backup_success_total',
    'Successful backups',
)

backup_failure_total = Counter(
    'fxlab_backup_failure_total',
    'Failed backups',
)
```

### Grafana Dashboards

**Dashboard: SLO Overview** (`infra/observability/grafana-slo-dashboard.json`)

Displays real-time status of all SLOs:
- **Left column:** Kill switch (SLO-1, SLO-2) — large, red if critical.
- **Middle column:** Order submission (SLO-3), Reconciliation (SLO-4), Position tracking (SLO-5).
- **Right column:** API metrics (SLO-6 to SLO-11).
- **Bottom row:** Infrastructure (database, Redis, backups).

Each SLO panel shows:
- **Current value** (large font)
- **Target** (green line)
- **Alert threshold** (orange/red line)
- **30-day trend** (historical view)

**Dashboard: API Latency Breakdown** (`infra/observability/grafana-api-latency.json`)

Drill-down dashboard for API latency (SLO-7 to SLO-11):
- **P50, P95, P99 latency** per endpoint (bar chart)
- **Error rate** per endpoint (line graph)
- **Request volume** per endpoint (heat map)
- **Slowest endpoints** (table sorted by P99)

**Dashboard: Database Performance** (`infra/observability/grafana-database.json`)

Monitor database health (SLO-12, SLO-13):
- **Connection pool usage** (% in-use)
- **Query latency** by operation (SELECT, INSERT, UPDATE, DELETE)
- **Slow query log** (table of slowest 10 queries)
- **Table/index sizes** (growth trend)

---

### Alert Configuration

All alerts are defined in `infra/alerting/prometheus-rules.yaml`:

```yaml
groups:
  - name: fxlab-slo
    interval: 30s
    rules:
      # SLO-1: Kill Switch Latency
      - alert: KillSwitchLatencyWarning
        expr: histogram_quantile(0.99, rate(fxlab_kill_switch_activation_latency_seconds_bucket[5m])) > 1.0
        for: 1m
        labels:
          severity: warning
          slo: "SLO-1"
        annotations:
          summary: "Kill switch P99 latency > 1s ({{ $value | humanizeDuration }})"
          runbook: "docs/runbooks/incident-response.md#kill-switch-latency"

      - alert: KillSwitchLatencyCritical
        expr: histogram_quantile(0.99, rate(fxlab_kill_switch_activation_latency_seconds_bucket[5m])) > 2.0
        for: 30s
        labels:
          severity: critical
          slo: "SLO-1"
        annotations:
          summary: "Kill switch P99 latency > 2s — CRITICAL ({{ $value | humanizeDuration }})"
          runbook: "docs/runbooks/incident-response.md#kill-switch-latency"

      # SLO-2: Kill Switch Availability
      - alert: KillSwitchAvailabilityWarning
        expr: |
          (sum(rate(fxlab_kill_switch_activations_total{status="success"}[7d]))
           / sum(rate(fxlab_kill_switch_activations_total[7d]))) < 0.9998
        for: 10m
        labels:
          severity: warning
          slo: "SLO-2"
        annotations:
          summary: "Kill switch availability < 99.98% over 7 days"
          runbook: "docs/runbooks/incident-response.md#kill-switch-availability"

      # SLO-3: Order Submission Latency
      - alert: OrderSubmissionLatencyWarning
        expr: histogram_quantile(0.99, rate(fxlab_order_submission_latency_seconds_bucket{mode="live"}[5m])) > 3.0
        for: 5m
        labels:
          severity: warning
          slo: "SLO-3"
        annotations:
          summary: "Order submission P99 latency > 3s ({{ $value | humanizeDuration }})"
          runbook: "docs/runbooks/incident-response.md#order-submission-latency"

      - alert: OrderSubmissionLatencyCritical
        expr: histogram_quantile(0.99, rate(fxlab_order_submission_latency_seconds_bucket{mode="live"}[5m])) > 5.0
        for: 2m
        labels:
          severity: critical
          slo: "SLO-3"
        annotations:
          summary: "Order submission P99 latency > 5s — CRITICAL ({{ $value | humanizeDuration }})"
          runbook: "docs/runbooks/incident-response.md#order-submission-latency"

      # SLO-4: Reconciliation Match Rate
      - alert: ReconciliationMatchRateWarning
        expr: |
          (sum(rate(fxlab_reconciliation_runs_total[1h]))
           - sum(rate(fxlab_reconciliation_runs_total{has_discrepancies="true"}[1h])))
          / sum(rate(fxlab_reconciliation_runs_total[1h]))
          < 0.995
        for: 10m
        labels:
          severity: warning
          slo: "SLO-4"
        annotations:
          summary: "Reconciliation match rate < 99.5%"
          runbook: "docs/runbooks/reconciliation-procedures.md"

      # SLO-5: Position Tracking Accuracy (CRITICAL)
      - alert: PositionDrift
        expr: fxlab_position_accuracy{status="mismatch"} > 0
        for: 1s  # Immediate alert
        labels:
          severity: critical
          slo: "SLO-5"
        annotations:
          summary: "Position drift detected — HALT TRADING ({{ $value }} symbols)"
          runbook: "docs/runbooks/incident-response.md#position-drift"

      # SLO-6: API Availability
      - alert: APIAvailabilityWarning
        expr: |
          sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"2..|3.."}[1h]))
          / sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[1h])) < 0.9995
        for: 10m
        labels:
          severity: warning
          slo: "SLO-6"
        annotations:
          summary: "API availability < 99.95%"

      - alert: APIAvailabilityCritical
        expr: |
          sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"2..|3.."}[4h]))
          / sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[4h])) < 0.999
        for: 30m
        labels:
          severity: critical
          slo: "SLO-6"
        annotations:
          summary: "API availability < 99.9% over 4 hours — CRITICAL"

      # SLO-7 to SLO-9: API Latency (P50, P95, P99)
      - alert: APILatencyP50Warning
        expr: histogram_quantile(0.50, rate(fxlab_http_request_duration_seconds_bucket{path=~"/api/.*"}[5m])) > 0.3
        for: 5m
        labels:
          severity: warning
          slo: "SLO-7"
        annotations:
          summary: "API P50 latency > 300ms ({{ $value | humanizeDuration }})"

      - alert: APILatencyP99Critical
        expr: histogram_quantile(0.99, rate(fxlab_http_request_duration_seconds_bucket{path=~"/api/.*"}[5m])) > 5.0
        for: 2m
        labels:
          severity: critical
          slo: "SLO-9"
        annotations:
          summary: "API P99 latency > 5s — CRITICAL ({{ $value | humanizeDuration }})"

      # SLO-10: API Error Rate
      - alert: API5xxErrorRateWarning
        expr: |
          sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"5.."}[5m]))
          / sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[5m])) > 0.0005
        for: 5m
        labels:
          severity: warning
          slo: "SLO-10"
        annotations:
          summary: "API 5xx error rate > 0.05% ({{ $value | humanizePercentage }})"

      - alert: API5xxErrorRateCritical
        expr: |
          sum(rate(fxlab_http_requests_total{path=~"/api/.*", status=~"5.."}[5m]))
          / sum(rate(fxlab_http_requests_total{path=~"/api/.*"}[5m])) > 0.001
        for: 2m
        labels:
          severity: critical
          slo: "SLO-10"
        annotations:
          summary: "API 5xx error rate > 0.1% — CRITICAL ({{ $value | humanizePercentage }})"

      # SLO-12: Database Availability
      - alert: DatabaseHealthCheckFailing
        expr: |
          sum(rate(fxlab_database_health_checks_total{status="failure"}[10m]))
          / sum(rate(fxlab_database_health_checks_total[10m])) > 0.1
        for: 5m
        labels:
          severity: critical
          slo: "SLO-12"
        annotations:
          summary: "Database health checks failing > 10% — CRITICAL"
          runbook: "docs/runbooks/database-backup-restore.md"

      # SLO-15: Backup Success Rate
      - alert: BackupFailure
        expr: fxlab_backup_failure_total > 0
        for: 1m
        labels:
          severity: critical
          slo: "SLO-15"
        annotations:
          summary: "Backup failed — IMMEDIATE investigation required"
          runbook: "docs/runbooks/database-backup-restore.md"
```

---

### SLO Reporting & Dashboard

**Monthly SLO Report** (automated via `infra/monitoring/slo-report.sh`):

```bash
#!/bin/bash
# Generate monthly SLO report from Prometheus

MONTH=$1  # e.g., 2026-03
START_DATE="2026-03-01T00:00:00Z"
END_DATE="2026-04-01T00:00:00Z"

echo "# SLO Report — $MONTH"
echo ""

# SLO-1: Kill Switch Latency
echo "## SLO-1: Kill Switch Activation Latency (P99 < 500ms)"
curl -s "http://prometheus:9090/api/v1/query" \
  --data-urlencode "query=histogram_quantile(0.99, rate(fxlab_kill_switch_activation_latency_seconds_bucket[$MONTH]))" \
  | jq '.data.result[0].value[1]' | xargs printf "**Measured:** %s ms\n"
echo ""

# SLO-2: Kill Switch Availability
echo "## SLO-2: Kill Switch Monthly Availability (Target: 99.99%)"
curl -s "http://prometheus:9090/api/v1/query" \
  --data-urlencode "query=(sum(rate(fxlab_kill_switch_activations_total{status=\"success\"}[$MONTH])) / sum(rate(fxlab_kill_switch_activations_total[$MONTH]))) * 100" \
  | jq '.data.result[0].value[1]' | xargs printf "**Measured:** %s %%\n"
echo ""

# ... repeat for all SLOs ...

echo "## Summary"
echo "Generated: $(date -u)"
```

Run this script on the 1st of every month to auto-populate the SLO report.

---

## Appendix A: SLO Definition Reference

| SLO # | Name | Target | Measurement | Alert Threshold | Runbook |
|-------|------|--------|-------------|-----------------|---------|
| 1 | Kill Switch Latency | P99 < 500ms | Per activation | > 1s | `incident-response.md#kill-switch` |
| 2 | Kill Switch Availability | 99.99% | 30d | < 99.98% over 7d | `incident-response.md#kill-switch` |
| 3 | Order Submission Latency | P99 < 5s | Live mode, 5m window | > 3s | `incident-response.md#order-submission` |
| 4 | Reconciliation Match Rate | 99.9% | 1h window | < 99.5% | `reconciliation-procedures.md` |
| 5 | Position Tracking Accuracy | 100% | Per trade, live | Any drift | `incident-response.md#position-drift` |
| 6 | API Availability | 99.9% | 30d | < 99.8% over 1h | `incident-response.md#api-availability` |
| 7 | API Latency P50 | < 200ms | 5m window | > 300ms | `incident-response.md#api-latency` |
| 8 | API Latency P95 | < 1s | 5m window | > 2s | `incident-response.md#api-latency` |
| 9 | API Latency P99 | < 3s | 5m window | > 5s | `incident-response.md#api-latency` |
| 10 | API Error Rate (5xx) | < 0.1% | 5m window | > 0.1% | `incident-response.md#api-errors` |
| 11 | Auth Latency (JWT) | P99 < 500ms | 5m window | > 500ms | `incident-response.md#auth` |
| 12 | Database Availability | 99.95% | 30d | < 99.9% over 1h | `database-backup-restore.md` |
| 13 | Database Query Latency | P95 < 100ms | 5m window | > 150ms | `database-backup-restore.md` |
| 14 | Redis Availability | 99.9% | 30d | < 99.5% over 1h | `incident-response.md#redis` |
| 15 | Backup Success Rate | 100% | Per backup (daily) | Any failure | `database-backup-restore.md` |
| 16 | Backup RTO | < 30min | Monthly restore test | > 45min | `database-backup-restore.md` |

---

## Appendix B: SLO Achievability on Single-Host Deployment

This document targets a **single-host Docker deployment** with:
- PostgreSQL 15 on local SSD
- Redis 7 (in-memory)
- FastAPI backend (4 worker processes)
- Nginx reverse proxy

**Achievable SLOs:**
- ✅ Kill switch latency (P99 < 500ms): Achievable; local DB calls are ~50–200ms.
- ✅ API availability (99.9%): Achievable; Uptime of 99.9% = 43min/month downtime, realistic with planned maintenance 1–2x/month.
- ✅ API latency (P99 < 3s): Achievable; local I/O dominates.
- ✅ Database availability (99.95%): Achievable with async replication (standby).
- ⚠️ Broker failover (SLO-5): Depends on Alpaca/Schwab API reliability (external).
- ✅ Backup success (100%): Achievable with heartbeat monitoring + local verification.

**Scaling considerations:**
- Multi-zone deployment: SLOs become stricter (add 50–100ms network latency for inter-zone calls).
- Horizontally-scaled API: SLOs become tighter (adds load-balancer latency, potential cache coherency issues).
- Database replication lag: Monitor replication lag; alert if > 1s.

---

## Appendix C: SLO Review Checklist

Use this checklist at every monthly SLO review:

```markdown
# Monthly SLO Review Checklist

**Month:** ________________
**Reviewed by:** ________________
**Date:** ________________

## Data Collection
- [ ] Downloaded Prometheus metrics for the entire month (via `slo-report.sh`).
- [ ] Verified data completeness (no gaps in time series).
- [ ] Confirmed all alert rules fired as expected (audit PagerDuty/Slack logs).

## SLO Assessment
- [ ] SLO-1 (Kill Switch Latency): P99 = ___ ms (target: < 500ms) → **PASS / FAIL**
- [ ] SLO-2 (Kill Switch Availability): ___ % (target: 99.99%) → **PASS / FAIL**
- [ ] SLO-3 (Order Submission): P99 = ___ s (target: < 5s) → **PASS / FAIL**
- [ ] SLO-4 (Reconciliation Match): ___ % (target: 99.9%) → **PASS / FAIL**
- [ ] SLO-5 (Position Accuracy): ___ matches (target: 100%) → **PASS / FAIL**
- [ ] SLO-6 (API Availability): ___ % (target: 99.9%) → **PASS / FAIL**
- [ ] SLO-7 (API P50 Latency): ___ ms (target: < 200ms) → **PASS / FAIL**
- [ ] SLO-8 (API P95 Latency): ___ ms (target: < 1s) → **PASS / FAIL**
- [ ] SLO-9 (API P99 Latency): ___ ms (target: < 3s) → **PASS / FAIL**
- [ ] SLO-10 (API 5xx Error Rate): ___ % (target: < 0.1%) → **PASS / FAIL**
- [ ] SLO-11 (Auth Latency): P99 = ___ ms (target: < 500ms) → **PASS / FAIL**
- [ ] SLO-12 (Database Availability): ___ % (target: 99.95%) → **PASS / FAIL**
- [ ] SLO-13 (Database Query Latency): P95 = ___ ms (target: < 100ms) → **PASS / FAIL**
- [ ] SLO-14 (Redis Availability): ___ % (target: 99.9%) → **PASS / FAIL**
- [ ] SLO-15 (Backup Success Rate): ___ % (target: 100%) → **PASS / FAIL**
- [ ] SLO-16 (Backup RTO): ___ min (target: < 30min) → **PASS / FAIL**

## Incident Analysis
- [ ] List all incidents triggered by SLO breaches this month:
  - Incident #1: ________________ (root cause: ________)
  - Incident #2: ________________ (root cause: ________)
- [ ] Were all incidents recorded in incident tracking system (Jira/Linear)?
- [ ] Do all incidents have post-mortems assigned? (Due date: within 1 week)

## Error Budget Review
- [ ] Calculate budget consumed for each SLO (see table below).
- [ ] If any SLO consumed > 80% of budget: Schedule hardening sprint for next month.
- [ ] If any SLO consumed 100% of budget: Declare reliability incident; freeze features.

| SLO | Budget | Consumed | % Used | Status |
|-----|--------|----------|--------|--------|
| SLO-1 | _____ | _____ | _____ | 🟢/🟡/🔴 |
| SLO-2 | _____ | _____ | _____ | 🟢/🟡/🔴 |
| ... |

## Action Items for Next Month
- [ ] Item 1: ________________ (assign to: ________, due: ________)
- [ ] Item 2: ________________ (assign to: ________, due: ________)

## Sign-Off
- [ ] Engineering lead: ________________ (date: ________)
- [ ] Product: ________________ (date: ________)

## Scheduling Next Review
- [ ] Date: ____________ (1st of next month, 10:00 UTC)
- [ ] Attendees: Engineering lead, on-call engineer, product manager
- [ ] Duration: 30–45 minutes
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-13 | Engineering | Initial SLO framework; 16 SLOs defined across safety, API, and infrastructure. |

---

**Last Updated:** 2026-04-13
**Next Review:** 2026-05-01 (monthly SLO review)

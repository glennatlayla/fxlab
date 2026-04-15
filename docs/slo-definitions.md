# FXLab Service Level Objectives (SLOs)

## Overview

This document defines the business-level SLOs for the FXLab execution layer.
Each SLO is measurable from Prometheus metrics emitted by the instrumented
services (M15). The Grafana dashboard (`infra/observability/grafana-execution-dashboard.json`)
visualizes these SLOs in real time.

SLOs are internal engineering targets, not external SLAs. Breaching an SLO
triggers investigation, not contractual penalties.

## SLO Definitions

### SLO-1: Order Submission Latency

The time from when a service method receives an order to when the broker
adapter acknowledges submission (or the paper adapter processes it).

| Mode | Percentile | Target | Metric |
|------|-----------|--------|--------|
| Paper | P99 | < 500ms | `histogram_quantile(0.99, rate(order_latency_seconds_bucket{execution_mode="paper"}[5m]))` |
| Shadow | P99 | < 500ms | `histogram_quantile(0.99, rate(order_latency_seconds_bucket{execution_mode="shadow"}[5m]))` |
| Live (Alpaca) | P99 | < 2s | `histogram_quantile(0.99, rate(order_latency_seconds_bucket{execution_mode="live"}[5m]))` |

Rationale: Paper and shadow execute in-process; live involves a network round
trip to Alpaca's REST API. The 2s target accounts for network latency,
retries on 429/5xx, and order acknowledgement time.

Alert threshold: Fire warning at P99 > 1s (paper/shadow) or P99 > 3s (live).
Fire critical at P99 > 2s (paper/shadow) or P99 > 5s (live).

### SLO-2: Kill Switch Mean Time To Halt (MTTH)

The time from kill switch activation to verified halt (all open orders
cancelled or emergency posture executed).

| Percentile | Target | Metric |
|-----------|--------|--------|
| P99 | < 5s | `histogram_quantile(0.99, rate(kill_switch_mtth_seconds_bucket[1h]))` |
| P50 | < 1s | `histogram_quantile(0.50, rate(kill_switch_mtth_seconds_bucket[1h]))` |

Rationale: The kill switch is a safety-critical mechanism. Operators expect
halts to take effect within seconds. The 5s P99 target accounts for retry
loops when cancelling stubborn orders or flattening positions.

Alert threshold: Fire critical if any single activation exceeds 10s. Fire
warning if P99 > 5s over a 1-hour window.

### SLO-3: Reconciliation Discrepancy Rate

The fraction of reconciliation runs that find discrepancies between
internal state and broker state.

| Metric | Target | Calculation |
|--------|--------|-------------|
| Discrepancy rate | < 0.1% | `sum(rate(reconciliation_discrepancies_total[1h])) / sum(rate(reconciliation_runs_total[1h]))` |

Rationale: In a well-functioning system, internal order/position state
should match broker state. Discrepancies indicate bugs, missed fills,
stale caches, or broker-side corrections. A rate above 0.1% suggests a
systemic issue requiring investigation.

Alert threshold: Fire warning at > 0.1% discrepancy rate over 1 hour.
Fire critical at > 1% discrepancy rate over 1 hour.

### SLO-4: API Availability

The fraction of health check probes that return 200 (healthy).

| Metric | Target | Calculation |
|--------|--------|-------------|
| Availability | > 99.9% | `sum(rate(http_requests_total{path="/health",status="200"}[30d])) / sum(rate(http_requests_total{path="/health"}[30d]))` |

Rationale: 99.9% availability allows ~43 minutes of downtime per month.
This is a reasonable target for a platform that handles non-real-time
batch strategy execution. Live trading deployments may require 99.99%.

Note: This SLO requires HTTP request metrics (e.g., from FastAPI
middleware or a reverse proxy). If using Kubernetes, the liveness probe
failure count from the kubelet is an alternative signal.

Alert threshold: Fire warning at < 99.95% over 1 hour. Fire critical
at < 99.9% over 24 hours.

## Measurement Infrastructure

All SLOs are measured from Prometheus metrics scraped from the `/metrics`
endpoint. The metrics are emitted by:

- `services/api/metrics.py` — metric definitions
- `services/api/services/paper_execution_service.py` — order latency, submission counts
- `services/api/services/shadow_execution_service.py` — order latency, submission counts
- `services/api/services/kill_switch_service.py` — MTTH histogram, activation counter
- `services/api/services/reconciliation_service.py` — run counter, discrepancy counter
- `services/api/services/risk_gate_service.py` — check counter by result
- `services/api/infrastructure/resilient_adapter.py` — broker request duration

## SLO Review Cadence

SLOs should be reviewed quarterly against actual production data. Adjust
targets based on observed baselines and business requirements. Overly
tight SLOs create alert fatigue; overly loose SLOs mask degradation.

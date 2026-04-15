"""
Prometheus metrics instrumentation for FXLab API.

Purpose:
    Define all Prometheus metrics (Counters, Histograms, Gauges) required
    by Phase 3 spec §15 and Phase 5 M15, and expose them via a /metrics
    endpoint for Prometheus scraping.

Responsibilities:
    - Define governance counters (approval, override, chart, export, autosave).
    - Define execution counters (orders submitted/filled/rejected).
    - Define execution histograms (order latency, kill switch MTTH, broker duration).
    - Define execution gauges (circuit breaker state, positions total).
    - Provide a FastAPI route that serves Prometheus exposition format.
    - Metrics are incremented/observed/set by service and route handlers at
      decision points via direct import.

Does NOT:
    - Contain business logic.
    - Manage Prometheus scrape configuration or alerting rules.
    - Implement collection logic — callers instrument themselves.

Dependencies:
    - prometheus_client: Counter, Histogram, Gauge, generate_latest,
      CONTENT_TYPE_LATEST.
    - FastAPI: APIRouter, Response.

Error conditions:
    - None — /metrics always returns 200 with current metric state.

Example:
    from services.api.metrics import ORDERS_SUBMITTED_TOTAL, ORDER_LATENCY_SECONDS
    ORDERS_SUBMITTED_TOTAL.labels(execution_mode="paper", symbol="AAPL", side="buy").inc()
    ORDER_LATENCY_SECONDS.labels(execution_mode="paper", order_type="market").observe(0.042)

    # Scrape: GET /metrics → text/plain Prometheus exposition
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Prometheus counters — Phase 3 spec §15
# ---------------------------------------------------------------------------

APPROVAL_REQUESTS_TOTAL = Counter(
    "approval_requests_total",
    "Total approval actions (approve/reject) processed",
    labelnames=["request_type", "status"],
)

OVERRIDE_REQUESTS_TOTAL = Counter(
    "override_requests_total",
    "Total override requests submitted to governance gates",
    labelnames=["governance_gate", "status"],
)

CHART_CACHE_HITS_TOTAL = Counter(
    "chart_cache_hits_total",
    "Total chart data cache hits (SQL cache layer)",
)

CHART_CACHE_MISSES_TOTAL = Counter(
    "chart_cache_misses_total",
    "Total chart data cache misses",
)

LTTB_APPLIED_TOTAL = Counter(
    "lttb_applied_total",
    "Total number of LTTB downsampling operations applied to chart data",
)

EXPORT_REQUESTS_TOTAL = Counter(
    "export_requests_total",
    "Total artifact export/download requests",
    labelnames=["format", "export_type"],
)

DRAFT_AUTOSAVES_TOTAL = Counter(
    "draft_autosaves_total",
    "Total draft autosave operations persisted",
)

# ---------------------------------------------------------------------------
# Execution metrics — Phase 5 M15
# ---------------------------------------------------------------------------

# -- Counters: order lifecycle events ---------------------------------------

ORDERS_SUBMITTED_TOTAL = Counter(
    "orders_submitted_total",
    "Total orders submitted to broker adapters",
    labelnames=["execution_mode", "symbol", "side"],
)

ORDERS_FILLED_TOTAL = Counter(
    "orders_filled_total",
    "Total orders that reached filled status",
    labelnames=["execution_mode", "symbol"],
)

ORDERS_REJECTED_TOTAL = Counter(
    "orders_rejected_total",
    "Total orders rejected (by risk gate, broker, or validation)",
    labelnames=["execution_mode", "reason"],
)

# -- Counters: safety and reconciliation ------------------------------------

KILL_SWITCH_ACTIVATIONS_TOTAL = Counter(
    "kill_switch_activations_total",
    "Total kill switch activations by scope (deployment, global)",
    labelnames=["scope"],
)

RECONCILIATION_RUNS_TOTAL = Counter(
    "reconciliation_runs_total",
    "Total reconciliation runs completed",
    labelnames=["trigger", "status"],
)

RECONCILIATION_DISCREPANCIES_TOTAL = Counter(
    "reconciliation_discrepancies_total",
    "Total reconciliation discrepancies detected, by type",
    labelnames=["type"],
)

RISK_GATE_CHECKS_TOTAL = Counter(
    "risk_gate_checks_total",
    "Total risk gate evaluations (pass and fail)",
    labelnames=["check_name", "result"],
)

# -- Histograms: latency and duration metrics --------------------------------

# Bucket boundaries chosen for trading latency:
# fine-grained sub-second for order submission, coarser for slower ops.
_ORDER_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
)

ORDER_LATENCY_SECONDS = Histogram(
    "order_latency_seconds",
    "Time from order submission to broker acknowledgement, in seconds",
    labelnames=["execution_mode", "order_type"],
    buckets=_ORDER_LATENCY_BUCKETS,
)

_KILL_SWITCH_MTTH_BUCKETS = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    3.0,
    5.0,
    10.0,
    15.0,
    30.0,
)

KILL_SWITCH_MTTH_SECONDS = Histogram(
    "kill_switch_mtth_seconds",
    "Mean Time To Halt — seconds from kill switch activation to verified halt",
    buckets=_KILL_SWITCH_MTTH_BUCKETS,
)

_BROKER_REQUEST_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
)

BROKER_REQUEST_DURATION_SECONDS = Histogram(
    "broker_request_duration_seconds",
    "Duration of individual broker adapter REST API calls",
    labelnames=["adapter", "method"],
    buckets=_BROKER_REQUEST_BUCKETS,
)

# -- Gauges: point-in-time state metrics ------------------------------------

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state: 0=closed (healthy), 1=open (tripped), 2=half_open",
    labelnames=["adapter_id", "state"],
)

POSITIONS_TOTAL = Gauge(
    "positions_total",
    "Current open position count per deployment",
    labelnames=["deployment_id"],
)

# ---------------------------------------------------------------------------
# Market data pipeline metrics — Phase 7 M1
# ---------------------------------------------------------------------------

MARKET_DATA_CANDLES_COLLECTED_TOTAL = Counter(
    "market_data_candles_collected_total",
    "Total OHLCV candles collected from market data providers",
    labelnames=["provider", "symbol", "interval"],
)

MARKET_DATA_COLLECTION_ERRORS_TOTAL = Counter(
    "market_data_collection_errors_total",
    "Total errors during market data collection, by symbol and error type",
    labelnames=["provider", "symbol", "error_type"],
)

MARKET_DATA_GAPS_DETECTED_TOTAL = Counter(
    "market_data_gaps_detected_total",
    "Total data gaps detected after market data collection",
    labelnames=["symbol", "interval"],
)

_COLLECTION_DURATION_BUCKETS = (
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
)

MARKET_DATA_COLLECTION_DURATION_SECONDS = Histogram(
    "market_data_collection_duration_seconds",
    "Duration of a full market data collection run, in seconds",
    labelnames=["provider", "interval"],
    buckets=_COLLECTION_DURATION_BUCKETS,
)

# ---------------------------------------------------------------------------
# Safety, health, and API operational metrics — alerts.yml / Phase 5 M15
# ---------------------------------------------------------------------------

# -- Gauges: kill switch and broker health -----------------------------------

KILL_SWITCH_STATE_INCONSISTENCIES_DETECTED = Gauge(
    "kill_switch_state_inconsistencies_detected",
    "Unresolved kill switch state mismatches detected by reconciliation",
)

BROKER_ADAPTER_HEALTH_STATUS = Gauge(
    "broker_adapter_health_status",
    "Broker adapter health status (0=unhealthy, 1=healthy)",
    labelnames=["adapter"],
)

# -- Gauges: reconciliation and orphaned orders ------------------------------

ORPHANED_ORDERS_DETECTED = Gauge(
    "orphaned_orders_detected",
    "Count of orphaned orders found by reconciliation (orders in local state but missing from broker)",
)

RECONCILIATION_DISCREPANCIES_UNRESOLVED = Gauge(
    "reconciliation_discrepancies_unresolved",
    "Count of unresolved reconciliation discrepancies awaiting manual intervention",
)

# -- Histograms: API HTTP request latency ------------------------------------

_API_HTTP_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

API_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "api_http_request_duration_seconds",
    "API HTTP request latency, in seconds, from receipt to response",
    labelnames=["endpoint", "method", "status"],
    buckets=_API_HTTP_LATENCY_BUCKETS,
)

# -- Counters: API HTTP traffic -----------------------------------------------

API_HTTP_REQUESTS_TOTAL = Counter(
    "api_http_requests_total",
    "Total HTTP requests received by the API",
    labelnames=["endpoint", "method", "status"],
)

# -- Gauges: API connection pool -------------------------------------------------

API_HTTP_ACTIVE_CONNECTIONS = Gauge(
    "api_http_active_connections",
    "Current active HTTP connections to the API",
)

API_HTTP_MAX_CONNECTIONS = Gauge(
    "api_http_max_connections",
    "Maximum configured HTTP connections for the API",
)

# ---------------------------------------------------------------------------
# /metrics endpoint — unauthenticated for Prometheus scraper access
# ---------------------------------------------------------------------------

router = APIRouter(tags=["observability"])


@router.get(
    "/metrics",
    summary="Prometheus metrics scrape endpoint",
    description="Returns all registered Prometheus counters in exposition format.",
    include_in_schema=False,
)
async def metrics_endpoint() -> Response:
    """
    Serve Prometheus exposition format for all registered counters.

    This endpoint is intentionally unauthenticated — Prometheus scrapers
    do not carry JWT tokens. Network-level access control (e.g. Kubernetes
    NetworkPolicy) should restrict access in production.

    Returns:
        Response with text/plain content containing Prometheus metrics.

    Example:
        GET /metrics → 200 text/plain
        # HELP approval_requests_total Total approval actions ...
        # TYPE approval_requests_total counter
        approval_requests_total{request_type="approve",status="success"} 1.0
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

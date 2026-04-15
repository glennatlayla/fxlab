"""
Unit tests for M15 execution metrics and /metrics endpoint.

Covers:
- All execution Counter metrics are defined with correct labels
- All execution Histogram metrics are defined with correct labels and buckets
- All execution Gauge metrics are defined with correct labels
- Counters can be incremented and observed
- /metrics endpoint returns Prometheus exposition format
- Governance counters from M14-T9 still present (backward compat)

Dependencies:
- services.api.metrics: all metric objects and router
- services.api.main: app (for TestClient)
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
)

from services.api.main import app
from services.api.metrics import (
    BROKER_REQUEST_DURATION_SECONDS,
    CIRCUIT_BREAKER_STATE,
    KILL_SWITCH_ACTIVATIONS_TOTAL,
    KILL_SWITCH_MTTH_SECONDS,
    ORDER_LATENCY_SECONDS,
    ORDERS_FILLED_TOTAL,
    ORDERS_REJECTED_TOTAL,
    ORDERS_SUBMITTED_TOTAL,
    POSITIONS_TOTAL,
    RECONCILIATION_DISCREPANCIES_TOTAL,
    RECONCILIATION_RUNS_TOTAL,
    RISK_GATE_CHECKS_TOTAL,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


# ------------------------------------------------------------------
# Tests: Metric Definitions
# ------------------------------------------------------------------


class TestExecutionCounterDefinitions:
    """All execution Counter metrics are properly defined."""

    def test_orders_submitted_total_is_counter(self) -> None:
        """ORDERS_SUBMITTED_TOTAL is a Counter with correct labels."""
        assert isinstance(ORDERS_SUBMITTED_TOTAL, Counter)
        assert ORDERS_SUBMITTED_TOTAL._labelnames == ("execution_mode", "symbol", "side")

    def test_orders_filled_total_is_counter(self) -> None:
        """ORDERS_FILLED_TOTAL is a Counter with correct labels."""
        assert isinstance(ORDERS_FILLED_TOTAL, Counter)
        assert ORDERS_FILLED_TOTAL._labelnames == ("execution_mode", "symbol")

    def test_orders_rejected_total_is_counter(self) -> None:
        """ORDERS_REJECTED_TOTAL is a Counter with correct labels."""
        assert isinstance(ORDERS_REJECTED_TOTAL, Counter)
        assert ORDERS_REJECTED_TOTAL._labelnames == ("execution_mode", "reason")

    def test_kill_switch_activations_total_is_counter(self) -> None:
        """KILL_SWITCH_ACTIVATIONS_TOTAL is a Counter with scope label."""
        assert isinstance(KILL_SWITCH_ACTIVATIONS_TOTAL, Counter)
        assert KILL_SWITCH_ACTIVATIONS_TOTAL._labelnames == ("scope",)

    def test_reconciliation_runs_total_is_counter(self) -> None:
        """RECONCILIATION_RUNS_TOTAL is a Counter with trigger+status labels."""
        assert isinstance(RECONCILIATION_RUNS_TOTAL, Counter)
        assert RECONCILIATION_RUNS_TOTAL._labelnames == ("trigger", "status")

    def test_reconciliation_discrepancies_total_is_counter(self) -> None:
        """RECONCILIATION_DISCREPANCIES_TOTAL is a Counter with type label."""
        assert isinstance(RECONCILIATION_DISCREPANCIES_TOTAL, Counter)
        assert RECONCILIATION_DISCREPANCIES_TOTAL._labelnames == ("type",)

    def test_risk_gate_checks_total_is_counter(self) -> None:
        """RISK_GATE_CHECKS_TOTAL is a Counter with check_name+result labels."""
        assert isinstance(RISK_GATE_CHECKS_TOTAL, Counter)
        assert RISK_GATE_CHECKS_TOTAL._labelnames == ("check_name", "result")


class TestExecutionHistogramDefinitions:
    """All execution Histogram metrics are properly defined."""

    def test_order_latency_seconds_is_histogram(self) -> None:
        """ORDER_LATENCY_SECONDS is a Histogram with correct labels."""
        assert isinstance(ORDER_LATENCY_SECONDS, Histogram)
        assert ORDER_LATENCY_SECONDS._labelnames == ("execution_mode", "order_type")

    def test_order_latency_has_sub_second_buckets(self) -> None:
        """ORDER_LATENCY_SECONDS has fine-grained sub-second buckets for trading."""
        # The upper_bounds include the +Inf bucket appended by prometheus_client
        upper_bounds = ORDER_LATENCY_SECONDS._upper_bounds
        assert 0.005 in upper_bounds
        assert 0.05 in upper_bounds
        assert 0.5 in upper_bounds

    def test_kill_switch_mtth_seconds_is_histogram(self) -> None:
        """KILL_SWITCH_MTTH_SECONDS is a Histogram."""
        assert isinstance(KILL_SWITCH_MTTH_SECONDS, Histogram)

    def test_broker_request_duration_seconds_is_histogram(self) -> None:
        """BROKER_REQUEST_DURATION_SECONDS is a Histogram with adapter+method labels."""
        assert isinstance(BROKER_REQUEST_DURATION_SECONDS, Histogram)
        assert BROKER_REQUEST_DURATION_SECONDS._labelnames == ("adapter", "method")


class TestExecutionGaugeDefinitions:
    """All execution Gauge metrics are properly defined."""

    def test_circuit_breaker_state_is_gauge(self) -> None:
        """CIRCUIT_BREAKER_STATE is a Gauge with adapter_id+state labels."""
        assert isinstance(CIRCUIT_BREAKER_STATE, Gauge)
        assert CIRCUIT_BREAKER_STATE._labelnames == ("adapter_id", "state")

    def test_positions_total_is_gauge(self) -> None:
        """POSITIONS_TOTAL is a Gauge with deployment_id label."""
        assert isinstance(POSITIONS_TOTAL, Gauge)
        assert POSITIONS_TOTAL._labelnames == ("deployment_id",)


# ------------------------------------------------------------------
# Tests: Metric Operations
# ------------------------------------------------------------------


class TestMetricOperations:
    """Metrics can be incremented, observed, and set without errors."""

    def test_counter_increment(self) -> None:
        """Counter metrics can be incremented with labels."""
        # Should not raise
        ORDERS_SUBMITTED_TOTAL.labels(execution_mode="paper", symbol="AAPL", side="buy").inc()

    def test_histogram_observe(self) -> None:
        """Histogram metrics can observe values."""
        ORDER_LATENCY_SECONDS.labels(execution_mode="paper", order_type="market").observe(0.042)

    def test_gauge_set(self) -> None:
        """Gauge metrics can be set."""
        POSITIONS_TOTAL.labels(deployment_id="deploy-001").set(5)

    def test_kill_switch_activation_counter(self) -> None:
        """Kill switch counter can be incremented by scope."""
        KILL_SWITCH_ACTIVATIONS_TOTAL.labels(scope="deployment").inc()
        KILL_SWITCH_ACTIVATIONS_TOTAL.labels(scope="global").inc()

    def test_risk_gate_counter(self) -> None:
        """Risk gate counter tracks pass/fail results."""
        RISK_GATE_CHECKS_TOTAL.labels(check_name="max_order_value", result="pass").inc()
        RISK_GATE_CHECKS_TOTAL.labels(check_name="max_order_value", result="fail").inc()

    def test_broker_request_duration(self) -> None:
        """Broker request histogram can observe durations."""
        BROKER_REQUEST_DURATION_SECONDS.labels(adapter="alpaca", method="submit_order").observe(
            0.15
        )


# ------------------------------------------------------------------
# Tests: /metrics Endpoint
# ------------------------------------------------------------------


class TestMetricsEndpoint:
    """GET /metrics returns Prometheus exposition format."""

    def test_metrics_returns_200(self) -> None:
        """Metrics endpoint returns 200."""
        client = _get_client()
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self) -> None:
        """Metrics endpoint returns Prometheus content type."""
        client = _get_client()
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_contains_execution_counters(self) -> None:
        """Metrics output includes execution counter names."""
        # Increment a counter so it appears in output
        ORDERS_SUBMITTED_TOTAL.labels(execution_mode="paper", symbol="SPY", side="sell").inc()
        client = _get_client()
        resp = client.get("/metrics")
        body = resp.text
        assert "orders_submitted_total" in body

    def test_metrics_contains_governance_counters(self) -> None:
        """Metrics output still includes governance counters (backward compat)."""
        client = _get_client()
        resp = client.get("/metrics")
        body = resp.text
        # These were defined in M14-T9 — must still be present
        assert "approval_requests_total" in body or "override_requests_total" in body

    def test_metrics_contains_histograms(self) -> None:
        """Metrics output includes histogram metrics with bucket info."""
        ORDER_LATENCY_SECONDS.labels(execution_mode="shadow", order_type="limit").observe(0.1)
        client = _get_client()
        resp = client.get("/metrics")
        body = resp.text
        assert "order_latency_seconds_bucket" in body

    def test_metrics_unauthenticated(self) -> None:
        """Metrics endpoint does not require authentication."""
        client = _get_client()
        resp = client.get("/metrics")
        # Should not be 401 or 403
        assert resp.status_code == 200

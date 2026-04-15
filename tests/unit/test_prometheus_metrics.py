"""
Unit tests for Prometheus metrics instrumentation (M14-T9 Gap 2).

Covers:
- All 7 metric counters are defined and accessible.
- Counter increment helpers produce correct label combinations.
- /metrics endpoint returns 200 with text/plain Prometheus exposition format.
- Metric counters appear in the /metrics scrape output after increment.

Test naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure test environment."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def client() -> TestClient:
    """TestClient for /metrics endpoint testing."""
    from services.api.main import app

    return TestClient(app)


# ===========================================================================
# Metric definitions exist
# ===========================================================================


class TestMetricDefinitions:
    """Verify all 7 Prometheus counters are defined."""

    def test_approval_requests_total_defined(self) -> None:
        from services.api.metrics import APPROVAL_REQUESTS_TOTAL

        assert APPROVAL_REQUESTS_TOTAL is not None

    def test_override_requests_total_defined(self) -> None:
        from services.api.metrics import OVERRIDE_REQUESTS_TOTAL

        assert OVERRIDE_REQUESTS_TOTAL is not None

    def test_chart_cache_hits_total_defined(self) -> None:
        from services.api.metrics import CHART_CACHE_HITS_TOTAL

        assert CHART_CACHE_HITS_TOTAL is not None

    def test_chart_cache_misses_total_defined(self) -> None:
        from services.api.metrics import CHART_CACHE_MISSES_TOTAL

        assert CHART_CACHE_MISSES_TOTAL is not None

    def test_lttb_applied_total_defined(self) -> None:
        from services.api.metrics import LTTB_APPLIED_TOTAL

        assert LTTB_APPLIED_TOTAL is not None

    def test_export_requests_total_defined(self) -> None:
        from services.api.metrics import EXPORT_REQUESTS_TOTAL

        assert EXPORT_REQUESTS_TOTAL is not None

    def test_draft_autosaves_total_defined(self) -> None:
        from services.api.metrics import DRAFT_AUTOSAVES_TOTAL

        assert DRAFT_AUTOSAVES_TOTAL is not None


# ===========================================================================
# Counter increment helpers
# ===========================================================================


class TestCounterIncrements:
    """Verify counter increment helpers work with correct labels."""

    def test_approval_counter_increments_with_labels(self) -> None:
        from services.api.metrics import APPROVAL_REQUESTS_TOTAL

        # Should not raise — labels: request_type, status
        APPROVAL_REQUESTS_TOTAL.labels(request_type="approve", status="success").inc()

    def test_override_counter_increments_with_labels(self) -> None:
        from services.api.metrics import OVERRIDE_REQUESTS_TOTAL

        OVERRIDE_REQUESTS_TOTAL.labels(governance_gate="manual_review", status="submitted").inc()

    def test_chart_cache_hits_counter_increments(self) -> None:
        from services.api.metrics import CHART_CACHE_HITS_TOTAL

        CHART_CACHE_HITS_TOTAL.inc()

    def test_chart_cache_misses_counter_increments(self) -> None:
        from services.api.metrics import CHART_CACHE_MISSES_TOTAL

        CHART_CACHE_MISSES_TOTAL.inc()

    def test_lttb_applied_counter_increments(self) -> None:
        from services.api.metrics import LTTB_APPLIED_TOTAL

        LTTB_APPLIED_TOTAL.inc()

    def test_export_requests_counter_increments_with_labels(self) -> None:
        from services.api.metrics import EXPORT_REQUESTS_TOTAL

        EXPORT_REQUESTS_TOTAL.labels(format="csv", export_type="backtest_result").inc()

    def test_draft_autosaves_counter_increments(self) -> None:
        from services.api.metrics import DRAFT_AUTOSAVES_TOTAL

        DRAFT_AUTOSAVES_TOTAL.inc()


# ===========================================================================
# /metrics endpoint
# ===========================================================================


class TestMetricsEndpoint:
    """Verify /metrics endpoint serves Prometheus exposition format."""

    def test_metrics_endpoint_returns_200(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_endpoint_returns_text_content_type(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        content_type = resp.headers.get("content-type", "")
        # Prometheus exposition format uses text/plain or openmetrics
        assert "text/plain" in content_type or "openmetrics" in content_type

    def test_metrics_endpoint_contains_counter_names(self, client: TestClient) -> None:
        """After incrementing, the counter name appears in /metrics output."""
        from services.api.metrics import APPROVAL_REQUESTS_TOTAL

        APPROVAL_REQUESTS_TOTAL.labels(request_type="approve", status="success").inc()
        resp = client.get("/metrics")
        assert "approval_requests_total" in resp.text

    def test_metrics_endpoint_is_unauthenticated(self, client: TestClient) -> None:
        """
        /metrics must be accessible without auth — Prometheus scrapers
        do not carry JWT tokens.
        """
        resp = client.get("/metrics")
        assert resp.status_code == 200

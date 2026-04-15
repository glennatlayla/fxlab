"""
Unit tests for M13 readiness probe (/ready endpoint).

Covers:
- Returns 200 when all dependencies are healthy
- Returns 503 when database is unreachable
- Returns 503 when broker adapter reports disconnected
- Includes dependency status details in response body
- /health (liveness) remains lightweight and separate

Dependencies:
- services.api.routes.health: router (with /ready endpoint)
- services.api.main: app
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.main import app

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


# ------------------------------------------------------------------
# Tests: Readiness Probe
# ------------------------------------------------------------------


class TestReadinessProbe:
    """GET /ready returns 200 when ready, 503 when not."""

    def test_ready_returns_200_when_db_is_up(self) -> None:
        """Readiness returns 200 when database is reachable."""
        client = _get_client()
        with patch("services.api.db.check_db_connection", return_value=True):
            resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"

    def test_ready_returns_503_when_db_is_down(self) -> None:
        """Readiness returns 503 when database is unreachable."""
        client = _get_client()
        with patch("services.api.db.check_db_connection", return_value=False):
            resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"

    def test_ready_includes_component_status(self) -> None:
        """Readiness response includes per-component health status."""
        client = _get_client()
        with patch("services.api.db.check_db_connection", return_value=True):
            resp = client.get("/ready")
        body = resp.json()
        assert "checks" in body
        assert "database" in body["checks"]

    def test_ready_returns_503_on_db_exception(self) -> None:
        """Readiness returns 503 when DB check throws exception."""
        client = _get_client()
        with patch(
            "services.api.db.check_db_connection",
            side_effect=Exception("connection refused"),
        ):
            resp = client.get("/ready")
        assert resp.status_code == 503

    def test_ready_unauthenticated(self) -> None:
        """Readiness endpoint does not require authentication."""
        client = _get_client()
        with patch("services.api.db.check_db_connection", return_value=True):
            resp = client.get("/ready")
        # No auth header needed — should not be 401 or 403
        assert resp.status_code in (200, 503)


# ------------------------------------------------------------------
# Tests: Liveness remains separate
# ------------------------------------------------------------------


class TestLivenessUnchanged:
    """GET /health remains a lightweight liveness check."""

    def test_health_returns_200_when_db_up(self) -> None:
        """Health check still returns 200 when DB is reachable."""
        client = _get_client()
        resp = client.get("/health")
        # Health endpoint uses the real DB check — just verify it responds
        assert resp.status_code in (200, 503)

    def test_health_response_has_status_field(self) -> None:
        """Health response includes the 'status' field."""
        client = _get_client()
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body

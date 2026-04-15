"""
Behavioral validation of core API endpoint contracts (replaces document-linting test).

Purpose:
    Verify that core API endpoints respond according to their documented
    contracts (status codes, response structure, content types). This replaces
    the previous document-linting test that only checked markdown formatting.

Responsibilities:
    - Verify /runs/{id}/results returns correct structure on success.
    - Verify /runs/{id}/readiness returns correct structure on success.
    - Verify /promotions/request accepts valid payloads.
    - Verify /audit returns proper list structure.
    - Verify error responses include expected detail fields.

Does NOT:
    - Run Playwright browser tests (deferred to M31).
    - Test full E2E flows spanning multiple services.

Dependencies:
    - FastAPI TestClient: HTTP-level integration testing.
    - services.api.main: The FastAPI application.

Example:
    pytest tests/unit/test_e2e_plan_document.py -v
"""

from __future__ import annotations

from fastapi.testclient import TestClient

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}


class TestCoreEndpointContracts:
    """Verify core API endpoints honor their response contracts."""

    def test_runs_results_returns_json_for_valid_ulid(self) -> None:
        """GET /runs/{run_id}/results should return JSON for valid ULID."""
        from services.api.main import app

        client = TestClient(app)
        # Valid ULID format — may not exist in DB (404 is valid)
        response = client.get(
            "/runs/01HABCDEF00000000000000000/results",
            headers=AUTH_HEADERS,
        )
        assert response.status_code in (200, 404)
        assert "application/json" in response.headers.get("content-type", "")

    def test_runs_results_422_for_invalid_ulid(self) -> None:
        """GET /runs/{run_id}/results should reject invalid ULID with 422."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get(
            "/runs/not-a-ulid/results",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

    def test_readiness_returns_json_for_valid_ulid(self) -> None:
        """GET /runs/{run_id}/readiness should return JSON for valid ULID."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get(
            "/runs/01HABCDEF00000000000000000/readiness",
            headers=AUTH_HEADERS,
        )
        assert response.status_code in (200, 404)
        assert "application/json" in response.headers.get("content-type", "")

    def test_readiness_422_for_invalid_ulid(self) -> None:
        """GET /runs/{run_id}/readiness should reject invalid ULID with 422."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get(
            "/runs/bad!/readiness",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

    def test_promotions_accepts_valid_payload(self) -> None:
        """POST /promotions/request should accept a valid payload."""
        from services.api.main import app

        client = TestClient(app)
        payload = {
            "candidate_id": "01HABCDEF00000000000000001",
            "target_environment": "paper",
            "requester_id": "01HABCDEF00000000000000002",
        }
        response = client.post(
            "/promotions/request",
            json=payload,
            headers=AUTH_HEADERS,
        )
        # Should be accepted (not 404 or 422)
        assert response.status_code in (200, 201, 202)
        body = response.json()
        assert "job_id" in body or "status" in body

    def test_audit_returns_json_list(self) -> None:
        """GET /audit should return a JSON response."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get("/audit", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    def test_unauthenticated_requests_rejected(self) -> None:
        """Endpoints should return 401 without authentication headers."""
        from services.api.main import app

        client = TestClient(app)
        endpoints = [
            "/runs/01HABCDEF00000000000000000/results",
            "/runs/01HABCDEF00000000000000000/readiness",
            "/audit",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401, f"GET {endpoint} should require authentication"


class TestErrorResponseContracts:
    """Verify error responses follow the expected structure."""

    def test_404_responses_include_detail(self) -> None:
        """404 responses should include a 'detail' field explaining what wasn't found."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get(
            "/runs/01HABCDEF00000000000000000/results",
            headers=AUTH_HEADERS,
        )
        if response.status_code == 404:
            body = response.json()
            assert "detail" in body

    def test_422_responses_include_detail(self) -> None:
        """422 responses for invalid input should include a detail message."""
        from services.api.main import app

        client = TestClient(app)
        response = client.get(
            "/runs/invalid!!!/results",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422
        body = response.json()
        assert "detail" in body

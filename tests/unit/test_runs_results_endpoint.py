"""
Unit tests for GET /runs/{run_id}/results endpoint.

These tests verify the endpoint contract, not implementation logic.
All tests MUST FAIL before implementation exists.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def client():
    """FastAPI test client."""
    from services.api.main import app

    return TestClient(app)


def test_results_endpoint_requires_valid_ulid_format(client):
    """
    Endpoint must validate run_id is a ULID.

    FAILURE MODE: Accepts invalid format or returns wrong error code.
    """
    invalid_run_id = "not-a-ulid"
    response = client.get(f"/runs/{invalid_run_id}/results", headers=AUTH_HEADERS)

    # Should return 400 Bad Request or 422 Unprocessable Entity for invalid format
    assert response.status_code in [400, 422], (
        "Invalid ULID format must be rejected with 400 or 422"
    )


def test_results_endpoint_returns_404_for_nonexistent_run(client):
    """
    Endpoint must return 404 for run_id that doesn't exist.

    FAILURE MODE: Returns 200 with empty data or wrong error code.
    """
    nonexistent_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    # Mock the service layer to return None (run not found)
    with patch("services.api.main.get_run_results") as mock_get:
        mock_get.return_value = None

        response = client.get(f"/runs/{nonexistent_run_id}/results", headers=AUTH_HEADERS)

        assert response.status_code == 404, "Non-existent run must return 404"


def test_results_endpoint_returns_structured_json(client):
    """
    Endpoint must return structured JSON with expected fields.

    FAILURE MODE: Returns None, empty dict, or unstructured data.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    # Mock successful response
    mock_results = {"run_id": test_run_id, "metrics": {}, "artifacts": []}

    with patch("services.api.main.get_run_results") as mock_get:
        mock_get.return_value = mock_results

        response = client.get(f"/runs/{test_run_id}/results", headers=AUTH_HEADERS)

        # Should return 200 with JSON data
        assert response.status_code == 200, "Valid run must return 200 OK"

        data = response.json()
        assert "run_id" in data, "Response must include run_id"
        assert data["run_id"] == test_run_id, "Response run_id must match request"


def test_results_endpoint_includes_metadata_fields(client):
    """
    Results must include timestamp and lineage metadata.

    FAILURE MODE: Missing required metadata fields.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    mock_results = {
        "run_id": test_run_id,
        "completed_at": "2026-03-17T10:00:00Z",
        "strategy_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0X",
        "metrics": {},
    }

    with patch("services.api.main.get_run_results") as mock_get:
        mock_get.return_value = mock_results

        response = client.get(f"/runs/{test_run_id}/results", headers=AUTH_HEADERS)
        data = response.json()

        assert "completed_at" in data, "Results must include completion timestamp"
        assert "strategy_id" in data, "Results must include strategy lineage"


def test_results_endpoint_handles_service_errors_gracefully(client):
    """
    Endpoint must return 500 for internal service errors.

    FAILURE MODE: Crashes or returns 200 when service fails.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    with patch("services.api.main.get_run_results") as mock_get:
        mock_get.side_effect = Exception("Database connection failed")

        response = client.get(f"/runs/{test_run_id}/results", headers=AUTH_HEADERS)

        assert response.status_code == 500, "Service errors must return 500 Internal Server Error"


def test_results_endpoint_does_not_compute_readiness_locally(client):
    """
    Results endpoint must NOT calculate readiness grades or governance state.

    FAILURE MODE: Response includes computed readiness fields.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    mock_results = {
        "run_id": test_run_id,
        "metrics": {"sharpe": 1.5},
        # NO readiness_grade or governance_state fields
    }

    with patch("services.api.main.get_run_results") as mock_get:
        mock_get.return_value = mock_results

        response = client.get(f"/runs/{test_run_id}/results", headers=AUTH_HEADERS)
        data = response.json()

        # These fields should NOT be present in results endpoint
        assert "readiness_grade" not in data, "Results endpoint must not compute readiness grades"
        assert "governance_state" not in data, "Results endpoint must not compute governance state"

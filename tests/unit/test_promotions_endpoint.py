"""
Unit tests for POST /promotions/request endpoint.

These tests verify promotion workflow initiation.
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


def test_promotions_endpoint_requires_candidate_id(client):
    """
    Promotion request must include candidate_id.

    FAILURE MODE: Accepts request without candidate_id.
    """
    payload = {"target_environment": "paper", "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W"}

    response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422, "Request without candidate_id must be rejected"


def test_promotions_endpoint_requires_target_environment(client):
    """
    Promotion request must specify target environment.

    FAILURE MODE: Accepts request without target_environment.
    """
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422, "Request without target_environment must be rejected"


def test_promotions_endpoint_validates_ulid_format(client):
    """
    All ID fields must be valid ULIDs.

    FAILURE MODE: Accepts non-ULID strings.
    """
    payload = {
        "candidate_id": "not-a-ulid",
        "target_environment": "paper",
        "requester_id": "also-not-a-ulid",
    }

    response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422, "Invalid ULID format must be rejected"


def test_promotions_endpoint_returns_job_id_immediately(client):
    """
    Promotion request must return job ID immediately (async workflow).

    FAILURE MODE: Blocks waiting for completion or returns no job ID.
    """
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "target_environment": "paper",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    mock_response = {"job_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0X", "status": "pending"}

    with patch("services.api.main.submit_promotion_request") as mock_submit:
        mock_submit.return_value = mock_response

        response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

        assert response.status_code == 202, (
            "Promotion request must return 202 Accepted for async processing"
        )

        data = response.json()
        assert "job_id" in data, "Response must include job_id for async tracking"


def test_promotions_endpoint_creates_audit_event(client):
    """
    Every promotion request must generate an audit event.

    FAILURE MODE: No audit event created.
    """
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "target_environment": "paper",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    with (
        patch("services.api.main.submit_promotion_request") as mock_submit,
        patch("services.api.main.audit_service") as mock_audit,
    ):
        mock_submit.return_value = {"job_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0X"}

        client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

        # Verify audit service was called
        assert mock_audit.log_event.called, "Promotion request must create an audit event"


def test_promotions_endpoint_validates_target_environment_enum(client):
    """
    Target environment must be from valid enum (paper, live, etc.).

    FAILURE MODE: Accepts arbitrary strings.
    """
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "target_environment": "invalid_environment",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422, "Invalid target environment must be rejected"


def test_promotions_endpoint_enforces_rbac(client):
    """
    Promotion request must enforce RBAC permissions.

    FAILURE MODE: Accepts request without proper permissions.
    """
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "target_environment": "paper",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    with patch("services.api.main.check_permission") as mock_check:
        mock_check.return_value = False  # User lacks permission

        response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

        assert response.status_code == 403, (
            "Promotion request without permission must return 403 Forbidden"
        )

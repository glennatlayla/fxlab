"""
Unit tests for GET /runs/{run_id}/readiness endpoint.

These tests verify the readiness report contract.
All tests MUST FAIL before implementation exists.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client():
    """FastAPI test client."""
    from services.api.main import app
    return TestClient(app)


def test_readiness_endpoint_requires_valid_ulid(client):
    """
    Endpoint must validate run_id is a ULID.
    
    FAILURE MODE: Accepts invalid format.
    """
    invalid_run_id = "invalid-format"
    response = client.get(f"/runs/{invalid_run_id}/readiness")
    
    assert response.status_code in [400, 422], \
        "Invalid ULID must be rejected"


def test_readiness_endpoint_returns_404_for_nonexistent_run(client):
    """
    Endpoint must return 404 for run that doesn't exist.
    
    FAILURE MODE: Returns 200 or wrong error.
    """
    nonexistent_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    
    with patch("services.api.main.get_readiness_report") as mock_get:
        mock_get.return_value = None
        
        response = client.get(f"/runs/{nonexistent_run_id}/readiness")
        
        assert response.status_code == 404, \
            "Non-existent run must return 404"


def test_readiness_response_includes_grade_and_blockers(client):
    """
    Readiness response must include grade and blocker list.
    
    FAILURE MODE: Missing required fields.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    
    mock_report = {
        "run_id": test_run_id,
        "readiness_grade": "GREEN",
        "blockers": []
    }
    
    with patch("services.api.main.get_readiness_report") as mock_get:
        mock_get.return_value = mock_report
        
        response = client.get(f"/runs/{test_run_id}/readiness")
        data = response.json()
        
        assert "readiness_grade" in data, \
            "Response must include readiness_grade"
        assert "blockers" in data, \
            "Response must include blockers list"


def test_readiness_blockers_include_owner_and_next_step(client):
    """
    Each blocker must include owner and next_step per v1.1 requirements.
    
    FAILURE MODE: Blocker missing required actionable fields.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    
    mock_report = {
        "run_id": test_run_id,
        "readiness_grade": "RED",
        "blockers": [
            {
                "code": "INSUFFICIENT_DATA",
                "message": "Strategy has unresolved ambiguity",
                "blocker_owner": "research-team",
                "next_step": "Contact research team to resolve data requirements"
            }
        ]
    }
    
    with patch("services.api.main.get_readiness_report") as mock_get:
        mock_get.return_value = mock_report
        
        response = client.get(f"/runs/{test_run_id}/readiness")
        data = response.json()
        
        blockers = data["blockers"]
        assert len(blockers) > 0, "Test requires at least one blocker"
        
        first_blocker = blockers[0]
        assert "blocker_owner" in first_blocker, \
            "Blocker must include blocker_owner field"
        assert "next_step" in first_blocker, \
            "Blocker must include next_step field for actionability"


def test_readiness_endpoint_is_read_only(client):
    """
    Readiness endpoint must not accept mutation methods.
    
    FAILURE MODE: POST/PUT/DELETE accepted on readiness endpoint.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    
    # Try POST (should be method not allowed)
    response = client.post(f"/runs/{test_run_id}/readiness")
    assert response.status_code == 405, \
        "Readiness endpoint must not accept POST"
    
    # Try PUT
    response = client.put(f"/runs/{test_run_id}/readiness")
    assert response.status_code == 405, \
        "Readiness endpoint must not accept PUT"


def test_readiness_report_includes_scoring_evidence(client):
    """
    Readiness report must include scoring evidence for each component.
    
    FAILURE MODE: Response lacks evidence fields.
    """
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    
    mock_report = {
        "run_id": test_run_id,
        "readiness_grade": "YELLOW",
        "blockers": [],
        "scoring_evidence": {
            "data_quality": {"score": 0.95, "checks_passed": 10},
            "backtest_metrics": {"sharpe": 1.5}
        }
    }
    
    with patch("services.api.main.get_readiness_report") as mock_get:
        mock_get.return_value = mock_report
        
        response = client.get(f"/runs/{test_run_id}/readiness")
        data = response.json()
        
        assert "scoring_evidence" in data, \
            "Readiness report must include scoring evidence"

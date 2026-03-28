"""
FastAPI Application Tests.

Test suite for the Phase 3 API service entry point, including health
checks and container orchestration readiness probes.
"""

import pytest
from fastapi.testclient import TestClient
from services.api.main import app, HEALTH_STATUS_OK as HEALTH_STATUS_HEALTHY, HEALTH_SERVICE_NAME

# HTTP status codes
HTTP_OK = 200

# Test client fixture
@pytest.fixture
def client():
    """
    Provide a FastAPI test client instance.
    
    Yields:
        TestClient: Configured test client for the FastAPI app
    """
    return TestClient(app)


def test_health_endpoint_returns_200(client):
    """
    Verify health endpoint responds with HTTP 200 OK.
    
    Container orchestration relies on this endpoint for readiness probes.
    A non-200 response would mark the service as unavailable.
    """
    response = client.get("/health")
    assert response.status_code == HTTP_OK


def test_health_endpoint_returns_correct_structure(client):
    """
    Verify health endpoint returns expected JSON structure.
    
    The response must contain 'status' and 'service' fields to satisfy
    the health check contract for monitoring and orchestration systems.
    """
    response = client.get("/health")
    json_data = response.json()
    
    assert "status" in json_data, "Health response must include 'status' field"
    assert "service" in json_data, "Health response must include 'service' field"


def test_health_endpoint_status_value(client):
    """
    Verify health endpoint reports 'healthy' status.
    
    The status field must explicitly indicate service health state.
    Any value other than 'healthy' may trigger alerts or service restarts.
    """
    response = client.get("/health")
    json_data = response.json()
    
    assert json_data["status"] == HEALTH_STATUS_HEALTHY


def test_health_endpoint_service_name(client):
    """
    Verify health endpoint identifies correct service name.
    
    The service field allows monitoring systems to distinguish between
    multiple services in a distributed deployment.
    """
    response = client.get("/health")
    json_data = response.json()
    
    assert json_data["service"] == HEALTH_SERVICE_NAME

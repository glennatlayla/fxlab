"""
Unit tests for FastAPI application entry point.
"""
import pytest
from fastapi.testclient import TestClient

from services.api.main import app, API_VERSION


@pytest.fixture
def client() -> TestClient:
    """Create test client for API."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Health check endpoint returns 200 with status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == API_VERSION


def test_root_endpoint(client: TestClient) -> None:
    """Root endpoint returns API metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "version" in data
    assert data["version"] == API_VERSION


def test_cors_headers_present(client: TestClient) -> None:
    """CORS middleware adds appropriate headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers

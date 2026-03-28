"""
RED tests for M1 - FastAPI application structure and health endpoint.

These tests verify:
- services/api/main.py exists and exports a FastAPI app
- Health check endpoint exists at GET /health
- Health endpoint returns 200 OK with correct structure

All tests must FAIL until implementation is complete.
"""
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient


def test_ac1_fastapi_main_module_exists():
    """AC1: FastAPI app exists at services/api/main.py (not app.py)."""
    try:
        from services.api import main
        assert hasattr(main, 'app'), "services/api/main.py must export 'app'"
    except ImportError as e:
        pytest.fail(f"services/api/main.py does not exist or cannot be imported: {e}")


def test_ac1_fastapi_app_is_fastapi_instance():
    """AC1: The exported app must be a FastAPI instance."""
    from services.api.main import app
    from fastapi import FastAPI
    
    assert isinstance(app, FastAPI), "app must be a FastAPI instance"


def test_ac2_health_endpoint_exists():
    """AC2: GET /health endpoint must exist."""
    from services.api.main import app
    
    client = TestClient(app)
    # This will fail if the endpoint doesn't exist (404)
    response = client.get("/health")
    
    # Must not be 404 (endpoint must exist)
    assert response.status_code != 404, "GET /health endpoint does not exist"


def test_ac2_health_endpoint_returns_200():
    """AC2: GET /health must return 200 OK status."""
    from services.api.main import app
    
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"


def test_ac2_health_endpoint_returns_json():
    """AC2: GET /health must return JSON response."""
    from services.api.main import app
    
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.headers.get("content-type") == "application/json", \
        "Health endpoint must return JSON"


def test_ac2_health_response_has_status_field():
    """AC2: Health response must contain 'status' field."""
    from services.api.main import app
    
    client = TestClient(app)
    response = client.get("/health")
    
    data = response.json()
    assert "status" in data, "Health response must contain 'status' field"


def test_ac2_health_status_is_ok():
    """AC2: Health status must be 'ok' when service is healthy."""
    from services.api.main import app
    
    client = TestClient(app)
    response = client.get("/health")
    
    data = response.json()
    assert data.get("status") == "ok", \
        f"Expected status='ok', got status='{data.get('status')}'"


def test_ac1_app_has_title():
    """AC1: FastAPI app should have a title for documentation."""
    from services.api.main import app
    
    assert app.title is not None, "FastAPI app must have a title"
    assert len(app.title) > 0, "FastAPI app title must not be empty"


def test_ac1_app_has_version():
    """AC1: FastAPI app should have a version for documentation."""
    from services.api.main import app
    
    assert app.version is not None, "FastAPI app must have a version"
    assert len(app.version) > 0, "FastAPI app version must not be empty"


def test_ac2_health_endpoint_does_not_require_auth():
    """AC2: Health endpoint must be accessible without authentication."""
    from services.api.main import app
    
    # Health checks must work without any authorization headers
    client = TestClient(app)
    response = client.get("/health")
    
    # Must not return 401 or 403
    assert response.status_code not in [401, 403], \
        "Health endpoint must not require authentication"
    assert response.status_code == 200, \
        f"Health endpoint returned {response.status_code} instead of 200"

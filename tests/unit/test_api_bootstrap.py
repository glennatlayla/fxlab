"""
M0 Bootstrap: FastAPI application structure and core endpoint presence tests.

These tests verify that:
- AC1: FastAPI application exists at services/api/main.py
- AC2: Core endpoint routes are registered
- AC3: Application can be instantiated (even with stub implementations)

All tests MUST FAIL before implementation exists.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}


def test_ac1_fastapi_application_module_exists():
    """
    AC1: FastAPI application structure initialized at canonical path.

    FAILURE MODE: ImportError if services/api/main.py doesn't exist.
    """
    try:
        from services.api import main

        assert hasattr(main, "app"), "main.py must export 'app' instance"
        assert isinstance(main.app, FastAPI), "app must be a FastAPI instance"
    except ImportError as e:
        pytest.fail(f"services/api/main.py not found: {e}")


def test_ac1_application_has_title_and_version():
    """
    AC1: FastAPI application has proper metadata.

    FAILURE MODE: AttributeError or empty title/version before implementation.
    """
    from services.api.main import app

    assert app.title is not None, "Application must have a title"
    assert app.title != "", "Application title must not be empty"
    assert app.version is not None, "Application must have a version"
    assert app.version != "", "Application version must not be empty"


def test_ac2_runs_results_endpoint_exists():
    """
    AC2: GET /runs/{run_id}/results endpoint is registered.

    Verifies route registration by checking the OpenAPI schema contains the
    path. A direct HTTP call to a non-existent run_id correctly returns 404
    (DB-backed implementation), so we verify registration via schema instead.
    """
    from services.api.main import app

    schema = app.openapi()
    assert "/runs/{run_id}/results" in schema["paths"], (
        "GET /runs/{run_id}/results route must be registered in OpenAPI schema"
    )

    # Also verify the route serves JSON for a non-existent run (404 is valid
    # behavior when the run is not found — proves the handler executed).
    client = TestClient(app)
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    response = client.get(f"/runs/{test_run_id}/results", headers=AUTH_HEADERS)
    assert response.status_code in (200, 404), f"Expected 200 or 404, got {response.status_code}"
    assert "application/json" in response.headers.get("content-type", "")


def test_ac2_runs_readiness_endpoint_exists():
    """
    AC2: GET /runs/{run_id}/readiness endpoint is registered.

    Verifies route registration via OpenAPI schema.
    """
    from services.api.main import app

    schema = app.openapi()
    assert "/runs/{run_id}/readiness" in schema["paths"], (
        "GET /runs/{run_id}/readiness route must be registered in OpenAPI schema"
    )

    client = TestClient(app)
    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    response = client.get(f"/runs/{test_run_id}/readiness", headers=AUTH_HEADERS)
    assert response.status_code in (200, 404), f"Expected 200 or 404, got {response.status_code}"
    assert "application/json" in response.headers.get("content-type", "")


def test_ac2_promotions_request_endpoint_exists():
    """
    AC2: POST /promotions/request endpoint is registered.

    FAILURE MODE: 404 Not Found if route not registered.
    """
    from services.api.main import app

    client = TestClient(app)

    # Minimal payload structure expected by contract
    payload = {
        "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0V",
        "target_environment": "paper",
        "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W",
    }

    response = client.post("/promotions/request", json=payload, headers=AUTH_HEADERS)

    assert response.status_code != 404, "POST /promotions/request route must be registered"


def test_ac2_approvals_approve_endpoint_exists():
    """
    AC2: POST /approvals/{id}/approve endpoint is registered.

    With M14-T3 GovernanceService, the endpoint returns 404 for non-existent
    approvals (correct behaviour). We verify the route is registered by
    checking the response detail contains the approval_id (service-level 404,
    not a framework-level 'route not found' 404).

    The approval endpoint enforces approvals:write scope, so we use a
    reviewer-role JWT instead of the default operator TEST_TOKEN.
    """
    from services.api.auth import create_access_token
    from services.api.main import app

    client = TestClient(app)

    # Reviewer role has approvals:write scope
    reviewer_token = create_access_token(
        user_id="01HABCDEF00000000000000099",
        role="reviewer",
        expires_minutes=60,
    )
    reviewer_headers = {"Authorization": f"Bearer {reviewer_token}"}

    test_approval_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    payload = {"approver_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0W", "decision": "approved"}

    response = client.post(
        f"/approvals/{test_approval_id}/approve", json=payload, headers=reviewer_headers
    )

    # Service-level 404 (approval not found in mock store) proves the route
    # is registered and delegates correctly to the service layer.
    assert response.status_code == 404
    assert test_approval_id in response.json()["detail"]


def test_ac2_audit_endpoint_exists():
    """
    AC2: GET /audit endpoint is registered.

    FAILURE MODE: 404 Not Found if route not registered.
    """
    from services.api.main import app

    client = TestClient(app)

    response = client.get("/audit", headers=AUTH_HEADERS)

    assert response.status_code != 404, "GET /audit route must be registered"


def test_ac3_application_can_start_without_dependencies():
    """
    AC3: Application can be instantiated (stub implementations allowed).

    FAILURE MODE: Exception during TestClient instantiation if app cannot start.
    """
    from services.api.main import app

    try:
        client = TestClient(app)
        # If we get here, the app can at least instantiate
        assert client is not None
    except Exception as e:
        pytest.fail(f"Application failed to instantiate: {e}")


def test_ac3_application_has_openapi_schema():
    """
    AC3: Application generates OpenAPI schema (proves FastAPI is properly configured).

    FAILURE MODE: Exception or None if schema generation fails.
    """
    from services.api.main import app

    schema = app.openapi()

    assert schema is not None, "Application must generate OpenAPI schema"
    assert "openapi" in schema, "Schema must have 'openapi' version field"
    assert "paths" in schema, "Schema must have 'paths' section"

    # Verify our core endpoints are in the schema
    paths = schema["paths"]
    assert "/runs/{run_id}/results" in paths, "Results endpoint must appear in OpenAPI schema"
    assert "/promotions/request" in paths, "Promotions endpoint must appear in OpenAPI schema"
    assert "/audit" in paths, "Audit endpoint must appear in OpenAPI schema"


def test_ac3_all_endpoints_return_json_or_error():
    """
    AC3: All registered endpoints return JSON or proper error responses.

    FAILURE MODE: Text/HTML responses indicate misconfigured endpoints.
    """
    from services.api.main import app

    client = TestClient(app)

    test_run_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"

    endpoints_to_test = [
        ("GET", f"/runs/{test_run_id}/results"),
        ("GET", f"/runs/{test_run_id}/readiness"),
        ("GET", "/audit"),
    ]

    for method, path in endpoints_to_test:
        if method == "GET":
            response = client.get(path, headers=AUTH_HEADERS)

        # We don't care about status code, just that response is JSON-structured
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type or response.status_code in [404, 405], (
            f"{method} {path} must return JSON or proper HTTP error, got: {content_type}"
        )

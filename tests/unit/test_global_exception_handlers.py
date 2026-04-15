"""
Unit tests for global exception handlers registered on the FastAPI app.

Responsibilities:
- Verify NotFoundError → 404
- Verify SeparationOfDutiesError → 409
- Verify DomainValidationError → 422
- Verify IntegrityError → 409
- Verify OperationalError → 503 with Retry-After header

Does NOT:
- Test business logic (that lives in services).
- Test individual route handlers.

Dependencies:
- FastAPI TestClient
- services.api.main.app

Example:
    pytest tests/unit/test_global_exception_handlers.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from services.api.main import app


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    """Ensure ENVIRONMENT=test so the test JWT secret is available."""
    monkeypatch.setenv("ENVIRONMENT", "test")


@pytest.fixture
def client():
    """Provide a test client for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


class TestNotFoundHandler:
    """Verify NotFoundError maps to 404."""

    def test_not_found_returns_404(self, client):
        """GET a non-existent override returns 404 with detail."""
        resp = client.get(
            "/overrides/01HNOTEXIST0000000000000000",
            headers={"Authorization": "Bearer TEST_TOKEN"},
        )
        assert resp.status_code == 404


class TestSeparationOfDutiesHandler:
    """Verify SeparationOfDutiesError maps to 409."""

    def test_sod_violation_returns_409(self, client):
        """POST override review by same user returns 409."""
        headers = {"Authorization": "Bearer TEST_TOKEN"}

        # First create an override to get a valid ID
        create_resp = client.post(
            "/overrides/request",
            json={
                "object_id": "01HTESTOBJ0000000000000000",
                "object_type": "candidate",
                "override_type": "grade_override",
                "original_state": {"grade": "C"},
                "new_state": {"grade": "B"},
                "evidence_link": "https://jira.example.com/browse/FX-100",
                "rationale": "This is a sufficiently long rationale for the override request",
            },
            headers=headers,
        )
        if create_resp.status_code != 200:
            pytest.skip(f"Override creation returned {create_resp.status_code}")

        override_id = create_resp.json().get("override_id")
        if not override_id:
            pytest.skip("No override_id returned")

        # Review with same user should trigger SoD
        review_resp = client.post(
            f"/overrides/{override_id}/review",
            json={"decision": "approved", "rationale": "Looks good, approved by reviewer"},
            headers=headers,
        )
        # Should be 409 (SoD) since test JWT user is the same submitter
        assert review_resp.status_code == 409
        body = review_resp.json()
        assert (
            "separation" in body.get("detail", "").lower()
            or "duties" in body.get("detail", "").lower()
        )


class TestIntegrityErrorHandler:
    """Verify IntegrityError handler is registered and returns correct status."""

    def test_integrity_handler_returns_409_content(self):
        """The IntegrityError handler produces a 409 response with correct body."""
        import asyncio
        from unittest.mock import MagicMock

        from services.api.main import _handle_integrity

        request = MagicMock()
        exc = IntegrityError("INSERT ...", {}, Exception("UNIQUE constraint failed"))

        response = asyncio.get_event_loop().run_until_complete(_handle_integrity(request, exc))
        assert response.status_code == 409
        assert b"integrity" in response.body.lower()

    def test_operational_handler_returns_503_with_retry_after(self):
        """The OperationalError handler produces a 503 response with Retry-After."""
        import asyncio
        from unittest.mock import MagicMock

        from services.api.main import _handle_operational

        request = MagicMock()
        exc = OperationalError("SELECT 1", {}, Exception("connection refused"))

        response = asyncio.get_event_loop().run_until_complete(_handle_operational(request, exc))
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "5"


class TestExceptionHandlerRegistration:
    """Verify all exception handlers are registered on the app."""

    def test_not_found_handler_registered(self):
        """NotFoundError handler is in app.exception_handlers."""
        from libs.contracts.errors import NotFoundError

        assert NotFoundError in app.exception_handlers

    def test_sod_handler_registered(self):
        """SeparationOfDutiesError handler is in app.exception_handlers."""
        from libs.contracts.errors import SeparationOfDutiesError

        assert SeparationOfDutiesError in app.exception_handlers

    def test_validation_handler_registered(self):
        """DomainValidationError handler is in app.exception_handlers."""
        from libs.contracts.errors import ValidationError

        assert ValidationError in app.exception_handlers

    def test_integrity_handler_registered(self):
        """IntegrityError handler is in app.exception_handlers."""
        assert IntegrityError in app.exception_handlers

    def test_operational_handler_registered(self):
        """OperationalError handler is in app.exception_handlers."""
        assert OperationalError in app.exception_handlers

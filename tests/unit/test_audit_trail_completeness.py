"""
Unit tests for audit trail completeness enforcement.

Validates that the audit_action dependency correctly records audit events
after successful route handler execution, extracts actor/object_id/correlation_id/source,
and gracefully handles write failures.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from services.api.auth import AuthenticatedUser, AuthMode
from services.api.middleware.audit_trail import _make_audit_callback

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_request() -> Mock:
    """Mock HTTP request."""
    request = MagicMock(spec=Request)
    request.path_params = {"deployment_id": "01HQZ9W3JF0000000000000002"}
    request.headers = {"X-Client-Source": "web-desktop"}
    request.state = MagicMock()
    request.state._audit_callbacks = []
    return request


@pytest.fixture
def authenticated_user() -> AuthenticatedUser:
    """Sample authenticated user."""
    return AuthenticatedUser(
        user_id="01HQZ9W3JF0000000000000001",
        role="operator",
        email="operator@fxlab.io",
        scopes=["deployments:write", "orders:write"],
        auth_mode=AuthMode.LOCAL_JWT,
    )


@pytest.fixture
def mock_db_session() -> Mock:
    """Mock SQLAlchemy session for audit writes."""
    return MagicMock(spec=Session)


# ---------------------------------------------------------------------------
# Tests for _make_audit_callback
# ---------------------------------------------------------------------------


class TestMakeAuditCallback:
    """Tests for _make_audit_callback function."""

    def test_audit_callback_writes_event_with_path_param_object_id(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback writes AuditEvent with object_id extracted from path params."""
        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        # Mock write_audit_event and correlation_id_var.get
        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                # Verify write_audit_event was called with correct args
                mock_write.assert_called_once()
                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["action"] == "kill_switch.activate"
                assert call_kwargs["object_type"] == "kill_switch"
                assert call_kwargs["object_id"] == "01HQZ9W3JF0000000000000002"
                assert call_kwargs["actor"] == "user:01HQZ9W3JF0000000000000001"
                assert call_kwargs["source"] == "web-desktop"

    def test_audit_callback_extracts_object_id_via_callable(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback extracts object_id via callable."""

        def extract_id(request, path_params):
            return path_params.get("deployment_id")

        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id=extract_id,
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["object_id"] == "01HQZ9W3JF0000000000000002"

    def test_audit_callback_extracts_details_and_merges_metadata(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback merges extracted details into metadata."""

        def extract_details(request, path_params):
            return {"deployment_status": "activated", "reason": "manual"}

        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=extract_details,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                call_kwargs = mock_write.call_args[1]
                metadata = call_kwargs["metadata"]
                assert metadata["deployment_status"] == "activated"
                assert metadata["reason"] == "manual"
                assert metadata["correlation_id"] == "corr-123"

    def test_audit_callback_includes_correlation_id_in_metadata(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback includes correlation_id from context variable."""
        callback = _make_audit_callback(
            action="order.submit_live",
            object_type="order",
            extract_object_id="order_id",
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "abc-def-ghi"

                callback()

                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["metadata"]["correlation_id"] == "abc-def-ghi"

    def test_audit_callback_skips_write_if_no_authenticated_user(
        self,
        mock_db_session: Mock,
        mock_request: Mock,
    ) -> None:
        """audit_callback does not write if user is None."""
        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=None,
            user=None,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            callback()
            # Verify no write occurred
            assert not mock_write.called

    def test_audit_callback_handles_object_id_extraction_failure_gracefully(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback continues even if object_id extraction fails."""

        def bad_extract(request, path_params):
            raise ValueError("extraction failed")

        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id=bad_extract,
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                # Verify write still happened, with empty object_id
                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["object_id"] == ""

    def test_audit_callback_handles_details_extraction_failure_gracefully(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback continues even if details extraction fails."""

        def bad_extract_details(request, path_params):
            raise RuntimeError("details extraction failed")

        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=bad_extract_details,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                # Verify write still happened
                assert mock_write.called

    def test_audit_callback_does_not_fail_request_if_audit_write_fails(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback logs error but does not raise if write fails."""
        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with (
            patch(
                "services.api.middleware.audit_trail.write_audit_event",
                side_effect=RuntimeError("database connection lost"),
            ),
            patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr,
        ):
            mock_corr.get.return_value = "corr-123"
            # Should not raise
            callback()

    def test_audit_callback_extracts_source_from_header(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback extracts source from X-Client-Source header."""
        mock_request.headers = {"X-Client-Source": "mobile-app"}

        callback = _make_audit_callback(
            action="order.cancel_live",
            object_type="order",
            extract_object_id="order_id",
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["source"] == "mobile-app"

    def test_audit_callback_handles_missing_object_id_param(
        self,
        mock_db_session: Mock,
        authenticated_user: AuthenticatedUser,
        mock_request: Mock,
    ) -> None:
        """audit_callback uses empty string if object_id param is missing."""
        mock_request.path_params = {}  # No deployment_id

        callback = _make_audit_callback(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
            extract_details=None,
            user=authenticated_user,
            db=mock_db_session,
            request=mock_request,
        )

        with patch("services.api.middleware.audit_trail.write_audit_event") as mock_write:
            with patch("services.api.middleware.audit_trail.correlation_id_var") as mock_corr:
                mock_write.return_value = "audit-event-ulid"
                mock_corr.get.return_value = "corr-123"

                callback()

                call_kwargs = mock_write.call_args[1]
                assert call_kwargs["object_id"] == ""


__all__ = [
    "TestMakeAuditCallback",
]

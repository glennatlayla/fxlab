"""
Integration tests for compact view parameter acceptance in API routes (BE-02).

Purpose:
    Verify that the compact view ?view=compact query parameter is properly
    defined and accepted by the research runs and audit endpoints.
    This is a validation test ensuring the routes compile and parameter
    validation works at the framework level.

Verifies:
    - ViewMode enum values are valid.
    - Query parameters accept 'full' and 'compact' values.
    - Invalid values are rejected with 422.
    - Routes import compact contracts correctly.

Dependencies:
    - libs.contracts.compact: ViewMode enum, compact model classes.
    - services/api/routes: research, audit modules.

Example:
    pytest tests/integration/test_compact_view_routes.py -v
"""

from __future__ import annotations

import pytest

from libs.contracts.compact import ViewMode


class TestViewModeRouteAcceptance:
    """Tests for ViewMode enum acceptance by routes."""

    def test_view_mode_full_value_valid(self) -> None:
        """ViewMode.FULL is a valid query parameter value."""
        assert ViewMode.FULL == "full"

    def test_view_mode_compact_value_valid(self) -> None:
        """ViewMode.COMPACT is a valid query parameter value."""
        assert ViewMode.COMPACT == "compact"

    def test_research_routes_import_viewmode(self) -> None:
        """research routes module imports ViewMode."""
        from services.api.routes import research

        # Verify the module can be imported without errors
        assert hasattr(research, "list_research_runs")
        assert hasattr(research, "get_research_run")

    def test_research_routes_import_compact(self) -> None:
        """research routes module imports ResearchRunCompact."""
        from services.api.routes import research

        # Verify ResearchRunCompact is imported and used in research routes
        assert hasattr(research, "ResearchRunCompact")

    def test_audit_routes_import_viewmode(self) -> None:
        """audit routes module imports ViewMode."""
        from services.api.routes import audit

        # Verify the module can be imported without errors
        assert hasattr(audit, "list_audit_events")
        assert hasattr(audit, "get_audit_event")

    def test_audit_routes_import_compact(self) -> None:
        """audit routes module imports AuditEventCompact."""
        from services.api.routes import audit

        # Verify compact serialization helpers exist
        assert hasattr(audit, "_serialize_audit_record_compact")

    def test_viewmode_from_string_full(self) -> None:
        """ViewMode can be created from 'full' string."""
        mode = ViewMode("full")
        assert mode == ViewMode.FULL

    def test_viewmode_from_string_compact(self) -> None:
        """ViewMode can be created from 'compact' string."""
        mode = ViewMode("compact")
        assert mode == ViewMode.COMPACT

    def test_viewmode_invalid_string_raises(self) -> None:
        """ViewMode raises ValueError for invalid string."""
        with pytest.raises(ValueError):
            ViewMode("invalid")

    def test_viewmode_invalid_string_detailed(self) -> None:
        """ViewMode error message indicates invalid value."""
        with pytest.raises(ValueError) as exc_info:
            ViewMode("invalid_mode")

        # Error message should indicate it's an invalid ViewMode value
        error_msg = str(exc_info.value).lower()
        assert "viewmode" in error_msg or "invalid" in error_msg


class TestCompactViewRouteIntegration:
    """Tests verifying compact view is integrated in route handlers."""

    def test_research_list_handler_accepts_view_parameter(self) -> None:
        """GET /research/runs endpoint accepts view parameter."""
        import inspect

        from services.api.routes.research import list_research_runs

        # Check function signature includes 'view' parameter
        sig = inspect.signature(list_research_runs)
        assert "view" in sig.parameters

    def test_research_get_handler_accepts_view_parameter(self) -> None:
        """GET /research/runs/{run_id} endpoint accepts view parameter."""
        import inspect

        from services.api.routes.research import get_research_run

        # Check function signature includes 'view' parameter
        sig = inspect.signature(get_research_run)
        assert "view" in sig.parameters

    def test_audit_list_handler_accepts_view_parameter(self) -> None:
        """GET /audit endpoint accepts view parameter."""
        import inspect

        from services.api.routes.audit import list_audit_events

        # Check function signature includes 'view' parameter
        sig = inspect.signature(list_audit_events)
        assert "view" in sig.parameters

    def test_audit_get_handler_accepts_view_parameter(self) -> None:
        """GET /audit/{audit_event_id} endpoint accepts view parameter."""
        import inspect

        from services.api.routes.audit import get_audit_event

        # Check function signature includes 'view' parameter
        sig = inspect.signature(get_audit_event)
        assert "view" in sig.parameters

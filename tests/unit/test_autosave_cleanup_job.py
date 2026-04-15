"""
Unit tests for autosave cleanup background job (services.api.jobs.autosave_cleanup).

Tests verify:
- run_autosave_cleanup() executes the cleanup and returns success result.
- Cleanup commits the transaction when successful.
- On repository error, cleanup rolls back and returns error result.
- On database session creation error, returns error result with appropriate message.
- Structured logging is called at key points.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.api.jobs.autosave_cleanup import run_autosave_cleanup


class TestAutosaveCleanupJob:
    """Tests for run_autosave_cleanup() function."""

    def test_autosave_cleanup_success_returns_deleted_count(self) -> None:
        """
        When repository.purge_expired() succeeds, return success result with count.

        Scenario:
        - Mock get_db() to return a session.
        - Mock repository to return deleted_count=42.
        - Call run_autosave_cleanup().

        Expected:
        - Returns dict with status='success', deleted_count=42.
        - Session is committed.
        - Session is closed.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.return_value = 42

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with patch(
                "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                return_value=mock_repo,
            ):
                result = run_autosave_cleanup(max_age_days=30)

        assert result["status"] == "success"
        assert result["deleted_count"] == 42
        assert "error_msg" not in result
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_autosave_cleanup_repository_error_returns_error_result(self) -> None:
        """
        When repository.purge_expired() raises exception, return error result.

        Scenario:
        - Mock get_db() to return a session.
        - Mock repository to raise an exception.
        - Call run_autosave_cleanup().

        Expected:
        - Returns dict with status='error', deleted_count=0, error_msg present.
        - Session is rolled back.
        - Session is closed.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.side_effect = RuntimeError("DB connection lost")

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with patch(
                "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                return_value=mock_repo,
            ):
                result = run_autosave_cleanup(max_age_days=30)

        assert result["status"] == "error"
        assert result["deleted_count"] == 0
        assert "error_msg" in result
        assert "DB connection lost" in result["error_msg"]
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    def test_autosave_cleanup_session_creation_error_returns_error_result(
        self,
    ) -> None:
        """
        When get_db() raises exception, return error result.

        Scenario:
        - Mock get_db() to raise an exception.
        - Call run_autosave_cleanup().

        Expected:
        - Returns dict with status='error', deleted_count=0, error_msg present.
        - error_msg mentions session creation.
        """
        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.side_effect = RuntimeError("Database unavailable")

            result = run_autosave_cleanup(max_age_days=30)

        assert result["status"] == "error"
        assert result["deleted_count"] == 0
        assert "error_msg" in result
        assert "Failed to create database session" in result["error_msg"]

    def test_autosave_cleanup_respects_max_age_days_parameter(self) -> None:
        """
        Cleanup respects the max_age_days parameter passed to purge_expired.

        Scenario:
        - Call run_autosave_cleanup(max_age_days=60).

        Expected:
        - repository.purge_expired is called with max_age_days=60.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.return_value = 10

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with patch(
                "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                return_value=mock_repo,
            ):
                run_autosave_cleanup(max_age_days=60)

        mock_repo.purge_expired.assert_called_once_with(max_age_days=60)

    def test_autosave_cleanup_default_max_age_is_30_days(self) -> None:
        """
        When max_age_days is not provided, default is 30 days.

        Scenario:
        - Call run_autosave_cleanup() without max_age_days.

        Expected:
        - repository.purge_expired is called with max_age_days=30.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.return_value = 5

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with patch(
                "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                return_value=mock_repo,
            ):
                run_autosave_cleanup()

        mock_repo.purge_expired.assert_called_once_with(max_age_days=30)

    def test_autosave_cleanup_zero_deletions_returns_success(self) -> None:
        """
        When no autosaves are deleted, still returns success (not an error).

        Scenario:
        - Mock repository to return deleted_count=0.
        - Call run_autosave_cleanup().

        Expected:
        - Returns dict with status='success', deleted_count=0.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.return_value = 0

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with patch(
                "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                return_value=mock_repo,
            ):
                result = run_autosave_cleanup()

        assert result["status"] == "success"
        assert result["deleted_count"] == 0
        mock_session.commit.assert_called_once()

    def test_autosave_cleanup_logs_success(self) -> None:
        """
        On success, structured logging is called with correct fields.

        Scenario:
        - Mock get_db() and repository.
        - Call run_autosave_cleanup(max_age_days=30).

        Expected:
        - logger.info is called with operation='autosave_cleanup'.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.return_value = 15

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with (
                patch(
                    "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                    return_value=mock_repo,
                ),
                patch("services.api.jobs.autosave_cleanup.logger") as mock_logger,
            ):
                run_autosave_cleanup(max_age_days=30)

                # Verify logger.info was called
                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args
                assert call_args[0][0] == "autosave.cleanup.completed"
                assert call_args[1]["extra"]["operation"] == "autosave_cleanup"
                assert call_args[1]["extra"]["deleted_count"] == 15

    def test_autosave_cleanup_logs_error_on_failure(self) -> None:
        """
        On error, structured logging is called with error message.

        Scenario:
        - Mock repository to raise exception.
        - Call run_autosave_cleanup().

        Expected:
        - logger.error is called with exc_info=True.
        """
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.purge_expired.side_effect = ValueError("Invalid data")

        with patch("services.api.jobs.autosave_cleanup.get_db") as mock_get_db:
            mock_get_db.return_value = iter([mock_session])
            with (
                patch(
                    "services.api.jobs.autosave_cleanup.SqlDraftAutosaveRepository",
                    return_value=mock_repo,
                ),
                patch("services.api.jobs.autosave_cleanup.logger") as mock_logger,
            ):
                run_autosave_cleanup()

                # Verify logger.error was called
                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args
                assert call_args[0][0] == "autosave.cleanup.failed"
                assert call_args[1]["extra"]["operation"] == "autosave_cleanup"
                assert call_args[1]["exc_info"] is True

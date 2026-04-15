"""
Background cleanup job for expired draft autosaves.

Purges autosave records older than 30 days to reclaim storage space.
Intended to run on a schedule (e.g. daily via Celery) or on-demand.

Responsibilities:
- Get a database session.
- Create a repository instance.
- Call purge_expired() to delete old records.
- Log the result with structured logging.

Does NOT:
- Manage Celery task registration (that belongs in the task broker config).
- Validate autosave records.
- Handle transactional rollback (caller manages transaction semantics).

Dependencies:
- SQLAlchemy Session (from get_db()).
- SqlDraftAutosaveRepository.
- structlog for structured logging.

Example:
    # Called directly (e.g., from a Celery task or CLI):
    result = run_autosave_cleanup(max_age_days=30)
    # result == {"deleted_count": 42, "status": "success"}
"""

from __future__ import annotations

from typing import Any

import structlog

from services.api.db import get_db
from services.api.repositories.sql_draft_autosave_repository import (
    SqlDraftAutosaveRepository,
)

logger = structlog.get_logger(__name__)


def run_autosave_cleanup(max_age_days: int = 30) -> dict[str, Any]:
    """
    Execute the draft autosave cleanup job.

    Deletes all autosave records older than max_age_days and logs the result.
    This function is idempotent and safe to call multiple times.

    Args:
        max_age_days: Number of days; autosaves older than this are deleted.
                     Defaults to 30 days.

    Returns:
        Dict with cleanup result:
        - deleted_count: Number of records deleted.
        - status: "success" or "error".
        - error_msg: Present if status is "error".

    Example:
        result = run_autosave_cleanup(max_age_days=30)
        if result["status"] == "success":
            logger.info(f"Cleanup succeeded: {result['deleted_count']} records deleted")
        else:
            logger.error(f"Cleanup failed: {result['error_msg']}")
    """
    try:
        # Get a database session.
        db = next(get_db())

        try:
            # Create repository and call purge_expired.
            repo = SqlDraftAutosaveRepository(db=db)
            deleted_count = repo.purge_expired(max_age_days=max_age_days)

            # Log success with structured fields.
            logger.info(
                "autosave.cleanup.completed",
                extra={
                    "operation": "autosave_cleanup",
                    "component": "autosave_cleanup_job",
                    "deleted_count": deleted_count,
                    "max_age_days": max_age_days,
                    "result": "success",
                },
            )

            # Commit the transaction to persist deletions.
            db.commit()

            return {
                "deleted_count": deleted_count,
                "status": "success",
            }
        except Exception as e:
            # Log error and roll back the transaction.
            db.rollback()
            error_msg = f"Cleanup failed: {str(e)}"
            logger.error(
                "autosave.cleanup.failed",
                extra={
                    "operation": "autosave_cleanup",
                    "component": "autosave_cleanup_job",
                    "error": str(e),
                    "result": "failure",
                },
                exc_info=True,
            )
            return {
                "deleted_count": 0,
                "status": "error",
                "error_msg": error_msg,
            }
        finally:
            # Always close the session.
            db.close()

    except Exception as e:
        # Catch errors in session creation.
        error_msg = f"Failed to create database session: {str(e)}"
        logger.error(
            "autosave.cleanup.session_error",
            extra={
                "operation": "autosave_cleanup",
                "component": "autosave_cleanup_job",
                "error": str(e),
                "result": "failure",
            },
            exc_info=True,
        )
        return {
            "deleted_count": 0,
            "status": "error",
            "error_msg": error_msg,
        }

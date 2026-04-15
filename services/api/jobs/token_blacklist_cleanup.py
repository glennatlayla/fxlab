"""
Background cleanup job for expired token blacklist entries.

Purpose:
    Purge revoked_tokens rows whose original token has naturally expired
    (expires_at <= now), keeping the blacklist table bounded and query
    performance stable.

Responsibilities:
    - Accept a database session (caller-managed or self-managed).
    - Delegate to TokenBlacklistService.purge_expired().
    - Return a structured result dict for logging and monitoring.

Does NOT:
    - Manage Celery / APScheduler task registration.
    - Commit or close the session (caller manages lifecycle).
    - Validate individual revocation records.

Dependencies:
    - SQLAlchemy Session (injected or from get_db()).
    - TokenBlacklistService.purge_expired().
    - structlog for structured logging.

Error conditions:
    - Database unavailable: Returns status="error" with error_msg.
    - Empty table: Returns deleted_count=0, status="success".

Example:
    # Called from a Celery task, CLI, or startup hook:
    from services.api.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_token_blacklist_cleanup(db)
        db.commit()
    finally:
        db.close()
    # result == {"deleted_count": 42, "status": "success"}
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from services.api.services.token_blacklist_service import TokenBlacklistService

logger = structlog.get_logger(__name__)


def run_token_blacklist_cleanup(db: Session) -> dict[str, Any]:
    """
    Execute the token blacklist cleanup job.

    Deletes all revoked_tokens entries where expires_at <= now(). This is
    safe to call concurrently and is idempotent — running it twice in a row
    purges nothing on the second call.

    The caller is responsible for committing and closing the session. This
    allows the cleanup to participate in a larger transaction if needed
    (e.g., combined with autosave cleanup in a single batch job).

    Args:
        db: Active SQLAlchemy session. Caller owns commit/close.

    Returns:
        Dict with cleanup result:
        - deleted_count (int): Number of records deleted.
        - status (str): "success" or "error".
        - error_msg (str, optional): Present only when status is "error".

    Example:
        result = run_token_blacklist_cleanup(db)
        if result["status"] == "success":
            logger.info("cleanup.done", count=result["deleted_count"])
    """
    try:
        service = TokenBlacklistService(db)
        deleted_count = service.purge_expired()

        logger.info(
            "token_blacklist.cleanup.completed",
            deleted_count=deleted_count,
            result="success",
            component="token_blacklist_cleanup",
        )

        return {
            "deleted_count": deleted_count,
            "status": "success",
        }

    except Exception as exc:
        error_msg = f"Token blacklist cleanup failed: {exc}"
        logger.error(
            "token_blacklist.cleanup.failed",
            error=str(exc),
            result="failure",
            component="token_blacklist_cleanup",
            exc_info=True,
        )
        return {
            "deleted_count": 0,
            "status": "error",
            "error_msg": error_msg,
        }

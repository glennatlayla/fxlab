"""
SQL transaction manager — SQLAlchemy-backed explicit commit/rollback.

Purpose:
    Implement TransactionManagerInterface by wrapping a SQLAlchemy Session,
    allowing service-layer code to control transaction boundaries without
    directly depending on SQLAlchemy.

Responsibilities:
    - commit: Call session.commit() to make all pending flushes durable.
    - rollback: Call session.rollback() to discard uncommitted changes.

Does NOT:
    - Create or close sessions (injected by caller).
    - Contain business logic.
    - Manage session lifecycle (caller / middleware responsibility).

Dependencies:
    - SQLAlchemy Session (injected).
    - structlog for logging commit/rollback events.

Error conditions:
    - commit may raise on constraint violations or connection failures.
    - rollback is best-effort (logs errors, does not re-raise).

Example:
    from services.api.db import SessionLocal
    session = SessionLocal()
    tx = SqlTransactionManager(db=session)
    tx.commit()   # make pending flushes durable
    tx.rollback() # discard uncommitted changes
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.transaction_manager_interface import (
    TransactionManagerInterface,
)

logger = structlog.get_logger(__name__)


class SqlTransactionManager(TransactionManagerInterface):
    """
    SQLAlchemy-backed transaction manager.

    Wraps a Session and exposes commit/rollback for explicit transaction
    boundary control in service-layer orchestration methods.

    Responsibilities:
        - Commit pending flushes to make changes durable.
        - Rollback on error to discard uncommitted work.

    Does NOT:
        - Create or close the session.
        - Manage connection pooling.

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        tx = SqlTransactionManager(db=session)
        order_repo.save(...)   # flush only
        tx.commit()            # make order durable
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize with an active SQLAlchemy session.

        Args:
            db: The SQLAlchemy session whose transactions this manager controls.
        """
        self._db = db

    def commit(self) -> None:
        """
        Commit all pending database changes.

        Delegates to ``session.commit()``.  On success, all flushed
        changes become durable.  On failure, the caller should invoke
        ``rollback()`` to clean up.

        Raises:
            Exception: Propagates any SQLAlchemy commit errors (integrity,
                connection, serialization failures).
        """
        self._db.commit()
        logger.debug(
            "tx.committed",
            component="SqlTransactionManager",
            operation="commit",
        )

    def rollback(self) -> None:
        """
        Roll back all uncommitted changes.

        Best-effort: logs errors but never re-raises so callers can
        use it safely in finally blocks.
        """
        try:
            self._db.rollback()
            logger.debug(
                "tx.rolled_back",
                component="SqlTransactionManager",
                operation="rollback",
            )
        except Exception:
            logger.warning(
                "tx.rollback_failed",
                component="SqlTransactionManager",
                operation="rollback",
                exc_info=True,
            )

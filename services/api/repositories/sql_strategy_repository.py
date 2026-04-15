"""
SQL-backed strategy repository.

Responsibilities:
- Persist strategy records to the strategies table via SQLAlchemy.
- Implement create, get_by_id, list, update, deactivate operations.
- Generate ULID primary keys for new records.
- Use flush() (not commit()) to stay within request-scoped transactions.

Does NOT:
- Contain business logic or DSL validation.
- Manage database sessions (caller provides via DI).
- Handle retry logic (infrastructure layer responsibility).

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.Strategy ORM model.
- python-ulid for ID generation.

Error conditions:
- SQLAlchemyError propagated to service layer for handling.

Example:
    repo = SqlStrategyRepository(db=session)
    strategy = repo.create(name="RSI Reversal", code="RSI(14) < 30", created_by="01HUSER001")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import desc
from sqlalchemy.orm import Session
from ulid import ULID

from libs.contracts.interfaces.strategy_repository_interface import (
    StrategyRepositoryInterface,
)
from libs.contracts.models import Strategy

logger = structlog.get_logger(__name__)


def _strategy_to_dict(record: Strategy) -> dict[str, Any]:
    """
    Convert a Strategy ORM instance to a plain dict.

    Args:
        record: SQLAlchemy Strategy model instance.

    Returns:
        Dict with all strategy fields serialised for layer decoupling.
    """
    return {
        "id": record.id,
        "name": record.name,
        "code": record.code,
        "version": record.version,
        "created_by": record.created_by,
        "is_active": record.is_active,
        "row_version": record.row_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


class SqlStrategyRepository(StrategyRepositoryInterface):
    """
    SQLAlchemy-backed strategy repository.

    Responsibilities:
    - CRUD operations on the strategies table.
    - ULID generation for new records.
    - Optimistic locking via row_version on updates.

    Does NOT:
    - Commit transactions (uses flush — caller commits).
    - Validate DSL syntax.

    Dependencies:
    - SQLAlchemy Session (injected via constructor).

    Example:
        repo = SqlStrategyRepository(db=session)
        strategy = repo.create(name="RSI Reversal", code="RSI(14) < 30", created_by="01HUSER001")
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        name: str,
        code: str,
        created_by: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new strategy record with a generated ULID.

        Args:
            name: Human-readable strategy name.
            code: Strategy DSL source code.
            created_by: ULID of the creating user.
            version: Optional semantic version string.

        Returns:
            Dict representation of the created strategy.
        """
        strategy_id = str(ULID())
        record = Strategy(
            id=strategy_id,
            name=name,
            code=code,
            version=version or "0.1.0",
            created_by=created_by,
            is_active=True,
        )
        self._db.add(record)
        self._db.flush()

        logger.info(
            "strategy.created",
            strategy_id=strategy_id,
            name=name,
            created_by=created_by,
            component="SqlStrategyRepository",
        )
        return _strategy_to_dict(record)

    def get_by_id(self, strategy_id: str) -> dict[str, Any] | None:
        """
        Retrieve a strategy by ULID.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Strategy dict or None if not found.
        """
        record = self._db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if record is None:
            return None
        return _strategy_to_dict(record)

    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List strategies with optional filters and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active status.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of strategy dicts ordered by created_at descending.
        """
        query = self._db.query(Strategy)
        if created_by is not None:
            query = query.filter(Strategy.created_by == created_by)
        if is_active is not None:
            query = query.filter(Strategy.is_active == is_active)

        records = query.order_by(desc(Strategy.created_at)).limit(limit).offset(offset).all()
        return [_strategy_to_dict(r) for r in records]

    def update(
        self,
        strategy_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
        version: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        Update strategy fields with optimistic locking.

        Args:
            strategy_id: ULID of the strategy.
            name: New name (optional).
            code: New DSL code (optional).
            version: New version (optional).
            is_active: New active status (optional).

        Returns:
            Updated strategy dict, or None if not found.
        """
        record = self._db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if record is None:
            return None

        if name is not None:
            record.name = name
        if code is not None:
            record.code = code
        if version is not None:
            record.version = version
        if is_active is not None:
            record.is_active = is_active

        # Optimistic locking: bump row_version
        record.row_version = record.row_version + 1

        self._db.flush()
        logger.info(
            "strategy.updated",
            strategy_id=strategy_id,
            row_version=record.row_version,
            component="SqlStrategyRepository",
        )
        return _strategy_to_dict(record)

    def deactivate(self, strategy_id: str) -> bool:
        """
        Soft-delete by setting is_active=False.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            True if found and deactivated, False if not found.
        """
        record = self._db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if record is None:
            return False

        record.is_active = False
        record.row_version = record.row_version + 1
        self._db.flush()

        logger.info(
            "strategy.deactivated",
            strategy_id=strategy_id,
            component="SqlStrategyRepository",
        )
        return True

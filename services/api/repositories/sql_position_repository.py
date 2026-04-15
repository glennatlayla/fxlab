"""
SQL repository for position records.

Purpose:
    Persist and retrieve position state via SQLAlchemy, providing
    a production-grade replacement for the in-memory MockPositionRepository.

Responsibilities:
    - Create and retrieve position records by deployment + symbol composite key.
    - Update specific position fields (quantity, P&L, etc.) without overwriting unchanged data.
    - Support pessimistic row-level locking for safe concurrent updates (get_for_update).
    - Generate ULID primary keys for new position records.

Does NOT:
    - Calculate position P&L (service layer responsibility).
    - Enforce risk limits or position size constraints (service layer responsibility).
    - Contain business logic or position reconciliation orchestration.

Dependencies:
    - SQLAlchemy Session (injected via get_db per request).
    - libs.contracts.models.Position ORM model.
    - libs.contracts.errors.NotFoundError, ExternalServiceError.

Error conditions:
    - get_by_deployment_and_symbol: returns None when position does not exist (not raises).
    - update_position: raises NotFoundError when position_id does not exist.
    - get_for_update: returns None if position does not exist; raises ExternalServiceError
      if row is locked by another transaction (NOWAIT semantics).

Example:
    db = next(get_db())
    repo = SqlPositionRepository(db=db)
    pos = repo.save(
        deployment_id="01HDEPLOY...",
        symbol="AAPL",
        quantity="100",
        average_entry_price="150.00",
    )
    pos = repo.get_for_update(deployment_id="01HDEPLOY...", symbol="AAPL")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from libs.contracts.errors import ExternalServiceError, NotFoundError
from libs.contracts.interfaces.position_repository_interface import (
    PositionRepositoryInterface,
)
from libs.contracts.models import Position

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID for new records.

    Uses python-ulid which is thread-safe and produces spec-compliant
    26-character Crockford base32 ULIDs with millisecond-precision
    timestamps and 80 bits of cryptographic randomness.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class SqlPositionRepository(PositionRepositoryInterface):
    """
    SQLAlchemy-backed repository for position records.

    Responsibilities:
    - CRUD operations for position state.
    - Pessimistic locking for safe concurrent updates.
    - Lookup by deployment + symbol composite key.
    - Generate ULID primary keys for new position records.

    Does NOT:
    - Contain business logic or P&L calculation.
    - Call session.commit() — uses flush() to stay within the
      request-scoped transaction managed by get_db().

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlPositionRepository(db=session)
        pos = repo.save(
            deployment_id="01HDEPLOY...",
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
        )
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _position_to_dict(record: Position) -> dict[str, Any]:
        """
        Convert a Position ORM instance to a plain dict.

        Returns a dict with keys matching the interface contract so
        callers don't need to change based on storage implementation.

        Args:
            record: The ORM model instance.

        Returns:
            Dict with all position detail fields.
        """
        return {
            "id": record.id,
            "deployment_id": record.deployment_id,
            "symbol": record.symbol,
            "quantity": record.quantity,
            "average_entry_price": record.average_entry_price,
            "market_price": record.market_price,
            "market_value": record.market_value,
            "unrealized_pnl": record.unrealized_pnl,
            "realized_pnl": record.realized_pnl,
            "cost_basis": record.cost_basis,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def save(
        self,
        *,
        deployment_id: str,
        symbol: str,
        quantity: str,
        average_entry_price: str,
        market_price: str = "0",
        market_value: str = "0",
        unrealized_pnl: str = "0",
        realized_pnl: str = "0",
        cost_basis: str = "0",
    ) -> dict[str, Any]:
        """
        Persist a new position record.

        Generates a ULID primary key. All monetary values stored as strings
        for decimal precision safety.

        Args:
            deployment_id: Owning deployment ULID.
            symbol: Instrument ticker (e.g. "AAPL").
            quantity: Current position quantity as string (negative = short).
            average_entry_price: Volume-weighted average entry price.
            market_price: Last known market price (default "0").
            market_value: Current market value (default "0").
            unrealized_pnl: Unrealized profit/loss (default "0").
            realized_pnl: Realized profit/loss (default "0").
            cost_basis: Total cost basis (default "0").

        Returns:
            Dict with all position fields including generated id and timestamps.

        Example:
            result = repo.save(
                deployment_id="01HDEPLOY...",
                symbol="AAPL",
                quantity="100",
                average_entry_price="150.00",
            )
            # result["id"] == "01HPOS..."
        """
        record = Position(
            id=_generate_ulid(),
            deployment_id=deployment_id,
            symbol=symbol,
            quantity=quantity,
            average_entry_price=average_entry_price,
            market_price=market_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            cost_basis=cost_basis,
        )

        self._db.add(record)
        self._db.flush()

        logger.debug(
            "position_repository.position_created",
            position_id=record.id,
            deployment_id=deployment_id,
            symbol=symbol,
            quantity=quantity,
            component="sql_position_repository",
        )

        return self._position_to_dict(record)

    def get_by_deployment_and_symbol(
        self,
        *,
        deployment_id: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Look up a position by deployment and symbol.

        Args:
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.

        Returns:
            Dict with all position fields, or None if no position exists.

        Example:
            pos = repo.get_by_deployment_and_symbol(
                deployment_id="01HDEPLOY...",
                symbol="AAPL",
            )
        """
        record = (
            self._db.query(Position)
            .filter(
                Position.deployment_id == deployment_id,
                Position.symbol == symbol,
            )
            .first()
        )

        if record is None:
            return None

        logger.debug(
            "position_repository.position_retrieved",
            deployment_id=deployment_id,
            symbol=symbol,
            component="sql_position_repository",
        )

        return self._position_to_dict(record)

    def list_by_deployment(self, *, deployment_id: str) -> list[dict[str, Any]]:
        """
        List all positions for a deployment.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of position dicts. Returns empty list if no positions exist.

        Example:
            positions = repo.list_by_deployment(deployment_id="01HDEPLOY...")
        """
        records = self._db.query(Position).filter(Position.deployment_id == deployment_id).all()

        logger.debug(
            "position_repository.positions_listed",
            deployment_id=deployment_id,
            count=len(records),
            component="sql_position_repository",
        )

        return [self._position_to_dict(r) for r in records]

    def update_position(
        self,
        *,
        position_id: str,
        quantity: str | None = None,
        average_entry_price: str | None = None,
        market_price: str | None = None,
        market_value: str | None = None,
        unrealized_pnl: str | None = None,
        realized_pnl: str | None = None,
        cost_basis: str | None = None,
    ) -> dict[str, Any]:
        """
        Update specific fields on an existing position.

        Only non-None fields are updated. The updated_at timestamp is
        automatically refreshed by the ORM onupdate handler.

        Args:
            position_id: ULID of the position to update.
            quantity: New quantity (if changed).
            average_entry_price: New average entry price (if changed).
            market_price: New market price (if changed).
            market_value: New market value (if changed).
            unrealized_pnl: New unrealized P&L (if changed).
            realized_pnl: New realized P&L (if changed).
            cost_basis: New cost basis (if changed).

        Returns:
            Updated position dict.

        Raises:
            NotFoundError: If no position exists with this ID.

        Example:
            result = repo.update_position(
                position_id="01HPOS...",
                market_price="180.00",
                unrealized_pnl="500.00",
            )
        """
        record = self._db.get(Position, position_id)
        if record is None:
            raise NotFoundError(f"Position '{position_id}' not found")

        if quantity is not None:
            record.quantity = quantity
        if average_entry_price is not None:
            record.average_entry_price = average_entry_price
        if market_price is not None:
            record.market_price = market_price
        if market_value is not None:
            record.market_value = market_value
        if unrealized_pnl is not None:
            record.unrealized_pnl = unrealized_pnl
        if realized_pnl is not None:
            record.realized_pnl = realized_pnl
        if cost_basis is not None:
            record.cost_basis = cost_basis

        self._db.flush()

        logger.debug(
            "position_repository.position_updated",
            position_id=position_id,
            component="sql_position_repository",
        )

        return self._position_to_dict(record)

    def get_for_update(
        self,
        *,
        deployment_id: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Acquire a pessimistic row-level lock on a position for safe update.

        Uses SELECT ... FOR UPDATE NOWAIT on PostgreSQL to immediately fail
        if the row is already locked by another transaction. On SQLite (which
        does not support FOR UPDATE), falls back to a regular query (SQLite
        uses optimistic locking via AUTOINCREMENT).

        Must be called within an active database transaction. The lock is
        released when the transaction commits or rolls back.

        Args:
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.

        Returns:
            Dict with all position fields (locked row), or None if no
            position exists for this deployment + symbol.

        Raises:
            ExternalServiceError: If the row is already locked by another
                transaction (NOWAIT semantics) — PostgreSQL only.

        Example:
            pos = repo.get_for_update(deployment_id="01HDEPLOY...", symbol="AAPL")
        """
        try:
            # On PostgreSQL, FOR UPDATE NOWAIT fails fast if locked.
            # On SQLite, FOR UPDATE is silently ignored, so we just do a normal query.
            record = (
                self._db.query(Position)
                .filter(
                    Position.deployment_id == deployment_id,
                    Position.symbol == symbol,
                )
                .with_for_update(nowait=True)
                .first()
            )
        except OperationalError as e:
            # SQLite does not support FOR UPDATE; catch the error and retry without it.
            # PostgreSQL will raise if NOWAIT fails (lock held by another transaction).
            if "FOR UPDATE" in str(e).upper() or "sqlite" in str(e).lower():
                # SQLite compatibility: fall back to regular query
                record = (
                    self._db.query(Position)
                    .filter(
                        Position.deployment_id == deployment_id,
                        Position.symbol == symbol,
                    )
                    .first()
                )
            else:
                # Lock is held by another transaction (PostgreSQL NOWAIT)
                raise ExternalServiceError("Position row locked by another transaction") from e

        if record is None:
            return None

        logger.debug(
            "position_repository.position_locked_for_update",
            deployment_id=deployment_id,
            symbol=symbol,
            component="sql_position_repository",
        )

        return self._position_to_dict(record)

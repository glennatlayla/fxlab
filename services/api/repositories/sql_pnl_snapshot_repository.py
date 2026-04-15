"""
SQL repository for daily P&L snapshots.

Purpose:
    Persist and retrieve daily P&L snapshots via SQLAlchemy, providing
    a production-grade implementation of PnlSnapshotRepositoryInterface.

Responsibilities:
    - Record daily P&L snapshots with upsert semantics (deployment + date).
    - Retrieve snapshots by deployment and date range.
    - Generate ULID primary keys for new snapshot records.
    - Delete snapshots for deployment cleanup.

Does NOT:
    - Calculate P&L values (PnlAttributionService responsibility).
    - Aggregate timeseries data (PnlAttributionService responsibility).
    - Contain business logic or order processing.

Dependencies:
    - SQLAlchemy Session (injected via get_db per request).
    - libs.contracts.models.PnlSnapshot ORM model.
    - libs.contracts.interfaces.pnl_snapshot_repository_interface.

Error conditions:
    - list_by_deployment: returns empty list when no snapshots exist.
    - get_by_deployment_and_date: returns None when no snapshot exists.

Example:
    db = next(get_db())
    repo = SqlPnlSnapshotRepository(db=db)
    snapshot = repo.save(
        deployment_id="01HDEPLOY...",
        snapshot_date=date(2026, 4, 12),
        realized_pnl="1250.50",
        unrealized_pnl="340.25",
        commission="52.00",
        fees="0",
        positions_count=5,
    )
    snapshots = repo.list_by_deployment(
        deployment_id="01HDEPLOY...",
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 12),
    )
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.pnl_snapshot_repository_interface import (
    PnlSnapshotRepositoryInterface,
)
from libs.contracts.models import PnlSnapshot

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class SqlPnlSnapshotRepository(PnlSnapshotRepositoryInterface):
    """
    SQLAlchemy-backed repository for daily P&L snapshots.

    Responsibilities:
    - Persist snapshots with upsert semantics (deployment + date).
    - Query snapshots by deployment and date range.
    - Generate ULID primary keys for new records.

    Does NOT:
    - Contain business logic or P&L calculation.
    - Call session.commit() — uses flush() to stay within the
      request-scoped transaction managed by get_db().

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlPnlSnapshotRepository(db=session)
        snapshot = repo.save(
            deployment_id="01HDEPLOY...",
            snapshot_date=date(2026, 4, 12),
            realized_pnl="1250.50",
            unrealized_pnl="340.25",
        )
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _snapshot_to_dict(record: PnlSnapshot) -> dict[str, Any]:
        """
        Convert a PnlSnapshot ORM instance to a plain dict.

        Returns a dict matching the interface contract so callers
        don't need to change based on storage implementation.

        Args:
            record: The ORM model instance.

        Returns:
            Dict with all snapshot fields.
        """
        return {
            "id": record.id,
            "deployment_id": record.deployment_id,
            "snapshot_date": (record.snapshot_date.isoformat() if record.snapshot_date else None),
            "realized_pnl": record.realized_pnl,
            "unrealized_pnl": record.unrealized_pnl,
            "commission": record.commission,
            "fees": record.fees,
            "positions_count": record.positions_count,
            "created_at": (record.created_at.isoformat() if record.created_at else None),
            "updated_at": (record.updated_at.isoformat() if record.updated_at else None),
        }

    def save(
        self,
        *,
        deployment_id: str,
        snapshot_date: date,
        realized_pnl: str,
        unrealized_pnl: str,
        commission: str = "0",
        fees: str = "0",
        positions_count: int = 0,
    ) -> dict[str, Any]:
        """
        Persist a daily P&L snapshot with upsert semantics.

        If a snapshot already exists for this deployment + date, updates its
        values. Otherwise, creates a new record with a ULID primary key.
        All monetary values stored as strings for decimal precision safety.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date of the snapshot.
            realized_pnl: Cumulative realized P&L as string.
            unrealized_pnl: Current unrealized P&L as string.
            commission: Cumulative commissions as string.
            fees: Cumulative fees as string.
            positions_count: Number of open positions.

        Returns:
            Dict with all snapshot fields including id and timestamps.

        Example:
            result = repo.save(
                deployment_id="01HDEPLOY...",
                snapshot_date=date(2026, 4, 12),
                realized_pnl="1250.50",
                unrealized_pnl="340.25",
                commission="52.00",
                fees="0",
                positions_count=5,
            )
        """
        # Check for existing snapshot (upsert)
        existing = (
            self._db.query(PnlSnapshot)
            .filter(
                PnlSnapshot.deployment_id == deployment_id,
                PnlSnapshot.snapshot_date == snapshot_date,
            )
            .first()
        )

        if existing:
            # Update existing snapshot
            existing.realized_pnl = realized_pnl
            existing.unrealized_pnl = unrealized_pnl
            existing.commission = commission
            existing.fees = fees
            existing.positions_count = positions_count
            self._db.flush()

            logger.debug(
                "pnl_snapshot_repository.snapshot_updated",
                snapshot_id=existing.id,
                deployment_id=deployment_id,
                snapshot_date=snapshot_date.isoformat(),
                component="sql_pnl_snapshot_repository",
            )

            return self._snapshot_to_dict(existing)

        # Create new snapshot
        record = PnlSnapshot(
            id=_generate_ulid(),
            deployment_id=deployment_id,
            snapshot_date=snapshot_date,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            commission=commission,
            fees=fees,
            positions_count=positions_count,
        )

        self._db.add(record)
        self._db.flush()

        logger.debug(
            "pnl_snapshot_repository.snapshot_persisted",
            snapshot_id=record.id,
            deployment_id=deployment_id,
            snapshot_date=snapshot_date.isoformat(),
            component="sql_pnl_snapshot_repository",
        )

        return self._snapshot_to_dict(record)

    def get_by_deployment_and_date(
        self,
        *,
        deployment_id: str,
        snapshot_date: date,
    ) -> dict[str, Any] | None:
        """
        Retrieve a snapshot for a specific deployment and date.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date of the snapshot.

        Returns:
            Dict with all snapshot fields, or None if not found.

        Example:
            snap = repo.get_by_deployment_and_date(
                deployment_id="01HDEPLOY...",
                snapshot_date=date(2026, 4, 12),
            )
        """
        record = (
            self._db.query(PnlSnapshot)
            .filter(
                PnlSnapshot.deployment_id == deployment_id,
                PnlSnapshot.snapshot_date == snapshot_date,
            )
            .first()
        )

        if record is None:
            return None

        logger.debug(
            "pnl_snapshot_repository.snapshot_retrieved",
            deployment_id=deployment_id,
            snapshot_date=snapshot_date.isoformat(),
            component="sql_pnl_snapshot_repository",
        )

        return self._snapshot_to_dict(record)

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """
        List snapshots for a deployment within a date range.

        Returns snapshots ordered by snapshot_date ascending (earliest first),
        inclusive of both date_from and date_to.

        Args:
            deployment_id: Deployment ULID.
            date_from: Inclusive start date.
            date_to: Inclusive end date.

        Returns:
            List of snapshot dicts ordered by date ascending.
            Empty list if no snapshots exist in the range.

        Example:
            snapshots = repo.list_by_deployment(
                deployment_id="01HDEPLOY...",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 12),
            )
        """
        records = (
            self._db.query(PnlSnapshot)
            .filter(
                PnlSnapshot.deployment_id == deployment_id,
                PnlSnapshot.snapshot_date >= date_from,
                PnlSnapshot.snapshot_date <= date_to,
            )
            .order_by(PnlSnapshot.snapshot_date.asc())
            .all()
        )

        logger.debug(
            "pnl_snapshot_repository.snapshots_listed",
            deployment_id=deployment_id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            count=len(records),
            component="sql_pnl_snapshot_repository",
        )

        return [self._snapshot_to_dict(r) for r in records]

    def delete_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> int:
        """
        Delete all snapshots for a deployment.

        Used during deployment reset or cleanup.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Number of records deleted.

        Example:
            count = repo.delete_by_deployment(deployment_id="01HDEPLOY...")
        """
        count = (
            self._db.query(PnlSnapshot)
            .filter(PnlSnapshot.deployment_id == deployment_id)
            .delete(synchronize_session="fetch")
        )

        self._db.flush()

        logger.info(
            "pnl_snapshot_repository.snapshots_deleted",
            deployment_id=deployment_id,
            count=count,
            component="sql_pnl_snapshot_repository",
        )

        return count

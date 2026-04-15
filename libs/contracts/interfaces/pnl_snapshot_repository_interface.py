"""
P&L snapshot repository interface (port).

Responsibilities:
- Define the abstract contract for daily P&L snapshot persistence.
- Support saving, retrieving, and listing snapshots by deployment and date range.
- Support upsert semantics (save-or-update by deployment + snapshot_date).

Does NOT:
- Implement storage logic.
- Calculate P&L values (service layer responsibility).
- Aggregate timeseries data (service layer responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised when a specific snapshot is not found.

Example:
    repo: PnlSnapshotRepositoryInterface = SqlPnlSnapshotRepository(db=session)
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

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class PnlSnapshotRepositoryInterface(ABC):
    """
    Port interface for daily P&L snapshot persistence.

    Responsibilities:
    - Append-only persistence of daily P&L snapshots.
    - Retrieval by deployment and date range.
    - Upsert for idempotent snapshot creation (same deployment + date).

    Does NOT:
    - Compute P&L values.
    - Aggregate snapshots into timeseries or summaries.
    """

    @abstractmethod
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
        Persist a daily P&L snapshot.

        If a snapshot already exists for this deployment + date, it is updated
        (upsert semantics). Generates a ULID primary key for new records.
        All monetary values stored as strings for decimal precision safety.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date of the snapshot (date only, no time component).
            realized_pnl: Cumulative realized P&L as string.
            unrealized_pnl: Current unrealized P&L as string.
            commission: Cumulative commissions as string.
            fees: Cumulative fees as string.
            positions_count: Number of open positions at snapshot time.

        Returns:
            Dict with all snapshot fields including generated id and timestamps.
        """
        ...

    @abstractmethod
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
            snapshot_date: Date of the snapshot to retrieve.

        Returns:
            Dict with all snapshot fields, or None if no snapshot exists.
        """
        ...

    @abstractmethod
    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """
        List all snapshots for a deployment within a date range.

        Returns snapshots ordered by snapshot_date ascending (earliest first),
        inclusive of both date_from and date_to.

        Args:
            deployment_id: Deployment ULID.
            date_from: Inclusive start date.
            date_to: Inclusive end date.

        Returns:
            List of snapshot dicts ordered by snapshot_date ascending.
            Returns empty list if no snapshots exist in the range.
        """
        ...

    @abstractmethod
    def delete_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> int:
        """
        Delete all snapshots for a deployment.

        Used during deployment reset or cleanup operations.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Number of records deleted.
        """
        ...

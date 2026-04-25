"""
In-memory mock for PnlSnapshotRepositoryInterface.

Purpose:
    Provide a fast, deterministic P&L snapshot repository for unit tests.
    Behavioural parity with SqlPnlSnapshotRepository.

Responsibilities:
    - Store snapshots in an in-memory dict.
    - Support upsert by deployment_id + snapshot_date.
    - Provide introspection helpers for test assertions.

Does NOT:
    - Persist data across process restarts.
    - Use SQL or any external storage.

Dependencies:
    - None (pure in-memory implementation).

Example:
    repo = MockPnlSnapshotRepository()
    repo.save(
        deployment_id="01HDEPLOY...",
        snapshot_date=date(2026, 4, 12),
        realized_pnl="1250.50",
        unrealized_pnl="340.25",
    )
    all_snaps = repo.get_all()
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from libs.contracts.interfaces.pnl_snapshot_repository_interface import (
    PnlSnapshotRepositoryInterface,
)


def _generate_ulid() -> str:
    """Generate a ULID for new records."""
    import ulid as _ulid

    return str(_ulid.ULID())


class MockPnlSnapshotRepository(PnlSnapshotRepositoryInterface):
    """
    In-memory implementation of PnlSnapshotRepositoryInterface for testing.

    Responsibilities:
    - Dict-backed snapshot storage keyed by (deployment_id, snapshot_date).
    - Full interface parity with SqlPnlSnapshotRepository.
    - Introspection helpers for test assertions.

    Does NOT:
    - Use SQL or any external I/O.
    - Persist data beyond the process lifetime.

    Example:
        repo = MockPnlSnapshotRepository()
        repo.save(deployment_id="d1", snapshot_date=date(2026, 4, 12),
                   realized_pnl="100", unrealized_pnl="50")
        assert repo.count() == 1
    """

    def __init__(self) -> None:
        # Keyed by (deployment_id, snapshot_date_iso) for upsert lookup.
        self._store: dict[str, dict[str, Any]] = {}
        # Index for fast composite key lookup.
        self._composite_index: dict[tuple[str, str], str] = {}

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
        Persist a snapshot with upsert semantics.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date of the snapshot.
            realized_pnl: Realized P&L as string.
            unrealized_pnl: Unrealized P&L as string.
            commission: Commissions as string.
            fees: Fees as string.
            positions_count: Number of open positions.

        Returns:
            Dict with all snapshot fields.
        """
        composite_key = (deployment_id, snapshot_date.isoformat())
        now = datetime.now(UTC).isoformat()

        if composite_key in self._composite_index:
            # Upsert: update existing
            record_id = self._composite_index[composite_key]
            record = self._store[record_id]
            record["realized_pnl"] = realized_pnl
            record["unrealized_pnl"] = unrealized_pnl
            record["commission"] = commission
            record["fees"] = fees
            record["positions_count"] = positions_count
            record["updated_at"] = now
            return dict(record)

        # Create new
        record_id = _generate_ulid()
        new_record: dict[str, Any] = {
            "id": record_id,
            "deployment_id": deployment_id,
            "snapshot_date": snapshot_date.isoformat(),
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "commission": commission,
            "fees": fees,
            "positions_count": positions_count,
            "created_at": now,
            "updated_at": now,
        }
        self._store[record_id] = new_record
        self._composite_index[composite_key] = record_id
        return dict(new_record)

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
            Dict with snapshot fields, or None.
        """
        composite_key = (deployment_id, snapshot_date.isoformat())
        record_id = self._composite_index.get(composite_key)
        if record_id is None:
            return None
        return dict(self._store[record_id])

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """
        List snapshots for a deployment within a date range.

        Args:
            deployment_id: Deployment ULID.
            date_from: Inclusive start date.
            date_to: Inclusive end date.

        Returns:
            List of snapshot dicts ordered by snapshot_date ascending.
        """
        results = []
        for record in self._store.values():
            if record["deployment_id"] != deployment_id:
                continue
            snap_date = date.fromisoformat(record["snapshot_date"])
            if date_from <= snap_date <= date_to:
                results.append(dict(record))

        # Sort by snapshot_date ascending
        results.sort(key=lambda r: r["snapshot_date"])
        return results

    def delete_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> int:
        """
        Delete all snapshots for a deployment.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Number of records deleted.
        """
        to_delete = [
            rid for rid, rec in self._store.items() if rec["deployment_id"] == deployment_id
        ]
        for rid in to_delete:
            rec = self._store.pop(rid)
            composite_key = (rec["deployment_id"], rec["snapshot_date"])
            self._composite_index.pop(composite_key, None)
        return len(to_delete)

    # ------------------------------------------------------------------
    # Introspection helpers (test-only)
    # ------------------------------------------------------------------

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored snapshots."""
        return [dict(r) for r in self._store.values()]

    def count(self) -> int:
        """Return total number of stored snapshots."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all stored snapshots."""
        self._store.clear()
        self._composite_index.clear()

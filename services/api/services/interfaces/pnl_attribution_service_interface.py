"""
P&L attribution service interface (port).

Responsibilities:
- Define the abstract contract for P&L attribution and performance tracking.
- Declare methods for P&L summary, timeseries, per-symbol attribution,
  strategy comparison, and daily snapshot persistence.

Does NOT:
- Implement any business logic.
- Access databases, brokers, or external services.
- Know about specific repository implementations.

Dependencies:
- None (pure interface).
- Consumers provide concrete implementations via dependency injection.

Error conditions:
- NotFoundError: raised when referenced deployment does not exist.
- ValidationError: raised when date range is invalid.

Example:
    service: PnlAttributionServiceInterface = PnlAttributionService(
        deployment_repo=deployment_repo,
        position_repo=position_repo,
        order_fill_repo=order_fill_repo,
        order_repo=order_repo,
        pnl_snapshot_repo=pnl_snapshot_repo,
    )
    summary = service.get_pnl_summary(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class PnlAttributionServiceInterface(ABC):
    """
    Port interface for P&L attribution and performance tracking.

    Responsibilities:
    - Calculate per-deployment P&L summary with performance metrics.
    - Provide P&L timeseries data for equity curve rendering.
    - Compute per-symbol P&L attribution (which instruments contribute most).
    - Compare multiple deployments side-by-side on key metrics.
    - Persist daily P&L snapshots for historical tracking.

    Does NOT:
    - Know about HTTP, WebSocket, or any transport layer.
    - Manage broker connections or order submission.
    - Access database or storage directly (delegates to repositories).
    """

    @abstractmethod
    def get_pnl_summary(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Compute current P&L summary for a deployment.

        Calculates aggregate P&L including realized/unrealized, commissions,
        win rate, Sharpe ratio, max drawdown, and trade statistics by
        analyzing all fills and positions for the deployment.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Dict matching PnlSummary schema with all performance metrics.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        ...

    @abstractmethod
    def get_pnl_timeseries(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
        granularity: str = "daily",
    ) -> list[dict[str, Any]]:
        """
        Retrieve P&L timeseries data for a deployment over a date range.

        Returns daily (or aggregated) P&L data points suitable for equity
        curve rendering and drawdown visualization. Each point includes
        cumulative and daily P&L, drawdown percentage, and position counts.

        Args:
            deployment_id: Deployment ULID.
            date_from: Inclusive start date.
            date_to: Inclusive end date.
            granularity: Aggregation level: "daily", "weekly", or "monthly".

        Returns:
            List of dicts matching PnlTimeseriesPoint schema, ordered by
            snapshot_date ascending.

        Raises:
            NotFoundError: If the deployment does not exist.
            ValidationError: If date_from > date_to or granularity is invalid.
        """
        ...

    @abstractmethod
    def get_attribution(
        self,
        *,
        deployment_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """
        Compute per-symbol P&L attribution for a deployment.

        Breaks down the deployment's total P&L by instrument symbol,
        showing each symbol's contribution to overall performance. Useful
        for identifying best/worst performing instruments.

        Args:
            deployment_id: Deployment ULID.
            date_from: Optional start date to filter fills (inclusive).
            date_to: Optional end date to filter fills (inclusive).

        Returns:
            Dict matching PnlAttributionReport schema with per-symbol breakdowns.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        ...

    @abstractmethod
    def get_comparison(
        self,
        *,
        deployment_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """
        Compare P&L metrics across multiple deployments side-by-side.

        Produces a comparison report showing key performance metrics for
        each requested deployment, enabling strategy-vs-strategy analysis.

        Args:
            deployment_ids: List of deployment ULIDs to compare.
            date_from: Optional start date for comparison period.
            date_to: Optional end date for comparison period.

        Returns:
            Dict matching PnlComparisonReport schema with one entry per deployment.

        Raises:
            ValidationError: If deployment_ids list is empty.
        """
        ...

    @abstractmethod
    def take_snapshot(
        self,
        *,
        deployment_id: str,
        snapshot_date: date,
    ) -> dict[str, Any]:
        """
        Persist a daily P&L snapshot for a deployment.

        Calculates the current P&L state from positions and fills,
        then persists it as a snapshot record. Uses upsert semantics:
        if a snapshot already exists for this deployment + date, it is
        updated with the latest values.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date to record the snapshot for.

        Returns:
            Dict with the persisted snapshot record.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        ...

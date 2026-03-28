"""
Chart repository interface (port).

Purpose:
    Define the abstract contract for chart data access, decoupling route
    handlers from any specific storage backend (SQL cache, in-memory mock,
    MinIO parquet files, etc.).

Responsibilities:
    - Declare abstract methods for raw equity, drawdown, and trade count retrieval.
    - Enable in-memory mock substitution in unit tests via dependency injection.

Does NOT:
    - Execute SQL, file I/O, or network requests.
    - Apply LTTB downsampling (that is the route/service layer's responsibility).
    - Contain business logic or filtering.

Dependencies:
    - libs.contracts.chart: EquityCurvePoint, DrawdownPoint.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - All abstract methods raise NotFoundError when no data exists for the given run_id.

Example:
    repo: ChartRepositoryInterface = MockChartRepository()
    equity_pts = repo.find_equity_by_run_id("01HQRUN...", correlation_id="corr-1")
    trade_count = repo.find_trade_count_by_run_id("01HQRUN...", correlation_id="corr-1")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.chart import DrawdownPoint, EquityCurvePoint
from libs.contracts.errors import NotFoundError  # noqa: F401 — document raised type


class ChartRepositoryInterface(ABC):
    """
    Port interface for chart data access.

    Implementations:
    - MockChartRepository      — in-memory, for unit tests
    - SqlChartRepository       — SQLAlchemy cache-backed, for production (future)
    """

    @abstractmethod
    def find_equity_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[EquityCurvePoint]:
        """
        Return the full (un-downsampled) equity curve for a run.

        Args:
            run_id:         ULID of the run whose equity curve is requested.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of EquityCurvePoint objects, sorted ascending by timestamp.
            May be empty for runs with no equity data.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            pts = repo.find_equity_by_run_id("01HQRUN...", correlation_id="c")
            # pts[0].equity >= 0.0
        """
        ...

    @abstractmethod
    def find_drawdown_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[DrawdownPoint]:
        """
        Return the full (un-downsampled) drawdown series for a run.

        Args:
            run_id:         ULID of the run whose drawdown series is requested.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of DrawdownPoint objects, sorted ascending by timestamp.
            May be empty for runs with no drawdown data.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            pts = repo.find_drawdown_by_run_id("01HQRUN...", correlation_id="c")
            # all(p.drawdown <= 0.0 for p in pts)
        """
        ...

    @abstractmethod
    def find_trade_count_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> int:
        """
        Return the total trade count for a run (without loading all trades).

        The route layer uses this count to populate trades_truncated and
        total_trade_count in EquityChartResponse.

        Args:
            run_id:         ULID of the run.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            Non-negative integer trade count.

        Raises:
            NotFoundError: If no run with run_id exists in the chart store.

        Example:
            count = repo.find_trade_count_by_run_id("01HQRUN...", correlation_id="c")
            # count >= 0
        """
        ...

"""
In-memory mock implementation of ChartRepositoryInterface.

Purpose:
    Provide a fast, deterministic substitute for chart data access in unit tests,
    eliminating database dependencies from the test suite.

Responsibilities:
    - Store equity curves, drawdown series, and trade counts keyed by run_id.
    - Implement full ChartRepositoryInterface contract including NotFoundError.
    - Expose introspection helpers so tests can assert on stored state.

Does NOT:
    - Perform SQL, file I/O, or network operations.
    - Apply LTTB or any downsampling (that belongs to the route/service layer).
    - Cache or persist data between test runs.

Dependencies:
    - libs.contracts.chart: EquityCurvePoint, DrawdownPoint.
    - libs.contracts.errors: NotFoundError.
    - libs.contracts.interfaces.chart_repository: ChartRepositoryInterface.

Error conditions:
    - find_equity_by_run_id: raises NotFoundError when run_id not in store.
    - find_drawdown_by_run_id: raises NotFoundError when run_id not in store.
    - find_trade_count_by_run_id: raises NotFoundError when run_id not in store.

Example:
    repo = MockChartRepository()
    repo.save_equity("01HQRUN...", [EquityCurvePoint(timestamp=dt, equity=10_000.0)])
    repo.save_drawdown("01HQRUN...", [DrawdownPoint(timestamp=dt, drawdown=0.0)])
    repo.save_trade_count("01HQRUN...", 120)
    pts = repo.find_equity_by_run_id("01HQRUN...", correlation_id="c")
    assert pts[0].equity == 10_000.0
"""

from __future__ import annotations

from libs.contracts.chart import DrawdownPoint, EquityCurvePoint
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.chart_repository import ChartRepositoryInterface


class MockChartRepository(ChartRepositoryInterface):
    """
    In-memory chart repository for unit testing.

    Stores equity curves, drawdown series, and trade counts keyed by run_id.
    All find_* methods raise NotFoundError for unknown run IDs, matching the
    behaviour expected of a production SQL-backed implementation.
    """

    def __init__(self) -> None:
        self._equity: dict[str, list[EquityCurvePoint]] = {}
        self._drawdown: dict[str, list[DrawdownPoint]] = {}
        self._trade_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # ChartRepositoryInterface implementation
    # ------------------------------------------------------------------

    def find_equity_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[EquityCurvePoint]:
        """
        Return stored equity curve for run_id.

        Args:
            run_id:         Run ULID.
            correlation_id: Tracing ID (unused in mock).

        Returns:
            List of EquityCurvePoint objects.

        Raises:
            NotFoundError: If run_id has no equity data.

        Example:
            pts = repo.find_equity_by_run_id("01HQRUN...", "c")
            assert len(pts) >= 0
        """
        if run_id not in self._equity:
            raise NotFoundError(f"No equity data for run {run_id}")
        return list(self._equity[run_id])

    def find_drawdown_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> list[DrawdownPoint]:
        """
        Return stored drawdown series for run_id.

        Args:
            run_id:         Run ULID.
            correlation_id: Tracing ID (unused in mock).

        Returns:
            List of DrawdownPoint objects.

        Raises:
            NotFoundError: If run_id has no drawdown data.

        Example:
            pts = repo.find_drawdown_by_run_id("01HQRUN...", "c")
            assert all(p.drawdown <= 0.0 for p in pts)
        """
        if run_id not in self._drawdown:
            raise NotFoundError(f"No drawdown data for run {run_id}")
        return list(self._drawdown[run_id])

    def find_trade_count_by_run_id(
        self,
        run_id: str,
        correlation_id: str,
    ) -> int:
        """
        Return stored trade count for run_id.

        Args:
            run_id:         Run ULID.
            correlation_id: Tracing ID (unused in mock).

        Returns:
            Non-negative integer trade count.

        Raises:
            NotFoundError: If run_id has no trade count data.

        Example:
            count = repo.find_trade_count_by_run_id("01HQRUN...", "c")
            assert count >= 0
        """
        if run_id not in self._trade_counts:
            raise NotFoundError(f"No trade count data for run {run_id}")
        return self._trade_counts[run_id]

    # ------------------------------------------------------------------
    # Test-setup helpers (not part of ChartRepositoryInterface)
    # ------------------------------------------------------------------

    def save_equity(self, run_id: str, points: list[EquityCurvePoint]) -> None:
        """
        Store equity curve points for a run.

        Args:
            run_id: Run ULID used as the storage key.
            points: Equity curve data to store.

        Example:
            repo.save_equity("01HQRUN...", [EquityCurvePoint(timestamp=dt, equity=10_000.0)])
        """
        self._equity[run_id] = list(points)

    def save_drawdown(self, run_id: str, points: list[DrawdownPoint]) -> None:
        """
        Store drawdown series points for a run.

        Args:
            run_id: Run ULID used as the storage key.
            points: Drawdown data to store.

        Example:
            repo.save_drawdown("01HQRUN...", [DrawdownPoint(timestamp=dt, drawdown=0.0)])
        """
        self._drawdown[run_id] = list(points)

    def save_trade_count(self, run_id: str, count: int) -> None:
        """
        Store the total trade count for a run.

        Args:
            run_id: Run ULID used as the storage key.
            count:  Non-negative integer trade count.

        Example:
            repo.save_trade_count("01HQRUN...", 250)
        """
        self._trade_counts[run_id] = count

    # ------------------------------------------------------------------
    # Introspection helpers for test assertions
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """
        Remove all stored data.

        Example:
            repo.clear()
            assert repo.run_count() == 0
        """
        self._equity.clear()
        self._drawdown.clear()
        self._trade_counts.clear()

    def run_count(self) -> int:
        """
        Return the number of runs that have at least equity data stored.

        Example:
            assert repo.run_count() == 0  # after clear()
        """
        return len(self._equity)

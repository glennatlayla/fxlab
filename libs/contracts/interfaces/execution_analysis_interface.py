"""
Execution analysis service interface (port).

Responsibilities:
- Define the abstract contract for drift analysis and replay operations.
- Compute drift between expected and actual execution.
- Reconstruct order timelines from event data.
- Search events by correlation ID.

Does NOT:
- Implement analysis logic (service responsibility).
- Access data stores directly.

Dependencies:
- libs.contracts.drift: DriftReport, ReplayTimeline.
- libs.contracts.execution: OrderEvent.

Error conditions:
- NotFoundError: order_id or deployment_id not found.

Example:
    service: ExecutionAnalysisInterface = ExecutionAnalysisService(...)
    report = service.compute_drift(deployment_id="01HDEPLOY...", window="1h")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.drift import DriftReport, ReplayTimeline
from libs.contracts.execution import OrderEvent
from libs.contracts.execution_report import (
    ExecutionReportSummary,
    OrderHistoryPage,
    OrderHistoryQuery,
)


class ExecutionAnalysisInterface(ABC):
    """
    Port interface for execution analysis service.

    Implementations:
    - ExecutionAnalysisService — production implementation (M8)
    """

    @abstractmethod
    def compute_drift(
        self,
        *,
        deployment_id: str,
        window: str,
    ) -> DriftReport:
        """
        Compute execution drift for a deployment over a time window.

        Compares actual execution metrics (fill price, timing, slippage,
        fill rate) against expected values from shadow/backtest runs.

        Args:
            deployment_id: ULID of the deployment.
            window: Time window (e.g., "1h", "24h", "7d").

        Returns:
            DriftReport with all metrics and severity classification.

        Raises:
            NotFoundError: deployment not found.
        """
        ...

    @abstractmethod
    def get_order_timeline(
        self,
        *,
        order_id: str,
    ) -> ReplayTimeline:
        """
        Reconstruct the full timeline for an order.

        Gathers all events from signal through broker response,
        ordered chronologically.

        Args:
            order_id: Client order ID.

        Returns:
            ReplayTimeline with ordered events.

        Raises:
            NotFoundError: order not found.
        """
        ...

    @abstractmethod
    def search_by_correlation_id(
        self,
        *,
        correlation_id: str,
    ) -> list[OrderEvent]:
        """
        Search for all execution events matching a correlation ID.

        Searches across orders, fills, risk events, and audit events.

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            List of OrderEvent objects matching the correlation ID.
        """
        ...

    @abstractmethod
    def get_order_history(self, *, query: OrderHistoryQuery) -> OrderHistoryPage:
        """
        Retrieve paginated order history with filtering and sorting.

        Supports filtering by deployment, symbol, side, status, execution mode,
        and date range. Results are sorted by the specified column in the
        specified direction.

        Args:
            query: OrderHistoryQuery with filter, sort, and pagination params.

        Returns:
            OrderHistoryPage with ordered results and pagination metadata.

        Raises:
            ValidationError: If query parameters are invalid.

        Example:
            query = OrderHistoryQuery(
                symbol="AAPL",
                status="filled",
                execution_mode="live",
                page=1,
                page_size=50,
            )
            page = service.get_order_history(query=query)
        """
        ...

    @abstractmethod
    def get_execution_report(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> ExecutionReportSummary:
        """
        Compute aggregate execution quality metrics over a date range.

        Summarizes orders, fills, fill rates, volumes, commissions, slippage,
        latency percentiles, and breakdowns by symbol and execution mode.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            ExecutionReportSummary with all aggregated metrics.

        Raises:
            ValidationError: If date_from > date_to or parameters are invalid.
            NotFoundError: If deployment_id is specified but not found.

        Example:
            report = service.get_execution_report(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 11),
                deployment_id="01HDEPLOY123",
            )
        """
        ...

    @abstractmethod
    def export_orders_csv(self, *, query: OrderHistoryQuery) -> str:
        """
        Export filtered orders as CSV string without pagination limit.

        Returns all matching orders (no page limit) in CSV format suitable
        for download or external analysis. Includes all order and fill details.

        Args:
            query: OrderHistoryQuery with filter and sort params
                   (pagination params are ignored; all results returned).

        Returns:
            CSV string with header row and one row per order.

        Raises:
            ValidationError: If query parameters are invalid.

        Example:
            query = OrderHistoryQuery(symbol="AAPL", status="filled")
            csv_data = service.export_orders_csv(query=query)
        """
        ...

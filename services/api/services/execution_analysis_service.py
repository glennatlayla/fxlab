"""
Execution analysis service implementation.

Responsibilities:
- Compute drift between expected and actual execution metrics.
- Classify drift severity based on configurable thresholds.
- Reconstruct order timelines from registered events.
- Search events by correlation ID.
- Optionally persist execution events to durable storage.

Does NOT:
- Implement broker communication (delegates to adapter).
- Persist drift reports (caller responsibility).

Dependencies:
- DeploymentRepositoryInterface: deployment lookups.
- BrokerAdapterInterface (via adapter_registry): get order/fill data.
- ExecutionEventRepositoryInterface (optional): durable event persistence.

Error conditions:
- NotFoundError: deployment_id or order_id not found.

Example:
    # Without event persistence (suitable for testing)
    service = ExecutionAnalysisService(
        deployment_repo=deployment_repo,
        adapter_registry={"01HDEPLOY...": adapter},
    )

    # With event persistence to durable storage
    service = ExecutionAnalysisService(
        deployment_repo=deployment_repo,
        adapter_registry={"01HDEPLOY...": adapter},
        execution_event_repo=event_repo,
    )
    report = service.compute_drift(deployment_id="01HDEPLOY...", window="1h")
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal

import ulid as _ulid

from libs.contracts.drift import (
    DriftMetric,
    DriftReport,
    DriftSeverity,
    ReplayTimeline,
    ReplayTimelineEvent,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.execution import OrderEvent, OrderResponse
from libs.contracts.execution_report import (
    ExecutionReportSummary,
    FillItem,
    ModeBreakdown,
    OrderHistoryItem,
    OrderHistoryPage,
    OrderHistoryQuery,
    SymbolBreakdown,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.execution_analysis_interface import (
    ExecutionAnalysisInterface,
)
from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)
from libs.contracts.interfaces.order_fill_repository_interface import (
    OrderFillRepositoryInterface,
)
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)

logger = logging.getLogger(__name__)

# Drift severity thresholds (percentage)
_SEVERITY_THRESHOLDS: dict[DriftSeverity, Decimal] = {
    DriftSeverity.NEGLIGIBLE: Decimal("0"),
    DriftSeverity.MINOR: Decimal("1"),
    DriftSeverity.SIGNIFICANT: Decimal("5"),
    DriftSeverity.CRITICAL: Decimal("10"),
}


class ExecutionAnalysisService(ExecutionAnalysisInterface):
    """
    Production implementation of ExecutionAnalysisInterface.

    Computes drift by comparing actual fill prices against expected
    prices from shadow/backtest runs. Reconstructs order timelines
    from registered events. Optionally persists events to durable storage.

    Responsibilities:
    - Fill price drift computation with severity classification.
    - In-memory event store cache for timeline reconstruction.
    - Correlation ID search across events.
    - Optional durable event persistence (if repo provided).

    Does NOT:
    - Auto-trigger halts on drift (M7 responsibility).
    - Persist reports (caller can persist if needed).

    Example:
        # Without persistence (testing)
        service = ExecutionAnalysisService(
            deployment_repo=deployment_repo,
            adapter_registry={"01HDEPLOY...": adapter},
        )

        # With persistence to durable storage
        service = ExecutionAnalysisService(
            deployment_repo=deployment_repo,
            adapter_registry={"01HDEPLOY...": adapter},
            execution_event_repo=event_repo,
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        adapter_registry: dict[str, BrokerAdapterInterface],
        execution_event_repo: ExecutionEventRepositoryInterface | None = None,
        order_repo: OrderRepositoryInterface | None = None,
        order_fill_repo: OrderFillRepositoryInterface | None = None,
    ) -> None:
        """
        Initialise the execution analysis service.

        Args:
            deployment_repo: Repository for deployment lookups.
            adapter_registry: Map of deployment_id → BrokerAdapterInterface.
            execution_event_repo: Optional repository for durable event persistence.
                If provided, events are persisted to storage. If None, in-memory
                store is used (suitable for testing).
            order_repo: Optional repository for order history and filtering.
                If provided, enables get_order_history, get_execution_report,
                and export_orders_csv methods. If None, these methods raise NotImplementedError.
            order_fill_repo: Optional repository for order fill retrieval.
                If provided, fills are fetched and attached to OrderHistoryItem
                objects. If None, fills default to empty lists (backward compat).
        """
        self._deployment_repo = deployment_repo
        self._adapter_registry = adapter_registry
        self._execution_event_repo = execution_event_repo
        self._order_repo = order_repo
        self._order_fill_repo = order_fill_repo
        # Expected prices: deployment_id → {client_order_id → expected_price}
        self._expected_prices: dict[str, dict[str, Decimal]] = {}
        # Event store: order_id → [OrderEvent]
        self._events: dict[str, list[OrderEvent]] = {}
        # All events for correlation search
        self._all_events: list[OrderEvent] = []
        # Locks for thread safety
        self._registry_lock = threading.Lock()
        self._state_lock = threading.Lock()

    def _fetch_fills_for_order(self, order_id: str) -> list[FillItem]:
        """
        Fetch fills for a single order from the order fill repository.

        Converts raw fill dicts (from OrderFillRepositoryInterface.list_by_order)
        into validated FillItem Pydantic models. If no order_fill_repo is
        configured or if the lookup fails, returns an empty list so that
        order construction is never blocked by fill retrieval errors.

        Args:
            order_id: The ULID of the order whose fills to retrieve.

        Returns:
            List of FillItem models for the given order, ordered chronologically.
            Empty list if no repo is configured or on any error.
        """
        if self._order_fill_repo is None:
            return []
        try:
            fill_dicts = self._order_fill_repo.list_by_order(order_id=order_id)
            fills: list[FillItem] = []
            for fd in fill_dicts:
                try:
                    fills.append(
                        FillItem(
                            fill_id=fd["fill_id"],
                            price=Decimal(fd["price"]),
                            quantity=Decimal(fd["quantity"]),
                            commission=Decimal(fd.get("commission", "0")),
                            filled_at=self._parse_datetime(fd.get("filled_at"))
                            or datetime.now(tz=None),
                            broker_execution_id=fd.get("broker_execution_id"),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    # Skip malformed fill records — log and continue
                    logger.warning(
                        "fill.conversion_failed order_id=%s fill_data=%s",
                        order_id,
                        str(fd)[:200],
                        exc_info=True,
                    )
            return fills
        except Exception:
            logger.warning(
                "fills.fetch_failed order_id=%s",
                order_id,
                exc_info=True,
            )
            return []

    def set_expected_prices(
        self,
        *,
        deployment_id: str,
        expected: dict[str, Decimal],
    ) -> None:
        """
        Set expected prices for drift comparison.

        Args:
            deployment_id: ULID of the deployment.
            expected: Map of client_order_id → expected fill price.
        """
        with self._state_lock:
            self._expected_prices[deployment_id] = expected

    def register_event(self, event: OrderEvent) -> None:
        """
        Register an execution event for timeline reconstruction.

        If an execution_event_repo was provided, persists the event durably.
        Always maintains an in-memory cache for fast timeline lookups.

        Args:
            event: OrderEvent to store.
        """
        # Persist to durable storage if repo available
        if self._execution_event_repo is not None:
            timestamp_str = (
                event.timestamp.isoformat()
                if hasattr(event.timestamp, "isoformat")
                else str(event.timestamp)
            )
            self._execution_event_repo.save(
                order_id=event.order_id,
                event_type=event.event_type,
                timestamp=timestamp_str,
                details=event.details,
                correlation_id=event.correlation_id,
            )

        # Maintain in-memory cache for fast lookups
        with self._state_lock:
            if event.order_id not in self._events:
                self._events[event.order_id] = []
            self._events[event.order_id].append(event)
            self._all_events.append(event)

    def compute_drift(
        self,
        *,
        deployment_id: str,
        window: str,
    ) -> DriftReport:
        """
        Compute execution drift for a deployment.

        Compares actual fill prices against expected prices and
        classifies the severity of each drift metric.

        Args:
            deployment_id: ULID of the deployment.
            window: Time window (e.g., "1h", "24h", "7d").

        Returns:
            DriftReport with all metrics and severity classification.

        Raises:
            NotFoundError: deployment not found.
        """
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        # Take snapshot of adapter and expected prices under locks
        with self._registry_lock:
            adapter = self._adapter_registry.get(deployment_id)
        if adapter is None:
            # No adapter — return empty report
            return DriftReport(
                report_id=str(_ulid.ULID()),
                deployment_id=deployment_id,
                window=window,
            )

        # Get all broker orders
        broker_orders = self._get_all_broker_orders(adapter)
        with self._state_lock:
            expected = dict(self._expected_prices.get(deployment_id, {}))

        metrics: list[DriftMetric] = []

        for order in broker_orders:
            if order.average_fill_price is None:
                continue
            expected_price = expected.get(order.client_order_id)
            if expected_price is None:
                continue

            actual_price = order.average_fill_price
            if expected_price != Decimal("0"):
                drift_pct = abs((actual_price - expected_price) / expected_price * Decimal("100"))
            else:
                drift_pct = Decimal("0")

            severity = self._classify_severity(drift_pct)

            metrics.append(
                DriftMetric(
                    metric_name="fill_price",
                    expected_value=expected_price,
                    actual_value=actual_price,
                    drift_pct=drift_pct,
                    severity=severity,
                    symbol=order.symbol,
                    order_id=order.client_order_id,
                    details=f"Fill price drift: expected {expected_price}, actual {actual_price}",
                )
            )

        # Compute severity counts
        critical_count = sum(1 for m in metrics if m.severity == DriftSeverity.CRITICAL)
        significant_count = sum(1 for m in metrics if m.severity == DriftSeverity.SIGNIFICANT)
        minor_count = sum(1 for m in metrics if m.severity == DriftSeverity.MINOR)
        negligible_count = sum(1 for m in metrics if m.severity == DriftSeverity.NEGLIGIBLE)

        max_severity = DriftSeverity.NEGLIGIBLE
        if critical_count > 0:
            max_severity = DriftSeverity.CRITICAL
        elif significant_count > 0:
            max_severity = DriftSeverity.SIGNIFICANT
        elif minor_count > 0:
            max_severity = DriftSeverity.MINOR

        report = DriftReport(
            report_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            window=window,
            metrics=metrics,
            max_severity=max_severity,
            total_metrics=len(metrics),
            critical_count=critical_count,
            significant_count=significant_count,
            minor_count=minor_count,
            negligible_count=negligible_count,
        )

        logger.info(
            "Drift analysis completed",
            extra={
                "operation": "drift_analysis_completed",
                "component": "ExecutionAnalysisService",
                "deployment_id": deployment_id,
                "window": window,
                "total_metrics": len(metrics),
                "max_severity": max_severity.value,
            },
        )

        return report

    def get_order_timeline(
        self,
        *,
        order_id: str,
    ) -> ReplayTimeline:
        """
        Reconstruct the full timeline for an order.

        Args:
            order_id: Client order ID.

        Returns:
            ReplayTimeline with ordered events.

        Raises:
            NotFoundError: order not found in event store.
        """
        # Take snapshot of events under lock
        with self._state_lock:
            events = list(self._events.get(order_id, []))
        if events is None or len(events) == 0:
            raise NotFoundError(f"No events found for order {order_id}")

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Convert to timeline events
        timeline_events = [
            ReplayTimelineEvent(
                event_type=e.event_type,
                timestamp=e.timestamp,
                details=e.details,
                source=e.details.get("source", ""),
            )
            for e in sorted_events
        ]

        # Get deployment and symbol from first event
        first_event = sorted_events[0]
        correlation_id = first_event.correlation_id

        # Try to find symbol from adapter (take snapshot of registry under lock)
        symbol = "unknown"
        with self._registry_lock:
            registry_snapshot = dict(self._adapter_registry)
        for _dep_id, adapter in registry_snapshot.items():
            try:
                if hasattr(adapter, "get_all_orders"):
                    for o in adapter.get_all_orders():  # type: ignore[attr-defined]
                        if o.client_order_id == order_id:
                            symbol = o.symbol
                            break
            except Exception:
                pass

        return ReplayTimeline(
            order_id=order_id,
            deployment_id=first_event.details.get("deployment_id", ""),
            symbol=symbol,
            correlation_id=correlation_id,
            events=timeline_events,
        )

    def search_by_correlation_id(
        self,
        *,
        correlation_id: str,
    ) -> list[OrderEvent]:
        """
        Search for all events matching a correlation ID.

        If an execution_event_repo was provided, queries from durable storage.
        Otherwise, searches the in-memory cache.

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            List of matching OrderEvent objects.
        """
        # Query from durable storage if repo available
        if self._execution_event_repo is not None:
            results = self._execution_event_repo.search_by_correlation_id(
                correlation_id=correlation_id
            )
            # Convert dicts back to OrderEvent objects
            return [
                OrderEvent(
                    event_id=r.get("event_id", ""),
                    order_id=r.get("order_id", ""),
                    event_type=r.get("event_type", ""),
                    timestamp=r.get("timestamp"),
                    details=r.get("details", {}),
                    correlation_id=r.get("correlation_id", ""),
                )
                for r in results
            ]

        # Fallback to in-memory cache
        with self._state_lock:
            all_events_snapshot = list(self._all_events)
        return [e for e in all_events_snapshot if e.correlation_id == correlation_id]

    def get_order_history(
        self,
        *,
        query: OrderHistoryQuery,
    ) -> OrderHistoryPage:
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
            RuntimeError: if order_repo was not provided to constructor.

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
        if self._order_repo is None:
            raise RuntimeError("OrderRepository not configured for order history queries")

        # Query orders from repo. Since the repo only supports list_by_deployment,
        # we require a deployment_id to be specified, or we fetch from all deployments
        # in the adapter registry
        all_order_dicts: list[dict] = []

        if query.deployment_id:
            # Fetch from specific deployment
            all_order_dicts = self._order_repo.list_by_deployment(deployment_id=query.deployment_id)
        else:
            # Fetch from all deployments in the adapter registry
            with self._registry_lock:
                deployment_ids = list(self._adapter_registry.keys())

            for dep_id in deployment_ids:
                try:
                    orders = self._order_repo.list_by_deployment(deployment_id=dep_id)
                    all_order_dicts.extend(orders)
                except Exception:
                    # Skip deployments that fail
                    pass

        # Convert dicts to OrderHistoryItem objects
        results_items: list[OrderHistoryItem] = []
        for order_dict in all_order_dicts:
            try:
                item = OrderHistoryItem(
                    order_id=order_dict.get("order_id", ""),
                    client_order_id=order_dict.get("client_order_id", ""),
                    broker_order_id=order_dict.get("broker_order_id"),
                    deployment_id=order_dict.get("deployment_id", ""),
                    strategy_id=order_dict.get("strategy_id", ""),
                    symbol=order_dict.get("symbol", ""),
                    side=order_dict.get("side", ""),
                    order_type=order_dict.get("order_type", ""),
                    quantity=Decimal(order_dict.get("quantity", "0")),
                    filled_quantity=Decimal(order_dict.get("filled_quantity", "0")),
                    average_fill_price=(
                        Decimal(order_dict.get("average_fill_price"))
                        if order_dict.get("average_fill_price")
                        else None
                    ),
                    limit_price=(
                        Decimal(order_dict.get("limit_price"))
                        if order_dict.get("limit_price")
                        else None
                    ),
                    stop_price=(
                        Decimal(order_dict.get("stop_price"))
                        if order_dict.get("stop_price")
                        else None
                    ),
                    status=order_dict.get("status", ""),
                    time_in_force=order_dict.get("time_in_force", ""),
                    execution_mode=order_dict.get("execution_mode", ""),
                    correlation_id=order_dict.get("correlation_id", ""),
                    submitted_at=self._parse_datetime(order_dict.get("submitted_at")),
                    filled_at=self._parse_datetime(order_dict.get("filled_at")),
                    cancelled_at=self._parse_datetime(order_dict.get("cancelled_at")),
                    rejected_reason=order_dict.get("rejected_reason"),
                    created_at=self._parse_datetime(order_dict.get("created_at")),
                    fills=self._fetch_fills_for_order(
                        order_dict.get("id", order_dict.get("order_id", ""))
                    ),
                )
                results_items.append(item)
            except Exception:
                # Skip orders that fail conversion
                pass

        # Apply filters
        results = results_items
        if query.symbol:
            results = [o for o in results if o.symbol == query.symbol]
        if query.side:
            results = [o for o in results if o.side == query.side]
        if query.status:
            results = [o for o in results if o.status == query.status]
        if query.execution_mode:
            results = [o for o in results if o.execution_mode == query.execution_mode]
        if query.date_from and query.date_to:
            results = [
                o
                for o in results
                if (o.submitted_at or o.created_at) >= query.date_from
                and (o.submitted_at or o.created_at) <= query.date_to
            ]
        elif query.date_from:
            results = [o for o in results if (o.submitted_at or o.created_at) >= query.date_from]
        elif query.date_to:
            results = [o for o in results if (o.submitted_at or o.created_at) <= query.date_to]

        # Apply sorting
        sort_reverse = query.sort_dir.lower() == "desc"
        try:
            results.sort(
                key=lambda o: getattr(o, query.sort_by) or "",
                reverse=sort_reverse,
            )
        except AttributeError:
            # Default to submitted_at if invalid sort column
            results.sort(
                key=lambda o: o.submitted_at or o.created_at,
                reverse=sort_reverse,
            )

        # Apply pagination
        total = len(results)
        start_idx = (query.page - 1) * query.page_size
        end_idx = start_idx + query.page_size
        page_items = results[start_idx:end_idx]

        total_pages = (total + query.page_size - 1) // query.page_size
        if total == 0:
            total_pages = 0

        logger.debug(
            "Order history retrieved",
            extra={
                "operation": "get_order_history",
                "component": "ExecutionAnalysisService",
                "total": total,
                "page": query.page,
                "page_size": query.page_size,
                "total_pages": total_pages,
            },
        )

        return OrderHistoryPage(
            items=page_items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=total_pages,
        )

    def get_execution_report(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> ExecutionReportSummary:
        """
        Compute aggregate execution quality metrics over a date range.

        Summarizes orders, fills, fill rates, volumes, commissions, and
        breakdowns by symbol and execution mode.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            ExecutionReportSummary with all aggregated metrics.

        Raises:
            RuntimeError: if order_repo was not provided to constructor.

        Example:
            report = service.get_execution_report(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 11),
                deployment_id="01HDEPLOY123",
            )
        """
        if self._order_repo is None:
            raise RuntimeError("OrderRepository not configured for execution reports")

        # Fetch all orders and filter by date and deployment
        all_order_dicts: list[dict] = []

        if deployment_id:
            # Fetch from specific deployment
            all_order_dicts = self._order_repo.list_by_deployment(deployment_id=deployment_id)
        else:
            # Fetch from all deployments in the adapter registry
            with self._registry_lock:
                deployment_ids = list(self._adapter_registry.keys())

            for dep_id in deployment_ids:
                try:
                    orders_for_deployment = self._order_repo.list_by_deployment(
                        deployment_id=dep_id
                    )
                    all_order_dicts.extend(orders_for_deployment)
                except Exception:
                    # Skip deployments that fail
                    pass

        # Convert dicts to OrderHistoryItem objects and filter by date range
        orders: list[OrderHistoryItem] = []
        for order_dict in all_order_dicts:
            try:
                submitted_at = self._parse_datetime(order_dict.get("submitted_at"))
                created_at = self._parse_datetime(order_dict.get("created_at"))

                # Check date range
                order_date = submitted_at or created_at
                if order_date and date_from <= order_date <= date_to:
                    item = OrderHistoryItem(
                        order_id=order_dict.get("order_id", ""),
                        client_order_id=order_dict.get("client_order_id", ""),
                        broker_order_id=order_dict.get("broker_order_id"),
                        deployment_id=order_dict.get("deployment_id", ""),
                        strategy_id=order_dict.get("strategy_id", ""),
                        symbol=order_dict.get("symbol", ""),
                        side=order_dict.get("side", ""),
                        order_type=order_dict.get("order_type", ""),
                        quantity=Decimal(order_dict.get("quantity", "0")),
                        filled_quantity=Decimal(order_dict.get("filled_quantity", "0")),
                        average_fill_price=(
                            Decimal(order_dict.get("average_fill_price"))
                            if order_dict.get("average_fill_price")
                            else None
                        ),
                        limit_price=(
                            Decimal(order_dict.get("limit_price"))
                            if order_dict.get("limit_price")
                            else None
                        ),
                        stop_price=(
                            Decimal(order_dict.get("stop_price"))
                            if order_dict.get("stop_price")
                            else None
                        ),
                        status=order_dict.get("status", ""),
                        time_in_force=order_dict.get("time_in_force", ""),
                        execution_mode=order_dict.get("execution_mode", ""),
                        correlation_id=order_dict.get("correlation_id", ""),
                        submitted_at=submitted_at,
                        filled_at=self._parse_datetime(order_dict.get("filled_at")),
                        cancelled_at=self._parse_datetime(order_dict.get("cancelled_at")),
                        rejected_reason=order_dict.get("rejected_reason"),
                        created_at=created_at,
                        fills=self._fetch_fills_for_order(
                            order_dict.get("id", order_dict.get("order_id", ""))
                        ),
                    )
                    orders.append(item)
            except Exception:
                # Skip orders that fail conversion
                pass

        if not orders:
            return ExecutionReportSummary(
                date_from=date_from,
                date_to=date_to,
                total_orders=0,
                filled_orders=0,
                cancelled_orders=0,
                rejected_orders=0,
                partial_fills=0,
                fill_rate=Decimal("0"),
                total_volume=Decimal("0"),
                total_commission=Decimal("0"),
                symbols_traded=[],
                by_symbol=[],
                by_execution_mode=[],
            )

        # Aggregate metrics
        total_orders = len(orders)
        filled_orders = len([o for o in orders if o.status == "filled"])
        cancelled_orders = len([o for o in orders if o.status == "cancelled"])
        rejected_orders = len([o for o in orders if o.status == "rejected"])
        partial_fills = len([o for o in orders if o.status == "partial_fill"])

        fill_rate = (
            (Decimal(filled_orders) / Decimal(total_orders) * Decimal("100"))
            if total_orders > 0
            else Decimal("0")
        )

        total_volume = sum((o.filled_quantity or Decimal("0") for o in orders), Decimal("0"))
        total_commission = sum(
            (sum((f.commission for f in o.fills), Decimal("0")) for o in orders),
            Decimal("0"),
        )

        # Unique symbols
        symbols_traded = sorted({o.symbol for o in orders})

        # By symbol breakdown
        by_symbol: list[SymbolBreakdown] = []
        for symbol in symbols_traded:
            symbol_orders = [o for o in orders if o.symbol == symbol]
            symbol_filled = len([o for o in symbol_orders if o.status == "filled"])
            symbol_volume = sum(
                (o.filled_quantity or Decimal("0") for o in symbol_orders),
                Decimal("0"),
            )
            symbol_fill_price: Decimal | None = (
                Decimal(
                    sum(
                        (o.average_fill_price or Decimal("0")) * (o.filled_quantity or Decimal("0"))
                        for o in symbol_orders
                        if o.average_fill_price and o.filled_quantity
                    )
                )
                / symbol_volume
                if symbol_volume > 0
                else None
            )

            by_symbol.append(
                SymbolBreakdown(
                    symbol=symbol,
                    total_orders=len(symbol_orders),
                    filled_orders=symbol_filled,
                    fill_rate=(
                        (Decimal(symbol_filled) / Decimal(len(symbol_orders)) * Decimal("100"))
                        if symbol_orders
                        else Decimal("0")
                    ),
                    total_volume=symbol_volume,
                    avg_fill_price=symbol_fill_price,
                )
            )

        # By execution mode breakdown
        by_execution_mode: list[ModeBreakdown] = []
        modes = sorted({o.execution_mode for o in orders})
        for mode in modes:
            mode_orders = [o for o in orders if o.execution_mode == mode]
            mode_filled = len([o for o in mode_orders if o.status == "filled"])
            mode_volume = sum(
                (o.filled_quantity or Decimal("0") for o in mode_orders),
                Decimal("0"),
            )

            by_execution_mode.append(
                ModeBreakdown(
                    execution_mode=mode,
                    total_orders=len(mode_orders),
                    filled_orders=mode_filled,
                    fill_rate=(
                        (Decimal(mode_filled) / Decimal(len(mode_orders)) * Decimal("100"))
                        if mode_orders
                        else Decimal("0")
                    ),
                    total_volume=mode_volume,
                )
            )

        logger.info(
            "Execution report computed",
            extra={
                "operation": "get_execution_report",
                "component": "ExecutionAnalysisService",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "total_orders": total_orders,
                "filled_orders": filled_orders,
                "fill_rate": str(fill_rate),
                "deployment_id": deployment_id,
            },
        )

        return ExecutionReportSummary(
            date_from=date_from,
            date_to=date_to,
            total_orders=total_orders,
            filled_orders=filled_orders,
            cancelled_orders=cancelled_orders,
            rejected_orders=rejected_orders,
            partial_fills=partial_fills,
            fill_rate=fill_rate,
            total_volume=total_volume,
            total_commission=total_commission,
            symbols_traded=symbols_traded,
            by_symbol=by_symbol,
            by_execution_mode=by_execution_mode,
        )

    def export_orders_csv(
        self,
        *,
        query: OrderHistoryQuery,
    ) -> str:
        """
        Export filtered orders as CSV string without pagination limit.

        Returns all matching orders (ignoring pagination) in CSV format
        suitable for download or external analysis.

        Args:
            query: OrderHistoryQuery with filter and sort params
                   (pagination params are ignored; all results returned).

        Returns:
            CSV string with header row and one row per order.

        Raises:
            RuntimeError: if order_repo was not provided to constructor.

        Example:
            query = OrderHistoryQuery(symbol="AAPL", status="filled")
            csv_data = service.export_orders_csv(query=query)
        """
        if self._order_repo is None:
            raise RuntimeError("OrderRepository not configured for order export")

        # Get all matching orders (ignore pagination)
        all_results_query = OrderHistoryQuery(
            deployment_id=query.deployment_id,
            symbol=query.symbol,
            side=query.side,
            status=query.status,
            execution_mode=query.execution_mode,
            date_from=query.date_from,
            date_to=query.date_to,
            sort_by=query.sort_by,
            sort_dir=query.sort_dir,
            page=1,
            page_size=500,  # High limit to get all
        )
        page = self.get_order_history(query=all_results_query)
        orders = page.items

        if not orders:
            # Return header only
            return (
                "order_id,client_order_id,symbol,side,order_type,quantity,"
                "filled_quantity,average_fill_price,status,execution_mode,"
                "submitted_at,filled_at,created_at\n"
            )

        # Build CSV content
        lines = [
            "order_id,client_order_id,symbol,side,order_type,quantity,"
            "filled_quantity,average_fill_price,status,execution_mode,"
            "submitted_at,filled_at,created_at"
        ]

        for order in orders:
            submitted_at = order.submitted_at.isoformat() if order.submitted_at else ""
            filled_at = order.filled_at.isoformat() if order.filled_at else ""
            created_at = order.created_at.isoformat() if order.created_at else ""

            line = (
                f"{order.order_id},{order.client_order_id},{order.symbol},"
                f"{order.side},{order.order_type},{order.quantity},"
                f"{order.filled_quantity},{order.average_fill_price or ''},"
                f"{order.status},{order.execution_mode},"
                f"{submitted_at},{filled_at},{created_at}"
            )
            lines.append(line)

        logger.info(
            "Orders exported to CSV",
            extra={
                "operation": "export_orders_csv",
                "component": "ExecutionAnalysisService",
                "order_count": len(orders),
                "symbol": query.symbol,
                "status": query.status,
            },
        )

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime | None:
        """
        Parse a datetime value from string or datetime object.

        Args:
            value: ISO 8601 string, datetime object, or None.

        Returns:
            datetime object in UTC, or None if value is None.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                # Try parsing ISO 8601 format
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _get_all_broker_orders(
        adapter: BrokerAdapterInterface,
    ) -> list[OrderResponse]:
        """Get all broker orders for analysis."""
        if hasattr(adapter, "get_all_order_states"):
            return adapter.get_all_order_states()  # type: ignore[attr-defined]
        if hasattr(adapter, "get_all_orders"):
            return adapter.get_all_orders()  # type: ignore[attr-defined]
        return adapter.list_open_orders()

    @staticmethod
    def _classify_severity(drift_pct: Decimal) -> DriftSeverity:
        """
        Classify drift percentage into severity level.

        Args:
            drift_pct: Absolute drift as a percentage.

        Returns:
            DriftSeverity based on configured thresholds.
        """
        if drift_pct >= _SEVERITY_THRESHOLDS[DriftSeverity.CRITICAL]:
            return DriftSeverity.CRITICAL
        if drift_pct >= _SEVERITY_THRESHOLDS[DriftSeverity.SIGNIFICANT]:
            return DriftSeverity.SIGNIFICANT
        if drift_pct >= _SEVERITY_THRESHOLDS[DriftSeverity.MINOR]:
            return DriftSeverity.MINOR
        return DriftSeverity.NEGLIGIBLE

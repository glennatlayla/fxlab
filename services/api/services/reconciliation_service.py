"""
Reconciliation service implementation.

Responsibilities:
- Compare internal order/position state against broker adapter state.
- Detect all 7 DiscrepancyType variants.
- Auto-resolve safe discrepancies (e.g., status lag where broker is ahead).
- Flag unsafe discrepancies for operator review.
- Persist ReconciliationReport via repository.
- Provide report retrieval (by ID, by deployment).

Does NOT:
- Implement broker communication (delegates to adapter).
- Enforce kill switches or halt orders (M7 responsibility).
- Perform automatic remediation beyond status sync.

Dependencies:
- DeploymentRepositoryInterface: look up deployment existence.
- ReconciliationRepositoryInterface: persist and query reports.
- BrokerAdapterInterface (via adapter_registry): get broker state.
- OrderRepositoryInterface (optional): query internal order state.
- PositionRepositoryInterface (optional): query internal position state.

Error conditions:
- NotFoundError: deployment_id or report_id not found.
- NotFoundError: no adapter registered for deployment_id.

Example:
    service = ReconciliationService(
        deployment_repo=deployment_repo,
        reconciliation_repo=recon_repo,
        adapter_registry={"01HDEPLOY...": adapter},
    )
    report = service.run_reconciliation(
        deployment_id="01HDEPLOY...",
        trigger=ReconciliationTrigger.STARTUP,
    )
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal

import ulid as _ulid

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import OrderResponse, OrderStatus, PositionSnapshot
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)
from libs.contracts.interfaces.position_repository_interface import (
    PositionRepositoryInterface,
)
from libs.contracts.interfaces.reconciliation_repository_interface import (
    ReconciliationRepositoryInterface,
)
from libs.contracts.interfaces.reconciliation_service_interface import (
    ReconciliationServiceInterface,
)
from libs.contracts.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationReport,
    ReconciliationTrigger,
)

logger = logging.getLogger(__name__)

# Status transitions where broker being ahead is a safe lag.
# If broker is in one of these "ahead" states while internal is in
# a "behind" state, the discrepancy can be auto-resolved.
_SAFE_STATUS_LAG: dict[str, set[str]] = {
    # Internal status → set of broker statuses that are safe to auto-resolve
    "submitted": {"filled", "partial_fill", "cancelled"},
    "pending": {"submitted", "filled", "partial_fill", "cancelled"},
    "partial_fill": {"filled"},
}


class ReconciliationService(ReconciliationServiceInterface):
    """
    Production implementation of ReconciliationServiceInterface.

    Compares internal state against broker adapter state to detect
    discrepancies in orders and positions.

    Responsibilities:
    - Order reconciliation: detect missing, extra, status/quantity/price
      mismatches.
    - Position reconciliation: detect missing, extra positions.
    - Auto-resolve safe status lags (broker ahead of internal).
    - Generate and persist ReconciliationReport.

    Does NOT:
    - Modify orders or positions (read-only comparison).
    - Halt trading on discrepancies (M7 responsibility).

    Example:
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY...": adapter},
        )
        report = service.run_reconciliation(
            deployment_id="01HDEPLOY...",
            trigger=ReconciliationTrigger.STARTUP,
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        reconciliation_repo: ReconciliationRepositoryInterface,
        adapter_registry: dict[str, BrokerAdapterInterface],
        order_repo: OrderRepositoryInterface | None = None,
        position_repo: PositionRepositoryInterface | None = None,
        internal_order_states: dict[str, dict[str, OrderStatus]] | None = None,
        internal_order_quantities: dict[str, dict[str, Decimal]] | None = None,
        internal_order_prices: dict[str, dict[str, Decimal]] | None = None,
        internal_positions: dict[str, dict[str, Decimal]] | None = None,
    ) -> None:
        """
        Initialise the reconciliation service.

        Args:
            deployment_repo: Repository for deployment lookups.
            reconciliation_repo: Repository for report persistence.
            adapter_registry: Map of deployment_id → BrokerAdapterInterface.
            order_repo: Optional OrderRepositoryInterface for persistent order queries.
                When provided, supersedes internal_order_states/quantities/prices.
            position_repo: Optional PositionRepositoryInterface for persistent
                position queries. When provided, supersedes internal_positions.
            internal_order_states: (DEPRECATED) Optional internal order status overrides
                (deployment_id → {client_order_id → OrderStatus}).
                Use order_repo instead; kept for backward compatibility with tests.
            internal_order_quantities: (DEPRECATED) Optional internal quantity overrides
                (deployment_id → {client_order_id → Decimal}).
                Use order_repo instead; kept for backward compatibility with tests.
            internal_order_prices: (DEPRECATED) Optional internal price overrides
                (deployment_id → {client_order_id → Decimal}).
                Use order_repo instead; kept for backward compatibility with tests.
            internal_positions: (DEPRECATED) Optional internal position overrides
                (deployment_id → {symbol → quantity}).
                Use position_repo instead; kept for backward compatibility with tests.
        """
        self._deployment_repo = deployment_repo
        self._reconciliation_repo = reconciliation_repo
        self._adapter_registry = adapter_registry
        self._registry_lock = threading.Lock()
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._internal_order_states = internal_order_states or {}
        self._internal_order_quantities = internal_order_quantities or {}
        self._internal_order_prices = internal_order_prices or {}
        self._internal_positions = internal_positions or {}

    def run_reconciliation(
        self,
        *,
        deployment_id: str,
        trigger: ReconciliationTrigger,
    ) -> ReconciliationReport:
        """
        Run reconciliation for a deployment.

        Compares internal order/position state against broker adapter
        state and generates a report of all discrepancies found.

        Args:
            deployment_id: ULID of the deployment.
            trigger: What triggered this reconciliation run.

        Returns:
            ReconciliationReport with all discrepancies.

        Raises:
            NotFoundError: deployment not found or no adapter registered.
        """
        logger.info(
            "Reconciliation run started",
            extra={
                "operation": "reconciliation_run_started",
                "component": "ReconciliationService",
                "deployment_id": deployment_id,
                "trigger": trigger.value,
            },
        )

        # Validate deployment exists
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        # Get adapter (thread-safe read from registry)
        with self._registry_lock:
            adapter = self._adapter_registry.get(deployment_id)
        if adapter is None:
            raise NotFoundError(f"No adapter registered for deployment {deployment_id}")

        discrepancies: list[Discrepancy] = []

        # --- Order reconciliation ---
        broker_orders = self._get_all_broker_orders(adapter)
        broker_order_map: dict[str, OrderResponse] = {o.client_order_id: o for o in broker_orders}

        # Build internal order state: from repo if available, otherwise from injected dict
        internal_states = self._internal_order_states.get(deployment_id)
        if self._order_repo is not None:
            try:
                orders = self._order_repo.list_by_deployment(deployment_id=deployment_id)
                internal_states = {
                    order["client_order_id"]: OrderStatus(order["status"]) for order in orders
                }
            except Exception as e:
                logger.warning(
                    "Failed to query order repository; falling back to injected state",
                    extra={
                        "operation": "order_repo_query_failed",
                        "component": "ReconciliationService",
                        "deployment_id": deployment_id,
                        "error": str(e),
                    },
                )

        orders_checked = len(broker_order_map)

        if internal_states is not None:
            # Explicit internal state provided — compare against broker
            internal_order_ids = set(internal_states.keys())
            broker_order_ids = set(broker_order_map.keys())

            # Missing orders: in internal but not at broker
            for oid in internal_order_ids - broker_order_ids:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=DiscrepancyType.MISSING_ORDER,
                        entity_type="order",
                        entity_id=oid,
                    )
                )

            # Extra orders: at broker but not in internal
            for oid in broker_order_ids - internal_order_ids:
                broker_order = broker_order_map[oid]
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=DiscrepancyType.EXTRA_ORDER,
                        entity_type="order",
                        entity_id=oid,
                        symbol=broker_order.symbol,
                    )
                )

            # Status mismatches for orders present in both
            for oid in internal_order_ids & broker_order_ids:
                internal_status = internal_states[oid]
                broker_status = broker_order_map[oid].status
                if internal_status.value != broker_status.value:
                    # Check if this is a safe status lag
                    auto_resolved = self._is_safe_status_lag(
                        internal_status.value, broker_status.value
                    )
                    discrepancies.append(
                        Discrepancy(
                            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
                            entity_type="order",
                            entity_id=oid,
                            symbol=broker_order_map[oid].symbol,
                            field="status",
                            internal_value=internal_status.value,
                            broker_value=broker_status.value,
                            auto_resolved=auto_resolved,
                            resolution=(
                                "Safe status lag: broker is ahead of internal"
                                if auto_resolved
                                else None
                            ),
                        )
                    )

            orders_checked = max(len(internal_order_ids), len(broker_order_ids))

        # Quantity mismatches
        internal_quantities = self._internal_order_quantities.get(deployment_id, {})
        if self._order_repo is not None and not internal_quantities:
            # Build quantities from repo if repo is available and no injected dict
            try:
                orders = self._order_repo.list_by_deployment(deployment_id=deployment_id)
                internal_quantities = {
                    order["client_order_id"]: Decimal(order["quantity"])
                    for order in orders
                    if order.get("quantity")
                }
            except Exception as e:
                logger.warning(
                    "Failed to query order quantities from repository",
                    extra={
                        "operation": "order_qty_repo_query_failed",
                        "component": "ReconciliationService",
                        "deployment_id": deployment_id,
                        "error": str(e),
                    },
                )

        for oid, expected_qty in internal_quantities.items():
            if oid in broker_order_map:
                broker_qty = broker_order_map[oid].quantity
                if expected_qty != broker_qty:
                    discrepancies.append(
                        Discrepancy(
                            discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
                            entity_type="order",
                            entity_id=oid,
                            symbol=broker_order_map[oid].symbol,
                            field="quantity",
                            internal_value=str(expected_qty),
                            broker_value=str(broker_qty),
                        )
                    )

        # Price mismatches
        internal_prices = self._internal_order_prices.get(deployment_id, {})
        if self._order_repo is not None and not internal_prices:
            # Build prices from repo if repo is available and no injected dict
            try:
                orders = self._order_repo.list_by_deployment(deployment_id=deployment_id)
                internal_prices = {
                    order["client_order_id"]: Decimal(order["average_fill_price"])
                    for order in orders
                    if order.get("average_fill_price") is not None
                }
            except Exception as e:
                logger.warning(
                    "Failed to query order prices from repository",
                    extra={
                        "operation": "order_price_repo_query_failed",
                        "component": "ReconciliationService",
                        "deployment_id": deployment_id,
                        "error": str(e),
                    },
                )

        for oid, expected_price in internal_prices.items():
            if oid in broker_order_map:
                broker_order = broker_order_map[oid]
                broker_price = broker_order.average_fill_price
                if broker_price is not None and expected_price != broker_price:
                    discrepancies.append(
                        Discrepancy(
                            discrepancy_type=DiscrepancyType.PRICE_MISMATCH,
                            entity_type="order",
                            entity_id=oid,
                            symbol=broker_order.symbol,
                            field="average_fill_price",
                            internal_value=str(expected_price),
                            broker_value=str(broker_price),
                        )
                    )

        # --- Position reconciliation ---
        broker_positions = adapter.get_positions()
        broker_pos_map: dict[str, PositionSnapshot] = {p.symbol: p for p in broker_positions}

        # Build internal positions: from repo if available, otherwise from injected dict
        internal_pos = self._internal_positions.get(deployment_id)
        if self._position_repo is not None:
            try:
                positions = self._position_repo.list_by_deployment(deployment_id=deployment_id)
                internal_pos = {
                    position["symbol"]: Decimal(position["quantity"])
                    for position in positions
                    if position.get("symbol") and position.get("quantity") is not None
                }
            except Exception as e:
                logger.warning(
                    "Failed to query position repository; falling back to injected state",
                    extra={
                        "operation": "position_repo_query_failed",
                        "component": "ReconciliationService",
                        "deployment_id": deployment_id,
                        "error": str(e),
                    },
                )

        positions_checked = len(broker_pos_map)

        if internal_pos is not None:
            internal_symbols = set(internal_pos.keys())
            broker_symbols = set(broker_pos_map.keys())

            # Missing positions: in internal but not at broker
            for sym in internal_symbols - broker_symbols:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=DiscrepancyType.MISSING_POSITION,
                        entity_type="position",
                        entity_id=sym,
                        symbol=sym,
                        internal_value=str(internal_pos[sym]),
                        broker_value="0",
                    )
                )

            # Extra positions: at broker but not in internal
            for sym in broker_symbols - internal_symbols:
                broker_p = broker_pos_map[sym]
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type=DiscrepancyType.EXTRA_POSITION,
                        entity_type="position",
                        entity_id=sym,
                        symbol=sym,
                        internal_value="0",
                        broker_value=str(broker_p.quantity),
                    )
                )

            positions_checked = max(len(internal_symbols), len(broker_symbols))

        # --- Build report ---
        resolved_count = sum(1 for d in discrepancies if d.auto_resolved)
        unresolved_count = len(discrepancies) - resolved_count
        status = "completed" if len(discrepancies) == 0 else "completed_with_discrepancies"

        report = ReconciliationReport(
            report_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            trigger=trigger,
            discrepancies=discrepancies,
            resolved_count=resolved_count,
            unresolved_count=unresolved_count,
            status=status,
            orders_checked=orders_checked,
            positions_checked=positions_checked,
        )

        self._reconciliation_repo.save(report)

        # Emit Prometheus metrics for reconciliation tracking.
        try:
            from services.api.metrics import (
                RECONCILIATION_DISCREPANCIES_TOTAL,
                RECONCILIATION_RUNS_TOTAL,
            )

            RECONCILIATION_RUNS_TOTAL.labels(trigger=trigger.value, status=status).inc()
            for d in discrepancies:
                dtype = "resolved" if d.auto_resolved else "unresolved"
                RECONCILIATION_DISCREPANCIES_TOTAL.labels(type=dtype).inc()
        except ImportError:
            pass  # Metrics module not available (standalone tests)

        logger.info(
            "Reconciliation run completed",
            extra={
                "operation": "reconciliation_run_completed",
                "component": "ReconciliationService",
                "deployment_id": deployment_id,
                "trigger": trigger.value,
                "report_id": report.report_id,
                "discrepancy_count": len(discrepancies),
                "resolved_count": resolved_count,
                "unresolved_count": unresolved_count,
                "status": status,
            },
        )

        return report

    def get_report(
        self,
        *,
        report_id: str,
    ) -> ReconciliationReport:
        """
        Get a specific reconciliation report.

        Args:
            report_id: ULID of the report.

        Returns:
            ReconciliationReport.

        Raises:
            NotFoundError: report not found.
        """
        report = self._reconciliation_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundError(f"Reconciliation report {report_id} not found")
        return report

    def list_reports(
        self,
        *,
        deployment_id: str,
        limit: int = 20,
    ) -> list[ReconciliationReport]:
        """
        List reconciliation reports for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            limit: Maximum number of reports to return.

        Returns:
            List of ReconciliationReport objects, most recent first.
        """
        return self._reconciliation_repo.list_by_deployment(
            deployment_id=deployment_id, limit=limit
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_all_broker_orders(
        adapter: BrokerAdapterInterface,
    ) -> list[OrderResponse]:
        """
        Get all broker order states for reconciliation.

        Uses get_all_order_states() if available (paper/shadow adapters),
        otherwise falls back to list_open_orders().

        Args:
            adapter: The broker adapter to query.

        Returns:
            List of all order responses from the broker.
        """
        # Paper adapter exposes get_all_order_states(), mock exposes
        # get_all_orders(). Try both before falling back to open orders only.
        if hasattr(adapter, "get_all_order_states"):
            return adapter.get_all_order_states()
        if hasattr(adapter, "get_all_orders"):
            return adapter.get_all_orders()
        # Fallback: only open orders visible
        return adapter.list_open_orders()

    @staticmethod
    def _is_safe_status_lag(internal_status: str, broker_status: str) -> bool:
        """
        Determine if a status mismatch is a safe lag.

        A safe lag means the broker is further along in the order
        lifecycle than internal state — this is normal during reconnection
        or when events are still propagating.

        Args:
            internal_status: Status from internal state.
            broker_status: Status from broker.

        Returns:
            True if the mismatch is a safe lag that can be auto-resolved.
        """
        safe_broker_statuses = _SAFE_STATUS_LAG.get(internal_status)
        if safe_broker_statuses is None:
            return False
        return broker_status in safe_broker_statuses

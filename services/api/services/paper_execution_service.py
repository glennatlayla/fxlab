"""
Paper execution service — orchestrates paper-mode order execution.

Responsibilities:
- Manage per-deployment PaperBrokerAdapter instances.
- Validate deployment state before accepting orders (must be active + paper mode).
- Run pre-trade risk checks (pass-through for M4, real gate in M5).
- Submit orders to the paper adapter (returns SUBMITTED, not instant fill).
- Process pending orders via tick-based fill cycle.
- Cancel open paper orders.
- Expose query methods (positions, account, open orders, reconciliation).

Does NOT:
- Execute real broker operations.
- Persist order data to the database (paper adapter is in-memory;
  database persistence added in later milestones).
- Implement risk gate logic (delegated to risk gate interface in M5).

Dependencies:
- DeploymentRepositoryInterface (injected): validates deployment existence and state.
- PaperBrokerAdapter (created internally): per-deployment paper execution.
- structlog: structured logging.

Error conditions:
- NotFoundError: deployment_id does not exist or has no active paper adapter.
- StateTransitionError: deployment is not in an executable paper state.
- ValidationError: duplicate registration attempt.

Example:
    service = PaperExecutionService(deployment_repo=repo)
    service.register_deployment(
        deployment_id="01HDEPLOY...",
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50")},
        commission_per_order=Decimal("1.00"),
    )
    resp = service.submit_paper_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
    filled = service.process_pending_orders(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

import structlog

from libs.broker.paper_broker_adapter import PaperBrokerAdapter
from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.paper_execution_service_interface import (
    PaperExecutionServiceInterface,
)
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface

logger = structlog.get_logger(__name__)


class PaperExecutionService(PaperExecutionServiceInterface):
    """
    Production implementation of paper-mode execution orchestration.

    Responsibilities:
    - Maintains a registry of PaperBrokerAdapter instances keyed by deployment_id.
    - Validates deployment state (active + paper mode) before order execution.
    - Delegates order submission to the per-deployment paper adapter (SUBMITTED status).
    - Processes pending orders via tick-based fill cycle.
    - Exposes query methods for positions, account, open orders, and reconciliation.

    Does NOT:
    - Contain risk gate logic (pass-through for M4; real gate injected in M5).
    - Persist paper events to the database (in-memory only for M4).
    - Access the database directly (uses repository interface).

    Dependencies:
    - DeploymentRepositoryInterface (injected): for deployment validation.
    - structlog: for structured logging of all operations.

    Example:
        service = PaperExecutionService(deployment_repo=repo)
        service.register_deployment(
            deployment_id="01HDEPLOY...",
            initial_equity=Decimal("1000000"),
        )
        resp = service.submit_paper_order(
            deployment_id="01HDEPLOY...",
            request=order_request,
            correlation_id="corr-001",
        )
        filled = service.process_pending_orders(deployment_id="01HDEPLOY...")
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        risk_gate: RiskGateInterface,
    ) -> None:
        """
        Initialise the paper execution service.

        Args:
            deployment_repo: Repository for deployment state validation.
            risk_gate: Mandatory risk gate for pre-trade checks.
                Every order is structurally enforced through the risk
                gate before reaching the broker adapter.
        """
        self._deployment_repo = deployment_repo
        self._risk_gate = risk_gate
        self._adapters: dict[str, PaperBrokerAdapter] = {}
        self._adapters_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_adapter(self, deployment_id: str) -> PaperBrokerAdapter:
        """
        Retrieve the paper adapter for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            PaperBrokerAdapter instance for this deployment.

        Raises:
            NotFoundError: deployment_id has no registered adapter.
        """
        with self._adapters_lock:
            adapter = self._adapters.get(deployment_id)
        if adapter is None:
            raise NotFoundError(f"Deployment {deployment_id} has no active paper adapter")
        return adapter

    def _validate_deployment_for_execution(self, deployment_id: str) -> None:
        """
        Validate that a deployment is eligible for paper order execution.

        Checks:
        1. Deployment exists in the repository.
        2. Deployment state is 'active'.
        3. Deployment execution_mode is 'paper'.
        4. Deployment has a registered paper adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment is not in executable state
                or not in paper mode.
        """
        record = self._deployment_repo.get_by_id(deployment_id)
        if record is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        if record["state"] != "active":
            raise StateTransitionError(
                f"Deployment {deployment_id} is not in executable state "
                f"(current: {record['state']}, required: active)",
                current_state=record["state"],
                attempted_state="active",
            )

        if record["execution_mode"] != "paper":
            raise StateTransitionError(
                f"Deployment {deployment_id} is not in paper mode "
                f"(current: {record['execution_mode']})",
                current_state=record["execution_mode"],
                attempted_state="paper",
            )

        with self._adapters_lock:
            if deployment_id not in self._adapters:
                raise NotFoundError(f"Deployment {deployment_id} has no active paper adapter")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_deployment(
        self,
        *,
        deployment_id: str,
        initial_equity: Decimal,
        market_prices: dict[str, Decimal] | None = None,
        commission_per_order: Decimal = Decimal("0"),
    ) -> None:
        """
        Register a deployment for paper execution.

        Creates an isolated PaperBrokerAdapter instance for the deployment.

        Args:
            deployment_id: ULID of the deployment.
            initial_equity: Starting hypothetical equity.
            market_prices: Optional initial market price map.
            commission_per_order: Fixed commission per fill.

        Raises:
            ValidationError: deployment_id is already registered.
        """
        with self._adapters_lock:
            if deployment_id in self._adapters:
                raise ValidationError(f"Deployment {deployment_id} is already registered")
            self._adapters[deployment_id] = PaperBrokerAdapter(
                market_prices=market_prices or {},
                initial_equity=initial_equity,
                commission_per_order=commission_per_order,
            )
        logger.info(
            "paper_deployment_registered",
            deployment_id=deployment_id,
            initial_equity=str(initial_equity),
            commission_per_order=str(commission_per_order),
            symbols=list((market_prices or {}).keys()),
        )

    def deregister_deployment(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Deregister a deployment and clean up its paper adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment_id is not registered.
        """
        with self._adapters_lock:
            if deployment_id not in self._adapters:
                raise NotFoundError(f"Deployment {deployment_id} is not registered")
            del self._adapters[deployment_id]
        logger.info(
            "paper_deployment_deregistered",
            deployment_id=deployment_id,
        )

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def submit_paper_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Submit an order for paper execution.

        Returns SUBMITTED status (not instant fill). Call
        process_pending_orders() to advance the order lifecycle.

        Pipeline: validate deployment → pre-trade risk check → paper submit
        → log result → return SUBMITTED response.

        Args:
            deployment_id: ULID of the deployment in paper mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with SUBMITTED status.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment not in executable paper state.
        """
        from services.api.metrics import (
            ORDER_LATENCY_SECONDS,
            ORDERS_REJECTED_TOTAL,
            ORDERS_SUBMITTED_TOTAL,
        )

        t0 = time.perf_counter()

        # Step 1: Validate deployment state
        self._validate_deployment_for_execution(deployment_id)

        # Step 2: Get adapter reference under lock, then release for work
        with self._adapters_lock:
            adapter = self._adapters[deployment_id]

        # Step 3: Structural pre-trade risk enforcement (mandatory — not optional).
        # enforce_order() raises RiskGateRejectionError on failure, making it
        # impossible to accidentally submit an order without risk checking.
        try:
            positions = adapter.get_positions()
            account = adapter.get_account()
            self._risk_gate.enforce_order(
                deployment_id=deployment_id,
                order=request,
                positions=positions,
                account=account,
                correlation_id=correlation_id,
            )
        except Exception:
            ORDERS_REJECTED_TOTAL.labels(execution_mode="paper", reason="risk_gate").inc()
            raise

        # Step 4: Submit to paper adapter (returns SUBMITTED, not FILLED)
        response = adapter.submit_order(request)

        # Emit execution metrics
        elapsed = time.perf_counter() - t0
        ORDERS_SUBMITTED_TOTAL.labels(
            execution_mode="paper",
            symbol=request.symbol,
            side=request.side.value,
        ).inc()
        ORDER_LATENCY_SECONDS.labels(
            execution_mode="paper",
            order_type=request.order_type.value
            if hasattr(request.order_type, "value")
            else str(request.order_type),
        ).observe(elapsed)

        logger.info(
            "paper_order_submitted",
            deployment_id=deployment_id,
            client_order_id=request.client_order_id,
            broker_order_id=response.broker_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            status=response.status.value,
            correlation_id=correlation_id,
            latency_ms=round(elapsed * 1000, 2),
        )

        return response

    def process_pending_orders(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Process pending orders for a deployment (tick-based fill).

        Delegates to the PaperBrokerAdapter's process_pending_orders()
        which evaluates fill conditions for all pending orders.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of OrderResponse for orders that were filled this tick.

        Raises:
            NotFoundError: deployment_id has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        filled = adapter.process_pending_orders()

        if filled:
            logger.info(
                "paper_orders_processed",
                deployment_id=deployment_id,
                filled_count=len(filled),
                order_ids=[f.broker_order_id for f in filled],
            )

        return filled

    def cancel_paper_order(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Cancel an open paper order.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with current status.

        Raises:
            NotFoundError: deployment or order not found.
        """
        adapter = self._get_adapter(deployment_id)
        response = adapter.cancel_order(broker_order_id)

        logger.info(
            "paper_order_cancelled",
            deployment_id=deployment_id,
            broker_order_id=broker_order_id,
            status=response.status.value,
            correlation_id=correlation_id,
        )

        return response

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def update_market_price(
        self,
        *,
        deployment_id: str,
        symbol: str,
        price: Decimal,
    ) -> None:
        """
        Update market price for a symbol in a deployment's paper adapter.

        Args:
            deployment_id: ULID of the deployment.
            symbol: Instrument ticker.
            price: Current market price.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        adapter.update_market_price(symbol, price)
        logger.debug(
            "paper_market_price_updated",
            deployment_id=deployment_id,
            symbol=symbol,
            price=str(price),
        )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_paper_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current positions for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for non-zero positions.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_positions()

    def get_paper_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get account state for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity, cash, positions.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_account()

    def get_open_orders(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Get all open/pending orders for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of open OrderResponse objects.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.list_open_orders()

    def get_all_order_states(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Get all order states for reconciliation recovery.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of all OrderResponse objects (all statuses).

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_all_order_states()

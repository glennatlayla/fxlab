"""
Shadow execution service — orchestrates shadow-mode order execution.

Responsibilities:
- Manage per-deployment ShadowBrokerAdapter instances.
- Validate deployment state before accepting orders (must be active + shadow mode).
- Run pre-trade risk checks (pass-through for M3, real gate in M5).
- Submit orders to the shadow adapter and return fill results.
- Expose shadow-specific query methods (decisions, P&L, positions, account).

Does NOT:
- Execute real broker operations.
- Persist order data to the database (shadow adapter is in-memory;
  database persistence of shadow events is added in M4+).
- Implement risk gate logic (delegated to risk gate interface in M5).

Dependencies:
- DeploymentRepositoryInterface (injected): validates deployment existence and state.
- ShadowBrokerAdapter (created internally): per-deployment shadow execution.
- structlog: structured logging.

Error conditions:
- NotFoundError: deployment_id does not exist or has no active shadow adapter.
- StateTransitionError: deployment is not in an executable shadow state.
- ValidationError: duplicate registration attempt.

Example:
    service = ShadowExecutionService(deployment_repo=repo)
    service.register_deployment(
        deployment_id="01HDEPLOY...",
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50")},
    )
    resp = service.execute_shadow_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any

import structlog

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
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.interfaces.shadow_execution_service_interface import (
    ShadowExecutionServiceInterface,
)
from libs.contracts.mocks.shadow_broker_adapter import ShadowBrokerAdapter

logger = structlog.get_logger(__name__)


class ShadowExecutionService(ShadowExecutionServiceInterface):
    """
    Production implementation of shadow-mode execution orchestration.

    Responsibilities:
    - Maintains a registry of ShadowBrokerAdapter instances keyed by deployment_id.
    - Validates deployment state (active + shadow mode) before order execution.
    - Delegates order execution to the per-deployment shadow adapter.
    - Exposes query methods for shadow decisions, P&L, positions, and account.

    Does NOT:
    - Contain risk gate logic (pass-through for M3; real gate injected in M5).
    - Persist shadow events to the database (in-memory only for M3).
    - Access the database directly (uses repository interface).

    Dependencies:
    - DeploymentRepositoryInterface (injected): for deployment validation.
    - structlog: for structured logging of all operations.

    Example:
        service = ShadowExecutionService(deployment_repo=repo)
        service.register_deployment(
            deployment_id="01HDEPLOY...",
            initial_equity=Decimal("1000000"),
        )
        resp = service.execute_shadow_order(
            deployment_id="01HDEPLOY...",
            request=order_request,
            correlation_id="corr-001",
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        risk_gate: RiskGateInterface,
    ) -> None:
        """
        Initialise the shadow execution service.

        Args:
            deployment_repo: Repository for deployment state validation.
            risk_gate: Mandatory risk gate for pre-trade checks.
                Every order is structurally enforced through the risk
                gate before reaching the broker adapter.
        """
        self._deployment_repo = deployment_repo
        self._risk_gate = risk_gate
        self._adapters: dict[str, ShadowBrokerAdapter] = {}
        self._adapters_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_adapter(self, deployment_id: str) -> ShadowBrokerAdapter:
        """
        Retrieve the shadow adapter for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            ShadowBrokerAdapter instance for this deployment.

        Raises:
            NotFoundError: deployment_id has no registered adapter.
        """
        with self._adapters_lock:
            adapter = self._adapters.get(deployment_id)
        if adapter is None:
            raise NotFoundError(f"Deployment {deployment_id} has no active shadow adapter")
        return adapter

    def _validate_deployment_for_execution(self, deployment_id: str) -> None:
        """
        Validate that a deployment is eligible for shadow order execution.

        Checks:
        1. Deployment exists in the repository.
        2. Deployment state is 'active'.
        3. Deployment execution_mode is 'shadow'.
        4. Deployment has a registered shadow adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment is not in executable state
                or not in shadow mode.
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

        if record["execution_mode"] != "shadow":
            raise StateTransitionError(
                f"Deployment {deployment_id} is not in shadow mode "
                f"(current: {record['execution_mode']})",
                current_state=record["execution_mode"],
                attempted_state="shadow",
            )

        with self._adapters_lock:
            adapter_exists = deployment_id in self._adapters
        if not adapter_exists:
            raise NotFoundError(f"Deployment {deployment_id} has no active shadow adapter")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_deployment(
        self,
        *,
        deployment_id: str,
        initial_equity: Decimal,
        market_prices: dict[str, Decimal] | None = None,
    ) -> None:
        """
        Register a deployment for shadow execution.

        Creates an isolated ShadowBrokerAdapter instance for the deployment.

        Args:
            deployment_id: ULID of the deployment.
            initial_equity: Starting hypothetical equity.
            market_prices: Optional initial market price map.

        Raises:
            ValidationError: deployment_id is already registered.
        """
        with self._adapters_lock:
            if deployment_id in self._adapters:
                raise ValidationError(f"Deployment {deployment_id} is already registered")
            self._adapters[deployment_id] = ShadowBrokerAdapter(
                market_prices=market_prices or {},
                initial_equity=initial_equity,
            )
        logger.info(
            "shadow_deployment_registered",
            deployment_id=deployment_id,
            initial_equity=str(initial_equity),
            symbols=list((market_prices or {}).keys()),
        )

    def deregister_deployment(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Deregister a deployment and clean up its shadow adapter.

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
            "shadow_deployment_deregistered",
            deployment_id=deployment_id,
        )

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def execute_shadow_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Execute a shadow order for a deployment.

        Pipeline: validate deployment → pre-trade risk check → shadow fill
        → log result → return response.

        Args:
            deployment_id: ULID of the deployment in shadow mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID from the originating signal.

        Returns:
            OrderResponse with FILLED status and shadow fill price.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment is not in executable shadow state.
        """
        from services.api.metrics import (
            ORDER_LATENCY_SECONDS,
            ORDERS_REJECTED_TOTAL,
            ORDERS_SUBMITTED_TOTAL,
        )

        t0 = time.perf_counter()

        # Step 1: Validate deployment state
        self._validate_deployment_for_execution(deployment_id)

        # Step 2: Get adapter reference under lock, then release
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
            ORDERS_REJECTED_TOTAL.labels(execution_mode="shadow", reason="risk_gate").inc()
            raise

        # Step 4: Submit to shadow adapter
        response = adapter.submit_order(request)

        # Emit execution metrics
        elapsed = time.perf_counter() - t0
        ORDERS_SUBMITTED_TOTAL.labels(
            execution_mode="shadow",
            symbol=request.symbol,
            side=request.side.value,
        ).inc()
        ORDER_LATENCY_SECONDS.labels(
            execution_mode="shadow",
            order_type=request.order_type.value
            if hasattr(request.order_type, "value")
            else str(request.order_type),
        ).observe(elapsed)

        logger.info(
            "shadow_order_executed",
            deployment_id=deployment_id,
            client_order_id=request.client_order_id,
            broker_order_id=response.broker_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            fill_price=str(response.average_fill_price),
            status=response.status.value,
            correlation_id=correlation_id,
            latency_ms=round(elapsed * 1000, 2),
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
        Update the market price for a symbol within a deployment's shadow adapter.

        Args:
            deployment_id: ULID of the deployment.
            symbol: Instrument ticker.
            price: Current market price.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.
        """
        adapter = self._get_adapter(deployment_id)
        adapter.update_market_price(symbol, price)
        logger.debug(
            "shadow_market_price_updated",
            deployment_id=deployment_id,
            symbol=symbol,
            price=str(price),
        )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_shadow_decisions(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        Retrieve the full decision timeline for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of decision event dicts, ordered chronologically.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_decision_timeline()

    def get_shadow_pnl(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Get hypothetical P&L summary for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Dict with total_unrealized_pnl, total_realized_pnl, positions.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_shadow_pnl()

    def get_shadow_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current hypothetical positions for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for non-zero positions.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_positions()

    def get_shadow_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get hypothetical account state for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity reflecting unrealized P&L.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.
        """
        adapter = self._get_adapter(deployment_id)
        return adapter.get_account()

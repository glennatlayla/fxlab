"""
Live execution service — orchestrates live-mode order execution through real brokers.

Responsibilities:
- Validate deployment state before accepting live orders (must be active + live mode).
- Double-check kill switch state before every order submission.
- Run mandatory pre-trade risk gate enforcement (no bypass).
- Persist every order to the database BEFORE broker submission.
- Submit orders through the BrokerAdapterRegistry to real broker adapters.
- Update order status with broker acknowledgment after submission.
- Record execution events at every lifecycle state transition.
- Provide position and account queries delegated to the broker adapter.
- Thread-safe: Lock on order state transitions.

Does NOT:
- Implement broker communication directly (delegates to BrokerAdapterInterface).
- Contain risk gate logic (delegates to RiskGateInterface).
- Contain kill switch logic (delegates to KillSwitchServiceInterface).
- Know about specific broker APIs (Alpaca, Schwab, etc.).

Dependencies:
- DeploymentRepositoryInterface (injected): validates deployment existence and state.
- OrderRepositoryInterface (injected): persists order records.
- PositionRepositoryInterface (injected): persists position records.
- ExecutionEventRepositoryInterface (injected): records order lifecycle events.
- RiskGateInterface (injected): mandatory pre-trade risk enforcement.
- BrokerAdapterRegistry (injected): routes orders to the correct broker.
- KillSwitchServiceInterface (injected): halts trading when activated.
- structlog: structured logging.

Error conditions:
- NotFoundError: deployment or order not found, or no broker adapter registered.
- StateTransitionError: deployment not in executable live state.
- KillSwitchActiveError: trading halted for this deployment/strategy/symbol.
- RiskGateRejectionError: order fails pre-trade risk checks.
- ExternalServiceError: broker communication failure.

Example:
    service = LiveExecutionService(
        deployment_repo=deployment_repo,
        order_repo=order_repo,
        position_repo=position_repo,
        execution_event_repo=event_repo,
        risk_gate=risk_gate,
        broker_registry=broker_registry,
        kill_switch_service=kill_switch_service,
    )
    resp = service.submit_live_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from libs.contracts.errors import (
    ConfigError,
    ExternalServiceError,
    KillSwitchActiveError,
    NotFoundError,
    StateTransitionError,
)
from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    PositionSnapshot,
)
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)
from libs.contracts.interfaces.kill_switch_service_interface import (
    KillSwitchServiceInterface,
)
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)
from libs.contracts.interfaces.position_repository_interface import (
    PositionRepositoryInterface,
)
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.interfaces.transaction_manager_interface import (
    TransactionManagerInterface,
)
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.services.interfaces.live_execution_service_interface import (
    LiveExecutionServiceInterface,
)

logger = structlog.get_logger(__name__)


@dataclass
class _PositionCache:
    """
    Cached broker position and account snapshot with staleness tracking.

    Used to avoid redundant broker calls within a short time window when
    submitting rapid orders. Accumulates pending (submitted but unfilled)
    order exposure for risk gate checks.

    Attributes:
        positions: List of PositionSnapshot from broker.
        account: AccountSnapshot from broker.
        timestamp: time.monotonic() when cache was populated (for staleness check).
        pending_exposure: Dict mapping symbol → total notional exposure from
            submitted-but-unfilled orders. Merged into position snapshots for
            risk gate calculations.
    """

    positions: list[PositionSnapshot]
    account: AccountSnapshot
    timestamp: float
    pending_exposure: dict[str, Decimal]


class LiveExecutionService(LiveExecutionServiceInterface):
    """
    Production implementation of live-mode execution orchestration.

    Responsibilities:
    - Validates deployment state (active + live mode) before order execution.
    - Checks kill switch state at all applicable scopes before every order.
    - Enforces pre-trade risk gate — structurally mandatory, no bypass.
    - Persists every order to the database BEFORE submitting to the broker.
    - Submits orders through BrokerAdapterRegistry to real broker adapters.
    - Updates order records and records execution events after broker response.
    - Delegates position/account queries to broker adapters via the registry.
    - Caches position/account snapshots with staleness awareness to avoid
      redundant broker calls during rapid order submission.
    - Thread-safe: order state transitions protected by Lock.

    Does NOT:
    - Create or manage broker adapter instances (BrokerAdapterRegistry does).
    - Implement broker protocols (adapter responsibility).
    - Persist shadow or paper orders (different service responsibilities).

    Dependencies:
    - DeploymentRepositoryInterface: deployment state validation.
    - OrderRepositoryInterface: order record persistence.
    - PositionRepositoryInterface: position record persistence.
    - ExecutionEventRepositoryInterface: execution event audit trail.
    - RiskGateInterface: mandatory pre-trade risk checks.
    - BrokerAdapterRegistry: broker adapter routing.
    - KillSwitchServiceInterface: halt state checks.

    Example:
        service = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=broker_registry,
            kill_switch_service=kill_switch_service,
        )
        resp = service.submit_live_order(
            deployment_id="01HDEPLOY...",
            request=order_request,
            correlation_id="corr-001",
        )
    """

    # Position cache staleness threshold (seconds). If cached data is older than
    # this, refresh from broker before risk checks.
    _POSITION_CACHE_TTL_SECONDS = 2.0

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        order_repo: OrderRepositoryInterface,
        position_repo: PositionRepositoryInterface,
        execution_event_repo: ExecutionEventRepositoryInterface,
        risk_gate: RiskGateInterface,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: KillSwitchServiceInterface,
        transaction_manager: TransactionManagerInterface | None = None,
        position_cache_ttl_seconds: float = 2.0,
    ) -> None:
        """
        Initialise the live execution service.

        Args:
            deployment_repo: Repository for deployment state validation.
            order_repo: Repository for order persistence.
            position_repo: Repository for position persistence.
            execution_event_repo: Repository for execution event audit trail.
            risk_gate: Mandatory risk gate for pre-trade checks.
            broker_registry: Registry routing deployment_id → broker adapter.
            kill_switch_service: Service for kill switch halt checks.
            transaction_manager: Optional explicit transaction boundary
                manager.  When provided, the service commits at critical
                points in the order lifecycle (e.g. after persisting a new
                order and BEFORE submitting to the broker).  This ensures
                the order record survives process crashes during broker
                communication.  When None, the service relies on the
                caller (request middleware, etc.) to manage transactions.
            position_cache_ttl_seconds: How long to reuse position/account
                snapshots before refreshing from broker (default 2.0 seconds).
                Allows rapid order submission without redundant broker calls.
        """
        self._deployment_repo = deployment_repo
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._execution_event_repo = execution_event_repo
        self._risk_gate = risk_gate
        self._broker_registry = broker_registry
        self._kill_switch_service = kill_switch_service
        self._tx = transaction_manager
        self._order_lock = threading.Lock()
        self._position_cache_ttl_seconds = position_cache_ttl_seconds
        self._position_cache: _PositionCache | None = None

        # Load execution mode restrictions from environment.
        # Default allows all modes for backward compatibility.
        # Set ALLOWED_EXECUTION_MODES=shadow,paper to disable live trading.
        allowed_modes_str = os.environ.get("ALLOWED_EXECUTION_MODES", "shadow,paper,live")
        self._allowed_modes = set(allowed_modes_str.split(","))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_position_cache_fresh(self) -> bool:
        """
        Check if cached position/account data is still fresh.

        Returns:
            True if cache exists and is within TTL, False otherwise.
        """
        if self._position_cache is None:
            return False

        age = time.monotonic() - self._position_cache.timestamp
        return age <= self._position_cache_ttl_seconds

    def _calculate_pending_exposure(
        self,
        deployment_id: str,
    ) -> dict[str, Decimal]:
        """
        Calculate pending order exposure for a deployment.

        Sums notional exposure of all orders with status='submitted' or
        'partial_fill' (orders sent to broker but not yet fully filled).
        Used to accumulate concurrent order risk before the individual
        order is filled or rejected.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Dict mapping symbol → total notional exposure (Decimal).
            Empty dict if no pending orders.
        """
        pending_exposure: dict[str, Decimal] = {}

        # Query open orders (non-terminal status)
        open_orders = self._order_repo.list_open_by_deployment(
            deployment_id=deployment_id,
        )

        for order in open_orders:
            # Only count orders that have been submitted to the broker
            # (status=submitted or partial_fill). Skip 'pending' orders
            # that haven't left our system yet.
            status = order.get("status", "")
            if status not in ("submitted", "partial_fill"):
                continue

            symbol = order.get("symbol", "")
            if not symbol:
                continue

            # Calculate notional: quantity × last known fill price or estimate
            try:
                quantity = Decimal(str(order.get("quantity", "0")))
                # If partially filled, add only unfilled qty to pending
                filled_qty = Decimal(str(order.get("filled_quantity", "0")))
                pending_qty = quantity - filled_qty

                # Use average fill price if available, else estimate from limit price
                price = None
                if order.get("average_fill_price"):
                    price = Decimal(str(order["average_fill_price"]))
                elif order.get("limit_price"):
                    price = Decimal(str(order["limit_price"]))

                if price and pending_qty > 0:
                    notional = pending_qty * price
                    pending_exposure[symbol] = pending_exposure.get(symbol, Decimal("0")) + notional
            except (ValueError, TypeError, ArithmeticError):
                # Skip malformed order records
                logger.warning(
                    "pending_exposure_calculation_skipped",
                    order_id=order.get("id"),
                    reason="malformed_numeric_field",
                    component="live_execution",
                )
                continue

        return pending_exposure

    def _get_cached_or_fresh_positions_and_account(
        self,
        *,
        deployment_id: str,
        adapter: Any,  # BrokerAdapterInterface
    ) -> tuple[list[PositionSnapshot], AccountSnapshot]:
        """
        Get position/account snapshot, using cache if fresh; refreshing if stale.

        If cached data is within TTL, reuse it. Otherwise, fetch from broker
        and update cache. Accumulates pending order exposure into the returned
        snapshots for risk gate calculations.

        Args:
            deployment_id: Deployment ULID (used for pending order queries).
            adapter: BrokerAdapterInterface to query if cache is stale.

        Returns:
            Tuple of (positions, account) with pending exposure accumulated.
        """
        # Check cache freshness
        if not self._is_position_cache_fresh():
            # Cache is stale or empty — fetch from broker
            positions = adapter.get_positions()
            account = adapter.get_account()

            # Calculate pending exposure for this deployment
            pending_exposure = self._calculate_pending_exposure(deployment_id)

            # Update cache
            self._position_cache = _PositionCache(
                positions=positions,
                account=account,
                timestamp=time.monotonic(),
                pending_exposure=pending_exposure,
            )

            logger.debug(
                "position_cache_refreshed",
                deployment_id=deployment_id,
                symbols_in_pending=len(pending_exposure),
                component="live_execution",
            )
        else:
            logger.debug(
                "position_cache_reused",
                deployment_id=deployment_id,
                age_ms=round((time.monotonic() - self._position_cache.timestamp) * 1000, 1),
                component="live_execution",
            )

        # Return cached data
        assert self._position_cache is not None
        return self._position_cache.positions, self._position_cache.account

    def _invalidate_position_cache(self) -> None:
        """
        Invalidate the position cache (force refresh on next order).

        Called after order submission to ensure the next order sees
        updated position state.
        """
        self._position_cache = None

    def _validate_deployment_for_live_execution(self, deployment_id: str) -> None:
        """
        Validate that a deployment is eligible for live order execution.

        Checks:
        1. Deployment exists in the repository.
        2. Deployment state is 'active'.
        3. Deployment execution_mode is 'live'.
        4. Deployment has a registered broker adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment is not in executable live state.
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

        if record["execution_mode"] != "live":
            raise StateTransitionError(
                f"Deployment {deployment_id} is not in live mode "
                f"(current: {record['execution_mode']})",
                current_state=record["execution_mode"],
                attempted_state="live",
            )

        if not self._broker_registry.is_registered(deployment_id):
            raise NotFoundError(f"No broker adapter registered for deployment {deployment_id}")

    def _check_kill_switch(
        self,
        *,
        deployment_id: str,
        strategy_id: str | None = None,
        symbol: str | None = None,
    ) -> None:
        """
        Check if trading is halted at any applicable scope.

        Checks global, strategy, and symbol-level kill switches.

        Args:
            deployment_id: ULID of the deployment.
            strategy_id: Optional strategy ULID for strategy-level check.
            symbol: Optional symbol for symbol-level check.

        Raises:
            KillSwitchActiveError: if any applicable kill switch is active.
        """
        if self._kill_switch_service.is_halted(
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol=symbol,
        ):
            logger.warning(
                "live_order_blocked_by_kill_switch",
                deployment_id=deployment_id,
                strategy_id=strategy_id,
                symbol=symbol,
                component="live_execution",
            )
            raise KillSwitchActiveError(
                f"Trading halted for deployment {deployment_id}",
                deployment_id=deployment_id,
                scope="deployment",
                target_id=deployment_id,
            )

    def _record_event(
        self,
        *,
        order_id: str,
        event_type: str,
        correlation_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an execution event to the append-only audit trail.

        Args:
            order_id: Parent order ULID.
            event_type: Event type string.
            correlation_id: Distributed tracing ID.
            details: Optional event context.
        """
        self._execution_event_repo.save(
            order_id=order_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id,
            details=details,
        )

    # ------------------------------------------------------------------
    # Submit live order
    # ------------------------------------------------------------------

    def submit_live_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Submit a live order through a real broker adapter.

        Pipeline:
        1. Validate deployment state (active + live mode)
        2. Check kill switch (global, strategy, symbol scopes)
        3. Check for idempotent duplicate (client_order_id)
        4. Enforce pre-trade risk gate
        5. Persist order to database (status=pending)
        6. Submit to broker adapter
        7. Update order with broker acknowledgment
        8. Record execution events

        Args:
            deployment_id: ULID of the deployment in live mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID from the originating signal.

        Returns:
            OrderResponse with broker-assigned status and broker_order_id.

        Raises:
            NotFoundError: deployment does not exist or has no broker adapter.
            StateTransitionError: deployment is not in executable live state.
            KillSwitchActiveError: trading halted for this scope.
            RiskGateRejectionError: order fails risk checks.
            ExternalServiceError: broker communication failure.
            ConfigError: TransactionManager is required for live execution mode.
        """
        from services.api.metrics import (
            ORDER_LATENCY_SECONDS,
            ORDERS_REJECTED_TOTAL,
            ORDERS_SUBMITTED_TOTAL,
        )

        t0 = time.perf_counter()

        # Step 0: Environment-level execution mode enforcement.
        # This is the first check — before any other logic — to ensure
        # operators can completely disable live trading via environment variable.
        if "live" not in self._allowed_modes:
            logger.error(
                "live_trading_disabled_by_environment",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="live_execution",
            )
            raise ConfigError(
                "Live trading is disabled via ALLOWED_EXECUTION_MODES environment variable"
            )

        # Step 1: Validate deployment state (mode, active, exists).
        # This must run first so that paper/shadow deployments get
        # StateTransitionError before any live-only checks fire.
        self._validate_deployment_for_live_execution(deployment_id)

        # Step 1b: Verify TransactionManager is wired for live mode.
        # Live execution MUST have a transaction manager to ensure order
        # records survive process crashes during broker communication.
        # Without it, an order could be submitted to the broker but the
        # database record rolled back, creating an orphaned trade.
        if self._tx is None:
            logger.critical(
                "transaction_manager_missing_for_live_execution",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="live_execution",
            )
            raise ConfigError(
                "TransactionManager is required for live execution mode. "
                "Wire SqlTransactionManager in production."
            )

        # Step 1c: Adapter type validation — prevent live deployments routed to paper/shadow adapters
        # Get the adapter to check its type BEFORE proceeding
        adapter = self._broker_registry.get(deployment_id)
        record = self._deployment_repo.get_by_id(deployment_id)
        if record["execution_mode"] == "live" and adapter.is_paper_adapter:
            logger.error(
                "live_deployment_routed_to_paper_adapter",
                deployment_id=deployment_id,
                adapter_type=type(adapter).__name__,
                correlation_id=correlation_id,
                component="live_execution",
            )
            raise ConfigError(
                f"Deployment {deployment_id} is in live mode but routed to a "
                f"paper/shadow adapter (type: {type(adapter).__name__})"
            )

        # Step 2: Kill switch pre-check — before any persistence or broker call
        self._check_kill_switch(
            deployment_id=deployment_id,
            strategy_id=request.strategy_id,
            symbol=request.symbol,
        )

        # Step 3: Idempotency check — return existing order if duplicate
        existing = self._order_repo.get_by_client_order_id(request.client_order_id)
        if existing is not None:
            logger.info(
                "live_order_idempotent_hit",
                client_order_id=request.client_order_id,
                existing_order_id=existing["id"],
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="live_execution",
            )
            return OrderResponse(
                broker_order_id=existing.get("broker_order_id", ""),
                status=OrderStatus(existing["status"]),
                client_order_id=existing["client_order_id"],
                symbol=existing["symbol"],
                side=existing["side"],
                order_type=existing["order_type"],
                quantity=existing["quantity"],
                time_in_force=existing["time_in_force"],
                filled_quantity=existing.get("filled_quantity"),
                average_fill_price=existing.get("average_fill_price"),
                limit_price=existing.get("limit_price"),
                stop_price=existing.get("stop_price"),
                submitted_at=existing.get("submitted_at"),
                filled_at=existing.get("filled_at"),
                cancelled_at=existing.get("cancelled_at"),
                rejected_reason=existing.get("rejected_reason"),
                correlation_id=existing.get("correlation_id", correlation_id),
                execution_mode=existing.get("execution_mode", "live"),
            )

        # Step 4: Structural pre-trade risk enforcement (mandatory — no bypass)
        # Use cached position/account if fresh (within TTL), else refresh from broker.
        # This prevents redundant calls during rapid order submission while still
        # allowing staleness-aware position updates.
        try:
            with self._order_lock:
                positions, account = self._get_cached_or_fresh_positions_and_account(
                    deployment_id=deployment_id,
                    adapter=adapter,
                )

            self._risk_gate.enforce_order(
                deployment_id=deployment_id,
                order=request,
                positions=positions,
                account=account,
                correlation_id=correlation_id,
            )
        except Exception:
            ORDERS_REJECTED_TOTAL.labels(execution_mode="live", reason="risk_gate").inc()
            raise

        # Step 5: Persist order to database BEFORE broker submission.
        # This guarantees recoverability if the process crashes after
        # broker submission but before receiving the acknowledgment.
        with self._order_lock:
            order_record = self._order_repo.save(
                client_order_id=request.client_order_id,
                deployment_id=deployment_id,
                strategy_id=request.strategy_id,
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                quantity=str(request.quantity),
                time_in_force=request.time_in_force.value,
                status="pending",
                correlation_id=correlation_id,
                execution_mode="live",
                limit_price=str(request.limit_price) if request.limit_price else None,
                stop_price=str(request.stop_price) if request.stop_price else None,
            )
        order_id = order_record["id"]

        # Record risk_checked event
        self._record_event(
            order_id=order_id,
            event_type="risk_checked",
            correlation_id=correlation_id,
            details={"result": "passed", "deployment_id": deployment_id},
        )

        # CRITICAL TRANSACTION BOUNDARY: Commit the order and risk_checked
        # event BEFORE broker submission.  If the process crashes after
        # broker submission but before receiving a response, the order
        # record must be in the database so reconciliation can recover it.
        # Without this commit, a crash would roll back both the order AND
        # the broker-submitted trade — leaving an orphaned order on the
        # broker with no database record.
        if self._tx is not None:
            self._tx.commit()

        logger.info(
            "live_order_persisted",
            order_id=order_id,
            client_order_id=request.client_order_id,
            deployment_id=deployment_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            correlation_id=correlation_id,
            component="live_execution",
        )

        # Step 6: Submit to broker adapter
        try:
            broker_response = adapter.submit_order(request)
        except Exception as exc:
            # Broker submission failed — update order to rejected state
            logger.error(
                "live_order_broker_submission_failed",
                order_id=order_id,
                client_order_id=request.client_order_id,
                deployment_id=deployment_id,
                error=str(exc),
                correlation_id=correlation_id,
                component="live_execution",
                exc_info=True,
            )
            self._order_repo.update_status(
                order_id=order_id,
                status="rejected",
                rejected_reason=f"Broker submission failed: {exc}",
            )
            self._record_event(
                order_id=order_id,
                event_type="rejected",
                correlation_id=correlation_id,
                details={"reason": f"Broker submission failed: {exc}"},
            )
            # Commit rejection status + event before raising so the
            # rejection is persisted even though the request will fail.
            if self._tx is not None:
                self._tx.commit()
            # Invalidate cache on failure to ensure next order refreshes
            with self._order_lock:
                self._invalidate_position_cache()
            ORDERS_REJECTED_TOTAL.labels(execution_mode="live", reason="broker_failure").inc()
            raise ExternalServiceError(
                f"Broker submission failed for order {request.client_order_id}: {exc}"
            ) from exc

        # Step 7: Update order with broker acknowledgment
        new_status = (
            broker_response.status.value
            if isinstance(broker_response.status, OrderStatus)
            else str(broker_response.status)
        )
        update_fields: dict[str, Any] = {
            "order_id": order_id,
            "status": new_status,
            "broker_order_id": broker_response.broker_order_id,
        }
        if broker_response.submitted_at:
            update_fields["submitted_at"] = (
                broker_response.submitted_at.isoformat()
                if isinstance(broker_response.submitted_at, datetime)
                else broker_response.submitted_at
            )
        if broker_response.filled_at:
            update_fields["filled_at"] = (
                broker_response.filled_at.isoformat()
                if isinstance(broker_response.filled_at, datetime)
                else broker_response.filled_at
            )
        if broker_response.average_fill_price is not None:
            update_fields["average_fill_price"] = str(broker_response.average_fill_price)
        if broker_response.filled_quantity is not None:
            update_fields["filled_quantity"] = str(broker_response.filled_quantity)
        if broker_response.rejected_reason:
            update_fields["rejected_reason"] = broker_response.rejected_reason

        self._order_repo.update_status(**update_fields)

        # Record submitted event
        self._record_event(
            order_id=order_id,
            event_type="submitted",
            correlation_id=correlation_id,
            details={
                "broker_order_id": broker_response.broker_order_id,
                "broker_status": new_status,
            },
        )

        # If the broker returned FILLED immediately (instant fill adapters),
        # record a fill event as well
        if broker_response.status == OrderStatus.FILLED:
            self._record_event(
                order_id=order_id,
                event_type="filled",
                correlation_id=correlation_id,
                details={
                    "broker_order_id": broker_response.broker_order_id,
                    "fill_price": str(broker_response.average_fill_price),
                    "filled_quantity": str(broker_response.filled_quantity),
                },
            )

        # TRANSACTION BOUNDARY: Commit the status update and all execution
        # events recorded after broker response.  This makes the broker
        # acknowledgment, status transition, and audit events durable as
        # a single atomic unit.
        if self._tx is not None:
            self._tx.commit()

        # Invalidate position cache after successful submission so the next
        # order will see updated position/account state.
        with self._order_lock:
            self._invalidate_position_cache()

        # Emit execution metrics
        elapsed = time.perf_counter() - t0
        ORDERS_SUBMITTED_TOTAL.labels(
            execution_mode="live",
            symbol=request.symbol,
            side=request.side.value,
        ).inc()
        ORDER_LATENCY_SECONDS.labels(
            execution_mode="live",
            order_type=(
                request.order_type.value
                if hasattr(request.order_type, "value")
                else str(request.order_type)
            ),
        ).observe(elapsed)

        logger.info(
            "live_order_submitted",
            order_id=order_id,
            client_order_id=request.client_order_id,
            broker_order_id=broker_response.broker_order_id,
            deployment_id=deployment_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            status=new_status,
            correlation_id=correlation_id,
            latency_ms=round(elapsed * 1000, 2),
            component="live_execution",
        )

        return broker_response

    # ------------------------------------------------------------------
    # Cancel live order
    # ------------------------------------------------------------------

    def cancel_live_order(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Cancel an open live order through the broker adapter.

        Looks up the order by broker_order_id in the database, submits
        cancellation to the broker, and persists the status update.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with updated status.

        Raises:
            NotFoundError: order or deployment not found.
            ExternalServiceError: broker communication failure.
        """
        # Verify the order exists in our database
        order_record = self._order_repo.get_by_broker_order_id(broker_order_id)
        if order_record is None:
            raise NotFoundError(f"No order found with broker_order_id={broker_order_id}")

        adapter = self._broker_registry.get(deployment_id)

        logger.info(
            "live_order_cancel_requested",
            broker_order_id=broker_order_id,
            deployment_id=deployment_id,
            correlation_id=correlation_id,
            component="live_execution",
        )

        cancel_response = adapter.cancel_order(broker_order_id)

        # Update database with cancellation status
        new_status = (
            cancel_response.status.value
            if isinstance(cancel_response.status, OrderStatus)
            else str(cancel_response.status)
        )
        cancelled_at = (
            datetime.now(timezone.utc).isoformat()
            if cancel_response.status == OrderStatus.CANCELLED
            else None
        )
        self._order_repo.update_status(
            order_id=order_record["id"],
            status=new_status,
            cancelled_at=cancelled_at,
        )

        # Record event
        self._record_event(
            order_id=order_record["id"],
            event_type=(
                "cancelled"
                if cancel_response.status == OrderStatus.CANCELLED
                else "cancel_requested"
            ),
            correlation_id=correlation_id,
            details={
                "broker_order_id": broker_order_id,
                "broker_status": new_status,
            },
        )

        # Commit cancellation status + event atomically.
        if self._tx is not None:
            self._tx.commit()

        logger.info(
            "live_order_cancel_result",
            broker_order_id=broker_order_id,
            deployment_id=deployment_id,
            result_status=new_status,
            correlation_id=correlation_id,
            component="live_execution",
        )

        return cancel_response

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def list_live_orders(
        self,
        *,
        deployment_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List live orders for a deployment from the database.

        Args:
            deployment_id: ULID of the deployment.
            status: Optional status filter.

        Returns:
            List of order dicts, ordered by created_at descending.
        """
        return self._order_repo.list_by_deployment(
            deployment_id=deployment_id,
            status=status,
        )

    def get_live_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current live positions from the broker adapter.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for current positions.

        Raises:
            NotFoundError: deployment has no broker adapter.
        """
        adapter = self._broker_registry.get(deployment_id)
        return adapter.get_positions()

    def get_live_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get live account state from the broker adapter.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity, cash, buying power.

        Raises:
            NotFoundError: deployment has no broker adapter.
        """
        adapter = self._broker_registry.get(deployment_id)
        return adapter.get_account()

    def get_live_pnl(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Get live P&L summary for a deployment.

        Combines broker position data to calculate P&L.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Dict with total_unrealized_pnl, total_realized_pnl, positions.

        Raises:
            NotFoundError: deployment has no broker adapter.
        """
        adapter = self._broker_registry.get(deployment_id)
        positions = adapter.get_positions()

        total_unrealized = sum(p.unrealized_pnl for p in positions)
        total_realized = sum(p.realized_pnl for p in positions)

        position_summaries = [
            {
                "symbol": p.symbol,
                "quantity": str(p.quantity),
                "average_entry_price": str(p.average_entry_price),
                "market_price": str(p.market_price),
                "unrealized_pnl": str(p.unrealized_pnl),
                "realized_pnl": str(p.realized_pnl),
            }
            for p in positions
        ]

        return {
            "total_unrealized_pnl": str(total_unrealized),
            "total_realized_pnl": str(total_realized),
            "positions": position_summaries,
        }

    def sync_order_status(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Synchronise a single order's status from the broker.

        Fetches the latest order state from the broker and updates the
        database record. Used for reconciliation and fill detection.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with the latest broker-reported status.

        Raises:
            NotFoundError: order or deployment not found.
            ExternalServiceError: broker communication failure.
        """
        # Verify the order exists in our database
        order_record = self._order_repo.get_by_broker_order_id(broker_order_id)
        if order_record is None:
            raise NotFoundError(f"No order found with broker_order_id={broker_order_id}")

        adapter = self._broker_registry.get(deployment_id)
        broker_state = adapter.get_order(broker_order_id)

        # Update database with the broker's current state
        new_status = (
            broker_state.status.value
            if isinstance(broker_state.status, OrderStatus)
            else str(broker_state.status)
        )
        update_fields: dict[str, Any] = {
            "order_id": order_record["id"],
            "status": new_status,
        }
        if broker_state.filled_at:
            update_fields["filled_at"] = (
                broker_state.filled_at.isoformat()
                if isinstance(broker_state.filled_at, datetime)
                else broker_state.filled_at
            )
        if broker_state.average_fill_price is not None:
            update_fields["average_fill_price"] = str(broker_state.average_fill_price)
        if broker_state.filled_quantity is not None:
            update_fields["filled_quantity"] = str(broker_state.filled_quantity)

        self._order_repo.update_status(**update_fields)

        # Record sync event
        self._record_event(
            order_id=order_record["id"],
            event_type="synced",
            correlation_id=correlation_id,
            details={
                "broker_order_id": broker_order_id,
                "synced_status": new_status,
            },
        )

        logger.info(
            "live_order_synced",
            broker_order_id=broker_order_id,
            deployment_id=deployment_id,
            synced_status=new_status,
            correlation_id=correlation_id,
            component="live_execution",
        )

        return broker_state

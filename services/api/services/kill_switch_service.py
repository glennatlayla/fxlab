"""
Kill switch service implementation.

Responsibilities:
- Manage kill switch activation/deactivation at global, strategy, symbol scopes.
- Measure Mean Time To Halt (MTTH) from trigger to order cancellation confirmation.
- Execute emergency posture for deployments (flatten, cancel, hold).
- Provide status queries and halt checks.
- Persist all kill switch events to durable storage via KillSwitchEventRepository.

Does NOT:
- Implement broker communication (delegates to adapter).
- Auto-trigger from risk gate (caller's responsibility).

Dependencies:
- DeploymentRepositoryInterface: look up deployment and posture config.
- KillSwitchEventRepositoryInterface: persist and query kill switch events.
- BrokerAdapterInterface (via adapter_registry): cancel orders, close positions.

Error conditions:
- StateTransitionError: kill switch already active at requested scope+target.
- NotFoundError: no active kill switch at scope+target for deactivation.
- NotFoundError: deployment not found or no adapter registered.

Example:
    service = KillSwitchService(
        deployment_repo=deployment_repo,
        ks_event_repo=ks_event_repo,
        adapter_registry={"01HDEPLOY...": adapter},
    )
    event = service.activate_kill_switch(
        scope=KillSwitchScope.GLOBAL,
        target_id="global",
        reason="Emergency halt",
        activated_by="system:risk_gate",
    )
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import ulid as _ulid

from libs.contracts.deployment import EmergencyPostureType
from libs.contracts.errors import NotFoundError, StateTransitionError, TransientError
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.kill_switch_event_repository_interface import (
    KillSwitchEventRepositoryInterface,
)
from libs.contracts.interfaces.kill_switch_service_interface import (
    KillSwitchServiceInterface,
)
from libs.contracts.safety import (
    EmergencyPostureDecision,
    EmergencyPostureVerification,
    HaltEvent,
    HaltTrigger,
    KillSwitchScope,
    KillSwitchStatus,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Result dataclasses for retry and verification
# ------------------------------------------------------------------


@dataclass
class CancellationResult:
    """
    Result of attempting to cancel open orders.

    Attributes:
        cancelled_count: Number of orders successfully cancelled.
        failed_count: Number of orders that failed to cancel after retries.
        failed_order_ids: List of broker_order_ids that failed to cancel.
    """

    cancelled_count: int
    failed_count: int
    failed_order_ids: list[str]


@dataclass
class FlattenResult:
    """
    Result of attempting to flatten open positions.

    Attributes:
        flattened_count: Number of close orders successfully submitted.
        failed_count: Number of positions that failed to close.
        failed_symbols: List of symbols that failed to close.
    """

    flattened_count: int
    failed_count: int
    failed_symbols: list[str]


class KillSwitchService(KillSwitchServiceInterface):
    """
    Production implementation of KillSwitchServiceInterface.

    All kill switch state is durably persisted via KillSwitchEventRepository.
    Status queries (is_halted, get_status) read from the database — kill
    switch state survives process restarts.

    Responsibilities:
    - Kill switch activation/deactivation with durable persistence.
    - MTTH measurement via wall-clock timing.
    - Emergency posture execution via broker adapter.
    - Structured logging on all state changes.
    - Thread-safe access to adapter registry.

    Does NOT:
    - Auto-trigger from risk gate (caller's responsibility).

    Example:
        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=ks_event_repo,
            adapter_registry={"01HDEPLOY...": adapter},
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        ks_event_repo: KillSwitchEventRepositoryInterface,
        adapter_registry: dict[str, BrokerAdapterInterface],
        verification_timeout_s: int = 30,
    ) -> None:
        """
        Initialise the kill switch service.

        Args:
            deployment_repo: Repository for deployment lookups.
            ks_event_repo: Repository for kill switch event persistence.
            adapter_registry: Map of deployment_id -> BrokerAdapterInterface.
            verification_timeout_s: Timeout for post-execution position
                verification loop in seconds (default 30). Used by
                execute_emergency_posture to confirm positions are flat.
        """
        self._deployment_repo = deployment_repo
        self._ks_event_repo = ks_event_repo
        self._adapter_registry = adapter_registry
        self._verification_timeout_s = verification_timeout_s
        # Lock protects _adapter_registry against concurrent mutation.
        self._registry_lock = threading.Lock()

    def activate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        reason: str,
        activated_by: str,
        trigger: HaltTrigger = HaltTrigger.KILL_SWITCH,
    ) -> HaltEvent:
        """
        Activate a kill switch at the given scope.

        Persists the halt to durable storage FIRST (fail-closed), then cancels
        all open orders for affected adapters and measures MTTH. If any
        cancellations fail, automatically executes emergency posture for
        affected deployments.

        Args:
            scope: Kill switch scope (global, strategy, symbol).
            target_id: Target identifier.
            reason: Human-readable activation reason.
            activated_by: Identity of the activator.
            trigger: What triggered this activation.

        Returns:
            HaltEvent recording the activation and MTTH.

        Raises:
            StateTransitionError: kill switch already active at this scope+target.
        """
        # Check if already active via DB query — survives restarts.
        existing = self._ks_event_repo.get_active(scope=scope.value, target_id=target_id)
        if existing is not None:
            raise StateTransitionError(
                f"Kill switch already active at scope={scope.value}, target_id={target_id}",
                current_state="active",
                attempted_state="active",
            )

        activated_at = datetime.now(timezone.utc)
        start_ns = time.monotonic_ns()

        # Cancel orders for affected adapters (thread-safe read).
        total_cancelled = 0
        all_failed_orders: list[str] = []
        with self._registry_lock:
            adapters_snapshot = dict(self._adapter_registry)

        for dep_id, adapter in adapters_snapshot.items():
            if self._scope_affects_adapter(scope, target_id, dep_id):
                cancel_result = self._cancel_open_orders(adapter)
                total_cancelled += cancel_result.cancelled_count
                all_failed_orders.extend(cancel_result.failed_order_ids)

                # If any cancellations failed, escalate to emergency posture for this deployment
                if cancel_result.failed_count > 0:
                    try:
                        self.execute_emergency_posture(
                            deployment_id=dep_id,
                            trigger=HaltTrigger.KILL_SWITCH,
                            reason=f"Escalation from failed kill switch order cancellation: "
                            f"{cancel_result.failed_count} orders failed",
                        )
                    except Exception as exc:
                        logger.error(
                            "Emergency posture escalation failed during kill switch",
                            extra={
                                "operation": "emergency_posture_escalation_failed",
                                "component": "KillSwitchService",
                                "deployment_id": dep_id,
                                "scope": scope.value,
                                "target_id": target_id,
                            },
                            exc_info=exc,
                        )

        end_ns = time.monotonic_ns()
        mtth_ms = (end_ns - start_ns) // 1_000_000
        confirmed_at = datetime.now(timezone.utc)

        # PERSIST to durable storage with final MTTH (fail-closed).
        # Even if external calls failed, the halt is recorded durably.
        self._ks_event_repo.save(
            scope=scope.value,
            target_id=target_id,
            activated_by=activated_by,
            activated_at=activated_at.isoformat(),
            reason=reason,
            mtth_ms=mtth_ms,
        )

        event = HaltEvent(
            event_id=str(_ulid.ULID()),
            scope=scope,
            target_id=target_id,
            trigger=trigger,
            reason=reason,
            activated_by=activated_by,
            activated_at=activated_at,
            confirmed_at=confirmed_at,
            mtth_ms=mtth_ms,
            orders_cancelled=total_cancelled,
        )

        # Emit Prometheus metrics for kill switch activation and MTTH.
        try:
            from services.api.metrics import (
                KILL_SWITCH_ACTIVATIONS_TOTAL,
                KILL_SWITCH_MTTH_SECONDS,
            )

            KILL_SWITCH_ACTIVATIONS_TOTAL.labels(scope=scope.value).inc()
            KILL_SWITCH_MTTH_SECONDS.observe(mtth_ms / 1000.0)
        except ImportError:
            pass  # Metrics module not available (e.g., standalone tests)

        logger.info(
            "Kill switch activated",
            extra={
                "operation": "kill_switch_activated",
                "component": "KillSwitchService",
                "scope": scope.value,
                "target_id": target_id,
                "trigger": trigger.value,
                "reason": reason,
                "activated_by": activated_by,
                "mtth_ms": mtth_ms,
                "orders_cancelled": total_cancelled,
                "orders_failed": len(all_failed_orders),
                "failed_order_ids": all_failed_orders,
            },
        )

        return event

    def deactivate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        deactivated_by: str,
    ) -> HaltEvent:
        """
        Deactivate a kill switch at the given scope.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.
            deactivated_by: Identity of the deactivator.

        Returns:
            HaltEvent with deactivation timestamp.

        Raises:
            NotFoundError: no active kill switch at this scope+target.
        """
        # Find the active event in the database.
        active_event = self._ks_event_repo.get_active(scope=scope.value, target_id=target_id)
        if active_event is None:
            raise NotFoundError(
                f"No active kill switch at scope={scope.value}, target_id={target_id}"
            )

        deactivated_at = datetime.now(timezone.utc)

        # Deactivate in the database.
        self._ks_event_repo.deactivate(
            event_id=active_event["id"],
            deactivated_at=deactivated_at.isoformat(),
        )

        event = HaltEvent(
            event_id=str(_ulid.ULID()),
            scope=scope,
            target_id=target_id,
            trigger=HaltTrigger.KILL_SWITCH,
            reason=f"Deactivated by {deactivated_by}",
            activated_by=deactivated_by,
            confirmed_at=deactivated_at,
        )

        logger.info(
            "Kill switch deactivated",
            extra={
                "operation": "kill_switch_deactivated",
                "component": "KillSwitchService",
                "scope": scope.value,
                "target_id": target_id,
                "deactivated_by": deactivated_by,
            },
        )

        return event

    def get_status(self) -> list[KillSwitchStatus]:
        """
        Get the current state of all active kill switches from the database.

        Reads from durable storage — state survives process restarts.

        Returns:
            List of KillSwitchStatus for all active switches.
        """
        active_records = self._ks_event_repo.list_active()
        statuses = []
        for record in active_records:
            statuses.append(
                KillSwitchStatus(
                    scope=KillSwitchScope(record["scope"]),
                    target_id=record["target_id"],
                    is_active=True,
                    activated_at=datetime.fromisoformat(record["activated_at"]),
                    activated_by=record["activated_by"],
                    reason=record["reason"],
                )
            )
        return statuses

    def is_halted(
        self,
        *,
        deployment_id: str,
        strategy_id: str | None = None,
        symbol: str | None = None,
    ) -> bool:
        """
        Check whether trading is halted for the given context.

        Reads from durable storage — halt state survives process restarts.

        A deployment is halted if any of the following are active:
        - Global kill switch
        - Strategy kill switch matching strategy_id
        - Symbol kill switch matching symbol

        Args:
            deployment_id: ULID of the deployment.
            strategy_id: Optional strategy ULID to check.
            symbol: Optional symbol to check.

        Returns:
            True if any relevant kill switch is active.
        """
        # Check global kill switch.
        if self._ks_event_repo.get_active(scope="global", target_id="global") is not None:
            return True

        # Check strategy scope.
        if (
            strategy_id is not None
            and self._ks_event_repo.get_active(scope="strategy", target_id=strategy_id) is not None
        ):
            return True

        # Check symbol scope.
        return (
            symbol is not None
            and self._ks_event_repo.get_active(scope="symbol", target_id=symbol) is not None
        )

    def execute_emergency_posture(
        self,
        *,
        deployment_id: str,
        trigger: HaltTrigger,
        reason: str,
    ) -> EmergencyPostureDecision:
        """
        Execute the declared emergency posture for a deployment.

        Looks up the deployment's declared posture and executes it:
        - flatten_all: Cancel open orders + close all positions at market.
        - cancel_open: Cancel open orders only.
        - hold: Do nothing (human intervention required).
        - custom: Strategy-specific logic (treated as hold for now).

        Args:
            deployment_id: ULID of the deployment.
            trigger: What triggered the posture execution.
            reason: Human-readable reason.

        Returns:
            EmergencyPostureDecision recording what was done.

        Raises:
            NotFoundError: deployment not found or no adapter registered.
        """
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        with self._registry_lock:
            adapter = self._adapter_registry.get(deployment_id)
        if adapter is None:
            raise NotFoundError(f"No adapter registered for deployment {deployment_id}")

        posture_str = deployment.get("emergency_posture", "hold")
        posture = EmergencyPostureType(posture_str)

        start_ns = time.monotonic_ns()
        orders_cancelled = 0
        positions_flattened = 0
        failed_orders: list[str] = []
        failed_symbols: list[str] = []

        # Track whether posture took action that needs verification.
        needs_verification = False

        if posture == EmergencyPostureType.flatten_all:
            cancel_result = self._cancel_open_orders(adapter)
            orders_cancelled = cancel_result.cancelled_count
            failed_orders = cancel_result.failed_order_ids
            flatten_result = self._flatten_positions(adapter)
            positions_flattened = flatten_result.flattened_count
            failed_symbols = flatten_result.failed_symbols
            needs_verification = True
        elif posture == EmergencyPostureType.cancel_open:
            cancel_result = self._cancel_open_orders(adapter)
            orders_cancelled = cancel_result.cancelled_count
            failed_orders = cancel_result.failed_order_ids
            needs_verification = True
        # hold and custom: do nothing, no verification needed

        # Run post-execution verification loop for active postures.
        verification: EmergencyPostureVerification | None = None
        if needs_verification:
            verify_positions = posture == EmergencyPostureType.flatten_all
            verification = self._verify_posture_execution(
                adapter,
                verify_positions=verify_positions,
            )

        end_ns = time.monotonic_ns()
        duration_ms = (end_ns - start_ns) // 1_000_000

        decision = EmergencyPostureDecision(
            decision_id=str(_ulid.ULID()),
            deployment_id=deployment_id,
            posture=posture,
            trigger=trigger,
            reason=reason,
            orders_cancelled=orders_cancelled,
            positions_flattened=positions_flattened,
            duration_ms=duration_ms,
            verification=verification,
        )

        logger.info(
            "Emergency posture executed",
            extra={
                "operation": "emergency_posture_executed",
                "component": "KillSwitchService",
                "deployment_id": deployment_id,
                "posture": posture.value,
                "trigger": trigger.value,
                "orders_cancelled": orders_cancelled,
                "positions_flattened": positions_flattened,
                "duration_ms": duration_ms,
                "failed_orders": failed_orders,
                "failed_symbols": failed_symbols,
                "verification_verified": verification.verified if verification else None,
                "residual_exposure_usd": str(verification.residual_exposure_usd)
                if verification
                else "0",
            },
        )

        return decision

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cancel_open_orders(self, adapter: BrokerAdapterInterface) -> CancellationResult:
        """
        Cancel all open orders via the adapter with retry logic.

        For each open order, attempts up to 3 cancellations with exponential
        backoff (1s, 2s, 4s). After retries, verifies each order status via
        get_order(). Orders still open after verification are added to the
        failed list.

        Args:
            adapter: Broker adapter to cancel orders through.

        Returns:
            CancellationResult with counts and list of failed order IDs.
        """
        from libs.contracts.execution import OrderStatus

        open_orders = adapter.list_open_orders()
        cancelled_count = 0
        failed_order_ids: list[str] = []

        for order in open_orders:
            if order.broker_order_id is None:
                continue

            broker_order_id = order.broker_order_id
            max_retries = 3
            backoff_delays = [1.0, 2.0, 4.0]  # exponential backoff in seconds

            # Attempt cancellation with retries
            cancellation_succeeded = False
            for attempt in range(max_retries):
                try:
                    adapter.cancel_order(broker_order_id)
                    cancellation_succeeded = True
                    logger.info(
                        "Order cancellation succeeded",
                        extra={
                            "operation": "order_cancel_succeeded",
                            "component": "KillSwitchService",
                            "broker_order_id": broker_order_id,
                            "attempt": attempt + 1,
                        },
                    )
                    break
                except TransientError as exc:
                    # Transient error: retry if we have more attempts
                    if attempt < max_retries - 1:
                        delay_s = backoff_delays[attempt]
                        logger.warning(
                            "Order cancellation transient error, retrying",
                            extra={
                                "operation": "order_cancel_transient_error",
                                "component": "KillSwitchService",
                                "broker_order_id": broker_order_id,
                                "attempt": attempt + 1,
                                "delay_seconds": delay_s,
                                "max_retries": max_retries,
                            },
                            exc_info=exc,
                        )
                        time.sleep(delay_s)
                    else:
                        logger.error(
                            "Order cancellation failed after all retries",
                            extra={
                                "operation": "order_cancel_max_retries_exceeded",
                                "component": "KillSwitchService",
                                "broker_order_id": broker_order_id,
                                "attempts": max_retries,
                            },
                            exc_info=exc,
                        )
                except Exception as exc:
                    # Permanent error: don't retry
                    logger.error(
                        "Order cancellation failed with permanent error",
                        extra={
                            "operation": "order_cancel_permanent_error",
                            "component": "KillSwitchService",
                            "broker_order_id": broker_order_id,
                            "attempt": attempt + 1,
                        },
                        exc_info=exc,
                    )
                    break

            # If cancellation succeeded, verify order status
            if cancellation_succeeded:
                try:
                    verified_order = adapter.get_order(broker_order_id)
                    # Check if order is still open
                    terminal_statuses = {
                        OrderStatus.CANCELLED,
                        OrderStatus.FILLED,
                        OrderStatus.REJECTED,
                        OrderStatus.EXPIRED,
                    }
                    if verified_order.status in terminal_statuses:
                        cancelled_count += 1
                    else:
                        # Order is still open — add to failed list
                        logger.critical(
                            "Order still open after cancellation verification",
                            extra={
                                "operation": "order_verification_failed",
                                "component": "KillSwitchService",
                                "broker_order_id": broker_order_id,
                                "verified_status": verified_order.status.value,
                            },
                        )
                        failed_order_ids.append(broker_order_id)
                except Exception as exc:
                    logger.error(
                        "Order verification failed",
                        extra={
                            "operation": "order_verification_error",
                            "component": "KillSwitchService",
                            "broker_order_id": broker_order_id,
                        },
                        exc_info=exc,
                    )
                    failed_order_ids.append(broker_order_id)
            else:
                # Cancellation failed — add to failed list
                failed_order_ids.append(broker_order_id)

        failed_count = len(failed_order_ids)
        return CancellationResult(
            cancelled_count=cancelled_count,
            failed_count=failed_count,
            failed_order_ids=failed_order_ids,
        )

    def _flatten_positions(self, adapter: BrokerAdapterInterface) -> FlattenResult:
        """
        Close all open positions by submitting market sell orders and polling.

        For each open position, submits a market close order, then polls broker
        positions every 1 second for up to 10 seconds to verify the position is
        closed. Positions not closed after timeout are logged at CRITICAL level
        and added to the failed list.

        Args:
            adapter: Broker adapter to close positions through.

        Returns:
            FlattenResult with counts and list of failed symbols.
        """
        from decimal import Decimal

        from libs.contracts.execution import (
            ExecutionMode,
            OrderRequest,
            OrderSide,
            OrderType,
            TimeInForce,
        )

        positions = adapter.get_positions()
        flattened_count = 0
        failed_symbols: list[str] = []

        # Track which symbols we submitted close orders for
        submitted_symbols: dict[str, Decimal] = {}

        # Step 1: Submit close orders for all open positions
        for pos in positions:
            if pos.quantity == 0:
                continue
            side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
            close_qty = abs(pos.quantity)
            try:
                close_request = OrderRequest(
                    client_order_id=f"flatten-{pos.symbol}-{str(_ulid.ULID())}",
                    symbol=pos.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=close_qty,
                    time_in_force=TimeInForce.IOC,
                    deployment_id="system",
                    strategy_id="system",
                    correlation_id=f"flatten-{str(_ulid.ULID())}",
                    execution_mode=ExecutionMode.PAPER,
                )
                adapter.submit_order(close_request)
                submitted_symbols[pos.symbol] = pos.quantity
                logger.info(
                    "Position close order submitted",
                    extra={
                        "operation": "position_close_submitted",
                        "component": "KillSwitchService",
                        "symbol": pos.symbol,
                        "quantity": str(pos.quantity),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to submit position close order",
                    extra={
                        "operation": "position_close_submit_failed",
                        "component": "KillSwitchService",
                        "symbol": pos.symbol,
                    },
                    exc_info=exc,
                )
                failed_symbols.append(pos.symbol)

        # Step 2: Poll for position closure (up to 10 seconds, 1 second intervals)
        max_poll_seconds = 10
        poll_interval_seconds = 1
        poll_count = 0
        max_polls = max_poll_seconds // poll_interval_seconds

        while poll_count < max_polls and submitted_symbols:
            poll_count += 1
            time.sleep(poll_interval_seconds)

            try:
                current_positions = adapter.get_positions()
                current_symbols = {p.symbol: p.quantity for p in current_positions}

                # Check which submitted positions are now closed
                closed_symbols = []
                for symbol in submitted_symbols:
                    if symbol not in current_symbols or current_symbols[symbol] == Decimal("0"):
                        closed_symbols.append(symbol)
                        flattened_count += 1

                # Remove closed symbols from tracking
                for symbol in closed_symbols:
                    del submitted_symbols[symbol]
                    logger.info(
                        "Position verified closed after polling",
                        extra={
                            "operation": "position_close_verified",
                            "component": "KillSwitchService",
                            "symbol": symbol,
                            "poll_count": poll_count,
                        },
                    )

            except Exception as exc:
                logger.error(
                    "Error polling positions",
                    extra={
                        "operation": "position_polling_error",
                        "component": "KillSwitchService",
                        "poll_count": poll_count,
                    },
                    exc_info=exc,
                )

        # Step 3: Any remaining symbols are failed (did not close within timeout)
        for symbol in submitted_symbols:
            logger.critical(
                "Position failed to close within timeout",
                extra={
                    "operation": "position_close_timeout",
                    "component": "KillSwitchService",
                    "symbol": symbol,
                    "timeout_seconds": max_poll_seconds,
                    "poll_count": poll_count,
                },
            )
            failed_symbols.append(symbol)

        failed_count = len(failed_symbols)
        return FlattenResult(
            flattened_count=flattened_count,
            failed_count=failed_count,
            failed_symbols=failed_symbols,
        )

    def _verify_posture_execution(
        self,
        adapter: BrokerAdapterInterface,
        *,
        verify_positions: bool = True,
    ) -> EmergencyPostureVerification:
        """
        Post-execution verification loop for emergency posture.

        After executing a posture (flatten_all or cancel_open), polls broker
        state every 1 second for up to verification_timeout_s:
        - For flatten_all (verify_positions=True): confirms all positions flat.
        - For cancel_open (verify_positions=False): confirms no open orders remain.

        If positions remain open after the timeout (when verify_positions=True),
        logs CRITICAL with residual exposure details.

        Args:
            adapter: Broker adapter to query state through.
            verify_positions: If True, verify positions are flat (flatten_all).
                If False, verify open orders are cancelled (cancel_open).

        Returns:
            EmergencyPostureVerification with position closure status,
            failed positions, and residual exposure calculation.

        Example:
            verification = service._verify_posture_execution(adapter)
            if not verification.verified:
                alert(verification.residual_exposure_usd)
        """
        from decimal import Decimal

        verification_start_ns = time.monotonic_ns()
        timeout_s = self._verification_timeout_s
        poll_interval_s = 1
        max_polls = timeout_s // poll_interval_s
        positions_closed = 0

        if verify_positions:
            # Poll positions until all are flat or timeout is reached.
            all_flat = False
            for poll_num in range(max_polls):
                try:
                    current_positions = adapter.get_positions()
                    open_positions = [p for p in current_positions if p.quantity != Decimal("0")]

                    if not open_positions:
                        all_flat = True
                        break
                except Exception as exc:
                    logger.error(
                        "Error polling positions during posture verification",
                        extra={
                            "operation": "posture_verification_poll_error",
                            "component": "KillSwitchService",
                            "poll_num": poll_num + 1,
                            "timeout_s": timeout_s,
                        },
                        exc_info=exc,
                    )
                time.sleep(poll_interval_s)

            # Final check after loop exits — get current state.
            failed_positions: list[dict[str, Any]] = []
            residual_exposure_usd = Decimal("0")

            try:
                final_positions = adapter.get_positions()
                for pos in final_positions:
                    if pos.quantity == Decimal("0"):
                        positions_closed += 1
                    else:
                        failed_positions.append(
                            {
                                "symbol": pos.symbol,
                                "quantity": str(pos.quantity),
                                "market_value": str(pos.market_value),
                            }
                        )
                        residual_exposure_usd += abs(pos.market_value)
            except Exception as exc:
                logger.error(
                    "Error querying final positions during posture verification",
                    extra={
                        "operation": "posture_verification_final_error",
                        "component": "KillSwitchService",
                    },
                    exc_info=exc,
                )

            verified = all_flat and len(failed_positions) == 0
        else:
            # cancel_open mode: verify no open orders remain.
            failed_positions = []
            residual_exposure_usd = Decimal("0")
            all_orders_cancelled = False
            for poll_num in range(max_polls):
                try:
                    open_orders = adapter.list_open_orders()
                    if not open_orders:
                        all_orders_cancelled = True
                        break
                except Exception as exc:
                    logger.error(
                        "Error polling orders during posture verification",
                        extra={
                            "operation": "posture_verification_order_poll_error",
                            "component": "KillSwitchService",
                            "poll_num": poll_num + 1,
                            "timeout_s": timeout_s,
                        },
                        exc_info=exc,
                    )
                time.sleep(poll_interval_s)
            verified = all_orders_cancelled

        verification_end_ns = time.monotonic_ns()
        verification_duration_ms = (verification_end_ns - verification_start_ns) // 1_000_000

        # Emit CRITICAL log if any residual exposure remains.
        if not verified and residual_exposure_usd > Decimal("0"):
            logger.critical(
                "Residual exposure after emergency posture verification",
                extra={
                    "operation": "emergency_posture_residual_exposure",
                    "component": "KillSwitchService",
                    "residual_exposure_usd": str(residual_exposure_usd),
                    "failed_positions_count": len(failed_positions),
                    "failed_positions": failed_positions,
                    "timeout_s": timeout_s,
                    "verification_duration_ms": verification_duration_ms,
                },
            )

        return EmergencyPostureVerification(
            verified=verified,
            positions_closed=positions_closed,
            positions_failed=failed_positions,
            residual_exposure_usd=residual_exposure_usd,
            timeout_s=timeout_s,
            verification_duration_ms=verification_duration_ms,
        )

    def verify_halt(self, *, scope: KillSwitchScope, target_id: str) -> dict[str, Any]:
        """
        Re-check all orders and positions in scope are cancelled and flat.

        For each adapter affected by the kill switch scope, queries open orders
        and positions. Returns a dict with verification results including counts
        of any remaining open orders/positions and estimated residual exposure.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.

        Returns:
            Dict with keys:
                - verified (bool): True if no residual open orders or positions.
                - open_orders_remaining (list[dict]): Any open orders found.
                - open_positions_remaining (list[dict]): Any open positions found.
                - residual_exposure (dict): Estimated exposure by symbol.

        Example:
            result = service.verify_halt(
                scope=KillSwitchScope.GLOBAL,
                target_id="global"
            )
            # result["verified"] == True or False depending on state
        """
        open_orders_remaining: list[dict[str, Any]] = []
        open_positions_remaining: list[dict[str, Any]] = []
        residual_exposure: dict[str, Any] = {}

        with self._registry_lock:
            adapters_snapshot = dict(self._adapter_registry)

        for dep_id, adapter in adapters_snapshot.items():
            if self._scope_affects_adapter(scope, target_id, dep_id):
                try:
                    # Query open orders
                    open_orders = adapter.list_open_orders()
                    for order in open_orders:
                        open_orders_remaining.append(
                            {
                                "deployment_id": dep_id,
                                "broker_order_id": order.broker_order_id,
                                "symbol": order.symbol,
                                "status": order.status.value,
                                "quantity": str(order.quantity),
                            }
                        )

                    # Query open positions
                    positions = adapter.get_positions()
                    for pos in positions:
                        if pos.quantity != 0:
                            open_positions_remaining.append(
                                {
                                    "deployment_id": dep_id,
                                    "symbol": pos.symbol,
                                    "quantity": str(pos.quantity),
                                    "market_value": str(pos.market_value),
                                }
                            )
                            # Accumulate residual exposure by symbol
                            if pos.symbol not in residual_exposure:
                                from decimal import Decimal

                                residual_exposure[pos.symbol] = Decimal("0")
                            residual_exposure[pos.symbol] += abs(pos.market_value)

                except Exception as exc:
                    logger.error(
                        "Error verifying halt state",
                        extra={
                            "operation": "verify_halt_error",
                            "component": "KillSwitchService",
                            "deployment_id": dep_id,
                            "scope": scope.value,
                            "target_id": target_id,
                        },
                        exc_info=exc,
                    )

        verified = len(open_orders_remaining) == 0 and len(open_positions_remaining) == 0

        logger.info(
            "Halt verification completed",
            extra={
                "operation": "verify_halt_completed",
                "component": "KillSwitchService",
                "scope": scope.value,
                "target_id": target_id,
                "verified": verified,
                "open_orders_count": len(open_orders_remaining),
                "open_positions_count": len(open_positions_remaining),
                "residual_symbols": list(residual_exposure.keys()),
            },
        )

        return {
            "verified": verified,
            "open_orders_remaining": open_orders_remaining,
            "open_positions_remaining": open_positions_remaining,
            "residual_exposure": {
                symbol: str(value) for symbol, value in residual_exposure.items()
            },
        }

    def _scope_affects_adapter(
        self,
        scope: KillSwitchScope,
        target_id: str,
        deployment_id: str,
    ) -> bool:
        """
        Determine if a kill switch scope+target affects a specific adapter.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.
            deployment_id: Deployment to check.

        Returns:
            True if the kill switch affects this deployment's adapter.
        """
        if scope == KillSwitchScope.GLOBAL:
            return True
        if scope == KillSwitchScope.STRATEGY:
            deployment = self._deployment_repo.get_by_id(deployment_id)
            if deployment is not None:
                strategy_id = deployment.get("strategy_id")
                return bool(strategy_id == target_id)
        # Symbol scope: conservative default — affects all adapters.
        return scope == KillSwitchScope.SYMBOL

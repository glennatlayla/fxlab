"""
In-memory mock broker adapter for unit testing.

Responsibilities:
- Implement BrokerAdapterInterface with configurable fill behaviour.
- Support four fill modes: instant, delayed (requires explicit settle call),
  partial, and reject.
- Enforce idempotency: duplicate client_order_id returns existing order.
- Provide introspection helpers for test assertions.

Does NOT:
- Perform any network I/O.
- Simulate market microstructure beyond basic fill modes.
- Contain business logic.

Dependencies:
- libs.contracts.interfaces.broker_adapter: BrokerAdapterInterface
- libs.contracts.execution: All execution schemas
- libs.contracts.errors: NotFoundError

Example:
    adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
    resp = adapter.submit_order(order_request)
    assert resp.status == OrderStatus.FILLED
    assert adapter.get_submitted_orders_count() == 1

    # Reject mode
    adapter = MockBrokerAdapter(fill_mode="reject", reject_reason="Insufficient funds")
    resp = adapter.submit_order(order_request)
    assert resp.status == OrderStatus.REJECTED
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    ConnectionStatus,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    PositionSnapshot,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

logger = structlog.get_logger(__name__)

FillMode = Literal["instant", "delayed", "partial", "reject"]


class MockBrokerAdapter(BrokerAdapterInterface):
    """
    In-memory broker adapter for unit testing.

    Responsibilities:
    - Simulate order submission, fill, cancel, and query operations.
    - Enforce idempotency on client_order_id.
    - Track positions and account state in memory.
    - Provide introspection helpers for test assertions.

    Does NOT:
    - Perform network I/O.
    - Simulate realistic latency or market microstructure.

    Dependencies:
    - BrokerAdapterInterface (implements)
    - All execution schemas from libs.contracts.execution

    Raises:
    - NotFoundError: When broker_order_id is unknown.

    Example:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("100"))
        resp = adapter.submit_order(request)
        assert resp.status == OrderStatus.FILLED
    """

    def __init__(
        self,
        fill_mode: FillMode = "instant",
        fill_price: Decimal = Decimal("100.00"),
        partial_fill_ratio: Decimal = Decimal("0.5"),
        reject_reason: str = "Order rejected by mock broker",
        market_open: bool = True,
        account_equity: Decimal = Decimal("100000.00"),
        account_cash: Decimal = Decimal("100000.00"),
        timeout_config: BrokerTimeoutConfig | None = None,
    ) -> None:
        """
        Initialize mock broker adapter.

        Args:
            fill_mode: How orders are filled:
                - "instant": Filled immediately at fill_price.
                - "delayed": Stays SUBMITTED until settle_order() called.
                - "partial": Partially filled at partial_fill_ratio.
                - "reject": Rejected immediately with reject_reason.
            fill_price: Price used for instant/partial fills.
            partial_fill_ratio: Fraction of quantity to fill in partial mode (0-1).
            reject_reason: Human-readable rejection reason for reject mode.
            market_open: Whether is_market_open() returns True.
            account_equity: Starting account equity.
            account_cash: Starting account cash.
            timeout_config: Timeout configuration. Defaults to BrokerTimeoutConfig().
        """
        self._fill_mode = fill_mode
        self._fill_price = fill_price
        self._partial_fill_ratio = partial_fill_ratio
        self._reject_reason = reject_reason
        self._market_open = market_open
        self._timeout_config = timeout_config or BrokerTimeoutConfig()

        # Internal state stores
        self._orders: dict[str, OrderResponse] = {}  # broker_order_id → response
        self._client_id_map: dict[str, str] = {}  # client_order_id → broker_order_id
        self._fills: dict[str, list[OrderFillEvent]] = {}  # broker_order_id → fills
        self._positions: dict[str, PositionSnapshot] = {}  # symbol → position
        self._account_equity = account_equity
        self._account_cash = account_cash
        self._error_count = 0
        self._started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Lifecycle methods (required by BrokerAdapterInterface)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Establish connection to the broker (mock implementation).

        This is a no-op for the mock adapter. In a real adapter, this
        method would authenticate, open sessions, and verify connectivity.
        Since the mock operates entirely in-memory, no connection setup
        is required.

        Idempotent — calling multiple times is safe and does nothing.

        Example:
            adapter.connect()
            # Mock adapter is now ready (was always ready)
        """
        logger.debug(
            "mock_broker_adapter.connect",
            component="MockBrokerAdapter",
            operation="connect",
            detail="No-op for in-memory mock",
        )

    def disconnect(self) -> None:
        """
        Gracefully close the broker connection (mock implementation).

        This is a no-op for the mock adapter. In a real adapter, this
        method would close HTTP sessions, release resources, and clean up
        connections. Since the mock operates entirely in-memory, no
        cleanup is required beyond what garbage collection provides.

        Idempotent — calling multiple times is safe and does nothing.

        Must NOT raise exceptions.

        Example:
            adapter.disconnect()
            # Mock adapter resources released (there are none)
        """
        logger.debug(
            "mock_broker_adapter.disconnect",
            component="MockBrokerAdapter",
            operation="disconnect",
            detail="No-op for in-memory mock",
        )

    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Return the timeout configuration for this adapter.

        For the mock adapter, this returns the BrokerTimeoutConfig
        that was provided at initialization, or a default configuration.
        Since the mock performs no actual network I/O, these timeouts
        are informational and not enforced.

        Returns:
            BrokerTimeoutConfig with the timeouts this adapter uses.

        Example:
            config = adapter.get_timeout_config()
            # config.order_timeout_s == 30.0 (or custom value if provided)
        """
        return self._timeout_config

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit an order. Idempotent on client_order_id.

        Args:
            request: Normalized order request.

        Returns:
            OrderResponse with status based on fill_mode.
        """
        # Idempotency check: return existing order if client_order_id seen
        if request.client_order_id in self._client_id_map:
            existing_broker_id = self._client_id_map[request.client_order_id]
            return self._orders[existing_broker_id]

        broker_order_id = f"MOCK-{uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        if self._fill_mode == "reject":
            response = OrderResponse(
                client_order_id=request.client_order_id,
                broker_order_id=broker_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                filled_quantity=Decimal("0"),
                average_fill_price=None,
                status=OrderStatus.REJECTED,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                submitted_at=now,
                rejected_reason=self._reject_reason,
                correlation_id=request.correlation_id,
                execution_mode=request.execution_mode,
            )
        elif self._fill_mode == "instant":
            response = OrderResponse(
                client_order_id=request.client_order_id,
                broker_order_id=broker_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                filled_quantity=request.quantity,
                average_fill_price=self._fill_price,
                status=OrderStatus.FILLED,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                submitted_at=now,
                filled_at=now,
                correlation_id=request.correlation_id,
                execution_mode=request.execution_mode,
            )
            self._record_fill(broker_order_id, request, request.quantity, now)
            self._update_position(request, request.quantity)
        elif self._fill_mode == "partial":
            fill_qty = (request.quantity * self._partial_fill_ratio).quantize(Decimal("0.01"))
            response = OrderResponse(
                client_order_id=request.client_order_id,
                broker_order_id=broker_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                filled_quantity=fill_qty,
                average_fill_price=self._fill_price,
                status=OrderStatus.PARTIAL_FILL,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                submitted_at=now,
                correlation_id=request.correlation_id,
                execution_mode=request.execution_mode,
            )
            self._record_fill(broker_order_id, request, fill_qty, now)
            self._update_position(request, fill_qty)
        else:
            # delayed: order stays SUBMITTED until settle_order()
            response = OrderResponse(
                client_order_id=request.client_order_id,
                broker_order_id=broker_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                filled_quantity=Decimal("0"),
                average_fill_price=None,
                status=OrderStatus.SUBMITTED,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                submitted_at=now,
                correlation_id=request.correlation_id,
                execution_mode=request.execution_mode,
            )

        self._orders[broker_order_id] = response
        self._client_id_map[request.client_order_id] = broker_order_id
        if broker_order_id not in self._fills:
            self._fills[broker_order_id] = []
        return response

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Cancel an open order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with CANCELLED status.

        Raises:
            NotFoundError: If broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Order {broker_order_id} not found")

        existing = self._orders[broker_order_id]
        now = datetime.now(timezone.utc)

        # Terminal orders cannot be cancelled
        if existing.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            return existing

        cancelled = OrderResponse(
            client_order_id=existing.client_order_id,
            broker_order_id=existing.broker_order_id,
            symbol=existing.symbol,
            side=existing.side,
            order_type=existing.order_type,
            quantity=existing.quantity,
            filled_quantity=existing.filled_quantity,
            average_fill_price=existing.average_fill_price,
            status=OrderStatus.CANCELLED,
            limit_price=existing.limit_price,
            stop_price=existing.stop_price,
            time_in_force=existing.time_in_force,
            submitted_at=existing.submitted_at,
            cancelled_at=now,
            correlation_id=existing.correlation_id,
            execution_mode=existing.execution_mode,
        )
        self._orders[broker_order_id] = cancelled
        return cancelled

    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query order state.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            Current OrderResponse.

        Raises:
            NotFoundError: If broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Order {broker_order_id} not found")
        return self._orders[broker_order_id]

    def list_open_orders(self) -> list[OrderResponse]:
        """Return all non-terminal orders."""
        terminal = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
        return [o for o in self._orders.values() if o.status not in terminal]

    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get fills for an order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            List of fill events.

        Raises:
            NotFoundError: If broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Order {broker_order_id} not found")
        return list(self._fills.get(broker_order_id, []))

    def get_positions(self) -> list[PositionSnapshot]:
        """Return all positions with non-zero quantity."""
        return [p for p in self._positions.values() if p.quantity != Decimal("0")]

    def get_account(self) -> AccountSnapshot:
        """Return current account snapshot."""
        now = datetime.now(timezone.utc)
        positions = self.get_positions()
        portfolio_value = sum((p.market_value for p in positions), Decimal("0"))
        daily_pnl = sum((p.unrealized_pnl + p.realized_pnl for p in positions), Decimal("0"))
        open_orders = self.list_open_orders()
        return AccountSnapshot(
            account_id="MOCK-ACCOUNT",
            equity=self._account_equity + daily_pnl,
            cash=self._account_cash,
            buying_power=self._account_cash * Decimal("2"),
            portfolio_value=portfolio_value,
            daily_pnl=daily_pnl,
            pending_orders_count=len(open_orders),
            positions_count=len(positions),
            updated_at=now,
        )

    def get_diagnostics(self) -> AdapterDiagnostics:
        """Return adapter health diagnostics."""
        now = datetime.now(timezone.utc)
        uptime = int((now - self._started_at).total_seconds())
        filled_count = sum(
            1
            for o in self._orders.values()
            if o.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)
        )
        return AdapterDiagnostics(
            broker_name="mock",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=1,
            error_count_1h=self._error_count,
            last_heartbeat=now,
            market_open=self._market_open,
            orders_submitted_today=len(self._orders),
            orders_filled_today=filled_count,
            uptime_seconds=uptime,
        )

    def is_market_open(self) -> bool:
        """Return configured market-open state."""
        return self._market_open

    # ------------------------------------------------------------------
    # Mock-only: manual settlement for delayed mode
    # ------------------------------------------------------------------

    def settle_order(
        self, broker_order_id: str, fill_price: Decimal | None = None
    ) -> OrderResponse:
        """
        Manually fill a delayed order (test helper, not part of interface).

        Args:
            broker_order_id: Order to settle.
            fill_price: Override fill price (defaults to self._fill_price).

        Returns:
            Updated OrderResponse with FILLED status.

        Raises:
            NotFoundError: If broker_order_id is unknown.
            ValueError: If order is not in SUBMITTED status.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Order {broker_order_id} not found")

        existing = self._orders[broker_order_id]
        if existing.status != OrderStatus.SUBMITTED:
            raise ValueError(f"Cannot settle order in {existing.status} status; expected SUBMITTED")

        price = fill_price or self._fill_price
        now = datetime.now(timezone.utc)

        filled = OrderResponse(
            client_order_id=existing.client_order_id,
            broker_order_id=existing.broker_order_id,
            symbol=existing.symbol,
            side=existing.side,
            order_type=existing.order_type,
            quantity=existing.quantity,
            filled_quantity=existing.quantity,
            average_fill_price=price,
            status=OrderStatus.FILLED,
            limit_price=existing.limit_price,
            stop_price=existing.stop_price,
            time_in_force=existing.time_in_force,
            submitted_at=existing.submitted_at,
            filled_at=now,
            correlation_id=existing.correlation_id,
            execution_mode=existing.execution_mode,
        )
        self._orders[broker_order_id] = filled

        # Build a synthetic OrderRequest for _record_fill / _update_position
        # We need the original request data; reconstruct from response fields
        self._fills.setdefault(broker_order_id, []).append(
            OrderFillEvent(
                fill_id=f"FILL-{uuid4().hex[:8].upper()}",
                order_id=existing.client_order_id,
                broker_order_id=broker_order_id,
                symbol=existing.symbol,
                side=existing.side,
                price=price,
                quantity=existing.quantity,
                commission=Decimal("0"),
                filled_at=now,
                broker_execution_id=f"EXEC-{uuid4().hex[:8].upper()}",
                correlation_id=existing.correlation_id,
            )
        )
        self._update_position_from_response(existing, existing.quantity, price)
        return filled

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def get_submitted_orders_count(self) -> int:
        """Return total number of orders submitted (all statuses)."""
        return len(self._orders)

    def get_all_orders(self) -> list[OrderResponse]:
        """Return all orders (all statuses)."""
        return list(self._orders.values())

    def get_all_fills(self) -> list[OrderFillEvent]:
        """Return all fills across all orders."""
        result: list[OrderFillEvent] = []
        for fills in self._fills.values():
            result.extend(fills)
        return result

    def clear(self) -> None:
        """Reset all internal state."""
        self._orders.clear()
        self._client_id_map.clear()
        self._fills.clear()
        self._positions.clear()
        self._error_count = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_fill(
        self,
        broker_order_id: str,
        request: OrderRequest,
        quantity: Decimal,
        filled_at: datetime,
    ) -> None:
        """Record a fill event for an order."""
        fill = OrderFillEvent(
            fill_id=f"FILL-{uuid4().hex[:8].upper()}",
            order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side,
            price=self._fill_price,
            quantity=quantity,
            commission=Decimal("0"),
            filled_at=filled_at,
            broker_execution_id=f"EXEC-{uuid4().hex[:8].upper()}",
            correlation_id=request.correlation_id,
        )
        self._fills.setdefault(broker_order_id, []).append(fill)

    def _update_position(self, request: OrderRequest, filled_qty: Decimal) -> None:
        """Update position state after a fill."""
        signed_qty = filled_qty if request.side == OrderSide.BUY else -filled_qty
        now = datetime.now(timezone.utc)

        if request.symbol in self._positions:
            existing = self._positions[request.symbol]
            new_qty = existing.quantity + signed_qty
            if new_qty == Decimal("0"):
                # Position fully closed
                self._positions[request.symbol] = PositionSnapshot(
                    symbol=request.symbol,
                    quantity=Decimal("0"),
                    average_entry_price=Decimal("0"),
                    market_price=self._fill_price,
                    market_value=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    realized_pnl=existing.realized_pnl
                    + (self._fill_price - existing.average_entry_price) * filled_qty,
                    cost_basis=Decimal("0"),
                    updated_at=now,
                )
            else:
                # Position still open — recalculate average entry
                if (existing.quantity > 0 and signed_qty > 0) or (
                    existing.quantity < 0 and signed_qty < 0
                ):
                    # Adding to position: weighted average
                    total_cost = existing.average_entry_price * abs(
                        existing.quantity
                    ) + self._fill_price * abs(signed_qty)
                    avg_price = total_cost / abs(new_qty)
                else:
                    avg_price = existing.average_entry_price

                market_value = new_qty * self._fill_price
                cost_basis = abs(new_qty) * avg_price
                unrealized = (self._fill_price - avg_price) * new_qty
                self._positions[request.symbol] = PositionSnapshot(
                    symbol=request.symbol,
                    quantity=new_qty,
                    average_entry_price=avg_price,
                    market_price=self._fill_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized,
                    realized_pnl=existing.realized_pnl,
                    cost_basis=cost_basis,
                    updated_at=now,
                )
        else:
            # New position
            self._positions[request.symbol] = PositionSnapshot(
                symbol=request.symbol,
                quantity=signed_qty,
                average_entry_price=self._fill_price,
                market_price=self._fill_price,
                market_value=signed_qty * self._fill_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                cost_basis=abs(signed_qty) * self._fill_price,
                updated_at=now,
            )

    def _update_position_from_response(
        self, response: OrderResponse, quantity: Decimal, price: Decimal
    ) -> None:
        """Update position from an OrderResponse (used by settle_order)."""
        signed_qty = quantity if response.side == OrderSide.BUY else -quantity
        now = datetime.now(timezone.utc)

        if response.symbol not in self._positions:
            self._positions[response.symbol] = PositionSnapshot(
                symbol=response.symbol,
                quantity=signed_qty,
                average_entry_price=price,
                market_price=price,
                market_value=signed_qty * price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                cost_basis=abs(signed_qty) * price,
                updated_at=now,
            )
        else:
            existing = self._positions[response.symbol]
            new_qty = existing.quantity + signed_qty
            avg_price = existing.average_entry_price if new_qty != Decimal("0") else Decimal("0")
            market_value = new_qty * price
            unrealized = (price - avg_price) * new_qty if new_qty != Decimal("0") else Decimal("0")
            self._positions[response.symbol] = PositionSnapshot(
                symbol=response.symbol,
                quantity=new_qty,
                average_entry_price=avg_price,
                market_price=price,
                market_value=market_value,
                unrealized_pnl=unrealized,
                realized_pnl=existing.realized_pnl,
                cost_basis=abs(new_qty) * avg_price,
                updated_at=now,
            )

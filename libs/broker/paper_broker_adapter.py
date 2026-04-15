"""
Paper broker adapter — simulated broker with realistic order lifecycle.

Responsibilities:
- Implement BrokerAdapterInterface for paper trading mode.
- Simulate realistic order lifecycle: submit → ack → fill/partial/reject.
- Support market, limit, and stop order types with proper fill logic.
- Track positions with weighted average cost basis, margin, and fees.
- Provide reconciliation-compatible state recovery (get_all_order_states).
- Support configurable commission, partial fill ratio, and market open state.

Does NOT:
- Execute any real broker operations.
- Persist state to a database (in-memory only; persistence is service concern).
- Simulate network latency or async callbacks (uses synchronous tick model).

Dependencies:
- libs.contracts.interfaces.broker_adapter: BrokerAdapterInterface
- libs.contracts.execution: All execution schemas
- libs.contracts.errors: NotFoundError

Error conditions:
- NotFoundError: broker_order_id is unknown.

Example:
    adapter = PaperBrokerAdapter(
        market_prices={"AAPL": Decimal("175.50")},
        initial_equity=Decimal("1000000"),
        commission_per_order=Decimal("1.00"),
    )
    resp = adapter.submit_order(order_request)
    # resp.status == OrderStatus.SUBMITTED
    filled = adapter.process_pending_orders()
    # filled[0].status == OrderStatus.FILLED
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
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
    OrderType,
    PositionSnapshot,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# Terminal statuses that cannot be further processed
_TERMINAL_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)


class PaperBrokerAdapter(BrokerAdapterInterface):
    """
    Simulated broker adapter for paper trading.

    Responsibilities:
    - Accept order submissions and acknowledge with SUBMITTED status.
    - Process pending orders on explicit tick (process_pending_orders).
    - Fill market orders at current market price.
    - Fill limit/stop orders when price conditions are met.
    - Support configurable partial fills (partial_fill_ratio < 1.0).
    - Track positions with weighted average cost basis and realized P&L.
    - Deduct configurable commission per order.
    - Provide reconciliation via get_all_order_states().

    Does NOT:
    - Fill orders instantly on submit (unlike shadow mode).
    - Simulate async callbacks or real-time market data streaming.
    - Contain business logic or risk checks.

    Dependencies:
    - BrokerAdapterInterface (implements)
    - All execution schemas from libs.contracts.execution

    Raises:
    - NotFoundError: When broker_order_id is unknown.

    Example:
        adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
        )
        resp = adapter.submit_order(request)
        filled = adapter.process_pending_orders()
    """

    def __init__(
        self,
        *,
        market_prices: dict[str, Decimal],
        initial_equity: Decimal,
        commission_per_order: Decimal = Decimal("0"),
        partial_fill_ratio: Decimal = Decimal("1.0"),
        market_open: bool = True,
        timeout_config: BrokerTimeoutConfig | None = None,
    ) -> None:
        """
        Initialise the paper broker adapter.

        Args:
            market_prices: Initial market prices keyed by symbol.
            initial_equity: Starting hypothetical account equity.
            commission_per_order: Fixed commission per fill event.
            partial_fill_ratio: Fraction of remaining quantity to fill per tick
                (1.0 = full fill, 0.5 = fill half of remaining each tick).
            market_open: Whether is_market_open() returns True.
            timeout_config: Broker timeout configuration. If None, defaults are used.
        """
        self._market_prices = dict(market_prices)
        self._initial_equity = initial_equity
        self._commission = commission_per_order
        self._partial_fill_ratio = partial_fill_ratio
        self._market_open = market_open
        self._timeout_config = timeout_config or BrokerTimeoutConfig()

        # Order state
        self._orders: dict[str, OrderResponse] = {}  # broker_order_id → response
        self._pending_requests: dict[str, OrderRequest] = {}  # broker_order_id → original request
        self._client_id_map: dict[str, str] = {}  # client_order_id → broker_order_id
        self._fills: dict[str, list[OrderFillEvent]] = {}  # broker_order_id → fills

        # Position and account state
        self._positions: dict[str, _PositionState] = {}  # symbol → mutable position
        self._cash = initial_equity
        self._total_commission = Decimal("0")

        # Diagnostics
        self._started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Lifecycle methods (BrokerAdapterInterface)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Establish connection to the broker.

        For the paper adapter, this is a no-op as there is no real broker
        connection. This method is present to satisfy the BrokerAdapterInterface
        contract and maintain compatibility with real adapters.

        Args:
            None

        Returns:
            None

        Raises:
            None

        Example:
            adapter = PaperBrokerAdapter(market_prices={...}, initial_equity=...)
            adapter.connect()
            # Adapter is ready for order operations
        """
        logger = structlog.get_logger(__name__)
        logger.debug(
            "paper_broker.connect",
            component="PaperBrokerAdapter",
            detail="No-op connection for paper adapter",
        )

    def disconnect(self) -> None:
        """
        Gracefully close the broker connection.

        For the paper adapter, this is a no-op as there is no real broker
        connection. This method is present to satisfy the BrokerAdapterInterface
        contract and maintain compatibility with real adapters.

        Args:
            None

        Returns:
            None

        Raises:
            None

        Example:
            adapter.disconnect()
            # Paper adapter cleanup complete (no-op)
        """
        logger = structlog.get_logger(__name__)
        logger.debug(
            "paper_broker.disconnect",
            component="PaperBrokerAdapter",
            detail="No-op disconnection for paper adapter",
        )

    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Return the timeout configuration for this adapter.

        Returns the BrokerTimeoutConfig that was set during initialization.
        For the paper adapter, timeouts are not enforced on any operations
        since there are no real network calls, but this method provides
        the configuration for consistency with the BrokerAdapterInterface contract.

        Args:
            None

        Returns:
            BrokerTimeoutConfig: The timeout configuration for this adapter.

        Raises:
            None

        Example:
            adapter = PaperBrokerAdapter(
                market_prices={"AAPL": Decimal("175.50")},
                initial_equity=Decimal("1000000"),
                timeout_config=BrokerTimeoutConfig(order_timeout_s=20.0),
            )
            config = adapter.get_timeout_config()
            # config.order_timeout_s == 20.0
        """
        return self._timeout_config

    # ------------------------------------------------------------------
    # BrokerAdapterInterface implementation
    # ------------------------------------------------------------------

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit an order. Returns SUBMITTED status (not instant fill).

        Idempotent: if client_order_id has been seen before, returns the
        existing order without re-submitting.

        Args:
            request: Normalized order request.

        Returns:
            OrderResponse with SUBMITTED status.
        """
        # Idempotency check
        if request.client_order_id in self._client_id_map:
            existing_id = self._client_id_map[request.client_order_id]
            return self._orders[existing_id]

        broker_order_id = f"PAPER-{uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

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
        self._pending_requests[broker_order_id] = request
        self._client_id_map[request.client_order_id] = broker_order_id
        self._fills[broker_order_id] = []
        return response

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Cancel an open order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with CANCELLED status (or current terminal status).

        Raises:
            NotFoundError: If broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Order {broker_order_id} not found")

        existing = self._orders[broker_order_id]
        if existing.status in _TERMINAL_STATUSES:
            return existing

        now = datetime.now(timezone.utc)
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
        self._pending_requests.pop(broker_order_id, None)
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
        return [o for o in self._orders.values() if o.status not in _TERMINAL_STATUSES]

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
        now = datetime.now(timezone.utc)
        result: list[PositionSnapshot] = []
        for symbol, pos in self._positions.items():
            if pos.quantity == Decimal("0"):
                continue
            market_price = self._market_prices.get(symbol, pos.avg_entry_price)
            market_value = pos.quantity * market_price
            unrealized = (market_price - pos.avg_entry_price) * pos.quantity
            cost_basis = abs(pos.quantity) * pos.avg_entry_price
            result.append(
                PositionSnapshot(
                    symbol=symbol,
                    quantity=pos.quantity,
                    average_entry_price=pos.avg_entry_price,
                    market_price=market_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized,
                    realized_pnl=pos.realized_pnl,
                    cost_basis=cost_basis,
                    updated_at=now,
                )
            )
        return result

    def get_account(self) -> AccountSnapshot:
        """Return current account snapshot."""
        now = datetime.now(timezone.utc)
        positions = self.get_positions()
        portfolio_value = sum((p.market_value for p in positions), Decimal("0"))
        unrealized_pnl = sum((p.unrealized_pnl for p in positions), Decimal("0"))
        equity = self._cash + portfolio_value
        open_orders = self.list_open_orders()
        return AccountSnapshot(
            account_id="PAPER-ACCOUNT",
            equity=equity,
            cash=self._cash,
            buying_power=self._cash * Decimal("2"),
            portfolio_value=portfolio_value,
            daily_pnl=unrealized_pnl,
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
            broker_name="paper",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=0,
            error_count_1h=0,
            last_heartbeat=now,
            market_open=self._market_open,
            orders_submitted_today=len(self._orders),
            orders_filled_today=filled_count,
            uptime_seconds=uptime,
        )

    def is_market_open(self) -> bool:
        """Return configured market-open state."""
        return self._market_open

    @property
    def is_paper_adapter(self) -> bool:
        """
        Indicate this is a paper (simulated) trading adapter.

        Returns:
            True, indicating this adapter does not execute real orders.

        Safety use case:
            LiveExecutionService uses this to prevent accidental routing of live
            deployments to paper adapters.
        """
        return True

    # ------------------------------------------------------------------
    # Paper-specific: order processing tick
    # ------------------------------------------------------------------

    def process_pending_orders(self) -> list[OrderResponse]:
        """
        Process all pending orders against current market prices.

        For each pending order, check whether fill conditions are met:
        - MARKET: always fills at current market price.
        - LIMIT BUY: fills when market price <= limit price.
        - LIMIT SELL: fills when market price >= limit price.
        - STOP BUY: fills when market price >= stop price.
        - STOP SELL: fills when market price <= stop price.

        Partial fills apply when partial_fill_ratio < 1.0.

        Returns:
            List of OrderResponse for orders that had fills this tick.
        """
        filled_this_tick: list[OrderResponse] = []
        # Snapshot pending order IDs to avoid mutation during iteration
        pending_ids = [
            bid
            for bid, order in self._orders.items()
            if order.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL)
        ]

        for broker_order_id in pending_ids:
            order = self._orders[broker_order_id]
            request = self._pending_requests.get(broker_order_id)
            if request is None:
                continue

            market_price = self._market_prices.get(order.symbol)
            if market_price is None:
                continue

            if not self._should_fill(order, market_price):
                continue

            # Determine fill price
            fill_price = self._determine_fill_price(order, market_price)

            # Determine fill quantity
            remaining = order.quantity - order.filled_quantity
            fill_qty = (remaining * self._partial_fill_ratio).quantize(Decimal("1"))
            if fill_qty <= Decimal("0"):
                fill_qty = remaining  # Fill at least the remainder

            new_filled_qty = order.filled_quantity + fill_qty
            is_complete = new_filled_qty >= order.quantity

            # Calculate volume-weighted average fill price
            if order.average_fill_price is not None and order.filled_quantity > Decimal("0"):
                total_cost = (
                    order.average_fill_price * order.filled_quantity + fill_price * fill_qty
                )
                avg_price = total_cost / new_filled_qty
            else:
                avg_price = fill_price

            now = datetime.now(timezone.utc)
            new_status = OrderStatus.FILLED if is_complete else OrderStatus.PARTIAL_FILL

            updated = OrderResponse(
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                filled_quantity=new_filled_qty,
                average_fill_price=avg_price,
                status=new_status,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                time_in_force=order.time_in_force,
                submitted_at=order.submitted_at,
                filled_at=now if is_complete else None,
                correlation_id=order.correlation_id,
                execution_mode=order.execution_mode,
            )
            self._orders[broker_order_id] = updated

            # Record fill event
            fill_event = OrderFillEvent(
                fill_id=f"FILL-{uuid4().hex[:8].upper()}",
                order_id=order.client_order_id,
                broker_order_id=broker_order_id,
                symbol=order.symbol,
                side=order.side,
                price=fill_price,
                quantity=fill_qty,
                commission=self._commission,
                filled_at=now,
                broker_execution_id=f"EXEC-{uuid4().hex[:8].upper()}",
                correlation_id=order.correlation_id,
            )
            self._fills.setdefault(broker_order_id, []).append(fill_event)

            # Update position
            self._update_position(order.symbol, order.side, fill_qty, fill_price)

            # Update cash (buy reduces cash, sell increases cash)
            if order.side == OrderSide.BUY:
                self._cash -= fill_price * fill_qty + self._commission
            else:
                self._cash += fill_price * fill_qty - self._commission
            self._total_commission += self._commission

            # Remove from pending if fully filled
            if is_complete:
                self._pending_requests.pop(broker_order_id, None)

            filled_this_tick.append(updated)

        return filled_this_tick

    # ------------------------------------------------------------------
    # Paper-specific: market price updates
    # ------------------------------------------------------------------

    def update_market_price(self, symbol: str, price: Decimal) -> None:
        """
        Update the market price for a symbol.

        Args:
            symbol: Instrument ticker.
            price: Current market price.
        """
        self._market_prices[symbol] = price

    # ------------------------------------------------------------------
    # Reconciliation support
    # ------------------------------------------------------------------

    def get_all_order_states(self) -> list[OrderResponse]:
        """
        Return all order states for reconciliation recovery.

        Returns:
            List of all OrderResponse objects (all statuses).
        """
        return list(self._orders.values())

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_submitted_orders_count(self) -> int:
        """Return total number of orders submitted (all statuses)."""
        return len(self._orders)

    def clear(self) -> None:
        """Reset all internal state."""
        self._orders.clear()
        self._pending_requests.clear()
        self._client_id_map.clear()
        self._fills.clear()
        self._positions.clear()
        self._cash = self._initial_equity
        self._total_commission = Decimal("0")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _should_fill(self, order: OrderResponse, market_price: Decimal) -> bool:
        """
        Check whether an order's fill conditions are met.

        Args:
            order: The pending order.
            market_price: Current market price for the symbol.

        Returns:
            True if the order should be filled this tick.
        """
        if order.order_type == OrderType.MARKET:
            return True

        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                # Limit buy: fill when market <= limit
                return market_price <= (order.limit_price or Decimal("0"))
            else:
                # Limit sell: fill when market >= limit
                return market_price >= (order.limit_price or Decimal("inf"))

        if order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY:
                # Stop buy: fill when market >= stop
                return market_price >= (order.stop_price or Decimal("inf"))
            else:
                # Stop sell: fill when market <= stop
                return market_price <= (order.stop_price or Decimal("0"))

        return False

    def _determine_fill_price(self, order: OrderResponse, market_price: Decimal) -> Decimal:
        """
        Determine the fill price for an order.

        Market orders fill at market price.
        Limit/stop orders fill at market price (simulating slippage-free execution).

        Args:
            order: The order being filled.
            market_price: Current market price.

        Returns:
            Fill price.
        """
        # All paper orders fill at current market price
        # This simulates realistic execution where you get the market
        # price at the time of fill, not the limit/stop price
        return market_price

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        """
        Update position state after a fill.

        Args:
            symbol: Instrument ticker.
            side: Fill direction.
            quantity: Filled quantity.
            price: Fill price.
        """
        signed_qty = quantity if side == OrderSide.BUY else -quantity

        if symbol not in self._positions:
            self._positions[symbol] = _PositionState(
                quantity=signed_qty,
                avg_entry_price=price,
                realized_pnl=Decimal("0"),
            )
            return

        pos = self._positions[symbol]
        new_qty = pos.quantity + signed_qty

        if new_qty == Decimal("0"):
            # Position fully closed — realize P&L
            pnl = (price - pos.avg_entry_price) * abs(signed_qty)
            if pos.quantity < Decimal("0"):
                # Closing a short: P&L is reversed
                pnl = (pos.avg_entry_price - price) * abs(signed_qty)
            pos.realized_pnl += pnl
            pos.quantity = Decimal("0")
            pos.avg_entry_price = Decimal("0")
        elif (pos.quantity > 0 and signed_qty > 0) or (pos.quantity < 0 and signed_qty < 0):
            # Adding to existing position — weighted average
            total_cost = pos.avg_entry_price * abs(pos.quantity) + price * abs(signed_qty)
            pos.avg_entry_price = total_cost / abs(new_qty)
            pos.quantity = new_qty
        else:
            # Reducing position (partial close)
            closed_qty = min(abs(signed_qty), abs(pos.quantity))
            if pos.quantity > 0:
                pnl = (price - pos.avg_entry_price) * closed_qty
            else:
                pnl = (pos.avg_entry_price - price) * closed_qty
            pos.realized_pnl += pnl
            pos.quantity = new_qty
            # avg_entry_price stays the same for the remaining position


class _PositionState:
    """
    Mutable internal position state.

    Used internally by PaperBrokerAdapter to track position changes.
    Not exposed in the public API — converted to frozen PositionSnapshot
    on query.
    """

    __slots__ = ("quantity", "avg_entry_price", "realized_pnl")

    def __init__(
        self,
        *,
        quantity: Decimal,
        avg_entry_price: Decimal,
        realized_pnl: Decimal,
    ) -> None:
        self.quantity = quantity
        self.avg_entry_price = avg_entry_price
        self.realized_pnl = realized_pnl

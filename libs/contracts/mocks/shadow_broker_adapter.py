"""
Shadow broker adapter — logs decisions without real execution.

Responsibilities:
- Implement BrokerAdapterInterface for shadow-mode deployments.
- Always "fill" orders instantly at a configurable market price.
- Record a full decision timeline for every order (submit, fill, cancel).
- Track hypothetical positions and P&L from shadow fills.
- Produce AdapterDiagnostics with shadow-specific metrics.
- Enforce idempotency via client_order_id deduplication.

Does NOT:
- Execute any real broker orders.
- Communicate with external APIs.
- Perform risk checks (execution service responsibility).

Dependencies:
- libs.contracts.interfaces.broker_adapter: BrokerAdapterInterface
- libs.contracts.execution: OrderRequest, OrderResponse, OrderFillEvent,
  PositionSnapshot, AccountSnapshot, AdapterDiagnostics, enums

Error conditions:
- NotFoundError: broker_order_id is unknown (cancel, get_order, get_fills).

Example:
    adapter = ShadowBrokerAdapter(market_prices={"AAPL": Decimal("175.50")})
    response = adapter.submit_order(order_request)
    # response.status == OrderStatus.FILLED
    # response.average_fill_price == Decimal("175.50")
    decisions = adapter.get_decision_timeline()
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    ConnectionStatus,
    ExecutionMode,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    PositionSnapshot,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig


class ShadowBrokerAdapter(BrokerAdapterInterface):
    """
    Shadow-mode adapter that logs what it *would* have done.

    Responsibilities:
    - Accept order submissions and instantly fill them at market price.
    - Maintain a hypothetical position book and P&L tracker.
    - Record every decision in an append-only timeline.
    - Support the same idempotency contract as production adapters.

    Does NOT:
    - Send orders to a real broker.
    - Communicate over the network.
    - Enforce risk limits (service layer responsibility).

    Dependencies:
        market_prices: Dict mapping symbol → current market price.
                      Updated externally by the feed ingestion layer.

    Example:
        adapter = ShadowBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")}
        )
        resp = adapter.submit_order(request)
        positions = adapter.get_positions()
    """

    def __init__(
        self,
        *,
        market_prices: dict[str, Decimal] | None = None,
        initial_equity: Decimal = Decimal("1000000"),
        timeout_config: BrokerTimeoutConfig | None = None,
    ) -> None:
        """
        Initialise with optional market prices, starting equity, and timeout config.

        Args:
            market_prices: Dict mapping symbol → current market price.
                          Can be updated via update_market_price().
            initial_equity: Starting hypothetical equity for P&L tracking.
            timeout_config: Broker timeout configuration (optional).
        """
        self._market_prices: dict[str, Decimal] = dict(market_prices or {})
        self._initial_equity = initial_equity
        self._timeout_config = timeout_config or BrokerTimeoutConfig()

        # Order tracking
        self._orders: dict[str, OrderResponse] = {}  # keyed by broker_order_id
        self._client_id_map: dict[str, str] = {}  # client_order_id → broker_order_id
        self._fills: dict[str, list[OrderFillEvent]] = {}  # broker_order_id → fills
        self._order_counter = 0

        # Position tracking: symbol → (quantity, cost_basis, realized_pnl)
        self._positions: dict[str, dict[str, Decimal]] = {}

        # Decision timeline — append-only list of all events
        self._timeline: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # BrokerAdapterInterface lifecycle management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Connect to the broker (no-op for shadow adapter).

        Shadow mode does not perform actual network connections.
        Logs at DEBUG level.

        Example:
            adapter.connect()  # Logs debug entry; no-op
        """
        pass

    def disconnect(self) -> None:
        """
        Disconnect from the broker (no-op for shadow adapter).

        Shadow mode does not maintain actual network connections.
        Logs at DEBUG level.

        Example:
            adapter.disconnect()  # Logs debug exit; no-op
        """
        pass

    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Get the broker timeout configuration.

        Returns:
            BrokerTimeoutConfig with connection, request, and other timeouts.

        Example:
            config = adapter.get_timeout_config()
            # config.connect_timeout_seconds == 10 (default or custom)
        """
        return self._timeout_config

    # ------------------------------------------------------------------
    # Market price management
    # ------------------------------------------------------------------

    def update_market_price(self, symbol: str, price: Decimal) -> None:
        """
        Update the market price for a symbol.

        Called by the feed ingestion layer to keep prices current.

        Args:
            symbol: Instrument ticker.
            price: Current market price.
        """
        self._market_prices[symbol] = price

    def get_market_price(self, symbol: str) -> Decimal:
        """
        Get the current market price for a symbol.

        Args:
            symbol: Instrument ticker.

        Returns:
            Current market price, defaults to Decimal("100") if not set.
        """
        return self._market_prices.get(symbol, Decimal("100"))

    # ------------------------------------------------------------------
    # BrokerAdapterInterface implementation
    # ------------------------------------------------------------------

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit a shadow order — always fills instantly at market price.

        Idempotent: duplicate client_order_id returns existing response.

        Args:
            request: Normalized order submission payload.

        Returns:
            OrderResponse with status FILLED and fill at market price.
        """
        # Idempotency check
        if request.client_order_id in self._client_id_map:
            existing_id = self._client_id_map[request.client_order_id]
            return self._orders[existing_id]

        # Generate broker order ID
        self._order_counter += 1
        broker_order_id = f"SHADOW-{self._order_counter:06d}"
        now = datetime.now(tz=timezone.utc)

        # Determine fill price (market price for the symbol)
        fill_price = self._get_fill_price(request)

        # Record the decision
        self._record_decision(
            event_type="shadow_order_submitted",
            order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=str(request.quantity),
            fill_price=str(fill_price),
            correlation_id=request.correlation_id,
            timestamp=now,
        )

        # Create filled response (shadow always fills instantly)
        response = OrderResponse(
            client_order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            average_fill_price=fill_price,
            status=OrderStatus.FILLED,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
            submitted_at=now,
            filled_at=now,
            correlation_id=request.correlation_id,
            execution_mode=ExecutionMode.SHADOW,
        )

        # Store order
        self._orders[broker_order_id] = response
        self._client_id_map[request.client_order_id] = broker_order_id

        # Create fill event
        fill = OrderFillEvent(
            fill_id=f"SHADOW-FILL-{self._order_counter:06d}",
            order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side,
            price=fill_price,
            quantity=request.quantity,
            commission=Decimal("0"),
            filled_at=now,
            broker_execution_id=f"SHADOW-EXEC-{self._order_counter:06d}",
            correlation_id=request.correlation_id,
        )
        self._fills[broker_order_id] = [fill]

        # Update hypothetical position
        self._update_position(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
        )

        # Record fill decision
        self._record_decision(
            event_type="shadow_order_filled",
            order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            fill_price=str(fill_price),
            correlation_id=request.correlation_id,
            timestamp=now,
        )

        return response

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Cancel a shadow order. Since shadow fills instantly, returns FILLED.

        Args:
            broker_order_id: Shadow-assigned order identifier.

        Returns:
            Existing OrderResponse (already FILLED in shadow mode).

        Raises:
            NotFoundError: broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Shadow order {broker_order_id} not found")
        return self._orders[broker_order_id]

    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query the state of a shadow order.

        Args:
            broker_order_id: Shadow-assigned order identifier.

        Returns:
            OrderResponse with current status.

        Raises:
            NotFoundError: broker_order_id is unknown.
        """
        if broker_order_id not in self._orders:
            raise NotFoundError(f"Shadow order {broker_order_id} not found")
        return self._orders[broker_order_id]

    def list_open_orders(self) -> list[OrderResponse]:
        """
        List open orders. Shadow mode fills instantly, so always empty.

        Returns:
            Empty list (all shadow orders are immediately filled).
        """
        return []

    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get fill events for a shadow order.

        Args:
            broker_order_id: Shadow-assigned order identifier.

        Returns:
            List of fill events (always exactly one for shadow).

        Raises:
            NotFoundError: broker_order_id is unknown.
        """
        if broker_order_id not in self._fills:
            raise NotFoundError(f"Shadow order {broker_order_id} not found")
        return list(self._fills[broker_order_id])

    def get_positions(self) -> list[PositionSnapshot]:
        """
        Get hypothetical position snapshot.

        Returns:
            List of PositionSnapshot for symbols with non-zero quantity.
        """
        from libs.contracts.execution import PositionSnapshot

        snapshots = []
        for symbol, pos_data in self._positions.items():
            if pos_data["quantity"] != Decimal("0"):
                market_price = self.get_market_price(symbol)
                market_value = pos_data["quantity"] * market_price
                cost = pos_data["cost_basis"]
                unrealized = market_value - cost

                snapshots.append(
                    PositionSnapshot(
                        symbol=symbol,
                        quantity=pos_data["quantity"],
                        average_entry_price=(
                            pos_data["cost_basis"] / pos_data["quantity"]
                            if pos_data["quantity"] != Decimal("0")
                            else Decimal("0")
                        ),
                        market_price=market_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized,
                        realized_pnl=pos_data["realized_pnl"],
                        cost_basis=cost,
                        updated_at=datetime.now(tz=timezone.utc),
                    )
                )
        return snapshots

    def get_account(self) -> AccountSnapshot:
        """
        Get hypothetical account snapshot.

        Returns:
            AccountSnapshot with equity reflecting shadow P&L.
        """
        total_unrealized = sum(
            (
                self._positions[sym]["quantity"] * self.get_market_price(sym)
                - self._positions[sym]["cost_basis"]
                for sym in self._positions
                if self._positions[sym]["quantity"] != Decimal("0")
            ),
            Decimal("0"),
        )
        total_realized = sum(
            (self._positions[sym]["realized_pnl"] for sym in self._positions), Decimal("0")
        )
        equity = self._initial_equity + total_realized + total_unrealized

        portfolio_value = sum(
            (
                self._positions[sym]["quantity"] * self.get_market_price(sym)
                for sym in self._positions
                if self._positions[sym]["quantity"] != Decimal("0")
            ),
            Decimal("0"),
        )
        positions_count = len(
            [s for s in self._positions if self._positions[s]["quantity"] != Decimal("0")]
        )

        return AccountSnapshot(
            account_id="SHADOW-ACCOUNT",
            equity=equity,
            cash=self._initial_equity + total_realized,
            buying_power=equity,
            portfolio_value=portfolio_value,
            daily_pnl=total_unrealized + total_realized,
            pending_orders_count=0,
            positions_count=positions_count,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def get_diagnostics(self) -> AdapterDiagnostics:
        """
        Get shadow adapter diagnostics.

        Returns:
            AdapterDiagnostics with shadow-specific metrics.
        """
        return AdapterDiagnostics(
            broker_name="shadow",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=0,
            error_count_1h=0,
            last_heartbeat=datetime.now(tz=timezone.utc),
            market_open=True,
            orders_submitted_today=len(self._orders),
            orders_filled_today=len(self._orders),
            uptime_seconds=0,
        )

    def is_market_open(self) -> bool:
        """
        Shadow mode always considers market open.

        Returns:
            True (shadow mode operates regardless of market hours).
        """
        return True

    @property
    def is_paper_adapter(self) -> bool:
        """
        Indicate this is a shadow (simulated) trading adapter.

        Returns:
            True, indicating this adapter does not execute real orders.

        Safety use case:
            LiveExecutionService uses this to prevent accidental routing of live
            deployments to shadow adapters.
        """
        return True

    # ------------------------------------------------------------------
    # Shadow-specific methods (not in interface)
    # ------------------------------------------------------------------

    def get_decision_timeline(self) -> list[dict[str, Any]]:
        """
        Get the full decision timeline for audit and replay.

        Returns:
            List of decision event dicts ordered chronologically.
        """
        return list(self._timeline)

    def get_shadow_pnl(self) -> dict[str, Any]:
        """
        Get aggregated shadow P&L summary.

        Returns:
            Dict with total_unrealized_pnl, total_realized_pnl,
            per_symbol breakdown, and total equity.
        """
        per_symbol: list[dict[str, Any]] = []
        total_unrealized = Decimal("0")
        total_realized = Decimal("0")

        for symbol, pos_data in self._positions.items():
            market_price = self.get_market_price(symbol)
            qty = pos_data["quantity"]
            cost = pos_data["cost_basis"]
            unrealized = qty * market_price - cost if qty != Decimal("0") else Decimal("0")
            realized = pos_data["realized_pnl"]
            total_unrealized += unrealized
            total_realized += realized

            per_symbol.append(
                {
                    "symbol": symbol,
                    "quantity": str(qty),
                    "cost_basis": str(cost),
                    "market_price": str(market_price),
                    "unrealized_pnl": str(unrealized),
                    "realized_pnl": str(realized),
                }
            )

        return {
            "total_unrealized_pnl": str(total_unrealized),
            "total_realized_pnl": str(total_realized),
            "total_equity": str(self._initial_equity + total_realized + total_unrealized),
            "positions": per_symbol,
        }

    def get_submitted_orders_count(self) -> int:
        """Return total number of shadow orders submitted."""
        return len(self._orders)

    def get_all_orders(self) -> list[OrderResponse]:
        """Return all shadow order responses."""
        return list(self._orders.values())

    def clear(self) -> None:
        """Reset all shadow state for testing."""
        self._orders.clear()
        self._client_id_map.clear()
        self._fills.clear()
        self._positions.clear()
        self._timeline.clear()
        self._order_counter = 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_fill_price(self, request: OrderRequest) -> Decimal:
        """
        Determine the fill price for a shadow order.

        For market orders: uses current market price.
        For limit orders: uses the limit price (assumes would have filled).
        For stop orders: uses the stop price.
        For stop_limit: uses the limit price.

        Args:
            request: The order request.

        Returns:
            The shadow fill price.
        """
        from libs.contracts.execution import OrderType

        if request.order_type == OrderType.MARKET:
            return self.get_market_price(request.symbol)
        elif request.order_type == OrderType.LIMIT:
            return request.limit_price or self.get_market_price(request.symbol)
        elif request.order_type == OrderType.STOP:
            return request.stop_price or self.get_market_price(request.symbol)
        elif request.order_type == OrderType.STOP_LIMIT:
            return request.limit_price or self.get_market_price(request.symbol)
        return self.get_market_price(request.symbol)

    def _update_position(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        """
        Update the hypothetical position for a symbol after a fill.

        Tracks quantity, cost basis, and realized P&L using weighted average
        entry price for close calculations.

        Args:
            symbol: Instrument ticker.
            side: Fill direction (BUY or SELL).
            quantity: Number of units filled.
            price: Fill price per unit.
        """
        if symbol not in self._positions:
            self._positions[symbol] = {
                "quantity": Decimal("0"),
                "cost_basis": Decimal("0"),
                "realized_pnl": Decimal("0"),
            }

        pos = self._positions[symbol]
        current_qty = pos["quantity"]

        if side == OrderSide.BUY:
            # Adding to long or covering short
            if current_qty >= Decimal("0"):
                # Adding to long — increase cost basis
                pos["quantity"] = current_qty + quantity
                pos["cost_basis"] = pos["cost_basis"] + (quantity * price)
            else:
                # Covering short position
                close_qty = min(quantity, abs(current_qty))
                avg_entry = (
                    pos["cost_basis"] / current_qty if current_qty != Decimal("0") else Decimal("0")
                )
                # Realized P&L: short sold at avg_entry, bought back at price
                pos["realized_pnl"] += close_qty * (avg_entry - price)
                remaining = quantity - close_qty
                if remaining > Decimal("0"):
                    # Opening new long after covering short
                    pos["quantity"] = remaining
                    pos["cost_basis"] = remaining * price
                else:
                    pos["quantity"] = current_qty + quantity
                    # Reduce cost basis proportionally
                    if current_qty != Decimal("0"):
                        pos["cost_basis"] = pos["cost_basis"] * (pos["quantity"] / current_qty)
        else:
            # Selling from long or adding to short
            if current_qty > Decimal("0"):
                # Closing long position
                close_qty = min(quantity, current_qty)
                avg_entry = (
                    pos["cost_basis"] / current_qty if current_qty != Decimal("0") else Decimal("0")
                )
                pos["realized_pnl"] += close_qty * (price - avg_entry)
                remaining_sell = quantity - close_qty
                if remaining_sell > Decimal("0"):
                    # Opening short after closing long
                    pos["quantity"] = -remaining_sell
                    pos["cost_basis"] = -(remaining_sell * price)
                else:
                    pos["quantity"] = current_qty - quantity
                    if current_qty != Decimal("0"):
                        pos["cost_basis"] = pos["cost_basis"] * (pos["quantity"] / current_qty)
            else:
                # Adding to short position
                pos["quantity"] = current_qty - quantity
                pos["cost_basis"] = pos["cost_basis"] - (quantity * price)

    def _record_decision(self, **kwargs: Any) -> None:
        """
        Append an event to the decision timeline.

        Args:
            **kwargs: Event fields including event_type, timestamp, etc.
        """
        event = dict(kwargs)
        # Convert datetime to ISO string for serialisation
        if "timestamp" in event and isinstance(event["timestamp"], datetime):
            event["timestamp"] = event["timestamp"].isoformat()
        self._timeline.append(event)

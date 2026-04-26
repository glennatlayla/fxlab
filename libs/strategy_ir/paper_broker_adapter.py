"""
Deterministic, fully-simulated paper broker adapter for the strategy-IR layer.

Purpose:
    Provide a real, production-grade
    :class:`libs.strategy_ir.interfaces.broker_adapter_interface.BrokerAdapterInterface`
    implementation that the BacktestEngine and the IR-driven strategy
    runner can drive WITHOUT any live broker connectivity. Fills are
    fully simulated against the bar stream; bookkeeping is exact
    (Decimal arithmetic); behaviour is deterministic (no wall-clock,
    no random number generation).

==============================================================================
M4.E5 SWAP PATH -- READ THIS BEFORE WIRING THE LIVE OANDA ADAPTER
==============================================================================

When M4.E5 lands the live :class:`OandaBrokerAdapter` (file
``libs/strategy_ir/interfaces/broker_adapter_interface.py``), the
swap is mechanical at every call site:

    1.  Construct an ``OandaBrokerAdapter(oanda_client=client)`` in
        place of ``PaperBrokerAdapter(...)``.
    2.  No call site changes -- both classes satisfy the same
        :class:`BrokerAdapterInterface` Protocol (the four methods
        ``place_order``, ``cancel_order``, ``get_position``,
        ``get_account_state``).
    3.  The :meth:`PaperBrokerAdapter.submit_bar` hook is
        backtest-only; the live execution loop subscribes to Oanda's
        transactions stream instead, but that wiring lives in the
        execution-service layer, not here.
    4.  Idempotency on ``client_extension_id`` is honoured by both
        adapters identically -- the paper adapter uses an in-memory
        dict, the Oanda adapter passes the value through to v20's
        ``clientExtensions.id`` field.

The IR-layer surface stays Protocol-narrow on purpose: the heavier
:class:`libs.contracts.execution.OrderFillEvent` and friends live in
the execution-service layer and are not imported here so the IR
import graph stays small.

==============================================================================

Responsibilities:
    - Implement :class:`BrokerAdapterInterface` (place_order,
      cancel_order, get_position, get_account_state).
    - Track pending orders (market, limit, stop) and fill them
      against the bar stream supplied via :meth:`submit_bar`.
    - Maintain exact Decimal bookkeeping for positions (units, avg
      price), realised PnL (accumulated to balance on close), and
      unrealised PnL (mark-to-market against the most-recent bar
      mid-price).
    - Apply per-symbol pip slippage to every simulated fill.
    - Enforce idempotency on ``client_extension_id`` so retries
      above the adapter never produce duplicate fills.
    - Be thread-safe: every mutation of shared state is guarded by a
      ``threading.Lock``.

Does NOT:
    - Talk to any live broker.
    - Use ``random``, ``time.time``, ``datetime.now``, or any other
      non-deterministic source. Same input order stream + same bar
      stream produces byte-identical fills.
    - Validate account margin requirements -- that lives in the risk
      gate above the adapter, not here. The paper account never runs
      out of margin; balance can go negative if a strategy bleeds.
    - Implement partial fills. Every order fills in full or stays
      pending. Partial-fill behaviour is an Oanda-side concern that
      M4.E5 will model on the live adapter.
    - Implement order expiry / GTC vs DAY semantics. Pending orders
      remain pending until cancelled or filled.

Dependencies:
    - :mod:`libs.contracts.market_data` for :class:`Candle`.
    - :mod:`libs.strategy_ir.interfaces.broker_adapter_interface` for
      the Protocol and value objects (OrderRef, Position,
      AccountState, OrderSide, OrderType).
    - :mod:`libs.strategy_ir.interfaces.market_data_provider_interface`
      for the :class:`MarketDataProviderInterface` Protocol -- the
      adapter consults the provider for pip sizes only (slippage
      conversion); it does NOT fetch bars itself (the engine
      supplies bars via :meth:`submit_bar`).

Raises:
    - ValueError: from :meth:`place_order` when arguments are
      malformed (empty symbol, non-positive units, missing limit/stop
      price for the matching order_type).
    - PaperBrokerError: when an order is placed for a symbol the
      market-data provider does not support (the adapter cannot know
      the pip size and so cannot compute slippage safely).

Example::

    from decimal import Decimal

    from libs.strategy_ir.mocks.mock_market_data_provider import (
        MockMarketDataProvider,
    )
    from libs.strategy_ir.paper_broker_adapter import PaperBrokerAdapter
    from libs.strategy_ir.interfaces.broker_adapter_interface import (
        OrderSide,
        OrderType,
    )

    provider = MockMarketDataProvider()
    broker = PaperBrokerAdapter(
        starting_balance=Decimal("100000"),
        pip_slippage={"EURUSD": 1},
        market_data=provider,
    )

    ref = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="run-1-bar-1-leg-A",
    )
    fills = broker.submit_bar("EURUSD", next_candle)
    assert len(fills) == 1
    assert fills[0].order_ref == ref
"""

from __future__ import annotations

import threading
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from libs.contracts.market_data import Candle
from libs.strategy_ir.interfaces.broker_adapter_interface import (
    AccountState,
    BrokerAdapterInterface,
    OrderRef,
    OrderSide,
    OrderType,
    Position,
)
from libs.strategy_ir.interfaces.market_data_provider_interface import (
    MarketDataProviderInterface,
)

# ---------------------------------------------------------------------------
# Public exception type (typed, NOT a bare Exception)
# ---------------------------------------------------------------------------


class PaperBrokerError(Exception):
    """
    Raised when the paper broker cannot complete an operation safely.

    Examples:
        - place_order called with a symbol the injected
          market-data provider does not support (no pip size known →
          slippage cannot be computed).
        - place_order called for a limit / stop order without the
          matching ``limit_price`` / ``stop_price`` argument.

    These are programmer errors (not transient), so call sites
    should fix the input rather than retry.
    """


# ---------------------------------------------------------------------------
# FillEvent value object (frozen Pydantic model)
# ---------------------------------------------------------------------------


class FillEvent(BaseModel):
    """
    Immutable record of a simulated fill produced by :meth:`PaperBrokerAdapter.submit_bar`.

    The IR-layer keeps this surface narrow on purpose: the heavier
    :class:`libs.contracts.execution.OrderFillEvent` carries
    execution-service plumbing (correlation IDs, broker timestamps,
    diagnostic spans) that the IR layer does not need. Backtest
    consumers convert this to the heavier shape only at the boundary.

    Attributes:
        order_ref: The :class:`OrderRef` returned by the original
            :meth:`PaperBrokerAdapter.place_order` call.
        symbol: Tradable instrument (echoed from the order).
        side: BUY or SELL (echoed from the order).
        units: Filled units. Always equal to the order's units --
            the paper adapter does not produce partial fills.
        fill_price: Decimal fill price AFTER slippage adjustment.
        slippage_pips: Number of pips of slippage applied (always
            non-negative; see :data:`PaperBrokerAdapter._pip_slippage`).
        bar_index: Monotonic 0-based index of the bar against which
            the fill was simulated. Used for deterministic ordering
            in tests and audit logs.

    Why frozen:
        Fills are immutable observations. Any later transformation
        (e.g. converting to the execution-service shape) creates a
        new value object.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_ref: OrderRef
    symbol: str = Field(..., min_length=1)
    side: OrderSide
    units: int = Field(..., gt=0)
    fill_price: Decimal = Field(..., ge=0)
    slippage_pips: int = Field(..., ge=0)
    bar_index: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Internal pending-order record
# ---------------------------------------------------------------------------


class _PendingOrder(BaseModel):
    """
    Internal mutable-by-construction record of an order awaiting fill.

    Not exported. The adapter holds these in a list and walks it on
    each :meth:`PaperBrokerAdapter.submit_bar` call to decide which
    orders should fill against the new bar.

    Frozen so that we never accidentally mutate an order in place;
    when an order fills it is REMOVED from the pending list and a
    :class:`FillEvent` is emitted instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_ref: OrderRef
    order_type: OrderType
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: The account ID surfaced by a fresh paper adapter. Documented
#: fictitious so it cannot be mistaken for a real Oanda account in
#: log scrapes.
_DEFAULT_ACCOUNT_ID: Final[str] = "PAPER-ACCOUNT-0001"

#: ISO currency code for the simulated account. Hard-coded to USD;
#: the M4.E5 live adapter inherits the currency from the real Oanda
#: account, but the paper adapter uses USD because every starting
#: balance in the IR-layer tests is denominated in USD.
_DEFAULT_CURRENCY: Final[str] = "USD"

#: Default starting balance applied when the constructor caller does
#: not pass ``starting_balance``. $100,000 matches the heavier mock
#: in :mod:`libs.strategy_ir.mocks.mock_broker_adapter`.
_DEFAULT_STARTING_BALANCE: Final[Decimal] = Decimal("100000")


class PaperBrokerAdapter(BrokerAdapterInterface):
    """
    Deterministic, fully-simulated broker adapter satisfying BrokerAdapterInterface.

    Responsibilities:
        - Generate sequential broker_order_id strings of the shape
          ``"PAPER-ORDER-N"`` so tests can assert on exact IDs and
          deterministic-replay assertions hold byte-for-byte.
        - Hold pending orders and walk them on each
          :meth:`submit_bar` call to decide fills.
        - Maintain exact Decimal accounting for positions, realised
          PnL (added to balance on close) and unrealised PnL
          (mark-to-market against the most recent bar's mid).
        - Apply per-symbol pip slippage on every fill so live-vs-
          paper drift is bounded by a configurable parameter.

    Does NOT:
        - Connect to any broker.
        - Use any non-deterministic source (no random, no clock).
        - Validate margin / risk -- that lives upstream in the risk
          gate.

    Thread safety:
        All shared mutable state (`_pending`, `_positions`,
        `_balance`, `_by_extension_id`, `_next_order_id`,
        `_bar_index`, `_last_bar`) is guarded by a single
        ``threading.Lock``. Concurrent callers see a consistent view.

    Constructor:
        starting_balance: Cash balance to seed the simulated account
            with. Defaults to $100,000.
        pip_slippage: Per-symbol pip count of slippage to apply on
            every fill. ``{"EURUSD": 1}`` means a EURUSD fill is 1
            pip (0.0001) WORSE than the "true" fill price -- a BUY
            fills ABOVE the bar open / limit, a SELL fills BELOW.
            Default is no slippage.
        market_data: Injected
            :class:`MarketDataProviderInterface`. The adapter
            consults it for pip sizes (the slippage in pips × the
            pip size = the price adjustment). The adapter does NOT
            fetch bars from the provider; the engine pushes bars in
            via :meth:`submit_bar`.

    Raises:
        ValueError: If ``starting_balance`` is negative.

    Example::

        broker = PaperBrokerAdapter(
            starting_balance=Decimal("100000"),
            pip_slippage={"EURUSD": 1},
            market_data=provider,
        )
    """

    def __init__(
        self,
        *,
        starting_balance: Decimal = _DEFAULT_STARTING_BALANCE,
        pip_slippage: dict[str, int] | None = None,
        market_data: MarketDataProviderInterface,
    ) -> None:
        if starting_balance < Decimal(0):
            raise ValueError(f"starting_balance must be non-negative; got {starting_balance}")

        self._market_data: MarketDataProviderInterface = market_data
        self._pip_slippage: dict[str, int] = dict(pip_slippage or {})

        # Idempotency map: client_extension_id -> the OrderRef from
        # the first call. Re-submission with the same key returns
        # this ref unchanged.
        self._by_extension_id: dict[str, OrderRef] = {}

        # Pending orders awaiting fill. Walked in insertion order on
        # every submit_bar so deterministic replay holds.
        self._pending: list[_PendingOrder] = []

        # Cancelled order IDs (set membership for O(1) lookup; we
        # also keep the list under self._cancelled for introspection).
        self._cancelled_ids: set[str] = set()

        # Position book: symbol -> (units, average_price). Units are
        # signed (positive long, negative short). When a fill closes
        # or flips the position, realised PnL is added to _balance.
        self._positions: dict[str, tuple[int, Decimal]] = {}

        # Cash balance and the most-recent bar per symbol (for
        # mark-to-market unrealised PnL).
        self._balance: Decimal = starting_balance
        self._last_bar: dict[str, Candle] = {}

        # Monotonic counters used everywhere a deterministic ID is
        # required.
        self._next_order_id: int = 1
        self._bar_index: int = 0

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # BrokerAdapterInterface implementation
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        units: int,
        *,
        order_type: OrderType,
        client_extension_id: str,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderRef:
        """
        Submit a paper order; idempotent on ``client_extension_id``.

        Args:
            symbol: Tradable instrument. Must be supported by the
                injected market-data provider (for pip-size lookup).
            side: BUY or SELL.
            units: Positive integer order size in instrument units.
            order_type: MARKET or LIMIT. STOP orders are placed by
                supplying ``stop_price`` alongside MARKET (the
                Protocol's narrow type set keeps the surface minimal;
                stop semantics ride on the price field).
            client_extension_id: Caller-supplied idempotency key.
                Re-submitting with the same key returns the existing
                :class:`OrderRef` without recording a duplicate.
            limit_price: Required when ``order_type == LIMIT``.
                The order fills when the bar low/high crosses this
                level (BUY waits for low ≤ limit, SELL waits for
                high ≥ limit).
            stop_price: Optional. When supplied, the order is treated
                as a stop: BUY fills when high ≥ stop, SELL fills
                when low ≤ stop. ``stop_price`` and ``limit_price``
                are mutually exclusive.

        Returns:
            The accepted :class:`OrderRef` (new or previously-issued).

        Raises:
            ValueError: If ``symbol`` or ``client_extension_id`` is
                empty, ``units`` is non-positive, or the
                limit / stop price arguments are inconsistent with
                the order type.
            PaperBrokerError: If ``symbol`` is not supported by the
                market-data provider (pip size unknowable → slippage
                cannot be computed).
        """
        # Argument validation -- raise ValueError with the offending
        # argument named, the same shape the mock uses so consumers
        # see consistent error messages across implementations.
        if not symbol:
            raise ValueError("symbol must be non-empty")
        if not client_extension_id:
            raise ValueError("client_extension_id must be non-empty")
        if units <= 0:
            raise ValueError(f"units must be positive; got {units}")
        if order_type == OrderType.LIMIT and limit_price is None and stop_price is None:
            raise ValueError("LIMIT orders require limit_price or stop_price")
        if limit_price is not None and stop_price is not None:
            raise ValueError("limit_price and stop_price are mutually exclusive")
        if limit_price is not None and limit_price <= Decimal(0):
            raise ValueError(f"limit_price must be positive; got {limit_price}")
        if stop_price is not None and stop_price <= Decimal(0):
            raise ValueError(f"stop_price must be positive; got {stop_price}")

        if not self._market_data.supports(symbol):
            raise PaperBrokerError(
                f"symbol {symbol!r} not supported by injected market-data provider; "
                "cannot compute pip-based slippage"
            )

        with self._lock:
            # Idempotency check: a re-submission must not record a
            # second placement, must not enqueue a second pending
            # order, and must return the original OrderRef byte-for-
            # byte. This mirrors Oanda v20's clientExtensions.id
            # behaviour exactly so the M4.E5 swap is observable as a
            # no-op from above.
            existing = self._by_extension_id.get(client_extension_id)
            if existing is not None:
                return existing

            broker_order_id = f"PAPER-ORDER-{self._next_order_id}"
            self._next_order_id += 1

            ref = OrderRef(
                broker_order_id=broker_order_id,
                client_extension_id=client_extension_id,
                symbol=symbol,
                side=side,
                units=units,
            )
            self._by_extension_id[client_extension_id] = ref
            self._pending.append(
                _PendingOrder(
                    order_ref=ref,
                    order_type=order_type,
                    limit_price=limit_price,
                    stop_price=stop_price,
                )
            )
            return ref

    def cancel_order(self, order_ref: OrderRef) -> None:
        """
        Cancel a pending order by reference.

        Cancelling an already-filled or already-cancelled order is a
        no-op (NOT an error) so callers can issue cancels defensively.
        Removes the order from the pending list immediately so the
        next :meth:`submit_bar` will not fill it.

        Args:
            order_ref: The reference returned by :meth:`place_order`.
        """
        with self._lock:
            self._cancelled_ids.add(order_ref.broker_order_id)
            # Remove from the pending list. We rebuild rather than
            # in-place delete so behaviour is obvious in the
            # presence of concurrent reads (we hold the lock, so
            # there are no concurrent readers, but the rebuild also
            # makes the intent unmistakable in code review).
            self._pending = [
                p for p in self._pending if p.order_ref.broker_order_id != order_ref.broker_order_id
            ]

    def get_position(self, symbol: str) -> Position | None:
        """
        Return the current position for ``symbol`` or ``None`` when flat.

        Args:
            symbol: Tradable instrument.

        Returns:
            :class:`Position` snapshot or ``None``. The snapshot's
            ``units`` field is signed (positive long, negative short);
            ``average_price`` is the volume-weighted entry price.
        """
        with self._lock:
            entry = self._positions.get(symbol)
            if entry is None:
                return None
            units, avg_price = entry
            return Position(symbol=symbol, units=units, average_price=avg_price)

    def get_account_state(self) -> AccountState:
        """
        Return the current account snapshot.

        ``unrealized_pl`` is mark-to-market against the most-recent
        bar received via :meth:`submit_bar` for each symbol with an
        open position. Symbols with no bar yet contribute zero
        unrealised PnL (the mark-to-market price is unknown).

        ``margin_used`` is always zero because the paper adapter does
        not model margin (see class docstring -- margin is an
        upstream-risk-gate concern, not a broker concern).

        Returns:
            :class:`AccountState` snapshot.
        """
        with self._lock:
            unrealized = self._compute_unrealized_pl_locked()
            return AccountState(
                account_id=_DEFAULT_ACCOUNT_ID,
                balance=self._balance,
                unrealized_pl=unrealized,
                margin_used=Decimal(0),
                margin_available=self._balance + unrealized,
                currency=_DEFAULT_CURRENCY,
            )

    # ------------------------------------------------------------------
    # Bar-driven simulation hook (engine calls this every bar)
    # ------------------------------------------------------------------

    def submit_bar(self, symbol: str, candle: Candle) -> list[FillEvent]:
        """
        Advance the simulation by one bar; fill any orders that should fill.

        Called by the BacktestEngine once per bar per symbol. The
        adapter:
            1. Records the bar as the most-recent for ``symbol`` so
               unrealised PnL can be marked.
            2. Walks every pending order for ``symbol`` (in insertion
               order, so determinism holds) and decides whether each
               should fill against this bar:
                   - MARKET: fills at this bar's open (the
                     "next bar open" rule -- the bar passed in IS the
                     next bar after the one in which the order was
                     placed; the engine controls bar timing).
                   - LIMIT (BUY): fills if low <= limit, at limit.
                   - LIMIT (SELL): fills if high >= limit, at limit.
                   - STOP (BUY): fills if high >= stop, at stop.
                   - STOP (SELL): fills if low <= stop, at stop.
            3. Applies per-symbol pip slippage to each fill price
               (BUY fills WORSE = higher; SELL fills WORSE = lower).
            4. Updates the position book and the realised PnL on
               closes / flips.
            5. Returns the list of :class:`FillEvent` produced this
               bar in deterministic order.

        Args:
            symbol: Tradable instrument the bar belongs to. Must
                match ``candle.symbol``.
            candle: The new bar. Used both as the fill-price source
                and as the mark-to-market price for unrealised PnL.

        Returns:
            List of :class:`FillEvent` -- empty when no order filled.

        Raises:
            ValueError: If ``symbol != candle.symbol``.
        """
        if symbol != candle.symbol:
            raise ValueError(
                f"symbol mismatch: passed {symbol!r}, candle carries {candle.symbol!r}"
            )

        with self._lock:
            # Record the bar so future get_account_state() calls can
            # mark unrealised PnL even before the next submit_bar.
            self._last_bar[symbol] = candle
            bar_index = self._bar_index
            self._bar_index += 1

            fills: list[FillEvent] = []
            still_pending: list[_PendingOrder] = []

            for pending in self._pending:
                # Only consider pending orders for THIS symbol; orders
                # on other symbols stay pending and will be revisited
                # when their symbol's bar arrives.
                if pending.order_ref.symbol != symbol:
                    still_pending.append(pending)
                    continue

                fill_price = self._compute_fill_price_locked(pending, candle)
                if fill_price is None:
                    # Order didn't qualify against this bar; keep it
                    # pending for the next one.
                    still_pending.append(pending)
                    continue

                slippage_pips = self._pip_slippage.get(symbol, 0)
                adjusted_price = self._apply_slippage_locked(
                    base_price=fill_price,
                    side=pending.order_ref.side,
                    symbol=symbol,
                    pips=slippage_pips,
                )

                # Update the position book and accumulate realised PnL.
                self._apply_fill_to_book_locked(
                    symbol=symbol,
                    side=pending.order_ref.side,
                    units=pending.order_ref.units,
                    fill_price=adjusted_price,
                )

                fills.append(
                    FillEvent(
                        order_ref=pending.order_ref,
                        symbol=symbol,
                        side=pending.order_ref.side,
                        units=pending.order_ref.units,
                        fill_price=adjusted_price,
                        slippage_pips=slippage_pips,
                        bar_index=bar_index,
                    )
                )

            self._pending = still_pending
            return fills

    # ------------------------------------------------------------------
    # Introspection helpers (tests use these)
    # ------------------------------------------------------------------

    def pending_orders(self) -> list[OrderRef]:
        """Return a copy of the pending-order list in insertion order."""
        with self._lock:
            return [p.order_ref for p in self._pending]

    def cancelled_order_ids(self) -> set[str]:
        """Return a copy of the cancelled-order-ID set."""
        with self._lock:
            return set(self._cancelled_ids)

    def realized_balance(self) -> Decimal:
        """Return the cash balance (starting balance + realised PnL)."""
        with self._lock:
            return self._balance

    # ------------------------------------------------------------------
    # Internals (require the lock to be held)
    # ------------------------------------------------------------------

    def _compute_fill_price_locked(self, pending: _PendingOrder, candle: Candle) -> Decimal | None:
        """
        Decide whether ``pending`` fills against ``candle`` and at what price.

        Returns the BASE fill price (before slippage) or ``None`` if
        the order does not qualify on this bar. Caller must hold the
        lock.
        """
        # Stop orders take priority over the order_type field because
        # a STOP can be expressed as MARKET + stop_price in this
        # narrow Protocol.
        if pending.stop_price is not None:
            stop = pending.stop_price
            if pending.order_ref.side == OrderSide.BUY:
                # BUY-STOP: fills when high >= stop.
                return stop if candle.high >= stop else None
            # SELL-STOP: fills when low <= stop.
            return stop if candle.low <= stop else None

        if pending.limit_price is not None:
            limit = pending.limit_price
            if pending.order_ref.side == OrderSide.BUY:
                # BUY-LIMIT: fills when low <= limit (price dropped to/below limit).
                return limit if candle.low <= limit else None
            # SELL-LIMIT: fills when high >= limit (price rose to/above limit).
            return limit if candle.high >= limit else None

        # MARKET: always fills, at this bar's open (the "next bar
        # open" rule -- engine schedules bars so the bar passed in
        # IS the next bar after the one in which place_order ran).
        if pending.order_type == OrderType.MARKET:
            return candle.open

        # LIMIT order with no limit_price (and no stop_price) was
        # already rejected by place_order's validation, so this branch
        # is unreachable in practice. Defensive return preserves the
        # invariant that this method either yields a Decimal or None.
        return None

    def _apply_slippage_locked(
        self,
        *,
        base_price: Decimal,
        side: OrderSide,
        symbol: str,
        pips: int,
    ) -> Decimal:
        """
        Adjust ``base_price`` by ``pips`` pips of slippage in the WORSE direction.

        BUY orders fill at base + (pips × pip_size) (paying more);
        SELL orders fill at base - (pips × pip_size) (receiving less).
        Caller must hold the lock.
        """
        if pips == 0:
            return base_price
        pip_size = self._market_data.get_pip_size(symbol)
        adjustment = Decimal(pips) * pip_size
        if side == OrderSide.BUY:
            return base_price + adjustment
        return base_price - adjustment

    def _apply_fill_to_book_locked(
        self,
        *,
        symbol: str,
        side: OrderSide,
        units: int,
        fill_price: Decimal,
    ) -> None:
        """
        Update the position book for ``symbol`` and accumulate realised PnL.

        Position bookkeeping rules:
            - Adding units in the same direction as the existing
              position: weighted-average the entry price; no realised
              PnL.
            - Reducing the position partially: realise PnL on the
              closed slice; average price unchanged on the surviving
              slice.
            - Closing exactly: realise PnL on the full slice; remove
              the position from the book.
            - Flipping (closing more than is open): realise PnL on
              the full closed slice; the surplus opens a new position
              in the opposite direction at ``fill_price``.

        Caller must hold the lock.
        """
        signed_units = units if side == OrderSide.BUY else -units
        existing = self._positions.get(symbol)

        if existing is None:
            # New position.
            self._positions[symbol] = (signed_units, fill_price)
            return

        existing_units, existing_avg = existing

        same_direction = (existing_units > 0 and signed_units > 0) or (
            existing_units < 0 and signed_units < 0
        )

        if same_direction:
            # Weighted-average entry price; no realised PnL.
            new_units = existing_units + signed_units
            total_cost = existing_avg * Decimal(abs(existing_units)) + fill_price * Decimal(
                abs(signed_units)
            )
            new_avg = total_cost / Decimal(abs(new_units))
            self._positions[symbol] = (new_units, new_avg)
            return

        # Opposite direction: at least a partial close. Realise PnL
        # on the slice that closes; the surviving slice keeps the
        # original average price; any surplus opens a flipped position
        # at fill_price.
        closing_units = min(abs(existing_units), abs(signed_units))
        # Realised PnL on a long close = (exit - entry) * units
        # Realised PnL on a short close = (entry - exit) * units
        if existing_units > 0:
            realised = (fill_price - existing_avg) * Decimal(closing_units)
        else:
            realised = (existing_avg - fill_price) * Decimal(closing_units)
        self._balance += realised

        remaining_existing = abs(existing_units) - closing_units
        remaining_new = abs(signed_units) - closing_units

        if remaining_existing == 0 and remaining_new == 0:
            # Exact close.
            del self._positions[symbol]
            return
        if remaining_existing > 0:
            # Partial close on the existing side; average price
            # unchanged on the surviving units.
            sign = 1 if existing_units > 0 else -1
            self._positions[symbol] = (sign * remaining_existing, existing_avg)
            return
        # Flip: the new order's surplus opens a fresh position in
        # its own direction at fill_price.
        sign = 1 if signed_units > 0 else -1
        self._positions[symbol] = (sign * remaining_new, fill_price)

    def _compute_unrealized_pl_locked(self) -> Decimal:
        """
        Mark-to-market unrealised PnL across every open position.

        Uses the most-recent bar's mid-price ((high + low) / 2) for
        each symbol. Symbols with no bar yet contribute zero (the
        mark price is unknown). Caller must hold the lock.
        """
        total = Decimal(0)
        for symbol, (units, avg_price) in self._positions.items():
            bar = self._last_bar.get(symbol)
            if bar is None:
                continue
            mid = (bar.high + bar.low) / Decimal(2)
            if units > 0:
                total += (mid - avg_price) * Decimal(units)
            else:
                total += (avg_price - mid) * Decimal(abs(units))
        return total


__all__ = [
    "FillEvent",
    "PaperBrokerAdapter",
    "PaperBrokerError",
]

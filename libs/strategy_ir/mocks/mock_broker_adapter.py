"""
In-memory mock broker adapter for unit tests.

Purpose:
    Satisfy
    :class:`libs.strategy_ir.interfaces.broker_adapter_interface.BrokerAdapterInterface`
    with deterministic, fully implemented behaviour so unit tests for
    every consumer of the Protocol can run with no I/O and no clock
    dependency.

Responsibilities:
    - Track placed and cancelled orders in memory.
    - Track positions and account state in memory.
    - Enforce idempotency on ``client_extension_id`` -- a second
      :meth:`place_order` call with a previously-seen extension ID
      MUST return the original :class:`OrderRef` without recording a
      new placement.
    - Expose a deterministic pip-size table for the seven majors
      (mirrored from
      :mod:`libs.strategy_ir.mocks.mock_market_data_provider`).
    - Provide introspection helpers (:meth:`placed_orders`,
      :meth:`cancelled_orders`, :meth:`clear`) so tests can assert
      on the recorded calls.

Does NOT:
    - Make any HTTP call.
    - Simulate fills, slippage, or market microstructure -- those
      live in the heavier
      :class:`libs.contracts.mocks.mock_broker_adapter.MockBrokerAdapter`
      used by the execution-service layer. The IR-layer mock is
      intentionally narrow because the IR consumers only need to
      verify "did I call place_order with the right shape".
    - Hold any global state -- every instance is independent.

Dependencies:
    - :mod:`libs.strategy_ir.interfaces.broker_adapter_interface` for
      the Protocol and value objects.

Example::

    from decimal import Decimal

    from libs.strategy_ir.mocks.mock_broker_adapter import MockBrokerAdapter
    from libs.strategy_ir.interfaces.broker_adapter_interface import (
        OrderSide,
        OrderType,
    )

    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="run-42-bar-1234-leg-A",
    )
    assert ref.symbol == "EURUSD"
    assert adapter.placed_orders() == [ref]
"""

from __future__ import annotations

import threading
from decimal import Decimal

from libs.strategy_ir.interfaces.broker_adapter_interface import (
    AccountState,
    BrokerAdapterInterface,
    OrderRef,
    OrderSide,
    OrderType,
    Position,
)

# ---------------------------------------------------------------------------
# Pip-size table mirrored from MockMarketDataProvider
# ---------------------------------------------------------------------------

#: Deterministic pip sizes for the seven majors. Kept in sync with
#: :data:`libs.strategy_ir.mocks.mock_market_data_provider._DEFAULT_PIP_SIZES`
#: so tests that exercise both mocks see consistent values.
_DEFAULT_PIP_SIZES: dict[str, Decimal] = {
    "EURUSD": Decimal("0.0001"),
    "GBPUSD": Decimal("0.0001"),
    "USDJPY": Decimal("0.01"),
    "USDCHF": Decimal("0.0001"),
    "AUDUSD": Decimal("0.0001"),
    "USDCAD": Decimal("0.0001"),
    "NZDUSD": Decimal("0.0001"),
}

#: Default account state surfaced by a fresh mock until the test
#: overrides it via :meth:`MockBrokerAdapter.set_account_state`. The
#: numbers are picked to be obviously fictitious so they do not get
#: mistaken for real production figures in test logs.
_DEFAULT_ACCOUNT_STATE = AccountState(
    account_id="MOCK-ACCOUNT-0001",
    balance=Decimal("100000.00"),
    unrealized_pl=Decimal("0.00"),
    margin_used=Decimal("0.00"),
    margin_available=Decimal("100000.00"),
    currency="USD",
)


class MockBrokerAdapter(BrokerAdapterInterface):
    """
    Deterministic in-memory BrokerAdapterInterface implementation.

    Responsibilities:
        - Generate sequential broker_order_id strings of the shape
          ``"MOCK-ORDER-N"`` so tests can assert on exact IDs.
        - Track every placement and cancellation.
        - Enforce idempotency on ``client_extension_id`` strictly:
          re-submission with the same key returns the original
          :class:`OrderRef` byte-for-byte and is NOT recorded as a
          second placement (mirrors the real Oanda v20 behaviour
          when ``clientExtensions.id`` is reused).
        - Allow tests to seed positions and account state via
          :meth:`set_position` and :meth:`set_account_state`.

    Does NOT:
        - Simulate fills, slippage, or partial cancels.
        - Validate against the seeded :class:`AccountState` (margin
          checks live in the risk gate, not the broker).

    Thread safety:
        All mutable state is guarded by an ``threading.Lock`` so
        concurrent test code (e.g. exercising a thread pool) sees a
        consistent view.
    """

    def __init__(self) -> None:
        # Idempotency map: client_extension_id -> the OrderRef we
        # returned the first time. Re-submission MUST return the same
        # ref without appending to _placed.
        self._by_extension_id: dict[str, OrderRef] = {}

        # Audit lists used by the introspection helpers.
        self._placed: list[OrderRef] = []
        self._cancelled: list[OrderRef] = []

        # Position / account state.
        self._positions: dict[str, Position] = {}
        self._account_state: AccountState = _DEFAULT_ACCOUNT_STATE

        # Pip-size table copy (per-instance so tests can mutate freely).
        self._pip_sizes: dict[str, Decimal] = dict(_DEFAULT_PIP_SIZES)

        # Monotonic order-ID counter and the lock that protects every
        # mutable field above.
        self._next_order_id: int = 1
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        units: int,
        *,
        order_type: OrderType,
        client_extension_id: str,
    ) -> OrderRef:
        """
        Record an order placement and return the :class:`OrderRef`.

        Idempotency:
            If ``client_extension_id`` was used before, the previously-
            returned :class:`OrderRef` is returned unchanged and the
            call is NOT recorded a second time. This mirrors the real
            Oanda v20 behaviour for repeated ``clientExtensions.id``.

        Args:
            symbol: Tradable instrument. Must be non-empty.
            side: Buy or sell.
            units: Positive integer order size.
            order_type: Market or limit.
            client_extension_id: Caller-supplied idempotency key.
                Must be non-empty.

        Returns:
            The :class:`OrderRef` (new or previously-issued).

        Raises:
            ValueError: If ``symbol`` or ``client_extension_id`` is
                empty, or ``units`` is non-positive.
        """
        # Argument validation. We deliberately raise ValueError rather
        # than letting Pydantic do it on OrderRef construction so the
        # error message names the offending argument.
        if not symbol:
            raise ValueError("symbol must be non-empty")
        if not client_extension_id:
            raise ValueError("client_extension_id must be non-empty")
        if units <= 0:
            raise ValueError(f"units must be positive; got {units}")
        # order_type is referenced so flake/ruff sees it used; the
        # mock does not branch on order_type today because the
        # IR-layer consumers do not yet care about the distinction.
        # M4.E5's real adapter will route market vs limit differently.
        del order_type

        with self._lock:
            # Idempotency check first -- a re-submission must not
            # record a second placement.
            existing = self._by_extension_id.get(client_extension_id)
            if existing is not None:
                return existing

            broker_order_id = f"MOCK-ORDER-{self._next_order_id}"
            self._next_order_id += 1

            ref = OrderRef(
                broker_order_id=broker_order_id,
                client_extension_id=client_extension_id,
                symbol=symbol,
                side=side,
                units=units,
            )
            self._by_extension_id[client_extension_id] = ref
            self._placed.append(ref)
            return ref

    def cancel_order(self, order_ref: OrderRef) -> None:
        """
        Record a cancellation for ``order_ref``.

        Cancelling the same order twice is a no-op the second time so
        callers can issue cancels defensively. The mock does NOT
        validate that the order was previously placed -- that is the
        execution-service layer's concern, not the IR layer's.

        Args:
            order_ref: The reference to cancel.
        """
        with self._lock:
            # No-op if already cancelled. We compare by broker_order_id
            # rather than by reference equality so the mock survives a
            # serialise / deserialise round-trip in any future test
            # that exercises persistence.
            already = any(c.broker_order_id == order_ref.broker_order_id for c in self._cancelled)
            if already:
                return
            self._cancelled.append(order_ref)

    def get_position(self, symbol: str) -> Position | None:
        """
        Return the seeded position for ``symbol`` or ``None`` when flat.

        Args:
            symbol: Tradable instrument.

        Returns:
            :class:`Position` or ``None``.
        """
        with self._lock:
            return self._positions.get(symbol)

    def get_account_state(self) -> AccountState:
        """
        Return the current seeded account state.

        Returns:
            :class:`AccountState`. Defaults to a documented fictitious
            balance until overridden by :meth:`set_account_state`.
        """
        with self._lock:
            return self._account_state

    # ------------------------------------------------------------------
    # Seeding helpers (tests use these between assertions)
    # ------------------------------------------------------------------

    def set_position(self, symbol: str, position: Position | None) -> None:
        """
        Seed (or clear) the position for ``symbol``.

        Args:
            symbol: Tradable instrument.
            position: New position, or ``None`` to mark flat.
        """
        with self._lock:
            if position is None:
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = position

    def set_account_state(self, state: AccountState) -> None:
        """
        Override the account state returned by :meth:`get_account_state`.

        Args:
            state: New :class:`AccountState`.
        """
        with self._lock:
            self._account_state = state

    def get_pip_size(self, symbol: str) -> Decimal:
        """
        Return the pip size for ``symbol``.

        Convenience method (NOT part of the Protocol -- the IR layer
        gets pip sizes from the market-data provider). Tests that
        want to assert symmetry between the two mocks can call this.

        Args:
            symbol: Tradable instrument.

        Returns:
            Pip size; ``Decimal("0.0001")`` for unknown symbols.
        """
        with self._lock:
            return self._pip_sizes.get(symbol, Decimal("0.0001"))

    # ------------------------------------------------------------------
    # Introspection helpers (test assertions use these)
    # ------------------------------------------------------------------

    def placed_orders(self) -> list[OrderRef]:
        """Return a copy of the placed-order log in chronological order."""
        with self._lock:
            return list(self._placed)

    def cancelled_orders(self) -> list[OrderRef]:
        """Return a copy of the cancelled-order log in chronological order."""
        with self._lock:
            return list(self._cancelled)

    def clear(self) -> None:
        """Wipe placement, cancellation, position, and account state."""
        with self._lock:
            self._by_extension_id.clear()
            self._placed.clear()
            self._cancelled.clear()
            self._positions.clear()
            self._account_state = _DEFAULT_ACCOUNT_STATE
            self._pip_sizes = dict(_DEFAULT_PIP_SIZES)
            self._next_order_id = 1


__all__ = ["MockBrokerAdapter"]

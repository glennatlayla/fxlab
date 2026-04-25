"""
Unit tests for libs.strategy_ir.mocks.mock_broker_adapter.MockBrokerAdapter.

Scope:
    Verify the mock satisfies
    :class:`BrokerAdapterInterface` end-to-end:

        * place_order returns an OrderRef with the right shape and
          appends to the placed-order log.
        * place_order is idempotent on client_extension_id -- the
          same key returns the same ref byte-for-byte and is NOT
          recorded a second time.
        * cancel_order appends to the cancelled-order log; double
          cancellation is a no-op the second time.
        * get_position returns the seeded position or None when flat.
        * get_account_state returns the documented default until
          overridden.
        * Argument validation rejects empty / non-positive inputs.
        * Introspection helpers (placed_orders, cancelled_orders,
          clear) work and return defensive copies.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.strategy_ir.interfaces.broker_adapter_interface import (
    AccountState,
    BrokerAdapterInterface,
    OrderRef,
    OrderSide,
    OrderType,
    Position,
)
from libs.strategy_ir.mocks.mock_broker_adapter import MockBrokerAdapter

# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_mock_satisfies_broker_adapter_protocol() -> None:
    """The mock must satisfy BrokerAdapterInterface structurally."""
    adapter = MockBrokerAdapter()
    assert isinstance(adapter, BrokerAdapterInterface)


# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------


def test_place_order_returns_order_ref_with_expected_shape() -> None:
    """place_order returns a populated OrderRef and records it."""
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="run-42-bar-1234-leg-A",
    )

    assert isinstance(ref, OrderRef)
    assert ref.symbol == "EURUSD"
    assert ref.side is OrderSide.BUY
    assert ref.units == 10_000
    assert ref.client_extension_id == "run-42-bar-1234-leg-A"
    assert ref.broker_order_id == "MOCK-ORDER-1"
    assert adapter.placed_orders() == [ref]


def test_place_order_assigns_sequential_broker_order_ids() -> None:
    """Successive placements get monotonically increasing IDs."""
    adapter = MockBrokerAdapter()
    ref_a = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )
    ref_b = adapter.place_order(
        "GBPUSD",
        OrderSide.SELL,
        2_000,
        order_type=OrderType.LIMIT,
        client_extension_id="ext-B",
    )

    assert ref_a.broker_order_id == "MOCK-ORDER-1"
    assert ref_b.broker_order_id == "MOCK-ORDER-2"


def test_place_order_is_idempotent_on_client_extension_id() -> None:
    """
    Re-submission with the same client_extension_id MUST return the
    original OrderRef byte-for-byte and MUST NOT record a second
    placement (mirrors Oanda v20 clientExtensions.id behaviour).
    """
    adapter = MockBrokerAdapter()
    first = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="dup-key",
    )

    # Even with different other args, the original ref comes back.
    second = adapter.place_order(
        "GBPUSD",
        OrderSide.SELL,
        99_999,
        order_type=OrderType.LIMIT,
        client_extension_id="dup-key",
    )

    assert second is first
    assert second.broker_order_id == first.broker_order_id
    assert adapter.placed_orders() == [first]  # only one recorded


def test_place_order_rejects_empty_symbol() -> None:
    adapter = MockBrokerAdapter()
    with pytest.raises(ValueError, match="symbol"):
        adapter.place_order(
            "",
            OrderSide.BUY,
            1_000,
            order_type=OrderType.MARKET,
            client_extension_id="ext-A",
        )


def test_place_order_rejects_empty_client_extension_id() -> None:
    adapter = MockBrokerAdapter()
    with pytest.raises(ValueError, match="client_extension_id"):
        adapter.place_order(
            "EURUSD",
            OrderSide.BUY,
            1_000,
            order_type=OrderType.MARKET,
            client_extension_id="",
        )


def test_place_order_rejects_non_positive_units() -> None:
    adapter = MockBrokerAdapter()
    with pytest.raises(ValueError, match="units"):
        adapter.place_order(
            "EURUSD",
            OrderSide.BUY,
            0,
            order_type=OrderType.MARKET,
            client_extension_id="ext-A",
        )
    with pytest.raises(ValueError, match="units"):
        adapter.place_order(
            "EURUSD",
            OrderSide.BUY,
            -100,
            order_type=OrderType.MARKET,
            client_extension_id="ext-B",
        )


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


def test_cancel_order_records_cancellation() -> None:
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )

    adapter.cancel_order(ref)
    assert adapter.cancelled_orders() == [ref]


def test_cancel_order_is_no_op_on_repeat() -> None:
    """Cancelling the same order twice records only one cancellation."""
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )

    adapter.cancel_order(ref)
    adapter.cancel_order(ref)
    assert adapter.cancelled_orders() == [ref]


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------


def test_get_position_returns_none_when_flat() -> None:
    adapter = MockBrokerAdapter()
    assert adapter.get_position("EURUSD") is None


def test_get_position_returns_seeded_position() -> None:
    adapter = MockBrokerAdapter()
    pos = Position(
        symbol="EURUSD",
        units=10_000,
        average_price=Decimal("1.1000"),
    )
    adapter.set_position("EURUSD", pos)
    assert adapter.get_position("EURUSD") == pos


def test_set_position_with_none_clears_position() -> None:
    adapter = MockBrokerAdapter()
    pos = Position(symbol="EURUSD", units=10_000, average_price=Decimal("1.1000"))
    adapter.set_position("EURUSD", pos)
    adapter.set_position("EURUSD", None)
    assert adapter.get_position("EURUSD") is None


# ---------------------------------------------------------------------------
# get_account_state
# ---------------------------------------------------------------------------


def test_get_account_state_returns_documented_default() -> None:
    adapter = MockBrokerAdapter()
    state = adapter.get_account_state()
    assert state.account_id == "MOCK-ACCOUNT-0001"
    assert state.balance == Decimal("100000.00")
    assert state.currency == "USD"


def test_set_account_state_overrides_default() -> None:
    adapter = MockBrokerAdapter()
    new_state = AccountState(
        account_id="MOCK-ACCOUNT-9999",
        balance=Decimal("50000.00"),
        unrealized_pl=Decimal("123.45"),
        margin_used=Decimal("1000.00"),
        margin_available=Decimal("49000.00"),
        currency="EUR",
    )
    adapter.set_account_state(new_state)
    assert adapter.get_account_state() == new_state


# ---------------------------------------------------------------------------
# Pip-size convenience method
# ---------------------------------------------------------------------------


def test_get_pip_size_returns_correct_value_for_each_major() -> None:
    adapter = MockBrokerAdapter()
    assert adapter.get_pip_size("EURUSD") == Decimal("0.0001")
    assert adapter.get_pip_size("USDJPY") == Decimal("0.01")
    assert adapter.get_pip_size("NZDUSD") == Decimal("0.0001")


def test_get_pip_size_defaults_for_unknown_symbol() -> None:
    adapter = MockBrokerAdapter()
    assert adapter.get_pip_size("XAUUSD") == Decimal("0.0001")


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def test_placed_orders_returns_defensive_copy() -> None:
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )

    log = adapter.placed_orders()
    log.clear()
    assert adapter.placed_orders() == [ref]


def test_cancelled_orders_returns_defensive_copy() -> None:
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )
    adapter.cancel_order(ref)

    log = adapter.cancelled_orders()
    log.clear()
    assert adapter.cancelled_orders() == [ref]


def test_clear_resets_every_mutable_field() -> None:
    """clear() must wipe placements, cancellations, positions, account state."""
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )
    adapter.cancel_order(ref)
    adapter.set_position(
        "EURUSD",
        Position(symbol="EURUSD", units=1_000, average_price=Decimal("1.1000")),
    )
    adapter.set_account_state(
        AccountState(
            account_id="MOCK-ACCOUNT-9999",
            balance=Decimal("0"),
            unrealized_pl=Decimal("0"),
            margin_used=Decimal("0"),
            margin_available=Decimal("0"),
            currency="EUR",
        )
    )

    adapter.clear()

    assert adapter.placed_orders() == []
    assert adapter.cancelled_orders() == []
    assert adapter.get_position("EURUSD") is None
    assert adapter.get_account_state().account_id == "MOCK-ACCOUNT-0001"

    # Counter resets too, so the next placement is MOCK-ORDER-1 again.
    new_ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-after-clear",
    )
    assert new_ref.broker_order_id == "MOCK-ORDER-1"


# ---------------------------------------------------------------------------
# Value object immutability
# ---------------------------------------------------------------------------


def test_order_ref_is_frozen() -> None:
    adapter = MockBrokerAdapter()
    ref = adapter.place_order(
        "EURUSD",
        OrderSide.BUY,
        1_000,
        order_type=OrderType.MARKET,
        client_extension_id="ext-A",
    )
    with pytest.raises(Exception):  # pydantic ValidationError
        ref.symbol = "GBPUSD"  # type: ignore[misc]

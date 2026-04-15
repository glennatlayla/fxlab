"""
Unit tests for AlpacaMarketStream WebSocket client (real-time market data).

Tests cover:
- Initialization with default/custom timeout config
- Symbol subscription/unsubscription (additive, case normalization)
- Callback registration and dispatch
- Connection status and diagnostics
- Trade message processing and validation
- Message handling (trades, status messages, unknown formats)
- Timestamp parsing (ISO 8601, Z suffix, +00:00 format)
- Lifecycle (start, stop, idempotency)
- Thread safety of shared state
- Callback error handling (one bad callback doesn't kill stream)

Dependencies:
    - services.api.adapters.alpaca_market_stream: AlpacaMarketStream
    - libs.contracts.alpaca_config: AlpacaConfig
    - libs.contracts.execution: PriceUpdate
    - libs.contracts.interfaces.market_stream_interface: MarketStreamInterface
    - services.api.infrastructure.timeout_config: BrokerTimeoutConfig
    - structlog: logging
    - unittest.mock: MagicMock, patch

Example:
    pytest tests/unit/test_alpaca_market_stream.py -v
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.execution import PriceUpdate
from services.api.adapters.alpaca_market_stream import AlpacaMarketStream
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_TEST_CONFIG = AlpacaConfig(
    api_key="PKTEST123456789ABCDEFGH",
    api_secret="secretsecretsecretsecretsecretsecret",
    base_url="https://paper-api.alpaca.markets",
)

_TRADE_MESSAGE_AAPL = {
    "T": "t",
    "S": "AAPL",
    "p": 185.50,
    "s": 100,
    "t": "2026-04-11T14:30:00Z",
    "c": ["@"],
}

_TRADE_MESSAGE_MSFT = {
    "T": "t",
    "S": "MSFT",
    "p": 415.25,
    "s": 50,
    "t": "2026-04-11T14:31:00Z",
    "c": [],
}

_STATUS_MESSAGE = {
    "stream": "listening",
    "data": {
        "streams": ["trades"],
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def timeout_config() -> BrokerTimeoutConfig:
    """Broker timeout configuration for testing."""
    return BrokerTimeoutConfig(
        connect_timeout_s=5.0,
        stream_heartbeat_s=10.0,
    )


@pytest.fixture
def mock_websocket() -> Any:
    """Mock WebSocket connection."""
    ws = MagicMock()
    ws.connected = True
    ws.recv.return_value = json.dumps({"stream": "listening", "data": {}})
    return ws


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamInit
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamInit:
    """Tests for AlpacaMarketStream initialization."""

    def test_init_default_timeout_config_used_when_none_provided(self) -> None:
        """Test that default timeout config is used when none provided."""
        stream = AlpacaMarketStream(config=_TEST_CONFIG)

        assert stream._timeout_config is not None
        assert isinstance(stream._timeout_config, BrokerTimeoutConfig)

    def test_init_custom_timeout_config_stored(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test that custom timeout config is stored."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        assert stream._timeout_config is timeout_config
        assert stream._timeout_config.stream_heartbeat_s == 10.0

    def test_init_initial_state_not_connected_no_symbols_no_messages(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test initial state: not connected, no symbols, no messages."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        assert not stream.is_connected()
        assert len(stream._subscribed_symbols) == 0
        assert stream._messages_received == 0
        assert stream._callbacks == []


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamSubscribe
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamSubscribe:
    """Tests for subscription management."""

    def test_subscribe_adds_symbols(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test that subscribe() adds symbols to _subscribed_symbols."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL", "MSFT"])

        assert "AAPL" in stream._subscribed_symbols
        assert "MSFT" in stream._subscribed_symbols
        assert len(stream._subscribed_symbols) == 2

    def test_subscribe_is_additive(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test that subscribe() is additive (call twice, union of symbols)."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL", "MSFT"])
        stream.subscribe(["GOOG"])

        assert len(stream._subscribed_symbols) == 3
        assert "AAPL" in stream._subscribed_symbols
        assert "MSFT" in stream._subscribed_symbols
        assert "GOOG" in stream._subscribed_symbols

    def test_subscribe_uppercases_symbols(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test that subscribe() uppercases symbols."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["aapl", "msft", "GooG"])

        assert "AAPL" in stream._subscribed_symbols
        assert "MSFT" in stream._subscribed_symbols
        assert "GOOG" in stream._subscribed_symbols
        # Lowercase should not exist
        assert "aapl" not in stream._subscribed_symbols

    def test_unsubscribe_removes_symbols(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test that unsubscribe() removes symbols."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL", "MSFT", "GOOG"])
        assert len(stream._subscribed_symbols) == 3

        stream.unsubscribe(["MSFT"])

        assert len(stream._subscribed_symbols) == 2
        assert "AAPL" in stream._subscribed_symbols
        assert "GOOG" in stream._subscribed_symbols
        assert "MSFT" not in stream._subscribed_symbols


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamCallbacks
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamCallbacks:
    """Tests for callback registration and management."""

    def test_register_callback_stores_callback_in_list(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that register_callback() stores callback in list."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        def my_callback(update: PriceUpdate) -> None:
            pass

        stream.register_callback(my_callback)

        assert len(stream._callbacks) == 1
        assert my_callback in stream._callbacks

    def test_register_callback_multiple_callbacks_can_be_registered(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that multiple callbacks can be registered."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        def callback1(update: PriceUpdate) -> None:
            pass

        def callback2(update: PriceUpdate) -> None:
            pass

        def callback3(update: PriceUpdate) -> None:
            pass

        stream.register_callback(callback1)
        stream.register_callback(callback2)
        stream.register_callback(callback3)

        assert len(stream._callbacks) == 3
        assert callback1 in stream._callbacks
        assert callback2 in stream._callbacks
        assert callback3 in stream._callbacks

    def test_register_callback_count_matches_registrations(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that callback count matches registrations."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        callbacks = [lambda u: None for _ in range(5)]

        for cb in callbacks:
            stream.register_callback(cb)

        assert len(stream._callbacks) == 5


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamStatus
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamStatus:
    """Tests for connection status and diagnostics."""

    def test_is_connected_returns_false_initially(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that is_connected() returns False initially."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        assert stream.is_connected() is False

    def test_diagnostics_returns_correct_structure_with_all_keys(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that diagnostics() returns correct structure with all keys."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        diag = stream.diagnostics()

        assert isinstance(diag, dict)
        assert "connected" in diag
        assert "subscribed_symbols" in diag
        assert "messages_received" in diag
        assert "last_message_at" in diag
        assert "reconnect_count" in diag
        assert "uptime_seconds" in diag

    def test_diagnostics_has_zero_messages_received_initially(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test that diagnostics() has zero messages_received initially."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        diag = stream.diagnostics()

        assert diag["messages_received"] == 0
        assert diag["last_message_at"] is None


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamTradeProcessing
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamTradeProcessing:
    """Tests for trade message processing."""

    def test_process_trade_message_with_valid_trade_dispatches_to_callback(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() with valid trade dispatches to callback."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []

        def callback(update: PriceUpdate) -> None:
            captured_updates.append(update)

        stream.register_callback(callback)
        stream._process_trade_message(_TRADE_MESSAGE_AAPL)

        assert len(captured_updates) == 1
        update = captured_updates[0]
        assert update.symbol == "AAPL"
        assert update.price == Decimal("185.50")
        assert update.size == 100

    def test_process_trade_message_with_non_trade_type_no_dispatch(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() with non-trade type (T != "t") ignores."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        # Message with T="q" (quote) instead of T="t" (trade)
        quote_message = {
            "T": "q",
            "S": "AAPL",
            "p": 185.50,
            "s": 100,
            "t": "2026-04-11T14:30:00Z",
        }

        stream._process_trade_message(quote_message)

        assert len(captured_updates) == 0

    def test_process_trade_message_with_missing_symbol_no_dispatch(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() with missing symbol ignores."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        # Message missing "S" field
        invalid_message = {
            "T": "t",
            "p": 185.50,
            "s": 100,
            "t": "2026-04-11T14:30:00Z",
        }

        stream._process_trade_message(invalid_message)

        assert len(captured_updates) == 0

    def test_process_trade_message_with_missing_price_no_dispatch(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() with missing price ignores."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        # Message missing "p" field
        invalid_message = {
            "T": "t",
            "S": "AAPL",
            "s": 100,
            "t": "2026-04-11T14:30:00Z",
        }

        stream._process_trade_message(invalid_message)

        assert len(captured_updates) == 0

    def test_process_trade_message_increments_messages_received_counter(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() increments messages_received counter."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        assert stream._messages_received == 0

        stream._process_trade_message(_TRADE_MESSAGE_AAPL)
        assert stream._messages_received == 1

        stream._process_trade_message(_TRADE_MESSAGE_MSFT)
        assert stream._messages_received == 2

    def test_process_trade_message_handles_callback_exception_gracefully(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() handles callback exception gracefully."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        successful_calls: list[PriceUpdate] = []

        def failing_callback(update: PriceUpdate) -> None:
            raise ValueError("Intentional test failure")

        def successful_callback(update: PriceUpdate) -> None:
            successful_calls.append(update)

        stream.register_callback(failing_callback)
        stream.register_callback(successful_callback)

        # Should not raise even though failing_callback raises
        stream._process_trade_message(_TRADE_MESSAGE_AAPL)

        # Successful callback should still have been called
        assert len(successful_calls) == 1


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamHandleMessage
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamHandleMessage:
    """Tests for message handling."""

    def test_handle_message_with_list_of_trades_processes_each(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _handle_message() with list of trades processes each."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        message_list = [_TRADE_MESSAGE_AAPL, _TRADE_MESSAGE_MSFT]
        stream._handle_message(message_list)

        assert len(captured_updates) == 2
        assert captured_updates[0].symbol == "AAPL"
        assert captured_updates[1].symbol == "MSFT"

    def test_handle_message_with_status_dict_logs_and_ignores(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _handle_message() with status dict ignores."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        stream._handle_message(_STATUS_MESSAGE)

        assert len(captured_updates) == 0

    def test_handle_message_with_unknown_format_no_crash(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _handle_message() with unknown format doesn't crash."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        # Unknown format: not a list, not a recognized status dict
        unknown_message = {
            "something": "unexpected",
            "data": {"field": "value"},
        }

        # Should not raise
        stream._handle_message(unknown_message)

        assert len(captured_updates) == 0


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamTimestamp
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamTimestamp:
    """Tests for timestamp parsing."""

    def test_parse_timestamp_handles_z_suffix_correctly(self) -> None:
        """Test _parse_timestamp() handles "Z" suffix correctly."""
        result = AlpacaMarketStream._parse_timestamp("2026-04-11T14:30:00Z")

        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 11
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 0
        assert result.tzinfo == timezone.utc

    def test_parse_timestamp_handles_plus_00_00_suffix(self) -> None:
        """Test _parse_timestamp() handles "+00:00" suffix."""
        result = AlpacaMarketStream._parse_timestamp("2026-04-11T14:30:00+00:00")

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_parse_timestamp_raises_on_empty_string(self) -> None:
        """Test _parse_timestamp() raises on empty string."""
        with pytest.raises(ValueError):
            AlpacaMarketStream._parse_timestamp("")

    def test_parse_timestamp_raises_on_invalid_string(self) -> None:
        """Test _parse_timestamp() raises on invalid string."""
        with pytest.raises(ValueError):
            AlpacaMarketStream._parse_timestamp("not a valid timestamp")


# ---------------------------------------------------------------------------
# TestAlpacaMarketStreamLifecycle
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamLifecycle:
    """Tests for lifecycle management (start, stop)."""

    def test_start_sets_running_flag(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test start() sets _running flag."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        assert not stream._running

        with patch("threading.Thread") as mock_thread_class:
            stream.start()

            assert stream._running
            mock_thread_class.assert_called_once()

    def test_stop_clears_running_and_authenticated_flags(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test stop() clears _running and _authenticated flags."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        with patch("threading.Thread"):
            stream.start()
            assert stream._running

        stream.stop()

        assert not stream._running
        assert not stream._authenticated

    def test_start_is_idempotent(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test start() is idempotent (second call is no-op)."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        with patch("threading.Thread") as mock_thread_class:
            stream.start()
            call_count_first = mock_thread_class.call_count

            stream.start()
            call_count_second = mock_thread_class.call_count

            # Thread should only be created once
            assert call_count_first == call_count_second == 1


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_process_trade_with_zero_size(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test _process_trade_message() handles zero size."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        message_zero_size = {
            "T": "t",
            "S": "AAPL",
            "p": 185.50,
            "s": 0,
            "t": "2026-04-11T14:30:00Z",
        }

        stream._process_trade_message(message_zero_size)

        assert len(captured_updates) == 1
        assert captured_updates[0].size == 0

    def test_process_trade_with_large_price(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test _process_trade_message() handles large prices."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        message_large_price = {
            "T": "t",
            "S": "BRK.A",
            "p": 598765.50,
            "s": 1,
            "t": "2026-04-11T14:30:00Z",
        }

        stream._process_trade_message(message_large_price)

        assert len(captured_updates) == 1
        assert captured_updates[0].price == Decimal("598765.50")

    def test_process_trade_with_missing_timestamp_ignores(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test _process_trade_message() with missing timestamp ignores."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        message_no_timestamp = {
            "T": "t",
            "S": "AAPL",
            "p": 185.50,
            "s": 100,
        }

        stream._process_trade_message(message_no_timestamp)

        assert len(captured_updates) == 0

    def test_subscribe_with_empty_list_is_noop(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test subscribe() with empty list is no-op."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL"])
        assert len(stream._subscribed_symbols) == 1

        stream.subscribe([])
        assert len(stream._subscribed_symbols) == 1

    def test_unsubscribe_with_empty_list_is_noop(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test unsubscribe() with empty list is no-op."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL", "MSFT"])
        assert len(stream._subscribed_symbols) == 2

        stream.unsubscribe([])
        assert len(stream._subscribed_symbols) == 2

    def test_diagnostics_with_subscribed_symbols(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test diagnostics() returns subscribed symbols."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        stream.subscribe(["AAPL", "MSFT", "GOOG"])

        diag = stream.diagnostics()

        assert "subscribed_symbols" in diag
        assert len(diag["subscribed_symbols"]) == 3
        assert "AAPL" in diag["subscribed_symbols"]
        assert "MSFT" in diag["subscribed_symbols"]
        assert "GOOG" in diag["subscribed_symbols"]

    def test_process_trade_with_conditions_list(self, timeout_config: BrokerTimeoutConfig) -> None:
        """Test _process_trade_message() preserves conditions list."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        captured_updates: list[PriceUpdate] = []
        stream.register_callback(lambda u: captured_updates.append(u))

        message_with_conditions = {
            "T": "t",
            "S": "AAPL",
            "p": 185.50,
            "s": 100,
            "t": "2026-04-11T14:30:00Z",
            "c": ["@", "O"],
        }

        stream._process_trade_message(message_with_conditions)

        assert len(captured_updates) == 1
        assert captured_updates[0].conditions == ["@", "O"]

    def test_thread_safety_concurrent_subscribe_and_callback_registration(
        self, timeout_config: BrokerTimeoutConfig
    ) -> None:
        """Test thread safety with concurrent subscribe and callback registration."""
        stream = AlpacaMarketStream(
            config=_TEST_CONFIG,
            timeout_config=timeout_config,
        )

        def register_callbacks() -> None:
            for i in range(10):
                stream.register_callback(lambda u, idx=i: None)

        def subscribe_symbols() -> None:
            for i in range(10):
                stream.subscribe([f"SYM{i}"])

        thread1 = threading.Thread(target=register_callbacks)
        thread2 = threading.Thread(target=subscribe_symbols)

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # Both operations should complete without error
        assert len(stream._callbacks) >= 10
        assert len(stream._subscribed_symbols) >= 10

    def test_parse_timestamp_with_microseconds(self) -> None:
        """Test _parse_timestamp() handles microseconds."""
        result = AlpacaMarketStream._parse_timestamp("2026-04-11T14:30:00.123456Z")

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

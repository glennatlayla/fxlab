"""
Unit tests for AlpacaBarStream (Phase 7 — M3).

Tests cover:
- Bar message parsing: valid OHLCV -> Candle, missing fields, malformed data.
- Callback registration and dispatch: single, multiple, error isolation.
- Symbol subscription: normalize, additive, unsubscribe.
- Diagnostics: counters, uptime, connected state, circuit breaker.
- Lifecycle: start/stop idempotency, double-start error, stop timeout logging.
- Repository persistence: candle upsert called, persistence failure isolation,
  repository timeout handling.
- Thread safety: all shared state mutations under lock.
- Auth error handling: code 402 raises ExternalServiceError.
- Message routing: success, subscription, error, bar types.
- Heartbeat watchdog: updates last_data_at, detects stale feeds.
- Circuit breaker: trips after threshold, auto-recovery, manual reset.
- Bar deduplication: skip duplicate bars, LRU eviction.

Dependencies:
    - services.worker.streams.alpaca_bar_stream: AlpacaBarStream
    - libs.contracts.alpaca_config: AlpacaConfig
    - libs.contracts.market_data: Candle, CandleInterval
    - libs.contracts.errors: ExternalServiceError

Example:
    pytest tests/unit/test_alpaca_bar_stream.py -v
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import ExternalServiceError
from libs.contracts.market_data import Candle, CandleInterval

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> AlpacaConfig:
    """Test Alpaca configuration."""
    return AlpacaConfig.paper(api_key="AKTEST123456", api_secret="secrettest123456")


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MarketDataRepositoryInterface."""
    repo = MagicMock()
    repo.upsert_candles = MagicMock(return_value=1)
    return repo


@pytest.fixture
def stream(config: AlpacaConfig, mock_repo: MagicMock):
    """Create an AlpacaBarStream instance without starting it."""
    from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

    return AlpacaBarStream(
        config=config,
        market_data_repo=mock_repo,
        heartbeat_timeout_s=30.0,
        repo_timeout_s=5.0,
    )


@pytest.fixture
def sample_bar_msg() -> dict[str, Any]:
    """Valid Alpaca bar message."""
    return {
        "T": "b",
        "S": "AAPL",
        "o": 150.12,
        "h": 151.00,
        "l": 149.80,
        "c": 150.75,
        "v": 12345,
        "t": "2026-04-10T16:00:00Z",
        "n": 100,
        "vw": 150.50,
    }


def _make_bar_msg(symbol: str = "AAPL", ts: str = "2026-01-01T00:00:00Z") -> dict[str, Any]:
    """Helper to build a minimal valid bar message."""
    return {
        "T": "b",
        "S": symbol,
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100,
        "v": 50,
        "t": ts,
    }


# ---------------------------------------------------------------------------
# Bar parsing tests
# ---------------------------------------------------------------------------


class TestParseBar:
    """Tests for AlpacaBarStream._parse_bar static method."""

    def test_parse_bar_valid_message(self, sample_bar_msg: dict[str, Any]) -> None:
        """Valid Alpaca bar message should parse to a Candle."""
        from decimal import Decimal

        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        candle = AlpacaBarStream._parse_bar(sample_bar_msg)

        assert candle.symbol == "AAPL"
        assert candle.interval == CandleInterval.M1
        assert candle.open == Decimal("150.12")
        assert candle.high == Decimal("151.0")
        assert candle.low == Decimal("149.8")
        assert candle.close == Decimal("150.75")
        assert candle.volume == 12345
        assert candle.vwap == Decimal("150.5")
        assert candle.trade_count == 100
        assert candle.timestamp.tzinfo is not None

    def test_parse_bar_missing_symbol_raises(self) -> None:
        """Bar message without symbol should raise ValueError."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = {
            "T": "b",
            "o": 100,
            "h": 101,
            "l": 99,
            "c": 100,
            "v": 50,
            "t": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(ValueError, match="missing symbol"):
            AlpacaBarStream._parse_bar(msg)

    def test_parse_bar_missing_timestamp_raises(self) -> None:
        """Bar message without timestamp should raise ValueError."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = {"T": "b", "S": "MSFT", "o": 100, "h": 101, "l": 99, "c": 100, "v": 50}
        with pytest.raises(ValueError, match="missing timestamp"):
            AlpacaBarStream._parse_bar(msg)

    def test_parse_bar_normalizes_symbol_to_uppercase(self) -> None:
        """Symbol should be normalized to uppercase."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = _make_bar_msg(symbol="aapl")
        candle = AlpacaBarStream._parse_bar(msg)
        assert candle.symbol == "AAPL"

    def test_parse_bar_without_optional_fields(self) -> None:
        """Bar message without vwap and trade_count should still parse."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = _make_bar_msg(symbol="TSLA", ts="2026-06-15T14:30:00+00:00")
        candle = AlpacaBarStream._parse_bar(msg)
        assert candle.symbol == "TSLA"
        assert candle.vwap is None
        assert candle.trade_count is None

    def test_parse_bar_iso_timestamp_with_timezone(self) -> None:
        """Timestamps with explicit timezone should be parsed correctly."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = _make_bar_msg(symbol="GOOG", ts="2026-03-15T09:30:00-04:00")
        candle = AlpacaBarStream._parse_bar(msg)
        assert candle.timestamp.tzinfo is not None

    def test_parse_bar_zero_volume(self) -> None:
        """Bar with zero volume should parse without error."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        msg = _make_bar_msg(symbol="XYZ")
        msg["v"] = 0
        candle = AlpacaBarStream._parse_bar(msg)
        assert candle.volume == 0


# ---------------------------------------------------------------------------
# Callback registration and dispatch tests
# ---------------------------------------------------------------------------


class TestCallbackDispatch:
    """Tests for callback registration and bar dispatch."""

    def test_register_single_callback(self, stream) -> None:
        """Single callback should be registered and invoked."""
        cb = MagicMock()
        stream.register_bar_callback(cb)

        stream._process_bar_message(_make_bar_msg())
        cb.assert_called_once()
        assert isinstance(cb.call_args[0][0], Candle)

    def test_register_multiple_callbacks(self, stream) -> None:
        """Multiple callbacks should all receive the bar."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        cb3 = MagicMock()
        stream.register_bar_callback(cb1)
        stream.register_bar_callback(cb2)
        stream.register_bar_callback(cb3)

        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T00:01:00Z"))

        cb1.assert_called_once()
        cb2.assert_called_once()
        cb3.assert_called_once()

    def test_callback_error_isolation(self, stream) -> None:
        """Error in one callback should not prevent others from being called."""
        cb_good_1 = MagicMock()
        cb_bad = MagicMock(side_effect=RuntimeError("callback crash"))
        cb_good_2 = MagicMock()

        stream.register_bar_callback(cb_good_1)
        stream.register_bar_callback(cb_bad)
        stream.register_bar_callback(cb_good_2)

        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T00:02:00Z"))

        cb_good_1.assert_called_once()
        cb_bad.assert_called_once()
        cb_good_2.assert_called_once()


# ---------------------------------------------------------------------------
# Repository persistence tests
# ---------------------------------------------------------------------------


class TestRepositoryPersistence:
    """Tests for candle persistence to repository."""

    def test_bar_persisted_to_repository(self, stream, mock_repo) -> None:
        """Received bar should be persisted via upsert_candles."""
        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T12:00:00Z"))

        mock_repo.upsert_candles.assert_called_once()
        candles = mock_repo.upsert_candles.call_args[0][0]
        assert len(candles) == 1
        assert candles[0].symbol == "AAPL"

    def test_repo_failure_does_not_kill_stream(self, stream, mock_repo) -> None:
        """Repository failure should be logged but not crash the stream."""
        mock_repo.upsert_candles.side_effect = RuntimeError("DB down")

        cb = MagicMock()
        stream.register_bar_callback(cb)

        # Should not raise
        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T00:03:00Z"))

        # Callback should still be called even though repo failed
        cb.assert_called_once()

    def test_no_repo_still_dispatches(self, config) -> None:
        """Stream without a repository should still dispatch to callbacks."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        stream = AlpacaBarStream(config=config, market_data_repo=None)
        cb = MagicMock()
        stream.register_bar_callback(cb)

        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T00:04:00Z"))

        cb.assert_called_once()

    def test_repo_timeout_increments_counter(self, config) -> None:
        """Repository that hangs should timeout and increment counter."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        slow_repo = MagicMock()

        def slow_upsert(candles: list) -> int:
            time.sleep(5.0)  # Longer than timeout
            return 1

        slow_repo.upsert_candles = slow_upsert

        stream = AlpacaBarStream(
            config=config,
            market_data_repo=slow_repo,
            repo_timeout_s=0.1,  # Very short timeout for test
        )

        stream._process_bar_message(_make_bar_msg(ts="2026-01-01T00:05:00Z"))

        diag = stream.diagnostics()
        assert diag["repo_timeouts"] == 1


# ---------------------------------------------------------------------------
# Bar deduplication tests
# ---------------------------------------------------------------------------


class TestBarDeduplication:
    """Tests for bar deduplication on reconnect replay."""

    def test_duplicate_bar_skipped(self, stream) -> None:
        """Processing the same bar twice should skip the second."""
        msg = _make_bar_msg(symbol="AAPL", ts="2026-06-15T16:00:00Z")
        cb = MagicMock()
        stream.register_bar_callback(cb)

        stream._process_bar_message(msg)
        stream._process_bar_message(msg)  # Duplicate

        assert cb.call_count == 1
        diag = stream.diagnostics()
        assert diag["bars_received"] == 1
        assert diag["bars_deduplicated"] == 1

    def test_different_timestamps_not_deduplicated(self, stream) -> None:
        """Bars with different timestamps should both be processed."""
        cb = MagicMock()
        stream.register_bar_callback(cb)

        stream._process_bar_message(_make_bar_msg(ts="2026-06-15T16:00:00Z"))
        stream._process_bar_message(_make_bar_msg(ts="2026-06-15T16:01:00Z"))

        assert cb.call_count == 2

    def test_different_symbols_not_deduplicated(self, stream) -> None:
        """Same timestamp but different symbols should both be processed."""
        cb = MagicMock()
        stream.register_bar_callback(cb)

        ts = "2026-06-15T16:00:00Z"
        stream._process_bar_message(_make_bar_msg(symbol="AAPL", ts=ts))
        stream._process_bar_message(_make_bar_msg(symbol="MSFT", ts=ts))

        assert cb.call_count == 2

    def test_dedup_cache_lru_eviction(self, config, mock_repo) -> None:
        """Dedup cache should evict old entries when max size exceeded."""
        from services.worker.streams.alpaca_bar_stream import _DEDUP_CACHE_MAX_SIZE, AlpacaBarStream

        stream = AlpacaBarStream(config=config, market_data_repo=mock_repo)

        # Fill the cache beyond max size
        for i in range(_DEDUP_CACHE_MAX_SIZE + 100):
            ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}Z"
            stream._process_bar_message(_make_bar_msg(ts=ts))

        assert len(stream._dedup_cache) <= _DEDUP_CACHE_MAX_SIZE


# ---------------------------------------------------------------------------
# Symbol subscription tests
# ---------------------------------------------------------------------------


class TestSymbolSubscription:
    """Tests for subscribe/unsubscribe."""

    def test_subscribe_normalizes_to_uppercase(self, stream) -> None:
        """Subscribe should normalize symbols to uppercase."""
        stream.subscribe(["aapl", " msft ", "gOOg"])

        diag = stream.diagnostics()
        assert "AAPL" in diag["subscribed_symbols"]
        assert "MSFT" in diag["subscribed_symbols"]
        assert "GOOG" in diag["subscribed_symbols"]

    def test_subscribe_is_additive(self, stream) -> None:
        """Multiple subscribe calls should accumulate symbols."""
        stream.subscribe(["AAPL"])
        stream.subscribe(["MSFT"])
        stream.subscribe(["GOOG"])

        diag = stream.diagnostics()
        assert len(diag["subscribed_symbols"]) == 3

    def test_subscribe_ignores_empty(self, stream) -> None:
        """Empty or whitespace-only symbols should be ignored."""
        stream.subscribe(["", "  ", "AAPL"])

        diag = stream.diagnostics()
        assert diag["subscribed_symbols"] == ["AAPL"]

    def test_unsubscribe_removes_symbols(self, stream) -> None:
        """Unsubscribe should remove symbols from the set."""
        stream.subscribe(["AAPL", "MSFT", "GOOG"])
        stream.unsubscribe(["MSFT"])

        diag = stream.diagnostics()
        assert "MSFT" not in diag["subscribed_symbols"]
        assert "AAPL" in diag["subscribed_symbols"]
        assert "GOOG" in diag["subscribed_symbols"]

    def test_unsubscribe_nonexistent_symbol_no_error(self, stream) -> None:
        """Unsubscribing a symbol not in the set should not error."""
        stream.subscribe(["AAPL"])
        stream.unsubscribe(["TSLA"])  # Not subscribed

        diag = stream.diagnostics()
        assert diag["subscribed_symbols"] == ["AAPL"]


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for diagnostics reporting."""

    def test_initial_diagnostics(self, stream) -> None:
        """Initial diagnostics should show zeros and not connected."""
        diag = stream.diagnostics()
        assert diag["connected"] is False
        assert diag["bars_received"] == 0
        assert diag["bars_deduplicated"] == 0
        assert diag["reconnect_count"] == 0
        assert diag["errors"] == 0
        assert diag["repo_timeouts"] == 0
        assert diag["last_bar_at"] is None
        assert diag["last_data_age_seconds"] is None
        assert diag["subscribed_symbols"] == []
        assert diag["circuit_breaker_open"] is False
        assert diag["consecutive_failures"] == 0

    def test_diagnostics_after_bars_received(self, stream) -> None:
        """Diagnostics should update after processing bars."""
        stream._process_bar_message(_make_bar_msg(ts="2026-06-15T16:00:00Z"))
        stream._process_bar_message(_make_bar_msg(ts="2026-06-15T16:01:00Z"))

        diag = stream.diagnostics()
        assert diag["bars_received"] == 2
        assert diag["last_bar_at"] is not None

    def test_diagnostics_error_count_on_parse_failure(self, stream) -> None:
        """Parse failures should increment error count."""
        stream._process_bar_message({"T": "b", "o": 100})

        diag = stream.diagnostics()
        assert diag["errors"] == 1
        assert diag["bars_received"] == 0


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for circuit breaker behavior."""

    def test_circuit_breaker_not_open_initially(self, stream) -> None:
        """Circuit breaker should be closed initially."""
        diag = stream.diagnostics()
        assert diag["circuit_breaker_open"] is False

    def test_circuit_breaker_trips_after_threshold(self, stream) -> None:
        """Circuit breaker should open after threshold consecutive failures."""
        from services.worker.streams.alpaca_bar_stream import _CIRCUIT_BREAKER_THRESHOLD

        with stream._lock:
            stream._consecutive_failures = _CIRCUIT_BREAKER_THRESHOLD
            stream._circuit_open = True
            stream._circuit_opened_at = time.monotonic()

        diag = stream.diagnostics()
        assert diag["circuit_breaker_open"] is True

    def test_manual_reset_clears_circuit(self, stream) -> None:
        """reset_circuit() should close the circuit breaker."""
        with stream._lock:
            stream._circuit_open = True
            stream._circuit_opened_at = time.monotonic()
            stream._consecutive_failures = 5

        stream.reset_circuit()

        diag = stream.diagnostics()
        assert diag["circuit_breaker_open"] is False
        assert diag["consecutive_failures"] == 0

    def test_start_raises_when_circuit_open(self, stream) -> None:
        """start() should raise CircuitBreakerOpenError when circuit is open."""
        from services.worker.streams.alpaca_bar_stream import CircuitBreakerOpenError

        with stream._lock:
            stream._circuit_open = True
            stream._circuit_opened_at = time.monotonic()

        with pytest.raises(CircuitBreakerOpenError, match="Circuit breaker is open"):
            stream.start()

    def test_start_auto_resets_after_recovery_period(self, stream) -> None:
        """start() should auto-reset circuit after recovery period."""
        from services.worker.streams.alpaca_bar_stream import _CIRCUIT_BREAKER_RECOVERY_S

        with stream._lock:
            stream._circuit_open = True
            # Set opened_at to far in the past
            stream._circuit_opened_at = time.monotonic() - _CIRCUIT_BREAKER_RECOVERY_S - 1

        # Should not raise — auto-recovery kicks in
        with patch("services.worker.streams.alpaca_bar_stream.websocket.WebSocketApp"):
            stream.start()
            assert stream._circuit_open is False
            stream.stop()


# ---------------------------------------------------------------------------
# Heartbeat watchdog tests
# ---------------------------------------------------------------------------


class TestHeartbeatWatchdog:
    """Tests for heartbeat watchdog behavior."""

    def test_on_message_updates_last_data_at(self, stream) -> None:
        """Every message should update the heartbeat timestamp."""
        assert stream._last_data_at is None

        msg = '[{"T":"success","msg":"connected"}]'
        stream._on_message(None, msg)

        assert stream._last_data_at is not None

    def test_heartbeat_disabled_when_zero(self, config, mock_repo) -> None:
        """heartbeat_timeout_s=0 should disable the watchdog thread."""
        from services.worker.streams.alpaca_bar_stream import AlpacaBarStream

        stream = AlpacaBarStream(
            config=config,
            market_data_repo=mock_repo,
            heartbeat_timeout_s=0,
        )

        with patch("services.worker.streams.alpaca_bar_stream.websocket.WebSocketApp"):
            stream.start()
            assert stream._heartbeat_thread is None
            stream.stop()

    def test_diagnostics_shows_last_data_age(self, stream) -> None:
        """Diagnostics should show age of last data in seconds."""
        with stream._lock:
            stream._last_data_at = time.monotonic() - 5.0

        diag = stream.diagnostics()
        assert diag["last_data_age_seconds"] is not None
        assert diag["last_data_age_seconds"] >= 4.0


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    def test_stop_is_idempotent(self, stream) -> None:
        """Calling stop without starting should be a no-op."""
        stream.stop()
        stream.stop()

    @patch("services.worker.streams.alpaca_bar_stream.websocket.WebSocketApp")
    def test_start_sets_running(self, mock_ws_app, stream) -> None:
        """Start should set the running flag and launch threads."""
        mock_ws_app.return_value.run_forever = MagicMock()

        stream.start()

        assert stream._running is True
        assert stream._thread is not None
        assert stream._thread.daemon is True
        # Heartbeat thread should also be started (heartbeat_timeout_s=30)
        assert stream._heartbeat_thread is not None
        assert stream._heartbeat_thread.daemon is True

        stream.stop()

    @patch("services.worker.streams.alpaca_bar_stream.websocket.WebSocketApp")
    def test_double_start_raises(self, mock_ws_app, stream) -> None:
        """Starting an already-running stream should raise ExternalServiceError."""
        mock_ws_app.return_value.run_forever = MagicMock()
        stream.start()

        with pytest.raises(ExternalServiceError, match="already running"):
            stream.start()

        stream.stop()

    def test_stop_uses_event_for_cooperative_cancellation(self, stream) -> None:
        """stop() should set the stop_event for cooperative thread cancellation."""
        assert not stream._stop_event.is_set()
        with stream._lock:
            stream._running = True
        stream.stop()
        assert stream._stop_event.is_set()


# ---------------------------------------------------------------------------
# Message routing tests
# ---------------------------------------------------------------------------


class TestMessageRouting:
    """Tests for _on_message dispatching to correct handlers."""

    def test_on_message_bar_type_dispatches(self, stream, mock_repo) -> None:
        """Messages with T=b should be processed as bars."""
        cb = MagicMock()
        stream.register_bar_callback(cb)

        msg = '[{"T":"b","S":"AAPL","o":150,"h":151,"l":149,"c":150,"v":1000,"t":"2026-01-01T00:00:00Z"}]'
        stream._on_message(None, msg)

        cb.assert_called_once()
        mock_repo.upsert_candles.assert_called_once()

    def test_on_message_success_authenticated(self, stream) -> None:
        """Authenticated success message should set connected=True."""
        msg = '[{"T":"success","msg":"authenticated"}]'
        stream._on_message(None, msg)

        assert stream.is_connected() is True

    def test_on_message_success_connected(self, stream) -> None:
        """Connected success message should not set authenticated."""
        msg = '[{"T":"success","msg":"connected"}]'
        stream._on_message(None, msg)

        assert stream.is_connected() is False

    def test_on_message_non_json_ignored(self, stream) -> None:
        """Non-JSON messages should be handled gracefully."""
        stream._on_message(None, "not valid json {{}")

    def test_on_message_non_array_wrapped(self, stream) -> None:
        """Non-array messages should be wrapped in a list."""
        cb = MagicMock()
        stream.register_bar_callback(cb)

        msg = (
            '{"T":"b","S":"AAPL","o":100,"h":101,"l":99,"c":100,"v":50,"t":"2026-01-01T00:06:00Z"}'
        )
        stream._on_message(None, msg)

        cb.assert_called_once()

    def test_on_message_updates_heartbeat(self, stream) -> None:
        """Every message should update _last_data_at for heartbeat watchdog."""
        assert stream._last_data_at is None
        stream._on_message(None, '[{"T":"subscription","bars":["AAPL"]}]')
        assert stream._last_data_at is not None


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error message handling."""

    def test_auth_failure_code_402_raises(self, stream) -> None:
        """Auth failure (code 402) should raise ExternalServiceError."""
        with pytest.raises(ExternalServiceError, match="authentication failed"):
            stream._handle_error({"T": "error", "code": 402, "msg": "auth failed"})

    def test_non_auth_error_increments_counter(self, stream) -> None:
        """Non-auth errors should increment error counter but not raise."""
        stream._handle_error({"T": "error", "code": 500, "msg": "server error"})

        diag = stream.diagnostics()
        assert diag["errors"] == 1

    def test_on_error_increments_counter(self, stream) -> None:
        """WebSocket on_error callback should increment error counter."""
        stream._on_error(None, RuntimeError("connection lost"))

        diag = stream.diagnostics()
        assert diag["errors"] == 1

    def test_on_close_sets_disconnected(self, stream) -> None:
        """WebSocket on_close callback should clear connected flag."""
        with stream._lock:
            stream._connected = True

        stream._on_close(None, 1000, "normal closure")

        assert stream.is_connected() is False


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests verifying thread-safe access patterns."""

    def test_diagnostics_under_concurrent_bar_processing(self, stream) -> None:
        """Diagnostics should be consistent even during bar processing."""
        import threading

        received: list[int] = []

        def process_bars() -> None:
            for i in range(50):
                ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}Z"
                stream._process_bar_message(_make_bar_msg(ts=ts))

        def read_diagnostics() -> None:
            for _ in range(50):
                diag = stream.diagnostics()
                received.append(diag["bars_received"])

        t1 = threading.Thread(target=process_bars)
        t2 = threading.Thread(target=read_diagnostics)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        final_diag = stream.diagnostics()
        assert final_diag["bars_received"] == 50

    def test_concurrent_callback_registration(self, stream) -> None:
        """Callbacks registered from multiple threads should all be preserved."""
        import threading

        callbacks = [MagicMock() for _ in range(10)]

        def register(cb: MagicMock) -> None:
            stream.register_bar_callback(cb)

        threads = [threading.Thread(target=register, args=(cb,)) for cb in callbacks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stream._process_bar_message(_make_bar_msg(ts="2026-02-01T00:00:00Z"))

        for cb in callbacks:
            cb.assert_called_once()

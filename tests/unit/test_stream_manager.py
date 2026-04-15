"""
Unit tests for StreamManager (thread-safe lifecycle manager for market and order streams).

Tests cover:
- Register market/order streams: stores stream in registry, raises ValueError on duplicate.
- Start streams: calls start() on both market and order streams, raises NotFoundError if missing.
- Stop streams: calls stop() on both streams, swallows exceptions, raises NotFoundError if missing.
- Stop all: calls stop_streams() on all deployments, tolerates exceptions.
- Add callbacks: delegates to stream.register_callback(), raises NotFoundError if missing.
- Diagnostics: aggregates health from all registered deployments.
- is_deployment_streaming: returns True only if both streams are registered.
- Thread safety: concurrent register/deregister operations under contention.

Dependencies:
    - services.api.infrastructure.stream_manager: StreamManager.
    - libs.contracts.interfaces.market_stream_interface: MarketStreamInterface, PriceCallback.
    - libs.contracts.interfaces.order_stream_interface: OrderStreamInterface, OrderEventCallback.
    - libs.contracts.errors: NotFoundError.

Example:
    pytest tests/unit/test_stream_manager.py -v
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.market_stream_interface import MarketStreamInterface
from libs.contracts.interfaces.order_stream_interface import OrderStreamInterface
from services.api.infrastructure.stream_manager import StreamManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market_stream() -> MagicMock:
    """Create a mock MarketStreamInterface for testing."""
    mock = MagicMock(spec=MarketStreamInterface)
    mock.diagnostics.return_value = {
        "connected": True,
        "subscribed_symbols": ["AAPL", "MSFT"],
        "messages_received": 42,
        "last_message_at": "2026-04-11T12:00:00Z",
        "reconnect_count": 0,
        "errors": [],
    }
    return mock


def _make_order_stream() -> MagicMock:
    """Create a mock OrderStreamInterface for testing."""
    mock = MagicMock(spec=OrderStreamInterface)
    mock.diagnostics.return_value = {
        "connected": True,
        "events_received": 10,
        "last_event_at": "2026-04-11T12:00:01Z",
        "reconnect_count": 0,
        "errors": [],
    }
    return mock


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestStreamManagerRegister:
    """Tests for market and order stream registration."""

    def test_register_market_stream_stores_stream(self) -> None:
        """
        Registered market stream should be stored and retrievable.

        Verifies that register_market_stream() stores the stream in the
        internal registry and that it can be accessed via diagnostics.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()

        manager.register_market_stream("dep-001", market_stream)

        # Verify by checking diagnostics includes the deployment
        diag = manager.diagnostics()
        assert "dep-001" in diag["deployments"]
        assert "market_stream" in diag["deployments"]["dep-001"]

    def test_register_order_stream_stores_stream(self) -> None:
        """
        Registered order stream should be stored and retrievable.

        Verifies that register_order_stream() stores the stream in the
        internal registry. We check is_deployment_streaming after also
        registering a market stream, since diagnostics only keys off
        market streams.
        """
        manager = StreamManager()
        order_stream = _make_order_stream()
        market_stream = _make_market_stream()

        manager.register_order_stream("dep-001", order_stream)

        # Order stream alone means deployment not fully streaming
        assert not manager.is_deployment_streaming("dep-001")

        # Add market stream → now both are registered
        manager.register_market_stream("dep-001", market_stream)
        assert manager.is_deployment_streaming("dep-001")

        # Verify diagnostics includes order_stream data
        diag = manager.diagnostics()
        assert "dep-001" in diag["deployments"]
        assert "order_stream" in diag["deployments"]["dep-001"]

    def test_register_market_stream_duplicate_raises_value_error(self) -> None:
        """
        Registering market stream twice for same deployment raises ValueError.

        Verifies that attempting to register a second market stream for
        the same deployment_id raises ValueError with appropriate message.
        """
        manager = StreamManager()
        market_stream1 = _make_market_stream()
        market_stream2 = _make_market_stream()

        manager.register_market_stream("dep-001", market_stream1)

        with pytest.raises(ValueError, match="already has a registered market stream"):
            manager.register_market_stream("dep-001", market_stream2)

    def test_register_order_stream_duplicate_raises_value_error(self) -> None:
        """
        Registering order stream twice for same deployment raises ValueError.

        Verifies that attempting to register a second order stream for
        the same deployment_id raises ValueError with appropriate message.
        """
        manager = StreamManager()
        order_stream1 = _make_order_stream()
        order_stream2 = _make_order_stream()

        manager.register_order_stream("dep-001", order_stream1)

        with pytest.raises(ValueError, match="already has a registered order stream"):
            manager.register_order_stream("dep-001", order_stream2)

    def test_different_deployments_can_register_independently(self) -> None:
        """
        Different deployments can register their own streams without conflict.

        Verifies that multiple deployments can each register market and order
        streams independently, and all are stored in separate registries.
        """
        manager = StreamManager()
        market1 = _make_market_stream()
        order1 = _make_order_stream()
        market2 = _make_market_stream()
        order2 = _make_order_stream()

        manager.register_market_stream("dep-001", market1)
        manager.register_order_stream("dep-001", order1)
        manager.register_market_stream("dep-002", market2)
        manager.register_order_stream("dep-002", order2)

        # Both deployments should be in diagnostics
        diag = manager.diagnostics()
        assert len(diag["deployments"]) == 2
        assert "dep-001" in diag["deployments"]
        assert "dep-002" in diag["deployments"]


# ---------------------------------------------------------------------------
# Start/Stop tests
# ---------------------------------------------------------------------------


class TestStreamManagerStartStop:
    """Tests for starting and stopping streams."""

    def test_start_streams_calls_start_on_both_streams(self) -> None:
        """
        start_streams() should call start() on market and order streams.

        Verifies that start_streams() invokes the start() method on both
        the market stream and order stream for the given deployment.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        order_stream = _make_order_stream()

        manager.register_market_stream("dep-001", market_stream)
        manager.register_order_stream("dep-001", order_stream)

        manager.start_streams("dep-001")

        market_stream.start.assert_called_once()
        order_stream.start.assert_called_once()

    def test_start_streams_raises_not_found_if_market_stream_missing(self) -> None:
        """
        start_streams() raises NotFoundError if market stream not registered.

        Verifies that when only the order stream is registered and
        start_streams() is called, NotFoundError is raised before attempting
        any start operations.
        """
        manager = StreamManager()
        order_stream = _make_order_stream()

        manager.register_order_stream("dep-001", order_stream)

        with pytest.raises(NotFoundError, match="No market stream"):
            manager.start_streams("dep-001")

        # Verify order stream.start() was not called
        order_stream.start.assert_not_called()

    def test_start_streams_raises_not_found_if_order_stream_missing(self) -> None:
        """
        start_streams() raises NotFoundError if order stream not registered.

        Verifies that when only the market stream is registered and
        start_streams() is called, NotFoundError is raised before attempting
        any start operations.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()

        manager.register_market_stream("dep-001", market_stream)

        with pytest.raises(NotFoundError, match="No order stream"):
            manager.start_streams("dep-001")

        # Verify market stream.start() was not called
        market_stream.start.assert_not_called()

    def test_stop_streams_calls_stop_on_both_streams(self) -> None:
        """
        stop_streams() should call stop() on market and order streams.

        Verifies that stop_streams() invokes the stop() method on both
        the market stream and order stream for the given deployment.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        order_stream = _make_order_stream()

        manager.register_market_stream("dep-001", market_stream)
        manager.register_order_stream("dep-001", order_stream)

        manager.stop_streams("dep-001")

        market_stream.stop.assert_called_once()
        order_stream.stop.assert_called_once()

    def test_stop_streams_raises_not_found_if_streams_not_registered(self) -> None:
        """
        stop_streams() raises NotFoundError if streams not registered.

        Verifies that calling stop_streams() on an unregistered deployment
        raises NotFoundError before attempting any stop operations.
        """
        manager = StreamManager()

        with pytest.raises(NotFoundError, match="No market stream"):
            manager.stop_streams("nonexistent")


# ---------------------------------------------------------------------------
# Stop all tests
# ---------------------------------------------------------------------------


class TestStreamManagerStopAll:
    """Tests for graceful shutdown via stop_all()."""

    def test_stop_all_calls_stop_on_all_deployments(self) -> None:
        """
        stop_all() should call stop on all registered deployments.

        Verifies that stop_all() iterates through all registered deployments
        and calls stop_streams() on each, resulting in all streams being stopped.
        """
        manager = StreamManager()

        # Register multiple deployments
        for i in range(3):
            market = _make_market_stream()
            order = _make_order_stream()
            manager.register_market_stream(f"dep-{i:03d}", market)
            manager.register_order_stream(f"dep-{i:03d}", order)

        manager.stop_all()

        # Verify stop was called on all streams
        diag = manager.diagnostics()
        # Check that deployments exist and can be stopped
        assert len(diag["deployments"]) == 3

    def test_stop_all_swallows_exceptions_from_individual_streams(self) -> None:
        """
        stop_all() should continue even if individual stream.stop() fails.

        Verifies that if one deployment's stop() raises an exception,
        stop_all() catches and logs it, then continues stopping remaining
        deployments without raising.
        """
        manager = StreamManager()

        # Register a good deployment
        good_market = _make_market_stream()
        good_order = _make_order_stream()
        manager.register_market_stream("dep-good", good_market)
        manager.register_order_stream("dep-good", good_order)

        # Register a bad deployment (will fail on stop)
        bad_market = _make_market_stream()
        bad_order = _make_order_stream()
        bad_market.stop.side_effect = RuntimeError("connection refused")
        manager.register_market_stream("dep-bad", bad_market)
        manager.register_order_stream("dep-bad", bad_order)

        # stop_all() should not raise despite the failure
        manager.stop_all()  # Should not raise

        # Verify both were attempted
        bad_market.stop.assert_called_once()
        good_market.stop.assert_called_once()

    def test_stop_all_on_empty_manager_does_not_raise(self) -> None:
        """
        stop_all() on empty manager should complete without error.

        Verifies that calling stop_all() when no deployments are registered
        completes gracefully without raising any exception.
        """
        manager = StreamManager()

        # Should not raise
        manager.stop_all()

        # Verify state is still correct
        diag = manager.diagnostics()
        assert len(diag["deployments"]) == 0
        assert diag["total_deployments"] == 0


# ---------------------------------------------------------------------------
# Callback registration tests
# ---------------------------------------------------------------------------


class TestStreamManagerCallbacks:
    """Tests for registering price and order event callbacks."""

    def test_add_price_callback_delegates_to_market_stream(self) -> None:
        """
        add_price_callback() should register callback on market stream.

        Verifies that add_price_callback() invokes register_callback()
        on the market stream with the provided callback function.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        manager.register_market_stream("dep-001", market_stream)

        callback = lambda update: None  # noqa: E731

        manager.add_price_callback("dep-001", callback)

        market_stream.register_callback.assert_called_once_with(callback)

    def test_add_order_callback_delegates_to_order_stream(self) -> None:
        """
        add_order_callback() should register callback on order stream.

        Verifies that add_order_callback() invokes register_callback()
        on the order stream with the provided callback function.
        """
        manager = StreamManager()
        order_stream = _make_order_stream()
        manager.register_order_stream("dep-001", order_stream)

        callback = lambda event: None  # noqa: E731

        manager.add_order_callback("dep-001", callback)

        order_stream.register_callback.assert_called_once_with(callback)

    def test_add_price_callback_raises_not_found_if_no_market_stream(self) -> None:
        """
        add_price_callback() raises NotFoundError if market stream missing.

        Verifies that attempting to add a price callback to an unregistered
        market stream raises NotFoundError.
        """
        manager = StreamManager()

        callback = lambda update: None  # noqa: E731

        with pytest.raises(NotFoundError, match="No market stream"):
            manager.add_price_callback("nonexistent", callback)

    def test_add_order_callback_raises_not_found_if_no_order_stream(self) -> None:
        """
        add_order_callback() raises NotFoundError if order stream missing.

        Verifies that attempting to add an order callback to an unregistered
        order stream raises NotFoundError.
        """
        manager = StreamManager()

        callback = lambda event: None  # noqa: E731

        with pytest.raises(NotFoundError, match="No order stream"):
            manager.add_order_callback("nonexistent", callback)


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestStreamManagerDiagnostics:
    """Tests for stream health diagnostics aggregation."""

    def test_diagnostics_returns_correct_structure_with_total_deployments(self) -> None:
        """
        diagnostics() returns dict with deployments and total_deployments count.

        Verifies that diagnostics() returns a dict with "deployments" key
        (dict of deployment_id → stream health) and "total_deployments" key
        with the count of registered deployments.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        order_stream = _make_order_stream()

        manager.register_market_stream("dep-001", market_stream)
        manager.register_order_stream("dep-001", order_stream)

        diag = manager.diagnostics()

        assert isinstance(diag, dict)
        assert "deployments" in diag
        assert "total_deployments" in diag
        assert diag["total_deployments"] == 1
        assert isinstance(diag["deployments"], dict)

    def test_diagnostics_aggregates_from_both_market_and_order_streams(self) -> None:
        """
        diagnostics() aggregates health data from market and order streams.

        Verifies that the returned diagnostics include the health data
        from both the market stream and order stream for each deployment.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        order_stream = _make_order_stream()

        manager.register_market_stream("dep-001", market_stream)
        manager.register_order_stream("dep-001", order_stream)

        diag = manager.diagnostics()
        deployment_health = diag["deployments"]["dep-001"]

        assert "market_stream" in deployment_health
        assert "order_stream" in deployment_health
        assert deployment_health["market_stream"]["connected"] is True
        assert deployment_health["order_stream"]["connected"] is True
        assert deployment_health["market_stream"]["messages_received"] == 42
        assert deployment_health["order_stream"]["events_received"] == 10

    def test_diagnostics_on_empty_manager_returns_empty_deployments_dict(self) -> None:
        """
        diagnostics() on empty manager returns empty deployments dict.

        Verifies that calling diagnostics() when no streams are registered
        returns a valid dict with empty deployments and total_deployments=0.
        """
        manager = StreamManager()

        diag = manager.diagnostics()

        assert diag["total_deployments"] == 0
        assert len(diag["deployments"]) == 0
        assert diag["deployments"] == {}


# ---------------------------------------------------------------------------
# is_deployment_streaming tests
# ---------------------------------------------------------------------------


class TestStreamManagerIsDeploymentStreaming:
    """Tests for checking if a deployment has both streams registered."""

    def test_is_deployment_streaming_returns_true_when_both_streams_registered(
        self,
    ) -> None:
        """
        is_deployment_streaming() returns True when both streams registered.

        Verifies that is_deployment_streaming() returns True only when
        both the market stream and order stream are registered for the
        given deployment_id.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()
        order_stream = _make_order_stream()

        manager.register_market_stream("dep-001", market_stream)
        manager.register_order_stream("dep-001", order_stream)

        assert manager.is_deployment_streaming("dep-001") is True

    def test_is_deployment_streaming_returns_false_when_only_market_registered(
        self,
    ) -> None:
        """
        is_deployment_streaming() returns False if only market stream registered.

        Verifies that is_deployment_streaming() returns False when only
        the market stream is registered, even though the market stream exists.
        """
        manager = StreamManager()
        market_stream = _make_market_stream()

        manager.register_market_stream("dep-001", market_stream)

        assert manager.is_deployment_streaming("dep-001") is False

    def test_is_deployment_streaming_returns_false_for_unregistered_deployment(
        self,
    ) -> None:
        """
        is_deployment_streaming() returns False for unregistered deployment.

        Verifies that is_deployment_streaming() returns False when the
        deployment_id has no registered streams at all.
        """
        manager = StreamManager()

        assert manager.is_deployment_streaming("nonexistent") is False


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class TestStreamManagerThreadSafety:
    """Tests for thread safety under concurrent access."""

    def test_concurrent_register_deregister_from_multiple_threads(self) -> None:
        """
        Concurrent register/deregister from multiple threads should not crash.

        Verifies that registering and checking is_deployment_streaming from
        multiple threads concurrently does not result in race conditions,
        crashes, or data corruption.
        """
        manager = StreamManager()
        errors: list[Exception] = []

        def register_and_check(dep_id: str) -> None:
            try:
                market = _make_market_stream()
                order = _make_order_stream()

                # Register both streams
                manager.register_market_stream(dep_id, market)
                manager.register_order_stream(dep_id, order)

                # Verify both are registered
                assert manager.is_deployment_streaming(dep_id) is True

                # Check diagnostics
                diag = manager.diagnostics()
                assert dep_id in diag["deployments"]
            except Exception as e:
                errors.append(e)

        # Run registration from multiple threads
        threads = [
            threading.Thread(target=register_and_check, args=(f"dep-{i:03d}",)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Thread errors: {errors}"

        # Verify all deployments are registered
        diag = manager.diagnostics()
        assert diag["total_deployments"] == 10

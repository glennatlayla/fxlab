"""
Unit tests for BrokerAdapterRegistry (M4 — Broker Adapter Registry).

Tests cover:
- Register adapter: calls connect(), stores in registry.
- Deregister adapter: calls disconnect(), removes from registry.
- Get adapter: returns registered adapter, raises NotFoundError if missing.
- Duplicate registration raises ValueError.
- Thread safety: concurrent register/deregister under contention.
- deregister_all: disconnects all adapters, clears registry.
- list_deployments: returns sorted list of registered deployments.
- connect() failure prevents registration.
- disconnect() failure does not prevent deregistration.

Dependencies:
    - services.api.infrastructure.broker_registry: BrokerAdapterRegistry.
    - libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter.
    - libs.contracts.errors: NotFoundError.

Example:
    pytest tests/unit/test_broker_registry.py -v
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter() -> MockBrokerAdapter:
    """Create a MockBrokerAdapter for testing."""
    return MockBrokerAdapter(fill_mode="instant")


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryRegister:
    """Tests for adapter registration."""

    def test_register_stores_adapter(self) -> None:
        """Registered adapter should be retrievable by deployment_id."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()

        registry.register("dep-001", adapter, "mock")

        assert registry.get("dep-001") is adapter
        assert registry.count() == 1

    def test_register_calls_connect(self) -> None:
        """register() should call adapter.connect()."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        adapter.connect = MagicMock()  # type: ignore[method-assign]

        registry.register("dep-001", adapter, "mock")

        adapter.connect.assert_called_once()

    def test_register_duplicate_raises_value_error(self) -> None:
        """Registering the same deployment_id twice should raise ValueError."""
        registry = BrokerAdapterRegistry()
        adapter1 = _make_adapter()
        adapter2 = _make_adapter()

        registry.register("dep-001", adapter1, "mock")

        with pytest.raises(ValueError, match="already registered"):
            registry.register("dep-001", adapter2, "mock")

    def test_register_connect_failure_prevents_registration(self) -> None:
        """If connect() raises, the adapter should NOT be registered."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        adapter.connect = MagicMock(side_effect=ConnectionError("refused"))  # type: ignore[method-assign]

        with pytest.raises(ConnectionError):
            registry.register("dep-001", adapter, "mock")

        assert registry.count() == 0
        assert not registry.is_registered("dep-001")

    def test_register_stores_broker_type(self) -> None:
        """Registered broker_type should be retrievable."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()

        registry.register("dep-001", adapter, "alpaca")

        assert registry.get_broker_type("dep-001") == "alpaca"


# ---------------------------------------------------------------------------
# Deregistration tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryDeregister:
    """Tests for adapter deregistration."""

    def test_deregister_removes_adapter(self) -> None:
        """Deregistered adapter should no longer be retrievable."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        registry.register("dep-001", adapter, "mock")

        registry.deregister("dep-001")

        assert registry.count() == 0
        assert not registry.is_registered("dep-001")

    def test_deregister_calls_disconnect(self) -> None:
        """deregister() should call adapter.disconnect()."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        adapter.disconnect = MagicMock()  # type: ignore[method-assign]
        registry.register("dep-001", adapter, "mock")

        registry.deregister("dep-001")

        adapter.disconnect.assert_called_once()

    def test_deregister_not_found_raises(self) -> None:
        """Deregistering unknown deployment_id should raise NotFoundError."""
        registry = BrokerAdapterRegistry()

        with pytest.raises(NotFoundError, match="not registered"):
            registry.deregister("nonexistent")

    def test_deregister_disconnect_failure_still_removes(self) -> None:
        """disconnect() failure should NOT prevent deregistration."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        adapter.disconnect = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("disconnect failed"),
        )
        registry.register("dep-001", adapter, "mock")

        # Should not raise even though disconnect() failed
        registry.deregister("dep-001")

        assert not registry.is_registered("dep-001")


# ---------------------------------------------------------------------------
# Retrieval tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryGet:
    """Tests for adapter retrieval."""

    def test_get_returns_correct_adapter(self) -> None:
        """get() should return the exact adapter instance that was registered."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        registry.register("dep-001", adapter, "mock")

        assert registry.get("dep-001") is adapter

    def test_get_not_found_raises(self) -> None:
        """get() with unknown deployment_id should raise NotFoundError."""
        registry = BrokerAdapterRegistry()

        with pytest.raises(NotFoundError, match="No broker adapter"):
            registry.get("nonexistent")

    def test_get_broker_type_not_found_raises(self) -> None:
        """get_broker_type() with unknown deployment_id raises NotFoundError."""
        registry = BrokerAdapterRegistry()

        with pytest.raises(NotFoundError):
            registry.get_broker_type("nonexistent")


# ---------------------------------------------------------------------------
# Listing tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryList:
    """Tests for listing registered deployments."""

    def test_list_empty_registry(self) -> None:
        """list_deployments() on empty registry returns empty list."""
        registry = BrokerAdapterRegistry()
        assert registry.list_deployments() == []

    def test_list_single_deployment(self) -> None:
        """list_deployments() returns single deployment info."""
        registry = BrokerAdapterRegistry()
        registry.register("dep-001", _make_adapter(), "mock")

        result = registry.list_deployments()
        assert len(result) == 1
        assert result[0]["deployment_id"] == "dep-001"
        assert result[0]["broker_type"] == "mock"

    def test_list_multiple_sorted(self) -> None:
        """list_deployments() returns entries sorted by deployment_id."""
        registry = BrokerAdapterRegistry()
        registry.register("dep-c", _make_adapter(), "alpaca")
        registry.register("dep-a", _make_adapter(), "mock")
        registry.register("dep-b", _make_adapter(), "paper")

        result = registry.list_deployments()
        ids = [r["deployment_id"] for r in result]
        assert ids == ["dep-a", "dep-b", "dep-c"]

    def test_is_registered_true(self) -> None:
        """is_registered() returns True for registered deployment."""
        registry = BrokerAdapterRegistry()
        registry.register("dep-001", _make_adapter(), "mock")
        assert registry.is_registered("dep-001") is True

    def test_is_registered_false(self) -> None:
        """is_registered() returns False for unknown deployment."""
        registry = BrokerAdapterRegistry()
        assert registry.is_registered("nonexistent") is False


# ---------------------------------------------------------------------------
# Deregister all tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryDeregisterAll:
    """Tests for deregister_all() shutdown method."""

    def test_deregister_all_empty(self) -> None:
        """deregister_all() on empty registry returns 0."""
        registry = BrokerAdapterRegistry()
        assert registry.deregister_all() == 0

    def test_deregister_all_disconnects_all(self) -> None:
        """deregister_all() calls disconnect() on every adapter."""
        registry = BrokerAdapterRegistry()
        adapters = []
        for i in range(3):
            a = _make_adapter()
            a.disconnect = MagicMock()  # type: ignore[method-assign]
            registry.register(f"dep-{i:03d}", a, "mock")
            adapters.append(a)

        count = registry.deregister_all()

        assert count == 3
        assert registry.count() == 0
        for a in adapters:
            a.disconnect.assert_called_once()

    def test_deregister_all_tolerates_disconnect_errors(self) -> None:
        """deregister_all() should continue even if some disconnect() calls fail."""
        registry = BrokerAdapterRegistry()

        good = _make_adapter()
        good.disconnect = MagicMock()  # type: ignore[method-assign]

        bad = _make_adapter()
        bad.disconnect = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("disconnect boom"),
        )

        registry.register("dep-good", good, "mock")
        registry.register("dep-bad", bad, "mock")

        count = registry.deregister_all()

        assert count == 2
        assert registry.count() == 0
        good.disconnect.assert_called_once()
        bad.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class TestBrokerRegistryThreadSafety:
    """Tests for thread safety under concurrent access."""

    def test_concurrent_register_deregister(self) -> None:
        """Registry should handle concurrent register/deregister safely."""
        registry = BrokerAdapterRegistry()
        errors: list[Exception] = []

        def register_and_deregister(dep_id: str) -> None:
            try:
                adapter = _make_adapter()
                registry.register(dep_id, adapter, "mock")
                # Verify it's there
                assert registry.is_registered(dep_id)
                # Deregister
                registry.deregister(dep_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_and_deregister, args=(f"dep-{i:03d}",))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert registry.count() == 0

    def test_concurrent_get_does_not_corrupt(self) -> None:
        """Concurrent get() calls should not corrupt registry state."""
        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()
        registry.register("dep-shared", adapter, "mock")

        results: list[BrokerAdapterInterface] = []

        def get_adapter() -> None:
            for _ in range(100):
                a = registry.get("dep-shared")
                results.append(a)

        threads = [threading.Thread(target=get_adapter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be the same adapter instance
        assert all(r is adapter for r in results)
        assert len(results) == 500


# ---------------------------------------------------------------------------
# Adapter lifecycle integration
# ---------------------------------------------------------------------------


class TestBrokerRegistryLifecycleIntegration:
    """Integration tests for the full register-use-deregister lifecycle."""

    def test_full_lifecycle(self) -> None:
        """Test the complete lifecycle: register → get → use → deregister."""
        from decimal import Decimal

        from libs.contracts.execution import OrderRequest

        registry = BrokerAdapterRegistry()
        adapter = _make_adapter()

        # Register
        registry.register("dep-lifecycle", adapter, "mock")
        assert registry.is_registered("dep-lifecycle")

        # Get and use
        retrieved = registry.get("dep-lifecycle")
        order = OrderRequest(
            client_order_id="lifecycle-001",
            deployment_id="01HDEPLOYLIFECYCLE001",
            strategy_id="01HSTRATLIFECYCLE001",
            correlation_id="corr-lifecycle-001",
            execution_mode="paper",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=Decimal("10"),
            time_in_force="day",
        )
        response = retrieved.submit_order(order)
        assert response.client_order_id == "lifecycle-001"

        # Deregister
        registry.deregister("dep-lifecycle")
        assert not registry.is_registered("dep-lifecycle")

        with pytest.raises(NotFoundError):
            registry.get("dep-lifecycle")

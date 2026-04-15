"""
Unit tests for the signal strategy registry.

Tests cover:
- Registration of strategies.
- Retrieval by strategy_id.
- Listing available strategies.
- Duplicate registration rejection.
- Case-insensitive lookup.
- Thread safety under concurrent registration.
- Unregister behaviour.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
from services.worker.strategies.registry import (
    SignalStrategyRegistry,
    StrategyAlreadyRegisteredError,
    StrategyNotFoundError,
)

# ---------------------------------------------------------------------------
# Helpers — minimal concrete strategy for testing
# ---------------------------------------------------------------------------


def _make_strategy(strategy_id: str, name: str = "Test") -> SignalStrategyInterface:
    """Create a mock strategy with a given strategy_id."""
    mock = MagicMock(spec=SignalStrategyInterface)
    type(mock).strategy_id = property(lambda self: strategy_id)
    type(mock).name = property(lambda self: name)
    type(mock).supported_symbols = property(lambda self: [])
    return mock


# ---------------------------------------------------------------------------
# TestSignalStrategyRegistry
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for registering strategies in the registry."""

    def test_register_strategy_succeeds(self) -> None:
        """Registering a strategy stores it for later retrieval."""
        registry = SignalStrategyRegistry()
        strategy = _make_strategy("strat-sma-cross")

        registry.register(strategy)

        assert registry.get("strat-sma-cross") is strategy

    def test_register_multiple_strategies_succeeds(self) -> None:
        """Multiple distinct strategies can be registered."""
        registry = SignalStrategyRegistry()
        s1 = _make_strategy("strat-1")
        s2 = _make_strategy("strat-2")

        registry.register(s1)
        registry.register(s2)

        assert registry.get("strat-1") is s1
        assert registry.get("strat-2") is s2

    def test_register_duplicate_raises_error(self) -> None:
        """Registering a strategy with the same ID raises StrategyAlreadyRegisteredError."""
        registry = SignalStrategyRegistry()
        s1 = _make_strategy("strat-dup")
        s2 = _make_strategy("strat-dup")

        registry.register(s1)

        with pytest.raises(StrategyAlreadyRegisteredError, match="strat-dup"):
            registry.register(s2)

    def test_register_duplicate_with_force_replaces(self) -> None:
        """Force-registering a duplicate ID replaces the existing strategy."""
        registry = SignalStrategyRegistry()
        s1 = _make_strategy("strat-replace")
        s2 = _make_strategy("strat-replace", name="Replacement")

        registry.register(s1)
        registry.register(s2, force=True)

        assert registry.get("strat-replace") is s2


class TestRetrieval:
    """Tests for retrieving strategies from the registry."""

    def test_get_existing_strategy_returns_instance(self) -> None:
        """Retrieving a registered strategy returns the exact instance."""
        registry = SignalStrategyRegistry()
        strategy = _make_strategy("strat-get")
        registry.register(strategy)

        result = registry.get("strat-get")

        assert result is strategy

    def test_get_missing_strategy_raises_not_found(self) -> None:
        """Retrieving an unregistered strategy raises StrategyNotFoundError."""
        registry = SignalStrategyRegistry()

        with pytest.raises(StrategyNotFoundError, match="nonexistent"):
            registry.get("nonexistent")

    def test_get_is_case_sensitive(self) -> None:
        """Strategy IDs are case-sensitive (no implicit normalization)."""
        registry = SignalStrategyRegistry()
        strategy = _make_strategy("strat-Case")
        registry.register(strategy)

        with pytest.raises(StrategyNotFoundError):
            registry.get("strat-case")


class TestListing:
    """Tests for listing available strategies."""

    def test_list_available_returns_all_ids(self) -> None:
        """list_available returns all registered strategy IDs."""
        registry = SignalStrategyRegistry()
        registry.register(_make_strategy("strat-a"))
        registry.register(_make_strategy("strat-b"))
        registry.register(_make_strategy("strat-c"))

        result = registry.list_available()

        assert sorted(result) == ["strat-a", "strat-b", "strat-c"]

    def test_list_available_empty_registry(self) -> None:
        """list_available returns empty list for empty registry."""
        registry = SignalStrategyRegistry()

        result = registry.list_available()

        assert result == []

    def test_count_returns_number_of_strategies(self) -> None:
        """count() returns the number of registered strategies."""
        registry = SignalStrategyRegistry()
        registry.register(_make_strategy("s1"))
        registry.register(_make_strategy("s2"))

        assert registry.count() == 2


class TestUnregister:
    """Tests for unregistering strategies."""

    def test_unregister_existing_strategy(self) -> None:
        """Unregistering a registered strategy removes it."""
        registry = SignalStrategyRegistry()
        registry.register(_make_strategy("strat-remove"))

        registry.unregister("strat-remove")

        with pytest.raises(StrategyNotFoundError):
            registry.get("strat-remove")

    def test_unregister_missing_strategy_raises(self) -> None:
        """Unregistering a non-existent strategy raises StrategyNotFoundError."""
        registry = SignalStrategyRegistry()

        with pytest.raises(StrategyNotFoundError, match="nonexistent"):
            registry.unregister("nonexistent")


class TestThreadSafety:
    """Tests for thread-safe concurrent access."""

    def test_concurrent_registration_no_data_loss(self) -> None:
        """Concurrent registrations from multiple threads do not lose data."""
        registry = SignalStrategyRegistry()
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def register_one(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                strategy = _make_strategy(f"strat-{idx}")
                registry.register(strategy)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_one, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors during concurrent registration: {errors}"
        assert registry.count() == num_threads

"""
Signal strategy registry — central catalog of available signal strategies.

Responsibilities:
- Maintain a strategy_id → SignalStrategyInterface mapping for runtime dispatch.
- Provide registration, lookup, listing, and unregistration of strategies.
- Thread-safe: uses a lock for all mutations and reads of the internal store.

Does NOT:
- Instantiate strategies (callers create and register them).
- Evaluate signals (strategies do that).
- Persist strategy configuration (infrastructure layer responsibility).

Dependencies:
- libs.contracts.interfaces.signal_strategy: SignalStrategyInterface
- threading: Lock for thread-safe access.

Error conditions:
- StrategyAlreadyRegisteredError: register() called with a duplicate strategy_id.
- StrategyNotFoundError: get() or unregister() called with an unknown strategy_id.

Example:
    from services.worker.strategies.registry import SignalStrategyRegistry

    registry = SignalStrategyRegistry()
    registry.register(my_strategy)
    strategy = registry.get("strat-sma-cross")
    available = registry.list_available()
"""

from __future__ import annotations

import threading

from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StrategyAlreadyRegisteredError(Exception):
    """Raised when attempting to register a strategy with a duplicate ID."""

    def __init__(self, strategy_id: str) -> None:
        super().__init__(
            f"Strategy '{strategy_id}' is already registered. Use force=True to replace it."
        )
        self.strategy_id = strategy_id


class StrategyNotFoundError(Exception):
    """Raised when attempting to retrieve or unregister an unknown strategy."""

    def __init__(self, strategy_id: str) -> None:
        super().__init__(
            f"Strategy '{strategy_id}' is not registered. "
            f"Available: use list_available() to see registered strategies."
        )
        self.strategy_id = strategy_id


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SignalStrategyRegistry:
    """
    Thread-safe registry mapping strategy IDs to SignalStrategyInterface instances.

    Provides the dispatch table for the signal evaluation pipeline. Strategy IDs
    are stored and looked up exactly as provided (case-sensitive).

    Responsibilities:
    - Register strategy instances by their strategy_id property.
    - Retrieve strategy instances by ID.
    - List all registered strategy IDs.
    - Unregister strategies.
    - Thread-safe for concurrent registration and lookup.

    Does NOT:
    - Own strategy lifecycle (callers manage instantiation).
    - Evaluate or persist signals.

    Example:
        registry = SignalStrategyRegistry()
        registry.register(sma_crossover)
        strategy = registry.get("strat-sma-cross")
        ids = registry.list_available()  # ["strat-sma-cross"]
    """

    def __init__(self) -> None:
        self._strategies: dict[str, SignalStrategyInterface] = {}
        self._lock = threading.Lock()

    def register(
        self,
        strategy: SignalStrategyInterface,
        *,
        force: bool = False,
    ) -> None:
        """
        Register a signal strategy.

        The strategy's ``strategy_id`` property is used as the registry key.

        Args:
            strategy: The strategy instance to register.
            force: If True, replace an existing strategy with the same ID.
                   If False (default), raise StrategyAlreadyRegisteredError
                   on duplicate IDs.

        Raises:
            StrategyAlreadyRegisteredError: If a strategy with the same ID
                is already registered and force is False.

        Example:
            registry.register(my_strategy)
            registry.register(replacement, force=True)
        """
        sid = strategy.strategy_id
        with self._lock:
            if sid in self._strategies and not force:
                raise StrategyAlreadyRegisteredError(sid)
            self._strategies[sid] = strategy

    def get(self, strategy_id: str) -> SignalStrategyInterface:
        """
        Retrieve a registered strategy by ID.

        Args:
            strategy_id: The unique strategy identifier.

        Returns:
            The registered SignalStrategyInterface instance.

        Raises:
            StrategyNotFoundError: If no strategy with the given ID exists.

        Example:
            strategy = registry.get("strat-sma-cross")
        """
        with self._lock:
            if strategy_id not in self._strategies:
                raise StrategyNotFoundError(strategy_id)
            return self._strategies[strategy_id]

    def unregister(self, strategy_id: str) -> None:
        """
        Remove a strategy from the registry.

        Args:
            strategy_id: The unique strategy identifier to remove.

        Raises:
            StrategyNotFoundError: If no strategy with the given ID exists.

        Example:
            registry.unregister("strat-sma-cross")
        """
        with self._lock:
            if strategy_id not in self._strategies:
                raise StrategyNotFoundError(strategy_id)
            del self._strategies[strategy_id]

    def list_available(self) -> list[str]:
        """
        List all registered strategy IDs.

        Returns:
            List of strategy_id strings for all registered strategies.

        Example:
            ids = registry.list_available()
            # ["strat-sma-cross", "strat-rsi-revert"]
        """
        with self._lock:
            return list(self._strategies.keys())

    def count(self) -> int:
        """
        Return the number of registered strategies.

        Returns:
            Integer count of registered strategies.

        Example:
            n = registry.count()  # 3
        """
        with self._lock:
            return len(self._strategies)

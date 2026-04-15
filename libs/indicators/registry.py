"""
Indicator registry — central catalog of all available technical indicators.

Responsibilities:
- Maintain a name → IndicatorCalculator mapping for runtime dispatch.
- Provide registration, lookup, and listing of available indicators.
- Thread-safe: uses a lock for concurrent registration/lookup safety.

Does NOT:
- Compute indicators (calculators do that).
- Import specific indicator modules (callers register at init time).
- Manage indicator state (calculators are stateless).

Dependencies:
- libs.contracts.indicator: IndicatorCalculator protocol, IndicatorInfo.
- libs.contracts.errors: IndicatorNotFoundError.
- threading: Lock for thread-safe registration.

Error conditions:
- IndicatorNotFoundError: get() called with unregistered name.
- ValueError: register() called with duplicate name (without force=True).

Example:
    from libs.indicators.registry import IndicatorRegistry

    registry = IndicatorRegistry()
    registry.register("SMA", sma_calculator)
    calc = registry.get("SMA")
    available = registry.list_available()
"""

from __future__ import annotations

import threading

from libs.contracts.errors import IndicatorNotFoundError
from libs.contracts.indicator import IndicatorCalculator, IndicatorInfo


class IndicatorRegistry:
    """
    Thread-safe registry mapping indicator names to calculator instances.

    Provides the dispatch table for IndicatorEngine. All names are stored
    and looked up in uppercase to ensure case-insensitive matching.

    Responsibilities:
    - Register indicator calculators by canonical name.
    - Retrieve calculators by name (case-insensitive).
    - List all registered indicators with metadata.

    Does NOT:
    - Compute indicator values.
    - Hold any mutable per-computation state.

    Dependencies:
    - IndicatorCalculator protocol: calculators must satisfy this.
    - IndicatorInfo: metadata returned by list_available().

    Example:
        registry = IndicatorRegistry()
        registry.register("SMA", sma_calc)
        calc = registry.get("SMA")
        info_list = registry.list_available()
    """

    def __init__(self) -> None:
        self._calculators: dict[str, IndicatorCalculator] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        calculator: IndicatorCalculator,
        *,
        force: bool = False,
    ) -> None:
        """
        Register an indicator calculator under the given name.

        Args:
            name: Canonical indicator name (stored uppercase).
            calculator: Instance satisfying the IndicatorCalculator protocol.
            force: If True, overwrite an existing registration. If False
                (default), raise ValueError on duplicate names.

        Raises:
            ValueError: If name is already registered and force is False.
            TypeError: If calculator does not satisfy IndicatorCalculator protocol.

        Example:
            registry.register("SMA", SMACalculator())
        """
        canonical = name.upper().strip()
        if not canonical:
            raise ValueError("Indicator name must not be empty")

        if not isinstance(calculator, IndicatorCalculator):
            raise TypeError(
                f"Calculator for '{canonical}' does not satisfy IndicatorCalculator protocol. "
                f"It must implement calculate() and info() methods."
            )

        with self._lock:
            if canonical in self._calculators and not force:
                raise ValueError(
                    f"Indicator '{canonical}' is already registered. Use force=True to overwrite."
                )
            self._calculators[canonical] = calculator

    def get(self, name: str) -> IndicatorCalculator:
        """
        Retrieve a registered indicator calculator by name.

        Args:
            name: Indicator name (case-insensitive lookup).

        Returns:
            The IndicatorCalculator instance registered under this name.

        Raises:
            IndicatorNotFoundError: If name is not registered.

        Example:
            calc = registry.get("SMA")
        """
        canonical = name.upper().strip()
        with self._lock:
            if canonical not in self._calculators:
                raise IndicatorNotFoundError(
                    canonical,
                    available=list(self._calculators.keys()),
                )
            return self._calculators[canonical]

    def list_available(self) -> list[IndicatorInfo]:
        """
        List metadata for all registered indicators.

        Returns:
            List of IndicatorInfo, sorted by name, one per registered
            indicator.

        Example:
            for info in registry.list_available():
                print(f"{info.name}: {info.description}")
        """
        with self._lock:
            calculators = list(self._calculators.items())

        result: list[IndicatorInfo] = []
        for _name, calc in sorted(calculators, key=lambda x: x[0]):
            result.append(calc.info())
        return result

    def has(self, name: str) -> bool:
        """
        Check if an indicator is registered.

        Args:
            name: Indicator name (case-insensitive).

        Returns:
            True if registered, False otherwise.
        """
        canonical = name.upper().strip()
        with self._lock:
            return canonical in self._calculators

    def count(self) -> int:
        """
        Return the number of registered indicators.

        Returns:
            Count of registered calculators.
        """
        with self._lock:
            return len(self._calculators)

    def clear(self) -> None:
        """
        Remove all registered indicators.

        Primarily for testing. Production code should not need this.
        """
        with self._lock:
            self._calculators.clear()

    def names(self) -> list[str]:
        """
        Return sorted list of all registered indicator names.

        Returns:
            List of canonical (uppercase) indicator names.
        """
        with self._lock:
            return sorted(self._calculators.keys())

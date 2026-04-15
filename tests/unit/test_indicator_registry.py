"""
Unit tests for the indicator registry.

Validates registration, lookup, listing, case-insensitivity,
duplicate handling, and thread safety of IndicatorRegistry.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import pytest

from libs.contracts.errors import IndicatorNotFoundError
from libs.contracts.indicator import IndicatorInfo
from libs.indicators.registry import IndicatorRegistry

# ---------------------------------------------------------------------------
# Stub calculator for testing (satisfies protocol, minimal logic)
# ---------------------------------------------------------------------------


class _StubCalculator:
    """Minimal IndicatorCalculator for registry tests."""

    def __init__(self, name: str = "STUB", category: str = "test") -> None:
        self._name = name
        self._category = category

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        return close

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(name=self._name, category=self._category)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistryRegistration:
    """Tests for register() behaviour."""

    def test_register_and_retrieve(self) -> None:
        registry = IndicatorRegistry()
        calc = _StubCalculator("SMA")
        registry.register("SMA", calc)
        assert registry.get("SMA") is calc

    def test_register_stores_uppercase(self) -> None:
        registry = IndicatorRegistry()
        calc = _StubCalculator("EMA")
        registry.register("ema", calc)
        assert registry.get("EMA") is calc

    def test_register_duplicate_raises_value_error(self) -> None:
        registry = IndicatorRegistry()
        registry.register("SMA", _StubCalculator("SMA"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register("SMA", _StubCalculator("SMA2"))

    def test_register_duplicate_with_force_overwrites(self) -> None:
        registry = IndicatorRegistry()
        calc1 = _StubCalculator("SMA")
        calc2 = _StubCalculator("SMA_v2")
        registry.register("SMA", calc1)
        registry.register("SMA", calc2, force=True)
        assert registry.get("SMA") is calc2

    def test_register_empty_name_raises_value_error(self) -> None:
        registry = IndicatorRegistry()
        with pytest.raises(ValueError, match="must not be empty"):
            registry.register("", _StubCalculator())

    def test_register_whitespace_name_raises_value_error(self) -> None:
        registry = IndicatorRegistry()
        with pytest.raises(ValueError, match="must not be empty"):
            registry.register("   ", _StubCalculator())

    def test_register_non_protocol_raises_type_error(self) -> None:
        registry = IndicatorRegistry()
        with pytest.raises(TypeError, match="does not satisfy"):
            registry.register("BAD", "not_a_calculator")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    """Tests for get() behaviour."""

    def test_get_case_insensitive(self) -> None:
        registry = IndicatorRegistry()
        calc = _StubCalculator("RSI")
        registry.register("RSI", calc)
        assert registry.get("rsi") is calc
        assert registry.get("Rsi") is calc
        assert registry.get("RSI") is calc

    def test_get_unregistered_raises_indicator_not_found(self) -> None:
        registry = IndicatorRegistry()
        registry.register("SMA", _StubCalculator("SMA"))
        with pytest.raises(IndicatorNotFoundError) as exc_info:
            registry.get("UNKNOWN")
        assert exc_info.value.indicator_name == "UNKNOWN"
        assert "SMA" in exc_info.value.available

    def test_has_returns_true_for_registered(self) -> None:
        registry = IndicatorRegistry()
        registry.register("SMA", _StubCalculator())
        assert registry.has("SMA") is True
        assert registry.has("sma") is True

    def test_has_returns_false_for_unregistered(self) -> None:
        registry = IndicatorRegistry()
        assert registry.has("SMA") is False


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestRegistryListing:
    """Tests for list_available() and metadata."""

    def test_list_available_returns_sorted_info(self) -> None:
        registry = IndicatorRegistry()
        registry.register("RSI", _StubCalculator("RSI", "momentum"))
        registry.register("SMA", _StubCalculator("SMA", "trend"))
        registry.register("ATR", _StubCalculator("ATR", "volatility"))

        available = registry.list_available()
        assert len(available) == 3
        assert [i.name for i in available] == ["ATR", "RSI", "SMA"]

    def test_list_available_empty_registry(self) -> None:
        registry = IndicatorRegistry()
        assert registry.list_available() == []

    def test_count(self) -> None:
        registry = IndicatorRegistry()
        assert registry.count() == 0
        registry.register("SMA", _StubCalculator())
        assert registry.count() == 1
        registry.register("EMA", _StubCalculator())
        assert registry.count() == 2

    def test_names_returns_sorted(self) -> None:
        registry = IndicatorRegistry()
        registry.register("RSI", _StubCalculator())
        registry.register("SMA", _StubCalculator())
        assert registry.names() == ["RSI", "SMA"]

    def test_clear_removes_all(self) -> None:
        registry = IndicatorRegistry()
        registry.register("SMA", _StubCalculator())
        registry.register("EMA", _StubCalculator())
        registry.clear()
        assert registry.count() == 0
        assert registry.list_available() == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestRegistryThreadSafety:
    """Tests for concurrent registry access."""

    def test_concurrent_registration(self) -> None:
        """Multiple threads registering different indicators concurrently."""
        registry = IndicatorRegistry()
        errors: list[Exception] = []

        def register_indicator(name: str) -> None:
            try:
                registry.register(name, _StubCalculator(name))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_indicator, args=(f"IND_{i}",)) for i in range(50)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert registry.count() == 50

    def test_concurrent_get(self) -> None:
        """Multiple threads reading the same indicator concurrently."""
        registry = IndicatorRegistry()
        calc = _StubCalculator("SMA")
        registry.register("SMA", calc)
        results: list[Any] = []

        def get_indicator() -> None:
            results.append(registry.get("SMA"))

        threads = [threading.Thread(target=get_indicator) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is calc for r in results)

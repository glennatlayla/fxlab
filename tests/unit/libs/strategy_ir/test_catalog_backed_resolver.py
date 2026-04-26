"""
Unit tests for libs.strategy_ir.dataset_resolver.CatalogBackedResolver
(the M4.E3 production resolver — wraps DatasetServiceInterface).

Scope:
    Verify that the adapter:
        - implements DatasetResolverInterface,
        - delegates resolve() to the wrapped service's lookup(),
        - preserves the ResolvedDataset round-trip,
        - re-raises DatasetNotFoundError unchanged on miss.

A tiny in-test fake satisfies DatasetServiceInterface so this file is
fully isolated from the SQL service and the database.
"""

from __future__ import annotations

import pytest

from libs.strategy_ir.dataset_resolver import CatalogBackedResolver
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetResolverInterface,
)
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    DatasetServiceInterface,
    ResolvedDataset,
)


class _FakeDatasetService(DatasetServiceInterface):
    """Minimal DatasetServiceInterface implementation for adapter tests."""

    def __init__(self) -> None:
        self._catalog: dict[str, ResolvedDataset] = {}
        self._certified: set[str] = set()
        self.lookup_calls: list[str] = []

    def lookup(self, dataset_ref: str) -> ResolvedDataset:
        self.lookup_calls.append(dataset_ref)
        if dataset_ref not in self._catalog:
            raise DatasetNotFoundError(dataset_ref)
        return self._catalog[dataset_ref]

    def list_known_refs(self) -> list[str]:
        return sorted(self._catalog.keys())

    def register_dataset(
        self,
        dataset_ref: str,
        *,
        symbols: list[str],
        timeframe: str,
        source: str,
        version: str,
    ) -> None:
        self._catalog[dataset_ref] = ResolvedDataset(
            dataset_ref=dataset_ref,
            dataset_id=f"id-{dataset_ref}",
            symbols=list(symbols),
        )

    def is_certified(self, dataset_ref: str) -> bool:
        return dataset_ref in self._certified

    # --- test helpers (not part of the interface) -------------------

    def _force_register(
        self,
        dataset_ref: str,
        dataset_id: str,
        symbols: list[str],
    ) -> None:
        self._catalog[dataset_ref] = ResolvedDataset(
            dataset_ref=dataset_ref,
            dataset_id=dataset_id,
            symbols=list(symbols),
        )


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_implements_resolver_interface() -> None:
    service = _FakeDatasetService()
    resolver = CatalogBackedResolver(service)
    assert isinstance(resolver, DatasetResolverInterface)


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_resolve_delegates_to_service_lookup() -> None:
    service = _FakeDatasetService()
    service._force_register(
        "fx-eurusd-15m-certified-v3",
        dataset_id="01HSEEDID000000000000000001",
        symbols=["EURUSD"],
    )
    resolver = CatalogBackedResolver(service)

    result = resolver.resolve("fx-eurusd-15m-certified-v3")

    assert service.lookup_calls == ["fx-eurusd-15m-certified-v3"]
    assert isinstance(result, ResolvedDataset)
    assert result.dataset_ref == "fx-eurusd-15m-certified-v3"
    assert result.dataset_id == "01HSEEDID000000000000000001"
    assert result.symbols == ["EURUSD"]


def test_resolve_round_trips_multi_symbol_dataset() -> None:
    service = _FakeDatasetService()
    service._force_register(
        "fx-majors-h1-certified-v1",
        dataset_id="01HSEEDID000000000000000002",
        symbols=["EURUSD", "GBPUSD", "USDJPY", "USDCHF"],
    )
    resolver = CatalogBackedResolver(service)

    result = resolver.resolve("fx-majors-h1-certified-v1")
    assert result.symbols == ["EURUSD", "GBPUSD", "USDJPY", "USDCHF"]


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_resolve_propagates_not_found_unchanged() -> None:
    service = _FakeDatasetService()
    resolver = CatalogBackedResolver(service)

    with pytest.raises(DatasetNotFoundError) as excinfo:
        resolver.resolve("never-registered")
    assert excinfo.value.dataset_ref == "never-registered"


def test_resolve_does_not_swallow_unexpected_errors() -> None:
    """If the service raises something unexpected, the adapter does
    not catch it — the route layer's exception handler decides what
    HTTP status to map it to."""

    class _BoomService(_FakeDatasetService):
        def lookup(self, dataset_ref: str) -> ResolvedDataset:
            raise RuntimeError("catalog explosion")

    resolver = CatalogBackedResolver(_BoomService())
    with pytest.raises(RuntimeError, match="catalog explosion"):
        resolver.resolve("anything")

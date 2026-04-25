"""
In-memory dataset resolver (M2.C2 stand-in for the M4.E3 DatasetService).

Purpose:
    Provide a typed, thread-safe :class:`DatasetResolverInterface`
    implementation backed by an in-process map so the
    ``POST /runs/from-ir`` endpoint (M2.C2) is fully functional
    end-to-end without waiting on Track E.

==============================================================================
M4.E3 SWAP POINT -- READ THIS BEFORE EXTENDING
==============================================================================

This adapter is **explicitly transitional**. When Track E milestone
M4.E3 lands (the real :class:`DatasetService` backed by the dataset
catalog tables), the swap is intentionally surgical:

    1.  Implement ``DatasetService`` in
        ``services/api/services/dataset_service.py`` so that it
        satisfies :class:`DatasetResolverInterface`.
    2.  Change the wiring in :mod:`services.api.main` from::

            from libs.strategy_ir.dataset_resolver import (
                InMemoryDatasetResolver,
                seed_default_datasets,
            )
            resolver = InMemoryDatasetResolver()
            seed_default_datasets(resolver)
            set_dataset_resolver(resolver)

        to::

            from services.api.services.dataset_service import DatasetService
            set_dataset_resolver(DatasetService(catalog_repo=catalog_repo))

    3.  Delete this module and its sibling
        ``tests/unit/libs/strategy_ir/test_dataset_resolver.py``.
        No other code needs to change -- the interface, the route,
        and all consumer tests stay identical.

Until M4.E3 ships, this resolver is the single source of truth for
dataset references inside the API process. It is acceptable in the
M2.C2 tranche because:

    *   It satisfies the same interface the real service will
        satisfy. No call site needs to know which implementation is
        active.
    *   It is seeded from the dataset names that already appear in
        the five production experiment plans, so every committed
        plan resolves cleanly.
    *   It is thread-safe via an internal lock, so concurrent route
        handlers cannot corrupt the registry during a request.

==============================================================================

Responsibilities:
    - Hold a name -> :class:`ResolvedDataset` map.
    - Provide ``register()`` for explicit seeding (production
      bootstrap) and a ``seed_default_datasets()`` helper that
      populates the map with the references used by the five
      committed production plans.
    - Implement ``resolve()`` per the interface contract: raise
      :class:`DatasetNotFoundError` on miss.

Does NOT:
    - Touch any database, file system, or network resource.
    - Persist registrations across process restarts -- the registry
      is rebuilt from :func:`seed_default_datasets` on every boot.
    - Validate dataset_ref string shape beyond non-empty (M4.E3 will
      enforce catalog-side rules).

Dependencies:
    - :mod:`libs.strategy_ir.interfaces.dataset_resolver_interface`.
    - :mod:`threading` for the lock.

Example::

    resolver = InMemoryDatasetResolver()
    resolver.register("fx-eurusd-15m-certified-v3", ["EURUSD"])
    resolved = resolver.resolve("fx-eurusd-15m-certified-v3")
    assert resolved.symbols == ["EURUSD"]
"""

from __future__ import annotations

import threading

from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetNotFoundError,
    DatasetResolverInterface,
    ResolvedDataset,
)

# ---------------------------------------------------------------------------
# Default seed map
# ---------------------------------------------------------------------------

#: Dataset references that appear in the five committed production
#: experiment plans under ``Strategy Repo/``. Mapping value is the
#: canonical symbol list the engine should treat the dataset as
#: covering. Once M4.E3 lands the catalog supplies these symbol lists
#: and this constant is deleted alongside the rest of this module.
_DEFAULT_DATASET_SEED: dict[str, list[str]] = {
    # canonical example
    "fx-eurusd-15m-certified-v3": ["EURUSD"],
    # Chan pack
    "fx-majors-h1-certified-v1": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    ],
    "fx-majors-d1-certified-v1": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    ],
    # Lien pack
    "fx-majors-1h-certified-v3": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
    ],
    "fx-majors-4h-certified-v3": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
    ],
}


class InMemoryDatasetResolver(DatasetResolverInterface):
    """
    Thread-safe in-memory implementation of
    :class:`DatasetResolverInterface`.

    Suitable only for the M2.C2 tranche. See the module-level
    "M4.E3 SWAP POINT" banner for the deletion plan.

    Attributes:
        _store: Internal name -> :class:`ResolvedDataset` map.
        _lock: :class:`threading.Lock` guarding writes; reads also
            take the lock to avoid torn dict views under PyPy / GIL
            removal scenarios.
    """

    def __init__(self) -> None:
        self._store: dict[str, ResolvedDataset] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, dataset_ref: str, symbols: list[str]) -> ResolvedDataset:
        """
        Register a dataset reference and return the resolved record.

        Args:
            dataset_ref: Opaque string used by experiment plans.
            symbols: Tradable symbols the dataset covers. Must be
                non-empty.

        Returns:
            The :class:`ResolvedDataset` that was stored.

        Raises:
            ValueError: If ``dataset_ref`` is empty or ``symbols``
                is empty.
        """
        if not dataset_ref:
            raise ValueError("dataset_ref must be non-empty")
        if not symbols:
            raise ValueError("symbols must be non-empty")

        resolved = ResolvedDataset(
            dataset_ref=dataset_ref,
            # M4.E3 swap: the catalog returns a ULID or row PK here;
            # the in-memory adapter uses the ref as an opaque ID.
            dataset_id=dataset_ref,
            symbols=list(symbols),
        )
        with self._lock:
            self._store[dataset_ref] = resolved
        return resolved

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def resolve(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate a textual reference into a :class:`ResolvedDataset`.

        Args:
            dataset_ref: Opaque string from
                :class:`ExperimentPlan.data_selection.dataset_ref`.

        Returns:
            The registered :class:`ResolvedDataset`.

        Raises:
            DatasetNotFoundError: If ``dataset_ref`` was never
                registered.
        """
        with self._lock:
            if dataset_ref not in self._store:
                raise DatasetNotFoundError(dataset_ref)
            return self._store[dataset_ref]

    # ------------------------------------------------------------------
    # Introspection helpers (test convenience)
    # ------------------------------------------------------------------

    def known_refs(self) -> list[str]:
        """Return all registered dataset_ref keys, sorted."""
        with self._lock:
            return sorted(self._store.keys())

    def clear(self) -> None:
        """Remove every registration. Intended for test fixtures."""
        with self._lock:
            self._store.clear()


def seed_default_datasets(resolver: InMemoryDatasetResolver) -> None:
    """
    Populate ``resolver`` with the dataset references used by every
    production experiment plan committed to ``Strategy Repo/``.

    Idempotent: re-registers each entry on every call (overwrites
    any prior value), so calling it twice is safe and predictable.

    Args:
        resolver: The :class:`InMemoryDatasetResolver` to seed.

    Example::

        resolver = InMemoryDatasetResolver()
        seed_default_datasets(resolver)
        assert "fx-eurusd-15m-certified-v3" in resolver.known_refs()
    """
    for dataset_ref, symbols in _DEFAULT_DATASET_SEED.items():
        resolver.register(dataset_ref, symbols)


__all__ = [
    "InMemoryDatasetResolver",
    "seed_default_datasets",
]

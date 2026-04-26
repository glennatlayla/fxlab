"""
Dataset resolver implementations (M2.C2 in-memory + M4.E3 catalog adapter).

Purpose:
    Provide concrete :class:`DatasetResolverInterface` implementations
    so the ``POST /runs/from-ir`` endpoint can translate a textual
    ``dataset_ref`` into a :class:`ResolvedDataset`.

==============================================================================
M4.E3 STATUS -- TWO IMPLEMENTATIONS LIVE HERE
==============================================================================

As of M4.E3 there are TWO implementations in this module:

    1. :class:`InMemoryDatasetResolver` (test-only, unchanged from M2.C2)
       -- A thread-safe in-memory map used by unit tests where a
       Postgres connection is not available. Production no longer
       wires this path.

    2. :class:`CatalogBackedResolver` (production, M4.E3)
       -- A thin adapter that wraps a :class:`DatasetServiceInterface`
       (the catalog-backed :class:`DatasetService`) and delegates
       :meth:`resolve` to its :meth:`lookup`. The route layer's
       narrow contract (:class:`DatasetResolverInterface`) keeps
       working but reads from the persisted catalog.

The split exists because the route layer only needs the narrow
"resolve(ref) -> ResolvedDataset" surface, while the catalog backend
exposes a richer "lookup / list / register / is_certified" surface
to admin tooling. Wrapping the rich service in the narrow adapter
means the route's tests stay untouched even after M4.E3 lands.

Production wiring in :mod:`services.api.main`::

    from libs.strategy_ir.dataset_resolver import CatalogBackedResolver
    from services.api.repositories.sql_dataset_repository import (
        SqlDatasetRepository,
    )
    from services.api.services.dataset_service import DatasetService
    from services.api.routes.runs import set_dataset_resolver

    repo = SqlDatasetRepository(db=SessionLocal())
    service = DatasetService(repo=repo)
    set_dataset_resolver(CatalogBackedResolver(service))

The :class:`InMemoryDatasetResolver` and :func:`seed_default_datasets`
are retained for unit tests only -- their docstrings and the test
files explicitly mark them as test-only.

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
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetServiceInterface,
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
    # Spread companion datasets — referenced by the
    # `spread_dataset_ref` field on every production experiment plan.
    # Same symbol coverage as the bar datasets they pair with.
    "fx-majors-spread-certified-v1": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    ],
    "fx-majors-spread-h1-certified-v1": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    ],
}


class InMemoryDatasetResolver(DatasetResolverInterface):
    """
    Thread-safe in-memory implementation of
    :class:`DatasetResolverInterface`.

    **TEST-ONLY** as of M4.E3. Production wiring uses
    :class:`CatalogBackedResolver` wrapping
    :class:`services.api.services.dataset_service.DatasetService`
    -- the Postgres-backed catalog service. This in-memory variant
    is retained for unit tests where a database connection is not
    available.

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


# ---------------------------------------------------------------------------
# M4.E3 swap target: the production resolver wraps the catalog service.
# ---------------------------------------------------------------------------


class CatalogBackedResolver(DatasetResolverInterface):
    """
    Production :class:`DatasetResolverInterface` adapter that wraps a
    :class:`DatasetServiceInterface` (the M4.E3 catalog service).

    Why this exists:
        The route layer's narrow contract is "resolve(ref) ->
        ResolvedDataset" — single method, returns a value object.
        The M4.E3 catalog service exposes a richer surface
        (lookup / list / register / is_certified) intended for admin
        tooling and the certification gate. This adapter keeps the
        narrow contract intact so the route's tests and consumers
        do not need to grow imports against the service surface.

    Wiring:
        ``set_dataset_resolver(CatalogBackedResolver(DatasetService(...)))``

    Responsibilities:
    - Delegate :meth:`resolve` to the wrapped service's :meth:`lookup`.
    - Re-raise :class:`DatasetNotFoundError` unchanged so route handlers
      can map it to HTTP 404 with a known exception type.

    Does NOT:
    - Cache lookups — callers using a request-scoped session must not
      see stale catalog state across requests.
    - Hold any state of its own beyond the wrapped service reference.

    Dependencies:
    - A :class:`DatasetServiceInterface` instance, injected via the
      constructor.

    Example::

        from services.api.services.dataset_service import DatasetService
        from services.api.repositories.sql_dataset_repository import (
            SqlDatasetRepository,
        )
        from libs.strategy_ir.dataset_resolver import CatalogBackedResolver

        repo = SqlDatasetRepository(db=SessionLocal())
        service = DatasetService(repo=repo)
        resolver = CatalogBackedResolver(service)
        resolved = resolver.resolve("fx-eurusd-15m-certified-v3")
    """

    def __init__(self, service: DatasetServiceInterface) -> None:
        """
        Args:
            service: A :class:`DatasetServiceInterface` implementation
                (production: :class:`DatasetService`; tests can pass
                any structural match).
        """
        self._service = service

    def resolve(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate ``dataset_ref`` into a :class:`ResolvedDataset` by
        delegating to the wrapped service's :meth:`lookup`.

        Args:
            dataset_ref: Opaque catalog reference string from
                :class:`ExperimentPlan.data_selection.dataset_ref`.

        Returns:
            Populated :class:`ResolvedDataset`.

        Raises:
            DatasetNotFoundError: Re-raised from the wrapped service
                when the reference is not registered.
        """
        # The narrow port already declares DatasetNotFoundError as the
        # only documented exception; the service raises the same type
        # so no translation is required.
        return self._service.lookup(dataset_ref)


__all__ = [
    "CatalogBackedResolver",
    "InMemoryDatasetResolver",
    "seed_default_datasets",
]

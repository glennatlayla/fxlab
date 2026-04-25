"""
Dataset service port (M4.E3 prep -- richer catalog surface).

==============================================================================
ARCHITECTURE -- HOW THIS PORT RELATES TO DatasetResolverInterface
==============================================================================

There are TWO dataset-related ports in :mod:`libs.strategy_ir.interfaces`:

    DatasetResolverInterface  (M2.C2, narrow, route-handler facing)
        - Single method: ``resolve(dataset_ref) -> ResolvedDataset``.
        - Used by the ``POST /runs/from-ir`` route to translate a
          textual reference into the ``dataset_id`` + ``symbols``
          tuple the engine needs.
        - Today satisfied by the in-memory
          :class:`InMemoryDatasetResolver`; will be satisfied by an
          adapter that wraps a M4.E3 :class:`DatasetService` (see
          below).

    DatasetServiceInterface  (M4.E3, fuller catalog surface, this file)
        - Four methods: lookup, list_known_refs, register_dataset,
          is_certified.
        - Owned by the data-pipeline / catalog backend that lands in
          M4.E3 (Postgres-backed dataset_catalog table + object-store
          handles).
        - The narrow ``DatasetResolverInterface`` will be satisfied
          by a thin adapter that wraps a :class:`DatasetServiceInterface`
          implementation::

              class CatalogBackedResolver(DatasetResolverInterface):
                  def __init__(self, svc: DatasetServiceInterface) -> None:
                      self._svc = svc

                  def resolve(self, dataset_ref: str) -> ResolvedDataset:
                      resolved = self._svc.lookup(dataset_ref)
                      return ResolvedDataset(
                          dataset_ref=dataset_ref,
                          dataset_id=resolved.dataset_id,
                          symbols=resolved.symbols,
                      )

          The route layer continues to depend only on the narrow
          surface, so its tests stay untouched. ``set_dataset_resolver``
          is the single wiring change in :mod:`services.api.main`.

This split keeps each port at the size its consumer needs, and lets
M4.E3 land the heavy catalog without invalidating the M2.C2 route's
tests or expanding the route's import graph.

==============================================================================

Responsibilities:
    - Define :class:`DatasetServiceInterface`, the Protocol the
      M4.E3 dataset catalog will satisfy.
    - Define :class:`ResolvedDataset` (re-exported from the
      narrow resolver interface so consumers only need one import).
    - Define :class:`DatasetNotFoundError` (re-exported for the same
      reason).

Does NOT:
    - Implement the catalog. The Postgres-backed implementation lives
      in :mod:`services.api.services.dataset_service` (M4.E3).
    - Define the catalog table schema -- that lives in
      :mod:`libs.contracts.market_data` / migrations under M4.E3.

Dependencies:
    - :mod:`libs.strategy_ir.interfaces.dataset_resolver_interface`
      (re-export of :class:`ResolvedDataset` and
      :class:`DatasetNotFoundError`).

Example::

    from libs.strategy_ir.interfaces.dataset_service_interface import (
        DatasetServiceInterface,
    )

    def boot(svc: DatasetServiceInterface) -> None:
        svc.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="M15",
            source="oanda-v20",
            version="v3",
        )
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetNotFoundError,
    ResolvedDataset,
)


@runtime_checkable
class DatasetServiceInterface(Protocol):
    """
    Port for the M4.E3 dataset catalog service.

    Implementations:
        - :class:`services.api.services.dataset_service.DatasetService`
          (M4.E3, Postgres-backed -- not yet committed).

    Why a Protocol rather than an ABC:
        Consumers structurally type against the four methods below.
        Test doubles can satisfy the Protocol without inheriting from
        a base class.

    Methods:
        lookup: Translate a textual reference into a
            :class:`ResolvedDataset`. Raises :class:`DatasetNotFoundError`
            on miss (parity with :class:`DatasetResolverInterface`).
        list_known_refs: Enumerate every registered dataset_ref in the
            catalog. Used by ops endpoints and admin tooling.
        register_dataset: Add or update a dataset entry in the
            catalog with full metadata (timeframe, source, version).
            The narrow :class:`DatasetResolverInterface` doesn't need
            this -- only the catalog owner does.
        is_certified: Boolean check used by the certification gate
            so an experiment plan can refuse to run against an
            uncertified dataset.
    """

    def lookup(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate ``dataset_ref`` into a :class:`ResolvedDataset`.

        Args:
            dataset_ref: Opaque catalog reference string.

        Returns:
            Populated :class:`ResolvedDataset`.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
        """
        ...

    def list_known_refs(self) -> list[str]:
        """
        Return every registered ``dataset_ref`` in the catalog.

        Returns:
            Sorted list of strings. Empty when the catalog is empty.
        """
        ...

    def register_dataset(
        self,
        dataset_ref: str,
        *,
        symbols: list[str],
        timeframe: str,
        source: str,
        version: str,
    ) -> None:
        """
        Register or upsert a dataset entry in the catalog.

        Args:
            dataset_ref: Opaque catalog reference string. Must be
                non-empty.
            symbols: Tradable symbols the dataset covers. Must be
                non-empty.
            timeframe: Bar resolution this dataset stores
                (``"M1"``, ``"H1"``, ``"D"``...).
            source: Provenance label (``"oanda-v20"``, ``"alpaca"``,
                ``"manual-import"``, ...).
            version: Catalog version string for this dataset entry
                (e.g. ``"v3"``); used by the certification gate.

        Returns:
            ``None``. Persistence is the implementation's
            responsibility; callers do not get a handle back.
        """
        ...

    def is_certified(self, dataset_ref: str) -> bool:
        """
        Return whether ``dataset_ref`` has cleared the certification
        gate.

        Args:
            dataset_ref: Opaque catalog reference string.

        Returns:
            ``True`` if the dataset has a certification record;
            ``False`` if not (including when the dataset is not
            registered at all -- callers that want to distinguish
            should call :meth:`lookup` first).
        """
        ...


__all__ = [
    "DatasetNotFoundError",
    "DatasetServiceInterface",
    "ResolvedDataset",
]

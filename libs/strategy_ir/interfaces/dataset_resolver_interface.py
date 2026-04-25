"""
Dataset resolver port (M2.C2 → M4.E3 swap point).

Purpose:
    Define the abstract interface used by the ``POST /runs/from-ir``
    route to translate an experiment plan's ``dataset_ref`` string
    (e.g. ``"fx-majors-h1-certified-v1"``) into a concrete dataset
    handle that downstream backtest engines can consume.

Why this lives here:
    The strategy-IR compile path is the first call site that needs
    dataset resolution. The proper :class:`DatasetService` (Track E
    milestone M4.E3) will wrap a real catalog (Postgres + object
    storage). Until M4.E3 lands, the in-memory adapter at
    :mod:`libs.strategy_ir.dataset_resolver` satisfies this port so
    the run-from-IR path is fully functional end-to-end without
    blocking on Track E.

Responsibilities:
    - Define :class:`DatasetResolverInterface` and the value object
      :class:`ResolvedDataset` it returns.
    - Define :class:`DatasetNotFoundError` so route handlers can map
      missing references to HTTP 404 cleanly.

Does NOT:
    - Provide any concrete implementation. Implementations live
      under :mod:`libs.strategy_ir.dataset_resolver` (in-memory) and
      will live under :mod:`services.api.services.dataset_service`
      once M4.E3 lands.

Dependencies:
    - Pydantic v2 only (for the immutable :class:`ResolvedDataset`
      value object).

Example::

    from libs.strategy_ir.interfaces.dataset_resolver_interface import (
        DatasetResolverInterface,
    )

    def submit_from_ir(resolver: DatasetResolverInterface, ref: str):
        resolved = resolver.resolve(ref)
        engine_config["dataset_id"] = resolved.dataset_id
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field


class DatasetNotFoundError(Exception):
    """
    Raised by :meth:`DatasetResolverInterface.resolve` when the
    supplied ``dataset_ref`` is not registered.

    Route handlers catch this and translate to HTTP 404 with the
    referenced name in the body so callers can correct typos.
    """

    def __init__(self, dataset_ref: str) -> None:
        self.dataset_ref = dataset_ref
        super().__init__(f"Dataset reference {dataset_ref!r} is not registered")


class ResolvedDataset(BaseModel):
    """
    Immutable value object describing a successfully-resolved dataset.

    Attributes:
        dataset_ref: The original string passed in (echoed back so
            log lines and audit trails can correlate).
        dataset_id: Stable identifier the engine layer uses to load
            the dataset. Today the in-memory resolver returns the
            same value as ``dataset_ref``; the M4.E3 service will
            return a ULID or catalog-row primary key.
        symbols: Tradable symbols the dataset covers. Used by the
            route handler to populate :class:`ResearchRunConfig`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_ref: str = Field(..., min_length=1)
    dataset_id: str = Field(..., min_length=1)
    symbols: list[str] = Field(..., min_length=1)


class DatasetResolverInterface(ABC):
    """
    Port for translating a textual ``dataset_ref`` into a concrete
    dataset handle.

    Implementations:
        - :class:`libs.strategy_ir.dataset_resolver.InMemoryDatasetResolver`
          (M2.C2 stand-in).
        - :class:`services.api.services.dataset_service.DatasetService`
          (M4.E3, Track E -- not yet committed).

    Why an interface rather than a function:
        The route handler depends on this port via constructor
        injection, so swapping the M2.C2 in-memory resolver for the
        M4.E3 catalog-backed service requires only a single wiring
        change (one ``set_dataset_resolver`` call in
        :mod:`services.api.main`). The route, the service, and the
        tests stay untouched.
    """

    @abstractmethod
    def resolve(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate a textual reference into a :class:`ResolvedDataset`.

        Args:
            dataset_ref: Opaque string from
                :class:`ExperimentPlan.data_selection.dataset_ref`.

        Returns:
            A populated :class:`ResolvedDataset` value object.

        Raises:
            DatasetNotFoundError: If the reference is not known.
        """


__all__ = [
    "DatasetNotFoundError",
    "DatasetResolverInterface",
    "ResolvedDataset",
]

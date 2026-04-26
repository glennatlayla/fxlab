"""
DatasetRepositoryInterface — port for dataset catalog persistence (M4.E3).

Purpose:
    Define the contract every dataset repository implementation must
    honour so the M4.E3 :class:`DatasetService` depends on an
    abstraction (not on SQLAlchemy or any other concrete storage).

Responsibilities:
    - find_by_ref(): lookup a single dataset by its ``dataset_ref`` key.
    - save(): upsert a dataset record. Returns the saved record so the
      caller can read back any database-side defaults (timestamps).
    - list_all(): enumerate every dataset record (admin / operator
      tooling).
    - list_known_refs(): enumerate just the ``dataset_ref`` keys, sorted
      (the cheap path consumed by ops endpoints).

Does NOT:
    - Mutate dataset payloads.
    - Drive ingestion or candle storage (that is the data-pipeline's
      responsibility).
    - Evaluate certification semantics — the service consumes
      ``is_certified`` directly.

Dependencies:
    - libs.contracts.market_data: ResolvedDataset value object — but
      this interface returns the storage-level dataclass below, not
      the wire model. The service layer is responsible for translating
      the storage record into the engine-facing
      :class:`ResolvedDataset`.

Error conditions:
    - find_by_ref returns ``None`` when the dataset_ref is absent (the
      service layer translates this into the typed
      :class:`DatasetNotFoundError` for upstream callers).
    - save raises :class:`DatasetRepositoryError` when the underlying
      store rejects the write (driver error, constraint violation).

Example:
    repo = SqlDatasetRepository(db=session)
    record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    if record is None:
        raise DatasetNotFoundError("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class DatasetRepositoryError(Exception):
    """
    Raised when the repository cannot satisfy a request for any reason
    other than caller error (network failure, DB outage, integrity
    violation).

    Service-layer callers should treat this as a 5xx-class failure.
    """


@dataclass(frozen=True)
class DatasetRecord:
    """
    Storage-level snapshot of a row in the ``datasets`` catalog table.

    Returned by :class:`DatasetRepositoryInterface` implementations.
    The service layer converts this into the engine-facing
    :class:`ResolvedDataset` value object before returning to callers.

    Attributes:
        id: ULID primary key.
        dataset_ref: Catalog reference string (UNIQUE).
        symbols: Tradable symbols the dataset covers.
        timeframe: Bar resolution.
        source: Provider tag (``"oanda"``, ``"alpaca"``,
            ``"synthetic"``...).
        version: Catalog version string.
        is_certified: True once the cert gate has cleared.
        created_by: ULID of the user who created the entry, or ``None``
            for bootstrap-seeded entries.
        created_at: Insert timestamp (server default ``now()``).
        updated_at: Last-update timestamp.
    """

    id: str
    dataset_ref: str
    symbols: list[str] = field(default_factory=list)
    timeframe: str = ""
    source: str = ""
    version: str = ""
    is_certified: bool = False
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasetRepositoryInterface(ABC):
    """
    Abstract port for dataset-catalog persistence.

    Implementations:
        - :class:`services.api.repositories.sql_dataset_repository.SqlDatasetRepository`
          (production, Postgres-backed).
        - :class:`libs.contracts.mocks.mock_dataset_repository.MockDatasetRepository`
          (unit tests, in-memory).
    """

    @abstractmethod
    def find_by_ref(self, dataset_ref: str) -> DatasetRecord | None:
        """
        Look up a dataset record by its catalog reference key.

        Args:
            dataset_ref: Opaque catalog reference string.

        Returns:
            The matching :class:`DatasetRecord` or ``None`` if no row
            exists for ``dataset_ref``.

        Raises:
            DatasetRepositoryError: On transport / driver failure.
        """
        ...

    @abstractmethod
    def save(self, record: DatasetRecord) -> DatasetRecord:
        """
        INSERT or UPDATE a dataset row.

        Behaviour:
            - If no row exists for ``record.dataset_ref``, INSERT.
            - If a row exists, UPDATE every field except ``id`` and
              ``created_at`` (those are immutable). ``updated_at`` is
              refreshed by the implementation.

        Args:
            record: The :class:`DatasetRecord` to persist.

        Returns:
            The persisted record, re-read from the database so any
            server-side defaults (timestamps) are populated.

        Raises:
            DatasetRepositoryError: On driver / integrity error.
        """
        ...

    @abstractmethod
    def list_all(self) -> list[DatasetRecord]:
        """
        Return every catalog row, sorted by ``dataset_ref``.

        Returns:
            List of :class:`DatasetRecord`. Empty when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        ...

    @abstractmethod
    def list_known_refs(self) -> list[str]:
        """
        Return every ``dataset_ref`` in the catalog, sorted.

        Cheaper than :meth:`list_all` because the implementation only
        SELECTs a single column — used by ops endpoints.

        Returns:
            Sorted list of strings. Empty when the catalog is empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        ...


__all__ = [
    "DatasetRecord",
    "DatasetRepositoryError",
    "DatasetRepositoryInterface",
]

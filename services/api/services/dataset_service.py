"""
DatasetService — Postgres-backed implementation of
:class:`DatasetServiceInterface` (M4.E3).

Purpose:
    Translate a textual ``dataset_ref`` into a concrete
    :class:`ResolvedDataset`, persist registrations into the catalog,
    and expose the certification flag — all backed by the ``datasets``
    table via :class:`SqlDatasetRepository`.

Replaces:
    The M2.C2 :class:`InMemoryDatasetResolver`. The narrow
    :class:`DatasetResolverInterface` continues to work via
    :class:`CatalogBackedResolver`, the thin adapter that wraps a
    :class:`DatasetServiceInterface`.

Responsibilities:
    - lookup(): translate dataset_ref → :class:`ResolvedDataset`,
      raising :class:`DatasetNotFoundError` on miss.
    - list_known_refs(): proxy to the repository's cheap
      single-column SELECT.
    - register_dataset(): upsert a dataset entry. Generates a ULID
      for the row id on first insert and preserves it on subsequent
      updates.
    - is_certified(): boolean check used by the certification gate.

Does NOT:
    - Drive ingestion or candle storage.
    - Touch SQL directly — every database call goes through
      :class:`DatasetRepositoryInterface`.

Dependencies:
    - DatasetRepositoryInterface (injected): the persistence port.

Error conditions:
    - lookup raises :class:`DatasetNotFoundError` for unknown refs.
    - register_dataset raises :class:`ValueError` on empty/short
      arguments. Repository-level errors propagate as
      :class:`DatasetRepositoryError`.

Example:
    repo = SqlDatasetRepository(db=session)
    svc = DatasetService(repo=repo)
    svc.register_dataset(
        "fx-eurusd-15m-certified-v3",
        symbols=["EURUSD"],
        timeframe="15m",
        source="oanda",
        version="v3",
    )
    resolved = svc.lookup("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

import structlog
import ulid

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
    DatasetRepositoryInterface,
)
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    DatasetServiceInterface,
    ResolvedDataset,
)

logger = structlog.get_logger(__name__)


class DatasetService(DatasetServiceInterface):
    """
    Postgres-backed catalog service.

    Responsibilities:
    - Coordinate lookup / list / register / is_certified against the
      repository.
    - Convert :class:`DatasetRecord` (storage shape) into
      :class:`ResolvedDataset` (engine-facing shape).
    - Generate ULIDs for new catalog rows.

    Does NOT:
    - Cache results — request-scoped sessions make caching unsafe.
      An LRU layer can sit in front of this service if profiling
      shows lookup is hot.
    - Validate symbol strings beyond non-empty list.

    Dependencies:
    - :class:`DatasetRepositoryInterface` (injected via constructor).
    """

    def __init__(self, repo: DatasetRepositoryInterface) -> None:
        """
        Args:
            repo: Persistence port. In production wire the SQL
                implementation; in tests use the in-memory mock.
        """
        self._repo = repo

    # ------------------------------------------------------------------
    # DatasetServiceInterface
    # ------------------------------------------------------------------

    def lookup(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate ``dataset_ref`` into a :class:`ResolvedDataset`.

        Args:
            dataset_ref: Catalog reference string.

        Returns:
            Populated :class:`ResolvedDataset`.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)

        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            logger.warning(
                "dataset_service.lookup.miss",
                component="DatasetService",
                operation="lookup",
                dataset_ref=dataset_ref,
                result="not_found",
            )
            raise DatasetNotFoundError(dataset_ref)

        return _to_resolved(record)

    def list_known_refs(self) -> list[str]:
        """Return every registered ``dataset_ref``, sorted."""
        return self._repo.list_known_refs()

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
        Upsert a dataset entry in the catalog.

        On first call for a given ``dataset_ref``, INSERTs a new row
        with a freshly-generated ULID. On subsequent calls UPDATEs
        the row in place (preserving the ULID and ``created_at``).

        Args:
            dataset_ref: Opaque catalog reference string. Must be
                non-empty.
            symbols: Tradable symbols the dataset covers. Must be
                non-empty.
            timeframe: Bar resolution (``"15m"``, ``"1h"``, ``"4h"``,
                ``"1d"``).
            source: Provider tag (``"oanda"``, ``"alpaca"``,
                ``"synthetic"``...).
            version: Catalog version string.

        Raises:
            ValueError: On empty / blank arguments.
            DatasetRepositoryError: On persistence failure.
        """
        if not dataset_ref:
            raise ValueError("dataset_ref must be non-empty")
        if not symbols:
            raise ValueError("symbols must be non-empty")
        if not timeframe:
            raise ValueError("timeframe must be non-empty")
        if not source:
            raise ValueError("source must be non-empty")
        if not version:
            raise ValueError("version must be non-empty")

        existing = self._repo.find_by_ref(dataset_ref)
        if existing is None:
            row_id = str(ulid.ULID())
            record = DatasetRecord(
                id=row_id,
                dataset_ref=dataset_ref,
                symbols=list(symbols),
                timeframe=timeframe,
                source=source,
                version=version,
                # is_certified defaults to False on first insert; the
                # certification workflow (separate path) flips it.
                is_certified=False,
                created_by=None,
            )
        else:
            record = DatasetRecord(
                id=existing.id,
                dataset_ref=dataset_ref,
                symbols=list(symbols),
                timeframe=timeframe,
                source=source,
                version=version,
                # Preserve certification across re-registrations —
                # upgrading a dataset's metadata should not implicitly
                # de-certify it.
                is_certified=existing.is_certified,
                created_by=existing.created_by,
                created_at=existing.created_at,
            )

        self._repo.save(record)
        logger.info(
            "dataset_service.register_dataset.succeeded",
            component="DatasetService",
            operation="register_dataset",
            dataset_ref=dataset_ref,
            symbols_count=len(symbols),
            timeframe=timeframe,
            source=source,
            version=version,
            inserted=existing is None,
            result="success",
        )

    def is_certified(self, dataset_ref: str) -> bool:
        """
        Return whether ``dataset_ref`` has cleared the cert gate.

        Returns ``False`` for unknown references (callers that want to
        distinguish should call :meth:`lookup` first).
        """
        if not dataset_ref:
            return False
        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            return False
        return bool(record.is_certified)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_resolved(record: DatasetRecord) -> ResolvedDataset:
    """
    Translate a storage :class:`DatasetRecord` into the engine-facing
    :class:`ResolvedDataset` value object.

    The ``dataset_id`` field carries the catalog row's ULID — stable
    across renames of the human-readable ``dataset_ref``.
    """
    return ResolvedDataset(
        dataset_ref=record.dataset_ref,
        dataset_id=record.id,
        symbols=list(record.symbols),
    )


__all__ = [
    "DatasetService",
]

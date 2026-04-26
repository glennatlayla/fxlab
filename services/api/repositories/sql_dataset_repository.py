"""
SQL-backed dataset catalog repository (M4.E3).

Purpose:
    Persist :class:`DatasetRecord` rows in the ``datasets`` table for
    consumption by :class:`DatasetService`. This is the single layer
    that talks SQL for the dataset catalog entity.

Responsibilities:
    - find_by_ref(): SELECT a single row by its UNIQUE ``dataset_ref``.
    - save(): UPSERT a row (INSERT on miss, UPDATE on hit).
    - list_all(): SELECT every row, sorted by ``dataset_ref``.
    - list_known_refs(): SELECT only the ``dataset_ref`` column.

Does NOT:
    - Drive ingestion (data-pipeline owns that).
    - Translate the storage record into the engine-facing
      :class:`ResolvedDataset` — :class:`DatasetService` does that.
    - commit() the session — request-scoped commits are the caller's
      responsibility (FastAPI's ``get_db`` handles it at request end).

Dependencies:
    - sqlalchemy.orm.Session (injected via constructor).
    - libs.contracts.models.Dataset: ORM model.
    - libs.contracts.interfaces.dataset_repository_interface:
      DatasetRecord, DatasetRepositoryError, DatasetRepositoryInterface.

Error conditions:
    - :class:`DatasetRepositoryError` is raised when SQLAlchemy reports
      any driver / integrity error. The inner exception is chained via
      ``raise from`` so operators see the full cause.

Example:
    repo = SqlDatasetRepository(db=session)
    record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    if record is None:
        raise DatasetNotFoundError("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
    DatasetRepositoryError,
    DatasetRepositoryInterface,
)
from libs.contracts.models import Dataset

logger = structlog.get_logger(__name__)


class SqlDatasetRepository(DatasetRepositoryInterface):
    """
    SQL-backed implementation of :class:`DatasetRepositoryInterface`.

    Responsibilities:
    - Translate ORM ``Dataset`` rows to/from the storage-level
      :class:`DatasetRecord` dataclass so the service layer never
      depends on SQLAlchemy.
    - Wrap every SQLAlchemy error in :class:`DatasetRepositoryError`
      so callers handle one consistent exception type.

    Does NOT:
    - Hold business logic.
    - Open or close transactions — the session lifetime is owned by
      the FastAPI ``get_db`` dependency.
    - Generate ULIDs — callers supply ``record.id``.
    """

    def __init__(self, db: Session) -> None:
        """
        Args:
            db: Request-scoped SQLAlchemy session. Not retained across
                requests; the caller ensures lifetime.
        """
        self._db = db

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def find_by_ref(self, dataset_ref: str) -> DatasetRecord | None:
        """
        Return the row matching ``dataset_ref`` or ``None``.

        Args:
            dataset_ref: Catalog reference key.

        Returns:
            :class:`DatasetRecord` or ``None`` if no row matches.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        try:
            stmt = select(Dataset).where(Dataset.dataset_ref == dataset_ref)
            row: Dataset | None = self._db.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.find_by_ref.failed",
                component="SqlDatasetRepository",
                operation="find_by_ref",
                dataset_ref=dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(f"Failed to look up dataset_ref={dataset_ref!r}") from exc

        if row is None:
            return None
        return _to_record(row)

    def save(self, record: DatasetRecord) -> DatasetRecord:
        """
        INSERT a new row or UPDATE the existing row in place.

        The dataset_ref column is UNIQUE; we use it as the natural key
        for upsert semantics. ``id`` and ``created_at`` are immutable
        once written.

        Args:
            record: The :class:`DatasetRecord` to persist.

        Returns:
            The persisted record, re-read from the session so any
            server-side defaults are populated.

        Raises:
            DatasetRepositoryError: On driver / integrity error.
        """
        try:
            stmt = select(Dataset).where(Dataset.dataset_ref == record.dataset_ref)
            existing: Dataset | None = self._db.execute(stmt).scalar_one_or_none()

            if existing is None:
                row = Dataset(
                    id=record.id,
                    dataset_ref=record.dataset_ref,
                    symbols=list(record.symbols),
                    timeframe=record.timeframe,
                    source=record.source,
                    version=record.version,
                    is_certified=record.is_certified,
                    created_by=record.created_by,
                )
                self._db.add(row)
            else:
                # UPDATE in place — preserve id + created_at, refresh
                # the rest. updated_at is bumped by TimestampMixin's
                # onupdate hook.
                existing.symbols = list(record.symbols)
                existing.timeframe = record.timeframe
                existing.source = record.source
                existing.version = record.version
                existing.is_certified = record.is_certified
                if record.created_by is not None:
                    existing.created_by = record.created_by
                row = existing

            self._db.flush()
            self._db.refresh(row)
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error(
                "dataset_repository.save.failed",
                component="SqlDatasetRepository",
                operation="save",
                dataset_ref=record.dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to save dataset_ref={record.dataset_ref!r}"
            ) from exc

        logger.info(
            "dataset_repository.save.succeeded",
            component="SqlDatasetRepository",
            operation="save",
            dataset_ref=record.dataset_ref,
            result="success",
        )
        return _to_record(row)

    def list_all(self) -> list[DatasetRecord]:
        """
        Return every row, sorted by ``dataset_ref``.

        Returns:
            List of :class:`DatasetRecord`. Empty when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        try:
            stmt = select(Dataset).order_by(Dataset.dataset_ref.asc())
            rows = list(self._db.execute(stmt).scalars().all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.list_all.failed",
                component="SqlDatasetRepository",
                operation="list_all",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to list datasets") from exc

        return [_to_record(r) for r in rows]

    def list_known_refs(self) -> list[str]:
        """
        Return every ``dataset_ref`` in the catalog, sorted.

        Returns:
            Sorted list of strings. Empty when the catalog is empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        try:
            stmt = select(Dataset.dataset_ref).order_by(Dataset.dataset_ref.asc())
            refs = [str(r) for r in self._db.execute(stmt).scalars().all()]
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.list_known_refs.failed",
                component="SqlDatasetRepository",
                operation="list_known_refs",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to list dataset refs") from exc

        return refs


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


def _to_record(row: Dataset) -> DatasetRecord:
    """
    Convert an ORM ``Dataset`` row to a storage-level
    :class:`DatasetRecord`.

    Defensive about ``symbols`` because JSON columns can round-trip as
    ``None`` on engines that do not enforce NOT NULL on JSON.
    """
    raw_symbols = row.symbols
    if raw_symbols is None:
        symbols: list[str] = []
    elif isinstance(raw_symbols, list):
        symbols = [str(s) for s in raw_symbols]
    else:
        # Defensive — JSON column shape is enforced by the contract,
        # but coerce anything else into the empty list rather than
        # leaking a non-list shape into the service layer.
        symbols = []

    return DatasetRecord(
        id=str(row.id),
        dataset_ref=str(row.dataset_ref),
        symbols=symbols,
        timeframe=str(row.timeframe),
        source=str(row.source),
        version=str(row.version),
        is_certified=bool(row.is_certified),
        created_by=str(row.created_by) if row.created_by is not None else None,
        # Cast: SQLAlchemy's typed Column descriptor reports as Column[datetime]
        # to mypy, but at runtime the row attribute is the materialised value.
        created_at=cast(datetime | None, row.created_at),
        updated_at=cast(datetime | None, row.updated_at),
    )


__all__ = [
    "SqlDatasetRepository",
]

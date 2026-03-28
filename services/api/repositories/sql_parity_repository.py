"""
SQL-backed parity repository implementation (ISS-020).

Responsibilities:
- Retrieve parity events from the database with optional filtering.
- Implement ParityRepositoryInterface using SQLAlchemy ORM.
- Support listing, finding by ID, and per-instrument summarization.

Does NOT:
- Perform parity computation or business logic.
- Validate parity data beyond schema.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.models.ParityEvent: ORM model.
- libs.contracts.parity: ParityEvent, ParityInstrumentSummary contracts.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_id: raises NotFoundError when parity event ID is unknown.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_parity_repository import SqlParityRepository

    db = SessionLocal()
    repo = SqlParityRepository(db=db)
    events = repo.list(severity="CRITICAL", correlation_id="corr-1")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.parity_repository import ParityRepositoryInterface
from libs.contracts.models import ParityEvent as ParityEventModel
from libs.contracts.parity import ParityEvent, ParityInstrumentSummary

logger = structlog.get_logger(__name__)


class SqlParityRepository(ParityRepositoryInterface):
    """
    SQL-backed implementation of ParityRepositoryInterface.

    Responsibilities:
    - Query parity_events table with optional severity/instrument/feed_id filters.
    - Convert ORM models to Pydantic contracts.
    - Raise NotFoundError when parity event IDs are not found.
    - Aggregate per-instrument parity severity summaries.

    Does NOT:
    - Perform parity computation or business logic.
    - Validate data beyond schema.
    - Perform orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_id: raises NotFoundError if parity event ID not in database.

    Example:
        repo = SqlParityRepository(db=session)
        events = repo.list(severity="CRITICAL", correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL parity repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlParityRepository(db=get_db())
        """
        self.db = db

    def list(
        self,
        *,
        severity: str = "",
        instrument: str = "",
        feed_id: str = "",
        correlation_id: str,
    ) -> list[ParityEvent]:
        """
        Return parity events, optionally filtered.

        Args:
            severity:       Filter by exact severity string ("CRITICAL", "WARNING", "INFO").
                            Empty string means no severity filter.
            instrument:     Filter by instrument/ticker string. Empty = no filter.
            feed_id:        Filter by feed ULID (matches either feed_id or reference_feed_id).
                            Empty = no filter.
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            List of ParityEvent matching all non-empty filter criteria (AND semantics).

        Example:
            events = repo.list(severity="CRITICAL", correlation_id="corr-123")
        """
        # Build query with filters
        stmt = select(ParityEventModel)
        filters = []

        if severity:
            filters.append(ParityEventModel.status == severity)
        if instrument:
            # Assuming instrument is stored in details JSON or separate column.
            # For now, we filter by checking details field (future M5+ enhancement).
            pass
        if feed_id:
            from sqlalchemy import or_

            filters.append(
                or_(
                    ParityEventModel.feed_id == feed_id,
                    ParityEventModel.reference_feed_id == feed_id,
                )
            )

        if filters:
            stmt = stmt.where(and_(*filters))

        orm_events = self.db.execute(stmt).scalars().all()
        events = [self._orm_to_contract(evt) for evt in orm_events]

        logger.debug(
            "parity.list",
            correlation_id=correlation_id,
            event_count=len(events),
            severity_filter=severity,
            feed_id_filter=feed_id,
        )

        return events

    def find_by_id(self, id: str, correlation_id: str) -> ParityEvent:
        """
        Return a single parity event by ULID.

        Args:
            id:               ULID of the parity event.
            correlation_id:   Request-scoped tracing ID.

        Returns:
            ParityEvent matching the given ID.

        Raises:
            NotFoundError: If no parity event exists with the given ID.

        Example:
            event = repo.find_by_id("01HQPARITY0AAAAAAAAAAAAA0", "corr-123")
        """
        stmt = select(ParityEventModel).where(ParityEventModel.id == id)
        orm_event = self.db.execute(stmt).scalar_one_or_none()

        if orm_event is None:
            logger.warning(
                "parity.not_found",
                parity_id=id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Parity event {id!r} not found")

        logger.debug(
            "parity.found",
            parity_id=id,
            correlation_id=correlation_id,
        )

        return self._orm_to_contract(orm_event)

    def summarize(self, *, correlation_id: str) -> list[ParityInstrumentSummary]:
        """
        Return per-instrument parity severity aggregates.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            List of ParityInstrumentSummary, one per unique instrument.
            Empty list when no events exist.

        Example:
            summaries = repo.summarize(correlation_id="corr-abc")
        """
        # Get all events
        stmt = select(ParityEventModel)
        orm_events = self.db.execute(stmt).scalars().all()

        # Group by instrument and aggregate severity
        instrument_map: dict[str, dict[str, Any]] = {}

        for evt in orm_events:
            # Extract instrument from event (assume it's in details or a field).
            # For now, use a placeholder until details schema is finalized.
            instrument = "UNKNOWN"

            if instrument not in instrument_map:
                instrument_map[instrument] = {
                    "event_count": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "worst_severity": "",
                }

            counts = instrument_map[instrument]
            counts["event_count"] += 1

            # Increment severity counter
            status = evt.status.upper() if evt.status else "INFO"
            if status == "CRITICAL":
                counts["critical_count"] += 1
                if counts["worst_severity"] != "CRITICAL":
                    counts["worst_severity"] = "CRITICAL"
            elif status == "WARNING":
                counts["warning_count"] += 1
                if counts["worst_severity"] not in ("CRITICAL",):
                    counts["worst_severity"] = "WARNING"
            else:
                counts["info_count"] += 1
                if not counts["worst_severity"]:
                    counts["worst_severity"] = "INFO"

        # Convert to contracts
        summaries = [
            ParityInstrumentSummary(
                instrument=instrument,
                event_count=data["event_count"],
                critical_count=data["critical_count"],
                warning_count=data["warning_count"],
                info_count=data["info_count"],
                worst_severity=data["worst_severity"],
            )
            for instrument, data in instrument_map.items()
        ]

        logger.debug(
            "parity.summarize",
            correlation_id=correlation_id,
            instrument_count=len(summaries),
        )

        return summaries

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _orm_to_contract(orm_event: Any) -> ParityEvent:
        """
        Convert an ORM ParityEvent model to a Pydantic ParityEvent contract.

        Args:
            orm_event: SQLAlchemy ORM ParityEvent instance.

        Returns:
            ParityEvent Pydantic model.
        """
        return ParityEvent(
            id=orm_event.id,
            feed_id=orm_event.feed_id or "",
            reference_feed_id=orm_event.reference_feed_id or "",
            parity_score=orm_event.parity_score or "",
            status=orm_event.status,
            checked_at=orm_event.checked_at,
            details=orm_event.details or {},
        )

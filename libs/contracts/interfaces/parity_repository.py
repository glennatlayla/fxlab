"""
ParityRepositoryInterface — port for feed parity event data access (M8/M10).

Purpose:
    Define the contract that all parity repository implementations must
    honour, so that service and route layers depend on an abstraction (not
    on a concrete database or API adapter).

Responsibilities:
    - list() → return parity events, optionally filtered by severity/instrument/feed_id.
    - find_by_id() → return a single ParityEvent by ULID.
    - summarize() → return per-instrument parity severity aggregates.

Does NOT:
    - Contain parity computation logic (belongs in the domain/service layer).
    - Connect to any database or external system (concrete adapters do that).

Dependencies:
    - libs.contracts.parity: ParityEvent, ParityInstrumentSummary.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - find_by_id raises NotFoundError when the parity event ID is unknown.

M10 additions:
    - list() now accepts optional severity, instrument, feed_id keyword filters.
    - summarize() added for per-instrument aggregate view.

Example:
    class SqlParityRepository(ParityRepositoryInterface):
        def list(self, *, severity="", instrument="", feed_id="", correlation_id) -> list[ParityEvent]: ...
        def find_by_id(self, id: str, correlation_id: str) -> ParityEvent: ...
        def summarize(self, *, correlation_id: str) -> list[ParityInstrumentSummary]: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.parity import ParityEvent, ParityInstrumentSummary


class ParityRepositoryInterface(ABC):
    """
    Abstract port for parity event data access.

    Implementations provide either a SQL-backed adapter (production) or
    an in-memory fake (tests).  All dependency injection targets this interface.

    M10 extensions (over M8 original):
        - list() accepts optional severity, instrument, feed_id keyword filters.
        - summarize() new abstract method for per-instrument aggregates.
    """

    @abstractmethod
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
            instrument:     Filter by instrument/ticker string.  Empty = no filter.
            feed_id:        Filter by feed ULID (matches either feed_id_official or
                            feed_id_shadow).  Empty = no filter.
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            List of ParityEvent matching all non-empty filter criteria (AND semantics).
            Returns all events when all filter args are empty strings.

        Raises:
            ExternalServiceError: On underlying storage failure.

        Example:
            events = repo.list(severity="CRITICAL", correlation_id="corr-123")
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def summarize(self, *, correlation_id: str) -> list[ParityInstrumentSummary]:
        """
        Return per-instrument parity severity aggregates.

        Groups all events by instrument and computes:
        - event_count: total events for the instrument.
        - critical_count / warning_count / info_count: per-severity breakdown.
        - worst_severity: highest severity seen ("CRITICAL" > "WARNING" > "INFO"),
          or "" when the instrument has no events.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            List of ParityInstrumentSummary, one entry per unique instrument
            that has at least one event.  Empty list when no events exist.

        Raises:
            ExternalServiceError: On underlying storage failure.

        Example:
            summaries = repo.summarize(correlation_id="corr-abc")
            # summaries[0].worst_severity == "CRITICAL"
        """
        ...

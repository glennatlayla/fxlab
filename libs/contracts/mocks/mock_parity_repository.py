"""
MockParityRepository — in-memory ParityRepositoryInterface for unit tests (M8/M10).

Purpose:
    Provide a fast, fully controllable fake implementation of
    ParityRepositoryInterface so that unit tests can exercise parity route
    handlers without a real database.

Responsibilities:
    - Store ParityEvent objects in memory, keyed by event id (ULID).
    - Implement list() with optional severity/instrument/feed_id filtering (M10).
    - Implement find_by_id() with NotFoundError on miss.
    - Implement summarize() to compute per-instrument aggregates (M10).
    - Provide save(), clear(), count() introspection helpers for test setup/teardown.

Does NOT:
    - Connect to any database or external system.
    - Compute parity deltas or severity classifications.

Dependencies:
    - ParityRepositoryInterface (parent).
    - ParityEvent, ParityInstrumentSummary (domain contracts).
    - NotFoundError (typed exception).

Error conditions:
    - find_by_id raises NotFoundError for unknown parity event IDs.

Example:
    repo = MockParityRepository()
    repo.save(
        ParityEvent(
            id="01HQPARITY0AAAAAAAAAAAAA0",
            feed_id_official="01HQFEED0AAAAAAAAAAAAAAAA0",
            feed_id_shadow="01HQFEED0BBBBBBBBBBBBBBB1",
            instrument="AAPL",
            timestamp=datetime.now(timezone.utc),
            delta=0.05,
            delta_pct=0.003,
            severity=ParityEventSeverity.WARNING,
            detected_at=datetime.now(timezone.utc),
        )
    )
    events = repo.list(correlation_id="test")
    # events == [the saved event]
    summaries = repo.summarize(correlation_id="test")
    # summaries[0].instrument == "AAPL"
"""

from __future__ import annotations

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.parity_repository import ParityRepositoryInterface
from libs.contracts.parity import ParityEvent, ParityEventSeverity, ParityInstrumentSummary

# Severity ordering for worst_severity computation (highest wins).
_SEVERITY_RANK: dict[str, int] = {
    ParityEventSeverity.CRITICAL.value: 3,
    ParityEventSeverity.WARNING.value: 2,
    ParityEventSeverity.INFO.value: 1,
}


class MockParityRepository(ParityRepositoryInterface):
    """
    In-memory ParityRepositoryInterface for unit tests.

    Implements all M10 interface additions:
    - list() supports optional severity, instrument, feed_id keyword filters.
    - summarize() computes per-instrument aggregates from the in-memory store.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Keyed by parity event ID (ULID string).
        self._store: dict[str, ParityEvent] = {}

    # ------------------------------------------------------------------
    # ParityRepositoryInterface implementation
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        severity: str = "",
        instrument: str = "",
        feed_id: str = "",
        correlation_id: str,
    ) -> list[ParityEvent]:
        """
        Return parity events matching all non-empty filter criteria (AND semantics).

        Args:
            severity:       Exact severity string filter.  Empty = no filter.
            instrument:     Exact instrument string filter.  Empty = no filter.
            feed_id:        Feed ULID filter (matches official OR shadow).  Empty = no filter.
            correlation_id: Ignored in mock; accepted for interface parity.

        Returns:
            Filtered list of ParityEvent (all events when all filters are empty).

        Example:
            events = repo.list(severity="CRITICAL", correlation_id="c")
        """
        results = list(self._store.values())
        if severity:
            results = [e for e in results if e.severity.value == severity]
        if instrument:
            results = [e for e in results if e.instrument == instrument]
        if feed_id:
            results = [
                e for e in results
                if e.feed_id_official == feed_id or e.feed_id_shadow == feed_id
            ]
        return results

    def find_by_id(self, id: str, correlation_id: str) -> ParityEvent:
        """
        Return a single parity event by ULID.

        Args:
            id:             Parity event ULID to look up.
            correlation_id: Ignored in mock.

        Returns:
            ParityEvent matching the given ID.

        Raises:
            NotFoundError: If no parity event exists with the given ID.

        Example:
            event = repo.find_by_id("01HQPARITY0AAAAAAAAAAAAA0", "c")
        """
        if id not in self._store:
            raise NotFoundError(f"ParityEvent id={id!r} not found")
        return self._store[id]

    def summarize(self, *, correlation_id: str) -> list[ParityInstrumentSummary]:
        """
        Return per-instrument severity aggregates computed from the in-memory store.

        Groups all events by instrument.  For each instrument, counts total events
        and per-severity events, then determines worst_severity using CRITICAL > WARNING > INFO.
        Returns empty list when the store has no events.

        Args:
            correlation_id: Ignored in mock.

        Returns:
            List of ParityInstrumentSummary, one per unique instrument in the store.

        Example:
            summaries = repo.summarize(correlation_id="c")
            aapl = next(s for s in summaries if s.instrument == "AAPL")
            assert aapl.critical_count == 1
        """
        # Build per-instrument buckets.
        buckets: dict[str, list[ParityEvent]] = {}
        for event in self._store.values():
            buckets.setdefault(event.instrument, []).append(event)

        summaries: list[ParityInstrumentSummary] = []
        for instr, events in buckets.items():
            critical_count = sum(1 for e in events if e.severity == ParityEventSeverity.CRITICAL)
            warning_count = sum(1 for e in events if e.severity == ParityEventSeverity.WARNING)
            info_count = sum(1 for e in events if e.severity == ParityEventSeverity.INFO)

            # worst_severity: highest-rank severity present, or "" if no events.
            worst = ""
            best_rank = 0
            for e in events:
                rank = _SEVERITY_RANK.get(e.severity.value, 0)
                if rank > best_rank:
                    best_rank = rank
                    worst = e.severity.value

            summaries.append(
                ParityInstrumentSummary(
                    instrument=instr,
                    event_count=len(events),
                    critical_count=critical_count,
                    warning_count=warning_count,
                    info_count=info_count,
                    worst_severity=worst,
                )
            )
        return summaries

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def save(self, event: ParityEvent) -> None:
        """
        Persist a ParityEvent to the in-memory store.

        Args:
            event: ParityEvent to store; keyed by event.id.
        """
        self._store[event.id] = event

    def clear(self) -> None:
        """Remove all stored parity events."""
        self._store.clear()

    def count(self) -> int:
        """Return the number of stored parity events."""
        return len(self._store)

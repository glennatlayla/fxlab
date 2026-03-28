"""
MockDiagnosticsRepository — in-memory DiagnosticsRepositoryInterface (M11).

Purpose:
    Provide a fast, fully controllable fake for DiagnosticsRepositoryInterface
    so that unit tests can exercise the GET /health/diagnostics endpoint without
    a real database or aggregation service.

Responsibilities:
    - Default snapshot() returns all counts as 0 (clean system state).
    - set_snapshot(**fields) allows tests to inject specific count values.
    - Provide clear() introspection helper.

Does NOT:
    - Connect to any database or external system.
    - Aggregate from real queue/parity/certification repositories.

Dependencies:
    - DiagnosticsRepositoryInterface (parent).
    - DiagnosticsSnapshot (domain contract).

Error conditions:
    - No errors raised by this mock; snapshot() always returns a response.

Example:
    repo = MockDiagnosticsRepository()
    snap = repo.snapshot(correlation_id="c")
    assert snap.parity_critical_count == 0

    repo.set_snapshot(parity_critical_count=3, certification_blocked_count=1)
    snap = repo.snapshot(correlation_id="c")
    assert snap.parity_critical_count == 3
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.diagnostics_repository import DiagnosticsRepositoryInterface
from libs.contracts.observability import DiagnosticsSnapshot


class MockDiagnosticsRepository(DiagnosticsRepositoryInterface):
    """
    In-memory DiagnosticsRepositoryInterface for unit tests.

    All counts default to 0.  Individual counts can be overridden via
    set_snapshot() to simulate various operational states.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Current snapshot values; all default to 0.
        self._queue_contention_count: int = 0
        self._feed_health_count: int = 0
        self._parity_critical_count: int = 0
        self._certification_blocked_count: int = 0

    # ------------------------------------------------------------------
    # DiagnosticsRepositoryInterface implementation
    # ------------------------------------------------------------------

    def snapshot(self, *, correlation_id: str) -> DiagnosticsSnapshot:
        """
        Return the current platform diagnostics snapshot.

        Args:
            correlation_id: Ignored in mock.

        Returns:
            DiagnosticsSnapshot with the counts set via set_snapshot()
            (all 0 by default).

        Example:
            snap = repo.snapshot(correlation_id="c")
            assert snap.queue_contention_count == 0
        """
        return DiagnosticsSnapshot(
            queue_contention_count=self._queue_contention_count,
            feed_health_count=self._feed_health_count,
            parity_critical_count=self._parity_critical_count,
            certification_blocked_count=self._certification_blocked_count,
            generated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Test configuration helpers
    # ------------------------------------------------------------------

    def set_snapshot(
        self,
        *,
        queue_contention_count: int = 0,
        feed_health_count: int = 0,
        parity_critical_count: int = 0,
        certification_blocked_count: int = 0,
    ) -> None:
        """
        Configure the count values returned by the next snapshot() call.

        All keyword arguments default to 0 so callers only need to specify
        the fields they want to set.

        Args:
            queue_contention_count:      Number of queue classes with active contention.
            feed_health_count:           Total feed health snapshots in the system.
            parity_critical_count:       Number of CRITICAL parity events.
            certification_blocked_count: Number of BLOCKED certified feeds.

        Example:
            repo.set_snapshot(parity_critical_count=3, certification_blocked_count=1)
        """
        self._queue_contention_count = queue_contention_count
        self._feed_health_count = feed_health_count
        self._parity_critical_count = parity_critical_count
        self._certification_blocked_count = certification_blocked_count

    def clear(self) -> None:
        """Reset all snapshot counts to 0."""
        self._queue_contention_count = 0
        self._feed_health_count = 0
        self._parity_critical_count = 0
        self._certification_blocked_count = 0

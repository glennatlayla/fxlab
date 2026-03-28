"""
DiagnosticsRepositoryInterface — port for platform-wide operational snapshot (M11).

Purpose:
    Define the contract that all diagnostics repository implementations must
    honour, so the observability route layer depends on an abstraction (not on
    concrete cross-repo aggregation logic).

Responsibilities:
    - snapshot() → return a DiagnosticsSnapshot with current platform operational counts.

Does NOT:
    - Access individual entity repositories directly (concrete implementations do).
    - Contain classification or threshold logic.

Dependencies:
    - libs.contracts.observability: DiagnosticsSnapshot.

Example:
    class SqlDiagnosticsRepository(DiagnosticsRepositoryInterface):
        def snapshot(self, *, correlation_id: str) -> DiagnosticsSnapshot:
            # Query queue, feed health, parity, and certification counts.
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.observability import DiagnosticsSnapshot


class DiagnosticsRepositoryInterface(ABC):
    """
    Abstract port for platform-wide operational diagnostics aggregation.

    Implementations provide either a SQL/real aggregator (production) or a
    configurable in-memory fake (tests).
    """

    @abstractmethod
    def snapshot(self, *, correlation_id: str) -> DiagnosticsSnapshot:
        """
        Return a platform-wide operational snapshot.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            DiagnosticsSnapshot containing:
            - queue_contention_count
            - feed_health_count
            - parity_critical_count
            - certification_blocked_count
            - generated_at

        Raises:
            ExternalServiceError: On underlying storage failure.

        Example:
            snap = repo.snapshot(correlation_id="corr-abc")
            assert snap.parity_critical_count >= 0
        """
        ...

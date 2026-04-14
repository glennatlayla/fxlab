"""
In-memory mock implementation of QueueServiceInterface.

Responsibilities:
- Return a configurable ContentionReport for unit tests.
- Allow tests to inject queue snapshot data programmatically.
- Track how many times get_contention_report() was called.

Does NOT:
- Connect to any queue backend.
- Contain scheduling logic.

Example:
    svc = MockQueueService()
    svc.set_snapshot(QueueDepthSnapshot(
        queue_name="optimization", depth=5, contention_score=42.0
    ))
    report = svc.get_contention_report()
    assert report.overall_score == 42.0
"""

from libs.jobs.interfaces.queue import (
    ContentionReport,
    QueueDepthSnapshot,
    QueueServiceInterface,
)


class MockQueueService(QueueServiceInterface):
    """
    Configurable in-memory queue service for unit testing.

    Responsibilities:
    - Return ContentionReport composed from injected snapshots.
    - Track call counts for test assertions.

    Does NOT:
    - Connect to Redis or any real queue.

    Example:
        svc = MockQueueService(overall_score=55.0)
        svc.add_snapshot(QueueDepthSnapshot(
            queue_name="backtest", depth=3, contention_score=55.0
        ))
        report = svc.get_contention_report()
        assert svc.call_count == 1
    """

    def __init__(self, overall_score: float = 0.0) -> None:
        """
        Initialise with an empty snapshot list and configurable overall score.

        Args:
            overall_score: Default overall_score for the returned report.
        """
        self._snapshots: list[QueueDepthSnapshot] = []
        self._overall_score: float = overall_score
        self.call_count: int = 0

    def add_snapshot(self, snapshot: QueueDepthSnapshot) -> None:
        """
        Add a queue snapshot to be included in the next report.

        Args:
            snapshot: QueueDepthSnapshot to include.
        """
        self._snapshots.append(snapshot)

    def set_overall_score(self, score: float) -> None:
        """
        Override the overall contention score returned by the report.

        Args:
            score: New overall_score (0–100).
        """
        self._overall_score = score

    def get_contention_report(self) -> ContentionReport:
        """
        Return a ContentionReport built from the current snapshot list.

        Returns:
            ContentionReport with all registered snapshots and overall_score.
        """
        self.call_count += 1
        return ContentionReport(
            queues=list(self._snapshots),
            overall_score=self._overall_score,
        )

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset snapshots, overall score, and call counter."""
        self._snapshots.clear()
        self._overall_score = 0.0
        self.call_count = 0


__all__ = ["MockQueueService"]

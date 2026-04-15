"""
In-memory mock data quality repository for unit testing.

Responsibilities:
- Implement DataQualityRepositoryInterface with dict-backed storage.
- Support idempotent upsert for quality scores keyed by (symbol, interval, window_start).
- Provide introspection helpers for test setup and assertions.

Does NOT:
- Persist data across process restarts.
- Contain anomaly detection or quality scoring logic.
- Use SQL or any database driver.

Dependencies:
- libs.contracts.interfaces.data_quality_repository.DataQualityRepositoryInterface
- libs.contracts.data_quality (DataAnomaly, QualityScore, AnomalySeverity)
- libs.contracts.market_data (CandleInterval)

Error conditions:
- None raised by the mock (all operations succeed).

Example:
    repo = MockDataQualityRepository()
    repo.save_anomaly(anomaly)
    anomalies = repo.find_anomalies("AAPL", CandleInterval.M1, since=cutoff)
    assert len(anomalies) == 1
"""

from __future__ import annotations

from datetime import datetime

from libs.contracts.data_quality import (
    AnomalySeverity,
    DataAnomaly,
    QualityScore,
)
from libs.contracts.interfaces.data_quality_repository import (
    DataQualityRepositoryInterface,
)
from libs.contracts.market_data import CandleInterval


class MockDataQualityRepository(DataQualityRepositoryInterface):
    """
    In-memory implementation of DataQualityRepositoryInterface for unit testing.

    Stores anomalies in a dict keyed by anomaly_id and quality scores in a
    dict keyed by (symbol, interval, window_start_iso) for upsert deduplication.

    Responsibilities:
    - Behavioural parity with a SQL data quality repository.
    - Introspection helpers (count, get_all_anomalies, get_all_scores, clear).

    Does NOT:
    - Simulate database failures (tests should use separate error mocks for that).
    - Enforce foreign key constraints.

    Example:
        repo = MockDataQualityRepository()
        repo.save_anomaly(anomaly)
        assert repo.anomaly_count() == 1
    """

    def __init__(self) -> None:
        """Initialize empty in-memory stores."""
        self._anomalies: dict[str, DataAnomaly] = {}
        self._scores: dict[tuple[str, str, str], QualityScore] = {}

    # ------------------------------------------------------------------
    # DataQualityRepositoryInterface implementation
    # ------------------------------------------------------------------

    def save_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly:
        """
        Persist a data anomaly record.

        Args:
            anomaly: The anomaly to persist.

        Returns:
            The persisted anomaly (unchanged).

        Example:
            saved = repo.save_anomaly(anomaly)
        """
        self._anomalies[anomaly.anomaly_id] = anomaly
        return anomaly

    def save_anomalies(self, anomalies: list[DataAnomaly]) -> int:
        """
        Persist multiple anomaly records.

        Args:
            anomalies: List of anomalies to persist.

        Returns:
            Number of anomalies persisted.

        Example:
            count = repo.save_anomalies([a1, a2])
        """
        for anomaly in anomalies:
            self._anomalies[anomaly.anomaly_id] = anomaly
        return len(anomalies)

    def save_quality_score(self, score: QualityScore) -> QualityScore:
        """
        Persist a quality score, upserting on (symbol, interval, window_start).

        Args:
            score: The quality score to persist.

        Returns:
            The persisted quality score (unchanged).

        Example:
            saved = repo.save_quality_score(score)
        """
        key = (score.symbol.upper(), score.interval.value, score.window_start.isoformat())
        self._scores[key] = score
        return score

    def find_anomalies(
        self,
        symbol: str,
        interval: CandleInterval,
        since: datetime,
        severity: AnomalySeverity | None = None,
        resolved: bool | None = None,
        limit: int = 100,
    ) -> list[DataAnomaly]:
        """
        Query anomalies by symbol, interval, and time range.

        Args:
            symbol: Ticker symbol to filter by.
            interval: Candle interval to filter by.
            since: Only return anomalies detected after this time.
            severity: Optional severity filter.
            resolved: Optional filter for resolved/unresolved.
            limit: Maximum number of results.

        Returns:
            List of matching anomalies, ordered by detected_at descending.

        Example:
            anomalies = repo.find_anomalies("AAPL", CandleInterval.M1, since=cutoff)
        """
        symbol_upper = symbol.upper()
        results = []
        for anomaly in self._anomalies.values():
            if anomaly.symbol != symbol_upper:
                continue
            if anomaly.interval != interval:
                continue
            if anomaly.detected_at <= since:
                continue
            if severity is not None and anomaly.severity != severity:
                continue
            if resolved is not None and anomaly.resolved != resolved:
                continue
            results.append(anomaly)

        # Sort by detected_at descending
        results.sort(key=lambda a: a.detected_at, reverse=True)
        return results[:limit]

    def get_latest_score(
        self,
        symbol: str,
        interval: CandleInterval,
    ) -> QualityScore | None:
        """
        Get the most recent quality score for a symbol and interval.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.

        Returns:
            The most recent QualityScore, or None if no scores exist.

        Example:
            score = repo.get_latest_score("AAPL", CandleInterval.D1)
        """
        symbol_upper = symbol.upper()
        matching = [
            s for s in self._scores.values() if s.symbol == symbol_upper and s.interval == interval
        ]
        if not matching:
            return None
        return max(matching, key=lambda s: s.window_start)

    def get_score_history(
        self,
        symbol: str,
        interval: CandleInterval,
        since: datetime,
        limit: int = 100,
    ) -> list[QualityScore]:
        """
        Get historical quality scores for a symbol and interval.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            since: Only return scores after this time.
            limit: Maximum number of results.

        Returns:
            List of quality scores, ordered by window_start descending.

        Example:
            history = repo.get_score_history("AAPL", CandleInterval.D1, since=cutoff)
        """
        symbol_upper = symbol.upper()
        results = [
            s
            for s in self._scores.values()
            if s.symbol == symbol_upper and s.interval == interval and s.window_start > since
        ]
        results.sort(key=lambda s: s.window_start, reverse=True)
        return results[:limit]

    def count_anomalies(
        self,
        symbol: str,
        interval: CandleInterval,
        since: datetime,
        severity: AnomalySeverity | None = None,
    ) -> int:
        """
        Count anomalies matching the given filters.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            since: Only count anomalies after this time.
            severity: Optional severity filter.

        Returns:
            Number of matching anomalies.

        Example:
            count = repo.count_anomalies("AAPL", CandleInterval.M1, since=cutoff)
        """
        return len(
            self.find_anomalies(
                symbol=symbol,
                interval=interval,
                since=since,
                severity=severity,
                limit=999_999,
            )
        )

    def resolve_anomaly(self, anomaly_id: str, resolved_at: datetime) -> bool:
        """
        Mark an anomaly as resolved.

        Args:
            anomaly_id: ID of the anomaly to resolve.
            resolved_at: Timestamp of resolution.

        Returns:
            True if the anomaly was found and resolved, False if not found.

        Example:
            success = repo.resolve_anomaly("anom-001", datetime.now(tz=utc))
        """
        if anomaly_id not in self._anomalies:
            return False
        old = self._anomalies[anomaly_id]
        # DataAnomaly is frozen, so we need to create a new instance
        self._anomalies[anomaly_id] = DataAnomaly(
            anomaly_id=old.anomaly_id,
            symbol=old.symbol,
            interval=old.interval,
            anomaly_type=old.anomaly_type,
            severity=old.severity,
            detected_at=old.detected_at,
            bar_timestamp=old.bar_timestamp,
            details=old.details,
            resolved=True,
            resolved_at=resolved_at,
        )
        return True

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def anomaly_count(self) -> int:
        """Return the total number of stored anomalies."""
        return len(self._anomalies)

    def score_count(self) -> int:
        """Return the total number of stored quality scores."""
        return len(self._scores)

    def get_all_anomalies(self) -> list[DataAnomaly]:
        """Return all stored anomalies (unordered)."""
        return list(self._anomalies.values())

    def get_all_scores(self) -> list[QualityScore]:
        """Return all stored quality scores (unordered)."""
        return list(self._scores.values())

    def clear(self) -> None:
        """Remove all stored anomalies and scores."""
        self._anomalies.clear()
        self._scores.clear()

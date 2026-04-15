"""
Data quality repository interface (port).

Responsibilities:
- Define the abstract contract for persisting and querying data quality
  anomalies and quality scores.
- Enable substitution of SQL and mock implementations without changing
  service code.

Does NOT:
- Execute any I/O or database operations.
- Contain anomaly detection logic or quality scoring.
- Know about specific database engines.

Dependencies:
- libs.contracts.data_quality: DataAnomaly, QualityScore, AnomalySeverity
- libs.contracts.market_data: CandleInterval

Error conditions:
- save_anomaly: implementors may raise ExternalServiceError on persistence failure.
- save_quality_score: implementors may raise ExternalServiceError on persistence failure.
- find_anomalies: returns empty list if no matches found.
- get_latest_score: returns None if no score exists.

Example:
    repo: DataQualityRepositoryInterface = MockDataQualityRepository()
    repo.save_anomaly(anomaly)
    anomalies = repo.find_anomalies("AAPL", CandleInterval.M1, since=some_dt)
    score = repo.get_latest_score("AAPL", CandleInterval.D1)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.data_quality import (
    AnomalySeverity,
    DataAnomaly,
    QualityScore,
)
from libs.contracts.market_data import CandleInterval


class DataQualityRepositoryInterface(ABC):
    """
    Port interface for data quality persistence.

    Responsibilities:
    - Persist anomaly records for audit and trend analysis.
    - Persist quality scores for readiness checks and dashboards.
    - Query anomalies and scores with filtering by symbol, interval, time range.

    Does NOT:
    - Detect anomalies (service responsibility).
    - Compute quality scores (service responsibility).

    Example:
        repo = SqlDataQualityRepository(session_factory)
        repo.save_anomaly(anomaly)
        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
    """

    @abstractmethod
    def save_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly:
        """
        Persist a data anomaly record.

        Args:
            anomaly: The anomaly to persist.

        Returns:
            The persisted anomaly (unchanged).

        Raises:
            ExternalServiceError: On persistence failure.

        Example:
            saved = repo.save_anomaly(anomaly)
        """

    @abstractmethod
    def save_anomalies(self, anomalies: list[DataAnomaly]) -> int:
        """
        Persist multiple anomaly records in a single operation.

        Args:
            anomalies: List of anomalies to persist.

        Returns:
            Number of anomalies persisted.

        Raises:
            ExternalServiceError: On persistence failure.

        Example:
            count = repo.save_anomalies([anomaly1, anomaly2])
        """

    @abstractmethod
    def save_quality_score(self, score: QualityScore) -> QualityScore:
        """
        Persist a quality score. Upserts on (symbol, interval, window_start).

        Args:
            score: The quality score to persist.

        Returns:
            The persisted quality score (unchanged).

        Raises:
            ExternalServiceError: On persistence failure.

        Example:
            saved = repo.save_quality_score(score)
        """

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

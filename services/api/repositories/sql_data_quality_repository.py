"""
SQL-backed data quality repository for anomaly and score persistence.

Purpose:
    Persist and query data quality anomalies and composite quality scores
    in PostgreSQL/SQLite via SQLAlchemy, implementing
    DataQualityRepositoryInterface.

Responsibilities:
    - Save individual and batch anomaly records to the data_anomalies table.
    - Save quality scores with upsert semantics on
      (symbol, interval, window_start) to the quality_scores table.
    - Query anomalies with filtering by symbol, interval, time range,
      severity, and resolved status.
    - Query quality scores: latest, history with time range filtering.
    - Count anomalies with optional severity filtering.
    - Resolve anomalies by ID.

Does NOT:
    - Detect anomalies (service layer responsibility).
    - Compute quality scores (service layer responsibility).
    - Call session.commit() — uses flush() for request-scoped transactions.
    - Contain business logic or quality policy evaluation.

Dependencies:
    - SQLAlchemy Session (injected).
    - libs.contracts.models.DataAnomalyRecord ORM model.
    - libs.contracts.models.QualityScoreRecord ORM model.
    - libs.contracts.interfaces.data_quality_repository.DataQualityRepositoryInterface.

Error conditions:
    - save_anomaly / save_anomalies: may raise on database constraint violation.
    - resolve_anomaly: returns False if anomaly_id does not exist.

Example:
    repo = SqlDataQualityRepository(db=session)
    repo.save_anomaly(anomaly)
    anomalies = repo.find_anomalies("AAPL", CandleInterval.M1, since=cutoff)
    score = repo.get_latest_score("AAPL", CandleInterval.D1)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from libs.contracts.data_quality import (
    AnomalySeverity,
    AnomalyType,
    DataAnomaly,
    QualityGrade,
    QualityScore,
)
from libs.contracts.interfaces.data_quality_repository import (
    DataQualityRepositoryInterface,
)
from libs.contracts.market_data import CandleInterval
from libs.contracts.models import DataAnomalyRecord, QualityScoreRecord

logger = structlog.get_logger(__name__)


class SqlDataQualityRepository(DataQualityRepositoryInterface):
    """
    SQLAlchemy implementation of DataQualityRepositoryInterface.

    Responsibilities:
    - Map between domain DataAnomaly / QualityScore objects and ORM records.
    - Use session.flush() (not commit) for request-scoped transactions.
    - Normalise symbols to uppercase for case-insensitive matching.

    Does NOT:
    - Contain anomaly detection or quality scoring logic.
    - Manage transaction commit/rollback (handled by caller or middleware).

    Dependencies:
    - SQLAlchemy Session (injected via constructor).

    Example:
        repo = SqlDataQualityRepository(db=session)
        repo.save_anomaly(anomaly)
        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Timezone helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        """
        Attach UTC timezone if the datetime is naive.

        SQLite strips tzinfo from stored datetimes.  This method re-attaches
        UTC so domain objects always carry timezone-aware values.

        Args:
            dt: A datetime that may or may not have tzinfo.

        Returns:
            The datetime with tzinfo=UTC, or None if input is None.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    # ------------------------------------------------------------------
    # Domain ↔ ORM mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _anomaly_to_record(anomaly: DataAnomaly) -> DataAnomalyRecord:
        """
        Convert a domain DataAnomaly to an ORM DataAnomalyRecord.

        Args:
            anomaly: Domain anomaly object.

        Returns:
            ORM record ready for persistence.

        Example:
            record = SqlDataQualityRepository._anomaly_to_record(anomaly)
        """
        return DataAnomalyRecord(
            id=anomaly.anomaly_id,
            symbol=anomaly.symbol.upper(),
            interval=anomaly.interval.value,
            anomaly_type=anomaly.anomaly_type.value,
            severity=anomaly.severity.value,
            detected_at=anomaly.detected_at,
            bar_timestamp=anomaly.bar_timestamp,
            details=anomaly.details,
            resolved=anomaly.resolved,
            resolved_at=anomaly.resolved_at,
        )

    @staticmethod
    def _record_to_anomaly(record: DataAnomalyRecord) -> DataAnomaly:
        """
        Convert an ORM DataAnomalyRecord to a domain DataAnomaly.

        Args:
            record: ORM record from the database.

        Returns:
            Domain DataAnomaly instance.

        Example:
            anomaly = SqlDataQualityRepository._record_to_anomaly(record)
        """
        # details may come back as a JSON string depending on driver
        details = record.details
        if isinstance(details, str):
            details = json.loads(details)

        ensure = SqlDataQualityRepository._ensure_utc
        return DataAnomaly(
            anomaly_id=record.id,
            symbol=record.symbol,
            interval=CandleInterval(record.interval),
            anomaly_type=AnomalyType(record.anomaly_type),
            severity=AnomalySeverity(record.severity),
            detected_at=ensure(record.detected_at),
            bar_timestamp=ensure(record.bar_timestamp),
            details=details if details else {},
            resolved=record.resolved,
            resolved_at=ensure(record.resolved_at),
        )

    @staticmethod
    def _score_to_record(score: QualityScore) -> QualityScoreRecord:
        """
        Convert a domain QualityScore to an ORM QualityScoreRecord.

        Dimension scores are stored as string representations of Decimal
        for precise numeric storage in the quality_scores table.

        Args:
            score: Domain quality score object.

        Returns:
            ORM record ready for persistence.

        Example:
            record = SqlDataQualityRepository._score_to_record(score)
        """
        # Generate a deterministic-ish ID for upsert matching
        score_id = f"qs-{score.symbol}-{score.interval.value}-{score.window_start.isoformat()}"
        return QualityScoreRecord(
            id=score_id,
            symbol=score.symbol.upper(),
            interval=score.interval.value,
            window_start=score.window_start,
            window_end=score.window_end,
            completeness=str(score.completeness),
            timeliness=str(score.timeliness),
            consistency=str(score.consistency),
            accuracy=str(score.accuracy),
            composite_score=str(score.composite_score),
            grade=score.grade.value,
            anomaly_count=score.anomaly_count,
            scored_at=score.scored_at or score.window_end,
        )

    @staticmethod
    def _record_to_score(record: QualityScoreRecord) -> QualityScore:
        """
        Convert an ORM QualityScoreRecord to a domain QualityScore.

        Parses string-encoded numeric fields back into floats.

        Args:
            record: ORM record from the database.

        Returns:
            Domain QualityScore instance.

        Raises:
            ValueError: If stored numeric values cannot be parsed.

        Example:
            score = SqlDataQualityRepository._record_to_score(record)
        """
        ensure = SqlDataQualityRepository._ensure_utc
        return QualityScore(
            symbol=record.symbol,
            interval=CandleInterval(record.interval),
            window_start=ensure(record.window_start),
            window_end=ensure(record.window_end),
            completeness=float(record.completeness),
            timeliness=float(record.timeliness),
            consistency=float(record.consistency),
            accuracy=float(record.accuracy),
            composite_score=float(record.composite_score),
            anomaly_count=record.anomaly_count,
            grade=QualityGrade(record.grade),
            scored_at=ensure(record.scored_at),
        )

    # ------------------------------------------------------------------
    # Anomaly persistence
    # ------------------------------------------------------------------

    def save_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly:
        """
        Persist a data anomaly record.

        Args:
            anomaly: The anomaly to persist.

        Returns:
            The persisted anomaly (unchanged).

        Raises:
            SQLAlchemy exceptions on constraint violation or DB failure.

        Example:
            saved = repo.save_anomaly(anomaly)
        """
        record = self._anomaly_to_record(anomaly)
        self._db.add(record)
        self._db.flush()
        logger.debug(
            "data_quality.anomaly_saved",
            anomaly_id=anomaly.anomaly_id,
            symbol=anomaly.symbol,
            anomaly_type=anomaly.anomaly_type.value,
            severity=anomaly.severity.value,
            component="SqlDataQualityRepository",
        )
        return anomaly

    def save_anomalies(self, anomalies: list[DataAnomaly]) -> int:
        """
        Persist multiple anomaly records in a single flush.

        Args:
            anomalies: List of anomalies to persist.

        Returns:
            Number of anomalies persisted.

        Raises:
            SQLAlchemy exceptions on constraint violation or DB failure.

        Example:
            count = repo.save_anomalies([anomaly1, anomaly2])
        """
        records = [self._anomaly_to_record(a) for a in anomalies]
        self._db.add_all(records)
        self._db.flush()
        logger.debug(
            "data_quality.anomalies_batch_saved",
            count=len(records),
            component="SqlDataQualityRepository",
        )
        return len(records)

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

        Results are ordered by detected_at descending (newest first).

        Args:
            symbol: Ticker symbol to filter by (case-insensitive).
            interval: Candle interval to filter by.
            since: Only return anomalies detected after this time (exclusive).
            severity: Optional severity filter.
            resolved: Optional filter for resolved/unresolved status.
            limit: Maximum number of results (default 100).

        Returns:
            List of matching DataAnomaly objects, newest first.

        Example:
            anomalies = repo.find_anomalies("AAPL", CandleInterval.M1, since=cutoff)
        """
        query = self._db.query(DataAnomalyRecord).filter(
            DataAnomalyRecord.symbol == symbol.upper(),
            DataAnomalyRecord.interval == interval.value,
            DataAnomalyRecord.detected_at > since,
        )

        if severity is not None:
            query = query.filter(DataAnomalyRecord.severity == severity.value)

        if resolved is not None:
            query = query.filter(DataAnomalyRecord.resolved == resolved)

        query = query.order_by(DataAnomalyRecord.detected_at.desc()).limit(limit)

        records = query.all()
        logger.debug(
            "data_quality.anomalies_queried",
            symbol=symbol.upper(),
            interval=interval.value,
            result_count=len(records),
            component="SqlDataQualityRepository",
        )
        return [self._record_to_anomaly(r) for r in records]

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
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.
            since: Only count anomalies after this time (exclusive).
            severity: Optional severity filter.

        Returns:
            Number of matching anomalies.

        Example:
            count = repo.count_anomalies("AAPL", CandleInterval.M1, since=cutoff)
        """
        query = self._db.query(DataAnomalyRecord).filter(
            DataAnomalyRecord.symbol == symbol.upper(),
            DataAnomalyRecord.interval == interval.value,
            DataAnomalyRecord.detected_at > since,
        )

        if severity is not None:
            query = query.filter(DataAnomalyRecord.severity == severity.value)

        count = query.count()
        logger.debug(
            "data_quality.anomalies_counted",
            symbol=symbol.upper(),
            interval=interval.value,
            count=count,
            component="SqlDataQualityRepository",
        )
        return count

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
        updated = (
            self._db.query(DataAnomalyRecord)
            .filter(DataAnomalyRecord.id == anomaly_id)
            .update(
                {"resolved": True, "resolved_at": resolved_at},
                synchronize_session="fetch",
            )
        )
        self._db.flush()

        if updated > 0:
            logger.debug(
                "data_quality.anomaly_resolved",
                anomaly_id=anomaly_id,
                component="SqlDataQualityRepository",
            )
            return True

        logger.debug(
            "data_quality.anomaly_resolve_not_found",
            anomaly_id=anomaly_id,
            component="SqlDataQualityRepository",
        )
        return False

    # ------------------------------------------------------------------
    # Quality score persistence
    # ------------------------------------------------------------------

    def save_quality_score(self, score: QualityScore) -> QualityScore:
        """
        Persist a quality score with upsert on (symbol, interval, window_start).

        If a score with the same (symbol, interval, window_start) already exists,
        it is replaced with the new values.

        Args:
            score: The quality score to persist.

        Returns:
            The persisted quality score (unchanged).

        Raises:
            SQLAlchemy exceptions on constraint violation or DB failure.

        Example:
            saved = repo.save_quality_score(score)
        """
        norm_symbol = score.symbol.upper()
        interval_val = score.interval.value

        # Check for existing record with same natural key
        existing = (
            self._db.query(QualityScoreRecord)
            .filter(
                QualityScoreRecord.symbol == norm_symbol,
                QualityScoreRecord.interval == interval_val,
                QualityScoreRecord.window_start == score.window_start,
            )
            .first()
        )

        if existing is not None:
            # Upsert: update existing record in place
            existing.window_end = score.window_end
            existing.completeness = str(score.completeness)
            existing.timeliness = str(score.timeliness)
            existing.consistency = str(score.consistency)
            existing.accuracy = str(score.accuracy)
            existing.composite_score = str(score.composite_score)
            existing.grade = score.grade.value
            existing.anomaly_count = score.anomaly_count
            existing.scored_at = score.scored_at or score.window_end
            self._db.flush()
            logger.debug(
                "data_quality.score_upserted",
                symbol=norm_symbol,
                interval=interval_val,
                composite_score=score.composite_score,
                grade=score.grade.value,
                operation="update",
                component="SqlDataQualityRepository",
            )
        else:
            # Insert new record
            record = self._score_to_record(score)
            self._db.add(record)
            self._db.flush()
            logger.debug(
                "data_quality.score_upserted",
                symbol=norm_symbol,
                interval=interval_val,
                composite_score=score.composite_score,
                grade=score.grade.value,
                operation="insert",
                component="SqlDataQualityRepository",
            )

        return score

    def get_latest_score(
        self,
        symbol: str,
        interval: CandleInterval,
    ) -> QualityScore | None:
        """
        Get the most recent quality score for a symbol and interval.

        Args:
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.

        Returns:
            The most recent QualityScore, or None if no scores exist.

        Example:
            score = repo.get_latest_score("AAPL", CandleInterval.D1)
        """
        record = (
            self._db.query(QualityScoreRecord)
            .filter(
                QualityScoreRecord.symbol == symbol.upper(),
                QualityScoreRecord.interval == interval.value,
            )
            .order_by(QualityScoreRecord.window_start.desc())
            .first()
        )

        if record is None:
            return None

        return self._record_to_score(record)

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
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.
            since: Only return scores with window_start after this time (exclusive).
            limit: Maximum number of results (default 100).

        Returns:
            List of QualityScore objects, ordered by window_start descending.

        Example:
            history = repo.get_score_history("AAPL", CandleInterval.D1, since=cutoff)
        """
        records = (
            self._db.query(QualityScoreRecord)
            .filter(
                QualityScoreRecord.symbol == symbol.upper(),
                QualityScoreRecord.interval == interval.value,
                QualityScoreRecord.window_start > since,
            )
            .order_by(QualityScoreRecord.window_start.desc())
            .limit(limit)
            .all()
        )

        logger.debug(
            "data_quality.score_history_queried",
            symbol=symbol.upper(),
            interval=interval.value,
            result_count=len(records),
            component="SqlDataQualityRepository",
        )
        return [self._record_to_score(r) for r in records]

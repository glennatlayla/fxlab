"""
Integration tests for SqlDataQualityRepository (Phase 8 — M1).

Tests verify that the SQL repository correctly persists and queries
data quality anomalies and quality scores against a real database,
using the SAVEPOINT isolation pattern (LL-S004).

These tests mirror the behavioural contract validated by the mock
repository unit tests, ensuring parity between the SQL and mock
implementations.

Dependencies:
- integration_db_session fixture (conftest.py): per-test SAVEPOINT-isolated session.
- DataAnomalyRecord / QualityScoreRecord ORM models must be registered in Base.metadata.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from libs.contracts.data_quality import (
    AnomalySeverity,
    AnomalyType,
    DataAnomaly,
    QualityGrade,
    QualityScore,
)
from libs.contracts.market_data import CandleInterval
from services.api.repositories.sql_data_quality_repository import (
    SqlDataQualityRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
_HOUR_AGO = _NOW - timedelta(hours=1)
_TWO_HOURS_AGO = _NOW - timedelta(hours=2)
_DAY_AGO = _NOW - timedelta(days=1)


def _make_anomaly(
    anomaly_id: str = "anom-001",
    symbol: str = "AAPL",
    severity: AnomalySeverity = AnomalySeverity.CRITICAL,
    detected_at: datetime = _NOW,
    anomaly_type: AnomalyType = AnomalyType.OHLCV_VIOLATION,
    interval: CandleInterval = CandleInterval.M1,
    resolved: bool = False,
) -> DataAnomaly:
    """Create a DataAnomaly with sensible defaults."""
    return DataAnomaly(
        anomaly_id=anomaly_id,
        symbol=symbol,
        interval=interval,
        anomaly_type=anomaly_type,
        severity=severity,
        detected_at=detected_at,
        bar_timestamp=detected_at,
        details={"test": True},
        resolved=resolved,
    )


def _make_score(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    window_start: datetime = _HOUR_AGO,
    window_end: datetime = _NOW,
    composite_score: float = 0.98,
    grade: QualityGrade = QualityGrade.A,
) -> QualityScore:
    """Create a QualityScore with sensible defaults."""
    return QualityScore(
        symbol=symbol,
        interval=interval,
        window_start=window_start,
        window_end=window_end,
        completeness=0.98,
        timeliness=0.95,
        consistency=1.0,
        accuracy=0.99,
        composite_score=composite_score,
        anomaly_count=0,
        grade=grade,
    )


# ---------------------------------------------------------------------------
# Anomaly persistence tests
# ---------------------------------------------------------------------------


class TestAnomalySaveAndFind:
    """Integration tests for anomaly save and retrieval via SQL."""

    def test_save_anomaly_roundtrip(self, integration_db_session) -> None:
        """save_anomaly persists and find_anomalies retrieves the record."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        anomaly = _make_anomaly()

        result = repo.save_anomaly(anomaly)
        assert result == anomaly

        found = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert len(found) == 1
        assert found[0].anomaly_id == "anom-001"
        assert found[0].symbol == "AAPL"
        assert found[0].anomaly_type == AnomalyType.OHLCV_VIOLATION
        assert found[0].severity == AnomalySeverity.CRITICAL

    def test_save_anomalies_batch(self, integration_db_session) -> None:
        """save_anomalies persists multiple records in a single flush."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        anomalies = [
            _make_anomaly(anomaly_id="a1"),
            _make_anomaly(anomaly_id="a2"),
            _make_anomaly(anomaly_id="a3"),
        ]

        count = repo.save_anomalies(anomalies)
        assert count == 3

        found = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert len(found) == 3

    def test_find_anomalies_by_symbol_and_interval(self, integration_db_session) -> None:
        """find_anomalies filters by symbol and interval."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", symbol="AAPL"))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2", symbol="MSFT"))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    def test_find_anomalies_since_filter(self, integration_db_session) -> None:
        """find_anomalies only returns anomalies detected after since."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="old", detected_at=_TWO_HOURS_AGO))
        repo.save_anomaly(_make_anomaly(anomaly_id="new", detected_at=_NOW))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_HOUR_AGO)
        assert len(results) == 1
        assert results[0].anomaly_id == "new"

    def test_find_anomalies_severity_filter(self, integration_db_session) -> None:
        """find_anomalies filters by severity when provided."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="warn", severity=AnomalySeverity.WARNING))
        repo.save_anomaly(_make_anomaly(anomaly_id="crit", severity=AnomalySeverity.CRITICAL))

        results = repo.find_anomalies(
            "AAPL",
            CandleInterval.M1,
            since=_DAY_AGO,
            severity=AnomalySeverity.CRITICAL,
        )
        assert len(results) == 1
        assert results[0].severity == AnomalySeverity.CRITICAL

    def test_find_anomalies_resolved_filter(self, integration_db_session) -> None:
        """find_anomalies filters by resolved status when provided."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="open", resolved=False))
        repo.save_anomaly(_make_anomaly(anomaly_id="closed", resolved=True))

        open_results = repo.find_anomalies(
            "AAPL",
            CandleInterval.M1,
            since=_DAY_AGO,
            resolved=False,
        )
        assert len(open_results) == 1
        assert open_results[0].anomaly_id == "open"

    def test_find_anomalies_ordered_by_detected_at_desc(self, integration_db_session) -> None:
        """Results are ordered by detected_at descending (newest first)."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        t1 = _NOW - timedelta(minutes=30)
        t2 = _NOW - timedelta(minutes=15)
        t3 = _NOW
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", detected_at=t1))
        repo.save_anomaly(_make_anomaly(anomaly_id="a3", detected_at=t3))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2", detected_at=t2))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert [r.anomaly_id for r in results] == ["a3", "a2", "a1"]

    def test_find_anomalies_limit(self, integration_db_session) -> None:
        """find_anomalies respects the limit parameter."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        for i in range(10):
            repo.save_anomaly(
                _make_anomaly(
                    anomaly_id=f"a{i}",
                    detected_at=_NOW + timedelta(minutes=i),
                )
            )

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO, limit=3)
        assert len(results) == 3

    def test_find_anomalies_symbol_case_insensitive(self, integration_db_session) -> None:
        """Symbol matching is case-insensitive."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", symbol="aapl"))

        results = repo.find_anomalies("Aapl", CandleInterval.M1, since=_DAY_AGO)
        assert len(results) == 1

    def test_anomaly_details_json_roundtrip(self, integration_db_session) -> None:
        """Anomaly details dict survives JSON serialization roundtrip."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        details = {"high": "170.00", "low": "175.00", "issue": "high < low"}
        anomaly = DataAnomaly(
            anomaly_id="anom-json",
            symbol="AAPL",
            interval=CandleInterval.M1,
            anomaly_type=AnomalyType.OHLCV_VIOLATION,
            severity=AnomalySeverity.CRITICAL,
            detected_at=_NOW,
            bar_timestamp=_NOW,
            details=details,
        )
        repo.save_anomaly(anomaly)

        found = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert len(found) == 1
        assert found[0].details == details


# ---------------------------------------------------------------------------
# Anomaly resolution tests
# ---------------------------------------------------------------------------


class TestResolveAnomaly:
    """Integration tests for resolve_anomaly via SQL."""

    def test_resolve_existing_anomaly(self, integration_db_session) -> None:
        """resolve_anomaly marks an existing anomaly as resolved."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="a1"))

        success = repo.resolve_anomaly("a1", _NOW)
        assert success is True

        # Verify the resolved status persisted
        found = repo.find_anomalies(
            "AAPL",
            CandleInterval.M1,
            since=_DAY_AGO,
            resolved=True,
        )
        assert len(found) == 1
        assert found[0].resolved is True
        assert found[0].resolved_at == _NOW

    def test_resolve_nonexistent_anomaly_returns_false(self, integration_db_session) -> None:
        """resolve_anomaly returns False for unknown anomaly_id."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        assert repo.resolve_anomaly("nonexistent", _NOW) is False

    def test_count_anomalies(self, integration_db_session) -> None:
        """count_anomalies returns correct count with filters."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", severity=AnomalySeverity.CRITICAL))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2", severity=AnomalySeverity.WARNING))
        repo.save_anomaly(_make_anomaly(anomaly_id="a3", severity=AnomalySeverity.CRITICAL))

        total = repo.count_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert total == 3

        critical = repo.count_anomalies(
            "AAPL",
            CandleInterval.M1,
            since=_DAY_AGO,
            severity=AnomalySeverity.CRITICAL,
        )
        assert critical == 2


# ---------------------------------------------------------------------------
# Quality score persistence tests
# ---------------------------------------------------------------------------


class TestScoreSaveAndRetrieve:
    """Integration tests for quality score save and retrieval via SQL."""

    def test_save_score_roundtrip(self, integration_db_session) -> None:
        """save_quality_score persists and get_latest_score retrieves."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        score = _make_score()

        result = repo.save_quality_score(score)
        assert result == score

        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.symbol == "AAPL"
        assert latest.composite_score == 0.98
        assert latest.grade == QualityGrade.A

    def test_upsert_on_same_key(self, integration_db_session) -> None:
        """Saving a score with same natural key replaces the old one."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        score1 = _make_score(composite_score=0.80, grade=QualityGrade.B)
        score2 = _make_score(composite_score=0.95, grade=QualityGrade.A)

        repo.save_quality_score(score1)
        repo.save_quality_score(score2)

        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.composite_score == 0.95

    def test_get_latest_score_returns_most_recent(self, integration_db_session) -> None:
        """get_latest_score returns the score with the newest window_start."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_quality_score(
            _make_score(
                window_start=_TWO_HOURS_AGO,
                window_end=_HOUR_AGO,
            )
        )
        repo.save_quality_score(
            _make_score(
                window_start=_HOUR_AGO,
                window_end=_NOW,
            )
        )

        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.window_start == _HOUR_AGO

    def test_get_latest_score_returns_none_when_empty(self, integration_db_session) -> None:
        """get_latest_score returns None when no scores exist."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        assert repo.get_latest_score("AAPL", CandleInterval.D1) is None

    def test_get_latest_score_filters_by_symbol(self, integration_db_session) -> None:
        """get_latest_score only returns scores for the requested symbol."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_quality_score(_make_score(symbol="AAPL"))
        repo.save_quality_score(_make_score(symbol="MSFT"))

        latest = repo.get_latest_score("MSFT", CandleInterval.D1)
        assert latest is not None
        assert latest.symbol == "MSFT"

    def test_get_latest_score_filters_by_interval(self, integration_db_session) -> None:
        """get_latest_score only returns scores for the requested interval."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_quality_score(_make_score(interval=CandleInterval.M1))
        repo.save_quality_score(_make_score(interval=CandleInterval.D1))

        latest = repo.get_latest_score("AAPL", CandleInterval.M1)
        assert latest is not None
        assert latest.interval == CandleInterval.M1

    def test_numeric_precision_preserved(self, integration_db_session) -> None:
        """Quality score numeric values survive string serialization roundtrip."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        score = QualityScore(
            symbol="AAPL",
            interval=CandleInterval.D1,
            window_start=_HOUR_AGO,
            window_end=_NOW,
            completeness=0.123456789,
            timeliness=0.987654321,
            consistency=0.555555555,
            accuracy=0.777777777,
            composite_score=0.611111111,
            anomaly_count=5,
            grade=QualityGrade.C,
        )
        repo.save_quality_score(score)

        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
        assert latest is not None
        # Float precision should be preserved through str() roundtrip
        assert abs(latest.completeness - 0.123456789) < 1e-9
        assert abs(latest.timeliness - 0.987654321) < 1e-9
        assert abs(latest.consistency - 0.555555555) < 1e-9
        assert abs(latest.accuracy - 0.777777777) < 1e-9
        assert abs(latest.composite_score - 0.611111111) < 1e-9


# ---------------------------------------------------------------------------
# Score history tests
# ---------------------------------------------------------------------------


class TestScoreHistory:
    """Integration tests for get_score_history via SQL."""

    def test_score_history_ordered_desc(self, integration_db_session) -> None:
        """Score history is ordered by window_start descending."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        for i in range(5):
            ws = _NOW - timedelta(hours=5 - i)
            we = ws + timedelta(hours=1)
            repo.save_quality_score(_make_score(window_start=ws, window_end=we))

        history = repo.get_score_history("AAPL", CandleInterval.D1, since=_DAY_AGO)
        assert len(history) == 5
        for i in range(len(history) - 1):
            assert history[i].window_start >= history[i + 1].window_start

    def test_score_history_since_filter(self, integration_db_session) -> None:
        """Score history only returns scores after since."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        repo.save_quality_score(
            _make_score(
                window_start=_TWO_HOURS_AGO,
                window_end=_HOUR_AGO,
            )
        )
        repo.save_quality_score(
            _make_score(
                window_start=_HOUR_AGO,
                window_end=_NOW,
            )
        )

        history = repo.get_score_history(
            "AAPL",
            CandleInterval.D1,
            since=_TWO_HOURS_AGO,
        )
        assert len(history) == 1
        assert history[0].window_start == _HOUR_AGO

    def test_score_history_limit(self, integration_db_session) -> None:
        """Score history respects the limit parameter."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        for i in range(10):
            ws = _NOW - timedelta(hours=10 - i)
            we = ws + timedelta(hours=1)
            repo.save_quality_score(_make_score(window_start=ws, window_end=we))

        history = repo.get_score_history(
            "AAPL",
            CandleInterval.D1,
            since=_DAY_AGO,
            limit=3,
        )
        assert len(history) == 3

    def test_score_history_empty(self, integration_db_session) -> None:
        """Score history returns empty list when no scores match."""
        repo = SqlDataQualityRepository(db=integration_db_session)
        history = repo.get_score_history("AAPL", CandleInterval.D1, since=_DAY_AGO)
        assert history == []

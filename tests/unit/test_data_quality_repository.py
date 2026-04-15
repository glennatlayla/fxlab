"""
Unit tests for MockDataQualityRepository (Phase 8 — M0).

Tests verify behavioural parity with what a SQL implementation would provide:
- Save and retrieve anomalies with filtering.
- Save and retrieve quality scores with upsert semantics.
- Symbol normalization to uppercase.
- Time-range filtering (since parameter).
- Severity filtering.
- Resolved/unresolved filtering.
- Resolve anomaly by ID.
- Introspection helpers.
- Score history and latest score ordering.
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
from libs.contracts.mocks.mock_data_quality_repository import (
    MockDataQualityRepository,
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
    """Tests for anomaly save and retrieval."""

    def test_save_anomaly_returns_same_object(self) -> None:
        """save_anomaly returns the persisted anomaly unchanged."""
        repo = MockDataQualityRepository()
        anomaly = _make_anomaly()
        result = repo.save_anomaly(anomaly)
        assert result == anomaly

    def test_save_anomaly_increments_count(self) -> None:
        """Saving an anomaly increases the anomaly count."""
        repo = MockDataQualityRepository()
        assert repo.anomaly_count() == 0
        repo.save_anomaly(_make_anomaly())
        assert repo.anomaly_count() == 1

    def test_save_anomalies_batch(self) -> None:
        """save_anomalies persists multiple anomalies and returns count."""
        repo = MockDataQualityRepository()
        anomalies = [
            _make_anomaly(anomaly_id="a1"),
            _make_anomaly(anomaly_id="a2"),
            _make_anomaly(anomaly_id="a3"),
        ]
        count = repo.save_anomalies(anomalies)
        assert count == 3
        assert repo.anomaly_count() == 3

    def test_find_anomalies_by_symbol_and_interval(self) -> None:
        """find_anomalies filters by symbol and interval."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", symbol="AAPL"))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2", symbol="MSFT"))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    def test_find_anomalies_since_filter(self) -> None:
        """find_anomalies only returns anomalies detected after since."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly(anomaly_id="old", detected_at=_TWO_HOURS_AGO))
        repo.save_anomaly(_make_anomaly(anomaly_id="new", detected_at=_NOW))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_HOUR_AGO)
        assert len(results) == 1
        assert results[0].anomaly_id == "new"

    def test_find_anomalies_severity_filter(self) -> None:
        """find_anomalies filters by severity when provided."""
        repo = MockDataQualityRepository()
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

    def test_find_anomalies_resolved_filter(self) -> None:
        """find_anomalies filters by resolved status when provided."""
        repo = MockDataQualityRepository()
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

    def test_find_anomalies_ordered_by_detected_at_desc(self) -> None:
        """Results are ordered by detected_at descending (newest first)."""
        repo = MockDataQualityRepository()
        t1 = _NOW - timedelta(minutes=30)
        t2 = _NOW - timedelta(minutes=15)
        t3 = _NOW
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", detected_at=t1))
        repo.save_anomaly(_make_anomaly(anomaly_id="a3", detected_at=t3))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2", detected_at=t2))

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO)
        assert [r.anomaly_id for r in results] == ["a3", "a2", "a1"]

    def test_find_anomalies_limit(self) -> None:
        """find_anomalies respects the limit parameter."""
        repo = MockDataQualityRepository()
        for i in range(10):
            repo.save_anomaly(
                _make_anomaly(
                    anomaly_id=f"a{i}",
                    detected_at=_NOW + timedelta(minutes=i),
                )
            )

        results = repo.find_anomalies("AAPL", CandleInterval.M1, since=_DAY_AGO, limit=3)
        assert len(results) == 3

    def test_find_anomalies_symbol_case_insensitive(self) -> None:
        """Symbol matching is case-insensitive (both stored and queried uppercased)."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly(anomaly_id="a1", symbol="aapl"))
        results = repo.find_anomalies("Aapl", CandleInterval.M1, since=_DAY_AGO)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Anomaly resolution tests
# ---------------------------------------------------------------------------


class TestResolveAnomaly:
    """Tests for resolve_anomaly method."""

    def test_resolve_existing_anomaly(self) -> None:
        """resolve_anomaly marks an existing anomaly as resolved."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly(anomaly_id="a1"))

        success = repo.resolve_anomaly("a1", _NOW)
        assert success is True

        anomalies = repo.get_all_anomalies()
        assert anomalies[0].resolved is True
        assert anomalies[0].resolved_at == _NOW

    def test_resolve_nonexistent_anomaly_returns_false(self) -> None:
        """resolve_anomaly returns False for unknown anomaly_id."""
        repo = MockDataQualityRepository()
        assert repo.resolve_anomaly("nonexistent", _NOW) is False

    def test_count_anomalies(self) -> None:
        """count_anomalies returns correct count with filters."""
        repo = MockDataQualityRepository()
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
    """Tests for quality score save and retrieval."""

    def test_save_score_returns_same_object(self) -> None:
        """save_quality_score returns the persisted score unchanged."""
        repo = MockDataQualityRepository()
        score = _make_score()
        result = repo.save_quality_score(score)
        assert result == score

    def test_save_score_increments_count(self) -> None:
        """Saving a score increases the score count."""
        repo = MockDataQualityRepository()
        assert repo.score_count() == 0
        repo.save_quality_score(_make_score())
        assert repo.score_count() == 1

    def test_upsert_on_same_key(self) -> None:
        """Saving a score with same (symbol, interval, window_start) replaces the old one."""
        repo = MockDataQualityRepository()
        score1 = _make_score(composite_score=0.80, grade=QualityGrade.B)
        score2 = _make_score(composite_score=0.95, grade=QualityGrade.A)

        repo.save_quality_score(score1)
        repo.save_quality_score(score2)

        assert repo.score_count() == 1
        latest = repo.get_latest_score("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.composite_score == 0.95

    def test_get_latest_score_returns_most_recent(self) -> None:
        """get_latest_score returns the score with the newest window_start."""
        repo = MockDataQualityRepository()
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

    def test_get_latest_score_returns_none_when_empty(self) -> None:
        """get_latest_score returns None when no scores exist for the symbol."""
        repo = MockDataQualityRepository()
        assert repo.get_latest_score("AAPL", CandleInterval.D1) is None

    def test_get_latest_score_filters_by_symbol(self) -> None:
        """get_latest_score only returns scores for the requested symbol."""
        repo = MockDataQualityRepository()
        repo.save_quality_score(_make_score(symbol="AAPL"))
        repo.save_quality_score(_make_score(symbol="MSFT"))

        latest = repo.get_latest_score("MSFT", CandleInterval.D1)
        assert latest is not None
        assert latest.symbol == "MSFT"

    def test_get_latest_score_filters_by_interval(self) -> None:
        """get_latest_score only returns scores for the requested interval."""
        repo = MockDataQualityRepository()
        repo.save_quality_score(_make_score(interval=CandleInterval.M1))
        repo.save_quality_score(_make_score(interval=CandleInterval.D1))

        latest = repo.get_latest_score("AAPL", CandleInterval.M1)
        assert latest is not None
        assert latest.interval == CandleInterval.M1


# ---------------------------------------------------------------------------
# Score history tests
# ---------------------------------------------------------------------------


class TestScoreHistory:
    """Tests for get_score_history method."""

    def test_score_history_ordered_desc(self) -> None:
        """Score history is ordered by window_start descending."""
        repo = MockDataQualityRepository()
        for i in range(5):
            ws = _NOW - timedelta(hours=5 - i)
            we = ws + timedelta(hours=1)
            repo.save_quality_score(_make_score(window_start=ws, window_end=we))

        history = repo.get_score_history("AAPL", CandleInterval.D1, since=_DAY_AGO)
        assert len(history) == 5
        # Most recent first
        for i in range(len(history) - 1):
            assert history[i].window_start >= history[i + 1].window_start

    def test_score_history_since_filter(self) -> None:
        """Score history only returns scores after since."""
        repo = MockDataQualityRepository()
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

        # Since filter: only scores with window_start > _HOUR_AGO should match
        # (strict >, not >=)
        history = repo.get_score_history(
            "AAPL",
            CandleInterval.D1,
            since=_TWO_HOURS_AGO,
        )
        assert len(history) == 1
        assert history[0].window_start == _HOUR_AGO

    def test_score_history_limit(self) -> None:
        """Score history respects the limit parameter."""
        repo = MockDataQualityRepository()
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

    def test_score_history_empty(self) -> None:
        """Score history returns empty list when no scores match."""
        repo = MockDataQualityRepository()
        history = repo.get_score_history("AAPL", CandleInterval.D1, since=_DAY_AGO)
        assert history == []


# ---------------------------------------------------------------------------
# Introspection helper tests
# ---------------------------------------------------------------------------


class TestIntrospection:
    """Tests for mock introspection helpers."""

    def test_clear_removes_all(self) -> None:
        """clear() removes all anomalies and scores."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly())
        repo.save_quality_score(_make_score())

        repo.clear()

        assert repo.anomaly_count() == 0
        assert repo.score_count() == 0

    def test_get_all_anomalies(self) -> None:
        """get_all_anomalies returns all stored anomalies."""
        repo = MockDataQualityRepository()
        repo.save_anomaly(_make_anomaly(anomaly_id="a1"))
        repo.save_anomaly(_make_anomaly(anomaly_id="a2"))

        all_anomalies = repo.get_all_anomalies()
        assert len(all_anomalies) == 2

    def test_get_all_scores(self) -> None:
        """get_all_scores returns all stored quality scores."""
        repo = MockDataQualityRepository()
        repo.save_quality_score(_make_score(symbol="AAPL"))
        repo.save_quality_score(_make_score(symbol="MSFT"))

        all_scores = repo.get_all_scores()
        assert len(all_scores) == 2

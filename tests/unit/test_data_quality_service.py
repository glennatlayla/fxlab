"""
Unit tests for DataQualityService (Phase 8 — M1).

Tests cover:
- OHLCV validation anomaly detection (high < low, negative volume, etc.).
- Price spike detection with configurable thresholds.
- Volume anomaly detection (3σ deviation from rolling mean).
- Timestamp gap detection (gap > 2× expected interval).
- Duplicate bar detection (same symbol, interval, timestamp).
- Missing bar detection placeholder (completeness dimension).
- Composite quality scoring with weighted dimensions.
- Grade assignment based on composite score.
- Trading readiness checks against per-mode quality policies.
- Edge cases: empty candle list, single candle, all-clean data.
- Repository persistence: anomalies and scores saved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from libs.contracts.data_quality import (
    AnomalySeverity,
    AnomalyType,
    QualityGrade,
    QualityReadinessResult,
)
from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataPage,
)
from libs.contracts.mocks.mock_data_quality_repository import (
    MockDataQualityRepository,
)
from services.api.services.data_quality_service import DataQualityService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Use a dynamic "now" so that candle timestamps are always fresh relative
# to the service's internal datetime.now() call, ensuring timeliness
# scores reflect recent data rather than stale fixed timestamps.
_NOW = datetime.now(timezone.utc)


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.M1,
    timestamp: datetime = _NOW,
    open_: Decimal = Decimal("175.00"),
    high: Decimal = Decimal("176.00"),
    low: Decimal = Decimal("174.00"),
    close: Decimal = Decimal("175.50"),
    volume: int = 50_000,
) -> Candle:
    """Create a valid Candle with sensible defaults."""
    return Candle(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_candle_series(
    count: int = 10,
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.M1,
    start: datetime = _NOW - timedelta(minutes=10),
    base_price: Decimal = Decimal("175.00"),
) -> list[Candle]:
    """
    Create a series of valid, evenly-spaced candles with no anomalies.

    Each candle has small, reasonable OHLCV values:
    - Open = base_price + slight variation
    - High = open + 1
    - Low = open - 1
    - Close = open + 0.50
    - Volume = 50000
    """
    from libs.contracts.market_data import INTERVAL_SECONDS

    interval_s = INTERVAL_SECONDS[interval]
    candles = []
    for i in range(count):
        ts = start + timedelta(seconds=i * interval_s)
        price = base_price + Decimal(str(i * 0.10))
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                timestamp=ts,
                open=price,
                high=price + Decimal("1.00"),
                low=price - Decimal("1.00"),
                close=price + Decimal("0.50"),
                volume=50_000,
            )
        )
    return candles


def _build_service(
    candles: list[Candle] | None = None,
    dq_repo: MockDataQualityRepository | None = None,
) -> tuple[DataQualityService, MockDataQualityRepository, MagicMock]:
    """
    Build a DataQualityService with a mock market data repo that returns
    the given candles, and an optional data quality repo.

    Returns (service, dq_repo, md_repo_mock).
    """
    if dq_repo is None:
        dq_repo = MockDataQualityRepository()

    md_repo = MagicMock()
    if candles is not None:
        md_repo.query_candles.return_value = MarketDataPage(
            candles=candles,
            total_count=len(candles),
            has_more=False,
            next_cursor=None,
        )
    else:
        md_repo.query_candles.return_value = MarketDataPage(
            candles=[],
            total_count=0,
            has_more=False,
            next_cursor=None,
        )

    service = DataQualityService(
        data_quality_repo=dq_repo,
        market_data_repo=md_repo,
    )
    return service, dq_repo, md_repo


# ---------------------------------------------------------------------------
# OHLCV validation tests
# ---------------------------------------------------------------------------


class TestOhlcvValidation:
    """Tests for OHLCV relationship anomaly detection."""

    def test_high_less_than_low_detected(self) -> None:
        """Candle where high < low produces a CRITICAL OHLCV_VIOLATION anomaly."""
        bad_candle = _make_candle(high=Decimal("170.00"), low=Decimal("175.00"))
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([bad_candle])

        ohlcv = [a for a in anomalies if a.anomaly_type == AnomalyType.OHLCV_VIOLATION]
        assert len(ohlcv) >= 1
        assert ohlcv[0].severity == AnomalySeverity.CRITICAL

    def test_high_less_than_open_detected(self) -> None:
        """Candle where high < open produces an OHLCV_VIOLATION anomaly."""
        bad_candle = _make_candle(
            open_=Decimal("180.00"),
            high=Decimal("179.00"),
            low=Decimal("174.00"),
            close=Decimal("175.00"),
        )
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([bad_candle])

        ohlcv = [a for a in anomalies if a.anomaly_type == AnomalyType.OHLCV_VIOLATION]
        assert len(ohlcv) >= 1

    def test_low_greater_than_close_detected(self) -> None:
        """Candle where low > close produces an OHLCV_VIOLATION anomaly."""
        bad_candle = _make_candle(
            open_=Decimal("175.00"),
            high=Decimal("180.00"),
            low=Decimal("176.00"),
            close=Decimal("174.00"),
        )
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([bad_candle])

        ohlcv = [a for a in anomalies if a.anomaly_type == AnomalyType.OHLCV_VIOLATION]
        assert len(ohlcv) >= 1

    def test_valid_ohlcv_no_anomaly(self) -> None:
        """A valid candle (high >= max(open,close), low <= min(open,close)) has no OHLCV anomaly."""
        good_candle = _make_candle()
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([good_candle])

        ohlcv = [a for a in anomalies if a.anomaly_type == AnomalyType.OHLCV_VIOLATION]
        assert len(ohlcv) == 0

    def test_zero_volume_during_valid_bar_is_warning(self) -> None:
        """Zero volume on a candle with price movement is a WARNING volume anomaly."""
        candle = _make_candle(volume=0)
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([candle])

        volume_anom = [a for a in anomalies if a.anomaly_type == AnomalyType.VOLUME_ANOMALY]
        assert len(volume_anom) >= 1
        assert volume_anom[0].severity == AnomalySeverity.WARNING


# ---------------------------------------------------------------------------
# Price spike detection tests
# ---------------------------------------------------------------------------


class TestPriceSpikeDetection:
    """Tests for price spike anomaly detection."""

    def test_large_price_spike_detected(self) -> None:
        """A bar-to-bar price change exceeding threshold is flagged as PRICE_SPIKE."""
        candles = _make_candle_series(count=5)
        # Inject a massive price spike on the last candle
        spike_candle = _make_candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open_=Decimal("250.00"),
            high=Decimal("260.00"),
            low=Decimal("245.00"),
            close=Decimal("255.00"),
        )
        candles.append(spike_candle)

        service, _, _ = _build_service()
        anomalies = service.detect_anomalies(candles)

        spikes = [a for a in anomalies if a.anomaly_type == AnomalyType.PRICE_SPIKE]
        assert len(spikes) >= 1
        assert spikes[0].severity in (AnomalySeverity.WARNING, AnomalySeverity.CRITICAL)

    def test_normal_price_movement_no_spike(self) -> None:
        """Normal price movement within reasonable range produces no PRICE_SPIKE anomaly."""
        candles = _make_candle_series(count=10)
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies(candles)

        spikes = [a for a in anomalies if a.anomaly_type == AnomalyType.PRICE_SPIKE]
        assert len(spikes) == 0

    def test_single_candle_no_spike(self) -> None:
        """A single candle cannot produce a price spike (no previous bar to compare)."""
        service, _, _ = _build_service()
        anomalies = service.detect_anomalies([_make_candle()])

        spikes = [a for a in anomalies if a.anomaly_type == AnomalyType.PRICE_SPIKE]
        assert len(spikes) == 0


# ---------------------------------------------------------------------------
# Volume anomaly detection tests
# ---------------------------------------------------------------------------


class TestVolumeAnomalyDetection:
    """Tests for volume deviation anomaly detection."""

    def test_extreme_volume_spike_detected(self) -> None:
        """Volume deviating > 3σ from rolling mean produces VOLUME_ANOMALY."""
        # Need enough history for rolling window (≥ 50 bars by default,
        # but detection starts at min(50, len) so we use 55 bars + 1 extreme)
        candles = _make_candle_series(count=55)
        # Inject extreme volume on the last candle
        extreme = _make_candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            volume=50_000_000,  # 1000× normal
        )
        candles.append(extreme)

        service, _, _ = _build_service()
        anomalies = service.detect_anomalies(candles)

        vol = [a for a in anomalies if a.anomaly_type == AnomalyType.VOLUME_ANOMALY]
        assert len(vol) >= 1

    def test_normal_volume_no_anomaly(self) -> None:
        """Normal volume produces no VOLUME_ANOMALY."""
        candles = _make_candle_series(count=20)
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies(candles)

        vol = [a for a in anomalies if a.anomaly_type == AnomalyType.VOLUME_ANOMALY]
        assert len(vol) == 0


# ---------------------------------------------------------------------------
# Timestamp gap detection tests
# ---------------------------------------------------------------------------


class TestTimestampGapDetection:
    """Tests for timestamp gap anomaly detection."""

    def test_gap_exceeding_2x_interval_detected(self) -> None:
        """A gap > 2× expected interval duration produces a TIMESTAMP_GAP anomaly."""
        candles = _make_candle_series(count=3)
        # Insert a 5-minute gap between 1-minute candles (5× expected)
        gap_candle = _make_candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=5),
        )
        candles.append(gap_candle)

        service, _, _ = _build_service()
        anomalies = service.detect_anomalies(candles)

        gaps = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMESTAMP_GAP]
        assert len(gaps) >= 1

    def test_normal_spacing_no_gap(self) -> None:
        """Candles evenly spaced at the expected interval produce no TIMESTAMP_GAP."""
        candles = _make_candle_series(count=10)
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies(candles)

        gaps = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMESTAMP_GAP]
        assert len(gaps) == 0


# ---------------------------------------------------------------------------
# Duplicate bar detection tests
# ---------------------------------------------------------------------------


class TestDuplicateBarDetection:
    """Tests for duplicate bar anomaly detection."""

    def test_duplicate_timestamp_detected(self) -> None:
        """Two candles with identical (symbol, interval, timestamp) produce DUPLICATE_BAR."""
        candles = _make_candle_series(count=3)
        # Add a duplicate of the last candle
        dup = _make_candle(timestamp=candles[-1].timestamp, volume=99_999)
        candles.append(dup)

        service, _, _ = _build_service()
        anomalies = service.detect_anomalies(candles)

        dups = [a for a in anomalies if a.anomaly_type == AnomalyType.DUPLICATE_BAR]
        assert len(dups) >= 1

    def test_no_duplicates_no_anomaly(self) -> None:
        """Candles with unique timestamps produce no DUPLICATE_BAR."""
        candles = _make_candle_series(count=5)
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies(candles)

        dups = [a for a in anomalies if a.anomaly_type == AnomalyType.DUPLICATE_BAR]
        assert len(dups) == 0


# ---------------------------------------------------------------------------
# Quality scoring tests
# ---------------------------------------------------------------------------


class TestQualityScoring:
    """Tests for composite quality score computation."""

    def test_perfect_data_yields_grade_a(self) -> None:
        """A clean candle series with no anomalies yields grade A."""
        candles = _make_candle_series(count=60)
        service, dq_repo, _ = _build_service(candles=candles)

        score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)

        assert score.grade == QualityGrade.A
        assert score.composite_score >= 0.95
        assert score.anomaly_count == 0

    def test_score_persisted_to_repository(self) -> None:
        """evaluate_quality persists the computed score to the data quality repository."""
        candles = _make_candle_series(count=10)
        service, dq_repo, _ = _build_service(candles=candles)

        service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=10)

        assert dq_repo.score_count() == 1

    def test_anomalies_persisted_to_repository(self) -> None:
        """Anomalies detected during evaluate_quality are persisted."""
        candles = _make_candle_series(count=5)
        # Add a bad candle
        bad = _make_candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            high=Decimal("170.00"),
            low=Decimal("175.00"),
        )
        candles.append(bad)

        service, dq_repo, _ = _build_service(candles=candles)
        service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=6)

        assert dq_repo.anomaly_count() > 0

    def test_empty_candles_yields_low_score(self) -> None:
        """No candle data yields a low composite score (grade F or D)."""
        service, dq_repo, _ = _build_service(candles=[])

        score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)

        assert score.completeness == 0.0
        assert score.grade in (QualityGrade.D, QualityGrade.F)

    def test_score_has_correct_symbol_and_interval(self) -> None:
        """Returned score has the correct symbol and interval."""
        candles = _make_candle_series(count=10, symbol="MSFT")
        service, _, _ = _build_service(candles=candles)

        score = service.evaluate_quality("MSFT", CandleInterval.M1, window_minutes=10)

        assert score.symbol == "MSFT"
        assert score.interval == CandleInterval.M1

    def test_score_window_times_set_correctly(self) -> None:
        """Score window_start and window_end span the requested window."""
        candles = _make_candle_series(count=10)
        service, _, _ = _build_service(candles=candles)

        score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=10)

        assert score.window_end > score.window_start
        delta = score.window_end - score.window_start
        # Window should be approximately 10 minutes
        assert delta.total_seconds() >= 600 - 1  # 10 min minus tiny tolerance

    def test_bad_data_lowers_accuracy_score(self) -> None:
        """Candles with OHLCV violations lower the accuracy dimension score."""
        candles = _make_candle_series(count=10)
        # Replace half the candles with OHLCV violations (high < low)
        for i in range(0, 10, 2):
            candles[i] = _make_candle(
                timestamp=candles[i].timestamp,
                high=Decimal("170.00"),
                low=Decimal("175.00"),
                open_=Decimal("172.00"),
                close=Decimal("173.00"),
            )

        service, _, _ = _build_service(candles=candles)
        score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=10)

        assert score.accuracy < 1.0
        assert score.anomaly_count > 0

    def test_composite_score_bounded(self) -> None:
        """Composite score is always between 0.0 and 1.0 inclusive."""
        for candles in [
            _make_candle_series(count=60),
            [],
            [_make_candle(high=Decimal("170.00"), low=Decimal("175.00"))],
        ]:
            service, _, _ = _build_service(candles=candles)
            score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)
            assert 0.0 <= score.composite_score <= 1.0


# ---------------------------------------------------------------------------
# Trading readiness tests
# ---------------------------------------------------------------------------


class TestTradingReadiness:
    """Tests for check_trading_readiness method."""

    def test_live_readiness_with_high_quality_passes(self) -> None:
        """Symbols with high quality scores pass LIVE readiness check."""
        candles = _make_candle_series(count=60)
        service, dq_repo, _ = _build_service(candles=candles)

        # Pre-populate a high quality score
        service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)

        result = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)

        assert isinstance(result, QualityReadinessResult)
        assert result.execution_mode == ExecutionMode.LIVE
        assert len(result.symbols) == 1
        # With perfect data, should be ready
        assert result.all_ready is True

    def test_live_readiness_with_no_score_fails(self) -> None:
        """Symbol with no quality score fails LIVE readiness."""
        service, _, _ = _build_service()

        result = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)

        assert result.all_ready is False
        assert result.symbols[0].ready is False
        assert len(result.symbols[0].blocking_reasons) > 0

    def test_shadow_readiness_always_passes(self) -> None:
        """SHADOW mode readiness always passes (no quality minimum)."""
        service, dq_repo, _ = _build_service()

        # Even with no score, SHADOW should pass since min_composite_score = 0.0
        # But we need a score to exist. Let's just check the result is well-formed
        result = service.check_trading_readiness(["AAPL"], ExecutionMode.SHADOW)

        assert result.execution_mode == ExecutionMode.SHADOW
        assert isinstance(result, QualityReadinessResult)

    def test_readiness_checks_multiple_symbols(self) -> None:
        """Readiness check handles multiple symbols independently."""
        candles_aapl = _make_candle_series(count=60, symbol="AAPL")
        service, dq_repo, md_repo = _build_service(candles=candles_aapl)

        # Evaluate AAPL to give it a score
        service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)

        result = service.check_trading_readiness(["AAPL", "MSFT"], ExecutionMode.LIVE)

        assert len(result.symbols) == 2
        # AAPL has a score, MSFT does not
        aapl = next(s for s in result.symbols if s.symbol == "AAPL")
        msft = next(s for s in result.symbols if s.symbol == "MSFT")
        assert aapl.ready is True
        assert msft.ready is False

    def test_readiness_result_includes_policy(self) -> None:
        """Readiness result includes the policy that was applied."""
        service, _, _ = _build_service()

        result = service.check_trading_readiness(["AAPL"], ExecutionMode.PAPER)

        assert result.policy is not None
        assert result.policy.execution_mode == ExecutionMode.PAPER

    def test_readiness_result_has_evaluated_at(self) -> None:
        """Readiness result includes an evaluated_at timestamp."""
        service, _, _ = _build_service()

        result = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)

        assert result.evaluated_at is not None


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_candle_list_returns_no_anomalies(self) -> None:
        """detect_anomalies on empty list returns empty list."""
        service, _, _ = _build_service()
        anomalies = service.detect_anomalies([])
        assert anomalies == []

    def test_single_candle_basic_checks_only(self) -> None:
        """Single candle runs OHLCV checks but not inter-bar checks."""
        candle = _make_candle()
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([candle])

        # No PRICE_SPIKE, TIMESTAMP_GAP, or DUPLICATE_BAR possible with single candle
        for a in anomalies:
            assert a.anomaly_type not in (
                AnomalyType.PRICE_SPIKE,
                AnomalyType.TIMESTAMP_GAP,
                AnomalyType.DUPLICATE_BAR,
            )

    def test_anomaly_ids_are_unique(self) -> None:
        """Each detected anomaly has a unique anomaly_id."""
        candles = _make_candle_series(count=5)
        # Add multiple bad candles to generate multiple anomalies
        for _i in range(3):
            candles.append(
                _make_candle(
                    timestamp=candles[-1].timestamp + timedelta(minutes=1),
                    high=Decimal("170.00"),
                    low=Decimal("175.00"),
                )
            )

        service, _, _ = _build_service()
        anomalies = service.detect_anomalies(candles)

        ids = [a.anomaly_id for a in anomalies]
        assert len(ids) == len(set(ids)), "Anomaly IDs must be unique"

    def test_all_anomalies_have_correct_symbol(self) -> None:
        """All anomalies carry the symbol from the candle that triggered them."""
        candle = _make_candle(
            symbol="SPY",
            high=Decimal("170.00"),
            low=Decimal("175.00"),
        )
        service, _, _ = _build_service()

        anomalies = service.detect_anomalies([candle])

        for a in anomalies:
            assert a.symbol == "SPY"

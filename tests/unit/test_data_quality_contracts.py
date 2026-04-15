"""
Unit tests for data quality contracts (Phase 8 — M0).

Tests cover:
- Enum values and membership for all data quality enums.
- DataAnomaly model validation, symbol normalization, and freezing.
- QualityScore model validation, window ordering, and grade enforcement.
- QualityPolicy constraints and default policies.
- assign_grade() function boundary cases.
- SymbolReadiness and QualityReadinessResult construction.
- Default quality weights sum to 1.0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from libs.contracts.data_quality import (
    DEFAULT_QUALITY_POLICIES,
    DEFAULT_QUALITY_WEIGHTS,
    AnomalySeverity,
    AnomalyType,
    DataAnomaly,
    DataQualityDimension,
    QualityGrade,
    QualityPolicy,
    QualityReadinessResult,
    QualityScore,
    SymbolReadiness,
    assign_grade,
)
from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import CandleInterval

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
_HOUR_AGO = _NOW - timedelta(hours=1)


def _make_anomaly(**overrides: object) -> DataAnomaly:
    """Create a DataAnomaly with sensible defaults, overridable per field."""
    defaults = {
        "anomaly_id": "anom-001",
        "symbol": "AAPL",
        "interval": CandleInterval.M1,
        "anomaly_type": AnomalyType.OHLCV_VIOLATION,
        "severity": AnomalySeverity.CRITICAL,
        "detected_at": _NOW,
        "bar_timestamp": _NOW,
        "details": {"high": "170.00", "low": "175.00"},
    }
    defaults.update(overrides)
    return DataAnomaly(**defaults)


def _make_score(**overrides: object) -> QualityScore:
    """Create a QualityScore with sensible defaults, overridable per field."""
    defaults = {
        "symbol": "AAPL",
        "interval": CandleInterval.D1,
        "window_start": _HOUR_AGO,
        "window_end": _NOW,
        "completeness": 0.98,
        "timeliness": 0.95,
        "consistency": 1.0,
        "accuracy": 0.99,
        "composite_score": 0.98,
        "anomaly_count": 1,
        "grade": QualityGrade.A,
    }
    defaults.update(overrides)
    return QualityScore(**defaults)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestDataQualityDimension:
    """Tests for DataQualityDimension enum values."""

    def test_all_dimensions_present(self) -> None:
        """All five quality dimensions are defined."""
        assert len(DataQualityDimension) == 5

    def test_dimension_values(self) -> None:
        """Dimension values are lowercase snake_case strings."""
        expected = {"completeness", "timeliness", "consistency", "accuracy", "volume_profile"}
        actual = {d.value for d in DataQualityDimension}
        assert actual == expected


class TestAnomalyType:
    """Tests for AnomalyType enum values."""

    def test_all_types_present(self) -> None:
        """All seven anomaly types are defined."""
        assert len(AnomalyType) == 7

    def test_type_values(self) -> None:
        """Anomaly type values match expected strings."""
        expected = {
            "missing_bar",
            "stale_data",
            "ohlcv_violation",
            "price_spike",
            "volume_anomaly",
            "timestamp_gap",
            "duplicate_bar",
        }
        actual = {t.value for t in AnomalyType}
        assert actual == expected


class TestAnomalySeverity:
    """Tests for AnomalySeverity enum values."""

    def test_all_severities_present(self) -> None:
        """All three severity levels are defined."""
        assert len(AnomalySeverity) == 3

    def test_severity_ordering(self) -> None:
        """Severity values are info, warning, critical."""
        assert AnomalySeverity.INFO.value == "info"
        assert AnomalySeverity.WARNING.value == "warning"
        assert AnomalySeverity.CRITICAL.value == "critical"


class TestQualityGrade:
    """Tests for QualityGrade enum values."""

    def test_all_grades_present(self) -> None:
        """All five letter grades are defined."""
        assert len(QualityGrade) == 5

    def test_grade_values(self) -> None:
        """Grades are uppercase letters A through F (no E)."""
        expected = {"A", "B", "C", "D", "F"}
        actual = {g.value for g in QualityGrade}
        assert actual == expected


# ---------------------------------------------------------------------------
# assign_grade tests
# ---------------------------------------------------------------------------


class TestAssignGrade:
    """Tests for the assign_grade() function."""

    def test_grade_a_at_boundary(self) -> None:
        """Score exactly at 0.95 yields grade A."""
        assert assign_grade(0.95) == QualityGrade.A

    def test_grade_a_above_boundary(self) -> None:
        """Score above 0.95 yields grade A."""
        assert assign_grade(1.0) == QualityGrade.A

    def test_grade_b_at_boundary(self) -> None:
        """Score exactly at 0.85 yields grade B."""
        assert assign_grade(0.85) == QualityGrade.B

    def test_grade_b_just_below_a(self) -> None:
        """Score just below 0.95 yields grade B."""
        assert assign_grade(0.949) == QualityGrade.B

    def test_grade_c_at_boundary(self) -> None:
        """Score exactly at 0.70 yields grade C."""
        assert assign_grade(0.70) == QualityGrade.C

    def test_grade_d_at_boundary(self) -> None:
        """Score exactly at 0.50 yields grade D."""
        assert assign_grade(0.50) == QualityGrade.D

    def test_grade_f_below_d(self) -> None:
        """Score below 0.50 yields grade F."""
        assert assign_grade(0.49) == QualityGrade.F

    def test_grade_f_at_zero(self) -> None:
        """Score of 0.0 yields grade F."""
        assert assign_grade(0.0) == QualityGrade.F

    def test_invalid_score_above_one_raises(self) -> None:
        """Score above 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="composite_score must be in"):
            assign_grade(1.01)

    def test_invalid_score_below_zero_raises(self) -> None:
        """Score below 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="composite_score must be in"):
            assign_grade(-0.01)


# ---------------------------------------------------------------------------
# DataAnomaly model tests
# ---------------------------------------------------------------------------


class TestDataAnomaly:
    """Tests for the DataAnomaly Pydantic model."""

    def test_valid_anomaly_creation(self) -> None:
        """A valid anomaly can be created with all required fields."""
        anomaly = _make_anomaly()
        assert anomaly.anomaly_id == "anom-001"
        assert anomaly.symbol == "AAPL"
        assert anomaly.anomaly_type == AnomalyType.OHLCV_VIOLATION
        assert anomaly.severity == AnomalySeverity.CRITICAL
        assert anomaly.resolved is False

    def test_symbol_normalized_to_uppercase(self) -> None:
        """Symbol is always uppercased."""
        anomaly = _make_anomaly(symbol="aapl")
        assert anomaly.symbol == "AAPL"

    def test_frozen_model(self) -> None:
        """DataAnomaly is frozen (immutable)."""
        anomaly = _make_anomaly()
        with pytest.raises(ValidationError):
            anomaly.resolved = True  # type: ignore[misc]

    def test_optional_bar_timestamp(self) -> None:
        """bar_timestamp can be None for feed-level anomalies."""
        anomaly = _make_anomaly(bar_timestamp=None)
        assert anomaly.bar_timestamp is None

    def test_default_details_empty(self) -> None:
        """details defaults to empty dict if not provided."""
        anomaly = DataAnomaly(
            anomaly_id="anom-002",
            symbol="MSFT",
            interval=CandleInterval.D1,
            anomaly_type=AnomalyType.STALE_DATA,
            severity=AnomalySeverity.WARNING,
            detected_at=_NOW,
        )
        assert anomaly.details == {}

    def test_empty_symbol_rejected(self) -> None:
        """Empty symbol raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_anomaly(symbol="")

    def test_missing_anomaly_id_rejected(self) -> None:
        """Missing anomaly_id raises ValidationError."""
        with pytest.raises(ValidationError):
            DataAnomaly(
                symbol="AAPL",
                interval=CandleInterval.M1,
                anomaly_type=AnomalyType.OHLCV_VIOLATION,
                severity=AnomalySeverity.CRITICAL,
                detected_at=_NOW,
            )

    def test_resolved_at_with_resolved_flag(self) -> None:
        """Resolved anomaly can include resolved_at timestamp."""
        anomaly = _make_anomaly(resolved=True, resolved_at=_NOW)
        assert anomaly.resolved is True
        assert anomaly.resolved_at == _NOW


# ---------------------------------------------------------------------------
# QualityScore model tests
# ---------------------------------------------------------------------------


class TestQualityScore:
    """Tests for the QualityScore Pydantic model."""

    def test_valid_score_creation(self) -> None:
        """A valid quality score can be created with all required fields."""
        score = _make_score()
        assert score.symbol == "AAPL"
        assert score.completeness == 0.98
        assert score.grade == QualityGrade.A
        assert score.anomaly_count == 1

    def test_symbol_normalized_to_uppercase(self) -> None:
        """Symbol is always uppercased."""
        score = _make_score(symbol="spy")
        assert score.symbol == "SPY"

    def test_frozen_model(self) -> None:
        """QualityScore is frozen (immutable)."""
        score = _make_score()
        with pytest.raises(ValidationError):
            score.completeness = 0.50  # type: ignore[misc]

    def test_dimension_score_below_zero_rejected(self) -> None:
        """Dimension scores below 0.0 are rejected."""
        with pytest.raises(ValidationError):
            _make_score(completeness=-0.1)

    def test_dimension_score_above_one_rejected(self) -> None:
        """Dimension scores above 1.0 are rejected."""
        with pytest.raises(ValidationError):
            _make_score(accuracy=1.1)

    def test_composite_score_below_zero_rejected(self) -> None:
        """Composite score below 0.0 is rejected."""
        with pytest.raises(ValidationError):
            _make_score(composite_score=-0.01)

    def test_composite_score_above_one_rejected(self) -> None:
        """Composite score above 1.0 is rejected."""
        with pytest.raises(ValidationError):
            _make_score(composite_score=1.01)

    def test_negative_anomaly_count_rejected(self) -> None:
        """Negative anomaly_count is rejected."""
        with pytest.raises(ValidationError):
            _make_score(anomaly_count=-1)

    def test_window_end_before_start_rejected(self) -> None:
        """window_end before window_start raises ValidationError."""
        with pytest.raises(ValidationError, match="window_end must be after"):
            _make_score(
                window_start=_NOW,
                window_end=_HOUR_AGO,
            )

    def test_window_end_equal_start_rejected(self) -> None:
        """window_end equal to window_start raises ValidationError."""
        with pytest.raises(ValidationError, match="window_end must be after"):
            _make_score(
                window_start=_NOW,
                window_end=_NOW,
            )

    def test_scored_at_optional(self) -> None:
        """scored_at defaults to None."""
        score = _make_score()
        assert score.scored_at is None

    def test_scored_at_provided(self) -> None:
        """scored_at can be explicitly set."""
        score = _make_score(scored_at=_NOW)
        assert score.scored_at == _NOW

    def test_zero_scores_valid(self) -> None:
        """All dimension scores at 0.0 are valid (e.g., no data)."""
        score = _make_score(
            completeness=0.0,
            timeliness=0.0,
            consistency=0.0,
            accuracy=0.0,
            composite_score=0.0,
            grade=QualityGrade.F,
        )
        assert score.composite_score == 0.0


# ---------------------------------------------------------------------------
# QualityPolicy tests
# ---------------------------------------------------------------------------


class TestQualityPolicy:
    """Tests for the QualityPolicy Pydantic model."""

    def test_valid_policy_creation(self) -> None:
        """A valid policy can be created."""
        policy = QualityPolicy(
            execution_mode=ExecutionMode.LIVE,
            min_composite_score=0.90,
            min_completeness=0.95,
            max_anomaly_severity=AnomalySeverity.WARNING,
            lookback_window_minutes=60,
        )
        assert policy.execution_mode == ExecutionMode.LIVE
        assert policy.min_composite_score == 0.90

    def test_frozen_model(self) -> None:
        """QualityPolicy is frozen (immutable)."""
        policy = QualityPolicy(
            execution_mode=ExecutionMode.PAPER,
            min_composite_score=0.70,
            min_completeness=0.80,
            max_anomaly_severity=AnomalySeverity.CRITICAL,
            lookback_window_minutes=120,
        )
        with pytest.raises(ValidationError):
            policy.min_composite_score = 0.50  # type: ignore[misc]

    def test_negative_lookback_rejected(self) -> None:
        """lookback_window_minutes must be positive."""
        with pytest.raises(ValidationError):
            QualityPolicy(
                execution_mode=ExecutionMode.LIVE,
                min_composite_score=0.90,
                min_completeness=0.95,
                max_anomaly_severity=AnomalySeverity.WARNING,
                lookback_window_minutes=0,
            )

    def test_score_above_one_rejected(self) -> None:
        """min_composite_score above 1.0 is rejected."""
        with pytest.raises(ValidationError):
            QualityPolicy(
                execution_mode=ExecutionMode.LIVE,
                min_composite_score=1.1,
                min_completeness=0.95,
                max_anomaly_severity=AnomalySeverity.WARNING,
                lookback_window_minutes=60,
            )


# ---------------------------------------------------------------------------
# Default policy tests
# ---------------------------------------------------------------------------


class TestDefaultPolicies:
    """Tests for the default quality policies."""

    def test_all_execution_modes_have_policy(self) -> None:
        """Every ExecutionMode has a default quality policy."""
        for mode in ExecutionMode:
            assert mode in DEFAULT_QUALITY_POLICIES

    def test_live_policy_strictest(self) -> None:
        """LIVE policy has the highest composite score requirement."""
        live = DEFAULT_QUALITY_POLICIES[ExecutionMode.LIVE]
        paper = DEFAULT_QUALITY_POLICIES[ExecutionMode.PAPER]
        shadow = DEFAULT_QUALITY_POLICIES[ExecutionMode.SHADOW]
        assert live.min_composite_score >= paper.min_composite_score
        assert paper.min_composite_score >= shadow.min_composite_score

    def test_live_completeness_strictest(self) -> None:
        """LIVE policy has the highest completeness requirement."""
        live = DEFAULT_QUALITY_POLICIES[ExecutionMode.LIVE]
        paper = DEFAULT_QUALITY_POLICIES[ExecutionMode.PAPER]
        assert live.min_completeness >= paper.min_completeness

    def test_shadow_policy_allows_everything(self) -> None:
        """SHADOW policy has zero minimum requirements."""
        shadow = DEFAULT_QUALITY_POLICIES[ExecutionMode.SHADOW]
        assert shadow.min_composite_score == 0.0
        assert shadow.min_completeness == 0.0


# ---------------------------------------------------------------------------
# Default weights tests
# ---------------------------------------------------------------------------


class TestDefaultWeights:
    """Tests for the default quality dimension weights."""

    def test_weights_sum_to_one(self) -> None:
        """Quality weights must sum to exactly 1.0."""
        total = sum(DEFAULT_QUALITY_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-10

    def test_four_dimensions_weighted(self) -> None:
        """Four dimensions have weights (VOLUME_PROFILE excluded from composite)."""
        assert len(DEFAULT_QUALITY_WEIGHTS) == 4

    def test_all_weights_positive(self) -> None:
        """All weights are positive."""
        for weight in DEFAULT_QUALITY_WEIGHTS.values():
            assert weight > 0.0


# ---------------------------------------------------------------------------
# SymbolReadiness tests
# ---------------------------------------------------------------------------


class TestSymbolReadiness:
    """Tests for the SymbolReadiness model."""

    def test_ready_symbol(self) -> None:
        """A ready symbol has no blocking reasons."""
        sr = SymbolReadiness(
            symbol="AAPL",
            ready=True,
            quality_score=_make_score(),
            blocking_reasons=[],
        )
        assert sr.ready is True
        assert sr.blocking_reasons == []

    def test_not_ready_with_reasons(self) -> None:
        """A not-ready symbol includes blocking reasons."""
        sr = SymbolReadiness(
            symbol="AAPL",
            ready=False,
            blocking_reasons=["Completeness 0.80 < min 0.95"],
        )
        assert sr.ready is False
        assert len(sr.blocking_reasons) == 1

    def test_no_score_available(self) -> None:
        """Quality score can be None when no data is available."""
        sr = SymbolReadiness(
            symbol="AAPL",
            ready=False,
            quality_score=None,
            blocking_reasons=["No quality score available"],
        )
        assert sr.quality_score is None


# ---------------------------------------------------------------------------
# QualityReadinessResult tests
# ---------------------------------------------------------------------------


class TestQualityReadinessResult:
    """Tests for the QualityReadinessResult model."""

    def test_all_ready(self) -> None:
        """Result shows all_ready=True when all symbols pass."""
        policy = DEFAULT_QUALITY_POLICIES[ExecutionMode.LIVE]
        result = QualityReadinessResult(
            execution_mode=ExecutionMode.LIVE,
            all_ready=True,
            symbols=[
                SymbolReadiness(symbol="AAPL", ready=True),
                SymbolReadiness(symbol="MSFT", ready=True),
            ],
            policy=policy,
        )
        assert result.all_ready is True
        assert len(result.symbols) == 2

    def test_partial_ready(self) -> None:
        """Result shows all_ready=False when any symbol fails."""
        policy = DEFAULT_QUALITY_POLICIES[ExecutionMode.LIVE]
        result = QualityReadinessResult(
            execution_mode=ExecutionMode.LIVE,
            all_ready=False,
            symbols=[
                SymbolReadiness(symbol="AAPL", ready=True),
                SymbolReadiness(symbol="MSFT", ready=False, blocking_reasons=["low score"]),
            ],
            policy=policy,
        )
        assert result.all_ready is False

    def test_evaluated_at_optional(self) -> None:
        """evaluated_at defaults to None."""
        policy = DEFAULT_QUALITY_POLICIES[ExecutionMode.SHADOW]
        result = QualityReadinessResult(
            execution_mode=ExecutionMode.SHADOW,
            all_ready=True,
            symbols=[],
            policy=policy,
        )
        assert result.evaluated_at is None

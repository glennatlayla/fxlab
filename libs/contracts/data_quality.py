"""
Data quality contracts for market data integrity monitoring.

Responsibilities:
- Define the quality dimension taxonomy (completeness, timeliness, etc.).
- Define anomaly types, severities, and anomaly records.
- Define quality scores with composite grading.
- Define quality policies per execution mode for trading readiness checks.
- Provide frozen Pydantic models for all data quality domain objects.

Does NOT:
- Execute anomaly detection logic (service layer responsibility).
- Persist data (repository layer responsibility).
- Know about specific market data providers (Alpaca, Schwab, etc.).

Dependencies:
- pydantic: BaseModel, Field
- libs.contracts.market_data: CandleInterval
- libs.contracts.execution: ExecutionMode
- datetime, enum: standard library

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.data_quality import (
        AnomalySeverity,
        AnomalyType,
        DataAnomaly,
        QualityGrade,
        QualityScore,
    )

    anomaly = DataAnomaly(
        anomaly_id="anom-001",
        symbol="AAPL",
        interval=CandleInterval.M1,
        anomaly_type=AnomalyType.OHLCV_VIOLATION,
        severity=AnomalySeverity.CRITICAL,
        detected_at=datetime.now(tz=timezone.utc),
        bar_timestamp=datetime(2026, 4, 13, 14, 30, tzinfo=timezone.utc),
        details={"high": "170.00", "low": "175.00"},
    )

    score = QualityScore(
        symbol="AAPL",
        interval=CandleInterval.D1,
        window_start=datetime(2026, 4, 12, tzinfo=timezone.utc),
        window_end=datetime(2026, 4, 13, tzinfo=timezone.utc),
        completeness=0.98,
        timeliness=0.95,
        consistency=1.0,
        accuracy=0.99,
        composite_score=0.98,
        anomaly_count=1,
        grade=QualityGrade.A,
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import CandleInterval

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DataQualityDimension(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Quality dimensions measured for market data feeds.

    Each dimension represents a distinct aspect of data quality that
    contributes to the composite quality score:
    - COMPLETENESS: percentage of expected bars actually present.
    - TIMELINESS: latency from expected arrival time.
    - CONSISTENCY: cross-field and cross-source agreement.
    - ACCURACY: OHLCV relationship validity (high >= low, etc.).
    - VOLUME_PROFILE: volume vs. historical norms.

    Example:
        dim = DataQualityDimension.COMPLETENESS
    """

    COMPLETENESS = "completeness"
    TIMELINESS = "timeliness"
    CONSISTENCY = "consistency"
    ACCURACY = "accuracy"
    VOLUME_PROFILE = "volume_profile"


class AnomalyType(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Classification of market data anomalies.

    Each type represents a specific data integrity issue that can be
    detected by the data quality engine:
    - MISSING_BAR: expected bar not present in the dataset.
    - STALE_DATA: real-time data feed has stopped updating.
    - OHLCV_VIOLATION: OHLCV relationships violated (e.g., high < low).
    - PRICE_SPIKE: bar-to-bar price change exceeds threshold.
    - VOLUME_ANOMALY: volume deviates significantly from rolling mean.
    - TIMESTAMP_GAP: gap between consecutive bars exceeds expected interval.
    - DUPLICATE_BAR: multiple bars with identical (symbol, interval, timestamp).

    Example:
        anomaly = AnomalyType.PRICE_SPIKE
    """

    MISSING_BAR = "missing_bar"
    STALE_DATA = "stale_data"
    OHLCV_VIOLATION = "ohlcv_violation"
    PRICE_SPIKE = "price_spike"
    VOLUME_ANOMALY = "volume_anomaly"
    TIMESTAMP_GAP = "timestamp_gap"
    DUPLICATE_BAR = "duplicate_bar"


class AnomalySeverity(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Severity classification for data anomalies.

    Used to determine alerting thresholds and trading readiness decisions:
    - INFO: informational only, no action required.
    - WARNING: potential issue, operator should investigate.
    - CRITICAL: confirmed data integrity problem, may block trading.

    Example:
        severity = AnomalySeverity.CRITICAL
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class QualityGrade(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Letter grade for composite quality score.

    Grade boundaries:
    - A: composite_score >= 0.95
    - B: composite_score >= 0.85
    - C: composite_score >= 0.70
    - D: composite_score >= 0.50
    - F: composite_score < 0.50

    Example:
        grade = QualityGrade.A
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


# ---------------------------------------------------------------------------
# Grade assignment helper
# ---------------------------------------------------------------------------

#: Grade boundary thresholds in descending order.
#: Each tuple is (minimum_composite_score, grade).
GRADE_BOUNDARIES: list[tuple[float, QualityGrade]] = [
    (0.95, QualityGrade.A),
    (0.85, QualityGrade.B),
    (0.70, QualityGrade.C),
    (0.50, QualityGrade.D),
]


def assign_grade(composite_score: float) -> QualityGrade:
    """
    Assign a letter grade based on composite quality score.

    Args:
        composite_score: A float in range [0.0, 1.0].

    Returns:
        QualityGrade corresponding to the score.

    Raises:
        ValueError: If composite_score is outside [0.0, 1.0].

    Example:
        assign_grade(0.97)  # QualityGrade.A
        assign_grade(0.88)  # QualityGrade.B
        assign_grade(0.42)  # QualityGrade.F
    """
    if not 0.0 <= composite_score <= 1.0:
        raise ValueError(f"composite_score must be in [0.0, 1.0], got {composite_score}")
    for threshold, grade in GRADE_BOUNDARIES:
        if composite_score >= threshold:
            return grade
    return QualityGrade.F


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class DataAnomaly(BaseModel):
    """
    A detected anomaly in market data.

    Represents a specific data integrity issue found during quality evaluation.
    Anomalies are persisted for audit trail and trend analysis.

    Attributes:
        anomaly_id: Unique identifier for this anomaly (ULID or UUID).
        symbol: Ticker symbol where anomaly was detected.
        interval: Candle interval that was evaluated.
        anomaly_type: Classification of the anomaly.
        severity: How severe the anomaly is.
        detected_at: When the anomaly was detected (UTC).
        bar_timestamp: Timestamp of the affected bar (None for feed-level issues).
        details: Arbitrary key-value details about the anomaly.
        resolved: Whether the anomaly has been resolved.
        resolved_at: When the anomaly was resolved (None if unresolved).

    Example:
        anomaly = DataAnomaly(
            anomaly_id="anom-001",
            symbol="AAPL",
            interval=CandleInterval.M1,
            anomaly_type=AnomalyType.OHLCV_VIOLATION,
            severity=AnomalySeverity.CRITICAL,
            detected_at=datetime(2026, 4, 13, 14, 0, tzinfo=timezone.utc),
            bar_timestamp=datetime(2026, 4, 13, 14, 30, tzinfo=timezone.utc),
            details={"high": "170.00", "low": "175.00", "issue": "high < low"},
        )
    """

    model_config = {"frozen": True}

    anomaly_id: str = Field(
        ..., min_length=1, max_length=255, description="Unique anomaly identifier"
    )
    symbol: str = Field(..., min_length=1, max_length=20, description="Ticker symbol")
    interval: CandleInterval = Field(..., description="Candle interval evaluated")
    anomaly_type: AnomalyType = Field(..., description="Type of anomaly detected")
    severity: AnomalySeverity = Field(..., description="Anomaly severity level")
    detected_at: datetime = Field(..., description="When anomaly was detected (UTC)")
    bar_timestamp: datetime | None = Field(
        default=None, description="Timestamp of the affected bar"
    )
    details: dict[str, Any] = Field(default_factory=dict, description="Anomaly-specific details")
    resolved: bool = Field(default=False, description="Whether anomaly has been resolved")
    resolved_at: datetime | None = Field(default=None, description="When anomaly was resolved")

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper()


class QualityScore(BaseModel):
    """
    Composite quality score for a symbol's market data over a time window.

    Combines multiple quality dimensions into a single composite score
    and letter grade. Persisted for trend analysis and trading readiness
    decisions.

    Attributes:
        symbol: Ticker symbol evaluated.
        interval: Candle interval evaluated.
        window_start: Start of the evaluation window (UTC).
        window_end: End of the evaluation window (UTC).
        completeness: Fraction of expected bars present [0.0, 1.0].
        timeliness: Timeliness score [0.0, 1.0].
        consistency: Consistency score [0.0, 1.0].
        accuracy: Accuracy score [0.0, 1.0].
        composite_score: Weighted composite of all dimensions [0.0, 1.0].
        anomaly_count: Number of anomalies detected in the window.
        grade: Letter grade (A/B/C/D/F) derived from composite_score.
        scored_at: When the score was computed (UTC).

    Example:
        score = QualityScore(
            symbol="AAPL",
            interval=CandleInterval.D1,
            window_start=datetime(2026, 4, 12, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 13, tzinfo=timezone.utc),
            completeness=0.98,
            timeliness=0.95,
            consistency=1.0,
            accuracy=0.99,
            composite_score=0.98,
            anomaly_count=1,
            grade=QualityGrade.A,
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=20)
    interval: CandleInterval
    window_start: datetime
    window_end: datetime
    completeness: float = Field(..., ge=0.0, le=1.0)
    timeliness: float = Field(..., ge=0.0, le=1.0)
    consistency: float = Field(..., ge=0.0, le=1.0)
    accuracy: float = Field(..., ge=0.0, le=1.0)
    composite_score: float = Field(..., ge=0.0, le=1.0)
    anomaly_count: int = Field(..., ge=0)
    grade: QualityGrade
    scored_at: datetime | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase."""
        return v.upper()

    @field_validator("window_end")
    @classmethod
    def _window_end_after_start(cls, v: datetime, info: Any) -> datetime:
        """Ensure window_end is after window_start."""
        if "window_start" in info.data and v <= info.data["window_start"]:
            raise ValueError("window_end must be after window_start")
        return v


class QualityPolicy(BaseModel):
    """
    Minimum data quality thresholds per execution mode.

    Used by the trading readiness check to determine whether market data
    quality is sufficient for the requested execution mode.

    Attributes:
        execution_mode: Which execution mode this policy applies to.
        min_composite_score: Minimum acceptable composite score.
        min_completeness: Minimum acceptable completeness score.
        max_anomaly_severity: Maximum tolerated anomaly severity.
            If any anomaly at this severity or above exists, readiness fails.
        lookback_window_minutes: How far back to look for quality data.

    Example:
        live_policy = QualityPolicy(
            execution_mode=ExecutionMode.LIVE,
            min_composite_score=0.90,
            min_completeness=0.95,
            max_anomaly_severity=AnomalySeverity.WARNING,
            lookback_window_minutes=60,
        )
    """

    model_config = {"frozen": True}

    execution_mode: ExecutionMode
    min_composite_score: float = Field(..., ge=0.0, le=1.0)
    min_completeness: float = Field(..., ge=0.0, le=1.0)
    max_anomaly_severity: AnomalySeverity
    lookback_window_minutes: int = Field(..., gt=0)


class SymbolReadiness(BaseModel):
    """
    Per-symbol readiness result for a trading readiness check.

    Attributes:
        symbol: Ticker symbol checked.
        ready: Whether the symbol passes quality policy.
        quality_score: Latest quality score (None if no score available).
        blocking_reasons: List of reasons why the symbol is not ready.

    Example:
        readiness = SymbolReadiness(
            symbol="AAPL",
            ready=True,
            quality_score=score,
            blocking_reasons=[],
        )
    """

    symbol: str
    ready: bool
    quality_score: QualityScore | None = None
    blocking_reasons: list[str] = Field(default_factory=list)


class QualityReadinessResult(BaseModel):
    """
    Aggregate trading readiness result across multiple symbols.

    Attributes:
        execution_mode: The execution mode being checked.
        all_ready: True only if every symbol passes the quality policy.
        symbols: Per-symbol readiness details.
        policy: The quality policy that was applied.
        evaluated_at: When the readiness check was performed.

    Example:
        result = QualityReadinessResult(
            execution_mode=ExecutionMode.LIVE,
            all_ready=False,
            symbols=[symbol_readiness_aapl, symbol_readiness_msft],
            policy=live_policy,
        )
    """

    execution_mode: ExecutionMode
    all_ready: bool
    symbols: list[SymbolReadiness]
    policy: QualityPolicy
    evaluated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Default quality policies
# ---------------------------------------------------------------------------

#: Default quality policies by execution mode.
#: LIVE requires high quality; PAPER is more lenient; SHADOW has minimal requirements.
DEFAULT_QUALITY_POLICIES: dict[ExecutionMode, QualityPolicy] = {
    ExecutionMode.LIVE: QualityPolicy(
        execution_mode=ExecutionMode.LIVE,
        min_composite_score=0.90,
        min_completeness=0.95,
        max_anomaly_severity=AnomalySeverity.WARNING,
        lookback_window_minutes=60,
    ),
    ExecutionMode.PAPER: QualityPolicy(
        execution_mode=ExecutionMode.PAPER,
        min_composite_score=0.70,
        min_completeness=0.80,
        max_anomaly_severity=AnomalySeverity.CRITICAL,
        lookback_window_minutes=120,
    ),
    ExecutionMode.SHADOW: QualityPolicy(
        execution_mode=ExecutionMode.SHADOW,
        min_composite_score=0.0,
        min_completeness=0.0,
        max_anomaly_severity=AnomalySeverity.CRITICAL,
        lookback_window_minutes=240,
    ),
}


# ---------------------------------------------------------------------------
# Composite score weighting
# ---------------------------------------------------------------------------

#: Default weights for computing composite quality score.
#: Must sum to 1.0.
DEFAULT_QUALITY_WEIGHTS: dict[DataQualityDimension, float] = {
    DataQualityDimension.COMPLETENESS: 0.35,
    DataQualityDimension.TIMELINESS: 0.20,
    DataQualityDimension.CONSISTENCY: 0.20,
    DataQualityDimension.ACCURACY: 0.25,
}

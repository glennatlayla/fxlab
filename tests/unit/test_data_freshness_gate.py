"""
Unit tests for DataFreshnessGate.

Test coverage:
- Happy path: fresh candles across intervals (1m, 5m, 15m, 1h, 1d).
- Stale candles: rejected when exceeding interval-based threshold.
- Absolute cap: hard rejection at absolute_max_staleness_seconds.
- Policy actions: "reject" vs "warn" produce correct outcomes.
- Boundary conditions: candles exactly at staleness threshold.
- Edge cases: candles with very old timestamps, zero age.
- is_fresh() convenience method.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from libs.contracts.data_freshness import DataFreshnessPolicy
from libs.contracts.market_data import Candle, CandleInterval
from services.api.services.data_freshness_gate import DataFreshnessGate

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gate() -> DataFreshnessGate:
    """Provide a DataFreshnessGate instance for testing."""
    return DataFreshnessGate()


@pytest.fixture
def now() -> datetime:
    """Provide a fixed current time for deterministic testing."""
    return datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc)


def make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.M1,
    timestamp: datetime | None = None,
) -> Candle:
    """
    Helper to construct a test candle with sensible defaults.

    Args:
        symbol: Ticker symbol.
        interval: Candle interval.
        timestamp: Candle timestamp (UTC). Defaults to a fixed past time.

    Returns:
        A Candle instance.
    """
    if timestamp is None:
        timestamp = datetime(2026, 4, 13, 15, 29, 30, tzinfo=timezone.utc)

    return Candle(
        symbol=symbol,
        interval=interval,
        open=Decimal("150.00"),
        high=Decimal("151.00"),
        low=Decimal("149.00"),
        close=Decimal("150.50"),
        volume=1_000_000,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Tests: Happy path (fresh candles)
# ---------------------------------------------------------------------------


def test_fresh_1m_candle_within_multiplier(gate: DataFreshnessGate, now: datetime) -> None:
    """
    1-min candle that is 30 seconds old should be fresh (30 < 180).

    With default policy (multiplier=3.0, absolute_max=600):
    - 1m candle threshold = 60 * 3.0 = 180 seconds
    - Age = 30 seconds
    - 30 <= 180 -> FRESH
    """
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=30),
    )
    policy = DataFreshnessPolicy()

    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.age_seconds == 30.0
    assert result.max_allowed_seconds == 180.0
    assert result.symbol == "AAPL"


def test_fresh_5m_candle_within_multiplier(gate: DataFreshnessGate, now: datetime) -> None:
    """
    5-min candle that is 5 minutes old should be fresh (300 < 900).

    With custom policy (absolute_max high enough to not interfere):
    - 5m threshold = 300 * 3.0 = 900 seconds
    - Age = 300 seconds
    - 300 <= 900 -> FRESH
    """
    candle = make_candle(
        interval=CandleInterval.M5,
        timestamp=now - timedelta(seconds=300),
    )
    policy = DataFreshnessPolicy(absolute_max_staleness_seconds=3600)  # 1 hour
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.age_seconds == 300.0
    assert result.max_allowed_seconds == 900.0


def test_fresh_daily_candle_within_multiplier(gate: DataFreshnessGate, now: datetime) -> None:
    """
    Daily candle that is 1 day old should be fresh (86400 < 259200).

    With custom policy (absolute_max high enough to not interfere):
    - 1d threshold = 86400 * 3.0 = 259200 seconds (3 days)
    - Age = 86400 seconds (1 day)
    - 86400 <= 259200 -> FRESH
    """
    candle = make_candle(
        interval=CandleInterval.D1,
        timestamp=now - timedelta(days=1),
    )
    policy = DataFreshnessPolicy(absolute_max_staleness_seconds=604800)  # 1 week
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.age_seconds == 86400.0
    assert result.max_allowed_seconds == 259200.0


def test_fresh_zero_age_candle(gate: DataFreshnessGate, now: datetime) -> None:
    """Candle with zero age (timestamp == now) should be fresh."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now,
    )
    policy = DataFreshnessPolicy()
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.age_seconds == 0.0


# ---------------------------------------------------------------------------
# Tests: Stale candles (interval-based threshold exceeded)
# ---------------------------------------------------------------------------


def test_stale_1m_candle_exceeds_multiplier(gate: DataFreshnessGate, now: datetime) -> None:
    """
    1-min candle that is 5 minutes old should be stale (300 > 180).

    With default policy:
    - 1m threshold = 60 * 3.0 = 180 seconds
    - Age = 300 seconds
    - 300 > 180 -> STALE
    """
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=300),
    )
    policy = DataFreshnessPolicy(action_on_stale="reject")
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.age_seconds == 300.0
    assert result.max_allowed_seconds == 180.0


def test_stale_1h_candle_exceeds_multiplier(gate: DataFreshnessGate, now: datetime) -> None:
    """
    1-hour candle that is 4 hours old should be stale (4h > 3h).

    With custom policy (absolute_max high enough to not interfere):
    - 1h threshold = 3600 * 3.0 = 10800 seconds (3 hours)
    - Age = 14400 seconds (4 hours)
    - 14400 > 10800 -> STALE
    """
    candle = make_candle(
        interval=CandleInterval.H1,
        timestamp=now - timedelta(hours=4),
    )
    policy = DataFreshnessPolicy(
        action_on_stale="reject",
        absolute_max_staleness_seconds=86400,  # 1 day
    )
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.age_seconds == 14400.0
    assert result.max_allowed_seconds == 10800.0


# ---------------------------------------------------------------------------
# Tests: Absolute cap enforcement
# ---------------------------------------------------------------------------


def test_absolute_cap_rejects_very_old_1m_candle(gate: DataFreshnessGate, now: datetime) -> None:
    """
    1-min candle that is 20 minutes old should be rejected by absolute cap.

    With default policy (absolute_max=600):
    - 1m interval threshold = 60 * 3.0 = 180 seconds
    - Absolute max = 600 seconds (10 min)
    - Effective threshold = min(180, 600) = 180 seconds
    - Age = 1200 seconds (20 minutes)
    - 1200 > 180 -> REJECTED (exceeds effective threshold)
    """
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=1200),  # 20 minutes
    )
    policy = DataFreshnessPolicy(
        max_staleness_multiplier=3.0,
        absolute_max_staleness_seconds=600,
        action_on_stale="reject",
    )
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.age_seconds == 1200.0
    # Threshold = min(interval_threshold=180, absolute_max=600) = 180
    assert result.max_allowed_seconds == 180.0


def test_absolute_cap_rejects_daily_candle_2_days_old(
    gate: DataFreshnessGate, now: datetime
) -> None:
    """
    Daily candle that is 2 days old should be rejected by absolute cap.

    With default policy (absolute_max=600):
    - 1d threshold = min(259200, 600) = 600 seconds
    - Age = 172800 seconds (2 days)
    - 172800 > 600 -> REJECTED
    """
    candle = make_candle(
        interval=CandleInterval.D1,
        timestamp=now - timedelta(days=2),
    )
    policy = DataFreshnessPolicy(absolute_max_staleness_seconds=600)
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.age_seconds == 172800.0
    assert result.max_allowed_seconds == 600.0


# ---------------------------------------------------------------------------
# Tests: Policy action modes ("reject" vs "warn")
# ---------------------------------------------------------------------------


def test_stale_candle_with_reject_policy(gate: DataFreshnessGate, now: datetime) -> None:
    """Stale candle with action_on_stale='reject' -> action='rejected'."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=300),
    )
    policy = DataFreshnessPolicy(action_on_stale="reject")
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"


def test_stale_candle_with_warn_policy(gate: DataFreshnessGate, now: datetime) -> None:
    """Stale candle with action_on_stale='warn' -> action='warned'."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=300),
    )
    policy = DataFreshnessPolicy(action_on_stale="warn")
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "warned"


def test_fresh_candle_action_always_accepted(gate: DataFreshnessGate, now: datetime) -> None:
    """Fresh candle has action='accepted' regardless of action_on_stale policy."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=30),
    )

    # Test with "reject" policy
    policy_reject = DataFreshnessPolicy(action_on_stale="reject")
    with patch.object(gate, "_get_current_time", return_value=now):
        result_reject = gate.check_freshness(candle, policy_reject)
        assert result_reject.action == "accepted"

        # Test with "warn" policy
        policy_warn = DataFreshnessPolicy(action_on_stale="warn")
        result_warn = gate.check_freshness(candle, policy_warn)
        assert result_warn.action == "accepted"


# ---------------------------------------------------------------------------
# Tests: Boundary conditions
# ---------------------------------------------------------------------------


def test_candle_exactly_at_staleness_threshold(gate: DataFreshnessGate, now: datetime) -> None:
    """Candle with age == threshold should be considered fresh."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=180),  # Exactly 3*60
    )
    policy = DataFreshnessPolicy(max_staleness_multiplier=3.0)
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.age_seconds == 180.0
    assert result.max_allowed_seconds == 180.0


def test_candle_one_second_over_threshold_is_stale(gate: DataFreshnessGate, now: datetime) -> None:
    """Candle with age == threshold + 1 should be stale."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=181),  # 1 second over 3*60
    )
    policy = DataFreshnessPolicy(max_staleness_multiplier=3.0, action_on_stale="reject")
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"


# ---------------------------------------------------------------------------
# Tests: Custom multiplier and absolute cap values
# ---------------------------------------------------------------------------


def test_custom_multiplier_higher_tolerance(gate: DataFreshnessGate, now: datetime) -> None:
    """Custom multiplier=5.0 allows 5x the interval age."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=250),  # Between 3*60 and 5*60
    )
    policy = DataFreshnessPolicy(max_staleness_multiplier=5.0)
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.max_allowed_seconds == 300.0  # 60 * 5.0


def test_custom_multiplier_lower_tolerance(gate: DataFreshnessGate, now: datetime) -> None:
    """Custom multiplier=1.5 allows only 1.5x the interval age."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=100),  # Between 1.5*60 and 3*60
    )
    policy = DataFreshnessPolicy(max_staleness_multiplier=1.5, action_on_stale="reject")
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.max_allowed_seconds == 90.0  # 60 * 1.5


def test_custom_absolute_cap_lower_than_interval_based(
    gate: DataFreshnessGate, now: datetime
) -> None:
    """When absolute_max < interval_threshold, absolute_max wins."""
    candle = make_candle(
        interval=CandleInterval.M15,
        timestamp=now - timedelta(seconds=301),  # Just over 5 minutes
    )
    policy = DataFreshnessPolicy(
        max_staleness_multiplier=3.0,  # 15m * 3 = 45m = 2700s
        absolute_max_staleness_seconds=300,  # But hard cap is 5m
        action_on_stale="reject",
    )
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is False
    assert result.action == "rejected"
    assert result.max_allowed_seconds == 300.0  # Uses absolute cap, not interval


# ---------------------------------------------------------------------------
# Tests: is_fresh() convenience method
# ---------------------------------------------------------------------------


def test_is_fresh_returns_true_for_fresh_candle(gate: DataFreshnessGate, now: datetime) -> None:
    """is_fresh() returns True if candle is within staleness threshold."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=30),
    )
    policy = DataFreshnessPolicy()
    gate._get_current_time = lambda: now  # type: ignore[assignment]

    result = gate.is_fresh(candle, policy)

    assert result is True


def test_is_fresh_returns_false_for_stale_candle(gate: DataFreshnessGate, now: datetime) -> None:
    """is_fresh() returns False if candle exceeds staleness threshold."""
    candle = make_candle(
        interval=CandleInterval.M1,
        timestamp=now - timedelta(seconds=300),
    )
    policy = DataFreshnessPolicy()
    gate._get_current_time = lambda: now  # type: ignore[assignment]

    result = gate.is_fresh(candle, policy)

    assert result is False


# ---------------------------------------------------------------------------
# Tests: Result object correctness
# ---------------------------------------------------------------------------


def test_result_contains_all_required_fields(gate: DataFreshnessGate, now: datetime) -> None:
    """FreshnessCheckResult contains all documented fields."""
    candle = make_candle(
        symbol="SPY",
        interval=CandleInterval.H1,
        timestamp=now - timedelta(hours=2),
    )
    policy = DataFreshnessPolicy(absolute_max_staleness_seconds=86400)  # 1 day
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.symbol == "SPY"
    assert result.candle_timestamp == candle.timestamp
    assert result.checked_at == now
    assert result.age_seconds == 7200.0
    assert result.max_allowed_seconds == 10800.0  # 3600 * 3
    assert result.is_fresh is True
    assert result.action == "accepted"


def test_result_immutable(gate: DataFreshnessGate, now: datetime) -> None:
    """FreshnessCheckResult is frozen and cannot be modified."""
    candle = make_candle()
    policy = DataFreshnessPolicy()
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    # Frozen Pydantic model raises on attribute assignment
    with pytest.raises(ValidationError):
        result.is_fresh = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: All supported intervals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interval,interval_seconds",
    [
        (CandleInterval.M1, 60),
        (CandleInterval.M5, 300),
        (CandleInterval.M15, 900),
        (CandleInterval.H1, 3600),
        (CandleInterval.D1, 86400),
    ],
)
def test_all_intervals_supported(
    gate: DataFreshnessGate,
    now: datetime,
    interval: CandleInterval,
    interval_seconds: int,
) -> None:
    """Each interval calculates threshold correctly."""
    age = interval_seconds * 2  # 2x the interval (within default 3x)
    candle = make_candle(
        interval=interval,
        timestamp=now - timedelta(seconds=age),
    )
    # Use a high absolute cap so interval-based threshold dominates
    policy = DataFreshnessPolicy(
        max_staleness_multiplier=3.0,
        absolute_max_staleness_seconds=999999,
    )
    with patch.object(gate, "_get_current_time", return_value=now):
        result = gate.check_freshness(candle, policy)

    assert result.is_fresh is True
    assert result.action == "accepted"
    assert result.max_allowed_seconds == interval_seconds * 3.0

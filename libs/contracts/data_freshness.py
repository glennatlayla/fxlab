"""
Market data freshness validation contracts.

Responsibilities:
- Define Pydantic schemas for data staleness policies and freshness check results.
- Provide value objects consumed by the data freshness gate service.
- Enable configuration of what staleness thresholds are acceptable.

Does NOT:
- Contain I/O, database queries, or network calls.
- Perform freshness calculations (service layer responsibility).
- Know about specific data feeds or providers.

Dependencies:
- pydantic: BaseModel, Field, ConfigDict
- datetime, typing: standard library
- libs.contracts.market_data: CandleInterval for type hints

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.data_freshness import DataFreshnessPolicy, FreshnessCheckResult
    from datetime import datetime, timezone

    policy = DataFreshnessPolicy(
        max_staleness_multiplier=3.0,
        absolute_max_staleness_seconds=600,
        action_on_stale="reject",
    )

    result = FreshnessCheckResult(
        symbol="AAPL",
        candle_timestamp=datetime(2026, 4, 13, 15, 30, tzinfo=timezone.utc),
        checked_at=datetime(2026, 4, 13, 15, 33, tzinfo=timezone.utc),
        age_seconds=180.0,
        max_allowed_seconds=180.0,
        is_fresh=True,
        action="accepted",
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DataFreshnessPolicy(BaseModel):
    """
    Controls how stale market data is before signals are suppressed.

    The staleness threshold is the minimum of two values:
    1. Interval-based: candle.interval_seconds * max_staleness_multiplier
    2. Absolute cap: absolute_max_staleness_seconds

    This allows different intervals to tolerate proportionally different ages
    while never accepting data older than the hard cap.

    Attributes:
        max_staleness_multiplier: Multiplier on interval duration. A 1-min candle
            is fresh if age <= 60 * 3.0 = 180 seconds. A daily candle is fresh if
            age <= 86400 * 3.0 = 259200 seconds. Default: 3.0 (3x the interval).
        absolute_max_staleness_seconds: Hard cap on staleness regardless of interval.
            No signal generated for data older than this. Default: 600 (10 minutes).
        action_on_stale: Policy when candle exceeds staleness threshold.
            - "reject": skip signal generation entirely (default, fail-safe).
            - "warn": generate signal but log WARNING (for shadow mode testing).

    Example:
        policy = DataFreshnessPolicy(
            max_staleness_multiplier=5.0,  # Allow 5x the interval age
            absolute_max_staleness_seconds=1200,  # But never older than 20 min
            action_on_stale="reject",  # Skip signals on stale data
        )
    """

    model_config = ConfigDict(frozen=True)

    max_staleness_multiplier: float = Field(
        default=3.0,
        ge=1.0,
        description="Multiplier on interval seconds for staleness threshold",
    )
    absolute_max_staleness_seconds: int = Field(
        default=600,
        ge=60,
        description="Hard cap: reject any data older than this (seconds)",
    )
    action_on_stale: Literal["reject", "warn"] = Field(
        default="reject",
        description="Action when data exceeds staleness threshold",
    )


class FreshnessCheckResult(BaseModel):
    """
    Result of a data freshness check against a policy.

    Attributes:
        symbol: Ticker symbol of the candle checked.
        candle_timestamp: UTC timestamp of the candle (its bar open time).
        checked_at: UTC timestamp when the check was performed (now).
        age_seconds: How old the candle is (checked_at - candle_timestamp), in seconds.
        max_allowed_seconds: The staleness threshold for this symbol/interval (minimum
            of interval-based and absolute caps).
        is_fresh: True if age_seconds <= max_allowed_seconds, False otherwise.
        action: Outcome of the check based on policy:
            - "accepted": candle is fresh, signal generation proceeds.
            - "rejected": candle is stale and policy.action_on_stale == "reject".
            - "warned": candle is stale and policy.action_on_stale == "warn".

    Example:
        result = FreshnessCheckResult(
            symbol="SPY",
            candle_timestamp=datetime(2026, 4, 13, 15, 29, 0, tzinfo=timezone.utc),
            checked_at=datetime(2026, 4, 13, 15, 29, 30, tzinfo=timezone.utc),
            age_seconds=30.0,
            max_allowed_seconds=180.0,
            is_fresh=True,
            action="accepted",
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    candle_timestamp: datetime = Field(..., description="UTC timestamp of candle bar open")
    checked_at: datetime = Field(..., description="UTC timestamp of freshness check")
    age_seconds: float = Field(..., ge=0.0, description="Age of candle in seconds")
    max_allowed_seconds: float = Field(
        ..., ge=0.0, description="Maximum allowed staleness for this candle"
    )
    is_fresh: bool = Field(..., description="True if age_seconds <= max_allowed_seconds")
    action: Literal["accepted", "rejected", "warned"] = Field(
        ..., description="Outcome of the freshness check"
    )

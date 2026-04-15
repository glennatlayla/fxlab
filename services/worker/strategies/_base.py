"""
Shared base utilities for built-in signal strategies.

Responsibilities:
- Provide a helper to build Signal objects with consistent defaults.
- Provide ULID-based signal ID generation.
- Centralise deployment_id and correlation_id handling.

Does NOT:
- Contain trading logic (strategies implement that).
- Persist signals (repository layer responsibility).
- Evaluate risk gates (service layer responsibility).

Dependencies:
- libs.contracts.signal: Signal, SignalDirection, SignalStrength, SignalType
- ulid: ULID generation for signal IDs.
- datetime: UTC timestamping.

Example:
    signal = build_signal(
        strategy_id="strat-sma-cross",
        deployment_id="deploy-001",
        symbol="AAPL",
        direction=SignalDirection.LONG,
        signal_type=SignalType.ENTRY,
        strength=SignalStrength.STRONG,
        confidence=0.85,
        indicators_used={"sma_fast": 175.5},
        bar_timestamp=candles[-1].timestamp,
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import ulid

from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalStrength,
    SignalType,
)


def build_signal(
    *,
    strategy_id: str,
    deployment_id: str,
    symbol: str,
    direction: SignalDirection,
    signal_type: SignalType,
    strength: SignalStrength,
    confidence: float,
    indicators_used: dict[str, float],
    bar_timestamp: datetime,
    correlation_id: str,
    suggested_entry: Decimal | None = None,
    suggested_stop: Decimal | None = None,
    suggested_target: Decimal | None = None,
    metadata: dict[str, Any] | None = None,
) -> Signal:
    """
    Build a Signal with a fresh ULID and UTC generated_at timestamp.

    This is the canonical factory for all built-in strategies. It ensures
    consistent signal_id generation and timestamping.

    Args:
        strategy_id: Originating strategy ID.
        deployment_id: Deployment context ID.
        symbol: Ticker symbol.
        direction: Signal direction (long/short/flat).
        signal_type: Signal type (entry/exit/etc.).
        strength: Signal strength (strong/moderate/weak).
        confidence: Confidence level [0.0, 1.0].
        indicators_used: Indicator name → value at signal time.
        bar_timestamp: Timestamp of the triggering bar.
        correlation_id: Request correlation ID.
        suggested_entry: Suggested entry price (None for market order).
        suggested_stop: Suggested stop-loss price.
        suggested_target: Suggested take-profit price.
        metadata: Optional strategy-specific metadata.

    Returns:
        A fully-constructed Signal instance.

    Example:
        signal = build_signal(
            strategy_id="strat-sma", deployment_id="d1",
            symbol="AAPL", direction=SignalDirection.LONG,
            signal_type=SignalType.ENTRY, strength=SignalStrength.MODERATE,
            confidence=0.7, indicators_used={"sma_20": 150.0},
            bar_timestamp=dt, correlation_id="c1",
        )
    """
    return Signal(
        signal_id=str(ulid.ULID()),
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        symbol=symbol,
        direction=direction,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        indicators_used=indicators_used,
        bar_timestamp=bar_timestamp,
        generated_at=datetime.now(tz=timezone.utc),
        correlation_id=correlation_id,
        suggested_entry=suggested_entry,
        suggested_stop=suggested_stop,
        suggested_target=suggested_target,
        metadata=metadata or {},
    )

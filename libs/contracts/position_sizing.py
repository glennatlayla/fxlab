"""
Dynamic position sizing contracts and value objects.

Responsibilities:
- Define sizing method enumeration (FIXED, ATR_BASED, KELLY, etc.).
- Define sizing request with inputs for each method.
- Define sizing result with recommended quantity and reasoning.
- Provide frozen Pydantic models for type safety and serialization.

Does NOT:
- Compute position sizes (service responsibility).
- Execute trades (execution service responsibility).
- Enforce risk limits (risk gate service responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    request = SizingRequest(
        symbol="AAPL",
        side="buy",
        method=SizingMethod.ATR_BASED,
        risk_per_trade_pct=Decimal("2.0"),
        account_equity=Decimal("100000"),
        atr_value=Decimal("3.50"),
    )
    result = SizingResult(
        recommended_quantity=Decimal("571"),
        recommended_value=Decimal("57100.00"),
        method_used=SizingMethod.ATR_BASED,
        reasoning="ATR-based: risking 2.0% of $100000 = $2000, ATR=$3.50 → 571 shares",
    )
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class SizingMethod(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+; keeping str+Enum for 3.10 compat
    """
    Available position sizing methods.

    Values:
    - FIXED: Static position size (existing max_position_size behavior).
    - ATR_BASED: Volatility-aware sizing using Average True Range.
    - KELLY: Kelly criterion for optimal bet sizing.
    - RISK_PARITY: Inverse-volatility weighting across portfolio.
    - EQUAL_WEIGHT: Equal dollar allocation across positions.
    """

    FIXED = "fixed"
    ATR_BASED = "atr_based"
    KELLY = "kelly"
    RISK_PARITY = "risk_parity"
    EQUAL_WEIGHT = "equal_weight"


class SizingRequest(BaseModel):
    """
    Input parameters for position sizing computation.

    Different methods require different optional fields:
    - FIXED: only symbol, side, account_equity, max_position_size.
    - ATR_BASED: requires atr_value and optionally atr_multiplier.
    - KELLY: requires win_rate and avg_win_loss_ratio.
    - RISK_PARITY: requires current_positions for weighting.
    - EQUAL_WEIGHT: requires total_positions for even allocation.

    Responsibilities:
    - Carry all inputs needed by any sizing method.
    - Validate field constraints.

    Does NOT:
    - Compute sizes (service responsibility).

    Example:
        req = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            atr_value=Decimal("3.50"),
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=10, description="Instrument ticker.")
    side: str = Field(..., pattern=r"^(buy|sell)$", description="Trade side: 'buy' or 'sell'.")
    method: SizingMethod = Field(..., description="Sizing method to use.")
    risk_per_trade_pct: Decimal = Field(
        default=Decimal("2.0"),
        gt=0.0,
        le=100.0,
        description="Percentage of equity to risk per trade (0-100).",
    )
    account_equity: Decimal = Field(
        ...,
        gt=0.0,
        description="Total account equity available.",
    )
    current_price: Decimal = Field(
        default=Decimal("0"),
        ge=0.0,
        description="Current market price of the instrument.",
    )
    max_position_size: Decimal | None = Field(
        default=None,
        description="Hard cap from risk gate (overrides computed size if exceeded).",
    )
    # ATR-based fields
    atr_value: Decimal | None = Field(
        default=None,
        ge=0.0,
        description="Average True Range value (required for ATR_BASED method).",
    )
    atr_multiplier: Decimal = Field(
        default=Decimal("2.0"),
        gt=0.0,
        description="ATR multiplier for stop distance (default 2× ATR).",
    )
    # Kelly criterion fields
    win_rate: Decimal | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Historical win rate (0-1, required for KELLY method).",
    )
    avg_win_loss_ratio: Decimal | None = Field(
        default=None,
        gt=0.0,
        description="Average win/loss ratio (required for KELLY method).",
    )
    # Portfolio-level fields
    total_positions: int = Field(
        default=1,
        ge=1,
        description="Total number of positions for equal weight allocation.",
    )
    current_position_count: int = Field(
        default=0,
        ge=0,
        description="Number of existing positions for risk parity.",
    )


class SizingResult(BaseModel):
    """
    Output of a position sizing computation.

    Contains the recommended quantity and dollar value, the method used,
    and a human-readable explanation of the computation.

    Responsibilities:
    - Convey the sizing recommendation to the caller.
    - Explain the reasoning for audit trail purposes.
    - Indicate if the result was capped by risk limits.

    Does NOT:
    - Execute the trade (caller/execution service responsibility).

    Example:
        result = SizingResult(
            recommended_quantity=Decimal("571"),
            recommended_value=Decimal("57100.00"),
            method_used=SizingMethod.ATR_BASED,
            reasoning="ATR-based: risking 2.0% of $100000...",
        )
    """

    model_config = {"frozen": True}

    recommended_quantity: Decimal = Field(
        ...,
        ge=0.0,
        description="Recommended position size in shares/contracts.",
    )
    recommended_value: Decimal = Field(
        ...,
        ge=0.0,
        description="Recommended position value in dollars.",
    )
    stop_loss_price: Decimal | None = Field(
        default=None,
        description="Suggested stop loss price (for ATR-based sizing).",
    )
    risk_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0.0,
        description="Dollar amount at risk for this position.",
    )
    method_used: SizingMethod = Field(..., description="Sizing method that was applied.")
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of the sizing calculation.",
    )
    was_capped: bool = Field(
        default=False,
        description="Whether the result was reduced by risk gate limits.",
    )

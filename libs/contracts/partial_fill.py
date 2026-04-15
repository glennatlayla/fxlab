"""
Partial fill handling contracts for safety-critical order management.

Responsibilities:
- Define the normalized configuration for partial fill timeout and resolution policies.
- Provide Pydantic schemas for partial fill monitoring and audit recording.
- Specify the contract for timeout-based cancellation and operator alerts.

Does NOT:
- Contain monitoring business logic (service layer responsibility).
- Know about specific broker implementations.
- Perform I/O or network calls.

Dependencies:
- pydantic: BaseModel, Field, ConfigDict
- datetime: timestamp handling for fill lifecycle

Error conditions:
- Pydantic ValidationError raised on invalid field values (negative timeouts, etc.).

Example:
    policy = PartialFillPolicy(
        timeout_seconds=300,
        min_fill_ratio=0.1,
        action_on_timeout="cancel_remaining",
    )
    resolution = PartialFillResolution(
        order_id="01HORDER...",
        broker_order_id="ALPACA-12345",
        original_quantity="1000",
        filled_quantity="750",
        fill_ratio=0.75,
        action_taken="cancelled_remaining",
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PartialFillPolicy(BaseModel):
    """
    Configuration for partial fill monitoring and resolution.

    Attributes:
        timeout_seconds: Seconds to wait before resolving a partial fill.
            Default 300 (5 minutes). Must be positive.
        min_fill_ratio: Minimum acceptable fill ratio (0.0 = any partial fill
            is acceptable; 0.5 = reject if <50% filled). Default 0.0.
        action_on_timeout: What to do when timeout expires:
            - "cancel_remaining": Send broker cancel request for unfilled qty.
            - "alert_only": Log warning but do not cancel (for manual review).

    Example:
        policy = PartialFillPolicy(
            timeout_seconds=300,
            min_fill_ratio=0.0,
            action_on_timeout="cancel_remaining",
        )
    """

    model_config = ConfigDict(frozen=True)

    timeout_seconds: int = Field(
        default=300,
        gt=0,
        description="Timeout in seconds before resolving partial fill (must be positive)",
    )
    min_fill_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum acceptable fill ratio (0.0-1.0)",
    )
    action_on_timeout: Literal["cancel_remaining", "alert_only"] = Field(
        default="cancel_remaining",
        description="Action to take when timeout expires: cancel or alert only",
    )


class PartialFillResolution(BaseModel):
    """
    Audit record for partial fill resolution.

    Captures the outcome of monitoring an individual partial fill order:
    whether it was cancelled, completed by the broker, or alerted.

    Attributes:
        order_id: Internal ULID of the order being monitored.
        broker_order_id: Broker-assigned order identifier.
        original_quantity: Total quantity ordered (string for decimal precision).
        filled_quantity: Quantity filled so far (string for decimal precision).
        fill_ratio: Filled / original quantity as a float (0.0-1.0).
        action_taken: What action was taken:
            - "cancelled_remaining": Broker cancel was sent successfully.
            - "fully_filled": Broker reports order now fully filled.
            - "alert_sent": Warning logged (alert_only policy).
            - "error": Attempted action failed (see error_message).
        cancelled_at: Timestamp when cancellation was processed (if applicable).
        error_message: Human-readable error description if action_taken == "error".

    Example:
        res = PartialFillResolution(
            order_id="01HORDER...",
            broker_order_id="ALPACA-12345",
            original_quantity="1000",
            filled_quantity="750",
            fill_ratio=0.75,
            action_taken="cancelled_remaining",
            cancelled_at=datetime.now(tz=timezone.utc),
        )
    """

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., min_length=1, description="Internal order ULID")
    broker_order_id: str = Field(..., min_length=1, description="Broker-assigned order ID")
    original_quantity: str = Field(
        ..., min_length=1, description="Original order quantity (decimal string)"
    )
    filled_quantity: str = Field(
        ..., min_length=1, description="Quantity filled so far (decimal string)"
    )
    fill_ratio: float = Field(..., ge=0.0, le=1.0, description="Fill ratio as float (0.0-1.0)")
    action_taken: Literal["cancelled_remaining", "fully_filled", "alert_sent", "error"] = Field(
        ..., description="What action was taken to resolve the partial fill"
    )
    cancelled_at: datetime | None = Field(
        default=None, description="Timestamp of cancellation (if applicable)"
    )
    error_message: str | None = Field(
        default=None, description="Error details if action_taken == 'error'"
    )

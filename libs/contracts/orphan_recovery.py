"""
Orphaned order recovery contracts.

Responsibilities:
- Define the data structures for orphaned order recovery reports.
- Capture per-order recovery results and deployment-level summaries.
- Provide Pydantic v2 frozen models for serialization and validation.

Does NOT:
- Implement recovery logic (service layer responsibility).
- Perform I/O or network calls.
- Know about specific broker implementations.

Dependencies:
- pydantic v2: BaseModel, Field, ConfigDict
- datetime: timezone-aware timestamps

Error conditions:
- Pydantic ValidationError on invalid field values.

Example:
    report = OrphanRecoveryReport(
        deployment_id="01HDEPLOY...",
        recovered_count=3,
        cancelled_count=0,
        failed_count=1,
        details=[...],
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Per-order recovery result
# ---------------------------------------------------------------------------


class OrphanOrderRecoveryResult(BaseModel):
    """Result of attempting to recover a single orphaned order.

    Captured in the details list of OrphanRecoveryReport.

    Attributes:
        order_id: ULID of the internal order record.
        client_order_id: Client-assigned idempotency key.
        symbol: Instrument ticker.
        side: Order side ("buy" or "sell").
        quantity: Order quantity as string.
        action: Recovery action taken ("imported", "expired", "synced_fills", "skipped").
        broker_order_id: Broker-assigned ID (if found at broker).
        status: Final order status after recovery attempt.
        filled_quantity: Quantity filled (if synced from broker).
        average_fill_price: Volume-weighted average fill price (if synced).
        error_message: Error text if recovery failed (None if successful).
        timestamp: When this recovery occurred (ISO 8601).
    """

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., description="ULID of the internal order record")
    client_order_id: str = Field(..., description="Client-assigned idempotency key")
    symbol: str = Field(..., description="Instrument ticker")
    side: str = Field(..., description="Order side (buy/sell)")
    quantity: str = Field(..., description="Order quantity as string")
    action: str = Field(
        ..., description="Recovery action: imported, expired, synced_fills, skipped"
    )
    broker_order_id: str | None = Field(None, description="Broker-assigned ID if found at broker")
    status: str = Field(..., description="Final order status after recovery")
    filled_quantity: str | None = Field(None, description="Quantity filled if synced from broker")
    average_fill_price: str | None = Field(None, description="VWAP if synced from broker")
    error_message: str | None = Field(None, description="Error text if recovery failed")
    timestamp: str = Field(..., description="ISO 8601 timestamp of recovery")


# ---------------------------------------------------------------------------
# Deployment-level recovery report
# ---------------------------------------------------------------------------


class OrphanRecoveryReport(BaseModel):
    """Summary report of orphaned order recovery for a deployment.

    Frozen Pydantic v2 model for immutability. Suitable for serialization
    to JSON or storage in audit logs.

    Attributes:
        deployment_id: ULID of the deployment being recovered.
        recovered_count: Number of orders successfully recovered.
        cancelled_count: Number of extra broker orders logged as warnings.
        failed_count: Number of recovery attempts that raised errors.
        details: List of per-order recovery results.
        started_at: ISO 8601 timestamp when recovery began.
        completed_at: ISO 8601 timestamp when recovery completed.
    """

    model_config = ConfigDict(frozen=True)

    deployment_id: str = Field(..., description="ULID of the deployment")
    recovered_count: int = Field(0, description="Number of orders successfully recovered", ge=0)
    cancelled_count: int = Field(
        0,
        description="Number of extra broker orders found (not auto-cancelled)",
        ge=0,
    )
    failed_count: int = Field(0, description="Number of recovery attempts that failed", ge=0)
    details: list[OrphanOrderRecoveryResult] = Field(
        default_factory=list, description="Per-order recovery results"
    )
    started_at: datetime = Field(..., description="Recovery start timestamp")
    completed_at: datetime = Field(..., description="Recovery completion timestamp")

    def duration_ms(self) -> float:
        """Compute recovery duration in milliseconds.

        Returns:
            Duration as a float in milliseconds.
        """
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000.0

    def is_successful(self) -> bool:
        """Check whether recovery completed with no failures.

        Returns:
            True if failed_count == 0, False otherwise.
        """
        return self.failed_count == 0

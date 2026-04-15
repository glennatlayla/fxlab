"""
Reconciliation schemas and value objects.

Responsibilities:
- Define reconciliation trigger, discrepancy types, and report contracts.
- Provide frozen Pydantic models for type safety and serialization.

Does NOT:
- Implement reconciliation logic (service responsibility).
- Persist reports (repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Example:
    report = ReconciliationReport(
        report_id="01HRECON...",
        deployment_id="01HDEPLOY...",
        trigger=ReconciliationTrigger.STARTUP,
        discrepancies=[...],
        resolved_count=2,
        unresolved_count=1,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ReconciliationTrigger(str, Enum):
    """Trigger type for reconciliation runs."""

    STARTUP = "startup"
    RECONNECT = "reconnect"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class DiscrepancyType(str, Enum):
    """Types of discrepancies between internal and broker state."""

    MISSING_ORDER = "missing_order"
    EXTRA_ORDER = "extra_order"
    QUANTITY_MISMATCH = "quantity_mismatch"
    PRICE_MISMATCH = "price_mismatch"
    STATUS_MISMATCH = "status_mismatch"
    MISSING_POSITION = "missing_position"
    EXTRA_POSITION = "extra_position"


class Discrepancy(BaseModel):
    """
    Individual discrepancy record.

    Captures the difference between internal state and broker state
    for a specific order or position.

    Example:
        d = Discrepancy(
            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
            entity_type="order",
            entity_id="ord-001",
            field="status",
            internal_value="submitted",
            broker_value="filled",
            auto_resolved=True,
            resolution="Updated internal status to filled",
        )
    """

    model_config = {"frozen": True}

    discrepancy_type: DiscrepancyType = Field(..., description="Type of discrepancy.")
    entity_type: str = Field(..., description="Entity type: 'order' or 'position'.")
    entity_id: str = Field(..., description="ID of the entity with discrepancy.")
    symbol: str | None = Field(default=None, description="Symbol if applicable.")
    field: str | None = Field(default=None, description="Field name with mismatch.")
    internal_value: str | None = Field(default=None, description="Value from internal state.")
    broker_value: str | None = Field(default=None, description="Value from broker state.")
    auto_resolved: bool = Field(default=False, description="Whether auto-resolved.")
    resolution: str | None = Field(default=None, description="Resolution description if resolved.")


class ReconciliationReport(BaseModel):
    """
    Result of a reconciliation run.

    Contains all discrepancies found, counts of resolved/unresolved,
    and metadata about the run.

    Example:
        report = ReconciliationReport(
            report_id="01HRECON...",
            deployment_id="01HDEPLOY...",
            trigger=ReconciliationTrigger.STARTUP,
            discrepancies=[...],
            resolved_count=2,
            unresolved_count=1,
            status="completed_with_discrepancies",
        )
    """

    model_config = {"frozen": True}

    report_id: str = Field(..., description="ULID of the reconciliation report.")
    deployment_id: str = Field(..., description="ULID of the deployment.")
    trigger: ReconciliationTrigger = Field(..., description="What triggered this run.")
    discrepancies: list[Discrepancy] = Field(
        default_factory=list, description="All discrepancies found."
    )
    resolved_count: int = Field(default=0, description="Number of auto-resolved discrepancies.")
    unresolved_count: int = Field(default=0, description="Number of unresolved discrepancies.")
    status: str = Field(
        default="completed",
        description="Status: completed, completed_with_discrepancies, failed.",
    )
    orders_checked: int = Field(default=0, description="Number of orders compared.")
    positions_checked: int = Field(default=0, description="Number of positions compared.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the report was created.",
    )

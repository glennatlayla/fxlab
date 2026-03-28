"""
Feed health and anomaly contracts.

These models represent feed health status, anomaly events, and parity issues.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FeedHealthStatus(str, Enum):
    """Feed health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    OFFLINE = "offline"


class AnomalyType(str, Enum):
    """Anomaly type enumeration."""

    GAP = "gap"
    SPIKE = "spike"
    STALE = "stale"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"


class Anomaly(BaseModel):
    """
    Feed anomaly event.

    Represents a detected anomaly in feed data.
    """

    id: str = Field(..., description="Anomaly ULID")
    feed_id: str = Field(..., description="Feed ULID")
    anomaly_type: AnomalyType = Field(..., description="Anomaly type")
    detected_at: datetime = Field(..., description="Detection timestamp")
    start_time: datetime = Field(..., description="Anomaly start time")
    end_time: Optional[datetime] = Field(
        default=None, description="Anomaly end time (if resolved)"
    )
    severity: str = Field(..., description="Anomaly severity (critical, high, medium, low)")
    message: str = Field(..., description="Human-readable anomaly description")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Additional anomaly context"
    )


class FeedHealthReport(BaseModel):
    """
    Feed health report.

    Represents the current health status and recent anomalies for a feed.
    """

    feed_id: str = Field(..., description="Feed ULID")
    status: FeedHealthStatus = Field(..., description="Current health status")
    last_update: datetime = Field(..., description="Last data update timestamp")
    recent_anomalies: list[Anomaly] = Field(
        default_factory=list, description="Recent anomaly events"
    )
    quarantine_reason: Optional[str] = Field(
        default=None, description="Reason for quarantine (if status=QUARANTINED)"
    )


class ParityIssue(BaseModel):
    """
    Parity issue detail.

    Represents a detected discrepancy between feeds.
    """

    id: str = Field(..., description="Parity issue ULID")
    feed_a_id: str = Field(..., description="First feed ULID")
    feed_b_id: str = Field(..., description="Second feed ULID")
    symbol: str = Field(..., description="Symbol identifier")
    detected_at: datetime = Field(..., description="Detection timestamp")
    discrepancy_type: str = Field(..., description="Type of discrepancy (price, gap, etc.)")
    message: str = Field(..., description="Human-readable discrepancy description")
    resolved: bool = Field(default=False, description="Whether issue is resolved")

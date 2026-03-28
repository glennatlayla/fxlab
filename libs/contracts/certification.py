"""
Feed certification contracts (Phase 3 — M8: Verification + Gaps + Anomalies + Certification).

Purpose:
    Provide the data shapes for the certification viewer UI, surfacing which feeds
    are certified, blocked (with human-readable reasons), pending, or expired.

Responsibilities:
    - CertificationStatus enum — canonical status values for a feed's certification.
    - CertificationEvent — per-feed certification record consumed by the UI.
    - CertificationReport — aggregate response for GET /data/certification.

Does NOT:
    - Contain certification logic (computation belongs in the service layer).
    - Access the database or any external system.

Example:
    report = CertificationReport(
        certifications=[
            CertificationEvent(
                feed_id="01HQFEED0AAAAAAAAAAAAAAAA0",
                feed_name="AAPL_1m_primary",
                status=CertificationStatus.CERTIFIED,
                blocked_reason="",
                generated_at=datetime.now(timezone.utc),
            )
        ],
        total_count=1,
        blocked_count=0,
        certified_count=1,
        generated_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CertificationStatus(str, Enum):
    """
    Canonical certification status for a data feed.

    Attributes:
        CERTIFIED: Feed has passed all certification checks and is approved for use.
        BLOCKED:   Feed has failed certification; reason is in blocked_reason.
        PENDING:   Certification check has been initiated but not yet completed.
        EXPIRED:   Feed was previously certified but its certification has lapsed.
    """

    CERTIFIED = "CERTIFIED"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"


class CertificationEvent(BaseModel):
    """
    Certification record for a single feed.

    Purpose:
        Provide the certification viewer with per-feed status, reasons for any
        blockage, and timestamp metadata for the certification lifecycle.

    Responsibilities:
        - Carry feed identity (feed_id, feed_name).
        - Report the current certification status.
        - Include a human-readable blocked_reason when status is BLOCKED.
        - Track certification and expiry timestamps.

    Does NOT:
        - Execute certification checks.
        - Persist to the database directly.

    Note on blocked_reason:
        Uses `str = ""` rather than `Optional[str]` to avoid the pydantic-core
        cross-arch stub failure (LL-007).  An empty string means "not blocked".

    Example:
        event = CertificationEvent(
            feed_id="01HQFEED0AAAAAAAAAAAAAAAA0",
            feed_name="AAPL_1m_primary",
            status=CertificationStatus.BLOCKED,
            blocked_reason="Gap detected: 2026-03-25 12:00 UTC – 14:00 UTC (2 h)",
            generated_at=datetime.now(timezone.utc),
        )
    """

    feed_id: str = Field(..., description="Feed ULID")
    feed_name: str = Field(..., description="Human-readable feed name")
    status: CertificationStatus = Field(..., description="Current certification status")
    blocked_reason: str = Field(
        default="",
        description=(
            "Human-readable explanation when status is BLOCKED or EXPIRED. "
            "Empty string when not applicable.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )
    certified_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when certification was granted; None if never certified",
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when certification expires; None if no expiry set",
    )
    generated_at: datetime = Field(..., description="Record generation timestamp")

    class Config:
        from_attributes = True


class CertificationReport(BaseModel):
    """
    Aggregate certification report for all feeds.

    Purpose:
        Returned by GET /data/certification to provide the operator dashboard with
        a single-request view of the certification posture across all feeds.

    Responsibilities:
        - Wrap a list of CertificationEvent objects.
        - Carry aggregate counts (total, blocked, certified) for quick dashboard rendering.

    Does NOT:
        - Include parity or anomaly details (use ParityEventList for those).

    Example:
        report = CertificationReport(
            certifications=[...],
            total_count=10,
            blocked_count=2,
            certified_count=7,
            generated_at=datetime.now(timezone.utc),
        )
    """

    certifications: list[CertificationEvent] = Field(
        default_factory=list,
        description="Per-feed certification records",
    )
    total_count: int = Field(..., ge=0, description="Total number of feeds evaluated")
    blocked_count: int = Field(..., ge=0, description="Number of feeds in BLOCKED status")
    certified_count: int = Field(..., ge=0, description="Number of feeds in CERTIFIED status")
    generated_at: datetime = Field(..., description="Report generation timestamp")

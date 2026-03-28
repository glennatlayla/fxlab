"""
Feed parity event contracts (Phase 3 — M8/M10: Parity Dashboard + Parity Service).

Purpose:
    Provide the data shapes for the parity dashboard UI, surfacing discrepancies
    between official and shadow data feeds for the same instrument/timestamp pair.

Responsibilities:
    - ParityEventSeverity enum — INFO / WARNING / CRITICAL classification.
    - ParityEvent — single cross-feed discrepancy record.
    - ParityEventList — aggregate response for GET /parity/events.
    - ParityInstrumentSummary — per-instrument severity aggregate (M10).
    - ParitySummaryResponse — GET /parity/summary response shape (M10).

Does NOT:
    - Compute parity logic (belongs in the service/domain layer).
    - Access the database or any external system directly.

Example:
    event = ParityEvent(
        id="01HQPARITY0AAAAAAAAAAAAA0",
        feed_id_official="01HQFEED0AAAAAAAAAAAAAAAA0",
        feed_id_shadow="01HQFEED0BBBBBBBBBBBBBBB1",
        instrument="AAPL",
        timestamp=datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc),
        delta=0.05,
        delta_pct=0.003,
        severity=ParityEventSeverity.WARNING,
        detected_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ParityEventSeverity(str, Enum):
    """
    Severity classification for a cross-feed parity discrepancy.

    Attributes:
        INFO:     Discrepancy is within normal tolerance; logged for completeness.
        WARNING:  Discrepancy exceeds soft threshold; review recommended.
        CRITICAL: Discrepancy exceeds hard threshold; feed certification may be blocked.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ParityEvent(BaseModel):
    """
    Single cross-feed parity discrepancy record.

    Purpose:
        Provide the parity dashboard with the data needed to surface discrepancies
        between an official data feed and its shadow counterpart for the same
        instrument and point in time.

    Responsibilities:
        - Identify which feed pair diverged (feed_id_official vs feed_id_shadow).
        - Report the instrument, timestamp, absolute delta, and relative delta.
        - Carry a severity classification for dashboard filtering.
        - Record when the discrepancy was detected.

    Does NOT:
        - Classify severity (done upstream by the service layer).
        - Persist to the database directly.

    Example:
        e = ParityEvent(
            id="01HQPARITY0AAAAAAAAAAAAA0",
            feed_id_official="01HQFEED0AAAAAAAAAAAAAAAA0",
            feed_id_shadow="01HQFEED0BBBBBBBBBBBBBBB1",
            instrument="AAPL",
            timestamp=datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc),
            delta=0.05,
            delta_pct=0.003,
            severity=ParityEventSeverity.WARNING,
            detected_at=datetime.now(timezone.utc),
        )
    """

    id: str = Field(..., description="ULID uniquely identifying this parity event")
    feed_id_official: str = Field(..., description="ULID of the official/primary feed")
    feed_id_shadow: str = Field(..., description="ULID of the shadow/comparison feed")
    instrument: str = Field(..., description="Instrument identifier (ticker symbol)")
    timestamp: datetime = Field(..., description="Point in time where the discrepancy occurred")
    delta: float = Field(..., description="Absolute difference between official and shadow values")
    delta_pct: float = Field(
        ..., description="Relative discrepancy: abs(delta) / official_value"
    )
    severity: ParityEventSeverity = Field(
        ..., description="Severity classification for dashboard filtering"
    )
    detected_at: datetime = Field(..., description="Timestamp when the discrepancy was detected")

    class Config:
        from_attributes = True


class ParityEventList(BaseModel):
    """
    Aggregate list of parity discrepancy events.

    Purpose:
        Returned by GET /parity/events to provide the operator parity dashboard
        with all detected cross-feed discrepancies in a single request.

    Responsibilities:
        - Wrap a list of ParityEvent objects.
        - Carry aggregate counts for quick dashboard rendering.
        - Carry a generation timestamp for staleness detection.

    Does NOT:
        - Include certification details (use CertificationReport for those).

    Example:
        plist = ParityEventList(
            events=[...],
            total_count=5,
            generated_at=datetime.now(timezone.utc),
        )
    """

    events: list[ParityEvent] = Field(
        default_factory=list,
        description="Detected cross-feed parity discrepancy events",
    )
    total_count: int = Field(..., ge=0, description="Total number of parity events")
    generated_at: datetime = Field(..., description="List generation timestamp")


class ParityInstrumentSummary(BaseModel):
    """
    Per-instrument aggregate of parity event severity counts.

    Purpose:
        Power the parity dashboard index view, which shows operators which
        instruments have outstanding parity issues and how severe they are,
        without loading all individual events.

    Responsibilities:
        - Report event_count, critical_count, warning_count, info_count per instrument.
        - Report worst_severity as a plain string ("CRITICAL", "WARNING", "INFO", or "").
          Empty string when the instrument has no events — uses str (not Optional[str])
          to avoid pydantic-core cross-arch stub failure (LL-007).

    Does NOT:
        - Include individual event details (use GET /parity/events for that).
        - Compute severity from raw feed data (upstream service/domain responsibility).

    Example:
        s = ParityInstrumentSummary(
            instrument="AAPL",
            event_count=5,
            critical_count=1,
            warning_count=3,
            info_count=1,
            worst_severity="CRITICAL",
        )
    """

    instrument: str = Field(..., description="Instrument/ticker symbol")
    event_count: int = Field(..., ge=0, description="Total parity events for this instrument")
    critical_count: int = Field(..., ge=0, description="Number of CRITICAL severity events")
    warning_count: int = Field(..., ge=0, description="Number of WARNING severity events")
    info_count: int = Field(..., ge=0, description="Number of INFO severity events")
    worst_severity: str = Field(
        default="",
        description=(
            "Worst severity seen for this instrument as a plain string: "
            "'CRITICAL', 'WARNING', 'INFO', or '' when no events.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )


class ParitySummaryResponse(BaseModel):
    """
    Aggregate parity summary grouped by instrument.

    Purpose:
        Returned by GET /parity/summary.  Provides the parity dashboard index
        page with a compact overview of which instruments have parity issues,
        enabling quick navigation to the filtered event list.

    Responsibilities:
        - Wrap a list of ParityInstrumentSummary objects (one per instrument).
        - Carry total_event_count for the dashboard header badge.
        - Carry generated_at for staleness detection.

    Does NOT:
        - Include individual event records (use GET /parity/events for those).
        - Contain feed-level detail.

    Example:
        resp = ParitySummaryResponse(
            summaries=[
                ParityInstrumentSummary(
                    instrument="AAPL", event_count=2,
                    critical_count=1, warning_count=1, info_count=0,
                    worst_severity="CRITICAL",
                ),
            ],
            total_event_count=2,
            generated_at=datetime.now(timezone.utc),
        )
    """

    summaries: list[ParityInstrumentSummary] = Field(
        default_factory=list,
        description="Per-instrument parity summary entries",
    )
    total_event_count: int = Field(
        ..., ge=0, description="Total parity events across all instruments"
    )
    generated_at: datetime = Field(..., description="Response generation timestamp")

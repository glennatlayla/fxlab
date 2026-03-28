"""
Feed contracts for Phase 3 Feed Registry API.

Responsibilities:
- Define Pydantic response schemas consumed by GET /feeds and GET /feeds/{feed_id}.
- Provide Phase 1/2 contracts (FeedResponse, FeedHealthSnapshotResponse,
  ParityEventResponse) unchanged so downstream consumers are unaffected.
- Add Phase 3 contracts: FeedConfigVersion, FeedConnectivityResult,
  FeedDetailResponse, FeedListResponse, FeedHealthListResponse.

Does NOT:
- Perform I/O or validation beyond Pydantic field declarations.
- Know about the ORM models in libs/contracts/models.py.

Dependencies:
- pydantic: BaseModel, Field.
- libs.contracts.feed_health: FeedHealthReport (for FeedHealthListResponse).

Error conditions:
- None — all fields are validated at construction time by Pydantic.

Example:
    feed = FeedResponse(id="01HQAAA...", name="binance-btcusd", provider="Binance", ...)
    detail = FeedDetailResponse(
        feed=feed, version_history=[...], connectivity_tests=[...]
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Phase 1 / 2 contracts — preserved unchanged for backward compatibility
# ---------------------------------------------------------------------------


class FeedResponse(BaseModel):
    """
    Response schema for a registered data feed.

    Phase 1 contract.  Phase 3 consumes but does not mutate.

    Attributes:
        id: Feed ULID.
        name: Human-readable feed name.
        provider: Data provider identifier (e.g. "Binance", "Alpaca").
        config: Provider-specific configuration dict.
        is_active: Whether this feed is currently active.
        is_quarantined: Whether this feed has been quarantined.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = Field(..., description="Feed ULID")
    name: str
    provider: str
    config: dict[str, Any]
    is_active: bool
    is_quarantined: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeedHealthSnapshotResponse(BaseModel):
    """
    Response schema for a feed health snapshot.

    Phase 1/2 contract.  Phase 3 consumes for charting.

    Attributes:
        id: Snapshot ULID.
        feed_id: Parent feed ULID.
        timestamp: Snapshot capture time.
        latency_ms: Feed ingestion latency in milliseconds.
        gap_count: Number of data gaps detected.
        anomaly_count: Number of anomalies detected.
        health_score: Composite health score 0–100.
        metadata: Additional snapshot context.
        created_at: Record creation timestamp.
    """

    id: str = Field(..., description="Snapshot ULID")
    feed_id: str
    timestamp: datetime
    latency_ms: Optional[int] = None
    gap_count: int
    anomaly_count: int
    health_score: float = Field(..., ge=0.0, le=100.0)
    metadata: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class ParityEventResponse(BaseModel):
    """
    Response schema for a parity discrepancy event between two feeds.

    Phase 2 contract.  Phase 3 consumes for alerting.

    Attributes:
        id: Parity event ULID.
        feed_a_id: First feed ULID.
        feed_b_id: Second feed ULID.
        symbol: Affected symbol.
        timestamp: Detection timestamp.
        discrepancy_type: Type of discrepancy (e.g. "price", "gap").
        magnitude: Magnitude of the discrepancy (if measurable).
        metadata: Additional event context.
        created_at: Record creation timestamp.
    """

    id: str = Field(..., description="Parity event ULID")
    feed_a_id: str
    feed_b_id: str
    symbol: str
    timestamp: datetime
    discrepancy_type: str
    magnitude: Optional[float] = None
    metadata: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Phase 3 contracts — Feed Registry detail and list responses
# ---------------------------------------------------------------------------


class ConnectivityStatus(str, Enum):
    """Result status of a feed connectivity test."""

    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"


class FeedConfigVersion(BaseModel):
    """
    A single versioned snapshot of a feed's configuration.

    The feed registry keeps an append-only version history so operators
    can audit every configuration change over time.

    Attributes:
        version: Monotonically increasing version number (1-based).
        config: Configuration dict at this version.
        created_at: When this version was created.
        created_by: ULID of the user who created this version.
        change_summary: Optional human-readable description of the change.

    Example:
        v = FeedConfigVersion(
            version=2,
            config={"symbol": "BTC/USD", "interval": "1m"},
            created_at=datetime.now(timezone.utc),
            created_by="01HQUUUUUUUUUUUUUUUUUUUUUU",
            change_summary="Reduced interval from 5m to 1m",
        )
    """

    version: int = Field(..., description="Version number (1-based)", ge=1)
    config: dict[str, Any] = Field(..., description="Configuration snapshot at this version")
    created_at: datetime = Field(..., description="Version creation timestamp")
    created_by: str = Field(..., description="ULID of user who created this version")
    change_summary: Optional[str] = Field(
        default=None, description="Optional description of what changed"
    )


class FeedConnectivityResult(BaseModel):
    """
    Result of a connectivity test performed against a feed endpoint.

    Connectivity tests are run periodically to verify that the feed
    source is reachable and responding within acceptable latency bounds.

    Attributes:
        id: Test result ULID.
        feed_id: ULID of the feed being tested.
        tested_at: When the test was performed.
        status: Outcome of the test (ok, failed, timeout).
        latency_ms: Round-trip latency in milliseconds (None on failure).
        error_message: Human-readable error description (None on success).

    Example:
        result = FeedConnectivityResult(
            id="01HQBBBBBBBBBBBBBBBBBBBBBB",
            feed_id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            tested_at=datetime.now(timezone.utc),
            status=ConnectivityStatus.OK,
            latency_ms=42,
        )
    """

    id: str = Field(..., description="Test result ULID")
    feed_id: str = Field(..., description="Feed ULID")
    tested_at: datetime = Field(..., description="Test execution timestamp")
    status: ConnectivityStatus = Field(..., description="Test outcome")
    latency_ms: Optional[int] = Field(default=None, description="Latency in ms (None on failure)")
    error_message: Optional[str] = Field(default=None, description="Error detail (None on success)")


class FeedDetailResponse(BaseModel):
    """
    Full detail response for a single registered feed.

    Aggregates the core feed metadata, its complete version history,
    and recent connectivity test results.  Used by GET /feeds/{feed_id}.

    Attributes:
        feed: Core feed metadata.
        version_history: All configuration versions, newest first.
        connectivity_tests: Recent connectivity test results, newest first.

    Example:
        detail = FeedDetailResponse(
            feed=FeedResponse(...),
            version_history=[FeedConfigVersion(version=1, ...)],
            connectivity_tests=[FeedConnectivityResult(status=ConnectivityStatus.OK, ...)],
        )
    """

    feed: FeedResponse
    version_history: list[FeedConfigVersion] = Field(
        default_factory=list,
        description="Configuration version history, newest first",
    )
    connectivity_tests: list[FeedConnectivityResult] = Field(
        default_factory=list,
        description="Recent connectivity test results, newest first",
    )


class FeedListResponse(BaseModel):
    """
    Paginated list response for GET /feeds.

    Attributes:
        feeds: Page of feed metadata records.
        total_count: Total number of feeds (across all pages).
        limit: Page size used for this response.
        offset: Offset used for this response.

    Example:
        resp = FeedListResponse(feeds=[...], total_count=5, limit=20, offset=0)
    """

    feeds: list[FeedResponse]
    total_count: int = Field(..., description="Total feeds across all pages", ge=0)
    limit: int = Field(..., description="Page size used for this response", ge=1)
    offset: int = Field(..., description="Offset used for this response", ge=0)


class FeedHealthListResponse(BaseModel):
    """
    Feed health summary response for GET /feed-health.

    Returns current health status and recent anomalies for every
    registered feed.  The UI must not compute derived health state
    locally — this response is the authoritative source of truth.

    Attributes:
        feeds: Health report for each registered feed.
        generated_at: Server timestamp when this report was assembled.

    Example:
        resp = FeedHealthListResponse(
            feeds=[FeedHealthReport(feed_id="01HQ...", status=FeedHealthStatus.HEALTHY, ...)],
            generated_at=datetime.now(timezone.utc),
        )
    """

    feeds: list[Any] = Field(
        default_factory=list,
        description="FeedHealthReport list — typed as Any to avoid pydantic-core issues",
    )
    generated_at: datetime = Field(..., description="Report generation timestamp")

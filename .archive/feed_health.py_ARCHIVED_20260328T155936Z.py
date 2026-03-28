"""
Feed Health API endpoint.

Responsibilities:
- Expose GET /feed-health returning current health status for all registered feeds.
- Delegate all data access to FeedHealthRepositoryInterface (injected).
- Never compute health state locally — the backend is the source of truth.

Does NOT:
- Contain health scoring or anomaly detection logic.
- Access the database directly.
- Know which repository implementation is in use (mock vs SQL).

Dependencies:
- libs.contracts.interfaces.feed_health_repository.FeedHealthRepositoryInterface
- libs.contracts.feed: FeedHealthListResponse
- libs.contracts.feed_health: FeedHealthReport, FeedHealthStatus, Anomaly

Error conditions:
- No 404 path — returns an empty feeds list if no health records exist.

Example (curl):
    curl http://localhost:8000/feed-health
    → {"feeds": [...], "generated_at": "2026-03-27T..."}
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from libs.contracts.interfaces.feed_health_repository import FeedHealthRepositoryInterface

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/feed-health", tags=["feed-health"])


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_feed_health_repository() -> FeedHealthRepositoryInterface:
    """
    Provide the active FeedHealthRepositoryInterface implementation.

    In tests: overridden via app.dependency_overrides[get_feed_health_repository].
    In production: returns the DB-backed repository wired by the DI container.

    Returns:
        FeedHealthRepositoryInterface implementation.
    """
    # TODO: ISS-014 — Wire SqlFeedHealthRepository via lifespan DI container.
    #       This stub exists so startup does not fail before DI is wired.
    from libs.contracts.mocks.mock_feed_health_repository import MockFeedHealthRepository

    return MockFeedHealthRepository()


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_health_report(report: Any) -> dict[str, Any]:
    """
    Serialize a FeedHealthReport to a plain dict.

    Converts status enum to its string value and datetimes to ISO strings.
    Handles nested Anomaly objects in recent_anomalies.

    Args:
        report: FeedHealthReport instance.

    Returns:
        Dict with all report fields serialized to JSON-safe types.
    """
    raw = report.model_dump()
    if "status" in raw and hasattr(raw["status"], "value"):  # pragma: no cover
        raw["status"] = raw["status"].value  # pragma: no cover
    if "last_update" in raw and hasattr(raw["last_update"], "isoformat"):
        raw["last_update"] = raw["last_update"].isoformat()
    # Normalize nested anomaly dicts (model_dump may return enum/datetime objects)
    for anomaly_dict in raw.get("recent_anomalies", []):
        for dt_field in ("detected_at", "start_time", "end_time"):
            val = anomaly_dict.get(dt_field)
            if val is not None and hasattr(val, "isoformat"):
                anomaly_dict[dt_field] = val.isoformat()
        at = anomaly_dict.get("anomaly_type")
        if at is not None and hasattr(at, "value"):  # pragma: no cover
            anomaly_dict["anomaly_type"] = at.value  # pragma: no cover
    return raw


def _serialize_health_list(result: Any) -> dict[str, Any]:
    """
    Serialize a FeedHealthListResponse to a JSON-safe dict.

    Args:
        result: FeedHealthListResponse instance.

    Returns:
        Dict with feeds list and generated_at timestamp string.
    """
    generated_at = result.generated_at
    if hasattr(generated_at, "isoformat"):
        generated_at = generated_at.isoformat()
    return {
        "feeds": [_serialize_health_report(r) for r in result.feeds],
        "generated_at": generated_at,
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("")
def get_feed_health(
    correlation_id: Optional[str] = Query(default=None, alias="x-correlation-id"),
    repo: FeedHealthRepositoryInterface = Depends(get_feed_health_repository),
) -> JSONResponse:
    """
    Return the current health status for all registered feeds.

    Provides the UI feed health dashboard with anomaly flags and
    certification status sourced entirely from the backend.  The UI
    must not compute or derive health state from this response locally.

    Args:
        correlation_id: Optional tracing correlation ID.
        repo: Injected FeedHealthRepositoryInterface.

    Returns:
        JSONResponse with feeds health list and generated_at timestamp.

    Example:
        GET /feed-health
        → {
            "feeds": [
                {"feed_id": "01HQ...", "status": "healthy", "recent_anomalies": []},
                {"feed_id": "01HQ...", "status": "degraded", "recent_anomalies": [...]}
            ],
            "generated_at": "2026-03-27T12:00:00+00:00"
          }
    """
    corr = correlation_id or "no-corr"
    logger.info(
        "feed_health.request",
        correlation_id=corr,
    )

    result = repo.get_all_health(correlation_id=corr)

    logger.info(
        "feed_health.response",
        feed_count=len(result.feeds),
        correlation_id=corr,
    )

    return JSONResponse(content=_serialize_health_list(result))

"""
Feed Registry API endpoints.

Responsibilities:
- Expose GET /feeds for paginated feed listing.
- Expose GET /feeds/{feed_id} for full feed detail including version history
  and connectivity test results.
- Delegate all data access to FeedRepositoryInterface (injected).
- Return 404 when a feed_id is not found.

Does NOT:
- Contain business logic or compute derived feed state.
- Access the database directly.
- Know which repository implementation is in use (mock vs SQL).

Dependencies:
- libs.contracts.interfaces.feed_repository.FeedRepositoryInterface
- libs.contracts.feed (FeedDetailResponse, FeedListResponse)
- libs.contracts.errors.NotFoundError

Error conditions:
- GET /feeds/{feed_id} returns 404 when feed_id is not in the registry.

Example (curl):
    curl http://localhost:8000/feeds?limit=20&offset=0
    curl http://localhost:8000/feeds/01HQFEED...
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.feed_repository import FeedRepositoryInterface
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/feeds", tags=["feeds"])


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_feed_repository(db: Session = Depends(get_db)) -> FeedRepositoryInterface:
    """
    Provide the active FeedRepositoryInterface implementation.

    Always returns the DB-backed repository bound to the current request's session.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        FeedRepositoryInterface implementation (SQL-backed).
    """
    from services.api.repositories.sql_feed_repository import SqlFeedRepository

    return SqlFeedRepository(db=db)


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_feed(feed: Any) -> dict[str, Any]:
    """
    Serialize a FeedResponse to a plain dict for JSONResponse.

    Uses explicit model_dump() to bypass pydantic-core stub serialization
    issues (LL-008).  Converts created_at / updated_at datetimes to ISO strings.

    Args:
        feed: FeedResponse instance.

    Returns:
        Dict with all feed fields, datetime fields as ISO strings.
    """
    raw = feed.model_dump()
    for dt_field in ("created_at", "updated_at"):
        if dt_field in raw and hasattr(raw[dt_field], "isoformat"):
            raw[dt_field] = raw[dt_field].isoformat()
    return raw


def _serialize_version(version: Any) -> dict[str, Any]:
    """
    Serialize a FeedConfigVersion to a plain dict.

    Args:
        version: FeedConfigVersion instance.

    Returns:
        Dict with all version fields, created_at as ISO string.
    """
    raw = version.model_dump()
    if "created_at" in raw and hasattr(raw["created_at"], "isoformat"):
        raw["created_at"] = raw["created_at"].isoformat()
    return raw


def _serialize_connectivity(test: Any) -> dict[str, Any]:
    """
    Serialize a FeedConnectivityResult to a plain dict.

    Args:
        test: FeedConnectivityResult instance.

    Returns:
        Dict with all test fields, tested_at as ISO string, status as string value.
    """
    raw = test.model_dump()
    if "tested_at" in raw and hasattr(raw["tested_at"], "isoformat"):
        raw["tested_at"] = raw["tested_at"].isoformat()
    if "status" in raw and hasattr(raw["status"], "value"):
        raw["status"] = raw["status"].value
    return raw


def _serialize_feed_list(result: Any) -> dict[str, Any]:
    """
    Serialize a FeedListResponse to a JSON-safe dict.

    Args:
        result: FeedListResponse instance.

    Returns:
        Dict with feeds list, total_count, limit, offset.
    """
    return {
        "feeds": [_serialize_feed(f) for f in result.feeds],
        "total_count": result.total_count,
        "limit": result.limit,
        "offset": result.offset,
    }


def _serialize_feed_detail(detail: Any) -> dict[str, Any]:
    """
    Serialize a FeedDetailResponse to a JSON-safe dict.

    Args:
        detail: FeedDetailResponse instance.

    Returns:
        Dict with feed, version_history, and connectivity_tests keys.
    """
    return {
        "feed": _serialize_feed(detail.feed),
        "version_history": [_serialize_version(v) for v in detail.version_history],
        "connectivity_tests": [_serialize_connectivity(t) for t in detail.connectivity_tests],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_feeds(
    limit: int = Query(default=20, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    correlation_id: str | None = Query(default=None, alias="x-correlation-id"),
    repo: FeedRepositoryInterface = Depends(get_feed_repository),
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
) -> JSONResponse:
    """
    Return a paginated list of registered feeds.

    Delegates all data retrieval to the injected FeedRepositoryInterface.
    Returns explicit JSONResponse to bypass pydantic-core stub serialization
    issues (LL-008).

    Args:
        limit: Maximum number of feeds to return (1–200, default 20).
        offset: Number of feeds to skip (default 0).
        correlation_id: Optional tracing correlation ID.
        repo: Injected FeedRepositoryInterface.

    Returns:
        JSONResponse with feeds list, total_count, limit, and offset.

    Example:
        GET /feeds?limit=10&offset=0
        → {"feeds": [...], "total_count": 5, "limit": 10, "offset": 0}
    """
    corr = correlation_id or "no-corr"
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "feeds.list.request",
        limit=limit,
        offset=offset,
        correlation_id=corr_id,
        component="feeds",
    )

    # LL-007: pydantic-core cross-arch stub does not coerce query-param strings to int;
    # explicit cast guards against '1' arriving as str instead of 1.
    result = repo.list(limit=int(limit), offset=int(offset), correlation_id=corr)

    logger.info(
        "feeds.list.response",
        total_count=result.total_count,
        returned=len(result.feeds),
        correlation_id=corr_id,
        component="feeds",
    )

    return JSONResponse(content=_serialize_feed_list(result))


@router.get("/{feed_id}")
def get_feed_detail(
    feed_id: str,
    correlation_id: str | None = Query(default=None, alias="x-correlation-id"),
    repo: FeedRepositoryInterface = Depends(get_feed_repository),
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
) -> JSONResponse:
    """
    Return the full detail record for a single registered feed.

    Includes the core feed metadata, complete configuration version history,
    and recent connectivity test results.

    Args:
        feed_id: 26-character ULID of the feed.
        correlation_id: Optional tracing correlation ID.
        repo: Injected FeedRepositoryInterface.

    Returns:
        JSONResponse with feed, version_history, and connectivity_tests.

    Raises:
        HTTPException(404): If no feed with feed_id exists in the registry.

    Example:
        GET /feeds/01HQFEED...
        → {"feed": {...}, "version_history": [...], "connectivity_tests": [...]}
    """
    corr = correlation_id or "no-corr"
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "feeds.detail.request",
        feed_id=feed_id,
        correlation_id=corr_id,
        component="feeds",
    )

    try:
        detail = repo.find_by_id(feed_id=feed_id, correlation_id=corr)
    except NotFoundError:
        logger.warning(
            "feeds.detail.not_found",
            feed_id=feed_id,
            correlation_id=corr_id,
            component="feeds",
        )
        raise HTTPException(
            status_code=404,
            detail=f"Feed {feed_id!r} not found",
        )

    logger.info(
        "feeds.detail.response",
        feed_id=feed_id,
        version_count=len(detail.version_history),
        connectivity_count=len(detail.connectivity_tests),
        correlation_id=corr_id,
        component="feeds",
    )

    return JSONResponse(content=_serialize_feed_detail(detail))

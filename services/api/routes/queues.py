"""
Queue API routes (Phase 3 — M7: Chart + LTTB + Queue Backend APIs).

Purpose:
    Expose queue depth and contention data for the Results Explorer and
    operator dashboard frontend (M27).

Responsibilities:
    - GET /queues/                         → QueueListResponse (all queue snapshots)
    - GET /queues/{queue_class}/contention → QueueContentionResponse (per-class)
    - Translate NotFoundError from the repository to HTTP 404.

Does NOT:
    - Cache queue data.
    - Connect to Redis or Celery directly (delegates to QueueRepositoryInterface).
    - Contain scheduling or dispatch logic.

Dependencies:
    - QueueRepositoryInterface (injected via Depends): provides queue state.
    - libs.contracts.queue: response schemas.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - NotFoundError from repository → HTTP 404 with detail message.

Example:
    GET /queues/
    → {"queues": [...], "generated_at": "2026-03-27T..."}

    GET /queues/research/contention
    → {
        "queue_class": "research",
        "depth": 3,
        "running": 1,
        "failed": 0,
        "contention_score": 15.0,
        "generated_at": "2026-03-27T..."
      }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.queue_repository import QueueRepositoryInterface
from libs.contracts.queue import QueueContentionResponse, QueueSnapshotResponse

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_queue_repository() -> QueueRepositoryInterface:
    """
    Provide a QueueRepositoryInterface implementation.

    Returns:
        MockQueueRepository bootstrap stub until Celery/Redis wiring is complete.

    Note:
        ISS-017 — Wire CeleryQueueRepository via lifespan DI container.
    """
    import os

    if os.environ.get("ENVIRONMENT", "test") != "test":
        from services.api.repositories.celery_queue_repository import CeleryQueueRepository

        return CeleryQueueRepository()

    from libs.contracts.mocks.mock_queue_repository import MockQueueRepository  # pragma: no cover
    return MockQueueRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_snapshot(snap: QueueSnapshotResponse) -> dict[str, Any]:
    """
    Serialize one QueueSnapshotResponse to a JSON-safe dict.

    Args:
        snap: QueueSnapshotResponse with datetime fields.

    Returns:
        Dict with all datetime fields as ISO strings.

    Example:
        d = _serialize_snapshot(snap)
        assert isinstance(d["timestamp"], str)
    """
    raw = snap.model_dump()
    for field in ("timestamp", "created_at"):
        val = raw.get(field)
        if val is not None and hasattr(val, "isoformat"):
            raw[field] = val.isoformat()
    return raw


def _serialize_contention(resp: QueueContentionResponse) -> dict[str, Any]:
    """
    Serialize one QueueContentionResponse to a JSON-safe dict.

    Args:
        resp: QueueContentionResponse with generated_at datetime.

    Returns:
        Dict with generated_at as ISO string.

    Example:
        d = _serialize_contention(resp)
        assert isinstance(d["generated_at"], str)
    """
    raw = resp.model_dump()
    val = raw.get("generated_at")
    if val is not None and hasattr(val, "isoformat"):
        raw["generated_at"] = val.isoformat()
    return raw


def _serialize_queue_list(
    snapshots: list[QueueSnapshotResponse],
    generated_at: datetime,
) -> dict[str, Any]:
    """
    Serialize a list of queue snapshots to a JSON-safe QueueListResponse shape.

    Args:
        snapshots:    Queue snapshot list from the repository.
        generated_at: Response generation timestamp.

    Returns:
        Dict with 'queues' list and 'generated_at' ISO string.

    Example:
        d = _serialize_queue_list(snaps, datetime.now(timezone.utc))
        assert "queues" in d and "generated_at" in d
    """
    return {
        "queues": [_serialize_snapshot(s) for s in snapshots],
        "generated_at": (
            generated_at.isoformat()
            if hasattr(generated_at, "isoformat")
            else str(generated_at)
        ),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/")
def list_queues(
    x_correlation_id: str = "no-corr",
    repo: QueueRepositoryInterface = Depends(get_queue_repository),
) -> JSONResponse:
    """
    Return all registered queue snapshots.

    Args:
        x_correlation_id: Request correlation ID.
        repo:             Injected queue repository.

    Returns:
        JSONResponse containing QueueListResponse shape with 'queues' and 'generated_at'.

    Example:
        GET /queues/
        → {"queues": [...], "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("queues.list.request", correlation_id=corr)
    snapshots = repo.list(correlation_id=corr)
    generated_at = datetime.now(timezone.utc)
    logger.info(
        "queues.list.response",
        queue_count=len(snapshots),
        correlation_id=corr,
    )
    return JSONResponse(content=_serialize_queue_list(snapshots, generated_at))


@router.get("/{queue_class}/contention")
def get_queue_contention(
    queue_class: str,
    x_correlation_id: str = "no-corr",
    repo: QueueRepositoryInterface = Depends(get_queue_repository),
) -> JSONResponse:
    """
    Return the contention snapshot for a specific queue class.

    Args:
        queue_class:      Queue class name (e.g. 'research', 'optimize').
        x_correlation_id: Request correlation ID.
        repo:             Injected queue repository.

    Returns:
        JSONResponse containing QueueContentionResponse fields.

    Raises:
        HTTPException(404): If no contention data exists for queue_class.

    Example:
        GET /queues/research/contention
        → {"queue_class": "research", "depth": 3, "running": 1, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("queues.contention.request", queue_class=queue_class, correlation_id=corr)
    try:
        contention = repo.find_by_class(queue_class, correlation_id=corr)
    except NotFoundError as exc:
        logger.warning(
            "queues.contention.not_found",
            queue_class=queue_class,
            detail=str(exc),
            correlation_id=corr,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "queues.contention.response",
        queue_class=queue_class,
        depth=contention.depth,
        contention_score=contention.contention_score,
        correlation_id=corr,
    )
    return JSONResponse(content=_serialize_contention(contention))
